import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import {
  activateHardwareLearningCanvas,
  createHardwareLearningCanvas,
  listHardwareLearningCanvases,
  recycleHardwareLearningCanvas,
  renameHardwareLearningCanvas,
} from "./canvas-catalog.mjs";
import { clearActiveHardwareLearningCanvasDir, resolveHardwareLearningPaths } from "./canvas-storage.mjs";

test("canvas catalog creates, activates, renames, persists, and recycles independent canvases", async () => {
  const projectDir = await mkdtemp(path.join(tmpdir(), "jlc-learning-catalog-"));
  try {
    const initial = await listHardwareLearningCanvases({ projectDir });
    assert.equal(initial.activeCanvasId, "default");
    assert.equal(initial.canvases.length, 1);
    assert.equal(initial.activeCanvas.name, "默认画板");

    const created = await createHardwareLearningCanvas({ projectDir }, "电源学习");
    const canvasId = created.activeCanvasId;
    assert.match(canvasId, /^[0-9a-f-]{36}$/i);
    assert.match(created.activeCanvas.canvasDir, /[\\/]canvases[\\/]/);
    assert.equal(resolveHardwareLearningPaths({ projectDir }).canvasDir, created.activeCanvas.canvasDir);
    await stat(created.activeCanvas.canvasDir);

    const renamed = await renameHardwareLearningCanvas({ projectDir }, canvasId, "模拟前端");
    assert.equal(renamed.activeCanvas.name, "模拟前端");
    await activateHardwareLearningCanvas({ projectDir }, "default");

    clearActiveHardwareLearningCanvasDir(projectDir);
    const reopened = await listHardwareLearningCanvases({ projectDir });
    assert.equal(reopened.activeCanvasId, "default");
    assert.equal(reopened.canvases[1].name, "模拟前端");

    await activateHardwareLearningCanvas({ projectDir }, canvasId);
    const recycled = await recycleHardwareLearningCanvas({ projectDir }, canvasId);
    assert.equal(recycled.activeCanvasId, "default");
    assert.equal(recycled.canvases.length, 1);
    await stat(recycled.recycledDir);
    await assert.rejects(stat(created.activeCanvas.canvasDir), { code: "ENOENT" });
    const manifest = JSON.parse(await readFile(path.join(projectDir, "canvases", "manifest.json"), "utf8"));
    assert.equal(manifest.canvases.length, 0);
  } finally {
    clearActiveHardwareLearningCanvasDir(projectDir);
    await rm(projectDir, { recursive: true, force: true });
  }
});

test("canvas catalog rejects duplicate names, invalid ids, and default deletion", async () => {
  const projectDir = await mkdtemp(path.join(tmpdir(), "jlc-learning-catalog-guard-"));
  try {
    await createHardwareLearningCanvas({ projectDir }, "射频");
    await assert.rejects(createHardwareLearningCanvas({ projectDir }, "射频"), /已存在/);
    await assert.rejects(activateHardwareLearningCanvas({ projectDir }, "../escape"), /无效的画板 ID/);
    await assert.rejects(recycleHardwareLearningCanvas({ projectDir }, "default"), /不能删除/);
  } finally {
    clearActiveHardwareLearningCanvasDir(projectDir);
    await rm(projectDir, { recursive: true, force: true });
  }
});
