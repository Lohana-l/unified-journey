{{ config(materialized='table') }}

{# Use dbt_utils.date_spine to produce every calendar day in the analysis window. #}

WITH date_spine AS (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="CAST('" ~ var('start_date') ~ "' AS DATE)",
        end_date  ="CAST('" ~ var('end_date')   ~ "' AS DATE)"
    ) }}
)

SELECT
    CAST(date_day AS DATE)                              AS date_day,
    EXTRACT(YEAR       FROM date_day)                   AS year,
    EXTRACT(MONTH      FROM date_day)                   AS month,
    EXTRACT(DAY        FROM date_day)                   AS day_of_month,
    EXTRACT(ISODOW     FROM date_day)                   AS day_of_week_iso,
    EXTRACT(WEEK       FROM date_day)                   AS iso_week,
    EXTRACT(QUARTER    FROM date_day)                   AS quarter,
    CASE WHEN EXTRACT(ISODOW FROM date_day) IN (6, 7) THEN TRUE ELSE FALSE END AS is_weekend
FROM date_spine
