{{ config(materialized='table') }}

SELECT * FROM {{ ref('dim_channels_seed') }}
