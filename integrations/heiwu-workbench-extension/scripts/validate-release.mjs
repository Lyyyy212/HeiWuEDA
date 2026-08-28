import { Buffer } from 'node:buffer';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import JSZip from 'jszip';

const integrationRoot = path.resolve(import.meta.dirname, '..');
const repositoryRoot = path.resolve(integrationRoot, '..', '..');

function readText(relativePath) {
	return fs.readFileSync(path.join(integrationRoot, relativePath), 'utf8');
}

function readJson(relativePath) {
	return JSON.parse(readText(relativePath));
}

function invariant(condition, message) {
	if (!condition)
		throw new Error(message);
}

function sameArray(left, right) {
	return left.length === right.length && left.every((value, index) => value === right[index]);
}

function assertNoDynamicExecution(label, source) {
	const forbidden = [
		['AsyncFunction', /AsyncFunction/],
		['new Function', /new\s+Function/],
		['eval()', /\beval\s*\(/],
	];
	for (const [name, pattern] of forbidden)
		invariant(!pattern.test(source), `${label} contains forbidden dynamic execution primitive: ${name}`);
}

const extension = readJson('extension.json');
const packageJson = readJson('package.json');
const packageLock = readJson('package-lock.json');
const identity = readJson('release/marketplace-identity.json');
const listing = readJson('release/marketplace-listing.json');
const iframe = readText('iframe/workbench.html');
const changelog = readText('CHANGELOG.md');
const releasing = readText('RELEASING.md');
const runtimeSource = readText('src/index.ts');
const serverSource = readText('scripts/workbench-bridge-server.mjs');

for (const key of ['name', 'uuid', 'displayName', 'description', 'version', 'license', 'repository'])
	invariant(extension[key] !== undefined && extension[key] !== '', `extension.json is missing required marketplace field ${key}`);
invariant(extension.repository?.type === 'github', 'extension.json repository type must be github');
invariant(extension.repository?.url === identity.repository?.url, 'extension.json repository URL differs from marketplace identity lock');
invariant(extension.repository?.type === identity.repository?.type, 'extension.json repository type differs from marketplace identity lock');
for (const key of ['name', 'uuid', 'displayName', 'publisher'])
	invariant(extension[key] === identity[key], `extension.json ${key} differs from marketplace identity lock`);
invariant(extension.engines?.eda === identity.edaEngine, 'EDA engine range differs from marketplace identity lock');
for (const key of ['description', 'categories'])
	invariant(extension[key] === listing[key], `extension.json ${key} differs from marketplace listing lock`);
invariant(sameArray(extension.keywords, listing.keywords), 'extension.json keywords differ from marketplace listing lock');
invariant(extension.images?.logo === listing.images.logo, 'extension.json logo differs from marketplace listing lock');
invariant(/^[A-F0-9]{64}$/.test(listing.sourceBaseline.sha256), 'Marketplace listing baseline SHA-256 is invalid');
invariant(extension.version === packageJson.version, 'extension.json and package.json versions differ');
invariant(extension.version === packageLock.version, 'extension.json and package-lock.json root versions differ');
invariant(extension.version === packageLock.packages?.['']?.version, 'package-lock root package version differs');
invariant(/^\d+\.\d+\.\d+$/.test(extension.version), 'Version must be a three-part semantic version');
invariant(
	iframe.includes(`<div id="version" class="version">v${extension.version}</div>`),
	'Workbench compact header version is stale',
);
invariant(
	new RegExp(`^## \\[${extension.version.replaceAll('.', '\\.')}\\] - \\d{4}-\\d{2}-\\d{2}$`, 'm').test(changelog),
	`CHANGELOG.md has no dated ${extension.version} entry`,
);
invariant(releasing.includes('手工上传到嘉立创官方扩展平台'), 'Release guide must preserve the manual official upload boundary');

const menuTitles = ['打开黑五EDA', 'GitHub 项目'];
for (const [context, menus] of Object.entries(extension.headerMenus ?? {})) {
	invariant(menus.length === 1, `${context} must expose exactly one top-level workbench menu`);
	invariant(menus[0].title === identity.displayName, `${context} menu title differs from the identity lock`);
	invariant(
		sameArray(menus[0].menuItems.map(item => item.title), menuTitles),
		`${context} exposes an unexpected menu item`,
	);
}

const runtimeOperations = [...runtimeSource.matchAll(/id: '(workbench\.[^']+\.v\d+)'/g)].map(match => match[1]);
invariant(sameArray(runtimeOperations, identity.allowedOperations), 'Runtime operation catalog differs from identity lock');
for (const operation of identity.allowedOperations)
	invariant(serverSource.includes(`'${operation}'`), `Bridge server is missing allowlisted operation ${operation}`);
invariant(runtimeSource.includes(`const PROTOCOL_VERSION = ${identity.protocolVersion};`), 'Runtime protocol version differs from identity lock');
invariant(serverSource.includes(`export const PROTOCOL_VERSION = ${identity.protocolVersion};`), 'Server protocol version differs from identity lock');
invariant(!/message\.code|payload\.code/.test(runtimeSource + serverSource), 'Raw code payload handling is forbidden');
invariant(serverSource.includes(`request.url === '/execute'`), 'Legacy endpoint rejection is missing');
invariant(serverSource.includes('410'), 'Legacy endpoint must return Gone');
assertNoDynamicExecution('Extension runtime source', runtimeSource);

const logo = fs.readFileSync(path.join(integrationRoot, extension.images.logo));
invariant(logo.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])), 'Logo is not a PNG');
const logoWidth = logo.readUInt32BE(16);
const logoHeight = logo.readUInt32BE(20);
invariant(logoWidth > 0 && logoWidth === logoHeight, 'Marketplace logo must be square');

for (const [relativePath, expected] of Object.entries(listing.requiredAssets)) {
	const asset = fs.readFileSync(path.join(integrationRoot, relativePath));
	invariant(asset.length === expected.bytes, `${relativePath} byte size differs from marketplace listing lock`);
	const assetHash = createHash('sha256').update(asset).digest('hex').toUpperCase();
	invariant(assetHash === expected.sha256, `${relativePath} SHA-256 differs from marketplace listing lock`);
}

const artifactName = `${extension.name}_v${extension.version}.eext`;
const artifactPath = path.join(integrationRoot, 'build', 'dist', artifactName);
invariant(fs.existsSync(artifactPath), `Release artifact is missing: ${artifactName}`);
const artifact = fs.readFileSync(artifactPath);
const zip = await JSZip.loadAsync(artifact);
const requiredFiles = [
	'CHANGELOG.md',
	'LICENSE',
	'NOTICE',
	'README.md',
	'RELEASING.md',
	'THIRD_PARTY_NOTICES.md',
	'dist/index.js',
	'extension.json',
	'images/logo.png',
	'release/marketplace-identity.json',
	'release/marketplace-listing.json',
];
for (const file of requiredFiles)
	invariant(Boolean(zip.file(file)), `Release artifact is missing ${file}`);
for (const prefix of ['build/', 'config/', 'node_modules/', 'scripts/', 'src/', 'tests/', 'tmp/'])
	invariant(zip.file(new RegExp(`^${prefix}`)).length === 0, `Release artifact contains development path ${prefix}`);

const packagedExtension = JSON.parse(await zip.file('extension.json').async('string'));
for (const key of ['name', 'uuid', 'displayName', 'description', 'publisher', 'version', 'license'])
	invariant(packagedExtension[key] === extension[key], `Packaged extension ${key} differs from source manifest`);
invariant(
	JSON.stringify(packagedExtension.repository) === JSON.stringify(extension.repository),
	'Packaged extension repository differs from source manifest',
);
const packagedBundle = await zip.file('dist/index.js').async('string');
assertNoDynamicExecution('Packaged runtime', packagedBundle);

const workflowPath = path.join(repositoryRoot, '.github', 'workflows', 'easyeda-extension-release.yml');
invariant(fs.existsSync(workflowPath), 'Automated extension build workflow is missing');

const sha256 = createHash('sha256').update(artifact).digest('hex').toUpperCase();
process.stdout.write(`${JSON.stringify({
	artifact: artifactPath,
	identity: {
		name: extension.name,
		publisher: extension.publisher,
		uuid: extension.uuid,
	},
	logo: `${logoWidth}x${logoHeight}`,
	listingBaseline: listing.sourceBaseline,
	operations: identity.allowedOperations,
	protocolVersion: identity.protocolVersion,
	sha256,
	version: extension.version,
}, null, 2)}\n`);
