{{ config(materialized='view') }}

SELECT
    event_id                                          AS event_id,
    event_name                                        AS event_name,
    CAST(event_ts AS TIMESTAMP)                       AS event_ts,
    campaign_id                                       AS campaign_id,
    subscriber_id                                     AS subscriber_id,
    email_hash                                        AS email_hash,
    url                                               AS click_url,
    consent_status                                    AS consent_status,
    'email'                                           AS channel_key
FROM {{ source('raw_email', 'events') }}
WHERE consent_status != 'withdrawn'
