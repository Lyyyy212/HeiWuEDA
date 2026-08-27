import assert from "node:assert/strict";
import test from "node:test";

import {
  createFeishuLearningRegistry,
  linkFeishuDialogue,
  upsertFeishuFrameNote,
  upsertFeishuPageBinding,
} from "./note-model.mjs";
import {
  inspectFeishuManagedPageContent,
  planFeishuManagedPagePatch,
  renderFeishuManagedPageContent,
} from "./page-content.mjs";

const PAGE = "page:main";
const QUESTION = "question:00000000-0000-4000-8000-000000000001";

function registryWithDialogue() {
  const project = { projectId: "project-1", projectName: "学习项目" };
  let registry = createFeishuLearningRegistry(project);
  registry = upsertFeishuPageBinding(registry, {
    projectId: project.projectId,
    canvasPageId: PAGE,
    schematicPageUuid: "FixtureSchematicPageUuid01",
    pageName: "主控板",
    nodeToken: "FixtureNodeToken01",
    docToken: "doc-main",
    whiteboardToken: "FixtureWhiteboardToken01",
    moduleIndexWhiteboardToken: "FixtureModuleIndexWhiteboardToken01",
  });
  registry = upsertFeishuFrameNote(registry, {
    projectId: project.projectId,
    canvasPageId: PAGE,
    frameNumber: 4,
    title: "模块 4",
    status: "learning",
  });
  registry = linkFeishuDialogue(registry, {
    projectId: project.projectId,
    canvasPageId: PAGE,
    questionId: QUESTION,
    frameNumbers: [4],
    questionDigest: "1".repeat(64),
    answerDigest: "2".repeat(64),
    linkedAt: "2026-08-27T00:00:00Z",
  });
  return registry;
}

function baseDocument(extra = "") {
  return [
    '<title id="doc-main">01 主控板</title>',
    '<h1 id="info">工程与图页信息</h1>',
    '<h1 id="learning">原理图学习画板</h1>',
    '<whiteboard id="FixtureWhiteboardToken01-block" token="FixtureWhiteboardToken01"></whiteboard>',
    '<h1 id="modules">模块索引</h1>',
    '<whiteboard id="FixtureModuleIndexWhiteboardToken01-block" token="FixtureModuleIndexWhiteboardToken01"></whiteboard>',
    extra,
    '<h1 id="qa">提问与解答</h1>',
    '<h1 id="relations">模块间关系</h1>',
    '<h1 id="todo">待验证项</h1>',
    '<h1 id="sync">同步记录</h1>',
  ].join("");
}

function withMarkerIds(xml, prefix) {
  let index = 0;
  return xml.replace(/<p><span text-color="gray">JLC 自动同步区：/gu, () => (
    `<p id="${prefix}-${++index}"><span text-color="gray">JLC 自动同步区：`
  ));
}

test("managed page rendering binds exact durable dialogue content to page-local frames", () => {
  const rendered = renderFeishuManagedPageContent({
    registry: registryWithDialogue(),
    canvasPageId: PAGE,
    dialogueRecords: [{
      questionId: QUESTION,
      questionDigest: "1".repeat(64),
      answerDigest: "2".repeat(64),
      frameNumbers: [4],
      questionText: "学习框 4 是什么电路？",
      answer: {
        summary: "这是受证据约束的模块说明。",
        explanation: "回答正文。",
        unknowns: ["仍需核对器件参数。"],
      },
    }],
  });
  assert.match(rendered.contentDigest, /^[a-f0-9]{64}$/u);
  assert.match(rendered.moduleIndexXml, /<table>/u);
  assert.match(rendered.moduleIndexXml, /模块 4/u);
  assert.match(rendered.dialoguesXml, /学习框 4 是什么电路/u);
  assert.match(rendered.dialoguesXml, new RegExp(QUESTION, "u"));
});
test("first synchronization inserts after the two stable section anchors without replacing boards", () => {
  const rendered = renderFeishuManagedPageContent({
    registry: registryWithDialogue(),
    canvasPageId: PAGE,
    dialogueRecords: [{
      questionId: QUESTION,
      questionDigest: "1".repeat(64),
      answerDigest: "2".repeat(64),
      frameNumbers: [4],
      questionText: "问题",
      answer: { summary: "回答" },
    }],
  });
  const patch = planFeishuManagedPagePatch({ content: baseDocument(), rendered });
  assert.deepEqual(patch.operations.map((operation) => operation.kind), [
    "block_insert_after",
    "block_insert_after",
  ]);
  assert.equal(patch.operations[0].blockId, "FixtureModuleIndexWhiteboardToken01-block");
  assert.equal(patch.operations[1].blockId, "qa");
  assert.doesNotMatch(patch.operations[0].content, /whiteboard/u);
});

test("later synchronization replaces only the two managed ranges", () => {
  const registry = registryWithDialogue();
  const first = renderFeishuManagedPageContent({
    registry,
    canvasPageId: PAGE,
    dialogueRecords: [{
      questionId: QUESTION,
      questionDigest: "1".repeat(64),
      answerDigest: "2".repeat(64),
      frameNumbers: [4],
      questionText: "问题",
      answer: { summary: "回答" },
    }],
  });
  const existing = baseDocument([
    withMarkerIds(first.moduleIndexXml, "module-marker"),
    withMarkerIds(first.dialoguesXml, "dialogue-marker"),
  ].join(""));
  const managed = inspectFeishuManagedPageContent(existing);
  assert.equal(managed.moduleIndex.contentDigest, first.contentDigest);
  assert.equal(managed.dialogues.contentDigest, first.contentDigest);
  const changed = renderFeishuManagedPageContent({
    registry,
    canvasPageId: PAGE,
    dialogueRecords: [{
      questionId: QUESTION,
      questionDigest: "1".repeat(64),
      answerDigest: "2".repeat(64),
      frameNumbers: [4],
      questionText: "问题",
      answer: { summary: "更新后的回答" },
    }],
  });
  const patch = planFeishuManagedPagePatch({ content: existing, rendered: changed });
  assert.deepEqual(patch.operations.map((operation) => operation.kind), [
    "block_replace",
    "block_replace",
  ]);
  assert.ok(patch.operations.every((operation) => operation.startBlockId));
  assert.ok(patch.operations.every((operation) => operation.endBlockId));
});
