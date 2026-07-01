"""CLI minimal pour enregistrer un run dans `audit_pipeline_runs`.

Utilisé par le Makefile après les étapes qui tournent hors-process Python
(dbt build, Soda scan), afin que le dashboard reflète l'état réel du pipeline.

Exemple :
    python -m ingestion.record_run --pipeline dbt --step build --status success --duration-ms 4200
    # insère une ligne d'audit "dbt:build" terminée avec succès en 4,2 s
"""

from __future__ import annotations

import argparse

from ingestion.observability import configure_logger, record_run


def main() -> int:
    configure_logger()
    parser = argparse.ArgumentParser(description="Enregistre un run d'audit pipeline.")
    parser.add_argument(
        "--pipeline",
        required=True,
        help="Nom du pipeline : dbt | soda | ga4 | meta | shopify | mailchimp",
    )
    parser.add_argument("--step", required=True, help="Étape, ex. 'build' ou 'soda scan'")
    parser.add_argument(
        "--status",
        default="success",
        choices=["success", "failed", "running"],
        help="Statut final du run",
    )
    parser.add_argument(
        "--duration-ms", type=int, default=None, help="Durée du run en millisecondes (optionnel)"
    )
    parser.add_argument(
        "--rows-out", type=int, default=None, help="Nombre de lignes produites (optionnel)"
    )
    parser.add_argument("--error", default=None, help="Message d'erreur si échec")
    args = parser.parse_args()

    record_run(
        pipeline=args.pipeline,
        step=args.step,
        status=args.status,
        duration_ms=args.duration_ms,
        rows_out=args.rows_out,
        error=args.error,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
