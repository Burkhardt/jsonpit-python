# CR044: Auto-Detect Cloud Storage Providers & Initialize `~/.config/RAIkeep.json5`

> **Naming Schema:** `CR044_AIA_and_jsonpit_to_RAIkeep_Auto-Detect-Cloud-Drives-and-Init-Config.md`

**Date:** 2026-09-28  
**Provider Amendment:** 2026-09-29 — standalone `Amafu` / `amafu` bootstrap CLI  
**Requesting Agents / PMs:** Adele (`7010`, PM AIA & Lead Engineer `jsonpit`), Dr. Rainer Burkhardt (`RAI`, Chief Maker)  
**Target Provider / Repository:** RAIkeep, introducing `Burkhardt/Amafu`  
**Consuming Tools:** `pits` and `jpit`  
**Status:** **Accepted (Provider Amendment Ratified by Adele & RAI)**  
**Target Release:** coordinated `Amafu v4.4.4`, `RAIkeep v4.4.4`, and `jsonpit v4.4.4`  
**Parent CR:** N/A

---

## 1. Objective & Problem Statement

To use `pits` (C#) or `jpit` (`jsonpit`, Python), a machine requires a configuration file at `~/.config/RAIkeep.json5` defining the machine's cloud roots (`Cloud`), temp directory (`TempDir`), and synchronization settings (`SyncPropagationDelayMs`).

### The friction today

1. **Onboarding blind spot:** First-time operators and developers do not know that `pits` and `jpit` require `~/.config/RAIkeep.json5`.
2. **Name mismatch for `jsonpit` users:** Python developers installing `jsonpit` do not naturally intuit that the shared configuration file is named `RAIkeep.json5`.
3. **Manual path archaeology:** Setting up `Cloud: { ... }` requires manually locating cloud-sync paths such as `~/Library/CloudStorage/OneDrive-Personal/OneDriveData/` or `~/Library/CloudStorage/GoogleDrive-user@gmail.com/My Drive/`.
4. **Predictable platform locations:** On macOS, cloud providers normally expose recognizable paths below `~/Library/CloudStorage/` and `~/Library/Mobile Documents/`.
5. **Boundary risk in the original proposal:** Placing discovery and configuration-file creation in `OsLib`, `PitSeeder`, and `jsonpit` would invite mutable configuration APIs, resets of OsLib's global configuration snapshot, duplicated detection logic, and tests that alter the operator's real configuration. Those patterns are explicitly outside the intended RAIkeep architecture.

CR044 therefore introduces one independent bootstrap utility that creates the common configuration consumed by both engines.

---

## 2. Provider Amendment: Dedicated `Amafu` CLI

### 2.1 Name and identity

- **Product and repository:** `Amafu`, in a new `Burkhardt/Amafu` repository.
- **Command:** `amafu`.
- **Meaning:** *amafu* is the isiZulu plural noun for “clouds,” matching a utility that discovers and configures multiple cloud providers.
- **Capitalization:** `Amafu` is used as the product/proper name; lowercase `amafu` is used for the executable and ordinary isiZulu word. `amaFu` is not used.
- **NuGet package identity:** `Amafu`.

The CR title and filename remain unchanged because the requested outcome—automatic cloud discovery and initialization of `RAIkeep.json5`—has not changed.

### 2.2 Language, binary, and dependency boundary

Amafu is implemented in **C# targeting .NET 10** and published as platform-specific **NativeAOT**, self-contained executables.

Runtime invariants:

1. Running a released Amafu binary must not require `dotnet`, a separately installed .NET runtime, Python, Node.js, Deno, Bun, OsLib, JsonPit, or any third-party package.
2. The .NET SDK is a build-time dependency only.
3. Amafu has no project or package dependency on any RAIkeep library. It is deliberately able to bootstrap the configuration before any RAIkeep library is initialized.
4. The initial implementation uses only the .NET base class library and code owned by Amafu.
5. Native release artifacts are produced at least for:
   - macOS ARM64;
   - macOS x64;
   - Linux x64;
   - Linux ARM64;
   - Windows x64.
6. Native debug symbols are separate release/debug artifacts and are not included in the ordinary executable download.
7. Release automation records each executable's byte size. The design target is no more than 5 MiB per stripped executable; exceeding that target requires an explicit release-note explanation rather than silently adding a general-purpose runtime or framework.

Native GitHub Release artifacts are the authoritative runtime-independent distribution. The coordinated release also publishes the `Amafu` NuGet package for .NET-oriented installation and to establish the package identity, but neither `pits` nor `jpit` may depend upon a framework-dependent NuGet installation.

### 2.3 Configuration naming and non-interference invariant

Amafu is a pre-configuration bootstrap boundary. Consequently:

1. Amafu's internal configuration representation is named `AmafuConfiguration`; Amafu does not define or expose a type named `Os.Config` or `OsConfig`.
2. Amafu does not load, reference, mutate, reset, reload, mock, or replace OsLib's `Os.Config`.
3. CR044 adds no mutable configuration seam such as `LoadConfig`, `ResetConfig`, `SetConfig`, or test-only static override to OsLib.
4. OsLib remains a consumer of an already-established configuration; it is not the cloud-drive detector or configuration writer.
5. `pits` and `jpit` do not duplicate Amafu's discovery algorithm.
6. Tests must never edit, replace, delete, or redirect the operator's real `~/.config/RAIkeep.json5`.
7. Tests must never mutate the process's real home-directory environment merely to influence an already initialized global configuration snapshot.
8. Amafu's detection and rendering core receives explicit home, platform, probe roots, and destination values. Only the production entry point resolves the actual current user's home directory.

This amendment supersedes the original placement of detection in OsLib and the original proposal for separate `pits init-config` and `jpit init-config` implementations. When their configuration is absent, those tools may direct the operator to run `amafu init`; they must not grow independent configuration writers.

---

## 3. CLI Contract and RAIkeep Visual Language

### 3.1 Commands

```text
amafu detect [--json]
amafu init [--dry-run] [-f|--force]
```

`amafu init-config` is accepted as a discoverability alias for `amafu init`.

- `detect` scans supported locations and reports discovered provider roots without writing a file.
- `detect --json` emits a stable machine-readable result suitable for diagnostics and integration verification.
- `init` detects providers, renders JSON5, and creates `~/.config/RAIkeep.json5`.
- `init --dry-run` emits the proposed JSON5 without creating or modifying files.
- `init --force` replaces an existing configuration after all validation and rendering have succeeded.

### 3.2 Global flags

- `-h`, `--help`: display help.
- `-v`, `--version`: display the coordinated suite version.
- `-n`, `--nologo`: suppress the banner.
- `-f`, `--force`: permit `init` to replace an existing destination.
- `--dry-run`: render to stdout without writing.
- `--json`: machine-readable detection output where supported.

Global flags must be recognized consistently before or after the verb when their meaning is unambiguous.

### 3.3 Help-screen quality

Amafu is a first-class member of the RAIkeep command family. A small binary is not permission to ship a diminished help screen.

Its help output must use the established RAIkeep visual language:

```text
 ─────────────────────────
 Amafu Cloud Bootstrap CLI
 ─────────────────────────
Commands:              detect, init
  amafu detect [--json]
  amafu init [--dry-run] [-f|--force]

-h, --help              print out all options
-v, --version           print version info
-n, --nologo            do not display the banner
-f, --force             overwrite an existing configuration
    --dry-run           print configuration without writing
```

Help-screen invariants:

1. Use the same JetBrains Nerd Font glyph vocabulary and alignment quality as `pits`, `iorg`, and `raid`.
2. Implement the renderer locally with direct console output and no OsLib or third-party dependency.
3. Keep command and option columns aligned.
4. Avoid truncation and malformed layout on narrow terminals.
5. Document in `README.md` that the output is best viewed with JetBrains Mono Nerd Font, including the established Blink-compatible font guidance.
6. Preserve glyph output; replacing glyphs with numbered textual substitutes is not an acceptable default presentation.

The banner, glyphs, ANSI formatting, and argument parsing are expected to add only a small amount of native code and must not introduce a general CLI framework dependency merely for formatting.

---

## 4. Cloud Provider Detection

### 4.1 macOS probes

The detector inspects an explicitly supplied home root in tests and the actual current user's home in production.

#### OneDrive

- `~/Library/CloudStorage/OneDrive/`
- `~/Library/CloudStorage/OneDrive-Personal/`
- `~/Library/CloudStorage/OneDrive-Personal(2)/`
- `~/Library/CloudStorage/OneDrive-*/`

If a provider root contains an existing `OneDriveData/`, use that directory; otherwise use the provider root.

#### Dropbox

- `~/Library/CloudStorage/Dropbox/`
- `~/Library/CloudStorage/Dropbox-Personal/`
- `~/Library/CloudStorage/Dropbox-*/`

If a provider root contains an existing `DropboxData/`, use that directory; otherwise use the provider root.

#### Google Drive

- `~/Library/CloudStorage/GoogleDrive-*/My Drive/`
- `~/Library/CloudStorage/GoogleDrive/`
- `/Users/Shared/ServerData/GDriveData/`

When applicable, prefer an existing inner `GDriveData/`.

#### iCloud Drive

- `~/Library/Mobile Documents/com~apple~CloudDocs/`
- `~/Library/CloudStorage/ICloudDrive/`

When applicable, prefer an existing inner `ICloudDriveData/`.

### 4.2 Determinism

1. Probe precedence is exactly the documented order.
2. Only confirmed existing directories are emitted as detected providers.
3. Duplicate canonical paths are emitted once.
4. The same fixture tree produces byte-for-byte equivalent provider ordering and JSON5 on every run.
5. Detection is read-only. It must not create provider directories, hydrate cloud placeholders, or write marker files.

### 4.3 Linux, Windows, and no-provider fallback

On platforms without a supported detected provider, Amafu:

- reports which supported categories were checked;
- emits a starter template with clear placeholder guidance;
- does not claim that placeholder paths were detected;
- remains usable through `--dry-run`;
- never creates a cloud root merely to make detection succeed.

---

## 5. Generated Configuration

Amafu renders standard, human-readable JSON5:

```json5
{
  TempDir: "~/temp/",
  LocalBackupDir: "~/backup/",
  SyncPropagationDelayMs: 10000,
  DefaultCloudOrder: [
    // Populated dynamically in detected-provider order
    "OneDrive",
    "Dropbox",
    "GoogleDrive",
    "ICloudDrive"
  ],
  Cloud: {
    // Only providers with confirmed existing paths are written
    "OneDrive": "~/Library/CloudStorage/OneDrive-Personal/OneDriveData/",
    "Dropbox": "~/Library/CloudStorage/Dropbox/DropboxData/",
    "GoogleDrive": "~/Library/CloudStorage/GoogleDrive-user@gmail.com/My Drive/GDriveData/",
    "ICloudDrive": "~/Library/Mobile Documents/com~apple~CloudDocs/ICloudDriveData/"
  },
  Observers: []
}
```

### 5.1 User-space and overwrite safety

1. Amafu runs with ordinary user privileges. On Unix-like systems it rejects execution as root and explains why `sudo` would create the configuration under the wrong home with incorrect ownership.
2. Amafu creates the local `$HOME/.config/` directory only when `init` is authorized to write and it is missing.
3. The generated file is user-owned and uses mode `0644` on Unix-like systems.
4. If `~/.config/RAIkeep.json5` already exists, `init` refuses deterministically rather than prompting or overwriting:

   ```text
   Configuration file already exists at '~/.config/RAIkeep.json5'. Use --force (-f) to overwrite.
   ```

5. `--force` affects only the resolved configuration file. It never deletes or replaces a directory.
6. `--dry-run` performs no filesystem writes, including creation of `$HOME/.config/`.
7. Amafu never stages files or directories in `TempDir`, and it never moves anything into or across a cloud root.
8. The JSON5 payload is completely rendered and validated before the destination is opened for writing.

---

## 6. Testing Requirements

### 6.1 Pure and fixture-based tests

Tests use explicit, isolated fixture roots and destination paths. They do not use or alter the operator's real home or configuration.

Required coverage:

1. OneDrive, Dropbox, Google Drive, and iCloud detection for every documented candidate form.
2. Inner data-directory preference and provider-root fallback.
3. Wildcard candidate ordering, deduplication, and deterministic output.
4. Clean creation when the destination does not exist.
5. Exact refusal and zero mutation when the destination exists without `--force`.
6. Successful replacement with `--force`.
7. `--dry-run` output with no directory or file creation.
8. Non-macOS and no-provider starter-template behavior.
9. Rejection of root/`sudo` execution through an injected runtime identity in tests rather than actually elevating the test process.
10. JSON5 escaping for spaces, `~`, parentheses, email-like path components, Unicode, and platform separators.

### 6.2 CLI and presentation tests

1. Snapshot coverage for the main help screen and command-specific help.
2. `-h` and `--help` parity.
3. `-v` and `--version` parity.
4. `-n` and `--nologo` behavior.
5. Global flags before and after verbs.
6. Stable help-column alignment and narrow-terminal behavior.
7. Preservation of the approved Nerd Font glyphs.

### 6.3 Native artifact verification

For every supported runtime identifier:

1. Publish a NativeAOT executable.
2. Run `--version` and `--help` smoke tests on a matching runner where available.
3. Verify that the released executable does not require an installed .NET runtime.
4. Record the executable's SHA-256 checksum and byte size.
5. Publish checksums beside the native artifacts.

---

## 7. Consumer Contract for `pits` and `jpit`

1. Amafu is the single owner of cloud-root auto-detection and initial configuration generation.
2. `pits` and `jpit` continue consuming the same `~/.config/RAIkeep.json5` shape.
3. Neither consumer requires the Amafu process during normal operation after configuration exists.
4. A missing-configuration diagnostic may say:

   ```text
   RAIkeep configuration was not found at '~/.config/RAIkeep.json5'. Run 'amafu init' to detect cloud providers and create it.
   ```

5. Consumers may use the stable `amafu detect --json` subprocess contract for an explicitly requested diagnostic workflow, but must not silently invoke Amafu or rewrite configuration during ordinary reads.
6. Python `jpit` must be able to use a downloaded native Amafu binary without installing .NET.
7. Cross-engine acceptance verifies that the generated file is consumable unchanged by both `pits` and `jpit` without rewriting.

---

## 8. Coordinated Release and Repository Integration

Amafu becomes a RAIkeep umbrella submodule and the **first package/tool processed by the release chain after the umbrella release marker**. Its addition brings the coordinated RAIkeep suite to nine packages/tools.

The v4.4.4 order is:

```text
RAIkeep umbrella label
→ Amafu
→ OsLib
→ RaiUtils
→ RaiImage
→ RaiDiagram
→ RaidSeeder
→ JsonPit
→ ImgSeeder
→ PitSeeder
```

Release requirements:

1. `scripts/release-chain.sh 4.4.4` preflights Amafu with the other RAIkeep repositories.
2. Amafu's repository, project metadata, help/version output, NuGet publication, Git tag, GitHub Release, checksums, and native artifacts all report `4.4.4`.
3. The release chain waits for Amafu's required publication endpoints and GitHub workflow before proceeding to OsLib.
4. Release recovery supports resuming after Amafu without recreating immutable tags.
5. RAIkeep release notes reference this exact filename:
   `CR044_AIA_and_jsonpit_to_RAIkeep_Auto-Detect-Cloud-Drives-and-Init-Config.md`.
6. No tags, GitHub Releases, or NuGet packages are published before RAI manually starts the coordinated release chain.

---

## 9. Acceptance Scenarios

1. **Clean macOS initialization:** Given an isolated home fixture containing `Library/CloudStorage/OneDrive-Personal/OneDriveData/`, `amafu init` creates a user-readable `RAIkeep.json5` whose primary provider is the detected OneDrive path.
2. **Existing configuration:** Given an existing destination, `amafu init` exits nonzero, prints the exact overwrite diagnostic, and leaves the file byte-for-byte unchanged.
3. **Forced regeneration:** `amafu init --force` regenerates only the destination file.
4. **Dry run:** `amafu init --dry-run` emits JSON5 and creates no filesystem entry.
5. **Read-only detection:** `amafu detect` creates and modifies nothing.
6. **Standalone operation:** A NativeAOT artifact runs successfully on a clean matching machine without `dotnet` installed.
7. **CLI consistency:** `amafu -h` presents the aligned RAIkeep-style banner, commands, options, and approved glyphs.
8. **Shared consumption:** The same generated file is accepted by released `pits` and `jpit` without rewriting.
9. **Sacred configuration boundary:** No CR044 test or implementation path mutates OsLib's `Os.Config` or the operator's actual configuration; Amafu uses its own `AmafuConfiguration` representation.
10. **Manual gate:** Preparation stops before tagging or publication so RAI can run `scripts/release-chain.sh 4.4.4` manually.

---

## 10. Requester Decision & Formal Ratification

Adele (`7010`, PM AIA & Lead Engineer `jsonpit`) and Dr. Rainer Burkhardt (`RAI`, Chief Maker) have reviewed and **unanimously ratified** this provider amendment on 2026-09-29:

1. **Standalone `Amafu` repository and `amafu` command:** **Approved**. Decouples initial bootstrapping cleanly from engine runtime.
2. **C#/.NET 10 NativeAOT self-contained binaries:** **Approved**. Provides zero-dependency native execution (< 5 MiB) across macOS, Linux, and Windows without requiring .NET, Python, or Node runtimes.
3. **Preservation of OsLib's Immutable Boundary:** **Approved**. Prohibiting mutable configuration APIs or dynamic reloading preserves OsLib's architectural integrity.
4. **Replacement of duplicated `pits init-config` / `jpit init-config`:** **Approved**. `pits` and `jpit` will guide the user to `amafu init` when configuration is absent, eliminating duplicate probe logic across C# and Python.
5. **Release Chain Integration:** **Approved**. `Amafu v4.4.4` will be the first tool processed in the coordinated `RAIkeep v4.4.4` and `jsonpit v4.4.4` release chain.
6. **Full-Quality RAIkeep Nerd Font Visual Language:** **Approved**. Preserves the signature CLI aesthetic.

**Status: Approved for Implementation in coordinated release `Amafu v4.4.4` / `RAIkeep v4.4.4` / `jsonpit v4.4.4`.**
