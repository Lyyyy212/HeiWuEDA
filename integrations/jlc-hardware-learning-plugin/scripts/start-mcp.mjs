import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const GENERATED_DIR = path.join(ROOT_DIR, "mcp", "generated");
const RELEASE_MANIFEST_PATH = path.join(GENERATED_DIR, "release-manifest.json");
const MCP_BUNDLE_PATH = path.join(GENERATED_DIR, "hardware-learning-mcp.mjs");
const WIDGET_ARTIFACT_PATH = path.join(GENERATED_DIR, "hardware-learning-widget.html");

for (const artifactPath of [
  RELEASE_MANIFEST_PATH,
  MCP_BUNDLE_PATH,
  WIDGET_ARTIFACT_PATH,
]) {
  if (!existsSync(artifactPath)) {
    throw new Error(
      `Missing JLC Hardware Learning release artifact: ${artifactPath}. Run npm run build:artifacts before publishing the plugin.`,
    );
  }
}

const packageVersion = JSON.parse(
  readFileSync(path.join(ROOT_DIR, "package.json"), "utf8"),
).version;
const releaseManifest = JSON.parse(readFileSync(RELEASE_MANIFEST_PATH, "utf8"));
if (releaseManifest.version !== packageVersion) {
  throw new Error(
    `JLC Hardware Learning release artifacts are for ${releaseManifest.version}, but package.json is ${packageVersion}. Run npm run build:artifacts.`,
  );
}

process.env.JLC_HARDWARE_LEARNING_PLUGIN_ROOT ||= ROOT_DIR;
process.chdir(ROOT_DIR);
await import(pathToFileURL(MCP_BUNDLE_PATH).href);
