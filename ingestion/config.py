"""Configuration centralisée de l'ingestion, lue depuis les variables d'environnement avec des valeurs par défaut raisonnables.

Tous les paramètres exposés par le pipeline sont ici sous forme de dataclass,
ce qui fait échouer rapidement une mauvaise configuration avec un message clair
plutôt que de planter au fond d'une écriture DataFrame.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Charge le .env depuis la racine du projet s'il existe.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env", override=False)


def _env(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key, default)
    if value in ("", None):
        return default
    return value


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    return int(raw) if raw is not None else default


@dataclass(frozen=True)
class MinioConfig:
    """Paramètres de connexion au store objet compatible S3."""

    endpoint_url: str = field(
        default_factory=lambda: _env("MINIO_ENDPOINT_LOCAL", "http://localhost:9000")
    )  # noqa: E501
    access_key: str = field(default_factory=lambda: _env("MINIO_ROOT_USER", "minioadmin"))
    secret_key: str = field(default_factory=lambda: _env("MINIO_ROOT_PASSWORD", "minioadmin"))
    bucket_bronze: str = field(
        default_factory=lambda: _env("MINIO_BUCKET_BRONZE", "tessera-bronze")
    )  # noqa: E501
    bucket_silver: str = field(
        default_factory=lambda: _env("MINIO_BUCKET_SILVER", "tessera-silver")
    )  # noqa: E501
    bucket_gold: str = field(default_factory=lambda: _env("MINIO_BUCKET_GOLD", "tessera-gold"))  # noqa: E501
    region: str = "us-east-1"  # MinIO accepte n'importe quelle chaîne de région


@dataclass(frozen=True)
class SourceCredentials:
    """Credentials API pour chaque source. Chaîne vide => bascule sur le générateur synthétique."""

    ga4_property_id: str = field(default_factory=lambda: _env("GA4_PROPERTY_ID", "") or "")
    ga4_credentials_file: str = field(
        default_factory=lambda: _env("GA4_CREDENTIALS_FILE", "") or ""
    )  # noqa: E501
    meta_access_token: str = field(default_factory=lambda: _env("META_ACCESS_TOKEN", "") or "")
    meta_ad_account_id: str = field(default_factory=lambda: _env("META_AD_ACCOUNT_ID", "") or "")
    shopify_store_domain: str = field(
        default_factory=lambda: _env("SHOPIFY_STORE_DOMAIN", "") or ""
    )  # noqa: E501
    shopify_access_token: str = field(
        default_factory=lambda: _env("SHOPIFY_ACCESS_TOKEN", "") or ""
    )  # noqa: E501

    def ga4_configured(self) -> bool:
        return bool(self.ga4_property_id) and bool(self.ga4_credentials_file)

    def meta_configured(self) -> bool:
        return bool(self.meta_access_token) and bool(self.meta_ad_account_id)

    def shopify_configured(self) -> bool:
        return bool(self.shopify_store_domain) and bool(self.shopify_access_token)


@dataclass(frozen=True)
class PipelineConfig:
    """Paramètres globaux du pipeline."""

    lookback_days: int = field(default_factory=lambda: _env_int("PIPELINE_LOOKBACK_DAYS", 90))
    seed: int = field(default_factory=lambda: _env_int("PIPELINE_SEED", 42))


def load_config() -> tuple[MinioConfig, SourceCredentials, PipelineConfig]:
    """Chargeur unique pratique utilisé par la CLI."""
    return MinioConfig(), SourceCredentials(), PipelineConfig()
