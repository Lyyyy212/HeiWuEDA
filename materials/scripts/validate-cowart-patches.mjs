import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MATERIALS_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const WORKBENCH_ROOT = path.resolve(MATERIALS_ROOT, "..");
const lock = JSON.parse(fs.readFileSync(path.join(MATERIALS_ROOT, "manifests", "integrations.lock.json"), "utf8"));
const cowart = lock.integrations.find((item) => item.name === "Cowart");
if (!cowart?.patchOverlay) throw new Error("Cowart patch overlay is not locked.");
if (cowart.patchOverlay.patches.length !== 37) throw new Error("Expected the complete 37-patch Cowart overlay.");
if (cowart.patchOverlay.patches.at(-1)?.testedCommit !== "f9f2f4e220c025c995bd7c26af98de8ced8d50d0") {
  throw new Error("Cowart unified trash deletion tested commit is not locked.");
}

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function git(cwd, ...args) {
  return execFileSync("git", ["-C", cwd, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

const source = path.join(MATERIALS_ROOT, ...cowart.localPath.split("/"));
const patchPaths = cowart.patchOverlay.patches.map((record) => {
  const patchPath = path.resolve(MATERIALS_ROOT, ...record.path.split("/"));
  if (!patchPath.startsWith(WORKBENCH_ROOT + path.sep)) throw new Error(`Patch escapes workbench: ${patchPath}`);
  if (sha256(patchPath) !== record.sha256) throw new Error(`Cowart patch hash mismatch: ${record.path}`);
  const text = fs.readFileSync(patchPath, "utf8");
  if (/^diff --git a\/mcp\/generated\//m.test(text)) throw new Error("Patch must not carry generated Cowart bundles.");
  return patchPath;
});

const verifyRoot = await mkdtemp(path.join(tmpdir(), "cowart-patch-verify-"));
try {
  execFileSync("git", ["clone", "--shared", "--no-checkout", source, verifyRoot], { stdio: "pipe" });
  git(verifyRoot, "checkout", "--detach", cowart.patchOverlay.baseCommit);
  for (const patchPath of patchPaths) {
    git(verifyRoot, "apply", "--check", patchPath);
    git(verifyRoot, "apply", patchPath);
  }
  for (const relativePath of [
    "mcp/server.mjs",
    "mcp/learning/storage.mjs",
    "mcp/learning/conversation-question.mjs",
    "mcp/learning/conversation-question.test.mjs",
    "mcp/lib/widget-resource.mjs",
    "src/learning/hardwareLearningProfile.js",
    "src/learning/learningAnnotations.js",
    "src/learning-canvas/model.js",
    "src/learning-canvas/annotations.js",
    "src/learning-canvas/export.js",
    "scripts/probe-hardware-learning.mjs",
    "scripts/probe-learning-tools.mjs",
  ]) {
    execFileSync(process.execPath, ["--check", path.join(verifyRoot, relativePath)], { stdio: "pipe" });
  }
  const server = await readFile(path.join(verifyRoot, "mcp", "server.mjs"), "utf8");
  for (const tool of ["save_cowart_learning_question", "insert_cowart_learning_annotations"]) {
    if (!server.includes(tool)) throw new Error(`Patched Cowart server is missing ${tool}`);
  }
  if (!server.includes("cowartWidgetResourceUri") ||
      !server.includes("resourceUri: COWART_WIDGET_URI") ||
      server.includes('const COWART_WIDGET_URI = "ui://widget/cowart/canvas.html"')) {
    throw new Error("Cowart Widget resource URI must be derived from the runtime plugin version.");
  }
  const storage = await readFile(path.join(verifyRoot, "mcp", "learning", "storage.mjs"), "utf8");
  for (const prohibited of ["imageUrl", "assetUrl", "html", "embed", "video", "slides"]) {
    if (!storage.includes(`\"${prohibited}\"`)) throw new Error(`Annotation forbidden key is missing: ${prohibited}`);
  }
  const app = await readFile(path.join(verifyRoot, "src", "App.jsx"), "utf8");
  const styles = await readFile(path.join(verifyRoot, "src", "styles.css"), "utf8");
  const main = await readFile(path.join(verifyRoot, "src", "main.jsx"), "utf8");
  const learningCanvas = await readFile(path.join(verifyRoot, "src", "learning-canvas", "HardwareLearningCanvas.jsx"), "utf8");
  const learningShape = await readFile(path.join(verifyRoot, "src", "learning-canvas", "LearningShape.jsx"), "utf8");
  const inlineTextEditor = await readFile(path.join(verifyRoot, "src", "learning-canvas", "InlineCanvasTextEditor.jsx"), "utf8");
  const textEditing = await readFile(path.join(verifyRoot, "src", "learning-canvas", "textEditing.js"), "utf8");
  const learningStyles = await readFile(path.join(verifyRoot, "src", "learning-canvas", "styles.css"), "utf8");
  const learningModel = await readFile(path.join(verifyRoot, "src", "learning-canvas", "model.js"), "utf8");
  const learningHistory = await readFile(path.join(verifyRoot, "src", "learning-canvas", "history.js"), "utf8");
  const learningExport = await readFile(path.join(verifyRoot, "src", "learning-canvas", "export.js"), "utf8");
  const artifactBuilder = await readFile(path.join(verifyRoot, "scripts", "build-release-artifacts.mjs"), "utf8");
  const widgetResource = await readFile(path.join(verifyRoot, "mcp", "lib", "widget-resource.mjs"), "utf8");
  const conversation = await readFile(path.join(verifyRoot, "mcp", "learning", "conversation-question.mjs"), "utf8");
  if (/HardwareQuestionPanel|cowart-hardware-question-panel/u.test(app + styles)) {
    throw new Error("The bottom-right hardware-learning panel is still enabled.");
  }
  if (!conversation.includes("last-non-empty") || !conversation.includes("selection-frame")) {
    throw new Error("Conversation-backed retained selection handling is missing.");
  }
  if (!main.includes("__COWART_HARDWARE_LEARNING_BUILD__") ||
      !learningCanvas.includes('data-engine="cowart-learning-canvas-v2"')) {
    throw new Error("The dedicated hardware-learning canvas entrypoint is missing.");
  }
  if (!learningCanvas.includes("cowartLearningFrame") || !learningCanvas.includes("selectionRevision")) {
    throw new Error("Explicit learning-frame or revision semantics are missing.");
  }
  if (!learningShape.includes("learning-frame-number") ||
      !learningShape.includes("cowartLearningFrameNumber") ||
      !learningCanvas.includes("cameraZoom={camera.z}")) {
    throw new Error("Persistent, zoom-stable learning-frame number badges are missing.");
  }
  if (!conversation.includes("parseLearningFrameReferences") ||
      !conversation.includes('source: "frame-number-reference"') ||
      !conversation.includes("selectedFrameNumbers") ||
      !conversation.includes("referencedFrameNumbers")) {
    throw new Error("Number-addressable single or multi-frame question capture is missing.");
  }
  for (const landmark of ["cowart-top-actions", "cowart-style-panel", "cowart-bottom-toolbar", "cowart-zoom-controls"]) {
    if (!learningCanvas.includes(landmark)) throw new Error(`Original-style Cowart UI landmark is missing: ${landmark}`);
  }
  for (const capability of ["duplicateLearningShapes", "marqueeBounds", "createEllipseShape", "createLineShape"]) {
    if (!learningCanvas.includes(capability)) throw new Error(`Replicated Cowart interaction is missing: ${capability}`);
  }
  for (const capability of ["toggleSelectedImageLock", "learning-image-lock", "setImageLockState", "setTool('select')"]) {
    if (!learningCanvas.includes(capability)) throw new Error(`Cowart Escape/image-lock interaction is missing: ${capability}`);
  }
  if (!inlineTextEditor.includes("learning-inline-text-editor") ||
      /learning-note-dialog|learning-dialog-backdrop/u.test(learningCanvas + inlineTextEditor + learningStyles)) {
    throw new Error("Cowart text and sticky-note editing must stay inline on the canvas.");
  }
  if (!inlineTextEditor.includes("pageToScreen(point, camera)") || /<foreignObject/u.test(learningCanvas + inlineTextEditor)) {
    throw new Error("Cowart text and sticky-note editing must use the host-focusable HTML overlay.");
  }
  if (!learningCanvas.includes("flushSync(() => {") ||
      !learningCanvas.includes("setNoteDraft(draft)") ||
      !inlineTextEditor.includes('data-cowart-inline-editor="true"')) {
    throw new Error("Cowart text and sticky-note editing must focus on the first canvas click.");
  }
  if (!inlineTextEditor.includes("input.setSelectionRange(caret, caret)") ||
      !textEditing.includes("key !== 'Enter'") ||
      !inlineTextEditor.includes("event.nativeEvent.isComposing")) {
    throw new Error("Cowart existing text must resume at the end and confirm with composition-safe Enter.");
  }
  if (!learningModel.includes("LEARNING_TEXT_METRICS") ||
      !learningModel.includes("layoutLearningText") ||
      !learningShape.includes("fontSize={textLayout.fontSize}") ||
      !inlineTextEditor.includes("textMetrics.fontSize * camera.z") ||
      !learningExport.includes('font-size="${textLayout.fontSize}"')) {
    throw new Error("Cowart right-side size controls must govern displayed, edited, and exported text.");
  }
  if (!learningCanvas.includes("beginShapeTextEdit(selectedShape)") ||
      !learningCanvas.includes("tool === 'text' && textKind === 'text'") ||
      !learningCanvas.includes("tool === 'note' && textKind === 'note'") ||
      !learningCanvas.includes("beginShapeTextEdit(shape)")) {
    throw new Error("Cowart existing text must reopen from selection Enter, matching-tool click, or double-click.");
  }
  if (!learningCanvas.includes("shouldBeginCanvasTextFromDoubleClick") ||
      !learningCanvas.includes("rightClickCanvasAction") ||
      !learningCanvas.includes("onDoubleClick={handleCanvasDoubleClick}") ||
      !learningCanvas.includes("onContextMenu={handleCanvasContextMenu}") ||
      !inlineTextEditor.includes("Esc/右键退出选择")) {
    throw new Error("Cowart select-mode double-click placement or right-click exit is missing.");
  }
  if (!learningCanvas.includes("deleteSelectedShapes") ||
      !learningCanvas.includes("learning-delete-image-dialog") ||
      !learningCanvas.includes("acknowledgedImageShapeDeletes: result.deletedImages") ||
      !learningCanvas.includes('label="删除选中内容"') ||
      learningCanvas.includes('testId="learning-delete-image"') ||
      !learningCanvas.includes("不会修改嘉立创 EDA 工程") ||
      !learningModel.includes("export function deleteSelectedShapes") ||
      !learningModel.includes("export function deleteImportedImages") ||
      !learningHistory.includes("metadata: cloneValue(delta.metadata)")) {
    throw new Error("Cowart unified trash deletion and redo authorization are incomplete.");
  }
  for (const exportControl of [
    "learning-export",
    "learning-export-page-png",
    "learning-export-selection-png",
    "learning-export-page-svg",
    "learning-export-canvas-json",
  ]) {
    if (!learningCanvas.includes(exportControl)) throw new Error(`Cowart export control is missing: ${exportControl}`);
  }
  if (!learningCanvas.includes("directoryName: 'Cowart学习画板'") ||
      !learningCanvas.includes("learning-choose-export-directory") ||
      !learningCanvas.includes("directoryToken: exportDirectory.directoryToken") ||
      !learningCanvas.includes("导出服务没有返回文件保存位置。") ||
      !learningCanvas.includes("learning-export-result")) {
    throw new Error("Cowart exports must support a compact menu, approved location token, and concrete result path.");
  }
  if (!server.includes("TOOL_CHOOSE_EXPORT_DIRECTORY") ||
      !server.includes("approvedCowartExportDirectories") ||
      !server.includes("Cowart 导出位置已失效，请重新选择文件夹。")) {
    throw new Error("Cowart system directory selection must stay tokenized and canvas-bound.");
  }
  if (!learningCanvas.includes("id: 'frame', label: '学习框'") ||
      /<small>\{label\}<\/small>/u.test(learningCanvas)) {
    throw new Error("The bottom toolbar learning-frame icon must not render the old visible 标注 caption.");
  }
  if (/\bTldraw\b|tl-watermark|Made with tldraw|production license/u.test(learningCanvas + learningStyles)) {
    throw new Error("The hardware-learning Widget must not render or hide a tldraw runtime/watermark.");
  }
  if (!artifactBuilder.includes("cowart-learning-canvas-v2") ||
      !artifactBuilder.includes("tl-watermark") ||
      !artifactBuilder.includes("Made with tldraw")) {
    throw new Error("Release build assertions for the dedicated learning Widget are missing.");
  }
  if (!widgetResource.includes("{ autoResize: false }") ||
      !widgetResource.includes('if (displayMode === "fullscreen") return;') ||
      !widgetResource.includes("lastReportedSize")) {
    throw new Error("Cowart fullscreen host-resize feedback-loop guards are missing.");
  }
  if (!learningModel.includes("export function shapeIntersectsViewport") ||
      !learningCanvas.includes("data-rendered-image-count") ||
      !learningCanvas.includes("learning-canvas-viewport-clip") ||
      !learningCanvas.includes("addEventListener('wheel', handleWheel, { passive: false })") ||
      !learningStyles.includes("contain: strict") ||
      !learningStyles.includes("overflow: hidden")) {
    throw new Error("Cowart viewport-culling or paint-containment guards are missing.");
  }
  if (!app.includes("COWART_TLDRAW_LICENSE_KEY") ||
      !app.includes("licenseKey={COWART_TLDRAW_LICENSE_KEY || undefined}")) {
    throw new Error("The supported tldraw license-key path is missing.");
  }
  if (/tl-watermark|SEE-LICENSE/u.test(styles)) {
    throw new Error("Cowart must not hide or obscure the tldraw watermark with CSS.");
  }
  if (/getExportDocumentFile|\beda\.|imagegen|insert_cowart_image/u.test(conversation)) {
    throw new Error("Conversation question capture must not call EasyEDA or generation tools.");
  }
  if (!server.includes("normal Codex conversation") ||
      !/registerAppTool\(\s*mcpServer,\s*TOOL_SAVE_LEARNING_QUESTION[\s\S]*?visibility: \["model", "app"\]/u.test(server)) {
    throw new Error("Conversation-backed learning question tool is not model-visible.");
  }
  if (!server.includes("beginChunkedCowartDownload") ||
      !/registerAppTool\(\s*mcpServer,\s*TOOL_DOWNLOAD_FILE[\s\S]*?"openai\/widgetAccessible": true/u.test(server)) {
    throw new Error("Widget-accessible chunked Cowart export is missing.");
  }
  if (!server.includes("completedCowartDownloads") || !server.includes("chunkDigests")) {
    throw new Error("Cowart chunked export retries are not idempotent.");
  }
  if (!server.includes("assetMeta.evidenceSource = evidenceSource") ||
      !server.includes("shapeMeta.evidenceSource = evidenceSource")) {
    throw new Error("Admitted image evidenceSource is not persisted on Cowart records.");
  }
  if (!server.includes("official-easyeda-pdf-render")) {
    throw new Error("Official EasyEDA PDF-render evidence is not admitted by Cowart.");
  }
  process.stdout.write(`${JSON.stringify({
    status: "PASS",
    baseCommit: cowart.patchOverlay.baseCommit,
    patches: patchPaths.map((item) => path.basename(item)),
    patchedToolCount: cowart.patchOverlay.patchedToolCount,
    generatedBundlesIncluded: false,
  }, null, 2)}\n`);
} finally {
  await rm(verifyRoot, { recursive: true, force: true });
}
