const CANVAS_ENDPOINT = '/api/canvas'
const SELECTION_ENDPOINT = '/api/selection'
const VIEW_STATE_ENDPOINT = '/api/view-state'

const TOOL_GET_CANVAS_STATE = 'get_hardware_learning_canvas_state'
const TOOL_SAVE_CANVAS_STATE = 'save_hardware_learning_canvas_state'
const TOOL_SAVE_SELECTION_STATE = 'save_hardware_learning_selection_state'
const TOOL_SAVE_VIEW_STATE = 'save_hardware_learning_view_state'
const TOOL_SAVE_REFERENCE_IMAGE = 'save_hardware_learning_reference_image'
const TOOL_READ_PAGE_ASSET = 'read_hardware_learning_page_asset'
const TOOL_CHOOSE_EXPORT_DIRECTORY = 'choose_hardware_learning_export_directory'
const TOOL_DOWNLOAD_FILE = 'download_hardware_learning_file'
const TOOL_COPY_IMAGE_TO_CLIPBOARD = 'copy_hardware_learning_image_to_clipboard'
const TOOL_INSERT_HTML_DRAFT = 'insert_hardware_learning_html_draft'
const TOOL_INSERT_LEARNING_ANNOTATIONS = 'insert_hardware_learning_annotations'
const TOOL_MANAGE_CANVASES = 'manage_hardware_learning_canvases'
const WIDGET_PAYLOAD_TIMEOUT_MS = 5000
// Keep each JSON-RPC tool request comfortably below host message limits. The
// decoded chunk is 36 KiB and the base64 field is 48 KiB before JSON overhead.
const DOWNLOAD_CHUNK_BASE64_LENGTH = 48 * 1024
const DOWNLOAD_TOOL_TIMEOUT_MS = 45_000
const DOWNLOAD_TOOL_MAX_ATTEMPTS = 2

globalThis.__JLC_HARDWARE_LEARNING_WIDGET_FETCH_GUARD__ = true

let activeStorageTarget = null

export const IS_JLC_HARDWARE_LEARNING_WIDGET_BUILD =
  typeof __JLC_HARDWARE_LEARNING_WIDGET_BUILD__ !== 'undefined' && __JLC_HARDWARE_LEARNING_WIDGET_BUILD__

export function hasHardwareLearningWidgetBridge() {
  return Boolean(window.hardwareLearningMcp && typeof window.hardwareLearningMcp.callServerTool === 'function')
}

function currentWidgetPayload() {
  return window.openai?.toolOutput && typeof window.openai.toolOutput === 'object'
    ? window.openai.toolOutput
    : {}
}

function hasWidgetStorageTarget() {
  const payload = currentWidgetPayload()
  return Boolean(activeStorageTarget?.projectDir || activeStorageTarget?.canvasDir || payload.projectDir || payload.canvasDir)
}

function serverToolArgs(extra = {}) {
  const payload = currentWidgetPayload()
  return removeUndefined({
    projectDir: activeStorageTarget?.projectDir || payload.projectDir,
    canvasDir: activeStorageTarget?.canvasDir || payload.canvasDir,
    ...extra
  })
}

export function setHardwareLearningStorageTarget(target = null) {
  activeStorageTarget = target
    ? removeUndefined({ projectDir: target.projectDir, canvasDir: target.canvasDir })
    : null
  return activeStorageTarget
}

export function getHardwareLearningStorageTarget() {
  return activeStorageTarget ? { ...activeStorageTarget } : null
}

function removeUndefined(value) {
  return Object.fromEntries(Object.entries(value).filter(([_key, item]) => item !== undefined))
}

function abortError() {
  return new DOMException('The operation was aborted.', 'AbortError')
}

async function waitForWidgetPayload(signal) {
  if (!hasHardwareLearningWidgetBridge()) return
  if (hasWidgetStorageTarget()) return

  await new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError())
      return
    }

    const timer = window.setTimeout(() => {
      cleanup()
      reject(new Error('JLC Hardware Learning widget storage target was not ready. Refusing to read or write without projectDir/canvasDir.'))
    }, WIDGET_PAYLOAD_TIMEOUT_MS)
    const cleanup = () => {
      window.clearTimeout(timer)
      window.removeEventListener('openai:set_globals', handleGlobals)
      signal?.removeEventListener('abort', handleAbort)
    }
    const finish = () => {
      cleanup()
      resolve()
    }
    const handleGlobals = () => {
      if (hasWidgetStorageTarget()) finish()
    }
    const handleAbort = () => {
      cleanup()
      reject(abortError())
    }

    // Codex publishes host capabilities/theme before the tool result that
    // carries projectDir/canvasDir. Keep listening until the storage target is
    // actually present; a one-shot listener races with that multi-event
    // handshake and leaves a remounted/resized widget permanently unloaded.
    window.addEventListener('openai:set_globals', handleGlobals)
    signal?.addEventListener('abort', handleAbort, { once: true })
  })
}

async function callHardwareLearningServerTool(name, args = {}, options = {}) {
  await waitForWidgetPayload(options.signal)
  if (options.signal?.aborted) throw abortError()
  const result = await window.hardwareLearningMcp.callServerTool({
    name,
    arguments: serverToolArgs(args)
  }, options.timeoutMs ? { timeoutMs: options.timeoutMs } : undefined)
  if (result?.isError) {
    const message = result.content?.find((item) => item.type === 'text')?.text
    throw new Error(message || `JLC Hardware Learning server tool failed: ${name}`)
  }
  return result.structuredContent ?? result
}

async function fetchJson(url, options = {}) {
  const response = await window.fetch(url, options)
  if (!response.ok) {
    throw new Error(`JLC Hardware Learning request failed: ${response.status} - ${response.statusText}`)
  }
  return response.json()
}

export async function loadHardwareLearningCanvasState(signal) {
  if (hasHardwareLearningWidgetBridge()) {
    const state = await callHardwareLearningServerTool(
      TOOL_GET_CANVAS_STATE,
      { hydrateAssets: false },
      { signal }
    )
    return {
      projectDir: state.projectDir,
      canvasDir: state.canvasDir,
      snapshot: state.snapshot,
      viewState: state.viewState ?? null,
      storage: state.storage,
      skippedRecords: []
    }
  }

  const [canvasData, viewStateData] = await Promise.all([
    fetchJson(CANVAS_ENDPOINT, { signal }),
    fetchJson(VIEW_STATE_ENDPOINT, { signal })
  ])
  return {
    snapshot: canvasData.snapshot,
    viewState: viewStateData.viewState ?? null,
    storage: canvasData.storage,
    skippedRecords: []
  }
}

export async function manageHardwareLearningCanvases(action = 'list', options = {}) {
  if (!hasHardwareLearningWidgetBridge()) {
    throw new Error('当前预览环境不支持多个项目画板；请在 Codex 画板中使用。')
  }
  const result = await callHardwareLearningServerTool(TOOL_MANAGE_CANVASES, {
    canvasDir: undefined,
    action,
    canvasId: options.canvasId,
    name: options.name
  })
  return result
}

export async function refreshHardwareLearningCanvasSnapshot(signal) {
  if (hasHardwareLearningWidgetBridge()) {
    const state = await callHardwareLearningServerTool(
      TOOL_GET_CANVAS_STATE,
      { hydrateAssets: false },
      { signal }
    )
    return state.snapshot
  }

  const canvasData = await fetchJson(CANVAS_ENDPOINT, { signal })
  return canvasData.snapshot
}

export async function saveHardwareLearningCanvasSnapshot(snapshot, options = {}) {
  if (hasHardwareLearningWidgetBridge()) {
    return callHardwareLearningServerTool(TOOL_SAVE_CANVAS_STATE, {
      snapshot,
      protectImageRecords: options.protectImageRecords,
      acknowledgedImageShapeDeletes: options.acknowledgedImageShapeDeletes
    })
  }

  return fetchJson(CANVAS_ENDPOINT, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(snapshot)
  })
}

export async function saveHardwareLearningSelectionState(selection) {
  if (hasHardwareLearningWidgetBridge()) {
    return callHardwareLearningServerTool(TOOL_SAVE_SELECTION_STATE, { selection })
  }

  return fetchJson(SELECTION_ENDPOINT, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(selection)
  })
}

export async function saveHardwareLearningViewState(viewState) {
  if (hasHardwareLearningWidgetBridge()) {
    return callHardwareLearningServerTool(TOOL_SAVE_VIEW_STATE, { viewState })
  }

  return fetchJson(VIEW_STATE_ENDPOINT, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(viewState)
  })
}

export async function saveHardwareLearningReferenceImage(reference) {
  if (!hasHardwareLearningWidgetBridge()) {
    throw new Error('当前 JLC Hardware Learning 画布没有可用的 Codex MCP 文件保存桥。')
  }

  return callHardwareLearningServerTool(TOOL_SAVE_REFERENCE_IMAGE, reference)
}

export async function pullHardwareLearningAnnotations(pageId) {
  if (!hasHardwareLearningWidgetBridge()) return { operations: [] }
  return callHardwareLearningServerTool(TOOL_INSERT_LEARNING_ANNOTATIONS, { action: 'pull', pageId })
}

export async function acknowledgeHardwareLearningAnnotations(operationId, commandsSha256) {
  if (!hasHardwareLearningWidgetBridge()) return { ok: false }
  return callHardwareLearningServerTool(TOOL_INSERT_LEARNING_ANNOTATIONS, {
    action: 'acknowledge',
    operationId,
    commandsSha256
  })
}

export async function chooseHardwareLearningExportDirectory() {
  if (!hasHardwareLearningWidgetBridge()) {
    throw new Error('当前预览环境不支持系统文件夹选择；请在 Codex 画板中使用。')
  }
  return callHardwareLearningServerTool(TOOL_CHOOSE_EXPORT_DIRECTORY, {}, {
    timeoutMs: 65_000
  })
}

export async function downloadHardwareLearningFile(download) {
  const { onProgress, ...downloadArgs } = download || {}
  if (!hasHardwareLearningWidgetBridge()) {
    return downloadFileInBrowser(downloadArgs)
  }

  const payload = downloadBase64Payload(downloadArgs)
  if (!payload || payload.base64.length <= DOWNLOAD_CHUNK_BASE64_LENGTH) {
    const result = await callHardwareLearningServerTool(TOOL_DOWNLOAD_FILE, downloadArgs, {
      timeoutMs: DOWNLOAD_TOOL_TIMEOUT_MS
    })
    onProgress?.({ phase: 'finish', sentBytes: payload ? base64ByteLength(payload.base64) : 0, totalBytes: payload ? base64ByteLength(payload.base64) : 0 })
    return result
  }

  const expectedBytes = base64ByteLength(payload.base64)
  let downloadId = typeof globalThis.crypto?.randomUUID === 'function' ? globalThis.crypto.randomUUID() : null
  try {
    const started = await callDownloadToolWithRetry({
      action: 'begin',
      downloadId: downloadId || undefined,
      fileName: downloadArgs.fileName,
      mimeType: downloadArgs.mimeType || payload.mimeType,
      directoryToken: downloadArgs.directoryToken,
      directoryName: downloadArgs.directoryName,
      subdirectory: downloadArgs.subdirectory,
      overwrite: downloadArgs.overwrite,
      uniqueDirectory: downloadArgs.uniqueDirectory,
      expectedBytes
    })
    downloadId = started.downloadId
    if (!downloadId) throw new Error('JLC Hardware Learning 分块导出未返回 downloadId。')
    onProgress?.({ phase: 'begin', sentBytes: 0, totalBytes: expectedBytes })
    let chunkIndex = 0
    let sentBytes = 0
    for (let offset = 0; offset < payload.base64.length; offset += DOWNLOAD_CHUNK_BASE64_LENGTH) {
      const chunkBase64 = payload.base64.slice(offset, offset + DOWNLOAD_CHUNK_BASE64_LENGTH)
      await callDownloadToolWithRetry({
        action: 'append',
        downloadId,
        chunkIndex,
        chunkBase64
      })
      chunkIndex += 1
      sentBytes = Math.min(expectedBytes, sentBytes + base64ByteLength(chunkBase64))
      onProgress?.({
        phase: 'append',
        sentBytes,
        totalBytes: expectedBytes
      })
    }
    const result = await callDownloadToolWithRetry({ action: 'finish', downloadId })
    onProgress?.({ phase: 'finish', sentBytes: expectedBytes, totalBytes: expectedBytes })
    return result
  } catch (error) {
    if (downloadId) {
      await callHardwareLearningServerTool(TOOL_DOWNLOAD_FILE, { action: 'cancel', downloadId }, {
        timeoutMs: DOWNLOAD_TOOL_TIMEOUT_MS
      }).catch(() => undefined)
    }
    throw error
  }
}

async function callDownloadToolWithRetry(args) {
  let lastError = null
  for (let attempt = 1; attempt <= DOWNLOAD_TOOL_MAX_ATTEMPTS; attempt += 1) {
    try {
      return await callHardwareLearningServerTool(TOOL_DOWNLOAD_FILE, args, {
        timeoutMs: DOWNLOAD_TOOL_TIMEOUT_MS
      })
    } catch (error) {
      lastError = error
      if (attempt === DOWNLOAD_TOOL_MAX_ATTEMPTS) break
    }
  }
  throw lastError || new Error('JLC Hardware Learning 导出 Bridge 调用失败。')
}

function downloadBase64Payload(download = {}) {
  if (typeof download.dataBase64 === 'string' && download.dataBase64) {
    return { base64: download.dataBase64, mimeType: download.mimeType || 'application/octet-stream' }
  }
  if (typeof download.dataUrl !== 'string' || !download.dataUrl) return null
  const match = /^data:([^;,]+)?((?:;[^,]*)?),(.*)$/s.exec(download.dataUrl)
  if (!match) throw new Error('导出数据不是有效的 data URL。')
  const mimeType = download.mimeType || match[1] || 'application/octet-stream'
  if (/;base64(?:;|$)/i.test(match[2] || '')) return { base64: match[3], mimeType }
  return { base64: textToBase64(decodeURIComponent(match[3] || '')), mimeType }
}

function base64ByteLength(base64) {
  const normalized = String(base64 || '').replace(/\s+/g, '')
  const padding = normalized.endsWith('==') ? 2 : normalized.endsWith('=') ? 1 : 0
  return Math.max(0, Math.floor(normalized.length * 3 / 4) - padding)
}

function textToBase64(value) {
  const bytes = new TextEncoder().encode(value)
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  }
  return btoa(binary)
}

function downloadFileInBrowser(download = {}) {
  const href = download.dataUrl || (download.dataBase64
    ? `data:${download.mimeType || 'application/octet-stream'};base64,${download.dataBase64}`
    : download.assetUrl)
  if (!href) throw new Error('导出缺少 assetUrl、dataUrl 或 dataBase64。')
  const link = document.createElement('a')
  link.href = href
  link.download = download.fileName || `jlc-hardware-learning-download-${Date.now()}`
  link.hidden = true
  document.body.appendChild(link)
  link.click()
  link.remove()
  return { ok: true, fileName: link.download, browserDownload: true, mimeType: download.mimeType || null }
}

export async function copyHardwareLearningImageToClipboard(image) {
  if (!hasHardwareLearningWidgetBridge()) {
    throw new Error('当前 JLC Hardware Learning 画布没有可用的系统剪贴板桥。')
  }

  return callHardwareLearningServerTool(TOOL_COPY_IMAGE_TO_CLIPBOARD, image)
}

export async function updateHardwareLearningHtmlDraft({ draftShapeId, htmlContent }) {
  if (!hasHardwareLearningWidgetBridge()) {
    return fetchJson('/api/html-draft', {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ draftShapeId, htmlContent })
    })
  }

  return callHardwareLearningServerTool(TOOL_INSERT_HTML_DRAFT, {
    draftShapeId,
    htmlContent,
    updateExistingDraft: true
  })
}

export async function readHardwareLearningPageAsset(assetUrl, options = {}) {
  if (!hasHardwareLearningWidgetBridge()) {
    const response = await window.fetch(assetUrl, { signal: options.signal })
    if (!response.ok) throw new Error(`JLC Hardware Learning 页面资源读取失败：${response.status} ${response.statusText}`)
    const bytes = new Uint8Array(await response.arrayBuffer())
    let binary = ''
    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
    }
    return {
      dataBase64: btoa(binary),
      mimeType: response.headers.get('content-type')?.split(';')[0] || 'application/octet-stream'
    }
  }

  return callHardwareLearningServerTool(TOOL_READ_PAGE_ASSET, { assetUrl }, options)
}
