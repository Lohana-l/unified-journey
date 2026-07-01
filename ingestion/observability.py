"""
Primitives d'observabilité pour la couche ingestion + pipeline.

Ce que ce module fournit
------------------------
1. **`configure_logger()`** installe un sink loguru qui émet soit des lignes
   colorisées lisibles (dev) soit un objet JSON par ligne (prod / CloudWatch).
   Basculement via `TESSERA_LOG_FORMAT={pretty,json}`.

2. **`pipeline_run(...)`** gestionnaire de contexte qui enregistre une ligne
   dans une table DuckDB persistante `audit_pipeline_runs` pour chaque étape
   du pipeline : start_ts, end_ts, status, rows_processed, error, environment.
   C'est l'équivalent léger, in-warehouse d'un "ops dashboard". Une simple requête
   (`SELECT * FROM audit_pipeline_runs ORDER BY start_ts DESC LIMIT 20`) donne
   l'historique des runs sans aucun service externe.

3. **`emit_metric(name, value, tags=...)`** écrit une ligne JSON de métrique
   que le filtre de métrique CloudWatch
   reconnaît et transforme en métrique CloudWatch sur AWS réel. La même ligne
   est utile comme simple log en dev.

Pourquoi c'est léger, pas lourd
--------------------------------
Ce pipeline n'a pas besoin d'OpenTelemetry. Il lui faut :
  * une ligne de log structurée qui survive au passage stdout vers CloudWatch,
  * un historique de runs auditable interrogeable depuis le même warehouse que
    le dashboard,
  * un compteur alarmable (`PipelineErrors`), prêt à câbler sur CloudWatch en production.

Trois primitives, ~120 lignes, zéro nouvelle dépendance.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from loguru import logger


# ---------------------------------------------------------------------------
# Configuration du logger
# ---------------------------------------------------------------------------
def _json_sink(message) -> None:
    """Sink loguru qui imprime un objet JSON par enregistrement sur stdout.
    La forme reste stable pour que le filtre de métrique CloudWatch
    `{ $.level = "ERROR" }` continue de matcher."""
    record = message.record
    payload = {
        "ts": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": record["name"],
        "message": record["message"],
        "module": record["module"],
        "function": record["function"],
        "line": record["line"],
    }
    if record["exception"] is not None:
        payload["exception"] = str(record["exception"].value)
    if record["extra"]:
        # Éviter les collisions avec les clés réservées ci-dessus
        payload.update({f"x_{k}": v for k, v in record["extra"].items()})
    print(json.dumps(payload, default=str), flush=True)


def configure_logger() -> None:
    """Installe le bon sink selon `TESSERA_LOG_FORMAT`. Idempotente."""
    fmt = os.getenv("TESSERA_LOG_FORMAT", "pretty").strip().lower()
    level = os.getenv("TESSERA_LOG_LEVEL", "INFO").upper()
    logger.remove()
    if fmt == "json":
        logger.add(_json_sink, level=level, backtrace=False, diagnose=False)
    else:
        logger.add(
            sys.stderr,
            level=level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
                "<level>{level: <8}</level> "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan> | <level>{message}</level>"
            ),
            colorize=True,
            backtrace=True,
            diagnose=False,
        )


# ---------------------------------------------------------------------------
# Table d'audit
# ---------------------------------------------------------------------------
_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS audit_pipeline_runs (
    run_id        VARCHAR        PRIMARY KEY,
    pipeline      VARCHAR        NOT NULL,
    step          VARCHAR        NOT NULL,
    environment   VARCHAR        NOT NULL,
    start_ts      TIMESTAMP      NOT NULL,
    end_ts        TIMESTAMP,
    duration_ms   BIGINT,
    status        VARCHAR        NOT NULL,    -- success | failed | running
    rows_in       BIGINT,
    rows_out      BIGINT,
    error         VARCHAR,
    extra         JSON
);
"""


def _audit_db_path() -> Path:
    """Emplacement de la table d'audit. Par défaut dans le fichier DuckDB du warehouse
    pour que le dashboard puisse lire l'historique des runs aux côtés des marts."""
    explicit = os.getenv("TESSERA_AUDIT_DB", "").strip()
    if explicit:
        return Path(explicit)
    # Même ordre de résolution que app/lib/db.py (_resolve_db_path) :
    # TESSERA_DUCKDB_PATH > DUCKDB_PATH > défaut ; sinon l'audit risque d'être écrit
    # dans un fichier différent de celui que lit le dashboard.
    default = Path(
        os.getenv("TESSERA_DUCKDB_PATH")
        or os.getenv("DUCKDB_PATH")
        or str(Path(__file__).resolve().parents[1] / "warehouse" / "tessera.duckdb")
    )
    default.parent.mkdir(parents=True, exist_ok=True)
    return default


def _connect_audit() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(_audit_db_path()))
    conn.execute(_AUDIT_DDL)
    return conn


@dataclass
class RunRecord:
    """Une ligne dans `audit_pipeline_runs`. Mutée au fil du `pipeline_run`."""

    run_id: str
    pipeline: str
    step: str
    environment: str
    start_ts: datetime
    end_ts: datetime | None = None
    duration_ms: int | None = None
    status: str = "running"
    rows_in: int | None = None
    rows_out: int | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@contextmanager
def pipeline_run(pipeline: str, step: str, **extra: Any) -> Iterator[RunRecord]:
    """Encapsule une unité de travail du pipeline et persiste son résultat.

    Usage :
        with pipeline_run("ingest", "ga4", source="ga4") as run:
            rows = extract_and_write(...)
            run.rows_out = rows

    En cas d'exception, la ligne est marquée `failed` avec l'erreur sérialisée
    et l'exception est re-levée, jamais silencieuse.
    """
    record = RunRecord(
        run_id=f"{pipeline}:{step}:{int(time.time() * 1000)}",
        pipeline=pipeline,
        step=step,
        environment=os.getenv("TESSERA_ENV", "dev"),
        # UTC *naïf* : la colonne est TIMESTAMP (sans fuseau). Un datetime
        # tz-aware serait converti en heure LOCALE par DuckDB au stockage,
        # alors que le dashboard relit ces valeurs comme de l'UTC (lags négatifs).
        start_ts=datetime.now(UTC).replace(tzinfo=None),
        extra=dict(extra),
    )
    logger.bind(run_id=record.run_id, step=step, pipeline=pipeline).info(
        f"[{pipeline}:{step}] start"
    )
    t0 = time.perf_counter()
    try:
        yield record
        record.status = "success"
    except Exception as exc:  # noqa: BLE001
        record.status = "failed"
        record.error = f"{type(exc).__name__}: {exc}"
        record.extra["traceback"] = traceback.format_exc(limit=2)
        logger.opt(exception=exc).bind(run_id=record.run_id).error(f"[{pipeline}:{step}] failed")
        raise
    finally:
        record.end_ts = datetime.now(UTC).replace(tzinfo=None)
        record.duration_ms = int((time.perf_counter() - t0) * 1000)
        try:
            with _connect_audit() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_pipeline_runs VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    [
                        record.run_id,
                        record.pipeline,
                        record.step,
                        record.environment,
                        record.start_ts,
                        record.end_ts,
                        record.duration_ms,
                        record.status,
                        record.rows_in,
                        record.rows_out,
                        record.error,
                        json.dumps(record.extra, default=str),
                    ],
                )
        except Exception as audit_exc:  # noqa: BLE001
            # Les écritures dans la table d'audit ne doivent jamais casser le pipeline ; on log et on continue.
            logger.warning(f"audit write failed (non-fatal): {audit_exc}")
        logger.bind(
            run_id=record.run_id, status=record.status, duration_ms=record.duration_ms
        ).info(f"[{pipeline}:{step}] {record.status} in {record.duration_ms} ms")


def record_run(
    pipeline: str,
    step: str,
    status: str = "success",
    duration_ms: int | None = None,
    rows_out: int | None = None,
    error: str | None = None,
    **extra: Any,
) -> None:
    """Insère directement une ligne *terminée* dans `audit_pipeline_runs`.

    Sert aux étapes orchestrées hors-process (dbt, Soda) et au mode synthétique,
    qui ne passent pas par le context manager `pipeline_run`. Sans cela la table
    d'audit reste vide et le dashboard ne peut pas refléter l'état réel du pipeline.
    """
    # UTC naïf, même raison que dans pipeline_run (colonne TIMESTAMP sans fuseau).
    now = datetime.now(UTC).replace(tzinfo=None)
    rec = RunRecord(
        run_id=f"{pipeline}:{step}:{int(time.time() * 1000)}",
        pipeline=pipeline,
        step=step,
        environment=os.getenv("TESSERA_ENV", "dev"),
        start_ts=now,
        end_ts=now,
        duration_ms=duration_ms,
        status=status,
        rows_out=rows_out,
        error=error,
        extra=dict(extra),
    )
    try:
        with _connect_audit() as conn:
            conn.execute(
                "INSERT INTO audit_pipeline_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    rec.run_id,
                    rec.pipeline,
                    rec.step,
                    rec.environment,
                    rec.start_ts,
                    rec.end_ts,
                    rec.duration_ms,
                    rec.status,
                    rec.rows_in,
                    rec.rows_out,
                    rec.error,
                    json.dumps(rec.extra, default=str),
                ],
            )
        logger.bind(run_id=rec.run_id, status=status).info(
            f"[{pipeline}:{step}] enregistré ({status})"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"audit record_run failed (non-fatal): {exc}")


# ---------------------------------------------------------------------------
# Métriques
# ---------------------------------------------------------------------------
def emit_metric(name: str, value: float, tags: dict[str, Any] | None = None) -> None:
    """Imprime une ligne JSON de métrique. Le filtre de métrique CloudWatch reconnaît
    cette forme ; en dev, c'est juste une ligne de log supplémentaire."""
    payload = {
        "metric": name,
        "value": value,
        "ts": datetime.now(UTC).isoformat(),
        "tags": tags or {},
    }
    print(json.dumps(payload, default=str), flush=True)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
__all__ = ["configure_logger", "pipeline_run", "record_run", "emit_metric", "RunRecord"]
