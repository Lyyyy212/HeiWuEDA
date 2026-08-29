import {
  FEISHU_PAGE_NOTE_TEMPLATE_VERSION,
  bindFeishuLearningRoot,
  bindFeishuProjectNode,
  markFeishuProjectHomepageSynced,
  upsertFeishuPageBinding,
} from "./note-model.mjs";
import {
  createConfirmedLarkCliWriteAdapter,
  createLarkCliAdapter,
} from "./lark-cli-adapter.mjs";
import { inspectFeishuLearningDocument } from "./document-inspection.mjs";
import { previewLegacyFeishuLearningMigrationFromProject } from "./legacy-migration.mjs";
import {
  inspectFeishuProjectHomepage,
  renderFeishuProjectHomepageAppendXml,
} from "./project-homepage.mjs";
import { saveFeishuLearningRegistry } from "./storage.mjs";

export const FEISHU_CONFIRMED_MIGRATION_RESULT_SCHEMA =
  "jlc.feishu-confirmed-migration-result.v1";

function requiredString(value, field) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${field} is required.`);
  return value.trim();
}

export function renderFeishuPageIdentitySummary({ project, page } = {}) {
  const projectName = requiredString(project?.projectName, "project.projectName");
  const pageName = requiredString(page?.pageName, "page.pageName");
  return `项目：${projectName}；图页：${pageName}`;
}

function payloadData(payload) {
  return payload?.data?.node ?? payload?.data?.space ?? payload?.data ?? payload;
}

function normalizeWikiNode(payload, label) {
  const data = payloadData(payload);
  const nodeToken = data?.node_token ?? data?.wiki_token;
  const docToken = data?.obj_token;
  if (!nodeToken) throw new Error(`${label} response is missing node_token.`);
  return {
    spaceId: String(data.space_id ?? data.resolved_space_id ?? ""),
    nodeToken: String(nodeToken),
    docToken: docToken ? String(docToken) : null,
    parentNodeToken: data.parent_node_token ? String(data.parent_node_token) : null,
    title: data.title ? String(data.title) : null,
    objType: data.obj_type ? String(data.obj_type) : null,
    hasChild: data.has_child === true,
  };
}

function nodesFromList(payload) {
  const nodes = payload?.data?.nodes;
  if (!Array.isArray(nodes)) throw new Error("Wiki node list response is missing data.nodes.");
  return nodes;
}

function documentFromPayload(payload) {
  const document = payload?.data?.document;
  if (!document || typeof document.content !== "string") {
    throw new Error("Feishu document response is missing data.document.content.");
  }
  return document;
}

async function findExactChild(readAdapter, { spaceId, parentNodeToken, title }) {
  const payload = await readAdapter.listWikiNodes({ spaceId, parentNodeToken });
  const matches = nodesFromList(payload).filter((node) => node.title === title);
  if (matches.length > 1) {
    throw new Error(`Ambiguous Wiki target: ${title} has ${matches.length} exact-name nodes.`);
  }
  return matches[0] ?? null;
}

async function verifyWikiNode(readAdapter, nodeToken, expected = {}) {
  const payload = await readAdapter.getWikiNode({ nodeToken });
  const node = normalizeWikiNode(payload, "Wiki node verification");
  if (expected.title && node.title !== expected.title) {
    throw new Error(`Wiki node title mismatch: expected ${expected.title}, received ${node.title}.`);
  }
  if (expected.parentNodeToken && node.parentNodeToken !== expected.parentNodeToken) {
    throw new Error(`Wiki node parent mismatch for ${expected.title ?? node.nodeToken}.`);
  }
  if (expected.docToken && node.docToken !== expected.docToken) {
    throw new Error(`Wiki node document mismatch for ${expected.title ?? node.nodeToken}.`);
  }
  return node;
}

async function ensureWikiNode({
  readAdapter,
  writeAdapter,
  action,
  spaceId,
  parentNodeToken,
}) {
  const existing = await findExactChild(readAdapter, {
    spaceId,
    parentNodeToken,
    title: action.title,
  });
  if (existing) {
    const node = await verifyWikiNode(readAdapter, existing.node_token, {
      title: action.title,
      parentNodeToken,
    });
    return { status: "reused", node };
  }
  const created = await writeAdapter.createWikiNode({
    actionId: action.actionId,
    spaceId,
    parentNodeToken,
  });
  const candidate = normalizeWikiNode(created.payload, "Wiki node create");
  const node = await verifyWikiNode(readAdapter, candidate.nodeToken, {
    title: action.title,
    parentNodeToken,
  });
  return { status: "created", node };
}

async function resolveCompletedMove(writeAdapter, actionId, firstPayload) {
  let payload = firstPayload;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const data = payloadData(payload);
    if (data?.ready === true || data?.node_token || data?.wiki_token) return payload;
    if (data?.applied === true && !data?.task_id) {
      throw new Error("Wiki move was submitted for approval and is not complete.");
    }
    if (!data?.task_id) throw new Error("Wiki move response is not complete and has no task_id.");
    payload = (await writeAdapter.continueWikiMove({
      actionId,
      taskId: String(data.task_id),
    })).payload;
  }
  throw new Error("Wiki move did not finish after three bounded continuation checks.");
}

async function applyDocumentTemplate({
  readAdapter,
  writeAdapter,
  action,
  document,
  project,
  page,
}) {
  const replacements = [
    {
      pattern: "Cowart 图页",
      content: "JLC 硬件学习图页",
    },
    {
      pattern: "Page 1（page:page）",
      content: renderFeishuPageIdentitySummary({ project, page }),
    },
    {
      pattern: "同步方向为 Cowart → 飞书",
      content: "同步方向为 JLC 硬件学习画板 → 飞书",
    },
  ];
  const writes = [];
  for (const replacement of replacements) {
    const before = documentFromPayload(await readAdapter.fetchDocumentFull(document));
    if (!before.content.includes(replacement.pattern)) {
      writes.push({ ...replacement, status: "already-satisfied", revisionId: before.revision_id });
      continue;
    }
    const result = await writeAdapter.replaceDocumentText({
      actionId: action.actionId,
      document,
      revisionId: before.revision_id,
      pattern: replacement.pattern,
      content: replacement.content,
    });
    const after = documentFromPayload(await readAdapter.fetchDocumentFull(document));
    if (after.content.includes(replacement.pattern) || !after.content.includes(replacement.content)) {
      throw new Error(`Document replacement verification failed for ${replacement.pattern}.`);
    }
    writes.push({
      ...replacement,
      status: "updated",
      revisionId: after.revision_id,
      result: payloadData(result.payload)?.result ?? null,
    });
  }
  return writes;
}

async function applyProjectHomepage({
  readAdapter,
  writeAdapter,
  action,
  document,
  project,
  pages,
  projectOverviewWhiteboardToken,
}) {
  const before = documentFromPayload(await readAdapter.fetchDocumentFull(document));
  const rendered = renderFeishuProjectHomepageAppendXml({
    project,
    pages,
    projectOverviewWhiteboardToken,
    existingContent: before.content,
  });
  if (rendered.indexDigest !== action.desiredContentDigest) {
    throw new Error("Project homepage index digest no longer matches the confirmed action.");
  }
  let status = "reused";
  if (rendered.xml) {
    await writeAdapter.appendDocumentXml({
      actionId: action.actionId,
      document,
      revisionId: before.revision_id,
      content: rendered.xml,
    });
    status = "updated";
  }
  const after = documentFromPayload(await readAdapter.fetchDocumentFull(document));
  const inspection = inspectFeishuProjectHomepage(after.content, {
    pages,
    projectOverviewWhiteboardToken,
  });
  if (
    inspection.missingSectionKeys.length > 0
    || inspection.missingPageDocTokens.length > 0
    || inspection.missingProjectOverviewWhiteboardToken
  ) {
    throw new Error("Project homepage verification failed after compact-index update.");
  }
  return {
    status,
    revisionId: after.revision_id,
    indexDigest: rendered.indexDigest,
    updatedBlocks: rendered.xml ? true : false,
  };
}

function verifyDocumentAgainstRegistry(inspection, preview) {
  if (inspection.requiredSections.missing.length > 0) {
    throw new Error(`Feishu note is missing sections: ${inspection.requiredSections.missing.join(", ")}`);
  }
  if (inspection.legacyBrandingTerms.length > 0) {
    throw new Error(`Legacy branding remains in Feishu note: ${inspection.legacyBrandingTerms.join(", ")}`);
  }
  const expectedFrames = Object.keys(preview.registry.pages[preview.registryPageId]?.frames ?? {})
    .map(Number)
    .sort((left, right) => left - right);
  const actualFrames = inspection.moduleHeadings
    .map((heading) => heading.frameNumber)
    .sort((left, right) => left - right);
  if (JSON.stringify(expectedFrames) !== JSON.stringify(actualFrames)) {
    throw new Error(`Module index mismatch: expected ${expectedFrames}, received ${actualFrames}.`);
  }
  for (const expected of [preview.reused.learningBoard, preview.reused.moduleIndexBoard]) {
    const live = inspection.whiteboards.find((board) => board.role === expected.role);
    if (!live || live.token !== expected.token) {
      throw new Error(`Feishu ${expected.role} token changed during migration.`);
    }
  }
}

export async function executeConfirmedFeishuLearningNoteMigration(input = {}, options = {}) {
  const document = requiredString(input.document, "document");
  const initialInspection = options.inspection ?? await inspectFeishuLearningDocument(
    { document },
    { adapter: options.readAdapter },
  );
  const preview = options.preview ?? await previewLegacyFeishuLearningMigrationFromProject(
    { ...input, inspection: initialInspection },
    { inspection: initialInspection },
  );
  const expectedRevisionId = Number(input.expectedDocumentRevisionId);
  if (preview.reused.document.revisionId !== expectedRevisionId) {
    throw new Error(
      `Feishu document revision changed: expected ${expectedRevisionId}, received ${preview.reused.document.revisionId}.`,
    );
  }
  if (preview.syncPlan.planFingerprint !== input.planFingerprint) {
    throw new Error("Fresh Feishu migration preview no longer matches the confirmed plan fingerprint.");
  }
  if (preview.syncPlan.actions.some((action) => (
    action.kind === "doc.project-overview-whiteboard.ensure"
  ))) {
    throw new Error(
      "Create and verify the project overview whiteboard containing every schematic page, bind its token, then re-preview the migration.",
    );
  }

  const readAdapter = options.readAdapter ?? createLarkCliAdapter(options);
  const writeAdapter = options.writeAdapter ?? createConfirmedLarkCliWriteAdapter({
    ...options,
    timeoutMs: options.timeoutMs ?? 90_000,
    plan: preview.syncPlan,
    confirmation: {
      confirmed: input.confirmed === true,
      planFingerprint: input.planFingerprint,
      expectedDocumentRevisionId: expectedRevisionId,
    },
  });
  const spacePayload = await readAdapter.getPersonalWikiSpace();
  const spaceId = String(payloadData(spacePayload)?.space_id ?? "");
  if (!/^\d+$/u.test(spaceId)) throw new Error("Could not resolve the personal Wiki space ID.");

  const bindings = new Map();
  const executionJournal = [];
  let movedPageNode = null;
  let templateWrites = [];
  let homepageWrite = null;
  if (preview.registry.wiki.learningRootNodeToken) {
    const node = await verifyWikiNode(readAdapter, preview.registry.wiki.learningRootNodeToken, {
      docToken: preview.registry.wiki.learningRootDocToken,
    });
    bindings.set(preview.directoryPlan.namespace.logicalId, { status: "reused", node });
  }
  if (preview.registry.wiki.projectNodeToken) {
    const node = await verifyWikiNode(readAdapter, preview.registry.wiki.projectNodeToken, {
      parentNodeToken: preview.registry.wiki.learningRootNodeToken,
      docToken: preview.registry.wiki.projectDocToken,
    });
    bindings.set(preview.directoryPlan.root.logicalId, { status: "reused", node });
  }
  const pageLogicalIds = new Set(preview.directoryPlan.root.children.map((page) => page.logicalId));
  for (const action of preview.syncPlan.actions) {
    if (action.kind === "wiki.node.ensure") {
      const parentNodeToken = action.parentLogicalId
        ? bindings.get(action.parentLogicalId)?.node.nodeToken
        : null;
      if (action.parentLogicalId && !parentNodeToken) {
        throw new Error(`Confirmed parent action has no verified node token: ${action.parentLogicalId}`);
      }
      const result = await ensureWikiNode({
        readAdapter,
        writeAdapter,
        action,
        spaceId,
        parentNodeToken,
      });
      bindings.set(action.logicalId, result);
      if (pageLogicalIds.has(action.logicalId)) movedPageNode = result.node;
      executionJournal.push({ actionId: action.actionId, kind: action.kind, status: result.status });
      continue;
    }
    if (action.kind === "wiki.document.move") {
      const parentNodeToken = bindings.get(action.parentLogicalId)?.node.nodeToken;
      if (!parentNodeToken) throw new Error("Project homepage has no verified Wiki node token.");
      let verified = null;
      let moveStatus = "reused";
      try {
        const existingPayload = await readAdapter.getWikiNode({
          nodeToken: preview.reused.document.docToken,
          objType: "docx",
        });
        const existing = normalizeWikiNode(existingPayload, "Existing Wiki document");
        verified = await verifyWikiNode(readAdapter, existing.nodeToken, {
          parentNodeToken,
          docToken: preview.reused.document.docToken,
        });
      } catch (error) {
        if (!/(?:not in wiki|not mounted|131005|131014)/iu.test(String(error?.message ?? error))) {
          throw error;
        }
      }
      if (!verified) {
        const moved = await writeAdapter.moveDriveDocumentToWiki({
          actionId: action.actionId,
          docToken: preview.reused.document.docToken,
          targetSpaceId: spaceId,
          targetParentNodeToken: parentNodeToken,
        });
        const completedPayload = await resolveCompletedMove(writeAdapter, action.actionId, moved.payload);
        const candidate = normalizeWikiNode(completedPayload, "Wiki document move");
        verified = await verifyWikiNode(readAdapter, candidate.nodeToken, {
          parentNodeToken,
          docToken: preview.reused.document.docToken,
        });
        moveStatus = "moved";
      }
      if (verified.title !== action.title) {
        await writeAdapter.renameMovedWikiDocument({ actionId: action.actionId, nodeToken: verified.nodeToken });
        verified = await verifyWikiNode(readAdapter, verified.nodeToken, {
          title: action.title,
          parentNodeToken,
          docToken: preview.reused.document.docToken,
        });
      }
      movedPageNode = verified;
      bindings.set(action.logicalId, { status: moveStatus, node: verified });
      executionJournal.push({ actionId: action.actionId, kind: action.kind, status: moveStatus });
      continue;
    }
    if (action.kind === "doc.page-template.ensure") {
      const page = preview.registry.pages[input.canvasPageId ?? "page:page"];
      templateWrites = await applyDocumentTemplate({
        readAdapter,
        writeAdapter,
        action,
        document,
        project: preview.project,
        page,
      });
      executionJournal.push({
        actionId: action.actionId,
        kind: action.kind,
        status: templateWrites.some((entry) => entry.status === "updated") ? "updated" : "reused",
      });
      continue;
    }
    if (action.kind === "doc.module-index.sync") {
      executionJournal.push({ actionId: action.actionId, kind: action.kind, status: "verified-no-op" });
      continue;
    }
    if (action.kind === "doc.project-homepage.ensure") {
      const projectNode = bindings.get(preview.directoryPlan.root.logicalId)?.node;
      if (!projectNode?.docToken) throw new Error("Project homepage has no verified Docx token.");
      const pages = preview.directoryPlan.root.children.map((pageNode) => {
        const liveNode = bindings.get(pageNode.logicalId)?.node;
        const registryPage = preview.registry.pages[pageNode.page.canvasPageId];
        return {
          canvasPageId: pageNode.page.canvasPageId,
          title: pageNode.title,
          docToken: liveNode?.docToken ?? registryPage?.docToken ?? null,
        };
      });
      homepageWrite = await applyProjectHomepage({
        readAdapter,
        writeAdapter,
        action,
        document: projectNode.docToken,
        project: preview.registry.project,
        pages,
        projectOverviewWhiteboardToken: preview.registry.wiki.projectOverviewWhiteboardToken,
      });
      executionJournal.push({
        actionId: action.actionId,
        kind: action.kind,
        status: homepageWrite.status,
      });
      continue;
    }
    throw new Error(`Confirmed migration contains unsupported action kind: ${action.kind}`);
  }
  if (!movedPageNode) throw new Error("Confirmed migration did not produce a Wiki page binding.");

  const finalInspection = await inspectFeishuLearningDocument(
    { document },
    { adapter: readAdapter },
  );
  const registryPageId = input.canvasPageId ?? "page:page";
  verifyDocumentAgainstRegistry(finalInspection, { ...preview, registryPageId });

  let registry = preview.registry;
  const rootBinding = bindings.get(preview.directoryPlan.namespace.logicalId)?.node;
  const projectBinding = bindings.get(preview.directoryPlan.root.logicalId)?.node;
  registry = bindFeishuLearningRoot(registry, {
    projectId: registry.project.projectId,
    spaceId,
    learningRootNodeToken: rootBinding.nodeToken,
    learningRootDocToken: rootBinding.docToken,
  });
  registry = bindFeishuProjectNode(registry, {
    projectId: registry.project.projectId,
    spaceId,
    projectNodeToken: projectBinding.nodeToken,
    projectDocToken: projectBinding.docToken,
  });
  const homepageAction = preview.syncPlan.actions.find(
    (action) => action.kind === "doc.project-homepage.ensure",
  );
  if (homepageAction) {
    registry = markFeishuProjectHomepageSynced(registry, {
      projectId: registry.project.projectId,
      indexDigest: homepageWrite?.indexDigest ?? homepageAction.desiredContentDigest,
      updatedAt: new Date().toISOString(),
    });
  }
  const page = registry.pages[registryPageId];
  registry = upsertFeishuPageBinding(registry, {
    ...page,
    projectId: registry.project.projectId,
    nodeToken: movedPageNode.nodeToken,
    docToken: movedPageNode.docToken,
    documentLocation: "wiki",
    docRevision: String(finalInspection.document.revisionId),
    noteTemplateVersion: FEISHU_PAGE_NOTE_TEMPLATE_VERSION,
    updatedAt: new Date().toISOString(),
  });
  // Initial migration preserves the page learning board and any legacy module-index
  // board. New notes use one project overview board plus one board per schematic page.
  // The separate
  // continuous-sync flow adopts the page into managed module/dialogue ranges and
  // only then records the content digest as synchronized.
  const saved = await (options.saveRegistry ?? saveFeishuLearningRegistry)(input, registry);
  return {
    ok: true,
    schemaVersion: FEISHU_CONFIRMED_MIGRATION_RESULT_SCHEMA,
    planFingerprint: preview.syncPlan.planFingerprint,
    initialRevisionId: expectedRevisionId,
    finalRevisionId: finalInspection.document.revisionId,
    spaceId,
    page: movedPageNode,
    boardTokens: {
      projectOverview: preview.registry.wiki.projectOverviewWhiteboardToken,
      schematicPage: preview.reused.learningBoard.token,
      legacyModuleIndex: preview.reused.moduleIndexBoard.token,
    },
    executionJournal,
    templateWrites,
    homepageWrite,
    registryPath: saved.path,
    remoteWritesPerformed: executionJournal.some((entry) => ["created", "moved", "updated"].includes(entry.status)),
    localWritesPerformed: true,
  };
}
