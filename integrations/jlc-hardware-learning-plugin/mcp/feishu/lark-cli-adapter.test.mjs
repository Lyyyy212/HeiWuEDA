import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import {
  createConfirmedLarkCliWriteAdapter,
  createLarkCliAdapter,
  normalizeFeishuDocReference,
  verifyConfirmedFeishuSyncPlan,
} from "./lark-cli-adapter.mjs";

const confirmedPlan = {
  schemaVersion: "jlc.feishu-learning-sync-plan.v1",
  projectKey: "project:test",
  identity: "user",
  actions: [
    {
      actionId: "wiki.node.ensure:root",
      kind: "wiki.node.ensure",
      logicalId: "root",
      title: "硬件学习笔记",
      parentLogicalId: null,
      idempotencyKey: "jlc-feishu-test-root",
      requires: [],
      verification: "wiki.node.get",
    },
    {
      actionId: "wiki.document.move:page",
      kind: "wiki.document.move",
      logicalId: "page",
      title: "01 主控板",
      parentLogicalId: "schematics",
      idempotencyKey: "jlc-feishu-test-page",
      requires: ["schematics"],
      verification: "wiki.node.get",
    },
    {
      actionId: "doc.page-template.ensure:page",
      kind: "doc.page-template.ensure",
      logicalId: "page:template",
      title: "主控板学习笔记结构",
      parentLogicalId: "page",
      idempotencyKey: "jlc-feishu-test-template",
      requires: ["page"],
      verification: "docs.fetch.page-template",
    },
    {
      actionId: "doc.project-homepage.ensure:project",
      kind: "doc.project-homepage.ensure",
      logicalId: "project:homepage",
      title: "项目主页",
      parentLogicalId: "root",
      idempotencyKey: "jlc-feishu-test-homepage",
      requires: ["root", "page"],
      verification: "docs.fetch.project-homepage",
      desiredContentDigest: "a".repeat(64),
    },
    {
      actionId: "doc.module-index.sync:page",
      kind: "doc.module-index.sync",
      logicalId: "page:managed-content",
      title: "主控板模块索引与学习问答",
      parentLogicalId: "page",
      idempotencyKey: "jlc-feishu-test-managed-content",
      requires: ["page"],
      verification: "docs.fetch.module-index",
      desiredContentDigest: "b".repeat(64),
    },
  ],
};
confirmedPlan.planFingerprint = createHash("sha256").update(JSON.stringify({
  schemaVersion: confirmedPlan.schemaVersion,
  projectKey: confirmedPlan.projectKey,
  identity: confirmedPlan.identity,
  actions: confirmedPlan.actions,
})).digest("hex");
confirmedPlan.writePolicy = "confirm-before-execute-and-fresh-read-after-write";

test("Feishu document references accept only one HTTPS Docx URL or token", () => {
  assert.equal(normalizeFeishuDocReference("FixtureUrlToken01").docToken, "FixtureUrlToken01");
  assert.equal(
    normalizeFeishuDocReference(
      "https://example.feishu.cn/docx/FixtureUrlToken01",
    ).docToken,
    "FixtureUrlToken01",
  );
  assert.throws(() => normalizeFeishuDocReference("http://example.feishu.cn/docx/token"), /HTTPS/u);
  assert.throws(() => normalizeFeishuDocReference("https://example.feishu.cn/wiki/token"), /docx/u);
  assert.throws(() => normalizeFeishuDocReference("; Remove-Item *"), /Docx URL or document token/u);
});
test("adapter runs the fixed read-only docs fetch command as user without a shell", async () => {
  const calls = [];
  const runner = async (executable, args, options) => {
    calls.push({ executable, args, options });
    return {
      stdout: JSON.stringify({
        ok: true,
        identity: "user",
        data: { document: { document_id: "FixtureUrlToken01", content: "", revision_id: 8 } },
      }),
      stderr: "",
    };
  };
  const adapter = createLarkCliAdapter({
    runner,
    launch: { executable: "node", prefixArgs: ["lark-run.js"] },
  });
  await adapter.fetchDocumentOutline("FixtureUrlToken01");
  await adapter.fetchDocumentFull("FixtureUrlToken01");
  assert.deepEqual(calls[0].args, [
    "lark-run.js", "docs", "+fetch",
    "--doc", "FixtureUrlToken01",
    "--scope", "outline",
    "--max-depth", "4",
    "--detail", "with-ids",
    "--as", "user",
    "--format", "json",
  ]);
  assert.deepEqual(calls[1].args.slice(-6), [
    "--detail", "full", "--as", "user", "--format", "json",
  ]);
  assert.equal(calls[0].options.shell, undefined);
  assert.equal(calls[0].options.windowsHide, true);
});

test("adapter rejects false success and non-user response identities", async () => {
  const adapterFor = (payload) => createLarkCliAdapter({
    runner: async () => ({ stdout: JSON.stringify(payload), stderr: "" }),
    launch: { executable: "node", prefixArgs: ["lark-run.js"] },
  });
  await assert.rejects(
    () => adapterFor({ ok: false, identity: "user", message: "denied" })
      .fetchDocumentFull("FixtureUrlToken01"),
    /denied/u,
  );
  await assert.rejects(
    () => adapterFor({ ok: true, identity: "bot", data: {} })
      .fetchDocumentFull("FixtureUrlToken01"),
    /identity must be user/u,
  );
});

test("confirmed write adapter rejects missing, stale, and tampered confirmations", () => {
  const validConfirmation = {
    confirmed: true,
    planFingerprint: confirmedPlan.planFingerprint,
    expectedDocumentRevisionId: 9,
  };
  assert.deepEqual(
    verifyConfirmedFeishuSyncPlan(confirmedPlan, validConfirmation),
    {
      planFingerprint: confirmedPlan.planFingerprint,
      expectedDocumentRevisionId: 9,
      expectedDocumentRevisions: null,
    },
  );
  assert.throws(
    () => verifyConfirmedFeishuSyncPlan(confirmedPlan, { ...validConfirmation, confirmed: false }),
    /explicit confirmation/u,
  );
  assert.throws(
    () => verifyConfirmedFeishuSyncPlan(confirmedPlan, {
      ...validConfirmation,
      planFingerprint: "0".repeat(64),
    }),
    /does not match/u,
  );
  assert.throws(
    () => verifyConfirmedFeishuSyncPlan({
      ...confirmedPlan,
      actions: [{ ...confirmedPlan.actions[0], title: "changed" }],
    }, validConfirmation),
    /fingerprint does not match/u,
  );
});

test("confirmed write adapter exposes fixed user-identity commands without a shell", async () => {
  const calls = [];
  const adapter = createConfirmedLarkCliWriteAdapter({
    plan: confirmedPlan,
    confirmation: {
      confirmed: true,
      planFingerprint: confirmedPlan.planFingerprint,
      expectedDocumentRevisionId: 9,
    },
    runner: async (executable, args, options) => {
      calls.push({ executable, args, options });
      return { stdout: JSON.stringify({ ok: true, identity: "user", data: {} }), stderr: "" };
    },
    launch: { executable: "node", prefixArgs: ["lark-run.js"] },
  });
  await adapter.createWikiNode({
    actionId: "wiki.node.ensure:root",
    spaceId: "FixtureSpaceId01",
  });
  await adapter.moveDriveDocumentToWiki({
    actionId: "wiki.document.move:page",
    docToken: "FixtureUrlToken01",
    targetSpaceId: "FixtureSpaceId01",
    targetParentNodeToken: "FixtureNodeToken01",
  });
  await adapter.renameMovedWikiDocument({
    actionId: "wiki.document.move:page",
    nodeToken: "FixtureNodeToken02",
  });
  await adapter.replaceDocumentText({
    actionId: "doc.page-template.ensure:page",
    document: "FixtureUrlToken01",
    revisionId: 9,
    pattern: "Cowart 图页",
    content: "JLC 硬件学习图页",
  });
  await adapter.appendDocumentXml({
    actionId: "doc.project-homepage.ensure:project",
    document: "FixtureUrlToken01",
    revisionId: 10,
    content: "<h1>00 项目总览</h1>",
  });
  await adapter.insertDocumentBlocksAfter({
    actionId: "doc.module-index.sync:page",
    document: "FixtureUrlToken01",
    revisionId: 11,
    blockId: "doxcnAnchor123",
    content: "<p>managed</p>",
  });
  await adapter.replaceDocumentBlocks({
    actionId: "doc.module-index.sync:page",
    document: "FixtureUrlToken01",
    revisionId: 12,
    startBlockId: "doxcnStart123",
    endBlockId: "doxcnEnd123",
    content: "<p>managed-v2</p>",
  });
  assert.deepEqual(calls[0].args, [
    "lark-run.js", "wiki", "+node-create",
    "--space-id", "FixtureSpaceId01",
    "--title", "硬件学习笔记",
    "--obj-type", "docx",
    "--as", "user",
    "--format", "json",
  ]);
  assert.deepEqual(calls[1].args.slice(1, 8), [
    "wiki", "+move", "--obj-type", "docx",
    "--obj-token", "FixtureUrlToken01", "--target-space-id",
  ]);
  assert.deepEqual(calls[2].args.slice(1, 7), [
    "drive", "+update-title", "--token", "FixtureNodeToken02", "--type", "wiki",
  ]);
  assert.deepEqual(calls[3].args.slice(-10), [
    "--content", "JLC 硬件学习图页",
    "--revision-id", "9",
    "--doc-format", "xml",
    "--as", "user",
    "--format", "json",
  ]);
  assert.deepEqual(calls[4].args.slice(-12), [
    "--command", "append",
    "--content", "<h1>00 项目总览</h1>",
    "--revision-id", "10",
    "--doc-format", "xml",
    "--as", "user",
    "--format", "json",
  ]);
  assert.deepEqual(calls[5].args.slice(1, 9), [
    "docs", "+update", "--doc", "FixtureUrlToken01",
    "--command", "block_insert_after", "--block-id", "doxcnAnchor123",
  ]);
  assert.deepEqual(calls[6].args.slice(5, 13), [
    "--command", "block_replace",
    "--start-block-id", "doxcnStart123",
    "--end-block-id", "doxcnEnd123",
    "--content", "<p>managed-v2</p>",
  ]);
  assert.ok(calls.every((call) => call.options.shell === undefined));
  assert.ok(calls.every((call) => call.options.windowsHide === true));
  await assert.rejects(
    () => adapter.createWikiNode({
      actionId: "doc.page-template.ensure:page",
      spaceId: "FixtureSpaceId01",
    }),
    /unsupported kind/u,
  );
});
