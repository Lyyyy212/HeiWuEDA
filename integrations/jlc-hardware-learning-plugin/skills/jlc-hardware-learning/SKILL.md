---
name: jlc-hardware-learning
description: Open and use the persistent JLC hardware-learning canvas for selection-scoped schematic questions, local evidence capture, and whitelisted teaching annotations. Use when the user wants to frame or select a schematic region and ask how its hardware works; do not use for image generation, AI HTML, Slides, or direct EasyEDA writes.
---

# JLC Hardware Learning

Use this plugin as the canvas adapter for the `easyeda-hardware-lifecycle` learning workflow. The canvas captures the user's frame or selection; the normal Codex conversation captures the question. The lifecycle skill owns hardware reasoning, official EasyEDA evidence, and page-identity rules.

## Open the learning canvas

Call `mcp__jlc_hardware_learning_mcp__render_hardware_learning_canvas_widget` with:

- `projectDir`: the active user workspace, never this plugin directory;
- `mode`: `hardware-learning`;
- `displayMode`: `fullscreen`, unless the user requests inline display.

Reuse an already-open learning canvas. Do not render a second widget merely to read state or answer a follow-up.

The MCP resource URI must include the runtime plugin version. When validating a
new installation, require the render result's `resourceUri` to match that exact
version before treating the visible canvas as current. Never restore the fixed
`ui://widget/jlc-hardware-learning/canvas.html` URI: the Codex Widget host may otherwise reuse
a stale frontend even though the plugin files changed. A backend URI/version
change requires a new task or app restart before interactive acceptance.

The hardware-learning Widget is a dedicated JLC SVG canvas, not a general
creative-canvas UI. Its frontend keeps the established arrangement: page/actions
at upper left, style controls at upper right, tools at bottom center, and
zoom/minimap at lower left. It supports select/pan, explicit learning frame,
pen, eraser, text, arrow, note, rectangle, ellipse, line, highlight, marquee
multi-select, duplicate, undo/redo, protected delete, page switching, style
editing, fit, zoom, and keyboard shortcuts. A question region must be an
explicit learning frame; never treat an ordinary rectangle as a selection
frame. Imported schematic images remain protected from erase, ordinary
Delete/Backspace, duplication, resize, and restyling. Their position has an
explicit user-owned lock state: select an image and use the lock/unlock control;
only an unlocked image may be dragged. The top toolbar trash icon is the single
selection-deletion entry and must be enabled for annotations, imported
schematics, and mixed selections. An annotation-only click deletes immediately;
if any image is included, it must show an in-canvas confirmation, state that the
EasyEDA project is not modified, acknowledge only the exact selected image IDs
to the protected storage gate, and delete the complete selection as one
undo/redo history item. Ordinary Delete/Backspace remains annotation-only.
Canceling or pressing Escape must leave the complete selection unchanged.
Escape otherwise cancels the active gesture/editor and returns the canvas to
the select tool.

Use the normal wheel to zoom around the pointer: wheel up zooms in and wheel
down zooms out. `Ctrl/Cmd + wheel` remains zoom-compatible, and
`Shift + wheel` pans horizontally. Space, middle/right drag, and Alt-drag
temporarily pan without changing the selected tool. Clicking an object already
inside a multi-selection preserves the group for a shared drag; movable
annotations and explicitly unlocked schematic images move together, while
locked evidence stays fixed. Arrow keys nudge a movable selection by one canvas
unit and `Shift + Arrow` uses ten. A canceled inline text edit must restore the
existing record and must not be re-saved by the following blur event.

Keep camera zoom inside the render-safe `8%` to `400%` range. Loaded camera
values must be normalized before rendering, and unusually large wheel deltas
must be bounded without losing pointer-centered zoom. Render the dot grid in
viewport space; never restore a giant world-space SVG grid that expands with
the camera transform, because it can exhaust the Widget's Chromium raster
surface and blank the entire canvas. These guards affect only view state and
the background grid; they must not resize, move, renumber, or rewrite any
learning frame, annotation, imported schematic, or saved canvas record.

Treat a fullscreen Widget's dimensions as Codex-host-owned. Keep the ext-apps
automatic document/body resize observer disabled and never report the
fullscreen viewport size back to the host, because that creates a container
resize feedback loop that can blank the Widget surface. Any explicit inline
size notification must ignore non-positive dimensions and deduplicate an
unchanged width/height pair. This affects only host layout negotiation and must
not modify the saved camera or canvas records.

Independently observe only the canvas root element to maintain the frontend's
internal viewport size. The first mount can expose a temporary `0 x 0` root, so
combine the root `ResizeObserver` with a bounded animation-frame retry and
remeasure on visibility/focus recovery. Publish only positive, changed sizes to
React state. This local observer must never call a host size-notification API,
change the host container, or modify the saved camera and canvas records.

Codex host globals can arrive in stages. Theme or capability-only
`openai:set_globals` events do not make the canvas storage-ready and must not
consume the bootstrap listener. Continue waiting until the tool result exposes
`projectDir` or `canvasDir`, then begin MCP-backed canvas reads and writes.

Do not keep every high-resolution schematic image mounted in one transformed
SVG world layer. Render vector annotations continuously, but mount and hydrate
bitmap evidence only when its page bounds intersect the viewport plus a bounded
screen-space overscan. Clip the SVG paint area to the viewport and keep the
viewport paint-contained. Export may hydrate every required image explicitly;
viewport culling must never delete, move, resize, relabel, or downsample the
saved evidence records. Bind the canvas wheel handler natively with
`passive: false` so its prevented zoom event cannot escape to the host.

Every explicit learning frame has a visible positive integer number scoped to
its canvas page. Numbers increase monotonically, survive save/restart, are not
reused after deletion, and are reallocated when a frame is duplicated. Legacy
frames without numbers are assigned deterministic numbers during load. Treat
phrases such as `模块1`, `学习框2`, `1和2`, or `1、2` as explicit current-page
frame references. Explicit number references override the incidental current
selection; missing or duplicate numbers are errors and must never fall back to
another frame or another page.

Text and sticky-note tools edit inline at the clicked canvas position; there is
no separate text-entry panel. The first canvas click synchronously mounts and
focuses the editor, so the user can type immediately without clicking a second
time. The editor is a screen-aligned HTML overlay, not an SVG `foreignObject`,
so it remains focusable in the Codex Widget host.
Double-click existing text or a sticky note to edit it in place. The editor
keeps the existing content and positions the caret at its end so typing extends
the prior text instead of replacing it. Detect the second activation from the
completed pointer cycle before the canvas root captures the next pointer; do
not depend on a later `click` event reaching the SVG shape. A selected text or
sticky-note resize handle must feed the same activation path, because at low
zoom the handles can cover the shape; a real handle drag must still resize.
Keep native double-click only as a fallback and initialize the editor once. A
single click in select mode must continue to select or drag; frames, ordinary
rectangles, images, and other annotations must never enter text editing. Enter
confirms and keeps the matching
text or sticky-note tool armed for another explicit canvas click;
Shift+Enter inserts a newline, while an IME composition Enter must not confirm
prematurely. Tab and Shift+Tab indent or outdent the current line or selection.
Existing content can also be reopened by selecting it and pressing
Enter, or by activating the matching text/note tool and clicking the existing
shape once. Saving must not create a shape by itself; only the user's next
explicit canvas click begins another editor. Escape exits to select. When a text or
sticky-note shape is selected, the right-side
`小 / 中 / 大 / 特大` size controls must change its font size immediately; the
four font presets are `26 / 30 / 40 / 56` canvas units, with matching doubled
line heights. The inline editor and PNG/SVG exports use the same persisted size.
Changing text size may reflow or grow only the text/sticky-note container; it
must never alter a learning frame's position, width, height, stored bounds,
number, or reference semantics. The style
panel remains interactive while text is being edited: changing size, color,
fill, dash, or opacity must keep the editor open and update the current draft
instead of causing a blur-save. Text grows to its content width and height up to
the documented limits. Sticky notes keep their working width, wrap long Chinese
or Latin content, and grow vertically so saved and exported lines are not
silently clipped; a manually resized note keeps that width across later edits.
The style panel applies to editable selected annotations and
otherwise sets the style for the next annotation. It must never restyle an
imported schematic image.

When select is active, a double-click at any non-text page position, including
on top of a protected schematic image, must begin a new inline text editor at
that point and arm the text tool. Existing text or sticky notes retain priority
and reopen instead; resize handles must never place text. Enter commits the
draft and keeps text armed. Right-click must cancel an active editor or exit an
active annotation tool and return to select. Cancellation must not save an
unsaved draft. Preserve right-drag panning only when select is already active
and no editor or other gesture needs to exit.

The Widget keeps current-page PNG/SVG, selection-cropped PNG, selection copy,
and complete JSON backup inside one compact export menu. The menu shows the
active save location. `选择文件夹…` opens the native system directory picker;
the backend returns a short-lived token bound to this canvas instead of
allowing the Widget to submit an arbitrary writable path. Without a custom
selection, files land under `Downloads/JLC硬件学习画板/`. Success requires the
Bridge to return a concrete file path, which stays visible on the canvas with
a copy-path action. Large widget downloads use the chunked local Bridge path
so page PNG/SVG payloads do not freeze the host. Transfers use 48 KiB base64
requests, a stable download session, progress feedback, and idempotent retry
validation; PNG export is capped at 4096 px while SVG remains the lossless
option. These local canvas operations do not authorize an EasyEDA export,
save, or write.

## Import an official EasyEDA schematic visual

The Widget has no separate import or question panel. When the user asks in the
normal conversation to import the current schematic visual, read the retained
canvas page ID and handle the request through the lifecycle skill. The Widget
must not call EasyEDA itself.

Before any export, resolve one explicit appearance mode. If the user did not
already specify `默认配色` or `黑白配色`, ask: `请选择原理图导入模式：默认配色，还是黑白配色？`
Do not start the Bridge export until they answer. Map
`默认配色` to lifecycle `visual-mode=default` and official EasyEDA
`theme=Default`; map `黑白配色` to `visual-mode=black-white` and official
`theme=Black on White`. Do not expose `White on Black`, silently choose a mode,
or recolor the image in the learning canvas.

1. Persist the live EasyEDA `projectUuid`, `documentUuid`, and `documentType=1`.
2. Resolve transport with lifecycle `learning-visual-import-route`. With no
   explicit transport request it must return the default `pdf` route. Use the
   `png` override only when the user explicitly asks for native PNG, a smaller
   import, or a faster import. Appearance is independent: `默认配色` does not
   select PNG. Never call any blocked `current-page` visual route.
3. For the default route, run
   `schematic-export --format PDF --scope current-schematic --theme
   <Default-or-Black-on-White>` exactly once. For an explicit native-PNG
   override, run `schematic-export --format PNG --scope current-schematic
   --theme <Default-or-Black-on-White>`.
4. Re-read the live identity and require an exact match.
5. If a sealed legacy execution rejected an official PNG-only ZIP only because
   it expected a direct PNG signature, use the lifecycle gateway's local
   `schematic-native-png-normalize` command. It must report zero EasyEDA API
   calls and must retain the original failure evidence; never export again for
   this compatibility case.
6. For native PNG, run `workbench.py learning-native-visual-import-manifest
   --visual-mode <default-or-black-white>` with the before, direct export or
   normalization execution, after, and requested canvas page ID.
7. For PDF, run local-only `schematic-native-pdf-render` against the exact
   passing official PDF execution and both identity records. Keep the default
   6144 px longest edge unless a bounded alternative is justified. Require
   `easyedaApiCallCount=0`, then run
   `workbench.py learning-pdf-visual-import-manifest --visual-mode
   <default-or-black-white>` with its execution.
8. For a direct PNG, call the manifest's exact tool and `toolArgs`. For an
   official multi-page PNG bundle, call each exact `operations[]` item in order.
   Require
   `mcp__jlc_hardware_learning_mcp__insert_hardware_learning_image`,
   `replaceAiImageHolder=false`, `evidenceSource=official-easyeda-export`, and
   the manifest-provided `displayWidth=1536`. Do not add `displayHeight` because
   the canvas must preserve the native aspect ratio; multi-page entries use the
   manifest's 120-unit layout margin.
   For PDF-derived pages, call every exact `operations[]` item in order and
   require `evidenceSource=official-easyeda-pdf-render`, `displayWidth=1536`,
   no `displayHeight`, and the manifest-provided 120-unit margin.
9. Read the JLC canvas state and verify every inserted image is on the
   requested page with the expected native PNG digest, native bundle index,
   visual source, and captured document UUID. PDF-derived entries additionally
   require the source PDF digest, PDF page index, renderer identity, render
   settings, and rendered PNG digest.
   For both routes, also verify `visualMode` and `easyedaExportTheme` on the
   manifest, asset metadata, and shape metadata.

The official `current-schematic` artifact must never be relabeled as an exact
current-page export. The order and filenames in an official multi-page bundle
may be preserved, but no entry may be assigned an inferred live page UUID.
Native PDF is allowed for review/archive and may be locally rasterized by the
lifecycle gateway, but the PDF itself is never passed to the canvas image tool.
The PDF-derived PNG evidence class is `official-easyeda-pdf-render`. EPRO source and project archives may still be
captured for non-image archival consumers; `schematic-source-render`,
`schematic-project-source-render`, page-import manifests, and all-project image
imports are disabled by policy.

On any failure, preserve the existing canvas and report which evidence gate
blocked. Never switch EasyEDA pages implicitly, retry a timed-out export
automatically, use EPRO-derived images, call the blocked current-page visual
export, or fall back to generation.

## Navigate EasyEDA schematic pages

When the user explicitly asks to list or switch EasyEDA pages, route through the
lifecycle skill's official page navigator. List pages first, resolve a page name
to exactly one freshly captured UUID, and bind activation to the current project
and origin-page UUID. A deliberate activation may leave the requested page
active; a traversal must restore and verify the origin page. The Widget never
calls this adapter and opening the canvas, importing an image, or asking a
question never authorizes navigation. Page activation does not make an official
`current-schematic` PNG an exact current-page image.

## Answer a selection question

1. Call `mcp__jlc_hardware_learning_mcp__get_hardware_learning_selection`. Prefer explicit numbered references in the conversation. Otherwise prefer the current non-empty selection. If clicking the conversation cleared it, use `lastNonEmptySelection` only after its page and shape IDs still resolve in the saved canvas. If neither is available, ask the user to draw or select a frame; never guess.
2. Call `mcp__jlc_hardware_learning_mcp__save_hardware_learning_question` with `projectDir`, the conversation text as `userQuestion`, an inferred `intent`, and `learningLevel` (`intermediate` by default). The tool creates the `questionId`, resolves one or more current-page frame numbers when present, builds a validated page-coordinate envelope, includes overlapping source images, and records the selected and explicitly referenced frame numbers.
3. Resolve the returned immutable record under `<projectDir>/.easyeda-hardware-workbench/learning/questions/`. A `question:<uuid>` ID is stored as `question-<uuid>.json`.
4. Run the `easyeda-hardware-lifecycle` command `workbench.py learning-answer-saved --project <projectDir> --question-id <questionId>`. This imports the conversation-backed record, verifies any saved PNG digest, creates or resumes the page-bound session, and idempotently stores evidence and a tutor answer.
5. Use the returned durable answer as the baseline. Treat offline canvas shapes and images as offline artifacts; do not present them as live EasyEDA evidence. For a follow-up, reuse the same session ID; `workbench.py learning-resume` must recover the ordered local history after a restart.
6. If live EasyEDA evidence is required, use only the official gateway and recheck project/document/page identity before and after capture. Page navigation requires the user's explicit request and the lifecycle navigator; never switch pages merely to answer a question.
7. Explain at the requested learning level, separating evidence, inference, unknowns, and suggested checks. If `annotationRequest` is present, pass its exact page-bound operation to the annotation tool; retrying the same question must reuse the same IDs.
8. Before ending the conversation turn, persist the exact response shown to the user through `workbench.py learning-dialogue-record`. This binds the normal conversation to the immutable question, current canvas page, selected/referenced frame numbers, and tutor-answer digest. Later Feishu learning-note synchronization must consume this record rather than attempting to scrape old Codex conversation UI.

## Add teaching annotations

Use `mcp__jlc_hardware_learning_mcp__insert_hardware_learning_annotations` only after preparing page-bound commands. Allowed kinds are `note`, `highlight`, `rectangle`, and `arrow`.

- Keep one stable `operationId` for retries.
- Every command must repeat the same `operationId` and exact `pageId`.
- Give every command a stable `commandId`, page-coordinate `bounds`, and concise teaching text where applicable.
- Never include image, imageUrl, assetUrl, HTML, embed, video, or Slides fields.
- Let the widget pull, apply, and acknowledge operations idempotently. Do not write the full canvas snapshot to simulate annotations.

## Hard boundaries

- Do not call image-generation, image-editing, AI HTML, or AI Slides workflows.
- Do not enable telemetry or analytics.
- Do not write to or save EasyEDA from a learning request.
- Do not merge evidence from different EasyEDA documents or canvas pages.
- Do not use EPRO-derived SVG, PNG, or PDF as a learning-canvas image.
- A teaching answer is not a schematic-review gate, BOM decision, or fabrication approval.
