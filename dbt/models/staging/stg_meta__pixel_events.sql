{{ config(materialized='view') }}

WITH raw AS (
    SELECT *
    FROM {{ source('raw_meta', 'pixel_events') }}
    WHERE consent_status != 'withdrawn'
)

SELECT
    event_id                                         AS event_id,
    event_name                                       AS event_name,
    TO_TIMESTAMP(event_time)                         AS event_ts,
    fbp                                              AS fbp,
    fbc                                              AS fbc,
    em_hash                                          AS email_hash,
    ph_hash                                          AS phone_hash,
    client_ip_prefix                                 AS ip_prefix,
    client_user_agent                                AS user_agent,
    action_source                                    AS action_source,
    currency                                         AS currency,
    CAST(value AS DOUBLE)                            AS value_eur,
    content_ids                                      AS content_ids,
    consent_status                                   AS consent_status,
    'paid_social'                                    AS channel_key  -- Meta Pixel = paid_social by definition
FROM raw
