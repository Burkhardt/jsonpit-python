# jpit (v4.4.3)

> **The developer and AI agent companion CLI for [jsonpit](https://pypi.org/project/jsonpit/) — daemon-free distributed storage over Cloud Drives.**  
> *100% lockstep parity with C# `pits v4.4.3` in [RAIkeep](https://github.com/Burkhardt/RAIkeep).*

`jpit` provides high-performance semantic living state search ("Pit-Grep"), time-travel inspection, and cloud-safe distributed ingestion across replicated JsonPits on OneDrive, Dropbox, and Google Drive.

---

## Installation & Upgrade

### Recommended: Global CLI via `pipx` (Isolated)
Install `jpit` in an isolated environment without dependency conflicts across your system:

```bash
# Install jpit globally
pipx install jpit

# Upgrade to latest lockstep release (v4.4.3)
pipx upgrade jpit
```

### In a Project / Virtual Environment via `pip`
```bash
# Install
pip install jpit

# Upgrade
pip install --upgrade jpit
```

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

