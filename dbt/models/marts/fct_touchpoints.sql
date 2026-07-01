{{ config(materialized='table') }}

SELECT
    t.touchpoint_id,
    t.touchpoint_ts,
    CAST(t.touchpoint_ts AS DATE)   AS touchpoint_date,
    t.source,
    t.channel_key,
    t.unified_user_id,
    t.conversion_id,
    t.conversion_ts,
    t.conversion_value_eur
FROM {{ ref('int_touchpoints__enriched') }} t
