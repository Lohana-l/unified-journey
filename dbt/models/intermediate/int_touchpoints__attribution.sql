{{ config(materialized='view') }}

/*
    The four attribution models, implemented side-by-side.

    Output schema:
        conversion_id, touchpoint_id, channel_key,
        attribution_model, weight, revenue_share_eur

    Invariant enforced by tests/assert_attribution_weights_sum_to_one.sql:
        For every (conversion_id, attribution_model) pair,
        SUM(weight) = 1.0.
*/

WITH ranked AS (
    SELECT
        conversion_id,
        conversion_value_eur,
        touchpoint_id,
        touchpoint_ts,
        channel_key,
        unified_user_id,
        ROW_NUMBER() OVER (
            PARTITION BY conversion_id ORDER BY touchpoint_ts ASC
        ) AS pos_asc,
        ROW_NUMBER() OVER (
            PARTITION BY conversion_id ORDER BY touchpoint_ts DESC
        ) AS pos_desc,
        COUNT(*) OVER (PARTITION BY conversion_id) AS n_touches
    FROM {{ ref('int_touchpoints__enriched') }}
),

-- Model 1: FIRST-TOUCH, 100% to the earliest touch.
first_touch AS (
    SELECT
        conversion_id, conversion_value_eur, touchpoint_id, channel_key,
        'first_touch'                  AS attribution_model,
        1.0                            AS weight,
        conversion_value_eur           AS revenue_share_eur
    FROM ranked WHERE pos_asc = 1
),

-- Model 2: LAST-TOUCH, 100% to the latest touch before conversion.
last_touch AS (
    SELECT
        conversion_id, conversion_value_eur, touchpoint_id, channel_key,
        'last_touch'                   AS attribution_model,
        1.0                            AS weight,
        conversion_value_eur           AS revenue_share_eur
    FROM ranked WHERE pos_desc = 1
),

-- Model 3: LINEAR, 1/N per touch.
linear AS (
    SELECT
        conversion_id, conversion_value_eur, touchpoint_id, channel_key,
        'linear'                       AS attribution_model,
        1.0 / n_touches                AS weight,
        conversion_value_eur / n_touches AS revenue_share_eur
    FROM ranked
),

-- Model 4: POSITION-BASED, 40/20/40 split (50/50 if n=2, 100 if n=1).
position_based AS (
    SELECT
        conversion_id,
        conversion_value_eur,
        touchpoint_id,
        channel_key,
        'position_based' AS attribution_model,
        CASE
            WHEN n_touches = 1                           THEN 1.0
            WHEN n_touches = 2                           THEN 0.5
            WHEN pos_asc = 1 OR pos_desc = 1             THEN 0.4
            ELSE                                              0.2 / (n_touches - 2)
        END AS weight,
        conversion_value_eur *
        CASE
            WHEN n_touches = 1                           THEN 1.0
            WHEN n_touches = 2                           THEN 0.5
            WHEN pos_asc = 1 OR pos_desc = 1             THEN 0.4
            ELSE                                              0.2 / (n_touches - 2)
        END AS revenue_share_eur
    FROM ranked
)

SELECT * FROM first_touch
UNION ALL SELECT * FROM last_touch
UNION ALL SELECT * FROM linear
UNION ALL SELECT * FROM position_based
