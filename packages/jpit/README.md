# jpit (v4.4.4)

> **The developer and AI agent companion CLI for [jsonpit](https://pypi.org/project/jsonpit/) — daemon-free distributed storage over Cloud Drives.**  
> *100% lockstep parity with C# `pits v4.4.4` in [RAIkeep](https://github.com/Burkhardt/RAIkeep).*

`jpit` provides high-performance semantic living state search ("Pit-Grep"), time-travel inspection, and cloud-safe distributed ingestion across replicated JsonPits on OneDrive, Dropbox, and Google Drive.

---

## Installation & Upgrade

### Recommended: Global CLI via `pipx` (Isolated)
Install `jpit` in an isolated environment without dependency conflicts across your system:

```bash
# Install jpit globally
pipx install jpit

# Upgrade to latest lockstep release (v4.4.4)
pipx upgrade jpit
```

### In a Project / Virtual Environment via `pip`
```bash
# Install
pip install jpit

# Upgrade
pip install --upgrade jpit
```

### Upgrading with Multi-Python / `pyenv` Environments
If you have multiple Python versions (e.g. 3.12, 3.13, 3.14):

1. **Anchor `pip` to your active interpreter:**
   ```bash
   python -m pip install --upgrade jpit
   ```
   *(Prevents installing into the wrong Python version if bare `pip` points to an older runtime).*

2. **If using `pyenv`, regenerate shims:**
   ```bash
   pyenv rehash
   ```
   *Ensures `which jpit` points to `~/.pyenv/shims/jpit`, dynamically delegating to your active shell Python.*

3. **Verify:**
   ```bash
   which jpit
   jpit --version
   ```

> [!TIP]
> **Encountering `error: externally-managed-environment` (Homebrew Python or Linux / PEP 668)?**  
> Run `brew install pipx && pipx install jpit`, or pass `--break-system-packages`:
> ```bash
> python -m pip install --upgrade --break-system-packages jpit
> ```
> *(Zero dependencies: safe to install without breaking system packages).*

*(Installing `jpit` automatically installs the `jsonpit` core storage engine and provisions both `jpit` and `jsonpit` command-line executables).*

---

## CLI Usage

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
echo '{Id: "AlanKay", Dynabook: true}' | jpit put Person

# Ingest single entity, keyed map, or array from file (CR043):
jpit seed Activity -s PerformLive.json5

# Set individual properties or tombstone an entity:
jpit set Person AlanKay '{"Status": "Visionary"}'
jpit del Person ObsoleteEntity
```

---

## Core Engine & Documentation

For complete Python library documentation, distributed lease protocols, and multi-agent coordination architecture, visit:  
👉 **[jsonpit on GitHub](https://github.com/Burkhardt/jsonpit-python)** · **[jsonpit on PyPI](https://pypi.org/project/jsonpit/)**

