# CR047 — Strict Patch Mode (`--require-existing` / `--patch`) & Commit Count Parity

| Metadata | Details |
| :--- | :--- |
| **Document ID** | CR047 |
| **Title** | Strict Patch Mode (`--require-existing` / `--patch`) & Seed Commit Count Parity |
| **Status** | Proposed |
| **Target Versions** | `RAIkeep 4.4.5`, `jsonpit 4.4.5`, `jpit 4.4.5`, `pits 4.4.5` |
| **Author** | Adele Goldberg (`7010`), Lead Software Architect, `jsonpit` / AIA Platform |
| **Contributors / QA** | Sipho (`7001`), Systems QA & Test Architect |
| **Ratifier** | Dr. Rainer Burkhardt (`RAI`, Chief Maker / CPO / CTO) |
| **Date** | 2026-09-29 |

---

## 1. Executive Summary & Problem Statement

In both C# `pits seed` and Python `jpit put` / `seed`, batch ingestion is currently an unconditional **upsert**:
- If an entity ID already exists in the Pit, the payload is appended as a sparse delta.
- If an entity ID does not exist in the Pit, a brand-new entity is created with only the attributes provided in the payload.

### The Operational Trap
As diagnosed and proven by Sipho (`7001`) during cross-engine certification:
1. `seed` and `put` perform **double duty**: they are used both for **initial seeding** (where unknown IDs are expected) and for **attribute patching** (e.g. enriching existing entities with `UseCase`, `Role`, or `Status`).
2. When patching existing entities, a single mistyped, mis-cased, or deleted ID does not fail. Instead, both tools exit with code `0`, report success, and create a **ghost entity** carrying no `Kind` and no `Name`.
3. Because these ghost entities lack `Kind`, they are completely invisible to standard projections like `select(.Kind == "Act")`, leaving silent data corruption in the Pit.
4. Furthermore, C# `pits seed` currently does not report the number of committed entities on stdout, leaving operators without quantitative feedback on whether their batch actually landed.

---

## 2. Architectural Invariants

1. **Pre-Validation Atomicity (All-or-Nothing):**
   If strict patching is requested and any entity in the batch fails validation or does not exist in the Pit, **zero writes shall be committed to disk**, and the command must exit with code `1`.
2. **100% Cross-Engine Parity (C# `pits` $\equiv$ Python `jpit`):**
   The flag syntax, error diagnostics, and success reporting must match across `pits 4.4.5` and `jpit 4.4.5`.
3. **Backwards Compatibility:**
   Default invocations of `pits seed` and `jpit put` / `seed` without the patch flag retain their existing upsert behavior.

---

## 3. Specification

### 3.1. CLI Flags: `--require-existing` and `--patch`

Both CLI engines must support `--require-existing` (with `--patch` as an alias) on their ingestion verbs:

- **C# `pits`:**
  ```bash
  pits seed <PitName> --source <file> [--require-existing | --patch]
  ```
- **Python `jpit`:**
  ```bash
  jpit put <PitName> [source] [--require-existing | --patch]
  # or alias
  jpit seed <PitName> [source] [--require-existing | --patch]
  ```

### 3.2. Validation Semantics

When `--require-existing` or `--patch` is present:

1. **Existence Verification:**
   Before acquiring the process flag or opening the Pit for write, the engine loads living state and verifies that **every entity ID** in the incoming batch exists in living state:
   - C#: `pit.Contains(id, withDeleted: false)` must be `true`.
   - Python: `pit.get(id, with_deleted=False)` must not be `None`.
2. **Missing ID Error Handling:**
   If any entity ID in the batch does not exist (or is currently tombstoned with `Deleted: true`), the engine immediately stops execution, emits an error message to `stderr`, and exits with code `1`:
   ```text
   error: Entity '{MissingId}' does not exist in Pit '{PitName}'. Use without --require-existing / --patch to allow creating new entities.
   ```
3. **Empty Source Batch Handling:**
   If the source payload contains an empty array (`[]`) or 0 entities when `--require-existing` / `--patch` is specified, the command must reject the write and exit with code `1`:
   ```text
   error: Patch source contained 0 entities.
   ```
   *(This ensures scripted pipelines using `set -e` fail if a generated patch was empty).*

### 3.3. Success Reporting Parity

Upon successful completion of `pits seed` (both with and without `--require-existing`):
- C# `pits` must emit the exact quantitative summary message on `stdout` currently emitted by Python `jpit`:
  ```text
  [pits] Successfully committed {N} entity(ies) to Pit '{PitName}'.
  ```

---

## 4. Acceptance Criteria & Test Vectors

| Test ID | Input Payload | CLI Flags | Expected Exit | Expected Output |
| :--- | :--- | :--- | :--- | :--- |
| **TC-01** | `[{"Id": "Alice", "UseCase": "Live"}]` (Alice exists) | `--require-existing` | `0` | `Successfully committed 1 entity(ies)...` |
| **TC-02** | `[{"Id": "Ghost99", "UseCase": "Live"}]` (Ghost99 does not exist) | `--require-existing` | `1` | `stderr`: `error: Entity 'Ghost99' does not exist in Pit...` |
| **TC-03** | `[{"Id": "Alice", ...}, {"Id": "Ghost99", ...}]` (1 good + 1 bad) | `--patch` | `1` | Atomic abort: neither entity written to disk |
| **TC-04** | `[]` (empty array) | `--require-existing` | `1` | `stderr`: `error: Patch source contained 0 entities.` |
| **TC-05** | `[{"Id": "Ghost99", "UseCase": "Live"}]` | *(no flag - default upsert)* | `0` | Creates `Ghost99` (backwards-compatible seeder behavior) |

---

## 5. Delivery Sequence

1. **Step 1:** Ratification of CR047 by Chief Maker (`RAI`).
2. **Step 2:** C# reference implementation in `RAIkeep` (`pits 4.4.5`).
3. **Step 3:** Independent certification by QA Architect (`Sipho`).
4. **Step 4:** Implementation and certification in Python (`jsonpit 4.4.5` / `jpit 4.4.5`).
5. **Step 5:** Simultaneous release to NuGet and PyPI.
