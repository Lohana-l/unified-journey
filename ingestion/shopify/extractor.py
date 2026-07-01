"""Extracteur Shopify Admin API.

Référence : https://shopify.dev/docs/api/admin-rest/2024-10
Récupère /customers et /orders avec pagination. Rate limit : 2 req/sec en leaky
bucket, géré par tenacity + sleep explicite.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd
import requests
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ingestion.config import load_config
from ingestion.utils.parquet_writer import write_partitioned
from ingestion.utils.s3 import get_fs


def _base_url(domain: str) -> str:
    return f"https://{domain}/admin/api/2024-10"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    retry=retry_if_exception_type((requests.HTTPError, requests.ConnectionError)),
)
def _paginate(url: str, headers: dict, params: dict) -> list[dict]:
    results: list[dict] = []
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        page = r.json()
        key = next(iter(page.keys()))
        results.extend(page[key])
        # Pagination Shopify par curseur via le header Link
        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            parts = [p.strip() for p in link.split(",") if 'rel="next"' in p]
            if parts:
                url = parts[0].split(";")[0].strip("<> ")
                params = {}  # l'URL suivante embarque son propre page_info
        time.sleep(0.5)  # respect du rate limit leaky-bucket
    return results


def run() -> None:
    minio, creds, pipeline = load_config()

    if not creds.shopify_configured():
        raise RuntimeError(
            "SHOPIFY_STORE_DOMAIN and SHOPIFY_ACCESS_TOKEN must be set. "
            "Use `python -m ingestion.main --all` for the synthetic fallback."
        )

    headers = {"X-Shopify-Access-Token": creds.shopify_access_token}
    base = _base_url(creds.shopify_store_domain)
    end = date.today()
    start = end - timedelta(days=pipeline.lookback_days)

    logger.info(f"Shopify real-API mode: store={creds.shopify_store_domain} range=[{start}, {end}]")

    customers = _paginate(
        f"{base}/customers.json",
        headers,
        params={"updated_at_min": start.isoformat(), "limit": 250},
    )
    orders = _paginate(
        f"{base}/orders.json",
        headers,
        params={"created_at_min": start.isoformat(), "status": "any", "limit": 250},
    )

    fs = get_fs(minio)
    write_partitioned(
        pd.DataFrame(customers),
        source="shopify",
        table="customers",
        partition_date=end,
        config=minio,
        fs=fs,
    )
    write_partitioned(
        pd.DataFrame(orders),
        source="shopify",
        table="orders",
        partition_date=end,
        config=minio,
        fs=fs,
    )
