import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const MATERIALS_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(MATERIALS_ROOT, ...relativePath.split('/')), 'utf8'));
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function validateLocalMarkdownLinks(relativePath) {
  const filePath = path.join(MATERIALS_ROOT, ...relativePath.split('/'));
  const text = fs.readFileSync(filePath, 'utf8');
  const pattern = /\[[^\]]+\]\(([^)]+)\)/g;
  for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
    const target = match[1].split('#')[0];
    if (!target || /^(?:https?:\/\/|#)/.test(target)) continue;
    const resolved = path.resolve(path.dirname(filePath), ...target.split('/'));
    assert(fs.existsSync(resolved), `Broken local Markdown link in ${relativePath}: ${match[1]}`);
  }
}

const manifest = readJson('manifests/api-manifest.json');
const apiMap = readJson('manifests/jlc-hardware-learning-api-map.json');
const profile = readJson('manifests/jlc-hardware-learning-profile.json');
const contracts = readJson('contracts/learning-canvas-contracts.schema.json');

assert(apiMap.apiManifest.version === manifest.canonicalSource.version, 'Learning API Map version mismatch.');
assert(
  apiMap.apiManifest.declarationSha256 === manifest.canonicalSource.declarationSha256,
  'Learning API Map declaration hash mismatch.',
);
assert(apiMap.globalPolicy.access === 'read-only', 'Learning API Map must remain read-only.');
assert(apiMap.globalPolicy.allowInternal === false, 'Internal EasyEDA methods must remain disabled.');
assert(apiMap.globalPolicy.allowUnknownMethods === false, 'Unknown EasyEDA methods must remain disabled.');
assert(apiMap.globalPolicy.allowDocumentSwitch === false, 'Learning mode must not switch EasyEDA documents.');
assert(apiMap.globalPolicy.allowCrossPageMerge === false, 'Learning mode must not merge pages.');

for (const [methodId, entry] of Object.entries(apiMap.methods)) {
  assert(entry.access === 'read', `API Map method is not read-only: ${methodId}`);
  assert(manifest.runtimeModules[entry.runtimeModule] === entry.class, `Runtime module mismatch: ${methodId}`);
  const declaration = manifest.declarations.classes[entry.class];
  assert(declaration, `Class missing from API manifest: ${entry.class}`);
  const overloads = declaration.methods.filter((method) => method.name === entry.method);
  assert(overloads.length > 0, `Method missing from API manifest: ${entry.class}.${entry.method}`);
  assert(
    overloads.some((method) => method.releaseTag === entry.releaseTag),
    `Release tag mismatch: ${entry.class}.${entry.method}`,
  );
  assert(
    overloads.every((method) => method.visibility !== 'private' && method.releaseTag !== 'internal'),
    `Learning API Map references an internal/private method: ${entry.class}.${entry.method}`,
  );
}

for (const methodId of apiMap.identityGuard) {
  assert(apiMap.methods[methodId], `Unknown identity guard method: ${methodId}`);
}
for (const [intent, routing] of Object.entries(apiMap.intents)) {
  for (const methodId of [...routing.required, ...routing.conditional]) {
    assert(apiMap.methods[methodId], `Intent ${intent} references an unknown method: ${methodId}`);
  }
}

assert(profile.privacyPolicy.telemetry === 'disabled', 'Learning mode telemetry must be disabled.');
assert(profile.privacyPolicy.remoteAnalyticsDomainsAllowed === false, 'Analytics domains must be disabled.');
assert(profile.uiProfile.renderArguments.mode === 'hardware-learning', 'JLC Hardware Learning render mode must be hardware-learning.');
assert(profile.excludedCapabilities.includes('analytics and telemetry'), 'Analytics capability must be absent.');
assert(profile.easyedaBoundary.directAccessFromCanvas === false, 'JLC Hardware Learning must not access EasyEDA directly.');

const requiredDefinitions = [
  'CanvasSelectionEnvelope',
  'EasyedaContextRef',
  'LearningQuestion',
  'EvidenceBundle',
  'TutorAnswer',
  'CanvasAnnotationCommand',
  'LearningSession',
];
for (const definition of requiredDefinitions) {
  assert(contracts.$defs?.[definition], `Contract definition is missing: ${definition}`);
}
const annotationKinds = contracts.$defs.CanvasAnnotationCommand.properties.kind.enum;
assert(
  JSON.stringify(annotationKinds) === JSON.stringify(['note', 'highlight', 'rectangle', 'arrow']),
  'Canvas annotation whitelist changed unexpectedly.',
);
for (const prohibited of ['image', 'html', 'embed', 'slides', 'video']) {
  assert(!annotationKinds.includes(prohibited), `Prohibited annotation kind is enabled: ${prohibited}`);
}

for (const document of [
  'references/INDEX.md',
  'references/learning-canvas-architecture.md',
  'references/jlc-hardware-learning-detailed-design.md',
]) {
  validateLocalMarkdownLinks(document);
}

process.stdout.write(`${JSON.stringify({
  status: 'PASS',
  apiManifestVersion: manifest.canonicalSource.version,
  mappedReadMethods: Object.keys(apiMap.methods).length,
  identityGuards: apiMap.identityGuard.length,
  intents: Object.keys(apiMap.intents).length,
  contractDefinitions: Object.keys(contracts.$defs).length,
  allowedCanvasAnnotationKinds: annotationKinds,
  telemetry: 'DENIED',
  imageGeneration: 'DENIED',
  easyedaWrite: 'DENIED',
  crossPageMerge: 'DENIED',
}, null, 2)}\n`);
