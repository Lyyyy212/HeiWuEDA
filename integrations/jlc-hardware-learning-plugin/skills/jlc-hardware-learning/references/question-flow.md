# Fast question flow

Use this module for questions about numbered learning frames or a current canvas selection. Keep the normal path local and compact.

## One-call capture

Call `mcp__jlc_hardware_learning_mcp__save_hardware_learning_question` directly with:

- `projectDir` and the active `canvasDir` when it is not the default canvas;
- the conversation text as `userQuestion`;
- an inferred `intent` and `learningLevel` (`intermediate` by default);
- `responseMode=quick` unless deep evidence is explicitly requested;
- `annotationRequested=true` only when the user explicitly asks to add a note, highlight, rectangle, or arrow.

Do not call the selection, canvas-state, or netlist-summary tools first. The save tool resolves explicit frame numbers, current selection, or a valid `lastNonEmptySelection`, reads the page netlist summary, persists the immutable question, and returns `quickContext` in one operation.

Explicit frame numbers override incidental selection. Missing or duplicate frame numbers are errors and must not fall back to another frame or page. The question record stores selected and referenced frame numbers, intersecting source-image references, page identity, evidence digests, response mode, and annotation intent.

`quickContext` is the model-facing context. It contains bounded shape summaries, relative asset references, the page-netlist summary, and digests. It must not contain a canvas store, image Base64, or a full netlist. Do not re-read information already present in it.

## Quick answer

Run:

```powershell
py scripts/workbench.py learning-answer-saved --project <projectDir> --question-id <question:uuid> --compact
```

Use the compact durable tutor result as the answer baseline. For a component-reference or connectivity question, call `read_hardware_learning_page_netlist` once with bounded `componentRefs` or `netNames`; never load the whole netlist merely because it exists. If visual inspection is required, prefer the saved selection screenshot. Otherwise read only the one intersecting source asset named by `quickContext`, not every image on the page.

Ordinary quick questions do not open live EasyEDA, browse the web, run distributor research, or load Feishu state. Separate evidence, inference, unknowns, and suggested checks in the response.

## Deep answer

Use `responseMode=deep` only when the user explicitly asks for deep analysis or the question genuinely needs current/high-stakes evidence, component selection, procurement facts, or a source that is not saved locally.

For live EasyEDA evidence, use the lifecycle `learning-live-plan` and the dedicated official gateway. Execute only a locked `READ` plan and bind identity before and after. Identity drift produces `stale`; missing evidence produces `partial`. Never send raw JavaScript or write EasyEDA. Browse datasheets or distributors only when the question requires them.

## Persistence and resume

Before ending the turn, persist the exact response shown to the user with:

```powershell
py scripts/workbench.py learning-dialogue-record --project <projectDir> --question-id <question:uuid> --response-file <utf8.md>
```

The response is immutable and bound to the same page, frame numbers, and tutor-answer digest. Do not reconstruct it from chat history later.

Call resume only after a restart or when the current task lacks the needed prior turn. Use the bounded form:

```powershell
py scripts/workbench.py learning-resume --project <projectDir> --session-id <learning:jlc-hardware-learning:page-id> --compact --tail 2
```

Do not load the entire session for an ordinary follow-up.

## Teaching annotations

Only after explicit annotation intent may `insert_hardware_learning_annotations` be used. Allowed kinds are `note`, `highlight`, `rectangle`, and `arrow`.

- Keep one stable `operationId` for retries.
- Every command repeats the exact `operationId` and `pageId` and has a stable `commandId`.
- Use page-coordinate bounds and concise teaching text.
- Never include image, imageUrl, assetUrl, HTML, embed, video, or Slides fields.
- Let the Widget pull, apply, and acknowledge operations idempotently; never rewrite the full canvas snapshot to simulate annotations.
