# JLC Hardware Learning learning notes in Feishu

## Goal and ownership

JLC Hardware Learning remains the interactive source of truth for schematic images, numbered
learning frames, text, and sticky notes. A Feishu Doc is the durable searchable
notebook. One native Feishu whiteboard block mirrors the tool-managed JLC Hardware Learning
scene, while the surrounding document owns module headings, ordered dialogue,
unknowns, and sync evidence.

The first release is one-way: `JLC Hardware Learning -> Feishu`. User-authored free notes are
outside the synchronized board and are never overwritten. Refreshing a non-empty
synchronized board still requires explicit overwrite confirmation.

## Dialogue and learning-frame linkage

The normal Codex conversation is the only question entry point. The linkage is
not inferred from visual proximity after the fact:

1. `save_hardware_learning_question` resolves the saved current page and numbered
   learning frames. Explicit references such as `模块5` or `4和5` override the
   incidental mouse selection.
2. `learning-answer-saved` seals the question, offline/live evidence envelope,
   tutor baseline, and page-bound session order.
3. `learning-dialogue-record` stores the exact assistant response shown in the
   conversation and binds it to the tutor-answer digest.
4. `learning-note-package` maps each turn to both stable frame numbers and JLC Hardware Learning
   frame shape IDs. A missing, duplicated, or cross-page frame blocks packaging.
5. The Feishu document renders every frame as a module heading and every linked
   turn below the corresponding module. The embedded whiteboard retains the same
   visible frame number.

Corrections are new conversation turns; immutable historical turns are never
rewritten. A question without an explicit frame may use the validated current or
retained last non-empty JLC Hardware Learning selection, but the system never guesses a frame
when neither exists.

## Module boundaries

```text
HardwareLearningNotebookReader
  -> LearningSessionStore
  -> LearningNotePackageBuilder
  -> FeishuSceneRenderer (future adapter)
  -> LarkDocAdapter + LarkWhiteboardAdapter (future adapter)
  -> SyncVerifier (future adapter)
```

- `HardwareLearningNotebookReader` performs local snapshot and official-image digest checks.
- `LearningSessionStore` owns immutable questions, evidence, tutor answers, exact
  conversation responses, and ordered page sessions.
- `LearningNotePackageBuilder` emits `learning.note-package.v1` and performs no
  network or cloud write.
- `FeishuSceneRenderer` must convert the normalized scene through
  `@larksuite/whiteboard-cli`; image-bearing boards use the DSL/image route and
  only the rendered result is submitted as `raw`.
- `LarkDocAdapter` creates or updates document structure with `--as user`.
- `LarkWhiteboardAdapter` reuses the stored board token, a stable 10+ character
  idempotency token, and never silently overwrites a non-empty board.
- `SyncVerifier` reads back the document/board, exports a preview, and records
  digests in `learning.lark-binding.v1`.

## Module-index board rendering profile

`larkPlan.whiteboard.moduleIndexBoard` is the stable handoff for the native
whiteboard inserted immediately after the document's `模块索引` heading. It
contains the source schematic page images and the numbered learning frames that
belong to that JLC Hardware Learning page, and it keeps native Feishu zoom and annotation
enabled.

The default profile is `learning.module-index-board.v1`:

- frame borders, number badges, and number text render at 70% color opacity;
- frame and badge border width renders at 50% of the original width;
- frame position and bounds are preserved exactly;
- every number badge follows its frame color and uses the approved frame 7
  geometry: `round_rect`, about `29.2544 x 28.41494` whiteboard units, font size
  `12`, anchored at the frame's top-left with offsets
  `-23.912109375 / -22.4390869140625`;
- the same resolved marker profile is mandatory for both the main synchronized
  learning board and the page-local module-index board; never update only one
  board token;
- legacy black ellipse badge bases are omitted or rendered fully transparent;
- an explicit user style request may override the defaults for that publish,
  but the resolved profile must be stored in the binding and verified by raw
  readback plus cloud preview.

## Local artifacts

```text
<project>/.easyeda-hardware-workbench/learning/
  questions/       JLC Hardware Learning conversation questions
  evidence/        immutable evidence bundles
  answers/         deterministic tutor baselines
  responses/       exact assistant conversation responses
  sessions/        ordered same-page histories
  notes/           local note packages and Markdown previews
  lark/            future bindings, rendered scenes, and verification records
```

`learning.note-package.v1` is validated by
`materials/contracts/learning-note-package.schema.json`. Cloud bindings use
`materials/contracts/lark-learning-note-binding.schema.json` and are created
only after the user authorizes a concrete Feishu target.

## Publish sequence

1. Build the note package and compare `contentSha256` with the last binding.
2. If unchanged, return `NOOP` without a Feishu call.
3. Create or identify the Feishu Doc and insert one blank native whiteboard block.
4. Persist its `docToken` and `boardToken` before rendering.
5. Render local images and shapes through the official whiteboard CLI, applying
   the resolved shared `whiteboard.learningFrameMarkerStyle` to both the main
   synchronized learning board and the module-index board without changing frame
   bounds.
6. Write the synchronized board with the same idempotency token on retries.
7. Update structured module/dialogue sections in the document.
8. Export and inspect a preview; read back tokens and store verification digests.

No step calls EasyEDA. Imported schematic images must already be official native
EasyEDA PNG evidence admitted by the learning workflow; EPRO-derived visuals stay
blocked.
