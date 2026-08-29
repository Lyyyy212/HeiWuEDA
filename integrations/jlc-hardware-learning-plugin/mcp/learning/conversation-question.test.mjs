import assert from "node:assert/strict";
import test from "node:test";

import {
  buildConversationLearningQuestion,
  buildQuickLearningContext,
  parseLearningFrameReferences,
} from "./conversation-question.mjs";

function fixtureSnapshot() {
  return {
    schema: { schemaVersion: 2 },
    store: {
      "page:page": { id: "page:page", typeName: "page", name: "Page 1", index: "a1", meta: {} },
      "asset:image": {
        id: "asset:image",
        typeName: "asset",
        type: "image",
        props: { src: "/page-assets/page-page/source.png", w: 600, h: 400 },
      },
      "shape:image": {
        id: "shape:image",
        typeName: "shape",
        type: "image",
        parentId: "page:page",
        x: 0,
        y: 0,
        rotation: 0,
        props: { assetId: "asset:image", w: 600, h: 400 },
        meta: {},
      },
      "shape:frame-one": {
        id: "shape:frame-one",
        typeName: "shape",
        type: "geo",
        parentId: "page:page",
        x: 40,
        y: 50,
        rotation: 0,
        props: { geo: "rectangle", w: 180, h: 120 },
        meta: {
          hardwareLearningFrame: true,
          hardwareLearningFrameNumber: 1,
          hardwareLearningKind: "frame",
          hardwareLearningBounds: { x: 0, y: 0, w: 180, h: 120 },
        },
      },
      "shape:frame-two": {
        id: "shape:frame-two",
        typeName: "shape",
        type: "geo",
        parentId: "page:page",
        x: 250,
        y: 80,
        rotation: 0,
        props: { geo: "rectangle", w: 200, h: 140 },
        meta: {
          hardwareLearningFrame: true,
          hardwareLearningFrameNumber: 2,
          hardwareLearningKind: "frame",
          hardwareLearningBounds: { x: 0, y: 0, w: 200, h: 140 },
        },
      },
    },
  };
}

const selectionState = {
  version: 2,
  selectionRevision: 9,
  currentPageId: "page:page",
  selectedShapes: [{ id: "shape:frame-two" }],
  updatedAt: "2026-08-25T00:00:00.000Z",
};

test("learning frame references cover module labels and joined bare numbers", () => {
  assert.deepEqual(parseLearningFrameReferences("模块1是什么？"), [1]);
  assert.deepEqual(parseLearningFrameReferences("1和2一起有什么作用？"), [1, 2]);
  assert.deepEqual(parseLearningFrameReferences("学习框2、1的信号怎样连接？"), [1, 2]);
  assert.deepEqual(parseLearningFrameReferences("3.3V和5V电源有什么区别？"), []);
});

test("explicit frame numbers override the current selection and persist stable references", () => {
  const built = buildConversationLearningQuestion({
    canvasSnapshot: fixtureSnapshot(),
    selectionState,
    userQuestion: "1和2一起有什么作用？",
    questionId: "question:numbered-frames",
    requestedAt: "2026-08-25T00:00:01.000Z",
  });
  assert.equal(built.selectionSource, "frame-number-reference");
  assert.equal(built.question.selection.version, 1);
  assert.equal(built.question.selection.canvasSelectionVersion, 2);
  assert.deepEqual(built.question.selection.selectedShapeIds, ["shape:frame-one", "shape:frame-two"]);
  assert.deepEqual(built.question.selection.selectedFrameNumbers, [1, 2]);
  assert.deepEqual(built.question.selection.referencedFrameNumbers, [1, 2]);
  assert.deepEqual(
    built.question.selection.shapes
      .filter((shape) => shape.role === "selection-frame")
      .map((shape) => shape.learningFrameNumber),
    [1, 2],
  );
  assert.ok(built.question.selection.shapes.some((shape) => shape.role === "source-image"));
  assert.equal(built.question.responseMode, "quick");
  assert.equal(built.question.annotationRequested, false);
});

test("response mode and explicit annotation intent are recorded without creating annotations", () => {
  const built = buildConversationLearningQuestion({
    canvasSnapshot: fixtureSnapshot(),
    selectionState,
    userQuestion: "请深入解释并把结果标在画板上",
    responseMode: "deep",
    annotationRequested: true,
    pageEvidence: { netlist: { status: "verified", summary: { componentCount: 2 } } },
  });
  assert.equal(built.question.responseMode, "deep");
  assert.equal(built.question.annotationRequested, true);
  assert.equal(built.question.pageEvidence.netlist.status, "verified");
});

test("quick context is bounded and contains references instead of image bytes or the canvas store", () => {
  const built = buildConversationLearningQuestion({
    canvasSnapshot: fixtureSnapshot(),
    selectionState,
    userQuestion: "模块2是什么？",
    questionId: "question:quick-context",
    pageEvidence: { netlist: { status: "verified", summary: { componentCount: 2, netCount: 3 } } },
  });
  const context = buildQuickLearningContext(built.question);
  const serialized = JSON.stringify(context);
  assert.equal(context.schemaVersion, "jlc.hardware-learning-quick-context.v1");
  assert.deepEqual(context.selection.referencedFrameNumbers, [2]);
  assert.ok(context.selection.shapes.some((shape) => shape.assetUrl === "/page-assets/page-page/source.png"));
  assert.match(context.contextSha256, /^[a-f0-9]{64}$/);
  assert.ok(serialized.length < 8192, `quick context is ${serialized.length} characters`);
  assert.doesNotMatch(serialized, /dataBase64|\"store\"|schemaVersion\":2/);
});

test("missing numbered frames fail without falling back to another selection", () => {
  assert.throws(
    () => buildConversationLearningQuestion({
      canvasSnapshot: fixtureSnapshot(),
      selectionState,
      userQuestion: "模块3是什么？",
    }),
    /not found.*3/i,
  );
});
