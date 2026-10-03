# jsonpit API Reference (v4.5.3)

This document provides a foldable, searchable reference for the public `jsonpit` Python API. Designed for 100% C# JsonPit parity, zero third-party runtime dependencies, and Smalltalk-grade object-oriented architecture.

---

## Architectural Diagrams

### Core Replicated Storage Architecture
<p align="center">
  <img src="https://raw.githubusercontent.com/Burkhardt/jsonpit-python/main/doc/uml/jsonpitCD.png" alt="Core Replicated Storage Architecture" width="700"/>
</p>

### Storage Maintenance & Recovery Audit Architecture
<p align="center">
  <img src="https://raw.githubusercontent.com/Burkhardt/jsonpit-python/main/doc/uml/jsonpit_opsCD.png" alt="Operations & Recovery Audit Architecture" width="700"/>
</p>

---

## Pit Lifecycle & Storage

- <details>
  <summary><code>Pit</code>: Live eventually consistent distributed JSON store</summary>

  Coordinates one live public instance per canonical pit path, implements `MutableMapping[str, PitItem]` and the `ContextManager` protocol, observes cloud-drive changes, emits sparse delta change files, and coordinates master leases.

  **Key Methods:**
  - `__enter__()` / `__exit__()`: Context manager for atomic batch sessions and guaranteed flag cleanup.
  - `add(item: PitItem, refresh_modified: bool = True) -> bool`: Adds or updates a living entity. Validates against prohibited template markers (`{` or `<`) under CR049.
  - `add_historical(item: PitItem) -> bool`: Replays an immutable historical fragment without modifying timestamps or rejecting legacy IDs.
  - `get(item_id: str, default: Any = None, at: datetime = None, with_deleted: bool = False) -> PitItem | None`: Retrieves the projected living state of an entity, with optional time-travel projection.
  - `delete_item(item_id: str, by: str | None = None, backdate_100: bool = False) -> bool`: Tombstones an entity across the distributed cluster.
  - `rename_id(old_key: str, new_key: str, by: str | None = None) -> bool`: Atomically migrates an entity identity.
  - `seed_from_file(file_path: Path | str, require_existing: bool = False) -> int`: Ingests an external JSON/JSON5 file (single entity, keyed map, or array) with whole-batch ID preflight and optional CR047 strict patch enforcement.
  - `maintain(options: PitMaintenanceOptions = None, apply: bool = False) -> PitMaintenanceResult`: Reconciles change files, manages 10-minute receipt grace periods, prunes expired process flags (`--older-than`), and repairs legacy event extensions.
  - `save(force: bool = False, pretty: bool = False) -> None`: Persists the unified canonical `.pit` file in-place using CR022 sibling writes (`.pit.tmp` followed by atomic rename).
  </details>

- <details>
  <summary><code>Pit.maintain(...)</code>, <code>PitMaintenanceOptions</code>, and <code>PitMaintenanceResult</code></summary>

  `maintain()` inventories pending change/receipt cleanup without mutation. It checks the canonical parent first, returning deferred status for missing targets without creating directories. `maintain(apply=True)` applies canonical reconciliation and eligible change-first/receipt-second retirement (10-minute grace period).
  
  **Maintenance Options:**
  - `apply: bool`: Authorizes modifications to disk (default False: report-only preview).
  - `prune_process_flags: bool`: Authorizes pruning of expired PID-window flag files. Requires `apply=True` and `older_than`.
  - `older_than: timedelta`: Duration threshold for flag pruning (e.g. `01:00:00`, `7.00:00:00`).
  - `repair_legacy_extensions: bool`: Migrates legacy `{stem}_{sha256}.event` files to clean `{stem}.event` in `Events/`.
  - `archive_events: bool`: Compacts event logs into immutable archives.

  **Maintenance Result (`to_dict()` for 100% C# parity):**
  - Exposes `PitFile`, `Applied`, `Succeeded`, `ChangeFilesObserved/Merged/Removed`, `ReceiptsCreated/Removed`, `ProcessFlagsActive/Expired/Pruned`, `LegacyArtifactsObserved/Repaired`, `Deferred`, and `Failures`.
  </details>

- <details>
  <summary><code>JsonPitBase</code>: Shared storage and path foundation</summary>

  Base class providing pit path resolution, cloud drive detection, subscriber identity, process leasing options (`read_only`, `unflagged`, `retain_window`), and canonical serialization.
  </details>

- <details>
  <summary><code>PitStore</code>: Thread-safe repository of open Pit instances</summary>

  Factory and cache ensuring only one active `Pit` instance exists per canonical file path within a single process, preventing memory divergence.
  </details>

---

## Entity Domain Model & History

- <details>
  <summary><code>PitItem</code>: Polymorphic living entity and sparse delta emitter</summary>

  Represents an individual entity within a Pit. Implements dictionary-like attribute access while protecting immutable engine attributes (`id`, `modified`, `deleted`) from accidental mutation (CR040). When bound to a `Pit`, mutations automatically stream sparse delta change files without triggering read-modify-write anti-patterns.

  **Core Attributes:**
  - `id`: Non-empty string identifier. Rejects unresolved template markers (`{` or `<`) at write boundaries (CR049).
  - `modified`: 7-digit UTC timestamp (`datetime`) of the latest fragment.
  - `deleted`: Boolean tombstone flag.
  - `note`: Optional human- or agent-readable string note.

  **Sparse Mutation Methods:**
  - `set_property(patch: dict[str, Any] | str) -> bool`: Atomically applies a property delta and emits a sparse change file.
  - `delete_property(property_name: str) -> None`: Emits a property-level null tombstone without rewriting living state.
  - `delete_property_path(property_path: str) -> None`: Traverses dot-delimited paths to tombstone nested properties.
  - `extend_with(obj: dict[str, Any]) -> bool`: Merges attributes from a dictionary.
  - `to_dict() -> dict[str, Any]` / `to_json() -> str`: Canonical JSON serialization.
  </details>

- <details>
  <summary><code>PitItems</code>: Immutable fragment stack and time-travel projector</summary>

  Maintains an entity's ordered history of timestamped fragments.

  **Key Methods:**
  - `push(item: PitItem) -> PitItems`: Returns a new `PitItems` stack with the fragment prepended.
  - `latest_fragment() -> PitItem | None`: Returns the most recently written fragment.
  - `project_state(at: datetime = None, with_deleted: bool = False) -> PitItem | None`: Merges historical fragments from oldest to newest up to timestamp `at` to compute accurate point-in-time living state.
  </details>

---

## Distributed Protocol & Cloud Safety

- <details>
  <summary><code>ChangeFile</code>: Shortened cloud-safe change artifact</summary>

  Writes sparse delta mutations into `Changes/` using the 4-character hex checksum format:
  `{UtcTicks}_{ExactProcessIdentity}_{4charHex}.json`
  Guards against partially synchronized cloud writes (e.g. OneDrive) without exceeding path length limits. Validates checksums on read and maintains backwards compatibility with legacy 64-character SHA-suffixed change files.
  </details>

- <details>
  <summary><code>ReceiptFile</code>: Durable round-trip confirmation</summary>

  Pairs with change files using the `.receipt` extension. Enforces a 10-minute grace period before allowing retired change files to be compacted or purged.
  </details>

- <details>
  <summary><code>MasterFlagFile</code> & <code>ProcessFlagFile</code>: Cloud drive lease coordination</summary>

  - `Master.flag`: 60-second lease renewed every 30 seconds by the active master writer.
  - `{Machine}-{Process}-{PID}.flag`: Ephemeral process activity flag with heartbeat updates. Enforces deterministic self-cleanup on process exit (CR024).
  </details>

- <details>
  <summary><code>EventFile</code>: Clean event compaction naming & migration</summary>

  Emits compacted historical events under clean logical stems (`{LogicalStem}.event`) without SHA-256 hash suffixes. Automatically recognizes legacy 64-char hash filenames and supports in-place migration.
  </details>

---

## Configuration & Cloud Discovery

- <details>
  <summary><code>OsConfig</code>: Cross-platform cloud drive discovery</summary>

  Discovers synchronization folders for `Dropbox`, `OneDrive`, `GoogleDrive`, and `ICloudDrive`. Reads primarily from `~/.config/RAIkeep.json5` with fallback to `~/.config/jsonpit.json5` or `$JSONPIT_CONFIG`.
  </details>

- <details>
  <summary><code>missing_configuration_diagnostic()</code>: CR044 operator guidance</summary>

  When cloud drives or configuration files are absent, formats clear actionable instructions directing the operator to run `amafu init` to bootstrap configuration.
  </details>

---

## Audit Engine & Recovery Inspection

- <details>
  <summary><code>PitAudit</code>: Read-only inspection of durable event logs</summary>

  Provides read-only access to durable JsonPit recovery events under `Events/` without opening a `Pit`, creating process activity flags, acquiring leases, or mutating disk state (CR003, coordinated v3.13.2). Inspects both loose `*.event` files and immutable `Events_*.zip` compaction archives.

  **Key Methods:**
  - `PitAudit.inspect(pit_directory: Path | str, machine_filter: str = "all", min_level: LogLevel = LogLevel.TRACE) -> PitAuditReadResult`: Reads, validates, deduplicates by `EventId`, filters by machine/severity, and orders events deterministically by machine, UTC time, and event identity.
  </details>

- <details>
  <summary><code>PitAuditEvent</code>: Durable recovery event domain model</summary>

  Encapsulates a single durable recovery event:
  - `file_name: str`: Source file or archive entry name.
  - `content: dict[str, Any]`: Raw deserialized event JSON object.
  - `machine: str`: Originating machine hostname.
  - `utc_time: datetime`: Event occurrence timestamp in UTC.
  - `level: LogLevel`: Severity level.
  - `stage: str`: Pit lifecycle stage (e.g. `ChangeFilesPublished`, `CleanupPending`, `Completed`).
  - `event_id: str`: Unique GUID event identifier used for cross-archive deduplication.
  - `message: str`: Human-readable summary message.
  </details>

- <details>
  <summary><code>LogLevel</code>: Event severity enumeration</summary>

  Matches .NET `LogLevel` integer values and names:
  - `TRACE = 0` (`Trace`)
  - `DEBUG = 1` (`Debug`)
  - `INFORMATION = 2` (`Information` / `info`)
  - `WARNING = 3` (`Warning` / `warn`)
  - `ERROR = 4` (`Error` / `err`)
  - `CRITICAL = 5` (`Critical` / `fatal`)
  - `from_string(name: str) -> LogLevel`: Case-insensitive parsing supporting names, aliases, and integer strings.
  - `display_name -> str`: Capitalized canonical name matching C# output formatting.
  </details>

- <details>
  <summary><code>PitAuditReadResult</code>: Filtered events and diagnostic issues</summary>

  Contains:
  - `events: list[PitAuditEvent]`: Filtered and ordinally sorted events.
  - `issues: list[str]`: Physical corruption, empty file, or conflicting event identity warnings.
  - `succeeded: bool`: Returns `True` if no diagnostic issues were discovered.
  </details>

---

## Exception Hierarchy

All `jsonpit` exceptions derive from `JsonPitError`:

```text
JsonPitError
├── PitNotFoundError               # Target pit directory or file does not exist
├── PitCorruptError                # Payload failed checksum or schema validation
├── PitConcurrencyError            # Conflict acquiring or renewing master lease
├── PitInstanceConflictError       # Multiple live Pit instances for the same file path
├── ProtectedAttributeError        # Client attempted to mutate 'id', 'modified', or 'deleted' (CR040)
├── TombstoneError                 # Attempted to delete protected engine attributes
└── StrictPatchValidationError     # Missing or tombstoned entity under --require-existing (CR047)
```
