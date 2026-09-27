# CR041: Restore Clean Change Filenames by Removing Redundant SHA-256 Hashes

> **Naming Schema:** `CR<NNN>_<Requester>_to_<Provider>_<Topic>.md`  
> **Follow-up Sub-CR Schema:** `CR<NNN>.<M>_<Requester>_to_<Provider>_<Topic>.md`  
> **Immutability Rule:** The provider agent must NEVER rename or modify this document filename.

**Date:** 2026-09-26  
**Requesting Agent / PM:** Adele (PM AIA, 7010) & Adele (Lead Software Architect jsonpit, 7010)  
**Target Provider / Repo:** `RAIkeep` (C# / `JsonPit` / `pits` — Custodian: Codex) & `jsonpit` (Python / `jpit`)  
**Status:** Proposed (Accepted by Requesters; Awaiting Codex Resumption)  
**Parent CR:** N/A (Supersedes CR003 filename elongation)  
**Parity Invariant:** 100% C# / Python Parity (0% Deviation)

---

## 1. Objective & Context

### 1.1 The CR003 Elongation Problem
In `JsonPit` v3.13.2 (CR003), ordinary change files were modified to append a full 64-character SHA-256 content hash:
```
{Modified.UtcTicks}_{ExactProcessIdentity}_{Sha256}.json
```
Example:
```
639260698972496240_Nkosikazi-pits-41360_c22b001cee7daff1eb5628212822177b9c94067b60e1a10b45dc7521db03295a.json
```

While the intent in CR003 was to guard against partial/torn cloud sync writes and enforce idempotency, appending a 64-character cryptographic hash introduces severe operational defects:
1. **Unusable in File Managers & UI Tooling:**  
   At ~110 characters, filenames are truncated in macOS Finder, Windows File Explorer, and Cloud Web UIs (OneDrive, Dropbox), rendering directories unreadable to operators and developers.
2. **Windows `MAX_PATH` Danger:**  
   Windows systems with default 260-character path limits easily throw `PathTooLongException` when a 110-character filename sits nested inside typical cloud storage paths (e.g., `C:\Users\username\OneDrive\OneDriveData\AfricaStage\Activity\`).
3. **Cryptographic Overkill:**  
   A 64-character SHA-256 hash ($2^{256}$ space) is designed for adversarial public blockchains. For a private cloud directory, appending 64 characters is unnecessary overhead.
4. **Multi-Domain Living Stage Telemetry in AIA:**  
   Under AIA's domain quartet architecture (`ADR-0007`), pits are arranged in nested hierarchies:  
   `~/Library/CloudStorage/OneDrive/OneDriveData/{Domain}/{PitName}/Events/`  
   When living stage activities emit changes across multiple agents (Zébio, Alan, Umshadisi, tenant agents), 110-character filenames cause terminal listings (`ls -l`, audit logs) and IDE file trees to wrap unreadably, severely degrading visual triage and runtime diagnostics.

### 1.2 The Clean Pre-CR003 Format is Already Unconditionally Unique
The original clean format:
```
{Modified.UtcTicks}_{ExactProcessIdentity}.json
e.g. 639260698972496240_Nkosikazi-pits-41360.json
```
already provides absolute, collision-free uniqueness across the universe:
- **`UtcTicks` (18 digits):** 100-nanosecond monotonic resolution (10,000,000 ticks per second). It is physically impossible for a single process to execute two separate mutations at the identical 100-nanosecond instant.
- **`ExactProcessIdentity`:** Composed of `{MachineName}-{Subscriber/ProcessName}-{PID}`. No two machines or distinct operating system processes can collide.

Torn-write protection is already cleanly provided by:
1. In-place sibling temporary writes (`safe_write_in_place` / atomic rename).
2. Standard strict JSON parse validation upon discovery (`json.loads` / `JToken.Parse`), where an incomplete payload is safely skipped until sync completion.

---

## 2. Desired Behavior & Constraints

### 2.1 File Naming Specification
1. **New Change Files:**  
   Both C# (`JsonPit`) and Python (`jsonpit`) must generate ordinary change filenames using the clean format:
   ```
   {UtcTicks}_{Machine}-{Subscriber}-{PID}.json
   ```
   Matching receipt files:
   ```
   {UtcTicks}_{Machine}-{Subscriber}-{PID}.receipt
   ```
2. **Backward Compatibility:**  
   Both engines must continue to read and merge existing 3-segment hashed change files (`{ticks}_{identity}_{sha256}.json`) encountered on disk, ensuring seamless rolling upgrades across distributed cloud drives.

### 2.2 Validation Protocol
1. **Integrity Validation:**  
   Change files are validated by parsing their canonical JSON structure. A file that fails JSON parsing (e.g. while cloud synchronization is mid-transit) is deferred until the next pass.
2. **Maintenance & Compaction:**  
   The maintenance routine (`pits maintain` / `jpit compact`) treats `{ticks}_{identity}.json` as primary, standard change files, merging them into canonical `.pit` snapshots and issuing `.receipt` cleanup tokens.

---

## 3. Suggested Acceptance Tests

### Scenario A: Clean Filename Generation
- **Action:** Execute a non-master sparse mutation via CLI:
  `jpit -r TestRoot set Jazz Sipho '{Role: "Musician"}'` (or via C# `pits`).
- **Assertion:** The created change file matches regex:
  `^[0-9]{18}_[A-Za-z0-9\.\-]+-[A-Za-z0-9\.\-]+-[0-9]+\.json$`
- **Negative Assertion:** Filename does NOT contain a 64-character hex suffix.

### Scenario B: Bidirectional Cross-Engine Merge
1. **C# Writes Clean Format:**  
   `pits` generates `639260698972496240_Nkosikazi-pits-41360.json`.
2. **Python Merges:**  
   `jpit` discovers and folds the clean change file into `Jazz.pit`.
3. **Python Writes Clean Format:**  
   `jpit` generates `639260698972496250_Nkosikazi-jpit-41370.json`.
4. **C# Merges:**  
   `pits maintain` / `pits export` discovers and folds the clean change file with zero warnings or deferrals.

---

## 4. Double Acceptance Sign-Off

| Implementation | Lead Authority | Status | Date |
| :--- | :--- | :--- | :--- |
| **AIA Platform** (Platform Authority) | Adele (PM AIA, 7010) | **[ACCEPTED / REQUESTED]** | 2026-09-26 |
| **jsonpit** (Python Lead) | Adele (Lead Software Architect jsonpit, 7010) | **[ACCEPTED]** | 2026-09-26 |
| **RAIkeep** (C# Provider) | Codex (Lead Custodian, RAIkeep) / Dr. Rainer Burkhardt (`RAI`, Chief Maker) | **[ACCEPTED]** | 2026-09-27 |
