import { createHash } from "node:crypto";

import {
  DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE,
  FEISHU_DIRECTORY_PLAN_SCHEMA,
  FEISHU_NOTE_REGISTRY_SCHEMA,
  FEISHU_PAGE_NOTE_TEMPLATE_VERSION,
  FEISHU_PAGE_MANAGED_CONTENT_VERSION,
  FEISHU_PROJECT_HOMEPAGE_TEMPLATE_VERSION,
  feishuPageContentDigest,
  validateFeishuLearningRegistry,
} from "./note-model.mjs";
import { feishuProjectHomepageIndexDigest } from "./project-homepage.mjs";

export const FEISHU_SYNC_PLAN_SCHEMA = "jlc.feishu-learning-sync-plan.v1";

function stableToken(...parts) {
  return `jlc-feishu-${createHash("sha256").update(parts.join("|")).digest("hex").slice(0, 24)}`;
}

function createAction({ kind, logicalId, title, parentLogicalId = null, requires = [], verification }) {
  return {
    actionId: `${kind}:${logicalId}`,
    kind,
    logicalId,
    title,
    parentLogicalId,
    idempotencyKey: stableToken(kind, logicalId),
    requires,
    verification,
  };
}

export function finalizeFeishuLearningSyncPlan({ projectKey, actions } = {}) {
  if (typeof projectKey !== "string" || !projectKey.trim()) throw new Error("projectKey is required.");
  if (!Array.isArray(actions)) throw new Error("actions must be an array.");
  const planIdentity = {
    schemaVersion: FEISHU_SYNC_PLAN_SCHEMA,
    projectKey: projectKey.trim(),
    identity: "user",
    actions,
  };
  return {
    ...planIdentity,
    writePolicy: "confirm-before-execute-and-fresh-read-after-write",
    planFingerprint: createHash("sha256").update(JSON.stringify(planIdentity)).digest("hex"),
  };
}

export function planFeishuLearningSync({ directoryPlan, registry } = {}) {
  if (!directoryPlan || directoryPlan.schemaVersion !== FEISHU_DIRECTORY_PLAN_SCHEMA) {
    throw new Error(`directoryPlan must use ${FEISHU_DIRECTORY_PLAN_SCHEMA}.`);
  }
  if (!registry || registry.schemaVersion !== FEISHU_NOTE_REGISTRY_SCHEMA) {
    throw new Error(`registry must use ${FEISHU_NOTE_REGISTRY_SCHEMA}.`);
  }
  validateFeishuLearningRegistry(registry);
  if (directoryPlan.project.projectId !== registry.project.projectId) {
    throw new Error("Feishu directory plan and registry project identity mismatch.");
  }

  const actions = [];
  const namespaceLogicalId = directoryPlan.namespace.logicalId;
  const projectLogicalId = directoryPlan.root.logicalId;
  if (!registry.wiki.learningRootNodeToken || !registry.wiki.learningRootDocToken) {
    actions.push(createAction({
      kind: "wiki.node.ensure",
      logicalId: namespaceLogicalId,
      title: directoryPlan.namespace.title,
      verification: "wiki.node.get",
    }));
  }
  if (!registry.wiki.projectNodeToken || !registry.wiki.projectDocToken) {
    actions.push(createAction({
      kind: "wiki.node.ensure",
      logicalId: projectLogicalId,
      title: directoryPlan.root.title,
      parentLogicalId: namespaceLogicalId,
      requires: [namespaceLogicalId],
      verification: "wiki.node.get",
    }));
  }
  if (!registry.wiki.projectOverviewWhiteboardToken) {
    const overviewBoard = directoryPlan.root.projectOverviewBoard;
    const action = createAction({
      kind: "doc.project-overview-whiteboard.ensure",
      logicalId: overviewBoard.logicalId,
      title: overviewBoard.title,
      parentLogicalId: projectLogicalId,
      requires: [projectLogicalId],
      verification: "docs.fetch.project_overview_board_token-and-all-schematic-pages",
    });
    action.schematicPages = overviewBoard.schematicPages;
    actions.push(action);
  }

  for (const pageNode of directoryPlan.root.children) {
    const page = registry.pages[pageNode.page.canvasPageId];
    if (!page?.nodeToken || !page?.docToken) {
      actions.push(createAction({
        kind: page?.docToken && page.documentLocation === "drive"
          ? "wiki.document.move"
          : "wiki.node.ensure",
        logicalId: pageNode.logicalId,
        title: pageNode.title,
        parentLogicalId: projectLogicalId,
        requires: [projectLogicalId],
        verification: "wiki.node.get",
      }));
    }
    if (!page?.whiteboardToken) {
      const action = createAction({
        kind: "doc.whiteboard.ensure",
        logicalId: `${pageNode.logicalId}:whiteboard`,
        title: `${pageNode.page.pageName}原理图学习画板`,
        parentLogicalId: pageNode.logicalId,
        requires: [pageNode.logicalId],
        verification: "docs.fetch.board_token-and-matching-schematic-page",
      });
      action.boardRole = "schematic-page-learning-board";
      action.schematicPage = {
        canvasPageId: pageNode.page.canvasPageId,
        schematicPageUuid: pageNode.page.schematicPageUuid,
        pageName: pageNode.page.pageName,
        sourceRevision: pageNode.page.sourceRevision,
      };
      action.learningFrameMarkerStyle = page?.learningFrameMarkerStyle
        ?? DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE;
      actions.push(action);
    }
    if (page?.docToken && (page.noteTemplateVersion ?? 0) < FEISHU_PAGE_NOTE_TEMPLATE_VERSION) {
      actions.push(createAction({
        kind: "doc.page-template.ensure",
        logicalId: `${pageNode.logicalId}:template-v${FEISHU_PAGE_NOTE_TEMPLATE_VERSION}`,
        title: `${pageNode.page.pageName}学习笔记结构`,
        parentLogicalId: pageNode.logicalId,
        requires: [pageNode.logicalId],
        verification: "docs.fetch.page-template",
      }));
    }
    if (page?.docToken) {
      const desiredContentDigest = feishuPageContentDigest(registry, pageNode.page.canvasPageId);
      if (
        (page.managedContentVersion ?? 0) < FEISHU_PAGE_MANAGED_CONTENT_VERSION
        || page.syncedContentDigest !== desiredContentDigest
      ) {
        actions.push({
          ...createAction({
            kind: "doc.module-index.sync",
            logicalId: `${pageNode.logicalId}:module-index`,
            title: `${pageNode.page.pageName}模块索引与学习问答`,
            parentLogicalId: pageNode.logicalId,
            requires: [pageNode.logicalId],
            verification: "docs.fetch.module-index",
          }),
          desiredContentDigest,
        });
      }
    }
  }

  const homepagePages = directoryPlan.root.children.map((pageNode) => ({
    canvasPageId: pageNode.page.canvasPageId,
    title: pageNode.title,
    docToken: registry.pages[pageNode.page.canvasPageId]?.docToken ?? null,
  }));
  const desiredHomepageIndexDigest = feishuProjectHomepageIndexDigest({
    project: registry.project,
    pages: homepagePages,
    projectOverviewWhiteboardToken: registry.wiki.projectOverviewWhiteboardToken,
  });
  if (
    registry.wiki.projectOverviewWhiteboardToken
    && (
    (registry.wiki.projectHomepageTemplateVersion ?? 0)
      < FEISHU_PROJECT_HOMEPAGE_TEMPLATE_VERSION
    || registry.wiki.projectHomepageIndexDigest !== desiredHomepageIndexDigest
    )
  ) {
    actions.push({
      ...createAction({
        kind: "doc.project-homepage.ensure",
        logicalId: `${projectLogicalId}:homepage-v${FEISHU_PROJECT_HOMEPAGE_TEMPLATE_VERSION}`,
        title: `${directoryPlan.root.title}项目主页`,
        parentLogicalId: projectLogicalId,
        requires: [
          projectLogicalId,
          `${projectLogicalId}:project-overview-whiteboard`,
          ...directoryPlan.root.children.map((page) => page.logicalId),
        ],
        verification: "docs.fetch.project-homepage",
      }),
      desiredContentDigest: desiredHomepageIndexDigest,
    });
  }

  return finalizeFeishuLearningSyncPlan({
    projectKey: registry.project.projectKey,
    actions,
  });
}
