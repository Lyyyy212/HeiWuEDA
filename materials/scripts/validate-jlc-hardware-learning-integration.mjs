import crypto from "node:crypto";
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MATERIALS_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const readJson = (filePath) => JSON.parse(fs.readFileSync(filePath, "utf8"));
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const fromMaterials = (relativePath) => path.resolve(MATERIALS_ROOT, ...relativePath.split("/"));
const sha256PortableText = (filePath) => crypto
  .createHash("sha256")
  .update(fs.readFileSync(filePath, "utf8").replace(/\r\n?/gu, "\n"), "utf8")
  .digest("hex");
const git = (repoPath, ...args) => execFileSync("git", ["-C", repoPath, ...args], { encoding: "utf8" }).trim();

async function listMcpTools(pluginRoot) {
  const child = spawn(process.execPath, [path.join(pluginRoot, "scripts", "start-mcp.mjs")], {
    cwd: pluginRoot,
    stdio: ["pipe", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  const requests = [
    {
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-11-25",
        capabilities: {},
        clientInfo: { name: "easyeda-workbench-integration-validator", version: "1.0.0" },
      },
    },
    { jsonrpc: "2.0", method: "notifications/initialized", params: {} },
    { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} },
  ];
  child.stdin.end(`${requests.map((item) => JSON.stringify(item)).join("\n")}\n`);
  const exitCode = await new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("close", resolve);
  });
  assert(exitCode === 0, `JLC Hardware Learning MCP probe exited ${exitCode}: ${stderr}`);
  const responses = stdout.split(/\r?\n/u).filter(Boolean).map((line) => JSON.parse(line));
  return {
    initialize: responses.find((item) => item.id === 1)?.result,
    tools: responses.find((item) => item.id === 2)?.result?.tools,
  };
}

const integrationLock = readJson(path.join(MATERIALS_ROOT, "manifests", "integrations.lock.json"));
const profile = readJson(path.join(MATERIALS_ROOT, "manifests", "jlc-hardware-learning-profile.json"));
const integration = integrationLock.integrations.find((item) => item.plugin === "jlc-hardware-learning");
assert(integration, "jlc-hardware-learning is missing from integrations.lock.json");
const pluginRoot = fromMaterials(integration.localPath);
const sourceRepository = fromMaterials(integration.sourceRepository);

assert(fs.statSync(pluginRoot).isDirectory(), "JLC Hardware Learning plugin package is missing");
assert(fs.statSync(sourceRepository).isDirectory(), "JLC Hardware Learning source repository is missing");
if (integration.distributionMode === "public-vendored-source") {
  assert(sourceRepository === pluginRoot, "public source must resolve to the vendored plugin directory");
} else {
  assert(git(sourceRepository, "rev-parse", "HEAD") === integration.sourceCommit, "independent source commit mismatch");
  assert(git(sourceRepository, "remote") === "", "independent source repository must not retain an upstream remote");
}
assert(
  sha256PortableText(fromMaterials(integration.licensePath)) === integration.licenseSha256,
  "license hash mismatch",
);
for (const evidence of Object.values(integration.sourceEvidence)) {
  const actualSha256 = sha256PortableText(fromMaterials(evidence.path));
  assert(
    actualSha256 === evidence.sha256,
    `source hash mismatch: ${evidence.path}; expected ${evidence.sha256}; actual ${actualSha256}`,
  );
}

const packageJson = readJson(path.join(pluginRoot, "package.json"));
const pluginJson = readJson(path.join(pluginRoot, ".codex-plugin", "plugin.json"));
const mcpConfig = readJson(path.join(pluginRoot, ".mcp.json"));
const releaseManifest = readJson(path.join(pluginRoot, "mcp", "generated", "release-manifest.json"));
assert(packageJson.name === integration.plugin, "package name does not match the lock");
assert(pluginJson.name === integration.plugin, "plugin name does not match the lock");
assert(packageJson.version === integration.version, "package version does not match the lock");
assert(pluginJson.version === integration.version, "plugin version does not match the lock");
assert(releaseManifest.version === integration.version, "release version does not match the lock");
assert(Object.hasOwn(mcpConfig.mcpServers, integration.runtime.mcpServer), "MCP server key does not match the lock");

const { initialize, tools } = await listMcpTools(pluginRoot);
assert(initialize?.serverInfo?.name === integration.runtime.serverInfoName, "unexpected MCP server name");
assert(initialize?.serverInfo?.version === integration.runtime.serverVersionVerified, "MCP version mismatch");
assert(Array.isArray(tools), "MCP tools/list response is missing");
assert(tools.length === integration.runtime.toolCountVerified, "MCP tool count mismatch");
const toolNames = new Set(tools.map((tool) => tool.name));
const governedTools = [
  ...profile.mcpPolicy.modelReadAllowed,
  ...profile.mcpPolicy.widgetPersistenceAllowed,
  profile.mcpPolicy.conditionalEvidenceInsertion.tool,
  ...profile.mcpPolicy.localExportAllowed,
  profile.mcpPolicy.pageNetlistAllowed.attach,
  profile.mcpPolicy.pageNetlistAllowed.read,
  ...profile.mcpPolicy.feishuLearningNotes.verifiedLocalRegistryAllowed,
  ...profile.mcpPolicy.feishuLearningNotes.confirmedRemoteWriteAllowed,
];
for (const toolName of governedTools) {
  assert(toolNames.has(toolName), `profile references a missing MCP tool: ${toolName}`);
}
assert(![...toolNames].some((name) => /cowart|analytics|html_draft/iu.test(name)), "retired public tool exposed");
assert(profile.easyedaBoundary.directAccessFromCanvas === false, "canvas must not access EasyEDA directly");
assert(profile.privacyPolicy.telemetry === "disabled", "telemetry must remain disabled");
assert(profile.migrationPolicy.legacyStorageWriteAllowed === false, "legacy storage must remain read-only");
assert(profile.excludedCapabilities.includes("image generation"), "image generation must remain excluded");
assert(profile.mcpPolicy.conditionalEvidenceInsertion.constraints.generatedBitmap === false, "generated bitmaps must remain disabled");
assert(profile.mcpPolicy.pageNetlistAllowed.constraints.officialEasyedaEvidenceOnly === true, "page netlists must require official EasyEDA evidence");
assert(profile.mcpPolicy.feishuLearningNotes.constraints.explicitConfirmation === true, "Feishu writes must require explicit confirmation");
assert(profile.mcpPolicy.feishuLearningNotes.constraints.freshReadVerification === true, "Feishu writes must require fresh-read verification");

process.stdout.write(`${JSON.stringify({
  status: "PASS",
  integration: integration.name,
  distributionMode: integration.distributionMode,
  plugin: integration.plugin,
  version: integration.version,
  mcpServer: initialize.serverInfo,
  toolCount: tools.length,
  governedToolCount: new Set(governedTools).size,
  imageGeneration: "DENIED",
  telemetry: "DISABLED",
  easyedaDirectAccess: "DENIED",
}, null, 2)}\n`);
