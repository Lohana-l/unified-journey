{{ config(materialized='view') }}

/*
    Every touchpoint (web + paid + email) enriched with:
      - unified_user_id
      - channel_key
      - the conversion_id it should get credit for (if any, within the window)

    Touchpoint definition: any event that can plausibly have influenced a
    purchase decision. We include:
      - GA4 non-purchase events (page_view, view_item, add_to_cart, begin_checkout)
      - Email clicks
      - Meta Pixel ViewContent / AddToCart / InitiateCheckout (not Purchase)

    A touchpoint is attributable to a conversion if:
      touchpoint_ts <  conversion_ts
      AND conversion_ts - touchpoint_ts <= attribution_window_days
*/

WITH ga_touches AS (
    SELECT
        event_id                                     AS touchpoint_id,
        event_ts                                     AS touchpoint_ts,
        'ga4'                                        AS source,
        channel_key,
        unified_user_id
    FROM {{ ref('int_sessions__stitched') }}
    WHERE event_name != 'purchase'
      AND unified_user_id IS NOT NULL
),

meta_touches AS (
    SELECT
        m.event_id                                   AS touchpoint_id,
        m.event_ts                                   AS touchpoint_ts,
        'meta'                                       AS source,
        m.channel_key,
        idg.unified_user_id
    FROM {{ ref('stg_meta__pixel_events') }} m
    LEFT JOIN {{ ref('int_identity__graph') }} idg
        ON  idg.raw_id = CONCAT('meta_fbp:', m.fbp)
    WHERE m.event_name != 'Purchase'
      AND idg.unified_user_id IS NOT NULL
),

email_touches AS (
    SELECT
        e.event_id                                   AS touchpoint_id,
        e.event_ts                                   AS touchpoint_ts,
        'email'                                      AS source,
        e.channel_key,
        idg.unified_user_id
    FROM {{ ref('stg_email__events') }} e
    LEFT JOIN {{ ref('int_identity__graph') }} idg
        ON  idg.raw_id = CONCAT('email_subscriber:', e.subscriber_id)
    WHERE e.event_name = 'campaign.clicked'
      AND idg.unified_user_id IS NOT NULL
),

all_touches AS (
    SELECT * FROM ga_touches
    UNION ALL
    SELECT * FROM meta_touches
    UNION ALL
    SELECT * FROM email_touches
),

-- Conversions = Shopify orders, joined to unified_user_id via customer_id.
conversions AS (
    SELECT
        o.order_id                                   AS conversion_id,
        o.order_ts                                   AS conversion_ts,
        o.total_price_eur                            AS conversion_value_eur,
        idg.unified_user_id
    FROM {{ ref('stg_shopify__orders') }} o
    LEFT JOIN {{ ref('int_identity__graph') }} idg
        ON idg.raw_id = CONCAT('shopify_customer:', CAST(o.shopify_customer_id AS VARCHAR))
    WHERE idg.unified_user_id IS NOT NULL
)

SELECT
    t.touchpoint_id,
    t.touchpoint_ts,
    t.source,
    t.channel_key,
    t.unified_user_id,
    c.conversion_id,
    c.conversion_ts,
    c.conversion_value_eur
FROM all_touches t
INNER JOIN conversions c
       ON  c.unified_user_id = t.unified_user_id
       AND t.touchpoint_ts   <  c.conversion_ts
       AND DATEDIFF('day', t.touchpoint_ts, c.conversion_ts)
           <= {{ var('attribution_window_days') }}
