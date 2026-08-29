import assert from "node:assert/strict";
import test from "node:test";

import {
  bindFeishuLearningRoot,
  bindFeishuProjectNode,
  bindFeishuProjectOverviewBoard,
  buildFeishuLearningDirectoryPlan,
  createFeishuLearningRegistry,
  markFeishuProjectHomepageSynced,
  upsertFeishuFrameNote,
  upsertFeishuPageBinding,
} from "./note-model.mjs";
import { planFeishuLearningSync } from "./sync-plan.mjs";
import {
  executeConfirmedFeishuLearningNoteSync,
  previewFeishuLearningSyncFromState,
} from "./confirmed-sync.mjs";

const DOC_TOKEN = "docMainToken123456";

function documentContent() {
  return [
    `<title id="${DOC_TOKEN}">01 主控板</title>`,
    '<h1 id="info">工程与图页信息</h1>',
    '<h1 id="learning">原理图学习画板</h1>',
    '<whiteboard id="learning-board" token="FixtureWhiteboardToken01"></whiteboard>',
    '<h1 id="modules">模块索引</h1>',
    '<h1 id="qa">提问与解答</h1>',
    '<h1 id="relations">模块间关系</h1>',
    '<h1 id="todo">待验证项</h1>',
    '<h1 id="sync">同步记录</h1>',
  ].join("");
}

function createState({ schematicPageUuid = "FixtureSchematicPageUuid01" } = {}) {
  const project = { projectId: "project-1", projectName: "测试项目" };
  let registry = createFeishuLearningRegistry(project);
  registry = bindFeishuLearningRoot(registry, {
    projectId: project.projectId,
    spaceId: "FixtureSpaceId01",
    learningRootNodeToken: "FixtureNodeToken01",
    learningRootDocToken: "learningRootDoc123",
  });
  registry = bindFeishuProjectNode(registry, {
    projectId: project.projectId,
    spaceId: "FixtureSpaceId01",
    projectNodeToken: "FixtureNodeToken02",
    projectDocToken: "projectDocToken123",
  });
  registry = bindFeishuProjectOverviewBoard(registry, {
    projectId: project.projectId,
    projectOverviewWhiteboardToken: "FixtureProjectOverviewWhiteboardToken01",
  });
  registry = upsertFeishuPageBinding(registry, {
    projectId: project.projectId,
    canvasPageId: "page:main",
    schematicPageUuid,
    pageName: "主控板",
    nodeToken: "FixtureNodeToken03",
    docToken: DOC_TOKEN,
    documentLocation: "wiki",
    whiteboardToken: "FixtureWhiteboardToken01",
  });
  registry = upsertFeishuFrameNote(registry, {
    projectId: project.projectId,
    canvasPageId: "page:main",
    frameNumber: 4,
    title: "模块 4",
    status: "learning",
  });
  const directoryPlan = buildFeishuLearningDirectoryPlan({
    project,
    schematicPages: [{ canvasPageId: "page:main", schematicPageUuid, pageName: "主控板" }],
  });
  let syncPlan = planFeishuLearningSync({ directoryPlan, registry });
  const homepage = syncPlan.actions.find((action) => action.kind === "doc.project-homepage.ensure");
  registry = markFeishuProjectHomepageSynced(registry, {
    projectId: project.projectId,
    indexDigest: homepage.desiredContentDigest,
  });
  syncPlan = planFeishuLearningSync({ directoryPlan, registry });
  return { ok: true, registryExists: true, registry, directoryPlan, syncPlan };
}

function readAdapterFor(document) {
  return {
    async fetchDocumentOutline() {
      return { ok: true, identity: "user", data: { document: { ...document } } };
    },
    async fetchDocumentFull() {
      return { ok: true, identity: "user", data: { document: { ...document } } };
    },
  };
}

function assignBlockIds(content, counter) {
  return content.replace(/<(p|h2)(?=>)/gu, (_match, tag) => `<${tag} id="managed-${++counter.value}"`);
}

test("continuous sync preview exposes exact managed patches and blocks missing schematic identity", async () => {
  const document = { document_id: DOC_TOKEN, revision_id: 7, content: documentContent() };
  const preview = await previewFeishuLearningSyncFromState(
    { projectDir: "D:/unused" },
    createState({ schematicPageUuid: null }),
    { readAdapter: readAdapterFor(document) },
  );
  assert.equal(preview.executable, false);
  assert.ok(preview.blockers.some((entry) => entry.code === "SCHEMATIC_PAGE_IDENTITY_MISSING"));
  assert.equal(preview.expectedDocumentRevisions[DOC_TOKEN], 7);
  assert.equal(preview.pagePatches["page:main"].operations.length, 2);
  assert.match(preview.syncPlan.planFingerprint, /^[a-f0-9]{64}$/u);
  assert.equal(preview.remoteWritesPerformed, false);
});

test("confirmed continuous sync updates only managed ranges, verifies, and saves once", async () => {
  const document = { document_id: DOC_TOKEN, revision_id: 7, content: documentContent() };
  const readAdapter = readAdapterFor(document);
  const preview = await previewFeishuLearningSyncFromState(
    { projectDir: "D:/unused" },
    createState(),
    { readAdapter },
  );
  assert.equal(preview.executable, true);
  const counter = { value: 0 };
  let remoteWriteCount = 0;
  const writeAdapter = {
    async insertDocumentBlocksAfter({ content }) {
      remoteWriteCount += 1;
      document.content += assignBlockIds(content, counter);
      document.revision_id += 1;
      return { payload: { ok: true, identity: "user", data: { result: "success" } } };
    },
    async replaceDocumentBlocks() {
      throw new Error("first adoption must not replace unrelated blocks");
    },
  };
  let saveCount = 0;
  const result = await executeConfirmedFeishuLearningNoteSync({
    projectDir: "D:/unused",
    confirmed: true,
    planFingerprint: preview.syncPlan.planFingerprint,
    expectedDocumentRevisions: preview.expectedDocumentRevisions,
  }, preview, {
    readAdapter,
    writeAdapter,
    saveRegistry: async (_input, registry) => {
      saveCount += 1;
      return { path: "D:/registry.json", registry };
    },
  });
  assert.equal(remoteWriteCount, 2);
  assert.equal(saveCount, 1);
  assert.equal(result.remoteWritesPerformed, true);
  assert.equal(result.registry.pages["page:main"].managedContentVersion, 1);
  assert.equal(result.registry.pages["page:main"].docRevision, "9");
  assert.match(document.content, /JLC 自动同步区：模块索引（开始）/u);
  assert.match(document.content, /JLC 自动同步区：提问与解答（开始）/u);
  assert.equal((document.content.match(/whiteboard/gu) ?? []).length, 2);
});

test("continuous sync rejects a stale revision map before any write", async () => {
  const document = { document_id: DOC_TOKEN, revision_id: 7, content: documentContent() };
  const readAdapter = readAdapterFor(document);
  const preview = await previewFeishuLearningSyncFromState(
    { projectDir: "D:/unused" },
    createState(),
    { readAdapter },
  );
  await assert.rejects(
    () => executeConfirmedFeishuLearningNoteSync({
      confirmed: true,
      planFingerprint: preview.syncPlan.planFingerprint,
      expectedDocumentRevisions: { [DOC_TOKEN]: 6 },
    }, preview, { readAdapter, writeAdapter: {} }),
    /revision map/u,
  );
});
