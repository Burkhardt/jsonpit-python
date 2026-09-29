# CR043: Support Single-Entity Payloads and Clarify Diagnostics in `pits seed`

> **Naming Schema:** `CR043_AfricaStage_to_RAIkeep_Improve-pits-seed-array-error-message.md`

**Date:** 2026-09-28  
**Requesting Agent / PM:** Eliza (`7000`), PM AfricaStage  
**Ratifying Agent / PM:** Adele (`7010`), PM AIA Platform  
**Target Provider / Repo:** RAIkeep (Codex Agent)  
**Status:** **Accepted (Provider Amendment Ratified)**  
**Target Release:** `RAIkeep v4.4.3`  
**Parent CR:** N/A

---

## 1. Objective & Context

During Sprint 2640 UseCase authoring on the AfricaStage tenant, Eliza (`7000`)
attempted to use the `pits seed` CLI to inject a single JSON5 entity blueprint
into the `Activity` pit:

```json5
{
  "Id": "PerformLive",
  "Kind": "UC",
  "Name": "Perform Live Show",
  "Note": "Live stage performance at an AfricaStage venue."
}
```

The CLI rejected the file with this confusing error:
`CLI Error: Source '/path/to/PerformLive.json5' must contain only JSON objects.`

### Root Cause Analysis

In [`PitSeeder/pits/Program.cs:1089-1102`](../PitSeeder/pits/Program.cs#L1089-L1102),
the parser treated any root `JObject` as a **keyed object map**
(`{ "Id1": { ... }, "Id2": { ... } }`) and extracted its property values:
`new JArray(obj.Properties().Select(p => p.Value))`. When supplied with a
single entity, the entity's own string properties (`Id: "PerformLive"`,
`Kind: "UC"`) were unpacked into the items array. The first string value was
then rejected as not being a `JObject`, producing the misleading diagnostic.

---

## 2. Ratified Provider Amendment (Option A with Exact `Id` Invariant)

The initial proposal (Option B) suggested requiring root arrays and improving
the error string. Following technical review with the RAIkeep Codex Agent, the
Provider Amendment is **unanimously ratified**:

`pits seed` officially supports three distinct payload shapes, validated
strictly before opening or mutating the target Pit:

1. **Single Entity Object:** A root JSON object is accepted directly as a
   single-item payload **if and only if** it has an exact, non-empty string `Id`
   property. `Kind` alone is insufficient because every JsonPit entity requires
   an `Id`.
2. **Keyed Entity Map:** A root JSON object whose properties are all `JObject`
   instances is unpacked into an array of its values.
3. **Entity Array:** A root JSON array of `JObject` instances is accepted
   directly.
4. **Comprehensive Diagnostic:** Any source payload that fails all three shapes
   must throw an `ArgumentException` explaining all three valid forms:

   ```text
   Source '{source.FullName}' must be a JSON array of entities, a single entity object with a non-empty 'Id', or a keyed map of entity objects.
   ```

5. **Pre-Flight Invariant Preserved:** Parsing and shape validation strictly
   precede opening the destination Pit or acquiring process flags.

---

## 3. Suggested Acceptance Tests

1. **Single Root Entity with Valid `Id`:**
   - Source: `{ "Id": "PerformLive", "Kind": "UC", "Name": "Perform Live Show" }`
   - Result: Seeds successfully as a one-entity array.
2. **Keyed Entity Map:**
   - Source: `{ "Item1": { "Id": "Item1", "Kind": "Obj" }, "Item2": { "Id": "Item2", "Kind": "Obj" } }`
   - Result: Seeds both items successfully.
3. **Standard Array:**
   - Source: `[ { "Id": "Item1" }, { "Id": "Item2" } ]`
   - Result: Seeds both items successfully.
4. **Invalid Root Object (Missing/Empty `Id` with Primitive Fields):**
   - Source: `{ "Title": "InvalidNoId", "Count": 42 }`
   - Result: Fails with the descriptive diagnostic citing all three accepted forms.
5. **Non-Object in Array:**
   - Source: `[ { "Id": "Valid" }, "InvalidString" ]`
   - Result: Fails with a clear diagnostic that array elements must be JSON objects.
