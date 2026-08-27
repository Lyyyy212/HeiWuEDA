import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, unlink, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { tmpdir } from "node:os";
import path from "node:path";
import { performance } from "node:perf_hooks";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const transportEnvironment = Object.fromEntries(
  Object.entries(process.env).filter(([, value]) => typeof value === "string"),
);
const serverRoot = path.resolve(optionValue("--server-root") || process.cwd());
const maximumStartupMs = Number(optionValue("--max-startup-ms") || 0);
const pluginManifest = JSON.parse(
  await readFile(path.join(serverRoot, ".codex-plugin", "plugin.json"), "utf8"),
);
const widgetCacheKey = String(pluginManifest.version || "")
  .trim()
  .replace(/[^A-Za-z0-9._-]+/g, "-")
  .replace(/^-+|-+$/g, "");
const expectedWidgetUri = `ui://widget/jlc-hardware-learning/canvas-${widgetCacheKey}.html`;
transportEnvironment.JLC_HARDWARE_LEARNING_PLUGIN_ROOT = serverRoot;
const transport = new StdioClientTransport({
  command: "node",
  args: ["./scripts/start-mcp.mjs"],
  cwd: serverRoot,
  env: transportEnvironment,
});

const client = new Client({
  name: "jlc-hardware-learning-probe",
  version: "0.1.0",
});
const toolsOnly = process.argv.includes("--tools-only");

const startupStartedAt = performance.now();
await client.connect(transport);

let downloadedProbePath = null;
let downloadedChunkedProbePath = null;
let downloadedProbeDirectory = null;
let projectDir = null;

function isCanvasDirectory(value) {
  const canvasDir = String(value || "");
  return (
    path.basename(path.normalize(canvasDir)) === "canvas" ||
    path.win32.basename(path.win32.normalize(canvasDir)) === "canvas"
  );
}

try {
  probe: {
  const tools = await client.listTools();
  const startupMs = performance.now() - startupStartedAt;
  if (maximumStartupMs > 0 && startupMs > maximumStartupMs) {
    throw new Error(
      `JLC Hardware Learning MCP tool discovery took ${Math.round(startupMs)} ms; expected at most ${maximumStartupMs} ms.`,
    );
  }
  const toolNames = tools.tools.map((tool) => tool.name);
  const requiredTools = [
    "render_hardware_learning_canvas_widget",
    "get_hardware_learning_canvas_state",
    "save_hardware_learning_canvas_state",
    "save_hardware_learning_selection_state",
    "save_hardware_learning_view_state",
    "manage_hardware_learning_canvases",
    "save_hardware_learning_reference_image",
    "read_hardware_learning_page_asset",
    "choose_hardware_learning_export_directory",
    "download_hardware_learning_file",
    "copy_hardware_learning_image_to_clipboard",
    "get_hardware_learning_selection",
    "insert_hardware_learning_image",
    "save_hardware_learning_question",
    "insert_hardware_learning_annotations",
    "attach_hardware_learning_page_netlist",
    "read_hardware_learning_page_netlist",
    "get_feishu_learning_note_state",
    "update_feishu_learning_note_state",
    "inspect_feishu_learning_note_target",
    "preview_feishu_learning_note_migration",
    "execute_feishu_learning_note_migration",
  ];

  for (const toolName of requiredTools) {
    if (!toolNames.includes(toolName)) {
      throw new Error(`${toolName} not found. Tools: ${toolNames.join(", ")}`);
    }
  }

  if (toolNames.some((name) => /analytics|telemetry|html_draft/.test(name))) {
    throw new Error(`Dedicated JLC Hardware Learning tools must not expose analytics, telemetry, or HTML generation: ${toolNames.join(", ")}`);
  }
  const clipboardTool = tools.tools.find((tool) => tool.name === "copy_hardware_learning_image_to_clipboard");
  if (JSON.stringify(clipboardTool?._meta?.ui?.visibility) !== JSON.stringify(["app"])) {
    throw new Error("JLC Hardware Learning clipboard tool should only be visible to the widget app.");
  }
  const downloadTool = tools.tools.find((tool) => tool.name === "download_hardware_learning_file");
  if (!downloadTool?._meta?.["openai/widgetAccessible"] || !downloadTool?._meta?.ui?.visibility?.includes("app")) {
    throw new Error("JLC Hardware Learning download tool should be callable from the widget app.");
  }
  if (!downloadTool?.inputSchema?.properties?.directoryToken) {
    throw new Error("JLC Hardware Learning download tool should accept a user-approved directory token.");
  }
  const chooseExportDirectoryTool = tools.tools.find((tool) => tool.name === "choose_hardware_learning_export_directory");
  if (
    JSON.stringify(chooseExportDirectoryTool?._meta?.ui?.visibility) !== JSON.stringify(["app"]) ||
    chooseExportDirectoryTool?._meta?.["openai/widgetAccessible"] !== true
  ) {
    throw new Error("JLC Hardware Learning export directory chooser should only be callable from the widget app.");
  }
  const manageCanvasesTool = tools.tools.find((tool) => tool.name === "manage_hardware_learning_canvases");
  if (
    JSON.stringify(manageCanvasesTool?._meta?.ui?.visibility) !== JSON.stringify(["app"]) ||
    manageCanvasesTool?._meta?.["openai/widgetAccessible"] !== true
  ) {
    throw new Error("JLC Hardware Learning canvas manager should only be callable from the widget app.");
  }

  projectDir = await mkdtemp(path.join(tmpdir(), "jlc-hardware-learning-widget-probe-"));
  const renderResult = await client.callTool({
    name: "render_hardware_learning_canvas_widget",
    arguments: {
      projectDir,
      title: "Probe JLC Hardware Learning",
    },
  });
  if (renderResult._meta?.["openai/outputTemplate"] !== expectedWidgetUri) {
    throw new Error("JLC Hardware Learning render tool result did not include the expected outputTemplate.");
  }
  if (renderResult.structuredContent?.resourceUri !== expectedWidgetUri) {
    throw new Error("JLC Hardware Learning render tool result did not expose its versioned resource URI.");
  }
  if (renderResult.structuredContent?.preferredDisplayMode !== "fullscreen") {
    throw new Error("JLC Hardware Learning render tool did not default to fullscreen display mode.");
  }
  if (renderResult.structuredContent?.projectDir !== projectDir) {
    throw new Error("JLC Hardware Learning render tool did not preserve the requested projectDir.");
  }
  if (renderResult.structuredContent?.canvasCatalog?.activeCanvasId !== "default") {
    throw new Error("Fresh JLC Hardware Learning projects should render the protected default canvas.");
  }
  if (toolsOnly) {
    console.log(
      `OK: JLC Hardware Learning MCP tools are available before the widget resource is built (${Math.round(startupMs)} ms).`,
    );
    break probe;
  }

  const createdCanvas = await client.callTool({
    name: "manage_hardware_learning_canvases",
    arguments: { projectDir, action: "create", name: "Probe Canvas" },
  });
  const createdCanvasId = createdCanvas.structuredContent?.activeCanvasId;
  const createdCanvasDir = createdCanvas.structuredContent?.activeCanvas?.canvasDir;
  if (!createdCanvasId || createdCanvasId === "default" || !createdCanvasDir) {
    throw new Error("JLC Hardware Learning canvas manager did not create and activate an independent canvas.");
  }
  const renamedCanvas = await client.callTool({
    name: "manage_hardware_learning_canvases",
    arguments: { projectDir, action: "rename", canvasId: createdCanvasId, name: "Renamed Probe Canvas" },
  });
  if (renamedCanvas.structuredContent?.activeCanvas?.name !== "Renamed Probe Canvas") {
    throw new Error("JLC Hardware Learning canvas manager did not rename the active canvas.");
  }
  await client.callTool({
    name: "manage_hardware_learning_canvases",
    arguments: { projectDir, action: "activate", canvasId: "default" },
  });
  const recycledCanvas = await client.callTool({
    name: "manage_hardware_learning_canvases",
    arguments: { projectDir, action: "recycle", canvasId: createdCanvasId },
  });
  if (recycledCanvas.structuredContent?.activeCanvasId !== "default") {
    throw new Error("Recycling a JLC Hardware Learning canvas should preserve the protected default canvas.");
  }
  await readFile(path.join(recycledCanvas.structuredContent.recycledDir, "pages", "manifest.json"), "utf8");
  await assert.rejects(readFile(path.join(createdCanvasDir, "pages", "manifest.json"), "utf8"), { code: "ENOENT" });

  const stateResult = await client.callTool({
    name: "get_hardware_learning_canvas_state",
    arguments: {
      projectDir,
    },
  });
  if (stateResult.structuredContent?.storage !== "per-page" || !stateResult.structuredContent?.snapshot) {
    throw new Error("Rendering a fresh JLC Hardware Learning project should initialize its project-local canvas.");
  }
  if (!isCanvasDirectory(stateResult.structuredContent?.canvasDir)) {
    throw new Error("JLC Hardware Learning canvas state did not report a project-local canvas directory.");
  }
  if ((stateResult.structuredContent?.hydratedAssets || []).length !== 0) {
    throw new Error("JLC Hardware Learning canvas state should not hydrate image assets by default.");
  }

  const probePageAssetDir = path.join(projectDir, "canvas", "pages", "probe-page", "assets");
  await mkdir(probePageAssetDir, { recursive: true });
  await writeFile(
    path.join(probePageAssetDir, "tiny.png"),
    Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=", "base64"),
  );
  const pageAssetResult = await client.callTool({
    name: "read_hardware_learning_page_asset",
    arguments: {
      projectDir,
      assetUrl: "/page-assets/probe-page/tiny.png",
    },
  });
  if (pageAssetResult.structuredContent?.mimeType !== "image/png" || !pageAssetResult.structuredContent?.dataBase64) {
    throw new Error("JLC Hardware Learning page asset tool did not return the expected png payload.");
  }

  const clipboardResult = await client.callTool({
    name: "copy_hardware_learning_image_to_clipboard",
    arguments: {
      projectDir,
      dataBase64: pageAssetResult.structuredContent.dataBase64,
      mimeType: "image/png",
      dryRun: true,
    },
  });
  if (
    clipboardResult.structuredContent?.dryRun !== true ||
    clipboardResult.structuredContent?.width !== 1 ||
    clipboardResult.structuredContent?.height !== 1
  ) {
    throw new Error("JLC Hardware Learning clipboard tool did not validate the expected PNG payload.");
  }

  const downloadResult = await client.callTool({
    name: "download_hardware_learning_file",
    arguments: {
      projectDir,
      assetUrl: "/page-assets/probe-page/tiny.png",
      fileName: `jlc-hardware-learning-download-probe-${process.pid}.png`,
    },
  });
  downloadedProbePath = downloadResult.structuredContent?.filePath;
  if (!downloadedProbePath || !(await readFile(downloadedProbePath)).length) {
    throw new Error("JLC Hardware Learning download tool did not write the expected file into Downloads.");
  }

  const chunkedText = "JLC Hardware Learning chunked export probe ".repeat(20_000);
  const chunkedBase64 = Buffer.from(chunkedText, "utf8").toString("base64");
  const requestedDownloadId = randomUUID();
  const chunkedBegin = await client.callTool({
    name: "download_hardware_learning_file",
    arguments: {
      projectDir,
      action: "begin",
      downloadId: requestedDownloadId,
      fileName: `jlc-hardware-learning-chunked-export-probe-${process.pid}.txt`,
      mimeType: "text/plain",
      expectedBytes: Buffer.byteLength(chunkedText),
    },
  });
  const downloadId = chunkedBegin.structuredContent?.downloadId;
  if (!downloadId) throw new Error("JLC Hardware Learning chunked download did not create a session.");
  if (downloadId !== requestedDownloadId) throw new Error("JLC Hardware Learning chunked download changed the requested session ID.");
  const resumedBegin = await client.callTool({
    name: "download_hardware_learning_file",
    arguments: {
      projectDir,
      action: "begin",
      downloadId,
      fileName: `jlc-hardware-learning-chunked-export-probe-${process.pid}.txt`,
      mimeType: "text/plain",
      expectedBytes: Buffer.byteLength(chunkedText),
    },
  });
  if (resumedBegin.structuredContent?.resumed !== true) {
    throw new Error("JLC Hardware Learning chunked download begin retry was not idempotent.");
  }
  const chunkLength = 48 * 1024;
  let chunkIndex = 0;
  for (let offset = 0; offset < chunkedBase64.length; offset += chunkLength) {
    const chunkBase64 = chunkedBase64.slice(offset, offset + chunkLength);
    const appendResult = await client.callTool({
      name: "download_hardware_learning_file",
      arguments: {
        projectDir,
        action: "append",
        downloadId,
        chunkIndex,
        chunkBase64,
      },
    });
    if (chunkIndex === 0) {
      const duplicate = await client.callTool({
        name: "download_hardware_learning_file",
        arguments: { projectDir, action: "append", downloadId, chunkIndex, chunkBase64 },
      });
      if (duplicate.structuredContent?.duplicate !== true) {
        throw new Error("JLC Hardware Learning chunk retry was not idempotent.");
      }
    }
    if (appendResult.structuredContent?.chunkIndex !== chunkIndex) {
      throw new Error("JLC Hardware Learning chunked download returned an unexpected chunk index.");
    }
    chunkIndex += 1;
  }
  const chunkedFinish = await client.callTool({
    name: "download_hardware_learning_file",
    arguments: { projectDir, action: "finish", downloadId },
  });
  downloadedChunkedProbePath = chunkedFinish.structuredContent?.filePath;
  if (!downloadedChunkedProbePath || await readFile(downloadedChunkedProbePath, "utf8") !== chunkedText) {
    throw new Error("JLC Hardware Learning chunked export did not preserve the complete payload.");
  }
  const duplicateFinish = await client.callTool({
    name: "download_hardware_learning_file",
    arguments: { projectDir, action: "finish", downloadId },
  });
  if (duplicateFinish.structuredContent?.duplicate !== true || duplicateFinish.structuredContent?.filePath !== downloadedChunkedProbePath) {
    throw new Error("JLC Hardware Learning chunked download finish retry was not idempotent.");
  }

  const folderDownloadResult = await client.callTool({
    name: "download_hardware_learning_file",
    arguments: {
      projectDir,
      dataUrl: "data:text/html;charset=utf-8,%3C!doctype%20html%3E%3Ctitle%3Eprobe%3C%2Ftitle%3E",
      directoryName: `JLC Hardware Learning Export Probe ${process.pid}`,
      subdirectory: "pages",
      fileName: "page-01.html",
      mimeType: "text/html",
      overwrite: true,
      uniqueDirectory: true,
    },
  });
  downloadedProbeDirectory = folderDownloadResult.structuredContent?.directoryPath;
  const folderDownloadPath = folderDownloadResult.structuredContent?.filePath;
  if (
    !downloadedProbeDirectory ||
    path.basename(path.dirname(folderDownloadPath || "")) !== "pages" ||
    !(await readFile(folderDownloadPath, "utf8")).includes("<title>probe</title>")
  ) {
    throw new Error("JLC Hardware Learning download tool did not create the expected Slides export folder structure.");
  }

  const resource = await client.readResource({
    uri: expectedWidgetUri,
  });
  const resourceItem = resource.contents?.[0] || {};
  if (resourceItem.uri !== expectedWidgetUri) {
    throw new Error(`JLC Hardware Learning widget resource returned ${resourceItem.uri || "no URI"}; expected ${expectedWidgetUri}.`);
  }
  if (resourceItem.mimeType !== "text/html;profile=mcp-app") {
    throw new Error(
      `JLC Hardware Learning widget resource must use text/html;profile=mcp-app, received ${resourceItem.mimeType || "no MIME type"}.`,
    );
  }
  const resourceMeta = resourceItem._meta || {};
  const widgetCsp = resourceMeta["openai/widgetCSP"] || {};
  const connectDomains = widgetCsp.connect_domains || [];
  if (connectDomains.length !== 0) {
    throw new Error(`JLC Hardware Learning widget CSP must not allow network connections. Found: ${connectDomains.join(", ")}`);
  }
  const resourceDomains = widgetCsp.resource_domains || [];
  if (!resourceDomains.includes("data:") || !resourceDomains.includes("blob:")) {
    throw new Error(`JLC Hardware Learning widget CSP should allow local data/blob resources. Found: ${resourceDomains.join(", ")}`);
  }
  if (resourceDomains.some((domain) => /^https?:/i.test(domain))) {
    throw new Error(`JLC Hardware Learning widget CSP must not allow remote resources. Found: ${resourceDomains.join(", ")}`);
  }
  const frameDomains = widgetCsp.frame_domains || [];
  if (frameDomains.length !== 0) {
    throw new Error(`JLC Hardware Learning widget CSP must not allow frames. Found: ${frameDomains.join(", ")}`);
  }

  const widgetHtml = resourceItem.text || "";
  if (!widgetHtml.includes("window.hardwareLearningMcp") || !widgetHtml.includes("JLC Hardware Learning Canvas")) {
    throw new Error("JLC Hardware Learning widget HTML does not include the expected bridge and app shell.");
  }
  if (/<script\b[^>]*\btype="module"/i.test(widgetHtml)) {
    throw new Error("JLC Hardware Learning widget HTML should use classic inline scripts for host compatibility.");
  }
  const shellMarkup = widgetHtml
    .replace(/<script\b[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[\s\S]*?<\/style>/gi, "");
  if (/<iframe\b/i.test(shellMarkup) || /<script\b[^>]+\bsrc=/i.test(shellMarkup) || /<link\b[^>]+\bhref=/i.test(shellMarkup)) {
    throw new Error("JLC Hardware Learning widget HTML should be direct static markup without iframe or external asset tags.");
  }

  console.log(
    `OK: JLC Hardware Learning MCP tools and native widget resource are available (${Math.round(startupMs)} ms startup).`,
  );
  }
} finally {
  if (downloadedProbePath) {
    await unlink(downloadedProbePath).catch(() => undefined);
  }
  if (downloadedChunkedProbePath) {
    await unlink(downloadedChunkedProbePath).catch(() => undefined);
  }
  if (downloadedProbeDirectory) {
    await rm(downloadedProbeDirectory, { recursive: true, force: true }).catch(() => undefined);
  }
  if (projectDir) {
    await rm(projectDir, { recursive: true, force: true }).catch(() => undefined);
  }
  await client.close();
}

function optionValue(name) {
  const exactIndex = process.argv.indexOf(name);
  if (exactIndex !== -1) return process.argv[exactIndex + 1] || "";
  const prefix = `${name}=`;
  const inline = process.argv.find((arg) => arg.startsWith(prefix));
  return inline ? inline.slice(prefix.length) : "";
}
