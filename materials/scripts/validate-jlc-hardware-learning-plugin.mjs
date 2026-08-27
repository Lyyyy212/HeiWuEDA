import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";

const pluginRoot = path.resolve(process.argv[2] || "");
assert.ok(process.argv[2], "usage: node validate-jlc-hardware-learning-plugin.mjs <plugin-root>");

const readJson = async (...segments) =>
  JSON.parse(await readFile(path.join(pluginRoot, ...segments), "utf8"));
const readText = (...segments) => readFile(path.join(pluginRoot, ...segments), "utf8");

const manifest = await readJson(".codex-plugin", "plugin.json");
assert.equal(manifest.name, "jlc-hardware-learning");
assert.match(manifest.version, /^\d+\.\d+\.\d+$/u);
assert.equal(manifest.mcpServers, "./.mcp.json");
assert.equal(manifest.skills, "./skills/");
assert.equal(manifest.interface?.displayName, "JLC Hardware Learning");

const mcpConfig = await readJson(".mcp.json");
assert.deepEqual(Object.keys(mcpConfig.mcpServers), ["jlc_hardware_learning_mcp"]);

const release = await readJson("mcp", "generated", "release-manifest.json");
assert.equal(release.version, manifest.version);
for (const [name, expected] of Object.entries(release.artifacts)) {
  const bytes = await readFile(path.join(pluginRoot, "mcp", "generated", name));
  assert.equal(createHash("sha256").update(bytes).digest("hex"), expected, `${name} hash drift`);
}

for (const text of await Promise.all([
  readText("README.md"),
  readText("skills", "jlc-hardware-learning", "SKILL.md"),
  readText("skills", "jlc-hardware-learning", "agents", "openai.yaml"),
])) {
  assert.doesNotMatch(text, /cowart/iu, "active plugin documentation must not expose the legacy product name");
}

const widget = await readText("mcp", "generated", "hardware-learning-widget.html");
assert.match(widget, /jlc-hardware-learning-canvas-v1/u);
assert.match(widget, /JLC Hardware Learning/u);
assert.match(widget, /JLC硬件学习画板/u);
assert.match(widget, /data-jlc-learning-inline-editor/u);
assert.match(widget, /learning-canvas-viewport-clip/u);
assert.match(widget, /contain:strict/u);
assert.doesNotMatch(widget, /tl-watermark|Made with tldraw|production license/iu);
assert.doesNotMatch(widget, /Google Analytics|track_.*analytics|insert_.*html_draft/iu);

const serverBundle = await readText("mcp", "generated", "hardware-learning-mcp.mjs");
assert.match(serverBundle, /ui:\/\/widget\/jlc-hardware-learning\/canvas-/u);
assert.doesNotMatch(serverBundle, /ui:\/\/widget\/cowart\//u);
assert.match(serverBundle, /choose_hardware_learning_export_directory/u);
assert.match(serverBundle, /save_hardware_learning_question/u);
assert.match(serverBundle, /insert_hardware_learning_annotations/u);

const requests = [
  {
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: "2025-11-25",
      capabilities: {},
      clientInfo: { name: "jlc-hardware-learning-validator", version: "1.0" },
    },
  },
  { jsonrpc: "2.0", method: "notifications/initialized", params: {} },
  { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} },
];
const probe = spawnSync(process.execPath, [path.join("scripts", "start-mcp.mjs")], {
  cwd: pluginRoot,
  input: `${requests.map((request) => JSON.stringify(request)).join("\n")}\n`,
  encoding: "utf8",
  timeout: 15_000,
});
assert.equal(probe.status, 0, probe.stderr || "JLC Hardware Learning MCP probe failed");
const responses = probe.stdout.split(/\r?\n/u).filter(Boolean).map((line) => JSON.parse(line));
const initialize = responses.find((response) => response.id === 1)?.result;
const tools = responses.find((response) => response.id === 2)?.result?.tools;
assert.equal(initialize?.serverInfo?.name, "jlc-hardware-learning");
assert.equal(initialize?.serverInfo?.version, manifest.version);
assert.ok(Array.isArray(tools), "tools/list response missing");

const names = tools.map((tool) => tool.name);
const expected = [
  "render_hardware_learning_canvas_widget",
  "get_hardware_learning_canvas_state",
  "save_hardware_learning_canvas_state",
  "save_hardware_learning_selection_state",
  "save_hardware_learning_view_state",
  "get_hardware_learning_selection",
  "insert_hardware_learning_image",
  "save_hardware_learning_reference_image",
  "read_hardware_learning_page_asset",
  "choose_hardware_learning_export_directory",
  "download_hardware_learning_file",
  "copy_hardware_learning_image_to_clipboard",
  "save_hardware_learning_question",
  "insert_hardware_learning_annotations",
  "manage_hardware_learning_canvases",
  "attach_hardware_learning_page_netlist",
  "read_hardware_learning_page_netlist",
  "get_feishu_learning_note_state",
  "update_feishu_learning_note_state",
  "inspect_feishu_learning_note_target",
  "preview_feishu_learning_note_migration",
  "execute_feishu_learning_note_migration",
  "link_feishu_learning_dialogue_from_record",
  "bind_feishu_page_identity_from_learning_evidence",
  "preview_feishu_learning_note_sync",
  "execute_feishu_learning_note_sync",
];
assert.deepEqual([...names].sort(), [...expected].sort());
assert.ok(!names.some((name) => /cowart|analytics|html_draft/iu.test(name)));

const widgetVersion = manifest.version.replace(/[^A-Za-z0-9._-]+/gu, "-").replace(/^-+|-+$/gu, "");
const expectedWidgetUri = `ui://widget/jlc-hardware-learning/canvas-${widgetVersion}.html`;
const renderTool = tools.find((tool) => tool.name === "render_hardware_learning_canvas_widget");
assert.equal(renderTool?._meta?.ui?.resourceUri, expectedWidgetUri);
assert.equal(renderTool?._meta?.["openai/outputTemplate"], expectedWidgetUri);

console.log(JSON.stringify({
  status: "PASS",
  pluginRoot,
  version: manifest.version,
  widgetUri: expectedWidgetUri,
  toolCount: names.length,
}, null, 2));
