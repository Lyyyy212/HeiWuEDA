import { createLarkCliAdapter, normalizeFeishuDocReference } from "./lark-cli-adapter.mjs";

export const FEISHU_DOCUMENT_INSPECTION_SCHEMA = "jlc.feishu-document-inspection.v1";
export const REQUIRED_LEARNING_NOTE_SECTIONS = Object.freeze([
  "工程与图页信息",
  "原理图学习画板",
  "模块索引",
  "提问与解答",
  "模块间关系",
  "待验证项",
  "同步记录",
]);

function decodeEntities(value) {
  return String(value ?? "")
    .replace(/&lt;/gu, "<")
    .replace(/&gt;/gu, ">")
    .replace(/&quot;/gu, '"')
    .replace(/&#39;/gu, "'")
    .replace(/&amp;/gu, "&");
}
function plainText(value) {
  return decodeEntities(String(value ?? "").replace(/<[^>]*>/gu, "")).trim();
}

function requiredDocument(payload, label) {
  const document = payload?.data?.document;
  if (!document || typeof document !== "object") {
    throw new Error(`${label} response is missing data.document.`);
  }
  if (typeof document.content !== "string") {
    throw new Error(`${label} response is missing document content.`);
  }
  return document;
}

export function parseFeishuDocumentContent(content) {
  const source = String(content ?? "");
  const titleMatch = /<title\s+id="([^"]+)"[^>]*>([\s\S]*?)<\/title>/u.exec(source);
  const headings = [];
  const whiteboards = [];
  let currentSection = null;
  const elementPattern = /<h([1-6])\s+id="([^"]+)"[^>]*>([\s\S]*?)<\/h\1>|<whiteboard\s+id="([^"]+)"\s+token="([^"]+)"[^>]*><\/whiteboard>/gu;
  for (const match of source.matchAll(elementPattern)) {
    if (match[1]) {
      const heading = {
        level: Number(match[1]),
        blockId: match[2],
        title: plainText(match[3]),
      };
      headings.push(heading);
      if (heading.level === 1) currentSection = heading.title;
    } else {
      whiteboards.push({
        blockId: match[4],
        token: match[5],
        sectionTitle: currentSection,
        role: currentSection === "原理图学习画板"
          ? "learning-board"
          : currentSection === "模块索引"
            ? "module-index-board"
            : "unclassified",
      });
    }
  }
  const moduleHeadings = headings
    .filter((heading) => heading.level === 2 && /^模块\s*\d+$/u.test(heading.title))
    .map((heading) => ({
      ...heading,
      frameNumber: Number(/\d+/u.exec(heading.title)[0]),
    }));
  const topLevelTitles = headings
    .filter((heading) => heading.level === 1)
    .map((heading) => heading.title);
  return {
    title: titleMatch ? plainText(titleMatch[2]) : null,
    titleBlockId: titleMatch?.[1] ?? null,
    headings,
    moduleHeadings,
    whiteboards,
    requiredSections: {
      expected: [...REQUIRED_LEARNING_NOTE_SECTIONS],
      present: topLevelTitles,
      missing: REQUIRED_LEARNING_NOTE_SECTIONS.filter((title) => !topLevelTitles.includes(title)),
    },
    legacyBrandingTerms: /\bCowart\b/u.test(plainText(source)) ? ["Cowart"] : [],
  };
}

export async function inspectFeishuLearningDocument(input = {}, options = {}) {
  const target = normalizeFeishuDocReference(input.document);
  const adapter = options.adapter ?? createLarkCliAdapter(options);
  const outlinePayload = await adapter.fetchDocumentOutline(target.reference);
  const fullPayload = await adapter.fetchDocumentFull(target.reference);
  const outlineDocument = requiredDocument(outlinePayload, "outline");
  const fullDocument = requiredDocument(fullPayload, "full");
  if (outlineDocument.document_id !== target.docToken || fullDocument.document_id !== target.docToken) {
    throw new Error("Feishu document identity changed during inspection.");
  }
  if (outlineDocument.revision_id !== fullDocument.revision_id) {
    throw new Error("Feishu document revision changed during inspection; retry from a fresh read.");
  }
  const parsed = parseFeishuDocumentContent(fullDocument.content);
  return {
    ok: true,
    schemaVersion: FEISHU_DOCUMENT_INSPECTION_SCHEMA,
    identity: "user",
    document: {
      reference: target.reference,
      docToken: target.docToken,
      revisionId: fullDocument.revision_id,
      title: parsed.title,
    },
    ...parsed,
    verifiedFromFreshReads: ["outline", "full"],
    remoteWritesPerformed: false,
  };
}
