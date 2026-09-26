"""
Collision-safe change files and receipt lifecycle protocol.
Adheres strictly to CR003 / CR021:
- Filename: {Modified.UtcTicks}_{ExactProcessIdentity}_{Sha256}.json
- Receipt: {Stem}.receipt (10-minute cleanup grace)
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from .canonical import (
	canonical_json,
	canonical_with_hash,
	datetime_to_utc_ticks,
	format_iso_timestamp,
	parse_iso_timestamp,
	sha256_hex,
	utc_ticks_to_datetime,
	utcnow,
)
from .fs import safe_delete_file, safe_read_text, safe_write_in_place
from .item import PitItem


class ChangeFile:
	"""
	Collision-safe change-file identity and validated payload access.
	Payload is [[fragment]] serialized as canonical UTF-8 JSON.
	"""

	@staticmethod
	def canonical_payload_for(fragment: PitItem) -> tuple[str, str]:
		"""Produces the canonical JSON payload [[fragment]] and its lowercase SHA-256."""
		payload = [[fragment.to_dict()]]
		return canonical_with_hash(payload)

	@staticmethod
	def compose_name(
		modified: datetime.datetime,
		exact_process_identity: str,
		sha256: str,
	) -> str:
		"""Composes the change-file stem: {UtcTicks}_{ExactProcessIdentity}_{Sha256}."""
		ticks = datetime_to_utc_ticks(modified)
		return f"{ticks}_{exact_process_identity}_{sha256}"

	@classmethod
	def compose_name_for(cls, fragment: PitItem, exact_process_identity: str) -> str:
		"""Composes the change-file stem directly from a PitItem fragment."""
		_, sha = cls.canonical_payload_for(fragment)
		return cls.compose_name(fragment.modified, exact_process_identity, sha)

	@staticmethod
	def try_parse_name(name_without_extension: str) -> tuple[int, str, str] | None:
		"""
		Parses a change-file name without extension.
		Returns (utc_ticks, exact_process_identity, sha256) or None if invalid.
		"""
		if not name_without_extension:
			return None
		first_sep = name_without_extension.find("_")
		last_sep = name_without_extension.rfind("_")
		if first_sep <= 0 or last_sep <= first_sep:
			return None

		ticks_str = name_without_extension[:first_sep]
		try:
			ticks = int(ticks_str)
		except ValueError:
			return None

		sha = name_without_extension[last_sep + 1 :]
		if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha.lower()):
			return None

		identity = name_without_extension[first_sep + 1 : last_sep]
		if not identity:
			return None

		return ticks, identity, sha.lower()

	@classmethod
	def identity_of(cls, name_without_extension: str) -> str | None:
		"""Extracts the process identity segment from a change file name."""
		parsed = cls.try_parse_name(name_without_extension)
		if parsed:
			return parsed[1]
		# Legacy format fallback: {ticks}_{identity}
		sep = name_without_extension.find("_")
		if sep > 0 and sep < len(name_without_extension) - 1:
			try:
				int(name_without_extension[:sep])
				return name_without_extension[sep + 1 :]
			except ValueError:
				pass
		return None

	@classmethod
	def read_validated(cls, file_path: Path) -> list[list[dict[str, Any]]] | None:
		"""
		Reads and validates a change file.
		Verifies the file content matches the embedded SHA-256 hash.
		Returns parsed JSON payload or None if invalid or corrupt.
		"""
		content = safe_read_text(file_path)
		if content is None or not content.strip():
			return None

		parsed_meta = cls.try_parse_name(file_path.stem)
		if parsed_meta:
			_, _, expected_sha = parsed_meta
			actual_sha = sha256_hex(content)
			if actual_sha != expected_sha:
				return None

		try:
			data = json.loads(content)
			if isinstance(data, list):
				return data
			return None
		except Exception:
			return None

	@classmethod
	def create(
		cls,
		pit_dir: Path,
		fragment: PitItem,
		exact_process_identity: str,
	) -> Path:
		"""
		Writes a fragment as an ordinary collision-safe change file in pit_dir.
		Filename: {Modified.UtcTicks}_{ExactProcessIdentity}_{Sha256}.json.
		Exact byte contract: canonical UTF-8 JSON without trailing newline.
		"""
		payload, sha = cls.canonical_payload_for(fragment)
		stem = cls.compose_name(fragment.modified, exact_process_identity, sha)
		target_path = pit_dir / f"{stem}.json"

		if not target_path.is_file():
			safe_write_in_place(target_path, payload)

		return target_path


class ReceiptFile:
	"""
	Immutable cleanup-eligibility receipt for one JsonPit change file (CR021).
	Stored beside the change file with the same stem and the .receipt extension.
	Content is the single round-trip ISO-8601 UTC timestamp of canonical accounting.
	"""

	CLEANUP_GRACE: datetime.timedelta = datetime.timedelta(minutes=10)

	def __init__(self, change_file_path: Path) -> None:
		self.change_file_path = change_file_path
		self.path = change_file_path.with_suffix(".receipt")

		if self.path.is_file():
			content = safe_read_text(self.path) or ""
			line = content.splitlines()[0] if content.splitlines() else ""
			try:
				self.time = parse_iso_timestamp(line)
			except Exception:
				self.time = utcnow()
		else:
			self.time = utcnow()
			safe_write_in_place(self.path, format_iso_timestamp(self.time))

	@property
	def is_eligible_for_cleanup(self) -> bool:
		"""True when the 10-minute grace period has passed since canonical accounting."""
		return (utcnow() - self.time) >= self.CLEANUP_GRACE

	def remove(self) -> bool:
		"""Removes this receipt file from disk."""
		return safe_delete_file(self.path)

	@classmethod
	def path_for(cls, change_file_path: Path) -> Path:
		"""Returns the path of the sibling receipt file."""
		return change_file_path.with_suffix(".receipt")
