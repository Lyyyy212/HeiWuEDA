# Canvas operations

## Open and identify the Widget

Call `mcp__jlc_hardware_learning_mcp__render_hardware_learning_canvas_widget` with the active workspace as `projectDir`, `mode=hardware-learning`, and `displayMode=fullscreen` unless inline display is requested. Reuse an open Widget.

The returned resource URI must contain the installed runtime version. Never restore the unversioned `ui://widget/jlc-hardware-learning/canvas.html`; a backend version change requires a new task or app restart before interactive acceptance.

Render the lower-right 黑五画板 watermark as an accessible link to the canonical 黑五EDA GitHub repository. It opens a new tab and never changes canvas records or exported schematic content.

## Interaction and protected evidence

Keep page/actions at upper left, style controls at upper right, tools at bottom center, and zoom/minimap at lower left. The Widget supports select/pan, learning frame, pen, eraser, text, arrow, note, rectangle, ellipse, line, highlight, marquee multi-select, duplicate, undo/redo, protected delete, style editing, fit, zoom, and keyboard shortcuts.

An ordinary rectangle is not a learning frame. Imported schematic images are protected from erasing, ordinary Delete/Backspace, duplication, resize, and restyling. Only an explicitly unlocked image may move.

The top-toolbar trash action is the single deletion entry for imported images or mixed selections. Annotation-only deletion is immediate. If an image is included, show an in-canvas confirmation, state that EasyEDA is not modified, acknowledge exactly the selected image IDs to storage, and delete the complete selection as one undoable operation. Escape/cancel leaves the selection unchanged. Ordinary Delete/Backspace remains annotation-only.

## Canvases and pages

Keep the default canvas at `<projectDir>/canvas`, additional canvases under `<projectDir>/canvases/<uuid>`, and the active stable ID in `<projectDir>/canvases/manifest.json`. Never accept a user path as a managed canvas ID. Creating a canvas activates a clean independent store. Finish writes to the previous canvas before switching storage, then reset history, selection, view polling, and hydrated asset caches.

Renaming changes catalog metadata only. The default canvas cannot be deleted. Move a deleted non-default canvas to `<projectDir>/canvases/.trash/` before removing it from the catalog.

Pages are independent. Allow create, rename, switch, and explicit delete; refuse to delete the last page. Page deletion requires in-canvas confirmation, exact protected-image acknowledgement, and one undoable history operation. Canvas/page switching never authorizes EasyEDA navigation or export.

## Pan, zoom, and rendering safety

Normal wheel zooms around the pointer; Ctrl/Cmd+wheel stays zoom-compatible and Shift+wheel pans horizontally. Space, middle/right drag, and Alt-drag temporarily pan. Clicking inside a multi-selection preserves the group. Arrow keys nudge movable selections by one unit, or ten with Shift.

Keep zoom within 8%–400%, normalize loaded camera values, and bound unusually large wheel deltas. Render the dot grid in viewport space. Never use a giant world-space SVG grid.

Fullscreen dimensions belong to the Codex host. Keep automatic document/body host resizing disabled. Observe only the canvas root, publish only positive changed internal sizes, retry a temporary 0×0 first mount for bounded animation frames, and remeasure on visibility/focus recovery. The root observer must never call a host-size notification API or alter saved camera/canvas records.

Host globals can arrive in stages. Do not treat theme/capability-only globals as storage-ready; wait for a tool result containing `projectDir` or `canvasDir`.

Render vector annotations continuously, but hydrate high-resolution bitmaps only when their bounds intersect the viewport plus bounded screen-space overscan. Clip SVG paint to the viewport and bind wheel handling natively with `passive:false`. Export may explicitly hydrate required images but must not rewrite evidence records.

## Learning frames

Frame numbers are positive, page-local, monotonic, persistent across restart, not reused after deletion, and reallocated on duplication. Migrate legacy unnumbered frames deterministically. The visible badge is part of the persisted shape and PNG/SVG export.

## Text and sticky notes

Text and notes edit inline at the clicked canvas position with a screen-aligned HTML overlay. The first click focuses the editor. Double-click existing text/note, select it and press Enter, or click it with the matching tool to reopen it; preserve content and place the caret at the end. Single-click in select mode only selects or drags.

Enter confirms, Shift+Enter inserts a newline, IME Enter does not confirm, and Tab/Shift+Tab indent/outdent. After save, return to select; only a new explicit click starts another object. Escape exits to select. Right-click cancels an editor/tool without saving an unsaved draft; preserve right-drag pan only when select was already active.

The right-side `小/中/大/特大` presets are 13/15/20/28 canvas units with 18/20/27/36 line heights. Inline editing and PNG/SVG export share the persisted size. Version-2 text metrics migrate once. Resizing text/note may reflow that container but must not alter learning-frame bounds or numbering. Style controls remain usable during editing and update the draft without blur-saving. Sticky notes preserve manually chosen width and grow vertically instead of clipping.

When select is active, a double-click at a non-text position may start new text, including over a protected schematic image. Existing text/note has priority; resize handles must never place text.

## Local export

Keep current-page PNG/SVG, selection-cropped PNG, selection copy, and full JSON backup in one compact menu. `选择文件夹…` uses the native directory picker and a short-lived canvas-bound token; never accept an arbitrary writable path from the Widget. Default exports go to `Downloads/黑五画板/`.

Success requires a concrete returned path shown with a copy-path action. Use 48 KiB Base64 chunks, a stable session, progress feedback, and idempotent retry checks so large files do not freeze the host. Cap PNG at 4096 px; SVG remains lossless. Local canvas export never authorizes EasyEDA export or write.
