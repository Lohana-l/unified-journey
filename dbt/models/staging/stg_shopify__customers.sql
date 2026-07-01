{{ config(materialized='view') }}

SELECT
    customer_id                                       AS shopify_customer_id,
    -- Hash email for analytics layer; raw email stays only in bronze.
    sha256(LOWER(TRIM(email)))                        AS email_hash,
    first_name                                        AS first_name,
    last_name                                         AS last_name,
    accepts_marketing                                 AS accepts_marketing,
    CAST(accepts_marketing_updated_at AS TIMESTAMP)   AS consent_updated_at,
    country                                           AS country,
    CAST(created_at AS TIMESTAMP)                     AS created_at,
    consent_status                                    AS consent_status
FROM {{ source('raw_shopify', 'customers') }}
WHERE consent_status != 'withdrawn'
-- Le bronze est append-only : une re-livraison (re-run du pipeline un autre
-- jour) dépose une nouvelle partition dt=… contenant les mêmes clients.
-- On déduplique ici en gardant la version la plus récente de chaque client,
-- pour que les couches aval restent idempotentes.
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY customer_id
    ORDER BY accepts_marketing_updated_at DESC, created_at DESC
) = 1
