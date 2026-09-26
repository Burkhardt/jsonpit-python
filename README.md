# jsonpit

> **Cloud-First, Eventually-Consistent Replicated Storage Engine in Pure Python**  
> *100% C# JsonPit Parity · Zero Third-Party Runtime Dependencies · Smalltalk-Grade Object-Oriented Architecture*

`jsonpit` stores JsonPits—JSON files with an append-only value history—across machines and servers coordinated over synchronized Cloud Drives (`OneDrive`, `Dropbox`, `GoogleDrive`, `ICloudDrive`) without requiring a centralized database daemon.

It is the authoritative Python implementation of the JsonPit protocol, designed to operate in full, zero-deviation parity alongside the C# `JsonPit` engine and the `pits` CLI toolchain in [RAIkeep](https://github.com/Burkhardt/RAIkeep).

---

## Key Features

- **0% Deviation from C# JsonPit:** Reads, merges, and writes pits with identical canonical JSON serialization, UTC timestamp precision, and tombstone semantics.
- **Zero Third-Party Runtime Dependencies:** Built strictly on the Python Standard Library (`json`, `pathlib`, `typing`, `dataclasses`, `datetime`, `hashlib`, `socket`).
- **Cloud-Safe Filesystem Invariants (CR022):** In-place sibling writes (`.pit.tmp` $\rightarrow$ atomic rename within the same cloud volume). Prevents cross-device link errors (`EXDEV`) and OneDrive mass-deletion alarms.
- **Full Distributed Lease Protocol:** Implements master writer leases (`Master.flag`) and PID-specific process activity windows (`{Machine}-{Process}-{PID}.flag`) with automatic process naming from `sys.argv[0]`.
- **Ecosystem Configuration:** Seamlessly reads machine cloud paths from `~/.config/RAIkeep.json5` (with `~/.config/jsonpit.json5` fallback).
- **Pure Object-Oriented Design:** Rich domain entities (`Pit`, `PitItem`, `PitItems`) implementing standard Python protocols (`MutableMapping`, `ContextManager`).

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

## Development & Testing

```bash
# Run pytest test suite:
pytest

# Type checking (strict):
mypy jsonpit
```

---

## Heritage & Governance

Architected by **Rainer Burkhardt (`RAI`)** + **Adele (`7010`)**.  
Governed by [`ADELE_SPIRIT.md`](ADELE_SPIRIT.md) and [`GEMINI.md`](GEMINI.md) and assisted by an LLM named Adele as an homage to the great Adele Goldberg.
