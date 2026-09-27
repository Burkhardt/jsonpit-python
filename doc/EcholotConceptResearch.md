# Echolot: Concept Research & Distributed Testing Architecture

| Metadata | Details |
| :--- | :--- |
| **Document** | Architectural Research Note |
| **Topic** | Eventual Consistency Testing, Polling Lifecycles, & Cross-Engine Distributed Soundings |
| **Authors** | Dr. Rainer Burkhardt (`RAI`, Chief Maker) & Adele (`7010`, Lead Software Architect) |
| **Date** | 2026-09-26 |
| **Status** | Concept Archived / Staged for Future Evolution |

---

## 1. The Core Problem: Testing Eventual Consistency

Traditional test frameworks (xUnit, pytest) assume instantaneous, binary assertions (`Assert.Equal(expected, actual)`). In distributed, cloud-first systems—where storage replicates asynchronously across cloud drives (OneDrive, Dropbox, iCloud) or external services (e.g., NuGet package indexing taking 300s, or cross-continental replication between Europe and Mzansi)—binary assertions fail:
- **Immediate assertions** produce false negatives due to replication transit time.
- **Fixed `sleep()` intervals** cause flakiness when network latency spikes and severely slow down test pipelines when latency is low.

---

## 2. The Echolot Metaphor & State Model

The German naval metaphor **Echolot** (acoustic depth sounder / sonar) accurately reflects the physics of asynchronous systems:

1. **Ping (Trigger):** An action is emitted (e.g., `jpit set` or `pits set` writing to cloud storage).
2. **Transit (`NotYet`):** The signal is traveling through the medium. The test harness does not fail immediately; it actively listens.
3. **Echo Return (`Converged`):** The state fold reflects back from the observing replica with 100% parity. Depth (latency in ms) is recorded.
4. **Divergence (`Diverged`):** The deadline elapses without receiving a matching echo.
5. **Violation (`Violated`):** An invariant was broken immediately (e.g., CR040 protected attribute injected).

```
                       ┌──────────────┐
                       │   Pending    │
                       └──────┬───────┘
                              │ ping sent
                              ▼
                       ┌──────────────┐
              ┌───────►│   NotYet     │◄────────┐
              │        │ (converging) │         │ retry within
              │        └──────┬───────┘         │ grace period / deadline
              │               │                 │
              │  poll check   ├─────────────────┘
              │               ▼
    ┌─────────┴────────┐┌──────────────┐┌──────────────┐
    │     Violated     ││  Converged   ││   Diverged   │
    │ (instant failure;││  (PASS: 100% ││(FAIL: timeout│
    │  invariant broke)││    Parity)   ││   exhausted) │
    └──────────────────┘└──────────────┘└──────────────┘
```

---

## 3. Survey of Existing Ecosystem Tools

A comprehensive survey was conducted to evaluate existing tools against the requirements:
- Declarative suites (`Construct`, `Tests`, `Destruct`)
- Delayed polling / retries for eventual consistency
- Remote command execution via SSH

| Tool | Language | Pros | Cons / Gaps |
| :--- | :--- | :--- | :--- |
| **OVH Venom** (`ovh/venom`) | Go | Declarative YAML suites; native `retry` and `delay` keys; built-in `ssh` and `exec` executors; stdout/stderr assertions. | Heavy 50MB external binary; YAML-only (no JSON5); bundled with dozens of unused database/messaging plugins. |
| **BATS-Core** | Bash | Unix CLI testing standard; lightweight; readable syntax. | Purely procedural shell scripting; no native declarative retry/polling without boilerplate `while` loops. |
| **pytest-testinfra** | Python | Outstanding SSH and multi-node execution; native Python assertions. | Code-centric rather than declarative data-driven suites; requires custom polling loops for eventual consistency. |
| **Kuttl** | Go | Specifically designed for eventual consistency polling assertions in declarative workflows. | Strictly coupled to Kubernetes YAML resources. |

---

## 4. Future Vision: Dogfooding JsonPit as the Test Ledger

When scaled to multi-node environments (e.g., local macOS $\leftrightarrow$ Mzansi Windows 11 node $\leftrightarrow$ Umshadisi):
- Test suites can be stored as declarative entities in a dedicated `Echolot.pit`.
- Distributed nodes can read test specifications and append their execution results as sparse fragments without central database infrastructure.
- Status of all nodes can be queried globally via `jpit -r AIA.Echolot get Echolot <TestId>`.
