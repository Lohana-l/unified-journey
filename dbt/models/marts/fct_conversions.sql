{{ config(materialized='table') }}

/*
    One row per conversion × channel, with the four attribution models as
    four columns. This is the canonical fact table for the Attribution page.

    Example query that powers the Streamlit "compare attribution models" chart:
        SELECT
            channel_key,
            SUM(revenue_first_touch)     AS revenue_first,
            SUM(revenue_last_touch)      AS revenue_last,
            SUM(revenue_linear)          AS revenue_linear,
            SUM(revenue_position_based)  AS revenue_position
        FROM marts.fct_conversions
        GROUP BY channel_key;
*/

WITH attribution AS (
    SELECT
        conversion_id,
        channel_key,
        SUM(CASE WHEN attribution_model = 'first_touch'    THEN revenue_share_eur ELSE 0 END) AS revenue_first_touch,
        SUM(CASE WHEN attribution_model = 'last_touch'     THEN revenue_share_eur ELSE 0 END) AS revenue_last_touch,
        SUM(CASE WHEN attribution_model = 'linear'         THEN revenue_share_eur ELSE 0 END) AS revenue_linear,
        SUM(CASE WHEN attribution_model = 'position_based' THEN revenue_share_eur ELSE 0 END) AS revenue_position_based
    FROM {{ ref('int_touchpoints__attribution') }}
    GROUP BY conversion_id, channel_key
),

order_meta AS (
    SELECT
        o.order_id                                    AS conversion_id,
        o.order_ts                                    AS conversion_ts,
        o.total_price_eur                             AS conversion_value_eur,
        o.country                                     AS country,
        idg.unified_user_id
    FROM {{ ref('stg_shopify__orders') }} o
    LEFT JOIN {{ ref('int_identity__graph') }} idg
        ON idg.raw_id = CONCAT('shopify_customer:', CAST(o.shopify_customer_id AS VARCHAR))
)

SELECT
    om.conversion_id,
    om.conversion_ts,
    CAST(om.conversion_ts AS DATE)   AS conversion_date,
    om.unified_user_id,
    om.country,
    om.conversion_value_eur,
    a.channel_key,
    a.revenue_first_touch,
    a.revenue_last_touch,
    a.revenue_linear,
    a.revenue_position_based
FROM order_meta om
LEFT JOIN attribution a USING (conversion_id)
