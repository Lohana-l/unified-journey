"""
Helper de connexion DuckDB, indépendant du framework.

Utilisé par le dashboard de monitoring CDP Streamlit (`app.py` à la racine
du dépôt) pour servir chaque KPI, ligne du registre RGPD et entrée de log pipeline.
La connexion est ouverte en **lecture seule** pour qu'un bug UI ne puisse jamais
modifier le warehouse.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

# ---------------------------------------------------------------------------
# Résolution du chemin
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "warehouse" / "tessera.duckdb"


def _resolve_db_path() -> Path:
    """Prioritise `TESSERA_DUCKDB_PATH`, puis `DUCKDB_PATH`, sinon la valeur par défaut du projet."""
    explicit = os.getenv("TESSERA_DUCKDB_PATH") or os.getenv("DUCKDB_PATH")
    return Path(explicit) if explicit else DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# Connexion
# ---------------------------------------------------------------------------
def get_connection() -> duckdb.DuckDBPyConnection:
    """Retourne une connexion DuckDB en lecture seule.

    Lève FileNotFoundError si le warehouse n'a pas encore été construit -
    l'appelant est censé basculer sur les données simulées et remonter la
    situation à l'interface (voir `app.main._safe_kpis`).
    """
    path = _resolve_db_path()
    if not path.exists():
        raise FileNotFoundError(
            f"DuckDB file not found at {path}. "
            "Run `make pipeline` (or `dbt build`) first to materialise the marts."
        )
    return duckdb.connect(str(path), read_only=True)


# ---------------------------------------------------------------------------
# Sonde de santé
# ---------------------------------------------------------------------------
def warehouse_status(conn: duckdb.DuckDBPyConnection | None) -> dict[str, Any]:
    """Retourne un petit dict consommé par le badge de statut en en-tête.

    Volontairement léger : un seul aller-retour `SELECT 1`. Le `mtime` du
    fichier DuckDB est exposé pour que l'interface affiche "dernier build"
    sans parser le `run_results.json` de dbt.
    """
    db_path = _resolve_db_path()
    base = {
        "warehouse": "offline",
        "duckdb_version": duckdb.__version__,
        "path": str(db_path),
        "size_bytes": None,
        "mtime": None,
        "ts": datetime.now(UTC).isoformat(),
    }
    if not db_path.exists():
        return base

    try:
        stat = db_path.stat()
        base["size_bytes"] = stat.st_size
        base["mtime"] = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    except OSError:
        pass

    if conn is None:
        return base

    try:
        conn.execute("SELECT 1").fetchone()
        base["warehouse"] = "online"
    except Exception:  # noqa: BLE001
        base["warehouse"] = "degraded"
    return base
