import assert from "node:assert/strict";
import test from "node:test";

import {
  inspectFeishuLearningDocument,
  parseFeishuDocumentContent,
} from "./document-inspection.mjs";

const content = [
  '<title id="doc-token">硬件学习笔记</title>',
  '<h1 id="project">工程与图页信息</h1>',
  '<h1 id="board-heading">原理图学习画板</h1>',
  '<p id="legacy">旧 Cowart 图页</p>',
  '<whiteboard id="board-block" token="board-token"></whiteboard>',
  '<h1 id="index-heading">模块索引</h1>',
  '<whiteboard id="index-block" token="index-token"></whiteboard>',
  '<h2 id="module-four">模块 4</h2>',
  '<h2 id="module-seven">模块 7</h2>',
  '<h1 id="qa">提问与解答</h1>',
  '<h1 id="relations">模块间关系</h1>',
  '<h1 id="pending">待验证项</h1>',
  '<h1 id="sync">同步记录</h1>',
].join("");

test("full document parsing classifies both existing whiteboards and module headings", () => {
  const parsed = parseFeishuDocumentContent(content);
  assert.equal(parsed.title, "硬件学习笔记");
  assert.deepEqual(parsed.moduleHeadings.map((heading) => heading.frameNumber), [4, 7]);
  assert.deepEqual(parsed.whiteboards.map((board) => board.role), [
    "learning-board",
    "module-index-board",
  ]);
  assert.deepEqual(parsed.requiredSections.missing, []);
  assert.deepEqual(parsed.legacyBrandingTerms, ["Cowart"]);
});
test("inspection requires two fresh reads of the same document revision", async () => {
  const calls = [];
  const payload = {
    ok: true,
    identity: "user",
    data: {
      document: {
        document_id: "CwGJdseLUoB3GlxIVEdc4zgZnBh",
        revision_id: 8,
        content,
      },
    },
  };
  const adapter = {
    async fetchDocumentOutline(document) {
      calls.push(["outline", document]);
      return payload;
    },
    async fetchDocumentFull(document) {
      calls.push(["full", document]);
      return payload;
    },
  };
  const inspected = await inspectFeishuLearningDocument(
    { document: "CwGJdseLUoB3GlxIVEdc4zgZnBh" },
    { adapter },
  );
  assert.deepEqual(calls.map(([kind]) => kind), ["outline", "full"]);
  assert.equal(inspected.document.revisionId, 8);
  assert.equal(inspected.whiteboards[0].token, "board-token");
  assert.equal(inspected.remoteWritesPerformed, false);
});

test("inspection stops when the document revision changes between reads", async () => {
  let revision = 8;
  const adapter = {
    async fetchDocumentOutline() {
      return { ok: true, identity: "user", data: { document: {
        document_id: "CwGJdseLUoB3GlxIVEdc4zgZnBh", revision_id: revision++, content,
      } } };
    },
    async fetchDocumentFull() {
      return { ok: true, identity: "user", data: { document: {
        document_id: "CwGJdseLUoB3GlxIVEdc4zgZnBh", revision_id: revision, content,
      } } };
    },
  };
  await assert.rejects(
    () => inspectFeishuLearningDocument(
      { document: "CwGJdseLUoB3GlxIVEdc4zgZnBh" },
      { adapter },
    ),
    /revision changed/u,
  );
});
