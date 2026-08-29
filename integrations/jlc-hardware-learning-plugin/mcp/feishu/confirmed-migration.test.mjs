import assert from "node:assert/strict";
import test from "node:test";

import {
  buildFeishuLearningDirectoryPlan,
  createFeishuLearningRegistry,
  upsertFeishuFrameNote,
  upsertFeishuPageBinding,
} from "./note-model.mjs";
import { planFeishuLearningSync } from "./sync-plan.mjs";
import {
  executeConfirmedFeishuLearningNoteMigration,
  renderFeishuPageIdentitySummary,
} from "./confirmed-migration.mjs";

const DOC_TOKEN = "CwGJdseLUoB3GlxIVEdc4zgZnBh";
const MAIN_BOARD = "PhfGw0fY2htpI8bOVXqcAoB7nvc";
const INDEX_BOARD = "E6uZwU99Qh3Xcqb4j8Mcs1xznOb";
const PROJECT_OVERVIEW_BOARD = "FixtureProjectOverviewWhiteboardToken01";

test("reader-facing page identity summary hides internal binding identifiers", () => {
  const summary = renderFeishuPageIdentitySummary({
    project: {
      projectName: "测试项目",
      projectUuid: "internal-project-uuid",
    },
    page: {
      pageName: "主控板",
      canvasPageId: "page:internal",
      schematicPageUuid: "fixture-schematic-page-uuid",
    },
  });
  assert.equal(summary, "项目：测试项目；图页：主控板");
  assert.doesNotMatch(summary, /internal|UUID|page:/u);
});

function documentContent() {
  return [
    `<title id="${DOC_TOKEN}">01 主控板</title>`,
    '<h1 id="project">工程与图页信息</h1>',
    '<h1 id="learning">原理图学习画板</h1>',
    `<whiteboard id="learning-board" token="${MAIN_BOARD}"></whiteboard>`,
    '<h1 id="modules">模块索引</h1>',
    `<whiteboard id="index-board" token="${INDEX_BOARD}"></whiteboard>`,
    '<h2 id="frame-4">模块 4</h2>',
    '<h2 id="frame-5">模块 5</h2>',
    '<h2 id="frame-7">模块 7</h2>',
    '<h1 id="qa">提问与解答</h1>',
    '<h1 id="relations">模块间关系</h1>',
    '<h1 id="todo">待验证项</h1>',
    '<h1 id="sync">同步记录</h1>',
  ].join("");
}

function migrationPreview() {
  const project = {
    projectId: "00000000000000000000000000000001",
    projectUuid: "00000000000000000000000000000001",
    projectName: "【已测试】MPPT96V35A自动升降控制器",
  };
  let registry = createFeishuLearningRegistry(project, {
    projectOverviewWhiteboardToken: PROJECT_OVERVIEW_BOARD,
    updatedAt: "2026-08-26T00:00:00Z",
  });
  registry = upsertFeishuPageBinding(registry, {
    projectId: project.projectId,
    canvasPageId: "page:page",
    pageName: "主控板",
    sourceRevision: "source-revision",
    documentLocation: "drive",
    docToken: DOC_TOKEN,
    docUrl: `https://example.feishu.cn/docx/${DOC_TOKEN}`,
    docRevision: "9",
    whiteboardToken: MAIN_BOARD,
    legacyModuleIndexWhiteboardToken: INDEX_BOARD,
    updatedAt: "2026-08-26T00:00:00Z",
  });
  for (const frameNumber of [4, 5, 7]) {
    registry = upsertFeishuFrameNote(registry, {
      projectId: project.projectId,
      canvasPageId: "page:page",
      frameNumber,
      title: `模块 ${frameNumber}`,
      status: "unstarted",
      updatedAt: "2026-08-26T00:00:00Z",
    });
  }
  const directoryPlan = buildFeishuLearningDirectoryPlan({
    project,
    schematicPages: [{ canvasPageId: "page:page", pageName: "主控板" }],
  });
  const syncPlan = planFeishuLearningSync({ directoryPlan, registry });
  return {
    project: registry.project,
    registry,
    directoryPlan,
    syncPlan,
    reused: {
      document: { docToken: DOC_TOKEN, revisionId: 9 },
      learningBoard: { role: "learning-board", token: MAIN_BOARD },
      moduleIndexBoard: { role: "module-index-board", token: INDEX_BOARD },
    },
  };
}

test("confirmed migration creates the hierarchy, embeds the project overview, and preserves legacy boards", async () => {
  const preview = migrationPreview();
  const nodes = new Map();
  const children = new Map([["", []]]);
  const addNode = (node) => {
    nodes.set(node.node_token, node);
    const key = node.parent_node_token || "";
    const list = children.get(key) ?? [];
    list.push(node);
    children.set(key, list);
    if (!children.has(node.node_token)) children.set(node.node_token, []);
  };
  const pageDocument = {
    document_id: DOC_TOKEN,
    revision_id: 9,
    content: documentContent(),
  };
  const documents = new Map([[DOC_TOKEN, pageDocument]]);
  const resolveDocument = (reference) => {
    const token = [...documents.keys()].find((candidate) => String(reference).includes(candidate));
    if (!token) throw new Error(`unknown document: ${reference}`);
    return documents.get(token);
  };
  const readAdapter = {
    async getPersonalWikiSpace() {
      return { ok: true, identity: "user", data: { space: { space_id: "7641963944449494211" } } };
    },
    async listWikiNodes({ parentNodeToken }) {
      return {
        ok: true,
        identity: "user",
        data: { nodes: [...(children.get(parentNodeToken || "") ?? [])] },
      };
    },
    async getWikiNode({ nodeToken }) {
      if (!nodes.has(nodeToken)) throw new Error("not in wiki (131005)");
      return { ok: true, identity: "user", data: nodes.get(nodeToken) };
    },
    async fetchDocumentFull(documentRef) {
      return { ok: true, identity: "user", data: { document: { ...resolveDocument(documentRef) } } };
    },
    async fetchDocumentOutline(documentRef) {
      return { ok: true, identity: "user", data: { document: { ...resolveDocument(documentRef) } } };
    },
  };
  const actionById = new Map(preview.syncPlan.actions.map((action) => [action.actionId, action]));
  let sequence = 0;
  const writeAdapter = {
    async createWikiNode({ actionId, parentNodeToken }) {
      const action = actionById.get(actionId);
      const node = {
        space_id: "7641963944449494211",
        node_token: `wiki-node-${++sequence}`,
        obj_token: `doc-node-${sequence}`,
        obj_type: "docx",
        parent_node_token: parentNodeToken ?? "",
        title: action.title,
      };
      addNode(node);
      documents.set(node.obj_token, {
        document_id: node.obj_token,
        revision_id: 1,
        content: `<title id="${node.obj_token}">${action.title}</title>`,
      });
      return { payload: { ok: true, identity: "user", data: node } };
    },
    async moveDriveDocumentToWiki({ targetParentNodeToken }) {
      const node = {
        space_id: "7641963944449494211",
        node_token: "wiki-page",
        obj_token: DOC_TOKEN,
        obj_type: "docx",
        parent_node_token: targetParentNodeToken,
        title: "硬件学习笔记",
        ready: true,
      };
      addNode(node);
      return { payload: { ok: true, identity: "user", data: node } };
    },
    async renameMovedWikiDocument({ actionId, nodeToken }) {
      nodes.get(nodeToken).title = actionById.get(actionId).title;
      pageDocument.content = pageDocument.content.replace(
        `<title id="${DOC_TOKEN}">硬件学习笔记</title>`,
        `<title id="${DOC_TOKEN}">01 主控板</title>`,
      );
      return { payload: { ok: true, identity: "user", data: { updated: true } } };
    },
    async replaceDocumentText() {
      throw new Error("already-satisfied template must not write");
    },
    async appendDocumentXml({ document: documentRef, content }) {
      const target = resolveDocument(documentRef);
      target.content += content;
      target.revision_id += 1;
      return { payload: { ok: true, identity: "user", data: { result: "success" } } };
    },
  };
  let saveCount = 0;
  const result = await executeConfirmedFeishuLearningNoteMigration({
    projectDir: "D:/test",
    canvasPageId: "page:page",
    document: `https://example.feishu.cn/docx/${DOC_TOKEN}`,
    planFingerprint: preview.syncPlan.planFingerprint,
    expectedDocumentRevisionId: 9,
    confirmed: true,
  }, {
    preview,
    inspection: {},
    readAdapter,
    writeAdapter,
    saveRegistry: async (_input, registry) => {
      saveCount += 1;
      return { path: "D:/test/registry.json", registry };
    },
  });
  assert.equal(result.ok, true);
  assert.equal(result.page.title, "01 主控板");
  assert.equal(result.page.docToken, DOC_TOKEN);
  assert.deepEqual(result.boardTokens, {
    projectOverview: PROJECT_OVERVIEW_BOARD,
    schematicPage: MAIN_BOARD,
    legacyModuleIndex: INDEX_BOARD,
  });
  assert.equal(result.executionJournal.filter((entry) => entry.status === "created").length, 2);
  assert.equal(result.executionJournal.filter((entry) => entry.status === "moved").length, 1);
  assert.equal(result.homepageWrite.status, "updated");
  assert.match(documents.get("doc-node-2").content, /03 原理图学习/u);
  assert.match(documents.get("doc-node-2").content, new RegExp(PROJECT_OVERVIEW_BOARD, "u"));
  assert.match(documents.get("doc-node-2").content, new RegExp(DOC_TOKEN, "u"));
  assert.equal(saveCount, 1);
  assert.equal(result.localWritesPerformed, true);
});
