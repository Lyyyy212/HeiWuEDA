# Changelog

## 0.9.0 - 2026-08-28

### Added

- Published the sanitized `黑五画板` `0.1.7` source from commit
  `a728c41a7e9ba8b1c78b4e8e107affe0fdee3240`.
- Added the `JLC-FN-1.2` Feishu learning-note standard, fixed-size learning-frame
  badges, stable distinct module colors and a raw-board acceptance validator.
- Added the `黑五EDA` protocol-v2 workbench extension `0.4.6` as a separate
  read-only developer preview with three fixed allowlisted operations.
- Added a dedicated GitHub Actions workflow that reproducibly builds and checks
  the restricted `.eext` candidate.

### Changed

- Renamed the user-visible learning canvas to `黑五画板` while retaining the
  `jlc-hardware-learning` plugin, MCP and storage identifiers for compatibility.
- Linked the canvas watermark to the `HeiWuEDA` repository and kept the
  generated Widget free of third-party runtime watermarks.
- Hid project, page, board and image binding identifiers from reader-visible
  Feishu note content while retaining them in internal registries and evidence.
- Replaced real-project demonstration screenshots with repository-contained
  abstract tutorial diagrams.

### Verification boundary

- `黑五画板` passes 107 tests plus metadata, artifact, cold-install, learning
  tool and MCP probes.
- The protocol-v2 extension passes lint, typecheck, 14 runtime tests, release
  validation and deterministic `.eext` packaging.
- The protocol-v2 extension remains a three-operation read-only preview. It
  does not replace the complete compatibility gateway, and official marketplace
  installation still requires a fresh real-client acceptance run.

## 0.8.2 - 2026-08-27

### Added

- Published the sanitized `JLC Hardware Learning` `0.1.6` source from commit
  `6f8b9e0116eed82140edd71326ca0acc16aa2c75`.
- Added project-local multi-canvas management, page-scoped official netlist
  sidecars and 12 guarded MCP operations for canvas, netlist and Feishu-note
  workflows.
- Added compact Feishu project-homepage and real-schematic-page note models,
  revision/fingerprint-gated migration, managed-range synchronization and
  fresh-read verification.
- Added a CI public-boundary scanner for private evidence directories, local
  paths, credentials, tenant URLs and live-looking identity literals.
- Normalized Vite source text before bundling so tracked Widget artifacts are
  reproducible across Windows and Linux checkouts.

### Changed

- Reduced the four canvas text presets to `13 / 15 / 20 / 28` with a one-time
  text-metric reflow that leaves learning-frame geometry unchanged.
- Added delayed first-layout recovery for a temporary `0 x 0` canvas root.
- Updated the integration lock, Widget URI, public capability profile and MCP
  validation from plugin `0.1.3`/14 tools to `0.1.6`/26 tools.

### Publishing boundary

- Excluded `docs/evidence/**` from the public plugin copy and replaced test-only
  Feishu URLs, tokens and project/page identifiers with explicit fixtures.
- Feishu writes remain disabled until an exact preview is explicitly confirmed;
  EasyEDA access remains read-only and outside the canvas runtime.

## 0.8.1 - 2026-08-27

### Added

- Added the first public source release of `黑五EDA Gateway` `0.1.0` under
  `integrations/zhiyuaneda-gateway/`.
- Added isolated gateway, WebSocket, MessageBus and storage identities without
  modifying the pinned official Run API Gateway submodule.
- Added parallel Bridge discovery, preferred-port memory, dedicated-Bridge
  preference, bounded retry backoff and heartbeat tolerance.
- Added an EasyEDA extension build and runtime-test workflow that produces a
  locally installable `.eext` developer-preview package.

### Changed

- Updated the publishing profile and README to distinguish the dedicated
  EasyEDA-side connector from the Python guarded gateway.
- Documented the new version in `docs/releases/v0.8.1.md`.

### Publishing boundary

- The dedicated extension is a GitHub developer preview. It preserves the
  official Bridge `execute` protocol for local compatibility and is therefore
  not yet the restricted-operation package intended for the EasyEDA
  Extensions Marketplace.

## 0.8.0 - 2026-08-27

- Prepared the first sanitized GitHub source release under publisher `Lyyyy`.
- Added the guarded EasyEDA API gateway and locked API manifest.
- Added UUID-bound page navigation with origin restoration.
- Added qualified PCB DFM, manufacturing SVG and GenCAD adapters.
- Added the five-stage hardware lifecycle and guarded BOM writeback handoff.
- Added the complete JLC Hardware Learning 0.1.3 source, generated artifacts
  and third-party licensing disclosures.
