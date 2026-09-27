# CR024 — `Pit` and `pits` Ephemeral Process-Flag Self-Cleanup

**Requesting product:** AIA

**Requesters:** Adele (PM, AIA) and RAI

**Provider:** RAIkeep

**Provider owner:** Codex (Owner and Lead Custodian, RAIkeep)

**Accepted by:** RAI and Adele (PM, AIA)

**Target release:** Coordinated RAIkeep v4.3.0 (carried forward from the unpublished v4.2.11 preparation)

**Parent contracts:** CR003, CR021, CR022

**Status:** Accepted and implemented for v4.3.0; awaiting RAI's manual release-chain gate

## 1. Problem

Finite `Pit` and `pits` invocations registered exact PID-specific process flags
but previously converted them to Unix-epoch tombstones on graceful disposal.
Although the tombstone was correctly inactive, repeated normal CLI and test runs
left hundreds of obsolete files for later maintenance pruning.

Clean termination is not a crash-recovery case. A process that can complete its
durability boundary can also remove the exact activity flag it owns.

## 2. Accepted lifecycle

1. `Pit.Dispose()` completes its existing CR003 durability work and then calls
   `ProcessFlagFile.TryReleaseCurrentProcess()`.
2. `TryReleaseCurrentProcess()` re-reads and ownership-checks the exact flag,
   then removes it through `RaiFile.rm()`. Cloud paths therefore use OsLib's
   disappearance wait.
3. Read-only and writable pits use the same release primitive. The finalizer
   remains strictly free of filesystem, recovery-publication, and flag I/O.
4. `pits` normal, exception-unwind, Ctrl+C, and process-exit paths converge on
   `Pit.Dispose()` for every tracked pit.
5. `Master.flag` is not released, deleted, or rewritten by this cleanup. Its
   established master-lease and TTL rules remain unchanged.
6. Crashed or forcibly killed processes can still leave flags. Their TTL and
   explicit `pits maintain ... --prune-process-flags` recovery remain unchanged.

## 3. `--retain-window` compatibility exception

RAI and AIA accepted preserving `--retain-window` in v4.3.0 for callers that
explicitly request the former timeout-based behavior. Every finite CLI call
without that option removes its owned process flag. `--retain-window` is
scheduled for removal in the next major release and must not become the default
for new integrations.

## 4. Verification

- Direct owned release deletes the PID flag; a foreign process flag is retained.
- Explicit read-only and writable `Pit.Dispose()` delete their process flags and
  preserve `Master.flag` content.
- Normal and exception CLI exits leave no process flag.
- Twenty sequential finite CLI queries leave zero PID flags.
- `--retain-window` deliberately leaves one active flag.
- The split-master finalizer regression continues proving finalizers publish no
  recovery data and perform no filesystem I/O.

## 5. Release boundary

CR024 was prepared for v4.2.11, which RAI intentionally did not publish. Its
implementation is carried unchanged into the coordinated seven-package RAIkeep
v4.3.0 line. Tagging,
GitHub labeling, workflow dispatch, and NuGet publication remain exclusively
behind RAI's manual `scripts/release-chain.sh 4.3.0` gate.
