# CR044: Auto-Detect Cloud Storage Providers & Initialize `~/.config/RAIkeep.json5`

> **Naming Schema:** `CR044_AIA_and_jsonpit_to_RAIkeep_Auto-Detect-Cloud-Drives-and-Init-Config.md`  

**Date:** 2026-09-28  
**Requesting Agents / PMs:** Adele (`7010`, PM AIA & Lead Engineer `jsonpit`), Dr. Rainer Burkhardt (`RAI`, Chief Maker)  
**Target Providers / Repos:** RAIkeep (`pits` CLI / `OsLib`), `jsonpit` (`jpit` CLI)  
**Status:** **Proposed**  
**Target Release:** `RAIkeep v4.4.4` & `jsonpit v4.4.4` (Strict Lockstep Parity)  
**Parent CR:** N/A  

---

## 1. Objective & Problem Statement

To use `pits` (C#) or `jpit` (`jsonpit` Python), a machine requires a configuration file at `~/.config/RAIkeep.json5` defining the machine's cloud roots (`Cloud`), temp directory (`TempDir`), and synchronization settings (`SyncPropagationDelayMs`).

### The Friction Today:
1. **Onboarding Blindspot:** First-time operators and developers do not know that `pits` and `jpit` require `~/.config/RAIkeep.json5`.
2. **Name Mismatch for `jsonpit` Users:** Python developers installing `pip install jsonpit` do not naturally intuit that the configuration file is named `RAIkeep.json5`.
3. **Manual Path Archaeology:** Setting up `Cloud: { ... }` requires manually hunting down obscure cloud sync paths on disk (e.g., `~/Library/CloudStorage/OneDrive-Personal/OneDriveData/` or `~/Library/CloudStorage/GoogleDrive-user@gmail.com/My Drive/`), which is tedious, error-prone, and fragile.
4. **Predictable macOS Locations:** On macOS (via FileProvider and standard CloudStorage integration), cloud providers install to highly standardized, predictable paths under `~/Library/CloudStorage/` and `~/Library/Mobile Documents/`.

---

## 2. Desired Behavior & Specification

Introduce a dedicated initialization command into both CLI toolchains:
- C# CLI: **`pits init-config`** (and alias `pits init`)
- Python CLI: **`jpit init-config`** (and alias `jpit init`)

### 2.1 Out-of-the-Box Cloud Provider Detection (macOS)
The command inspects the user's home directory (`$HOME` / `~`) for well-known cloud sync directories:

1. **OneDrive:**
   - Probe `~/Library/CloudStorage/OneDrive/`
   - Probe `~/Library/CloudStorage/OneDrive-Personal/`
   - Probe `~/Library/CloudStorage/OneDrive-Personal(2)/`
   - Probe `~/Library/CloudStorage/OneDrive-*/`
   - If a provider root exists, check for an existing inner `OneDriveData/` directory; if found, wire to `.../OneDriveData/`, otherwise wire to the provider root.
2. **Dropbox:**
   - Probe `~/Library/CloudStorage/Dropbox/`
   - Probe `~/Library/CloudStorage/Dropbox-Personal/`
   - Probe `~/Library/CloudStorage/Dropbox-*/`
   - If found, check for an existing inner `DropboxData/`; if present, wire to `.../DropboxData/`, otherwise wire to the provider root.
3. **Google Drive:**
   - Probe `~/Library/CloudStorage/GoogleDrive-*/My Drive/`
   - Probe `~/Library/CloudStorage/GoogleDrive/`
   - Probe `/Users/Shared/ServerData/GDriveData/`
   - If found, check for inner `GDriveData/`.
4. **iCloud Drive:**
   - Probe `~/Library/Mobile Documents/com~apple~CloudDocs/`
   - Probe `~/Library/CloudStorage/ICloudDrive/`
   - If found, check for inner `ICloudDriveData/`.

### 2.2 Generated Configuration Shape
The command generates a clean, formatted JSON5 configuration file:

```json5
{
  TempDir: "~/temp/",
  LocalBackupDir: "~/backup/",
  SyncPropagationDelayMs: 10000,
  DefaultCloudOrder: [
    // Populated dynamically in order of detected providers
    "OneDrive",
    "Dropbox",
    "GoogleDrive",
    "ICloudDrive"
  ],
  Cloud: {
    // Only detected providers with confirmed existing paths are written
    "OneDrive": "~/Library/CloudStorage/OneDrive-Personal/OneDriveData/",
    "Dropbox": "~/Library/CloudStorage/Dropbox/DropboxData/",
    "GoogleDrive": "~/Library/CloudStorage/GoogleDrive-user@gmail.com/My Drive/GDriveData/",
    "ICloudDrive": "~/Library/Mobile Documents/com~apple~CloudDocs/ICloudDriveData/"
  },
  Observers: []
}
```

### 2.3 CLI Flags & Safety Rules
1. **No `sudo` (User-Space Security Invariant):**
   - The command must run with normal user privileges. `$HOME/.config/` is standard XDG user space. 
   - The CLI creates `$HOME/.config/` if it does not already exist, owned cleanly by the current user. Running with `sudo` is explicitly prohibited (which would corrupt permissions to `root:wheel` and resolve `~` to `/var/root/`).
2. **Safety Against Overwriting:**
   - If `~/.config/RAIkeep.json5` already exists, `pits init-config` **must not** overwrite it silently.
   - It prints a summary of the existing configuration and prompts the user or requires `--force` (`-f`) to overwrite.
3. **`--dry-run` Option:**
   - Prints the detected cloud paths and the generated JSON5 payload to stdout without writing to disk.

### 2.4 Non-macOS Fallback (Linux & Windows)
On non-macOS platforms (or when no cloud providers are detected):
- The CLI outputs a helpful diagnostic indicating which paths were checked.
- Generates a starter template with placeholder paths and instructions, allowing the operator to quickly fill in their mount points.

---

## 3. Acceptance Tests

1. **Clean Installation on macOS:**
   - Given a machine with `~/Library/CloudStorage/OneDrive-Personal` existing.
   - Operator runs `pits init-config` (or `jpit init-config`).
   - File `~/.config/RAIkeep.json5` is created with user ownership (`644`).
   - `Cloud.OneDrive` points to the detected OneDrive path.
   - `DefaultCloudOrder` includes `"OneDrive"` as primary.
2. **Idempotency & Overwrite Guard:**
   - Given `~/.config/RAIkeep.json5` already exists.
   - Operator runs `pits init-config` without `--force`.
   - The command refuses to overwrite, reporting: `Configuration file already exists at '~/.config/RAIkeep.json5'. Use --force to overwrite.`
3. **Force Overwrite:**
   - Operator runs `pits init-config --force`.
   - The file is regenerated cleanly.
4. **Dry Run:**
   - Operator runs `pits init-config --dry-run`.
   - Emits the JSON5 payload to stdout; no file is created or modified on disk.
5. **Cross-Engine Parity:**
   - Both C# `pits` and Python `jpit` produce identical, interoperable JSON5 configuration files.
