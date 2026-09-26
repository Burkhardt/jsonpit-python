"""
Deterministic JSON canonicalization, content hashing, and time conversions.
Adheres strictly to the CR003 / v3.13.2 specification in OsLib.CanonicalJson.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import Any

# .NET ticks: 100-nanosecond intervals since 0001-01-01 00:00:00 UTC
TICKS_PER_MICROSECOND = 10
TICKS_PER_SECOND = 10_000_000
TICKS_AT_UNIX_EPOCH = 621_355_968_000_000_000
UNIX_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)


def utcnow() -> datetime.datetime:
	"""Returns the current UTC datetime with explicit UTC timezone."""
	return datetime.datetime.now(datetime.timezone.utc)


def datetime_to_utc_ticks(dt: datetime.datetime) -> int:
	"""
	Converts a UTC datetime to .NET DateTimeOffset.UtcTicks.
	1 tick = 100 nanoseconds since 0001-01-01 00:00:00 UTC.
	"""
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=datetime.timezone.utc)
	else:
		dt = dt.astimezone(datetime.timezone.utc)
	diff = dt - UNIX_EPOCH
	total_microseconds = diff.days * 86_400_000_000 + diff.seconds * 1_000_000 + diff.microseconds
	return TICKS_AT_UNIX_EPOCH + (total_microseconds * TICKS_PER_MICROSECOND)


def utc_ticks_to_datetime(ticks: int) -> datetime.datetime:
	"""Converts .NET UtcTicks back to a timezone-aware UTC datetime."""
	diff_ticks = ticks - TICKS_AT_UNIX_EPOCH
	diff_microseconds = diff_ticks // TICKS_PER_MICROSECOND
	return UNIX_EPOCH + datetime.timedelta(microseconds=diff_microseconds)


def format_iso_timestamp(dt: datetime.datetime) -> str:
	"""
	Formats a UTC datetime in standard round-trip ISO-8601 format:
	'yyyy-MM-ddTHH:mm:ss.ffffffZ' (or 'yyyy-MM-ddTHH:mm:ssZ' if zero microseconds).
	"""
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=datetime.timezone.utc)
	else:
		dt = dt.astimezone(datetime.timezone.utc)
	if dt.microsecond == 0:
		return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
	return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso_timestamp(ts: str) -> datetime.datetime:
	"""
	Parses an ISO-8601 timestamp string into a timezone-aware UTC datetime.
	Supports 'Z', '+00:00', negative offsets, and fractional seconds.
	"""
	clean_ts = ts.strip()
	if clean_ts.endswith("Z"):
		clean_ts = clean_ts[:-1] + "+00:00"
	dt = datetime.datetime.fromisoformat(clean_ts)
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=datetime.timezone.utc)
	return dt.astimezone(datetime.timezone.utc)


def canonical_json(obj: Any) -> str:
	"""
	Produces deterministic, compact JSON text without insignificant whitespace,
	with dictionary keys sorted in ordinal order, matching OsLib.CanonicalJson.
	"""
	return json.dumps(
		obj,
		sort_keys=True,
		separators=(",", ":"),
		ensure_ascii=False,
		default=_json_default_serializer,
	)


def _json_default_serializer(obj: Any) -> Any:
	"""Serializes datetime objects and domain items to canonical JSON primitives."""
	if isinstance(obj, datetime.datetime):
		return format_iso_timestamp(obj)
	if hasattr(obj, "to_dict"):
		return obj.to_dict()
	raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def sha256_hex(text: str) -> str:
	"""Returns the full lowercase hex SHA-256 digest of the UTF-8 encoding of text."""
	return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_with_hash(obj: Any) -> tuple[str, str]:
	"""Returns (canonical_json_string, sha256_hex_digest)."""
	canonical = canonical_json(obj)
	return canonical, sha256_hex(canonical)
