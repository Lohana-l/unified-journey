"""
Test unitaire Python pur de la règle de pondération position-based.

La version SQL vit dans dbt/models/intermediate/int_touchpoints__attribution.sql
et est vérifiée par le test singulier
dbt/tests/assert_attribution_weights_sum_to_one.sql.

Ce test unitaire documente la règle en Python pour qu'un relecteur puisse
la comprendre sans démarrer dbt.
"""

from __future__ import annotations

import math

import pytest


def position_based_weights(n_touches: int) -> list[float]:
    """40/20/40 : un seul contact reçoit 100%, deux contacts reçoivent 50/50."""
    if n_touches <= 0:
        raise ValueError("n_touches must be positive")
    if n_touches == 1:
        return [1.0]
    if n_touches == 2:
        return [0.5, 0.5]
    middle = n_touches - 2
    w_middle = 0.2 / middle
    return [0.4, *([w_middle] * middle), 0.4]


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 10, 37])
def test_weights_sum_to_one(n: int) -> None:
    weights = position_based_weights(n)
    assert math.isclose(
        sum(weights), 1.0, abs_tol=1e-9
    ), f"weights for n={n} must sum to 1.0, got {sum(weights)}"


@pytest.mark.parametrize("n", [3, 4, 5, 10])
def test_first_and_last_are_40_pct(n: int) -> None:
    weights = position_based_weights(n)
    assert math.isclose(weights[0], 0.4, abs_tol=1e-9)
    assert math.isclose(weights[-1], 0.4, abs_tol=1e-9)


def test_invalid_zero_touches() -> None:
    with pytest.raises(ValueError):
        position_based_weights(0)
