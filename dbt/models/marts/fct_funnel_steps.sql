{{ config(materialized='table') }}

/*
    Funnel volumes per acquisition channel.
    Each column = count of users who reached that step at least once.
*/

SELECT
    s.acquisition_channel                                AS channel_key,
    COUNT(DISTINCT f.unified_user_id)                    AS users_visited,
    COUNT(DISTINCT CASE WHEN step_2_pdp      = 1 THEN f.unified_user_id END) AS users_pdp,
    COUNT(DISTINCT CASE WHEN step_3_atc      = 1 THEN f.unified_user_id END) AS users_add_to_cart,
    COUNT(DISTINCT CASE WHEN step_4_checkout = 1 THEN f.unified_user_id END) AS users_checkout,
    COUNT(DISTINCT CASE WHEN step_5_purchase = 1 THEN f.unified_user_id END) AS users_purchased
FROM {{ ref('int_funnel__steps') }} f
LEFT JOIN {{ ref('fct_sessions') }} s
    ON s.unified_user_id = f.unified_user_id
   AND s.stitched_session_id = f.stitched_session_id
WHERE s.acquisition_channel IS NOT NULL
GROUP BY s.acquisition_channel
