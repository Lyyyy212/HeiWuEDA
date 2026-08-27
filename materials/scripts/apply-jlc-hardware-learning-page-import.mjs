import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";

const [pluginRootArg, manifestPathArg, acceptancePathArg] = process.argv.slice(2);
assert.ok(acceptancePathArg, "usage: node apply-hardware-learning-page-import.mjs <plugin-root> <import-manifest.json> <acceptance.json>");
const pluginRoot = path.resolve(pluginRootArg);
const manifestPath = path.resolve(manifestPathArg);
const acceptancePath = path.resolve(acceptancePathArg);
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
assert.equal(manifest.schemaVersion, "learning.canvas-page-import.v1");
assert.equal(manifest.status, "READY");
assert.equal(manifest.tool, "mcp__jlc_hardware_learning_mcp__insert_hardware_learning_image");
assert.equal(manifest.toolArgs.projectDir, manifest.projectDir);
assert.equal(manifest.toolArgs.pageId, manifest.canvasPageId);
assert.equal(manifest.toolArgs.replaceAiImageHolder, false);
assert.equal(manifest.toolArgs.evidenceSource, "official-easyeda-export");
assert.equal(manifest.toolArgs.assetMeta.evidenceSource, "official-easyeda-export");
assert.equal(manifest.toolArgs.assetMeta.documentUuid, manifest.easyedaIdentity.documentUuid);

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

const digestInput = structuredClone(manifest);
delete digestInput.manifestSha256;
const manifestSha256 = createHash("sha256")
  .update(JSON.stringify(canonical(digestInput)))
  .digest("hex");
assert.equal(manifestSha256, manifest.manifestSha256, "manifest digest mismatch");
const sourcePng = path.resolve(manifest.toolArgs.imagePath);
const sourcePngSha256 = createHash("sha256").update(await readFile(sourcePng)).digest("hex");
assert.equal(sourcePngSha256, manifest.toolArgs.assetMeta.renderSha256, "render PNG digest mismatch");
await assert.rejects(() => stat(acceptancePath), /ENOENT/u, "acceptance output already exists");

const server = spawn(process.execPath, [path.join(pluginRoot, "scripts", "start-mcp.mjs")], {
  cwd: pluginRoot,
  stdio: ["pipe", "pipe", "pipe"],
});
let stderr = "";
let stdoutBuffer = "";
let nextId = 1;
const pending = new Map();
server.stderr.setEncoding("utf8");
server.stderr.on("data", (chunk) => { stderr += chunk; });
server.stdout.setEncoding("utf8");
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
    clientInfo: { name: "hardware-learning-page-import-apply", version: "1.0" },
  });
  notify("notifications/initialized");
  await callTool("render_hardware_learning_canvas_widget", {
    projectDir: manifest.projectDir,
    mode: "hardware-learning",
    analyticsEnabled: false,
    displayMode: "fullscreen",
  });
  const before = await callTool("get_hardware_learning_canvas_state", {
    projectDir: manifest.projectDir,
    hydrateAssets: false,
  });
  assert.ok(before.snapshot?.store?.[manifest.canvasPageId], "target JLC Hardware Learning page does not exist");
  const duplicate = Object.values(before.snapshot.store).find((record) =>
    record?.typeName === "asset" &&
    record?.meta?.documentUuid === manifest.easyedaIdentity.documentUuid &&
    record?.meta?.renderSha256 === sourcePngSha256
  );
  assert.equal(duplicate, undefined, "this page evidence is already present on the JLC Hardware Learning canvas");

  const inserted = await callTool("insert_hardware_learning_image", manifest.toolArgs);
  assert.equal(inserted.evidenceSource, "official-easyeda-export");
  assert.equal(inserted.pageId, manifest.canvasPageId);
  const after = await callTool("get_hardware_learning_canvas_state", {
    projectDir: manifest.projectDir,
    hydrateAssets: false,
  });
  const asset = after.snapshot.store[inserted.assetId];
  const shape = after.snapshot.store[inserted.shapeId];
  assert.equal(asset?.meta?.evidenceSource, "official-easyeda-export");
  assert.equal(shape?.meta?.evidenceSource, "official-easyeda-export");
  assert.equal(asset?.meta?.documentUuid, manifest.easyedaIdentity.documentUuid);
  assert.equal(shape?.parentId, manifest.canvasPageId);
  assert.equal(asset?.meta?.renderSha256, sourcePngSha256);
  const copiedSha256 = createHash("sha256").update(await readFile(inserted.assetFile)).digest("hex");
  assert.equal(copiedSha256, sourcePngSha256);

  const acceptance = {
    schemaVersion: "jlc.hardware-learning-page-import-apply-acceptance.v1",
    status: "PASS",
    serverVersion: initialized.serverInfo.version,
    manifestPath,
    manifestSha256,
    projectDir: manifest.projectDir,
    pageId: manifest.canvasPageId,
    shapeId: inserted.shapeId,
    assetId: inserted.assetId,
    assetFile: inserted.assetFile,
    projectUuid: manifest.easyedaIdentity.projectUuid,
    documentUuid: manifest.easyedaIdentity.documentUuid,
    evidenceSource: asset.meta.evidenceSource,
    sourceSha256: sourcePngSha256,
    copiedSha256,
  };
  await writeFile(acceptancePath, `${JSON.stringify(acceptance, null, 2)}\n`, { flag: "wx" });
  console.log(JSON.stringify(acceptance, null, 2));
} finally {
  server.stdin.end();
  server.kill();
}
