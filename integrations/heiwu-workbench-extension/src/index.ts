/**
 * Heiwu Workbench EasyEDA extension runtime.
 *
 * This extension uses a project-owned bridge protocol with a fixed read-only
 * operation catalog, an isolated connection identity, and a resilient
 * reconnect state machine.
 *
 * Connection policy:
 * - probe 49620-49629 sequentially because the native WebSocket API requires
 *   the previous probe to be closed before registering the next endpoint;
 * - require a bridge advertising this project's gateway and product IDs;
 * - remember the last successful port;
 * - retry indefinitely with bounded exponential backoff and jitter;
 * - require two consecutive heartbeat misses before reconnecting.
 */
import * as extensionConfig from '../extension.json';

// ─── Protocol identity ────────────────────────────────────────
const SERVICE_ID = 'easyeda-bridge';
const GATEWAY_ID = 'lyyyy.hardware-workbench';
const PRODUCT_ID = 'hardware-workbench';
const PROTOCOL_VERSION = 2;
const WS_ID_PREFIX = 'hardware-workbench-bridge';
const ACCESS_POLICY = 'dedicated-extension-required';
const WORKBENCH_IFRAME_ID = 'heiwu-workbench-window';
const WORKBENCH_IFRAME_PATH = '/iframe/workbench.html';
const GITHUB_REPOSITORY_URL = 'https://github.com/Lyyyy212/HeiWuEDA';

let workbenchWindowOpen = false;
let workbenchWindowOpening: Promise<void> | null = null;

// ─── Connection tuning ────────────────────────────────────────
const PORT_START = 49620;
const PORT_END = 49629;
const CONNECTION_TIMEOUT_MS = 3500;
const REGISTRATION_TIMEOUT_MS = 3500;
const RETRY_BASE_DELAY_MS = 1000;
const RETRY_MAX_DELAY_MS = 15000;
const RETRY_JITTER_RATIO = 0.2;
const HEARTBEAT_INTERVAL_MS = 15000;
const HEARTBEAT_TIMEOUT_MS = 7500;
const HEARTBEAT_MISSES_BEFORE_RECONNECT = 2;

// ─── Namespaced persistence / RPC ──────────────────────────────────
const STORAGE_KEY_AUTO_CONNECT = 'hardwareWorkbench.gateway.autoConnect';
const STORAGE_KEY_PREFERRED_PORT = 'hardwareWorkbench.gateway.preferredPort';
const MBUS_TOPIC_STATUS = 'hardware-workbench-gateway-status';
const MBUS_TOPIC_CONTROL = 'hardware-workbench-gateway-control';

interface BridgeMessage {
	type: 'operation' | 'ping' | 'pong' | 'handshake' | 'registered' | 'result' | 'error';
	id?: string;
	operation?: string;
	args?: Record<string, unknown>;
	service?: string;
	gatewayId?: string;
	productId?: string;
	protocolVersion?: number;
	registrationNonce?: string;
	result?: unknown;
	error?: string;
	timestamp?: number;
	windowId?: string;
}

interface CurrentContext {
	project: {
		friendlyName: string;
		itemType: unknown;
		name: string;
		uuid: string;
	} | null;
	document: {
		documentType: unknown;
		parentLibraryUuid: string | null;
		parentProjectUuid: string | null;
		tabId: string;
		uuid: string;
	} | null;
}

const OPERATION_CATALOG = Object.freeze([
	{
		id: 'workbench.catalog.read.v1',
		effect: 'read-only',
		stability: 'stable',
		description: 'Read the fixed operation catalog.',
	},
	{
		id: 'workbench.context.read.v1',
		effect: 'read-only',
		stability: 'beta-document-api',
		description: 'Read the current project and active document identity.',
	},
	{
		id: 'workbench.schematic.index.read.v1',
		effect: 'read-only',
		stability: 'beta-schematic-api',
		description: 'Read the schematic index after binding it to the expected project and document.',
	},
] as const);

const OPERATION_IDS = new Set<string>(OPERATION_CATALOG.map(operation => operation.id));

interface ConnectionCandidate {
	port: number;
	socketId: string;
	bridgeGatewayId: string | null;
	bridgeProtocolVersion: number | null;
	registrationNonce: string;
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
	connectionMode: 'dedicated' | 'disconnected';
	retryCount: number;
	nextRetryAt: number | null;
	lastError: string | null;
	connectedAt: number | null;
	extensionVersion: string;
	productId: string;
	accessPolicy: string;
}

interface GatewayControlResponse {
	handled: boolean;
	status: GatewayStatus;
}

interface PendingRegistrationAck {
	resolve: (accepted: boolean) => void;
	sessionId: number;
	socketId: string;
	timer: ReturnType<typeof setTimeout>;
	windowId: string;
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
let pendingRegistrationAck: PendingRegistrationAck | null = null;
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
			? 'dedicated'
			: 'disconnected',
		retryCount,
		nextRetryAt,
		lastError,
		connectedAt,
		extensionVersion: extensionConfig.version,
		productId: PRODUCT_ID,
		accessPolicy: ACCESS_POLICY,
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

function settleRegistrationAck(accepted: boolean): void {
	const pending = pendingRegistrationAck;
	if (!pending)
		return;

	pendingRegistrationAck = null;
	clearTimeout(pending.timer);
	pending.resolve(accepted);
}

function waitForRegistrationAck(
	sessionId: number,
	socketId: string,
	expectedWindowId: string,
): Promise<boolean> {
	settleRegistrationAck(false);
	return new Promise((resolve) => {
		const timer = setTimeout(() => settleRegistrationAck(false), REGISTRATION_TIMEOUT_MS);
		pendingRegistrationAck = {
			resolve,
			sessionId,
			socketId,
			timer,
			windowId: expectedWindowId,
		};
	});
}

function handleRegistrationAck(message: BridgeMessage, socketId: string): void {
	const pending = pendingRegistrationAck;
	if (!pending || pending.socketId !== socketId)
		return;

	const accepted = isConnectionSessionActive(pending.sessionId)
		&& message.gatewayId === GATEWAY_ID
		&& message.productId === PRODUCT_ID
		&& message.protocolVersion === PROTOCOL_VERSION
		&& message.windowId === pending.windowId;
	settleRegistrationAck(accepted);
}

function cancelConnectionFlow(resetRetryCount = true): void {
	nextConnectionSessionId();
	settleRegistrationAck(false);
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
	eda.sys_Message.showToastMessage('黑五EDA 正在重新连接…');
	cancelConnectionFlow();
	void scanAndConnect(true);
}

function performStopConnection(showToast = true): void {
	cancelConnectionFlow();
	lastError = 'Connection stopped by user';
	if (showToast) {
		eda.sys_Message.showToastMessage('已停止黑五EDA 连接');
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
				eda.sys_Message.showToastMessage('已停止黑五EDA 连接');
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

function ensureWorkbenchAutoConnect(): void {
	const wasDisabled = !autoConnectEnabled;
	autoConnectEnabled = true;
	void eda.sys_Storage.setExtensionUserConfig(STORAGE_KEY_AUTO_CONNECT, true);
	if (wasDisabled) {
		lastError = null;
		cancelConnectionFlow();
	}
	if (!handshakeVerified && !isConnecting) {
		void scanAndConnect();
	}
}

// eslint-disable-next-line unused-imports/no-unused-vars
export function activate(status?: 'onStartupFinished', arg?: string): void {
	ensureMessageBusServices();
	const storedPreferredPort = eda.sys_Storage.getExtensionUserConfig(STORAGE_KEY_PREFERRED_PORT);
	preferredPort = isValidPort(storedPreferredPort) ? storedPreferredPort : null;
	ensureWorkbenchAutoConnect();
}

export function deactivate(): void {
	workbenchWindowOpen = false;
	void eda.sys_IFrame.closeIFrame(WORKBENCH_IFRAME_ID);
	cancelConnectionFlow(false);
}

// ─── Menu actions ───────────────────────────────────────────────

export function reconnect(): void {
	void dispatchControlCommand('reconnect');
}

export function stopConnection(): void {
	void dispatchControlCommand('stop');
}

export async function openWorkbenchWindow(): Promise<void> {
	ensureWorkbenchAutoConnect();
	if (workbenchWindowOpening) {
		await workbenchWindowOpening;
		return;
	}

	const opening = (async (): Promise<void> => {
		try {
			if (workbenchWindowOpen) {
				const shown = await eda.sys_IFrame.showIFrame(WORKBENCH_IFRAME_ID);
				if (shown)
					return;
				workbenchWindowOpen = false;
			}

			// A user-close can leave the fixed ID registered briefly in some EDA
			// releases. Clear that stale registration before creating a new frame.
			try {
				await eda.sys_IFrame.closeIFrame(WORKBENCH_IFRAME_ID);
			}
			catch { /* a missing stale frame is already the desired state */ }

			const opened = await eda.sys_IFrame.openIFrame(
				WORKBENCH_IFRAME_PATH,
				420,
				520,
				WORKBENCH_IFRAME_ID,
				{
					buttonCallbackFn(button) {
						if (button === 'close')
							workbenchWindowOpen = false;
					},
					grayscaleMask: false,
					maximizeButton: true,
					minimizeButton: true,
					minimizeStyle: 'collapsed',
					onBeforeCloseCallFn() {
						workbenchWindowOpen = false;
						return true;
					},
					title: '黑五EDA',
				},
			);
			if (!opened) {
				throw new Error('嘉立创EDA未能打开工作台窗口');
			}
			workbenchWindowOpen = true;
		}
		catch (error: unknown) {
			workbenchWindowOpen = false;
			await eda.sys_Dialog.showInformationMessage(
				`打开黑五EDA 失败：${error instanceof Error ? error.message : String(error)}`,
				'黑五EDA',
			);
		}
	})();

	workbenchWindowOpening = opening;
	try {
		await opening;
	}
	finally {
		if (workbenchWindowOpening === opening)
			workbenchWindowOpening = null;
	}
}

export function openGithubRepository(): void {
	eda.sys_Window.open(GITHUB_REPOSITORY_URL);
}

export async function toggleAutoConnect(): Promise<void> {
	const newValue = !autoConnectEnabled;
	await eda.sys_Storage.setExtensionUserConfig(STORAGE_KEY_AUTO_CONNECT, newValue);
	autoConnectEnabled = newValue;

	if (newValue) {
		lastError = null;
		cancelConnectionFlow();
		void scanAndConnect();
		eda.sys_Message.showToastMessage('已启用黑五EDA 自动连接');
	}
	else {
		performStopConnection(false);
		eda.sys_Message.showToastMessage('已禁用黑五EDA 自动连接');
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
		`黑五EDA v${extensionConfig.version}`,
		connectionText,
		`Gateway ID: ${GATEWAY_ID}`,
		`Protocol: ${PROTOCOL_VERSION}`,
		`Window ID: ${statusInfo.windowId ?? '(not registered)'}`,
		`自动连接：${statusInfo.autoConnect ? '开' : '关'}`,
	];
	if (statusInfo.lastError) {
		details.push(`最后错误：${statusInfo.lastError}`);
	}

	eda.sys_Dialog.showInformationMessage(details.join('\n'), '黑五EDA 运行诊断');
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
			lastError = `No dedicated ${GATEWAY_ID} bridge found on ${PORT_START}-${PORT_END}`;
			console.warn(`[Hardware-Workbench] ${lastError}`);
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
		const registrationAck = waitForRegistrationAck(sessionId, activeSocketId, windowId);

		try {
			eda.sys_WebSocket.send(activeSocketId, JSON.stringify({
				type: 'register',
				windowId,
				gatewayId: GATEWAY_ID,
				productId: PRODUCT_ID,
				protocolVersion: PROTOCOL_VERSION,
				registrationNonce: candidate.registrationNonce,
				extensionVersion: extensionConfig.version,
				timestamp: Date.now(),
			}));
		}
		catch (error: unknown) {
			settleRegistrationAck(false);
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

		const registered = await registrationAck;
		if (!isConnectionSessionActive(sessionId)) {
			return;
		}
		if (!registered) {
			lastError = 'Dedicated bridge registration was not acknowledged';
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
		eda.sys_Message.showToastMessage('黑五EDA 已就绪');
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
		console.warn('[Hardware-Workbench] Failed to persist preferred bridge port:', error);
	}
}

async function discoverConnectionCandidate(
	ports: Array<number>,
	sessionId: number,
): Promise<ConnectionCandidate | null> {
	for (const port of ports) {
		if (!isConnectionSessionActive(sessionId)) {
			closeAllSockets();
			return null;
		}

		const candidate = await tryConnectToPort(port, sessionId);
		if (!isConnectionSessionActive(sessionId)) {
			closeAllSockets();
			return null;
		}
		if (candidate) {
			closeAllSockets(candidate.socketId);
			return candidate;
		}
	}

	closeAllSockets();
	return null;
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
						console.warn(`[Hardware-Workbench] Invalid bridge message on ${port}:`, error);
						return;
					}

					if (message.type === 'handshake') {
						if (
							message.service !== SERVICE_ID
							|| message.gatewayId !== GATEWAY_ID
							|| message.productId !== PRODUCT_ID
							|| message.protocolVersion !== PROTOCOL_VERSION
							|| typeof message.registrationNonce !== 'string'
							|| !message.registrationNonce
						) {
							settle(null);
							return;
						}
						settle({
							port,
							socketId,
							bridgeGatewayId: message.gatewayId,
							bridgeProtocolVersion: Number.isInteger(message.protocolVersion)
								? Number(message.protocolVersion)
								: null,
							registrationNonce: message.registrationNonce,
						});
						return;
					}

					if (message.type === 'registered') {
						handleRegistrationAck(message, socketId);
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
			console.warn(`[Hardware-Workbench] WebSocket registration failed on ${port}:`, error);
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
			productId: PRODUCT_ID,
			protocolVersion: PROTOCOL_VERSION,
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
	console.warn(`[Hardware-Workbench] ${lastError ?? 'Transport disconnected'}, reconnecting...`);
	cancelConnectionFlow();
	if (autoConnectEnabled) {
		void scanAndConnect();
	}
}

// ─── Bridge messages ─────────────────────────────────────────────

function requireObjectArgs(args: BridgeMessage['args']): Record<string, unknown> {
	if (args === undefined) {
		return {};
	}
	if (!args || typeof args !== 'object' || Array.isArray(args)) {
		throw new Error('Operation args must be a JSON object');
	}
	return args;
}

function requireExactKeys(args: Record<string, unknown>, allowedKeys: string[]): void {
	const unexpectedKeys = Object.keys(args).filter(key => !allowedKeys.includes(key));
	if (unexpectedKeys.length > 0) {
		throw new Error(`Unexpected operation args: ${unexpectedKeys.join(', ')}`);
	}
}

function requireNonEmptyString(value: unknown, name: string): string {
	if (typeof value !== 'string' || !value.trim()) {
		throw new Error(`${name} must be a non-empty string`);
	}
	return value;
}

async function readCurrentContext(): Promise<CurrentContext> {
	const [project, document] = await Promise.all([
		eda.dmt_Project.getCurrentProjectInfo(),
		eda.dmt_SelectControl.getCurrentDocumentInfo(),
	]);
	let projectContext: CurrentContext['project'] = null;
	if (project) {
		projectContext = {
			friendlyName: project.friendlyName,
			itemType: project.itemType,
			name: project.name,
			uuid: project.uuid,
		};
	}
	let documentContext: CurrentContext['document'] = null;
	if (document) {
		documentContext = {
			documentType: document.documentType,
			parentLibraryUuid: document.parentLibraryUuid ?? null,
			parentProjectUuid: document.parentProjectUuid ?? null,
			tabId: document.tabId,
			uuid: document.uuid,
		};
	}
	return {
		document: documentContext,
		project: projectContext,
	};
}

function assertBoundContext(
	context: CurrentContext,
	expectedProjectUuid: string,
	expectedDocumentUuid: string,
): void {
	if (context.project?.uuid !== expectedProjectUuid) {
		throw new Error('Active project does not match expectedProjectUuid');
	}
	if (context.document?.uuid !== expectedDocumentUuid) {
		throw new Error('Active document does not match expectedDocumentUuid');
	}
	if (context.document.parentProjectUuid !== expectedProjectUuid) {
		throw new Error('Active document is not owned by expectedProjectUuid');
	}
}

async function dispatchOperation(operation: string, rawArgs: BridgeMessage['args']): Promise<unknown> {
	if (!OPERATION_IDS.has(operation)) {
		throw new Error(`Operation is not allowed: ${operation}`);
	}
	const args = requireObjectArgs(rawArgs);

	if (operation === 'workbench.catalog.read.v1') {
		requireExactKeys(args, []);
		return {
			operations: OPERATION_CATALOG,
			protocolVersion: PROTOCOL_VERSION,
		};
	}

	if (operation === 'workbench.context.read.v1') {
		requireExactKeys(args, []);
		return readCurrentContext();
	}

	requireExactKeys(args, ['expectedProjectUuid', 'expectedDocumentUuid']);
	const expectedProjectUuid = requireNonEmptyString(args.expectedProjectUuid, 'expectedProjectUuid');
	const expectedDocumentUuid = requireNonEmptyString(args.expectedDocumentUuid, 'expectedDocumentUuid');
	const before = await readCurrentContext();
	assertBoundContext(before, expectedProjectUuid, expectedDocumentUuid);

	const [schematics, pages] = await Promise.all([
		eda.dmt_Schematic.getAllSchematicsInfo(),
		eda.dmt_Schematic.getAllSchematicPagesInfo(),
	]);
	const after = await readCurrentContext();
	assertBoundContext(after, expectedProjectUuid, expectedDocumentUuid);

	return {
		context: after,
		pages: pages.map(page => ({
			itemType: page.itemType,
			name: page.name,
			parentSchematicUuid: page.parentSchematicUuid,
			uuid: page.uuid,
		})),
		schematics: schematics.map(schematic => ({
			itemType: schematic.itemType,
			name: schematic.name,
			parentBoardName: schematic.parentBoardName ?? null,
			parentProjectUuid: schematic.parentProjectUuid,
			uuid: schematic.uuid,
		})),
	};
}

async function handleMessage(message: BridgeMessage, socketId: string): Promise<void> {
	if (
		message.gatewayId !== GATEWAY_ID
		|| message.productId !== PRODUCT_ID
		|| message.protocolVersion !== PROTOCOL_VERSION
	) {
		return;
	}

	if (message.type === 'ping') {
		eda.sys_WebSocket.send(socketId, JSON.stringify({
			type: 'pong',
			id: message.id,
			gatewayId: GATEWAY_ID,
			productId: PRODUCT_ID,
			protocolVersion: PROTOCOL_VERSION,
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

	if (message.type !== 'operation' || !message.id || !message.operation) {
		return;
	}

	try {
		const result = await dispatchOperation(message.operation, message.args);
		eda.sys_WebSocket.send(socketId, JSON.stringify({
			type: 'result',
			id: message.id,
			result: result !== undefined ? result : null,
			gatewayId: GATEWAY_ID,
			productId: PRODUCT_ID,
			protocolVersion: PROTOCOL_VERSION,
			timestamp: Date.now(),
		}));
	}
	catch (error: unknown) {
		eda.sys_WebSocket.send(socketId, JSON.stringify({
			type: 'error',
			id: message.id,
			error: error instanceof Error ? error.message : String(error),
			gatewayId: GATEWAY_ID,
			productId: PRODUCT_ID,
			protocolVersion: PROTOCOL_VERSION,
			timestamp: Date.now(),
		}));
	}
}
