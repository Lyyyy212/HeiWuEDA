---
name: easyeda-hardware-lifecycle
description: Orchestrate an EasyEDA hardware project from concept and architecture through module-level design, schematic review, BOM selection, and guarded four-field BOM writeback. Use when the work must remain traceable, modular, and backed by the official EasyEDA API; do not use for a one-off component lookup or an unrelated EDA.
---

# EasyEDA Hardware Lifecycle

Treat this skill as the lifecycle orchestrator. Keep design judgment, official API transport, evidence capture, BOM sourcing, and writeback as separate modules with explicit contracts.

## Dedicated gateway contract

For every live EasyEDA operation in this workbench, use only the project-dedicated endpoint returned by `py scripts/easyeda_gateway.py discover`. A usable endpoint must satisfy all of the following at the same time:

- `service = easyeda-bridge`
- `gatewayId = lyyyy.hardware-workbench`
- `productId = hardware-workbench`
- `protocolVersion = 2`
- `edaConnected = true`

The service name or listening port alone is never sufficient. Do not use the generic Bridge bundled with `easyeda-api`, do not fall back to a Bridge whose `/health` omits the dedicated identity, and do not guess that port 49620 is the selected endpoint. If discovery reports no dedicated endpoint, run `py scripts/easyeda_gateway.py start-bridge`, then repeat discovery and require a registered Hardware Workbench EasyEDA window before continuing. Use the returned `bridgeUrl`; when multiple windows are present, resolve the explicit `windowId` before any operation.

## Route the request

- For system requirements, alternatives, partitioning, power tree, interfaces, or cost targets, run the `concept` stage.
- For one subsystem's circuit, interfaces, constraints, calculations, and verification plan, run `module_design`.
- For exported or live schematics, run `schematic_review` through the `hardware-design-review` skill and the official evidence adapter.
- For a schematic visual, BOM, netlist, source archive, strict DRC, cross-artifact audit, or JLC Hardware Learning import, route through the named export adapters; read [references/export-capabilities.md](references/export-capabilities.md) and [references/export-adapter.md](references/export-adapter.md). Never construct an export call in a domain module.
- For official PCB DFM, layered manufacturing SVG, or GenCAD, use `EasyedaOfficialPluginAdapter`; for schematic device suggestions use the separate device-match dry-run. Keep unqualified PCB exports blocked and never turn a candidate report into implicit binding authorization.
- For schematic-page listing, board-associated schematic/PCB switching, an explicit page activation, or guarded cross-page traversal, use the official page navigators; read [references/page-navigation.md](references/page-navigation.md). Navigation is independent of visual export and never saves EasyEDA.
- For MPN, package, lifecycle, stock, price, alternates, or final BOM decisions, run `bom_selection` through the `bom` orchestrator and applicable distributor/datasheet skills. Reuse its sourcing and validation flow, not its KiCad property-write scripts; this lifecycle's canonical final BOM remains the EasyEDA selection authority.
- For live EasyEDA audit and BOM-authoritative standardization policy, use `jlc` as the policy/evidence layer while keeping this workbench gateway as the transport boundary. Do not route through legacy `jlc.py` mutation paths.
- For final EasyEDA procurement-field filling, run `bom_writeback` only through the installed `jlc-bom-sync`; modify only Manufacturer, Manufacturer Part, Supplier, and Supplier Part.
- For JLC Hardware Learning selection-scoped hardware questions or teaching annotations, read [references/learning-mode.md](references/learning-mode.md) and use the learning modules. Keep image generation, telemetry, EasyEDA writes, implicit page switching, and cross-page evidence merging disabled.
- For a JLC Hardware Learning schematic visual import, require one explicit appearance choice before export. If the user did not already say `默认配色` or `黑白配色`, ask: `请选择原理图导入模式：默认配色，还是黑白配色？` Map `默认配色` to `visual-mode=default` and official `theme=Default`; map `黑白配色` to `visual-mode=black-white` and official `theme=Black on White`. Never silently choose a mode.
- Keep transport separate from appearance. Resolve it with `learning-visual-import-route`: an omitted transport request must resolve to the official-PDF-to-6144px-PNG route. Use native PNG only when the user explicitly requests a smaller or faster import; `默认配色` never means native PNG.
- For status, resume, or an upstream change, inspect the lifecycle state before choosing a stage.

Read [references/stage-contracts.md](references/stage-contracts.md) for the selected stage. Read [references/architecture.md](references/architecture.md) when adding or replacing a module. Read [references/api-boundary.md](references/api-boundary.md) before any live EasyEDA operation. For current-page structured read-only capture, also read [references/read-adapter.md](references/read-adapter.md); this does not authorize the blocked current-page visual-export scope. Read [references/artifact-contracts.md](references/artifact-contracts.md) when creating, validating, or migrating project artifacts.

## Shared invariants

1. The lifecycle state and immutable evidence artifacts are the handoff between stages; conversation text is not a durable handoff.
2. Never let a domain module construct raw `eda.*` calls. It emits a typed API plan; the official API gateway validates the exact method ID against the locked API manifest before execution.
3. Bind every live snapshot to `projectUuid`, `documentUuid`, `documentType`, `capturedAt`, bridge identity, API declaration hash, and artifact hashes.
4. Do not skip gates. When an upstream requirement, interface, footprint, or selected part changes, invalidate the affected stage and every dependent downstream stage.
5. Separate evidence, inference, decision, unknowns, and acceptance criteria in every design or review artifact.
6. Default to read-only. A design recommendation, canvas annotation, selected BOM, or accepted review is not authorization to modify or save EasyEDA.
7. A zero-error DRC or internally consistent export is supporting evidence, not fabrication approval.
8. Persistent writeback requires a frozen final BOM, fresh page-bound plan, plan digest, reversible acceptance test, explicit save authorization, and post-save readback.

## Operating workflow

1. Locate or initialize `.hardware-lifecycle/project-state.json` with `scripts/lifecycle.py`.
2. Confirm the current stage, inputs, upstream digests, and unresolved blockers.
3. Produce the selected stage's canonical artifacts and evidence envelope.
4. Validate official API plans with `scripts/api_contract.py`; do not execute plans that are invalid or non-executable.
5. Record the stage gate only when its acceptance criteria are proven, then advance exactly one stage.
6. If an upstream artifact changes, record invalidation before continuing downstream work.

Useful commands:

```powershell
py -m pip install --user --no-deps <workbench>\packages\easyeda-gateway
py scripts/lifecycle.py init --state <project>\.hardware-lifecycle\project-state.json --project-name <name>
py scripts/lifecycle.py validate --state <project>\.hardware-lifecycle\project-state.json
py scripts/lifecycle.py artifact --state <state.json> --stage concept --path design/system-architecture.json --sha256 <digest> --type system-architecture
py scripts/api_contract.py identity --manifest <workbench>\materials\manifests\api-manifest.json
py scripts/api_contract.py validate-plan --manifest <manifest> --plan <api-plan.json>
py scripts/easyeda_read.py snapshot-active-schematic --manifest <manifest> --evidence-dir <project>\evidence
py scripts/easyeda_gateway.py discover
py scripts/easyeda_gateway.py probe --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py execute-plan --manifest <manifest> --plan <api-plan.json> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py schematic-pages --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py schematic-page-activate --page-uuid <page-uuid> --project-uuid <project-uuid> --document-uuid <origin-page-uuid> --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py schematic-page-traverse --project-uuid <project-uuid> --document-uuid <origin-page-uuid> --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py board-documents --project-uuid <project-uuid> --document-uuid <origin-document-uuid> --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py board-document-activate --target-uuid <target-document-uuid> --target-document-type <1-or-3> --project-uuid <project-uuid> --document-uuid <origin-document-uuid> --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py export-capabilities
py scripts/easyeda_gateway.py export-safety-status
py scripts/easyeda_gateway.py schematic-export --format PNG --scope current-schematic --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py schematic-native-png-normalize --source <official-png-or-zip> --source-envelope <failed-export-envelope.json> --identity-before <before.json> --identity-after <after.json> --evidence-dir <derived-evidence-dir> --output <normalization-execution.json>
py scripts/easyeda_gateway.py schematic-native-pdf-render --source-execution <official-pdf-execution.json> --identity-before <before.json> --identity-after <after.json> --evidence-dir <derived-evidence-dir> --output <pdf-render-execution.json> --max-long-edge 6144
py scripts/easyeda_gateway.py schematic-bom-export --format csv --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py schematic-netlist-export --format jlceda --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py schematic-source-export --format epro --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py schematic-project-source-export --format epro --project-uuid <project-uuid> --document-uuid <active-page-uuid> --output <project.epro>
py scripts/easyeda_gateway.py schematic-drc --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py schematic-evidence-bundle --manifest <manifest> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py pcb-dfm-report --material FR4 --thickness-mm 1.6 --project-uuid <project-uuid> --document-uuid <pcb-uuid> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py pcb-manufacturing-svg-export --project-uuid <project-uuid> --document-uuid <pcb-uuid> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py pcb-gencad-export --project-uuid <project-uuid> --document-uuid <pcb-uuid> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py device-match-dry-run --max-components 25 --max-candidates 5 --project-uuid <project-uuid> --document-uuid <schematic-uuid> --evidence-dir <project>\evidence\gateway
py scripts/easyeda_gateway.py evidence-archive --source-dir <project>\evidence\gateway --output <evidence.zip>
py scripts/workbench.py learning-session --project <project> --page-id <hardware-learning-page-id> --level intermediate
py scripts/workbench.py learning-ask-offline --project <project> --session-id <learning-id> --shapes <selection.json> --question "<question>" --canvas-sha256 <digest>
py scripts/workbench.py learning-answer-saved --project <project> --question-id <question:uuid>
py scripts/workbench.py learning-resume --project <project> --session-id <learning:jlc-hardware-learning:page-id>
py scripts/workbench.py learning-dialogue-record --project <project> --question-id <question:uuid> --response-file <assistant-response.md>
py scripts/workbench.py learning-note-package --project <project> --canvas <hardware-learning-canvas.json> --page-id <page:id> --output <learning-note.json> --markdown-output <learning-note.md>
py scripts/workbench.py learning-live-plan --project <project> --question <question.json> --manifest <manifest> --output <plan.json>
py scripts/workbench.py learning-native-visual-import-manifest --project <project> --canvas-page-id <page:id> --identity-before <before.json> --visual-execution <native-png.json> --identity-after <after.json> --visual-mode <default-or-black-white> --output <import.json>
py scripts/workbench.py learning-pdf-visual-import-manifest --project <project> --canvas-page-id <page:id> --identity-before <before.json> --render-execution <pdf-render-execution.json> --identity-after <after.json> --visual-mode <default-or-black-white> --output <import.json>
py scripts/workbench.py learning-visual-import-route --project <project> [--requested-route png]
py scripts/workbench.py bom-sync-command --project <project> --phase freeze --bom <final.xlsx> --sheet BOM --output <frozen.json>
py scripts/workbench.py bom-sync-command --project <project> --phase plan --bom <final.xlsx> --sheet BOM --output <plan.json> --evidence-dir <evidence-dir>
py scripts/workbench.py bom-sync-command --project <project> --phase acceptance --plan <plan.json> --evidence-dir <evidence-dir>
py scripts/workbench.py bom-sync-command --project <project> --phase apply --plan <fresh-plan.json> --acceptance-report <acceptance-report.json> --evidence-dir <evidence-dir> --authorize-save
```

`lifecycle.py` and `api_contract.py` manage state and contracts without connecting to EasyEDA. `easyeda_gateway.py` is the guarded runtime adapter: it validates locked method IDs, verifies the official local bridge and EasyEDA window identity, executes the plan, and records evidence. Persistent writes remain blocked unless separate authorization and acceptance artifacts are supplied.

When `current-schematic` contains several schematic sheets, the official PNG result may be a ZIP containing one native PNG per sheet. Use the gateway's returned page inventory directly. For a previously sealed export that older validation rejected only because it expected a direct PNG signature, run `schematic-native-png-normalize`; it performs no EasyEDA API call. The learning import manifest then returns `operations[]`, one exact JLC Hardware Learning insertion per official entry. Preserve the official order, and do not claim that an individual entry is an exact current-page UUID export.

For the default learning-canvas import, export the qualified whole-schematic PDF once, recheck identity, then run `schematic-native-pdf-render`. This local adapter uses Poppler, defaults to a 6144 px longest edge, makes zero EasyEDA API calls, and seals the source PDF, renderer and every output PNG digest. Pass only its execution to `learning-pdf-visual-import-manifest`, then execute the returned ordered JLC Hardware Learning operations with `evidenceSource=official-easyeda-pdf-render`. Never pass the PDF itself to JLC Hardware Learning, render a blocked current-page PDF, or substitute EPRO-derived visuals. The native-PNG route remains available only as an explicit smaller/faster override.

Both native-PNG and PDF-derived JLC Hardware Learning imports require the selected `--visual-mode`. The manifest builder rejects a mismatch between that mode and the official export theme, and persists `visualMode` plus `easyedaExportTheme` into the manifest, image asset metadata, and shape metadata.
