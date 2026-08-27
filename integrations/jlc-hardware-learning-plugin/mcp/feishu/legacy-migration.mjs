import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { resolveHardwareLearningPaths } from "../lib/canvas-storage.mjs";
import {
  buildFeishuLearningDirectoryPlan,
  createFeishuLearningRegistry,
  linkFeishuDialogue,
  upsertFeishuFrameNote,
  upsertFeishuPageBinding,
} from "./note-model.mjs";
import { planFeishuLearningSync } from "./sync-plan.mjs";

export const FEISHU_LEGACY_MIGRATION_PREVIEW_SCHEMA = "jlc.feishu-legacy-migration-preview.v1";

function requiredString(value, field) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${field} is required.`);
  return value.trim();
}

function artifactStem(canvasPageId) {
  const pageId = requiredString(canvasPageId, "canvasPageId");
  if (!pageId.startsWith("page:")) throw new Error("canvasPageId must start with page:.");
  return pageId.replace(/[^A-Za-z0-9._-]+/gu, "--");
}

export function resolveLegacyFeishuLearningFiles(input = {}) {
  const { projectDir } = resolveHardwareLearningPaths(input);
  const stem = artifactStem(input.canvasPageId ?? "page:page");
  return {
    bindingPath: join(
      projectDir,
      ".easyeda-hardware-workbench",
      "learning",
      "lark",
      `${stem}-binding.json`,
    ),
    notePackagePath: join(
      projectDir,
      ".easyeda-hardware-workbench",
      "learning",
      "notes",
      `${stem}-note-package.json`,
    ),
  };
}

export async function readLegacyFeishuLearningArtifacts(input = {}) {
  const files = resolveLegacyFeishuLearningFiles(input);
  const [binding, notePackage] = await Promise.all([
    readFile(files.bindingPath, "utf8").then(JSON.parse),
    readFile(files.notePackagePath, "utf8").then(JSON.parse),
  ]);
  return { files, binding, notePackage };
}

function uniqueProjectUuid(notePackage) {
  const values = new Set(
    (notePackage.sourceImages ?? [])
      .map((image) => image?.easyedaIdentity?.projectUuid)
      .filter(Boolean),
  );
  if (values.size !== 1) {
    throw new Error("Legacy note package must contain one unambiguous EasyEDA project UUID.");
  }
  return [...values][0];
}

export function inferLegacySchematicPageIdentity(notePackage, expectedProjectId) {
  if (notePackage?.schemaVersion !== "learning.note-package.v1") {
    throw new Error("Legacy note package must use learning.note-package.v1.");
  }
  const images = new Map((notePackage.sourceImages ?? []).map((image) => [image.shapeId, image]));
  const documentUuids = new Set();
  for (const frame of notePackage.frames ?? []) {
    if (!Array.isArray(frame.sourceImageIds) || frame.sourceImageIds.length === 0) {
      throw new Error(`Learning frame ${frame.frameNumber} has no source-image identity.`);
    }
    for (const imageId of frame.sourceImageIds) {
      const image = images.get(imageId);
      const identity = image?.easyedaIdentity;
      if (
        image?.evidenceSource !== "official-easyeda-export"
        || identity?.documentType !== 1
        || !identity?.projectUuid
        || !identity?.documentUuid
      ) {
        throw new Error(`Learning frame ${frame.frameNumber} has unverified schematic evidence.`);
      }
      if (expectedProjectId && identity.projectUuid !== expectedProjectId) {
        throw new Error("Learning-frame schematic evidence belongs to another EasyEDA project.");
      }
      documentUuids.add(identity.documentUuid);
    }
  }
  if (documentUuids.size !== 1) {
    throw new Error("Learning frames must resolve to one unambiguous EasyEDA schematic page UUID.");
  }
  return {
    projectUuid: expectedProjectId ?? uniqueProjectUuid(notePackage),
    schematicPageUuid: [...documentUuids][0],
    evidence: "all-learning-frames-link-one-official-schematic-page",
  };
}

function nativePageName(image) {
  const fileName = image?.easyedaIdentity?.nativeBundleEntryName ?? image?.altText ?? "";
  const match = /_\d+-([^_]+)_\d{4}-\d{2}-\d{2}(?:\.[A-Za-z0-9]+)?/u.exec(fileName);
  return match?.[1]?.trim() || null;
}

function inferLearningPageName(notePackage) {
  const images = new Map((notePackage.sourceImages ?? []).map((image) => [image.shapeId, image]));
  const linkedNames = new Set();
  for (const frame of notePackage.frames ?? []) {
    for (const imageId of frame.sourceImageIds ?? []) {
      const pageName = nativePageName(images.get(imageId));
      if (pageName) linkedNames.add(pageName);
    }
  }
  if (linkedNames.size === 1) {
    return { pageName: [...linkedNames][0], evidence: "all-learning-frames-link-one-native-page" };
  }
  return {
    pageName: requiredString(notePackage?.page?.name, "notePackage.page.name"),
    evidence: linkedNames.size > 1 ? "frames-link-multiple-native-pages" : "legacy-page-name",
  };
}

function boardByRole(inspection, role) {
  return (inspection.whiteboards ?? []).find((board) => board.role === role) ?? null;
}

function sha256(value) {
  return createHash("sha256").update(String(value)).digest("hex");
}

function validateSources({ binding, notePackage, inspection, projectId, canvasPageId }) {
  if (binding?.schemaVersion !== "learning.lark-binding.v1") {
    throw new Error("Legacy binding must use learning.lark-binding.v1.");
  }
  if (notePackage?.schemaVersion !== "learning.note-package.v1") {
    throw new Error("Legacy note package must use learning.note-package.v1.");
  }
  const notePackagePageId = notePackage.page?.canvasPageId ?? notePackage.page?.cowartPageId;
  if (binding.cowartPageId !== canvasPageId || notePackagePageId !== canvasPageId) {
    throw new Error("Legacy binding, note package, and requested canvas page do not match.");
  }
  if (binding.source?.contentSha256 !== notePackage.contentSha256) {
    throw new Error("Legacy binding and note package content digests do not match.");
  }
  if (uniqueProjectUuid(notePackage) !== projectId) {
    throw new Error("Legacy note package belongs to another EasyEDA project.");
  }
  if (inspection?.remoteWritesPerformed !== false || inspection?.identity !== "user") {
    throw new Error("Migration requires a read-only Feishu inspection using user identity.");
  }
  if (inspection.document?.docToken !== binding.document?.documentId) {
    throw new Error("Live Feishu document does not match the legacy binding.");
  }
  const learningBoard = boardByRole(inspection, "learning-board");
  const moduleIndexBoard = boardByRole(inspection, "module-index-board");
  if (learningBoard?.token !== binding.whiteboard?.token) {
    throw new Error("Live learning-board token does not match the legacy binding.");
  }
  if (moduleIndexBoard?.token !== binding.moduleIndexBoard?.token) {
    throw new Error("Live module-index-board token does not match the legacy binding.");
  }
  return { learningBoard, moduleIndexBoard };
}

export function previewLegacyFeishuLearningMigration(input = {}) {
  const binding = input.binding;
  const notePackage = input.notePackage;
  const inspection = input.inspection;
  const canvasPageId = input.canvasPageId
    ?? notePackage?.page?.canvasPageId
    ?? notePackage?.page?.cowartPageId;
  const projectId = input.projectId ?? input.projectUuid ?? uniqueProjectUuid(notePackage);
  const projectName = requiredString(input.projectName, "projectName");
  const boards = validateSources({
    binding,
    notePackage,
    inspection,
    projectId,
    canvasPageId,
  });
  const pageIdentity = inferLearningPageName(notePackage);
  const schematicIdentity = inferLegacySchematicPageIdentity(notePackage, projectId);
  let registry = createFeishuLearningRegistry({
    projectId,
    projectUuid: projectId,
    projectName,
  }, { updatedAt: binding.lastPublishedAt ?? notePackage.generatedAt });
  registry = upsertFeishuPageBinding(registry, {
    projectId,
    canvasPageId,
    schematicPageUuid: schematicIdentity.schematicPageUuid,
    pageName: pageIdentity.pageName,
    sourceRevision: notePackage.canvasSnapshot?.sha256 ?? notePackage.contentSha256,
    documentLocation: "drive",
    docToken: binding.document.documentId,
    docUrl: binding.document.url,
    docRevision: String(inspection.document.revisionId),
    whiteboardToken: boards.learningBoard.token,
    moduleIndexWhiteboardToken: boards.moduleIndexBoard.token,
    legacyContentDigest: notePackage.contentSha256,
    learningFrameMarkerStyle: binding.whiteboard?.markerStyle
      ?? notePackage.larkPlan?.whiteboard?.learningFrameMarkerStyle,
    updatedAt: binding.lastPublishedAt ?? notePackage.generatedAt,
  });
  const moduleBlocks = new Map(
    (inspection.moduleHeadings ?? []).map((heading) => [heading.frameNumber, heading.blockId]),
  );
  for (const frame of notePackage.frames ?? []) {
    registry = upsertFeishuFrameNote(registry, {
      projectId,
      canvasPageId,
      frameNumber: frame.frameNumber,
      title: frame.title,
      status: (frame.dialogueTurnIds ?? []).length > 0 ? "learning" : "unstarted",
      docBlockId: moduleBlocks.get(frame.frameNumber),
      updatedAt: binding.lastPublishedAt ?? notePackage.generatedAt,
    });
  }
  for (const turn of notePackage.dialogue?.turns ?? []) {
    const frameNumbers = [...new Set(
      (turn.frameLinks ?? []).map((link) => Number(link.frameNumber)).filter(Number.isSafeInteger),
    )];
    if (!turn.questionId || frameNumbers.length === 0) continue;
    registry = linkFeishuDialogue(registry, {
      projectId,
      canvasPageId,
      questionId: turn.questionId,
      frameNumbers,
      answerDigest: turn.assistantResponse ? sha256(turn.assistantResponse) : undefined,
      status: turn.assistantResponse ? "concluded" : "question-open",
      linkedAt: turn.savedAt ?? notePackage.generatedAt,
    });
  }
  registry.migrations = {
    legacyLearningNote: {
      schemaVersion: binding.schemaVersion,
      sourceBindingId: binding.bindingId ?? null,
      inspectedRevisionId: inspection.document.revisionId,
      previousVerifiedRevisionId: binding.document.verifiedRevisionId ?? null,
      sourceContentDigest: notePackage.contentSha256,
      mainBoardToken: boards.learningBoard.token,
      moduleIndexBoardToken: boards.moduleIndexBoard.token,
      pageNameEvidence: pageIdentity.evidence,
      schematicPageIdentityEvidence: schematicIdentity.evidence,
      legacyBrandingTerms: [...(inspection.legacyBrandingTerms ?? [])],
    },
  };
  const directoryPlan = buildFeishuLearningDirectoryPlan({
    project: registry.project,
    schematicPages: [{
      canvasPageId,
      schematicPageUuid: registry.pages[canvasPageId].schematicPageUuid,
      pageName: pageIdentity.pageName,
      sourceRevision: registry.pages[canvasPageId].sourceRevision,
    }],
  });
  const syncPlan = planFeishuLearningSync({ directoryPlan, registry });
  return {
    ok: true,
    schemaVersion: FEISHU_LEGACY_MIGRATION_PREVIEW_SCHEMA,
    mode: "PREVIEW_ONLY_NO_LOCAL_OR_REMOTE_WRITE",
    project: registry.project,
    reused: {
      document: {
        docToken: binding.document.documentId,
        revisionId: inspection.document.revisionId,
      },
      learningBoard: boards.learningBoard,
      moduleIndexBoard: boards.moduleIndexBoard,
    },
    registry,
    directoryPlan,
    syncPlan,
    remoteWritesPerformed: false,
    localWritesPerformed: false,
  };
}

export async function previewLegacyFeishuLearningMigrationFromProject(input = {}, options = {}) {
  const artifacts = await readLegacyFeishuLearningArtifacts(input);
  const inspection = options.inspection ?? input.inspection;
  return {
    ...(previewLegacyFeishuLearningMigration({
      ...input,
      ...artifacts,
      canvasPageId: input.canvasPageId
        ?? artifacts.notePackage.page.canvasPageId
        ?? artifacts.notePackage.page.cowartPageId,
      inspection,
    })),
    sourceFiles: artifacts.files,
  };
}
