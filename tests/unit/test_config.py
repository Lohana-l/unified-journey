"""Tests unitaires pour ingestion.config : détection des credentials et chargement des variables d'env."""

from __future__ import annotations

import pytest

from ingestion.config import MinioConfig, PipelineConfig, SourceCredentials, load_config


def test_minio_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINIO_ENDPOINT_LOCAL", "http://minio:9000")
    monkeypatch.setenv("MINIO_ROOT_USER", "k")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "s")
    monkeypatch.setenv("MINIO_BUCKET_BRONZE", "bronze")

    cfg = MinioConfig()
    assert cfg.endpoint_url == "http://minio:9000"
    assert cfg.access_key == "k"
    assert cfg.bucket_bronze == "bronze"


def test_minio_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("MINIO_ENDPOINT_LOCAL", "MINIO_BUCKET_BRONZE"):
        monkeypatch.delenv(k, raising=False)

    cfg = MinioConfig()
    assert cfg.endpoint_url == "http://localhost:9000"
    assert cfg.bucket_bronze == "tessera-bronze"


def test_ga4_not_configured_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # Aucun credential GA4, non configuré ; bascule sur le synthétique.
    for k in ("GA4_PROPERTY_ID", "GA4_CREDENTIALS_FILE"):
        monkeypatch.delenv(k, raising=False)

    assert SourceCredentials().ga4_configured() is False


def test_ga4_requires_both_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # property_id seul ne suffit pas : il faut aussi le fichier de credentials.
    monkeypatch.setenv("GA4_PROPERTY_ID", "123456789")
    monkeypatch.delenv("GA4_CREDENTIALS_FILE", raising=False)

    assert SourceCredentials().ga4_configured() is False


def test_meta_configured_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("META_ACCESS_TOKEN", "t")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "act_123")

    assert SourceCredentials().meta_configured() is True


def test_pipeline_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("PIPELINE_LOOKBACK_DAYS", "PIPELINE_SEED"):
        monkeypatch.delenv(k, raising=False)

    cfg = PipelineConfig()
    assert cfg.lookback_days == 90
    assert cfg.seed == 42


def test_load_config_returns_three_blocks() -> None:
    minio, creds, pipeline = load_config()
    assert isinstance(minio, MinioConfig)
    assert isinstance(creds, SourceCredentials)
    assert isinstance(pipeline, PipelineConfig)
