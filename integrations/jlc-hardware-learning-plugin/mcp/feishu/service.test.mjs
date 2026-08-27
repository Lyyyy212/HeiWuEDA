import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  bindFeishuPageIdentityFromLearningEvidence,
  getFeishuLearningNoteState,
  linkFeishuLearningDialogueFromRecord,
  updateFeishuLearningNoteState,
} from "./service.mjs";

async function writeJson(path, value) {
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

test("Feishu note state previews do not write before initialization", async () => {
  const projectDir = await mkdtemp(join(tmpdir(), "jlc-feishu-service-preview-"));
  try {
    const state = await getFeishuLearningNoteState({
      projectDir,
      projectId: "project-preview",
      projectName: "预览项目",
      schematicPages: [{ canvasPageId: "page:main", pageName: "主控页" }],
      updatedAt: "2026-08-26T00:00:00.000Z",
    });
    assert.equal(state.registryExists, false);
    assert.equal(state.directoryPlan.root.title, "预览项目");
    assert.ok(state.syncPlan.actions.length > 0);
    assert.equal((await getFeishuLearningNoteState({
      projectDir,
      projectId: "project-preview",
      projectName: "预览项目",
    })).registryExists, false);
  } finally {
    await rm(projectDir, { recursive: true, force: true });
  }
});
test("Feishu note state updates persist local bindings without remote writes", async () => {
  const projectDir = await mkdtemp(join(tmpdir(), "jlc-feishu-service-update-"));
  try {
    const initialized = await updateFeishuLearningNoteState({
      projectDir,
      action: "initialize",
      payload: {
        projectId: "00000000000000000000000000000001",
        projectName: "主控板",
        schematicPages: [{ canvasPageId: "page:main", pageName: "主控页" }],
        updatedAt: "2026-08-26T00:00:00.000Z",
      },
    });
    assert.equal(initialized.replayed, false);
    assert.ok(initialized.registry.pages["page:main"]);

    const rebound = await updateFeishuLearningNoteState({
      projectDir,
      action: "bind-page",
      payload: {
        canvasPageId: "page:main",
        pageName: "主控页",
        nodeToken: "FixtureNodeToken01",
        docToken: "doccn-main",
        whiteboardToken: "FixtureWhiteboardToken01",
      },
    });
    assert.equal(rebound.registry.pages["page:main"].docToken, "doccn-main");

    const compact = await updateFeishuLearningNoteState({
      projectDir,
      action: "mark-project-homepage-synced",
      payload: { indexDigest: "d".repeat(64) },
    });
    assert.equal(compact.registry.wiki.layoutMode, "compact-project-homepage");
    assert.equal(compact.registry.wiki.projectHomepageTemplateVersion, 1);

    const state = await getFeishuLearningNoteState({ projectDir });
    assert.equal(state.registryExists, true);
    assert.equal(state.registry.project.projectName, "主控板");
    assert.ok(state.syncPlan.actions.some((action) => action.kind === "doc.page-template.ensure"));

    const replay = await updateFeishuLearningNoteState({
      projectDir,
      action: "initialize",
      payload: { projectId: "00000000000000000000000000000001", projectName: "主控板" },
    });
    assert.equal(replay.replayed, true);
  } finally {
    await rm(projectDir, { recursive: true, force: true });
  }
});

test("verified local evidence binds schematic identity and durable dialogue without Feishu writes", async () => {
  const projectDir = await mkdtemp(join(tmpdir(), "jlc-feishu-service-evidence-"));
  const learningRoot = join(projectDir, ".easyeda-hardware-workbench", "learning");
  const questionUuid = "00000000-0000-4000-8000-000000000001";
  const questionId = `question:${questionUuid}`;
  try {
    await updateFeishuLearningNoteState({
      projectDir,
      action: "initialize",
      payload: {
        projectId: "00000000000000000000000000000001",
        projectName: "主控板",
        schematicPages: [{ canvasPageId: "page:main", pageName: "主控页" }],
      },
    });
    await updateFeishuLearningNoteState({
      projectDir,
      action: "upsert-frame",
      payload: { canvasPageId: "page:main", frameNumber: 4, status: "learning" },
    });
    await Promise.all(["notes", "lark", "runs", "questions", "answers"].map((dir) => (
      mkdir(join(learningRoot, dir), { recursive: true })
    )));
    await writeJson(join(learningRoot, "lark", "page--main-binding.json"), {
      schemaVersion: "learning.lark-binding.v1",
    });
    await writeJson(join(learningRoot, "notes", "page--main-note-package.json"), {
      schemaVersion: "learning.note-package.v1",
      page: { canvasPageId: "page:main", name: "主控页" },
      sourceImages: [{
        shapeId: "image:main",
        evidenceSource: "official-easyeda-export",
        easyedaIdentity: {
          projectUuid: "00000000000000000000000000000001",
          documentUuid: "schematic-main",
          documentType: 1,
        },
      }],
      frames: [{ frameNumber: 4, sourceImageIds: ["image:main"] }],
    });
    const identity = await bindFeishuPageIdentityFromLearningEvidence({
      projectDir,
      canvasPageId: "page:main",
    });
    assert.equal(identity.binding.schematicPageUuid, "schematic-main");
    assert.equal(identity.remoteWritesPerformed, false);

    await writeJson(join(learningRoot, "runs", `question--${questionUuid}.json`), {
      schemaVersion: "learning.question-run.v1",
      questionId,
      canvasPageId: "page:main",
      questionSha256: "1".repeat(64),
      answerId: "answer:offline:test",
      answerSha256: "2".repeat(64),
      completedAt: "2026-08-27T00:00:00Z",
    });
    await writeJson(join(learningRoot, "questions", `question-${questionUuid}.json`), {
      schemaVersion: "jlc.hardware-learning-question-record.v1",
      question: {
        questionId,
        userQuestion: "学习框 4 是什么？",
        selection: { canvasPageId: "page:main", referencedFrameNumbers: [4] },
      },
    });
    await writeJson(join(learningRoot, "answers", "answer--offline--test.json"), {
      schemaVersion: "learning.tutor-answer.v1",
      questionId,
      summary: "回答",
    });
    const linked = await linkFeishuLearningDialogueFromRecord({
      projectDir,
      canvasPageId: "page:main",
      questionId,
    });
    assert.equal(linked.dialogue.questionDigest, "1".repeat(64));
    assert.equal(linked.dialogue.answerDigest, "2".repeat(64));
    assert.equal(linked.remoteWritesPerformed, false);
  } finally {
    await rm(projectDir, { recursive: true, force: true });
  }
});
