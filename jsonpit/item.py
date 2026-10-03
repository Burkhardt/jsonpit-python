"""
Living entity instance and timestamped value protocol.
PitItem is a rich domain object implementing MutableMapping, property tombstones,
change tracking (dirty state), and audited deletion backdating.
"""

from __future__ import annotations

import contextlib
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


class ObservableDict(dict[str, Any]):
	"""
	Dictionary subclass that notifies a parent observer callback on mutation.
	Wraps nested dictionaries and lists recursively to enable deep live change tracking
	with 100% C# JObject / INotifyCollectionChanged parity.
	"""

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		super().__init__()
		self._observer: Any = None
		self.update(*args, **kwargs)

	def _set_observer(self, observer: Any) -> None:
		self._observer = observer
		for v in self.values():
			if isinstance(v, (ObservableDict, ObservableList)):
				v._set_observer(observer)

	def __setitem__(self, key: str, value: Any) -> None:
		wrapped = _wrap_observable(value, self._observer)
		super().__setitem__(key, wrapped)
		if self._observer is not None and key not in ("Modified", "Deleted"):
			self._observer()

	def __delitem__(self, key: str) -> None:
		super().__delitem__(key)
		if self._observer is not None:
			self._observer()

	def pop(self, key: str, *args: Any) -> Any:
		res = super().pop(key, *args)
		if self._observer is not None:
			self._observer()
		return res

	def clear(self) -> None:
		super().clear()
		if self._observer is not None:
			self._observer()

	def update(self, *args: Any, **kwargs: Any) -> None:
		other = dict(*args, **kwargs)
		for k, v in other.items():
			self[k] = v

	def __deepcopy__(self, memo: Any) -> ObservableDict:
		copied = ObservableDict()
		memo[id(self)] = copied
		for k, v in self.items():
			copied[copy.deepcopy(k, memo)] = copy.deepcopy(v, memo)
		return copied


class ObservableList(list[Any]):
	"""
	List subclass that notifies a parent observer callback on mutation.
	Wraps nested dictionaries and lists recursively to enable deep live change tracking
	with 100% C# JArray / INotifyCollectionChanged parity.
	"""

	def __init__(self, *args: Any) -> None:
		super().__init__()
		self._observer: Any = None
		if args:
			self.extend(args[0])

	def _set_observer(self, observer: Any) -> None:
		self._observer = observer
		for item in self:
			if isinstance(item, (ObservableDict, ObservableList)):
				item._set_observer(observer)

	def __setitem__(self, index: Any, value: Any) -> None:
		wrapped = _wrap_observable(value, self._observer)
		super().__setitem__(index, wrapped)
		if self._observer is not None:
			self._observer()

	def __delitem__(self, index: Any) -> None:
		super().__delitem__(index)
		if self._observer is not None:
			self._observer()

	def append(self, value: Any) -> None:
		wrapped = _wrap_observable(value, self._observer)
		super().append(wrapped)
		if self._observer is not None:
			self._observer()

	def extend(self, values: Any) -> None:
		wrapped = [_wrap_observable(v, self._observer) for v in values]
		super().extend(wrapped)
		if self._observer is not None:
			self._observer()

	def insert(self, index: int, value: Any) -> None:
		wrapped = _wrap_observable(value, self._observer)
		super().insert(index, wrapped)
		if self._observer is not None:
			self._observer()

	def pop(self, *args: Any) -> Any:
		res = super().pop(*args)
		if self._observer is not None:
			self._observer()
		return res

	def remove(self, value: Any) -> None:
		super().remove(value)
		if self._observer is not None:
			self._observer()

	def clear(self) -> None:
		super().clear()
		if self._observer is not None:
			self._observer()

	def __deepcopy__(self, memo: Any) -> ObservableList:
		copied = ObservableList()
		memo[id(self)] = copied
		for item in self:
			copied.append(copy.deepcopy(item, memo))
		return copied


def _clean_dict(val: Any) -> Any:
	"""Creates a pure python JSON-safe copy without attached observers."""
	if isinstance(val, dict):
		return {str(k): _clean_dict(v) for k, v in val.items()}
	elif isinstance(val, list):
		return [_clean_dict(x) for x in val]
	return copy.deepcopy(val)


def _wrap_observable(value: Any, observer: Any) -> Any:
	if isinstance(value, dict) and not isinstance(value, ObservableDict):
		obs = ObservableDict()
		for k, v in value.items():
			obs[k] = _wrap_observable(v, observer)
		obs._set_observer(observer)
		return obs
	elif isinstance(value, ObservableDict):
		value._set_observer(observer)
		return value
	elif isinstance(value, list) and not isinstance(value, ObservableList):
		obs_list = ObservableList()
		for v in value:
			obs_list.append(_wrap_observable(v, observer))
		obs_list._set_observer(observer)
		return obs_list
	elif isinstance(value, ObservableList):
		value._set_observer(observer)
		return value
	return value


def _reconcile_dict(target: dict[str, Any], source: dict[str, Any], observer: Any) -> None:
	"""Reconciles target dictionary from source in place, preserving object identities."""
	for k, v in source.items():
		curr = target.get(k)
		if isinstance(curr, dict) and isinstance(v, dict):
			_reconcile_dict(curr, v, observer)
		elif isinstance(curr, list) and isinstance(v, list):
			curr.clear()
			curr.extend([_wrap_observable(copy.deepcopy(x), observer) for x in v])
		else:
			target[k] = _wrap_observable(copy.deepcopy(v), observer)
	for k in list(target.keys()):
		if k not in source:
			del target[k]


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
		self._refreshing: bool = False
		self._bound_id: str | None = None
		self._client_supplied_lifecycle_attribute: str | None = None
		self._pit_ref: weakref.ref[Any] | None = weakref.ref(pit) if pit is not None else None

		if isinstance(initial, PitItem):
			self._data = _wrap_observable(copy.deepcopy(initial._data), self._on_mutation)
			self._dirty = initial._dirty
			self._bound_id = initial._bound_id or initial.id
			self._client_supplied_lifecycle_attribute = initial._client_supplied_lifecycle_attribute
			if pit is not None:
				self._pit_ref = weakref.ref(pit)
			if id is not None:
				self._data["Id"] = id
			if note:
				self._data["Note"] = note
			if modified is not None:
				self.modified = modified
			return

		if isinstance(initial, dict):
			if "Modified" in initial or "modified" in initial:
				self._client_supplied_lifecycle_attribute = (
					"Modified" if "Modified" in initial else "modified"
				)
			if "Deleted" in initial or "deleted" in initial:
				self._client_supplied_lifecycle_attribute = (
					"Deleted" if "Deleted" in initial else "deleted"
				)
			self._data = copy.deepcopy(initial)
		elif isinstance(initial, str):
			trimmed = initial.strip()
			if trimmed.startswith("{") and trimmed.endswith("}"):
				self._data = json.loads(trimmed)
				if "Modified" in self._data or "modified" in self._data:
					self._client_supplied_lifecycle_attribute = (
						"Modified" if "Modified" in self._data else "modified"
					)
				if "Deleted" in self._data or "deleted" in self._data:
					self._client_supplied_lifecycle_attribute = (
						"Deleted" if "Deleted" in self._data else "deleted"
					)
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

		self._data = _wrap_observable(self._data, self._on_mutation)
		self._dirty = bool(invalidate)

	@contextlib.contextmanager
	def suppress_notifications(self) -> Iterator[None]:
		"""Context manager to suppress live mutation notifications (simulating unnotified edits)."""
		prev = self._refreshing
		self._refreshing = True
		try:
			yield
		finally:
			self._refreshing = prev

	def _on_mutation(self) -> None:
		"""Dispatches live changes immediately to bound parent Pit container."""
		if self._refreshing:
			return
		self._dirty = True
		p = self.pit
		if p is not None and hasattr(p, "accept_live_changes"):
			p.accept_live_changes(self)

	def ensure_valid_for_live_add(self) -> None:
		"""Validates an entity at a live write boundary (CR040 / CR049)."""
		if not self.id or not self.id.strip():
			raise ValueError("Entity Id must be a non-empty string.")
		if not self.deleted and ("{" in self.id or "<" in self.id):
			raise ValueError(
				f"Entity Id '{self.id}' contains a prohibited template marker ('{{' or '<'). "
				"Resolve template placeholders before writing to a Pit."
			)
		if self._client_supplied_lifecycle_attribute:
			attr = self._client_supplied_lifecycle_attribute
			raise ProtectedAttributeError(
				f"Cannot manually set lifecycle attribute '{attr}' on live entity creation."
			)

	def bind(self, pit: Any) -> PitItem:
		"""Binds this living entity to its parent Pit container."""
		self._pit_ref = weakref.ref(pit) if pit is not None else None
		self._bound_id = self.id
		self._data = _wrap_observable(self._data, self._on_mutation)
		return self

	def _reconcile_from(self, source: PitItem | dict[str, Any]) -> None:
		"""Reconciles internal state from incoming source while preserving held object references."""
		self._refreshing = True
		try:
			src_dict = source.to_dict() if isinstance(source, PitItem) else source
			_reconcile_dict(self._data, src_dict, self._on_mutation)
			if "Modified" in src_dict:
				mod = src_dict["Modified"]
				self.modified = parse_iso_timestamp(mod) if isinstance(mod, str) else mod
			if "Deleted" in src_dict:
				self.deleted = bool(src_dict["Deleted"])
			if "Note" in src_dict:
				self.note = str(src_dict["Note"])
		finally:
			self._refreshing = False

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

	def invalidate(self, modified: datetime.datetime | None = None) -> None:
		"""Marks this item as dirty and refreshes its Modified timestamp."""
		self._dirty = True
		self.modified = modified if modified is not None else utcnow()

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
		if property_name.lower() in ("id", "modified", "deleted"):
			raise ProtectedAttributeError(f"Cannot tombstone protected attribute '{property_name}'.")
		self.deleted = False
		self._data[property_name] = None
		if self.pit is None:
			self.invalidate()
		else:
			self._on_mutation()

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
				created: dict[str, Any] = ObservableDict()
				created._set_observer(self._on_mutation)
				container[seg] = created
				container = created
			else:
				raise TombstoneError(
					f"Property path '{property_path}' cannot traverse non-object property '{seg}'."
				)

		container[segments[-1]] = None
		self.deleted = False
		if self.pit is None:
			self.invalidate()
		else:
			self._on_mutation()

	def delete(self, by: str | None = None, backdate_100: bool = True) -> bool:
		"""
		Tombstones this item. Appends an audit trail to Note.
		If backdate_100 is True, preserves precedence by backdating Modified by 100 seconds.
		If bound to a Pit, dispatches the tombstone to the Pit.
		Returns True if newly deleted, False if already deleted.
		"""
		if self.deleted:
			return False

		p = self.pit
		if p is not None:
			return p.delete_item(self.id, by=by, backdate_100=backdate_100)

		self._refreshing = True
		try:
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
		finally:
			self._refreshing = False
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
			if self.pit is None:
				self.invalidate()
		return changed

	def extend_with(self, obj: dict[str, Any]) -> bool:
		"""
		Deep merges a dictionary into this entity.
		Arrays are replaced; objects are recursively merged; nulls (tombstones) are preserved.
		If bound to a Pit, automatically dispatches a single sparse delta fragment.
		Returns True if any value was modified.
		"""
		for k in obj:
			if k.lower() in ("id", "modified", "deleted"):
				raise ProtectedAttributeError(f"Cannot manually mutate protected attribute '{k}'.")
		self._refreshing = True
		try:
			changed = self._apply_extend(obj)
		finally:
			self._refreshing = False

		if changed:
			self._data = _wrap_observable(self._data, self._on_mutation)
			if self.pit is not None:
				self._on_mutation()
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
		result = _clean_dict(self._data)
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
		if key.lower() == "id":
			raise ProtectedAttributeError("Cannot mutate Id property directly. Use Pit.rename_id().")
		elif key.lower() in ("modified", "deleted"):
			raise ProtectedAttributeError(f"Cannot manually mutate protected attribute '{key}'.")
		elif key == "Note":
			self.note = str(value)
		else:
			self._data[key] = _wrap_observable(value, self._on_mutation)
			if self.pit is None:
				self.invalidate()
			else:
				self._on_mutation()

	def __delitem__(self, key: str) -> None:
		if key.lower() in ("id", "modified", "deleted"):
			raise ProtectedAttributeError(f"Cannot delete protected attribute '{key}'.")
		if key in self._data:
			del self._data[key]
		if self.pit is None:
			self.invalidate()
		else:
			self._on_mutation()

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
