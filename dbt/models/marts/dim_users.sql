{{ config(materialized='table') }}

/*
    dim_users : one row per unified_user_id with currently-known PII hashes
    and consent status. SCD Type 2 historisation is sketched via the
    valid_from / valid_to columns (populated from the identity graph's
    first-seen timestamp). For now we keep a single current
    row per user; the wiring for a full SCD2 rebuild is documented in
    docs/identity_resolution.md §4.
*/

WITH base AS (
    SELECT
        idg.unified_user_id,
        -- RGPD : le hash e-mail n'est conservé dans la couche analytique que
        -- pour les profils au consentement explicite.
        MAX(CASE WHEN c.consent_status = 'granted' THEN c.email_hash END) AS email_hash,
        MAX(c.country)                         AS country,
        MAX(c.consent_status)                  AS consent_status,
        MIN(CAST(c.created_at AS TIMESTAMP))   AS first_seen_at
    FROM {{ ref('int_identity__graph') }} idg
    LEFT JOIN {{ ref('stg_shopify__customers') }} c
        ON idg.raw_id = CONCAT('shopify_customer:', CAST(c.shopify_customer_id AS VARCHAR))
    GROUP BY idg.unified_user_id
)

SELECT
    unified_user_id,
    email_hash,
    country,
    COALESCE(consent_status, 'anonymous') AS consent_status,
    COALESCE(first_seen_at, CURRENT_TIMESTAMP) AS valid_from,
    CAST('9999-12-31' AS TIMESTAMP)           AS valid_to,
    TRUE                                      AS is_current
FROM base
