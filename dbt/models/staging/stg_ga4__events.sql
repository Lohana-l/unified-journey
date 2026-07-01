{{ config(materialized='view') }}

-- Typed, renamed, PII-minimised view over GA4 bronze.
-- Consent filter: drop withdrawn events immediately; keep anonymous for
-- aggregate analytics (bounce rate etc) but mark them for filtered joins.

WITH raw AS (

    SELECT *
    FROM {{ source('raw_ga4', 'events') }}
    WHERE consent_status != 'withdrawn'

)

SELECT
    event_id                              AS event_id,
    event_name                            AS event_name,
    CAST(event_ts AS TIMESTAMP)           AS event_ts,
    ga_client_id                          AS ga_client_id,
    ga_user_id                            AS ga_user_id,
    ga_session_id                         AS ga_session_id,
    page_location                         AS page_location,
    page_title                            AS page_title,
    device_category                       AS device_category,
    country                               AS country,
    source                                AS utm_source,
    medium                                AS utm_medium,
    campaign                               AS utm_campaign,
    item_id                               AS item_sku,
    value_eur                             AS value_eur,
    consent_status                        AS consent_status,
    -- Channel derivation (matches dim_channels keys)
    CASE
        WHEN medium = 'cpc'       AND source = 'meta'     THEN 'paid_social'
        WHEN medium = 'cpc'       AND source = 'tiktok'   THEN 'paid_social_tt'
        WHEN medium = 'cpc'       AND source = 'google'   THEN 'paid_search'
        WHEN medium = 'organic'                           THEN 'organic_search'
        WHEN medium = 'email'                             THEN 'email'
        WHEN medium = 'display'                           THEN 'display'
        WHEN medium = 'referral'                          THEN 'referral'
        WHEN medium = 'social'                            THEN 'social_organic'
        ELSE                                                   'direct'
    END                                   AS channel_key
FROM raw
