import assert from "node:assert/strict";
import test from "node:test";

import {
  previewLegacyFeishuLearningMigration,
  resolveLegacyFeishuLearningFiles,
} from "./legacy-migration.mjs";

const projectId = "3887ba22c860470abf2ab42453fdd249";
const docToken = "CwGJdseLUoB3GlxIVEdc4zgZnBh";
const learningBoardToken = "PhfGw0fY2htpI8bOVXqcAoB7nvc";
const indexBoardToken = "E6uZwU99Qh3Xcqb4j8Mcs1xznOb";
const digest = "a".repeat(64);
const markerStyle = {
  colorOpacityPercent: 70,
  numberOpacityPercent: 70,
  borderWidthScale: 0.5,
  preserveBounds: true,
  numberBadgeStyle: {
    shape: "round_rect",
    width: 29.2544002532959,
    height: 28.414939880371094,
    fontSize: 12,
    anchor: "frame-top-left",
    offsetX: -23.912109375,
    offsetY: -22.4390869140625,
    colorMode: "follow-frame",
  },
};

const binding = {
  schemaVersion: "learning.lark-binding.v1",
  cowartPageId: "page:page",
  document: {
    documentId: docToken,
    url: `https://example.feishu.cn/docx/${docToken}`,
    verifiedRevisionId: 5,
  },
  whiteboard: { token: learningBoardToken, markerStyle },
  moduleIndexBoard: { token: indexBoardToken },
  source: { contentSha256: digest },
  lastPublishedAt: "2026-08-26T05:14:23.000Z",
};

const notePackage = {
  schemaVersion: "learning.note-package.v1",
  generatedAt: "2026-08-26T05:00:00.000Z",
  contentSha256: digest,
  page: { cowartPageId: "page:page", name: "Page 1" },
  canvasSnapshot: { sha256: "b".repeat(64) },
  sourceImages: [{
    shapeId: "shape:main",
    evidenceSource: "official-easyeda-export",
    altText: "EasyEDA PNG (SCH_新_4管升降压SCH_B1_2_2-主控板_2026-08-24.png)",
    easyedaIdentity: {
      projectUuid: projectId,
      documentUuid: "schematic-main",
      documentType: 1,
      nativeBundleEntryName: "SCH_新_4管升降压SCH_B1_2_2-主控板_2026-08-24.png",
    },
  }],
  frames: [4, 5, 7].map((frameNumber) => ({
    frameId: `frame:${frameNumber}`,
    frameNumber,
    title: `模块${frameNumber}`,
    sourceImageIds: ["shape:main"],
    dialogueTurnIds: [],
  })),
  dialogue: { turns: [] },
  larkPlan: { whiteboard: { learningFrameMarkerStyle: markerStyle } },
};

const inspection = {
  identity: "user",
  remoteWritesPerformed: false,
  document: { docToken, revisionId: 8 },
  whiteboards: [
    { role: "learning-board", blockId: "block-main", token: learningBoardToken },
    { role: "module-index-board", blockId: "block-index", token: indexBoardToken },
  ],
  moduleHeadings: [4, 5, 7].map((frameNumber) => ({
    frameNumber,
    blockId: `block-module-${frameNumber}`,
  })),
  legacyBrandingTerms: ["Cowart"],
};

test("legacy migration preview reuses the live document and both board tokens", () => {
  const preview = previewLegacyFeishuLearningMigration({
    binding,
    notePackage,
    inspection,
    projectId,
    projectName: "【已测试】MPPT96V35A自动升降控制器",
  });
  const page = preview.registry.pages["page:page"];
  assert.equal(preview.mode, "PREVIEW_ONLY_NO_LOCAL_OR_REMOTE_WRITE");
  assert.equal(preview.directoryPlan.root.title, "【已测试】MPPT96V35A自动升降控制器");
  assert.equal(preview.directoryPlan.root.layoutMode, "compact-project-homepage");
  assert.equal(preview.directoryPlan.root.children[0].title, "01 主控板");
  assert.deepEqual(preview.directoryPlan.root.sections.map((section) => section.title), [
    "00 项目总览",
    "01 方案设计",
    "02 模块详细设计",
    "03 原理图学习",
    "04 原理图检查",
    "05 BOM与器件选型",
    "06 调试与实验记录",
    "99 历史归档",
  ]);
  assert.equal(page.documentLocation, "drive");
  assert.equal(page.docToken, docToken);
  assert.equal(page.whiteboardToken, learningBoardToken);
  assert.equal(page.moduleIndexWhiteboardToken, indexBoardToken);
  assert.equal(page.schematicPageUuid, "schematic-main");
  assert.equal(page.learningFrameMarkerStyle.colorOpacityPercent, 70);
  assert.equal(page.learningFrameMarkerStyle.borderWidthScale, 0.5);
  assert.deepEqual(Object.keys(page.frames), ["4", "5", "7"]);
  assert.equal(page.frames["7"].docBlockId, "block-module-7");
  assert.equal(
    preview.syncPlan.actions.filter((action) => action.kind === "wiki.document.move").length,
    1,
  );
  assert.equal(
    preview.syncPlan.actions.filter((action) => action.kind.includes("whiteboard.ensure")).length,
    0,
  );
});

test("legacy migration blocks mismatched live board identities", () => {
  assert.throws(() => previewLegacyFeishuLearningMigration({
    binding,
    notePackage,
    inspection: {
      ...inspection,
      whiteboards: inspection.whiteboards.map((board) => (
        board.role === "learning-board" ? { ...board, token: "wrong-token" } : board
      )),
    },
    projectId,
    projectName: "项目",
  }), /learning-board token does not match/u);
});

test("legacy artifact paths are page-scoped and project-local", () => {
  const files = resolveLegacyFeishuLearningFiles({ projectDir: "D:/project", canvasPageId: "page:main" });
  assert.match(files.bindingPath, /page--main-binding\.json$/u);
  assert.match(files.notePackagePath, /page--main-note-package\.json$/u);
});
