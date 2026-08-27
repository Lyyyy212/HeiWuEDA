import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MATERIALS_ROOT = path.resolve(HERE, '..', '..', '..');
const lock = JSON.parse(fs.readFileSync(path.join(MATERIALS_ROOT, 'manifests', 'sources.lock.json'), 'utf8'));
const manifest = JSON.parse(fs.readFileSync(path.join(MATERIALS_ROOT, 'manifests', 'api-manifest.json'), 'utf8'));
const examples = JSON.parse(fs.readFileSync(path.join(MATERIALS_ROOT, 'manifests', 'api-example-index.json'), 'utf8'));

test('manifest counts and source identity match the fixed lock', () => {
  assert.deepEqual(manifest.stats.declarations, lock.typePackage.declarationCounts);
  assert.equal(manifest.canonicalSource.version, lock.typePackage.version);
  assert.equal(manifest.canonicalSource.declarationSha256, lock.typePackage.declarationSha256);
});

test('EDA runtime module mapping comes from the canonical EDA class', () => {
  assert.equal(manifest.runtimeModules.dmt_Project, 'DMT_Project');
  assert.equal(manifest.runtimeModules.sch_PrimitiveComponent, 'SCH_PrimitiveComponent');
  assert.equal(manifest.runtimeModules.sys_IFrame, 'SYS_IFrame');
});

test('a canonical project API preserves parameters, Promise return, and docs link', () => {
  const method = manifest.declarations.classes.DMT_Project.methods.find(
    (item) => item.name === 'getCurrentProjectInfo',
  );
  assert.ok(method);
  assert.equal(method.returnType, 'Promise<IDMT_ProjectItem | undefined>');
  assert.equal(method.returnsPromise, true);
  assert.deepEqual(method.parameters, []);
  assert.equal(
    manifest.declarations.classes.DMT_Project.documentationPath,
    'sources/core/easyeda-api-skill/references/classes/DMT_Project.md',
  );
});

test('every mapped example points to an existing runtime class method and a valid line', () => {
  for (const item of Object.values(examples.calls)) {
    if (item.mappingStatus !== 'mapped') continue;
    assert.equal(manifest.runtimeModules[item.runtimeModule], item.class);
    assert.ok(manifest.declarations.classes[item.class].methods.some((method) => method.name === item.method));
    for (const occurrence of item.occurrences) {
      const filePath = path.join(MATERIALS_ROOT, ...occurrence.path.split('/'));
      assert.ok(fs.existsSync(filePath), filePath);
      const lineCount = fs.readFileSync(filePath, 'utf8').split(/\r?\n/).length;
      assert.ok(occurrence.line >= 1 && occurrence.line <= lineCount, `${occurrence.path}:${occurrence.line}`);
      assert.equal(occurrence.commit.length, 40);
    }
  }
});

test('known official calls are indexed at method level', () => {
  assert.equal(examples.calls['eda.sys_IFrame.openIFrame'].canonicalMethod, 'SYS_IFrame.openIFrame');
  assert.ok(examples.calls['eda.sys_IFrame.openIFrame'].occurrences.length > 0);
  assert.equal(
    examples.calls['eda.sch_PrimitiveComponent.getAll'].canonicalMethod,
    'SCH_PrimitiveComponent.getAll',
  );
});
