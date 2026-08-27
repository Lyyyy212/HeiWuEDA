import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import test from 'node:test';
import vm from 'node:vm';

const integrationRoot = path.resolve(import.meta.dirname, '..');
const bundleSource = fs.readFileSync(path.join(integrationRoot, 'dist', 'index.js'), 'utf8');
const autoConnectKey = 'zhiyuaneda.gateway.autoConnect';
const statusTopic = 'zhiyuaneda-gateway-status';

function wait(milliseconds) {
	return new Promise(resolve => setTimeout(resolve, milliseconds));
}

function createHarness(initialStorage = {}) {
	const sockets = new Map();
	const sent = [];
	const storage = new Map(Object.entries(initialStorage));
	const services = new Map();
	const toasts = [];
	const dialogs = [];

	const eda = {
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
	return {
		api: context.edaEsbuildExportName,
		dialogs,
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

test('connects through the project-dedicated handshake and cancels losing probes', async () => {
	const harness = createHarness();
	harness.api.activate();
	assert.equal(harness.sockets.size, 10);

	const [socketId, socket] = socketForPort(harness, 49624);
	await socket.onMessage({
		data: JSON.stringify({
			type: 'handshake',
			service: 'easyeda-bridge',
			gatewayId: 'lyyyy.zhiyuaneda',
			protocolVersion: 1,
		}),
	});
	await wait(20);

	assert.equal(harness.sockets.size, 1);
	assert.equal(harness.sockets.has(socketId), true);
	const registration = harness.sent.find(item => item.payload.type === 'register');
	assert.equal(registration.payload.gatewayId, 'lyyyy.zhiyuaneda');
	assert.equal(registration.payload.productId, 'zhiyuaneda');
	assert.equal(registration.payload.protocolVersion, 1);

	const status = harness.services.get(statusTopic)();
	assert.equal(status.connected, true);
	assert.equal(status.port, 49624);
	assert.equal(status.connectionMode, 'dedicated');
	harness.api.deactivate();
	assert.equal(harness.sockets.size, 0);
});

test('retains compatibility with the official generic easyeda bridge', async () => {
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
	assert.equal(harness.services.get(statusTopic)().connected, false);
	await wait(300);
	const status = harness.services.get(statusTopic)();
	assert.equal(status.connected, true);
	assert.equal(status.port, 49620);
	assert.equal(status.connectionMode, 'compatible');
	harness.api.deactivate();
});

test('applies the auto-connect switch immediately', async () => {
	const harness = createHarness({ [autoConnectKey]: false });
	harness.api.activate();
	assert.equal(harness.sockets.size, 0);

	await harness.api.toggleAutoConnect();
	assert.equal(harness.storage.get(autoConnectKey), true);
	assert.equal(harness.sockets.size, 10);

	await harness.api.toggleAutoConnect();
	assert.equal(harness.storage.get(autoConnectKey), false);
	assert.equal(harness.sockets.size, 0);
	harness.api.deactivate();
});
