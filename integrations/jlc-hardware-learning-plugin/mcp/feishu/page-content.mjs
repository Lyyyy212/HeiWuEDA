import { createHash } from "node:crypto";

import {
  FEISHU_PAGE_MANAGED_CONTENT_VERSION,
  validateFeishuLearningRegistry,
} from "./note-model.mjs";
import { parseFeishuDocumentContent } from "./document-inspection.mjs";

export const FEISHU_MANAGED_PAGE_CONTENT_SCHEMA = "jlc.feishu-managed-page-content.v1";

const MODULE_START = "JLC 自动同步区：模块索引（开始）";
const MODULE_END = "JLC 自动同步区：模块索引（结束）";
const DIALOGUE_START = "JLC 自动同步区：提问与解答（开始）";
const DIALOGUE_END = "JLC 自动同步区：提问与解答（结束）";

const STATUS_LABELS = Object.freeze({
  unstarted: "尚未开始",
  learning: "学习中",
  "question-open": "问题待解答",
  concluded: "已形成结论",
  "review-required": "需要复核",
});

function requiredString(value, field) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${field} is required.`);
  return value.trim();
}

function escapeXml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function sha256(value) {
  return createHash("sha256").update(String(value)).digest("hex");
}

function markerText(label, digest) {
  return `${label}；内容摘要 ${digest}`;
}

function markerXml(label, digest) {
  return `<p><span text-color="gray">${escapeXml(markerText(label, digest))}</span></p>`;
}

function normalizeAnswer(answer = {}) {
  return {
    summary: answer.summary ? String(answer.summary) : null,
    explanation: answer.explanation ? String(answer.explanation) : null,
    claims: Array.isArray(answer.claims)
      ? answer.claims.map((claim) => String(claim?.text ?? "")).filter(Boolean)
      : [],
    assumptions: Array.isArray(answer.assumptions) ? answer.assumptions.map(String) : [],
    unknowns: Array.isArray(answer.unknowns) ? answer.unknowns.map(String) : [],
    safetyNotes: Array.isArray(answer.safetyNotes) ? answer.safetyNotes.map(String) : [],
    nextQuestions: Array.isArray(answer.nextQuestions) ? answer.nextQuestions.map(String) : [],
  };
}

function normalizeDialogueRecord(record = {}) {
  return {
    questionId: requiredString(record.questionId, "dialogueRecord.questionId"),
    questionDigest: record.questionDigest ? requiredString(record.questionDigest, "questionDigest") : null,
    answerDigest: record.answerDigest ? requiredString(record.answerDigest, "answerDigest") : null,
    frameNumbers: [...new Set((record.frameNumbers ?? []).map(Number))]
      .filter((number) => Number.isSafeInteger(number) && number > 0)
      .sort((left, right) => left - right),
    questionText: requiredString(record.questionText, "dialogueRecord.questionText"),
    answer: normalizeAnswer(record.answer),
  };
}

export function buildFeishuManagedPageModel({
  registry,
  canvasPageId,
  dialogueRecords = [],
} = {}) {
  validateFeishuLearningRegistry(registry);
  const page = registry.pages[requiredString(canvasPageId, "canvasPageId")];
  if (!page) throw new Error(`Feishu page binding not found: ${canvasPageId}`);
  const recordByQuestionId = new Map(dialogueRecords.map((record) => {
    const normalized = normalizeDialogueRecord(record);
    return [normalized.questionId, normalized];
  }));
  const frames = Object.values(page.frames ?? {})
    .sort((left, right) => left.frameNumber - right.frameNumber)
    .map((frame) => ({
      frameNumber: frame.frameNumber,
      title: frame.title,
      status: frame.status,
      questionIds: [...(frame.questionIds ?? [])].sort(),
      answerDigests: [...(frame.answerDigests ?? [])].sort(),
    }));
  const dialogues = Object.values(registry.dialogues)
    .filter((dialogue) => dialogue.canvasPageId === canvasPageId)
    .sort((left, right) => left.linkedAt.localeCompare(right.linkedAt)
      || left.questionId.localeCompare(right.questionId))
    .map((dialogue) => {
      const record = recordByQuestionId.get(dialogue.questionId);
      if (!record) throw new Error(`Durable learning dialogue record not found: ${dialogue.questionId}`);
      if (JSON.stringify(record.frameNumbers) !== JSON.stringify(dialogue.frameNumbers)) {
        throw new Error(`Learning dialogue frame binding changed: ${dialogue.questionId}`);
      }
      if ((dialogue.questionDigest ?? null) !== record.questionDigest) {
        throw new Error(`Learning question digest changed: ${dialogue.questionId}`);
      }
      if ((dialogue.answerDigest ?? null) !== record.answerDigest) {
        throw new Error(`Learning answer digest changed: ${dialogue.questionId}`);
      }
      return {
        ...record,
        linkedAt: dialogue.linkedAt,
      };
    });
  return {
    schemaVersion: FEISHU_MANAGED_PAGE_CONTENT_SCHEMA,
    managedContentVersion: FEISHU_PAGE_MANAGED_CONTENT_VERSION,
    canvasPageId,
    schematicPageUuid: page.schematicPageUuid,
    pageName: page.pageName,
    frames,
    dialogues,
  };
}

function renderList(title, items) {
  if (items.length === 0) return "";
  return `<p><b>${escapeXml(title)}：</b></p><ul>${items.map((item) => (
    `<li>${escapeXml(item)}</li>`
  )).join("")}</ul>`;
}

function renderModuleIndex(model, digest) {
  const chunks = [markerXml(MODULE_START, digest)];
  if (model.frames.length === 0) {
    chunks.push("<p>当前图页尚无学习框。</p>");
  } else {
    chunks.push("<table><colgroup><col/><col/><col/></colgroup><thead><tr><th><p>学习框</p></th><th><p>模块</p></th><th><p>状态</p></th></tr></thead><tbody>");
    for (const frame of model.frames) {
      chunks.push(
        `<tr><td><p>${frame.frameNumber}</p></td><td><p>${escapeXml(frame.title)}</p></td><td><p>${escapeXml(STATUS_LABELS[frame.status] ?? frame.status)}</p></td></tr>`,
      );
    }
    chunks.push("</tbody></table>");
  }
  chunks.push(markerXml(MODULE_END, digest));
  return chunks.join("");
}

function renderDialogues(model, digest) {
  const chunks = [markerXml(DIALOGUE_START, digest)];
  if (model.dialogues.length === 0) {
    chunks.push("<p>尚无已绑定到本图页学习框的问答。</p>");
  }
  for (const dialogue of model.dialogues) {
    chunks.push(`<h2>学习框 ${dialogue.frameNumbers.join(" + ")} 的问答</h2>`);
    chunks.push(`<p><b>问题：</b>${escapeXml(dialogue.questionText)}</p>`);
    chunks.push(`<p><b>记录 ID：</b>${escapeXml(dialogue.questionId)}</p>`);
    if (dialogue.answer.summary) {
      chunks.push(`<p><b>回答摘要：</b>${escapeXml(dialogue.answer.summary)}</p>`);
    }
    if (dialogue.answer.explanation) {
      chunks.push(`<p>${escapeXml(dialogue.answer.explanation)}</p>`);
    }
    chunks.push(renderList("证据结论", dialogue.answer.claims));
    chunks.push(renderList("假设", dialogue.answer.assumptions));
    chunks.push(renderList("待确认", dialogue.answer.unknowns));
    chunks.push(renderList("安全提示", dialogue.answer.safetyNotes));
    chunks.push(renderList("后续问题", dialogue.answer.nextQuestions));
  }
  chunks.push(markerXml(DIALOGUE_END, digest));
  return chunks.join("");
}

export function renderFeishuManagedPageContent(input = {}) {
  const model = input.model ?? buildFeishuManagedPageModel(input);
  const contentDigest = sha256(JSON.stringify(model));
  return {
    schemaVersion: FEISHU_MANAGED_PAGE_CONTENT_SCHEMA,
    contentDigest,
    model,
    moduleIndexXml: renderModuleIndex(model, contentDigest),
    dialoguesXml: renderDialogues(model, contentDigest),
  };
}

function plainText(value) {
  return String(value ?? "")
    .replace(/<[^>]*>/gu, "")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replaceAll("&amp;", "&")
    .trim();
}

function findMarker(content, label) {
  const pattern = /<p\s+id="([^"]+)"[^>]*>([\s\S]*?)<\/p>/gu;
  const matches = [...String(content ?? "").matchAll(pattern)]
    .map((match) => ({ blockId: match[1], text: plainText(match[2]) }))
    .filter((entry) => entry.text.startsWith(`${label}；内容摘要 `));
  if (matches.length > 1) throw new Error(`Duplicate Feishu managed marker: ${label}`);
  if (matches.length === 0) return null;
  const digest = matches[0].text.slice(`${label}；内容摘要 `.length);
  return { ...matches[0], digest };
}

function managedRange(content, startLabel, endLabel) {
  const start = findMarker(content, startLabel);
  const end = findMarker(content, endLabel);
  if (Boolean(start) !== Boolean(end)) throw new Error(`Incomplete Feishu managed range: ${startLabel}`);
  if (!start) return null;
  if (start.digest !== end.digest) throw new Error(`Feishu managed range digest mismatch: ${startLabel}`);
  return { startBlockId: start.blockId, endBlockId: end.blockId, contentDigest: start.digest };
}

export function inspectFeishuManagedPageContent(content) {
  return {
    moduleIndex: managedRange(content, MODULE_START, MODULE_END),
    dialogues: managedRange(content, DIALOGUE_START, DIALOGUE_END),
  };
}

function heading(parsed, title) {
  return parsed.headings.find((candidate) => candidate.title === title) ?? null;
}

export function planFeishuManagedPagePatch({ content, rendered } = {}) {
  if (!rendered || rendered.schemaVersion !== FEISHU_MANAGED_PAGE_CONTENT_SCHEMA) {
    throw new Error(`rendered must use ${FEISHU_MANAGED_PAGE_CONTENT_SCHEMA}.`);
  }
  const desired = rendered;
  const parsed = parseFeishuDocumentContent(content);
  const managed = inspectFeishuManagedPageContent(content);
  const moduleBoard = parsed.whiteboards.find((board) => board.role === "module-index-board");
  const moduleHeading = heading(parsed, "模块索引");
  const dialogueHeading = heading(parsed, "提问与解答");
  if (!moduleBoard && !moduleHeading) throw new Error("Feishu page has no module-index anchor.");
  if (!dialogueHeading) throw new Error("Feishu page has no dialogue anchor.");
  const operations = [];
  if (managed.moduleIndex?.contentDigest !== desired.contentDigest) {
    operations.push(managed.moduleIndex ? {
      kind: "block_replace",
      startBlockId: managed.moduleIndex.startBlockId,
      endBlockId: managed.moduleIndex.endBlockId,
      content: desired.moduleIndexXml,
      section: "module-index",
    } : {
      kind: "block_insert_after",
      blockId: moduleBoard?.blockId ?? moduleHeading.blockId,
      content: desired.moduleIndexXml,
      section: "module-index",
    });
  }
  if (managed.dialogues?.contentDigest !== desired.contentDigest) {
    operations.push(managed.dialogues ? {
      kind: "block_replace",
      startBlockId: managed.dialogues.startBlockId,
      endBlockId: managed.dialogues.endBlockId,
      content: desired.dialoguesXml,
      section: "dialogues",
    } : {
      kind: "block_insert_after",
      blockId: dialogueHeading.blockId,
      content: desired.dialoguesXml,
      section: "dialogues",
    });
  }
  return {
    contentDigest: desired.contentDigest,
    operations,
    alreadySynchronized: operations.length === 0,
  };
}
