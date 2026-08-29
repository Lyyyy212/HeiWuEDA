---
name: jlc-hardware-learning
description: Open and use the persistent 黑五画板 for selection-scoped schematic questions, local evidence, teaching annotations, exports, and guarded Feishu learning-note synchronization. Use for hardware-learning frames and page-bound schematic study; do not use for image generation, AI HTML, Slides, or direct EasyEDA writes.
---

# JLC Hardware Learning

Use this plugin as the canvas adapter for the `easyeda-hardware-lifecycle` learning workflow. The canvas identifies what the user is asking about; Codex owns the conversation; the lifecycle layer owns hardware reasoning, official EasyEDA evidence, and page identity.

## Route only to the needed module

- To open or operate 黑五画板, edit text/notes, manage pages/canvases, or export PNG/SVG/JSON, read [references/canvas-operations.md](references/canvas-operations.md).
- To import an official EasyEDA schematic visual or explicitly navigate EasyEDA pages, read [references/schematic-import.md](references/schematic-import.md). Before any live EasyEDA call, also use the lifecycle API boundary it names.
- To answer a learning-frame or selection question, read [references/question-flow.md](references/question-flow.md). This is the default route for ordinary hardware-learning questions.
- To plan, migrate, or synchronize Feishu learning notes, read [references/feishu-sync.md](references/feishu-sync.md) and then the referenced versioned standard.

Do not load unrelated modules. In particular, ordinary questions must not load the import, canvas-interaction, or Feishu procedures.

## Shared contract

- The user-facing product name is `黑五画板`; keep the plugin ID, MCP namespace, Widget URI prefix, and project storage paths unchanged for compatibility.
- Use the active user workspace as `projectDir`, never the plugin directory. Reuse an open Widget instead of rendering another copy.
- Treat canvas, canvas-page, EasyEDA project, and EasyEDA document identity as separate. Never merge evidence across canvas pages or EasyEDA documents.
- A learning frame is the only numbered question region. Explicit references such as `模块1`, `学习框2`, or `1和2` override incidental selection and resolve only on the current saved canvas page.
- Default to `responseMode=quick`. Use `deep` only for an explicit deep request or evidence need.
- A normal question is read-only with respect to EasyEDA. It never authorizes page switching, export, save, device binding, BOM writeback, or any other EDA mutation.
- Never add a sticky note or other annotation automatically. Annotation requires explicit user intent and remains a separate page-bound operation.

## Hard boundaries

- Do not call image-generation, image-editing, AI HTML, or AI Slides workflows.
- Do not enable telemetry or analytics.
- Do not write to or save EasyEDA from a learning request.
- Do not use EPRO-derived SVG, PNG, or PDF as a learning-canvas image.
- A teaching answer is not a schematic-review gate, BOM decision, or fabrication approval.
