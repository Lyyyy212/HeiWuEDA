/**
 * ZhiYuanEDA Gateway extension for EasyEDA.
 *
 * This extension keeps the official `easyeda-bridge` wire protocol so the
 * guarded workbench adapter can use it, while owning an isolated connection
 * identity and a more resilient reconnect state machine.
 *
 * Connection policy:
 * - probe 49620-49629 concurrently instead of waiting on every port serially;
 * - prefer a bridge advertising this project's gateway ID;
 * - remember the last successful port;
 * - retry indefinitely with bounded exponential backoff and jitter;
 * - require two consecutive heartbeat misses before reconnecting.
 */
import * as extensionConfig from '../extension.json';

// ─── Protocol identity ────────────────────────────────────────
const SERVICE_ID = 'easyeda-bridge';
const GATEWAY_ID = 'lyyyy.zhiyuaneda';
const PRODUCT_ID = 'zhiyuaneda';
const PROTOCOL_VERSION = 1;
const WS_ID_PREFIX = 'zhiyuaneda-bridge';

// ─── Connection tuning ────────────────────────────────────────
const PORT_START = 49620;
const PORT_END = 49629;
const CONNECTION_TIMEOUT_MS = 3500;
const DEDICATED_PREFERENCE_WINDOW_MS = 300;
const RETRY_BASE_DELAY_MS = 1000;
const RETRY_MAX_DELAY_MS = 15000;
const RETRY_JITTER_RATIO = 0.2;
const HEARTBEAT_INTERVAL_MS = 15000;
const HEARTBEAT_TIMEOUT_MS = 7500;
const HEARTBEAT_MISSES_BEFORE_RECONNECT = 2;

// ─── Namespaced persistence / RPC ──────────────────────────────────
const STORAGE_KEY_AUTO_CONNECT = 'zhiyuaneda.gateway.autoConnect';
const STORAGE_KEY_PREFERRED_PORT = 'zhiyuaneda.gateway.preferredPort';
const MBUS_TOPIC_STATUS = 'zhiyuaneda-gateway-status';
const MBUS_TOPIC_CONTROL = 'zhiyuaneda-gateway-control';

interface BridgeMessage {
	type: 'execute' | 'ping' | 'pong' | 'handshake' | 'result' | 'error';
	id?: string;
	code?: string;
	service?: string;
	gatewayId?: string;
	protocolVersion?: number;
	result?: unknown;
	error?: string;
	timestamp?: number;
}

interface ConnectionCandidate {
	port: number;
	socketId: string;
	dedicated: boolean;
	bridgeGatewayId: string | null;
	bridgeProtocolVersion: number | null;
}

interface GatewayControlRequest {
	command: 'reconnect' | 'stop';
}

interface GatewayStatus {
	connected: boolean;
	connecting: boolean;
	autoConnect: boolean;
	port: number | null;
	preferredPort: number | null;
	windowId: string | null;
	gatewayId: string;
	bridgeGatewayId: string | null;
	protocolVersion: number;
	bridgeProtocolVersion: number | null;
	connectionMode: 'dedicated' | 'compatible' | 'disconnected';
	retryCount: number;
	nextRetryAt: number | null;
	lastError: string | null;
	connectedAt: number | null;
}

interface GatewayControlResponse {
	handled: boolean;
	status: GatewayStatus;
}

// ─── Runtime state ─────────────────────────────────────────────
let currentPort: number | null = null;
let preferredPort: number | null = null;
let activeSocketId: string | null = null;
let handshakeVerified = false;
let bridgeGatewayId: string | null = null;
let bridgeProtocolVersion: number | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let heartbeatTimeoutTimer: ReturnType<typeof setTimeout> | null = null;
let heartbeatPendingId: string | null = null;
let heartbeatMisses = 0;
let autoConnectEnabled = true;
let retryCount = 0;
let windowId: string | null = null;
let isConnecting = false;
let connectionSessionId = 0;
let messageBusRegistered = false;
let nextRetryAt: number | null = null;
let lastError: string | null = null;
let connectedAt: number | null = null;
const knownSocketIds = new Set<string>();
const pendingProbeCancels = new Map<string, () => void>();

function getConnectionStatus(): GatewayStatus {
	return {
		connected: handshakeVerified,
		connecting: isConnecting,
		autoConnect: autoConnectEnabled,
		port: currentPort,
		preferredPort,
		windowId,
		gatewayId: GATEWAY_ID,
		bridgeGatewayId,
		protocolVersion: PROTOCOL_VERSION,
		bridgeProtocolVersion,
		connectionMode: handshakeVerified
			? bridgeGatewayId === GATEWAY_ID ? 'dedicated' : 'compatible'
			: 'disconnected',
		retryCount,
		nextRetryAt,
		lastError,
		connectedAt,
	};
}

function ensureMessageBusServices(): void {
	if (messageBusRegistered)
		return;

	eda.sys_MessageBus.rpcService(MBUS_TOPIC_STATUS, () => getConnectionStatus());
	eda.sys_MessageBus.rpcService(MBUS_TOPIC_CONTROL, (request?: GatewayControlRequest): GatewayControlResponse => {
		if (request?.command === 'reconnect') {
			performReconnect();
		}
		else if (request?.command === 'stop') {
			performStopConnection(false);
		}

		return {
			handled: true,
			status: getConnectionStatus(),
		};
	});

	messageBusRegistered = true;
}

function nextConnectionSessionId(): number {
	connectionSessionId += 1;
	return connectionSessionId;
}

function isConnectionSessionActive(sessionId: number): boolean {
	return sessionId === connectionSessionId;
}

function isValidPort(value: unknown): value is number {
	return Number.isInteger(value) && Number(value) >= PORT_START && Number(value) <= PORT_END;
}

function socketIdForPort(port: number): string {
	return `${WS_ID_PREFIX}-${port}`;
}

function closeSocketTransport(socketId: string): void {
	try {
		eda.sys_WebSocket.close(socketId);
	}
	catch { /* best-effort cleanup */ }
	knownSocketIds.delete(socketId);
}

function closeSocket(socketId: string): void {
	const cancelProbe = pendingProbeCancels.get(socketId);
	if (cancelProbe) {
		cancelProbe();
		return;
	}
	closeSocketTransport(socketId);
}

function closeAllSockets(exceptSocketId: string | null = null): void {
	for (const socketId of [...knownSocketIds]) {
		if (socketId !== exceptSocketId) {
			closeSocket(socketId);
		}
	}
}

function clearRetryTimer(): void {
	if (retryTimer) {
		clearTimeout(retryTimer);
		retryTimer = null;
	}
	nextRetryAt = null;
}

function stopHeartbeat(): void {
	if (heartbeatTimer) {
		clearInterval(heartbeatTimer);
		heartbeatTimer = null;
	}
	if (heartbeatTimeoutTimer) {
		clearTimeout(heartbeatTimeoutTimer);
		heartbeatTimeoutTimer = null;
	}
	heartbeatPendingId = null;
	heartbeatMisses = 0;
}

function cancelConnectionFlow(resetRetryCount = true): void {
	nextConnectionSessionId();
	isConnecting = false;
	clearRetryTimer();
	stopHeartbeat();
	handshakeVerified = false;
	currentPort = null;
	activeSocketId = null;
	bridgeGatewayId = null;
	bridgeProtocolVersion = null;
	windowId = null;
	connectedAt = null;
	if (resetRetryCount) {
		retryCount = 0;
	}
	closeAllSockets();
}

function performReconnect(): void {
	eda.sys_Message.showToastMessage('ZhiYuanEDA Gateway 正在重新连接…');
	cancelConnectionFlow();
	void scanAndConnect(true);
}

function performStopConnection(showToast = true): void {
	cancelConnectionFlow();
	lastError = 'Connection stopped by user';
	if (showToast) {
		eda.sys_Message.showToastMessage('已停止 ZhiYuanEDA Gateway 连接');
	}
}

async function dispatchControlCommand(command: GatewayControlRequest['command']): Promise<void> {
	try {
		const response = await eda.sys_MessageBus.rpcCall(
			MBUS_TOPIC_CONTROL,
			{ command },
			500,
		) as GatewayControlResponse;
		if (response?.handled) {
			if (command === 'stop') {
				eda.sys_Message.showToastMessage('已停止 ZhiYuanEDA Gateway 连接');
			}
			return;
		}
	}
	catch { /* the current window becomes the RPC owner below */ }

	ensureMessageBusServices();
	if (command === 'reconnect') {
		performReconnect();
	}
	else {
		performStopConnection();
	}
}

// ─── Extension lifecycle ───────────────────────────────────────

// eslint-disable-next-line unused-imports/no-unused-vars
export function activate(status?: 'onStartupFinished', arg?: string): void {
	ensureMessageBusServices();
	const storedAutoConnect = eda.sys_Storage.getExtensionUserConfig(STORAGE_KEY_AUTO_CONNECT);
	autoConnectEnabled = storedAutoConnect !== false;
	const storedPreferredPort = eda.sys_Storage.getExtensionUserConfig(STORAGE_KEY_PREFERRED_PORT);
	preferredPort = isValidPort(storedPreferredPort) ? storedPreferredPort : null;

	if (autoConnectEnabled) {
		void scanAndConnect();
	}
}

export function deactivate(): void {
	cancelConnectionFlow(false);
}

// ─── Menu actions ───────────────────────────────────────────────

export function reconnect(): void {
	void dispatchControlCommand('reconnect');
}

export function stopConnection(): void {
	void dispatchControlCommand('stop');
}

export async function toggleAutoConnect(): Promise<void> {
	const newValue = !autoConnectEnabled;
	await eda.sys_Storage.setExtensionUserConfig(STORAGE_KEY_AUTO_CONNECT, newValue);
	autoConnectEnabled = newValue;

	if (newValue) {
		lastError = null;
		cancelConnectionFlow();
		void scanAndConnect();
		eda.sys_Message.showToastMessage('已启用网关自动连接');
	}
	else {
		performStopConnection(false);
		eda.sys_Message.showToastMessage('已禁用网关自动连接');
	}
}

export async function about(): Promise<void> {
	let statusInfo = getConnectionStatus();
	try {
		statusInfo = await eda.sys_MessageBus.rpcCall(MBUS_TOPIC_STATUS, undefined, 300) as GatewayStatus;
	}
	catch { /* local status is sufficient */ }

	const connectionText = statusInfo.connected
		? `已连接：${statusInfo.port} (${statusInfo.connectionMode})`
		: statusInfo.connecting
			? '正在连接'
			: statusInfo.nextRetryAt
				? `等待重连：${Math.max(0, statusInfo.nextRetryAt - Date.now())} ms`
				: '未连接';
	const details = [
		`ZhiYuanEDA Gateway v${extensionConfig.version}`,
		connectionText,
		`Gateway ID: ${GATEWAY_ID}`,
		`Protocol: ${PROTOCOL_VERSION}`,
		`Window ID: ${statusInfo.windowId ?? '(not registered)'}`,
		`自动连接：${statusInfo.autoConnect ? '开' : '关'}`,
	];
	if (statusInfo.lastError) {
		details.push(`最后错误：${statusInfo.lastError}`);
	}

	eda.sys_Dialog.showInformationMessage(details.join('\n'), 'ZhiYuanEDA Gateway');
}

// ─── Discovery and connection ─────────────────────────────────────

function orderedPorts(): Array<number> {
	const ports = Array.from({ length: PORT_END - PORT_START + 1 }, (_, index) => PORT_START + index);
	if (preferredPort === null) {
		return ports;
	}
	return [preferredPort, ...ports.filter(port => port !== preferredPort)];
}

async function scanAndConnect(force = false): Promise<void> {
	if (isConnecting || (!autoConnectEnabled && !force)) {
		return;
	}

	const sessionId = nextConnectionSessionId();
	isConnecting = true;
	clearRetryTimer();
	lastError = null;

	try {
		const candidate = await discoverConnectionCandidate(orderedPorts(), sessionId);
		if (!isConnectionSessionActive(sessionId)) {
			return;
		}

		if (!candidate) {
			retryCount += 1;
			lastError = `No ${SERVICE_ID} service found on ${PORT_START}-${PORT_END}`;
			console.warn(`[ZhiYuanEDA] ${lastError}`);
			if (autoConnectEnabled) {
				scheduleRetry(sessionId);
			}
			return;
		}

		activeSocketId = candidate.socketId;
		closeAllSockets(activeSocketId);
		currentPort = candidate.port;
		bridgeGatewayId = candidate.bridgeGatewayId;
		bridgeProtocolVersion = candidate.bridgeProtocolVersion;
		windowId = crypto.randomUUID();

		try {
			eda.sys_WebSocket.send(activeSocketId, JSON.stringify({
				type: 'register',
				windowId,
				gatewayId: GATEWAY_ID,
				productId: PRODUCT_ID,
				protocolVersion: PROTOCOL_VERSION,
				extensionVersion: extensionConfig.version,
				timestamp: Date.now(),
			}));
		}
		catch (error: unknown) {
			lastError = `Bridge registration failed: ${error instanceof Error ? error.message : String(error)}`;
			closeAllSockets();
			activeSocketId = null;
			currentPort = null;
			windowId = null;
			retryCount += 1;
			if (autoConnectEnabled) {
				scheduleRetry(sessionId);
			}
			return;
		}

		handshakeVerified = true;
		preferredPort = candidate.port;
		retryCount = 0;
		nextRetryAt = null;
		lastError = null;
		connectedAt = Date.now();
		void persistPreferredPort(candidate.port);
		startHeartbeat(sessionId);
		const mode = candidate.dedicated ? '专属' : '官方兼容';
		eda.sys_Message.showToastMessage(`ZhiYuanEDA Gateway 已连接（${candidate.port}，${mode}）`);
	}
	finally {
		if (isConnectionSessionActive(sessionId)) {
			isConnecting = false;
		}
	}
}

async function persistPreferredPort(port: number): Promise<void> {
	try {
		await eda.sys_Storage.setExtensionUserConfig(STORAGE_KEY_PREFERRED_PORT, port);
	}
	catch (error: unknown) {
		console.warn('[ZhiYuanEDA] Failed to persist preferred bridge port:', error);
	}
}

function discoverConnectionCandidate(
	ports: Array<number>,
	sessionId: number,
): Promise<ConnectionCandidate | null> {
	return new Promise((resolve) => {
		let resolved = false;
		let remaining = ports.length;
		let compatibleFallback: ConnectionCandidate | null = null;
		let preferenceTimer: ReturnType<typeof setTimeout> | null = null;

		const finish = (candidate: ConnectionCandidate | null): void => {
			if (resolved)
				return;
			resolved = true;
			if (preferenceTimer) {
				clearTimeout(preferenceTimer);
			}
			if (candidate) {
				closeAllSockets(candidate.socketId);
			}
			else {
				closeAllSockets();
			}
			resolve(candidate);
		};

		for (const port of ports) {
			void tryConnectToPort(port, sessionId).then((candidate) => {
				remaining -= 1;
				if (resolved) {
					if (candidate) {
						closeSocket(candidate.socketId);
					}
					return;
				}
				if (!isConnectionSessionActive(sessionId)) {
					finish(null);
					return;
				}

				if (candidate?.dedicated) {
					finish(candidate);
					return;
				}
				if (candidate && !compatibleFallback) {
					compatibleFallback = candidate;
					preferenceTimer = setTimeout(
						() => finish(compatibleFallback),
						DEDICATED_PREFERENCE_WINDOW_MS,
					);
				}
				if (remaining === 0) {
					finish(compatibleFallback);
				}
			});
		}
	});
}

function tryConnectToPort(port: number, sessionId: number): Promise<ConnectionCandidate | null> {
	return new Promise((resolve) => {
		const socketId = socketIdForPort(port);
		let settled = false;
		let timer: ReturnType<typeof setTimeout>;

		const settle = (candidate: ConnectionCandidate | null): void => {
			if (settled)
				return;
			settled = true;
			clearTimeout(timer);
			pendingProbeCancels.delete(socketId);
			if (!candidate) {
				closeSocketTransport(socketId);
			}
			resolve(candidate);
		};

		if (!isConnectionSessionActive(sessionId)) {
			resolve(null);
			return;
		}

		closeSocket(socketId);
		knownSocketIds.add(socketId);
		timer = setTimeout(() => settle(null), CONNECTION_TIMEOUT_MS);
		pendingProbeCancels.set(socketId, () => settle(null));

		try {
			eda.sys_WebSocket.register(
				socketId,
				`ws://127.0.0.1:${port}/eda`,
				async (event: MessageEvent) => {
					if (!isConnectionSessionActive(sessionId)) {
						settle(null);
						return;
					}

					let message: BridgeMessage;
					try {
						message = JSON.parse(String(event.data)) as BridgeMessage;
					}
					catch (error: unknown) {
						console.warn(`[ZhiYuanEDA] Invalid bridge message on ${port}:`, error);
						return;
					}

					if (message.type === 'handshake') {
						if (message.service !== SERVICE_ID) {
							settle(null);
							return;
						}
						if (message.gatewayId && message.gatewayId !== GATEWAY_ID) {
							settle(null);
							return;
						}
						settle({
							port,
							socketId,
							dedicated: message.gatewayId === GATEWAY_ID,
							bridgeGatewayId: message.gatewayId ?? null,
							bridgeProtocolVersion: Number.isInteger(message.protocolVersion)
								? Number(message.protocolVersion)
								: null,
						});
						return;
					}

					if (activeSocketId !== socketId || !handshakeVerified) {
						return;
					}
					await handleMessage(message, socketId);
				},
				() => {},
			);
		}
		catch (error: unknown) {
			console.warn(`[ZhiYuanEDA] WebSocket registration failed on ${port}:`, error);
			settle(null);
		}
	});
}

// ─── Retry and heartbeat ───────────────────────────────────────

function retryDelayMs(attempt: number): number {
	const exponent = Math.min(Math.max(0, attempt - 1), 8);
	const bounded = Math.min(RETRY_BASE_DELAY_MS * (2 ** exponent), RETRY_MAX_DELAY_MS);
	const jitter = bounded * RETRY_JITTER_RATIO * ((Math.random() * 2) - 1);
	return Math.max(RETRY_BASE_DELAY_MS, Math.round(bounded + jitter));
}

function scheduleRetry(sessionId: number): void {
	clearRetryTimer();
	const delay = retryDelayMs(retryCount);
	nextRetryAt = Date.now() + delay;
	retryTimer = setTimeout(() => {
		if (!isConnectionSessionActive(sessionId) || isConnecting || !autoConnectEnabled) {
			return;
		}
		void scanAndConnect();
	}, delay);
}

function startHeartbeat(sessionId: number): void {
	stopHeartbeat();
	heartbeatTimer = setInterval(() => {
		if (!isConnectionSessionActive(sessionId) || !handshakeVerified || !activeSocketId) {
			stopHeartbeat();
			return;
		}
		sendHeartbeat(sessionId, activeSocketId);
	}, HEARTBEAT_INTERVAL_MS);
}

function sendHeartbeat(sessionId: number, socketId: string): void {
	const heartbeatId = `hw-hb-${Date.now()}`;
	heartbeatPendingId = heartbeatId;
	try {
		eda.sys_WebSocket.send(socketId, JSON.stringify({
			type: 'ping',
			id: heartbeatId,
			gatewayId: GATEWAY_ID,
			timestamp: Date.now(),
		}));
	}
	catch (error: unknown) {
		lastError = `Heartbeat send failed: ${error instanceof Error ? error.message : String(error)}`;
		reconnectAfterTransportFailure();
		return;
	}

	if (heartbeatTimeoutTimer) {
		clearTimeout(heartbeatTimeoutTimer);
	}
	heartbeatTimeoutTimer = setTimeout(() => {
		if (!isConnectionSessionActive(sessionId) || heartbeatPendingId !== heartbeatId) {
			return;
		}
		heartbeatPendingId = null;
		heartbeatMisses += 1;
		lastError = `Heartbeat timeout (${heartbeatMisses}/${HEARTBEAT_MISSES_BEFORE_RECONNECT})`;
		if (heartbeatMisses >= HEARTBEAT_MISSES_BEFORE_RECONNECT) {
			reconnectAfterTransportFailure();
		}
	}, HEARTBEAT_TIMEOUT_MS);
}

function reconnectAfterTransportFailure(): void {
	console.warn(`[ZhiYuanEDA] ${lastError ?? 'Transport disconnected'}, reconnecting...`);
	cancelConnectionFlow();
	if (autoConnectEnabled) {
		void scanAndConnect();
	}
}

// ─── Bridge messages ─────────────────────────────────────────────

async function handleMessage(message: BridgeMessage, socketId: string): Promise<void> {
	if (message.type === 'ping') {
		eda.sys_WebSocket.send(socketId, JSON.stringify({
			type: 'pong',
			id: message.id,
			gatewayId: GATEWAY_ID,
			timestamp: Date.now(),
		}));
		return;
	}

	if (message.type === 'pong') {
		if (!heartbeatPendingId || !message.id || message.id === heartbeatPendingId) {
			heartbeatPendingId = null;
			heartbeatMisses = 0;
			if (heartbeatTimeoutTimer) {
				clearTimeout(heartbeatTimeoutTimer);
				heartbeatTimeoutTimer = null;
			}
		}
		return;
	}

	if (message.type !== 'execute' || !message.code) {
		return;
	}

	try {
		const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
		const execute = new AsyncFunction('eda', message.code);
		const result = await execute(eda);
		eda.sys_WebSocket.send(socketId, JSON.stringify({
			type: 'result',
			id: message.id,
			result: result !== undefined ? result : null,
			gatewayId: GATEWAY_ID,
			timestamp: Date.now(),
		}));
	}
	catch (error: unknown) {
		eda.sys_WebSocket.send(socketId, JSON.stringify({
			type: 'error',
			id: message.id,
			error: error instanceof Error ? error.message : String(error),
			gatewayId: GATEWAY_ID,
			timestamp: Date.now(),
		}));
	}
}
