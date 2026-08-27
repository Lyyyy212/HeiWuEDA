import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  chmod,
  cp,
  mkdir,
  mkdtemp,
  readdir,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sandboxDir = await mkdtemp(path.join(tmpdir(), "jlc-hardware-learning-cold-install-"));

try {
  const pluginDir = path.join(sandboxDir, "plugin");
  const cleanTmpDir = path.join(sandboxDir, "tmp");
  const sentinelBinDir = path.join(sandboxDir, "bin");
  const npmSentinel = path.join(sandboxDir, "npm-was-called");
  await mkdir(cleanTmpDir, { recursive: true });
  await mkdir(sentinelBinDir, { recursive: true });
  await cp(ROOT_DIR, pluginDir, {
    recursive: true,
    filter: shouldCopyPluginPath,
  });

  const npmCommand = process.platform === "win32"
    ? path.join(sentinelBinDir, "npm.cmd")
    : path.join(sentinelBinDir, "npm");
  const npmScript = process.platform === "win32"
    ? "@echo called>%JLC_HARDWARE_LEARNING_NPM_SENTINEL%\r\n@exit /b 99\r\n"
    : "#!/bin/sh\nprintf called > \"$JLC_HARDWARE_LEARNING_NPM_SENTINEL\"\nexit 99\n";
  await writeFile(npmCommand, npmScript);
  if (process.platform !== "win32") await chmod(npmCommand, 0o755);

  assert.equal(await pathExists(path.join(pluginDir, "node_modules")), false);
  assert.equal(await pathExists(path.join(pluginDir, "mcp", "generated", "hardware-learning-mcp.mjs")), true);
  assert.equal(await pathExists(path.join(pluginDir, "mcp", "generated", "hardware-learning-widget.html")), true);

  const probe = spawnSync(
    process.execPath,
    [
      path.join(ROOT_DIR, "scripts", "probe-mcp.mjs"),
      "--server-root",
      pluginDir,
      "--max-startup-ms",
      "3000",
    ],
    {
      cwd: ROOT_DIR,
      env: {
        ...process.env,
        JLC_HARDWARE_LEARNING_NPM_SENTINEL: npmSentinel,
        NODE_PATH: "",
        PATH: `${sentinelBinDir}${path.delimiter}${process.env.PATH || ""}`,
        TEMP: cleanTmpDir,
        TMP: cleanTmpDir,
        TMPDIR: cleanTmpDir,
      },
      encoding: "utf8",
      timeout: 60_000,
    },
  );

  if (probe.stdout) process.stdout.write(probe.stdout);
  if (probe.stderr) process.stderr.write(probe.stderr);
  if (probe.error) throw probe.error;
  if (probe.status !== 0) {
    throw new Error(`JLC Hardware Learning cold-install probe failed with exit ${probe.status}.`);
  }

  assert.equal(
    await pathExists(path.join(pluginDir, "node_modules")),
    false,
    "Cold startup must not create node_modules in the installed plugin.",
  );
  assert.equal(
    await pathExists(npmSentinel),
    false,
    "Cold startup must not invoke npm.",
  );
  const temporaryEntries = await readdir(cleanTmpDir);
  assert.equal(
    temporaryEntries.some((name) => name.startsWith("jlc-hardware-learning-widget-build-v")),
    false,
    "Cold startup must not build the widget into a temporary directory.",
  );

  console.log("OK: A dependency-free JLC Hardware Learning install exposes tools and renders the widget without npm.");
} finally {
  await rm(sandboxDir, { recursive: true, force: true });
}

function shouldCopyPluginPath(sourcePath) {
  const relativePath = path.relative(ROOT_DIR, sourcePath);
  if (!relativePath) return true;
  const excludedSegments = new Set([
    ".git",
    "canvas",
    "dist",
    "node_modules",
    "output",
  ]);
  return !relativePath.split(path.sep).some((segment) => excludedSegments.has(segment));
}

async function pathExists(filePath) {
  try {
    await stat(filePath);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}
