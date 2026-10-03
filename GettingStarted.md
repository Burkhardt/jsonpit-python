# Getting Started with Python jsonpit (v4.5.1)

This guide provides a practical walkthrough for using **`jsonpit`** from Python—either embedded as a library in your services, AI agent frameworks, and data pipelines, or as the standalone **`jpit`** CLI for command-line workflows.

It is based on `jsonpit` v4.5.1, featuring 100% lockstep parity with C# `JsonPit` in [RAIkeep](https://github.com/Burkhardt/RAIkeep).

---

## 1. Purpose and Mental Model

`jsonpit` is a cloud-first, file-based, distributed replicated storage engine for `Id`-identified items that need to be shared, synchronized, and reloaded across machines and processes without introducing a database daemon.

### The Core Concepts:
- **`Pit`**: A named container directory stored on disk (e.g. `Person/Person.pit`).
- **`PitItem`**: An `Id`-identified JSON object with lifecycle metadata (`Modified`, `Deleted`, `Note`) and arbitrary properties.
- **`PitItems`**: The immutable version history of sparse change fragments for an item key.

### Mental Model:
- A `Pit` is closer to a synchronized document store than a SQL table.
- Updates are **append-only sparse fragments**, not blind in-memory overwrites.
- Coordination happens through synchronized cloud storage (OneDrive, Dropbox, GoogleDrive, ICloudDrive) using lease flags and change files.
- **[Asynchronous persistence with eventual durability](https://github.com/Burkhardt/RAIkeep/blob/main/MANIFESTO.md#asynchronous-persistence-with-eventual-durability)**: request handling happens in memory; synchronization is explicit via `save()` or context manager exit.

---

## 2. Installing the `jpit` CLI Tool

`jpit` is the command-line companion for `jsonpit` and the Python counterpart to C# `pits`. Choose the method that best matches your workflow:

### Method 1: Single-File Direct Download (Zero Installation, Zero Dependencies)

Because `jsonpit` has zero third-party dependencies, it is packaged as a single 51 KB executable using Python's standard library `zipapp`.

👉 **[Download `jpit` binary directly (51 KB)](https://raw.githubusercontent.com/Burkhardt/jsonpit-python/main/bin/jpit)**

To install it from your terminal on **any Mac or Linux machine** (runs anywhere, from any folder):
```bash
mkdir -p ~/.local/bin && curl -fsSL https://raw.githubusercontent.com/Burkhardt/jsonpit-python/main/bin/jpit -o ~/.local/bin/jpit && chmod +x ~/.local/bin/jpit
```

Verify the installation:
```bash
jpit -v
```

### Method 2: Install All 5 CLIs (`amafu`, `raid`, `iorg`, `pits`, `jpit`)

To install the entire suite of CLI tools into `~/.local/bin` using the public installer script from GitHub:  
👉 **[`install-clis.sh` on GitHub](https://github.com/Burkhardt/RAIkeep/blob/main/scripts/install-clis.sh)**

Run this one-liner directly in your terminal (no repository cloning needed):
```bash
curl -fsSL https://raw.githubusercontent.com/Burkhardt/RAIkeep/main/scripts/install-clis.sh | bash -s -- 4.5.0 local
```

---

## 3. Installing `jsonpit` in Python Applications

If you are building a Python service, backend daemon, or AI agent workflow:

### Using Standard Python `pip`
Create and activate an isolated virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade jsonpit
```

### Using `uv`
```bash
uv add jsonpit
```

---

## 4. Configuration & Cloud Roots

`jsonpit` automatically reads your cloud provider root from `~/.config/RAIkeep.json5` (with fallback to `~/.config/jsonpit.json5` or `$JSONPIT_CONFIG`):

```json5
{
  Cloud: {
    OneDrive: "~/Cloud/OneDrive-AfricaStage/",
    GoogleDrive: "~/Library/CloudStorage/GoogleDrive-me@example.com/"
  }
}
```

If no configuration file exists, you can pass explicit directory paths directly, or run `amafu init` to auto-detect your cloud drives.

---

## 5. First Steps with the Python Library

### Basic End-to-End Example
Here is the recommended Python idiom using the `Pit.open()` context manager:

```python
from jsonpit import Pit, PitItem

# 1. Open the Pit using the context manager
# (Acquires a process activity window, loads state, and auto-saves on exit)
with Pit.open("person", cloud="GoogleDrive") as people:
    
    # 2. Create an entity with Id
    max_person = PitItem("Max")
    max_person["Email"] = "max@example.org"
    max_person["Phone"] = "+27-82-000-0000"
    max_person["ComPref"] = ["WhatsApp", "Email"]
    
    # 3. Add to Pit
    people.add(max_person)
    print(f"Added {max_person.id} to Pit '{people.pit_name}'")

# --- On context manager exit, people.save() is called automatically ---

# 4. Reopen and query
with Pit.open("person", cloud="GoogleDrive", read_only=True) as people:
    loaded_max = people["Max"]
    print(f"Loaded: {loaded_max.id} -> Email: {loaded_max['Email']}, Phone: {loaded_max['Phone']}")
    print(f"Channels: {loaded_max['ComPref']}")
```

### Updating an Existing Item
Looking up an entity returns a **live reference**. Mutating that reference records sparse modifications directly:

```python
with Pit.open("person", cloud="GoogleDrive") as people:
    max_person = people["Max"]
    
    # Direct indexer updates append sparse fragments
    max_person["Phone"] = "+27-82-111-2222"
    max_person["Instagram"] = "max.africastage"
    
    # Nested dictionaries are deep-merged
    max_person["Address"] = {
        "Street": "42 Long Street",
        "City": "Cape Town",
        "Country": "South Africa"
    }
```

### Removing Attributes (Tombstones)
`jsonpit` never mutates history destructively. Deleting a property appends a **null tombstone** that masks previous values in the projection while preserving time travel:

```python
with Pit.open("person", cloud="GoogleDrive") as people:
    max_person = people["Max"]
    
    # Remove a top-level property
    max_person.delete_property("Instagram")
    
    # Remove a nested path
    max_person.delete_property_path("Address.Street")
```

### Deleting an Entity
```python
with Pit.open("person", cloud="GoogleDrive") as people:
    # Tombstones the entire entity
    del people["Max"]
    # or: people.delete_item("Max", by="Operator")
```

### Time Travel and Historical Auditing
Because every modification is an immutable timestamped fragment, you can inspect historical states:

```python
with Pit.open("person", cloud="GoogleDrive", read_only=True) as people:
    # Inspect raw version history
    history = people.history["Max"]
    for frag in history.history:
        print(f"[{frag.timestamp}] {frag.data}")
    
    # Reconstruct the entity as it existed at a past point in time
    past_state = people.get_at("Max", at="2026-10-01T12:00:00Z")
    if past_state:
        print("Past Phone:", past_state.get("Phone"))
```

---

## 6. Alternative: First Steps with the `jpit` CLI

If you prefer to operate directly from the command line without writing Python code, the `jpit` CLI provides high-performance data seeding, mutation, and inspection.

### Step 1: Seed Initial Data
Create a JSON or JSON5 file (`people.json5`):

```json5
[
  {
    Id: "Max",
    Email: "max@example.org",
    Phone: "+27-82-000-0000",
    ComPref: ["WhatsApp", "Email"]
  },
  {
    Id: "Adele",
    Email: "adele@example.org",
    Role: "Software Architect"
  }
]
```

Seed the entities into a Pit named `person`:
```bash
jpit seed person people.json5
```

### Step 2: Read Entities
Get one entity formatted as JSON:
```bash
jpit get person Max
```

Get only a specific property:
```bash
jpit get person Max --property Email
```

List all active entities in the pit:
```bash
jpit list person
```

### Step 3: Sparse Mutations (Anti-Read-Modify-Write)
Update attributes without rewriting the entire entity:

```bash
jpit set person Max Phone "+27-82-111-2222"
```

Add a nested object:
```bash
jpit set person Max Address '{"City": "Cape Town", "Country": "South Africa"}'
```

Tombstone an attribute:
```bash
jpit del-prop person Max Email
```

### Step 4: Semantic Search ("Pit-Grep")
Search across living entity states using ripgrep-style speed:

```bash
jpit grep "Cape Town" person
```

Filter by property and output structured JSON:
```bash
jpit grep --property Role "Architect" person --json
```

### Step 5: Exporting & Piping with `jq`
Pipe living state directly into `jq`:
```bash
jpit export person --jq '.[].Id'
```

---

## 7. 100% C# / `pits` Cross-Language Interoperability

Every Pit created or updated by Python `jsonpit` is 100% binary- and schema-compatible with C# `JsonPit` and the `pits` CLI.

Write an entity attribute with Python `jpit`:
```bash
jpit set person Max Status "Online"
```

Read it immediately with C# `pits`:
```bash
pits get person Max
```

Both engines enforce identical timestamp parsing, canonical key ordering, lease flag acquisition, receipt grace periods, and sparse delta projection.
