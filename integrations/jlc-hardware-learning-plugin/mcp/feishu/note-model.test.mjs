import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE,
  FEISHU_LEARNING_NOTE_STANDARD_VERSION,
  assignFeishuLearningFrameMarkerColors,
  bindFeishuProjectNode,
  bindFeishuProjectOverviewBoard,
  bindFeishuLearningRoot,
  buildFeishuLearningDirectoryPlan,
  createFeishuLearningRegistry,
  feishuProjectDisplayTitle,
  feishuPageContentDigest,
  linkFeishuDialogue,
  markFeishuProjectHomepageSynced,
  markFeishuPageContentSynced,
  resolveFeishuLearningTarget,
  upsertFeishuFrameNote,
  upsertFeishuPageBinding,
} from "./note-model.mjs";

const project = {
  projectId: "00000000000000000000000000000001",
  projectUuid: "00000000000000000000000000000001",
  projectName: "主控板",
};

const pages = [
  { canvasPageId: "page:main", schematicPageUuid: "FixtureSchematicPageUuid01", pageName: "主控板原理图" },
  { canvasPageId: "page:power", schematicPageUuid: "FixtureSchematicPageUuid02", pageName: "电源板原理图" },
];

test("project names remain readable and add a stable suffix only for collisions", () => {
  assert.equal(feishuProjectDisplayTitle(project), "主控板");
  const collisionTitle = feishuProjectDisplayTitle(project, [{
    projectId: "another-project",
    projectName: "主控板",
  }]);
  assert.match(collisionTitle, /^主控板〔[a-f0-9]{8}〕$/u);
  assert.equal(feishuProjectDisplayTitle(project, [{
    projectId: project.projectId,
    projectName: "主控板",
  }]), "主控板");
});

test("directory plans keep categories in one project homepage and pages as direct children", () => {
  const plan = buildFeishuLearningDirectoryPlan({ project, schematicPages: pages });
  assert.equal(plan.namespace.title, "硬件学习笔记");
  assert.equal(plan.root.title, "主控板");
  assert.equal(plan.root.layoutMode, "compact-project-homepage");
  assert.equal(plan.root.projectOverviewBoard.role, "project-schematic-overview");
  assert.deepEqual(
    plan.root.projectOverviewBoard.schematicPages.map((page) => page.schematicPageUuid),
    ["FixtureSchematicPageUuid01", "FixtureSchematicPageUuid02"],
  );
  assert.deepEqual(plan.root.sections.map((section) => section.title), [
    "00 项目总览",
    "01 方案设计",
    "02 模块详细设计",
    "03 原理图学习",
    "04 原理图检查",
    "05 BOM与器件选型",
    "06 调试与实验记录",
    "99 历史归档",
  ]);
  assert.deepEqual(plan.root.children.map((page) => page.title), [
    "01 主控板原理图",
    "02 电源板原理图",
  ]);
  assert.equal(plan.root.children[0].page.canvasPageId, "page:main");
  assert.equal(plan.root.children[0].parentLogicalId, plan.root.logicalId);
});

test("duplicate schematic page names stay readable but receive stable disambiguators", () => {
  const plan = buildFeishuLearningDirectoryPlan({
    project,
    schematicPages: [
      { canvasPageId: "page:a", pageName: "接口页" },
      { canvasPageId: "page:b", pageName: "接口页" },
    ],
  });
  const pageTitles = plan.root.children.map((page) => page.title);
  assert.match(pageTitles[0], /^01 接口页〔[a-f0-9]{8}〕$/u);
  assert.match(pageTitles[1], /^02 接口页〔[a-f0-9]{8}〕$/u);
  assert.notEqual(pageTitles[0], pageTitles[1]);
});

test("learning-frame markers use a translucent top-left badge and stable random distinct colors", () => {
  assert.equal(FEISHU_LEARNING_NOTE_STANDARD_VERSION, "JLC-FN-1.3");
  assert.equal(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.colorOpacityPercent, 50);
  assert.equal(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.numberOpacityPercent, 50);
  assert.equal(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.borderWidthScale, 0.5);
  assert.equal(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.numberBadgeStyle.shape, "round_rect");
  assert.equal(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.numberBadgeStyle.anchor, "frame-top-left");
  assert.equal(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.numberBadgeStyle.scaleMode, "fixed-canvas-size");
  assert.equal(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.numberBadgeStyle.width, 29.2544002532959);
  assert.equal(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.numberBadgeStyle.height, 28.414939880371094);
  assert.equal(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.numberBadgeStyle.offsetX, -8);
  assert.equal(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.numberBadgeStyle.offsetY, -8);
  assert.equal(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.frameColorMode, "stable-random-distinct");
  assert.deepEqual(DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE.moduleIndexStyle, {
    containerMode: "embedded-in-schematic-page-board",
    colorMode: "follow-learning-frame",
    frameGeometryMode: "map-with-schematic-image",
    badgeGeometryMode: "fixed-size-top-left-overlap",
    detailContentMode: "one-sentence-module-summary",
    labelBorderOpacityPercent: 50,
    labelFillOpacityPercent: 50,
    detailBorderOpacityPercent: 50,
    borderWidth: "narrow",
    preserveMindMapStructure: true,
    preserveSchematicEvidence: true,
  });

  const first = assignFeishuLearningFrameMarkerColors(
    DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE,
    [1, 2, 3, 4],
    "page:main",
  );
  const repeated = assignFeishuLearningFrameMarkerColors(
    DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE,
    [1, 2, 3, 4],
    "page:main",
  );
  assert.equal(new Set(Object.values(first).map((entry) => entry.borderColor)).size, 4);
  assert.deepEqual(repeated, first);
  assert.notDeepEqual(
    assignFeishuLearningFrameMarkerColors(
      DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE,
      [1, 2, 3, 4],
      "page:other",
    ),
    first,
  );

  const registry = upsertFeishuPageBinding(createFeishuLearningRegistry(project), {
    projectId: project.projectId,
    canvasPageId: "page:legacy-opacity",
    pageName: "Legacy opacity",
    learningFrameMarkerStyle: {
      ...DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE,
      colorOpacityPercent: 70,
      numberOpacityPercent: 70,
    },
  });
  assert.equal(registry.pages["page:legacy-opacity"].learningFrameMarkerStyle.colorOpacityPercent, 50);
  assert.equal(registry.pages["page:legacy-opacity"].learningFrameMarkerStyle.numberOpacityPercent, 50);
  assert.equal(
    registry.pages["page:legacy-opacity"].learningFrameMarkerStyle.moduleIndexStyle.labelFillOpacityPercent,
    50,
  );
  assert.equal(registry.pages["page:legacy-opacity"].learningFrameMarkerStyle.numberBadgeStyle.width, 29.2544002532959);
  assert.equal(registry.pages["page:legacy-opacity"].learningFrameMarkerStyle.numberBadgeStyle.offsetX, -8);
});

test("page-local frame notes and dialogue bindings resolve to one Feishu target", () => {
  let registry = createFeishuLearningRegistry(project, { updatedAt: "2026-08-26T00:00:00.000Z" });
  registry = bindFeishuLearningRoot(registry, {
    projectId: project.projectId,
    spaceId: "FixtureSpaceId01",
    learningRootNodeToken: "FixtureNodeToken01",
    learningRootDocToken: "doccn-learning-root",
    updatedAt: "2026-08-26T00:00:30.000Z",
  });
  registry = bindFeishuProjectNode(registry, {
    projectId: project.projectId,
    spaceId: "FixtureSpaceId01",
    projectNodeToken: "FixtureNodeToken02",
    projectDocToken: "doccn-project",
    updatedAt: "2026-08-26T00:01:00.000Z",
  });
  registry = bindFeishuProjectOverviewBoard(registry, {
    projectId: project.projectId,
    projectOverviewWhiteboardToken: "FixtureProjectOverviewWhiteboardToken01",
    updatedAt: "2026-08-26T00:02:00.000Z",
  });
  registry = upsertFeishuPageBinding(registry, {
    projectId: project.projectId,
    ...pages[0],
    nodeToken: "FixtureNodeToken03",
    docToken: "doccn-main",
    whiteboardToken: "FixtureWhiteboardToken01",
    updatedAt: "2026-08-26T00:03:00.000Z",
  });
  registry = upsertFeishuFrameNote(registry, {
    projectId: project.projectId,
    canvasPageId: "page:main",
    frameNumber: 5,
    status: "question-open",
    updatedAt: "2026-08-26T00:04:00.000Z",
  });
  registry = linkFeishuDialogue(registry, {
    projectId: project.projectId,
    canvasPageId: "page:main",
    frameNumbers: [5, 7],
    questionId: "question:abc",
    answerDigest: "a".repeat(64),
    docBlockId: "block-answer-abc",
    linkedAt: "2026-08-26T00:05:00.000Z",
  });

  const target = resolveFeishuLearningTarget(registry, {
    canvasPageId: "page:main",
    frameNumbers: [7, 5],
  });
  assert.equal(target.ready, true);
  assert.equal(target.page.docToken, "doccn-main");
  assert.equal(target.page.whiteboardToken, "FixtureWhiteboardToken01");
  assert.equal(target.project.projectId, project.projectId);
  assert.ok(target.frames.every((frame) => frame.schematicPageUuid === "FixtureSchematicPageUuid01"));
  assert.deepEqual(target.frames.map((frame) => frame.frameNumber), [5, 7]);
  assert.deepEqual(registry.pages["page:main"].frames["5"].questionIds, ["question:abc"]);
  assert.deepEqual(registry.pages["page:main"].frames["7"].answerDigests, ["a".repeat(64)]);
});

test("marking a compact project homepage clears legacy section-document bindings", () => {
  const registry = createFeishuLearningRegistry(project, {
    projectOverviewWhiteboardToken: "FixtureProjectOverviewWhiteboardToken01",
  });
  registry.sections.schematics.nodeToken = "legacy-section-node";
  registry.sections.schematics.docToken = "legacy-section-doc";
  const compact = markFeishuProjectHomepageSynced(registry, {
    projectId: project.projectId,
    indexDigest: "c".repeat(64),
    updatedAt: "2026-08-27T00:00:00.000Z",
  });
  assert.equal(compact.wiki.layoutMode, "compact-project-homepage");
  assert.equal(compact.wiki.projectHomepageTemplateVersion, 2);
  assert.equal(compact.sections.schematics.nodeToken, null);
  assert.equal(compact.sections.schematics.docToken, null);
});

test("project, page and frame identity mismatches fail instead of falling back", () => {
  let registry = createFeishuLearningRegistry(project, { updatedAt: "2026-08-26T00:00:00.000Z" });
  assert.throws(() => upsertFeishuPageBinding(registry, {
    projectId: "wrong-project",
    ...pages[0],
  }), /project identity mismatch/u);
  registry = upsertFeishuPageBinding(registry, { projectId: project.projectId, ...pages[0] });
  assert.throws(() => upsertFeishuFrameNote(registry, {
    projectId: project.projectId,
    canvasPageId: "page:main",
    schematicPageUuid: "FixtureSchematicPageUuid03",
    frameNumber: 1,
  }), /does not belong to the bound schematic page/u);
  assert.throws(() => upsertFeishuPageBinding(registry, {
    projectId: project.projectId,
    ...pages[0],
    schematicPageUuid: "FixtureSchematicPageUuid04",
  }), /schematic identity mismatch/u);
  assert.throws(() => upsertFeishuFrameNote(registry, {
    projectId: project.projectId,
    canvasPageId: "page:missing",
    frameNumber: 1,
  }), /page binding not found/u);
  assert.throws(() => upsertFeishuPageBinding(registry, {
    projectId: project.projectId,
    ...pages[1],
    learningFrameMarkerStyle: {
      ...registry.pages["page:main"].learningFrameMarkerStyle,
      numberBadgeStyle: {
        ...registry.pages["page:main"].learningFrameMarkerStyle.numberBadgeStyle,
        offsetX: Number.NaN,
      },
    },
  }), /offsetX must be finite/u);
});

test("dialogue replays are immutable and page content digests track note changes", () => {
  let registry = createFeishuLearningRegistry(project, { updatedAt: "2026-08-26T00:00:00.000Z" });
  registry = upsertFeishuPageBinding(registry, { projectId: project.projectId, ...pages[0] });
  const dialogue = {
    projectId: project.projectId,
    canvasPageId: "page:main",
    frameNumbers: [1],
    questionId: "question:stable",
    answerDigest: "b".repeat(64),
    linkedAt: "2026-08-26T00:01:00.000Z",
  };
  registry = linkFeishuDialogue(registry, dialogue);
  const digest = feishuPageContentDigest(registry, "page:main");
  assert.equal(digest.length, 64);
  assert.deepEqual(linkFeishuDialogue(registry, dialogue), registry);
  assert.throws(() => linkFeishuDialogue(registry, {
    ...dialogue,
    docBlockId: "different-block",
  }), /Immutable Feishu dialogue binding differs/u);
  const synced = markFeishuPageContentSynced(registry, {
    projectId: project.projectId,
    canvasPageId: "page:main",
    updatedAt: "2026-08-26T00:02:00.000Z",
  });
  assert.equal(synced.pages["page:main"].syncedContentDigest, digest);
  assert.equal(synced.pages["page:main"].noteTemplateVersion, 2);
});
