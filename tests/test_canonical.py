"""
Tests for canonical JSON serialization, SHA-256 hashing, and UtcTicks conversions.
"""

from __future__ import annotations

import datetime

from jsonpit.canonical import (
	canonical_json,
	canonical_with_hash,
	datetime_to_utc_ticks,
	format_iso_timestamp,
	parse_iso_timestamp,
	sha256_hex,
	utc_ticks_to_datetime,
	utcnow,
)


def test_canonical_json_sorts_keys_ordinally() -> None:
	payload = {"z": 1, "a": 2, "m": {"b": "nested", "a": 10}}
	serialized = canonical_json(payload)
	assert serialized == '{"a":2,"m":{"a":10,"b":"nested"},"z":1}'


def test_canonical_json_preserves_array_order() -> None:
	payload = {"items": [3, 1, 2, "b", "a"]}
	serialized = canonical_json(payload)
	assert serialized == '{"items":[3,1,2,"b","a"]}'


def test_sha256_hex_matches_known_digest() -> None:
	text = '{"a":1}'
	expected_sha = "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"
	assert sha256_hex(text) == expected_sha


def test_canonical_with_hash() -> None:
	payload = {"test": True}
	text, digest = canonical_with_hash(payload)
	assert text == '{"test":true}'
	assert digest == sha256_hex(text)


def test_utc_ticks_round_trip() -> None:
	now = utcnow()
	ticks = datetime_to_utc_ticks(now)
	restored = utc_ticks_to_datetime(ticks)
	diff_microseconds = abs((now - restored).total_seconds() * 1_000_000)
	assert diff_microseconds < 2.0


def test_iso_timestamp_round_trip() -> None:
	now = datetime.datetime(2026, 9, 26, 14, 30, 0, 123456, tzinfo=datetime.timezone.utc)
	formatted = format_iso_timestamp(now)
	parsed = parse_iso_timestamp(formatted)
	assert now == parsed
