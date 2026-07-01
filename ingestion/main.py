"""Point d'entrée CLI de l'ingestion.

Deux modes :

  python -m ingestion.main --all
      Si les 4 sources ont des credentials API réels configurés, lance chaque extracteur.
      Sinon, exécute le générateur synthétique (aucun credential externe requis).

  python -m ingestion.main --source ga4
      Lance un seul extracteur API réel. Échoue bruyamment si les credentials manquent.

Appelé par : `make ingest`, Kestra `ingest_all.yaml`.
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger

from ingestion.config import load_config
from ingestion.observability import configure_logger, pipeline_run

# Installe le sink configuré (pretty en dev, JSON en prod) avant qu'une
# quelconque ligne de log soit émise par les modules importés ci-dessous.
configure_logger()

SOURCES = ("ga4", "meta", "shopify", "email")


def _run_source(source: str) -> None:
    if source == "ga4":
        from ingestion.ga4.extractor import run as run_ga4

        run_ga4()
    elif source == "meta":
        from ingestion.meta.extractor import run as run_meta

        run_meta()
    elif source == "shopify":
        from ingestion.shopify.extractor import run as run_shop

        run_shop()
    elif source == "email":
        from ingestion.email.extractor import run as run_email

        run_email()
    else:
        raise ValueError(f"Unknown source: {source}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Tessera CDP ingestion CLI.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--source", action="append", choices=SOURCES)
    args = parser.parse_args()

    minio, creds, _ = load_config()
    logger.info(f"MinIO: {minio.endpoint_url}  bronze bucket: {minio.bucket_bronze}")

    any_real = creds.ga4_configured() or creds.meta_configured() or creds.shopify_configured()

    if args.all and not any_real:
        logger.info("No real API credentials detected, running synthetic generator (one-shot).")
        from ingestion.observability import record_run
        from seed.generate_sample_data import generate_and_write

        generate_and_write()
        # Enregistre un run d'audit par source pour que le dashboard reflète
        # l'exécution. Sans cela, audit_pipeline_runs reste vide en mode
        # synthétique et l'état du pipeline (santé / logs / Gantt) s'affiche vide.
        # On utilise les clés attendues par le dashboard (email = mailchimp).
        _audit_name = {"email": "mailchimp"}
        for src in SOURCES:
            record_run(
                pipeline=_audit_name.get(src, src),
                step="bronze",
                status="success",
                mode="synthetic",
            )
        logger.success("Ingestion complete via synthetic generator.")
        return 0

    targets = SOURCES if args.all else tuple(args.source)
    for src in targets:
        logger.info(f"─── Running source: {src} ───")
        try:
            with pipeline_run("ingest", src, source=src):
                _run_source(src)
        except Exception as exc:
            # `pipeline_run` a déjà enregistré la ligne d'échec ; on remonte et on sort.
            logger.exception(f"[{src}] failed: {exc}")
            return 2

    logger.success(f"Ingestion complete for: {', '.join(targets)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
