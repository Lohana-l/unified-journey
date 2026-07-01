{{ config(materialized='view') }}

SELECT
    order_id                                          AS order_id,
    customer_id                                       AS shopify_customer_id,
    sha256(LOWER(TRIM(email)))                        AS email_hash,
    CAST(created_at AS TIMESTAMP)                     AS order_ts,
    CAST(total_price_eur AS DOUBLE)                   AS total_price_eur,
    currency                                          AS currency,
    financial_status                                  AS financial_status,
    fulfillment_status                                AS fulfillment_status,
    country                                           AS country,
    consent_status                                    AS consent_status
FROM {{ source('raw_shopify', 'orders') }}
WHERE consent_status != 'withdrawn'
