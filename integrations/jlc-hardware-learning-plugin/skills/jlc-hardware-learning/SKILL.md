---
name: jlc-hardware-learning
description: Open and use the persistent JLC hardware-learning canvas for selection-scoped schematic questions, local evidence capture, whitelisted teaching annotations, and project-scoped Feishu learning-note synchronization. Use when the user wants to frame or select a schematic region, ask how its hardware works, or organize verified learning records by project and schematic page in Feishu; do not use for image generation, AI HTML, Slides, or direct EasyEDA writes.
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

The user-facing product name is `黑五画板`; keep the technical plugin ID,
MCP tool names, Widget URI prefix, and existing project storage paths unchanged
for compatibility. Render the lower-right brand watermark as an accessible link
to the canonical 黑五EDA GitHub repository. It opens a new tab and never modifies
canvas records or exported schematic content.

The hardware-learning Widget is a dedicated JLC SVG canvas, not a general
creative-canvas UI. Its frontend keeps the established arrangement: page/actions
at upper left, style controls at upper right, tools at bottom center, and
zoom/minimap at lower left. It supports select/pan, explicit learning frame,
pen, eraser, text, arrow, note, rectangle, ellipse, line, highlight, marquee
multi-select, duplicate, undo/redo, protected delete, project-canvas and page management, style
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

The top-left canvas selector manages project-local learning workspaces. Keep
the legacy/default canvas at `<projectDir>/canvas`; store additional canvases
only under `<projectDir>/canvases/<uuid>` and persist the active stable ID in
`<projectDir>/canvases/manifest.json`. Creating a canvas activates an empty,
independent store. Wait for all writes to the previous canvas before changing
the client storage target, then reset history, selection, view polling, and
hydrated asset caches before loading the new target. Renaming changes catalog
metadata only. The default canvas cannot be deleted; deleting another canvas
must move its whole directory to `<projectDir>/canvases/.trash/` before it is
removed from the catalog. Never accept a user-provided directory or path as a
managed canvas ID.

Each canvas contains one or more independent tldraw pages. The page management
control may create, rename, switch, and explicitly delete pages. Refuse to
delete the final page. Page deletion must use an in-canvas confirmation, pass
the exact image-shape IDs through the protected storage acknowledgement, and
remain one undoable history operation. Canvas switching and page switching do
not authorize an EasyEDA page activation, export, save, or write.

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
four font presets are `13 / 15 / 20 / 28` canvas units, with matching
`18 / 20 / 27 / 36` line heights. The inline editor and PNG/SVG exports use the
same persisted size. Version-2 text metrics must migrate once so existing text
and note bounds are reflowed for the smaller presets without touching frames.
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
selection, files land under `Downloads/黑五画板/`. Success requires the
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
2. Before the first visual insertion on this canvas page, call
   `mcp__jlc_hardware_learning_mcp__read_hardware_learning_page_netlist` with
   the exact canvas `pageId`. If it reports `missing`, run the lifecycle's
   official `schematic-netlist-export --format jlceda` once against the same
   before-identity, re-read and exactly match the live identity, then run
   `workbench.py learning-page-netlist-manifest`. Call the manifest's exact
   `mcp__jlc_hardware_learning_mcp__attach_hardware_learning_page_netlist`
   operation. The plugin stores `official-easyeda-netlist.net` and
   `official-easyeda-netlist.meta.json` beside that page's
   `hardware-learning-canvas.json`. Reusing the same digest is idempotent;
   different identity or content must block evidence mixing. A failed netlist
   export must be reported explicitly, but it does not delete the existing
   canvas or silently substitute an unofficial netlist.
3. Resolve transport with lifecycle `learning-visual-import-route`. With no
   explicit transport request it must return the default `pdf` route. Use the
   `png` override only when the user explicitly asks for native PNG, a smaller
   import, or a faster import. Appearance is independent: `默认配色` does not
   select PNG. Never call any blocked `current-page` visual route.
4. For the default route, run
   `schematic-export --format PDF --scope current-schematic --theme
   <Default-or-Black-on-White>` exactly once. For an explicit native-PNG
   override, run `schematic-export --format PNG --scope current-schematic
   --theme <Default-or-Black-on-White>`.
5. Re-read the live identity and require an exact match.
6. If a sealed legacy execution rejected an official PNG-only ZIP only because
   it expected a direct PNG signature, use the lifecycle gateway's local
   `schematic-native-png-normalize` command. It must report zero EasyEDA API
   calls and must retain the original failure evidence; never export again for
   this compatibility case.
7. For native PNG, run `workbench.py learning-native-visual-import-manifest
   --visual-mode <default-or-black-white>` with the before, direct export or
   normalization execution, after, and requested canvas page ID.
8. For PDF, run local-only `schematic-native-pdf-render` against the exact
   passing official PDF execution and both identity records. Keep the default
   6144 px longest edge unless a bounded alternative is justified. Require
   `easyedaApiCallCount=0`, then run
   `workbench.py learning-pdf-visual-import-manifest --visual-mode
   <default-or-black-white>` with its execution.
9. For a direct PNG, call the manifest's exact tool and `toolArgs`. For an
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
10. Read the JLC canvas state and verify every inserted image is on the
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

1. Call `mcp__jlc_hardware_learning_mcp__save_hardware_learning_question`
   directly with `projectDir`, the conversation text as `userQuestion`, an
   inferred `intent`, `learningLevel` (`intermediate` by default), and
   `responseMode=quick`. This one call resolves explicit frame numbers, current
   selection, or validated `lastNonEmptySelection`; do not issue a preliminary
   selection-tool round trip. Use `responseMode=deep` only when the user asks
   for deep analysis or the question genuinely requires live/high-stakes
   evidence. Set `annotationRequested=true` only when the user explicitly asks
   to add a note, highlight, rectangle, or arrow to the canvas.
2. Resolve the returned immutable record under
   `<projectDir>/.easyeda-hardware-workbench/learning/questions/`. A
   `question:<uuid>` ID is stored as `question-<uuid>.json`. The record also
   reports whether a verified page-local official netlist is available.
3. Run `workbench.py learning-answer-saved --project <projectDir>
   --question-id <questionId>` and use its durable offline answer as the quick
   baseline. For component references or connectivity, call
   `mcp__jlc_hardware_learning_mcp__read_hardware_learning_page_netlist` with
   bounded `componentRefs` or `netNames`; never load the whole netlist merely
   because it exists.
4. Ordinary explanations stay local: do not open live EasyEDA, browse the web,
   or perform distributor/datasheet research unless the question requests deep
   analysis, current procurement facts, component selection, or another source
   that cannot be answered from saved visual and netlist evidence.
5. Explain at the requested learning level, separating evidence, inference,
   unknowns, and suggested checks. Never create a sticky note automatically.
   Only after explicit annotation intent may the exact page-bound operation be
   passed to the annotation tool; retrying must reuse the same IDs.
6. Before ending the conversation turn, persist the exact response shown to the
   user through `workbench.py learning-dialogue-record`. For a follow-up, reuse
   the same session ID; `workbench.py learning-resume` recovers the ordered
   local history after a restart.

## Synchronize Feishu learning notes

Before planning, creating, exporting, or editing a Feishu hardware-learning note,
read and apply [references/feishu-learning-note-standard.md](references/feishu-learning-note-standard.md).
Treat its document layout, paired-whiteboard contract, fixed-size number badge,
stable color mapping, confirmation gate, and post-write acceptance checks as one
versioned standard. A schematic image may scale a learning frame, but it must
never scale the number badge. A module-index detail branch contains one concise
sentence summarizing that module; progress labels such as `待学习` belong in the
Docx status table, not in the mind map.

Organize Feishu notes by readable project name, but bind them by stable
`projectId/projectUuid`. A canvas page maps to one long-lived Feishu Docx, one
reused main `whiteboardToken`, and one reused `moduleIndexWhiteboardToken`;
learning-frame numbers remain page-local. Never use a
renamed title, duplicate page name, or frame number alone as an identity.
Keep project, schematic-page, board, and image binding identifiers internal to
the registry, sync plan, node attributes, and verification evidence. Never
render them as reader-visible Docx titles, paragraphs, callouts, image captions,
tables, or mind-map text; use readable project and page names instead.

1. For an existing legacy learning note, first call
   `mcp__jlc_hardware_learning_mcp__inspect_feishu_learning_note_target`. It uses
   official `lark-cli` with user identity and requires outline/full fresh reads
   to return the same document token and revision. Then call
   `mcp__jlc_hardware_learning_mcp__preview_feishu_learning_note_migration` with
   the verified EasyEDA project name/UUID and project directory. The preview
   must reuse the existing Docx plus both existing whiteboard tokens and must
   report zero local and remote writes.
2. Otherwise call `mcp__jlc_hardware_learning_mcp__get_feishu_learning_note_state` with
   the project identity and known canvas/schematic pages. This is a read-only
   preview and returns the compact project-homepage layout, current local registry,
   and deterministic pending sync actions.
   The `00..99` categories are headings inside the one project homepage; never
   create one empty Wiki/Docx node per category. Only real schematic pages are
   direct child Docx nodes of the project.
3. Use Feishu user identity for personal Wiki/Docs resources. Route Wiki node
   creation through the Feishu Wiki capability, Docx content through the Feishu
   Docs capability, and both existing boards through the Feishu Whiteboard
   capability. Existing `board_token` values must be updated; never replace
   either with a new blank board. A cross-project Base index is optional and does not replace
   the per-project Wiki/Docx hierarchy.
4. Before any remote write, show the exact target nodes/documents and obtain the
   user's confirmation. Reuse the sync plan's stable idempotency key for retries.
   After every write, freshly read the resulting node, document, or board token.
5. For an approved legacy migration, call
   `mcp__jlc_hardware_learning_mcp__execute_feishu_learning_note_migration` with
   `confirmed=true`, the exact preview `planFingerprint`, and the previewed
   `expectedDocumentRevisionId`. The tool must re-preview before writing, create
   or reuse only unique exact-name Wiki nodes, move the original Docx, preserve
   both board tokens, apply only local text replacements, fresh-read verify, and
   save the registry only after every verification succeeds. A fingerprint or
   revision change requires a new preview and confirmation.
6. For independently verified atomic operations, only after the fresh read succeeds, call
   `mcp__jlc_hardware_learning_mcp__update_feishu_learning_note_state` to store
   the verified binding locally. Supported actions are `initialize`,
   `bind-root`, `bind-project`, the legacy-compatible `bind-section`, `bind-page`,
   `upsert-frame`, `link-dialogue`, `mark-project-homepage-synced`, and
   `mark-page-synced`. Do not use `bind-section` in the compact layout.
7. `link-dialogue` must consume the durable `questionId`, canvas page, frame
   numbers, and answer digest from the saved learning dialogue. It must not
   scrape previous Codex messages. Call `mark-page-synced` only after a fresh
   Docx read verifies the page template and module index represented by the
   current content digest.
8. Before continuous Docx synchronization, call
   `mcp__jlc_hardware_learning_mcp__bind_feishu_page_identity_from_learning_evidence`
   when `schematicPageUuid` is missing. It may persist the local identity only
   when every registered frame resolves through the saved note package to one
   official EasyEDA schematic page in the same project; never infer identity
   from a title. Link a completed question with
   `mcp__jlc_hardware_learning_mcp__link_feishu_learning_dialogue_from_record`,
   which must verify the saved question/run/answer records and their digests.
9. Call `mcp__jlc_hardware_learning_mcp__preview_feishu_learning_note_sync`
   before every continuous sync. Show its exact target Docx tokens, both reused
   board tokens, managed block patches, complete `expectedDocumentRevisions`,
   blockers, and `planFingerprint`. Only after the user confirms that exact
   preview may `mcp__jlc_hardware_learning_mcp__execute_feishu_learning_note_sync`
   be called with `confirmed=true`, the same fingerprint, and the complete
   revision map. The executor may insert or replace only the JLC-managed module
   index and dialogue ranges. It must preserve unrelated Docx blocks and both
   existing board tokens, fresh-read verify both managed digests, and save the
   registry once after all verification succeeds.

The local registry lives at
`<projectDir>/.easyeda-hardware-workbench/learning/feishu-learning-note-registry.json`.
The inspect and migration-preview tools call Feishu read-only; the state tools
do not call Feishu. None grants remote-write permission. The default hierarchy
is `硬件学习笔记 / <项目名称> / <真实原理图页>`; `00..99` lives inside the
project homepage as headings. An existing standalone Drive Docx is moved
directly under the project instead of being copied into a duplicate document
or placed under an empty category Docx.
If authentication, scope, target identity, or fresh-read verification is
missing, leave the pending sync action unresolved and do not record a guessed
token.

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
