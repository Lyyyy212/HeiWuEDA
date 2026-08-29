import {
  FEISHU_PAGE_MANAGED_CONTENT_VERSION,
  FEISHU_PAGE_NOTE_TEMPLATE_VERSION,
  markFeishuPageContentSynced,
  markFeishuProjectHomepageSynced,
  upsertFeishuPageBinding,
} from "./note-model.mjs";
import { readFeishuLearningDialogueRecords } from "./dialogue-records.mjs";
import {
  inspectFeishuManagedPageContent,
  planFeishuManagedPagePatch,
  renderFeishuManagedPageContent,
} from "./page-content.mjs";
import { inspectFeishuLearningDocument } from "./document-inspection.mjs";
import {
  createConfirmedLarkCliWriteAdapter,
  createLarkCliAdapter,
} from "./lark-cli-adapter.mjs";
import {
  inspectFeishuProjectHomepage,
  renderFeishuProjectHomepageAppendXml,
} from "./project-homepage.mjs";
import { saveFeishuLearningRegistry } from "./storage.mjs";
import { finalizeFeishuLearningSyncPlan } from "./sync-plan.mjs";

export const FEISHU_SYNC_PREVIEW_SCHEMA = "jlc.feishu-learning-sync-preview.v1";
export const FEISHU_CONFIRMED_SYNC_RESULT_SCHEMA = "jlc.feishu-confirmed-sync-result.v1";

const UNSUPPORTED_GENERIC_ACTIONS = new Set([
  "wiki.node.ensure",
  "wiki.document.move",
  "doc.project-overview-whiteboard.ensure",
  "doc.whiteboard.ensure",
]);

function documentFromPayload(payload) {
  const document = payload?.data?.document;
  if (!document || typeof document.content !== "string") {
    throw new Error("Feishu document response is missing data.document.content.");
  }
  return document;
}

function blocker(code, message, target = {}) {
  return { code, message, ...target };
}

function pageNodeForAction(directoryPlan, action) {
  return directoryPlan.root.children.find((pageNode) => (
    action.logicalId === pageNode.logicalId
    || action.parentLogicalId === pageNode.logicalId
    || action.logicalId.startsWith(`${pageNode.logicalId}:`)
  )) ?? null;
}

function sortRevisionMap(value) {
  return Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)));
}

export async function previewFeishuLearningSyncFromState(
  args = {},
  state,
  options = {},
) {
  if (!state?.registryExists) throw new Error("Initialize or migrate the Feishu learning-note registry first.");
  const readAdapter = options.readAdapter ?? createLarkCliAdapter(options);
  const blockers = [];
  const inspections = {};
  const pagePatches = {};
  const expectedDocumentRevisions = {};

  for (const pageNode of state.directoryPlan.root.children) {
    const page = state.registry.pages[pageNode.page.canvasPageId];
    if (!page?.docToken) continue;
    const pageActions = state.syncPlan.actions.filter((action) => {
      const targetPage = pageNodeForAction(state.directoryPlan, action);
      return targetPage?.page.canvasPageId === page.canvasPageId
        && ["doc.page-template.ensure", "doc.module-index.sync"].includes(action.kind);
    });
    if (pageActions.length === 0) continue;
    const inspection = await inspectFeishuLearningDocument(
      { document: page.docToken },
      { adapter: readAdapter },
    );
    inspections[page.canvasPageId] = inspection;
    expectedDocumentRevisions[page.docToken] = inspection.document.revisionId;
    if (!page.schematicPageUuid) {
      blockers.push(blocker(
        "SCHEMATIC_PAGE_IDENTITY_MISSING",
        "The canvas page is not bound to a verified EasyEDA schematicPageUuid.",
        { canvasPageId: page.canvasPageId, docToken: page.docToken },
      ));
    }
    const learningBoard = inspection.whiteboards.find((board) => board.role === "learning-board");
    if (!learningBoard || learningBoard.token !== page.whiteboardToken) {
      blockers.push(blocker(
        "LEARNING_BOARD_TOKEN_MISMATCH",
        "The existing learning whiteboard token is missing or differs from the registry.",
        { canvasPageId: page.canvasPageId, docToken: page.docToken },
      ));
    }
    const dialogueRecords = await readFeishuLearningDialogueRecords(
      args,
      state.registry,
      page.canvasPageId,
    );
    const rendered = renderFeishuManagedPageContent({
      registry: state.registry,
      canvasPageId: page.canvasPageId,
      dialogueRecords,
    });
    const liveDocument = documentFromPayload(await readAdapter.fetchDocumentFull(page.docToken));
    if (
      liveDocument.document_id !== page.docToken
      || liveDocument.revision_id !== inspection.document.revisionId
    ) throw new Error(`Feishu document changed during sync preview: ${page.docToken}`);
    const patch = planFeishuManagedPagePatch({
      content: liveDocument.content,
      rendered,
    });
    pagePatches[page.canvasPageId] = {
      canvasPageId: page.canvasPageId,
      schematicPageUuid: page.schematicPageUuid,
      docToken: page.docToken,
      expectedRevisionId: inspection.document.revisionId,
      learningBoardToken: page.whiteboardToken,
      rendered,
      operations: patch.operations,
      contentDigest: patch.contentDigest,
      alreadySynchronized: patch.alreadySynchronized,
    };
  }

  let homepagePatch = null;
  if (state.syncPlan.actions.some((action) => action.kind === "doc.project-homepage.ensure")) {
    const document = state.registry.wiki.projectDocToken;
    if (!document) {
      blockers.push(blocker(
        "PROJECT_HOMEPAGE_BINDING_MISSING",
        "The project homepage has no verified Docx binding.",
      ));
    } else {
      const before = documentFromPayload(await readAdapter.fetchDocumentFull(document));
      expectedDocumentRevisions[document] = before.revision_id;
      const pages = state.directoryPlan.root.children.map((pageNode) => ({
        canvasPageId: pageNode.page.canvasPageId,
        title: pageNode.title,
        docToken: state.registry.pages[pageNode.page.canvasPageId]?.docToken ?? null,
      }));
      const rendered = renderFeishuProjectHomepageAppendXml({
        project: state.registry.project,
        pages,
        projectOverviewWhiteboardToken: state.registry.wiki.projectOverviewWhiteboardToken,
        existingContent: before.content,
      });
      homepagePatch = {
        docToken: document,
        expectedRevisionId: before.revision_id,
        pages,
        appendXml: rendered.xml,
        indexDigest: rendered.indexDigest,
      };
    }
  }

  const actions = state.syncPlan.actions.map((action) => {
    const pageNode = pageNodeForAction(state.directoryPlan, action);
    if (UNSUPPORTED_GENERIC_ACTIONS.has(action.kind)) {
      blockers.push(blocker(
        "INITIAL_MIGRATION_REQUIRED",
        "Hierarchy creation, Drive-to-Wiki moves, and new boards require the guarded initial migration flow; a blank board will not be created by continuous sync.",
        { actionId: action.actionId, actionKind: action.kind },
      ));
    }
    if (pageNode && ["doc.page-template.ensure", "doc.module-index.sync"].includes(action.kind)) {
      const patch = pagePatches[pageNode.page.canvasPageId];
      if (!patch) return action;
      if (
        action.kind === "doc.page-template.ensure"
        && inspections[pageNode.page.canvasPageId].requiredSections.missing.length > 0
      ) {
        blockers.push(blocker(
          "PAGE_TEMPLATE_REPAIR_REQUIRES_MIGRATION",
          "The page is missing required structural sections; repair it through the guarded migration flow before continuous sync.",
          { canvasPageId: pageNode.page.canvasPageId, docToken: patch.docToken },
        ));
      }
      return {
        ...action,
        target: {
          canvasPageId: patch.canvasPageId,
          schematicPageUuid: patch.schematicPageUuid,
          docToken: patch.docToken,
          expectedRevisionId: patch.expectedRevisionId,
          learningBoardToken: patch.learningBoardToken,
        },
        managedContentDigest: patch.contentDigest,
      };
    }
    if (action.kind === "doc.project-homepage.ensure" && homepagePatch) {
      return {
        ...action,
        target: {
          docToken: homepagePatch.docToken,
          expectedRevisionId: homepagePatch.expectedRevisionId,
        },
        appendXmlDigest: homepagePatch.appendXml ? action.desiredContentDigest : null,
      };
    }
    return action;
  });
  const syncPlan = finalizeFeishuLearningSyncPlan({
    projectKey: state.registry.project.projectKey,
    actions,
  });
  const uniqueBlockers = [...new Map(blockers.map((entry) => [
    JSON.stringify(entry),
    entry,
  ])).values()];
  return {
    ok: true,
    schemaVersion: FEISHU_SYNC_PREVIEW_SCHEMA,
    identity: "user",
    project: state.registry.project,
    registry: state.registry,
    directoryPlan: state.directoryPlan,
    syncPlan,
    expectedDocumentRevisions: sortRevisionMap(expectedDocumentRevisions),
    pagePatches,
    homepagePatch,
    blockers: uniqueBlockers,
    executable: uniqueBlockers.length === 0,
    localWritesPerformed: false,
    remoteWritesPerformed: false,
  };
}

function verifyConfirmation(input, preview) {
  if (input.confirmed !== true) throw new Error("Feishu writes require explicit confirmation.");
  if (input.planFingerprint !== preview.syncPlan.planFingerprint) {
    throw new Error("Fresh Feishu sync preview no longer matches the confirmed plan fingerprint.");
  }
  const expected = sortRevisionMap(input.expectedDocumentRevisions ?? {});
  if (JSON.stringify(expected) !== JSON.stringify(preview.expectedDocumentRevisions)) {
    throw new Error("Fresh Feishu document revisions no longer match the confirmed revision map.");
  }
  if (preview.blockers.length > 0) {
    throw new Error(`Feishu sync is blocked: ${preview.blockers.map((entry) => entry.code).join(", ")}`);
  }
}

async function applyManagedPage({ readAdapter, writeAdapter, action, patch }) {
  const writes = [];
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const before = documentFromPayload(await readAdapter.fetchDocumentFull(patch.docToken));
    const livePlan = planFeishuManagedPagePatch({
      content: before.content,
      rendered: patch.rendered,
    });
    if (livePlan.operations.length === 0) {
      const managed = inspectFeishuManagedPageContent(before.content);
      if (
        managed.moduleIndex?.contentDigest !== patch.contentDigest
        || managed.dialogues?.contentDigest !== patch.contentDigest
      ) throw new Error(`Managed Feishu page verification failed: ${patch.canvasPageId}`);
      return { status: writes.length > 0 ? "updated" : "reused", writes, document: before };
    }
    const operation = livePlan.operations[0];
    if (operation.kind === "block_insert_after") {
      await writeAdapter.insertDocumentBlocksAfter({
        actionId: action.actionId,
        document: patch.docToken,
        revisionId: before.revision_id,
        blockId: operation.blockId,
        content: operation.content,
      });
    } else if (operation.kind === "block_replace") {
      await writeAdapter.replaceDocumentBlocks({
        actionId: action.actionId,
        document: patch.docToken,
        revisionId: before.revision_id,
        startBlockId: operation.startBlockId,
        endBlockId: operation.endBlockId,
        content: operation.content,
      });
    } else {
      throw new Error(`Unsupported managed Feishu page operation: ${operation.kind}`);
    }
    writes.push({ section: operation.section, kind: operation.kind, revisionId: before.revision_id });
  }
  throw new Error(`Managed Feishu page did not converge after four bounded writes: ${patch.canvasPageId}`);
}

async function applyHomepage({ readAdapter, writeAdapter, action, preview }) {
  const patch = preview.homepagePatch;
  const before = documentFromPayload(await readAdapter.fetchDocumentFull(patch.docToken));
  const rendered = renderFeishuProjectHomepageAppendXml({
    project: preview.registry.project,
    pages: patch.pages,
    projectOverviewWhiteboardToken: preview.registry.wiki.projectOverviewWhiteboardToken,
    existingContent: before.content,
  });
  let status = "reused";
  if (rendered.xml) {
    await writeAdapter.appendDocumentXml({
      actionId: action.actionId,
      document: patch.docToken,
      revisionId: before.revision_id,
      content: rendered.xml,
    });
    status = "updated";
  }
  const after = documentFromPayload(await readAdapter.fetchDocumentFull(patch.docToken));
  const inspection = inspectFeishuProjectHomepage(after.content, {
    pages: patch.pages,
    projectOverviewWhiteboardToken: preview.registry.wiki.projectOverviewWhiteboardToken,
  });
  if (
    inspection.missingSectionKeys.length > 0
    || inspection.missingPageDocTokens.length > 0
    || inspection.missingProjectOverviewWhiteboardToken
  ) {
    throw new Error("Project homepage verification failed after continuous sync.");
  }
  return { status, document: after, indexDigest: rendered.indexDigest };
}

export async function executeConfirmedFeishuLearningNoteSync(
  input = {},
  preview,
  options = {},
) {
  verifyConfirmation(input, preview);
  if (preview.syncPlan.actions.length === 0) {
    return {
      ok: true,
      schemaVersion: FEISHU_CONFIRMED_SYNC_RESULT_SCHEMA,
      planFingerprint: preview.syncPlan.planFingerprint,
      executionJournal: [],
      remoteWritesPerformed: false,
      localWritesPerformed: false,
    };
  }
  const readAdapter = options.readAdapter ?? createLarkCliAdapter(options);
  const writeAdapter = options.writeAdapter ?? createConfirmedLarkCliWriteAdapter({
    ...options,
    timeoutMs: options.timeoutMs ?? 90_000,
    plan: preview.syncPlan,
    confirmation: {
      confirmed: true,
      planFingerprint: preview.syncPlan.planFingerprint,
      expectedDocumentRevisions: preview.expectedDocumentRevisions,
    },
  });
  for (const [docToken, revisionId] of Object.entries(preview.expectedDocumentRevisions)) {
    const live = documentFromPayload(await readAdapter.fetchDocumentFull(docToken));
    if (live.document_id !== docToken || live.revision_id !== revisionId) {
      throw new Error(`Feishu document revision changed before sync: ${docToken}`);
    }
  }
  let registry = preview.registry;
  const executionJournal = [];
  const pageResults = {};
  let homepageResult = null;
  for (const action of preview.syncPlan.actions) {
    if (action.kind === "doc.page-template.ensure") {
      const pageInspection = await inspectFeishuLearningDocument(
        { document: action.target.docToken },
        { adapter: readAdapter },
      );
      if (pageInspection.requiredSections.missing.length > 0) {
        throw new Error(`Feishu page template changed after preview: ${action.target.docToken}`);
      }
      pageResults[action.target.canvasPageId] = {
        status: "reused",
        document: { revision_id: pageInspection.document.revisionId },
        templateOnly: true,
      };
      executionJournal.push({ actionId: action.actionId, kind: action.kind, status: "reused" });
      continue;
    }
    if (action.kind === "doc.module-index.sync") {
      const patch = preview.pagePatches[action.target.canvasPageId];
      const result = await applyManagedPage({ readAdapter, writeAdapter, action, patch });
      pageResults[action.target.canvasPageId] = { ...result, templateOnly: false };
      executionJournal.push({ actionId: action.actionId, kind: action.kind, status: result.status });
      continue;
    }
    if (action.kind === "doc.project-homepage.ensure") {
      homepageResult = await applyHomepage({ readAdapter, writeAdapter, action, preview });
      executionJournal.push({ actionId: action.actionId, kind: action.kind, status: homepageResult.status });
      continue;
    }
    throw new Error(`Continuous Feishu sync contains unsupported action kind: ${action.kind}`);
  }
  const now = new Date().toISOString();
  for (const [canvasPageId, result] of Object.entries(pageResults)) {
    const page = registry.pages[canvasPageId];
    registry = upsertFeishuPageBinding(registry, {
      ...page,
      projectId: registry.project.projectId,
      docRevision: String(result.document.revision_id),
      noteTemplateVersion: FEISHU_PAGE_NOTE_TEMPLATE_VERSION,
      managedContentVersion: FEISHU_PAGE_MANAGED_CONTENT_VERSION,
      updatedAt: now,
    });
    const action = preview.syncPlan.actions.find((candidate) => (
      candidate.kind === "doc.module-index.sync"
      && candidate.target?.canvasPageId === canvasPageId
    ));
    if (action) {
      registry = markFeishuPageContentSynced(registry, {
        projectId: registry.project.projectId,
        canvasPageId,
        noteTemplateVersion: FEISHU_PAGE_NOTE_TEMPLATE_VERSION,
        managedContentVersion: FEISHU_PAGE_MANAGED_CONTENT_VERSION,
        syncedContentDigest: action.desiredContentDigest,
        updatedAt: now,
      });
    }
  }
  if (homepageResult) {
    registry = markFeishuProjectHomepageSynced(registry, {
      projectId: registry.project.projectId,
      indexDigest: homepageResult.indexDigest,
      updatedAt: now,
    });
  }
  const saved = await (options.saveRegistry ?? saveFeishuLearningRegistry)(input, registry);
  return {
    ok: true,
    schemaVersion: FEISHU_CONFIRMED_SYNC_RESULT_SCHEMA,
    planFingerprint: preview.syncPlan.planFingerprint,
    expectedDocumentRevisions: preview.expectedDocumentRevisions,
    executionJournal,
    registryPath: saved.path,
    registry: saved.registry,
    remoteWritesPerformed: executionJournal.some((entry) => entry.status === "updated"),
    localWritesPerformed: true,
  };
}
