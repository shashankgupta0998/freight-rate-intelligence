"""Unit tests for tools/validator.py — site checks + red-flag merging."""
from __future__ import annotations

from tools.validator import (
    is_flagged_site,
    is_verified_site,
    red_flags_for_mode,
)


def test_is_verified_site_exact_domain(reset_validator_cache):
    assert is_verified_site("https://freightos.com/x") is True


def test_is_verified_site_subdomain(reset_validator_cache):
    assert is_verified_site("https://ship.freightos.com/x") is True


def test_is_verified_site_www_stripped(reset_validator_cache):
    assert is_verified_site("https://www.freightos.com/x") is True


def test_is_verified_site_unknown_domain(reset_validator_cache):
    assert is_verified_site("https://scammer.example.com/") is False


def test_is_verified_site_empty_url(reset_validator_cache):
    assert is_verified_site("") is False


def test_is_verified_site_malformed_url(reset_validator_cache):
    # urlparse handles most weird input by returning an empty hostname.
    assert is_verified_site("not a url") is False


def test_is_flagged_site_empty_flagged_list(reset_validator_cache):
    # Default Phase-1 patterns have flagged_sites == []
    assert is_flagged_site("https://any-domain.example.com/") is False


def test_red_flags_for_mode_merges_generic_and_specific(reset_validator_cache):
    air = red_flags_for_mode("air_freight")
    sea = red_flags_for_mode("sea_freight")
    # 8 generic + 2 mode-specific = 10 each
    assert len(air) == 10
    assert len(sea) == 10
    assert any("security / ISPS" in f for f in air)
    assert any("chassis fee" in f for f in sea)
