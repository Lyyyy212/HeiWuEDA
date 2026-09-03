import { Buffer } from 'node:buffer';
import { createHash, randomUUID } from 'node:crypto';
import { createServer, get as httpGet } from 'node:http';
import { createConnection } from 'node:net';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

import { WebSocketServer } from 'ws';

export const SERVICE_ID = 'easyeda-bridge';
export const GATEWAY_ID = 'lyyyy.hardware-workbench';
export const PRODUCT_ID = 'hardware-workbench';
export const PROTOCOL_VERSION = 2;
export const ACCESS_POLICY = 'dedicated-extension-required';
export const CODE_OPERATION_ID = 'workbench.official-api.execute.v1';
export const CODE_PROFILE = 'easyeda-gateway-generated.v1';
export const OPERATION_IDS = Object.freeze([
	'workbench.catalog.read.v1',
	'workbench.context.read.v1',
	CODE_OPERATION_ID,
	'workbench.schematic.index.read.v1',
]);

const operationIdSet = new Set(OPERATION_IDS);

function operationRequestError(message) {
	const error = new Error(message);
	error.statusCode = 400;
	return error;
}

const DEFAULT_PORT_START = 49620;
const DEFAULT_PORT_END = 49629;
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;
const MAX_REQUEST_BYTES = 1024 * 1024;

function hasDedicatedIdentity(value) {
	return value?.gatewayId === GATEWAY_ID
		&& value?.productId === PRODUCT_ID
		&& value?.protocolVersion === PROTOCOL_VERSION;
}

function validateOperationRequest(operation, args) {
	if (typeof operation !== 'string' || !operationIdSet.has(operation))
		throw operationRequestError(`Operation is not allowed: ${String(operation)}`);
	if (args !== undefined && (!args || typeof args !== 'object' || Array.isArray(args)))
		throw operationRequestError('Operation args must be a JSON object');
	const normalizedArgs = args ?? {};
	const allowedKeys = operation === 'workbench.schematic.index.read.v1'
		? ['expectedProjectUuid', 'expectedDocumentUuid']
		: operation === CODE_OPERATION_ID
			? ['code', 'codeSha256', 'profile']
			: [];
	const unexpectedKeys = Object.keys(normalizedArgs).filter(key => !allowedKeys.includes(key));
	if (unexpectedKeys.length > 0)
		throw operationRequestError(`Unexpected operation args: ${unexpectedKeys.join(', ')}`);
	if (operation === 'workbench.schematic.index.read.v1') {
		for (const key of allowedKeys) {
			if (typeof normalizedArgs[key] !== 'string' || !normalizedArgs[key].trim())
				throw operationRequestError(`${key} must be a non-empty string`);
		}
	}
	if (operation === CODE_OPERATION_ID) {
		if (normalizedArgs.profile !== CODE_PROFILE)
			throw operationRequestError('Unsupported generated-code profile');
		if (typeof normalizedArgs.code !== 'string' || !normalizedArgs.code.trim())
			throw operationRequestError('code must be a non-empty string');
		if (Buffer.byteLength(normalizedArgs.code, 'utf8') > 768 * 1024)
			throw operationRequestError('Generated code exceeds 768 KiB');
		if (typeof normalizedArgs.codeSha256 !== 'string' || !/^[0-9a-f]{64}$/.test(normalizedArgs.codeSha256))
			throw operationRequestError('codeSha256 must be a lowercase SHA-256 digest');
		const actualDigest = createHash('sha256').update(normalizedArgs.code, 'utf8').digest('hex');
		if (actualDigest !== normalizedArgs.codeSha256)
			throw operationRequestError('Generated-code digest mismatch');
	}
	return normalizedArgs;
}

function sendJson(response, status, value) {
	const body = Buffer.from(JSON.stringify(value), 'utf8');
	response.writeHead(status, {
		'Content-Length': body.length,
		'Content-Type': 'application/json; charset=utf-8',
		'X-Content-Type-Options': 'nosniff',
	});
	response.end(body);
}

async function readJson(request) {
	let size = 0;
	const chunks = [];
	for await (const chunk of request) {
		size += chunk.length;
		if (size > MAX_REQUEST_BYTES) {
			throw new Error(`Request body exceeds ${MAX_REQUEST_BYTES} bytes`);
		}
		chunks.push(chunk);
	}
	return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function isPortInUse(port) {
	if (port === 0)
		return Promise.resolve(false);
	return new Promise((resolve) => {
		const socket = createConnection({ host: '127.0.0.1', port });
		socket.setTimeout(300);
		socket.on('connect', () => {
			socket.destroy();
			resolve(true);
		});
		socket.on('timeout', () => {
			socket.destroy();
			resolve(false);
		});
		socket.on('error', () => {
			socket.destroy();
			resolve(false);
		});
	});
}

function isDedicatedBridgeRunning(port) {
	if (port === 0)
		return Promise.resolve(false);
	return new Promise((resolve) => {
		const request = httpGet(`http://127.0.0.1:${port}/health`, { timeout: 800 }, (response) => {
			let body = '';
			response.on('data', chunk => body += chunk);
			response.on('end', () => {
				try {
					const health = JSON.parse(body);
					resolve(health.service === SERVICE_ID && hasDedicatedIdentity(health));
				}
				catch {
					resolve(false);
				}
			});
		});
		request.on('error', () => resolve(false));
		request.on('timeout', () => {
			request.destroy();
			resolve(false);
		});
	});
}

export function createWorkbenchBridgeServer(options = {}) {
	const portStart = options.portStart ?? DEFAULT_PORT_START;
	const portEnd = options.portEnd ?? DEFAULT_PORT_END;
	const requestTimeoutMs = options.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
	const logger = options.logger ?? console;
	const edaClients = new Map();
	const pendingRequests = new Map();
	let activeWindowId = null;
	let listeningPort = null;

	function identityEnvelope() {
		return {
			accessPolicy: ACCESS_POLICY,
			gatewayId: GATEWAY_ID,
			productId: PRODUCT_ID,
			protocolVersion: PROTOCOL_VERSION,
			service: SERVICE_ID,
		};
	}

	function connectedClient(windowId) {
		const client = edaClients.get(windowId);
		return client?.ws?.readyState === 1 ? client : null;
	}

	function sendToEda(windowId, message) {
		const client = connectedClient(windowId);
		if (!client)
			throw new Error(`Dedicated EasyEDA window "${windowId}" is not connected`);
		client.ws.send(JSON.stringify({ ...message, ...identityEnvelope() }));
	}

	function executeOperationOnEda(operation, args, requestedWindowId) {
		return new Promise((resolve, reject) => {
			let validatedArgs;
			try {
				validatedArgs = validateOperationRequest(operation, args);
			}
			catch (error) {
				reject(error);
				return;
			}
			const windowId = requestedWindowId || activeWindowId;
			if (!windowId) {
				reject(new Error('Dedicated Hardware Workbench extension is not connected'));
				return;
			}
			if (!connectedClient(windowId)) {
				reject(new Error(`Dedicated EasyEDA window "${windowId}" is not connected`));
				return;
			}

			const id = randomUUID();
			const timer = setTimeout(() => {
				pendingRequests.delete(id);
				reject(new Error(`Request ${id} timed out after ${requestTimeoutMs}ms`));
			}, requestTimeoutMs);
			pendingRequests.set(id, { reject, resolve, timer, windowId });
			try {
				sendToEda(windowId, {
					args: validatedArgs,
					id,
					operation,
					timestamp: Date.now(),
					type: 'operation',
					windowId,
				});
			}
			catch (error) {
				clearTimeout(timer);
				pendingRequests.delete(id);
				reject(error);
			}
		});
	}

	function handleEdaMessage(message, windowId) {
		if (!hasDedicatedIdentity(message))
			return;
		if (message.type === 'ping') {
			sendToEda(windowId, { id: message.id, timestamp: Date.now(), type: 'pong' });
			return;
		}
		if (message.type === 'pong')
			return;
		if (message.type !== 'result' && message.type !== 'error')
			return;

		const pending = pendingRequests.get(message.id);
		if (!pending || pending.windowId !== windowId)
			return;
		clearTimeout(pending.timer);
		pendingRequests.delete(message.id);
		if (message.type === 'result')
			pending.resolve(message.result);
		else
			pending.reject(new Error(message.error || 'Unknown EasyEDA error'));
	}

	const httpServer = createServer(async (request, response) => {
		if (request.method === 'GET' && request.url === '/health') {
			sendJson(response, 200, {
				...identityEnvelope(),
				activeWindowId,
				edaConnected: edaClients.size > 0,
				edaWindowCount: edaClients.size,
				pendingRequests: pendingRequests.size,
				status: 'ok',
				timestamp: Date.now(),
			});
			return;
		}

		if (request.method === 'GET' && request.url === '/eda-windows') {
			const windows = [...edaClients.entries()].map(([windowId, client]) => ({
				active: windowId === activeWindowId,
				connected: client.ws.readyState === 1,
				extensionVersion: client.extensionVersion,
				gatewayId: client.gatewayId,
				productId: client.productId,
				protocolVersion: client.protocolVersion,
				windowId,
			}));
			sendJson(response, 200, { activeWindowId, count: windows.length, windows });
			return;
		}

		if (request.method === 'POST' && request.url === '/eda-windows/select') {
			try {
				const payload = await readJson(request);
				if (!hasDedicatedIdentity(payload)) {
					sendJson(response, 403, { error: 'Hardware Workbench client identity required' });
					return;
				}
				if (!connectedClient(payload.windowId)) {
					sendJson(response, 404, { error: `Dedicated EasyEDA window "${payload.windowId}" not found` });
					return;
				}
				activeWindowId = payload.windowId;
				sendJson(response, 200, { activeWindowId, success: true });
			}
			catch (error) {
				sendJson(response, 400, { error: error.message || 'Invalid request body' });
			}
			return;
		}

		if (request.method === 'GET' && request.url === '/operations') {
			sendJson(response, 200, { operations: OPERATION_IDS, protocolVersion: PROTOCOL_VERSION });
			return;
		}

		if (request.method === 'POST' && request.url === '/execute') {
			sendJson(response, 410, {
				error: 'Arbitrary code execution is disabled; use /operations/execute',
				success: false,
			});
			return;
		}

		if (request.method === 'POST' && request.url === '/operations/execute') {
			try {
				const payload = await readJson(request);
				if (!hasDedicatedIdentity(payload)) {
					sendJson(response, 403, { error: 'Hardware Workbench client identity required', success: false });
					return;
				}
				const result = await executeOperationOnEda(payload.operation, payload.args, payload.windowId);
				sendJson(response, 200, {
					result,
					success: true,
					windowId: payload.windowId || activeWindowId,
				});
			}
			catch (error) {
				const status = error.statusCode ?? (error.message?.includes('not connected') ? 503 : 500);
				sendJson(response, status, { error: error.message, success: false });
			}
			return;
		}

		sendJson(response, 404, { error: 'Not found' });
	});

	const webSocketServer = new WebSocketServer({ server: httpServer });
	webSocketServer.on('connection', (socket, request) => {
		const clientType = request.url === '/eda' ? 'eda' : request.url === '/agent' ? 'agent' : null;
		if (!clientType) {
			socket.close(1008, 'Unsupported endpoint');
			return;
		}
		const registrationNonce = randomUUID();
		socket.send(JSON.stringify({
			...identityEnvelope(),
			clientType,
			registrationNonce: clientType === 'eda' ? registrationNonce : undefined,
			timestamp: Date.now(),
			type: 'handshake',
		}));

		if (clientType === 'eda') {
			let registeredWindowId = null;
			socket.on('message', (raw) => {
				try {
					const message = JSON.parse(raw.toString());
					if (!registeredWindowId) {
						const registrationValid = message.type === 'register'
							&& typeof message.windowId === 'string'
							&& message.windowId
							&& hasDedicatedIdentity(message)
							&& message.registrationNonce === registrationNonce;
						if (!registrationValid) {
							logger.warn?.(
								'[Hardware-Workbench] rejected EDA registration '
								+ `gatewayId=${String(message.gatewayId)} `
								+ `productId=${String(message.productId)} `
								+ `protocolVersion=${String(message.protocolVersion)} `
								+ `extensionVersion=${String(message.extensionVersion)} `
								+ `nonceMatch=${String(message.registrationNonce === registrationNonce)}`,
							);
							socket.close(1008, 'Dedicated Hardware Workbench extension required');
							return;
						}
						registeredWindowId = message.windowId;
						const previous = edaClients.get(registeredWindowId);
						if (previous && previous.ws !== socket)
							previous.ws.close(1008, 'Window re-registered');
						edaClients.set(registeredWindowId, {
							extensionVersion: message.extensionVersion ?? null,
							gatewayId: message.gatewayId,
							productId: message.productId,
							protocolVersion: message.protocolVersion,
							ws: socket,
						});
						if (!activeWindowId)
							activeWindowId = registeredWindowId;
						logger.info?.(
							`[Hardware-Workbench] registered EDA window ${registeredWindowId} `
							+ `extensionVersion=${String(message.extensionVersion)}`,
						);
						socket.send(JSON.stringify({
							...identityEnvelope(),
							timestamp: Date.now(),
							type: 'registered',
							windowId: registeredWindowId,
						}));
						return;
					}
					handleEdaMessage(message, registeredWindowId);
				}
				catch (error) {
					logger.warn?.(`[Hardware-Workbench] Invalid EDA message: ${error.message}`);
				}
			});
			socket.on('close', () => {
				if (!registeredWindowId || edaClients.get(registeredWindowId)?.ws !== socket)
					return;
				serverCleanupWindow(registeredWindowId);
			});
		}
		else {
			socket.on('message', async (raw) => {
				try {
					const message = JSON.parse(raw.toString());
					if (!hasDedicatedIdentity(message)) {
						socket.send(JSON.stringify({ id: message.id, error: 'Hardware Workbench client identity required', type: 'error' }));
						return;
					}
					if (message.type === 'operation') {
						const result = await executeOperationOnEda(message.operation, message.args, message.windowId);
						socket.send(JSON.stringify({ ...identityEnvelope(), id: message.id, result, timestamp: Date.now(), type: 'result' }));
					}
					else if (message.type === 'ping') {
						socket.send(JSON.stringify({ ...identityEnvelope(), id: message.id, timestamp: Date.now(), type: 'pong' }));
					}
				}
				catch (error) {
					socket.send(JSON.stringify({ ...identityEnvelope(), error: error.message, timestamp: Date.now(), type: 'error' }));
				}
			});
		}
	});

	function serverCleanupWindow(windowId) {
		edaClients.delete(windowId);
		if (activeWindowId === windowId)
			activeWindowId = edaClients.keys().next().value || null;
		for (const [id, pending] of pendingRequests) {
			if (pending.windowId !== windowId)
				continue;
			clearTimeout(pending.timer);
			pending.reject(new Error(`Dedicated EasyEDA window "${windowId}" disconnected`));
			pendingRequests.delete(id);
		}
	}

	async function findExistingInstance() {
		if (portStart === 0 && portEnd === 0)
			return null;
		for (let port = portStart; port <= portEnd; port += 1) {
			if (await isDedicatedBridgeRunning(port))
				return port;
		}
		return null;
	}

	async function findAvailablePort() {
		if (portStart === 0 && portEnd === 0)
			return 0;
		for (let port = portStart; port <= portEnd; port += 1) {
			if (!(await isPortInUse(port)))
				return port;
		}
		throw new Error(`All ports in range ${portStart}-${portEnd} are in use`);
	}

	async function start() {
		const existingPort = await findExistingInstance();
		if (existingPort !== null)
			return { alreadyRunning: true, port: existingPort };
		const requestedPort = await findAvailablePort();
		await new Promise((resolve, reject) => {
			httpServer.once('error', reject);
			httpServer.listen(requestedPort, '127.0.0.1', () => {
				httpServer.off('error', reject);
				resolve();
			});
		});
		listeningPort = httpServer.address().port;
		logger.info?.(`[Hardware-Workbench] dedicated bridge listening on 127.0.0.1:${listeningPort}`);
		return { alreadyRunning: false, port: listeningPort };
	}

	async function stop() {
		for (const client of edaClients.values())
			client.ws.close(1001, 'Bridge stopping');
		for (const pending of pendingRequests.values()) {
			clearTimeout(pending.timer);
			pending.reject(new Error('Dedicated bridge stopped'));
		}
		pendingRequests.clear();
		await new Promise(resolve => webSocketServer.close(resolve));
		if (httpServer.listening)
			await new Promise(resolve => httpServer.close(resolve));
		listeningPort = null;
	}

	return {
		get port() {
			return listeningPort;
		},
		start,
		stop,
	};
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
	const server = createWorkbenchBridgeServer();
	server.start().then(({ alreadyRunning, port }) => {
		process.stdout.write(`${JSON.stringify({ alreadyRunning, gatewayId: GATEWAY_ID, port, service: SERVICE_ID })}\n`);
	}).catch((error) => {
		process.stderr.write(`[Hardware-Workbench] ${error.stack || error.message}\n`);
		process.exitCode = 1;
	});
}
