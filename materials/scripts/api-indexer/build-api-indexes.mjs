import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from './vendor/package/lib/typescript.js';

const INDEXER_DIR = path.dirname(fileURLToPath(import.meta.url));
const MATERIALS_ROOT = path.resolve(INDEXER_DIR, '..', '..');
const LOCK_PATH = path.join(MATERIALS_ROOT, 'manifests', 'sources.lock.json');
const API_MANIFEST_PATH = path.join(MATERIALS_ROOT, 'manifests', 'api-manifest.json');
const EXAMPLE_INDEX_PATH = path.join(MATERIALS_ROOT, 'manifests', 'api-example-index.json');
const SUMMARY_PATH = path.join(MATERIALS_ROOT, 'references', 'api-index-summary.md');

const CODE_EXTENSIONS = new Set([
  '.cjs', '.htm', '.html', '.js', '.jsx', '.mjs', '.svelte', '.ts', '.tsx', '.vue',
]);
const DOCUMENTATION_EXTENSIONS = new Set(['.md', '.mdx']);
const IGNORED_DIRECTORY_NAMES = new Set([
  '.git', '.next', 'coverage', 'dist', 'node_modules',
]);

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

function toPosix(filePath) {
  return filePath.split(path.sep).join('/');
}

function relativeToMaterials(filePath) {
  return toPosix(path.relative(MATERIALS_ROOT, filePath));
}

function sha256Text(text) {
  return crypto.createHash('sha256').update(text).digest('hex');
}

function normalizeWhitespace(value) {
  return value.replace(/\s+/g, ' ').trim();
}

function docText(value) {
  if (typeof value === 'string') return normalizeWhitespace(value);
  if (!Array.isArray(value)) return '';
  return normalizeWhitespace(value.map((part) => part.text ?? '').join(''));
}

function getJsDoc(node) {
  const blocks = node.jsDoc ?? [];
  const summary = blocks.map((block) => docText(block.comment)).filter(Boolean).join(' ');
  const tags = ts.getJSDocTags(node).map((tag) => ({
    name: tag.tagName.text,
    comment: docText(tag.comment),
  }));
  const tagNames = new Set(tags.map((tag) => tag.name));
  const releaseTag = ['internal', 'alpha', 'beta', 'public'].find((name) => tagNames.has(name)) ?? null;
  return {
    summary,
    tags,
    releaseTag,
    deprecated: tagNames.has('deprecated'),
  };
}

function lineOf(sourceFile, node) {
  return sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
}

function modifiersOf(node) {
  const modifiers = node.modifiers?.map((modifier) => modifier.getText()) ?? [];
  let visibility = 'default';
  if (modifiers.includes('public')) visibility = 'public';
  if (modifiers.includes('protected')) visibility = 'protected';
  if (modifiers.includes('private')) visibility = 'private';
  return { modifiers, visibility };
}

function nameOf(node, sourceFile) {
  return node.name ? node.name.getText(sourceFile) : '';
}

function parameterRecord(sourceFile, parameter) {
  return {
    name: parameter.name.getText(sourceFile),
    type: parameter.type?.getText(sourceFile) ?? 'any',
    optional: Boolean(parameter.questionToken || parameter.initializer),
    rest: Boolean(parameter.dotDotDotToken),
    line: lineOf(sourceFile, parameter),
  };
}

function callableRecord(sourceFile, node, ownerName, overloadNumber) {
  const name = nameOf(node, sourceFile);
  const returnType = node.type?.getText(sourceFile) ?? 'any';
  const docs = getJsDoc(node);
  return {
    id: `${ownerName}.${name}#${overloadNumber}`,
    name,
    overload: overloadNumber,
    signature: normalizeWhitespace(node.getText(sourceFile)),
    typeParameters: node.typeParameters?.map((item) => item.getText(sourceFile)) ?? [],
    parameters: node.parameters.map((parameter) => parameterRecord(sourceFile, parameter)),
    returnType,
    returnsPromise: /^(?:globalThis\.)?Promise(?:<|$)/.test(normalizeWhitespace(returnType)),
    line: lineOf(sourceFile, node),
    ...modifiersOf(node),
    ...docs,
  };
}

function propertyRecord(sourceFile, node) {
  const docs = getJsDoc(node);
  return {
    name: nameOf(node, sourceFile),
    type: node.type?.getText(sourceFile) ?? 'any',
    optional: Boolean(node.questionToken),
    readonly: Boolean(node.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ReadonlyKeyword)),
    static: Boolean(node.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.StaticKeyword)),
    line: lineOf(sourceFile, node),
    ...modifiersOf(node),
    ...docs,
  };
}

function referencePathFor(kind, name) {
  const folderByKind = {
    class: 'classes',
    enum: 'enums',
    interface: 'interfaces',
    type: 'types',
  };
  const candidate = path.join(
    MATERIALS_ROOT,
    'sources',
    'core',
    'easyeda-api-skill',
    'references',
    folderByKind[kind],
    `${name}.md`,
  );
  return fs.existsSync(candidate) ? relativeToMaterials(candidate) : null;
}

function declarationBase(sourceFile, node, kind, canonicalPath) {
  const name = node.name.text;
  return {
    name,
    kind,
    line: lineOf(sourceFile, node),
    sourcePath: canonicalPath,
    documentationPath: referencePathFor(kind, name),
    ...getJsDoc(node),
  };
}

function parseClassOrInterface(sourceFile, node, kind, canonicalPath) {
  const base = declarationBase(sourceFile, node, kind, canonicalPath);
  const methodOverloads = new Map();
  const methods = [];
  const properties = [];
  const constructors = [];
  const accessors = [];

  for (const member of node.members) {
    if (ts.isMethodDeclaration(member) || ts.isMethodSignature(member)) {
      const memberName = nameOf(member, sourceFile);
      const overload = (methodOverloads.get(memberName) ?? 0) + 1;
      methodOverloads.set(memberName, overload);
      methods.push(callableRecord(sourceFile, member, base.name, overload));
    } else if (ts.isPropertyDeclaration(member) || ts.isPropertySignature(member)) {
      properties.push(propertyRecord(sourceFile, member));
    } else if (ts.isConstructorDeclaration(member)) {
      constructors.push({
        signature: normalizeWhitespace(member.getText(sourceFile)),
        parameters: member.parameters.map((parameter) => parameterRecord(sourceFile, parameter)),
        line: lineOf(sourceFile, member),
        ...modifiersOf(member),
        ...getJsDoc(member),
      });
    } else if (ts.isGetAccessorDeclaration(member) || ts.isSetAccessorDeclaration(member)) {
      accessors.push({
        kind: ts.isGetAccessorDeclaration(member) ? 'get' : 'set',
        name: nameOf(member, sourceFile),
        signature: normalizeWhitespace(member.getText(sourceFile)),
        line: lineOf(sourceFile, member),
        ...modifiersOf(member),
        ...getJsDoc(member),
      });
    }
  }

  return {
    ...base,
    heritage: node.heritageClauses?.map((clause) => normalizeWhitespace(clause.getText(sourceFile))) ?? [],
    methods,
    properties,
    constructors,
    accessors,
  };
}

function parseEnum(sourceFile, node, canonicalPath) {
  return {
    ...declarationBase(sourceFile, node, 'enum', canonicalPath),
    members: node.members.map((member) => ({
      name: member.name.getText(sourceFile),
      value: member.initializer?.getText(sourceFile) ?? null,
      line: lineOf(sourceFile, member),
      ...getJsDoc(member),
    })),
  };
}

function parseTypeAlias(sourceFile, node, canonicalPath) {
  return {
    ...declarationBase(sourceFile, node, 'type', canonicalPath),
    typeParameters: node.typeParameters?.map((item) => item.getText(sourceFile)) ?? [],
    target: node.type.getText(sourceFile),
  };
}

function collectDeclarations(sourceFile, canonicalPath) {
  const classes = {};
  const enums = {};
  const interfaces = {};
  const types = {};

  function visit(node) {
    if (ts.isClassDeclaration(node) && node.name) {
      classes[node.name.text] = parseClassOrInterface(sourceFile, node, 'class', canonicalPath);
      return;
    }
    if (ts.isEnumDeclaration(node)) {
      enums[node.name.text] = parseEnum(sourceFile, node, canonicalPath);
      return;
    }
    if (ts.isInterfaceDeclaration(node)) {
      interfaces[node.name.text] = parseClassOrInterface(sourceFile, node, 'interface', canonicalPath);
      return;
    }
    if (ts.isTypeAliasDeclaration(node)) {
      types[node.name.text] = parseTypeAlias(sourceFile, node, canonicalPath);
      return;
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return { classes, enums, interfaces, types };
}

function buildRuntimeModules(classes) {
  const runtimeModules = {};
  const edaClass = classes.EDA;
  if (!edaClass) throw new Error('Canonical declaration does not contain class EDA.');
  for (const property of edaClass.properties) {
    if (classes[property.type]) runtimeModules[property.name] = property.type;
  }
  return runtimeModules;
}

function domainOf(name) {
  const separator = name.indexOf('_');
  return separator === -1 ? name : name.slice(0, separator);
}

function declarationStats(declarations, runtimeModules) {
  const classes = Object.values(declarations.classes);
  const interfaces = Object.values(declarations.interfaces);
  const methodRecords = classes.flatMap((item) => item.methods);
  const interfaceMethodRecords = interfaces.flatMap((item) => item.methods);
  const domains = {};
  for (const item of classes) {
    const domain = domainOf(item.name);
    domains[domain] ??= { classes: 0, methods: 0, runtimeModules: 0 };
    domains[domain].classes += 1;
    domains[domain].methods += item.methods.length;
  }
  for (const className of Object.values(runtimeModules)) {
    const domain = domainOf(className);
    domains[domain] ??= { classes: 0, methods: 0, runtimeModules: 0 };
    domains[domain].runtimeModules += 1;
  }
  return {
    declarations: {
      class: classes.length,
      enum: Object.keys(declarations.enums).length,
      interface: interfaces.length,
      type: Object.keys(declarations.types).length,
    },
    classMethods: methodRecords.length,
    publicOrBetaClassMethods: methodRecords.filter((item) => ['public', 'beta'].includes(item.releaseTag)).length,
    promiseReturningClassMethods: methodRecords.filter((item) => item.returnsPromise).length,
    interfaceMethods: interfaceMethodRecords.length,
    runtimeModules: Object.keys(runtimeModules).length,
    documentedDeclarations: [...classes, ...Object.values(declarations.enums), ...interfaces, ...Object.values(declarations.types)]
      .filter((item) => item.documentationPath).length,
    domains,
  };
}

function buildApiManifest(lock) {
  const declarationPath = path.join(MATERIALS_ROOT, ...lock.typePackage.declarationPath.split('/'));
  const declarationText = fs.readFileSync(declarationPath, 'utf8');
  const actualHash = sha256Text(declarationText);
  if (actualHash !== lock.typePackage.declarationSha256) {
    throw new Error(`Declaration SHA-256 mismatch: expected ${lock.typePackage.declarationSha256}, got ${actualHash}`);
  }
  const sourceFile = ts.createSourceFile(
    declarationPath,
    declarationText,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  );
  const declarations = collectDeclarations(sourceFile, lock.typePackage.declarationPath);
  const runtimeModules = buildRuntimeModules(declarations.classes);
  const stats = declarationStats(declarations, runtimeModules);

  for (const [kind, expected] of Object.entries(lock.typePackage.declarationCounts)) {
    if (stats.declarations[kind] !== expected) {
      throw new Error(`Declaration count mismatch for ${kind}: expected ${expected}, got ${stats.declarations[kind]}`);
    }
  }

  return {
    schemaVersion: 'easyeda.api-manifest.v1',
    generatedAt: lock.generatedAt,
    sourceLockPath: 'manifests/sources.lock.json',
    canonicalSource: {
      package: lock.typePackage.name,
      version: lock.typePackage.version,
      declarationPath: lock.typePackage.declarationPath,
      declarationSha256: actualHash,
      trustLevel: lock.typePackage.trustLevel,
    },
    referenceSource: {
      repository: 'easyeda-api-skill',
      version: lock.skillComparison.officialSnapshotVersion,
      commit: lock.repositories.find((repo) => repo.name === 'easyeda-api-skill')?.commit ?? null,
      path: 'sources/core/easyeda-api-skill/references',
      role: 'documentation-link-only',
    },
    stats,
    runtimeModules,
    declarations,
  };
}

function walkFiles(root) {
  const files = [];
  const stack = [root];
  while (stack.length) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      if (entry.isDirectory() && IGNORED_DIRECTORY_NAMES.has(entry.name)) continue;
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) stack.push(fullPath);
      else if (entry.isFile()) files.push(fullPath);
    }
  }
  return files.sort((a, b) => a.localeCompare(b, 'en'));
}

function lineNumberAt(text, offset) {
  let line = 1;
  for (let index = 0; index < offset; index += 1) {
    if (text.charCodeAt(index) === 10) line += 1;
  }
  return line;
}

function lineSnippetAt(text, offset) {
  const start = text.lastIndexOf('\n', offset - 1) + 1;
  const rawEnd = text.indexOf('\n', offset);
  const end = rawEnd === -1 ? text.length : rawEnd;
  const snippet = normalizeWhitespace(text.slice(start, end));
  return snippet.length <= 240 ? snippet : `${snippet.slice(0, 237)}...`;
}

function methodNamesByClass(apiManifest) {
  const result = {};
  for (const [className, declaration] of Object.entries(apiManifest.declarations.classes)) {
    result[className] = new Set(declaration.methods.map((method) => method.name));
  }
  return result;
}

function scanRepository(repo, apiManifest) {
  const repoPath = path.join(MATERIALS_ROOT, ...repo.localPath.split('/'));
  const methodSets = methodNamesByClass(apiManifest);
  const occurrences = [];
  const callPattern = /\beda\s*\??\.\s*([A-Za-z_$][\w$]*)\s*\??\.\s*([A-Za-z_$][\w$]*)\s*\(/g;

  for (const filePath of walkFiles(repoPath)) {
    const extension = path.extname(filePath).toLowerCase();
    const kind = DOCUMENTATION_EXTENSIONS.has(extension)
      ? 'documentation'
      : CODE_EXTENSIONS.has(extension)
        ? 'code'
        : null;
    if (!kind || filePath.toLowerCase().endsWith('.d.ts')) continue;
    let text;
    try {
      text = fs.readFileSync(filePath, 'utf8');
    } catch {
      continue;
    }
    callPattern.lastIndex = 0;
    for (let match = callPattern.exec(text); match; match = callPattern.exec(text)) {
      const runtimeModule = match[1];
      const method = match[2];
      const className = apiManifest.runtimeModules[runtimeModule] ?? null;
      const methodExists = className ? methodSets[className]?.has(method) ?? false : false;
      const mappingStatus = !className ? 'unknown-runtime-module' : methodExists ? 'mapped' : 'unknown-method';
      occurrences.push({
        call: `eda.${runtimeModule}.${method}`,
        runtimeModule,
        method,
        class: className,
        canonicalMethod: methodExists ? `${className}.${method}` : null,
        mappingStatus,
        repository: repo.name,
        repositoryGroup: repo.group,
        commit: repo.commit,
        path: relativeToMaterials(filePath),
        line: lineNumberAt(text, match.index),
        kind,
        snippet: lineSnippetAt(text, match.index),
      });
    }
  }
  return occurrences;
}

function buildExampleIndex(lock, apiManifest) {
  const calls = {};
  const repositoryStats = {};
  const allOccurrences = lock.repositories.flatMap((repo) => scanRepository(repo, apiManifest));
  allOccurrences.sort((a, b) =>
    a.call.localeCompare(b.call, 'en')
      || a.repository.localeCompare(b.repository, 'en')
      || a.path.localeCompare(b.path, 'en')
      || a.line - b.line,
  );

  for (const repo of lock.repositories) {
    repositoryStats[repo.name] = {
      group: repo.group,
      commit: repo.commit,
      distinctCalls: 0,
      occurrences: 0,
      codeOccurrences: 0,
      documentationOccurrences: 0,
    };
  }

  for (const occurrence of allOccurrences) {
    calls[occurrence.call] ??= {
      runtimeModule: occurrence.runtimeModule,
      method: occurrence.method,
      class: occurrence.class,
      canonicalMethod: occurrence.canonicalMethod,
      mappingStatus: occurrence.mappingStatus,
      occurrences: [],
    };
    calls[occurrence.call].occurrences.push({
      repository: occurrence.repository,
      repositoryGroup: occurrence.repositoryGroup,
      commit: occurrence.commit,
      path: occurrence.path,
      line: occurrence.line,
      kind: occurrence.kind,
      snippet: occurrence.snippet,
    });
    const repoStat = repositoryStats[occurrence.repository];
    repoStat.occurrences += 1;
    repoStat[occurrence.kind === 'code' ? 'codeOccurrences' : 'documentationOccurrences'] += 1;
  }

  for (const [repoName, repoStat] of Object.entries(repositoryStats)) {
    repoStat.distinctCalls = Object.values(calls).filter((item) =>
      item.occurrences.some((occurrence) => occurrence.repository === repoName),
    ).length;
  }

  const callValues = Object.values(calls);
  const mappedCalls = callValues.filter((item) => item.mappingStatus === 'mapped');
  const mappedMethods = new Set(mappedCalls.map((item) => item.canonicalMethod));
  const allRuntimeMethods = Object.values(apiManifest.runtimeModules).reduce(
    (count, className) => count + apiManifest.declarations.classes[className].methods.length,
    0,
  );

  return {
    schemaVersion: 'easyeda.api-example-index.v1',
    generatedAt: lock.generatedAt,
    sourceLockPath: 'manifests/sources.lock.json',
    apiManifestPath: 'manifests/api-manifest.json',
    scope: {
      repositories: lock.repositories.length,
      repositoryGroups: [...new Set(lock.repositories.map((repo) => repo.group))].sort(),
      includedExtensions: [...CODE_EXTENSIONS, ...DOCUMENTATION_EXTENSIONS].sort(),
      excludedDirectories: [...IGNORED_DIRECTORY_NAMES].sort(),
      note: 'Only direct eda.<runtimeModule>.<method>(...) calls are indexed; aliases and computed property access are intentionally excluded.',
    },
    stats: {
      distinctCalls: callValues.length,
      occurrences: allOccurrences.length,
      codeOccurrences: allOccurrences.filter((item) => item.kind === 'code').length,
      documentationOccurrences: allOccurrences.filter((item) => item.kind === 'documentation').length,
      mappedCalls: mappedCalls.length,
      unmappedCalls: callValues.length - mappedCalls.length,
      mappedCanonicalMethods: mappedMethods.size,
      runtimeClassMethods: allRuntimeMethods,
      runtimeMethodExampleCoverage: allRuntimeMethods === 0 ? 0 : Number((mappedMethods.size / allRuntimeMethods).toFixed(6)),
    },
    repositoryStats,
    unmapped: Object.fromEntries(
      Object.entries(calls).filter(([, item]) => item.mappingStatus !== 'mapped'),
    ),
    calls,
  };
}

function markdownTable(rows) {
  if (!rows.length) return '_无_';
  const headers = Object.keys(rows[0]);
  const header = `| ${headers.join(' | ')} |`;
  const divider = `| ${headers.map(() => '---').join(' | ')} |`;
  const body = rows.map((row) => `| ${headers.map((key) => String(row[key]).replace(/\|/g, '\\|')).join(' | ')} |`);
  return [header, divider, ...body].join('\n');
}

function buildSummary(lock, apiManifest, exampleIndex) {
  const domainRows = Object.entries(apiManifest.stats.domains)
    .sort(([a], [b]) => a.localeCompare(b, 'en'))
    .map(([domain, stats]) => ({
      域: domain,
      类: stats.classes,
      方法: stats.methods,
      运行时模块: stats.runtimeModules,
    }));
  const repositoryRows = Object.entries(exampleIndex.repositoryStats)
    .sort(([, a], [, b]) => b.occurrences - a.occurrences)
    .map(([name, stats]) => ({
      仓库: name,
      分组: stats.group,
      不同调用: stats.distinctCalls,
      代码命中: stats.codeOccurrences,
      文档命中: stats.documentationOccurrences,
    }));
  const popularRows = Object.entries(exampleIndex.calls)
    .sort(([, a], [, b]) => b.occurrences.length - a.occurrences.length)
    .slice(0, 20)
    .map(([call, item]) => ({
      调用: `\`${call}()\``,
      类方法: item.canonicalMethod ? `\`${item.canonicalMethod}\`` : item.mappingStatus,
      命中: item.occurrences.length,
      仓库数: new Set(item.occurrences.map((occurrence) => occurrence.repository)).size,
    }));
  const unmappedRows = Object.entries(exampleIndex.unmapped).map(([call, item]) => ({
    调用: `\`${call}()\``,
    状态: item.mappingStatus,
    命中: item.occurrences.length,
    首个位置: `${item.occurrences[0].path}:${item.occurrences[0].line}`,
  }));

  return `# EasyEDA 官方 API 机器索引摘要

本页由 \`materials/scripts/api-indexer/build-api-indexes.mjs\` 从固定官方快照生成。它不连接 EasyEDA，不执行任何工程读写。

## 固定输入

- API 签名：\`${lock.typePackage.name}\` ${lock.typePackage.version}，声明 SHA-256 \`${lock.typePackage.declarationSha256}\`。
- 官方参考：\`easyeda-api-skill\` ${lock.skillComparison.officialSnapshotVersion}，固定提交 \`${apiManifest.referenceSource.commit}\`。
- 官方仓库：${lock.repositories.length} 个固定 Git 快照。
- 机器输出：[\`api-manifest.json\`](../manifests/api-manifest.json) 与 [\`api-example-index.json\`](../manifests/api-example-index.json)。

## API 规模

- ${apiManifest.stats.declarations.class} 个类、${apiManifest.stats.declarations.enum} 个枚举、${apiManifest.stats.declarations.interface} 个接口、${apiManifest.stats.declarations.type} 个类型别名。
- ${apiManifest.stats.classMethods} 个类方法，其中 ${apiManifest.stats.promiseReturningClassMethods} 个直接返回 \`Promise\`。
- \`eda\` 暴露 ${apiManifest.stats.runtimeModules} 个运行时模块。
- ${apiManifest.stats.documentedDeclarations} 个声明能链接到同一固定版本的官方参考 Markdown。

${markdownTable(domainRows)}

## 官方调用样本

- 不同直接调用：${exampleIndex.stats.distinctCalls}。
- 总命中：${exampleIndex.stats.occurrences}（代码 ${exampleIndex.stats.codeOccurrences}，文档 ${exampleIndex.stats.documentationOccurrences}）。
- 已映射调用：${exampleIndex.stats.mappedCalls}；未映射调用：${exampleIndex.stats.unmappedCalls}。
- 覆盖运行时类方法：${exampleIndex.stats.mappedCanonicalMethods}/${exampleIndex.stats.runtimeClassMethods}（${(exampleIndex.stats.runtimeMethodExampleCoverage * 100).toFixed(2)}%）。

### 仓库覆盖

${markdownTable(repositoryRows)}

### 高频调用

${markdownTable(popularRows)}

### 未映射调用

未映射并不自动等于错误：它可能是固定示例使用了比当前类型包更新、已移除或动态注入的接口。进入融合 Skill 前必须逐项审查，不能猜签名。

${markdownTable(unmappedRows)}

## 消费约定

1. 生成代码前先查 \`api-manifest.json\` 的确切签名、返回值、枚举和发布标签。
2. 查用法时以 \`api-example-index.json\` 的固定提交、文件和行号回到官方上下文。
3. \`mappingStatus !== "mapped"\` 的调用不得自动生成。
4. 示例覆盖率只表示本地官方快照中存在直接调用，不代表 API 可在任意文档状态、权限或版本下执行。
`;
}

export function buildAll() {
  const lock = readJson(LOCK_PATH);
  const apiManifest = buildApiManifest(lock);
  const exampleIndex = buildExampleIndex(lock, apiManifest);
  writeJson(API_MANIFEST_PATH, apiManifest);
  writeJson(EXAMPLE_INDEX_PATH, exampleIndex);
  fs.writeFileSync(SUMMARY_PATH, buildSummary(lock, apiManifest, exampleIndex), 'utf8');
  return { lock, apiManifest, exampleIndex };
}

if (path.resolve(process.argv[1] ?? '') === path.resolve(fileURLToPath(import.meta.url))) {
  const { apiManifest, exampleIndex } = buildAll();
  process.stdout.write(`${JSON.stringify({
    apiManifest: relativeToMaterials(API_MANIFEST_PATH),
    exampleIndex: relativeToMaterials(EXAMPLE_INDEX_PATH),
    summary: relativeToMaterials(SUMMARY_PATH),
    declarations: apiManifest.stats.declarations,
    runtimeModules: apiManifest.stats.runtimeModules,
    distinctExampleCalls: exampleIndex.stats.distinctCalls,
    mappedExampleCalls: exampleIndex.stats.mappedCalls,
    unmappedExampleCalls: exampleIndex.stats.unmappedCalls,
  }, null, 2)}\n`);
}
