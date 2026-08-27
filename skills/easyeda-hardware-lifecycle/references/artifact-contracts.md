# Artifact contracts

## Canonical project layout

```text
<project>/
  .hardware-lifecycle/
    project-state.json
    history/
  design/
    requirements.json
    system-architecture.json
    verification-strategy.json
    modules/<module-id>.json
    interfaces.json
    electrical-constraints.json
  evidence/
    <snapshot-id>/
      envelope.json
      schematic.pdf
      netlist.*
      bom.*
      drc.*
    <page-navigation-id>/
      request.json
      result.json
      envelope.json
    <pcb-official-plugin-id>/
      request.json
      result.json
      envelope.json
      official-pcb-dfm-report.json | official-manufacturing-svg.zip | official-board-gencad.cad
    <device-match-id>/
      request.json
      result.json
      envelope.json
      device-match-report.json
  reviews/<review-id>/
    review-report.json
    review-actions.json
    release-gate.json
  bom/
    requirements.json
    candidates.json
    final-bom.json
    final-bom.digest
  writeback/<plan-id>/
    api-plan.json
    acceptance-report.json
    apply-journal.json
    post-save-verification.json
  .easyeda-hardware-workbench/learning/
    sessions/
    questions/
    evidence/
    answers/
    responses/
    notes/
    lark/
```

State files refer to artifacts by project-relative path and SHA-256. Do not embed large exports or unbounded API responses in project state.

Learning-note packages use `learning.note-package.v1`. A package binds one
JLC Hardware Learning page snapshot to its numbered frames and ordered dialogue turns. Each
turn carries both stable frame numbers and frame shape IDs, and the exact
assistant response is stored separately from the deterministic tutor baseline.
The included Feishu plan is local-only until a dedicated adapter receives an
explicitly authorized document/whiteboard target.

## Artifact envelope

Every canonical artifact should carry or be paired with:

```json
{
  "schemaVersion": "easyeda.hardware-lifecycle.artifact-envelope.v1",
  "artifactId": "artifact:<uuid>",
  "artifactType": "system-architecture",
  "artifactVersion": "1.0.0",
  "createdAt": "<ISO-8601>",
  "producer": { "module": "concept-design", "version": "1.0.0" },
  "project": { "projectId": "project:<uuid>" },
  "sourceIdentity": {
    "projectUuid": null,
    "documentUuid": null,
    "documentType": null,
    "capturedAt": null
  },
  "upstream": [
    { "path": "design/requirements.json", "sha256": "<64 hex>" }
  ],
  "payload": { "path": "design/system-architecture.json", "sha256": "<64 hex>" },
  "evidence": [],
  "assumptions": [],
  "unknowns": [],
  "safetyNotes": []
}
```

Null EasyEDA identity is allowed for concept artifacts. It is mandatory for live schematic, review, BOM-sync, and writeback evidence.

## Requirements

Use stable IDs such as `REQ-PERF-001`. Each requirement contains statement, rationale, numeric limits or explicit qualitative acceptance, priority, verification method, owner, status, and source. Do not delete superseded IDs; mark them superseded and link the replacement.

## Module design

Each module artifact contains:

- module ID, purpose, owners, inputs, outputs, and dependencies;
- traced requirement IDs;
- supply, clock, reset, signal, mechanical, thermal, protection, and test constraints;
- topology and selected/allowed implementation options;
- calculations and evidence references;
- interface IDs owned and consumed;
- failure behavior and safe state;
- verification plan, unresolved questions, and invalidation triggers.

## Review findings

Use stable finding IDs and severity `P0` through `P3`. Each finding records location, evidence, impact, recommendation, confidence, disposition, action owner, verification evidence, and the schematic snapshot digest.

## Final BOM

The final BOM is grouped only when Value, footprint, implementation role, selection, DNP/variant status, and four procurement fields are truly identical. Each line includes:

- references and quantity;
- Value and footprint captured from the schematic;
- Manufacturer and Manufacturer Part;
- Supplier and Supplier Part;
- selection requirement IDs and rationale;
- datasheet evidence and package/spec validation;
- lifecycle, alternate, stock/price observation timestamp;
- DNP, variant, assembly, and substitution notes;
- page UUID or exact schematic-source identity.

Blank procurement fields mean unspecified. Clearing requires an explicit clear token supported by the guarded writeback workflow.

## API plan

Use `easyeda.hardware-lifecycle.api-plan.v1`. A plan contains registry identity, document identity, risk, calls by canonical method ID, expected protected fields, and rollback/save policy. Calculate the plan digest over the plan with `planDigest` removed. Persistent authorization and acceptance are separate artifacts that bind the resulting immutable digest.

Write plans additionally bind `gatewayVersion` and `bridgeScriptSha256`. The trusted bridge launcher records the live script path, SHA-256, PID, service identity, URL, and start time in `.runtime/easyeda-bridge.json`; the executor rejects a write when that runtime record is absent or differs from the plan.

Schemas in `references/schemas/` document project state, API plans, and independently maintainable module profiles. The bundled scripts enforce additional cross-field invariants that JSON Schema alone cannot express.

## Page-navigation evidence

A page-navigation envelope records the action (`list`, `activate`, or
`traverse`), exact project/origin/target UUIDs, ordered page UUIDs and names,
selected EasyEDA window, generated-code digest, identity before and after, every
visited page, restoration result, `saveCalled=false`,
`documentContentMutation=false`, and `automaticRetry=false`. `list` and
`traverse` must finish on the original page. `activate` must finish on the exact
requested target. A timeout records `UNKNOWN_REPROBE_REQUIRED`; downstream
consumers must obtain a fresh identity before continuing.

## Official PCB plugin evidence

An official-plugin envelope records the exact upstream repository, 40-character commit, source path, browser-bundle SHA-256, locked method IDs, intercepted UI/download/storage methods, capability admission, one-call execution model, zero-retry policy, pre/post PCB identity, artifact SHA-256, and structural inspection. DFM adds all 18 numbered rows and summary counts; SVG adds safe ZIP entries and valid SVG counts; GenCAD adds required sections and component/signal counts. A DFM `PASS` never sets `fabricationApproval=true`.

## Official PDF visual derivative evidence

A JLC Hardware Learning PDF-render envelope references one passing official whole-schematic PDF export envelope and repeats its exact project/document identity. It records the source PDF path, byte count and SHA-256; Poppler executable path, version and SHA-256; maximum long edge and timeout; ordered page indexes, native PDF point sizes, PNG dimensions, byte counts and SHA-256 values; and `easyedaApiCallCount=0`. Rendered pages remain derived evidence and must not be labeled as exact live page-UUID exports.

JLC Hardware Learning native and PDF-render import manifests also carry one closed
`visualMode`: `default` or `black-white`. It must map respectively to the
sealed EasyEDA export theme `Default` or `Black on White`. Repeat both
`visualMode` and `easyedaExportTheme` in every imported asset and shape record
so later learning notes can distinguish appearance without inferring it from
pixels.

## Device-match dry-run evidence

A device-match report records the source-pinned scoring reference, bounded designator/query scope, normalized component snapshot, ordered candidates with 100/85/60 score and reasons, search errors, and explicit `designWriteCalls=0` / `designSaveCalls=0`. The report is advisory; it is neither a final BOM nor device-binding authorization.
