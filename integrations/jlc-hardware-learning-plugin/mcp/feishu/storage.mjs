import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

import { resolveHardwareLearningPaths } from "../lib/canvas-storage.mjs";
import { validateFeishuLearningRegistry } from "./note-model.mjs";

const REGISTRY_FILE_NAME = "feishu-learning-note-registry.json";

export function resolveFeishuLearningRegistryFile(args = {}) {
  const { projectDir } = resolveHardwareLearningPaths(args);
  return join(projectDir, ".easyeda-hardware-workbench", "learning", REGISTRY_FILE_NAME);
}
export async function readFeishuLearningRegistry(args = {}) {
  const path = resolveFeishuLearningRegistryFile(args);
  try {
    const registry = JSON.parse(await readFile(path, "utf8"));
    validateFeishuLearningRegistry(registry);
    return { registry, path, exists: true };
  } catch (error) {
    if (error?.code === "ENOENT") return { registry: null, path, exists: false };
    throw error;
  }
}

export async function saveFeishuLearningRegistry(args = {}, registry) {
  validateFeishuLearningRegistry(registry);
  const path = resolveFeishuLearningRegistryFile(args);
  await mkdir(dirname(path), { recursive: true });
  const temporaryPath = `${path}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(registry, null, 2)}\n`, "utf8");
  await rename(temporaryPath, path);
  return { ok: true, path, registry };
}
