"""
Test de fumée end-to-end.

S'exécute contre le fichier DuckDB matérialisé par dbt en CI via
`dbt build` sur le seed synthétique. L'objectif est de vérifier la forme
générale des gold marts, sans re-tester chaque invariant dbt (ceux-ci
sont vérifiés dans dbt lui-même).
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pytest

DB_PATH = Path(
    os.getenv(
        "TESSERA_DUCKDB_PATH",
        # Même fichier que dbt (profiles.yml : ../warehouse/tessera.duckdb)
        # et que Soda, sinon le test se skippe silencieusement en CI.
        str(Path(__file__).resolve().parents[2] / "warehouse" / "tessera.duckdb"),
    )
)


@pytest.fixture(scope="module")
def conn() -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        pytest.skip(f"{DB_PATH} not built. Run `dbt build` first.")
    return duckdb.connect(str(DB_PATH), read_only=True)


def test_marts_non_empty(conn: duckdb.DuckDBPyConnection) -> None:
    for table in (
        "dim_users",
        "dim_channels",
        "dim_dates",
        "fct_touchpoints",
        "fct_sessions",
        "fct_conversions",
        "fct_funnel_steps",
    ):
        n = conn.execute(f"SELECT COUNT(*) FROM marts.{table}").fetchone()[0]
        assert n > 0, f"mart {table} vide"


def test_attribution_totals_reconcile(conn: duckdb.DuckDBPyConnection) -> None:
    """Chaque modèle doit conserver le revenu attribué : pour une conversion
    attribuée (au moins un touchpoint dans la fenêtre), la somme de chaque modèle
    redistribue exactement la valeur de commande. fct_conversions a un grain
    conversion x canal, donc on dédoublonne la valeur par conversion avant de
    comparer, et on écarte les conversions hors fenêtre (channel_key NULL)."""
    row = conn.execute(
        """
        WITH per_conversion AS (
            SELECT
                conversion_id,
                MAX(conversion_value_eur)    AS conversion_value_eur,
                SUM(revenue_first_touch)     AS first_total,
                SUM(revenue_last_touch)      AS last_total,
                SUM(revenue_linear)          AS linear_total,
                SUM(revenue_position_based)  AS pos_total
            FROM marts.fct_conversions
            WHERE channel_key IS NOT NULL
            GROUP BY conversion_id
        )
        SELECT
            SUM(conversion_value_eur) AS attributed_gmv,
            SUM(first_total)          AS first_total,
            SUM(last_total)           AS last_total,
            SUM(linear_total)         AS linear_total,
            SUM(pos_total)            AS pos_total
        FROM per_conversion
        """
    ).fetchone()
    attributed_gmv = row[0]
    assert attributed_gmv and attributed_gmv > 0, "aucune conversion attribuée"
    for i, name in enumerate(("first", "last", "linear", "position"), start=1):
        assert (
            abs(row[i] - attributed_gmv) < max(1.0, 0.001 * attributed_gmv)
        ), f"total {name}-touch ({row[i]}) ne réconcilie pas avec le GMV attribué ({attributed_gmv})"


def test_funnel_monotonic(conn: duckdb.DuckDBPyConnection) -> None:
    """Devrait être un ensemble vide si l'invariant tient."""
    violations = conn.execute(
        """
        SELECT channel_key
        FROM marts.fct_funnel_steps
        WHERE users_pdp        > users_visited
           OR users_add_to_cart > users_pdp
           OR users_checkout    > users_add_to_cart
           OR users_purchased   > users_checkout
        """
    ).fetchall()
    assert violations == [], f"Monotonie du funnel violée : {violations}"
