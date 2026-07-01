"""Génère un dataset marketing multi-sources réaliste avec chevauchement d'identité délibéré.

Le générateur modélise une population implicite de "ground truth" de `N_PEOPLE` humains,
chacun avec 1-3 appareils et un statut de consentement varié. À partir de cette vérité terrain,
il projette quatre vues partielles (GA4, Meta Pixel, Shopify, Email), chacune avec son
propre schéma d'identifiants. Le graphe d'identité dans dbt doit redécouvrir qui est qui
à partir des colonnes de liaison (hash email, user_id connecté, Pixel fbp).

Usage :
    python -m seed.generate_sample_data
    python -m seed.generate_sample_data --n-people 5000 --days 60

Notes de conception :
- Le mix de canaux est orienté pour que le first-touch soit dominé par les canaux
  de découverte (paid_social, display) et le last-touch par les canaux de closing
  (email, direct), ce qui rend la page de comparaison d'attribution visuellement intéressante.
- ~35% des convertisseurs n'ont PAS d'email au premier contact (ils convertissent
  anonymement puis s'identifient au checkout), ce qui exercice le code path "back-attribution".
- ~20% des utilisateurs utilisent deux appareils, ce qui exercice le stitching cross-device.
- Répartition du consentement : 70% accordé, 20% anonyme, 10% retiré.
"""

from __future__ import annotations

import argparse
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker
from loguru import logger

from ingestion.config import load_config
from ingestion.utils.parquet_writer import write_partitioned
from ingestion.utils.s3 import get_fs

# ---------------- Constantes paramétrables ----------------
CHANNELS = [
    ("paid_social", "meta", "cpc", 0.22, 1.0),
    ("paid_social_tt", "tiktok", "cpc", 0.08, 0.7),
    ("paid_search", "google", "cpc", 0.18, 1.4),
    ("organic_search", "google", "organic", 0.15, 1.2),
    ("email", "mailchimp", "email", 0.12, 2.8),
    ("direct", "direct", "none", 0.10, 2.0),
    ("display", "google", "display", 0.08, 0.5),
    ("referral", "partner", "referral", 0.04, 1.3),
    ("social_organic", "instagram", "social", 0.03, 0.8),
]
# poids                                           ^^^^  ^^^^ multiplicateur de conversion

FUNNEL_EVENTS = ["page_view", "view_item", "add_to_cart", "begin_checkout", "purchase"]
FUNNEL_DROPOFF = [1.0, 0.60, 0.38, 0.28, 0.82]  # taux À chaque étape sachant l'étape précédente

PRODUCTS = [
    ("SKU-SNK-001", "Urban Runner", "Sneakers", 89.00),
    ("SKU-SNK-002", "Trail Pro", "Sneakers", 129.00),
    ("SKU-JKT-003", "Wind Shell", "Jackets", 189.00),
    ("SKU-JKT-004", "Alpine Down", "Jackets", 349.00),
    ("SKU-ACC-005", "Merino Beanie", "Accessories", 29.00),
    ("SKU-ACC-006", "Wool Gloves", "Accessories", 39.00),
    ("SKU-BAG-007", "Day Pack 20L", "Bags", 79.00),
    ("SKU-BAG-008", "Travel Duffel", "Bags", 149.00),
]

COUNTRIES = ["FR", "FR", "FR", "FR", "BE", "CH", "DE", "ES", "IT", "NL"]  # biais vers la France
DEVICES = [("mobile", 0.55), ("desktop", 0.35), ("tablet", 0.10)]
CONSENT = [("granted", 0.70), ("anonymous", 0.20), ("withdrawn", 0.10)]


# ---------------- Fonctions utilitaires ----------------
def _sha256(s: str) -> str:
    return hashlib.sha256(s.lower().strip().encode()).hexdigest()


def _weighted_choice(rng: np.random.Generator, items: list[tuple], n: int) -> np.ndarray:
    values = [it[0] for it in items]
    weights = np.array([it[1] for it in items], dtype=float)
    return rng.choice(values, size=n, p=weights / weights.sum())


@dataclass
class Person:
    """Humain de ground truth, jamais persisté, pilote les projections."""

    person_id: str  # UUID interne, jamais exposé à aucune source
    email: str
    email_hash: str
    country: str
    consent: str
    n_devices: int
    device_ids: list[str]
    shopify_customer_id: int | None
    subscriber_id: str | None
    is_converter: bool


def _build_population(rng: np.random.Generator, fake: Faker, n_people: int) -> list[Person]:
    """Crée la population de ground truth."""
    people: list[Person] = []
    for i in range(n_people):
        email = fake.unique.email()
        n_devices = int(rng.choice([1, 2, 3], p=[0.75, 0.20, 0.05]))
        consent = str(rng.choice([c[0] for c in CONSENT], p=[c[1] for c in CONSENT]))
        is_converter = bool(rng.random() < 0.08)  # 8% des visiteurs convertissent
        country = str(rng.choice(COUNTRIES))
        people.append(
            Person(
                person_id=str(uuid.uuid4()),
                email=email,
                email_hash=_sha256(email),
                country=country,
                consent=consent,
                n_devices=n_devices,
                device_ids=[
                    f"GA1.2.{rng.integers(10**8, 10**10)}.{rng.integers(10**9, 10**10)}"
                    for _ in range(n_devices)
                ],
                shopify_customer_id=(100_000 + i) if is_converter else None,
                subscriber_id=f"sub_{uuid.uuid4().hex[:12]}" if rng.random() < 0.55 else None,
                is_converter=is_converter,
            )
        )
    return people


# ---------------- Projections par source ----------------
def _generate_ga4(rng, people, start, end):
    rows = []
    days = (end - start).days
    for p in people:
        n_sessions = max(1, int(rng.poisson(3.5 if p.is_converter else 1.8)))
        for _ in range(n_sessions):
            device_id = str(rng.choice(p.device_ids))
            sess_ts = start + timedelta(
                days=int(rng.integers(0, days)),
                seconds=int(rng.integers(0, 86400)),
            )
            channel = str(
                rng.choice(
                    [c[0] for c in CHANNELS],
                    p=[c[3] for c in CHANNELS],
                )
            )
            session_id = f"{device_id}.{int(sess_ts.timestamp())}"
            reached = 0
            for i, _ev in enumerate(FUNNEL_EVENTS):
                if i == 0 or rng.random() < FUNNEL_DROPOFF[i] * (1.3 if p.is_converter else 0.7):
                    reached = i
                else:
                    break
            for i in range(reached + 1):
                sku = str(rng.choice([p[0] for p in PRODUCTS])) if i >= 1 else None
                rows.append(
                    {
                        "event_id": str(uuid.uuid4()),
                        "event_name": FUNNEL_EVENTS[i],
                        "event_ts": sess_ts + timedelta(seconds=int(rng.integers(0, 1200))),
                        "ga_client_id": device_id,
                        "ga_user_id": str(p.shopify_customer_id)
                        if p.is_converter and p.consent == "granted" and i == 4
                        else None,  # noqa: E501
                        "ga_session_id": session_id,
                        "page_location": f"/catalog/{sku}" if sku else "/home",
                        "page_title": sku or "Home",
                        "device_category": str(
                            rng.choice([d[0] for d in DEVICES], p=[d[1] for d in DEVICES])
                        ),  # noqa: E501
                        "country": p.country,
                        "source": next(c[1] for c in CHANNELS if c[0] == channel),
                        "medium": next(c[2] for c in CHANNELS if c[0] == channel),
                        "campaign": f"cpg_{channel}_{sess_ts.strftime('%Y%m')}",
                        "item_id": sku,
                        "value_eur": next(p[3] for p in PRODUCTS if p[0] == sku) if sku else None,
                        "consent_status": p.consent,
                    }
                )
    return pd.DataFrame(rows)


def _generate_meta_pixel(rng, people, start, end):
    rows = []
    days = (end - start).days
    for p in people:
        # La visibilité Meta est biaisée vers les personnes ayant vu du paid_social
        n_pixel = int(rng.poisson(2.2 if p.is_converter else 0.9))
        for _ in range(n_pixel):
            ev_ts = start + timedelta(
                days=int(rng.integers(0, days)), seconds=int(rng.integers(0, 86400))
            )
            event_name = str(
                rng.choice(
                    ["PageView", "ViewContent", "AddToCart", "InitiateCheckout", "Purchase"],
                    p=[0.45, 0.25, 0.15, 0.10, 0.05],
                )
            )
            rows.append(
                {
                    "event_id": str(uuid.uuid4()),
                    "event_name": event_name,
                    "event_time": int(ev_ts.timestamp()),
                    "fbp": f"fb.1.{rng.integers(10**12, 10**13)}.{rng.integers(10**9, 10**10)}",
                    "fbc": f"fb.1.{rng.integers(10**12, 10**13)}.{rng.integers(10**9, 10**10)}"
                    if rng.random() < 0.3
                    else None,  # noqa: E501
                    "em_hash": p.email_hash
                    if (p.consent == "granted" and rng.random() < 0.6)
                    else None,
                    "ph_hash": None,
                    "client_ip_prefix": f"{rng.integers(1, 255)}.{rng.integers(1, 255)}.{rng.integers(1, 255)}.0",  # noqa: E501
                    "client_user_agent": "Mozilla/5.0 (synthetic)",
                    "action_source": "website",
                    "currency": "EUR",
                    "value": float(rng.uniform(29, 349)) if event_name == "Purchase" else None,
                    "content_ids": [str(rng.choice([p[0] for p in PRODUCTS]))],
                    "consent_status": p.consent,
                }
            )
    return pd.DataFrame(rows)


def _generate_shopify_customers(people):
    rows = []
    for p in people:
        if not p.is_converter:
            continue
        first, *rest = p.email.split("@")[0].split(".") + [""]
        rows.append(
            {
                "customer_id": p.shopify_customer_id,
                "email": p.email,
                "first_name": first.title(),
                "last_name": (rest[0].title() if rest and rest[0] else "Unknown"),
                "accepts_marketing": p.consent == "granted",
                "accepts_marketing_updated_at": datetime.utcnow().isoformat(),
                "country": p.country,
                "orders_count": None,  # complété par la jointure avec les commandes
                "total_spent": None,
                "created_at": (
                    datetime.utcnow() - timedelta(days=int(np.random.randint(10, 720)))
                ).isoformat(),  # noqa: E501
                "consent_status": p.consent,
            }
        )
    return pd.DataFrame(rows)


def _generate_shopify_orders(rng, people, start, end):
    rows = []
    items_rows = []
    days = (end - start).days
    for p in people:
        if not p.is_converter:
            continue
        n_orders = int(rng.poisson(1.6))
        for _ in range(max(1, n_orders)):
            ts = start + timedelta(
                days=int(rng.integers(0, days)), seconds=int(rng.integers(0, 86400))
            )
            order_id = f"ord_{uuid.uuid4().hex[:10]}"
            n_items = int(rng.integers(1, 4))
            total = 0.0
            for _ in range(n_items):
                product = list(PRODUCTS)[int(rng.integers(0, len(PRODUCTS)))]
                qty = int(rng.integers(1, 3))
                total += product[3] * qty
                items_rows.append(
                    {
                        "order_id": order_id,
                        "sku": product[0],
                        "title": product[1],
                        "product_type": product[2],
                        "quantity": qty,
                        "price_eur": product[3],
                    }
                )
            rows.append(
                {
                    "order_id": order_id,
                    "customer_id": p.shopify_customer_id,
                    "email": p.email,
                    "created_at": ts.isoformat(),
                    "total_price_eur": round(total, 2),
                    "currency": "EUR",
                    "financial_status": "paid",
                    "fulfillment_status": "fulfilled",
                    "country": p.country,
                    "consent_status": p.consent,
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(items_rows)


def _generate_email_events(rng, people, start, end):
    rows = []
    days = (end - start).days
    campaigns = [f"cmp_{i:03d}" for i in range(12)]
    for p in people:
        if not p.subscriber_id:
            continue
        for cmp_id in rng.choice(campaigns, size=int(rng.integers(1, 6)), replace=False):
            send_ts = start + timedelta(
                days=int(rng.integers(0, days)), seconds=int(rng.integers(0, 86400))
            )
            rows.append(
                {
                    "event_id": str(uuid.uuid4()),
                    "event_name": "campaign.sent",
                    "event_ts": send_ts.isoformat(),
                    "campaign_id": str(cmp_id),
                    "subscriber_id": p.subscriber_id,
                    "email_hash": p.email_hash,
                    "url": None,
                    "consent_status": p.consent,
                }
            )
            if rng.random() < 0.28:  # ouverture
                rows.append(
                    {
                        "event_id": str(uuid.uuid4()),
                        "event_name": "campaign.opened",
                        "event_ts": (
                            send_ts + timedelta(hours=int(rng.integers(1, 48)))
                        ).isoformat(),
                        "campaign_id": str(cmp_id),
                        "subscriber_id": p.subscriber_id,
                        "email_hash": p.email_hash,
                        "url": None,
                        "consent_status": p.consent,
                    }
                )
                if rng.random() < 0.45:  # clic
                    rows.append(
                        {
                            "event_id": str(uuid.uuid4()),
                            "event_name": "campaign.clicked",
                            "event_ts": (
                                send_ts + timedelta(hours=int(rng.integers(1, 72)))
                            ).isoformat(),  # noqa: E501
                            "campaign_id": str(cmp_id),
                            "subscriber_id": p.subscriber_id,
                            "email_hash": p.email_hash,
                            "url": f"https://shop.example.com/promo/{cmp_id}",
                            "consent_status": p.consent,
                        }
                    )
    return pd.DataFrame(rows)


# ---------------- Orchestrateur ----------------
def generate_and_write(n_people: int = 2000, days: int = 90, write_to_minio: bool = True):
    """Niveau supérieur : construit la population, projette les 5 tables, écrit en bronze."""
    minio, _, pipeline = load_config()
    rng = np.random.default_rng(pipeline.seed)
    fake = Faker("fr_FR")
    fake.seed_instance(pipeline.seed)

    end = datetime.utcnow().replace(microsecond=0)
    start = end - timedelta(days=days)

    logger.info(f"Generating population of {n_people:,} people over {days} days …")
    people = _build_population(rng, fake, n_people)

    ga4 = _generate_ga4(rng, people, start, end)
    meta = _generate_meta_pixel(rng, people, start, end)
    shop_c = _generate_shopify_customers(people)
    shop_o, shop_li = _generate_shopify_orders(rng, people, start, end)
    email = _generate_email_events(rng, people, start, end)

    logger.info(
        f"Generated: GA4={len(ga4):,} | Meta={len(meta):,} | Shopify cust={len(shop_c):,} "
        f"| orders={len(shop_o):,} | items={len(shop_li):,} | Email={len(email):,}"
    )

    if not write_to_minio:
        return {
            "ga4": ga4,
            "meta": meta,
            "shopify_customers": shop_c,
            "shopify_orders": shop_o,
            "shopify_line_items": shop_li,
            "email": email,
        }

    fs = get_fs(minio)
    today = end.date()
    for source, table, df in [
        ("ga4", "events", ga4),
        ("meta", "pixel_events", meta),
        ("shopify", "customers", shop_c),
        ("shopify", "orders", shop_o),
        ("shopify", "line_items", shop_li),
        ("email", "events", email),
    ]:
        write_partitioned(df, source=source, table=table, partition_date=today, config=minio, fs=fs)

    return {"ok": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic Tessera CDP data.")
    parser.add_argument("--n-people", type=int, default=2000)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument(
        "--no-write", action="store_true", help="Dry-run: generate but do not upload to MinIO."
    )
    args = parser.parse_args()

    try:
        generate_and_write(n_people=args.n_people, days=args.days, write_to_minio=not args.no_write)
    except Exception as e:
        logger.exception(f"Generation failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
