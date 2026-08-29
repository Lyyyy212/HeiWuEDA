import { execFile } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { appendFile, copyFile, mkdir, mkdtemp, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { homedir, platform, tmpdir } from "node:os";
import { basename, extname, join, relative, resolve, sep } from "node:path";
import { promisify } from "node:util";

import { registerAppTool } from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { generateKeyBetween } from "fractional-indexing";
import { z } from "zod";

import {
  CANVAS_BRAND_NAME,
  CANVAS_EXPORT_DIRECTORY_NAME,
  CANVAS_WIDGET_TITLE,
} from "../shared/branding.mjs";
import {
  HARDWARE_LEARNING_STATIC_BUILD_DIR,
  hardwareLearningStaticHtml,
} from "./lib/hardware-learning-static-widget.mjs";
import {
  nonEmptyString,
  ensureHardwareLearningCanvasState,
  pageAssetUrl,
  pageDirName,
  pathResolve,
  readHardwareLearningCanvasState,
  readHardwareLearningPageAsset,
  readHardwareLearningSelectionState,
  readHardwareLearningViewState,
  resolveCanvasDir,
  resolveHardwareLearningPaths,
  saveHardwareLearningCanvasSnapshot,
  writeHardwareLearningPageAsset,
  writeHardwareLearningSelectionState,
  writeHardwareLearningViewState,
} from "./lib/canvas-storage.mjs";
import {
  attachHardwareLearningPageNetlist,
  readHardwareLearningPageNetlist,
} from "./lib/page-netlist.mjs";
import {
  activateHardwareLearningCanvas,
  createHardwareLearningCanvas,
  listHardwareLearningCanvases,
  recycleHardwareLearningCanvas,
  renameHardwareLearningCanvas,
} from "./lib/canvas-catalog.mjs";
import { pluginPath } from "./lib/plugin-root.mjs";
import { inlineWidget, registerWidgetResource } from "./lib/widget-resource.mjs";
import {
  acknowledgeLearningAnnotations,
  insertLearningAnnotations,
  learningAnnotationKinds,
  pullLearningAnnotations,
  saveLearningQuestion,
} from "./learning/storage.mjs";
import {
  buildConversationLearningQuestion,
  buildQuickLearningContext,
  conversationLearningIntents,
  conversationLearningLevels,
  conversationLearningResponseModes,
} from "./learning/conversation-question.mjs";
import {
  bindFeishuPageIdentityFromLearningEvidence,
  executeFeishuLearningNoteMigration,
  executeFeishuLearningNoteSync,
  getFeishuLearningNoteState,
  inspectFeishuLearningNoteTarget,
  linkFeishuLearningDialogueFromRecord,
  previewFeishuLearningNoteMigration,
  previewFeishuLearningNoteSync,
  updateFeishuLearningNoteState,
} from "./feishu/service.mjs";

const TOOL_RENDER_WIDGET = "render_hardware_learning_canvas_widget";
const TOOL_GET_CANVAS_STATE = "get_hardware_learning_canvas_state";
const TOOL_SAVE_CANVAS_STATE = "save_hardware_learning_canvas_state";
const TOOL_SAVE_SELECTION_STATE = "save_hardware_learning_selection_state";
const TOOL_SAVE_VIEW_STATE = "save_hardware_learning_view_state";
const TOOL_GET_SELECTION = "get_hardware_learning_selection";
const TOOL_INSERT_IMAGE = "insert_hardware_learning_image";
const TOOL_SAVE_REFERENCE_IMAGE = "save_hardware_learning_reference_image";
const TOOL_READ_PAGE_ASSET = "read_hardware_learning_page_asset";
const TOOL_CHOOSE_EXPORT_DIRECTORY = "choose_hardware_learning_export_directory";
const TOOL_DOWNLOAD_FILE = "download_hardware_learning_file";
const TOOL_COPY_IMAGE_TO_CLIPBOARD = "copy_hardware_learning_image_to_clipboard";
const TOOL_SAVE_LEARNING_QUESTION = "save_hardware_learning_question";
const TOOL_INSERT_LEARNING_ANNOTATIONS = "insert_hardware_learning_annotations";
const TOOL_MANAGE_CANVASES = "manage_hardware_learning_canvases";
const TOOL_ATTACH_PAGE_NETLIST = "attach_hardware_learning_page_netlist";
const TOOL_READ_PAGE_NETLIST = "read_hardware_learning_page_netlist";
const TOOL_GET_FEISHU_NOTE_STATE = "get_feishu_learning_note_state";
const TOOL_UPDATE_FEISHU_NOTE_STATE = "update_feishu_learning_note_state";
const TOOL_INSPECT_FEISHU_NOTE_TARGET = "inspect_feishu_learning_note_target";
const TOOL_PREVIEW_FEISHU_NOTE_MIGRATION = "preview_feishu_learning_note_migration";
const TOOL_EXECUTE_FEISHU_NOTE_MIGRATION = "execute_feishu_learning_note_migration";
const TOOL_LINK_FEISHU_DIALOGUE_FROM_RECORD = "link_feishu_learning_dialogue_from_record";
const TOOL_BIND_FEISHU_PAGE_IDENTITY = "bind_feishu_page_identity_from_learning_evidence";
const TOOL_PREVIEW_FEISHU_NOTE_SYNC = "preview_feishu_learning_note_sync";
const TOOL_EXECUTE_FEISHU_NOTE_SYNC = "execute_feishu_learning_note_sync";

const execFileAsync = promisify(execFile);

const PAGE_ID_PREFIX = "page:";
const HARDWARE_LEARNING_HTML_DRAFT_URL_ORIGIN = "http://jlc-hardware-learning.local";
const DEFAULT_DISPLAY_MODE = "fullscreen";
const HARDWARE_LEARNING_CONNECT_DOMAINS = [];
const HARDWARE_LEARNING_RESOURCE_DOMAINS = ["data:", "blob:"];
const HARDWARE_LEARNING_FRAME_DOMAINS = [];

const projectArgsSchema = {
  projectDir: z.string().trim().optional(),
  canvasDir: z.string().trim().optional(),
};

const displayModeSchema = z.enum(["fullscreen", "inline"]);
const widgetModeSchema = z.enum(["default", "hardware-learning"]);
const HARDWARE_LEARNING_MODE = "hardware-learning";
const hardwareLearningCanvasDirs = new Set();
const activeHardwareLearningDownloads = new Map();
const completedHardwareLearningDownloads = new Map();
const approvedHardwareLearningExportDirectories = new Map();
const MAX_CHUNKED_DOWNLOAD_BYTES = 128 * 1024 * 1024;
const MAX_DOWNLOAD_CHUNK_BYTES = 1024 * 1024;
const MAX_COMPLETED_DOWNLOAD_RESULTS = 64;
const MAX_APPROVED_EXPORT_DIRECTORIES = 64;
const EXPORT_DIRECTORY_TOKEN_TTL_MS = 8 * 60 * 60 * 1000;
const LEARNING_EVIDENCE_SOURCES = new Set([
  "user-provided-local-image",
  "official-easyeda-export",
  "official-easyeda-pdf-render",
  "official-datasheet-figure",
]);

function isHardwareLearningTarget(args = {}) {
  return hardwareLearningCanvasDirs.has(resolveHardwareLearningPaths(args).canvasDir);
}

function assertLearningGenerationAllowed(args, capability) {
  if (!isHardwareLearningTarget(args)) return;
  if (capability === "image" && LEARNING_EVIDENCE_SOURCES.has(args.evidenceSource)) return;
  throw new Error(`JLC Hardware Learning hardware-learning mode blocks ${capability} generation or insertion.`);
}

const pluginManifest = JSON.parse(
  readFileSync(pluginPath(".codex-plugin", "plugin.json"), "utf8"),
);
const HARDWARE_LEARNING_WIDGET_URI = hardwareLearningWidgetResourceUri(pluginManifest.version);

function hardwareLearningWidgetResourceUri(version) {
  const cacheKey = String(version || "")
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (!cacheKey) throw new Error("JLC Hardware Learning widget resource requires a plugin version.");
  return `ui://widget/jlc-hardware-learning/canvas-${cacheKey}.html`;
}

const server = new McpServer(
  {
    name: pluginManifest.name,
    version: pluginManifest.version,
  },
  {
    instructions:
      "jlc_hardware_learning_mcp serves the JLC Hardware Learning canvas. Reuse an open widget, keep EasyEDA access read-only, and use the hardware-learning state, selection, evidence-image, annotation, and export tools for project-local operations.",
  },
);

registerHardwareLearningWidget(server);
registerHardwareLearningStateTools(server);
registerHardwareLearningImageTools(server);
registerHardwareLearningTools(server);
registerFeishuLearningNoteTools(server);

const transport = new StdioServerTransport();
await server.connect(transport);

function finiteNumber(value, fallback) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function isSafeChildPath(parent, child) {
  const pathToChild = relative(parent, child);
  return pathToChild && !pathToChild.startsWith("..") && !pathToChild.includes(`..${sep}`);
}

function sanitizeFileName(name, fallbackName = "image.png") {
  const rawName = basename(String(name || fallbackName));
  const extension = extname(rawName) || extname(fallbackName) || ".png";
  const baseName = rawName
    .slice(0, rawName.length - extname(rawName).length)
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `${baseName || "image"}${extension}`;
}

function sanitizeDirectoryName(name, fallbackName = `${CANVAS_BRAND_NAME}导出`) {
  return basename(String(name || fallbackName))
    .replace(/[<>:"/\\|?*\u0000-\u001f]+/g, "-")
    .replace(/[. ]+$/g, "")
    .trim()
    .slice(0, 120) || fallbackName;
}

function pruneApprovedExportDirectories(now = Date.now()) {
  for (const [token, record] of approvedHardwareLearningExportDirectories) {
    if (record.expiresAt <= now) approvedHardwareLearningExportDirectories.delete(token);
  }
  while (approvedHardwareLearningExportDirectories.size > MAX_APPROVED_EXPORT_DIRECTORIES) {
    approvedHardwareLearningExportDirectories.delete(approvedHardwareLearningExportDirectories.keys().next().value);
  }
}

function exportDirectoryStorageKey(args = {}) {
  return resolveCanvasDir(args);
}

function approvedExportDirectory(args = {}) {
  const token = nonEmptyString(args.directoryToken);
  if (!token) return null;
  pruneApprovedExportDirectories();
  const record = approvedHardwareLearningExportDirectories.get(token);
  if (!record || record.storageKey !== exportDirectoryStorageKey(args)) {
    throw new Error(`${CANVAS_BRAND_NAME}导出位置已失效，请重新选择文件夹。`);
  }
  return record;
}

async function chooseHardwareLearningExportDirectory(args = {}) {
  const defaultDirectoryPath = join(homedir(), "Downloads", CANVAS_EXPORT_DIRECTORY_NAME);
  await mkdir(defaultDirectoryPath, { recursive: true });
  const directoryPath = await showSystemDirectoryPicker(defaultDirectoryPath);
  if (!directoryPath) {
    return { ok: true, canceled: true, defaultDirectoryPath };
  }
  const selectedPath = resolve(directoryPath);
  const selectedStats = await stat(selectedPath);
  if (!selectedStats.isDirectory()) throw new Error(`选择的${CANVAS_BRAND_NAME}导出位置不是文件夹。`);
  const directoryToken = randomUUID();
  const expiresAt = Date.now() + EXPORT_DIRECTORY_TOKEN_TTL_MS;
  approvedHardwareLearningExportDirectories.set(directoryToken, {
    directoryPath: selectedPath,
    expiresAt,
    storageKey: exportDirectoryStorageKey(args),
  });
  pruneApprovedExportDirectories();
  return {
    ok: true,
    canceled: false,
    directoryName: basename(selectedPath),
    directoryPath: selectedPath,
    directoryToken,
    expiresAt: new Date(expiresAt).toISOString(),
  };
}

async function showSystemDirectoryPicker(defaultDirectoryPath) {
  const systemPlatform = platform();
  if (systemPlatform === "win32") {
    const script = [
      "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()",
      "Add-Type -AssemblyName System.Windows.Forms",
      "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog",
      `$dialog.Description = '选择${CANVAS_BRAND_NAME}导出位置'`,
      "$dialog.ShowNewFolderButton = $true",
      "$dialog.SelectedPath = $env:JLC_HARDWARE_LEARNING_EXPORT_DEFAULT_PATH",
      "try { if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($dialog.SelectedPath)) } } finally { $dialog.Dispose() }",
    ].join("; ");
    const { stdout } = await execFileAsync(
      "powershell.exe",
      ["-NoProfile", "-STA", "-Command", script],
      {
        env: { ...process.env, JLC_HARDWARE_LEARNING_EXPORT_DEFAULT_PATH: defaultDirectoryPath },
        timeout: 60_000,
        windowsHide: true,
      },
    );
    const encodedPath = stdout.trim();
    return encodedPath ? Buffer.from(encodedPath, "base64").toString("utf8") : null;
  }
  if (systemPlatform === "darwin") {
    try {
      const { stdout } = await execFileAsync(
        "/usr/bin/osascript",
        ["-e", `POSIX path of (choose folder with prompt \"选择${CANVAS_BRAND_NAME}导出位置\")`],
        { timeout: 60_000 },
      );
      return stdout.trim() || null;
    } catch (error) {
      if (/User canceled|(-128)/iu.test(String(error?.stderr || error?.message))) return null;
      throw error;
    }
  }
  try {
    const { stdout } = await execFileAsync(
      "zenity",
      ["--file-selection", "--directory", `--title=选择${CANVAS_BRAND_NAME}导出位置`, `--filename=${defaultDirectoryPath}${sep}`],
      { timeout: 60_000 },
    );
    return stdout.trim() || null;
  } catch (error) {
    if (Number(error?.code) === 1) return null;
    throw new Error(`当前系统无法打开${CANVAS_BRAND_NAME}文件夹选择器：${error instanceof Error ? error.message : String(error)}`);
  }
}

function sanitizeHtmlFileName(name, fallbackName = "draft.html") {
  const safeName = sanitizeFileName(name, fallbackName);
  return /\.html?$/i.test(safeName) ? safeName : `${safeName.replace(/\.[^.]+$/, "")}.html`;
}

function sanitizeIdPart(value, fallback = "image") {
  return String(value || fallback)
    .replace(/\.[^.]+$/, "")
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || fallback;
}

function mimeTypeForFile(filePath) {
  switch (extname(filePath).toLowerCase()) {
    case ".apng":
      return "image/apng";
    case ".avif":
      return "image/avif";
    case ".gif":
      return "image/gif";
    case ".jpg":
    case ".jpeg":
      return "image/jpeg";
    case ".png":
      return "image/png";
    case ".webp":
      return "image/webp";
    case ".svg":
      return "image/svg+xml";
    case ".htm":
    case ".html":
      return "text/html";
    default:
      return "application/octet-stream";
  }
}

function parseDownloadDataUrl(dataUrl) {
  const match = /^data:([^;,]+)?((?:;[^,]*)?),(.*)$/s.exec(String(dataUrl || ""));
  if (!match) throw new Error("Invalid download dataUrl.");
  const mimeType = nonEmptyString(match[1]) || "application/octet-stream";
  const parameters = match[2] || "";
  const payload = match[3] || "";
  const buffer = /;base64(?:;|$)/i.test(parameters)
    ? Buffer.from(payload, "base64")
    : Buffer.from(decodeURIComponent(payload), "utf8");
  return { buffer, mimeType };
}

async function uniqueFilePath(dir, requestedName) {
  const safeName = sanitizeFileName(requestedName);
  const ext = extname(safeName);
  const base = safeName.slice(0, safeName.length - ext.length);
  let candidate = safeName;
  let counter = 2;
  while (true) {
    const candidatePath = join(dir, candidate);
    try {
      await stat(candidatePath);
      candidate = `${base}-v${counter}${ext}`;
      counter += 1;
    } catch (error) {
      if (error?.code === "ENOENT") return { fileName: candidate, filePath: candidatePath };
      throw error;
    }
  }
}

async function uniqueDirectoryPath(dir, requestedName) {
  const safeName = sanitizeDirectoryName(requestedName);
  let candidate = safeName;
  let counter = 2;
  while (true) {
    const candidatePath = join(dir, candidate);
    try {
      await stat(candidatePath);
      candidate = `${safeName}-${counter}`;
      counter += 1;
    } catch (error) {
      if (error?.code === "ENOENT") {
        return { directoryName: candidate, directoryPath: candidatePath };
      }
      throw error;
    }
  }
}

function uniqueRecordId(store, prefix, seed) {
  const cleanSeed = sanitizeIdPart(seed);
  let candidate = `${prefix}:${cleanSeed}`;
  let counter = 2;
  while (store[candidate]) {
    candidate = `${prefix}:${cleanSeed}-${counter}`;
    counter += 1;
  }
  return candidate;
}

function getRecord(store, id, label) {
  const record = store[id];
  if (!record) throw new Error(`Missing ${label}: ${id}`);
  return record;
}

function findPageIdForShape(store, shapeId) {
  let record = getRecord(store, shapeId, "shape");
  const visited = new Set();
  while (record && !visited.has(record.id)) {
    visited.add(record.id);
    if (record.typeName === "page") return record.id;
    const parentId = record.parentId;
    if (!parentId) break;
    const parent = store[parentId];
    if (parent?.typeName === "page") return parent.id;
    record = parent;
  }
  return null;
}

function getPageShapes(store, pageId) {
  const shapes = [];
  const byParent = new Map();
  for (const record of Object.values(store)) {
    if (record?.typeName !== "shape") continue;
    const siblings = byParent.get(record.parentId) ?? [];
    siblings.push(record);
    byParent.set(record.parentId, siblings);
  }
  const queue = [...(byParent.get(pageId) ?? [])];
  while (queue.length > 0) {
    const shape = queue.shift();
    shapes.push(shape);
    queue.push(...(byParent.get(shape.id) ?? []));
  }
  return shapes;
}

function localBoundsForShape(shape) {
  if (!shape || shape.typeName !== "shape") return null;
  const learningBounds = shape.meta?.hardwareLearningBounds;
  if (
    learningBounds &&
    [learningBounds.x, learningBounds.y, learningBounds.w, learningBounds.h].every(Number.isFinite)
  ) {
    return {
      x: learningBounds.x,
      y: learningBounds.y,
      w: Math.max(1, learningBounds.w),
      h: Math.max(1, learningBounds.h),
    };
  }
  if (shape.type === "arrow") {
    const start = shape.props?.start ?? { x: 0, y: 0 };
    const end = shape.props?.end ?? { x: 0, y: 0 };
    const minX = Math.min(start.x ?? 0, end.x ?? 0);
    const minY = Math.min(start.y ?? 0, end.y ?? 0);
    const maxX = Math.max(start.x ?? 0, end.x ?? 0);
    const maxY = Math.max(start.y ?? 0, end.y ?? 0);
    return { x: minX, y: minY, w: Math.max(1, maxX - minX), h: Math.max(1, maxY - minY) };
  }
  const w = finiteNumber(shape.props?.w, shape.type === "text" ? 160 : 1);
  const h = finiteNumber(shape.props?.h, shape.type === "text" ? 40 : 1);
  return { x: 0, y: 0, w, h };
}

function pageBoundsForShape(store, shape) {
  const local = localBoundsForShape(shape);
  if (!local) return null;
  let x = finiteNumber(shape.x, 0) + local.x;
  let y = finiteNumber(shape.y, 0) + local.y;
  let parent = store[shape.parentId];
  const visited = new Set([shape.id]);
  while (parent?.typeName === "shape" && !visited.has(parent.id)) {
    visited.add(parent.id);
    x += finiteNumber(parent.x, 0);
    y += finiteNumber(parent.y, 0);
    parent = store[parent.parentId];
  }
  return { x, y, w: local.w, h: local.h };
}

function rectsOverlap(a, b, padding = 0) {
  return !(
    a.x + a.w + padding <= b.x ||
    b.x + b.w + padding <= a.x ||
    a.y + a.h + padding <= b.y ||
    b.y + b.h + padding <= a.y
  );
}

function chooseIndex(store, parentId) {
  const siblingIndexes = Object.values(store)
    .filter((record) => record?.typeName === "shape" && record.parentId === parentId && typeof record.index === "string")
    .map((record) => record.index)
    .sort();
  return generateKeyBetween(siblingIndexes.at(-1) ?? null, null);
}

function firstSelectedShapeId(selection) {
  return selection?.selectedShapes?.length === 1 ? selection.selectedShapes[0]?.id : null;
}

function isAiImageHolderShape(shape) {
  return shape?.typeName === "shape" && shape.meta?.hardwareLearningAiImageHolder === true;
}

function isAiDraftHolderShape(shape) {
  return shape?.typeName === "shape" && shape.meta?.hardwareLearningAiDraftHolder === true;
}

function isAiSlidesShape(shape) {
  return shape?.typeName === "shape" && shape.meta?.hardwareLearningAiSlides === true;
}

function isHardwareLearningHtmlDraftShape(shape) {
  return shape?.typeName === "shape" && shape.type === "embed" && (
    shape.meta?.hardwareLearningHtmlDraft === true ||
    /^data:text\/html(?:;[^,]*)?,/i.test(String(shape.props?.url || ""))
  );
}

function hardwareLearningHtmlDraftVirtualUrl(assetUrl) {
  return `${HARDWARE_LEARNING_HTML_DRAFT_URL_ORIGIN}${assetUrl}`;
}

function hardwareLearningHtmlDraftDataUrl(htmlContent) {
  return `data:text/html;base64,${Buffer.from(String(htmlContent || ""), "utf8").toString("base64")}`;
}

function collectDescendantShapeIds(store, shapeId) {
  if (!shapeId) return [];
  const byParent = new Map();
  for (const record of Object.values(store)) {
    if (record?.typeName !== "shape") continue;
    const children = byParent.get(record.parentId) ?? [];
    children.push(record.id);
    byParent.set(record.parentId, children);
  }

  const descendants = [];
  const queue = [...(byParent.get(shapeId) ?? [])];
  const visited = new Set([shapeId]);
  while (queue.length > 0) {
    const childId = queue.shift();
    if (!childId || visited.has(childId)) continue;
    visited.add(childId);
    descendants.push(childId);
    queue.push(...(byParent.get(childId) ?? []));
  }
  return descendants;
}

function choosePlacement({ store, pageId, parentId, anchorShape, width, height, margin, placement }) {
  const anchorBounds = anchorShape ? pageBoundsForShape(store, anchorShape) : null;
  let x = anchorBounds ? anchorBounds.x + anchorBounds.w + margin : 0;
  let y = anchorBounds ? anchorBounds.y : 0;

  if (placement === "left" && anchorBounds) x = anchorBounds.x - width - margin;
  if (placement === "below" && anchorBounds) {
    x = anchorBounds.x;
    y = anchorBounds.y + anchorBounds.h + margin;
  }

  const pageShapes = getPageShapes(store, pageId);
  const obstacles = pageShapes
    .filter((shape) => shape.parentId === parentId && shape.id !== anchorShape?.id)
    .map((shape) => pageBoundsForShape(store, shape))
    .filter(Boolean);

  const stepX = Math.max(width + margin, 1);
  const stepY = Math.max(height + margin, 1);
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const candidate = { x, y, w: width, h: height };
    if (!obstacles.some((bounds) => rectsOverlap(candidate, bounds, margin / 2))) return candidate;
    if (placement === "below") y += stepY;
    else if (placement === "left") x -= stepX;
    else x += stepX;
  }

  return { x, y, w: width, h: height };
}

async function getImageDimensions(filePath) {
  const buffer = await readFile(filePath);
  if (buffer.length >= 24 && buffer.toString("ascii", 1, 4) === "PNG") {
    return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
  }
  if (buffer.length >= 10 && buffer[0] === 0xff && buffer[1] === 0xd8) {
    let offset = 2;
    while (offset < buffer.length) {
      if (buffer[offset] !== 0xff) break;
      const marker = buffer[offset + 1];
      const size = buffer.readUInt16BE(offset + 2);
      if ((marker >= 0xc0 && marker <= 0xc3) || (marker >= 0xc5 && marker <= 0xc7) || (marker >= 0xc9 && marker <= 0xcb) || (marker >= 0xcd && marker <= 0xcf)) {
        return { width: buffer.readUInt16BE(offset + 7), height: buffer.readUInt16BE(offset + 5) };
      }
      offset += 2 + size;
    }
  }
  if (buffer.length >= 30 && buffer.toString("ascii", 0, 4) === "RIFF" && buffer.toString("ascii", 8, 12) === "WEBP") {
    const chunk = buffer.toString("ascii", 12, 16);
    if (chunk === "VP8X") {
      return {
        width: 1 + buffer.readUIntLE(24, 3),
        height: 1 + buffer.readUIntLE(27, 3),
      };
    }
  }
  throw new Error(`Could not read image dimensions for ${filePath}. Pass displayWidth/displayHeight and use a PNG/JPEG/WebP source.`);
}

async function insertHardwareLearningImage(args = {}) {
  assertLearningGenerationAllowed(args, "image");
  const imagePath = nonEmptyString(args.imagePath);
  if (!imagePath) throw new Error("imagePath is required.");

  const sourceImagePath = pathResolve(imagePath);
  const sourceStat = await stat(sourceImagePath);
  if (!sourceStat.isFile()) throw new Error(`imagePath is not a file: ${sourceImagePath}`);

  const canvasState = await readHardwareLearningCanvasState(args, { hydrateAssets: false });
  const snapshot = canvasState.snapshot;
  if (!snapshot || typeof snapshot !== "object" || !snapshot.schema || !snapshot.store) {
    throw new Error("No JLC Hardware Learning canvas snapshot exists yet. Open the JLC Hardware Learning widget for the target project and create or save the canvas before inserting images.");
  }

  const store = snapshot.store;
  const { selection } = await readHardwareLearningSelectionState(args);
  const { viewState } = await readHardwareLearningViewState(args);

  const anchorShapeId = nonEmptyString(args.anchorShapeId) || nonEmptyString(args.sourceShapeId) || firstSelectedShapeId(selection);
  const anchorShape = anchorShapeId ? getRecord(store, anchorShapeId, "anchor shape") : null;
  const pageId =
    nonEmptyString(args.pageId) ||
    (anchorShape ? findPageIdForShape(store, anchorShape.id) : null) ||
    nonEmptyString(viewState?.currentPageId) ||
    Object.values(store).find((record) => record?.typeName === "page")?.id;
  if (!pageId || !store[pageId]) throw new Error("Could not determine target pageId.");

  const imageSize = await getImageDimensions(sourceImagePath);
  const anchorBounds = anchorShape ? pageBoundsForShape(store, anchorShape) : null;
  const shouldTargetAiImageHolder = args.matchAnchor !== false && isAiImageHolderShape(anchorShape) && anchorBounds;
  const shouldReplaceAiImageHolder = shouldTargetAiImageHolder && args.replaceAiImageHolder !== false;
  const shouldFillAiImageHolder = shouldTargetAiImageHolder && !shouldReplaceAiImageHolder;
  const matchAnchor = args.matchAnchor !== false && anchorBounds;
  const width = shouldTargetAiImageHolder
    ? anchorBounds.w
    : finiteNumber(args.displayWidth, matchAnchor ? anchorBounds.w : Math.min(imageSize.width, 512));
  const height = shouldTargetAiImageHolder
    ? anchorBounds.h
    : finiteNumber(
      args.displayHeight,
      matchAnchor ? anchorBounds.h : Math.round(width * (imageSize.height / imageSize.width)),
    );
  const margin = Math.max(0, finiteNumber(args.margin, 40));
  const placement = ["right", "left", "below"].includes(args.placement) ? args.placement : "right";
  let parentId = anchorShape?.parentId && store[anchorShape.parentId] ? anchorShape.parentId : pageId;
  let rotation = 0;
  let bounds = null;

  if (shouldFillAiImageHolder && anchorShape.type === "frame") {
    parentId = anchorShape.id;
    bounds = { x: 0, y: 0, w: width, h: height };
  } else if (shouldTargetAiImageHolder) {
    parentId = anchorShape.parentId && store[anchorShape.parentId] ? anchorShape.parentId : pageId;
    rotation = finiteNumber(anchorShape.rotation, 0);
    bounds = {
      x: finiteNumber(anchorShape.x, 0),
      y: finiteNumber(anchorShape.y, 0),
      w: width,
      h: height,
    };
  } else {
    parentId = anchorShape?.parentId && store[anchorShape.parentId]?.typeName === "page" ? anchorShape.parentId : pageId;
    bounds = choosePlacement({ store, pageId, parentId, anchorShape, width, height, margin, placement });
  }

  const canvasDir = resolveCanvasDir(args);
  const assetsDir = join(canvasDir, "pages", pageDirName(pageId), "assets");
  if (!isSafeChildPath(resolveCanvasDir(args), assetsDir)) {
    throw new Error(`Unsafe page assets directory: ${assetsDir}`);
  }
  const { fileName, filePath } = await uniqueFilePath(assetsDir, args.fileName || basename(sourceImagePath));
  const recordSeed = sanitizeIdPart(fileName);
  const assetId = uniqueRecordId(store, "asset", recordSeed);
  const shapeId = uniqueRecordId(store, "shape", recordSeed);
  const replacedShapeIds = shouldReplaceAiImageHolder && anchorShapeId
    ? [anchorShapeId, ...collectDescendantShapeIds(store, anchorShapeId)]
    : [];
  const replacedImageShapeIds = replacedShapeIds.filter((id) => store[id]?.typeName === "shape" && store[id]?.type === "image");
  const index = shouldReplaceAiImageHolder && typeof anchorShape?.index === "string"
    ? anchorShape.index
    : chooseIndex(store, parentId);
  const mimeType = mimeTypeForFile(fileName);

  const evidenceSource = nonEmptyString(args.evidenceSource);
  const assetMeta = args.assetMeta && typeof args.assetMeta === "object"
    ? { ...args.assetMeta }
    : {};
  if (evidenceSource) {
    if (assetMeta.evidenceSource && assetMeta.evidenceSource !== evidenceSource) {
      throw new Error("assetMeta.evidenceSource does not match the admitted evidenceSource");
    }
    assetMeta.evidenceSource = evidenceSource;
  }

  const assetRecord = {
    id: assetId,
    typeName: "asset",
    type: "image",
    props: {
      name: fileName,
      src: pageAssetUrl(pageId, fileName),
      w: imageSize.width,
      h: imageSize.height,
      fileSize: sourceStat.size,
      mimeType,
      isAnimated: false,
    },
    meta: assetMeta,
  };

  const shapeMeta = args.shapeMeta && typeof args.shapeMeta === "object" ? { ...args.shapeMeta } : {};
  if (evidenceSource) {
    if (shapeMeta.evidenceSource && shapeMeta.evidenceSource !== evidenceSource) {
      throw new Error("shapeMeta.evidenceSource does not match the admitted evidenceSource");
    }
    shapeMeta.evidenceSource = evidenceSource;
  }
  if (anchorShapeId && !shapeMeta.hardwareLearningAnnotationSourceShapeId) {
    shapeMeta.hardwareLearningAnnotationSourceShapeId = anchorShapeId;
  }
  if (shouldTargetAiImageHolder && anchorShapeId && !shapeMeta.hardwareLearningGeneratedForAiImageHolder) {
    shapeMeta.hardwareLearningGeneratedForAiImageHolder = anchorShapeId;
  }
  if (shouldReplaceAiImageHolder && anchorShapeId) {
    shapeMeta.hardwareLearningReplacedAiImageHolder = true;
  }
  if (nonEmptyString(args.annotationScreenshot) && !shapeMeta.hardwareLearningAnnotationScreenshot) {
    shapeMeta.hardwareLearningAnnotationScreenshot = nonEmptyString(args.annotationScreenshot);
  }

  const shapeRecord = {
    x: bounds.x,
    y: bounds.y,
    rotation,
    isLocked: false,
    opacity: 1,
    meta: shapeMeta,
    id: shapeId,
    type: "image",
    props: {
      w: width,
      h: height,
      assetId,
      playing: true,
      url: "",
      crop: null,
      flipX: false,
      flipY: false,
      altText: nonEmptyString(args.altText) || "JLC Hardware Learning inserted image",
    },
    parentId,
    index,
    typeName: "shape",
  };

  if (!args.dryRun) {
    await mkdir(assetsDir, { recursive: true });
    await copyFile(sourceImagePath, filePath);
    for (const replacedShapeId of replacedShapeIds) {
      delete store[replacedShapeId];
    }
    store[assetId] = assetRecord;
    store[shapeId] = shapeRecord;
    const saveArgs = replacedImageShapeIds.length > 0
      ? {
          ...args,
          acknowledgedImageShapeDeletes: Array.from(new Set([
            ...(Array.isArray(args.acknowledgedImageShapeDeletes) ? args.acknowledgedImageShapeDeletes : []),
            ...replacedImageShapeIds,
          ])),
        }
      : args;
    await saveHardwareLearningCanvasSnapshot(saveArgs, snapshot);
  }

  return {
    canvasDir,
    sourceUrl: nonEmptyString(args.sourceUrl),
    pageId,
    parentId,
    anchorShapeId,
    assetId,
    shapeId,
    index,
    sourceImagePath,
    assetFile: filePath,
    assetUrl: assetRecord.props.src,
    evidenceSource,
    imageSize,
    bounds,
    replacedAiImageHolder: shouldReplaceAiImageHolder,
    replacedShapeIds,
    dryRun: Boolean(args.dryRun),
  };
}

async function insertHardwareLearningHtmlDraft(args = {}) {
  assertLearningGenerationAllowed(args, "HTML");
  const htmlContent = nonEmptyString(args.htmlContent);
  const htmlPath = nonEmptyString(args.htmlPath);
  if (!htmlContent && !htmlPath) {
    throw new Error("htmlContent or htmlPath is required.");
  }

  const sourceHtmlPath = htmlPath ? pathResolve(htmlPath) : null;
  const finalHtml = htmlContent ?? await readFile(sourceHtmlPath, "utf8");
  if (!nonEmptyString(finalHtml)) {
    throw new Error("HTML draft content is empty.");
  }
  if (sourceHtmlPath) {
    const sourceStat = await stat(sourceHtmlPath);
    if (!sourceStat.isFile()) throw new Error(`htmlPath is not a file: ${sourceHtmlPath}`);
  }

  const canvasState = await readHardwareLearningCanvasState(args, { hydrateAssets: false });
  const snapshot = canvasState.snapshot;
  if (!snapshot || typeof snapshot !== "object" || !snapshot.schema || !snapshot.store) {
    throw new Error("No JLC Hardware Learning canvas snapshot exists yet. Open the JLC Hardware Learning widget for the target project and create or save the canvas before inserting HTML drafts.");
  }

  const store = snapshot.store;
  const { selection } = await readHardwareLearningSelectionState(args);
  const { viewState } = await readHardwareLearningViewState(args);

  const draftShapeId = nonEmptyString(args.draftShapeId) || nonEmptyString(args.anchorShapeId) || firstSelectedShapeId(selection);
  const draftShape = draftShapeId ? getRecord(store, draftShapeId, "AI draft holder shape") : null;
  const pageId =
    nonEmptyString(args.pageId) ||
    (draftShape ? findPageIdForShape(store, draftShape.id) : null) ||
    nonEmptyString(viewState?.currentPageId) ||
    Object.values(store).find((record) => record?.typeName === "page")?.id;
  if (!pageId || !store[pageId]) throw new Error("Could not determine target pageId.");

  const anchorBounds = draftShape ? pageBoundsForShape(store, draftShape) : null;
  const shouldUpdateExistingDraft = args.updateExistingDraft !== false && isHardwareLearningHtmlDraftShape(draftShape) && anchorBounds;
  const shouldTargetDraftHolder = args.matchAnchor !== false && isAiDraftHolderShape(draftShape) && anchorBounds;
  const shouldTargetAiSlides = isAiSlidesShape(draftShape);
  const shouldReplaceDraftHolder = shouldTargetDraftHolder && args.replaceDraftHolder !== false;
  const matchAnchor = args.matchAnchor !== false && anchorBounds;
  const width = shouldUpdateExistingDraft || shouldTargetDraftHolder
    ? anchorBounds.w
    : finiteNumber(args.displayWidth, shouldTargetAiSlides ? 1024 : matchAnchor ? anchorBounds.w : 512);
  const height = shouldUpdateExistingDraft || shouldTargetDraftHolder
    ? anchorBounds.h
    : finiteNumber(args.displayHeight, shouldTargetAiSlides ? 576 : matchAnchor ? anchorBounds.h : 683);
  const margin = Math.max(0, finiteNumber(args.margin, 40));
  const placement = ["right", "left", "below"].includes(args.placement) ? args.placement : "right";
  let parentId = draftShape?.parentId && store[draftShape.parentId] ? draftShape.parentId : pageId;
  let rotation = 0;
  let bounds = null;

  if (shouldTargetAiSlides) {
    const padding = Math.max(0, finiteNumber(draftShape.meta?.hardwareLearningAiSlidesPadding, 12));
    const gap = Math.max(0, finiteNumber(draftShape.meta?.hardwareLearningAiSlidesGap, 32));
    const slideItems = Object.values(store)
      .filter((record) => record?.typeName === "shape" && record.parentId === draftShape.id)
      .sort((a, b) => String(a.index || "").localeCompare(String(b.index || "")));
    const nextX = slideItems.reduce(
      (cursor, item) => Math.max(cursor, finiteNumber(item.x, padding) + finiteNumber(item.props?.w, 0) + gap),
      padding,
    );
    parentId = draftShape.id;
    rotation = 0;
    bounds = { x: nextX, y: padding, w: width, h: height };
  } else if (shouldUpdateExistingDraft || shouldTargetDraftHolder) {
    parentId = draftShape.parentId && store[draftShape.parentId] ? draftShape.parentId : pageId;
    rotation = finiteNumber(draftShape.rotation, 0);
    bounds = {
      x: finiteNumber(draftShape.x, 0),
      y: finiteNumber(draftShape.y, 0),
      w: width,
      h: height,
    };
  } else {
    parentId = draftShape?.parentId && store[draftShape.parentId]?.typeName === "page" ? draftShape.parentId : pageId;
    bounds = choosePlacement({ store, pageId, parentId, anchorShape: draftShape, width, height, margin, placement });
  }

  const canvasDir = resolveCanvasDir(args);
  const assetsDir = join(canvasDir, "pages", pageDirName(pageId), "assets");
  if (!isSafeChildPath(canvasDir, assetsDir)) {
    throw new Error(`Unsafe page assets directory: ${assetsDir}`);
  }
  const existingAssetUrl = shouldUpdateExistingDraft
    ? nonEmptyString(draftShape.meta?.hardwareLearningHtmlDraftAssetUrl)
    : null;
  const expectedAssetPrefix = `/page-assets/${pageDirName(pageId)}/`;
  let existingFileName = null;
  if (existingAssetUrl?.startsWith(expectedAssetPrefix)) {
    try {
      existingFileName = decodeURIComponent(existingAssetUrl.slice(expectedAssetPrefix.length).split(/[?#]/)[0]);
    } catch (_error) {
      existingFileName = null;
    }
  }
  const shouldForkSharedAsset = Boolean(
    shouldUpdateExistingDraft &&
      existingAssetUrl &&
      Object.values(store).some(
        (record) =>
          record?.id !== draftShape.id &&
          isHardwareLearningHtmlDraftShape(record) &&
          nonEmptyString(record.meta?.hardwareLearningHtmlDraftAssetUrl) === existingAssetUrl,
      ),
  );
  const requestedName = sanitizeHtmlFileName(
    existingFileName || args.fileName,
    `draft-${Date.now()}.html`,
  );
  const fileTarget = shouldUpdateExistingDraft && existingFileName && !shouldForkSharedAsset
    ? { fileName: requestedName, filePath: join(assetsDir, requestedName) }
    : await uniqueFilePath(assetsDir, requestedName);
  const { fileName, filePath } = fileTarget;
  if (!isSafeChildPath(assetsDir, filePath)) {
    throw new Error(`Unsafe HTML draft file path: ${filePath}`);
  }
  const recordSeed = sanitizeIdPart(fileName, "html-draft");
  const shapeId = shouldUpdateExistingDraft ? draftShape.id : uniqueRecordId(store, "shape", recordSeed);
  const replacedShapeIds = shouldReplaceDraftHolder && draftShapeId
    ? [draftShapeId, ...collectDescendantShapeIds(store, draftShapeId)]
    : [];
  const index = shouldUpdateExistingDraft && typeof draftShape?.index === "string"
    ? draftShape.index
    : shouldReplaceDraftHolder && typeof draftShape?.index === "string"
    ? draftShape.index
    : chooseIndex(store, parentId);
  const assetUrl = pageAssetUrl(pageId, fileName);
  const shapeMeta = args.shapeMeta && typeof args.shapeMeta === "object" ? { ...args.shapeMeta } : {};
  if (shouldTargetDraftHolder && draftShapeId && !shapeMeta.hardwareLearningGeneratedForAiDraftHolder) {
    shapeMeta.hardwareLearningGeneratedForAiDraftHolder = draftShapeId;
  }
  if (shouldReplaceDraftHolder && draftShapeId) {
    shapeMeta.hardwareLearningReplacedAiDraftHolder = true;
  }
  if (shouldTargetAiSlides && draftShapeId && !shapeMeta.hardwareLearningAiSlidesParentShapeId) {
    shapeMeta.hardwareLearningAiSlidesParentShapeId = draftShapeId;
  }

  const shapeRecord = {
    x: bounds.x,
    y: bounds.y,
    rotation,
    isLocked: false,
    opacity: 1,
    meta: {
      ...(shouldUpdateExistingDraft && draftShape.meta && typeof draftShape.meta === "object" ? draftShape.meta : {}),
      hardwareLearningHtmlDraft: true,
      hardwareLearningHtmlDraftAssetUrl: assetUrl,
      ...shapeMeta,
    },
    id: shapeId,
    type: "embed",
    props: {
      ...(shouldUpdateExistingDraft && draftShape.props && typeof draftShape.props === "object" ? draftShape.props : {}),
      w: width,
      h: height,
      url: hardwareLearningHtmlDraftDataUrl(finalHtml),
    },
    parentId,
    index,
    typeName: "shape",
  };

  if (!args.dryRun) {
    await mkdir(assetsDir, { recursive: true });
    await writeFile(filePath, finalHtml);
    for (const replacedShapeId of replacedShapeIds) {
      delete store[replacedShapeId];
    }
    store[shapeId] = shapeRecord;
    await saveHardwareLearningCanvasSnapshot(args, snapshot);
  }

  return {
    canvasDir,
    pageId,
    parentId,
    draftShapeId,
    shapeId,
    index,
    assetFile: filePath,
    assetUrl,
    virtualUrl: hardwareLearningHtmlDraftVirtualUrl(assetUrl),
    displayUrlKind: "data:text/html;base64",
    bounds,
    updatedExistingHtmlDraft: Boolean(shouldUpdateExistingDraft),
    forkedSharedHtmlDraftAsset: shouldForkSharedAsset,
    replacedAiDraftHolder: shouldReplaceDraftHolder,
    replacedShapeIds,
    dryRun: Boolean(args.dryRun),
  };
}

async function saveHardwareLearningReferenceImage(args = {}) {
  const canvasState = await readHardwareLearningCanvasState(args, { hydrateAssets: false });
  const snapshot = canvasState.snapshot;
  if (!snapshot || typeof snapshot !== "object" || !snapshot.schema || !snapshot.store) {
    throw new Error("No JLC Hardware Learning canvas snapshot exists yet. Open the JLC Hardware Learning widget for the target project and create or save the canvas before saving reference images.");
  }

  const store = snapshot.store;
  const { selection } = await readHardwareLearningSelectionState(args);
  const { viewState } = await readHardwareLearningViewState(args);
  const holderShapeId = nonEmptyString(args.holderShapeId) || nonEmptyString(args.anchorShapeId) || firstSelectedShapeId(selection);
  const holderShape = holderShapeId ? getRecord(store, holderShapeId, "AI image holder shape") : null;
  const pageId =
    nonEmptyString(args.pageId) ||
    (holderShape ? findPageIdForShape(store, holderShape.id) : null) ||
    nonEmptyString(viewState?.currentPageId) ||
    Object.values(store).find((record) => record?.typeName === "page")?.id;
  if (!pageId || !store[pageId]) throw new Error("Could not determine target pageId for the reference image.");

  const result = await writeHardwareLearningPageAsset(args, {
    pageId,
    fileName: args.fileName,
    dataUrl: args.dataUrl,
    dataBase64: args.dataBase64,
    mimeType: args.mimeType,
  });
  const { projectDir } = resolveHardwareLearningPaths(args);

  return {
    ...result,
    projectDir,
    holderShapeId: holderShape?.id ?? holderShapeId ?? null,
    assetPathRelativeToProject: relative(projectDir, result.assetPath),
    assetPathRelativeToCanvas: relative(result.canvasDir, result.assetPath),
  };
}

async function downloadHardwareLearningFileDirect(args = {}) {
  const assetUrl = nonEmptyString(args.assetUrl);
  const dataUrl = nonEmptyString(args.dataUrl);
  const dataBase64 = nonEmptyString(args.dataBase64);
  let buffer = null;
  let mimeType = nonEmptyString(args.mimeType) || "application/octet-stream";
  let sourceFileName = null;

  if (assetUrl) {
    const asset = await readHardwareLearningPageAsset(args, { assetUrl });
    buffer = Buffer.from(asset.dataBase64, "base64");
    mimeType = asset.mimeType || mimeType;
    sourceFileName = basename(asset.assetPath);
  } else if (dataUrl) {
    const parsed = parseDownloadDataUrl(dataUrl);
    buffer = parsed.buffer;
    mimeType = nonEmptyString(args.mimeType) || parsed.mimeType;
  } else if (dataBase64) {
    buffer = Buffer.from(dataBase64, "base64");
  } else {
    throw new Error("assetUrl, dataUrl, or dataBase64 is required.");
  }

  if (!buffer.length) throw new Error("JLC Hardware Learning download data is empty.");

  const downloadsDir = join(homedir(), "Downloads");
  const approvedDirectory = approvedExportDirectory(args);
  const requestedName = sanitizeFileName(
    nonEmptyString(args.fileName) || sourceFileName,
    `jlc-hardware-learning-download-${Date.now()}.png`,
  );
  const requestedDirectoryName = nonEmptyString(args.directoryName);
  const requestedSubdirectory = nonEmptyString(args.subdirectory);
  let directoryName = approvedDirectory
    ? basename(approvedDirectory.directoryPath)
    : requestedDirectoryName
      ? sanitizeDirectoryName(requestedDirectoryName)
      : null;
  let exportRoot = approvedDirectory?.directoryPath || (directoryName ? join(downloadsDir, directoryName) : downloadsDir);
  if (!approvedDirectory && directoryName && args.uniqueDirectory === true) {
    const uniqueDirectory = await uniqueDirectoryPath(downloadsDir, directoryName);
    directoryName = uniqueDirectory.directoryName;
    exportRoot = uniqueDirectory.directoryPath;
  }
  const targetDir = requestedSubdirectory
    ? join(exportRoot, sanitizeDirectoryName(requestedSubdirectory, "pages"))
    : exportRoot;
  if (!isSafeChildPath(exportRoot, targetDir) && targetDir !== exportRoot) {
    throw new Error("Invalid JLC Hardware Learning download directory.");
  }
  await mkdir(targetDir, { recursive: true });
  const { fileName, filePath } = args.overwrite === true
    ? { fileName: requestedName, filePath: join(targetDir, requestedName) }
    : await uniqueFilePath(targetDir, requestedName);
  await writeFile(filePath, buffer);

  return {
    ok: true,
    fileName,
    filePath,
    directoryName,
    directoryPath: exportRoot,
    mimeType,
    fileSize: buffer.length,
  };
}

async function beginChunkedHardwareLearningDownload(args = {}) {
  const expectedBytes = Number(args.expectedBytes);
  if (!Number.isInteger(expectedBytes) || expectedBytes <= 0 || expectedBytes > MAX_CHUNKED_DOWNLOAD_BYTES) {
    throw new Error(`Chunked JLC Hardware Learning download expectedBytes must be between 1 and ${MAX_CHUNKED_DOWNLOAD_BYTES}.`);
  }

  const requestedDownloadId = nonEmptyString(args.downloadId);
  const existing = requestedDownloadId ? activeHardwareLearningDownloads.get(requestedDownloadId) : null;
  if (existing) {
    if (existing.expectedBytes !== expectedBytes) {
      throw new Error("JLC Hardware Learning chunked download retry changed expectedBytes.");
    }
    return {
      ok: true,
      action: "begin",
      downloadId: existing.downloadId,
      expectedBytes: existing.expectedBytes,
      fileName: existing.fileName,
      mimeType: existing.mimeType,
      resumed: true,
    };
  }

  const downloadsDir = join(homedir(), "Downloads");
  const approvedDirectory = approvedExportDirectory(args);
  const requestedName = sanitizeFileName(nonEmptyString(args.fileName), `jlc-hardware-learning-download-${Date.now()}.bin`);
  const requestedDirectoryName = nonEmptyString(args.directoryName);
  const requestedSubdirectory = nonEmptyString(args.subdirectory);
  let directoryName = approvedDirectory
    ? basename(approvedDirectory.directoryPath)
    : requestedDirectoryName
      ? sanitizeDirectoryName(requestedDirectoryName)
      : null;
  let exportRoot = approvedDirectory?.directoryPath || (directoryName ? join(downloadsDir, directoryName) : downloadsDir);
  if (!approvedDirectory && directoryName && args.uniqueDirectory === true) {
    const uniqueDirectory = await uniqueDirectoryPath(downloadsDir, directoryName);
    directoryName = uniqueDirectory.directoryName;
    exportRoot = uniqueDirectory.directoryPath;
  }
  const targetDir = requestedSubdirectory
    ? join(exportRoot, sanitizeDirectoryName(requestedSubdirectory, "pages"))
    : exportRoot;
  if (!isSafeChildPath(exportRoot, targetDir) && targetDir !== exportRoot) {
    throw new Error("Invalid JLC Hardware Learning download directory.");
  }
  await mkdir(targetDir, { recursive: true });
  const { fileName, filePath } = args.overwrite === true
    ? { fileName: requestedName, filePath: join(targetDir, requestedName) }
    : await uniqueFilePath(targetDir, requestedName);
  const temporaryDir = await mkdtemp(join(tmpdir(), "jlc-hardware-learning-download-"));
  const temporaryPath = join(temporaryDir, "payload.part");
  await writeFile(temporaryPath, Buffer.alloc(0));
  const downloadId = requestedDownloadId || randomUUID();
  completedHardwareLearningDownloads.delete(downloadId);
  activeHardwareLearningDownloads.set(downloadId, {
    downloadId,
    directoryName,
    directoryPath: exportRoot,
    expectedBytes,
    fileName,
    filePath,
    mimeType: nonEmptyString(args.mimeType) || "application/octet-stream",
    chunkDigests: new Map(),
    nextChunkIndex: 0,
    overwrite: args.overwrite === true,
    receivedBytes: 0,
    temporaryDir,
    temporaryPath,
  });
  return { ok: true, action: "begin", downloadId, expectedBytes, fileName, mimeType: nonEmptyString(args.mimeType) || "application/octet-stream" };
}

function activeHardwareLearningDownload(args = {}) {
  const downloadId = nonEmptyString(args.downloadId);
  const download = downloadId ? activeHardwareLearningDownloads.get(downloadId) : null;
  if (!download) throw new Error("JLC Hardware Learning chunked download session was not found or has expired.");
  return download;
}

async function appendChunkedHardwareLearningDownload(args = {}) {
  const download = activeHardwareLearningDownload(args);
  const chunkIndex = Number(args.chunkIndex);
  const chunkBase64 = nonEmptyString(args.chunkBase64);
  if (!chunkBase64) throw new Error("JLC Hardware Learning download chunkBase64 is required.");
  const chunk = Buffer.from(chunkBase64, "base64");
  if (!chunk.length || chunk.length > MAX_DOWNLOAD_CHUNK_BYTES) {
    throw new Error(`JLC Hardware Learning download chunks must contain between 1 and ${MAX_DOWNLOAD_CHUNK_BYTES} bytes.`);
  }
  if (!Number.isInteger(chunkIndex) || chunkIndex < 0) {
    throw new Error(`JLC Hardware Learning download received invalid chunk index ${args.chunkIndex}.`);
  }
  const chunkDigest = createHash("sha256").update(chunk).digest("hex");
  if (chunkIndex < download.nextChunkIndex) {
    if (download.chunkDigests.get(chunkIndex) !== chunkDigest) {
      throw new Error(`JLC Hardware Learning download retry changed the contents of chunk ${chunkIndex}.`);
    }
    return {
      ok: true,
      action: "append",
      downloadId: download.downloadId,
      chunkIndex,
      duplicate: true,
      receivedBytes: download.receivedBytes,
      expectedBytes: download.expectedBytes,
    };
  }
  if (chunkIndex !== download.nextChunkIndex) {
    throw new Error(`JLC Hardware Learning download expected chunk ${download.nextChunkIndex}, received ${args.chunkIndex}.`);
  }
  if (download.receivedBytes + chunk.length > download.expectedBytes) {
    throw new Error("JLC Hardware Learning download received more bytes than expected.");
  }
  await appendFile(download.temporaryPath, chunk);
  download.chunkDigests.set(chunkIndex, chunkDigest);
  download.receivedBytes += chunk.length;
  download.nextChunkIndex += 1;
  return {
    ok: true,
    action: "append",
    downloadId: download.downloadId,
    chunkIndex,
    receivedBytes: download.receivedBytes,
    expectedBytes: download.expectedBytes,
  };
}

async function cancelChunkedHardwareLearningDownload(args = {}) {
  const downloadId = nonEmptyString(args.downloadId);
  const download = downloadId ? activeHardwareLearningDownloads.get(downloadId) : null;
  if (!download) {
    return { ok: true, action: "cancel", downloadId, alreadyClosed: true };
  }
  activeHardwareLearningDownloads.delete(download.downloadId);
  await rm(download.temporaryDir, { recursive: true, force: true });
  return { ok: true, action: "cancel", downloadId: download.downloadId };
}

async function finishChunkedHardwareLearningDownload(args = {}) {
  const downloadId = nonEmptyString(args.downloadId);
  const completed = downloadId ? completedHardwareLearningDownloads.get(downloadId) : null;
  if (completed) return { ...completed, duplicate: true };
  const download = activeHardwareLearningDownload(args);
  if (download.receivedBytes !== download.expectedBytes) {
    throw new Error(`JLC Hardware Learning download is incomplete: ${download.receivedBytes} of ${download.expectedBytes} bytes.`);
  }
  if (download.overwrite) await rm(download.filePath, { force: true });
  await rename(download.temporaryPath, download.filePath);
  activeHardwareLearningDownloads.delete(download.downloadId);
  await rm(download.temporaryDir, { recursive: true, force: true });
  const result = {
    ok: true,
    action: "finish",
    downloadId: download.downloadId,
    fileName: download.fileName,
    filePath: download.filePath,
    directoryName: download.directoryName,
    directoryPath: download.directoryPath,
    mimeType: download.mimeType,
    fileSize: download.receivedBytes,
  };
  completedHardwareLearningDownloads.set(download.downloadId, result);
  while (completedHardwareLearningDownloads.size > MAX_COMPLETED_DOWNLOAD_RESULTS) {
    completedHardwareLearningDownloads.delete(completedHardwareLearningDownloads.keys().next().value);
  }
  return result;
}

async function downloadHardwareLearningFile(args = {}) {
  if (args.action === "begin") return beginChunkedHardwareLearningDownload(args);
  if (args.action === "append") return appendChunkedHardwareLearningDownload(args);
  if (args.action === "finish") return finishChunkedHardwareLearningDownload(args);
  if (args.action === "cancel") return cancelChunkedHardwareLearningDownload(args);
  return downloadHardwareLearningFileDirect(args);
}

async function copyHardwareLearningImageToClipboard(args = {}) {
  const dataUrl = nonEmptyString(args.dataUrl);
  const dataBase64 = nonEmptyString(args.dataBase64);
  let buffer = null;
  let mimeType = nonEmptyString(args.mimeType) || "image/png";

  if (dataUrl) {
    const parsed = parseDownloadDataUrl(dataUrl);
    buffer = parsed.buffer;
    mimeType = nonEmptyString(args.mimeType) || parsed.mimeType;
  } else if (dataBase64) {
    buffer = Buffer.from(dataBase64, "base64");
  } else {
    throw new Error("dataUrl or dataBase64 is required.");
  }

  if (!buffer.length) throw new Error("JLC Hardware Learning clipboard image data is empty.");
  if (mimeType !== "image/png") throw new Error(`JLC Hardware Learning clipboard only supports image/png, received ${mimeType}.`);
  if (buffer.length < 8 || !buffer.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    throw new Error("JLC Hardware Learning clipboard data is not a valid PNG image.");
  }

  const dimensions = readPngDimensions(buffer);
  if (args.dryRun !== true) {
    await writePngToSystemClipboard(buffer);
  }

  return {
    ok: true,
    mimeType,
    fileSize: buffer.length,
    width: dimensions.width,
    height: dimensions.height,
    platform: platform(),
    dryRun: args.dryRun === true,
  };
}

function readPngDimensions(buffer) {
  if (buffer.length < 24 || buffer.toString("ascii", 12, 16) !== "IHDR") {
    throw new Error("JLC Hardware Learning clipboard PNG is missing its IHDR header.");
  }
  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
  };
}

async function writePngToSystemClipboard(buffer) {
  const systemPlatform = platform();
  const tempDir = await mkdtemp(join(tmpdir(), "jlc-hardware-learning-clipboard-"));
  const pngPath = join(tempDir, "jlc-hardware-learning-copy.png");

  try {
    await writeFile(pngPath, buffer);
    if (systemPlatform === "darwin") {
      const script = [
        "on run argv",
        "set imageFile to POSIX file (item 1 of argv)",
        "set the clipboard to (read imageFile as «class PNGf»)",
        "end run",
      ].join("\n");
      await execFileAsync("/usr/bin/osascript", ["-e", script, pngPath], { timeout: 10000 });
      return;
    }

    if (systemPlatform === "win32") {
      const script = [
        "Add-Type -AssemblyName System.Windows.Forms",
        "Add-Type -AssemblyName System.Drawing",
        "$image = [System.Drawing.Image]::FromFile($env:JLC_HARDWARE_LEARNING_CLIPBOARD_PNG_PATH)",
        "try { [System.Windows.Forms.Clipboard]::SetImage($image) } finally { $image.Dispose() }",
      ].join("; ");
      await execFileAsync(
        "powershell.exe",
        ["-NoProfile", "-STA", "-Command", script],
        {
          env: { ...process.env, JLC_HARDWARE_LEARNING_CLIPBOARD_PNG_PATH: pngPath },
          timeout: 10000,
        },
      );
      return;
    }

    throw new Error(`JLC Hardware Learning system clipboard is not supported on ${systemPlatform}.`);
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("JLC Hardware Learning system clipboard")) throw error;
    throw new Error(`系统剪贴板写入失败：${error instanceof Error ? error.message : String(error)}`);
  } finally {
    await rm(tempDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

function registerHardwareLearningWidget(mcpServer) {
  registerWidgetResource(mcpServer, {
    name: "jlc-hardware-learning-widget",
    uri: HARDWARE_LEARNING_WIDGET_URI,
    title: CANVAS_WIDGET_TITLE,
    description:
      `${CANVAS_BRAND_NAME}原生 Codex 矢量画板，数据持久化在当前项目中。`,
    connectDomains: HARDWARE_LEARNING_CONNECT_DOMAINS,
    resourceDomains: HARDWARE_LEARNING_RESOURCE_DOMAINS,
    frameDomains: HARDWARE_LEARNING_FRAME_DOMAINS,
    html: async () => inlineWidget({
      html: await hardwareLearningStaticHtml(),
      appVersion: pluginManifest.version,
      initialDisplayMode: DEFAULT_DISPLAY_MODE,
    }),
  });

  registerAppTool(
    mcpServer,
    TOOL_RENDER_WIDGET,
    {
      title: `打开${CANVAS_BRAND_NAME}`,
      description:
        `打开、重新打开或刷新当前 Codex 项目的${CANVAS_BRAND_NAME}。传入 projectDir 后，画板数据保存在项目本地；已有画板应直接复用。`,
      inputSchema: {
        ...projectArgsSchema,
        title: z.string().trim().optional(),
        displayMode: displayModeSchema.optional(),
        mode: widgetModeSchema.optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
      _meta: {
        ui: {
          resourceUri: HARDWARE_LEARNING_WIDGET_URI,
          visibility: ["model", "app"],
        },
        "ui/resourceUri": HARDWARE_LEARNING_WIDGET_URI,
        "openai/outputTemplate": HARDWARE_LEARNING_WIDGET_URI,
        "openai/widgetAccessible": true,
        "openai/toolInvocation/invoking": `正在打开${CANVAS_BRAND_NAME}…`,
        "openai/toolInvocation/invoked": `${CANVAS_BRAND_NAME}已就绪`,
      },
    },
    async (input = {}) => {
      const catalog = await listHardwareLearningCanvases(input);
      const { projectDir, canvasDir } = resolveHardwareLearningPaths(input);
      const title = nonEmptyString(input.title) || CANVAS_WIDGET_TITLE;
      const preferredDisplayMode = normalizeDisplayMode(input.displayMode);
      const mode = HARDWARE_LEARNING_MODE;
      await ensureHardwareLearningCanvasState({ ...input, projectDir, canvasDir });
      hardwareLearningCanvasDirs.add(canvasDir);

      return {
        content: [
          {
            type: "text",
            text: `${CANVAS_BRAND_NAME}已打开。`,
          },
        ],
        structuredContent: {
          version: 1,
          widget: "jlc-hardware-learning-widget",
          title,
          rendering: "native-widget",
          staticDir: HARDWARE_LEARNING_STATIC_BUILD_DIR,
          resourceUri: HARDWARE_LEARNING_WIDGET_URI,
          projectDir,
          canvasDir,
          canvasCatalog: catalog,
          preferredDisplayMode,
          mode,
        },
        _meta: {
          "openai/outputTemplate": HARDWARE_LEARNING_WIDGET_URI,
          widgetData: {
            title,
            rendering: "native-widget",
            staticDir: HARDWARE_LEARNING_STATIC_BUILD_DIR,
            resourceUri: HARDWARE_LEARNING_WIDGET_URI,
            projectDir,
            canvasDir,
            canvasCatalog: catalog,
            preferredDisplayMode,
            mode,
          },
        },
      };
    },
  );
}

function registerFeishuLearningNoteTools(mcpServer) {
  mcpServer.registerTool(
    TOOL_INSPECT_FEISHU_NOTE_TARGET,
    {
      title: "Inspect Feishu Hardware Learning Note",
      description:
        "Read one existing Feishu Docx twice through official lark-cli user identity, verify a stable revision, and identify its headings plus existing learning and module-index whiteboards. This tool performs no local or remote write.",
      inputSchema: {
        document: z.string().trim().min(1),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (input = {}) => {
      const result = await inspectFeishuLearningNoteTarget(input);
      return {
        content: [{
          type: "text",
          text: `Inspected Feishu document ${result.document.docToken} at revision ${result.document.revisionId}; found ${result.whiteboards.length} whiteboard(s).`,
        }],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_PREVIEW_FEISHU_NOTE_MIGRATION,
    {
      title: "Preview Feishu Hardware Learning Note Migration",
      description:
        "Read the project-local legacy learning-note package and binding, freshly inspect its existing Feishu Docx, preserve its page board and any legacy index board, require the project overview board binding, and return the guarded sync plan. This preview performs no local or remote write.",
      inputSchema: {
        ...projectArgsSchema,
        document: z.string().trim().min(1),
        projectOverviewWhiteboardToken: z.string().trim().optional(),
        canvasPageId: z.string().trim().optional(),
        projectId: z.string().trim().optional(),
        projectUuid: z.string().trim().optional(),
        projectName: z.string().trim().min(1),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (input = {}) => {
      const result = await previewFeishuLearningNoteMigration(input);
      return {
        content: [{
          type: "text",
          text: `Previewed project-scoped migration for ${result.project.projectName}; preserved the existing page board and any legacy index board with ${result.syncPlan.actions.length} pending confirmed action(s).`,
        }],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_EXECUTE_FEISHU_NOTE_MIGRATION,
    {
      title: "Execute Confirmed Feishu Hardware Learning Note Migration",
      description:
        "Re-preview one legacy learning note, require the exact confirmed plan fingerprint, document revision, and project overview board binding, move the existing Docx without replacing its page board or legacy board, minimally update legacy template text, fresh-read verify, and only then save the local registry.",
      inputSchema: {
        ...projectArgsSchema,
        document: z.string().trim().min(1),
        projectOverviewWhiteboardToken: z.string().trim().optional(),
        canvasPageId: z.string().trim().optional(),
        projectId: z.string().trim().optional(),
        projectUuid: z.string().trim().optional(),
        projectName: z.string().trim().min(1),
        planFingerprint: z.string().regex(/^[a-f0-9]{64}$/u),
        expectedDocumentRevisionId: z.number().int().nonnegative(),
        confirmed: z.literal(true),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (input = {}) => {
      const result = await executeFeishuLearningNoteMigration(input);
      return {
        content: [{
          type: "text",
          text: `Migrated ${result.page.title} into the project-scoped Feishu Wiki hierarchy, verified its schematic-page board, preserved any legacy index board, and saved ${result.registryPath}.`,
        }],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_BIND_FEISHU_PAGE_IDENTITY,
    {
      title: "Bind Feishu Page Identity from Verified Learning Evidence",
      description:
        "Read the project-local learning note package, require every registered learning frame to reference one official EasyEDA schematic page from the same project, and persist that schematicPageUuid in the local Feishu registry. It performs no Feishu or EasyEDA write.",
      inputSchema: {
        ...projectArgsSchema,
        canvasPageId: z.string().trim().regex(/^page:/),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const result = await bindFeishuPageIdentityFromLearningEvidence(input);
      return {
        content: [{
          type: "text",
          text: `${result.replayed ? "Reused" : "Bound"} ${result.binding.canvasPageId} to verified EasyEDA schematic page ${result.binding.schematicPageUuid}; Feishu was not modified.`,
        }],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_LINK_FEISHU_DIALOGUE_FROM_RECORD,
    {
      title: "Link Durable Learning Dialogue to Feishu Note",
      description:
        "Read one saved hardware-learning question/run/answer record, verify its immutable question and answer digests plus page-local frame numbers, and link it only in the local Feishu registry. It never scrapes chat history and performs no Feishu write.",
      inputSchema: {
        ...projectArgsSchema,
        canvasPageId: z.string().trim().regex(/^page:/),
        questionId: z.string().trim().regex(/^question:[0-9a-f-]{36}$/u),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const result = await linkFeishuLearningDialogueFromRecord(input);
      return {
        content: [{
          type: "text",
          text: `${result.replayed ? "Reused" : "Linked"} ${result.record.questionId} to learning frame(s) ${result.record.frameNumbers.join(", ")}; Feishu was not modified.`,
        }],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_PREVIEW_FEISHU_NOTE_SYNC,
    {
      title: "Preview Feishu Hardware Learning Note Sync",
      description:
        "Fresh-read every targeted Docx, verify the existing learning and module-index board tokens, load only durable linked question/answer records, and return exact managed block patches, a revision map, blockers, and a fingerprinted continuous-sync plan. This performs no local or remote write.",
      inputSchema: {
        ...projectArgsSchema,
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (input = {}) => {
      const result = await previewFeishuLearningNoteSync(input);
      return {
        content: [{
          type: "text",
          text: result.blockers.length > 0
            ? `Previewed ${result.syncPlan.actions.length} Feishu sync action(s), blocked by ${result.blockers.map((entry) => entry.code).join(", ")}; no write was performed.`
            : `Previewed ${result.syncPlan.actions.length} confirmed Feishu sync action(s) across ${Object.keys(result.expectedDocumentRevisions).length} Docx target(s); no write was performed.`,
        }],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_EXECUTE_FEISHU_NOTE_SYNC,
    {
      title: "Execute Confirmed Feishu Hardware Learning Note Sync",
      description:
        "Re-preview the continuous sync, require confirmed=true plus the exact plan fingerprint and complete Docx revision map, update only JLC-managed module-index/dialogue block ranges, preserve the project overview board, schematic-page boards, legacy boards, and unrelated content, fresh-read verify every result, and save the registry once after success.",
      inputSchema: {
        ...projectArgsSchema,
        planFingerprint: z.string().regex(/^[a-f0-9]{64}$/u),
        expectedDocumentRevisions: z.record(
          z.string().regex(/^[A-Za-z0-9_-]{3,128}$/u),
          z.number().int().nonnegative(),
        ),
        confirmed: z.literal(true),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (input = {}) => {
      const result = await executeFeishuLearningNoteSync(input);
      return {
        content: [{
          type: "text",
          text: result.executionJournal.length === 0
            ? "Feishu learning notes were already synchronized; no write was needed."
            : `Synchronized ${result.executionJournal.length} guarded Feishu action(s) and saved ${result.registryPath}.`,
        }],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_GET_FEISHU_NOTE_STATE,
    {
      title: "Get Feishu Hardware Learning Note State",
      description:
        "Read or preview the project-local Feishu learning-note registry, project-name directory plan, page-note bindings, and idempotent sync plan. This tool does not write Feishu or local state.",
      inputSchema: {
        ...projectArgsSchema,
        projectId: z.string().trim().optional(),
        projectUuid: z.string().trim().optional(),
        projectName: z.string().trim().optional(),
        projectOverviewWhiteboardToken: z.string().trim().optional(),
        schematicPages: z.array(z.object({
          canvasPageId: z.string().trim(),
          schematicPageUuid: z.string().trim().optional(),
          pageName: z.string().trim(),
          sourceRevision: z.string().trim().optional(),
        })).optional(),
        existingProjects: z.array(z.object({
          projectId: z.string().trim().optional(),
          projectUuid: z.string().trim().optional(),
          projectName: z.string().trim(),
        })).optional(),
        updatedAt: z.string().trim().optional(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const result = await getFeishuLearningNoteState(input);
      return {
        content: [{
          type: "text",
          text: result.registryExists
            ? `Loaded Feishu learning-note state with ${result.syncPlan.actions.length} pending sync action(s).`
            : `Previewed Feishu learning-note state with ${result.syncPlan.actions.length} pending sync action(s); no local registry was written.`,
        }],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_UPDATE_FEISHU_NOTE_STATE,
    {
      title: "Update Feishu Hardware Learning Note State",
      description:
        "Update only the project-local Feishu learning-note binding registry after an externally confirmed and freshly verified Feishu operation. It never calls Feishu or EasyEDA.",
      inputSchema: {
        ...projectArgsSchema,
        action: z.enum([
          "initialize",
          "bind-root",
          "bind-project",
          "bind-project-overview-board",
          "bind-section",
          "bind-page",
          "upsert-frame",
          "link-dialogue",
          "mark-project-homepage-synced",
          "mark-page-synced",
        ]),
        payload: z.record(z.string(), z.unknown()).optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const result = await updateFeishuLearningNoteState(input);
      return {
        content: [{
          type: "text",
          text: `${result.replayed ? "Reused" : "Updated"} local Feishu learning-note state at ${result.registryPath}.`,
        }],
        structuredContent: result,
      };
    },
  );
}

function registerHardwareLearningTools(mcpServer) {
  registerAppTool(
    mcpServer,
    TOOL_SAVE_LEARNING_QUESTION,
    {
      title: "Save JLC Hardware Learning Question",
      description:
        "Save a hardware question typed in the normal Codex conversation, resolve its frame/selection and page netlist in one call, and return a bounded quick context with asset references rather than image bytes. It can also accept the legacy Widget question envelope. This tool never generates or edits an image.",
      inputSchema: {
        ...projectArgsSchema,
        question: z.any().optional(),
        userQuestion: z.string().trim().min(1).max(4000).optional(),
        learningLevel: z.enum(conversationLearningLevels).optional(),
        intent: z.enum(conversationLearningIntents).optional(),
        responseMode: z.enum(conversationLearningResponseModes).optional(),
        annotationRequested: z.boolean().optional(),
        questionId: z.string().regex(/^question:/).optional(),
        screenshotDataUrl: z.string().optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
      _meta: {
        ui: { visibility: ["model", "app"] },
        "openai/widgetAccessible": true,
      },
    },
    async (input = {}) => {
      if (!isHardwareLearningTarget(input)) throw new Error("learning question tool requires hardware-learning mode");
      if (input.question && input.userQuestion) {
        throw new Error("Provide either question or userQuestion, not both.");
      }
      let question = input.question;
      let selectionSource = "legacy-widget-envelope";
      if (!question) {
        const [{ selection }, canvasState] = await Promise.all([
          readHardwareLearningSelectionState(input),
          readHardwareLearningCanvasState(input, { hydrateAssets: false }),
        ]);
        const built = buildConversationLearningQuestion({
          canvasSnapshot: canvasState.snapshot,
          selectionState: selection,
          userQuestion: input.userQuestion,
          learningLevel: input.learningLevel,
          intent: input.intent,
          responseMode: input.responseMode,
          annotationRequested: input.annotationRequested,
          questionId: input.questionId,
        });
        question = built.question;
        selectionSource = built.selectionSource;
        const netlist = await readHardwareLearningPageNetlist({
          ...input,
          pageId: question.selection.canvasPageId,
        });
        question.pageEvidence = {
          ...(question.pageEvidence ?? {}),
          netlist: netlist.status === "verified"
            ? {
                status: "verified",
                identity: netlist.identity,
                artifact: netlist.artifact,
                summary: netlist.summary,
              }
            : { status: "missing" },
        };
      }
      const result = await saveLearningQuestion({ ...input, question });
      return {
        content: [{ type: "text", text: `Saved JLC Hardware Learning learning question to ${result.questionPath}.` }],
        structuredContent: {
          ...result,
          questionId: question.questionId,
          canvasPageId: question.selection?.canvasPageId ?? null,
          selectionSource,
          quickContext: buildQuickLearningContext(question),
        },
      };
    },
  );

  registerAppTool(
    mcpServer,
    TOOL_ATTACH_PAGE_NETLIST,
    {
      title: "Attach Official EasyEDA Netlist to JLC Hardware Learning Page",
      description:
        "Attach a verified official EasyEDA JLCEDA netlist beside one saved canvas page. The first attachment is immutable and conflicting schematic evidence is rejected.",
      inputSchema: {
        ...projectArgsSchema,
        pageId: z.string().trim().regex(/^page:/),
        netlistPath: z.string().trim().min(1),
        evidence: z.object({
          source: z.literal("official-easyeda-export"),
          format: z.literal("jlceda"),
          identity: z.object({
            projectUuid: z.string().trim().min(1),
            documentUuid: z.string().trim().min(1),
            documentType: z.string().trim().min(1),
            schematicPageUuid: z.string().trim().optional(),
            windowId: z.string().trim().optional(),
          }),
          artifactSha256: z.string().regex(/^[a-f0-9]{64}$/).optional(),
          evidencePath: z.string().trim().min(1),
          evidenceSha256: z.string().regex(/^[a-f0-9]{64}$/),
          exportedAt: z.string().trim().optional(),
        }),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
      _meta: { ui: { visibility: ["model"] } },
    },
    async (input = {}) => {
      if (!isHardwareLearningTarget(input)) throw new Error("page netlist tool requires hardware-learning mode");
      const result = await attachHardwareLearningPageNetlist(input);
      return {
        content: [{
          type: "text",
          text: result.status === "already-attached"
            ? `Official EasyEDA netlist is already attached to ${result.pageId}.`
            : `Attached official EasyEDA netlist beside ${result.pageId}.`,
        }],
        structuredContent: result,
      };
    },
  );

  registerAppTool(
    mcpServer,
    TOOL_READ_PAGE_NETLIST,
    {
      title: "Read JLC Hardware Learning Page Netlist",
      description:
        "Read verified page-local EasyEDA netlist evidence. With no filters it returns only identity and summary; componentRefs or netNames return bounded connectivity details.",
      inputSchema: {
        ...projectArgsSchema,
        pageId: z.string().trim().regex(/^page:/).optional(),
        componentRefs: z.array(z.string().trim().min(1)).max(64).optional(),
        netNames: z.array(z.string().trim().min(1)).max(64).optional(),
        includeData: z.boolean().optional(),
        maxComponents: z.number().int().min(1).max(500).optional(),
        maxNets: z.number().int().min(1).max(500).optional(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
      _meta: { ui: { visibility: ["model"] } },
    },
    async (input = {}) => {
      if (!isHardwareLearningTarget(input)) throw new Error("page netlist tool requires hardware-learning mode");
      let pageId = input.pageId;
      if (!pageId) pageId = (await readHardwareLearningViewState(input)).viewState?.currentPageId;
      if (!pageId) throw new Error("No current canvas page is available; provide pageId explicitly.");
      const result = await readHardwareLearningPageNetlist({ ...input, pageId });
      return {
        content: [{
          type: "text",
          text: result.status === "verified"
            ? `Loaded verified official EasyEDA netlist evidence for ${pageId}.`
            : `No official EasyEDA netlist is attached to ${pageId}.`,
        }],
        structuredContent: result,
      };
    },
  );

  registerAppTool(
    mcpServer,
    TOOL_INSERT_LEARNING_ANNOTATIONS,
    {
      title: "Insert JLC Hardware Learning Annotations",
      description:
        "Queue, pull, or acknowledge idempotent hardware-learning annotations. Only note, highlight, rectangle, and arrow commands are accepted; image, HTML, embed, video, and slides are rejected.",
      inputSchema: {
        ...projectArgsSchema,
        action: z.enum(["insert", "pull", "acknowledge"]).default("insert"),
        operationId: z.string().trim().optional(),
        pageId: z.string().trim().optional(),
        commands: z.array(z.any()).optional(),
        commandsSha256: z.string().regex(/^[a-f0-9]{64}$/).optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
      _meta: {
        ui: { visibility: ["model", "app"] },
        "openai/widgetAccessible": true,
      },
    },
    async (input = {}) => {
      if (!isHardwareLearningTarget(input)) throw new Error("learning annotation tool requires hardware-learning mode");
      let result;
      if (input.action === "pull") result = await pullLearningAnnotations(input);
      else if (input.action === "acknowledge") result = await acknowledgeLearningAnnotations(input);
      else result = await insertLearningAnnotations(input);
      return {
        content: [{
          type: "text",
          text: input.action === "pull"
            ? `Loaded ${result.operations.length} pending JLC Hardware Learning learning annotation operation(s).`
            : `Processed JLC Hardware Learning learning annotations (${learningAnnotationKinds.join(", ")}).`,
        }],
        structuredContent: result,
      };
    },
  );
}

function registerHardwareLearningStateTools(mcpServer) {
  registerAppTool(
    mcpServer,
    TOOL_MANAGE_CANVASES,
    {
      title: "Manage JLC Hardware Learning Canvases",
      description:
        "List, create, activate, rename, or recoverably recycle project-local JLC Hardware Learning canvases. The default canvas remains under <projectDir>/canvas; additional canvases use managed IDs under <projectDir>/canvases.",
      inputSchema: {
        projectDir: z.string().trim().optional(),
        action: z.enum(["list", "create", "activate", "rename", "recycle"]).default("list"),
        canvasId: z.string().trim().optional(),
        name: z.string().trim().max(64).optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: false,
      },
      _meta: {
        ui: { visibility: ["app"] },
        "openai/widgetAccessible": true,
      },
    },
    async (input = {}) => {
      let result;
      if (input.action === "create") {
        result = await createHardwareLearningCanvas(input, input.name);
      } else if (input.action === "activate") {
        result = await activateHardwareLearningCanvas(input, input.canvasId);
      } else if (input.action === "rename") {
        result = await renameHardwareLearningCanvas(input, input.canvasId, input.name);
      } else if (input.action === "recycle") {
        result = await recycleHardwareLearningCanvas(input, input.canvasId);
      } else {
        result = await listHardwareLearningCanvases(input);
      }
      if (result.recycledCanvasDir) hardwareLearningCanvasDirs.delete(result.recycledCanvasDir);
      if (["create", "activate"].includes(input.action)) {
        await ensureHardwareLearningCanvasState({
          projectDir: result.projectDir,
          canvasDir: result.activeCanvas.canvasDir,
        });
      }
      hardwareLearningCanvasDirs.add(result.activeCanvas.canvasDir);
      return {
        content: [{
          type: "text",
          text: `JLC Hardware Learning canvas ${input.action}: ${result.activeCanvas.name}.`,
        }],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_GET_CANVAS_STATE,
    {
      title: "Get JLC Hardware Learning Canvas State",
      description:
        "Read the project-backed JLC Hardware Learning canvas snapshot, view state, and storage paths. The widget uses this instead of a localhost /api/canvas request.",
      inputSchema: {
        ...projectArgsSchema,
        hydrateAssets: z.boolean().optional(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const state = await readHardwareLearningCanvasState(input, { hydrateAssets: input.hydrateAssets === true });
      return {
        content: [
          {
            type: "text",
            text: `Loaded JLC Hardware Learning canvas state from ${state.canvasDir} (${state.storage}).`,
          },
        ],
        structuredContent: state,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_READ_PAGE_ASSET,
    {
      title: "Read JLC Hardware Learning Page Asset",
      description:
        "Read one project-local JLC Hardware Learning /page-assets/... image or HTML asset for lazy widget rendering. Prefer this over hydrating all assets into the canvas snapshot.",
      inputSchema: {
        ...projectArgsSchema,
        assetUrl: z.string().trim(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const asset = await readHardwareLearningPageAsset(input, { assetUrl: input.assetUrl });
      return {
        content: [
          {
            type: "text",
            text: `Loaded JLC Hardware Learning page asset ${asset.assetUrl}.`,
          },
        ],
        structuredContent: asset,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_SAVE_CANVAS_STATE,
    {
      title: "Save JLC Hardware Learning Canvas State",
      description:
        "Persist a hardware-learning/tldraw store snapshot to the project canvas directory, preserving per-page files and page-local assets.",
      inputSchema: {
        ...projectArgsSchema,
        snapshot: z.any(),
        protectImageRecords: z.boolean().optional(),
        acknowledgedImageShapeDeletes: z.array(z.string()).optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const result = await saveHardwareLearningCanvasSnapshot(input, input.snapshot);
      if (!result.ok) {
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: result.message || "Invalid JLC Hardware Learning canvas snapshot.",
            },
          ],
          structuredContent: result,
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Saved JLC Hardware Learning canvas state (${result.storage}).`,
          },
        ],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_SAVE_SELECTION_STATE,
    {
      title: "Save JLC Hardware Learning Selection State",
      description:
        "Persist the current JLC Hardware Learning widget selection to canvas/hardware-learning-selection.json so Codex can target selected shapes.",
      inputSchema: {
        ...projectArgsSchema,
        selection: z.any(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const result = await writeHardwareLearningSelectionState(input, input.selection);
      return {
        content: [
          {
            type: "text",
            text: `Saved JLC Hardware Learning selection state to ${result.path}.`,
          },
        ],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_SAVE_VIEW_STATE,
    {
      title: "Save JLC Hardware Learning View State",
      description:
        "Persist the current JLC Hardware Learning page and camera state to canvas/hardware-learning-view-state.json.",
      inputSchema: {
        ...projectArgsSchema,
        viewState: z.any(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const result = await writeHardwareLearningViewState(input, input.viewState);
      return {
        content: [
          {
            type: "text",
            text: `Saved JLC Hardware Learning view state to ${result.path}.`,
          },
        ],
        structuredContent: result,
      };
    },
  );
}

function registerHardwareLearningImageTools(mcpServer) {
  registerAppTool(
    mcpServer,
    TOOL_COPY_IMAGE_TO_CLIPBOARD,
    {
      title: "Copy JLC Hardware Learning PNG to system clipboard",
      description:
        "Copy a PNG rendered by the JLC Hardware Learning widget to the local system clipboard when the widget iframe cannot use the browser Clipboard API.",
      inputSchema: {
        ...projectArgsSchema,
        dataUrl: z.string().optional(),
        dataBase64: z.string().optional(),
        mimeType: z.literal("image/png").optional(),
        dryRun: z.boolean().optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
      _meta: {
        ui: {
          visibility: ["app"],
        },
        "openai/widgetAccessible": true,
      },
    },
    async (input = {}) => {
      const result = await copyHardwareLearningImageToClipboard(input);
      return {
        content: [
          {
            type: "text",
            text: result.dryRun
              ? `Validated JLC Hardware Learning clipboard PNG (${result.width}x${result.height}).`
              : `Copied JLC Hardware Learning PNG to the system clipboard (${result.width}x${result.height}).`,
          },
        ],
        structuredContent: result,
      };
    },
  );

  registerAppTool(
    mcpServer,
    TOOL_CHOOSE_EXPORT_DIRECTORY,
    {
      title: "Choose JLC Hardware Learning Export Directory",
      description:
        "Open the system folder picker for a user-initiated JLC Hardware Learning export and return a short-lived directory token bound to the current canvas.",
      inputSchema: {
        ...projectArgsSchema,
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
      },
      _meta: {
        ui: { visibility: ["app"] },
        "openai/widgetAccessible": true,
      },
    },
    async (input = {}) => {
      const result = await chooseHardwareLearningExportDirectory(input);
      return {
        content: [
          {
            type: "text",
            text: result.canceled
              ? "JLC Hardware Learning export directory selection was canceled."
              : `JLC Hardware Learning export directory selected: ${result.directoryPath}.`,
          },
        ],
        structuredContent: result,
      };
    },
  );

  registerAppTool(
    mcpServer,
    TOOL_DOWNLOAD_FILE,
    {
      title: "Download JLC Hardware Learning File",
      description:
        "Save a JLC Hardware Learning export into the default Downloads location or a user-approved directory token returned by choose_hardware_learning_export_directory.",
      inputSchema: {
        ...projectArgsSchema,
        assetUrl: z.string().trim().optional(),
        fileName: z.string().trim().optional(),
        dataUrl: z.string().optional(),
        dataBase64: z.string().optional(),
        mimeType: z.string().trim().optional(),
        directoryToken: z.string().uuid().optional(),
        directoryName: z.string().trim().optional(),
        subdirectory: z.string().trim().optional(),
        overwrite: z.boolean().optional(),
        uniqueDirectory: z.boolean().optional(),
        action: z.enum(["begin", "append", "finish", "cancel"]).optional(),
        downloadId: z.string().uuid().optional(),
        chunkIndex: z.number().int().nonnegative().optional(),
        chunkBase64: z.string().optional(),
        expectedBytes: z.number().int().positive().max(MAX_CHUNKED_DOWNLOAD_BYTES).optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
      },
      _meta: {
        ui: { visibility: ["model", "app"] },
        "openai/widgetAccessible": true,
      },
    },
    async (input = {}) => {
      const result = await downloadHardwareLearningFile(input);
      return {
        content: [
          {
            type: "text",
            text: result.filePath
              ? `Downloaded JLC Hardware Learning file to ${result.filePath}.`
              : `JLC Hardware Learning chunked download ${result.action}.`,
          },
        ],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_SAVE_REFERENCE_IMAGE,
    {
      title: "Save JLC Hardware Learning Reference Image",
      description:
        "Save a widget-selected reference image into the current JLC Hardware Learning page's assets folder so Codex can read it from the local project when ui/message image attachments are unavailable.",
      inputSchema: {
        ...projectArgsSchema,
        holderShapeId: z.string().trim().optional(),
        anchorShapeId: z.string().trim().optional(),
        pageId: z.string().trim().optional(),
        fileName: z.string().trim().optional(),
        dataUrl: z.string().optional(),
        dataBase64: z.string().optional(),
        mimeType: z.string().trim().optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const result = await saveHardwareLearningReferenceImage(input);
      return {
        content: [
          {
            type: "text",
            text: `Saved JLC Hardware Learning reference image to ${result.assetPath}.`,
          },
        ],
        structuredContent: result,
      };
    },
  );

  mcpServer.registerTool(
    TOOL_GET_SELECTION,
    {
      title: "Get JLC Hardware Learning Selection",
      description:
        "Return the current JLC Hardware Learning selection and the last non-empty selection retained for conversation-bar questions after canvas focus changes.",
      inputSchema: projectArgsSchema,
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const { selection, selectionFile } = await readHardwareLearningSelectionState(input);
      const selectedShapes = selection.selectedShapes ?? [];
      const fallbackShapes = selection.lastNonEmptySelection?.selectedShapes ?? [];
      const summary =
        selectedShapes.length === 0
          ? fallbackShapes.length === 0
            ? "No current or retained JLC Hardware Learning selection is available."
            : `No JLC Hardware Learning shapes are currently selected. Retained last non-empty selection:\n${fallbackShapes
                .map((shape) => `${shape.id} [${shape.type ?? "unknown"}]`)
                .join("\n")}`
          : selectedShapes
              .map((shape) => {
                const assetName = shape.asset?.name ? ` (${shape.asset.name})` : "";
                return `${shape.id} [${shape.type ?? "unknown"}]${assetName}`;
              })
              .join("\n");

      return {
        content: [{ type: "text", text: summary }],
        structuredContent: { selection, selectionFile },
      };
    },
  );

  mcpServer.registerTool(
    TOOL_INSERT_IMAGE,
    {
      title: "Insert JLC Hardware Learning Image",
      description:
        "Copy a local bitmap or a locally rendered official EasyEDA PDF page into a JLC Hardware Learning page-local assets folder, create a tldraw image asset and shape, replace a targeted AI image holder by default, otherwise place it beside an anchor or clear page area, and save the project-backed JLC Hardware Learning canvas.",
      inputSchema: {
        imagePath: z.string().trim(),
        projectDir: z.string().trim().optional(),
        canvasDir: z.string().trim().optional(),
        sourceUrl: z.string().trim().optional(),
        pageId: z.string().trim().optional(),
        anchorShapeId: z.string().trim().optional(),
        sourceShapeId: z.string().trim().optional(),
        fileName: z.string().trim().optional(),
        placement: z.enum(["right", "left", "below"]).optional(),
        margin: z.number().optional(),
        matchAnchor: z.boolean().optional(),
        replaceAiImageHolder: z.boolean().optional(),
        displayWidth: z.number().optional(),
        displayHeight: z.number().optional(),
        altText: z.string().trim().optional(),
        annotationScreenshot: z.string().trim().optional(),
        shapeMeta: z.record(z.string(), z.unknown()).optional(),
        assetMeta: z.record(z.string(), z.unknown()).optional(),
        evidenceSource: z.enum([
          "user-provided-local-image",
          "official-easyeda-export",
          "official-easyeda-pdf-render",
          "official-datasheet-figure",
        ]).optional(),
        dryRun: z.boolean().optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async (input = {}) => {
      const result = await insertHardwareLearningImage(input);
      return {
        content: [
          {
            type: "text",
            text: `${result.dryRun ? "Planned" : "Inserted"} ${result.shapeId} on ${result.pageId} at (${result.bounds.x}, ${result.bounds.y}) using ${result.index}.`,
          },
        ],
        structuredContent: result,
      };
    },
  );
}

function normalizeDisplayMode(displayMode) {
  const parsed = displayModeSchema.safeParse(displayMode);
  return parsed.success ? parsed.data : DEFAULT_DISPLAY_MODE;
}
