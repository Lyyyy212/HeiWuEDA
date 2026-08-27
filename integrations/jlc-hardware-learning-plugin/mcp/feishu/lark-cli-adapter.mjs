import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_BUFFER_BYTES = 16 * 1024 * 1024;
const FEISHU_SYNC_PLAN_SCHEMA = "jlc.feishu-learning-sync-plan.v1";

function nonEmptyString(value, field) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${field} is required.`);
  return value.trim();
}
export function normalizeFeishuDocReference(value) {
  const reference = nonEmptyString(value, "document");
  if (/^[A-Za-z0-9_-]{16,128}$/u.test(reference)) {
    return { reference, docToken: reference, kind: "token" };
  }
  let url;
  try {
    url = new URL(reference);
  } catch {
    throw new Error("document must be a Feishu/Lark Docx URL or document token.");
  }
  if (url.protocol !== "https:") throw new Error("Feishu document URLs must use HTTPS.");
  const match = /^\/docx\/([A-Za-z0-9_-]{16,128})\/?$/u.exec(url.pathname);
  if (!match) throw new Error("document URL must point to one Feishu/Lark /docx/<token> resource.");
  return { reference: url.toString(), docToken: match[1], kind: "url" };
}

function defaultLaunchSpec({ env = process.env, platform = process.platform } = {}) {
  if (platform !== "win32") return { executable: "lark-cli", prefixArgs: [] };
  const candidates = [
    env.APPDATA && join(env.APPDATA, "npm", "node_modules", "@larksuite", "cli", "scripts", "run.js"),
    env.npm_config_prefix
      && join(env.npm_config_prefix, "node_modules", "@larksuite", "cli", "scripts", "run.js"),
  ].filter(Boolean);
  const cliScript = candidates.find((candidate) => existsSync(candidate));
  if (!cliScript) {
    throw new Error(
      "Unable to resolve the installed lark-cli JavaScript entrypoint without a shell.",
    );
  }
  return { executable: process.execPath, prefixArgs: [cliScript] };
}

function parseLarkJson(stdout) {
  const raw = String(stdout ?? "").trim();
  if (!raw) throw new Error("lark-cli returned an empty response.");
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (error) {
    throw new Error(`lark-cli returned invalid JSON: ${error.message}`);
  }
  if (payload?.ok !== true) {
    const detail = payload?.error?.message ?? payload?.message ?? payload?.code ?? "unknown error";
    throw new Error(`lark-cli request failed: ${detail}`);
  }
  if (payload.identity !== "user") {
    throw new Error(`lark-cli response identity must be user, received ${payload.identity ?? "none"}.`);
  }
  return payload;
}

function safeToken(value, field) {
  const token = nonEmptyString(value, field);
  if (!/^[A-Za-z0-9_-]{3,128}$/u.test(token)) {
    throw new Error(`${field} must be one Feishu token or numeric space ID.`);
  }
  return token;
}

function computePlanFingerprint(plan) {
  const identity = {
    schemaVersion: plan.schemaVersion,
    projectKey: plan.projectKey,
    identity: plan.identity,
    actions: plan.actions,
  };
  return createHash("sha256").update(JSON.stringify(identity)).digest("hex");
}

export function verifyConfirmedFeishuSyncPlan(plan, confirmation = {}) {
  if (!plan || plan.schemaVersion !== FEISHU_SYNC_PLAN_SCHEMA) {
    throw new Error(`plan must use ${FEISHU_SYNC_PLAN_SCHEMA}.`);
  }
  if (plan.identity !== "user" || !Array.isArray(plan.actions)) {
    throw new Error("Feishu write plans require user identity and an action array.");
  }
  const computedFingerprint = computePlanFingerprint(plan);
  if (plan.planFingerprint !== computedFingerprint) {
    throw new Error("Feishu sync plan fingerprint does not match its actions.");
  }
  if (confirmation.confirmed !== true) {
    throw new Error("Feishu writes require explicit confirmation.");
  }
  if (confirmation.planFingerprint !== plan.planFingerprint) {
    throw new Error("Feishu write confirmation does not match the current plan fingerprint.");
  }
  let expectedDocumentRevisions = null;
  if (confirmation.expectedDocumentRevisions != null) {
    if (
      typeof confirmation.expectedDocumentRevisions !== "object"
      || Array.isArray(confirmation.expectedDocumentRevisions)
    ) {
      throw new Error("expectedDocumentRevisions must map Docx tokens to revisions.");
    }
    expectedDocumentRevisions = Object.fromEntries(
      Object.entries(confirmation.expectedDocumentRevisions)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([token, revision]) => {
          const normalizedToken = safeToken(token, "expectedDocumentRevisions token");
          const normalizedRevision = Number(revision);
          if (!Number.isSafeInteger(normalizedRevision) || normalizedRevision < 0) {
            throw new Error("expectedDocumentRevisions values must be non-negative integers.");
          }
          return [normalizedToken, normalizedRevision];
        }),
    );
    if (Object.keys(expectedDocumentRevisions).length === 0) {
      throw new Error("expectedDocumentRevisions must contain at least one document.");
    }
  }
  const expectedRevisionId = confirmation.expectedDocumentRevisionId == null
    ? null
    : Number(confirmation.expectedDocumentRevisionId);
  if (
    !expectedDocumentRevisions
    && (!Number.isSafeInteger(expectedRevisionId) || expectedRevisionId < 0)
  ) throw new Error("Feishu write confirmation requires expected document revisions.");
  return Object.freeze({
    planFingerprint: plan.planFingerprint,
    expectedDocumentRevisionId: expectedRevisionId,
    expectedDocumentRevisions,
  });
}

export function createLarkCliAdapter(options = {}) {
  const runner = options.runner ?? execFileAsync;
  const launch = options.launch ?? defaultLaunchSpec(options);
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  async function runReadOnly(args) {
    if (!Array.isArray(args) || args.some((arg) => typeof arg !== "string")) {
      throw new Error("lark-cli arguments must be a string array.");
    }
    const { stdout, stderr } = await runner(
      launch.executable,
      [...launch.prefixArgs, ...args],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          LARK_CLI_DISABLE_SKILLS_NOTICE: "1",
          LARK_CLI_DISABLE_UPDATE_NOTICE: "1",
        },
        maxBuffer: MAX_BUFFER_BYTES,
        timeout: timeoutMs,
        windowsHide: true,
      },
    );
    const payload = parseLarkJson(stdout);
    return { payload, stderr: String(stderr ?? "") };
  }

  return Object.freeze({
    async getPersonalWikiSpace() {
      const { payload } = await runReadOnly([
        "wiki", "spaces", "get",
        "--params", JSON.stringify({ space_id: "my_library" }),
        "--as", "user",
        "--format", "json",
      ]);
      return payload;
    },

    async listWikiNodes({ spaceId, parentNodeToken } = {}) {
      const args = [
        "wiki", "+node-list",
        "--space-id", safeToken(spaceId, "spaceId"),
      ];
      if (parentNodeToken) {
        args.push("--parent-node-token", safeToken(parentNodeToken, "parentNodeToken"));
      }
      args.push(
        "--page-all", "--page-limit", "0",
        "--as", "user",
        "--format", "json",
      );
      const { payload } = await runReadOnly(args);
      return payload;
    },

    async getWikiNode({ nodeToken, objType } = {}) {
      const args = [
        "wiki", "+node-get",
        "--node-token", safeToken(nodeToken, "nodeToken"),
      ];
      if (objType) args.push("--obj-type", nonEmptyString(objType, "objType"));
      args.push("--as", "user", "--format", "json");
      const { payload } = await runReadOnly(args);
      return payload;
    },

    async fetchDocumentOutline(document) {
      const target = normalizeFeishuDocReference(document);
      const { payload } = await runReadOnly([
        "docs", "+fetch",
        "--doc", target.reference,
        "--scope", "outline",
        "--max-depth", "4",
        "--detail", "with-ids",
        "--as", "user",
        "--format", "json",
      ]);
      return payload;
    },

    async fetchDocumentFull(document) {
      const target = normalizeFeishuDocReference(document);
      const { payload } = await runReadOnly([
        "docs", "+fetch",
        "--doc", target.reference,
        "--detail", "full",
        "--as", "user",
        "--format", "json",
      ]);
      return payload;
    },
  });
}

export function createConfirmedLarkCliWriteAdapter(options = {}) {
  const runner = options.runner ?? execFileAsync;
  const launch = options.launch ?? defaultLaunchSpec(options);
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const confirmation = verifyConfirmedFeishuSyncPlan(options.plan, options.confirmation);
  const actionsById = new Map(options.plan.actions.map((action) => [action.actionId, action]));

  function requireAction(actionId, expectedKinds) {
    const action = actionsById.get(nonEmptyString(actionId, "actionId"));
    if (!action) throw new Error(`Action is not present in the confirmed plan: ${actionId}`);
    const kinds = new Set(Array.isArray(expectedKinds) ? expectedKinds : [expectedKinds]);
    if (!kinds.has(action.kind)) {
      throw new Error(`Confirmed action ${actionId} has unsupported kind ${action.kind}.`);
    }
    return action;
  }

  async function runConfirmed(args) {
    const { stdout, stderr } = await runner(
      launch.executable,
      [...launch.prefixArgs, ...args],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          LARK_CLI_DISABLE_SKILLS_NOTICE: "1",
          LARK_CLI_DISABLE_UPDATE_NOTICE: "1",
        },
        maxBuffer: MAX_BUFFER_BYTES,
        timeout: timeoutMs,
        windowsHide: true,
      },
    );
    return { payload: parseLarkJson(stdout), stderr: String(stderr ?? "") };
  }

  return Object.freeze({
    confirmation,

    async createWikiNode({ actionId, spaceId, parentNodeToken = null } = {}) {
      const action = requireAction(actionId, "wiki.node.ensure");
      const args = [
        "wiki", "+node-create",
        "--space-id", safeToken(spaceId, "spaceId"),
      ];
      if (parentNodeToken) {
        args.push("--parent-node-token", safeToken(parentNodeToken, "parentNodeToken"));
      }
      args.push(
        "--title", nonEmptyString(action.title, "action.title"),
        "--obj-type", "docx",
        "--as", "user",
        "--format", "json",
      );
      const { payload } = await runConfirmed(args);
      return { payload, action, idempotencyKey: action.idempotencyKey };
    },

    async moveDriveDocumentToWiki({
      actionId,
      docToken,
      targetSpaceId,
      targetParentNodeToken,
    } = {}) {
      const action = requireAction(actionId, "wiki.document.move");
      const args = [
        "wiki", "+move",
        "--obj-type", "docx",
        "--obj-token", safeToken(docToken, "docToken"),
        "--target-space-id", safeToken(targetSpaceId, "targetSpaceId"),
        "--target-parent-token", safeToken(targetParentNodeToken, "targetParentNodeToken"),
        "--as", "user",
        "--format", "json",
      ];
      const { payload } = await runConfirmed(args);
      return { payload, action, idempotencyKey: action.idempotencyKey };
    },

    async continueWikiMove({ actionId, taskId } = {}) {
      const action = requireAction(actionId, "wiki.document.move");
      const { payload } = await runConfirmed([
        "drive", "+task_result",
        "--scenario", "wiki_move",
        "--task-id", safeToken(taskId, "taskId"),
        "--as", "user",
        "--format", "json",
      ]);
      return { payload, action, idempotencyKey: action.idempotencyKey };
    },

    async renameMovedWikiDocument({ actionId, nodeToken } = {}) {
      const action = requireAction(actionId, "wiki.document.move");
      const { payload } = await runConfirmed([
        "drive", "+update-title",
        "--token", safeToken(nodeToken, "nodeToken"),
        "--type", "wiki",
        "--title", nonEmptyString(action.title, "action.title"),
        "--as", "user",
        "--format", "json",
      ]);
      return { payload, action, idempotencyKey: action.idempotencyKey };
    },

    async replaceDocumentText({ actionId, document, revisionId, pattern, content } = {}) {
      const action = requireAction(actionId, ["doc.page-template.ensure", "doc.module-index.sync"]);
      const target = normalizeFeishuDocReference(document);
      const revision = Number(revisionId);
      if (!Number.isSafeInteger(revision) || revision < 0) {
        throw new Error("revisionId must be a non-negative integer.");
      }
      const { payload } = await runConfirmed([
        "docs", "+update",
        "--doc", target.reference,
        "--command", "str_replace",
        "--pattern", nonEmptyString(pattern, "pattern"),
        "--content", String(content ?? ""),
        "--revision-id", String(revision),
        "--doc-format", "xml",
        "--as", "user",
        "--format", "json",
      ]);
      return { payload, action, idempotencyKey: action.idempotencyKey };
    },

    async appendDocumentXml({ actionId, document, revisionId, content } = {}) {
      const action = requireAction(actionId, "doc.project-homepage.ensure");
      const target = normalizeFeishuDocReference(document);
      const revision = Number(revisionId);
      if (!Number.isSafeInteger(revision) || revision < 0) {
        throw new Error("revisionId must be a non-negative integer.");
      }
      const { payload } = await runConfirmed([
        "docs", "+update",
        "--doc", target.reference,
        "--command", "append",
        "--content", nonEmptyString(content, "content"),
        "--revision-id", String(revision),
        "--doc-format", "xml",
        "--as", "user",
        "--format", "json",
      ]);
      return { payload, action, idempotencyKey: action.idempotencyKey };
    },

    async insertDocumentBlocksAfter({
      actionId,
      document,
      revisionId,
      blockId,
      content,
    } = {}) {
      const action = requireAction(actionId, ["doc.page-template.ensure", "doc.module-index.sync"]);
      const target = normalizeFeishuDocReference(document);
      const revision = Number(revisionId);
      if (!Number.isSafeInteger(revision) || revision < 0) {
        throw new Error("revisionId must be a non-negative integer.");
      }
      const { payload } = await runConfirmed([
        "docs", "+update",
        "--doc", target.reference,
        "--command", "block_insert_after",
        "--block-id", safeToken(blockId, "blockId"),
        "--content", nonEmptyString(content, "content"),
        "--revision-id", String(revision),
        "--doc-format", "xml",
        "--as", "user",
        "--format", "json",
      ]);
      return { payload, action, idempotencyKey: action.idempotencyKey };
    },

    async replaceDocumentBlocks({
      actionId,
      document,
      revisionId,
      startBlockId,
      endBlockId,
      content,
    } = {}) {
      const action = requireAction(actionId, "doc.module-index.sync");
      const target = normalizeFeishuDocReference(document);
      const revision = Number(revisionId);
      if (!Number.isSafeInteger(revision) || revision < 0) {
        throw new Error("revisionId must be a non-negative integer.");
      }
      const { payload } = await runConfirmed([
        "docs", "+update",
        "--doc", target.reference,
        "--command", "block_replace",
        "--start-block-id", safeToken(startBlockId, "startBlockId"),
        "--end-block-id", safeToken(endBlockId, "endBlockId"),
        "--content", nonEmptyString(content, "content"),
        "--revision-id", String(revision),
        "--doc-format", "xml",
        "--as", "user",
        "--format", "json",
      ]);
      return { payload, action, idempotencyKey: action.idempotencyKey };
    },
  });
}
