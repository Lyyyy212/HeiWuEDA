import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";

const [pluginRootArg, projectDirArg, imagePathArg, projectUuid, documentUuid, expectedSha256] =
  process.argv.slice(2);
assert.ok(expectedSha256, "usage: node probe-hardware-learning-page-import.mjs <plugin-root> <fresh-project-dir> <png> <project-uuid> <document-uuid> <png-sha256>");

const pluginRoot = path.resolve(pluginRootArg);
const projectDir = path.resolve(projectDirArg);
const imagePath = path.resolve(imagePathArg);
const pageId = "page:acceptance";
const imageSha256 = createHash("sha256").update(await readFile(imagePath)).digest("hex");
assert.equal(imageSha256, expectedSha256.toLowerCase(), "source PNG digest mismatch");
await assert.rejects(() => stat(projectDir), /ENOENT/u, "acceptance project must be a fresh path");
await mkdir(projectDir, { recursive: false });

const schema = {
  schemaVersion: 2,
  sequences: {
    "com.tldraw.store": 5,
    "com.tldraw.asset": 1,
    "com.tldraw.camera": 1,
    "com.tldraw.document": 2,
    "com.tldraw.instance": 26,
    "com.tldraw.instance_page_state": 5,
    "com.tldraw.page": 1,
    "com.tldraw.instance_presence": 6,
    "com.tldraw.pointer": 1,
    "com.tldraw.shape": 4,
    "com.tldraw.user": 1,
    "com.tldraw.asset.image": 6,
    "com.tldraw.asset.video": 5,
    "com.tldraw.asset.bookmark": 2,
    "com.tldraw.shape.arrow": 8,
    "com.tldraw.shape.bookmark": 2,
    "com.tldraw.shape.draw": 4,
    "com.tldraw.shape.embed": 4,
    "com.tldraw.shape.frame": 1,
    "com.tldraw.shape.geo": 11,
    "com.tldraw.shape.group": 0,
    "com.tldraw.shape.highlight": 3,
    "com.tldraw.shape.image": 5,
    "com.tldraw.shape.line": 5,
    "com.tldraw.shape.note": 12,
    "com.tldraw.shape.text": 4,
    "com.tldraw.shape.video": 4,
    "com.tldraw.binding.arrow": 1,
  },
};

const server = spawn(process.execPath, [path.join(pluginRoot, "scripts", "start-mcp.mjs")], {
  cwd: pluginRoot,
  stdio: ["pipe", "pipe", "pipe"],
});
let stderr = "";
server.stderr.setEncoding("utf8");
server.stderr.on("data", (chunk) => { stderr += chunk; });
server.stdout.setEncoding("utf8");
let stdoutBuffer = "";
let nextId = 1;
const pending = new Map();
server.stdout.on("data", (chunk) => {
  stdoutBuffer += chunk;
  const lines = stdoutBuffer.split(/\r?\n/u);
  stdoutBuffer = lines.pop() ?? "";
  for (const line of lines.filter(Boolean)) {
    const message = JSON.parse(line);
    if (message.id !== undefined && pending.has(message.id)) {
      const { resolve, reject, timer } = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(timer);
      if (message.error) reject(new Error(JSON.stringify(message.error)));
      else resolve(message.result);
    }
  }
});

function request(method, params) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`MCP request ${method} timed out. ${stderr}`));
    }, 15_000);
    pending.set(id, { resolve, reject, timer });
    server.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
  });
}

function notify(method, params = {}) {
  server.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
}

async function callTool(name, args) {
  const result = await request("tools/call", { name, arguments: args });
  if (result.isError) throw new Error(result.content?.[0]?.text || `${name} failed`);
  return result.structuredContent;
}

try {
  const initialized = await request("initialize", {
    protocolVersion: "2025-11-25",
    capabilities: {},
    clientInfo: { name: "hardware-learning-page-import-acceptance", version: "1.0" },
  });
  notify("notifications/initialized");
  assert.match(initialized.serverInfo.version, /^0\.1\.27\+codex\./u);

  await callTool("render_hardware_learning_canvas_widget", {
    projectDir,
    mode: "hardware-learning",
    analyticsEnabled: false,
    displayMode: "fullscreen",
  });
  await callTool("save_hardware_learning_canvas_state", {
    projectDir,
    snapshot: {
      schema,
      store: {
        [pageId]: { meta: {}, id: pageId, name: "Acceptance", index: "a1", typeName: "page" },
      },
    },
  });
  const inserted = await callTool("insert_hardware_learning_image", {
    projectDir,
    pageId,
    imagePath,
    replaceAiImageHolder: false,
    displayWidth: 1536,
    evidenceSource: "official-easyeda-export",
    altText: `EasyEDA schematic page ${documentUuid}`,
    assetMeta: {
      schemaVersion: "learning.canvas-page-import.v1",
      scope: "current-schematic-official-native",
      visualSource: "official-native-current-schematic",
      projectUuid,
      documentUuid,
      renderSha256: imageSha256,
    },
    shapeMeta: {
      hardwareLearningEvidence: true,
      easyedaDocumentUuid: documentUuid,
    },
  });
  assert.equal(inserted.evidenceSource, "official-easyeda-export");
  assert.equal(inserted.pageId, pageId);

  const state = await callTool("get_hardware_learning_canvas_state", { projectDir, hydrateAssets: false });
  const records = Object.values(state.snapshot.store);
  const asset = records.find((record) => record?.id === inserted.assetId);
  const shape = records.find((record) => record?.id === inserted.shapeId);
  assert.equal(asset?.meta?.evidenceSource, "official-easyeda-export");
  assert.equal(shape?.meta?.evidenceSource, "official-easyeda-export");
  assert.equal(asset?.meta?.documentUuid, documentUuid);
  assert.equal(shape?.parentId, pageId);
  assert.equal(asset?.meta?.renderSha256, imageSha256);

  const assetFile = path.resolve(inserted.assetFile);
  const copiedSha256 = createHash("sha256").update(await readFile(assetFile)).digest("hex");
  assert.equal(copiedSha256, imageSha256);
  const acceptance = {
    schemaVersion: "jlc.hardware-learning-page-import-acceptance.v1",
    status: "PASS",
    serverVersion: initialized.serverInfo.version,
    projectDir,
    pageId,
    shapeId: inserted.shapeId,
    assetId: inserted.assetId,
    assetFile,
    projectUuid,
    documentUuid,
    evidenceSource: asset.meta.evidenceSource,
    sourceSha256: imageSha256,
    copiedSha256,
  };
  await writeFile(
    path.join(projectDir, "page-import-acceptance.json"),
    `${JSON.stringify(acceptance, null, 2)}\n`,
    { flag: "wx" },
  );
  console.log(JSON.stringify(acceptance, null, 2));
} finally {
  server.stdin.end();
  server.kill();
}
