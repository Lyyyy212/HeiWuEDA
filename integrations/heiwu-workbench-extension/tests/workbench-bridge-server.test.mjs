import assert from 'node:assert/strict';
import test from 'node:test';

import { WebSocket } from 'ws';

import {
	createWorkbenchBridgeServer,
	GATEWAY_ID,
	OPERATION_IDS,
	PRODUCT_ID,
	PROTOCOL_VERSION,
} from '../scripts/workbench-bridge-server.mjs';

const identity = {
	gatewayId: GATEWAY_ID,
	productId: PRODUCT_ID,
	protocolVersion: PROTOCOL_VERSION,
};

function waitForMessage(socket) {
	return new Promise((resolve, reject) => {
		socket.once('message', raw => resolve(JSON.parse(raw.toString())));
		socket.once('error', reject);
	});
}

function waitForClose(socket) {
	return new Promise((resolve, reject) => {
		socket.once('close', (code, reason) => resolve({ code, reason: reason.toString() }));
		socket.once('error', reject);
	});
}

async function requestJson(url, options = {}) {
	const response = await fetch(url, options);
	return { status: response.status, value: await response.json() };
}

test('requires dedicated registration and forwards only allowlisted operations', async () => {
	const server = createWorkbenchBridgeServer({
		logger: { info() {}, warn() {} },
		portEnd: 0,
		portStart: 0,
		requestTimeoutMs: 1000,
	});
	await server.start();
	const baseUrl = `http://127.0.0.1:${server.port}`;

	try {
		const health = await requestJson(`${baseUrl}/health`);
		assert.equal(health.status, 200);
		assert.equal(health.value.gatewayId, GATEWAY_ID);
		assert.equal(health.value.productId, PRODUCT_ID);
		assert.equal(health.value.protocolVersion, 2);
		assert.equal(health.value.edaConnected, false);

		const operations = await requestJson(`${baseUrl}/operations`);
		assert.deepEqual(operations.value.operations, OPERATION_IDS);

		const genericSocket = new WebSocket(`ws://127.0.0.1:${server.port}/eda`);
		const genericHandshake = await waitForMessage(genericSocket);
		assert.equal(genericHandshake.gatewayId, GATEWAY_ID);
		genericSocket.send(JSON.stringify({ type: 'register', windowId: 'generic-window' }));
		const genericClose = await waitForClose(genericSocket);
		assert.equal(genericClose.code, 1008);

		const edaSocket = new WebSocket(`ws://127.0.0.1:${server.port}/eda`);
		const handshake = await waitForMessage(edaSocket);
		edaSocket.send(JSON.stringify({
			...identity,
			extensionVersion: '0.2.0',
			registrationNonce: handshake.registrationNonce,
			type: 'register',
			windowId: 'dedicated-window',
		}));
		const registered = await waitForMessage(edaSocket);
		assert.equal(registered.type, 'registered');

		const windows = await requestJson(`${baseUrl}/eda-windows`);
		assert.equal(windows.value.count, 1);
		assert.equal(windows.value.windows[0].gatewayId, GATEWAY_ID);
		assert.equal(windows.value.windows[0].productId, PRODUCT_ID);

		const legacy = await requestJson(`${baseUrl}/execute`, {
			body: JSON.stringify({ ...identity }),
			headers: { 'Content-Type': 'application/json' },
			method: 'POST',
		});
		assert.equal(legacy.status, 410);

		const unauthorized = await requestJson(`${baseUrl}/operations/execute`, {
			body: JSON.stringify({ operation: 'workbench.context.read.v1' }),
			headers: { 'Content-Type': 'application/json' },
			method: 'POST',
		});
		assert.equal(unauthorized.status, 403);

		const operationSeen = waitForMessage(edaSocket).then((message) => {
			assert.equal(message.type, 'operation');
			assert.equal(message.operation, 'workbench.context.read.v1');
			assert.equal(message.gatewayId, GATEWAY_ID);
			edaSocket.send(JSON.stringify({
				...identity,
				id: message.id,
				result: { route: 'dedicated-extension' },
				type: 'result',
			}));
		});
		const authorizedPromise = requestJson(`${baseUrl}/operations/execute`, {
			body: JSON.stringify({
				...identity,
				args: {},
				operation: 'workbench.context.read.v1',
				windowId: 'dedicated-window',
			}),
			headers: { 'Content-Type': 'application/json' },
			method: 'POST',
		});
		await operationSeen;
		const authorized = await authorizedPromise;
		assert.equal(authorized.status, 200);
		assert.deepEqual(authorized.value.result, { route: 'dedicated-extension' });
		assert.equal(authorized.value.windowId, 'dedicated-window');

		const unknown = await requestJson(`${baseUrl}/operations/execute`, {
			body: JSON.stringify({
				...identity,
				operation: 'workbench.design.save.v1',
				windowId: 'dedicated-window',
			}),
			headers: { 'Content-Type': 'application/json' },
			method: 'POST',
		});
		assert.equal(unknown.status, 400);
		assert.match(unknown.value.error, /not allowed/);

		edaSocket.close();
	}
	finally {
		await server.stop();
	}
});
