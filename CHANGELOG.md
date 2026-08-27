# Changelog

## 0.8.1 - 2026-08-27

### Added

- Added the first public source release of `ZhiYuanEDA Gateway` `0.1.0` under
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
