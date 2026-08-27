import path from 'node:path';
import process from 'node:process';
import fs from 'fs-extra';
import ignore from 'ignore';
import JSZip from 'jszip';

import * as extensionConfig from '../extension.json';

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
		'src/',
		'tests/',
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
		.filter(entry => fs.statSync(path.join(integrationRoot, entry)).isFile());

	const zip = new JSZip();
	for (const file of files) {
		zip.file(file, await fs.readFile(path.join(integrationRoot, file)));
	}

	zip.file('LICENSE', await fs.readFile(path.join(workbenchRoot, 'LICENSE')));
	zip.file('NOTICE', await fs.readFile(path.join(workbenchRoot, 'NOTICE')));
	zip.file('THIRD_PARTY_NOTICES.md', await fs.readFile(path.join(workbenchRoot, 'THIRD_PARTY_NOTICES.md')));
	zip.file(
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
	}));
	process.stdout.write(`${output}\n`);
}

void main();
