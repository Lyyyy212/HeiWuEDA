import { createHash } from "node:crypto";

import {
  FEISHU_NOTE_SECTIONS,
  FEISHU_PROJECT_HOMEPAGE_TEMPLATE_VERSION,
} from "./note-model.mjs";

const SECTION_DESCRIPTIONS = Object.freeze({
  overview: "记录项目目标、版本、范围与当前状态。",
  concept: "记录前期架构、需求和方案取舍。",
  modules: "记录各功能模块的接口、器件与关键参数。",
  schematics: "真实原理图页作为本项目下的独立文档，并在这里建立索引。",
  review: "记录检查结论、风险项和修订状态。",
  bom: "记录 BOM 决策、替代料、供应与封装信息。",
  experiments: "记录测试条件、现象、数据与结论。",
  archive: "存放已失效方案、历史版本和迁移记录。",
});

function requiredString(value, field) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${field} is required.`);
  return value.trim();
}

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function normalizedPages(pages = []) {
  if (!Array.isArray(pages)) throw new Error("pages must be an array.");
  return pages.map((page) => ({
    canvasPageId: requiredString(page.canvasPageId, "page.canvasPageId"),
    title: requiredString(page.title ?? page.pageName, "page.title"),
    docToken: page.docToken ? requiredString(page.docToken, "page.docToken") : null,
  })).sort((left, right) => left.canvasPageId.localeCompare(right.canvasPageId));
}

export function feishuProjectHomepageIndexDigest({ project, pages = [] } = {}) {
  const identity = {
    templateVersion: FEISHU_PROJECT_HOMEPAGE_TEMPLATE_VERSION,
    projectId: requiredString(project?.projectId, "project.projectId"),
    sections: FEISHU_NOTE_SECTIONS.map(({ key, title }) => ({ key, title })),
    pages: normalizedPages(pages),
  };
  return createHash("sha256").update(JSON.stringify(identity)).digest("hex");
}

export function inspectFeishuProjectHomepage(content, { pages = [] } = {}) {
  const xml = String(content ?? "");
  const normalized = normalizedPages(pages);
  return {
    missingSectionKeys: FEISHU_NOTE_SECTIONS
      .filter((section) => !xml.includes(`>${section.title}<`))
      .map((section) => section.key),
    missingPageDocTokens: normalized
      .filter((page) => page.docToken && !xml.includes(`doc-id=\"${page.docToken}\"`))
      .map((page) => page.docToken),
  };
}

export function renderFeishuProjectHomepageAppendXml({ project, pages = [], existingContent = "" } = {}) {
  const projectId = requiredString(project?.projectId, "project.projectId");
  const normalized = normalizedPages(pages);
  const inspection = inspectFeishuProjectHomepage(existingContent, { pages: normalized });
  const chunks = [];
  if (!String(existingContent).includes(projectId)) {
    chunks.push(
      `<callout emoji="📌" background-color="light-blue" border-color="blue"><p>项目 UUID：${escapeXml(projectId)}</p><p>笔记按项目集中管理；真实原理图页作为本项目下的独立文档。</p></callout>`,
    );
  }
  for (const section of FEISHU_NOTE_SECTIONS) {
    if (!inspection.missingSectionKeys.includes(section.key)) continue;
    chunks.push(`<h1>${escapeXml(section.title)}</h1>`);
    chunks.push(`<p>${escapeXml(SECTION_DESCRIPTIONS[section.key])}</p>`);
  }
  if (inspection.missingPageDocTokens.length > 0) {
    chunks.push("<p>原理图页：</p>");
    chunks.push("<ul>");
    for (const page of normalized) {
      if (!page.docToken || !inspection.missingPageDocTokens.includes(page.docToken)) continue;
      chunks.push(`<li>${escapeXml(page.title)}：<cite type="doc" doc-id="${escapeXml(page.docToken)}"/></li>`);
    }
    chunks.push("</ul>");
  }
  return {
    templateVersion: FEISHU_PROJECT_HOMEPAGE_TEMPLATE_VERSION,
    indexDigest: feishuProjectHomepageIndexDigest({ project, pages: normalized }),
    inspection,
    xml: chunks.join(""),
  };
}
