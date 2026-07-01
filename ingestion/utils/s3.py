"""Helpers légers autour de s3fs pour MinIO. Passage en prod : même API, vrais credentials AWS."""

from __future__ import annotations

import s3fs
from loguru import logger

from ingestion.config import MinioConfig


def get_fs(config: MinioConfig) -> s3fs.S3FileSystem:
    """Retourne un handle s3fs configuré pour MinIO.

    Sur AWS, passer credentials=None et supprimer endpoint_url donne du S3 natif.
    """
    return s3fs.S3FileSystem(
        key=config.access_key,
        secret=config.secret_key,
        client_kwargs={"endpoint_url": config.endpoint_url, "region_name": config.region},
        use_listings_cache=False,
    )


def ensure_bucket(fs: s3fs.S3FileSystem, bucket: str) -> None:
    """Crée le bucket s'il n'existe pas. Sans effet s'il est déjà présent."""
    try:
        if not fs.exists(bucket):
            fs.mkdir(bucket)
            logger.info(f"Created bucket: {bucket}")
    except FileExistsError:
        pass
