"""
Living entity instance and timestamped value protocol.
PitItem is a rich domain object implementing MutableMapping, property tombstones,
change tracking (dirty state), and audited deletion backdating.
"""

from __future__ import annotations

import copy
import datetime
import json
from collections.abc import Iterator, MutableMapping
from typing import Any
import weakref

from .canonical import (
	canonical_json,
	datetime_to_utc_ticks,
	format_iso_timestamp,
	parse_iso_timestamp,
	utcnow,
)
from .exceptions import ProtectedAttributeError, TombstoneError


class TimestampedValue:
	"""
	Value with an attached timestamp and round-trip string format.
	Persisted as "value|timestamp" where timestamp uses ISO 8601 round-trip format.
	"""

	def __init__(
		self,
		value_or_string: Any = "",
		time: datetime.datetime | None = None,
	) -> None:
		if time is not None:
			self.value: str = "" if value_or_string is None else str(value_or_string)
			if time.tzinfo is None:
				self.time: datetime.datetime = time.replace(tzinfo=datetime.timezone.utc)
			else:
				self.time = time.astimezone(datetime.timezone.utc)
		else:
			# Single argument string: either "value|timestamp" or raw value
			raw = "" if value_or_string is None else str(value_or_string)
			if "|" in raw:
				parts = raw.split("|", 1)
				self.value = parts[0]
				if parts[1].strip():
					try:
						self.time = parse_iso_timestamp(parts[1])
					except Exception:
						self.time = utcnow()
				else:
					self.time = utcnow()
			else:
				if raw.strip():
					try:
						self.time = parse_iso_timestamp(raw.strip())
						self.value = ""
					except Exception:
						self.value = raw
						self.time = utcnow()
				else:
					self.value = raw
					self.time = utcnow()

	def __str__(self) -> str:
		return f"{self.value}|{format_iso_timestamp(self.time)}"

	def __repr__(self) -> str:
		return f"TimestampedValue({self.value!r}, {self.time.isoformat()!r})"

	def __eq__(self, other: object) -> bool:
		if not isinstance(other, TimestampedValue):
			return False
		return self.value == other.value and self.time == other.time


class PitItem(MutableMapping[str, Any]):
	"""
	JSON-backed living domain entity with metadata and change tracking.
	Extends MutableMapping for native dictionary access while encapsulating
	property tombstone protocols, dirty tracking, and deep merging.
	"""

	def __init__(
		self,
		initial: dict[str, Any] | PitItem | str | None = None,
		*,
		id: str | None = None,
		note: str = "",
		deleted: bool = False,
		modified: datetime.datetime | None = None,
		invalidate: bool = True,
		pit: Any | None = None,
	) -> None:
		self._data: dict[str, Any] = {}
		self._dirty: bool = False
		self._pit_ref: weakref.ref[Any] | None = weakref.ref(pit) if pit is not None else None

		if isinstance(initial, PitItem):
			self._data = copy.deepcopy(initial._data)
			self._dirty = initial._dirty
			if pit is not None:
				self._pit_ref = weakref.ref(pit)
			if id is not None:
				self._data["Id"] = id
			if note:
				self._data["Note"] = note
			if modified is not None:
				self.modified = modified
			if invalidate:
				self.invalidate()
			return

		if isinstance(initial, dict):
			self._data = copy.deepcopy(initial)
		elif isinstance(initial, str):
			trimmed = initial.strip()
			if trimmed.startswith("{") and trimmed.endswith("}"):
				self._data = json.loads(trimmed)
			else:
				self._data["Id"] = initial
		elif initial is not None:
			self._data["Id"] = str(initial)

		# Explicit overrides
		if id is not None:
			self._data["Id"] = id
		elif "Id" not in self._data and "id" in self._data:
			self._data["Id"] = self._data.pop("id")
		elif "Id" not in self._data and "Name" in self._data and isinstance(self._data["Name"], str):
			self._data["Id"] = self._data["Name"]

		if "Id" not in self._data:
			self._data["Id"] = ""

		if note:
			self._data["Note"] = note
		elif "Note" not in self._data and "note" in self._data:
			self._data["Note"] = self._data.pop("note")

		if "Deleted" in self._data:
			self._data["Deleted"] = bool(self._data["Deleted"])
		elif "deleted" in self._data:
			self._data["Deleted"] = bool(self._data.pop("deleted"))
		else:
			self._data["Deleted"] = deleted

		if modified is not None:
			self.modified = modified
		elif "Modified" in self._data:
			raw_mod = self._data["Modified"]
			if isinstance(raw_mod, str):
				self.modified = parse_iso_timestamp(raw_mod)
			elif isinstance(raw_mod, datetime.datetime):
				self.modified = raw_mod
			else:
				self.modified = utcnow()
		else:
			self.modified = utcnow()

		if invalidate:
			self.invalidate()
		else:
			self.validate()

	def bind(self, pit: Any) -> PitItem:
		"""Binds this living entity to its parent Pit container."""
		self._pit_ref = weakref.ref(pit) if pit is not None else None
		return self

	@property
	def pit(self) -> Any | None:
		"""Returns the parent Pit if bound and alive, else None."""
		return self._pit_ref() if self._pit_ref is not None else None

	# --- Property Accessors ---

	@property
	def id(self) -> str:
		return str(self._data.get("Id", ""))

	@id.setter
	def id(self, value: str) -> None:
		self._data["Id"] = str(value)
		self.invalidate()

	@property
	def modified(self) -> datetime.datetime:
		val = self._data.get("Modified")
		if isinstance(val, datetime.datetime):
			return val
		if isinstance(val, str):
			try:
				dt = parse_iso_timestamp(val)
				self._data["Modified"] = dt
				return dt
			except Exception:
				pass
		now = utcnow()
		self._data["Modified"] = now
		return now

	@modified.setter
	def modified(self, value: datetime.datetime) -> None:
		if value.tzinfo is None:
			self._data["Modified"] = value.replace(tzinfo=datetime.timezone.utc)
		else:
			self._data["Modified"] = value.astimezone(datetime.timezone.utc)

	@property
	def deleted(self) -> bool:
		return bool(self._data.get("Deleted", False))

	@deleted.setter
	def deleted(self, value: bool) -> None:
		self._data["Deleted"] = bool(value)

	@property
	def note(self) -> str:
		return str(self._data.get("Note", ""))

	@note.setter
	def note(self, value: str) -> None:
		self._data["Note"] = str(value)

	# --- Dirty Tracking ---

	def is_valid(self) -> bool:
		"""Returns True if the item is clean (unmodified since last validation)."""
		return not self._dirty

	def validate(self) -> None:
		"""Marks this item as clean."""
		self._dirty = False

	def invalidate(self) -> None:
		"""Marks this item as dirty and refreshes its Modified timestamp to UtcNow."""
		self._dirty = True
		self.modified = utcnow()

	# --- Domain Mutation & Tombstone Protocol ---

	def set_property(self, patch: dict[str, Any] | str) -> bool:
		"""
		Sets or merges properties from a dictionary or JSON string.
		Automatically resets Deleted to False and marks the entity dirty.
		CR040: Rejects any attempt to manually update protected lifecycle attributes.
		"""
		if isinstance(patch, str):
			parsed = json.loads(patch)
			if not isinstance(parsed, dict):
				raise ValueError("set_property patch string must parse to a JSON object")
			patch_dict = parsed
		elif isinstance(patch, dict):
			patch_dict = patch
		else:
			raise ValueError("set_property patch must be a dictionary or JSON string")

		for k in patch_dict:
			if k.lower() in ("modified", "deleted"):
				raise ProtectedAttributeError(
					f"Cannot manually update protected attribute '{k}'. "
					"Use sparse properties only, and use delete() to tombstone."
				)

		return self.extend_with(patch_dict)

	@staticmethod
	def validate_client_payload(payload: dict[str, Any]) -> None:
		"""
		Validates a client entity payload before live ingestion.
		CR040: Lifecycle attributes (Modified, Deleted) are reserved for historical replay.
		CR049: Prohibit template markers '{' or '<' in entity ID.
		"""
		if not isinstance(payload, dict):
			raise ValueError("Client payload must evaluate to a dictionary.")
		if "Id" in payload:
			val = str(payload["Id"])
			if "{" in val or "<" in val:
				raise ValueError(
					f"Entity Id '{val}' contains a prohibited template marker ('{{' or '<'). "
					"Resolve template placeholders before writing to a Pit."
				)
		for k in payload:
			if k.lower() in ("modified", "deleted"):
				raise ProtectedAttributeError(
					f"Cannot manually update protected attribute '{k}'. "
					"Use 'jpit del' to delete an entity."
				)

	def delete_property(self, property_name: str) -> None:
		"""
		Appends a property tombstone by setting the top-level property to None (JSON null).
		Resets Deleted to False and marks the entity dirty.
		If bound to a Pit, automatically dispatches a sparse tombstone delta.
		"""
		self.deleted = False
		self.invalidate()
		self._data[property_name] = None
		p = self.pit
		if p is not None:
			mutation = PitItem(id=self.id)
			mutation.delete_property(property_name)
			p.add(mutation)

	def delete_property_path(self, property_path: str) -> None:
		"""
		Appends a property tombstone at a dot-delimited nested JSON path (e.g. 'Address.City').
		Sets the leaf property to None (JSON null), resets Deleted to False, and marks dirty.
		If bound to a Pit, automatically dispatches a sparse tombstone delta.
		"""
		if not property_path or not property_path.strip():
			raise TombstoneError("A property path is required.")

		segments = [seg.strip() for seg in property_path.split(".")]
		if any(not seg for seg in segments):
			raise TombstoneError(
				f"Property path '{property_path}' must contain non-empty dot-delimited property names."
			)

		if len(segments) == 1:
			self.delete_property(segments[0])
			return

		container = self._data
		for seg in segments[:-1]:
			val = container.get(seg)
			if isinstance(val, dict):
				container = val
			elif val is None or seg not in container:
				created: dict[str, Any] = {}
				container[seg] = created
				container = created
			else:
				raise TombstoneError(
					f"Property path '{property_path}' cannot traverse non-object property '{seg}'."
				)

		container[segments[-1]] = None
		self.deleted = False
		self.invalidate()
		p = self.pit
		if p is not None:
			mutation = PitItem(id=self.id)
			mutation.delete_property_path(property_path)
			p.add(mutation)

	def delete(self, by: str | None = None, backdate_100: bool = True) -> bool:
		"""
		Tombstones this item. Appends an audit trail to Note.
		If backdate_100 is True, preserves precedence by backdating Modified by 100 seconds.
		If bound to a Pit, dispatches the tombstone to the Pit.
		Returns True if newly deleted, False if already deleted.
		"""
		if self.deleted:
			return False

		self.deleted = True
		self._dirty = True
		if backdate_100:
			self.modified = utcnow() - datetime.timedelta(seconds=100)
		else:
			self.modified = utcnow()

		audit_entry = f"[{format_iso_timestamp(self.modified)}] deleted"
		if by:
			audit_entry += f" by {by}"
		self.note = f"{audit_entry};\n{self.note}" if self.note else f"{audit_entry};"
		p = self.pit
		if p is not None:
			p.delete_item(self.id, by=by, backdate_100=backdate_100)
		return True

	def _apply_extend(self, obj: dict[str, Any]) -> bool:
		"""In-memory deep merge without dispatching to parent Pit."""
		original_canonical = canonical_json(self.to_dict())

		def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
			for key, val in source.items():
				if isinstance(val, dict) and isinstance(target.get(key), dict):
					_deep_merge(target[key], val)
				else:
					target[key] = copy.deepcopy(val)

		_deep_merge(self._data, obj)
		changed = canonical_json(self.to_dict()) != original_canonical
		if changed:
			self.deleted = False
			self.invalidate()
		return changed

	def extend_with(self, obj: dict[str, Any]) -> bool:
		"""
		Deep merges a dictionary into this entity.
		Arrays are replaced; objects are recursively merged; nulls (tombstones) are preserved.
		If bound to a Pit, automatically dispatches a sparse delta fragment.
		Returns True if any value was modified.
		"""
		changed = self._apply_extend(obj)
		p = self.pit
		if changed and p is not None:
			delta = copy.deepcopy(obj)
			delta["Id"] = self.id
			p.add(PitItem(delta))
		return changed

	def extend(self, json_string: str) -> bool:
		"""Parses JSON text and merges it into this entity."""
		parsed = json.loads(json_string)
		if isinstance(parsed, dict):
			return self.extend_with(parsed)
		if isinstance(parsed, list):
			changed = False
			for el in parsed:
				if isinstance(el, dict):
					changed = self.extend_with(el) or changed
			return changed
		return False

	def clone(self) -> PitItem:
		"""Returns an independent deep clone of this PitItem."""
		return PitItem(self, invalidate=False)

	def to_dict(self) -> dict[str, Any]:
		"""Returns a clean JSON-serializable dictionary representation."""
		result = copy.deepcopy(self._data)
		result["Id"] = self.id
		result["Modified"] = format_iso_timestamp(self.modified)
		result["Deleted"] = self.deleted
		if self.note:
			result["Note"] = self.note
		elif "Note" in result and not result["Note"]:
			del result["Note"]
		return result

	def to_json(self, indent: int | None = None) -> str:
		"""Serializes this item to JSON string."""
		if indent is None:
			return canonical_json(self.to_dict())
		return json.dumps(
			self.to_dict(),
			indent=indent,
			sort_keys=True,
			ensure_ascii=False,
			default=lambda o: format_iso_timestamp(o) if isinstance(o, datetime.datetime) else str(o),
		)

	# --- MutableMapping Interface ---

	def __getitem__(self, key: str) -> Any:
		if key == "Id":
			return self.id
		if key == "Modified":
			return self.modified
		if key == "Deleted":
			return self.deleted
		if key == "Note":
			return self.note
		return self._data[key]

	def __setitem__(self, key: str, value: Any) -> None:
		if key == "Id":
			self.id = str(value)
		elif key == "Modified":
			if isinstance(value, datetime.datetime):
				self.modified = value
			else:
				self.modified = parse_iso_timestamp(str(value))
		elif key == "Deleted":
			self.deleted = bool(value)
		elif key == "Note":
			self.note = str(value)
		else:
			self._data[key] = value
			self.invalidate()
			p = self.pit
			if p is not None:
				p.add(PitItem({"Id": self.id, key: value}))

	def __delitem__(self, key: str) -> None:
		if key in self._data:
			del self._data[key]
		self.invalidate()
		p = self.pit
		if p is not None:
			mutation = PitItem(id=self.id)
			mutation.delete_property(key)
			p.add(mutation)

	def __iter__(self) -> Iterator[str]:
		# Ensure Id, Modified, Deleted are always visible in key enumeration
		keys = set(self._data.keys()) | {"Id", "Modified", "Deleted"}
		for k in sorted(keys):
			yield k

	def __len__(self) -> int:
		return len(set(self._data.keys()) | {"Id", "Modified", "Deleted"})

	# --- Equality & String Representation ---

	def __eq__(self, other: object) -> bool:
		if not isinstance(other, PitItem):
			return False
		if self.id != other.id:
			return False
		if datetime_to_utc_ticks(self.modified) != datetime_to_utc_ticks(other.modified):
			return False
		return canonical_json(self.to_dict()) == canonical_json(other.to_dict())

	def __hash__(self) -> int:
		return hash((self.id, datetime_to_utc_ticks(self.modified)))

	def __repr__(self) -> str:
		status = " [DELETED]" if self.deleted else ""
		return f"<PitItem Id={self.id!r} Modified={format_iso_timestamp(self.modified)}{status}>"

	def __str__(self) -> str:
		return self.to_json()
