{{ config(materialized='view') }}

/*
    Session stitching:
      - Reuse GA4's native ga_session_id where available.
      - Re-sessionise across devices for the same unified_user_id when the
        gap between events is < session_timeout_minutes.
*/

WITH events_with_user AS (
    SELECT
        g.event_id,
        g.event_ts,
        g.event_name,
        g.channel_key,
        g.page_location,
        g.item_sku,
        g.value_eur,
        g.country,
        g.device_category,
        g.ga_client_id,
        g.ga_session_id,
        idg.unified_user_id
    FROM {{ ref('stg_ga4__events') }} g
    LEFT JOIN {{ ref('int_identity__graph') }} idg
        ON idg.raw_id = CONCAT('ga_client:', g.ga_client_id)
),

with_gaps AS (
    SELECT
        *,
        DATEDIFF(
            'minute',
            LAG(event_ts) OVER (PARTITION BY unified_user_id ORDER BY event_ts),
            event_ts
        ) AS mins_since_prev
    FROM events_with_user
),

with_session_flag AS (
    SELECT
        *,
        CASE
            WHEN mins_since_prev IS NULL
              OR mins_since_prev > {{ var('session_timeout_minutes') }}
            THEN 1 ELSE 0
        END AS is_new_session
    FROM with_gaps
)

SELECT
    event_id,
    event_ts,
    event_name,
    channel_key,
    page_location,
    item_sku,
    value_eur,
    country,
    device_category,
    ga_client_id,
    unified_user_id,
    -- Stitched session id = per-user running count of session starts.
    SUM(is_new_session) OVER (
        PARTITION BY unified_user_id ORDER BY event_ts ROWS UNBOUNDED PRECEDING
    ) AS stitched_session_id
FROM with_session_flag
