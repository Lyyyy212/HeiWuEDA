import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPOSITORY_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
);

const trackedEntries = execFileSync(
  "git",
  ["-C", REPOSITORY_ROOT, "ls-files", "--stage", "-z"],
  { encoding: "utf8" },
)
  .split("\0")
  .filter(Boolean)
  .map((line) => {
    const match = /^(?<mode>\d+) [0-9a-f]+ \d+\t(?<file>.+)$/u.exec(line);
    if (!match) throw new Error(`unexpected git ls-files entry: ${line}`);
    return match.groups;
  });
const untrackedEntries = execFileSync(
  "git",
  ["-C", REPOSITORY_ROOT, "ls-files", "--others", "--exclude-standard", "-z"],
  { encoding: "utf8" },
)
  .split("\0")
  .filter(Boolean)
  .map((file) => ({ mode: "untracked", file }));
const releaseEntries = [...trackedEntries, ...untrackedEntries];

const violations = [];
const report = (file, rule) => violations.push({ file, rule });
const privateDirectory = /(?:^|\/)(?:artifacts|evidence|backups|\.runtime|\.easyeda-hardware-workbench)(?:\/|$)/iu;
const localPath = /(?:\b[A-Z]:\\(?:Users|jlc)\\|\/(?:Users|home)\/[A-Za-z0-9._-]+\/)/u;
const secretLiteral = /(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)/u;
const credentialAssignment = /(?:app[_-]?secret|client[_-]?secret|api[_-]?key|access[_-]?token|refresh[_-]?token|password)\s*[:=]\s*["'](?!fixture|example|test|mock|fake|placeholder)[^"']{8,}["']/iu;
const feishuHost = /https?:\/\/(?<host>(?:[A-Za-z0-9.-]+\.)?(?:feishu\.cn|larksuite\.com|doubao\.com))\b/giu;
const identityLiteral = /(?:spaceId|documentToken|nodeToken|wikiNodeToken|docxToken|whiteboardToken|moduleIndexWhiteboardToken|schematicPageUuid|projectUuid)\s*[:=]\s*["'](?<value>[^"']{6,})["']/giu;
const explicitFixture = /(?:fixture|example|test|mock|fake|placeholder|project|page|node|doc|board|space|root|module|legacy|revision|index|old|new)/iu;
const reservedUuid = /^(?:0{28,31}[0-9]{1,4}|00000000-0000-4[0-9a-f]{3}-8[0-9a-f]{3}-0{11}[0-9])$/iu;

for (const { mode, file } of releaseEntries) {
  const normalized = file.replaceAll("\\", "/");
  if (privateDirectory.test(normalized)) report(normalized, "private-directory");
  if (mode === "160000") continue;

  const absolutePath = path.join(REPOSITORY_ROOT, file);
  if (!fs.statSync(absolutePath).isFile()) continue;
  const bytes = fs.readFileSync(absolutePath);
  if (bytes.length > 5 * 1024 * 1024 || bytes.includes(0)) continue;
  const text = bytes.toString("utf8");

  if (localPath.test(text)) report(normalized, "local-absolute-path");
  if (secretLiteral.test(text)) report(normalized, "known-secret-format");
  if (credentialAssignment.test(text)) report(normalized, "credential-literal");
  for (const match of text.matchAll(feishuHost)) {
    if (match.groups.host.toLowerCase() !== "example.feishu.cn") {
      report(normalized, "private-feishu-host");
    }
  }

  if (normalized.startsWith("integrations/jlc-hardware-learning-plugin/")) {
    for (const match of text.matchAll(identityLiteral)) {
      const value = match.groups.value;
      const compactIdentity = /^[A-Za-z0-9_-]{16,}$/u.test(value);
      const uuidIdentity = /^(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/iu.test(value);
      if (
        !explicitFixture.test(value)
        && !reservedUuid.test(value)
        && (compactIdentity || uuidIdentity)
      ) {
        report(normalized, "live-looking-identity-literal");
      }
    }
  }
}

const uniqueViolations = [...new Map(
  violations.map((item) => [`${item.file}\0${item.rule}`, item]),
).values()];

if (uniqueViolations.length > 0) {
  process.stderr.write(`${JSON.stringify({
    status: "FAIL",
    violations: uniqueViolations,
  }, null, 2)}\n`);
  process.exit(1);
}

process.stdout.write(`${JSON.stringify({
  status: "PASS",
  trackedFilesChecked: trackedEntries.filter(({ mode }) => mode !== "160000").length,
  untrackedFilesChecked: untrackedEntries.length,
  submodulesSkipped: trackedEntries.filter(({ mode }) => mode === "160000").length,
  rules: [
    "private directories",
    "local absolute paths",
    "known secret formats",
    "credential literals",
    "private Feishu hosts",
    "live-looking canvas identity fixtures",
  ],
}, null, 2)}\n`);
