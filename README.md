# jsonpit

> **Daemon-free distributed storage over Cloud Drives for developers and AI agents — multi-process, immutable history, zero dependencies.**  
> *100% C# JsonPit Parity · Zero Third-Party Runtime Dependencies · Smalltalk-Grade Object-Oriented Architecture*

`jsonpit` stores JsonPits—JSON files with an append-only value history—across machines and servers coordinated over synchronized Cloud Drives (`OneDrive`, `Dropbox`, `GoogleDrive`, `ICloudDrive`) without requiring a centralized database daemon.

The canonical **reference (lead) implementation** is C# `JsonPit` and the `pits` CLI in [RAIkeep](https://github.com/Burkhardt/RAIkeep). `jsonpit` is the pure-Python implementation engineered for 100% behavioral and physical storage parity with zero deviation.

---

## Cross-Tool & Cross-Language Version Alignment (`v4.4.7`)

`jsonpit` and the `jpit` CLI are version-synchronized to **`v4.4.7`** in direct lockstep with C# `JsonPit` in [RAIkeep](https://github.com/Burkhardt/RAIkeep).

### Why Harmonized Versioning is Essential:
- **Instant Compatibility Clarity:** Operators, DevOps pipelines, and autonomous AI agents immediately know whether `jpit` and `pits` share the exact same distributed protocol revision. If both tools report `4.4.x`, they guarantee identical master leasing rules, receipt mechanisms, 7-digit UTC timestamp parsing, and CR041 clean change file conventions.
- **Elimination of Multi-Language Matrix Confusion:** In heterogeneous environments (e.g. C# backend daemons paired with Python agent orchestrators and data science tooling), unified SemVer tags eliminate complex cross-compatibility lookup tables.
- **Joint Protocol Governance:** Architectural changes—such as CR040 anti-Read-Modify-Write rules, CR041 clean change file formatting, CR044 missing configuration diagnostics, CR047 strict patch validation, and [CR049](https://github.com/Burkhardt/jsonpit-python/blob/main/doc/CR/CR049_AIA_and_jsonpit_to_RAIkeep_Live-ID-Validation_and_Zip-Image-Import.md) live ID validation with 4-character change checksums—are certified across both languages under the exact same version milestone before release.

---

## Key Features

- **The Persistence Fabric for AI Agents:** Autonomous agents running across macOS desktop apps, backend servers, and web runtimes synchronize memory and living state across shared cloud drives without managing database servers, connection pools, or cloud credentials.
- **0% Deviation from C# JsonPit:** Reads, merges, and writes pits with identical canonical JSON serialization, UTC timestamp precision, and tombstone semantics.
- **Zero Third-Party Runtime Dependencies:** Built strictly on the Python Standard Library (`json`, `pathlib`, `typing`, `dataclasses`, `datetime`, `hashlib`, `socket`).
- **Cloud-Safe Filesystem Invariants (CR022):** In-place sibling writes (`.pit.tmp` $\rightarrow$ atomic rename within the same cloud volume). Prevents cross-device link errors (`EXDEV`) and OneDrive mass-deletion alarms.
- **Full Distributed Lease Protocol:** Implements master writer leases (`Master.flag`) and PID-specific process activity windows (`{Machine}-{Process}-{PID}.flag`) with automatic process naming from `sys.argv[0]`.
- **Ecosystem Configuration:** Seamlessly reads machine cloud paths from `~/.config/RAIkeep.json5` (with `~/.config/jsonpit.json5` fallback).
- **Pure Object-Oriented Design:** Rich domain entities (`Pit`, `PitItem`, `PitItems`) implementing standard Python protocols (`MutableMapping`, `ContextManager`).

---

## Object-Oriented Architecture

`jsonpit` models distributed state through rich, encapsulated domain classes implementing standard Python protocols (`MutableMapping`, `ContextManager`):

- **`Pit`**: Living collection and coordinator of distributed leases, change files, and storage compaction.
- **`PitItem`**: Polymorphic living entity. Emits pure sparse deltas without read-modify-write cycles (CR040).
- **`PitItems`**: Immutable fragment stack managing value history and accurate point-in-time state projection.
- **`JsonPitBase`**: Shared foundation for storage resolution, subscriber roles, and cloud synchronization.
- **`PitMaintenanceOptions` / `PitMaintenanceResult`**: Automated reconciliation, 10-minute receipt grace periods, and flag pruning (CR021/CR022).
- **`PitAudit` / `PitAuditEvent`**: Read-only durable recovery event inspection without acquiring leases or flags (CR003).

### 1. Core Replicated Storage Architecture

<p align="center">
  <img src="https://raw.githubusercontent.com/Burkhardt/jsonpit-python/main/doc/uml/jsonpitCD.png" alt="jsonpit Core Class Diagram" width="700"/>
</p>

<p align="center">
  <em>Core Living Entity Model · Vector SVG: <a href="https://github.com/Burkhardt/jsonpit-python/blob/main/doc/uml/jsonpitCD.svg">jsonpitCD.svg</a></em>
</p>

### 2. Storage Maintenance & Event Recovery Audit Architecture

<p align="center">
  <img src="https://raw.githubusercontent.com/Burkhardt/jsonpit-python/main/doc/uml/jsonpit_opsCD.png" alt="jsonpit Operations Class Diagram" width="700"/>
</p>

<p align="center">
  <em>Maintenance &amp; Recovery Audit · Vector SVG: <a href="https://github.com/Burkhardt/jsonpit-python/blob/main/doc/uml/jsonpit_opsCD.svg">jsonpit_opsCD.svg</a></em>
</p>

> 📖 **Architecture & Full API:**  
> • For the complete unified architecture across all subsystems, see **[jsonpit_unifiedCD.svg](https://github.com/Burkhardt/jsonpit-python/blob/main/doc/uml/jsonpit_unifiedCD.svg)**.  
> • For comprehensive method signatures, exception contracts, and protocol details, see **[API.md](https://github.com/Burkhardt/jsonpit-python/blob/main/API.md)**.

---

## Installation & Upgrade

### As a Global CLI Tool (`jpit`) via `pipx` (Recommended)
To run the `jpit` command-line companion anywhere across your machine in an isolated environment without polluting system packages:

```bash
# Install globally
pipx install jsonpit
# (or via companion alias)
pipx install jpit

# Upgrade to the latest lockstep release (v4.4.7)
pipx upgrade jsonpit
# (or)
pipx upgrade jpit
```

### In a Project / Virtual Environment via `pip`
To embed `jsonpit` into your Python applications, data science workflows, or agentic runtimes:

```bash
# Install
pip install jsonpit

# Upgrade to the latest release
pip install --upgrade jsonpit
```

### Upgrading with Multi-Python / `pyenv` Environments
If you maintain multiple Python versions on your machine (e.g. 3.12, 3.13, 3.14):

1. **Always anchor `pip` to your active Python interpreter:**
   ```bash
   python -m pip install --upgrade jpit
   ```
   *(Avoid bare `pip install`: invoking `pip` directly may resolve to an older Python version in `$PATH`, installing the package into the wrong runtime).*

2. **If using `pyenv`, regenerate shims:**
   ```bash
   pyenv rehash
   ```
   *This ensures `which jpit` resolves to `~/.pyenv/shims/jpit`, which dynamically routes to whichever Python version is currently active in your shell.*

3. **Verify the active executable:**
   ```bash
   which jpit
   jpit --version
   ```

> [!TIP]
> **Encountering `error: externally-managed-environment` (Homebrew Python or modern Linux / PEP 668)?**  
> Modern Homebrew and Linux package managers protect their system Python prefix by default. You have two clean options:
> - **Option A (Isolated CLI via `pipx`):** Run `brew install pipx && pipx ensurepath`, then `pipx install jpit`.
> - **Option B (Direct install into Homebrew Python):** Pass `--break-system-packages`:
>   ```bash
>   python -m pip install --upgrade --break-system-packages jpit
>   ```
>   *(Completely safe: `jsonpit` has zero runtime dependencies and cannot break system packages).*

*(Both the `jsonpit` library package and the `jpit` companion package provide both `jpit` and `jsonpit` command-line executables).*

---

## Quickstart

### 1. Cloud-First Triad (The Standard Pattern)

Given a machine configured with `~/.config/RAIkeep.json5`:

```python
from jsonpit import Pit, PitItem

# Automatically resolves cloud storage (OneDriveData/AfricaStage/Person/):
with Pit.open("Person", cloud="OneDrive", root="AfricaStage") as pit:
    # Get an entity (projected state)
    sipho = pit.get("Sipho")
    if sipho:
        print(f"Sipho's current role: {sipho.get('Role')}")
        # Mutate an entity: sparse append-only mutation, auto-sets Deleted=False
        sipho.set_property({"Status": "Active", "Location": "RehearsalStage"})

    # Add a new entity
    hugh = PitItem(id="HughMasekela")
    hugh.set_property({"Genre": "Jazz", "Instruments": ["Flugelhorn", "Cornet"]})
    pit.add(hugh)

# On exit of the context manager:
# 1. Point-in-time snapshot captured
# 2. In-place sibling temporary file written (CR022 cloud-safe)
# 3. Atomically replaces Person.pit on the cloud volume
# 4. Owned process activity flag cleanly released
```

### 2. Local / Explicit Filesystem Path

For local test directories or custom scripts:

```python
with Pit.open("/path/to/my/Person") as pit:
    for item in pit.values():
        print(item.id, item.modified)
```

### 3. Developer Companion CLI: `jpit`

The package installs both `jpit` and `jsonpit` commands:

```bash
# Fast semantic search across one or all pits ("Pit-Grep"):
jpit grep "Adele" Person
jpit grep "Burkhardt" --root AIA

# Pipe search results directly into jq:
jpit grep "Jazz" Person --json | jq '.[].Genre'

# Inspect entity living state or full immutable history:
jpit get Person Rainer
jpit history Person Rainer

# Pipe JSON5 / JSON mutations directly into a pit:
cat update.json5 | jpit put Person
echo '{id: "AlanKay", dynabook: true}' | jpit put Person

# Set individual properties or tombstone an entity:
jpit set Person AlanKay Status "Visionary"
jpit del Person ObsoleteEntity

# Automated maintenance and dead flag pruning (100% C# pits maintain parity):
jpit maintain Activity -c OneDrive -r AIA
jpit maintain Activity -c OneDrive -r AIA --apply --prune-process-flags --older-than 01:00:00 --json
jpit maintain --wwwa -c OneDrive -r AIA --apply --prune-process-flags --older-than 7.00:00:00

# Read-only audit of durable recovery events (100% C# pits audit parity):
jpit audit Activity -c OneDrive -r AIA
jpit audit Activity -c OneDrive -r AIA --machine local --level Warning
jpit audit --wwwa -c OneDrive -r AIA --json
```

---

## The Physical Structure of a Pit

A Pit is not a single file—it is a **Directory Ecosystem**:

```
Person/
├── Person.pit                     # Canonical point-in-time snapshot
├── Master.flag                    # Master writer lease ticket (Owner|Timestamp)
├── Nkosikazi-python-59346.flag    # Process activity window ({Machine}-{App}-{PID}.flag)
├── Events/                        # Immutable change streams & compaction archives
└── Changes/                       # Hashed, collision-safe change files & receipts
```

---

## Autonomous Agents & Cross-Platform State

`jsonpit` solves the distributed state dilemma for autonomous AI agents:

1. **Zero Database Infrastructure:** An agent needs only a directory path on a synchronized cloud drive (e.g. `OneDriveData/AIA/AgentMemory`). It never requires cloud database API keys, connection pools, firewall punch-through, or hosted database servers.
2. **Auditability & Time-Travel:** Because history is strictly append-only and stamped with .NET `UtcTicks`, every agent mutation retains full provenance. Operators or supervising agents can time-travel and inspect exact state at any millisecond.
3. **Multi-Agent Collision-Proof Coordination:** Multiple agents (or desktop apps + background agents) coordinate through collision-free change files (`Changes/`) and opportunistic master writer leases (`Master.flag`), guaranteeing eventual consistency without write collisions.

---

## Development & Testing

### Cross-Library Differential Parity Battery

To ensure 100% interoperability with C# `JsonPit`, this repository includes a dedicated **Differential Cross-Testing Suite** (`tests/suites/*.json5` & `tests/sequence_runner.py`). The test harness orchestrates bidirectional interaction between the Python runtime (`jpit`) and the C# CLI binary (`pits`):

- **Python Writes $\rightarrow$ C# Validates:** Python writes `.pit` snapshots and sparse changes; C# `pits export` and `pits verify` assert physical byte formatting, timestamp precision, and schema invariants.
- **C# Writes $\rightarrow$ Python Validates:** C# `pits seed`, `delete-property`, and `maintain` mutate state; Python `jpit get`, `history`, and `PitStore` verify projections and receipt mechanics.
- **7 Parity Suites (41 Cross-Engine Steps):** Covers persistence CRUD, CR041 clean change files, receipt grace periods, nested property tombstones, compaction/events archiving, process flag lifecycles, and split-master partition recovery.

For full suite descriptions, architecture diagrams, and certification tables, see:  
👉 **[`doc/CROSS_ENGINE_PARITY_SPECIFICATION.md`](https://github.com/Burkhardt/jsonpit-python/blob/main/doc/CROSS_ENGINE_PARITY_SPECIFICATION.md)**

```bash
# Run the full test battery (Unit Tests + 7 Cross-Engine Parity Suites):
python3 tests/run_all.py

# Run a specific declarative parity suite directly:
python3 -m tests.sequence_runner tests/suites/01_persistence_and_crud.json5
```
