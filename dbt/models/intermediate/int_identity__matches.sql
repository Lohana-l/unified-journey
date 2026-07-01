{# Matérialisé en TABLE (et non en vue) : le graphe d'identité aval fait 5
   passes de label propagation qui référencent ce modèle ~10 fois. En vue,
   chaque référence re-télécharge tous les Parquet bronze depuis MinIO via
   HTTP (lenteur + erreurs de connexion intermittentes). En table, le bronze
   n'est lu qu'une fois. #}
{{ config(materialized='table') }}

/*
    Pair-wise identity matches.

    Each row = "these two raw identifiers belong to the same person" with a
    confidence tag. Downstream, int_identity__graph runs label propagation
    to discover the connected components.

    Matching rules applied here:
      L1 (deterministic, confidence=high):
        - Same email_hash across Shopify + Meta + Email.
        - Same ga_user_id + Shopify customer_id (logged-in bridge).
      L2 (session-anchor, confidence=medium):
        - Same ga_client_id carries events that eventually set a ga_user_id.
    GDPR rule:
        - Only match when BOTH ends have consent_status = 'granted'.
*/

WITH

-- L1a: email_hash between Shopify customers and email events
email_shopify_match AS (
    SELECT
        CONCAT('shopify_customer:', c.shopify_customer_id) AS id_a,
        CONCAT('email_hash:',         c.email_hash)        AS id_b,
        'email_hash'                                       AS match_type,
        'high'                                             AS confidence
    FROM {{ ref('stg_shopify__customers') }} c
    WHERE c.consent_status = 'granted' AND c.email_hash IS NOT NULL
),

-- L1b: email_hash between Meta Pixel (Conversion API) and email_hash
email_meta_match AS (
    SELECT DISTINCT
        CONCAT('meta_fbp:',     m.fbp)        AS id_a,
        CONCAT('email_hash:',   m.email_hash) AS id_b,
        'email_hash'                          AS match_type,
        'high'                                AS confidence
    FROM {{ ref('stg_meta__pixel_events') }} m
    WHERE m.consent_status = 'granted'
      AND m.email_hash IS NOT NULL
      AND m.fbp IS NOT NULL
),

-- L1c: email_hash between Email subscribers and email_hash
email_email_match AS (
    SELECT DISTINCT
        CONCAT('email_subscriber:', e.subscriber_id) AS id_a,
        CONCAT('email_hash:',       e.email_hash)   AS id_b,
        'email_hash'                                AS match_type,
        'high'                                      AS confidence
    FROM {{ ref('stg_email__events') }} e
    WHERE e.consent_status = 'granted'
      AND e.email_hash IS NOT NULL
      AND e.subscriber_id IS NOT NULL
),

-- L1d: GA4 ga_user_id (set at login/checkout) = Shopify customer_id
ga_shopify_match AS (
    SELECT DISTINCT
        CONCAT('ga_client:', g.ga_client_id)                       AS id_a,
        CONCAT('shopify_customer:', CAST(g.ga_user_id AS VARCHAR)) AS id_b,
        'logged_in_user_id'                                        AS match_type,
        'high'                                                     AS confidence
    FROM {{ ref('stg_ga4__events') }} g
    WHERE g.consent_status = 'granted'
      AND g.ga_user_id IS NOT NULL
),

-- L2: session-anchor, same ga_client_id across multiple events binds all
-- those events together (trivially). We emit it explicitly so orphan cookies
-- show up as singleton components in the graph rather than being dropped.
ga_self_anchor AS (
    SELECT DISTINCT
        CONCAT('ga_client:', ga_client_id) AS id_a,
        CONCAT('ga_client:', ga_client_id) AS id_b,
        'self'                             AS match_type,
        'high'                             AS confidence
    FROM {{ ref('stg_ga4__events') }}
    WHERE consent_status = 'granted'
),

-- L2b: self-anchor Shopify, chaque client acheteur est au minimum son propre
-- nœud singleton, quel que soit son consentement. On ancre depuis les ORDERS
-- (identifiant pseudonyme, aucune PII) : le consentement gouverne le
-- rapprochement ENTRE sources (L1), pas l'existence d'un identifiant.
-- Sans cet ancrage, les commandes des clients non 'granted' sortent
-- orphelines de fct_conversions (unified_user_id NULL, donc test not_null KO).
shopify_self_anchor AS (
    SELECT DISTINCT
        CONCAT('shopify_customer:', CAST(shopify_customer_id AS VARCHAR)) AS id_a,
        CONCAT('shopify_customer:', CAST(shopify_customer_id AS VARCHAR)) AS id_b,
        'self'                                                            AS match_type,
        'high'                                                            AS confidence
    FROM {{ ref('stg_shopify__orders') }}
    WHERE shopify_customer_id IS NOT NULL
),

all_matches AS (
    SELECT * FROM email_shopify_match
    UNION ALL SELECT * FROM email_meta_match
    UNION ALL SELECT * FROM email_email_match
    UNION ALL SELECT * FROM ga_shopify_match
    UNION ALL SELECT * FROM ga_self_anchor
    UNION ALL SELECT * FROM shopify_self_anchor
),

-- Make the relation symmetric so the graph is undirected.
bidirectional AS (
    SELECT id_a AS raw_id_src, id_b AS raw_id_dst, match_type, confidence FROM all_matches
    UNION ALL
    SELECT id_b AS raw_id_src, id_a AS raw_id_dst, match_type, confidence FROM all_matches
)

SELECT DISTINCT
    raw_id_src,
    raw_id_dst,
    match_type,
    confidence
FROM bidirectional
