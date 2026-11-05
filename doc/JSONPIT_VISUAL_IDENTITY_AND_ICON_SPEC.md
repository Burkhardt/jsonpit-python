# JsonPit Visual Identity & Icon Specification

**Document:** `JSONPIT_VISUAL_IDENTITY_AND_ICON_SPEC.md`
**Related Documents:** `CR040`, `CR057`, `CR077`
**Curator / Creative Direction:** Koyo (Chief Marketing & Web Design Assistant)
**Target Repositories:** `Burkhardt/jsonpit` (Python / `jpit`), `Burkhardt/RAIkeep` (C# / `JsonPit` / `pits`), `AIA-Marketing`
**Status:** Approved Specification
**Asset Deliverables:**
- **Flagship Multi-Machine Sync Logo (Primary):** [jsonpit-sync-logo.svg](../assets/jsonpit-sync-logo.svg)
- **Isometric Bedrock Quarry Variant:** `jsonpit-logo-hex.svg` (external design variant; not bundled)
- **Architectural Stepwell Variant:** `jsonpit-logo.svg` (external design variant; not bundled)

---

## 1. Product Identity & Design Metaphor

> *"Daemon-free distributed storage over Cloud Drives for developers and AI agents — multi-process, immutable history, zero dependencies."*

JsonPit is fundamentally **not** a single database file, a siloed document store, or a local cache. Its defining architectural reality is **multi-machine synchronization**: coordinating deterministic state across independent physical laptops, workstations, headless agents, and cloud drives (Dropbox, OneDrive, Google Drive, iCloud, Amafu) without a central coordinating daemon.

### 1.1 Brand Sovereignty & Decoupling (The Anti-Coupling Invariant)
While both tools emerge from the same engineering ecosystem, **`vikela` and `jsonpit` must maintain sovereign, independent visual identities**:
- **Vikela** stands on its own on PyPI as a sovereign Python mutation guardrail and AST linter. Its *Ihawu* shield must never look like an internal proprietary sidecar or an obvious puzzle-piece to JsonPit.
- **JsonPit** stands on its own as a distributed multi-machine storage substrate.
- **The Color Semiotics:** Gold carries authentic Southern African resonance through **eGoli** (the City of Gold / Johannesburg reef). Grounding JsonPit's multi-machine nodes in eGoli Gold (`#DCA832`) and crisp Calçada White braces (`#F4F4F0`) allows both tools to share cultural dignity without sharing an artificial corporate uniform or revealing architectural co-dependency.

---

## 2. The Bespoke Logo Architecture: The Multi-Machine Constellation

The primary visual identity is codified in **`jsonpit-sync-logo.svg`**:

### 2.1 Anatomy of the Mark
1. **The Architectural JSON Brackets `{ }`:**
   Prominent, weighted Calçada White curly braces that enclose the distributed space, establishing that all distributed mutations ultimately resolve into clean, structured document entities.
2. **The Multi-Machine Triad (It’s Not Just One):**
   Three distinct machine hubs (e.g., Workstation, Remote Cloud Server, Laptop/Agent) arranged in an equilateral constellation, each maintaining its own local stratified change history.
3. **The Inter-Machine Synchronization Orbits:**
   Dynamic bidirectional arcs and moving delta packets passing continuously between the machines, illustrating asynchronous replication over cloud drives.
4. **The Central Eventual Consistency Nexus:**
   A central harmonic focal point where independent machine timelines converge into a single, deterministic projection fold.

---

## 3. Nerd Fonts & CLI Badge Specification

For `jpit` (Python) and `pits` (C#) CLI tools, interactive terminal prompts, and CI status badges:

| Purpose | Icon | Nerd Font Name | Codepoint | Usage & Meaning |
| :--- | :---: | :--- | :--- | :--- |
| **Primary CLI Prefix** | `󰘦` | `nf-md-code_json` | `\udb81\ude26` | Identifies structured JSON document storage. |
| **History / Strata** | `󰔅` | `nf-md-layers_triple`| `\udb81\udf0e` | Multi-tiered append-only value history. |
| **Storage Core** | `` | `nf-fa-database` | `\uf1c0` | Classic storage repository indicator. |
| **Time-Travel / Log** | `` | `nf-cod-history` | `\uea82` | Historical revision and projection replay. |
| **Distributed Mesh** | `󰒍` | `nf-md-server_network`| `\udb81\udc8d` | Cloud-drive multi-machine replication. |

### 3.1 CLI Output Formatting in Practice

```bash
# Multi-Machine Projection
󰘦 jpit get Jazz Miles
{
  "Id": "Miles",
  "Instrument": "Trumpet",
  "Era": "Kind of Blue",
  "Modified": "2026-11-04T16:20:00Z"
}

# Multi-Node Replication Status
󰒍 jpit sync --status
  OneDrive: synchronized | Dropbox: synchronized | Amafu: 0 pending deltas
```

---

## 4. Brand Palette & Color Tokens

| Token Name | Hex Code | Semantic Role |
| :--- | :--- | :--- |
| **eGoli Gold** | `#DCA832` | Machine node hubs, active sync arcs, value history. |
| **Radiant Gold Highlight** | `#F7D373` | Synchronized live planes, in-flight delta packets. |
| **Calçada White** | `#F4F4F0` | Structural JSON braces `{ }`, terminal typography. |
| **Warm Obsidian Ground** | `#11110F` | Deep dark ground container (independent of heraldic green). |
| **Replication Stream Track** | `#33332A` | Background synchronization orbits. |

---

## 5. Asset Placements Across Fleet

- **PyPI Package Banner:** `Burkhardt/jsonpit/assets/jsonpit-sync-logo.svg`
- **GitHub Repository Avatar:** Rendered from `jsonpit-sync-logo.svg` (512×512 PNG/SVG)
- **Sphinx / MkDocs Favicon:** `Burkhardt/jsonpit/docs/_static/favicon.svg`
- **RAIkeep Documentation Archive:** `doc/assets/jsonpit-sync-logo.svg`
