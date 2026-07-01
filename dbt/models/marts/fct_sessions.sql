{{ config(materialized='table') }}

/*
    One row per stitched session. Aggregates the events within the session
    into metrics useful for funnel / behaviour analysis.
*/

SELECT
    unified_user_id,
    stitched_session_id,
    MIN(event_ts)                                      AS session_started_at,
    MAX(event_ts)                                      AS session_ended_at,
    DATEDIFF('second', MIN(event_ts), MAX(event_ts))   AS session_duration_sec,
    COUNT(*)                                           AS event_count,
    COUNT(DISTINCT page_location)                      AS unique_pages,
    MAX(channel_key)                                   AS acquisition_channel,
    MAX(device_category)                               AS device_category,
    MAX(country)                                       AS country,
    MAX(CASE WHEN event_name = 'purchase' THEN 1 ELSE 0 END) AS is_purchase_session
FROM {{ ref('int_sessions__stitched') }}
WHERE unified_user_id IS NOT NULL
GROUP BY unified_user_id, stitched_session_id
