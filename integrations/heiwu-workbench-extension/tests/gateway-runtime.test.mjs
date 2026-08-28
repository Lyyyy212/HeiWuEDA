import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import test from 'node:test';
import vm from 'node:vm';
import JSZip from 'jszip';

const integrationRoot = path.resolve(import.meta.dirname, '..');
const bundleSource = fs.readFileSync(path.join(integrationRoot, 'dist', 'index.js'), 'utf8');
const workbenchHtml = fs.readFileSync(path.join(integrationRoot, 'iframe', 'workbench.html'), 'utf8');
const extensionDetails = fs.readFileSync(path.join(integrationRoot, 'README.md'), 'utf8');
const extensionConfig = JSON.parse(fs.readFileSync(path.join(integrationRoot, 'extension.json'), 'utf8'));
const packagedExtensionPath = path.join(
	integrationRoot,
	'build',
	'dist',
	`hardware-workbench_v${extensionConfig.version}.eext`,
);
const autoConnectKey = 'hardwareWorkbench.gateway.autoConnect';
const statusTopic = 'hardware-workbench-gateway-status';

function wait(milliseconds) {
	return new Promise(resolve => setTimeout(resolve, milliseconds));
}

function createHarness(initialStorage = {}) {
	const sockets = new Map();
	const sent = [];
	const storage = new Map(Object.entries(initialStorage));
	const services = new Map();
	const frames = new Map();
	const staleFrameIds = new Set();
	const frameActions = [];
	const toasts = [];
	const dialogs = [];
	const openedUrls = [];
	const currentProject = {
		friendlyName: 'Learning Board',
		itemType: 'PROJECT',
		name: 'Learning Board',
		uuid: 'project-1',
	};
	const currentDocument = {
		documentType: 'SCHEMATIC_PAGE',
		parentProjectUuid: 'project-1',
		tabId: 'tab-1',
		uuid: 'page-1',
	};

	const eda = {
		dmt_Project: {
			getCurrentProjectInfo() {
				return Promise.resolve({ ...currentProject });
			},
		},
		dmt_Schematic: {
			getAllSchematicPagesInfo() {
				return Promise.resolve([{
					itemType: 'SCHEMATIC_PAGE',
					name: 'Main',
					parentSchematicUuid: 'schematic-1',
					uuid: 'page-1',
				}]);
			},
			getAllSchematicsInfo() {
				return Promise.resolve([{
					itemType: 'SCHEMATIC',
					name: 'Main Schematic',
					parentProjectUuid: 'project-1',
					uuid: 'schematic-1',
				}]);
			},
		},
		dmt_SelectControl: {
			getCurrentDocumentInfo() {
				return Promise.resolve({ ...currentDocument });
			},
		},
		sys_Dialog: {
			showInformationMessage(message, title) {
				dialogs.push({ message, title });
			},
		},
		sys_Message: {
			showToastMessage(message) {
				toasts.push(message);
			},
		},
		sys_IFrame: {
			closeIFrame(id) {
				frameActions.push({ action: 'close', id });
				if (id) {
					frames.delete(id);
					staleFrameIds.delete(id);
				}
				else {
					frames.clear();
					staleFrameIds.clear();
				}
				return Promise.resolve(true);
			},
			openIFrame(htmlFileName, width, height, id, props) {
				frameActions.push({ action: 'open', height, htmlFileName, id, props, width });
				staleFrameIds.delete(id);
				frames.set(id, { height, htmlFileName, props, width });
				return Promise.resolve(true);
			},
			showIFrame(id) {
				frameActions.push({ action: 'show', id });
				return Promise.resolve(frames.has(id) || staleFrameIds.has(id));
			},
		},
		sys_MessageBus: {
			rpcCall(topic, request) {
				const service = services.get(topic);
				if (!service)
					return Promise.reject(new Error(`Missing RPC service: ${topic}`));
				return Promise.resolve(service(request));
			},
			rpcService(topic, handler) {
				services.set(topic, handler);
			},
		},
		sys_Storage: {
			getExtensionUserConfig(key) {
				return storage.get(key);
			},
			setExtensionUserConfig(key, value) {
				storage.set(key, value);
				return Promise.resolve(true);
			},
		},
		sys_WebSocket: {
			close(socketId) {
				sockets.delete(socketId);
			},
			register(socketId, url, onMessage, onConnected) {
				sockets.set(socketId, { url, onMessage, onConnected });
				onConnected();
			},
			send(socketId, payload) {
				if (!sockets.has(socketId))
					throw new Error(`Socket is not registered: ${socketId}`);
				sent.push({ socketId, payload: JSON.parse(payload) });
			},
		},
		sys_Window: {
			open(url) {
				openedUrls.push(url);
			},
		},
	};

	const context = vm.createContext({
		Date,
		JSON,
		Math,
		Promise,
		clearInterval,
		clearTimeout,
		console,
		crypto: { randomUUID },
		eda,
		process,
		setInterval,
		setTimeout,
	});
	vm.runInContext(bundleSource, context);
	async function closeFrameFromUi(id) {
		const frame = frames.get(id);
		if (!frame)
			return false;
		const allowed = await frame.props.onBeforeCloseCallFn?.();
		if (allowed === false)
			return false;
		await frame.props.buttonCallbackFn?.('close');
		frames.delete(id);
		// Reproduce the fixed-ID residue observed after the native close button.
		staleFrameIds.add(id);
		frameActions.push({ action: 'ui-close', id });
		return true;
	}
	return {
		api: context.edaEsbuildExportName,
		closeFrameFromUi,
		dialogs,
		frameActions,
		frames,
		openedUrls,
		sent,
		services,
		sockets,
		storage,
		toasts,
	};
}

function socketForPort(harness, port) {
	return [...harness.sockets.entries()].find(([, socket]) => socket.url.includes(`:${port}/eda`));
}

async function advanceSequentialProbeToPort(harness, targetPort) {
	for (let port = 49620; port < targetPort; port++) {
		const currentProbe = socketForPort(harness, port);
		assert.ok(currentProbe, `expected an active sequential probe for port ${port}`);
		const [, socket] = currentProbe;
		await socket.onMessage({
			data: JSON.stringify({
				type: 'handshake',
				service: 'easyeda-bridge',
			}),
		});
		await wait(0);
	}
}

async function acknowledgeRegistration(harness, socketId, socket) {
	await wait(20);
	const registration = harness.sent.find(item => item.socketId === socketId && item.payload.type === 'register');
	assert.ok(registration, 'extension should send a dedicated registration request');
	await socket.onMessage({
		data: JSON.stringify({
			type: 'registered',
			gatewayId: 'lyyyy.hardware-workbench',
			productId: 'hardware-workbench',
			protocolVersion: 2,
			windowId: registration.payload.windowId,
		}),
	});
	await wait(20);
	return registration;
}

test('connects through the project-dedicated handshake after sequentially rejecting other ports', async () => {
	const harness = createHarness();
	harness.api.activate();
	assert.equal(harness.sockets.size, 1);
	assert.ok(socketForPort(harness, 49620));
	await advanceSequentialProbeToPort(harness, 49624);

	const [socketId, socket] = socketForPort(harness, 49624);
	await socket.onMessage({
		data: JSON.stringify({
			type: 'handshake',
			service: 'easyeda-bridge',
			gatewayId: 'lyyyy.hardware-workbench',
			productId: 'hardware-workbench',
			protocolVersion: 2,
			registrationNonce: 'nonce-49624',
		}),
	});
	await wait(20);
	const pendingStatus = harness.services.get(statusTopic)();
	assert.equal(pendingStatus.connected, false);
	assert.equal(pendingStatus.connecting, true);
	const registration = await acknowledgeRegistration(harness, socketId, socket);

	assert.equal(harness.sockets.size, 1);
	assert.equal(harness.sockets.has(socketId), true);
	assert.equal(registration.payload.gatewayId, 'lyyyy.hardware-workbench');
	assert.equal(registration.payload.productId, 'hardware-workbench');
	assert.equal(registration.payload.protocolVersion, 2);
	assert.equal(registration.payload.registrationNonce, 'nonce-49624');

	const status = harness.services.get(statusTopic)();
	assert.equal(status.connected, true);
	assert.equal(status.port, 49624);
	assert.equal(status.connectionMode, 'dedicated');
	harness.api.deactivate();
	assert.equal(harness.sockets.size, 0);
});

test('rejects the generic official easyeda bridge', async () => {
	const harness = createHarness();
	harness.api.activate();
	const [, socket] = socketForPort(harness, 49620);
	await socket.onMessage({
		data: JSON.stringify({
			type: 'handshake',
			service: 'easyeda-bridge',
		}),
	});

	await wait(50);
	const status = harness.services.get(statusTopic)();
	assert.equal(status.connected, false);
	assert.equal(status.port, null);
	assert.equal(status.connectionMode, 'disconnected');
	harness.api.deactivate();
});

test('dispatches only allowlisted operations carrying the dedicated bridge identity', async () => {
	const harness = createHarness();
	harness.api.activate();
	await advanceSequentialProbeToPort(harness, 49622);
	const [socketId, socket] = socketForPort(harness, 49622);
	await socket.onMessage({
		data: JSON.stringify({
			type: 'handshake',
			service: 'easyeda-bridge',
			gatewayId: 'lyyyy.hardware-workbench',
			productId: 'hardware-workbench',
			protocolVersion: 2,
			registrationNonce: 'nonce-49622',
		}),
	});
	await acknowledgeRegistration(harness, socketId, socket);

	const sentBeforeUnauthorized = harness.sent.length;
	await socket.onMessage({
		data: JSON.stringify({ type: 'operation', id: 'unauthorized', operation: 'workbench.context.read.v1' }),
	});
	await wait(10);
	assert.equal(harness.sent.length, sentBeforeUnauthorized);

	await socket.onMessage({
		data: JSON.stringify({
			type: 'operation',
			id: 'authorized',
			operation: 'workbench.context.read.v1',
			gatewayId: 'lyyyy.hardware-workbench',
			productId: 'hardware-workbench',
			protocolVersion: 2,
		}),
	});
	await wait(10);
	const result = harness.sent.find(item => item.socketId === socketId && item.payload.id === 'authorized');
	assert.equal(result.payload.type, 'result');
	assert.equal(result.payload.result.project.uuid, 'project-1');
	assert.equal(result.payload.result.document.uuid, 'page-1');

	await socket.onMessage({
		data: JSON.stringify({
			type: 'operation',
			id: 'unknown-operation',
			operation: 'workbench.design.save.v1',
			gatewayId: 'lyyyy.hardware-workbench',
			productId: 'hardware-workbench',
			protocolVersion: 2,
		}),
	});
	await wait(10);
	const rejected = harness.sent.find(item => item.socketId === socketId && item.payload.id === 'unknown-operation');
	assert.equal(rejected.payload.type, 'error');
	assert.match(rejected.payload.error, /not allowed/);
	harness.api.deactivate();
});

test('binds the schematic index read to the expected project and document', async () => {
	const harness = createHarness();
	harness.api.activate();
	await advanceSequentialProbeToPort(harness, 49623);
	const [socketId, socket] = socketForPort(harness, 49623);
	await socket.onMessage({
		data: JSON.stringify({
			type: 'handshake',
			service: 'easyeda-bridge',
			gatewayId: 'lyyyy.hardware-workbench',
			productId: 'hardware-workbench',
			protocolVersion: 2,
			registrationNonce: 'nonce-49623',
		}),
	});
	await acknowledgeRegistration(harness, socketId, socket);

	await socket.onMessage({
		data: JSON.stringify({
			type: 'operation',
			id: 'bound-index',
			operation: 'workbench.schematic.index.read.v1',
			args: { expectedProjectUuid: 'project-1', expectedDocumentUuid: 'page-1' },
			gatewayId: 'lyyyy.hardware-workbench',
			productId: 'hardware-workbench',
			protocolVersion: 2,
		}),
	});
	await wait(10);
	const result = harness.sent.find(item => item.socketId === socketId && item.payload.id === 'bound-index');
	assert.equal(result.payload.type, 'result');
	assert.equal(result.payload.result.schematics[0].uuid, 'schematic-1');
	assert.equal(result.payload.result.pages[0].uuid, 'page-1');

	await socket.onMessage({
		data: JSON.stringify({
			type: 'operation',
			id: 'wrong-project',
			operation: 'workbench.schematic.index.read.v1',
			args: { expectedProjectUuid: 'project-2', expectedDocumentUuid: 'page-1' },
			gatewayId: 'lyyyy.hardware-workbench',
			productId: 'hardware-workbench',
			protocolVersion: 2,
		}),
	});
	await wait(10);
	const rejected = harness.sent.find(item => item.socketId === socketId && item.payload.id === 'wrong-project');
	assert.equal(rejected.payload.type, 'error');
	assert.match(rejected.payload.error, /expectedProjectUuid/);
	harness.api.deactivate();
});

test('activation recovers a legacy disabled auto-connect setting', async () => {
	const harness = createHarness({ [autoConnectKey]: false });
	harness.api.activate();
	assert.equal(harness.storage.get(autoConnectKey), true);
	assert.equal(harness.sockets.size, 1);
	harness.api.deactivate();
});

test('opening the workbench re-enables a connection stopped in the current session', async () => {
	const harness = createHarness();
	harness.api.activate();

	await harness.api.toggleAutoConnect();
	assert.equal(harness.storage.get(autoConnectKey), false);
	assert.equal(harness.sockets.size, 0);

	await harness.api.openWorkbenchWindow();
	assert.equal(harness.storage.get(autoConnectKey), true);
	assert.equal(harness.sockets.size, 1);
	harness.api.deactivate();
});

test('opens one reusable Heiwu Workbench feature window with the product name', async () => {
	const harness = createHarness({ [autoConnectKey]: false });
	harness.api.activate();

	await harness.api.openWorkbenchWindow();
	await harness.api.openWorkbenchWindow();

	const openActions = harness.frameActions.filter(item => item.action === 'open');
	assert.equal(openActions.length, 1);
	assert.equal(openActions[0].htmlFileName, '/iframe/workbench.html');
	assert.equal(openActions[0].id, 'heiwu-workbench-window');
	assert.equal(openActions[0].width, 420);
	assert.equal(openActions[0].height, 520);
	assert.equal(openActions[0].props.title, '黑五EDA');
	assert.equal(openActions[0].props.minimizeButton, true);
	assert.equal(openActions[0].props.maximizeButton, true);
	assert.equal(typeof openActions[0].props.onBeforeCloseCallFn, 'function');
	assert.equal(typeof openActions[0].props.buttonCallbackFn, 'function');
	harness.api.deactivate();
});

test('reopens the workbench after the native close button leaves a stale fixed ID', async () => {
	const harness = createHarness({ [autoConnectKey]: false });
	harness.api.activate();

	await harness.api.openWorkbenchWindow();
	assert.equal(await harness.closeFrameFromUi('heiwu-workbench-window'), true);
	assert.equal(harness.frames.has('heiwu-workbench-window'), false);

	await harness.api.openWorkbenchWindow();

	const openActions = harness.frameActions.filter(item => item.action === 'open');
	assert.equal(openActions.length, 2);
	assert.equal(harness.frames.has('heiwu-workbench-window'), true);
	assert.equal(harness.dialogs.length, 0);
	harness.api.deactivate();
});

test('workbench iframe restores the compact status dashboard and uses the injected eda API', () => {
	assert.match(workbenchHtml, /<title>黑五EDA<\/title>/);
	assert.match(workbenchHtml, /<h1>黑五EDA<\/h1>/);
	assert.match(workbenchHtml, /<img class="brand-mark" src="\.\.\/images\/logo\.png" alt="黑五EDA 五叶草头像" \/>/);
	assert.doesNotMatch(workbenchHtml, /<div class="brand-mark"[^>]*>五<\/div>/);
	assert.match(workbenchHtml, /当前工程/);
	assert.match(workbenchHtml, /专属 Bridge/);
	assert.match(workbenchHtml, /自动连接/);
	assert.match(workbenchHtml, /访问策略/);
	assert.match(workbenchHtml, /刷新状态/);
	assert.match(workbenchHtml, /重新连接专属网关/);
	assert.match(workbenchHtml, /eda\.dmt_Project\.getCurrentProjectInfo\(\)/);
	assert.match(workbenchHtml, /eda\.sys_MessageBus\.rpcCall\(STATUS_TOPIC/);
	assert.doesNotMatch(workbenchHtml, /window\.parent\.eda/);
	assert.doesNotMatch(workbenchHtml, /heiwu-workbench-two-core-flows|学习电路，设计电路/);
});

test('extension-manager details focus on the two product flows with local visuals', () => {
	assert.match(extensionDetails, /^# 黑五EDA/m);
	assert.match(extensionDetails, /学习画板：把原理图变成可追溯的学习材料/);
	assert.match(extensionDetails, /原理图全流程：把设计推进变成可审查、可回读、可验收的工程链/);
	assert.match(extensionDetails, /https:\/\/github\.com\/Lyyyy212\/HeiWuEDA/);
	assert.match(extensionDetails, /assets\/generated\/heiwu-workbench-two-core-flows\.png/);
	assert.match(extensionDetails, /assets\/generated\/learning-workflow\.svg/);
	assert.match(extensionDetails, /assets\/generated\/frame-question-model\.svg/);
	assert.match(extensionDetails, /assets\/generated\/schematic-lifecycle-concept\.png/);
	assert.doesNotMatch(extensionDetails, /网关|gateway|bridge|websocket|4962/i);
	assert.doesNotMatch(extensionDetails, /图片来源|录屏|截帧|安全裁切|Image 2 生成/);

	const localImages = [...extensionDetails.matchAll(/!\[[^\]]*\]\(([^)]+)\)/g)]
		.map(match => match[1]);
	assert.equal(localImages.length, 4);
	for (const localImage of localImages) {
		assert.equal(fs.existsSync(path.join(integrationRoot, localImage)), true, localImage);
	}
});

test('manifest exposes only the Heiwu Workbench feature page and GitHub entry', () => {
	assert.equal(extensionConfig.name, 'hardware-workbench');
	assert.equal(extensionConfig.uuid, '647e863e3bd34060949c51f22d52de05');
	assert.equal(extensionConfig.displayName, '黑五EDA');
	assert.equal(extensionConfig.images.logo, './images/logo.png');
	assert.equal(extensionConfig.publisher, 'Lyyyy');
	assert.match(extensionConfig.version, /^\d+\.\d+\.\d+$/);
	for (const menus of Object.values(extensionConfig.headerMenus)) {
		assert.equal(menus[0].title, '黑五EDA');
		assert.deepEqual(
			menus[0].menuItems.map(item => item.title),
			['打开黑五EDA', 'GitHub 项目'],
		);
	}
});

test('opens the real HeiWuEDA GitHub repository through the EasyEDA window API', () => {
	const harness = createHarness({ [autoConnectKey]: false });
	harness.api.openGithubRepository();
	assert.deepEqual(harness.openedUrls, ['https://github.com/Lyyyy212/HeiWuEDA']);
	harness.api.deactivate();
});

test('package contains the workbench iframe and excludes development-only files', async () => {
	const zip = await JSZip.loadAsync(fs.readFileSync(packagedExtensionPath));
	const packagedManifest = JSON.parse(await zip.file('extension.json').async('string'));
	assert.equal(packagedManifest.name, 'hardware-workbench');
	assert.equal(packagedManifest.uuid, '647e863e3bd34060949c51f22d52de05');
	assert.equal(packagedManifest.publisher, 'Lyyyy');
	assert.equal(packagedManifest.version, extensionConfig.version);
	assert.equal(packagedManifest.images.logo, './images/logo.png');
	assert.ok(zip.file('images/logo.png'));
	assert.ok(zip.file('README.md'));
	assert.ok(zip.file('CHANGELOG.md'));
	assert.ok(zip.file('release/marketplace-identity.json'));
	assert.ok(zip.file('release/marketplace-listing.json'));
	assert.ok(zip.file('iframe/workbench.html'));
	assert.ok(zip.file('assets/generated/heiwu-workbench-two-core-flows.png'));
	assert.ok(zip.file('assets/generated/schematic-lifecycle-concept.png'));
	assert.ok(zip.file('assets/generated/learning-workflow.svg'));
	assert.ok(zip.file('assets/generated/frame-question-model.svg'));
	assert.ok(zip.file('dist/index.js'));
	assert.ok(zip.file('extension.json'));
	for (const legalPath of ['LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'LICENSES/Apache-2.0.txt']) {
		const legalFile = zip.file(legalPath);
		assert.ok(legalFile, `${legalPath} is packaged`);
		assert.doesNotMatch(await legalFile.async('string'), /\r/u, `${legalPath} uses LF line endings`);
	}
	assert.equal(zip.file(/^tmp\//).length, 0);
	assert.equal(zip.file(/^src\//).length, 0);
	assert.equal(zip.file(/^scripts\//).length, 0);
	assert.equal(zip.file(/^tests\//).length, 0);
	const bundle = await zip.file('dist/index.js').async('string');
	assert.doesNotMatch(bundle, /AsyncFunction|new\s+Function|\beval\s*\(/);
});
