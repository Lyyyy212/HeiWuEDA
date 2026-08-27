import assert from "node:assert/strict";
import test from "node:test";

import {
  feishuProjectHomepageIndexDigest,
  inspectFeishuProjectHomepage,
  renderFeishuProjectHomepageAppendXml,
} from "./project-homepage.mjs";

const project = { projectId: "project-1", projectName: "项目一" };
const pages = [{ canvasPageId: "page:main", title: "01 主控板", docToken: "doc-main" }];

test("project homepage renderer adds compact section headings and page references", () => {
  const rendered = renderFeishuProjectHomepageAppendXml({ project, pages });
  assert.match(rendered.xml, /00 项目总览/u);
  assert.match(rendered.xml, /99 历史归档/u);
  assert.match(rendered.xml, /doc-id="doc-main"/u);
  assert.equal(rendered.indexDigest, feishuProjectHomepageIndexDigest({ project, pages }));
  assert.equal(rendered.indexDigest.length, 64);
  const inspected = inspectFeishuProjectHomepage(rendered.xml, { pages });
  assert.deepEqual(inspected.missingSectionKeys, []);
  assert.deepEqual(inspected.missingPageDocTokens, []);
});

test("project homepage renderer is additive and idempotent for existing content", () => {
  const first = renderFeishuProjectHomepageAppendXml({ project, pages });
  const second = renderFeishuProjectHomepageAppendXml({
    project,
    pages,
    existingContent: first.xml,
  });
  assert.equal(second.xml, "");
});
