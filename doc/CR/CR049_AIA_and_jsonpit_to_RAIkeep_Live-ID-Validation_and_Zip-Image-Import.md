# CR049 — Live ID Validation, ZIP Image Ingestion, and Receipt Persistence

| Metadata | Ratification Specification |
| :--- | :--- |
| **CR Number** | **CR049** |
| **Title** | Live ID Validation, ZIP Image Ingestion, and Receipt Persistence |
| **Originating Agent** | Adele (`7010`, AIA Product Manager) |
| **Author / Requestor** | Dr. Rainer Burkhardt (`RAI`, Chief Product & Technology Officer) |
| **Drafting Agent** | RAIkeep Codex Agent |
| **Implementing Providers** | `RAIkeep` (C#) and `jsonpit-python` (Python) |
| **C# Target Components** | `JsonPit`, `PitSeeder` (`pits`), `ImgSeeder` (`iorg`), `RaiImage`, `OsLib` |
| **Python Target Components** | `jsonpit` (Core Library), `jpit` (CLI) |
| **Target Release** | `RAIkeep v4.4.6` / `jsonpit-python v4.4.6` |
| **Date** | 2026-10-01 |
| **Status** | **Ratified Platform Mandate** |

---

## 1. Problem Statement and Strategic Motivation

Two operational observations from live multi-domain production motivate this unified change request:

1. **Unexpanded Template Placeholders in Living Pits:**  
   Operator inspection of live pit data revealed entities with unexpanded template placeholders such as `{AdminPersonId}` or `<AdminPersonId>`. Because `PitSeeder` and `jsonpit` historically only enforced non-empty string checks on `Id`, an unexpanded template string was treated as a valid identifier and committed as a ghost entity.
2. **Autonomous ZIP Image Ingestion for Show Activities:**  
   The flagship `ImportPhotos` workflow (e.g. `ImportPhotosSDSU20260928`) receives multi-gigabyte ZIP archives (from Uwe via Google Photos or photographer uploads). The platform requires a headless, deterministic mechanism to:
   - Ingest images from local ZIP archives (or direct HTTPS endpoints) into the tenant's canonical 8x2 ImageServer tree (`ImagesRoot/<Domain>/<ItemIdTree8x2>/`).
   - Emit an authoritative, machine-readable JSON receipt (`Class: "ImageImport"`).
   - Ingest that receipt through standard input (`--source -`) into living pits (`Object.pit` / `Activity.pit`) using either `pits` or `jpit`.

This CR unifies these two deliverables because they constitute the complete trust boundary for external data ingestion: **guaranteeing clean entity identities at the write door while enabling fully automated media ingestion receipts.**

---

## 2. Ownership Architecture and Boundary Invariants

```
                      ┌────────────────────────────────────────────────┐
                      │              Caller / Activity                 │
                      │  (ImportPhotosSDSU20260928 / Umshadisi 7008)   │
                      └───────┬───────────────────────────────┬────────┘
                              │ 1. Ingest Archive             │ 3. Pipe Receipt
                              ▼                               ▼
                   ┌────────────────────┐          ┌───────────────────────┐
                   │ ImgSeeder (`iorg`) │          │  PitSeeder (`pits`)   │
                   │                    │          │    or jpit (Python)   │
                   │ • Extracts ZIP     │          │  • Reads stdin (-)    │
                   │ • Normalizes 8x2   │          │  • Preflights batch   │
                   │ • Emits Receipt    │          │  • Prohibits { and <  │
                   └──────────┬─────────┘          └───────────┬───────────┘
                              │ 2. Emits JSON                  │ 4. Commits
                              └───────────────┐  ┌─────────────┘
                                              ▼  ▼
                                      ┌──────────────────┐
                                      │   Core JsonPit   │
                                      │  (C# & Python)   │
                                      │ • Rejects { & <  │
                                      │ • Living State   │
                                      └──────────────────┘
```

| Component | Ingestion Responsibility | Boundary Invariant |
| :--- | :--- | :--- |
| **C# `JsonPit`** | Rejects `{` and `<` in live entity IDs at public write boundaries (`Add`, `Put`). | **Core Defense:** Direct library callers cannot bypass the rule. General deserialization and historical replay remain unhindered. |
| **PitSeeder (`pits`)** | Whole-batch preflight validation before opening target pit; accepts standard input (`--source -`). | **Fail-Fast CLI:** Zero filesystem mutations, directory creations, or process flags if any entity in the batch is invalid. |
| **Python `jsonpit`** | Mirrors C# `JsonPit` ID validation and preflight semantics in `put` and batch ingestion. | **100% Lockstep Parity:** Python agents cannot introduce identities that C# rejects. |
| **`jpit` (Python CLI)** | Whole-batch preflight on `put` and `seed`; accepts standard input (`-`). | **CLI Parity:** Supports piping receipts directly into living pits on Python runtimes. |
| **ImgSeeder (`iorg`)** | Reads ZIP archives, enforces canonical RaiImage 8x2 naming, writes files, emits JSON receipt. | **Data Only:** `iorg` does not mutate pits or trigger activities; caller orchestrates receipt persistence. |
| **RaiImage / OsLib** | Retains canonical `ItemIdTree8x2` layout and in-place CloudSafe invariants (CR022). | **No Cloud Races:** Never moves temporary files into cloud directories; streams directly to final targets. |

---

## 3. Deliverable A — Prohibit Template Markers in Live Entity IDs

### 3.1 The Canonical Identifier Invariant

A live incoming entity identifier (`Id`) must be a non-empty string and **must not contain either literal character `{` or `<` anywhere in the decoded string**.

- **Forbidden Examples:** `{AdminPersonId}`, `<AdminPersonId>`, `Person{Suffix}`, `Activity<Pending>`, `{"id": "foo"}`.
- **Evaluation Point:** Applied after JSON/JSON5 string unescaping.
- **Strict Rejection:** The engine must reject with an error; it must never silently trim, substitute, or auto-generate a fallback ID.
- **Scope Restriction:** The restriction applies strictly to the entity's own primary `Id`. Ordinary fields (`Name`, `Note`, `EMail`, descriptions) may contain braces or angle brackets.
- **Universality:** Applies to all live creation and mutation operations, including `--patch` / `--require-existing` (CR047).

### 3.2 Whole-Batch Preflight and Actionable Diagnostics

Both `pits` and `jpit` must validate **all** entities in an incoming payload before applying any mutations:
- If entity 1 is valid but entity 5 contains `{Placeholder}`, **zero entities must be applied**.
- Rejection must occur before acquiring master locks, writing ephemeral process flags, or touching pit files.

**Authoritative Error Format (stderr, Exit Code 1):**
```text
error: Entity Id '{AdminPersonId}' contains a prohibited template marker ('{' or '<'). Resolve template placeholders before writing to a Pit.
```

### 3.3 Historical Preservation and Clean Recovery

- **Replay Safety:** Existing historical pits containing legacy placeholder IDs must continue to be readable, queryable, exportable, and replayable. Loading an existing pit must not crash or fail.
- **Targeted Tombstone / Deletion:** Explicit deletion or tombstoning of legacy invalid IDs via `pits delete-item <Pit> <Id>` remains permitted to enable operators to purge historical anomalies. Re-creating the invalid ID is blocked.

---

## 4. Deliverable B — ZIP Image Ingestion and JSON Receipts

### 4.1 CLI Surface in `iorg`

Extend the `organize` command in `iorg`:

```bash
# Ingest from local ZIP archive
iorg organize --source <path-to-archive.zip> --import-id <ImportId> [--activity-id <ActivityId>] --json [options]

# Ingest from direct HTTPS ZIP URL
iorg organize --source-url <https-url> --import-id <ImportId> [--activity-id <ActivityId>] --json [options]
```

- `--source` and `--source-url` are mutually exclusive.
- `--import-id <Id>` is required when `--json` is supplied; it defines the `Id` of the resulting `ImageImport` receipt.
- The supplied `ImportId` and optional `ActivityId` are subject to the Deliverable A validation rule (no `{` or `<`).
- Standard `--root`, `--app` / `--tenant`, and naming convention options (`--pathconv 3` for `ItemIdTree8x2`) remain authoritative.

### 4.2 Security, Bounds, and Extraction Invariants

1. **Path-Traversal Defense:** Reject any archive entry containing `..`, absolute paths, or symlinks.
2. **Resource Quotas (Rainer amendment, 2026-10-01):** Limits on archive bytes, expanded bytes, entry count, and download duration are opt-in CLI parameters. No application-imposed defaults. Validate configured bounds before extraction and verify extracted sizes afterward; OS storage constraints still apply.
3. **Canonical 8x2 Placement:** Each image is normalized via `RaiImage` into `ImagesRoot/<Tenant>/<ItemIdTree8x2>/<ShortName>.<ext>`.
4. **Collision Handling:** If an identical file exists at the target, mark `Unchanged`. If a different file exists at the target, report collision error; never silently overwrite.
5. **CR022 Cloud-Safe Invariant:** Any temporary download/extraction workspace must reside in OS temp space, outside the CloudDrive. Files are written directly to their canonical destination.

### 4.3 The Authoritative Receipt Contract (`Class: "ImageImport"`)

When `--json` is specified, `iorg` outputs **strictly valid JSON to stdout** (prose, banners, and progress indicators go to stderr).

```json
{
  "Id": "ImportPhotos-20261001-001",
  "Class": "ImageImport",
  "ReceiptVersion": 1,
  "ActivityId": "ImportPhotosSDSU20260928",
  "Status": "Completed",
  "Tenant": "AfricaStage",
  "Source": {
    "Kind": "Zip",
    "Name": "Nomsa-1-001.zip"
  },
  "Summary": {
    "Copied": 193,
    "Unchanged": 0,
    "Skipped": 995,
    "Failed": 0
  },
  "Files": [
    {
      "SourceEntry": "Nomsa/Nomsa_San_Diego_State_0001.jpg",
      "ItemId": "NomsaSanDiegoState",
      "ImageNumber": 1,
      "RelativePath": "NomsaSan/NomsaSanDi/NomsaSanDiegoState_01.jpg",
      "Exif": {"DateTimeOriginal": "2026-09-28T17:40:31-07:00"},
      "Status": "Copied"
    }
  ]
}
```

- **Status Taxonomy:**
  - `Completed` (Exit Code 0): All eligible images copied or verified unchanged.
  - `Partial` (Exit Code 1): Some images imported, but one or more failures occurred.
  - `Failed` (Exit Code 1): Extraction, download, or preflight failure.

---

## 5. Deliverable C — Receipt Ingestion via Stdin (`pits` & `jpit`)

To allow seamless piping from `iorg` into living pits, both `pits` and `jpit` must support standard input via `-`:

```bash
# C# PitSeeder
pits seed <PitName> --source - [options]

# Python jpit
jpit put <PitName> - [options]
jpit seed <PitName> - [options]
```

### 5.1 End-to-End Orchestration Pattern

The caller (e.g. `import-photos.ts` or shell script) buffers the receipt, verifies the exit code, and commits the receipt entity:

```bash
# 1. Ingest images and capture receipt
iorg organize --source /Volumes/NVMe/GooglePhotos/Nomsa/Nomsa-1-001.zip \
  --root /Users/RSB/Library/CloudStorage/OneDrive/OneDriveData/AfricaStage/Image \
  --tenant AfricaStage --pathconv 3 \
  --import-id "ImportPhotos-20261001-SDSU" \
  --activity-id "ImportPhotosSDSU20260928" \
  --json > /tmp/import-receipt.json

# 2. Assert success before committing receipt to Object.pit
if [ $? -eq 0 ]; then
  pits seed Object --source - \
    -r /Users/RSB/Library/CloudStorage/OneDrive/OneDriveData/AfricaStage < /tmp/import-receipt.json
fi
```

---

## 6. Comprehensive Acceptance Matrix

| ID | Test Scenario | Expected Outcome | Engine |
| :--- | :--- | :--- | :--- |
| **A01** | Attempt to seed entity with `Id: "{AdminPersonId}"` or `<Pending>` | Hard error before mutation; exit code 1; diagnostic to stderr. | `pits` & `jpit` |
| **A02** | Batch containing valid entity followed by `{InvalidId}` | Zero entities committed; no target directories or lockfiles created. | `pits` & `jpit` |
| **A03** | Valid entity `Id` with `{value}` or `<tag>` inside `Note` or `Name` | Accepted and committed verbatim; no false-positive rejection. | `pits` & `jpit` |
| **A04** | Direct C# / Python library calls: `pit.Add(itemWithPlaceholderId)` | Throws `ArgumentException` before changing in-memory state. | `JsonPit` (C# & Py) |
| **A05** | Historical pit containing existing `{Placeholder}` records | Loads and exports cleanly; `delete-item` purges it; re-insert fails. | `pits` & `jpit` |
| **B01** | Ingest ZIP containing 193 target concert images | Extracted, sanitized to 8x2 tree, receipt emitted with `Copied: 193`. | `iorg` |
| **B02** | ZIP containing path traversal (`../../evil.jpg`) | Immediate rejection during preflight; zero bytes written to image tree. | `iorg` |
| **B03** | Re-running ingestion of identical ZIP | Reports `Unchanged: 193`, `Copied: 0`; zero duplicate files written. | `iorg` |
| **B04** | Ingestion with `--json` flag | Strictly valid JSON receipt on stdout; diagnostics on stderr. | `iorg` |
| **C01** | Pipe JSON receipt into `pits seed Object --source -` | Successfully commits `Class: "ImageImport"` entity into `Object.pit`. | `pits` |
| **C02** | Pipe JSON receipt into `jpit seed Object -` | Successfully commits identical entity into `Object.pit`. | `jpit` |
| **C03** | Malformed or empty JSON piped via stdin | Fails with non-zero exit; zero changes committed to pit. | `pits` & `jpit` |

---

## 7. Handover and Implementation Mandate

- **Ratification:** This specification is approved and ratified by Adele (`7010`) on behalf of AIA Platform Governance.
- **Action for RAIkeep Codex Agent:** Implement Deliverables A, B, and C in `RAIkeep` (`JsonPit`, `PitSeeder`, `ImgSeeder`), publish `v4.4.6`, and coordinate lockstep implementation with `jsonpit-python v4.4.6`.

## 8. Rainer's implementation clarifications (2026-10-01)

- Retain existing RaiImage/ImageTreeFile naming behavior; no separate ZIP renaming policy.
- On macOS and Ubuntu use the native `unzip` CLI through asynchronous `RaiSystem` execution into OS temporary storage. Keep archive preflight, collision checks, direct final writes, cancellation, and failure receipts. Insufficient temporary disk space is an import failure, not a reason to bypass staging.
- Offer `--exif` on both `iorg list` and `iorg organize`, accepting `*`, individual tags, comma-separated selectors, and dotted group selectors.
- Emit structured EXIF objects with matching date/offset pairs converted to C# `DateTimeOffset`; group thumbnail/lens/focal-plane/exposure fields. Preserve unconvertible values with diagnostics. No `Captured` alias and no filesystem or local-timezone fallback.
- Rainer runs the release chain. Adele owns Python implementation and release parity; this repository provides the C# reference and acceptance evidence, without asserting Python completion.

The ratified matrix above ends at B04/C03 and differs in numbering from the
original draft. Its rows remain authoritative. The requested additional draft
coverage is retained as B05 (direct HTTPS, rejection of share pages and credential
redaction), B06 (strict JSON stdout including debug mode), and C04 (repeat import
and cloud-safe final writes). Partial copy failures and collision handling are
also covered independently of the numbering.
