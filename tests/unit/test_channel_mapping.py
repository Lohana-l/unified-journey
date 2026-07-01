"""
Test unitaire de la règle de mapping source+medium vers channel_key utilisée dans
stg_ga4__events.sql. Garantit que la règle est aussi documentée en Python.
"""

from __future__ import annotations

import pytest


def map_channel(source: str, medium: str, paid: bool) -> str:
    """Miroir de l'expression CASE dans stg_ga4__events.sql."""
    s, m = (source or "").lower(), (medium or "").lower()
    if s == "google" and m == "organic":
        return "organic_search"
    if s == "google" and m == "cpc":
        return "paid_search_google"
    if s == "bing" and m == "cpc":
        return "paid_search_bing"
    if s in ("facebook", "meta") and m in ("cpc", "paid_social"):
        return "paid_social_meta"
    if s == "newsletter" or m == "email":
        return "email"
    if m == "referral":
        return "referral"
    if s == "(direct)" and m == "(none)":
        return "direct"
    return "other_paid" if paid else "other_organic"


@pytest.mark.parametrize(
    "source,medium,paid,expected",
    [
        ("google", "organic", False, "organic_search"),
        ("google", "cpc", True, "paid_search_google"),
        ("bing", "cpc", True, "paid_search_bing"),
        ("facebook", "paid_social", True, "paid_social_meta"),
        ("meta", "cpc", True, "paid_social_meta"),
        ("newsletter", "email", False, "email"),
        ("nytimes", "referral", False, "referral"),
        ("(direct)", "(none)", False, "direct"),
        ("unknown", "display", True, "other_paid"),
        ("unknown", "display", False, "other_organic"),
    ],
)
def test_channel_mapping(source: str, medium: str, paid: bool, expected: str) -> None:
    assert map_channel(source, medium, paid) == expected
