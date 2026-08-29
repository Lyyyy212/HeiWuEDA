# Official EasyEDA schematic import and navigation

The Widget never calls EasyEDA. Import is requested in the normal conversation and routed through `easyeda-hardware-lifecycle`.

## Appearance and transport

Before export, require exactly one appearance choice. If absent, ask: `请选择原理图导入模式：默认配色，还是黑白配色？`

- `默认配色` -> `visual-mode=default` -> official theme `Default`.
- `黑白配色` -> `visual-mode=black-white` -> official theme `Black on White`.

Do not expose White on Black, infer a choice, or recolor in the canvas. Appearance does not choose transport. The default transport is official whole-schematic PDF followed by a local 6144px PNG render. Native PNG is used only when the user explicitly asks for a smaller or faster import.

## First-import netlist sidecar

Persist live `projectUuid`, `documentUuid`, and `documentType=1`. Before the first visual insertion on the target canvas page, call `read_hardware_learning_page_netlist` with its exact `pageId`.

If missing, execute official `schematic-netlist-export --format jlceda` once against the same before-identity, re-read identity and require an exact match, then run `workbench.py learning-page-netlist-manifest`. Execute only the manifest's exact `attach_hardware_learning_page_netlist` operation.

The plugin stores `official-easyeda-netlist.net` and `official-easyeda-netlist.meta.json` beside that page's `hardware-learning-canvas.json`. Same evidence is idempotent; different identity or content blocks. Report failure explicitly and never substitute an unofficial netlist or perform a second automatic export.

## Default PDF route

1. Resolve `learning-visual-import-route` without an override and require `pdf`.
2. Run official `schematic-export --format PDF --scope current-schematic --theme <theme>` exactly once.
3. Re-read live identity and require an exact match.
4. Run local-only `schematic-native-pdf-render` against that sealed execution and both identity records, normally with `--max-long-edge 6144`. Require `easyedaApiCallCount=0`.
5. Run `learning-pdf-visual-import-manifest --visual-mode <mode>`.
6. Execute every returned insertion once and in order. Require `evidenceSource=official-easyeda-pdf-render`, `replaceAiImageHolder=false`, `displayWidth=1536`, no `displayHeight`, and the manifest's 120-unit multi-page margin.
7. Verify page ID, source-PDF digest, PDF page index, rendered-PNG digest, renderer identity/settings, visual source, document UUID, visual mode, and EasyEDA theme.

The PDF is evidence/archive material and is never passed directly to the canvas image tool.

## Explicit native-PNG route

Use only after an explicit faster/smaller/native-PNG request.

1. Run official `schematic-export --format PNG --scope current-schematic --theme <theme>` exactly once against the persisted identity.
2. Re-read identity and require an exact match.
3. If a sealed legacy execution rejected an official PNG-only ZIP only because it expected a direct PNG signature, run local-only `schematic-native-png-normalize`; preserve the failure evidence and do not export again.
4. Run `learning-native-visual-import-manifest --visual-mode <mode>`.
5. Execute the manifest's exact tool/arguments or each ordered `operations[]` item once. Require `evidenceSource=official-easyeda-export`, `replaceAiImageHolder=false`, `displayWidth=1536`, no `displayHeight`, and the manifest margin.
6. Verify native PNG digest, bundle index/order, visual source, page ID, document UUID, visual mode, and theme.

The official artifact remains `current-schematic`; never relabel a bundle entry or PDF-rendered page as an exact EasyEDA current-page export.

## Navigation

Navigate only after an explicit request. List pages freshly, resolve the requested name to exactly one UUID, and bind activation to the current project and origin-page UUID. A deliberate activation may leave the requested page active; traversal must restore and verify the origin. Canvas open/import/question never authorizes navigation.

## Failure boundaries

Preserve the existing canvas on any failure and report the failed evidence gate. Never implicitly switch pages, automatically retry a timed-out export, use any blocked `current-page` visual route, render EPRO, or fall back to generated imagery. EPRO remains archive-only.
