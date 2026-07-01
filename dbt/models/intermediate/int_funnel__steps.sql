{{ config(materialized='view') }}

/*
    Funnel step reached per unified user per session.
    Steps (monotonic): page_view, view_item, add_to_cart, begin_checkout, purchase.

    L'étape purchase est détectée par l'événement GA4 `purchase` DE LA SESSION,
    comme les 4 autres étapes. (L'ancienne version utilisait EXISTS(une commande
    Shopify, n'importe quand) : un acheteur voyait TOUTES ses sessions flaggées
    "achat", y compris celles sans checkout, d'où un entonnoir non monotone par canal,
    test assert_funnel_monotonic_decay en échec.)
*/

SELECT
    unified_user_id,
    stitched_session_id,
    MAX(CASE WHEN event_name = 'page_view'      THEN 1 ELSE 0 END) AS step_1_viewed,
    MAX(CASE WHEN event_name = 'view_item'      THEN 1 ELSE 0 END) AS step_2_pdp,
    MAX(CASE WHEN event_name = 'add_to_cart'    THEN 1 ELSE 0 END) AS step_3_atc,
    MAX(CASE WHEN event_name = 'begin_checkout' THEN 1 ELSE 0 END) AS step_4_checkout,
    MAX(CASE WHEN event_name = 'purchase'       THEN 1 ELSE 0 END) AS step_5_purchase
FROM {{ ref('int_sessions__stitched') }}
WHERE unified_user_id IS NOT NULL
GROUP BY unified_user_id, stitched_session_id
