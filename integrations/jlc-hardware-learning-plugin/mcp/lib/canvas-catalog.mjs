import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import {
  nonEmptyString,
  pathResolve,
  setActiveHardwareLearningCanvasDir,
} from "./canvas-storage.mjs";

const CATALOG_VERSION = 1;
const DEFAULT_CANVAS_ID = "default";
const DEFAULT_CANVAS_NAME = "默认画板";
const CANVAS_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function catalogPaths(projectDirValue) {
  const projectDir = pathResolve(projectDirValue);
  const rootDir = join(projectDir, "canvases");
  return {
    projectDir,
    rootDir,
    catalogFile: join(rootDir, "manifest.json"),
    trashDir: join(rootDir, ".trash"),
  };
}

function normalizeCanvasName(value) {
  const name = nonEmptyString(value);
  if (!name) throw new Error("画板名称不能为空。");
  if (name.length > 64) throw new Error("画板名称不能超过 64 个字符。");
  return name;
}

function isManagedCanvasId(value) {
  return CANVAS_ID_PATTERN.test(String(value || ""));
}

function defaultCatalog() {
  return {
    version: CATALOG_VERSION,
    activeCanvasId: DEFAULT_CANVAS_ID,
    defaultCanvasName: DEFAULT_CANVAS_NAME,
    canvases: [],
  };
}

function sanitizeCatalog(value) {
  if (!value || typeof value !== "object") return defaultCatalog();
  const seen = new Set();
  const canvases = Array.isArray(value.canvases)
    ? value.canvases.flatMap((entry) => {
        if (!isManagedCanvasId(entry?.id) || seen.has(entry.id)) return [];
        let name;
        try {
          name = normalizeCanvasName(entry.name);
        } catch {
          return [];
        }
        seen.add(entry.id);
        return [{
          id: entry.id,
          name,
          createdAt: nonEmptyString(entry.createdAt),
          updatedAt: nonEmptyString(entry.updatedAt),
        }];
      })
    : [];
  const activeCanvasId = value.activeCanvasId === DEFAULT_CANVAS_ID || seen.has(value.activeCanvasId)
    ? value.activeCanvasId
    : DEFAULT_CANVAS_ID;
  let defaultCanvasName = DEFAULT_CANVAS_NAME;
  try {
    defaultCanvasName = normalizeCanvasName(value.defaultCanvasName || DEFAULT_CANVAS_NAME);
  } catch {
    defaultCanvasName = DEFAULT_CANVAS_NAME;
  }
  return {
    version: CATALOG_VERSION,
    activeCanvasId,
    defaultCanvasName,
    canvases,
  };
}

async function readCatalog(projectDirValue) {
  const paths = catalogPaths(projectDirValue);
  try {
    const value = JSON.parse(await readFile(paths.catalogFile, "utf8"));
    return { paths, catalog: sanitizeCatalog(value) };
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    return { paths, catalog: defaultCatalog() };
  }
}

async function writeCatalog(paths, catalog) {
  await mkdir(dirname(paths.catalogFile), { recursive: true });
  const tempFile = `${paths.catalogFile}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(tempFile, `${JSON.stringify(catalog, null, 2)}\n`, "utf8");
  await rename(tempFile, paths.catalogFile);
}

function canvasDirFor(paths, canvasId) {
  if (canvasId === DEFAULT_CANVAS_ID) return join(paths.projectDir, "canvas");
  if (!isManagedCanvasId(canvasId)) throw new Error("无效的画板 ID。");
  const target = resolve(paths.rootDir, canvasId);
  if (dirname(target) !== resolve(paths.rootDir)) throw new Error("画板目录越界。");
  return target;
}

function canvasEntry(paths, catalog, canvasId) {
  if (canvasId === DEFAULT_CANVAS_ID) {
    return {
      id: DEFAULT_CANVAS_ID,
      name: catalog.defaultCanvasName,
      canvasDir: canvasDirFor(paths, DEFAULT_CANVAS_ID),
      isDefault: true,
      canDelete: false,
    };
  }
  if (!isManagedCanvasId(canvasId)) throw new Error("无效的画板 ID。");
  const entry = catalog.canvases.find((candidate) => candidate.id === canvasId);
  if (!entry) throw new Error("找不到指定画板。");
  return {
    ...entry,
    canvasDir: canvasDirFor(paths, entry.id),
    isDefault: false,
    canDelete: true,
  };
}

function assertUniqueName(catalog, name, exceptCanvasId = null) {
  const key = name.toLocaleLowerCase("zh-CN");
  const entries = [
    { id: DEFAULT_CANVAS_ID, name: catalog.defaultCanvasName },
    ...catalog.canvases,
  ];
  if (entries.some((entry) => entry.id !== exceptCanvasId && entry.name.toLocaleLowerCase("zh-CN") === key)) {
    throw new Error(`画板名称“${name}”已存在。`);
  }
}

function catalogResult(paths, catalog) {
  const canvases = [
    canvasEntry(paths, catalog, DEFAULT_CANVAS_ID),
    ...catalog.canvases.map((entry) => canvasEntry(paths, catalog, entry.id)),
  ];
  const activeCanvas = canvases.find((entry) => entry.id === catalog.activeCanvasId) || canvases[0];
  setActiveHardwareLearningCanvasDir(paths.projectDir, activeCanvas.canvasDir);
  return {
    ok: true,
    version: CATALOG_VERSION,
    projectDir: paths.projectDir,
    catalogFile: paths.catalogFile,
    activeCanvasId: activeCanvas.id,
    activeCanvas,
    canvases,
  };
}

export async function listHardwareLearningCanvases(args = {}) {
  const projectDir = nonEmptyString(args.projectDir) || process.cwd();
  const { paths, catalog } = await readCatalog(projectDir);
  return catalogResult(paths, catalog);
}

export async function createHardwareLearningCanvas(args = {}, nameValue) {
  const projectDir = nonEmptyString(args.projectDir) || process.cwd();
  const name = normalizeCanvasName(nameValue);
  const { paths, catalog } = await readCatalog(projectDir);
  assertUniqueName(catalog, name);
  const now = new Date().toISOString();
  const id = randomUUID();
  await mkdir(canvasDirFor(paths, id), { recursive: true });
  catalog.canvases.push({ id, name, createdAt: now, updatedAt: now });
  catalog.activeCanvasId = id;
  await writeCatalog(paths, catalog);
  return catalogResult(paths, catalog);
}

export async function activateHardwareLearningCanvas(args = {}, canvasIdValue) {
  const projectDir = nonEmptyString(args.projectDir) || process.cwd();
  const canvasId = String(canvasIdValue || "");
  const { paths, catalog } = await readCatalog(projectDir);
  const entry = canvasEntry(paths, catalog, canvasId);
  await mkdir(entry.canvasDir, { recursive: true });
  catalog.activeCanvasId = canvasId;
  await writeCatalog(paths, catalog);
  return catalogResult(paths, catalog);
}

export async function renameHardwareLearningCanvas(args = {}, canvasIdValue, nameValue) {
  const projectDir = nonEmptyString(args.projectDir) || process.cwd();
  const canvasId = String(canvasIdValue || "");
  const name = normalizeCanvasName(nameValue);
  const { paths, catalog } = await readCatalog(projectDir);
  canvasEntry(paths, catalog, canvasId);
  assertUniqueName(catalog, name, canvasId);
  const now = new Date().toISOString();
  if (canvasId === DEFAULT_CANVAS_ID) {
    catalog.defaultCanvasName = name;
  } else {
    const entry = catalog.canvases.find((candidate) => candidate.id === canvasId);
    entry.name = name;
    entry.updatedAt = now;
  }
  await writeCatalog(paths, catalog);
  return catalogResult(paths, catalog);
}

export async function recycleHardwareLearningCanvas(args = {}, canvasIdValue) {
  const projectDir = nonEmptyString(args.projectDir) || process.cwd();
  const canvasId = String(canvasIdValue || "");
  if (canvasId === DEFAULT_CANVAS_ID) throw new Error("默认画板不能删除。");
  const { paths, catalog } = await readCatalog(projectDir);
  const entry = canvasEntry(paths, catalog, canvasId);
  await mkdir(paths.trashDir, { recursive: true });
  const suffix = new Date().toISOString().replace(/[:.]/g, "-");
  const recycledDir = join(paths.trashDir, `${canvasId}-${suffix}`);
  try {
    await stat(entry.canvasDir);
    await rename(entry.canvasDir, recycledDir);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  catalog.canvases = catalog.canvases.filter((candidate) => candidate.id !== canvasId);
  if (catalog.activeCanvasId === canvasId) catalog.activeCanvasId = DEFAULT_CANVAS_ID;
  await writeCatalog(paths, catalog);
  return {
    ...catalogResult(paths, catalog),
    recycledCanvasId: canvasId,
    recycledCanvasDir: entry.canvasDir,
    recycledDir,
  };
}
