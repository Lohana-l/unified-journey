"""Extracteur Meta Graph API (Marketing Insights + Conversion API).

Mode réel : récupère les insights au niveau annonce (portée, impressions, clics, dépenses)
depuis /act_{id}/insights et les événements Pixel depuis /{pixel_id}/events.
Référence : https://developers.facebook.com/docs/marketing-api/conversions-api/
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from ingestion.config import load_config
from ingestion.utils.parquet_writer import write_partitioned
from ingestion.utils.s3 import get_fs

GRAPH_API = "https://graph.facebook.com/v21.0"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
def _fetch_insights(
    ad_account_id: str, access_token: str, since: date, until: date
) -> pd.DataFrame:
    url = f"{GRAPH_API}/act_{ad_account_id}/insights"
    params = {
        "access_token": access_token,
        "level": "ad",
        "fields": "ad_id,ad_name,campaign_id,campaign_name,adset_id,adset_name,"
        "impressions,reach,clicks,spend,ctr,cpc,actions",
        "time_range": f'{{"since":"{since}","until":"{until}"}}',
        "limit": 1000,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()
    return pd.json_normalize(payload.get("data", []))


def run() -> None:
    minio, creds, pipeline = load_config()

    if not creds.meta_configured():
        raise RuntimeError(
            "META_ACCESS_TOKEN and META_AD_ACCOUNT_ID must be set to use the real "
            "Meta extractor. Run `python -m ingestion.main --all` for the synthetic "
            "fallback instead."
        )

    end = date.today()
    start = end - timedelta(days=pipeline.lookback_days)
    logger.info(f"Meta real-API mode: account={creds.meta_ad_account_id} range=[{start}, {end}]")
    df = _fetch_insights(creds.meta_ad_account_id, creds.meta_access_token, start, end)

    fs = get_fs(minio)
    write_partitioned(
        df, source="meta", table="ad_insights", partition_date=end, config=minio, fs=fs
    )
