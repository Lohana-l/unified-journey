"""Extracteur GA4.

Mode réel : appelle la GA4 Data API v1 avec un compte de service et un PROPERTY_ID.
Bascule sur la propriété de démo Google Merchandise Store si les credentials sont
absents mais qu'un PROPERTY_ID de démo est défini. Si rien n'est disponible,
lève une exception : utiliser `ingestion.main --all` pour déclencher le générateur synthétique.

Schéma de référence : https://developers.google.com/analytics/devguides/reporting/data/v1/basics
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from ingestion.config import load_config
from ingestion.utils.parquet_writer import write_partitioned
from ingestion.utils.s3 import get_fs


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
def _fetch_real_ga4(
    property_id: str, credentials_file: str, start: date, end: date
) -> pd.DataFrame:
    """Récupère les événements GA4 via la Data API. Import paresseux pour qu'un
    credentials_file manquant ne fasse pas planter la CLI à l'import."""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Metric,
        RunReportRequest,
    )

    client = BetaAnalyticsDataClient.from_service_account_file(credentials_file)
    request = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[
            Dimension(name="eventName"),
            Dimension(name="deviceCategory"),
            Dimension(name="country"),
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
            Dimension(name="sessionCampaignName"),
            Dimension(name="pagePath"),
            Dimension(name="date"),
        ],
        metrics=[
            Metric(name="eventCount"),
            Metric(name="sessions"),
            Metric(name="totalUsers"),
        ],
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        limit=100_000,
    )
    response = client.run_report(request)

    rows = []
    for row in response.rows:
        rows.append(
            {
                "event_name": row.dimension_values[0].value,
                "device_category": row.dimension_values[1].value,
                "country": row.dimension_values[2].value,
                "source": row.dimension_values[3].value,
                "medium": row.dimension_values[4].value,
                "campaign": row.dimension_values[5].value,
                "page_location": row.dimension_values[6].value,
                "event_date": row.dimension_values[7].value,
                "event_count": int(row.metric_values[0].value),
                "sessions": int(row.metric_values[1].value),
                "total_users": int(row.metric_values[2].value),
            }
        )
    return pd.DataFrame(rows)


def run() -> None:
    minio, creds, pipeline = load_config()

    if not creds.ga4_configured():
        raise RuntimeError(
            "GA4_PROPERTY_ID and GA4_CREDENTIALS_FILE must be set to use the real "
            "extractor. Run `python -m ingestion.main --all` to use the synthetic "
            "generator instead."
        )

    end = date.today()
    start = end - timedelta(days=pipeline.lookback_days)
    logger.info(f"GA4 real-API mode: property={creds.ga4_property_id} range=[{start}, {end}]")
    df = _fetch_real_ga4(creds.ga4_property_id, creds.ga4_credentials_file, start, end)

    fs = get_fs(minio)
    write_partitioned(df, source="ga4", table="events", partition_date=end, config=minio, fs=fs)
