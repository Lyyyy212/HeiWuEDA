import { createHash, randomUUID } from "node:crypto";

const INTENTS = new Set([
  "explain-selection",
  "trace-signal",
  "explain-component",
  "power-path",
  "review-concept",
  "compare-options",
]);
const LEARNING_LEVELS = new Set(["beginner", "intermediate", "advanced"]);

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function finite(value, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function shapeLocalBounds(shape) {
  const learningBounds = shape?.meta?.hardwareLearningBounds;
  if (
    learningBounds &&
    [learningBounds.x, learningBounds.y, learningBounds.w, learningBounds.h].every(Number.isFinite)
  ) {
    return {
      x: learningBounds.x,
      y: learningBounds.y,
      width: Math.max(1, learningBounds.w),
      height: Math.max(1, learningBounds.h),
    };
  }
  if (shape?.type !== "arrow") {
    return {
      x: 0,
      y: 0,
      width: Math.max(1, finite(shape?.props?.w, shape?.type === "text" ? 160 : 1)),
      height: Math.max(1, finite(shape?.props?.h, shape?.type === "text" ? 40 : 1)),
    };
  }
  const start = shape.props?.start ?? { x: 0, y: 0 };
  const end = shape.props?.end ?? { x: 0, y: 0 };
  const x = Math.min(finite(start.x), finite(end.x));
  const y = Math.min(finite(start.y), finite(end.y));
  return {
    x,
    y,
    width: Math.max(1, Math.abs(finite(end.x) - finite(start.x))),
    height: Math.max(1, Math.abs(finite(end.y) - finite(start.y))),
  };
}

function pageBounds(store, shape) {
  const local = shapeLocalBounds(shape);
  let x = finite(shape.x) + local.x;
  let y = finite(shape.y) + local.y;
  let parent = store[shape.parentId];
  const visited = new Set([shape.id]);
  while (parent?.typeName === "shape" && !visited.has(parent.id)) {
    visited.add(parent.id);
    x += finite(parent.x);
    y += finite(parent.y);
    parent = store[parent.parentId];
  }
  return {
    x,
    y,
    width: local.width,
    height: local.height,
    rotation: finite(shape.rotation),
    coordinateSpace: "hardware-learning-page",
  };
}

function pageIdForShape(store, shape) {
  let record = shape;
  const visited = new Set();
  while (record && !visited.has(record.id)) {
    visited.add(record.id);
    if (record.typeName === "page") return record.id;
    const parent = store[record.parentId];
    if (parent?.typeName === "page") return parent.id;
    record = parent;
  }
  return null;
}

function roleForShape(shape) {
  if (shape.type === "image") return "source-image";
  if (shape.meta?.hardwareLearningFrame === true) return "selection-frame";
  if (shape.type === "note" || shape.type === "text") return "question-note";
  if (shape.meta?.hardwareLearningKind === "note") return "question-note";
  if (shape.meta?.hardwareLearningAnnotation === true) return "annotation";
  if (["arrow", "highlight", "geo", "draw"].includes(shape.type)) return "annotation";
  return "other";
}

function envelopeForShape(store, shape, role = roleForShape(shape)) {
  const asset = shape.props?.assetId ? store[shape.props.assetId] : null;
  return {
    shapeId: shape.id,
    shapeType: shape.type,
    role,
    pageBounds: pageBounds(store, shape),
    parentShapeId: shape.parentId ?? null,
    assetUrl: asset?.props?.src ?? null,
    text: shape.props?.text ?? null,
    learningFrameNumber: shape.meta?.hardwareLearningFrame === true
      ? shape.meta?.hardwareLearningFrameNumber ?? null
      : null,
    meta: shape.meta ?? {},
  };
}

function unionBounds(bounds) {
  const x = Math.min(...bounds.map((item) => item.x));
  const y = Math.min(...bounds.map((item) => item.y));
  const right = Math.max(...bounds.map((item) => item.x + item.width));
  const bottom = Math.max(...bounds.map((item) => item.y + item.height));
  return {
    x,
    y,
    width: right - x,
    height: bottom - y,
    rotation: 0,
    coordinateSpace: "hardware-learning-page",
  };
}

function overlapArea(a, b) {
  const width = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
  const height = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
  return width * height;
}

function positiveFrameNumber(value) {
  const number = Number.parseInt(String(value), 10);
  return Number.isSafeInteger(number) && number > 0 ? number : null;
}

export function parseLearningFrameReferences(userQuestion) {
  const text = String(userQuestion ?? "");
  const references = new Set();
  const add = (value) => {
    const number = positiveFrameNumber(value);
    if (number !== null) references.add(number);
  };
  const taggedPatterns = [
    /(?:学习框|模块|区域|框)\s*[#＃]?\s*(\d+)/giu,
    /[#＃]?\s*(\d+)\s*(?:号\s*)?(?:学习框|模块|区域|框)/giu,
    /[#＃]\s*(\d+)/gu,
  ];
  for (const pattern of taggedPatterns) {
    for (const match of text.matchAll(pattern)) add(match[1]);
  }
  const listPattern = /(?:^|[^\d.])(\d+(?:\s*(?:和|与|及|、|，|,|\+|＆|&)\s*\d+)+)(?=$|[^\d.])/gu;
  for (const match of text.matchAll(listPattern)) {
    for (const value of match[1].match(/\d+/g) ?? []) add(value);
  }
  return [...references].sort((left, right) => left - right);
}

function numberedSelection(canvasSnapshot, selectionState, frameNumbers) {
  const store = canvasSnapshot.store;
  const currentPageId = selectionState?.currentPageId
    ?? selectionState?.lastNonEmptySelection?.currentPageId
    ?? null;
  if (!currentPageId || store[currentPageId]?.typeName !== "page") {
    throw new Error("Numbered learning-frame references require a saved current JLC Hardware Learning page.");
  }
  const matchesByNumber = new Map();
  for (const record of Object.values(store)) {
    if (record?.typeName !== "shape" || record.meta?.hardwareLearningFrame !== true) continue;
    if (pageIdForShape(store, record) !== currentPageId) continue;
    const number = positiveFrameNumber(record.meta?.hardwareLearningFrameNumber);
    if (number === null || !frameNumbers.includes(number)) continue;
    const matches = matchesByNumber.get(number) ?? [];
    matches.push(record);
    matchesByNumber.set(number, matches);
  }
  const missing = frameNumbers.filter((number) => !matchesByNumber.has(number));
  if (missing.length > 0) {
    throw new Error(`Learning frame number(s) not found on the current page: ${missing.join(", ")}`);
  }
  const duplicates = frameNumbers.filter((number) => matchesByNumber.get(number).length !== 1);
  if (duplicates.length > 0) {
    throw new Error(`Learning frame number(s) are ambiguous on the current page: ${duplicates.join(", ")}`);
  }
  return {
    source: "frame-number-reference",
    referencedFrameNumbers: frameNumbers,
    selection: {
      version: selectionState?.version
        ?? selectionState?.lastNonEmptySelection?.version
        ?? 1,
      selectionRevision: selectionState?.selectionRevision
        ?? selectionState?.lastNonEmptySelection?.selectionRevision
        ?? null,
      currentPageId,
      selectedShapes: frameNumbers.map((number) => ({ id: matchesByNumber.get(number)[0].id })),
      updatedAt: selectionState?.updatedAt
        ?? selectionState?.lastNonEmptySelection?.updatedAt
        ?? null,
    },
  };
}

function choosePersistedSelection(selectionState) {
  if (selectionState?.selectedShapes?.length > 0) {
    return { source: "current", selection: selectionState, referencedFrameNumbers: [] };
  }
  if (selectionState?.lastNonEmptySelection?.selectedShapes?.length > 0) {
    return { source: "last-non-empty", selection: selectionState.lastNonEmptySelection, referencedFrameNumbers: [] };
  }
  throw new Error("No current or last non-empty JLC Hardware Learning selection is available. Draw or select a frame first.");
}

export function buildConversationLearningQuestion({
  canvasSnapshot,
  selectionState,
  userQuestion,
  learningLevel = "intermediate",
  intent = "explain-selection",
  questionId = `question:${randomUUID()}`,
  requestedAt = new Date().toISOString(),
} = {}) {
  if (!canvasSnapshot?.store || !canvasSnapshot?.schema) {
    throw new Error("A saved JLC Hardware Learning canvas snapshot is required.");
  }
  if (typeof userQuestion !== "string" || !userQuestion.trim() || userQuestion.trim().length > 4000) {
    throw new Error("userQuestion must contain 1..4000 characters.");
  }
  if (!INTENTS.has(intent)) throw new Error(`Unsupported learning intent: ${intent}`);
  if (!LEARNING_LEVELS.has(learningLevel)) throw new Error(`Unsupported learning level: ${learningLevel}`);
  if (typeof questionId !== "string" || !questionId.startsWith("question:")) {
    throw new Error("questionId must start with question:");
  }

  const store = canvasSnapshot.store;
  const frameReferences = parseLearningFrameReferences(userQuestion);
  const chosen = frameReferences.length > 0
    ? numberedSelection(canvasSnapshot, selectionState, frameReferences)
    : choosePersistedSelection(selectionState);
  const selectedRecords = chosen.selection.selectedShapes.map((item) => {
    const record = store[item.id];
    if (!record || record.typeName !== "shape") {
      throw new Error(`Selected JLC Hardware Learning shape no longer exists: ${item.id}`);
    }
    return record;
  });
  const pageIds = new Set(selectedRecords.map((shape) => pageIdForShape(store, shape)));
  if (pageIds.size !== 1 || pageIds.has(null)) {
    throw new Error("JLC Hardware Learning learning selection must belong to exactly one page.");
  }
  const canvasPageId = [...pageIds][0];
  if (chosen.selection.currentPageId && chosen.selection.currentPageId !== canvasPageId) {
    throw new Error("Persisted JLC Hardware Learning selection page no longer matches its selected shapes.");
  }

  const selectedBounds = selectedRecords.map((shape) => pageBounds(store, shape));
  const selectionBounds = unionBounds(selectedBounds);
  const selectedIds = new Set(selectedRecords.map((shape) => shape.id));
  const contextualImages = Object.values(store)
    .filter((record) => record?.typeName === "shape" && record.type === "image")
    .filter((record) => pageIdForShape(store, record) === canvasPageId)
    .filter((record) => !selectedIds.has(record.id))
    .map((record) => ({ record, area: overlapArea(selectionBounds, pageBounds(store, record)) }))
    .filter((item) => item.area > 0)
    .sort((left, right) => right.area - left.area)
    .slice(0, 4);

  const shapes = selectedRecords.map((shape) => envelopeForShape(store, shape));
  const existingSourceImages = shapes.filter((shape) => shape.role === "source-image").length;
  for (const item of contextualImages.slice(0, Math.max(0, 4 - existingSourceImages))) {
    shapes.push({
      ...envelopeForShape(store, item.record, "source-image"),
      contextualForSelectedShapeIds: [...selectedIds],
    });
  }

  const selectionCore = {
    version: 1,
    canvasSelectionVersion: chosen.selection.version ?? 1,
    selectionRevision: chosen.selection.selectionRevision ?? null,
    canvasPageId,
    selectedShapeIds: [...selectedIds],
    selectedFrameNumbers: selectedRecords
      .map((shape) => positiveFrameNumber(shape.meta?.hardwareLearningFrameNumber))
      .filter((number) => number !== null),
    referencedFrameNumbers: chosen.referencedFrameNumbers,
    shapes,
    unionBounds: selectionBounds,
    capturedAt: chosen.selection.updatedAt ?? requestedAt,
    selectionSource: chosen.source,
  };
  const canvasSnapshotSha256 = sha256(JSON.stringify(selectionCore));
  const question = {
    schemaVersion: "learning.question.v1",
    questionId,
    sessionId: `learning:jlc-hardware-learning:${canvasPageId.replace(/^page:/, "")}`,
    intent,
    userQuestion: userQuestion.trim(),
    learningLevel,
    selection: {
      ...selectionCore,
      selectionScreenshotAssetUrl: null,
      selectionScreenshotSha256: null,
      canvasSnapshotSha256,
    },
    easyedaContext: {
      mode: "offline-artifact",
      projectUuid: null,
      documentUuid: null,
      documentType: null,
      schematicPageUuid: null,
      windowId: null,
      capturedAt: requestedAt,
      artifactSha256: canvasSnapshotSha256,
    },
    requestedAt,
  };
  return { question, selectionSource: chosen.source };
}

export const conversationLearningIntents = [...INTENTS];
export const conversationLearningLevels = [...LEARNING_LEVELS];
