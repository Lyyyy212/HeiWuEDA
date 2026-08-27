import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";

import {
  nonEmptyString,
  resolveHardwareLearningPageDir,
  resolveHardwareLearningPageFile,
} from "./canvas-storage.mjs";

export const HARDWARE_LEARNING_NETLIST_FILE_NAME = "official-easyeda-netlist.net";
export const HARDWARE_LEARNING_NETLIST_META_FILE_NAME = "official-easyeda-netlist.meta.json";

const MAX_FILTER_ITEMS = 64;
const DEFAULT_COMPONENT_LIMIT = 80;
const DEFAULT_NET_LIMIT = 120;
const MAX_RESULT_LIMIT = 500;

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function cloneJson(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function normalizeIdentity(identity = {}) {
  const rawDocumentType = identity.documentType;
  const documentType = [1, "1", "SCHEMATIC_PAGE", "schematic"].includes(rawDocumentType)
    ? "SCHEMATIC_PAGE"
    : null;
  const normalized = {
    projectUuid: nonEmptyString(identity.projectUuid),
    documentUuid: nonEmptyString(identity.documentUuid),
    documentType,
    schematicPageUuid: nonEmptyString(identity.schematicPageUuid),
    windowId: nonEmptyString(identity.windowId),
  };
  if (!normalized.projectUuid || !normalized.documentUuid || !normalized.documentType) {
    throw new Error("Official EasyEDA netlist evidence requires projectUuid, documentUuid, and documentType.");
  }
  return normalized;
}

function sameCoreIdentity(left, right) {
  return ["projectUuid", "documentUuid", "documentType"]
    .every((key) => left[key] === right[key]);
}

function parseNetlist(buffer) {
  let payload;
  try {
    payload = JSON.parse(buffer.toString("utf8"));
  } catch (error) {
    throw new Error(`Official EasyEDA JLCEDA netlist is not valid UTF-8 JSON: ${error.message}`);
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Official EasyEDA JLCEDA netlist must be a JSON object.");
  }
  if (!payload.components || typeof payload.components !== "object") {
    throw new Error("Official EasyEDA JLCEDA netlist is missing its components object or array.");
  }
  return payload;
}

function componentRows(netlist) {
  return Object.entries(netlist.components).map(([componentId, component]) => {
    const props = component?.props && typeof component.props === "object" ? component.props : {};
    const pinInfoMap = component?.pinInfoMap && typeof component.pinInfoMap === "object"
      ? component.pinInfoMap
      : {};
    const pins = Object.entries(pinInfoMap).map(([pinKey, pin]) => ({
      key: pinKey,
      number: nonEmptyString(pin?.number) ?? pinKey,
      name: nonEmptyString(pin?.name),
      net: nonEmptyString(pin?.net),
    }));
    return {
      componentId,
      designator: nonEmptyString(props.Designator),
      name: nonEmptyString(props.Name),
      value: nonEmptyString(props.Value),
      footprint: nonEmptyString(props.FootprintName),
      manufacturer: nonEmptyString(props.Manufacturer),
      manufacturerPart: nonEmptyString(props["Manufacturer Part"]),
      supplier: nonEmptyString(props.Supplier),
      supplierPart: nonEmptyString(props["Supplier Part"]),
      pins,
    };
  });
}

function netRows(components) {
  const nets = new Map();
  for (const component of components) {
    for (const pin of component.pins) {
      if (!pin.net) continue;
      const members = nets.get(pin.net) ?? [];
      members.push({
        componentId: component.componentId,
        designator: component.designator,
        pinNumber: pin.number,
        pinName: pin.name,
      });
      nets.set(pin.net, members);
    }
  }
  return [...nets.entries()]
    .map(([name, members]) => ({ name, members }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

function netlistSummary(netlist) {
  const components = componentRows(netlist);
  const nets = netRows(components);
  return {
    componentCount: components.length,
    pinCount: components.reduce((count, component) => count + component.pins.length, 0),
    netCount: nets.length,
    connectedPinCount: nets.reduce((count, net) => count + net.members.length, 0),
  };
}

function normalizeStringList(value, label) {
  if (value == null) return [];
  if (!Array.isArray(value) || value.length > MAX_FILTER_ITEMS) {
    throw new Error(`${label} must be an array with at most ${MAX_FILTER_ITEMS} entries.`);
  }
  return [...new Set(value.map(nonEmptyString).filter(Boolean))];
}

function normalizeLimit(value, fallback) {
  if (value == null) return fallback;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > MAX_RESULT_LIMIT) {
    throw new Error(`Result limits must be integers from 1 through ${MAX_RESULT_LIMIT}.`);
  }
  return parsed;
}

async function writeAtomic(filePath, buffer) {
  await mkdir(dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.${randomUUID()}.tmp`;
  await writeFile(tempPath, buffer);
  await rename(tempPath, filePath);
}

async function readMetadata(metaPath) {
  try {
    return JSON.parse(await readFile(metaPath, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

function pagePaths(args, pageId) {
  const pageDir = resolveHardwareLearningPageDir(args, pageId);
  return {
    pageDir,
    canvasPath: resolveHardwareLearningPageFile(args, pageId),
    netlistPath: join(pageDir, HARDWARE_LEARNING_NETLIST_FILE_NAME),
    metadataPath: join(pageDir, HARDWARE_LEARNING_NETLIST_META_FILE_NAME),
  };
}

export async function attachHardwareLearningPageNetlist(args = {}) {
  const pageId = nonEmptyString(args.pageId);
  const sourcePath = resolve(String(args.netlistPath ?? ""));
  if (!pageId) throw new Error("pageId is required.");
  if (!nonEmptyString(args.netlistPath)) throw new Error("netlistPath is required.");
  const identity = normalizeIdentity(args.evidence?.identity);
  if (args.evidence?.source !== "official-easyeda-export" || args.evidence?.format !== "jlceda") {
    throw new Error("Only identity-bound official-easyeda-export JLCEDA netlists can be attached.");
  }
  const { pageDir, canvasPath, netlistPath, metadataPath } = pagePaths(args, pageId);
  try {
    if (!(await stat(canvasPath)).isFile()) throw new Error("not a file");
  } catch (error) {
    throw new Error(`Canvas page must be saved before attaching its netlist: ${canvasPath} (${error.message})`);
  }

  const sourceBuffer = await readFile(sourcePath);
  const digest = sha256(sourceBuffer);
  const declaredDigest = nonEmptyString(args.evidence?.artifactSha256);
  if (declaredDigest && declaredDigest !== digest) {
    throw new Error(`Official EasyEDA netlist digest mismatch: expected ${declaredDigest}, got ${digest}.`);
  }
  const netlist = parseNetlist(sourceBuffer);
  const summary = netlistSummary(netlist);
  const evidencePathValue = nonEmptyString(args.evidence?.evidencePath);
  const evidenceDigest = nonEmptyString(args.evidence?.evidenceSha256);
  if (!evidencePathValue || !evidenceDigest) {
    throw new Error("Official EasyEDA netlist attachment requires evidencePath and evidenceSha256.");
  }
  const evidencePath = resolve(evidencePathValue);
  const evidenceBuffer = await readFile(evidencePath);
  if (sha256(evidenceBuffer) !== evidenceDigest) {
    throw new Error("Official EasyEDA netlist evidence digest mismatch.");
  }
  let evidenceEnvelope;
  try {
    evidenceEnvelope = JSON.parse(evidenceBuffer.toString("utf8"));
  } catch (error) {
    throw new Error(`Official EasyEDA netlist evidence is not valid JSON: ${error.message}`);
  }
  if (
    evidenceEnvelope?.schemaVersion !== "easyeda.gateway.formal-export-evidence.v1"
    || evidenceEnvelope?.status !== "PASS"
  ) {
    throw new Error("Official EasyEDA netlist evidence must be a PASS formal-export envelope.");
  }
  const envelopeIdentity = normalizeIdentity(evidenceEnvelope.identity);
  if (!sameCoreIdentity(identity, envelopeIdentity)) {
    throw new Error("Official EasyEDA netlist evidence identity differs from the attachment identity.");
  }
  const safety = evidenceEnvelope.safety;
  if (
    safety?.capabilityId !== "netlist.jlceda"
    || safety?.executionModel !== "ONE_OFFICIAL_CALL_PER_BRIDGE_REQUEST"
    || safety?.automaticRetry !== false
  ) {
    throw new Error("Official EasyEDA netlist evidence does not prove the one-call, zero-retry safety contract.");
  }
  if (evidenceEnvelope.files?.[basename(sourcePath)] !== digest) {
    throw new Error("Official EasyEDA netlist artifact is not sealed by its evidence envelope.");
  }
  const existing = await readMetadata(metadataPath);
  if (existing) {
    if (existing.artifact?.sha256 === digest && JSON.stringify(existing.identity) === JSON.stringify(identity)) {
      return { ...existing, status: "already-attached", pageDir, netlistPath, metadataPath };
    }
    throw new Error(
      "This canvas page already has a different official netlist. Create a new page or explicitly migrate its evidence instead of mixing schematics.",
    );
  }

  const attachedAt = new Date().toISOString();
  const metadata = {
    schemaVersion: "jlc.hardware-learning-page-netlist.v1",
    status: "verified",
    pageId,
    source: "official-easyeda-export",
    format: "jlceda",
    identity,
    artifact: {
      fileName: HARDWARE_LEARNING_NETLIST_FILE_NAME,
      sourceFileName: basename(sourcePath),
      sha256: digest,
      bytes: sourceBuffer.length,
    },
    summary,
    evidence: {
      evidencePath,
      evidenceSha256: evidenceDigest,
      exportedAt: nonEmptyString(args.evidence?.exportedAt),
    },
    attachedAt,
  };
  await mkdir(pageDir, { recursive: true });
  await writeAtomic(netlistPath, sourceBuffer);
  await writeAtomic(metadataPath, Buffer.from(`${JSON.stringify(metadata, null, 2)}\n`));
  return { ...metadata, status: "attached", pageDir, netlistPath, metadataPath };
}

export async function readHardwareLearningPageNetlist(args = {}) {
  const pageId = nonEmptyString(args.pageId);
  if (!pageId) throw new Error("pageId is required.");
  const { pageDir, netlistPath, metadataPath } = pagePaths(args, pageId);
  const metadata = await readMetadata(metadataPath);
  if (!metadata) {
    return {
      schemaVersion: "jlc.hardware-learning-page-netlist-read.v1",
      status: "missing",
      pageId,
      pageDir,
      netlistPath,
      metadataPath,
    };
  }
  const buffer = await readFile(netlistPath);
  const digest = sha256(buffer);
  if (digest !== metadata.artifact?.sha256) {
    throw new Error(`Stored official EasyEDA netlist digest mismatch for ${pageId}.`);
  }
  const netlist = parseNetlist(buffer);
  const componentRefs = normalizeStringList(args.componentRefs, "componentRefs");
  const requestedNetNames = normalizeStringList(args.netNames, "netNames");
  const includeData = args.includeData === true || componentRefs.length > 0 || requestedNetNames.length > 0;
  const base = {
    schemaVersion: "jlc.hardware-learning-page-netlist-read.v1",
    status: "verified",
    pageId,
    pageDir,
    netlistPath,
    metadataPath,
    identity: cloneJson(metadata.identity),
    artifact: cloneJson(metadata.artifact),
    summary: cloneJson(metadata.summary),
  };
  if (!includeData) return base;

  const componentLimit = normalizeLimit(args.maxComponents, DEFAULT_COMPONENT_LIMIT);
  const netLimit = normalizeLimit(args.maxNets, DEFAULT_NET_LIMIT);
  const referenceSet = new Set(componentRefs.map((value) => value.toLowerCase()));
  const netNameSet = new Set(requestedNetNames.map((value) => value.toLowerCase()));
  const allComponents = componentRows(netlist);
  const allNets = netRows(allComponents);
  const components = allComponents.filter((component) => {
    if (referenceSet.size === 0 && netNameSet.size === 0) return true;
    if (referenceSet.has(String(component.designator ?? "").toLowerCase())) return true;
    return component.pins.some((pin) => netNameSet.has(String(pin.net ?? "").toLowerCase()));
  });
  const selectedDesignators = new Set(components.map((component) => component.designator).filter(Boolean));
  const nets = allNets.filter((net) => {
    if (referenceSet.size === 0 && netNameSet.size === 0) return true;
    if (netNameSet.has(net.name.toLowerCase())) return true;
    return net.members.some((member) => selectedDesignators.has(member.designator));
  });
  return {
    ...base,
    query: { componentRefs, netNames: requestedNetNames },
    components: components.slice(0, componentLimit),
    nets: nets.slice(0, netLimit),
    truncated: components.length > componentLimit || nets.length > netLimit,
    matchedComponentCount: components.length,
    matchedNetCount: nets.length,
  };
}
