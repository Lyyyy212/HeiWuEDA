import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import test from "node:test";

import { attachHardwareLearningPageNetlist, readHardwareLearningPageNetlist } from "./page-netlist.mjs";

const pageId = "page:schematic-main";
const identity = {
  projectUuid: "project-1",
  documentUuid: "document-1",
  documentType: "schematic",
  schematicPageUuid: "page-1",
  windowId: "window-1",
};

function fixtureNetlist(value = "10k") {
  return {
    version: "1.0",
    components: {
      c1: {
        props: { Designator: "R1", Name: "R", Value: value, FootprintName: "R0603" },
        pinInfoMap: {
          "1": { number: "1", name: "1", net: "VIN" },
          "2": { number: "2", name: "2", net: "SENSE" },
        },
      },
      c2: {
        props: { Designator: "U1", Name: "ADC", Value: "ADC" },
        pinInfoMap: { "3": { number: "3", name: "AIN", net: "SENSE" } },
      },
    },
  };
}

async function fixtureProject() {
  const projectDir = await mkdtemp(join(tmpdir(), "jlc-netlist-test-"));
  const pageDir = join(projectDir, "canvas", "pages", "schematic-main");
  await mkdir(pageDir, { recursive: true });
  await writeFile(join(pageDir, "hardware-learning-canvas.json"), JSON.stringify({ schema: {}, store: {} }));
  const sourcePath = join(projectDir, "official.net");
  await writeFile(sourcePath, JSON.stringify(fixtureNetlist()));
  return { projectDir, pageDir, sourcePath };
}

async function officialEvidence(netlistPath, overrides = {}) {
  const buffer = await readFile(netlistPath);
  const artifactSha256 = createHash("sha256").update(buffer).digest("hex");
  const evidencePath = `${netlistPath}.evidence.json`;
  const envelope = {
    schemaVersion: "easyeda.gateway.formal-export-evidence.v1",
    status: "PASS",
    identity: { ...identity, documentType: 1 },
    safety: {
      capabilityId: "netlist.jlceda",
      executionModel: "ONE_OFFICIAL_CALL_PER_BRIDGE_REQUEST",
      automaticRetry: false,
    },
    files: { [basename(netlistPath)]: artifactSha256 },
    ...overrides,
  };
  const evidenceBuffer = Buffer.from(JSON.stringify(envelope));
  await writeFile(evidencePath, evidenceBuffer);
  return {
    source: "official-easyeda-export",
    format: "jlceda",
    identity,
    artifactSha256,
    evidencePath,
    evidenceSha256: createHash("sha256").update(evidenceBuffer).digest("hex"),
  };
}

test("official netlist is attached beside the page canvas and queried by component or net", async () => {
  const fixture = await fixtureProject();
  const attached = await attachHardwareLearningPageNetlist({
    projectDir: fixture.projectDir,
    pageId,
    netlistPath: fixture.sourcePath,
    evidence: await officialEvidence(fixture.sourcePath),
  });
  assert.equal(attached.status, "attached");
  assert.equal(attached.summary.componentCount, 2);
  assert.equal(attached.summary.netCount, 2);
  assert.match(attached.netlistPath, /pages[\\/]schematic-main[\\/]official-easyeda-netlist\.net$/);
  assert.equal(JSON.parse(await readFile(attached.metadataPath, "utf8")).identity.documentUuid, "document-1");

  const byComponent = await readHardwareLearningPageNetlist({
    projectDir: fixture.projectDir,
    pageId,
    componentRefs: ["R1"],
  });
  assert.deepEqual(byComponent.components.map((component) => component.designator), ["R1"]);
  assert.deepEqual(byComponent.nets.map((net) => net.name), ["SENSE", "VIN"]);

  const byNet = await readHardwareLearningPageNetlist({
    projectDir: fixture.projectDir,
    pageId,
    netNames: ["SENSE"],
  });
  assert.deepEqual(byNet.components.map((component) => component.designator), ["R1", "U1"]);
  assert.equal(byNet.nets[0].members.length, 2);
});

test("same evidence is idempotent and a conflicting first-import netlist is rejected", async () => {
  const fixture = await fixtureProject();
  const input = {
    projectDir: fixture.projectDir,
    pageId,
    netlistPath: fixture.sourcePath,
    evidence: await officialEvidence(fixture.sourcePath),
  };
  await attachHardwareLearningPageNetlist(input);
  assert.equal((await attachHardwareLearningPageNetlist(input)).status, "already-attached");
  const conflictingPath = join(fixture.projectDir, "conflicting.net");
  await writeFile(conflictingPath, JSON.stringify(fixtureNetlist("20k")));
  await assert.rejects(
    attachHardwareLearningPageNetlist({
      ...input,
      netlistPath: conflictingPath,
      evidence: await officialEvidence(conflictingPath),
    }),
    /different official netlist/i,
  );
});

test("missing sidecar is explicit and invalid sources are rejected", async () => {
  const fixture = await fixtureProject();
  assert.equal(
    (await readHardwareLearningPageNetlist({ projectDir: fixture.projectDir, pageId })).status,
    "missing",
  );
  await assert.rejects(
    attachHardwareLearningPageNetlist({
      projectDir: fixture.projectDir,
      pageId,
      netlistPath: fixture.sourcePath,
      evidence: { ...(await officialEvidence(fixture.sourcePath)), source: "user-file" },
    }),
    /official-easyeda-export/i,
  );
});

test("official component-array netlists remain readable", async () => {
  const fixture = await fixtureProject();
  await writeFile(fixture.sourcePath, JSON.stringify({
    version: "1.0",
    components: [{
      props: { Designator: "C1", Value: "100n" },
      pinInfoMap: { "1": { number: "1", net: "VCC" } },
    }],
  }));
  const attached = await attachHardwareLearningPageNetlist({
    projectDir: fixture.projectDir,
    pageId,
    netlistPath: fixture.sourcePath,
    evidence: await officialEvidence(fixture.sourcePath),
  });
  assert.equal(attached.summary.componentCount, 1);
  const read = await readHardwareLearningPageNetlist({
    projectDir: fixture.projectDir,
    pageId,
    componentRefs: ["C1"],
  });
  assert.equal(read.components[0].designator, "C1");
});

test("tampered or unsealed formal evidence is rejected", async () => {
  const fixture = await fixtureProject();
  const evidence = await officialEvidence(fixture.sourcePath);
  await writeFile(evidence.evidencePath, "{}");
  await assert.rejects(
    attachHardwareLearningPageNetlist({
      projectDir: fixture.projectDir,
      pageId,
      netlistPath: fixture.sourcePath,
      evidence,
    }),
    /evidence digest mismatch/i,
  );
  const unsealed = await officialEvidence(fixture.sourcePath, { files: {} });
  await assert.rejects(
    attachHardwareLearningPageNetlist({
      projectDir: fixture.projectDir,
      pageId,
      netlistPath: fixture.sourcePath,
      evidence: unsealed,
    }),
    /not sealed/i,
  );
});
