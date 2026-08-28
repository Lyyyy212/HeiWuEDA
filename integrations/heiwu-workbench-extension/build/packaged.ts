import { Buffer } from 'node:buffer';
import path from 'node:path';
import process from 'node:process';
import fs from 'fs-extra';
import ignore from 'ignore';
import JSZip from 'jszip';

import * as extensionConfig from '../extension.json';

const archiveDate = new Date('1980-01-01T00:00:00.000Z');
const textExtensions = new Set([
	'.css',
	'.html',
	'.js',
	'.json',
	'.md',
	'.svg',
	'.txt',
]);

function normalizePackagedData(name: string, data: Buffer): Buffer {
	if (name !== 'LICENSE' && name !== 'NOTICE' && !textExtensions.has(path.extname(name).toLowerCase())) {
		return data;
	}
	return Buffer.from(data.toString('utf8').replace(/\r\n?/gu, '\n'), 'utf8');
}

function addFile(zip: JSZip, name: string, data: Buffer): void {
	zip.file(name, normalizePackagedData(name, data), { createFolders: false, date: archiveDate });
}

const integrationRoot = path.resolve(__dirname, '..');
const workbenchRoot = path.resolve(integrationRoot, '..', '..');
const upstreamGatewayRoot = path.join(
	workbenchRoot,
	'materials',
	'sources',
	'core',
	'eext-run-api-gateway',
);

async function main(): Promise<void> {
	const ignored = ignore().add([
		'.git/',
		'build/',
		'config/',
		'node_modules/',
		'scripts/',
		'src/',
		'tests/',
		'tmp/',
		'.editorconfig',
		'.gitattributes',
		'.gitignore',
		'.gitignore',
		'.npmrc',
		'eslint.config.mjs',
		'package-lock.json',
		'package.json',
		'tsconfig.json',
	]);
	const entries = await fs.readdir(integrationRoot, { encoding: 'utf-8', recursive: true });
	const files = ignored.filter(entries.map(entry => entry.replace(/\\/g, '/')))
		.filter(entry => fs.statSync(path.join(integrationRoot, entry)).isFile())
		.sort((left, right) => left < right ? -1 : left > right ? 1 : 0);

	const zip = new JSZip();
	for (const file of files) {
		addFile(zip, file, await fs.readFile(path.join(integrationRoot, file)));
	}

	addFile(zip, 'LICENSE', await fs.readFile(path.join(workbenchRoot, 'LICENSE')));
	addFile(zip, 'NOTICE', await fs.readFile(path.join(workbenchRoot, 'NOTICE')));
	addFile(zip, 'THIRD_PARTY_NOTICES.md', await fs.readFile(path.join(workbenchRoot, 'THIRD_PARTY_NOTICES.md')));
	addFile(
		zip,
		'LICENSES/Apache-2.0.txt',
		await fs.readFile(path.join(upstreamGatewayRoot, 'LICENSE')),
	);

	const outputDirectory = path.join(integrationRoot, 'build', 'dist');
	await fs.ensureDir(outputDirectory);
	const output = path.join(outputDirectory, `${extensionConfig.name}_v${extensionConfig.version}.eext`);
	await fs.writeFile(output, await zip.generateAsync({
		type: 'nodebuffer',
		compression: 'DEFLATE',
		compressionOptions: { level: 9 },
		platform: 'UNIX',
	}));
	process.stdout.write(`${output}\n`);
}

void main();
