import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { readFeishuLearningDialogueRecord } from "./dialogue-records.mjs";

const UUID = "00000000-0000-4000-8000-000000000001";
const QUESTION_ID = `question:${UUID}`;

async function writeJson(path, value) {
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

test("durable dialogue loader verifies run, question, answer, page, frames and digests", async () => {
  const projectDir = await mkdtemp(join(tmpdir(), "jlc-feishu-dialogue-"));
  const root = join(projectDir, ".easyeda-hardware-workbench", "learning");
  try {
    await Promise.all(["runs", "questions", "answers"].map((dir) => mkdir(join(root, dir), { recursive: true })));
    await writeJson(join(root, "runs", `question--${UUID}.json`), {
      schemaVersion: "learning.question-run.v1",
      questionId: QUESTION_ID,
      canvasPageId: "page:main",
      questionSha256: "1".repeat(64),
      answerId: "answer:offline:test",
      answerSha256: "2".repeat(64),
      completedAt: "2026-08-27T00:00:00Z",
    });
    await writeJson(join(root, "questions", `question-${UUID}.json`), {
      schemaVersion: "jlc.hardware-learning-question-record.v1",
      question: {
        questionId: QUESTION_ID,
        userQuestion: "学习框 4 是什么？",
        selection: {
          canvasPageId: "page:main",
          referencedFrameNumbers: [4],
        },
      },
    });
    await writeJson(join(root, "answers", "answer--offline--test.json"), {
      schemaVersion: "learning.tutor-answer.v1",
      questionId: QUESTION_ID,
      summary: "回答摘要",
    });
    const record = await readFeishuLearningDialogueRecord({ projectDir }, {
      questionId: QUESTION_ID,
      canvasPageId: "page:main",
    });
    assert.deepEqual(record.frameNumbers, [4]);
    assert.equal(record.questionDigest, "1".repeat(64));
    assert.equal(record.answerDigest, "2".repeat(64));
    assert.equal(record.answer.summary, "回答摘要");
    await assert.rejects(
      () => readFeishuLearningDialogueRecord({ projectDir }, {
        questionId: QUESTION_ID,
        canvasPageId: "page:other",
      }),
      /another canvas page/u,
    );
  } finally {
    await rm(projectDir, { recursive: true, force: true });
  }
});
