import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { resolveHardwareLearningPaths } from "../lib/canvas-storage.mjs";

function requiredString(value, field) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${field} is required.`);
  return value.trim();
}
function learningRoot(args = {}) {
  const { projectDir } = resolveHardwareLearningPaths(args);
  return join(projectDir, ".easyeda-hardware-workbench", "learning");
}

async function readJson(path, label) {
  let value;
  try {
    value = JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") throw new Error(`${label} not found: ${path}`);
    throw new Error(`${label} is invalid: ${error.message}`);
  }
  return value;
}

function questionUuid(questionId) {
  const id = requiredString(questionId, "questionId");
  if (!/^question:[0-9a-f-]{36}$/u.test(id)) {
    throw new Error("questionId must be one durable hardware-learning question UUID.");
  }
  return id.slice("question:".length);
}

function positiveFrameNumbers(value, field) {
  const numbers = [...new Set((value ?? []).map(Number))]
    .filter((number) => Number.isSafeInteger(number) && number > 0)
    .sort((left, right) => left - right);
  if (numbers.length === 0) throw new Error(`${field} has no learning-frame number.`);
  return numbers;
}

export async function readFeishuLearningDialogueRecord(args = {}, input = {}) {
  const id = requiredString(input.questionId, "questionId");
  const uuid = questionUuid(id);
  const root = learningRoot(args);
  const runPath = join(root, "runs", `question--${uuid}.json`);
  const questionPath = join(root, "questions", `question-${uuid}.json`);
  const run = await readJson(runPath, "Learning question run");
  const questionRecord = await readJson(questionPath, "Learning question record");
  if (run.schemaVersion !== "learning.question-run.v1" || run.questionId !== id) {
    throw new Error(`Learning question run identity mismatch: ${id}`);
  }
  const question = questionRecord?.question;
  if (
    questionRecord?.schemaVersion !== "jlc.hardware-learning-question-record.v1"
    || question?.questionId !== id
  ) {
    throw new Error(`Learning question record identity mismatch: ${id}`);
  }
  const canvasPageId = requiredString(question.selection?.canvasPageId, "question.canvasPageId");
  if (run.canvasPageId !== canvasPageId) {
    throw new Error(`Learning question page identity mismatch: ${id}`);
  }
  if (input.canvasPageId && input.canvasPageId !== canvasPageId) {
    throw new Error(`Learning dialogue belongs to another canvas page: ${id}`);
  }
  const frameNumbers = positiveFrameNumbers(
    question.selection?.referencedFrameNumbers?.length > 0
      ? question.selection.referencedFrameNumbers
      : question.selection?.selectedFrameNumbers,
    "question.frameNumbers",
  );
  const answerId = requiredString(run.answerId, "run.answerId");
  const answerPath = join(root, "answers", `${answerId.replaceAll(":", "--")}.json`);
  const answer = await readJson(answerPath, "Learning answer record");
  if (answer.schemaVersion !== "learning.tutor-answer.v1" || answer.questionId !== id) {
    throw new Error(`Learning answer record identity mismatch: ${id}`);
  }
  const questionDigest = requiredString(run.questionSha256, "run.questionSha256");
  const answerDigest = requiredString(run.answerSha256, "run.answerSha256");
  if (!/^[a-f0-9]{64}$/u.test(questionDigest) || !/^[a-f0-9]{64}$/u.test(answerDigest)) {
    throw new Error(`Learning run digests are invalid: ${id}`);
  }
  return {
    questionId: id,
    canvasPageId,
    frameNumbers,
    questionDigest,
    answerDigest,
    questionText: requiredString(question.userQuestion, "question.userQuestion"),
    answer,
    completedAt: requiredString(run.completedAt, "run.completedAt"),
    source: {
      runPath,
      questionPath,
      answerPath,
    },
  };
}

export async function readFeishuLearningDialogueRecords(args = {}, registry, canvasPageId) {
  const bindings = Object.values(registry.dialogues ?? {})
    .filter((dialogue) => dialogue.canvasPageId === canvasPageId)
    .sort((left, right) => left.questionId.localeCompare(right.questionId));
  return Promise.all(bindings.map(async (binding) => {
    const record = await readFeishuLearningDialogueRecord(args, {
      questionId: binding.questionId,
      canvasPageId,
    });
    if (JSON.stringify(binding.frameNumbers) !== JSON.stringify(record.frameNumbers)) {
      throw new Error(`Learning dialogue frame binding changed: ${binding.questionId}`);
    }
    if ((binding.questionDigest ?? null) !== record.questionDigest) {
      throw new Error(`Learning dialogue question digest changed: ${binding.questionId}`);
    }
    if ((binding.answerDigest ?? null) !== record.answerDigest) {
      throw new Error(`Learning dialogue answer digest changed: ${binding.questionId}`);
    }
    return record;
  }));
}
