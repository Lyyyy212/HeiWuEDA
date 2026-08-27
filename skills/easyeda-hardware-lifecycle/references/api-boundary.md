# Official EasyEDA API boundary

## Authority chain

Use the locked workbench materials in this order:

1. `@jlceda/pro-api-types` for canonical classes, method IDs, signatures, parameters, return types, enums, and interfaces.
2. Official EasyEDA documentation for semantics, runtime limitations, units, stability, and permission behavior.
3. Official EasyEDA repositories for composition examples.
4. Third-party examples only for discovery; they cannot authorize or define API calls.

The installed EasyEDA skill, bridge, and materials snapshot can have different versions. Record all three and block an unreviewed write when the canonical declaration hash or live adapter version changes.

## Layered gateway

```text
Domain operation
    -> TypedApiPlan
    -> RegistryValidator
    -> SessionIdentityGuard
    -> RiskAndAuthorizationGuard
    -> BridgeExecutor
    -> ResultNormalizer
    -> EvidenceRecorder
```

Only `BridgeExecutor` may construct the final executable code or call `/execute`. Domain and stage modules refer to canonical method IDs such as `DMT_SelectControl.getCurrentDocumentInfo#1`.

The concrete implementation is in `packages/easyeda-gateway/`. Compatibility entrypoints live in `scripts/api_contract.py` and `scripts/easyeda_gateway.py`; neither domain modules nor stage modules should import `BridgeClient` directly.

## Required plan identity

Every plan binds:

- `projectUuid`;
- `documentUuid`;
- `documentType`;
- `capturedAt`;
- bridge service identity and selected EasyEDA window when known;
- API manifest schema, canonical package version, and declaration SHA-256.

Re-read current project and document identity immediately before execution. Identity drift makes the plan stale.

## Risk classes

### `READ`

May query identity, components, nets, properties, DRC, BOM, netlist, or formal exports. It cannot save, modify, create, delete, open another project, or change active content.

### `EPHEMERAL_NAVIGATION`

May open and activate an existing schematic page or board-associated PCB inside
the already-open project. It may not open another project, close a document,
modify document content, or save. An activation requires exact project,
origin-document, target-document and target-type identity guards and must verify
the target UUID/type after switching. A traversal must restore and verify the
original tab before reporting success. A timeout is never retried; the active
page becomes `UNKNOWN_REPROBE_REQUIRED` until a fresh identity probe.

### `EPHEMERAL_WRITE`

Used only for an acceptance test that writes a bounded field, reads it back, restores the original value, and proves restoration. It requires a rollback description and `save=false`.

### `PERSISTENT_WRITE`

Requires a fresh immutable plan digest, passed acceptance report, explicit user authorization for the exact plan and scope, `save=true`, an apply journal, and post-save verification. The initial integrated skill permits persistent writes only through the BOM four-field sync module.

## Validator rules

`scripts/api_contract.py` verifies that:

- every method ID exists in the locked canonical manifest;
- registry identity matches the plan;
- deprecated methods are rejected by ordinary typed plans and composite reads;
- declared call effects are consistent with method-name semantics where the effect is clear;
- unknown-effect methods require a recorded manual classification review;
- read plans contain no write calls;
- ephemeral writes declare rollback and never save;
- persistent writes are non-executable until authorization, accepted plan digest, acceptance evidence, and save intent are present.

Plan arguments are JSON values. An enum argument must use an explicit manifest-bound reference such as `{ "$enum": "EPCB_LayerId.TOP" }`; raw executable expressions are not accepted. Persistent authorization and acceptance are separate artifacts so that authorization can bind an already-computed immutable plan digest without creating a self-referential digest.

The initial write allowlist is executable, not descriptive: write calls may use only `SCH_PrimitiveComponent.modify#1` with property keys mapped from the authorized procurement-field scope. Persistent plans must contain exactly one `SCH_Document.save#1`. Any geometry, identity, connectivity, designator, Value, footprint, or arbitrary `otherProperty` mutation is rejected before code generation.

Validation does not prove that a method is permitted in the current client, appropriate for the active document, or electrically safe. The session guard and stage gate still apply.

The implemented current-page structured-read adapter is documented in [read-adapter.md](read-adapter.md). It uses a fixed, manifest-validated read template and never accepts arbitrary JavaScript from a stage module.

The fixed `EasyedaPageNavigator` is documented in
[page-navigation.md](page-navigation.md). It is isolated from ordinary `READ`
plans because activating a tab changes EasyEDA UI state, even though it does not
change or save document content. Its only non-identity methods are
`DMT_EditorControl.openDocument#1` and
`DMT_EditorControl.activateDocument#1`.

`EasyedaBoardDocumentNavigator` applies the same navigation controls to exact
schematic-page/PCB UUIDs returned by `DMT_Board.getAllBoardsInfo#1` for the
active project. It neither creates a board nor opens a project.

The one deprecated-method compatibility exception is the fixed `EasyedaExportAdapter` documented in [export-adapter.md](export-adapter.md). It may call only `SCH_ManufactureData.getExportDocumentFile#1` and `SYS_FileSystem.saveFileToFileSystem#1` to create a non-overwriting local evidence artifact. The export method is deprecated since EDA v4.1 and has no documented non-deprecated visual-export replacement. This exception is isolated from `TypedApiPlan`, records the deprecated status and exact scope in every evidence envelope, and does not permit any EasyEDA document mutation or save. Only the qualified whole-schematic PNG/PDF combinations execute; page scope is blocked before `/execute` because it is a known UI-hang route on the installed client.

Non-deprecated formal exports use their own fixed adapters for BOM CSV, JLCEDA netlist, EPRO source, and strict DRC. They remain outside arbitrary domain plans because export admission, no-overwrite file handling, and circuit breaking require stronger transport controls than a normal read. Every adapter must use the machine-readable capability matrix, a shared single-flight safety state, one official call per bridge request, zero automatic retries, and pre/post identity guards. A transport timeout opens the breaker because it does not cancel the underlying EasyEDA operation.

Source-pinned official example plugins use `EasyedaOfficialPluginAdapter`. Their minified IIFE bundle digest, upstream commit, active read methods, and intercepted side-effect methods are fixed in code and evidence. The proxy blocks extension-global assignment, UI/log/config persistence, and browser downloads; only the locked read surface and one non-overwriting local evidence save reach real `eda`. DFM, manufacturing SVG, and GenCAD remain capability-gated and require an active PCB with exact pre/post identity.

Device matching uses `EasyedaDeviceMatchDryRunAdapter`, not a generic plan or write adapter. It admits only current-schematic component reads and bounded `LIB_Device.search#1` calls. Candidate scoring and local report creation cannot be promoted to component modification, device creation, or schematic save without a new explicitly authorized write workflow.

The complete matrix and future consumer-driven packages are documented in [export-capabilities.md](export-capabilities.md).

## Writeback boundary

The BOM write adapter may change only:

- Manufacturer;
- Manufacturer Part;
- Supplier;
- Supplier Part.

It must preserve device, symbol, footprint, value, designator, unique ID, geometry, text placement, pins, nets, and PCB participation. A package mismatch or missing part selection becomes a blocked finding, not an invitation to rebuild the component.

Use plan -> acceptance test -> fresh plan -> explicit apply/save -> post-save readback. Never reuse a plan after the active page, BOM digest, protected field digest, or API declaration hash changes.
