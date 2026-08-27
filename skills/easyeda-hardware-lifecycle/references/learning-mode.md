# Hardware learning canvas mode

Use this mode when the user wants to select or frame a JLC Hardware Learning schematic image,
ask a hardware question, enrich the answer with optional live EasyEDA evidence,
or write ordinary explanatory annotations back to JLC Hardware Learning.

## Boundary

- JLC Hardware Learning is a canvas UI provider. It never calls EasyEDA directly.
- Offline mode uses only the selected JLC Hardware Learning image, shapes, text and screenshot.
- Live mode emits a locked `READ` API plan for the official gateway. Bind the
  result to project/document identity before and after the call.
- Page navigation is allowed only after an explicit user request naming a
  freshly listed, unambiguous page. It uses the lifecycle page navigator rather
  than a learning or canvas module.
- `stale` evidence cannot support claims or canvas writeback.
- Learning mode never invokes image generation, annotation-driven image edit,
  AI HTML, Slides, telemetry, or EasyEDA write methods.
- Canvas writeback permits only note, highlight, rectangle and arrow commands.

## Offline flow

1. Create a local learning session with `workbench.py learning-session`.
2. Normalize the selected shapes with `LearningCanvasAdapter`.
3. Save `LearningQuestion`, offline `EvidenceBundle`, and `TutorAnswer` through
   `LearningSessionStore`.
4. Return the answer in Codex. Canvas annotation remains separately authorized.

For a question typed in the normal Codex conversation, first read the current or
retained last non-empty JLC Hardware Learning selection and call the model-visible
`save_hardware_learning_question` tool. It creates a validated page-bound record and
adds any source image intersected by a drawn rectangle. Then use `workbench.py
learning-answer-saved`. The workflow verifies the record and any saved PNG digest,
imports an enriched canonical question, creates or resumes the same-page session,
and derives stable evidence, answer, operation and command IDs.
Replaying the command returns the existing artifacts. Use `workbench.py
learning-resume` to recover the ordered question/evidence/answer history after a
Widget or Codex restart. A session must never merge different JLC Hardware Learning page IDs.

After composing the exact response that will be shown in the normal Codex
conversation, persist it with `workbench.py learning-dialogue-record --project
<project> --question-id <questionId> --response-file <utf8.md>`. This response is
stored separately from the deterministic tutor baseline, is immutable, and binds
to the same question, JLC Hardware Learning page, frame numbers, and tutor-answer digest. Do not
scrape or reconstruct prior Codex messages later.

Learning frames have visible page-local monotonic numbers. Creation reserves the
next number, deletion never releases it, duplication reserves another number,
and legacy frames receive deterministic numbers during migration. Explicit
conversation references such as `模块1`, `学习框2`, or `1和2` override incidental
mouse selection and resolve only on the persisted current JLC Hardware Learning page. The
question envelope stores `selectedFrameNumbers` and `referencedFrameNumbers` so
durable answers, notes, and resumed history retain stable module identities.

Six deterministic fixtures under `materials/fixtures/learning/` cover an
inverting op-amp, RC low-pass, LDO/decoupling, MCU UART, differential chain,
and image/netlist conflict.

## Live read-only flow

1. Start from a `LearningQuestion` whose `easyedaContext.mode` is
   `live-verified` and contains project/page/window identity.
2. Build a plan with `workbench.py learning-live-plan`.
3. Validate and execute it through `easyeda_gateway.py`; do not send raw JS.
4. Normalize the result. Identity drift produces `stale`; missing evidence
   produces `partial` rather than an invented claim.
5. Prefer structured `SCH_Net` evidence over a wire's transient net field.

The installed EasyEDA profile blocks every `current-page` visual export because that scope has timed out and can keep the page busy. Never call that route from learning mode.

## Explicit EasyEDA page navigation

Use `schematic-pages` to capture the current schematic's ordered page UUIDs and
names. When the user explicitly asks to switch, resolve the requested name to
exactly one UUID, then call `schematic-page-activate` with the freshly captured
project UUID and origin-page UUID. For a multi-page evidence consumer, call
`schematic-page-traverse` or use the same adapter in a `try/finally` flow that
restores the origin page. Never switch merely because the JLC Hardware Learning canvas opened,
an image import was requested, or a question was asked.

Navigation changes only the active EasyEDA tab; it does not authorize a save or
make `current-schematic` PNG/PDF page-specific. Keep the blocked `current-page`
visual route and all EPRO image renderers disabled.

To import a schematic visual into JLC Hardware Learning, use the guarded
official-PDF-to-bounded-PNG route by default. The guarded native PNG route is an
explicit smaller/faster override only. Resolve this with `workbench.py
learning-visual-import-route`: omit `--requested-route` for the maintained PDF
default, and pass `--requested-route png` only when the user explicitly asked
for native PNG, a smaller import, or a faster import. The Widget does not import
automatically and has no separate import control. The user requests import in
the normal conversation; the Widget still never reads EasyEDA or renders PDF
directly.

Before either route starts, resolve one explicit appearance choice. If the user
did not already specify it, ask exactly one short question:
`请选择原理图导入模式：默认配色，还是黑白配色？` The modes are closed and stable:

- `默认配色` -> `visual-mode=default` -> official EasyEDA `theme=Default`;
- `黑白配色` -> `visual-mode=black-white` -> official EasyEDA
  `theme=Black on White`.

Do not infer a default, show `White on Black`, or apply a JLC Hardware Learning-side color
filter. Pass the chosen official `--theme` to `schematic-export`, and pass the
matching `--visual-mode` to the native or PDF import-manifest command. The
manifest must reject a theme mismatch and record `visualMode` plus
`easyedaExportTheme` on the manifest, visual record, asset metadata, and shape
metadata. Appearance does not select the transport route: `默认配色` still uses
the PDF route unless the user separately requested the native-PNG override.

For an explicit native-PNG override:

1. Read and persist the current `projectUuid`, `documentUuid`, and `documentType=1`.
2. Run official `schematic-export --format PNG --scope current-schematic
   --theme <Default-or-Black-on-White>` with that expected identity. Do not
   retry automatically.
3. Read the live EasyEDA identity again and require an exact match.
4. If an older gateway sealed the official result as a signature failure and the
   artifact is an official PNG-only ZIP, run `schematic-native-png-normalize`
   against that exact failure envelope and both identity records. This is a
   local-only recovery with zero EasyEDA API calls, not an export retry.
5. Run `workbench.py learning-native-visual-import-manifest --visual-mode
   <default-or-black-white>` with both identity records and the direct native
   export or local normalization execution record.
6. For a direct PNG, call only the manifest's exact `tool` and `toolArgs`. For
   a multi-page native bundle, call each item in `operations[]` exactly once and
   in order. Require
   `mcp__jlc_hardware_learning_mcp__insert_hardware_learning_image`,
   `replaceAiImageHolder=false`, `evidenceSource=official-easyeda-export`, and
   the manifest-provided `displayWidth=1536`. Leave `displayHeight` unset so
   JLC Hardware Learning preserves the native aspect ratio; native bundle entries use a
   120-unit layout margin.
7. Verify every inserted JLC Hardware Learning asset's page ID, native PNG SHA-256, visual
   source, bundle index, and captured EasyEDA document UUID.

For the default high-resolution PDF-derived import:

1. Read and persist the current `projectUuid`, `documentUuid`, and
   `documentType=1`.
2. Run official `schematic-export --format PDF --scope current-schematic
   --theme <Default-or-Black-on-White>` once.
   Never use the blocked `current-page` PDF route and never retry automatically.
3. Re-read live identity and require an exact match.
4. Run local-only `schematic-native-pdf-render` with that exact official export
   execution, both identity records, and default `--max-long-edge 6144`. It
   must report `easyedaApiCallCount=0`, use Poppler, reject encrypted or
   unbounded input, and seal the source PDF, renderer and every PNG digest.
5. Run `workbench.py learning-pdf-visual-import-manifest --visual-mode
   <default-or-black-white>` with the render execution and the same identities.
6. Execute each returned `operations[]` item exactly once and in order. Require
   `mcp__jlc_hardware_learning_mcp__insert_hardware_learning_image`,
   `replaceAiImageHolder=false`,
   `evidenceSource=official-easyeda-pdf-render`, `displayWidth=1536`, no
   `displayHeight`, and the 120-unit multi-page layout margin.
7. Verify each inserted asset's page ID, source PDF digest, PDF page index,
   rendered PNG digest, render settings, renderer identity, visual source, and
   captured EasyEDA document UUID.

The official artifact is `current-schematic` scope and must not be relabeled as
an exact current-page visual. For an official multi-page PNG bundle, preserve
the official entry name and order, but do not infer a page UUID for an individual
entry. Official native PDF remains allowed for review/archive; JLC Hardware Learning receives
only the bounded PNG derivative, never the PDF file itself. EPRO source
and project archives remain available to non-image archive consumers;
`schematic-source-render`, `schematic-project-source-render`,
`learning-page-import-manifest`, and `learning-project-import-manifest` reject
with `DISABLED_BY_POLICY`.

If native export, identity recheck, manifest validation, or JLC Hardware Learning insertion
fails, leave the existing canvas unchanged and report the blocking evidence.
Do not switch pages implicitly, use a blocked current-page visual export, render
EPRO, or invent an image.

## JLC Hardware Learning plugin

The active canvas is the independently maintained `jlc-hardware-learning` plugin.
Its release package is built from the dedicated JLC source tree and validated as a
dependency-free MCP bundle. Historical third-party snapshots and patch sequences are
provenance only; they are not the active runtime identity or maintenance boundary.
The plugin keeps local question storage, selection capture and idempotent annotation
recovery. It has no separate question/import panel, retains the last non-empty
selection across focus changes, and exposes conversation-backed question storage
to the model. Its dedicated SVG frontend provides the four-zone layout and safe
drawing interactions, including style controls, ordinary
geometry, eraser, marquee selection, duplicate, zoom menu and minimap. Source
schematic images remain protected, and only an explicit learning frame is a
question region. Its numbered badge is part of the persistent shape and exported
PNG/SVG, not a transient DOM label. The Widget has no direct EasyEDA access.
Existing text and sticky notes are resumed by double-clicking: the inline editor
keeps the prior content, places the caret at its end, confirms on Enter, inserts
a newline on Shift+Enter, and ignores Enter as confirmation during IME
composition. A successful save returns the canvas to select.
An existing text or sticky-note object may be reopened by double-clicking it,
selecting it and pressing Enter, or clicking it once while the matching tool is
active. All routes preserve the prior value and move the caret to its end;
saving must not create another object or leave the creation tool active.
For a selected text or sticky-note shape, the right-side `小 / 中 / 大 / 特大`
control changes the persisted font size, not just stroke width. Canvas display,
inline editing, wrapping and PNG/SVG export must share the same size mapping.

`insert_hardware_learning_annotations` first stores a validated pending operation.
The Widget applies missing commands, tags each created shape with operation and
command IDs, then acknowledges the operation. A crash before acknowledgement is
safe because reopening finds those tags and does not duplicate shapes.

## Learning-note package and Feishu handoff

Build the local handoff with `workbench.py learning-note-package`. It joins the
saved JLC Hardware Learning page, official native EasyEDA images, numbered learning frames,
ordinary annotations, ordered questions, tutor evidence, and exact recorded
assistant responses. Explicit frame numbers remain authoritative; a dialogue
reference to a deleted or missing frame blocks the package instead of silently
moving the turn to another module.

The package contains a `PLAN_ONLY_NO_CLOUD_WRITE` Feishu document/whiteboard
scene. It is a typed handoff, not write authorization. Keep the first sync
direction `JLC Hardware Learning -> Feishu`; bind a future document token and board token in a
separate adapter-owned binding record. A synchronized board is tool-owned and
may be regenerated only with explicit overwrite confirmation, while user-owned
free notes must never be overwritten.

The package emits one shared `larkPlan.whiteboard.learningFrameMarkerStyle` for
both `synchronized-learning-board` and `module-index-board`; the adapter must not
update only one of them. It also emits `larkPlan.whiteboard.moduleIndexBoard` for
the native board placed directly under the document's `模块索引` heading. The
default `learning.module-index-board.v1` profile renders learning-frame borders,
number badges, and number text at 70% color opacity, reduces frame and badge
border width to 50%, and preserves every frame's position and bounds. Every
number badge uses the live-approved frame 7 geometry: a `round_rect` of
approximately `29.2544 x 28.41494` whiteboard units, font size `12`, anchored to
the frame's top-left at offsets `-23.912109375 / -22.4390869140625`. Its color
follows the associated learning frame. Legacy black ellipse badge bases must be
omitted or rendered fully transparent. The Feishu adapter must persist the
resolved profile for both board tokens, then verify each through raw node
readback and a cloud preview. An explicit user request may override the style
for that publish only.

## BOM separation

A learning answer is not a BOM decision or write authorization. Final BOM work
continues through `bom_selection`, then the `jlc-bom-sync` sequence:

`freeze -> plan -> unsaved acceptance -> fresh plan -> explicit apply --save`.
