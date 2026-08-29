import assert from "node:assert/strict";
import test from "node:test";

import {
  feishuProjectHomepageIndexDigest,
  inspectFeishuProjectHomepage,
  renderFeishuProjectHomepageAppendXml,
} from "./project-homepage.mjs";

const project = { projectId: "project-1", projectName: "项目一" };
const pages = [{ canvasPageId: "page:main", title: "01 主控板", docToken: "doc-main" }];
const projectOverviewWhiteboardToken = "FixtureProjectOverviewWhiteboardToken01";

test("project homepage renderer adds compact section headings and page references", () => {
  const rendered = renderFeishuProjectHomepageAppendXml({
    project,
    pages,
    projectOverviewWhiteboardToken,
  });
  const readerVisibleText = rendered.xml.replace(/<[^>]*>/gu, "");
  assert.match(rendered.xml, /00 项目总览/u);
  assert.match(rendered.xml, /99 历史归档/u);
  assert.match(rendered.xml, /doc-id="doc-main"/u);
  assert.match(rendered.xml, /工程原理图总画板/u);
  assert.match(rendered.xml, /token="FixtureProjectOverviewWhiteboardToken01"/u);
  assert.match(readerVisibleText, /项目：项目一/u);
  assert.doesNotMatch(readerVisibleText, /project-1|page:main|doc-main|项目 UUID|图页 ID/u);
  assert.equal(rendered.indexDigest, feishuProjectHomepageIndexDigest({
    project,
    pages,
    projectOverviewWhiteboardToken,
  }));
  assert.equal(rendered.indexDigest.length, 64);
  const inspected = inspectFeishuProjectHomepage(rendered.xml, {
    pages,
    projectOverviewWhiteboardToken,
  });
  assert.deepEqual(inspected.missingSectionKeys, []);
  assert.deepEqual(inspected.missingPageDocTokens, []);
  assert.equal(inspected.missingProjectOverviewWhiteboardToken, null);
});

test("project homepage renderer is additive and idempotent for existing content", () => {
  const first = renderFeishuProjectHomepageAppendXml({
    project,
    pages,
    projectOverviewWhiteboardToken,
  });
  const second = renderFeishuProjectHomepageAppendXml({
    project,
    pages,
    projectOverviewWhiteboardToken,
    existingContent: first.xml,
  });
  assert.equal(second.xml, "");
});
