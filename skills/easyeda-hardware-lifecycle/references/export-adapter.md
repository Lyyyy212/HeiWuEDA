# Official export adapters

## Boundary

All EasyEDA exports pass through a named fixed adapter. A stage module may select a qualified capability and provide expected identity, but it may not assemble `eda.*` code, call `/execute`, retry, or start several exports concurrently.

The installed runtime has one important limitation: a network timeout does not cancel the Promise already running inside EasyEDA. An unknown or hanging official call can therefore keep the page busy after the HTTP caller has returned. The export boundary prevents that failure mode with four controls:

1. reject unknown, documented-only, and known-hanging capability IDs before `/execute`;
2. allow exactly one official export call per bridge request and one request at a time;
3. never retry an export automatically;
4. open a persistent circuit breaker after a transport timeout and require EasyEDA recovery or restart plus an explicit reset reason.

Run `easyeda_gateway.py export-capabilities` before choosing a format and `export-safety-status` before live execution. Do not reset an `OPEN` breaker merely because the HTTP request ended.

## Adapter set

### `EasyedaExportAdapter`

This is the visual compatibility quarantine. It uses the official deprecated `SCH_ManufactureData.getExportDocumentFile#1` only for a pre-qualified combination and saves the returned `File` locally with `SYS_FileSystem.saveFileToFileSystem#1`, `force=false`.

The installed profile permits whole-schematic PNG and PDF. Whole-schematic SVG remains documented but unverified. All `current-page` visual combinations are `BLOCKED_KNOWN_HANG`; the adapter rejects them before any bridge execution. Never relabel a whole-schematic artifact as a page artifact.

JLC Hardware Learning imports expose exactly two user-selected official themes: `default`
maps to EasyEDA `Default`, and `black-white` maps to `Black on White`. The
choice is made before this adapter runs and is passed as its existing `theme`
field. No canvas-side recoloring is used. Passing evidence records the complete
normalized export spec so downstream import manifests can reject a selected
mode/theme mismatch.

An official PNG response is either a direct PNG or, for a multi-sheet schematic, a ZIP whose entries are all official native PNG files. The adapter securely validates the container and emits a per-entry page inventory. It does not infer an EasyEDA page UUID for any entry. A previously sealed execution that failed only because an older validator expected a direct PNG can be passed to `schematic-native-png-normalize` with the original artifact, failure envelope, and matching before/after identity records. That command is local-only, records `easyedaApiCallCount=0`, performs no retry, and writes new derived evidence without changing the immutable original failure evidence.

Ordinary typed plans continue to reject deprecated methods. Every compatibility execution records the method, reason, generated-code digest, locked declaration identity, bridge/window identity, scope, pre/post document identity, artifact signature, size, and SHA-256.

### `NativePdfVisualAdapter`

This is the default JLC Hardware Learning visual-import adapter. It consumes a successful, digest-sealed whole-schematic PDF execution from `EasyedaExportAdapter`; it never connects to the Bridge. It requires an exact schematic identity match before and after the official export, an unencrypted readable PDF, the qualified `visual.current-schematic.pdf` capability, and the original artifact inside its immutable export evidence directory. The native-PNG path is retained only for an explicit smaller/faster request.

Poppler `pdftoppm` renders every PDF page to PNG with a default 6144 px longest edge and an 8192 px hard maximum. Page count, source bytes, output dimensions, per-page bytes and total bytes are bounded. The evidence records the source PDF SHA-256, Poppler path/version/SHA-256, render settings and each PNG SHA-256, with `easyedaApiCallCount=0`, `officialCallRepeated=false`, and `automaticRetry=false`. JLC Hardware Learning receives only the PNG pages and the admitted `official-easyeda-pdf-render` evidence source; it never embeds a PDF.

### `EasyedaFormalExportAdapter`

This adapter exports one formal artifact per request:

- BOM CSV through `SCH_ManufactureData.getBomFile#1`;
- JLCEDA Pro netlist through `SCH_ManufactureData.getNetlistFile#1`;
- EPRO source through `SYS_FileManager.getDocumentFile#1`, with before/after `getDocumentSource#1` comparison.
- project EPRO through `SYS_FileManager.getProjectFile#1`, with before/after schematic-tree comparison and archive/live page-UUID set equality.

It validates UTF-16/tab BOM structure, netlist JSON components, source archive size/signature, identity stability, and no-overwrite publication. For EPRO source preservation, the before/after comparison may normalize only the volatile `DOCHEAD.client`, `DOCHEAD.updateTime`, and `DOCHEAD.version` fields already identified by the retained `$jlc` exporter; the evidence records both the raw comparison and this exact allowlist, and every other source difference remains blocking. XLSX BOM, Protel2 netlist, and EPRO2 source are present in the typed interface but blocked until separately qualified.

### `EasyedaDrcAdapter`

This adapter makes one fixed strict call: `SCH_Drc.check(true, false, true)`. It stores the verbose result as JSON and distinguishes `PASS`, `REVIEW_REQUIRED`, and `BLOCKED_BY_DRC`. A zero-error result is evidence only, not fabrication approval.

### `EasyedaOfficialPluginAdapter`

This adapter embeds three browser bundles built from exact official repository commits: JLC PCB DFM, layered manufacturing SVG, and GenCAD. Each bundle digest is checked before code generation. The adapter supplies a proxy `eda` surface that intercepts UI, log, extension-storage, and browser-download calls; the plugin can read through the locked official API surface, while its one artifact is redirected to `SYS_FileSystem.saveFileToFileSystem#1` with no overwrite.

Each bridge request invokes exactly one exported plugin function and has zero retries. DFM must contain checks 1 through 18 with internally consistent counts. SVG output must be a safe ZIP containing valid SVG XML. GenCAD must contain the required 1.4 sections. These structural checks and a zero-error DFM are not fabrication approval. Until a capability has completed a supervised live PCB qualification, it remains `DOCUMENTED_UNVERIFIED` and is rejected by the shared breaker before `/execute`.

### `EasyedaDeviceMatchDryRunAdapter`

This is a read adapter, not an export capability. It reads current-page schematic components and calls `LIB_Device.search#1` for bounded query candidates. Candidate scoring reproduces the official standardization plugin's default rule: exact target/name 100, contains 85, otherwise 60. The local report may recommend manual review, but the adapter never calls device create, component modify, or schematic save APIs.

### `EasyedaEvidenceBundleAdapter`

This is the old `$jlc` audit set rebuilt as isolated serial requests: native whole-schematic PDF, formal BOM CSV, JLCEDA netlist, EPRO source, then strict DRC. Each step rechecks project/document identity, uses the same safety state, has zero retries, and stops immediately on failure. The local audit compares BOM/netlist designator sets, quantities, duplicates, visible PDF references, required/forbidden refs, identity, and DRC status.

Do not combine these five official calls into one `/execute`; that old pattern allows one hanging Promise to hold the full batch and the EasyEDA UI.

### Retained EPRO renderers (disabled)

`OfflineSourceRenderAdapter` and `OfflineProjectSourceRenderAdapter` remain in
source for parser maintenance and regression fixtures, but their product-facing
CLI commands and learning import builders reject with `DISABLED_BY_POLICY`.
Their output is not admitted as a schematic visual because visual fidelity is
not acceptable. EPRO document/project export remains available only to typed
archive or evidence consumers. JLC Hardware Learning uses the official native
`visual.current-schematic.png` capability; review/archive may use the official
native PNG or PDF capability.

## Evidence and publication

Every live adapter creates a unique immutable evidence directory. Optional user-facing outputs are atomically copied only after validation and are never overwritten. Failure evidence is sealed before the original error is returned.

After a Bridge restart, `--allow-window-rebind` is opt-in. Rebinding is admitted only for a stale requested window, one connected replacement window, and non-empty exact project/document UUID guards. The fixed API code still verifies those identities before and after the operation, and the evidence records requested/resolved IDs and whether a rebind occurred.

Use `evidence-archive --source-dir <evidence> --output <archive.zip>` for an external handoff. The archive refuses overwrite and links/reparse points, fixes ZIP metadata for stable hashes, and contains `evidence-manifest.json` with each relative path, byte count and SHA-256.

Use a shared `--safety-state <project>\.easyeda-hardware-workbench\export-safety.json` for every export in one project. A timeout leaves that state `OPEN`. After confirming EasyEDA is responsive or restarting it, reset explicitly:

```powershell
py scripts/easyeda_gateway.py export-safety-reset `
  --safety-state <project>\.easyeda-hardware-workbench\export-safety.json `
  --reason "EasyEDA restarted and active page identity re-probed"
```

See [export-capabilities.md](export-capabilities.md) for the executable matrix and future export packages.
