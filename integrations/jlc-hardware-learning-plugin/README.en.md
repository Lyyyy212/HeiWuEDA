# Black Five Canvas (黑五画板)

An independent hardware-learning canvas plugin for Codex. It uses official EasyEDA PNG exports or locally rendered PDF pages as visual evidence, supports schematic-region framing and normal-conversation questions, accepts teaching annotations, manages independent canvases and pages, attaches official page-netlist sidecars, and exports PNG, SVG, and JSON.

The plugin does not generate images, upload telemetry, or write directly to EasyEDA projects. EasyEDA access remains read-only and is handled by the hardware lifecycle layer through official `eda.*` APIs.

## Components

- Plugin: `jlc-hardware-learning`
- Skill: `$jlc-hardware-learning`
- MCP server: `jlc_hardware_learning_mcp`
- Widget: `黑五画板`

## Development and verification

```powershell
npm install
npm run build:artifacts
npm run quality
```

Release artifacts are written to `mcp/generated/`. Validate the plugin and skill with the Codex Plugin Creator and Skill Creator validators before publishing.

## Project data

The legacy/default canvas remains in the active project's `canvas/` directory. Additional canvases use stable IDs under `canvases/`, and deleted non-default canvases are moved into the project-local trash directory:

```text
canvas/
  hardware-learning-selection.json
  hardware-learning-view-state.json
  pages/
    manifest.json
    <page-id>/
      hardware-learning-canvas.json
      assets/
canvases/
  manifest.json
  <canvas-uuid>/
    pages/
  .trash/
```

Legacy canvas filenames and metadata are accepted only as migration input. The next save writes the new `hardware-learning-*` filenames and `hardwareLearning*` metadata.

## Feishu learning notes

The compact note model keeps `00..99` categories as headings inside one project homepage and creates separate Docx pages only for real schematic pages. Migration and continuous synchronization are preview-first: remote writes require explicit confirmation of the exact plan fingerprint and expected revisions, reuse the existing Docx and both whiteboards, update only JLC-managed ranges, and persist the local registry only after fresh-read verification. The public source contains Fixture-only test identities and no live tenant URLs or tokens.

## Environment variables

- `JLC_HARDWARE_LEARNING_PLUGIN_ROOT`: plugin root.
- `JLC_HARDWARE_LEARNING_PROJECT_DIR`: project that owns the canvas.
- `JLC_HARDWARE_LEARNING_CANVAS_DIR`: canvas directory; defaults to `<projectDir>/canvas`.
- `JLC_HARDWARE_LEARNING_PORT`: local development server port; defaults to `43217`.

The original MIT license text and Git history remain to satisfy the license of inherited source code. The user-facing product name is Black Five Canvas (黑五画板); technical plugin IDs and MCP tool names retain `jlc-hardware-learning` for compatibility.
