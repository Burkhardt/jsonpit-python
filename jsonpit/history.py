"""
Historical event stream and state projection fold.
Implements the CR003 / v3.13.2 deterministic history ordering and tombstone projection.
"""

from __future__ import annotations

import copy
import datetime
from collections.abc import Iterator, Sequence
from typing import Any

from .canonical import (
	canonical_json,
	datetime_to_utc_ticks,
	parse_iso_timestamp,
	utcnow,
)
from .item import PitItem


def fragment_sort_key(item: PitItem) -> tuple[int, int, str]:
	"""
	Deterministic fragment ordering key adhering to CR003 / v3.13.2:
	1. Primary: Modified descending (newest first).
	2. Equal timestamps: fragment with fewer JSON properties sorts first.
	3. Equal timestamp and property count: canonical JSON text tie-break.
	"""
	ticks = datetime_to_utc_ticks(item.modified)
	prop_count = len(item)
	canonical = canonical_json(item.to_dict())
	return (-ticks, prop_count, canonical)


def apply_projected_property(target: dict[str, Any], name: str, value: Any) -> bool:
	"""
	Recursively merges a property into the projection accumulator.
	Null values (None) act as tombstones and remove properties from the projection.
	Returns True if a tombstone was applied.
	"""
	if value is None:
		target.pop(name, None)
		return True

	if not isinstance(value, dict):
		target[name] = copy.deepcopy(value)
		return False

	existing = target.get(name)
	nested = copy.deepcopy(existing) if isinstance(existing, dict) else {}
	contains_tombstone = False

	for k, v in value.items():
		contains_tombstone |= apply_projected_property(nested, k, v)

	if nested:
		target[name] = nested
	elif contains_tombstone:
		target.pop(name, None)
	else:
		target[name] = nested

	return contains_tombstone


class PitItems(Sequence[PitItem]):
	"""
	Immutable history stack of PitItem fragments for a single key.
	Stack semantics: history[0] is the newest fragment, history[-1] the oldest.
	Push returns a new immutable PitItems instance.
	"""

	def __init__(
		self,
		key: str,
		history: Sequence[PitItem] | None = None,
		max_count: int = 10,
	) -> None:
		self._key = key
		self._max_count = max_count
		raw_items = list(history or [])
		if len(raw_items) > 1:
			raw_items.sort(key=fragment_sort_key)
		if max_count > 0 and len(raw_items) > max_count:
			raw_items = raw_items[:max_count]
		self._history: tuple[PitItem, ...] = tuple(raw_items)

	@property
	def key(self) -> str:
		return self._key

	@property
	def history(self) -> tuple[PitItem, ...]:
		return tuple(frag.clone() for frag in self._history)

	@property
	def max_count(self) -> int:
		return self._max_count

	@classmethod
	def create(cls, key: str, max_count: int = 10) -> PitItems:
		"""Creates an empty PitItems sequence for a key."""
		return cls(key=key, history=(), max_count=max_count)

	def push(self, item: PitItem) -> PitItems:
		"""
		Pushes a fragment onto the history using deterministic CR003 ordering.
		Replaying an exact fragment already present is idempotent and returns self unchanged.
		"""
		item_ticks = datetime_to_utc_ticks(item.modified)
		item_canonical = canonical_json(item.to_dict())

		# Replay idempotence check
		for existing in self._history:
			if (
				datetime_to_utc_ticks(existing.modified) == item_ticks
				and canonical_json(existing.to_dict()) == item_canonical
			):
				return self

		combined = list(self._history) + [item.clone()]
		combined.sort(key=fragment_sort_key)

		if self._max_count > 0 and len(combined) > self._max_count:
			combined = combined[: self._max_count]

		return PitItems(self._key, combined, self._max_count)

	def latest_fragment(self) -> PitItem | None:
		"""Returns the most recent fragment, or None if history is empty."""
		return self._history[0] if self._history else None

	def project_state(
		self,
		at: datetime.datetime | None = None,
		with_deleted: bool = False,
	) -> PitItem | None:
		"""
		Folds history into the living projected entity state.
		If at is provided, projects state as of that historical point in time.
		Omitted null properties (tombstones) are pruned; deleted entities return None
		(unless with_deleted=True).
		"""
		if not self._history:
			return None

		# Find starting index (first fragment <= at)
		start_idx = 0
		if at is not None:
			target_ticks = datetime_to_utc_ticks(at)
			found = False
			for idx, frag in enumerate(self._history):
				if datetime_to_utc_ticks(frag.modified) <= target_ticks:
					start_idx = idx
					found = True
					break
			if not found:
				return None

		newest = self._history[start_idx]
		if newest.deleted:
			if not with_deleted:
				return None
			return PitItem(
				{"Id": newest.id, "Modified": newest.modified, "Deleted": True},
				invalidate=False,
			)

		# Find oldest unbroken non-deleted fragment
		end_exclusive = start_idx
		while end_exclusive < len(self._history) and not self._history[end_exclusive].deleted:
			end_exclusive += 1

		accumulator: dict[str, Any] = {}
		# Fold forward from oldest to newest
		for idx in range(end_exclusive - 1, start_idx - 1, -1):
			frag_dict = self._history[idx].to_dict()
			for prop_name, prop_val in frag_dict.items():
				if prop_name in ("Id", "Modified", "Deleted", "Note"):
					continue
				apply_projected_property(accumulator, prop_name, prop_val)

		accumulator["Id"] = newest.id
		accumulator["Modified"] = newest.modified
		accumulator["Deleted"] = False
		if newest.note:
			accumulator["Note"] = newest.note

		return PitItem(accumulator, invalidate=False)

	# --- Sequence Interface ---

	def __getitem__(self, index: int) -> PitItem:  # type: ignore[override]
		return self._history[index].clone()

	def __len__(self) -> int:
		return len(self._history)

	def __iter__(self) -> Iterator[PitItem]:
		for frag in self._history:
			yield frag.clone()

	def __repr__(self) -> str:
		return f"<PitItems Key={self._key!r} Count={len(self._history)} MaxCount={self._max_count}>"
