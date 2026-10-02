"""
Aggregate Root and storage engine for JsonPit.
Encapsulates directory ecosystems, context manager transactions, distributed lease
coordination, change-file streaming, receipt-based cleanup, and Mapping protocols.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import datetime
import hashlib
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
	ProtectedAttributeError,
	StrictPatchValidationError,
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
from .item import PitItem, TimestampedValue


def has_non_empty_string_id(item: Any) -> bool:
	"""
	CR043: Checks if an item is a dictionary with an exact non-empty string 'Id'.
	Lowercase 'id' or non-string/whitespace values are not accepted.
	"""
	if not isinstance(item, dict):
		return False
	val = item.get("Id")
	return isinstance(val, str) and bool(val.strip())


def parse_and_validate_seed_payload(
	payload: str | bytes | Any,
	source_name: str = "source",
) -> list[dict[str, Any]]:
	"""
	CR043: Parses and validates a seed payload strictly BEFORE opening target Pit.
	Three accepted shapes:
	  1. Single Entity Object with an exact, non-empty string 'Id'
	  2. Keyed Entity Map where all values are entity dictionaries
	  3. Entity Array of dictionaries
	Every individual entity must have an exact, non-empty string 'Id' and pass client payload validation.
	"""
	if isinstance(payload, (str, bytes)):
		text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
		if not text.strip():
			raise ValueError(f"Source '{source_name}' is empty.")
		try:
			root = loads_json5(text)
		except Exception as ex:
			raise ValueError(f"Source '{source_name}' contains invalid JSON: {ex}") from ex
	else:
		root = payload

	shape_diagnostic = (
		f"Source '{source_name}' must be a JSON array of entities, a single entity object "
		f"with a non-empty 'Id', or a keyed map of entity objects."
	)

	items: list[Any]
	if isinstance(root, list):
		items = root
	elif isinstance(root, dict) and has_non_empty_string_id(root):
		items = [root]
	elif isinstance(root, dict) and all(isinstance(v, dict) for v in root.values()):
		items = list(root.values())
	else:
		raise ValueError(shape_diagnostic)

	validated: list[dict[str, Any]] = []
	for item in items:
		if not isinstance(item, dict):
			raise ValueError(
				f"{shape_diagnostic} Arrays and keyed maps may contain only JSON objects."
			)
		if not has_non_empty_string_id(item):
			raise ValueError(
				f"Source '{source_name}' contains an entity without a non-empty string 'Id'."
			)
		val = str(item["Id"])
		if "{" in val or "<" in val:
			raise ValueError(
				f"Entity Id '{val}' contains a prohibited template marker ('{{' or '<'). "
				"Resolve template placeholders before writing to a Pit."
			)
		PitItem.validate_client_payload(item)
		validated.append(item)

	return validated


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
		retain_window: bool = False,
	) -> None:
		self.pit_dir = Path(pit_dir)
		self.pit_name = pit_name
		self.canonical_file = self.pit_dir / f"{pit_name}.pit"
		self.subscriber = subscriber
		self.read_only = read_only
		self.backup = backup
		self.unflagged = unflagged
		self.retain_window = retain_window

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


@dataclass
class PitMaintenanceOptions:
	"""Configuration options for Pit maintenance (CR021/CR022)."""
	apply: bool = False
	prune_process_flags: bool = False
	older_than: datetime.timedelta | None = None
	repair_legacy_extensions: bool = False
	archive_events: bool = False


@dataclass
class PitMaintenanceResult:
	"""Results of an inspection or apply maintenance operation."""
	pit_file: str
	applied: bool
	master_flags_observed: int = 0
	conflict_flags_observed: int = 0
	process_flags_active: int = 0
	process_flags_expired: int = 0
	process_flags_pruned: int = 0
	process_flags_malformed: int = 0
	change_files_observed: int = 0
	change_files_invalid: int = 0
	change_files_valid: int = 0
	change_files_merged: int = 0
	change_files_eligible: int = 0
	change_files_removed: int = 0
	receipts_observed: int = 0
	receipts_created: int = 0
	receipts_retained: int = 0
	receipts_removed: int = 0
	receipts_malformed: int = 0
	legacy_artifacts_observed: int = 0
	legacy_artifacts_repaired: int = 0
	event_files_observed: int = 0
	event_files_archived: int = 0
	event_files_removed: int = 0
	event_archive_name: str | None = None
	canonical_persisted: bool = False
	current_master: bool = False
	deferred: list[str] = field(default_factory=list)
	failures: list[str] = field(default_factory=list)

	@property
	def succeeded(self) -> bool:
		return len(self.failures) == 0

	def to_dict(self) -> dict[str, Any]:
		return {
			"PitFile": self.pit_file,
			"Applied": self.applied,
			"Succeeded": self.succeeded,
			"MasterFlagsObserved": self.master_flags_observed,
			"ConflictFlagsObserved": self.conflict_flags_observed,
			"ProcessFlagsActive": self.process_flags_active,
			"ProcessFlagsExpired": self.process_flags_expired,
			"ProcessFlagsPruned": self.process_flags_pruned,
			"ProcessFlagsMalformed": self.process_flags_malformed,
			"ChangeFilesObserved": self.change_files_observed,
			"ChangeFilesInvalid": self.change_files_invalid,
			"ChangeFilesValid": self.change_files_valid,
			"ChangeFilesMerged": self.change_files_merged,
			"ChangeFilesEligible": self.change_files_eligible,
			"ChangeFilesRemoved": self.change_files_removed,
			"ReceiptsObserved": self.receipts_observed,
			"ReceiptsCreated": self.receipts_created,
			"ReceiptsRetained": self.receipts_retained,
			"ReceiptsRemoved": self.receipts_removed,
			"ReceiptsMalformed": self.receipts_malformed,
			"LegacyArtifactsObserved": self.legacy_artifacts_observed,
			"LegacyArtifactsRepaired": self.legacy_artifacts_repaired,
			"EventFilesObserved": self.event_files_observed,
			"EventFilesArchived": self.event_files_archived,
			"EventFilesRemoved": self.event_files_removed,
			"EventArchiveName": self.event_archive_name,
			"CanonicalPersisted": self.canonical_persisted,
			"CurrentMaster": self.current_master,
			"Deferred": self.deferred,
			"Failures": self.failures,
		}


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
		retain_window: bool = False,
		default_max_count: int = 10,
		autoload: bool = True,
	) -> None:
		super().__init__(
			pit_dir=pit_dir,
			pit_name=pit_name,
			subscriber=subscriber,
			read_only=read_only,
			backup=backup,
			unflagged=unflagged,
			retain_window=retain_window,
		)
		self.default_max_count = default_max_count
		self.autoload = autoload
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
		if self.autoload:
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
			if not self.retain_window:
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
		retain_window: bool = False,
		default_max_count: int = 10,
		autoload: bool = True,
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
			retain_window=retain_window,
			default_max_count=default_max_count,
			autoload=autoload,
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

	def seed_from_file(self, file_path: Path | str, require_existing: bool = False) -> int:
		"""
		Ingests a seed file (JSON or JSON5) and adds all entities to the pit.
		Returns count of imported entities.
		CR043: Validates payload shape and entities strictly before mutation.
		CR047: If require_existing is True, validates that all IDs exist in living state.
		"""
		path = Path(file_path)
		if not path.is_file():
			raise PitNotFoundError(f"Seed file not found: {path}")

		text = path.read_text(encoding="utf-8")
		items_to_add = parse_and_validate_seed_payload(text, str(path))

		if require_existing:
			if not items_to_add:
				raise StrictPatchValidationError("Patch source contained 0 entities.")
			for raw_obj in items_to_add:
				item_id = raw_obj["Id"]
				if not self.contains(item_id, with_deleted=False):
					raise StrictPatchValidationError(
						f"Entity '{item_id}' does not exist in Pit '{self.pit_name}'. "
						"Use without --require-existing / --patch to allow creating new entities."
					)

		count = 0
		for raw_obj in items_to_add:
			item = PitItem(raw_obj)
			self.add(item)
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
		if not item.deleted and ("{" in item.id or "<" in item.id):
			raise ValueError(
				f"Entity Id '{item.id}' contains a prohibited template marker ('{{' or '<'). "
				"Resolve template placeholders before writing to a Pit."
			)

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

	def delete_item(self, item_id: str, by: str | None = None, backdate_100: bool = False) -> bool:
		"""
		Tombstones an entity across the distributed mesh.
		Stamps the tombstone with the current wall-clock instant of deletion.
		"""
		tombstone = PitItem(id=item_id)
		if tombstone.delete(by=by, backdate_100=backdate_100):
			return self.add(tombstone, refresh_modified=True)
		return False

	def rename_id(self, old_key: str, new_key: str, by: str | None = None) -> bool:
		"""
		Migrates state from old_key to new_key, tombstoning old_key.
		100% parity with C# Pit.RenameId.
		"""
		if not old_key or not new_key or old_key == new_key:
			return False
		if self.get(old_key) is None or self.get(new_key, with_deleted=True) is not None:
			return False

		old_item = self.get(old_key)
		if old_item is None:
			return False

		new_data = old_item.to_dict()
		new_data["Id"] = new_key
		new_data.pop("Modified", None)
		new_item = PitItem(new_data)

		with self._locker:
			deleted = self.delete_item(old_key, by=by)
			added = self.add(new_item)
			return deleted and added

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
				for entry in payload:
					if isinstance(entry, dict):
						item = PitItem(entry, invalidate=False)
						current = self._historic_items.get(item.id) or PitItems.create(
							item.id, self.default_max_count
						)
						self._historic_items[item.id] = current.push(item)
					elif isinstance(entry, list):
						for raw_frag in entry:
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

	# --- Maintenance & Cleanup (CR021/CR022) ---

	def maintain(
		self,
		options: PitMaintenanceOptions | None = None,
		*,
		apply: bool = False,
	) -> PitMaintenanceResult:
		"""
		Inspects or reconciles changes, receipts, process flags, and event archives.
		Report-only by default; apply=True performs authorized modifications.
		"""
		if options is None:
			options = PitMaintenanceOptions(apply=apply)
		elif apply:
			options.apply = True

		if options.prune_process_flags and not options.apply:
			raise ValueError("Process-flag pruning requires apply=True.")
		if options.prune_process_flags and options.older_than is None:
			raise ValueError("Process-flag pruning requires older_than duration.")
		if not options.prune_process_flags and options.older_than is not None:
			raise ValueError("older_than applies only to process-flag pruning.")
		if options.older_than is not None and options.older_than <= datetime.timedelta(0):
			raise ValueError("older_than must be positive.")

		result = PitMaintenanceResult(
			pit_file=str(self.canonical_file),
			applied=options.apply,
		)

		if not self.pit_dir.is_dir():
			result.deferred.append(f"Pit directory does not exist: {self.pit_dir}")
			return result

		now = utcnow()

		if not self._historic_items and self.canonical_file.is_file():
			self.load(undercover=True)

		with self._locker:
			# 1. Enumerate and process change files
			change_files = sorted(
				[p for p in self.pit_dir.glob("*.json") if p.name != self.canonical_file.name],
				key=lambda p: p.name,
				reverse=True if options.apply else False,
			)

			merged_files: list[tuple[Path, list[Any]]] = []
			for cf in change_files:
				result.change_files_observed += 1
				try:
					payload = ChangeFile.read_validated(cf)
					if payload is None:
						result.change_files_invalid += 1
						continue
					result.change_files_valid += 1
					for entry in payload:
						if isinstance(entry, dict):
							item = PitItem(entry, invalidate=False)
							current = self._historic_items.get(item.id) or PitItems.create(
								item.id, self.default_max_count
							)
							self._historic_items[item.id] = current.push(item)
						elif isinstance(entry, list):
							for raw_frag in entry:
								if isinstance(raw_frag, dict):
									item = PitItem(raw_frag, invalidate=False)
									current = self._historic_items.get(item.id) or PitItems.create(
										item.id, self.default_max_count
									)
									self._historic_items[item.id] = current.push(item)
					result.change_files_merged += 1
					merged_files.append((cf, payload))
				except Exception as ex:
					result.change_files_invalid += 1
					result.deferred.append(f"Change file is not currently mergeable: {cf.name}: {ex}")

			# 2. If apply: acquire master, store canonical, manage receipts & cleanup
			if options.apply:
				result.current_master = not self.read_only and self.try_acquire_master()
				if result.current_master:
					if merged_files:
						self._store_canonical(force=True)
						result.canonical_persisted = True

					for cf, _ in merged_files:
						receipt_path = cf.with_suffix(".receipt")
						existed = receipt_path.is_file()
						try:
							receipt = ReceiptFile(cf)
							result.receipts_observed += 1 if existed else 0
							result.receipts_created += 0 if existed else 1
							result.receipts_retained += 1
							if receipt.is_eligible_for_cleanup:
								result.change_files_eligible += 1
								safe_delete_file(cf)
								result.change_files_removed += 1
								receipt.remove()
								result.receipts_removed += 1
						except Exception as ex:
							result.receipts_malformed += 1
							result.deferred.append(f"Receipt is not currently valid: {receipt_path.name}: {ex}")

					# Inspect orphan receipts whose change file is missing
					for rf_path in sorted(self.pit_dir.glob("*.receipt"), key=lambda p: p.name):
						cf_path = rf_path.with_suffix(".json")
						if not cf_path.is_file():
							result.receipts_observed += 1
							try:
								orphan_receipt = ReceiptFile(cf_path)
								if orphan_receipt.is_eligible_for_cleanup:
									orphan_receipt.remove()
									result.receipts_removed += 1
								else:
									result.receipts_retained += 1
							except Exception:
								pass
				elif merged_files:
					result.deferred.append("Cleanup evidence and deletion require current exact-master authority.")
			else:
				# Report-only inspection of receipts
				for cf in change_files:
					rf_path = cf.with_suffix(".receipt")
					if rf_path.is_file():
						result.receipts_observed += 1
						try:
							receipt = ReceiptFile(cf)
							if receipt.is_eligible_for_cleanup:
								result.change_files_eligible += 1
							result.receipts_retained += 1
						except Exception:
							result.receipts_malformed += 1

			# 3. Process Flags inspection and optional pruning
			for pf in sorted(self.pit_dir.glob("*.flag"), key=lambda p: p.name):
				if pf.name == "Master.flag" or pf.name == "Master":
					result.master_flags_observed += 1
					continue
				if pf.name.startswith("Master"):
					result.conflict_flags_observed += 1
					continue

				try:
					content = safe_read_text(pf)
					first_line = content.splitlines()[0] if content else ""
					if not first_line:
						result.process_flags_malformed += 1
						result.deferred.append(f"Process flag is malformed: {pf.name}")
						continue
					tv = TimestampedValue(first_line)
					is_expired = (now - tv.time) > MasterFlagFile.TICKET_DURATION
					if not is_expired:
						result.process_flags_active += 1
						continue

					result.process_flags_expired += 1
					if options.prune_process_flags and options.older_than is not None:
						age = now - tv.time
						if age >= options.older_than:
							reread_content = safe_read_text(pf)
							reread_line = reread_content.splitlines()[0] if reread_content else ""
							if reread_line and (now - TimestampedValue(reread_line).time) >= options.older_than:
								safe_delete_file(pf)
								if not pf.exists():
									result.process_flags_pruned += 1
								else:
									result.failures.append(f"Expired process flag remained after removal: {pf}")
				except Exception as ex:
					result.process_flags_malformed += 1
					result.deferred.append(f"Process flag is not currently verifiable: {pf.name}: {ex}")

			# 4. Legacy EventFile migration
			events_dir = self.pit_dir / "Events"
			if events_dir.is_dir():
				for ef in sorted(events_dir.glob("*.event"), key=lambda p: p.name):
					result.event_files_observed += 1
					stem = ef.stem
					if "_" in stem:
						prefix, possible_hash = stem.rsplit("_", 1)
						if len(possible_hash) == 64 and all(c in "0123456789abcdefABCDEF" for c in possible_hash):
							result.legacy_artifacts_observed += 1
							if options.repair_legacy_extensions or options.apply:
								content = safe_read_text(ef)
								actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
								if actual_hash.lower() == possible_hash.lower():
									clean_target = events_dir / f"{prefix}.event"
									try:
										ef.rename(clean_target)
										result.legacy_artifacts_repaired += 1
									except Exception as ex:
										result.failures.append(f"Legacy event rename failed for {ef.name}: {ex}")
								else:
									result.deferred.append(f"Legacy event file hash mismatch for {ef.name}")

		return result

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
		if projected is not None and at is None and not self.read_only:
			projected.bind(self)
		return projected if projected is not None else default

	def get_at(
		self,
		item_id: str,
		at: datetime.datetime,
		with_deleted: bool = False,
	) -> PitItem | None:
		"""Point-in-time historical projection of an entity."""
		return self.get(item_id, at=at, with_deleted=with_deleted)

	def contains(self, item_id: str, with_deleted: bool = False) -> bool:
		"""100% C# parity: checks if an entity exists in living state."""
		if not item_id:
			return False
		return self.get(item_id, with_deleted=with_deleted) is not None

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


Pit.parse_and_validate_seed_payload = staticmethod(parse_and_validate_seed_payload)  # type: ignore[attr-defined]
PitStore = Pit
