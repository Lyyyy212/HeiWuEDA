import assert from "node:assert/strict";
import test from "node:test";

import {
  bindFeishuProjectNode,
  buildFeishuLearningDirectoryPlan,
  createFeishuLearningRegistry,
  markFeishuProjectHomepageSynced,
  markFeishuPageContentSynced,
  upsertFeishuPageBinding,
} from "./note-model.mjs";
import { planFeishuLearningSync } from "./sync-plan.mjs";

const project = { projectId: "project-1", projectName: "声呐接收板" };
const page = { canvasPageId: "page:receiver", pageName: "接收链路" };

test("an empty registry produces deterministic compact-homepage, page and whiteboard actions", () => {
  const directoryPlan = buildFeishuLearningDirectoryPlan({ project, schematicPages: [page] });
  const registry = createFeishuLearningRegistry(project, { updatedAt: "2026-08-26T00:00:00.000Z" });
  const first = planFeishuLearningSync({ directoryPlan, registry });
  const second = planFeishuLearningSync({ directoryPlan, registry });
  assert.deepEqual(first, second);
  assert.match(first.planFingerprint, /^[a-f0-9]{64}$/u);
  assert.equal(first.identity, "user");
  assert.equal(first.writePolicy, "confirm-before-execute-and-fresh-read-after-write");
  assert.equal(first.actions.filter((action) => action.kind === "wiki.node.ensure").length, 3);
  assert.equal(first.actions.filter((action) => action.kind === "doc.whiteboard.ensure").length, 1);
  assert.equal(
    first.actions.filter((action) => action.kind === "doc.module-index-whiteboard.ensure").length,
    1,
  );
  assert.equal(
    first.actions.filter((action) => action.kind === "doc.project-homepage.ensure").length,
    1,
  );
  const categoryTitles = new Set(directoryPlan.root.sections.map((section) => section.title));
  assert.deepEqual(
    first.actions
      .filter((action) => categoryTitles.has(action.title))
      .map((action) => ({ kind: action.kind, title: action.title })),
    [],
    "00..99 categories must stay inside the project homepage instead of creating Wiki/Docx nodes",
  );
  assert.equal(
    first.actions.filter((action) => action.kind === "wiki.node.ensure").length,
    2 + directoryPlan.root.children.length,
    "Wiki nodes are limited to the learning root, project homepage, and real schematic pages",
  );
  assert.ok(first.actions.every((action) => action.idempotencyKey.length >= 10));
});

test("existing bindings are reused and a complete project produces no duplicate actions", () => {
  const directoryPlan = buildFeishuLearningDirectoryPlan({ project, schematicPages: [page] });
  let registry = createFeishuLearningRegistry(project, { updatedAt: "2026-08-26T00:00:00.000Z" });
  registry.wiki.learningRootNodeToken = "FixtureNodeToken01";
  registry.wiki.learningRootDocToken = "doc-learning-root";
  registry = bindFeishuProjectNode(registry, {
    projectId: project.projectId,
    spaceId: "FixtureSpaceId01",
    projectNodeToken: "FixtureNodeToken02",
    projectDocToken: "doc-project",
  });
  registry = upsertFeishuPageBinding(registry, {
    projectId: project.projectId,
    ...page,
    nodeToken: "FixtureNodeToken03",
    docToken: "doc-receiver",
    whiteboardToken: "FixtureWhiteboardToken01",
    moduleIndexWhiteboardToken: "FixtureModuleIndexWhiteboardToken01",
  });
  registry = markFeishuPageContentSynced(registry, {
    projectId: project.projectId,
    canvasPageId: page.canvasPageId,
  });
  const homepageAction = planFeishuLearningSync({ directoryPlan, registry }).actions.find(
    (action) => action.kind === "doc.project-homepage.ensure",
  );
  registry = markFeishuProjectHomepageSynced(registry, {
    projectId: project.projectId,
    indexDigest: homepageAction.desiredContentDigest,
  });
  assert.deepEqual(planFeishuLearningSync({ directoryPlan, registry }).actions, []);
});

test("bound pages request template and module-index updates until fresh content is marked synced", () => {
  const directoryPlan = buildFeishuLearningDirectoryPlan({ project, schematicPages: [page] });
  let registry = createFeishuLearningRegistry(project);
  registry = upsertFeishuPageBinding(registry, {
    projectId: project.projectId,
    ...page,
    nodeToken: "FixtureNodeToken03",
    docToken: "doc-receiver",
    whiteboardToken: "FixtureWhiteboardToken01",
    moduleIndexWhiteboardToken: "FixtureModuleIndexWhiteboardToken01",
  });
  const pageActions = planFeishuLearningSync({ directoryPlan, registry }).actions
    .filter((action) => action.logicalId.includes(registry.pages[page.canvasPageId].pageKey));
  assert.deepEqual(pageActions.map((action) => action.kind), [
    "doc.page-template.ensure",
    "doc.module-index.sync",
  ]);
  assert.match(pageActions[1].desiredContentDigest, /^[a-f0-9]{64}$/u);
});

test("directory plans cannot be combined with another project registry", () => {
  const directoryPlan = buildFeishuLearningDirectoryPlan({ project, schematicPages: [page] });
  const registry = createFeishuLearningRegistry({ projectId: "project-2", projectName: "另一项目" });
  assert.throws(
    () => planFeishuLearningSync({ directoryPlan, registry }),
    /project identity mismatch/u,
  );
});
