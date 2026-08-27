import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";

const [pluginRootArg, manifestPathArg, acceptancePathArg] = process.argv.slice(2);
assert.ok(
  acceptancePathArg,
  "usage: node apply-jlc-hardware-learning-project-import.mjs <plugin-root> <project-import-manifest.json> <acceptance.json>",
);
const pluginRoot = path.resolve(pluginRootArg);
const manifestPath = path.resolve(manifestPathArg);
const acceptancePath = path.resolve(acceptancePathArg);
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
assert.equal(manifest.schemaVersion, "learning.canvas-project-import.v1");
assert.equal(manifest.status, "READY");
assert.equal(manifest.reviewRequired, true);
assert.ok(Array.isArray(manifest.operations) && manifest.operations.length > 0);
assert.equal(manifest.render.pageCount, manifest.operations.length);
assert.equal(manifest.layout.anchorFromPreviousResult, true);

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

function sha256(data) {
  return createHash("sha256").update(data).digest("hex");
}

const digestInput = structuredClone(manifest);
delete digestInput.manifestSha256;
const manifestSha256 = sha256(JSON.stringify(canonical(digestInput)));
assert.equal(manifestSha256, manifest.manifestSha256, "manifest digest mismatch");
assert.equal(
  sha256(await readFile(path.resolve(manifest.source.path))),
  manifest.source.sha256,
  "project EPRO digest mismatch",
);
await assert.rejects(() => stat(acceptancePath), /ENOENT/u, "acceptance output already exists");

for (const [offset, operation] of manifest.operations.entries()) {
  assert.equal(operation.index, offset + 1);
  assert.equal(operation.tool, "mcp__jlc_hardware_learning_mcp__insert_hardware_learning_image");
  assert.equal(operation.toolArgs.projectDir, manifest.projectDir);
  assert.equal(operation.toolArgs.pageId, manifest.canvasPageId);
  assert.equal(operation.toolArgs.replaceAiImageHolder, false);
  assert.equal(operation.toolArgs.evidenceSource, "official-easyeda-export");
  assert.equal(operation.toolArgs.assetMeta.scope, "current-project-from-epro");
  assert.equal(operation.toolArgs.assetMeta.projectUuid, manifest.easyedaIdentity.projectUuid);
  assert.equal(operation.toolArgs.assetMeta.documentUuid, operation.documentUuid);
  assert.equal(operation.reviewRequired, true);
  assert.notEqual(operation.toolArgs.assetMeta.renderQuality.visualStatus, "QUALIFIED");
  const pngSha256 = sha256(await readFile(path.resolve(operation.toolArgs.imagePath)));
  assert.equal(pngSha256, operation.toolArgs.assetMeta.renderSha256);
}

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
    }, 20_000);
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

function findExistingPageEvidence(snapshot, operation) {
  const records = Object.values(snapshot.store ?? {});
  const asset = records.find((record) =>
    record?.typeName === "asset" &&
    record?.meta?.projectUuid === manifest.easyedaIdentity.projectUuid &&
    record?.meta?.documentUuid === operation.documentUuid &&
    record?.meta?.renderSha256 === operation.toolArgs.assetMeta.renderSha256
  );
  if (!asset) return null;
  const shape = records.find((record) =>
    record?.typeName === "shape" &&
    record?.parentId === manifest.canvasPageId &&
    record?.props?.assetId === asset.id
  );
  return shape ? { asset, shape } : null;
}

try {
  const initialized = await request("initialize", {
    protocolVersion: "2025-11-25",
    capabilities: {},
    clientInfo: { name: "jlc-hardware-learning-project-import-apply", version: "1.0" },
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

  const results = [];
  let anchorShapeId = null;
  let currentState = before;
  for (const operation of manifest.operations) {
    const existing = findExistingPageEvidence(currentState.snapshot, operation);
    if (existing) {
      anchorShapeId = existing.shape.id;
      results.push({
        index: operation.index,
        documentUuid: operation.documentUuid,
        action: "SKIPPED_EXACT_DUPLICATE",
        shapeId: existing.shape.id,
        assetId: existing.asset.id,
        renderSha256: operation.toolArgs.assetMeta.renderSha256,
      });
      continue;
    }

    const toolArgs = structuredClone(operation.toolArgs);
    if (anchorShapeId) toolArgs.anchorShapeId = anchorShapeId;
    const inserted = await callTool("insert_hardware_learning_image", toolArgs);
    assert.equal(inserted.pageId, manifest.canvasPageId);
    assert.equal(inserted.evidenceSource, "official-easyeda-export");
    currentState = await callTool("get_hardware_learning_canvas_state", {
      projectDir: manifest.projectDir,
      hydrateAssets: false,
    });
    const asset = currentState.snapshot.store[inserted.assetId];
    const shape = currentState.snapshot.store[inserted.shapeId];
    assert.equal(asset?.meta?.projectUuid, manifest.easyedaIdentity.projectUuid);
    assert.equal(asset?.meta?.documentUuid, operation.documentUuid);
    assert.equal(asset?.meta?.renderSha256, operation.toolArgs.assetMeta.renderSha256);
    assert.equal(asset?.meta?.evidenceSource, "official-easyeda-export");
    assert.equal(shape?.meta?.evidenceSource, "official-easyeda-export");
    assert.equal(shape?.parentId, manifest.canvasPageId);
    const copiedSha256 = sha256(await readFile(inserted.assetFile));
    assert.equal(copiedSha256, operation.toolArgs.assetMeta.renderSha256);
    anchorShapeId = inserted.shapeId;
    results.push({
      index: operation.index,
      documentUuid: operation.documentUuid,
      action: "INSERTED",
      shapeId: inserted.shapeId,
      assetId: inserted.assetId,
      assetFile: inserted.assetFile,
      renderSha256: copiedSha256,
    });
  }

  const finalState = await callTool("get_hardware_learning_canvas_state", {
    projectDir: manifest.projectDir,
    hydrateAssets: false,
  });
  for (const operation of manifest.operations) {
    assert.ok(
      findExistingPageEvidence(finalState.snapshot, operation),
      `project page ${operation.documentUuid} is missing after import`,
    );
  }
  const acceptance = {
    schemaVersion: "jlc.hardware-learning-project-import-apply-acceptance.v1",
    status: "PASS",
    serverVersion: initialized.serverInfo.version,
    manifestPath,
    manifestSha256,
    projectDir: manifest.projectDir,
    pageId: manifest.canvasPageId,
    projectUuid: manifest.easyedaIdentity.projectUuid,
    pageCount: manifest.operations.length,
    insertedCount: results.filter((item) => item.action === "INSERTED").length,
    skippedExactDuplicateCount: results.filter(
      (item) => item.action === "SKIPPED_EXACT_DUPLICATE"
    ).length,
    results,
  };
  await writeFile(acceptancePath, `${JSON.stringify(acceptance, null, 2)}\n`, { flag: "wx" });
  console.log(JSON.stringify(acceptance, null, 2));
} finally {
  server.stdin.end();
  server.kill();
}
