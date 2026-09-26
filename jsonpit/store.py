"""
Aggregate Root and storage engine for JsonPit.
Encapsulates directory ecosystems, context manager transactions, distributed lease
coordination, change-file streaming, receipt-based cleanup, and Mapping protocols.
"""

from __future__ import annotations

import copy
import datetime
import json
import os
from pathlib import Path
import threading
from typing import Any, ClassVar, Iterator, MutableMapping
import weakref

from .canonical import (
	canonical_json,
	format_iso_timestamp,
	parse_iso_timestamp,
	utcnow,
)
from .changes import ChangeFile, ReceiptFile
from .config import OsConfig, loads_json5
from .exceptions import (
	PitConcurrencyError,
	PitCorruptError,
	PitInstanceConflictError,
	PitNotFoundError,
)
from .flags import (
	MasterFlagFile,
	ProcessFlagFile,
	current_flag_name,
	flag_name,
	get_machine_name,
	is_exact_process_identity,
	participant_of,
)
from .fs import (
	ensure_directory,
	resolve_pit_target,
	safe_delete_file,
	safe_read_text,
	safe_write_in_place,
)
from .history import PitItems
from .item import PitItem


class JsonPitBase:
	"""
	Common base for pit storage with leasing, identity, and persistence coordination.
	"""

	def __init__(
		self,
		pit_dir: Path,
		pit_name: str,
		subscriber: str | None = None,
		read_only: bool = False,
		backup: bool = False,
		unflagged: bool = False,
	) -> None:
		self.pit_dir = ensure_directory(pit_dir)
		self.pit_name = pit_name
		self.canonical_file = self.pit_dir / f"{pit_name}.pit"
		self.subscriber = subscriber
		self.read_only = read_only
		self.backup = backup
		self.unflagged = unflagged

		self._master_flag = MasterFlagFile(self.pit_dir, "Master")
		self._process_flag: ProcessFlagFile | None = None
		self._locker = threading.RLock()

	@property
	def participant_identity(self) -> str:
		"""Stable participant identity: '{MachineName}-{Subscriber}'."""
		return flag_name(self.subscriber)

	@property
	def exact_process_identity(self) -> str:
		"""Exact PID-specific identity: '{MachineName}-{Subscriber}-{PID}'."""
		return current_flag_name(self.subscriber)

	@property
	def master_flag(self) -> MasterFlagFile:
		return self._master_flag

	@property
	def process_flag(self) -> ProcessFlagFile:
		if self._process_flag is None:
			self._process_flag = ProcessFlagFile(self.pit_dir, self.subscriber)
			if not self._process_flag.path.is_file():
				self._process_flag.update()
		return self._process_flag

	def running_on_master(self) -> bool:
		"""Quick check: is this exact process currently recorded as the master owner?"""
		if self.unflagged:
			return True
		return self.master_flag.originator == self.exact_process_identity

	def try_acquire_master(self) -> bool:
		"""
		Attempts to acquire or renew master lease rights under CR003 exact-process ownership.
		"""
		if self.unflagged:
			return True

		with self._locker:
			master = self.master_flag
			# 1. Fast path: this exact process already owns a valid lease — renew it
			if master.is_owned_by(self.exact_process_identity):
				master.try_claim(self.exact_process_identity)
				return True

			if not master.is_expired:
				recorded_owner = master.originator
				owner_participant = participant_of(recorded_owner)
				if owner_participant == self.participant_identity:
					# Same participant, check if recorded owner PID is still alive
					if is_exact_process_identity(recorded_owner) and ProcessFlagFile.is_process_window_active(
						self.pit_dir, recorded_owner
					):
						return False  # Existing PID is still active
					# Window released or expired -> inherit!
					master.update(originator=self.exact_process_identity)
					return True
				# A different participant holds a valid lease
				return False

			# Ticket is expired — verify no other foreign process was recently active
			if self._any_foreign_process_active():
				return False

			return master.try_claim(self.exact_process_identity)

	def _any_foreign_process_active(self) -> bool:
		"""Checks if another machine wrote a flag file within TICKET_DURATION."""
		if not self.pit_dir.is_dir():
			return False
		now = utcnow()
		my_flag_name = current_flag_name(self.subscriber)
		machine = get_machine_name().lower()

		for p in self.pit_dir.glob("*.flag"):
			if p.stem.lower() == "master":
				continue
			if p.stem.lower() == my_flag_name.lower():
				continue
			# Check machine prefix
			sep = p.stem.find("-")
			if sep > 0 and p.stem[:sep].lower() == machine:
				continue
			# Foreign process flag
			content = safe_read_text(p)
			if not content:
				continue
			line = content.splitlines()[0] if content.splitlines() else ""
			if "|" in line:
				try:
					stamp = parse_iso_timestamp(line.split("|", 1)[1])
					if (now - stamp) <= MasterFlagFile.TICKET_DURATION:
						return True
				except Exception:
					pass
		return False

	def try_release_process_window(self) -> bool:
		"""Releases this process's activity flag on disk."""
		if self.unflagged or self._process_flag is None:
			return False
		return self._process_flag.try_release_current_process()


class Pit(JsonPitBase, MutableMapping[str, PitItem]):
	"""
	Domain Aggregate Root for a Pit directory ecosystem.
	Encapsulates entity lifecycles, dirty state tracking, and cloud transactions.
	"""

	_live_instances: ClassVar[dict[str, weakref.ref[Pit]]] = {}
	_registry_lock: ClassVar[threading.Lock] = threading.Lock()

	def __init__(
		self,
		pit_dir: Path,
		pit_name: str,
		subscriber: str | None = None,
		read_only: bool = False,
		backup: bool = False,
		unflagged: bool = False,
		default_max_count: int = 10,
	) -> None:
		super().__init__(
			pit_dir=pit_dir,
			pit_name=pit_name,
			subscriber=subscriber,
			read_only=read_only,
			backup=backup,
			unflagged=unflagged,
		)
		self.default_max_count = default_max_count
		self._historic_items: dict[str, PitItems] = {}
		self._disposed = False
		self._owned_canonical_path: str | None = None

		self._register_path_ownership()

	# --- Path Ownership Registry (CR003 §4) ---

	def _register_path_ownership(self) -> None:
		canonical_key = str(self.canonical_file.resolve())
		with self._registry_lock:
			if canonical_key in self._live_instances:
				existing_ref = self._live_instances[canonical_key]
				existing = existing_ref()
				if existing is not None and not existing._disposed:
					raise PitInstanceConflictError(
						f"A live Pit instance is already active for '{canonical_key}'."
					)
			self._live_instances[canonical_key] = weakref.ref(self)
			self._owned_canonical_path = canonical_key

	def _release_path_ownership(self) -> None:
		if self._owned_canonical_path is None:
			return
		with self._registry_lock:
			existing_ref = self._live_instances.get(self._owned_canonical_path)
			if existing_ref is not None:
				existing = existing_ref()
				if existing is None or existing is self:
					self._live_instances.pop(self._owned_canonical_path, None)
		self._owned_canonical_path = None

	# --- Context Manager Protocol ---

	def __enter__(self) -> Pit:
		if not self.unflagged and not self.read_only:
			self.process_flag.update()
		self.load()
		self.merge_changes()
		return self

	def __exit__(
		self,
		exc_type: type[BaseException] | None,
		exc_val: BaseException | None,
		exc_tb: Any,
	) -> None:
		try:
			if exc_type is None and not self.read_only:
				if self.has_dirty_items():
					self.save()
		finally:
			self.close()

	def close(self) -> None:
		"""Explicitly releases process activity flags and path ownership."""
		if self._disposed:
			return
		try:
			self.try_release_process_window()
		finally:
			self._release_path_ownership()
			self._disposed = True

	# --- Factory ---

	@classmethod
	def open(
		cls,
		name_or_path: str | Path,
		cloud: str | None = "OneDrive",
		root: str | None = None,
		subscriber: str | None = None,
		read_only: bool = False,
		backup: bool = False,
		unflagged: bool = False,
		default_max_count: int = 10,
	) -> Pit:
		"""
		Opens a Pit directory using the Cloud-First Triad or explicit local path.

		Examples:
		    with Pit.open("Person", cloud="OneDrive", root="AfricaStage") as pit:
		        ...
		    with Pit.open("/path/to/my/Person") as pit:
		        ...
		"""
		pit_dir, pit_name = resolve_pit_target(name_or_path, cloud=cloud, root=root)
		return cls(
			pit_dir=pit_dir,
			pit_name=pit_name,
			subscriber=subscriber,
			read_only=read_only,
			backup=backup,
			unflagged=unflagged,
			default_max_count=default_max_count,
		)

	# --- State Loading & Ingestion ---

	def load(self, undercover: bool = False) -> bool:
		"""
		Loads the canonical .pit snapshot into memory.
		Snapshot format: array of history arrays: [[{fragment}, ...], [{fragment}], ...].
		"""
		if not self.canonical_file.is_file():
			return False

		content = safe_read_text(self.canonical_file)
		if not content or not content.strip():
			return False

		try:
			data = json.loads(content)
			if not isinstance(data, list):
				raise PitCorruptError(f"Pit snapshot in {self.canonical_file} must be a JSON array.")

			with self._locker:
				for history_entry in data:
					if not isinstance(history_entry, list):
						continue
					fragments: list[PitItem] = []
					key: str | None = None
					for raw_frag in history_entry:
						if isinstance(raw_frag, dict):
							item = PitItem(raw_frag, invalidate=False)
							fragments.append(item)
							if not key:
								key = item.id
					if key:
						self._historic_items[key] = PitItems(key, fragments, self.default_max_count)

				if not undercover and not self.unflagged and not self.read_only:
					self.process_flag.update()
			return True
		except Exception as ex:
			if isinstance(ex, PitCorruptError):
				raise
			raise PitCorruptError(f"Failed to parse pit file {self.canonical_file}: {ex}") from ex

	def seed_from_file(self, file_path: Path | str) -> int:
		"""
		Ingests a seed file (JSON or JSON5) and adds all entities to the pit.
		Returns count of imported entities.
		"""
		path = Path(file_path)
		if not path.is_file():
			raise PitNotFoundError(f"Seed file not found: {path}")

		text = path.read_text(encoding="utf-8")
		# Human seeder files may use JSON5 syntax (comments, unquoted keys, trailing commas)
		data = loads_json5(text)

		count = 0
		if isinstance(data, list):
			for row in data:
				if isinstance(row, dict):
					item = PitItem(row)
					self.add(item)
					count += 1
		elif isinstance(data, dict):
			# Object mapping ID -> entity or single entity
			if "Id" in data or "id" in data:
				self.add(PitItem(data))
				count = 1
			else:
				for k, v in data.items():
					if isinstance(v, dict):
						row = copy.deepcopy(v)
						if "Id" not in row and "id" not in row:
							row["Id"] = k
						self.add(PitItem(row))
						count += 1
		return count

	# --- Entity Addition & Mutation ---

	def add(self, item: PitItem, refresh_modified: bool = True) -> bool:
		"""
		Adds a PitItem as a new historical fragment.
		If refresh_modified is True, refreshes Modified to UtcNow.
		"""
		if not item.id:
			raise ValueError("PitItem must have a non-empty Id.")

		with self._locker:
			if refresh_modified:
				item.invalidate()
			else:
				item.validate()

			current = self._historic_items.get(item.id) or PitItems.create(
				item.id, self.default_max_count
			)
			updated = current.push(item)
			self._historic_items[item.id] = updated
			return True

	def add_historical(self, item: PitItem) -> bool:
		"""Adds a fragment while preserving its original Modified timestamp intact."""
		return self.add(item, refresh_modified=False)

	def delete_item(self, item_id: str, by: str | None = None, backdate_100: bool = True) -> bool:
		"""
		Tombstones an entity across the distributed mesh.
		Backdates timestamp by 100 seconds to preserve deletion precedence.
		"""
		tombstone = PitItem(id=item_id)
		if tombstone.delete(by=by, backdate_100=backdate_100):
			return self.add_historical(tombstone)
		return False

	def has_dirty_items(self) -> bool:
		"""True if any entity fragment in memory has unpersisted modifications."""
		for pit_items in self._historic_items.values():
			for frag in pit_items.history:
				if not frag.is_valid():
					return True
		return False

	# --- Persistence & Change Files ---

	def save(self, force: bool = False, pretty: bool = False) -> None:
		"""
		Persists memory state adhering to the JsonPit distributed protocol:
		- If running as Master: updates the canonical <PitName>.pit file in place.
		- If running as Non-Master: writes collision-safe change files into Changes/.
		"""
		if self.read_only:
			raise OSError(f"Cannot save read-only Pit '{self.pit_name}'.")

		with self._locker:
			if self.try_acquire_master():
				self._store_canonical(force=force, pretty=pretty)
			else:
				self._create_change_files()

	def _store_canonical(self, force: bool = False, pretty: bool = False) -> bool:
		"""Writes the complete point-in-time snapshot to <PitName>.pit."""
		dirty_frags: list[PitItem] = []
		model: list[list[dict[str, Any]]] = []
		snapshot_change_time = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

		for key in sorted(self._historic_items.keys()):
			pit_items = self._historic_items[key]
			history_list: list[dict[str, Any]] = []
			for frag in pit_items.history:
				history_list.append(frag.to_dict())
				if not frag.is_valid():
					dirty_frags.append(frag)
				if frag.modified > snapshot_change_time:
					snapshot_change_time = frag.modified
			model.append(history_list)

		if not dirty_frags and not force and self.canonical_file.is_file():
			return False

		# Serializes to strict canonical JSON
		if pretty:
			raw_json = json.dumps(model, indent="\t", sort_keys=True, ensure_ascii=False)
		else:
			raw_json = canonical_json(model)

		# CR022 in-place sibling write
		safe_write_in_place(self.canonical_file, raw_json)

		if not self.unflagged:
			change_time = (
				utcnow()
				if snapshot_change_time == datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
				else snapshot_change_time
			)
			self.master_flag.update(time=change_time, originator=self.exact_process_identity)
			self.process_flag.update(time=change_time)

		# Mark all included fragments as clean
		for frag in dirty_frags:
			frag.validate()

		return True

	def _create_change_files(self) -> int:
		"""Writes all dirty fragments as ordinary collision-safe change files."""
		count = 0
		for pit_items in self._historic_items.values():
			for frag in pit_items.history:
				if not frag.is_valid():
					ChangeFile.create(self.pit_dir, frag, self.exact_process_identity)
					frag.validate()
					count += 1
		return count

	# --- Change Merging & Receipt Cleanup (CR021) ---

	def merge_changes(self) -> int:
		"""
		Discovers and merges change files from peer processes.
		If running as master, canonicalizes updates and issues cleanup receipts.
		"""
		change_files = [
			p for p in self.pit_dir.glob("*.json") if p.name != self.canonical_file.name
		]
		if not change_files:
			return 0

		merged_count = 0
		merged_entries: list[tuple[Path, list[list[dict[str, Any]]]]] = []

		with self._locker:
			for cf in sorted(change_files, key=lambda p: p.name, reverse=True):
				payload = ChangeFile.read_validated(cf)
				if payload is None:
					continue
				for history_row in payload:
					for raw_frag in history_row:
						if isinstance(raw_frag, dict):
							item = PitItem(raw_frag, invalidate=False)
							current = self._historic_items.get(item.id) or PitItems.create(
								item.id, self.default_max_count
							)
							self._historic_items[item.id] = current.push(item)
				merged_entries.append((cf, payload))
				merged_count += 1

			# If master, persist merged state and manage cleanup receipts
			if not self.read_only and self.try_acquire_master():
				self._store_canonical(force=True)
				now = utcnow()
				for cf, _ in merged_entries:
					receipt = ReceiptFile(cf)
					if receipt.is_eligible_for_cleanup:
						safe_delete_file(cf)
						receipt.remove()

		return merged_count

	# --- Query & Mapping Protocol ---

	def get(
		self,
		item_id: str,
		default: Any = None,
		*,
		at: datetime.datetime | None = None,
		with_deleted: bool = False,
	) -> PitItem | None:
		"""
		Returns the projected state of an entity.
		If with_deleted is False, returns None for tombstoned entities.
		"""
		pit_items = self._historic_items.get(item_id)
		if pit_items is None:
			return default
		projected = pit_items.project_state(at=at, with_deleted=with_deleted)
		return projected if projected is not None else default

	def get_at(
		self,
		item_id: str,
		at: datetime.datetime,
		with_deleted: bool = False,
	) -> PitItem | None:
		"""Point-in-time historical projection of an entity."""
		return self.get(item_id, at=at, with_deleted=with_deleted)

	def all_undeleted(self) -> list[PitItem]:
		"""Returns all active, non-deleted entities in this pit."""
		results: list[PitItem] = []
		for key in sorted(self._historic_items.keys()):
			item = self.get(key)
			if item is not None and not item.deleted:
				results.append(item)
		return results

	def export_json(
		self,
		export_path: Path | str,
		at: datetime.datetime | None = None,
		pretty: bool = True,
	) -> Path:
		"""Exports undeleted entity projections to a JSON file."""
		target = Path(export_path)
		ensure_directory(target.parent)

		items = [
			self.get(key, at=at).to_dict()
			for key in sorted(self._historic_items.keys())
			if self.get(key, at=at) is not None
		]

		if pretty:
			content = json.dumps(items, indent="\t", sort_keys=True, ensure_ascii=False)
		else:
			content = canonical_json(items)

		safe_write_in_place(target, content)
		return target

	# --- MutableMapping Interface ---

	def __getitem__(self, item_id: str) -> PitItem:
		val = self.get(item_id)
		if val is None:
			raise KeyError(item_id)
		return val

	def __setitem__(self, item_id: str, item: PitItem | dict[str, Any]) -> None:
		if isinstance(item, PitItem):
			if item.id != item_id:
				item = item.clone()
				item.id = item_id
			self.add(item)
		elif isinstance(item, dict):
			payload = copy.deepcopy(item)
			payload["Id"] = item_id
			self.add(PitItem(payload))
		else:
			raise TypeError(f"Cannot assign {type(item).__name__} to Pit.")

	def __delitem__(self, item_id: str) -> None:
		deleted = self.delete_item(item_id)
		if not deleted:
			raise KeyError(item_id)

	def __contains__(self, item_id: object) -> bool:
		if not isinstance(item_id, str):
			return False
		return self.get(item_id) is not None

	def __iter__(self) -> Iterator[str]:
		for key in sorted(self._historic_items.keys()):
			if self.get(key) is not None:
				yield key

	def __len__(self) -> int:
		return sum(1 for _ in self)

	def __repr__(self) -> str:
		return f"<Pit '{self.pit_name}' path={self.pit_dir} items={len(self)}>"
