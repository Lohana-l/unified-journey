"""
Requêtes SQL utilisées par les pages Streamlit.

Toutes les requêtes lisent depuis les gold marts (`marts.*`). Les regrouper
dans un seul module facilite l'audit et les tests, et permet à un relecteur
de vérifier la correspondance dashboard / SQL sans plonger dans le code UI.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import duckdb
import pandas as pd


# ---------------------------------------------------------------------------
# Bandeau KPI vue d'ensemble
# ---------------------------------------------------------------------------
def kpi_overview(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM marts.dim_users)                       AS unified_users,
            (SELECT COUNT(*) FROM marts.fct_sessions)                    AS sessions,
            (SELECT COUNT(*) FROM marts.fct_touchpoints)                 AS touchpoints,
            (SELECT COUNT(*) FROM marts.fct_conversions)                 AS conversions,
            (SELECT COALESCE(SUM(conversion_value_eur), 0)
             FROM marts.fct_conversions)                                 AS revenue_total
        """
    ).fetchone()
    return {
        "unified_users": row[0],
        "sessions": row[1],
        "touchpoints": row[2],
        "conversions": row[3],
        "revenue_total": row[4],
    }


# ---------------------------------------------------------------------------
# Graphe d'identité
# ---------------------------------------------------------------------------
def identity_graph_stats(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Taux de fusion : combien d'IDs bruts ont été consolidés en combien d'utilisateurs."""
    row = conn.execute(
        """
        SELECT
            COUNT(*)                           AS raw_ids,
            COUNT(DISTINCT unified_user_id)    AS unified_users,
            COUNT(*) * 1.0
                / NULLIF(COUNT(DISTINCT unified_user_id), 0)
                                               AS avg_ids_per_user
        FROM intermediate.int_identity__graph
        """
    ).fetchone()
    return {
        "raw_ids": row[0],
        "unified_users": row[1],
        "avg_ids_per_user": float(row[2] or 0),
    }


def identity_cluster_sample(conn: duckdb.DuckDBPyConnection, limit: int = 10) -> pd.DataFrame:
    """Retourne les clusters les plus grands pour illustrer le graphe visuellement."""
    return conn.execute(
        f"""
        WITH sized AS (
            SELECT unified_user_id, COUNT(*) AS n_ids
            FROM intermediate.int_identity__graph
            GROUP BY unified_user_id
            ORDER BY n_ids DESC
            LIMIT {int(limit)}
        )
        SELECT g.unified_user_id, g.raw_id, s.n_ids
        FROM intermediate.int_identity__graph g
        JOIN sized s USING (unified_user_id)
        ORDER BY s.n_ids DESC, g.unified_user_id, g.raw_id
        """
    ).df()


# ---------------------------------------------------------------------------
# Entonnoir de conversion
# ---------------------------------------------------------------------------
def funnel_by_channel(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return conn.execute(
        """
        SELECT
            channel_key,
            users_visited,
            users_pdp,
            users_add_to_cart,
            users_checkout,
            users_purchased
        FROM marts.fct_funnel_steps
        ORDER BY users_visited DESC
        """
    ).df()


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------
def attribution_by_channel(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return conn.execute(
        """
        SELECT
            channel_key,
            SUM(revenue_first_touch)     AS first_touch,
            SUM(revenue_last_touch)      AS last_touch,
            SUM(revenue_linear)          AS linear,
            SUM(revenue_position_based)  AS position_based
        FROM marts.fct_conversions
        WHERE channel_key IS NOT NULL
        GROUP BY channel_key
        ORDER BY linear DESC
        """
    ).df()


def attribution_delta_vs_last_touch(
    conn: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    """Gain ou perte de revenu par canal en passant du last-touch aux modèles
    multi-touch. C'est la slide que les marketeurs veulent vraiment voir."""
    return conn.execute(
        """
        SELECT
            channel_key,
            SUM(revenue_last_touch)                                      AS last_touch,
            SUM(revenue_position_based)                                  AS position_based,
            SUM(revenue_position_based) - SUM(revenue_last_touch)        AS delta_eur,
            CASE WHEN SUM(revenue_last_touch) = 0 THEN NULL
                 ELSE (SUM(revenue_position_based) - SUM(revenue_last_touch))
                      / SUM(revenue_last_touch)
            END                                                          AS delta_pct
        FROM marts.fct_conversions
        WHERE channel_key IS NOT NULL
        GROUP BY channel_key
        ORDER BY delta_eur DESC
        """
    ).df()


# ---------------------------------------------------------------------------
# Cohortes
# ---------------------------------------------------------------------------
def weekly_cohort_retention(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Cohortes d'acquisition hebdomadaires, revenu par semaine depuis la première conversion."""
    return conn.execute(
        """
        WITH first_conv AS (
            SELECT
                unified_user_id,
                DATE_TRUNC('week', MIN(conversion_date)) AS cohort_week
            FROM marts.fct_conversions
            GROUP BY unified_user_id
        ),
        activity AS (
            SELECT
                fc.cohort_week,
                DATE_DIFF('week', fc.cohort_week,
                          DATE_TRUNC('week', c.conversion_date)) AS weeks_since,
                SUM(c.conversion_value_eur) AS revenue
            FROM marts.fct_conversions c
            JOIN first_conv fc USING (unified_user_id)
            GROUP BY 1, 2
        )
        SELECT cohort_week, weeks_since, revenue
        FROM activity
        WHERE weeks_since BETWEEN 0 AND 12
        ORDER BY cohort_week, weeks_since
        """
    ).df()


# ===========================================================================
# Dashboard CDP Monitoring : helpers utilisés directement par app.py
# ===========================================================================

DATA_SOURCES = ["GA4", "Meta Ads", "Shopify", "Mailchimp"]

# Mapping noms d'affichage UI / valeurs `source` dans fct_touchpoints / pipelines
_SOURCE_KEY = {
    "GA4": "ga4",
    "Meta Ads": "meta",
    "Shopify": "shopify",
    "Mailchimp": "mailchimp",
}

# La source e-mail est stockée 'email' dans les marts mais 'mailchimp' dans les
# noms de pipeline d'audit. On réconcilie les deux conventions ici pour que les
# libellés et filtres soient cohérents partout (graphe d'identité, RGPD, logs…).
_KEY_TO_DISPLAY = {
    "ga4": "GA4",
    "meta": "Meta Ads",
    "shopify": "Shopify",
    "mailchimp": "Mailchimp",
    "email": "Mailchimp",
}

# Libellé d'affichage : toutes les clés source possibles (pour les filtres SQL).
_DISPLAY_TO_KEYS = {
    "GA4": ["ga4"],
    "Meta Ads": ["meta"],
    "Shopify": ["shopify"],
    "Mailchimp": ["mailchimp", "email"],
}


def _display_from_key(key: str) -> str:
    """Clé source (marts ou pipeline) : libellé d'affichage UI."""
    return _KEY_TO_DISPLAY.get((key or "").lower(), (key or "").upper() or "?")


def _src_filter_sql(sources: list[str] | None, col: str = "source") -> str:
    """Construit le filtre SQL `AND col IN (...)`. Vide si aucune source choisie."""
    if not sources:
        return ""
    keys: list[str] = []
    for s in sources:
        keys.extend(_DISPLAY_TO_KEYS.get(s, [_SOURCE_KEY.get(s, s).lower()]))
    quoted = ",".join(f"'{k}'" for k in keys)
    return f" AND LOWER({col}) IN ({quoted})"


# ---------------------------------------------------------------------------
# Bandeau "Pipeline opérationnel"  (Runs / Succès / Soda / RGPD / Kestra)
# ---------------------------------------------------------------------------
def pipeline_health(conn: duckdb.DuckDBPyConnection, start: date, end: date) -> dict[str, Any]:
    """Métriques de l'en-tête de santé pipeline, calculées sur la fenêtre demandée."""
    row = conn.execute(
        """
        SELECT
            COUNT(*)                                                      AS runs,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) * 100.0
                / NULLIF(COUNT(*), 0)                                     AS success_pct,
            AVG(duration_ms) / 1000.0                                     AS kestra_avg_s,
            SUM(CASE WHEN status = 'failed' AND pipeline = 'soda'
                     THEN 1 ELSE 0 END)                                   AS soda_alerts,
            MAX(end_ts)                                                   AS last_run_ts
        FROM audit_pipeline_runs
        WHERE start_ts >= ? AND start_ts < ?
        """,
        [start, end + timedelta_one_day()],
    ).fetchone()

    rgpd_row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN consent_status IS NOT NULL THEN 1 ELSE 0 END) * 100.0
                / NULLIF(COUNT(*), 0) AS rgpd_pct
        FROM marts.dim_users
        """
    ).fetchone()

    return {
        "runs": int(row[0] or 0),
        "success_pct": float(row[1] or 0),
        "kestra_avg_s": float(row[2] or 0),
        "soda_alerts": int(row[3] or 0),
        "rgpd_pct": float(rgpd_row[0] or 0),
        "last_run_ts": row[4],
    }


def timedelta_one_day():
    """Imported locally to avoid polluting the module namespace."""
    from datetime import timedelta

    return timedelta(days=1)


# ---------------------------------------------------------------------------
# 4 KPI top metrics (Profils bruts / unifiés / Match / Revenu)
# ---------------------------------------------------------------------------
def top_metrics(
    conn: duckdb.DuckDBPyConnection, start: date, end: date, sources: list[str] | None = None
) -> dict[str, Any]:
    src = _src_filter_sql(sources)
    row = conn.execute(
        f"""
        WITH window_tp AS (
            SELECT * FROM marts.fct_touchpoints
            WHERE touchpoint_ts >= ? AND touchpoint_ts < ?
            {src}
        ),
        raw AS (SELECT COUNT(*) AS n FROM window_tp),
        unified AS (SELECT COUNT(DISTINCT unified_user_id) AS n FROM window_tp),
        rev AS (
            SELECT COALESCE(SUM(revenue_linear), 0) AS r
            FROM marts.fct_conversions
            WHERE conversion_ts >= ? AND conversion_ts < ?
        )
        SELECT
            raw.n         AS profils_bruts,
            unified.n     AS profils_unifies,
            CASE WHEN raw.n = 0 THEN 0
                 ELSE unified.n * 100.0 / raw.n END AS taux_match,
            rev.r         AS revenu_eur
        FROM raw, unified, rev
        """,
        [start, end + timedelta_one_day(), start, end + timedelta_one_day()],
    ).fetchone()
    return {
        "profils_bruts": int(row[0] or 0),
        "profils_unifies": int(row[1] or 0),
        "taux_match": float(row[2] or 0),
        "revenu_eur": float(row[3] or 0),
    }


# ---------------------------------------------------------------------------
# Tab Vue d'ensemble : bar chart "Profils unifiés par source"
# ---------------------------------------------------------------------------
def unification_per_source(
    conn: duckdb.DuckDBPyConnection, start: date, end: date, sources: list[str] | None = None
) -> pd.DataFrame:
    src = _src_filter_sql(sources)
    df = conn.execute(
        f"""
        SELECT
            source                                  AS source_key,
            COUNT(*)                                AS profils_bruts,
            COUNT(DISTINCT unified_user_id)         AS profils_unifies
        FROM marts.fct_touchpoints
        WHERE touchpoint_ts >= ? AND touchpoint_ts < ?
        {src}
        GROUP BY source
        ORDER BY profils_bruts DESC
        """,
        [start, end + timedelta_one_day()],
    ).df()
    # Map back to display names + compute match rate
    df["Source"] = df["source_key"].apply(_display_from_key)
    df["Taux de match (%)"] = (
        (df["profils_unifies"] / df["profils_bruts"].replace(0, pd.NA) * 100).round(1).fillna(0)
    )
    out = df[["Source", "profils_bruts", "profils_unifies", "Taux de match (%)"]].copy()
    out.columns = ["Source", "Profils bruts", "Profils unifiés", "Taux de match (%)"]
    return out


# ---------------------------------------------------------------------------
# Tab Vue d'ensemble : line chart "Évolution du score qualité" (hebdo)
# ---------------------------------------------------------------------------
def quality_trend_weekly(conn: duckdb.DuckDBPyConnection, start: date, end: date) -> pd.DataFrame:
    """Score qualité hebdo = % de runs `success` parmi tous les runs de la semaine."""
    df = conn.execute(
        """
        SELECT
            DATE_TRUNC('week', start_ts)::DATE                          AS semaine,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) * 100.0
                / NULLIF(COUNT(*), 0)                                   AS score
        FROM audit_pipeline_runs
        WHERE start_ts >= ? AND start_ts < ?
        GROUP BY 1
        ORDER BY 1
        """,
        [start, end + timedelta_one_day()],
    ).df()
    df.columns = ["Semaine", "Score qualité"]
    return df.set_index("Semaine")


# ---------------------------------------------------------------------------
# Tab RGPD : registre des traitements par source × statut
# ---------------------------------------------------------------------------
def rgpd_registry(
    conn: duckdb.DuckDBPyConnection, sources: list[str] | None = None
) -> pd.DataFrame:
    src = _src_filter_sql(sources, col="t.source")
    df = conn.execute(
        f"""
        SELECT
            t.source                                  AS source_key,
            u.consent_status                          AS statut,
            COUNT(*)                                  AS enregistrements,
            MAX(t.touchpoint_ts)                      AS derniere_maj
        FROM marts.fct_touchpoints t
        JOIN marts.dim_users u USING (unified_user_id)
        WHERE TRUE {src}
        GROUP BY t.source, u.consent_status
        ORDER BY t.source, u.consent_status
        """
    ).df()
    df["Source"] = df["source_key"].apply(_display_from_key)
    statut_map = {"granted": "Consentement OK", "anonymous": "Anonymisé"}
    df["Statut"] = df["statut"].map(lambda s: statut_map.get(s, s or "À anonymiser"))
    out = df[["Source", "Statut", "enregistrements", "derniere_maj"]].copy()
    out.columns = ["Source", "Statut", "Enregistrements", "Dernière MAJ"]
    return out


# ---------------------------------------------------------------------------
# Tab Logs : runs du pipeline (audit_pipeline_runs)
# ---------------------------------------------------------------------------
def pipeline_logs(
    conn: duckdb.DuckDBPyConnection,
    start: date,
    end: date,
    sources: list[str] | None = None,
    limit: int = 200,
) -> pd.DataFrame:
    """Renvoie les derniers runs sur la fenêtre. `Source` est dérivée du nom
    de pipeline (`pipeline` = 'ga4' / 'meta' / 'shopify' / 'mailchimp' / 'dbt' / 'soda')."""
    df = conn.execute(
        """
        SELECT
            LOWER(pipeline)                              AS pipeline_key,
            step                                         AS step,
            UPPER(status)                                AS statut,
            COALESCE(duration_ms, 0) / 1000.0            AS duree_s,
            start_ts                                     AS ts
        FROM audit_pipeline_runs
        WHERE start_ts >= ? AND start_ts < ?
        ORDER BY start_ts DESC
        LIMIT ?
        """,
        [start, end + timedelta_one_day(), int(limit)],
    ).df()
    df["Source"] = df["pipeline_key"].apply(_display_from_key)
    # Map FAILED / WARNING / SUCCESS / RUNNING, déjà en uppercase
    df["Statut"] = df["statut"].replace({"WARN": "WARNING"})
    out = df[["Source", "step", "Statut", "duree_s", "ts"]].copy()
    out.columns = ["Source", "Étape", "Statut", "Durée (s)", "Timestamp"]
    # Filtre source si demandé (après mapping pour respecter les libellés UI)
    if sources:
        out = out[out["Source"].isin(sources)]
    return out


# ---------------------------------------------------------------------------
# Sidebar : STATUT SYSTÈME (5 signaux de service)
# ---------------------------------------------------------------------------
def system_signals(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str]]:
    """Retourne [(name, status, detail), ...] où status ∈ {ok, warn, error}."""
    out: list[tuple[str, str, str]] = []

    # 1. MinIO lakehouse : basé sur le dernier run d'ingestion (s'il écrit, il
    #    a parlé à MinIO).
    minio_row = conn.execute(
        """
        SELECT status, end_ts FROM audit_pipeline_runs
        WHERE step ILIKE '%bronze%' OR pipeline IN ('ga4','meta','shopify','mailchimp')
        ORDER BY end_ts DESC NULLS LAST LIMIT 1
        """
    ).fetchone()
    if minio_row and minio_row[0] == "success":
        out.append(("MinIO lakehouse", "ok", "3/3 buckets up"))
    elif minio_row:
        out.append(("MinIO lakehouse", "warn", f"dernier write : {minio_row[0]}"))
    else:
        out.append(("MinIO lakehouse", "error", "aucun run trouvé"))

    # 2. Kestra orchestrator : lag depuis le dernier run
    k = conn.execute("SELECT MAX(end_ts) FROM audit_pipeline_runs").fetchone()
    if k and k[0]:
        last = k[0]
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        lag = datetime.now(UTC) - last
        lag_s = int(lag.total_seconds())
        # Seuils alignés sur la cadence batch quotidienne du pipeline :
        # vert < 26 h, orange < 48 h, rouge au-delà. (Les anciens seuils
        # 60 s / 10 min correspondaient à du streaming, pas à ce projet.)
        status = "ok" if lag_s < 26 * 3600 else "warn" if lag_s < 48 * 3600 else "error"
        lag_label = (
            f"lag {lag_s}s"
            if lag_s < 120
            else f"lag {lag_s // 60} min"
            if lag_s < 7200
            else f"lag {lag_s // 3600} h"
        )
        out.append(("Kestra orchestrator", status, lag_label))
    else:
        out.append(("Kestra orchestrator", "error", "aucun run"))

    # 3. dbt build : dernier run du pipeline "dbt"
    d = conn.execute(
        """
        SELECT status, end_ts FROM audit_pipeline_runs
        WHERE pipeline = 'dbt' ORDER BY end_ts DESC NULLS LAST LIMIT 1
        """
    ).fetchone()
    if d and d[1]:
        last = d[1]
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        mins = int((datetime.now(UTC) - last).total_seconds() // 60)
        when = "à l'instant" if mins == 0 else f"il y a {mins} min"
        out.append(("dbt build", "ok" if d[0] == "success" else "warn", f"last run, {when}"))
    else:
        out.append(("dbt build", "error", "aucun build"))

    # 4. Soda data quality : failures dans la fenêtre récente
    s = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END),
            COUNT(*)
        FROM audit_pipeline_runs WHERE pipeline = 'soda'
          AND start_ts >= NOW() - INTERVAL '1 day'
        """
    ).fetchone()
    soda_fail, soda_total = (s[0] or 0), (s[1] or 0)
    if soda_total == 0:
        out.append(("Soda data quality", "warn", "aucun scan récent"))
    elif soda_fail == 0:
        out.append(("Soda data quality", "ok", f"{soda_total} checks OK"))
    else:
        out.append(("Soda data quality", "warn", f"{soda_fail} check en alerte"))

    # 5. GDPR consent ledger : % de profils avec consent_status renseigné
    g = conn.execute(
        """
        SELECT
            SUM(CASE WHEN consent_status IS NOT NULL THEN 1 ELSE 0 END) * 100.0
                / NULLIF(COUNT(*), 0)
        FROM marts.dim_users
        """
    ).fetchone()
    pct = float(g[0] or 0)
    out.append(("GDPR consent ledger", "ok" if pct >= 99 else "warn", f"{pct:.0f}% propagé"))
    return out


# ---------------------------------------------------------------------------
# Sidebar : FRAÎCHEUR DES SOURCES
# ---------------------------------------------------------------------------
def source_freshness(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str, int]]:
    """Retourne [(display_name, label, minutes), ...] pour les 4 sources.

    Fraîcheur = dernière INGESTION réussie par source (audit_pipeline_runs),
    pas la date du dernier événement métier : les événements du seed sont
    étalés sur 90 jours (valeurs absurdes), et Shopify n'émet pas de
    touchpoints (source de conversions, affichait « jamais reçu »).
    """
    rows = conn.execute(
        """
        SELECT LOWER(pipeline), MAX(COALESCE(end_ts, start_ts))
        FROM audit_pipeline_runs
        WHERE LOWER(pipeline) IN ('ga4', 'meta', 'shopify', 'mailchimp', 'email')
          AND status = 'success'
        GROUP BY 1
        """
    ).fetchall()
    last_by_key = {r[0]: r[1] for r in rows}
    # Le pipeline e-mail peut être audité 'email' : on l'expose aussi sous 'mailchimp'.
    if "mailchimp" not in last_by_key and "email" in last_by_key:
        last_by_key["mailchimp"] = last_by_key["email"]
    out: list[tuple[str, str, int]] = []
    now = datetime.now(UTC)
    for display, key in _SOURCE_KEY.items():
        last = last_by_key.get(key)
        if last is None:
            out.append((display, "jamais reçu", 99_999))
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        mins = max(0, int((now - last).total_seconds() // 60))
        label = "à l'instant" if mins == 0 else f"il y a {mins} min"
        out.append((display, label, mins))
    return out


# ===========================================================================
# Panneaux détaillés : branchés sur les vrais marts (remplacent les anciens
# panneaux codés en dur de app.py).
# ===========================================================================


# ---------------------------------------------------------------------------
# Panneau "Attribution Multi-Touch" : revenu réel par canal (modèle linéaire)
# ---------------------------------------------------------------------------
def attribution_panel(
    conn: duckdb.DuckDBPyConnection, start: date, end: date, limit: int = 5
) -> pd.DataFrame:
    """Revenu attribué par canal sur la période, avec part (%) du total.

    Lit `marts.fct_conversions` (revenue_linear) joint à `marts.dim_channels`
    pour le libellé d'affichage. Renvoie un DataFrame trié décroissant :
    colonnes [canal, revenu, part_pct].
    """
    df = conn.execute(
        """
        SELECT
            COALESCE(ch.channel_display_name, c.channel_key) AS canal,
            SUM(c.revenue_linear)                            AS revenu
        FROM marts.fct_conversions c
        LEFT JOIN marts.dim_channels ch USING (channel_key)
        WHERE c.channel_key IS NOT NULL
          AND c.conversion_ts >= ? AND c.conversion_ts < ?
        GROUP BY 1
        HAVING SUM(c.revenue_linear) > 0
        ORDER BY revenu DESC
        LIMIT ?
        """,
        [start, end + timedelta_one_day(), int(limit)],
    ).df()
    total = float(df["revenu"].sum()) if not df.empty else 0.0
    df["part_pct"] = (df["revenu"] / total * 100).round(0) if total else 0
    return df


# ---------------------------------------------------------------------------
# Panneau "GDPR Score" : répartition réelle des profils par statut de consentement
# ---------------------------------------------------------------------------
def gdpr_breakdown(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Compte réel des profils dans `marts.dim_users` par statut.

    - consent_ok    : consent_status = 'granted'
    - anonymes      : consent_status = 'anonymous' (à anonymiser/oublier)
    - pseudonymises : email_hash renseigné (PII jamais stockée en clair)
    - score_pct     : part de profils avec consentement explicite
    """
    row = conn.execute(
        """
        SELECT
            COUNT(*)                                                      AS total,
            SUM(CASE WHEN consent_status = 'granted'   THEN 1 ELSE 0 END) AS consent_ok,
            SUM(CASE WHEN consent_status = 'anonymous' THEN 1 ELSE 0 END) AS anonymes,
            SUM(CASE WHEN email_hash IS NOT NULL       THEN 1 ELSE 0 END) AS pseudonymises
        FROM marts.dim_users
        """
    ).fetchone()
    total = int(row[0] or 0)
    consent_ok = int(row[1] or 0)
    return {
        "total": total,
        "consent_ok": consent_ok,
        "anonymes": int(row[2] or 0),
        "pseudonymises": int(row[3] or 0),
        "score_pct": round(consent_ok / total * 100) if total else 0,
    }


# ---------------------------------------------------------------------------
# Alerte Soda : checks réellement en échec (audit_pipeline_runs, pipeline='soda')
# ---------------------------------------------------------------------------
def soda_status(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """État réel des contrôles Soda sur les dernières 24 h.

    Renvoie {failed, total, alerts:[(check, detail, minutes), ...]}.
    `alerts` est vide quand tout est au vert.
    """
    summary = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
            COUNT(*)                                           AS total
        FROM audit_pipeline_runs
        WHERE pipeline = 'soda' AND start_ts >= NOW() - INTERVAL '1 day'
        """
    ).fetchone()

    rows = conn.execute(
        """
        SELECT step, error, start_ts
        FROM audit_pipeline_runs
        WHERE pipeline = 'soda' AND status = 'failed'
          AND start_ts >= NOW() - INTERVAL '1 day'
        ORDER BY start_ts DESC
        """
    ).fetchall()

    now = datetime.now(UTC)
    alerts: list[tuple[str, str, int | None]] = []
    for step, error, ts in rows:
        if ts is not None and getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=UTC)
        mins = int((now - ts).total_seconds() // 60) if ts else None
        alerts.append((step or "check", error or "", mins))

    return {
        "failed": int(summary[0] or 0),
        "total": int(summary[1] or 0),
        "alerts": alerts,
    }


# ---------------------------------------------------------------------------
# Timeline pipeline (Gantt) : runs réels des dernières 24 h
# ---------------------------------------------------------------------------
def pipeline_timeline_24h(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Runs des dernières 24 h pour le diagramme de Gantt.

    Colonnes : [source, etape, statut, start_ts, end_ts]. `source` est dérivée
    du nom de pipeline (ga4/meta/shopify/mailchimp) ; dbt et soda restent tels quels.
    """
    df = conn.execute(
        """
        SELECT
            LOWER(pipeline)                              AS pipeline_key,
            step                                         AS etape,
            UPPER(status)                                AS statut,
            start_ts,
            COALESCE(end_ts, start_ts)                   AS end_ts
        FROM audit_pipeline_runs
        WHERE start_ts >= NOW() - INTERVAL '1 day'
        ORDER BY start_ts
        """
    ).df()
    if df.empty:
        return df
    df["source"] = df["pipeline_key"].apply(_display_from_key)
    return df[["source", "etape", "statut", "start_ts", "end_ts"]]
