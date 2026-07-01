"""Écriture Parquet partitionnée vers le bucket bronze.

Convention :
    s3://<bucket>/<source>/<table>/dt=YYYY-MM-DD/part-0000.parquet

Pourquoi partitionné : chargements incrémentaux sans réécrire l'historique,
et la couche aval bénéficie d'un layout de partition prévisible.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import s3fs
from loguru import logger

from ingestion.config import MinioConfig
from ingestion.utils.s3 import ensure_bucket


def write_partitioned(
    df: pd.DataFrame,
    *,
    source: str,
    table: str,
    partition_date: date | datetime | None = None,
    config: MinioConfig,
    fs: s3fs.S3FileSystem | None = None,
) -> str:
    """Écrit un DataFrame en bronze sous forme d'un unique fichier Parquet part.

    Retourne l'URI S3 du fichier écrit.
    """
    if df.empty:
        logger.warning(f"[{source}/{table}] empty DataFrame, skipping write")
        return ""

    if fs is None:
        from ingestion.utils.s3 import get_fs

        fs = get_fs(config)

    ensure_bucket(fs, config.bucket_bronze)

    dt = partition_date or date.today()
    if isinstance(dt, datetime):
        dt = dt.date()

    path = f"{config.bucket_bronze}/{source}/{table}/" f"dt={dt.isoformat()}/part-0000.parquet"
    table_arrow = pa.Table.from_pandas(df, preserve_index=False)

    with fs.open(path, "wb") as fh:
        pq.write_table(table_arrow, fh, compression="snappy")

    logger.success(f"[{source}/{table}] wrote {len(df):,} rows to s3://{path}")
    return f"s3://{path}"
