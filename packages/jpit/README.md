# jpit

The developer and agent companion CLI for [jsonpit](https://pypi.org/project/jsonpit/) — daemon-free distributed storage over Cloud Drives.

## Quick Install

```bash
pip install jpit
```

Installing `jpit` installs the core `jsonpit` storage engine and provides both `jpit` and `jsonpit` command-line executables:

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
```

For full library documentation, distributed architecture details, and multi-agent coordination protocols, visit the official [jsonpit repository on GitHub](https://github.com/Burkhardt/jsonpit-python).
