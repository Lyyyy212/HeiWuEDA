import {
  bindFeishuProjectNode,
  bindFeishuProjectOverviewBoard,
  bindFeishuLearningRoot,
  bindFeishuSectionNode,
  buildFeishuLearningDirectoryPlan,
  createFeishuLearningRegistry,
  linkFeishuDialogue,
  markFeishuProjectHomepageSynced,
  markFeishuPageContentSynced,
  normalizeFeishuProjectIdentity,
  upsertFeishuFrameNote,
  upsertFeishuPageBinding,
} from "./note-model.mjs";
import { planFeishuLearningSync } from "./sync-plan.mjs";
import { readFeishuLearningRegistry, saveFeishuLearningRegistry } from "./storage.mjs";
import { inspectFeishuLearningDocument } from "./document-inspection.mjs";
import {
  inferLegacySchematicPageIdentity,
  previewLegacyFeishuLearningMigrationFromProject,
  readLegacyFeishuLearningArtifacts,
} from "./legacy-migration.mjs";
import { executeConfirmedFeishuLearningNoteMigration } from "./confirmed-migration.mjs";
import { readFeishuLearningDialogueRecord } from "./dialogue-records.mjs";
import {
  executeConfirmedFeishuLearningNoteSync,
  previewFeishuLearningSyncFromState,
} from "./confirmed-sync.mjs";

function projectFromArgs(args = {}) {
  return normalizeFeishuProjectIdentity({
    projectId: args.projectId ?? args.projectUuid,
    projectUuid: args.projectUuid,
    projectName: args.projectName,
  });
}
function pagesFromRegistry(registry) {
  return Object.values(registry.pages).map((page) => ({
    canvasPageId: page.canvasPageId,
    schematicPageUuid: page.schematicPageUuid,
    pageName: page.pageName,
    sourceRevision: page.sourceRevision,
  }));
}

export async function getFeishuLearningNoteState(args = {}) {
  const stored = await readFeishuLearningRegistry(args);
  const project = stored.registry?.project ?? projectFromArgs(args);
  const registry = stored.registry ?? createFeishuLearningRegistry(project, {
    projectOverviewWhiteboardToken: args.projectOverviewWhiteboardToken,
    updatedAt: args.updatedAt,
  });
  const schematicPages = Array.isArray(args.schematicPages)
    ? args.schematicPages
    : pagesFromRegistry(registry);
  const directoryPlan = buildFeishuLearningDirectoryPlan({
    project,
    schematicPages,
    existingProjects: args.existingProjects ?? [],
  });
  return {
    ok: true,
    registryExists: stored.exists,
    registryPath: stored.path,
    registry,
    directoryPlan,
    syncPlan: planFeishuLearningSync({ directoryPlan, registry }),
  };
}

export async function updateFeishuLearningNoteState(args = {}) {
  const action = String(args.action ?? "");
  const payload = args.payload && typeof args.payload === "object" ? args.payload : {};
  const stored = await readFeishuLearningRegistry(args);
  let registry = stored.registry;
  let replayed = false;

  if (action === "initialize") {
    const project = projectFromArgs(payload);
    if (registry) {
      if (registry.project.projectId !== project.projectId) {
        throw new Error("Existing Feishu note registry belongs to another project.");
      }
      replayed = true;
    } else {
      registry = createFeishuLearningRegistry(project, {
        spaceId: payload.spaceId,
        learningRootNodeToken: payload.learningRootNodeToken,
        learningRootDocToken: payload.learningRootDocToken,
        projectNodeToken: payload.projectNodeToken,
        projectDocToken: payload.projectDocToken,
        projectOverviewWhiteboardToken: payload.projectOverviewWhiteboardToken,
        updatedAt: payload.updatedAt,
      });
      for (const page of payload.schematicPages ?? []) {
        registry = upsertFeishuPageBinding(registry, {
          ...page,
          projectId: project.projectId,
        });
      }
    }
  } else {
    if (!registry) throw new Error("Initialize the Feishu learning note registry first.");
    const projectId = registry.project.projectId;
    const operation = { ...payload, projectId };
    if (action === "bind-root") registry = bindFeishuLearningRoot(registry, operation);
    else if (action === "bind-project") registry = bindFeishuProjectNode(registry, operation);
    else if (action === "bind-project-overview-board") {
      registry = bindFeishuProjectOverviewBoard(registry, operation);
    }
    else if (action === "bind-section") registry = bindFeishuSectionNode(registry, operation);
    else if (action === "bind-page") registry = upsertFeishuPageBinding(registry, operation);
    else if (action === "upsert-frame") registry = upsertFeishuFrameNote(registry, operation);
    else if (action === "link-dialogue") registry = linkFeishuDialogue(registry, operation);
    else if (action === "mark-project-homepage-synced") {
      registry = markFeishuProjectHomepageSynced(registry, operation);
    }
    else if (action === "mark-page-synced") registry = markFeishuPageContentSynced(registry, operation);
    else throw new Error(`Unsupported Feishu learning note state action: ${action}`);
  }

  const saved = await saveFeishuLearningRegistry(args, registry);
  return {
    ok: true,
    action,
    replayed,
    registryPath: saved.path,
    registry: saved.registry,
  };
}

export async function inspectFeishuLearningNoteTarget(args = {}, options = {}) {
  return inspectFeishuLearningDocument({ document: args.document }, options);
}

export async function previewFeishuLearningNoteMigration(args = {}, options = {}) {
  const inspection = await inspectFeishuLearningNoteTarget(args, options);
  return previewLegacyFeishuLearningMigrationFromProject(
    { ...args, inspection },
    { inspection },
  );
}

export async function executeFeishuLearningNoteMigration(args = {}, options = {}) {
  return executeConfirmedFeishuLearningNoteMigration(args, options);
}

export async function linkFeishuLearningDialogueFromRecord(args = {}) {
  const stored = await readFeishuLearningRegistry(args);
  if (!stored.registry) throw new Error("Initialize or migrate the Feishu learning-note registry first.");
  const record = await readFeishuLearningDialogueRecord(args, {
    questionId: args.questionId,
    canvasPageId: args.canvasPageId,
  });
  const page = stored.registry.pages[record.canvasPageId];
  if (!page) throw new Error(`Feishu page binding not found: ${record.canvasPageId}`);
  for (const frameNumber of record.frameNumbers) {
    if (!page.frames?.[String(frameNumber)]) {
      throw new Error(`Learning dialogue references a frame not present on the bound page: ${frameNumber}`);
    }
  }
  const replayed = Boolean(stored.registry.dialogues[record.questionId]);
  const registry = linkFeishuDialogue(stored.registry, {
    projectId: stored.registry.project.projectId,
    canvasPageId: record.canvasPageId,
    questionId: record.questionId,
    frameNumbers: record.frameNumbers,
    questionDigest: record.questionDigest,
    answerDigest: record.answerDigest,
    linkedAt: record.completedAt,
  });
  const saved = await saveFeishuLearningRegistry(args, registry);
  return {
    ok: true,
    replayed,
    registryPath: saved.path,
    registry: saved.registry,
    dialogue: saved.registry.dialogues[record.questionId],
    record: {
      questionId: record.questionId,
      canvasPageId: record.canvasPageId,
      frameNumbers: record.frameNumbers,
      questionDigest: record.questionDigest,
      answerDigest: record.answerDigest,
      questionText: record.questionText,
    },
    remoteWritesPerformed: false,
  };
}

export async function bindFeishuPageIdentityFromLearningEvidence(args = {}) {
  const stored = await readFeishuLearningRegistry(args);
  if (!stored.registry) throw new Error("Initialize or migrate the Feishu learning-note registry first.");
  const canvasPageId = String(args.canvasPageId ?? "").trim();
  const page = stored.registry.pages[canvasPageId];
  if (!page) throw new Error(`Feishu page binding not found: ${canvasPageId}`);
  const { notePackage, files } = await readLegacyFeishuLearningArtifacts({
    ...args,
    canvasPageId,
  });
  const packagePageId = notePackage.page?.canvasPageId ?? notePackage.page?.cowartPageId;
  if (packagePageId !== canvasPageId) {
    throw new Error("Learning note package belongs to another canvas page.");
  }
  const identity = inferLegacySchematicPageIdentity(
    notePackage,
    stored.registry.project.projectId,
  );
  const packageFrames = [...new Set((notePackage.frames ?? []).map((frame) => frame.frameNumber))]
    .sort((left, right) => left - right);
  const registryFrames = Object.values(page.frames ?? {}).map((frame) => frame.frameNumber)
    .sort((left, right) => left - right);
  if (JSON.stringify(packageFrames) !== JSON.stringify(registryFrames)) {
    throw new Error("Learning note package frame set differs from the Feishu page binding.");
  }
  const replayed = page.schematicPageUuid === identity.schematicPageUuid;
  const registry = upsertFeishuPageBinding(stored.registry, {
    ...page,
    projectId: stored.registry.project.projectId,
    schematicPageUuid: identity.schematicPageUuid,
    updatedAt: new Date().toISOString(),
  });
  const saved = await saveFeishuLearningRegistry(args, registry);
  return {
    ok: true,
    replayed,
    registryPath: saved.path,
    registry: saved.registry,
    binding: {
      canvasPageId,
      projectUuid: identity.projectUuid,
      schematicPageUuid: identity.schematicPageUuid,
      evidence: identity.evidence,
      notePackagePath: files.notePackagePath,
    },
    remoteWritesPerformed: false,
  };
}

export async function previewFeishuLearningNoteSync(args = {}, options = {}) {
  const state = await getFeishuLearningNoteState(args);
  return previewFeishuLearningSyncFromState(args, state, options);
}

export async function executeFeishuLearningNoteSync(args = {}, options = {}) {
  const preview = await previewFeishuLearningNoteSync(args, options);
  return executeConfirmedFeishuLearningNoteSync(args, preview, options);
}
