import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { resolveHardwareLearningPaths } from "../lib/canvas-storage.mjs";

const ALLOWED_ANNOTATION_KINDS = new Set(["note", "highlight", "rectangle", "arrow"]);
const FORBIDDEN_KEYS = new Set(["image", "imageUrl", "assetUrl", "html", "embed", "video", "slides"]);

function digest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function safeId(value, prefix) {
  if (typeof value !== "string" || !value.startsWith(`${prefix}:`)) {
    throw new Error(`${prefix} ID must start with ${prefix}:`);
  }
  return value.replace(/[^A-Za-z0-9._-]+/g, "-").slice(0, 180);
}

function learningRoot(args = {}) {
  const { projectDir } = resolveHardwareLearningPaths(args);
  return join(projectDir, ".easyeda-hardware-workbench", "learning");
}

async function readJsonIfPresent(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

async function writeJsonAtomic(path, value) {
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await rename(temporary, path);
}

async function writeImmutableJson(path, value) {
  const existing = await readJsonIfPresent(path);
  if (existing) {
    if (digest(existing) !== digest(value)) throw new Error(`Immutable JLC Hardware Learning learning record differs: ${path}`);
    return { replayed: true, value: existing };
  }
  await writeJsonAtomic(path, value);
  return { replayed: false, value };
}

function pngFromDataUrl(dataUrl) {
  if (dataUrl == null) return null;
  const match = /^data:image\/png;base64,([A-Za-z0-9+/=]+)$/.exec(String(dataUrl));
  if (!match) throw new Error("Learning selection screenshot must be a PNG data URL.");
  const buffer = Buffer.from(match[1], "base64");
  if (!buffer.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    throw new Error("Learning selection screenshot is not a valid PNG.");
  }
  return buffer;
}

export async function saveLearningQuestion(args = {}) {
  const question = args.question;
  if (!question || question.schemaVersion !== "learning.question.v1") {
    throw new Error("question must use learning.question.v1");
  }
  const questionName = safeId(question.questionId, "question");
  if (!question.selection || !Array.isArray(question.selection.selectedShapeIds) || question.selection.selectedShapeIds.length === 0) {
    throw new Error("learning question requires a non-empty JLC Hardware Learning selection");
  }
  const root = learningRoot(args);
  const questionsDir = join(root, "questions");
  const assetsDir = join(root, "assets");
  await mkdir(questionsDir, { recursive: true });
  await mkdir(assetsDir, { recursive: true });
  const screenshot = pngFromDataUrl(args.screenshotDataUrl);
  let screenshotRecord = null;
  if (screenshot) {
    const sha256 = createHash("sha256").update(screenshot).digest("hex");
    const screenshotPath = join(assetsDir, `${sha256}.png`);
    try {
      await writeFile(screenshotPath, screenshot, { flag: "wx" });
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
    }
    screenshotRecord = { path: screenshotPath, sha256 };
  }
  const questionPath = join(questionsDir, `${questionName}.json`);
  const existing = await readJsonIfPresent(questionPath);
  if (existing) {
    if (digest(existing.question) !== digest(question) || existing.screenshot?.sha256 !== screenshotRecord?.sha256) {
      throw new Error(`Immutable JLC Hardware Learning learning record differs: ${questionPath}`);
    }
    return { ok: true, questionPath, screenshot: existing.screenshot, replayed: true };
  }
  const record = {
    schemaVersion: "jlc.hardware-learning-question-record.v1",
    question,
    screenshot: screenshotRecord,
    savedAt: new Date().toISOString(),
  };
  const stored = await writeImmutableJson(questionPath, record);
  return { ok: true, questionPath, screenshot: screenshotRecord, replayed: stored.replayed };
}

function validateCommands(operationId, pageId, commands) {
  safeId(operationId, "operation");
  if (typeof pageId !== "string" || !pageId.startsWith("page:")) throw new Error("pageId must start with page:");
  if (!Array.isArray(commands) || commands.length === 0) throw new Error("annotation commands must be non-empty");
  for (const command of commands) {
    if (!command || !ALLOWED_ANNOTATION_KINDS.has(command.kind)) throw new Error("annotation kind is not whitelisted");
    if (command.operationId !== operationId || command.pageId !== pageId) throw new Error("annotation operation/page identity mismatch");
    for (const key of Object.keys(command)) {
      if (FORBIDDEN_KEYS.has(key)) throw new Error(`generated/embed annotation field is forbidden: ${key}`);
    }
  }
}

export async function insertLearningAnnotations(args = {}) {
  const operationId = args.operationId;
  const pageId = args.pageId;
  const commands = args.commands;
  validateCommands(operationId, pageId, commands);
  const operationsDir = join(learningRoot(args), "operations");
  await mkdir(operationsDir, { recursive: true });
  const operationPath = join(operationsDir, `${safeId(operationId, "operation")}.json`);
  const existing = await readJsonIfPresent(operationPath);
  const commandsSha256 = digest(commands);
  if (existing) {
    if (existing.commandsSha256 !== commandsSha256) throw new Error("operationId already belongs to different annotation commands");
    return { ok: true, operationPath, replayed: true, operation: existing };
  }
  const operation = {
    schemaVersion: "jlc.hardware-learning-annotation-operation.v1",
    operationId,
    pageId,
    commandsSha256,
    commands,
    status: "PENDING",
    createdAt: new Date().toISOString(),
  };
  await writeJsonAtomic(operationPath, operation);
  return { ok: true, operationPath, replayed: false, operation };
}

export async function pullLearningAnnotations(args = {}) {
  const operationsDir = join(learningRoot(args), "operations");
  await mkdir(operationsDir, { recursive: true });
  const names = await readdir(operationsDir);
  const operations = [];
  for (const name of names.filter((item) => item.endsWith(".json")).sort()) {
    const operation = await readJsonIfPresent(join(operationsDir, name));
    if (operation?.status !== "PENDING") continue;
    if (args.pageId && operation.pageId !== args.pageId) continue;
    operations.push(operation);
  }
  return { ok: true, operations };
}

export async function acknowledgeLearningAnnotations(args = {}) {
  const operationPath = join(
    learningRoot(args),
    "operations",
    `${safeId(args.operationId, "operation")}.json`,
  );
  const operation = await readJsonIfPresent(operationPath);
  if (!operation) throw new Error("learning annotation operation does not exist");
  if (operation.status === "APPLIED") return { ok: true, replayed: true, operation };
  if (operation.commandsSha256 !== args.commandsSha256) throw new Error("annotation acknowledgement digest mismatch");
  const applied = { ...operation, status: "APPLIED", appliedAt: new Date().toISOString() };
  await writeJsonAtomic(operationPath, applied);
  return { ok: true, replayed: false, operation: applied };
}

export const learningAnnotationKinds = [...ALLOWED_ANNOTATION_KINDS];
