import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createFeishuLearningRegistry } from "./note-model.mjs";
import {
  readFeishuLearningRegistry,
  resolveFeishuLearningRegistryFile,
  saveFeishuLearningRegistry,
} from "./storage.mjs";

test("Feishu note registries persist atomically under the project learning directory", async () => {
  const projectDir = await mkdtemp(join(tmpdir(), "jlc-feishu-note-registry-"));
  try {
    const registry = createFeishuLearningRegistry(
      { projectId: "project-1", projectName: "主控板" },
      { updatedAt: "2026-08-26T00:00:00.000Z" },
    );
    const before = await readFeishuLearningRegistry({ projectDir });
    assert.equal(before.exists, false);
    const stored = await saveFeishuLearningRegistry({ projectDir }, registry);
    assert.equal(stored.path, resolveFeishuLearningRegistryFile({ projectDir }));
    const raw = JSON.parse(await readFile(stored.path, "utf8"));
    assert.equal(raw.project.projectName, "主控板");
    const after = await readFeishuLearningRegistry({ projectDir });
    assert.equal(after.exists, true);
    assert.deepEqual(after.registry, registry);
  } finally {
    await rm(projectDir, { recursive: true, force: true });
  }
});
test("invalid registries are rejected before any file is written", async () => {
  const projectDir = await mkdtemp(join(tmpdir(), "jlc-feishu-note-invalid-"));
  try {
    await assert.rejects(
      () => saveFeishuLearningRegistry({ projectDir }, { schemaVersion: "wrong" }),
      /registry must use/u,
    );
    assert.equal((await readFeishuLearningRegistry({ projectDir })).exists, false);
  } finally {
    await rm(projectDir, { recursive: true, force: true });
  }
});
