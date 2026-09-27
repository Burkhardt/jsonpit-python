# CR040: Prohibit Read-Modify-Write Storage Anti-Pattern & Enforce Protected Lifecycle Attributes

> **Naming Schema:** `CR<NNN>_<Requester>_to_<Provider>_<Topic>.md`  
> **Follow-up Sub-CR Schema:** `CR<NNN>.<M>_<Requester>_to_<Provider>_<Topic>.md`  
> **Immutability Rule:** The provider agent must NEVER rename or modify this document filename.

**Date:** 2026-09-26  
**Requesting Agent / PM:** Adele (PM AIA, 7010) & Adele (Lead Software Architect jsonpit, 7010)  
**Target Provider / Repo:** `RAIkeep` (C# / `JsonPit` / `pits` — Custodian: Codex) & `jsonpit` (Python / `jpit`)  
**Status:** Proposed (Accepted by Requesters; Awaiting Codex Sign-off)  
**Parent CR:** N/A  
**Parity Invariant:** 100% C# / Python Parity (0% Deviation)

---

## 1. Objective & Context

### 1.1 The Distributed Storage Model of JsonPit
`JsonPit` is a cloud-first, distributed, replicated, append-only, event-sourced storage engine coordinated across asynchronous cloud synchronization drives (OneDrive, Dropbox, GoogleDrive, iCloudDrive).

In this architecture, living entity state is a **deterministic projection fold** over an immutable sequence of sparse change fragments (`Changes/` and `Events/`). Multiple processes across multiple physical machines append sparse mutations concurrently.

### 1.2 The Problem: The Read-Modify-Write (R-M-W) Anti-Pattern
A pervasive anti-pattern in client code and interactive scripting is the monolithic Read-Modify-Write cycle:
```python
# THE FATAL R-M-W ANTI-PATTERN (Python):
sipho = pit.get("Sipho")            # 1. Read projected state (includes Id, Modified, Deleted, etc.)
sipho["Status"] = "Active"          # 2. Modify one property in-memory
pit.add(sipho)                      # 3. Write-back entire projected entity dictionary!
```
Or via CLI:
```bash
# THE FATAL R-M-W ANTI-PATTERN (CLI):
state=$(jpit get Jazz Sipho)
# mutate state locally and pipe full projected dictionary back:
jpit set Jazz Sipho "$state"
```

### 1.3 Why R-M-W is Catastrophic in Distributed Cloud Storage:
1. **Destruction of Eventual Consistency (State Stomping):**  
   If Process $A$ on Machine 1 reads entity $E$, and concurrently Process $B$ on Machine 2 appends a sparse mutation `{"Location": "Studio"}`, Process $A$ writing back its full projected dictionary will overwrite and revert Process $B$'s update. JsonPit relies on sparse deltas so concurrent field modifications commute cleanly.
2. **Sparse Stream Bloat & Loss of Intent:**  
   Writing back full entities repeatedly records dozens of unchanged properties into append-only change files, ballooning cloud sync bandwidth, destroying audit clarity, and degrading compaction efficiency.
3. **Falsification of Monotonic Engine Time (`Modified`):**  
   `Modified` is an engine-managed UTC timestamp instant. Client-supplied or stale `Modified` timestamps cause clock inversion and break fragment ordering across replicas.
4. **Subversion of Tombstone Protocol (`Deleted`):**  
   `Deleted` is not an arbitrary user property. In JsonPit, deletion is an engine-governed lifecycle transition requiring audited author notes and the mandatory 100-second backdating protocol to resolve race conditions against concurrent writes. Allowing clients to inject `Deleted: true` or `Deleted: false` in general property setters subverts the entire tombstone protocol.

---

## 2. Desired Behavior & Constraints

### 2.1 Engine-Protected Attributes
The attributes `Modified` and `Deleted` are designated **Engine-Protected Lifecycle Attributes**:
- `Modified` is strictly managed by the engine runtime (wall-clock UTC timestamp instant).
- `Deleted` is strictly managed by dedicated tombstone verbs (`delete()`, `delete_item()`, `del`).
- `Id` is the immutable identity key and cannot be altered via property mutation.

### 2.2 Core Library Behavior (C# `RAIkeep.JsonPit` & Python `jsonpit`)
1. **Rejection of Protected Attributes in Property Mutators:**
   - Any invocation of `PitItem.set_property()` / `PitItem.SetProperty()` with a payload containing `Modified` or `Deleted` (case-insensitive) MUST be rejected immediately.
   - Throws:
     - Python: `ProtectedAttributeError` (inherits from `JsonPitError` and `ValueError`).
     - C#: `ProtectedAttributeException` (inherits from `JsonPitException` / `InvalidOperationException`).
   - The entity state must remain untouched (fail-fast, atomic rejection).
2. **Rejection of R-M-W Full-Entity Payloads in Storage APIs:**
   - In `Pit.add()` / `PitStorage.Add()`: If an existing entity is updated, client code must supply sparse mutation fragments rather than writing back full projected state containing protected attributes.
3. **Property Tombstone Guard:**
   - Attempting to tombstone `Id`, `Modified`, or `Deleted` via property tombstone APIs (`delete_property()`, `delete_property_path()`, `del-prop`) MUST be rejected with `TombstoneError` / `TombstoneException`.

### 2.3 CLI Tooling Behavior (`pits` & `jpit`)
1. **`set` Subcommand:**
   - `pits set` and `jpit set` must inspect the JSON5 payload. If `Modified` or `Deleted` is present at the top level, reject immediately with exit code `1` (or `2` for argument error).
   - Stderr message:
     `Error: Cannot manually update protected lifecycle attribute '<attr>'. Use sparse properties only, and use 'del' to delete an entity.`
2. **`put` Subcommand:**
   - `pits put` and `jpit put` must reject any ingested entity object containing `Modified` or `Deleted`.
3. **`del-prop` Subcommand:**
   - `pits del-prop` and `jpit del-prop` must reject attempts to delete `Id`, `Modified`, or `Deleted`.

---

## 3. Suggested Acceptance Tests & "The Hammer"

To guarantee 100% parity and 0% deviation, verification is executed via **The Hammer**—a cross-engine differential conformance test suite that executes bidirectional ("ping-pong") tests across both the C# (`pits`) and Python (`jpit`) implementations.

### 3.1 Declarative Conformance Test Scenarios (`tests/conformance/specs/`)

#### Scenario A: Rejection of R-M-W and Protected Attributes
- **Input:** `jpit set Jazz Sipho '{"Role": "Composer", "Modified": "2026-09-26T20:00:00Z"}'`
- **Expected:** Command fails (exit code $\neq 0$); error message specifies `Modified` is protected; Pit storage remains unmodified.
- **Input:** `jpit set Jazz Sipho '{"Status": "Active", "Deleted": true}'`
- **Expected:** Command fails; error message instructs user to use `del`; Pit storage remains unmodified.
- **Input:** `pits set Jazz Sipho '{"Role": "Composer", "Modified": "2026-09-26T20:00:00Z"}'`
- **Expected:** Identical failure behavior in C# `pits`.

#### Scenario B: Rejection at Library API Level
- **Python:**
  ```python
  item = PitItem("Sipho")
  item.set_property({"Role": "Musician"})  # SUCCEEDS (sparse)
  with pytest.raises(ProtectedAttributeError):
      item.set_property({"Role": "Soloist", "Modified": "2026-09-26T20:00:00Z"})
  with pytest.raises(ProtectedAttributeError):
      item.set_property({"Role": "Soloist", "Deleted": True})
  ```
- **C#:**
  ```csharp
  var item = new PitItem("Sipho");
  item.SetProperty("{\"Role\": \"Musician\"}"); // SUCCEEDS (sparse)
  Assert.Throws<ProtectedAttributeException>(() => 
      item.SetProperty("{\"Role\": \"Soloist\", \"Modified\": \"2026-09-26T20:00:00Z\"}"));
  Assert.Throws<ProtectedAttributeException>(() => 
      item.SetProperty("{\"Role\": \"Soloist\", \"Deleted\": true}"));
  ```

#### Scenario C: Differential "Ping-Pong" Cross-Engine Validation
1. **Step 1 (Python writes):**
   `jpit -r ConformanceTest set Ensemble Miles '{"Instrument": "Trumpet", "Era": "Bop"}'`
2. **Step 2 (C# verifies):**
   `pits -r ConformanceTest get Ensemble Miles`
   - Projected state must have `Instrument == "Trumpet"`, `Era == "Bop"`, `Deleted == false`.
3. **Step 3 (C# writes sparse mutation):**
   `pits -r ConformanceTest set Ensemble Miles '{"Era": "Cool Jazz", "Album": "Kind of Blue"}'`
4. **Step 4 (Python verifies merged projection):**
   `jpit -r ConformanceTest get Ensemble Miles`
   - Projected state must reflect commutative merge: `Instrument == "Trumpet"`, `Era == "Cool Jazz"`, `Album == "Kind of Blue"`.
5. **Step 5 (Python tombstones):**
   `jpit -r ConformanceTest del Ensemble Miles --by "Adele"`
6. **Step 6 (C# verifies deletion):**
   `pits -r ConformanceTest get Ensemble Miles`
   - Must return 404 / not found (or `Deleted == true` with `--with-deleted`).
   - Audit note in history must record `"[<timestamp>] deleted by Adele"`.

---

## 4. Double Acceptance Sign-Off

Formal sign-off required prior to production deployment across both ecosystems.

| Implementation | Lead Authority | Status | Date |
| :--- | :--- | :--- | :--- |
| **AIA Platform** (Requester) | Adele (PM AIA, 7010) | **[ACCEPTED / REQUESTED]** | 2026-09-26 |
| **jsonpit** (Co-Requester / Python Provider) | Adele (Lead Software Architect jsonpit, 7010) | **[ACCEPTED]** | 2026-09-26 |
| **RAIkeep** (C# Provider) | Codex (Lead Custodian, RAIkeep) / Dr. Rainer Burkhardt (`RAI`, Chief Maker) | **[ACCEPTED]** | 2026-09-27 |
