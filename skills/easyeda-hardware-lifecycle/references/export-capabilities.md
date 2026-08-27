# Export capability matrix

This matrix separates an official API declaration from a runtime-qualified workflow. Only `VERIFIED_SERIAL` capabilities may reach the bridge. Query the machine-readable current matrix with `easyeda_gateway.py export-capabilities`.

## Implemented foundation

| Consumer | Capability | Runtime status | Adapter |
| --- | --- | --- | --- |
| Review / JLC Hardware Learning | whole-schematic PNG or official ZIP-of-PNG | `VERIFIED_SERIAL` | `EasyedaExportAdapter` |
| Review / archive | whole-schematic PDF | `VERIFIED_SERIAL` | `EasyedaExportAdapter` |
| JLC Hardware Learning high-zoom evidence | sealed whole-schematic PDF to bounded PNG pages | `VERIFIED_LOCAL` | `NativePdfVisualAdapter` |
| Component/connectivity analysis | structured schematic snapshot JSON | fixed read template | `CompositeReadExecutor` |
| Procurement / audit | formal BOM CSV | `VERIFIED_SERIAL` | `EasyedaFormalExportAdapter` |
| Connectivity / audit | JLCEDA Pro netlist | `VERIFIED_SERIAL` | `EasyedaFormalExportAdapter` |
| Archive only | EPRO source | `VERIFIED_SERIAL` | `EasyedaFormalExportAdapter` |
| Project page inventory | project EPRO + exact page UUID tree | `VERIFIED_SERIAL` | `EasyedaFormalExportAdapter` |
| Review gate | strict verbose DRC JSON | `VERIFIED_SERIAL` | `EasyedaDrcAdapter` |
| PCB manufacturability review | official 18-check DFM JSON | `VERIFIED_SERIAL` | `EasyedaOfficialPluginAdapter` |
| PCB manufacturing handoff | layered manufacturing SVG ZIP | `VERIFIED_SERIAL` | `EasyedaOfficialPluginAdapter` |
| PCB CAD interchange | GenCAD 1.4 | `VERIFIED_SERIAL` | `EasyedaOfficialPluginAdapter` |
| Schematic device candidate review | device-match JSON | live-qualified read-only dry-run | `EasyedaDeviceMatchDryRunAdapter` |
| Release evidence | PDF + BOM + netlist + EPRO + DRC | serial isolated steps | `EasyedaEvidenceBundleAdapter` |
| Legacy EPRO image renderer | EPRO to SVG/PNG/PDF | `DISABLED_BY_POLICY` | retained maintenance code only |
| Legacy all-page image renderer | project EPRO to ordered PNGs | `DISABLED_BY_POLICY` | retained maintenance code only |
| Evidence handoff | immutable ZIP + per-file SHA-256 manifest | local only | `create_evidence_archive` |

The old `$jlc` catalog-selection report is not an EasyEDA export. It remains in the BOM selection layer so distributor searches and part decisions do not become EDA transport responsibilities.

## Present but blocked

| Capability | Status | Reason |
| --- | --- | --- |
| current-page PNG/PDF/SVG | `BLOCKED_KNOWN_HANG` | Installed client timed out and the underlying operation can keep the page busy. |
| whole-schematic SVG | `DOCUMENTED_UNVERIFIED` | Declared officially but not qualified on this runtime. Do not substitute an EPRO-derived SVG. |
| BOM XLSX | `DOCUMENTED_UNVERIFIED` | CSV is the stable inspectable interchange format. |
| Protel2 netlist | `DOCUMENTED_UNVERIFIED` | Useful for external tools but not qualified for this integrated runtime. |
| EPRO2 source | `DOCUMENTED_UNVERIFIED` | No retained runtime evidence or parser consumer. |

The three source-pinned PCB plugin capabilities were live-qualified serially on
2026-08-24 against one exact active PCB. DFM returned all 18 numbered checks
with zero errors and zero warnings; manufacturing SVG returned 13 valid SVG
entries; GenCAD returned every required 1.4 section with 154 components and 82
signals. Each execution preserved project/document identity, used one bridge
request, made no automatic retry, and restored the original schematic page
after the qualification batch. These results qualify transport and artifact
structure only; they do not grant fabrication approval.

Do not probe blocked formats opportunistically during normal work. Qualification is a separate maintenance task with a disposable project, visible EasyEDA supervision, one call, a fresh safety state, and restart readiness.

An adapter `PASS` proves transport, identity, and artifact structure only. EPRO-derived visuals are not admitted for review or JLC Hardware Learning because their visual fidelity was rejected. JLC Hardware Learning defaults to bounded local PNG pages derived from a digest-sealed official native PDF; official native PNG is available only for an explicit smaller/faster import. Native PNG/PDF remain valid for review or archive. A native PDF with an incomplete text layer produces a review finding instead of proving that references are visually missing. Evidence-bundle acceptance is true only when the report status is exactly `PASS`.

For JLC Hardware Learning, each qualified PNG/PDF route supports two explicit import modes
without adding another capability: `default` uses official `theme=Default`, and
`black-white` uses official `theme=Black on White`. The mode must be selected
before export and match the sealed export spec; `White on Black` is not exposed
as a learning-canvas import mode.

For a multi-sheet schematic, the qualified official `current-schematic` PNG call may return a ZIP containing only native PNG entries. This remains one official capability and one Bridge call. The gateway rejects traversal, links, encryption, duplicate names, unsupported compression, non-PNG entries, excessive counts and size limits, then records each entry's official name, dimensions and SHA-256. Entry order is usable for deterministic canvas layout, but no entry may be asserted to equal a particular live document UUID because the official response does not provide that mapping.

## Future exports by downstream consumer

Add an export only when a stage has a typed consumer and acceptance contract:

1. Simulation: SPICE/simulation netlist, model manifest, analysis settings, and tool/version identity.
2. PCB fabrication: Gerber layers, NC drill, fabrication drawing, stack-up/rule summary, and optionally an independent PCB netlist when official PCB APIs support them.
3. PCB assembly: PCB-bound BOM, CPL/pick-and-place, assembly drawing, board side, units, origin, rotation convention, fiducials, and footprint/package validation.
4. Release traceability: exact symbol, footprint, and 3D-model library archives only when reproducible build or supplier handoff needs them.
5. Test/manufacturing: test-point map, boundary/ICT data, programming files, and serial-number metadata only after a manufacturing-test stage exists.

Do not create an “export everything” command. Consumer-driven packages keep the API surface smaller, make timeouts attributable to one method, and prevent unrelated large exports from blocking EasyEDA.
