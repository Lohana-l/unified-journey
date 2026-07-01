"""CLI de droit à l'oubli (RGPD).

À partir d'un email brut, résout le unified_user_id via dim_users puis supprime
ses lignes des marts du warehouse (dim_users + tables de faits). Écrit une ligne
tombstone dans `forgotten_users` (sans PII) à des fins d'audit. Le bronze brut est
conservé pour l'audit et purgé séparément par la rétention (expiration de partitions).

Usage :
    python -m ingestion.gdpr.forget --email user@example.com
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime

import duckdb
from loguru import logger

from ingestion.config import load_config


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()


def forget_user(email: str, duckdb_path: str = "warehouse/tessera.duckdb") -> None:
    email_h = _email_hash(email)
    logger.info(f"Computing footprint for email_hash={email_h[:12]}…")
    conn = duckdb.connect(duckdb_path)
    try:
        # 1. Résolution du unified_user_id via dim_users.
        row = conn.execute(
            "SELECT unified_user_id FROM marts.dim_users WHERE email_hash = ? LIMIT 1",
            [email_h],
        ).fetchone()
        if row is None:
            logger.warning("No matching user found in dim_users. Nothing to forget.")
            return
        uid = row[0]
        logger.info(f"Resolved unified_user_id = {uid}")

        # 2. Suppression dans les tables de faits.
        for fact in ("fct_touchpoints", "fct_sessions", "fct_conversions", "fct_funnel_steps"):
            deleted = conn.execute(
                f"DELETE FROM marts.{fact} WHERE unified_user_id = ? RETURNING 1",
                [uid],
            ).fetchall()
            logger.info(f"{fact}: {len(deleted)} rows deleted")

        # 3. Suppression dans dim_users (toutes les lignes SCD pour cet uid).
        conn.execute("DELETE FROM marts.dim_users WHERE unified_user_id = ?", [uid])

        # 4. Enregistrement du tombstone.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS marts.forgotten_users (
                unified_user_id VARCHAR,
                email_hash VARCHAR,
                forgotten_at TIMESTAMP,
                request_id VARCHAR
            )
            """
        )
        conn.execute(
            "INSERT INTO marts.forgotten_users VALUES (?, ?, ?, ?)",
            [uid, email_h, datetime.utcnow(), f"req_{uid[:8]}"],
        )
        logger.success(f"Tombstone recorded. Forget operation complete for {uid}")
    finally:
        conn.close()


def main() -> int:
    minio, _, _ = load_config()  # noqa: F841 conservé pour montrer le chemin de config
    parser = argparse.ArgumentParser(description="GDPR right-to-be-forgotten.")
    parser.add_argument("--email", required=True, help="Email address of the data subject.")
    parser.add_argument("--duckdb-path", default="warehouse/tessera.duckdb")
    args = parser.parse_args()

    try:
        forget_user(args.email, args.duckdb_path)
    except Exception as exc:
        logger.exception(f"Forget failed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
