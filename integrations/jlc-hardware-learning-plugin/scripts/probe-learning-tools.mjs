import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  acknowledgeLearningAnnotations,
  insertLearningAnnotations,
  pullLearningAnnotations,
  saveLearningQuestion,
} from "../mcp/learning/storage.mjs";
import {
  readHardwareLearningSelectionState,
  writeHardwareLearningSelectionState,
} from "../mcp/lib/canvas-storage.mjs";
import {
  buildConversationLearningQuestion,
  buildQuickLearningContext,
} from "../mcp/learning/conversation-question.mjs";

const projectDir = await mkdtemp(join(tmpdir(), "jlc-hardware-learning-probe-"));
try {
  const question = {
    schemaVersion: "learning.question.v1",
    questionId: "question:probe",
    selection: { selectedShapeIds: ["shape:source"] },
  };
  const screenshotDataUrl = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
  const saved = await saveLearningQuestion({ projectDir, question, screenshotDataUrl });
  assert.equal(saved.replayed, false);
  assert.equal((await saveLearningQuestion({ projectDir, question, screenshotDataUrl })).replayed, true);

  const selectedFrame = {
    version: 2,
    selectionRevision: 7,
    currentPageId: "page:page",
    selectedShapes: [{ id: "shape:frame", type: "geo" }],
    updatedAt: "2026-08-24T00:00:00.000Z",
  };
  await writeHardwareLearningSelectionState({ projectDir }, selectedFrame);
  await writeHardwareLearningSelectionState({ projectDir }, {
    version: 1,
    currentPageId: "page:page",
    selectedShapes: [],
    updatedAt: "2026-08-24T00:00:01.000Z",
  });
  const persistedSelection = (await readHardwareLearningSelectionState({ projectDir })).selection;
  assert.equal(persistedSelection.selectedShapes.length, 0);
  assert.equal(persistedSelection.lastNonEmptySelection.selectedShapes[0].id, "shape:frame");

  const canvasSnapshot = {
    schema: { schemaVersion: 2 },
    store: {
      "page:page": { id: "page:page", typeName: "page", name: "Page 1", index: "a1" },
      "asset:image": {
        id: "asset:image",
        typeName: "asset",
        type: "image",
        props: { src: "/page-assets/page-page/source.png", w: 300, h: 200 },
      },
      "shape:image": {
        id: "shape:image",
        typeName: "shape",
        type: "image",
        parentId: "page:page",
        x: 0,
        y: 0,
        rotation: 0,
        props: { assetId: "asset:image", w: 300, h: 200 },
        meta: {},
      },
      "shape:frame": {
        id: "shape:frame",
        typeName: "shape",
        type: "geo",
        parentId: "page:page",
        x: 50,
        y: 40,
        rotation: 0,
        props: { geo: "rectangle", w: 100, h: 80 },
        meta: {
          hardwareLearningFrame: true,
          hardwareLearningFrameNumber: 1,
          hardwareLearningKind: "frame",
          hardwareLearningAnnotation: true,
          hardwareLearningBounds: { x: 0, y: 0, w: 100, h: 80 },
        },
      },
      "shape:frame-two": {
        id: "shape:frame-two",
        typeName: "shape",
        type: "geo",
        parentId: "page:page",
        x: 170,
        y: 60,
        rotation: 0,
        props: { geo: "rectangle", w: 90, h: 70 },
        meta: {
          hardwareLearningFrame: true,
          hardwareLearningFrameNumber: 2,
          hardwareLearningKind: "frame",
          hardwareLearningAnnotation: true,
          hardwareLearningBounds: { x: 0, y: 0, w: 90, h: 70 },
        },
      },
    },
  };
  const conversational = buildConversationLearningQuestion({
    canvasSnapshot,
    selectionState: persistedSelection,
    userQuestion: "这个框里的电路是做什么的？",
    questionId: "question:conversation-probe",
    requestedAt: "2026-08-24T00:00:02.000Z",
  });
  assert.equal(conversational.selectionSource, "last-non-empty");
  assert.equal(conversational.question.selection.canvasPageId, "page:page");
  assert.deepEqual(conversational.question.selection.selectedShapeIds, ["shape:frame"]);
  assert.equal(conversational.question.selection.shapes[0].role, "selection-frame");
  assert.equal(conversational.question.selection.selectionRevision, 7);
  assert.equal(conversational.question.selection.version, 1);
  assert.equal(conversational.question.selection.canvasSelectionVersion, 2);
  assert.deepEqual(conversational.question.selection.selectedFrameNumbers, [1]);
  assert.ok(conversational.question.selection.shapes.some((shape) => shape.role === "source-image"));
  const quickContext = buildQuickLearningContext(conversational.question);
  assert.equal(quickContext.schemaVersion, "jlc.hardware-learning-quick-context.v1");
  assert.deepEqual(quickContext.selection.selectedFrameNumbers, [1]);
  assert.doesNotMatch(JSON.stringify(quickContext), /dataBase64|hardware-learning-canvas\.json/);
  assert.ok(JSON.stringify(quickContext).length < 8192);
  assert.equal((await saveLearningQuestion({ projectDir, question: conversational.question })).replayed, false);

  const numbered = buildConversationLearningQuestion({
    canvasSnapshot,
    selectionState: persistedSelection,
    userQuestion: "1和2一起有什么作用？",
    questionId: "question:numbered-conversation-probe",
    requestedAt: "2026-08-24T00:00:03.000Z",
  });
  assert.equal(numbered.selectionSource, "frame-number-reference");
  assert.deepEqual(numbered.question.selection.selectedShapeIds, ["shape:frame", "shape:frame-two"]);
  assert.deepEqual(numbered.question.selection.referencedFrameNumbers, [1, 2]);

  const operationId = "operation:probe";
  const pageId = "page:probe";
  const commands = [{
    commandId: "annotation-command:probe",
    operationId,
    kind: "note",
    pageId,
    anchorShapeId: "shape:source",
    text: "evidence-backed note",
  }];
  const inserted = await insertLearningAnnotations({ projectDir, operationId, pageId, commands });
  assert.equal(inserted.replayed, false);
  assert.equal((await insertLearningAnnotations({ projectDir, operationId, pageId, commands })).replayed, true);
  const pending = await pullLearningAnnotations({ projectDir, pageId });
  assert.equal(pending.operations.length, 1);
  await acknowledgeLearningAnnotations({ projectDir, operationId, commandsSha256: inserted.operation.commandsSha256 });
  assert.equal((await pullLearningAnnotations({ projectDir, pageId })).operations.length, 0);

  await assert.rejects(
    () => insertLearningAnnotations({
      projectDir,
      operationId: "operation:generated",
      pageId,
      commands: [{
        commandId: "annotation-command:generated",
        operationId: "operation:generated",
        pageId,
        kind: "image",
        imageUrl: "https://example.invalid/generated.png",
      }],
    }),
    /not whitelisted|forbidden/,
  );

  const conversationSource = await readFile(new URL("../mcp/learning/conversation-question.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(conversationSource, /imagegen|insert_hardware_learning_image|insert_hardware_learning_html_draft/);
  const annotationSource = await readFile(new URL("../src/learning-canvas/annotations.js", import.meta.url), "utf8");
  assert.match(annotationSource, /hardwareLearningOperationId/);
  assert.doesNotMatch(annotationSource, /type: ['"]image['"]|type: ['"]embed['"]/);

  const canvasSource = await readFile(new URL("../src/learning-canvas/HardwareLearningCanvas.jsx", import.meta.url), "utf8");
  assert.ok(
    canvasSource.indexOf("await saveQueueRef.current") <
      canvasSource.indexOf("await acknowledgeHardwareLearningAnnotations("),
    "learning annotations must persist the canvas before acknowledging the operation",
  );

  console.log("JLC Hardware Learning learning question and annotation tools probe passed.");
} finally {
  await rm(projectDir, { recursive: true, force: true });
}
