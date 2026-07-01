/*
    Invariant: for every (conversion_id, attribution_model) the sum of touch
    weights must equal 1.0 (±0.001 for floating-point slack).

    If this test fails, at least one attribution model is redistributing
    revenue incorrectly, which would silently bias every downstream marketing
    decision.

    This is the single most important business rule of the project and lives
    here (not in schema tests) because it spans rows within a group.
*/

SELECT
    conversion_id,
    attribution_model,
    SUM(weight) AS total_weight
FROM {{ ref('int_touchpoints__attribution') }}
GROUP BY conversion_id, attribution_model
HAVING ABS(SUM(weight) - 1.0) > 0.001
