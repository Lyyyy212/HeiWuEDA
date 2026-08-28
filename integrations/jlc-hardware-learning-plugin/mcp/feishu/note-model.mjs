import { createHash } from "node:crypto";

export const FEISHU_NOTE_REGISTRY_SCHEMA = "jlc.feishu-learning-note-registry.v1";
export const FEISHU_DIRECTORY_PLAN_SCHEMA = "jlc.feishu-learning-directory-plan.v1";
export const FEISHU_PAGE_NOTE_TEMPLATE_VERSION = 1;
export const FEISHU_PAGE_MANAGED_CONTENT_VERSION = 1;
export const FEISHU_PROJECT_HOMEPAGE_TEMPLATE_VERSION = 1;
export const FEISHU_NOTE_LAYOUT_MODE = "compact-project-homepage";
export const FEISHU_LEARNING_NOTE_STANDARD_VERSION = "JLC-FN-1.2";

export const DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE = Object.freeze({
  colorOpacityPercent: 50,
  numberOpacityPercent: 50,
  borderWidthScale: 0.5,
  preserveBounds: true,
  frameColorMode: "stable-random-distinct",
  framePalette: Object.freeze([
    Object.freeze({ name: "coral", borderColor: "#e26d5a", numberFillColor: "#fde8e3" }),
    Object.freeze({ name: "blue", borderColor: "#5178c6", numberFillColor: "#f0f4fc" }),
    Object.freeze({ name: "violet", borderColor: "#8569cb", numberFillColor: "#eae2fe" }),
    Object.freeze({ name: "gold", borderColor: "#d4b45b", numberFillColor: "#fef1ce" }),
    Object.freeze({ name: "teal", borderColor: "#2f9294", numberFillColor: "#e0f3f3" }),
    Object.freeze({ name: "green", borderColor: "#5f9e6e", numberFillColor: "#e3f3e7" }),
    Object.freeze({ name: "orange", borderColor: "#d8893a", numberFillColor: "#fcebd8" }),
    Object.freeze({ name: "rose", borderColor: "#c76d98", numberFillColor: "#f8e4ed" }),
  ]),
  numberBadgeStyle: Object.freeze({
    shape: "round_rect",
    width: 29.2544002532959,
    height: 28.414939880371094,
    fontSize: 12,
    anchor: "frame-top-left",
    scaleMode: "fixed-canvas-size",
    offsetX: -8,
    offsetY: -8,
    colorMode: "follow-frame",
  }),
  moduleIndexStyle: Object.freeze({
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
  }),
});

export const FEISHU_NOTE_SECTIONS = Object.freeze([
  { key: "overview", title: "00 项目总览", role: "project-overview" },
  { key: "concept", title: "01 方案设计", role: "concept-design" },
  { key: "modules", title: "02 模块详细设计", role: "module-design" },
  { key: "schematics", title: "03 原理图学习", role: "schematic-learning" },
  { key: "review", title: "04 原理图检查", role: "schematic-review" },
  { key: "bom", title: "05 BOM与器件选型", role: "bom-selection" },
  { key: "experiments", title: "06 调试与实验记录", role: "experiments" },
  { key: "archive", title: "99 历史归档", role: "archive" },
]);

export const FEISHU_FRAME_STATUSES = Object.freeze([
  "unstarted",
  "learning",
  "question-open",
  "concluded",
  "review-required",
]);

const FRAME_STATUS_SET = new Set(FEISHU_FRAME_STATUSES);

function requiredString(value, field, maximum = 240) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${field} is required.`);
  const normalized = value.trim();
  if (normalized.length > maximum) throw new Error(`${field} must be at most ${maximum} characters.`);
  return normalized;
}

function optionalString(value, field, maximum = 500) {
  if (value == null || value === "") return null;
  return requiredString(value, field, maximum);
}

function uniqueStrings(value, field) {
  if (value == null) return [];
  if (!Array.isArray(value)) throw new Error(`${field} must be an array.`);
  return [...new Set(value.map((item) => requiredString(item, field, 500)))];
}

function positiveInteger(value, field) {
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number <= 0) throw new Error(`${field} must be a positive integer.`);
  return number;
}

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function normalizeMarkerStyle(input) {
  const style = input ?? DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE;
  const fallback = DEFAULT_FEISHU_LEARNING_FRAME_MARKER_STYLE;
  const percent = (value, field) => {
    const number = Number(value);
    if (!Number.isInteger(number) || number < 0 || number > 100) {
      throw new Error(`${field} must be an integer from 0 to 100.`);
    }
    return number;
  };
  const positiveNumber = (value, field) => {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) throw new Error(`${field} must be positive.`);
    return number;
  };
  const finiteNumber = (value, field) => {
    const number = Number(value);
    if (!Number.isFinite(number)) throw new Error(`${field} must be finite.`);
    return number;
  };
  const color = (value, field) => {
    const normalized = String(value ?? "").trim().toLowerCase();
    if (!/^#[0-9a-f]{6}$/u.test(normalized)) throw new Error(`${field} must be a six-digit hex color.`);
    return normalized;
  };
  const badge = { ...fallback.numberBadgeStyle, ...style.numberBadgeStyle };
  const moduleIndex = { ...fallback.moduleIndexStyle, ...style.moduleIndexStyle };
  const frameColorMode = style.frameColorMode ?? fallback.frameColorMode;
  if (frameColorMode !== "stable-random-distinct") {
    throw new Error("learningFrameMarkerStyle must use stable random distinct colors.");
  }
  const paletteInput = style.framePalette ?? fallback.framePalette;
  if (!Array.isArray(paletteInput) || paletteInput.length < 2) {
    throw new Error("learningFrameMarkerStyle.framePalette must contain at least two colors.");
  }
  const framePalette = paletteInput.map((entry, index) => ({
    name: requiredString(entry?.name, `framePalette[${index}].name`, 32),
    borderColor: color(entry?.borderColor, `framePalette[${index}].borderColor`),
    numberFillColor: color(entry?.numberFillColor, `framePalette[${index}].numberFillColor`),
  }));
  if (new Set(framePalette.map((entry) => entry.borderColor)).size !== framePalette.length) {
    throw new Error("learningFrameMarkerStyle.framePalette border colors must be distinct.");
  }
  if (style.preserveBounds !== true) throw new Error("learningFrameMarkerStyle must preserve bounds.");
  if (badge.shape !== "round_rect" || badge.anchor !== "frame-top-left") {
    throw new Error("learningFrameMarkerStyle must use the approved round-rect top-left badge.");
  }
  if (badge.colorMode !== "follow-frame") {
    throw new Error("learningFrameMarkerStyle badge color must follow the frame.");
  }
  if (badge.scaleMode !== "fixed-canvas-size") {
    throw new Error("learningFrameMarkerStyle badge size must stay fixed when schematic images are scaled.");
  }
  positiveNumber(badge.width, "numberBadgeStyle.width");
  positiveNumber(badge.height, "numberBadgeStyle.height");
  positiveNumber(badge.fontSize, "numberBadgeStyle.fontSize");
  finiteNumber(badge.offsetX, "numberBadgeStyle.offsetX");
  finiteNumber(badge.offsetY, "numberBadgeStyle.offsetY");
  if (moduleIndex.colorMode !== "follow-learning-frame") {
    throw new Error("module index colors must follow the matching learning frame.");
  }
  if (moduleIndex.frameGeometryMode !== "map-with-schematic-image"
      || moduleIndex.badgeGeometryMode !== "fixed-size-top-left-overlap") {
    throw new Error("module index frames must map with the schematic while badges remain fixed at the frame corner.");
  }
  if (moduleIndex.detailContentMode !== "one-sentence-module-summary") {
    throw new Error("module index detail nodes must contain one-sentence module summaries.");
  }
  if (moduleIndex.borderWidth !== "narrow") {
    throw new Error("module index nodes must use narrow borders.");
  }
  if (moduleIndex.preserveMindMapStructure !== true || moduleIndex.preserveSchematicEvidence !== true) {
    throw new Error("module index styling must preserve mind-map structure and schematic evidence.");
  }
  percent(moduleIndex.labelBorderOpacityPercent, "moduleIndexStyle.labelBorderOpacityPercent");
  percent(moduleIndex.labelFillOpacityPercent, "moduleIndexStyle.labelFillOpacityPercent");
  percent(moduleIndex.detailBorderOpacityPercent, "moduleIndexStyle.detailBorderOpacityPercent");
  const borderWidthScale = positiveNumber(style.borderWidthScale, "borderWidthScale");
  if (borderWidthScale > 1) throw new Error("borderWidthScale must not exceed 1.");
  percent(style.colorOpacityPercent ?? fallback.colorOpacityPercent, "colorOpacityPercent");
  percent(style.numberOpacityPercent ?? fallback.numberOpacityPercent, "numberOpacityPercent");
  return {
    colorOpacityPercent: fallback.colorOpacityPercent,
    numberOpacityPercent: fallback.numberOpacityPercent,
    borderWidthScale,
    preserveBounds: true,
    frameColorMode,
    framePalette,
    numberBadgeStyle: {
      shape: "round_rect",
      width: fallback.numberBadgeStyle.width,
      height: fallback.numberBadgeStyle.height,
      fontSize: fallback.numberBadgeStyle.fontSize,
      anchor: "frame-top-left",
      scaleMode: "fixed-canvas-size",
      offsetX: fallback.numberBadgeStyle.offsetX,
      offsetY: fallback.numberBadgeStyle.offsetY,
      colorMode: "follow-frame",
    },
    moduleIndexStyle: {
      colorMode: "follow-learning-frame",
      frameGeometryMode: "map-with-schematic-image",
      badgeGeometryMode: "fixed-size-top-left-overlap",
      detailContentMode: "one-sentence-module-summary",
      labelBorderOpacityPercent: fallback.moduleIndexStyle.labelBorderOpacityPercent,
      labelFillOpacityPercent: fallback.moduleIndexStyle.labelFillOpacityPercent,
      detailBorderOpacityPercent: fallback.moduleIndexStyle.detailBorderOpacityPercent,
      borderWidth: "narrow",
      preserveMindMapStructure: true,
      preserveSchematicEvidence: true,
    },
  };
}

export function assignFeishuLearningFrameMarkerColors(style, frameNumbers, pageIdentity) {
  const normalized = normalizeMarkerStyle(style);
  if (!Array.isArray(frameNumbers) || frameNumbers.length === 0) {
    throw new Error("frameNumbers must contain at least one learning frame.");
  }
  const numbers = [...new Set(frameNumbers.map((number) => positiveInteger(number, "frameNumbers")))].sort((a, b) => a - b);
  const seed = requiredString(pageIdentity, "pageIdentity", 500);
  const palette = normalized.framePalette
    .map((entry) => ({
      entry,
      score: createHash("sha256").update(`${seed}|${entry.name}`).digest("hex"),
    }))
    .sort((left, right) => left.score.localeCompare(right.score))
    .map(({ entry }) => entry);
  return Object.fromEntries(numbers.map((number, index) => [
    String(number),
    clone(palette[index % palette.length]),
  ]));
}

function shortDigest(value) {
  return createHash("sha256").update(String(value)).digest("hex").slice(0, 8);
}

function timestamp(value) {
  return optionalString(value, "updatedAt", 80) ?? new Date().toISOString();
}

function sha256Json(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

export function normalizeFeishuProjectIdentity(input = {}) {
  const projectId = requiredString(input.projectId ?? input.projectUuid, "projectId");
  const projectName = requiredString(input.projectName, "projectName");
  return {
    projectKey: `project:${shortDigest(projectId)}`,
    projectId,
    projectUuid: optionalString(input.projectUuid, "projectUuid") ?? projectId,
    projectName,
  };
}

export function feishuProjectDisplayTitle(project, existingProjects = []) {
  const normalized = normalizeFeishuProjectIdentity(project);
  const collides = existingProjects.some((item) => {
    const candidate = normalizeFeishuProjectIdentity(item);
    return candidate.projectName === normalized.projectName && candidate.projectId !== normalized.projectId;
  });
  return collides ? `${normalized.projectName}〔${shortDigest(normalized.projectId)}〕` : normalized.projectName;
}

export function normalizeFeishuSchematicPage(input = {}) {
  const canvasPageId = requiredString(input.canvasPageId, "canvasPageId");
  if (!canvasPageId.startsWith("page:")) throw new Error("canvasPageId must start with page:.");
  return {
    pageKey: `canvas-page:${shortDigest(canvasPageId)}`,
    canvasPageId,
    schematicPageUuid: optionalString(input.schematicPageUuid, "schematicPageUuid"),
    pageName: requiredString(input.pageName, "pageName"),
    sourceRevision: optionalString(input.sourceRevision, "sourceRevision"),
  };
}

function pageDisplayTitles(pages) {
  const counts = new Map();
  for (const page of pages) counts.set(page.pageName, (counts.get(page.pageName) ?? 0) + 1);
  return pages.map((page, index) => ({
    ...page,
    displayTitle: `${String(index + 1).padStart(2, "0")} ${page.pageName}${
      counts.get(page.pageName) > 1 ? `〔${shortDigest(page.canvasPageId)}〕` : ""
    }`,
  }));
}

export function buildFeishuLearningDirectoryPlan({
  project,
  schematicPages = [],
  existingProjects = [],
} = {}) {
  const normalizedProject = normalizeFeishuProjectIdentity(project);
  const pages = pageDisplayTitles(schematicPages.map(normalizeFeishuSchematicPage));
  const pageIds = new Set();
  for (const page of pages) {
    if (pageIds.has(page.canvasPageId)) throw new Error(`Duplicate canvasPageId: ${page.canvasPageId}`);
    pageIds.add(page.canvasPageId);
  }

  const sections = FEISHU_NOTE_SECTIONS.map((section) => ({
    ...section,
    logicalId: `${normalizedProject.projectKey}:section:${section.key}`,
    objectType: "docx-heading",
    parentLogicalId: normalizedProject.projectKey,
  }));
  const pageNodes = pages.map((page) => ({
    logicalId: `${normalizedProject.projectKey}:${page.pageKey}`,
    objectType: "docx",
    role: "schematic-page-note",
    title: page.displayTitle,
    parentLogicalId: normalizedProject.projectKey,
    page,
  }));

  return {
    schemaVersion: FEISHU_DIRECTORY_PLAN_SCHEMA,
    namespace: {
      logicalId: "jlc-hardware-learning:root",
      objectType: "docx",
      role: "learning-note-root",
      title: "硬件学习笔记",
    },
    project: {
      ...normalizedProject,
      displayTitle: feishuProjectDisplayTitle(project, existingProjects),
    },
    root: {
      logicalId: normalizedProject.projectKey,
      objectType: "docx",
      role: "project-root",
      title: feishuProjectDisplayTitle(project, existingProjects),
      parentLogicalId: "jlc-hardware-learning:root",
      layoutMode: FEISHU_NOTE_LAYOUT_MODE,
      sections,
      children: pageNodes,
    },
  };
}

export function createFeishuLearningRegistry(project, options = {}) {
  const normalizedProject = normalizeFeishuProjectIdentity(project);
  return {
    schemaVersion: FEISHU_NOTE_REGISTRY_SCHEMA,
    project: normalizedProject,
    wiki: {
      spaceId: optionalString(options.spaceId, "spaceId"),
      learningRootNodeToken: optionalString(
        options.learningRootNodeToken,
        "learningRootNodeToken",
      ),
      learningRootDocToken: optionalString(options.learningRootDocToken, "learningRootDocToken"),
      projectNodeToken: optionalString(options.projectNodeToken, "projectNodeToken"),
      projectDocToken: optionalString(options.projectDocToken, "projectDocToken"),
      layoutMode: FEISHU_NOTE_LAYOUT_MODE,
      projectHomepageTemplateVersion: 0,
      projectHomepageIndexDigest: null,
    },
    sections: Object.fromEntries(FEISHU_NOTE_SECTIONS.map((section) => [section.key, {
      logicalId: `${normalizedProject.projectKey}:section:${section.key}`,
      nodeToken: null,
      docToken: null,
      headingBlockId: null,
    }])),
    pages: {},
    dialogues: {},
    updatedAt: timestamp(options.updatedAt),
  };
}

export function validateFeishuLearningRegistry(registry) {
  if (!registry || registry.schemaVersion !== FEISHU_NOTE_REGISTRY_SCHEMA) {
    throw new Error(`registry must use ${FEISHU_NOTE_REGISTRY_SCHEMA}.`);
  }
  normalizeFeishuProjectIdentity(registry.project);
  if (!registry.wiki || typeof registry.wiki !== "object") throw new Error("registry.wiki is required.");
  if (registry.wiki.layoutMode && registry.wiki.layoutMode !== FEISHU_NOTE_LAYOUT_MODE) {
    throw new Error(`registry.wiki.layoutMode must be ${FEISHU_NOTE_LAYOUT_MODE}.`);
  }
  if (registry.wiki.projectHomepageTemplateVersion != null) {
    const version = Number(registry.wiki.projectHomepageTemplateVersion);
    if (!Number.isSafeInteger(version) || version < 0) {
      throw new Error("registry.wiki.projectHomepageTemplateVersion must be a non-negative integer.");
    }
  }
  if (
    registry.wiki.projectHomepageIndexDigest != null
    && !/^[a-f0-9]{64}$/u.test(registry.wiki.projectHomepageIndexDigest)
  ) {
    throw new Error("registry.wiki.projectHomepageIndexDigest must be a lowercase SHA-256 digest.");
  }
  if (!registry.sections || typeof registry.sections !== "object") throw new Error("registry.sections is required.");
  if (!registry.pages || typeof registry.pages !== "object") throw new Error("registry.pages is required.");
  if (!registry.dialogues || typeof registry.dialogues !== "object") throw new Error("registry.dialogues is required.");
  for (const page of Object.values(registry.pages)) {
    if (page?.learningFrameMarkerStyle) normalizeMarkerStyle(page.learningFrameMarkerStyle);
    if (page?.documentLocation && !["drive", "wiki"].includes(page.documentLocation)) {
      throw new Error("registry page documentLocation must be drive or wiki.");
    }
    if (page?.managedContentVersion != null) {
      const version = Number(page.managedContentVersion);
      if (!Number.isSafeInteger(version) || version < 0) {
        throw new Error("registry page managedContentVersion must be a non-negative integer.");
      }
    }
  }
  for (const dialogue of Object.values(registry.dialogues)) {
    if (dialogue?.questionDigest && !/^[a-f0-9]{64}$/u.test(dialogue.questionDigest)) {
      throw new Error("registry dialogue questionDigest must be a lowercase SHA-256 digest.");
    }
    if (dialogue?.answerDigest && !/^[a-f0-9]{64}$/u.test(dialogue.answerDigest)) {
      throw new Error("registry dialogue answerDigest must be a lowercase SHA-256 digest.");
    }
  }
  return registry;
}

function ensureMatchingProject(registry, projectId) {
  const validated = validateFeishuLearningRegistry(registry);
  if (projectId && validated.project.projectId !== projectId) {
    throw new Error("Feishu note binding project identity mismatch.");
  }
  return clone(validated);
}

export function bindFeishuLearningRoot(registry, binding = {}) {
  const next = ensureMatchingProject(registry, binding.projectId);
  next.wiki = {
    ...next.wiki,
    spaceId: requiredString(binding.spaceId ?? next.wiki.spaceId, "spaceId"),
    learningRootNodeToken: requiredString(
      binding.learningRootNodeToken ?? next.wiki.learningRootNodeToken,
      "learningRootNodeToken",
    ),
    learningRootDocToken: requiredString(
      binding.learningRootDocToken ?? next.wiki.learningRootDocToken,
      "learningRootDocToken",
    ),
  };
  next.updatedAt = timestamp(binding.updatedAt);
  return next;
}

export function bindFeishuProjectNode(registry, binding = {}) {
  const next = ensureMatchingProject(registry, binding.projectId);
  next.wiki = {
    ...next.wiki,
    spaceId: requiredString(binding.spaceId ?? next.wiki.spaceId, "spaceId"),
    projectNodeToken: requiredString(
      binding.projectNodeToken ?? next.wiki.projectNodeToken,
      "projectNodeToken",
    ),
    projectDocToken: requiredString(
      binding.projectDocToken ?? next.wiki.projectDocToken,
      "projectDocToken",
    ),
    layoutMode: FEISHU_NOTE_LAYOUT_MODE,
  };
  next.updatedAt = timestamp(binding.updatedAt);
  return next;
}

export function markFeishuProjectHomepageSynced(registry, binding = {}) {
  const next = ensureMatchingProject(registry, binding.projectId);
  const templateVersion = binding.templateVersion == null
    ? FEISHU_PROJECT_HOMEPAGE_TEMPLATE_VERSION
    : Number(binding.templateVersion);
  if (!Number.isSafeInteger(templateVersion) || templateVersion < 0) {
    throw new Error("templateVersion must be a non-negative integer.");
  }
  const indexDigest = requiredString(binding.indexDigest, "indexDigest", 64);
  if (!/^[a-f0-9]{64}$/u.test(indexDigest)) {
    throw new Error("indexDigest must be a lowercase SHA-256 digest.");
  }
  next.wiki = {
    ...next.wiki,
    layoutMode: FEISHU_NOTE_LAYOUT_MODE,
    projectHomepageTemplateVersion: templateVersion,
    projectHomepageIndexDigest: indexDigest,
  };
  for (const section of Object.values(next.sections)) {
    section.nodeToken = null;
    section.docToken = null;
  }
  next.updatedAt = timestamp(binding.updatedAt);
  return next;
}

export function bindFeishuSectionNode(registry, binding = {}) {
  const next = ensureMatchingProject(registry, binding.projectId);
  const sectionKey = requiredString(binding.sectionKey, "sectionKey");
  if (!next.sections[sectionKey]) throw new Error(`Unknown Feishu note section: ${sectionKey}`);
  next.sections[sectionKey] = {
    ...next.sections[sectionKey],
    nodeToken: requiredString(binding.nodeToken, "nodeToken"),
    docToken: requiredString(binding.docToken, "docToken"),
  };
  next.updatedAt = timestamp(binding.updatedAt);
  return next;
}

export function upsertFeishuPageBinding(registry, pageInput = {}) {
  const next = ensureMatchingProject(registry, pageInput.projectId);
  const page = normalizeFeishuSchematicPage(pageInput);
  const existing = next.pages[page.canvasPageId] ?? {
    pageKey: page.pageKey,
    canvasPageId: page.canvasPageId,
    frames: {},
  };
  if (
    existing.schematicPageUuid
    && page.schematicPageUuid
    && existing.schematicPageUuid !== page.schematicPageUuid
  ) {
    throw new Error(`Feishu page binding schematic identity mismatch: ${page.canvasPageId}`);
  }
  const noteTemplateVersion = pageInput.noteTemplateVersion == null
    ? existing.noteTemplateVersion ?? 0
    : Number(pageInput.noteTemplateVersion);
  if (!Number.isSafeInteger(noteTemplateVersion) || noteTemplateVersion < 0) {
    throw new Error("noteTemplateVersion must be a non-negative integer.");
  }
  const managedContentVersion = pageInput.managedContentVersion == null
    ? existing.managedContentVersion ?? 0
    : Number(pageInput.managedContentVersion);
  if (!Number.isSafeInteger(managedContentVersion) || managedContentVersion < 0) {
    throw new Error("managedContentVersion must be a non-negative integer.");
  }
  const nodeToken = optionalString(pageInput.nodeToken, "nodeToken") ?? existing.nodeToken ?? null;
  const docToken = optionalString(pageInput.docToken, "docToken") ?? existing.docToken ?? null;
  const documentLocation = optionalString(
    pageInput.documentLocation,
    "documentLocation",
  ) ?? existing.documentLocation ?? (nodeToken ? "wiki" : docToken ? "drive" : null);
  if (documentLocation && !new Set(["drive", "wiki"]).has(documentLocation)) {
    throw new Error("documentLocation must be drive or wiki.");
  }
  if (documentLocation === "wiki" && !nodeToken) {
    throw new Error("Wiki page bindings require nodeToken.");
  }
  next.pages[page.canvasPageId] = {
    ...existing,
    ...page,
    nodeToken,
    docToken,
    docUrl: optionalString(pageInput.docUrl, "docUrl", 2048) ?? existing.docUrl ?? null,
    docRevision: optionalString(pageInput.docRevision, "docRevision")
      ?? existing.docRevision
      ?? null,
    documentLocation,
    whiteboardToken: optionalString(pageInput.whiteboardToken, "whiteboardToken")
      ?? existing.whiteboardToken
      ?? null,
    moduleIndexWhiteboardToken: optionalString(
      pageInput.moduleIndexWhiteboardToken,
      "moduleIndexWhiteboardToken",
    ) ?? existing.moduleIndexWhiteboardToken ?? null,
    legacyContentDigest: optionalString(
      pageInput.legacyContentDigest,
      "legacyContentDigest",
      64,
    ) ?? existing.legacyContentDigest ?? null,
    learningFrameMarkerStyle: normalizeMarkerStyle(
      pageInput.learningFrameMarkerStyle ?? existing.learningFrameMarkerStyle,
    ),
    noteTemplateVersion,
    managedContentVersion,
    syncedContentDigest: optionalString(pageInput.syncedContentDigest, "syncedContentDigest", 64)
      ?? existing.syncedContentDigest
      ?? null,
    frames: existing.frames ?? {},
    updatedAt: timestamp(pageInput.updatedAt),
  };
  next.updatedAt = next.pages[page.canvasPageId].updatedAt;
  return next;
}

export function upsertFeishuFrameNote(registry, frameInput = {}) {
  const next = ensureMatchingProject(registry, frameInput.projectId);
  const canvasPageId = requiredString(frameInput.canvasPageId, "canvasPageId");
  const page = next.pages[canvasPageId];
  if (!page) throw new Error(`Feishu page binding not found: ${canvasPageId}`);
  const frameNumber = positiveInteger(frameInput.frameNumber, "frameNumber");
  const status = frameInput.status ?? "unstarted";
  if (!FRAME_STATUS_SET.has(status)) throw new Error(`Unsupported Feishu frame status: ${status}`);
  const existing = page.frames[String(frameNumber)] ?? {
    frameNumber,
    title: `模块 ${frameNumber}`,
    questionIds: [],
    answerDigests: [],
  };
  const updatedAt = timestamp(frameInput.updatedAt);
  page.frames[String(frameNumber)] = {
    ...existing,
    title: optionalString(frameInput.title, "title") ?? existing.title,
    status,
    questionIds: [...new Set([
      ...(existing.questionIds ?? []),
      ...uniqueStrings(frameInput.questionIds, "questionIds"),
    ])],
    answerDigests: [...new Set([
      ...(existing.answerDigests ?? []),
      ...uniqueStrings(frameInput.answerDigests, "answerDigests"),
    ])],
    docBlockId: optionalString(frameInput.docBlockId, "docBlockId") ?? existing.docBlockId ?? null,
    updatedAt,
  };
  page.updatedAt = updatedAt;
  next.updatedAt = updatedAt;
  return next;
}

export function linkFeishuDialogue(registry, dialogueInput = {}) {
  let next = ensureMatchingProject(registry, dialogueInput.projectId);
  const canvasPageId = requiredString(dialogueInput.canvasPageId, "canvasPageId");
  if (!next.pages[canvasPageId]) throw new Error(`Feishu page binding not found: ${canvasPageId}`);
  const questionId = requiredString(dialogueInput.questionId, "questionId");
  if (!questionId.startsWith("question:")) throw new Error("questionId must start with question:.");
  const frameNumbers = [...new Set((dialogueInput.frameNumbers ?? []).map((number) => (
    positiveInteger(number, "frameNumbers")
  )))].sort((left, right) => left - right);
  if (frameNumbers.length === 0) throw new Error("frameNumbers must contain at least one learning frame.");
  const answerDigest = optionalString(dialogueInput.answerDigest, "answerDigest", 64);
  if (answerDigest && !/^[a-f0-9]{64}$/u.test(answerDigest)) {
    throw new Error("answerDigest must be a lowercase SHA-256 digest.");
  }
  const questionDigest = optionalString(dialogueInput.questionDigest, "questionDigest", 64);
  if (questionDigest && !/^[a-f0-9]{64}$/u.test(questionDigest)) {
    throw new Error("questionDigest must be a lowercase SHA-256 digest.");
  }
  const linkedAt = timestamp(dialogueInput.linkedAt);
  const docBlockId = optionalString(dialogueInput.docBlockId, "docBlockId");
  const existing = next.dialogues[questionId];
  if (existing) {
    const comparable = { canvasPageId, frameNumbers, questionDigest, answerDigest, docBlockId };
    if (JSON.stringify({
      canvasPageId: existing.canvasPageId,
      frameNumbers: existing.frameNumbers,
      questionDigest: existing.questionDigest ?? null,
      answerDigest: existing.answerDigest,
      docBlockId: existing.docBlockId,
    }) !== JSON.stringify(comparable)) {
      throw new Error(`Immutable Feishu dialogue binding differs: ${questionId}`);
    }
    return next;
  }
  for (const frameNumber of frameNumbers) {
    next = upsertFeishuFrameNote(next, {
      projectId: next.project.projectId,
      canvasPageId,
      frameNumber,
      status: dialogueInput.status ?? "learning",
      questionIds: [questionId],
      answerDigests: answerDigest ? [answerDigest] : [],
      updatedAt: linkedAt,
    });
  }
  next.dialogues[questionId] = {
    questionId,
    canvasPageId,
    frameNumbers,
    questionDigest,
    answerDigest,
    docBlockId,
    linkedAt,
  };
  next.updatedAt = linkedAt;
  return next;
}

export function feishuPageContentDigest(registry, canvasPageIdInput) {
  const validated = validateFeishuLearningRegistry(registry);
  const canvasPageId = requiredString(canvasPageIdInput, "canvasPageId");
  const page = validated.pages[canvasPageId];
  if (!page) throw new Error(`Feishu page binding not found: ${canvasPageId}`);
  const frames = Object.values(page.frames ?? {})
    .sort((left, right) => left.frameNumber - right.frameNumber)
    .map((frame) => ({
      frameNumber: frame.frameNumber,
      title: frame.title,
      status: frame.status,
      questionIds: [...(frame.questionIds ?? [])].sort(),
      answerDigests: [...(frame.answerDigests ?? [])].sort(),
      docBlockId: frame.docBlockId ?? null,
    }));
  const dialogues = Object.values(validated.dialogues)
    .filter((dialogue) => dialogue.canvasPageId === canvasPageId)
    .sort((left, right) => left.questionId.localeCompare(right.questionId))
    .map((dialogue) => ({
      questionId: dialogue.questionId,
      frameNumbers: dialogue.frameNumbers,
      questionDigest: dialogue.questionDigest ?? null,
      answerDigest: dialogue.answerDigest,
      docBlockId: dialogue.docBlockId,
    }));
  return sha256Json({
    pageName: page.pageName,
    schematicPageUuid: page.schematicPageUuid,
    sourceRevision: page.sourceRevision,
    frames,
    dialogues,
  });
}

export function markFeishuPageContentSynced(registry, input = {}) {
  const next = ensureMatchingProject(registry, input.projectId);
  const canvasPageId = requiredString(input.canvasPageId, "canvasPageId");
  const page = next.pages[canvasPageId];
  if (!page) throw new Error(`Feishu page binding not found: ${canvasPageId}`);
  const noteTemplateVersion = input.noteTemplateVersion == null
    ? FEISHU_PAGE_NOTE_TEMPLATE_VERSION
    : Number(input.noteTemplateVersion);
  if (!Number.isSafeInteger(noteTemplateVersion) || noteTemplateVersion < 0) {
    throw new Error("noteTemplateVersion must be a non-negative integer.");
  }
  const managedContentVersion = input.managedContentVersion == null
    ? FEISHU_PAGE_MANAGED_CONTENT_VERSION
    : Number(input.managedContentVersion);
  if (!Number.isSafeInteger(managedContentVersion) || managedContentVersion < 0) {
    throw new Error("managedContentVersion must be a non-negative integer.");
  }
  const expectedDigest = feishuPageContentDigest(next, canvasPageId);
  const syncedContentDigest = optionalString(
    input.syncedContentDigest,
    "syncedContentDigest",
    64,
  ) ?? expectedDigest;
  if (!/^[a-f0-9]{64}$/u.test(syncedContentDigest)) {
    throw new Error("syncedContentDigest must be a lowercase SHA-256 digest.");
  }
  if (syncedContentDigest !== expectedDigest) {
    throw new Error("syncedContentDigest does not match the current Feishu page content.");
  }
  page.noteTemplateVersion = noteTemplateVersion;
  page.managedContentVersion = managedContentVersion;
  page.syncedContentDigest = syncedContentDigest;
  page.updatedAt = timestamp(input.updatedAt);
  next.updatedAt = page.updatedAt;
  return next;
}

export function resolveFeishuLearningTarget(registry, input = {}) {
  const validated = validateFeishuLearningRegistry(registry);
  const canvasPageId = requiredString(input.canvasPageId, "canvasPageId");
  const page = validated.pages[canvasPageId] ?? null;
  const frameNumbers = [...new Set((input.frameNumbers ?? []).map((number) => (
    positiveInteger(number, "frameNumbers")
  )))].sort((left, right) => left - right);
  const missing = [];
  if (!validated.wiki.spaceId) missing.push("wiki.spaceId");
  if (!validated.wiki.learningRootNodeToken) missing.push("wiki.learningRootNodeToken");
  if (!validated.wiki.projectNodeToken) missing.push("wiki.projectNodeToken");
  if (!page) missing.push("pageBinding");
  if (page && !page.docToken) missing.push("page.docToken");
  if (page && !page.whiteboardToken) missing.push("page.whiteboardToken");
  if (page && !page.moduleIndexWhiteboardToken) missing.push("page.moduleIndexWhiteboardToken");
  const frames = frameNumbers.map((number) => page?.frames?.[String(number)] ?? null);
  for (let index = 0; index < frames.length; index += 1) {
    if (!frames[index]) missing.push(`frame:${frameNumbers[index]}`);
  }
  return {
    ready: missing.length === 0,
    missing,
    project: clone(validated.project),
    page: clone(page),
    frames: clone(frames.filter(Boolean)),
  };
}
