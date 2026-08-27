import {
  ArrowUpRight,
  BoxSelect,
  Brush,
  Check,
  ChevronDown,
  Circle,
  Clipboard,
  Copy,
  Download,
  Eraser,
  FolderOpen,
  Hand,
  Highlighter,
  LoaderCircle,
  Lock,
  Map as MapIcon,
  Maximize2,
  Menu,
  Minus,
  MoreHorizontal,
  MousePointer2,
  Plus,
  RectangleHorizontal,
  Redo2,
  Shapes,
  StickyNote,
  Trash2,
  Type,
  Undo2,
  Unlock,
  ZoomIn,
  ZoomOut
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'

import {
  acknowledgeHardwareLearningAnnotations,
  chooseHardwareLearningExportDirectory,
  copyHardwareLearningImageToClipboard,
  downloadHardwareLearningFile,
  loadHardwareLearningCanvasState,
  pullHardwareLearningAnnotations,
  readHardwareLearningPageAsset,
  refreshHardwareLearningCanvasSnapshot,
  saveHardwareLearningCanvasSnapshot,
  saveHardwareLearningSelectionState,
  saveHardwareLearningViewState
} from '../hardwareLearningClient.js'
import { applyLearningAnnotationOperations } from './annotations.js'
import {
  addShape,
  createArrowShape,
  createEllipseShape,
  createFrameShape,
  createLineShape,
  createNoteShape,
  createRectangleShape,
  createStrokeShape,
  createTextShape,
  DEFAULT_LEARNING_STYLE,
  deleteLearningShapes,
  deleteSelectedShapes,
  duplicateLearningShapes,
  fitCamera,
  migrateLegacyLearningFrames,
  normalizeCamera,
  normalizeBounds,
  normalizeLearningStyle,
  pageBoundsForShape,
  pageRecords,
  resizeRectangleShape,
  screenToPage,
  selectionState,
  setImageLockState,
  shapeIntersectsViewport,
  shapesForPage,
  styleLearningShapes,
  translateShape,
  unionBounds,
  updateLearningTextShapeContent,
  updateShape,
  updateShapes,
  zoomCameraAt
} from './model.js'
import { createHistoryManager } from './history.js'
import InlineCanvasTextEditor from './InlineCanvasTextEditor.jsx'
import LearningShape from './LearningShape.jsx'
import {
  cameraAfterWheel,
  canMoveCanvasShape,
  completeTextEditPointerActivation,
  escapeAction,
  isSpaceKey,
  isTextEditingTarget,
  learningTextEditMode,
  learningTextEditState,
  movableShapeIds,
  nudgeDeltaForKey,
  rightClickCanvasAction,
  selectionForShapePointerDown,
  shouldBeginCanvasTextFromDoubleClick,
  shouldBeginTextEditFromActivation,
  shouldBeginTextEditFromPointerDown,
  translateCanvasSelection
} from './interaction.js'
import {
  buildLearningCanvasSvg,
  svgDataUrl,
  svgToPngDataUrl,
  textToBase64
} from './export.js'
import { normalizeInlineLearningText, toolAfterInlineTextEdit } from './textEditing.js'
import { observeElementViewportSize } from './viewport.js'
import './styles.css'

const PRIMARY_TOOLS = [
  { id: 'frame', label: '学习框', Icon: BoxSelect },
  { id: 'select', label: '选择', Icon: MousePointer2 },
  { id: 'hand', label: '平移', Icon: Hand },
  { id: 'pen', label: '画笔', Icon: Brush },
  { id: 'eraser', label: '橡皮擦', Icon: Eraser },
  { id: 'text', label: '文本', Icon: Type },
  { id: 'arrow', label: '箭头', Icon: ArrowUpRight },
  { id: 'note', label: '便签', Icon: StickyNote }
]

const MORE_TOOLS = [
  { id: 'rectangle', label: '矩形', Icon: RectangleHorizontal },
  { id: 'ellipse', label: '椭圆', Icon: Circle },
  { id: 'line', label: '直线', Icon: Minus },
  { id: 'highlight', label: '高亮', Icon: Highlighter }
]

const STYLE_COLORS = [
  ['black', '#1f2937'], ['grey', '#64748b'], ['light-violet', '#c4b5fd'],
  ['violet', '#7c3aed'], ['blue', '#2563eb'], ['light-blue', '#38bdf8'],
  ['yellow', '#eab308'], ['orange', '#f97316'], ['green', '#16a34a'],
  ['light-green', '#86efac'], ['light-red', '#fca5a5'], ['red', '#dc2626']
]

const FILL_OPTIONS = [['none', '无'], ['semi', '浅色'], ['solid', '实色']]
const DASH_OPTIONS = [['draw', '手绘'], ['dashed', '虚线'], ['dotted', '点线'], ['solid', '实线']]
const SIZE_OPTIONS = [['s', '小'], ['m', '中'], ['l', '大'], ['xl', '特大']]
const DEFAULT_EXPORT_DIRECTORY_LABEL = '默认：下载/JLC硬件学习画板'
const VIEWPORT_IMAGE_OVERSCAN_PX = 512

const DEFAULT_CAMERA = { x: 0, y: 0, z: 1 }
const EMPTY_VIEW_STATE = { version: 1, currentPageId: null, camera: DEFAULT_CAMERA }

function snapshotSignature(snapshot) {
  return JSON.stringify(snapshot?.store ?? {})
}

function assetDataUrl(asset) {
  return `data:${asset.mimeType};base64,${asset.dataBase64}`
}

function pointerPosition(event, root) {
  const rect = root.getBoundingClientRect()
  return { x: event.clientX - rect.left, y: event.clientY - rect.top }
}

function ToolbarButton({ active = false, disabled = false, label, Icon, onClick, testId }) {
  return (
    <button
      aria-label={label}
      aria-pressed={active ? 'true' : 'false'}
      className="learning-toolbar-button"
      data-active={active ? 'true' : 'false'}
      data-testid={testId}
      disabled={disabled}
      onClick={onClick}
      title={label}
      type="button"
    >
      <Icon aria-hidden="true" size={19} strokeWidth={2} />
    </button>
  )
}

function MenuButton({ active = false, danger = false, disabled = false, label, Icon, onClick, testId, children }) {
  return (
    <button
      aria-label={label}
      className="jlc-learning-icon-button"
      data-active={active ? 'true' : 'false'}
      data-danger={danger ? 'true' : 'false'}
      data-testid={testId}
      disabled={disabled}
      onClick={onClick}
      title={label}
      type="button"
    >
      {Icon && <Icon aria-hidden="true" size={17} strokeWidth={2} />}
      {children}
    </button>
  )
}

function resizeFromHandle(start, point, handle) {
  const corners = {
    nw: [{ x: start.x + start.w, y: start.y + start.h }, point],
    ne: [{ x: start.x, y: start.y + start.h }, point],
    sw: [{ x: start.x + start.w, y: start.y }, point],
    se: [{ x: start.x, y: start.y }, point]
  }
  const [anchor, cursor] = corners[handle]
  return normalizeBounds(anchor, cursor, 12)
}

function timestampFilePart() {
  return new Date().toISOString().replace(/[:.]/g, '-').replace('T', '_').replace('Z', '')
}

export default function HardwareLearningCanvas() {
  const rootRef = useRef(null)
  const snapshotRef = useRef(null)
  const viewRef = useRef(EMPTY_VIEW_STATE)
  const assetSourcesRef = useRef(new Map())
  const remoteSignatureRef = useRef('')
  const saveQueueRef = useRef(Promise.resolve())
  const localMutationRef = useRef(0)
  const selectionRevisionRef = useRef(0)
  const historyRef = useRef(createHistoryManager({ limit: 100 }))
  const annotationPollingRef = useRef(false)
  const spacePressedRef = useRef(false)
  const lastTextEditPointerActivationRef = useRef(null)
  const [snapshot, setSnapshot] = useState(null)
  const [view, setView] = useState(EMPTY_VIEW_STATE)
  const [selectedIds, setSelectedIds] = useState([])
  const [tool, setTool] = useState('select')
  const [style, setStyle] = useState(DEFAULT_LEARNING_STYLE)
  const [gesture, setGesture] = useState(null)
  const [draftShape, setDraftShape] = useState(null)
  const [draftShapes, setDraftShapes] = useState([])
  const [marqueeBounds, setMarqueeBounds] = useState(null)
  const [assetSources, setAssetSources] = useState(new Map())
  const [status, setStatus] = useState({ kind: 'loading', text: '正在加载学习画布…' })
  const [historyVersion, setHistoryVersion] = useState(0)
  const [noteDraft, setNoteDraft] = useState(null)
  const [openMenu, setOpenMenu] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [choosingExportDirectory, setChoosingExportDirectory] = useState(false)
  const [exportDirectory, setExportDirectory] = useState({
    directoryPath: DEFAULT_EXPORT_DIRECTORY_LABEL,
    directoryToken: null
  })
  const [lastExport, setLastExport] = useState(null)
  const [minimapOpen, setMinimapOpen] = useState(false)
  const [spacePanActive, setSpacePanActive] = useState(false)
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 })
  const [pendingDeleteIds, setPendingDeleteIds] = useState([])

  const pages = useMemo(() => pageRecords(snapshot), [snapshot])
  const pageId = view.currentPageId || pages[0]?.id || null
  const camera = view.camera || DEFAULT_CAMERA
  const pageShapes = useMemo(
    () => pageId && snapshot ? shapesForPage(snapshot, pageId) : [],
    [snapshot, pageId]
  )
  const selectedImageIds = useMemo(
    () => selectedIds.filter((id) => snapshot?.store?.[id]?.type === 'image'),
    [selectedIds, snapshot]
  )
  const pendingImageDeleteIds = useMemo(
    () => pendingDeleteIds.filter((id) => snapshot?.store?.[id]?.type === 'image'),
    [pendingDeleteIds, snapshot]
  )
  const pendingAnnotationDeleteIds = useMemo(
    () => pendingDeleteIds.filter((id) => snapshot?.store?.[id]?.typeName === 'shape' && snapshot.store[id]?.type !== 'image'),
    [pendingDeleteIds, snapshot]
  )
  const viewportBounds = useMemo(() => {
    if (viewportSize.width <= 0 || viewportSize.height <= 0) return null
    return {
      x: -camera.x / camera.z,
      y: -camera.y / camera.z,
      w: viewportSize.width / camera.z,
      h: viewportSize.height / camera.z
    }
  }, [camera, viewportSize])
  const viewportImageShapes = useMemo(() => {
    if (!snapshot || !viewportBounds) return []
    const margin = VIEWPORT_IMAGE_OVERSCAN_PX / camera.z
    return pageShapes.filter((shape) => shape.type === 'image' &&
      shapeIntersectsViewport(snapshot.store, shape, viewportBounds, margin))
  }, [snapshot, pageShapes, viewportBounds, camera.z])

  useEffect(() => {
    return observeElementViewportSize(rootRef.current, setViewportSize)
  }, [])

  useEffect(() => {
    if (selectedIds.length !== 1 || !snapshot) return
    const shape = snapshot.store[selectedIds[0]]
    if (!shape || shape.type === 'image') return
    setStyle(normalizeLearningStyle({
      color: shape.props?.color,
      fill: shape.props?.fill,
      dash: shape.props?.dash,
      size: shape.props?.size,
      opacity: shape.opacity
    }))
  }, [selectedIds, snapshot])

  const persistSnapshot = useCallback((next, message = '已保存', saveMetadata = null) => {
    snapshotRef.current = next
    remoteSignatureRef.current = snapshotSignature(next)
    localMutationRef.current = Date.now()
    setSnapshot(next)
    setStatus({ kind: 'saving', text: '正在保存…' })
    const operation = saveQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        const result = await saveHardwareLearningCanvasSnapshot(next, {
          protectImageRecords: true,
          acknowledgedImageShapeDeletes: saveMetadata?.acknowledgedImageShapeDeletes
        })
        if (result?.ok === false) throw new Error(result.message || '学习画布保存被拒绝。')
        return result
      })
    saveQueueRef.current = operation
    operation
      .then(() => {
        if (saveQueueRef.current === operation) setStatus({ kind: 'saved', text: message })
      })
      .catch((error) => {
        console.error(error)
        if (saveQueueRef.current === operation) setStatus({ kind: 'error', text: '保存失败，请重试' })
      })
    return operation
  }, [])

  const commitSnapshot = useCallback((next, options = {}) => {
    const current = snapshotRef.current
    if (!current || next === current) return Promise.resolve()
    const saveMetadata = options.acknowledgedImageShapeDeletes?.length
      ? { acknowledgedImageShapeDeletes: [...new Set(options.acknowledgedImageShapeDeletes)] }
      : null
    if (options.history !== false) {
      if (historyRef.current.record(current, next, options.message, saveMetadata)) {
        setHistoryVersion((value) => value + 1)
      }
    }
    return persistSnapshot(next, options.message, saveMetadata)
  }, [persistSnapshot])

  const setViewState = useCallback((updater) => {
    setView((current) => {
      const next = typeof updater === 'function' ? updater(current) : updater
      const normalized = { ...next, camera: normalizeCamera(next.camera) }
      viewRef.current = normalized
      return normalized
    })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      try {
        const loaded = await loadHardwareLearningCanvasState(controller.signal)
        if (!loaded.snapshot) throw new Error('学习画布尚未初始化。')
        const migration = migrateLegacyLearningFrames(loaded.snapshot)
        const loadedPages = pageRecords(migration.snapshot)
        const requestedPage = loaded.viewState?.currentPageId
        const currentPageId = loadedPages.some((page) => page.id === requestedPage)
          ? requestedPage
          : loadedPages[0]?.id
        const loadedView = {
          version: 1,
          currentPageId,
          camera: normalizeCamera(loaded.viewState?.camera || DEFAULT_CAMERA)
        }
        snapshotRef.current = migration.snapshot
        historyRef.current.clear()
        remoteSignatureRef.current = snapshotSignature(migration.snapshot)
        viewRef.current = loadedView
        setSnapshot(migration.snapshot)
        setView(loadedView)
        setStatus({
          kind: 'saved',
          text: migration.changed ? '学习画布兼容迁移完成' : '学习画布已就绪'
        })
        if (migration.changed) await persistSnapshot(migration.snapshot, '学习画布兼容迁移完成')
      } catch (error) {
        if (error.name === 'AbortError') return
        console.error(error)
        setStatus({ kind: 'error', text: error.message || '学习画布加载失败' })
      }
    }
    load()
    return () => controller.abort()
  }, [persistSnapshot])

  const ensureAssetSources = useCallback(async (targetPageId, { signal, strict = false, shapes } = {}) => {
    const currentSnapshot = snapshotRef.current
    if (!currentSnapshot || !targetPageId) return assetSourcesRef.current
    const missing = []
    const candidates = shapes || shapesForPage(currentSnapshot, targetPageId)
    for (const shape of candidates) {
      if (shape.type !== 'image') continue
      const asset = currentSnapshot.store[shape.props?.assetId]
      const source = asset?.props?.src
      if (!source || assetSourcesRef.current.has(source)) continue
      missing.push(source)
    }
    if (!missing.length) return assetSourcesRef.current
    const entries = await Promise.all(missing.map(async (source) => {
      try {
        if (/^(?:data:|https?:)/i.test(source)) return [source, source]
        const asset = await readHardwareLearningPageAsset(source, { signal })
        return [source, assetDataUrl(asset)]
      } catch (error) {
        if (error.name === 'AbortError' || strict) throw error
        console.error(error)
        return [source, source]
      }
    }))
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    const next = new Map(assetSourcesRef.current)
    for (const [source, resolved] of entries) next.set(source, resolved)
    assetSourcesRef.current = next
    setAssetSources(next)
    return next
  }, [])

  useEffect(() => {
    if (!snapshot || !pageId) return
    const controller = new AbortController()
    ensureAssetSources(pageId, { signal: controller.signal, shapes: viewportImageShapes }).catch((error) => {
      if (error.name !== 'AbortError') console.error(error)
    })
    return () => controller.abort()
  }, [snapshot, pageId, viewportImageShapes, ensureAssetSources])

  useEffect(() => {
    if (!snapshot || !pageId) return
    selectionRevisionRef.current += 1
    const payload = selectionState(snapshot, pageId, selectedIds, selectionRevisionRef.current)
    saveHardwareLearningSelectionState(payload).catch((error) => console.error(error))
  }, [snapshot, pageId, selectedIds])

  useEffect(() => {
    if (!pageId) return
    const timer = window.setTimeout(() => {
      saveHardwareLearningViewState({
        version: 1,
        currentPageId: pageId,
        camera: view.camera,
        updatedAt: new Date().toISOString()
      }).catch((error) => console.error(error))
    }, 300)
    return () => window.clearTimeout(timer)
  }, [pageId, view.camera])

  useEffect(() => {
    if (!pageId) return
    let stopped = false
    async function refresh() {
      if (Date.now() - localMutationRef.current < 1200) return
      try {
        const remote = await refreshHardwareLearningCanvasSnapshot()
        const signature = snapshotSignature(remote)
        if (!stopped && remote && signature !== remoteSignatureRef.current) {
          const migration = migrateLegacyLearningFrames(remote)
          snapshotRef.current = migration.snapshot
          historyRef.current.clear()
          setHistoryVersion((value) => value + 1)
          remoteSignatureRef.current = snapshotSignature(migration.snapshot)
          setSnapshot(migration.snapshot)
          setStatus({ kind: 'saved', text: '已同步外部导入或标注' })
          if (migration.changed) persistSnapshot(migration.snapshot, '外部画布同步完成')
        }
      } catch (error) {
        console.error(error)
      }
    }
    const timer = window.setInterval(refresh, 1600)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [pageId, persistSnapshot])

  useEffect(() => {
    if (!pageId || !snapshot) return
    async function pollAnnotations() {
      if (annotationPollingRef.current) return
      annotationPollingRef.current = true
      try {
        const pulled = await pullHardwareLearningAnnotations(pageId)
        if (!pulled.operations?.length) return
        const applied = applyLearningAnnotationOperations(snapshotRef.current, pageId, pulled.operations)
        if (applied.changed) await commitSnapshot(applied.snapshot, { history: false, message: '教学标注已写入画布' })
        await saveQueueRef.current
        for (const operation of pulled.operations) {
          await acknowledgeHardwareLearningAnnotations(operation.operationId, operation.commandsSha256)
        }
      } catch (error) {
        console.error(error)
      } finally {
        annotationPollingRef.current = false
      }
    }
    pollAnnotations()
    const timer = window.setInterval(pollAnnotations, 1500)
    return () => window.clearInterval(timer)
  }, [pageId, snapshot, commitSnapshot])

  useEffect(() => {
    function keyDown(event) {
      if (isTextEditingTarget(event.target)) return
      if (pendingDeleteIds.length) {
        if (event.key === 'Escape') {
          event.preventDefault()
          setPendingDeleteIds([])
          setStatus({ kind: 'saved', text: '已取消删除' })
        }
        return
      }
      if (isSpaceKey(event)) {
        event.preventDefault()
        if (!spacePressedRef.current) {
          spacePressedRef.current = true
          setSpacePanActive(true)
        }
        return
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        if (!snapshotRef.current || !selectedIds.length) return
        const result = deleteLearningShapes(snapshotRef.current, selectedIds)
        if (result.deleted.length) {
          event.preventDefault()
          setSelectedIds([])
          commitSnapshot(result.snapshot, { message: `已删除 ${result.deleted.length} 个标注` })
        }
        return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) redo()
        else undo()
        return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'd') {
        event.preventDefault()
        duplicateSelected()
        return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
        event.preventDefault()
        setSelectedIds(pageShapes.map((shape) => shape.id))
        return
      }
      if ((event.ctrlKey || event.metaKey) && event.key === '0') {
        event.preventDefault()
        fitContent()
        return
      }
      if ((event.ctrlKey || event.metaKey) && event.key === '1') {
        event.preventDefault()
        zoomTo100()
        return
      }
      if (!event.ctrlKey && !event.metaKey && (event.key === '+' || event.key === '=')) {
        event.preventDefault()
        zoomBy(1.2)
        return
      }
      if (!event.ctrlKey && !event.metaKey && event.key === '-') {
        event.preventDefault()
        zoomBy(1 / 1.2)
        return
      }
      if (event.key === 'Escape') {
        event.preventDefault()
        const action = escapeAction({
          hasGesture: Boolean(gesture),
          openMenu,
          tool,
          selectedCount: selectedIds.length
        })
        if (action === 'cancel-gesture') cancelActiveGesture()
        if (action === 'close-menu') setOpenMenu(null)
        if (action === 'clear-selection') setSelectedIds([])
        setTool('select')
        return
      }
      if (event.key === 'Enter' && !event.ctrlKey && !event.metaKey && !event.altKey && selectedIds.length === 1) {
        const selectedShape = snapshotRef.current?.store?.[selectedIds[0]]
        if (beginShapeTextEdit(selectedShape)) {
          event.preventDefault()
          return
        }
      }
      const nudge = !event.ctrlKey && !event.metaKey && !event.altKey
        ? nudgeDeltaForKey(event.key, { shiftKey: event.shiftKey })
        : null
      if (nudge && snapshotRef.current && selectedIds.length) {
        event.preventDefault()
        const result = translateCanvasSelection(snapshotRef.current, selectedIds, nudge)
        if (result.updated.length) {
          commitSnapshot(result.snapshot, {
            message: `已移动 ${result.updated.length} 个对象`
          })
        } else {
          setStatus({ kind: 'saved', text: '锁定的原理图不能移动' })
        }
        return
      }
      const shortcut = {
        v: 'select', h: 'hand', f: 'frame', d: 'pen', e: 'eraser', t: 'text',
        a: 'arrow', n: 'note', r: 'rectangle', o: 'ellipse', l: 'line', k: 'highlight'
      }[event.key.toLowerCase()]
      if (shortcut && !event.ctrlKey && !event.metaKey) setTool(shortcut)
    }
    function keyUp(event) {
      if (!isSpaceKey(event)) return
      spacePressedRef.current = false
      setSpacePanActive(false)
    }
    function windowBlur() {
      spacePressedRef.current = false
      setSpacePanActive(false)
      if (gesture) cancelActiveGesture()
    }
    window.addEventListener('keydown', keyDown)
    window.addEventListener('keyup', keyUp)
    window.addEventListener('blur', windowBlur)
    return () => {
      window.removeEventListener('keydown', keyDown)
      window.removeEventListener('keyup', keyUp)
      window.removeEventListener('blur', windowBlur)
    }
  })

  const undo = useCallback(() => {
    if (!snapshotRef.current) return
    const result = historyRef.current.undo(snapshotRef.current)
    if (!result) return
    setHistoryVersion((value) => value + 1)
    setSelectedIds([])
    persistSnapshot(result.snapshot, `已撤销：${result.label}`)
  }, [persistSnapshot])

  const redo = useCallback(() => {
    if (!snapshotRef.current) return
    const result = historyRef.current.redo(snapshotRef.current)
    if (!result) return
    setHistoryVersion((value) => value + 1)
    setSelectedIds([])
    persistSnapshot(result.snapshot, `已重做：${result.label}`, result.metadata)
  }, [persistSnapshot])

  const fitContent = useCallback((ids = [], targetPageId = pageId) => {
    if (!rootRef.current || !snapshotRef.current || !targetPageId) return
    const candidates = ids.length
      ? ids.map((id) => snapshotRef.current.store[id]).filter(Boolean)
      : shapesForPage(snapshotRef.current, targetPageId)
    const bounds = unionBounds(candidates.map((shape) => pageBoundsForShape(snapshotRef.current.store, shape)))
    const rect = rootRef.current.getBoundingClientRect()
    setViewState((current) => ({
      ...current,
      camera: fitCamera(bounds, { width: rect.width, height: rect.height })
    }))
  }, [pageId, setViewState])

  function zoomBy(factor) {
    if (!rootRef.current) return
    const center = { x: rootRef.current.clientWidth / 2, y: rootRef.current.clientHeight / 2 }
    setViewState((current) => ({
      ...current,
      camera: zoomCameraAt(current.camera, center, current.camera.z * factor)
    }))
  }

  function zoomTo100() {
    if (!rootRef.current) return
    const center = { x: rootRef.current.clientWidth / 2, y: rootRef.current.clientHeight / 2 }
    setViewState((current) => ({ ...current, camera: zoomCameraAt(current.camera, center, 1) }))
  }

  function duplicateSelected() {
    if (!snapshotRef.current || !selectedIds.length) return
    const result = duplicateLearningShapes(snapshotRef.current, selectedIds)
    if (!result.duplicated.length) {
      setStatus({ kind: 'saved', text: '原理图底图受保护，不能复制' })
      return
    }
    setSelectedIds(result.duplicated)
    commitSnapshot(result.snapshot, { message: `已复制 ${result.duplicated.length} 个标注` })
  }

  function deleteSelected() {
    if (!snapshotRef.current || !selectedIds.length) return
    const imageIds = selectedIds.filter((id) => snapshotRef.current.store[id]?.type === 'image')
    if (imageIds.length) {
      setOpenMenu(null)
      setPendingDeleteIds([...new Set(selectedIds)])
      return
    }
    const result = deleteLearningShapes(snapshotRef.current, selectedIds)
    if (!result.deleted.length) {
      setStatus({ kind: 'saved', text: '原理图底图受保护，不能删除' })
      return
    }
    setSelectedIds([])
    commitSnapshot(result.snapshot, { message: `已删除 ${result.deleted.length} 个标注` })
  }

  function cancelSelectedDeletion() {
    setPendingDeleteIds([])
    setStatus({ kind: 'saved', text: '已取消删除' })
  }

  function confirmSelectedDeletion() {
    if (!snapshotRef.current || !pendingDeleteIds.length || !pendingImageDeleteIds.length) return
    const result = deleteSelectedShapes(snapshotRef.current, pendingDeleteIds, { includeImages: true })
    setPendingDeleteIds([])
    if (!result.deleted.length) {
      setStatus({ kind: 'saved', text: '选中的内容已不存在，无需删除' })
      return
    }
    setSelectedIds((current) => current.filter((id) => !result.deleted.includes(id)))
    const summary = [
      result.deletedImages.length ? `${result.deletedImages.length} 张原理图` : '',
      result.deletedAnnotations.length ? `${result.deletedAnnotations.length} 个标注` : ''
    ].filter(Boolean).join('和')
    commitSnapshot(result.snapshot, {
      message: `已删除 ${summary}；可撤销恢复`,
      acknowledgedImageShapeDeletes: result.deletedImages
    })
  }

  function toggleSelectedImageLock() {
    if (!snapshotRef.current) return
    const imageIds = selectedIds.filter((id) => snapshotRef.current.store[id]?.type === 'image')
    if (!imageIds.length) return
    const shouldLock = imageIds.some((id) => snapshotRef.current.store[id]?.isLocked !== true)
    const result = setImageLockState(snapshotRef.current, imageIds, shouldLock)
    if (!result.updated.length) return
    commitSnapshot(result.snapshot, {
      message: shouldLock
        ? `已锁定 ${result.updated.length} 张原理图`
        : `已解锁 ${result.updated.length} 张原理图，可拖动调整位置`
    })
  }

  function applyStyle(stylePatch) {
    const nextStyle = normalizeLearningStyle({ ...style, ...stylePatch })
    setStyle(nextStyle)
    if (noteDraft) {
      setNoteDraft((current) => current
        ? { ...current, style: normalizeLearningStyle({ ...current.style, ...stylePatch }) }
        : current)
      return
    }
    if (!snapshotRef.current || !selectedIds.length) return
    const result = styleLearningShapes(snapshotRef.current, selectedIds, stylePatch)
    if (result.updated.length) {
      commitSnapshot(result.snapshot, { message: `已更新 ${result.updated.length} 个对象的样式` })
    } else {
      setStatus({ kind: 'saved', text: '原理图底图受保护；新样式将用于下一项标注' })
    }
  }

  function chooseTool(nextTool) {
    lastTextEditPointerActivationRef.current = null
    setTool(nextTool)
    setGesture(null)
    setDraftShape(null)
    setDraftShapes([])
    setMarqueeBounds(null)
    setOpenMenu(null)
  }

  function cancelActiveGesture() {
    if (gesture?.pointerId !== undefined && rootRef.current?.hasPointerCapture?.(gesture.pointerId)) {
      rootRef.current.releasePointerCapture(gesture.pointerId)
    }
    setGesture(null)
    setDraftShape(null)
    setDraftShapes([])
    setMarqueeBounds(null)
  }

  function startPointerGesture(event, type, data = {}) {
    rootRef.current?.setPointerCapture?.(event.pointerId)
    setGesture({ type, pointerId: event.pointerId, ...data })
  }

  function beginInlineTextAtPoint(point, mode, { armTool = false } = {}) {
    const draft = {
      point,
      text: '',
      mode,
      style: mode === 'note'
        ? normalizeLearningStyle({ color: 'yellow', fill: 'solid', dash: 'solid', size: style.size, opacity: style.opacity })
        : style
    }
    lastTextEditPointerActivationRef.current = null
    setGesture(null)
    setDraftShape(null)
    setDraftShapes([])
    setMarqueeBounds(null)
    setOpenMenu(null)
    flushSync(() => {
      if (armTool) setTool(mode)
      setNoteDraft(draft)
    })
    const input = rootRef.current?.querySelector('[data-jlc-learning-inline-editor="true"]')
    input?.focus({ preventScroll: true })
  }

  function exitCanvasModeFromRightClick() {
    lastTextEditPointerActivationRef.current = null
    if (noteDraft) {
      cancelTextEdit()
      return
    }
    cancelActiveGesture()
    setOpenMenu(null)
    setTool('select')
    setStatus({ kind: 'saved', text: '已退出当前模式并返回选择' })
  }

  function handleCanvasPointerDown(event) {
    if (!rootRef.current || !snapshot || !pageId) return
    const rightClickAction = event.button === 2
      ? rightClickCanvasAction({ tool, hasTextDraft: Boolean(noteDraft), hasGesture: Boolean(gesture) })
      : null
    if (rightClickAction && rightClickAction !== 'pan') {
      event.preventDefault()
      exitCanvasModeFromRightClick()
      return
    }
    if (noteDraft) return
    lastTextEditPointerActivationRef.current = null
    const screen = pointerPosition(event, rootRef.current)
    const page = screenToPage(screen, camera)
    if (event.button === 1 || event.button === 2 || tool === 'hand' || spacePressedRef.current || event.altKey) {
      event.preventDefault()
      startPointerGesture(event, 'pan', { startScreen: screen, startCamera: camera })
      return
    }
    if (event.button !== 0) return
    if (tool === 'select') {
      const baseSelection = event.shiftKey ? selectedIds : []
      if (!event.shiftKey) setSelectedIds([])
      startPointerGesture(event, 'marquee', { startPage: page, currentPage: page, baseSelection })
      return
    }
    if (tool === 'note' || tool === 'text') {
      event.preventDefault()
      beginInlineTextAtPoint(page, tool)
      return
    }
    if (['frame', 'arrow', 'line', 'rectangle', 'ellipse'].includes(tool)) {
      startPointerGesture(event, tool, { startPage: page, currentPage: page })
      return
    }
    if (tool === 'pen' || tool === 'highlight') {
      startPointerGesture(event, 'stroke', { kind: tool, points: [page] })
    }
  }

  function handleShapePointerDown(event, shape) {
    if (!rootRef.current) return
    if (event.button !== 0 || tool === 'hand' || spacePressedRef.current || event.altKey) return
    if (noteDraft) return
    if (tool === 'eraser') {
      event.stopPropagation()
      if (shape.type === 'image') {
        setStatus({ kind: 'saved', text: '原理图底图受保护，不能擦除' })
        return
      }
      const result = deleteLearningShapes(snapshotRef.current, [shape.id])
      if (result.deleted.length) {
        setSelectedIds((current) => current.filter((id) => id !== shape.id))
        commitSnapshot(result.snapshot, { message: '标注已擦除' })
      }
      return
    }
    const textKind = learningTextEditMode(shape)
    if ((tool === 'text' && textKind === 'text') || (tool === 'note' && textKind === 'note')) {
      event.preventDefault()
      event.stopPropagation()
      beginShapeTextEdit(shape)
      return
    }
    if (tool !== 'select') return
    event.stopPropagation()
    const screen = pointerPosition(event, rootRef.current)
    const previousActivation = lastTextEditPointerActivationRef.current
    lastTextEditPointerActivationRef.current = null
    if (shouldBeginTextEditFromPointerDown(shape, previousActivation, {
      altKey: event.altKey,
      button: event.button,
      ctrlKey: event.ctrlKey,
      metaKey: event.metaKey,
      point: screen,
      pointerType: event.pointerType,
      shiftKey: event.shiftKey,
      timeStamp: event.timeStamp
    })) {
      event.preventDefault()
      beginShapeTextEdit(shape)
      return
    }
    const page = screenToPage(screen, camera)
    const nextSelection = selectionForShapePointerDown(selectedIds, shape.id, { shiftKey: event.shiftKey })
    setSelectedIds(nextSelection)
    if (event.shiftKey) return
    if (shape.type === 'image' && shape.isLocked === true) {
      setStatus({ kind: 'saved', text: '原理图已锁定；点击上方解锁按钮后可移动' })
      return
    }
    if (canMoveCanvasShape(shape)) {
      const dragIds = movableShapeIds(snapshotRef.current, nextSelection)
      const originalShapes = dragIds.map((id) => snapshotRef.current.store[id]).filter(Boolean)
      if (originalShapes.length) {
        startPointerGesture(event, 'move', {
          startPage: page,
          originalShapes,
          textEditActivationCandidate: textKind
            ? {
                shapeId: shape.id,
                point: screen,
                pointerType: event.pointerType,
                timeStamp: event.timeStamp
              }
            : null
        })
      }
    }
  }

  function beginShapeTextEdit(shape) {
    const editState = learningTextEditState(shape)
    if (!editState) return false
    lastTextEditPointerActivationRef.current = null
    setGesture(null)
    setDraftShape(null)
    setDraftShapes([])
    setMarqueeBounds(null)
    setOpenMenu(null)
    flushSync(() => {
      setSelectedIds([shape.id])
      setTool(toolAfterInlineTextEdit(editState.mode))
      setNoteDraft({
        ...editState,
        style: normalizeLearningStyle({
          color: shape.props?.color,
          fill: shape.props?.fill,
          dash: shape.props?.dash,
          size: shape.props?.size,
          opacity: shape.opacity
        })
      })
    })
    return true
  }

  function handleShapeDoubleClick(event, shape) {
    if (!shouldBeginTextEditFromActivation(shape, { eventType: 'dblclick', detail: event.detail })) return
    event.preventDefault()
    event.stopPropagation()
    if (noteDraft?.shapeId !== shape.id) beginShapeTextEdit(shape)
  }

  function handleCanvasDoubleClick(event) {
    if (!rootRef.current || !snapshot || !pageId || noteDraft) return
    const shapeElement = event.target?.closest?.('[data-shape-id]')
    const targetShape = shapeElement?.dataset?.shapeId ? snapshot.store[shapeElement.dataset.shapeId] : null
    const targetIsControl = Boolean(event.target?.closest?.('[data-jlc-learning-canvas-control="true"]'))
    if (!shouldBeginCanvasTextFromDoubleClick({
      tool,
      button: event.button,
      detail: event.detail,
      targetIsText: Boolean(learningTextEditMode(targetShape)),
      targetIsControl,
      shiftKey: event.shiftKey,
      ctrlKey: event.ctrlKey,
      metaKey: event.metaKey,
      altKey: event.altKey
    })) return
    event.preventDefault()
    event.stopPropagation()
    const page = screenToPage(pointerPosition(event, rootRef.current), camera)
    setSelectedIds([])
    beginInlineTextAtPoint(page, 'text', { armTool: true })
    setStatus({ kind: 'saved', text: '双击位置已进入文字输入；右键可退出并返回选择' })
  }

  function handleCanvasContextMenu(event) {
    event.preventDefault()
    const action = rightClickCanvasAction({ tool, hasTextDraft: Boolean(noteDraft), hasGesture: Boolean(gesture) })
    if (action !== 'pan') exitCanvasModeFromRightClick()
  }

  function handlePointerMove(event) {
    if (!gesture || !rootRef.current || gesture.pointerId !== event.pointerId) return
    const screen = pointerPosition(event, rootRef.current)
    const page = screenToPage(screen, camera)
    if (gesture.type === 'pan') {
      const delta = { x: screen.x - gesture.startScreen.x, y: screen.y - gesture.startScreen.y }
      setViewState((current) => ({
        ...current,
        camera: { ...gesture.startCamera, x: gesture.startCamera.x + delta.x, y: gesture.startCamera.y + delta.y }
      }))
      return
    }
    if (gesture.type === 'marquee') {
      setMarqueeBounds(normalizeBounds(gesture.startPage, page, 0))
      setGesture({ ...gesture, currentPage: page })
      return
    }
    if (gesture.type === 'frame') {
      const bounds = normalizeBounds(gesture.startPage, page)
      setDraftShape(createFrameShape({ snapshot, pageId, bounds, style, id: 'shape:jlc-learning-frame-preview', index: 'a0' }))
      setGesture({ ...gesture, currentPage: page })
      return
    }
    if (gesture.type === 'arrow') {
      setDraftShape(createArrowShape({ snapshot, pageId, start: gesture.startPage, end: page, style, id: 'shape:jlc-learning-arrow-preview', index: 'a0' }))
      setGesture({ ...gesture, currentPage: page })
      return
    }
    if (gesture.type === 'line') {
      setDraftShape(createLineShape({ snapshot, pageId, start: gesture.startPage, end: page, style, id: 'shape:jlc-learning-line-preview', index: 'a0' }))
      setGesture({ ...gesture, currentPage: page })
      return
    }
    if (gesture.type === 'rectangle' || gesture.type === 'ellipse') {
      const bounds = normalizeBounds(gesture.startPage, page)
      setDraftShape(gesture.type === 'ellipse'
        ? createEllipseShape({ snapshot, pageId, bounds, style, id: 'shape:jlc-learning-ellipse-preview', index: 'a0' })
        : createRectangleShape({ snapshot, pageId, bounds, style, id: 'shape:jlc-learning-rectangle-preview', index: 'a0' }))
      setGesture({ ...gesture, currentPage: page })
      return
    }
    if (gesture.type === 'stroke') {
      const last = gesture.points.at(-1)
      if (Math.hypot(page.x - last.x, page.y - last.y) < 2 / camera.z) return
      const points = [...gesture.points, page]
      setGesture({ ...gesture, points })
      if (points.length > 1) {
        setDraftShape(createStrokeShape({ snapshot, pageId, points, kind: gesture.kind, style, id: 'shape:jlc-learning-stroke-preview', index: 'a0' }))
      }
      return
    }
    if (gesture.type === 'move') {
      const delta = { x: page.x - gesture.startPage.x, y: page.y - gesture.startPage.y }
      setDraftShape(null)
      setDraftShapes(gesture.originalShapes.map((shape) => translateShape(shape, delta)))
      return
    }
    if (gesture.type === 'resize') {
      const bounds = resizeFromHandle(gesture.startBounds, page, gesture.handle)
      setDraftShape(resizeRectangleShape(gesture.originalShape, bounds))
    }
  }

  function finishGesture(event) {
    if (!gesture || gesture.pointerId !== event.pointerId || !snapshotRef.current) return
    rootRef.current?.releasePointerCapture?.(event.pointerId)
    if (['move', 'resize'].includes(gesture.type) && gesture.textEditActivationCandidate && rootRef.current) {
      lastTextEditPointerActivationRef.current = completeTextEditPointerActivation(
        gesture.textEditActivationCandidate,
        {
          point: pointerPosition(event, rootRef.current),
          pointerType: event.pointerType,
          timeStamp: event.timeStamp
        }
      )
    }
    let created = null
    let next = snapshotRef.current
    if (gesture.type === 'marquee') {
      const bounds = marqueeBounds ?? normalizeBounds(gesture.startPage, gesture.currentPage, 0)
      if (bounds.w > 3 / camera.z || bounds.h > 3 / camera.z) {
        const matches = pageShapes
          .filter((shape) => {
            const shapeBounds = pageBoundsForShape(next.store, shape)
            return shapeBounds.x <= bounds.x + bounds.w && shapeBounds.x + shapeBounds.w >= bounds.x &&
              shapeBounds.y <= bounds.y + bounds.h && shapeBounds.y + shapeBounds.h >= bounds.y
          })
          .map((shape) => shape.id)
        setSelectedIds([...new Set([...(gesture.baseSelection || []), ...matches])])
      }
      setGesture(null)
      setMarqueeBounds(null)
      return
    }
    if (gesture.type === 'frame' && draftShape) created = createFrameShape({ snapshot: next, pageId, bounds: { x: draftShape.x, y: draftShape.y, w: draftShape.props.w, h: draftShape.props.h }, style })
    if (gesture.type === 'arrow' && draftShape) {
      created = createArrowShape({
        snapshot: next,
        pageId,
        start: gesture.startPage,
        end: gesture.currentPage,
        style
      })
    }
    if (gesture.type === 'line' && draftShape) {
      created = createLineShape({ snapshot: next, pageId, start: gesture.startPage, end: gesture.currentPage, style })
    }
    if (gesture.type === 'rectangle' && draftShape) {
      created = createRectangleShape({ snapshot: next, pageId, bounds: { x: draftShape.x, y: draftShape.y, w: draftShape.props.w, h: draftShape.props.h }, style })
    }
    if (gesture.type === 'ellipse' && draftShape) {
      created = createEllipseShape({ snapshot: next, pageId, bounds: { x: draftShape.x, y: draftShape.y, w: draftShape.props.w, h: draftShape.props.h }, style })
    }
    if (gesture.type === 'stroke' && gesture.points.length > 1) {
      created = createStrokeShape({ snapshot: next, pageId, points: gesture.points, kind: gesture.kind, style })
    }
    if (created) {
      next = addShape(next, created)
      setSelectedIds([created.id])
      commitSnapshot(next, { message: created.meta.hardwareLearningFrame ? '学习框已保存，可在对话栏提问' : '标注已保存' })
    } else if (gesture.type === 'move' && draftShapes.length) {
      commitSnapshot(updateShapes(next, draftShapes), {
        message: `已移动 ${draftShapes.length} 个对象`
      })
    } else if (gesture.type === 'resize' && draftShape) {
      commitSnapshot(updateShape(next, draftShape), {
        message: '标注大小已更新'
      })
    }
    setGesture(null)
    setDraftShape(null)
    setDraftShapes([])
  }

  const handleWheel = useCallback((event) => {
    if (!rootRef.current) return
    event.preventDefault()
    const screen = pointerPosition(event, rootRef.current)
    const wheel = {
      ctrlKey: event.ctrlKey,
      deltaMode: event.deltaMode,
      deltaX: event.deltaX,
      deltaY: event.deltaY,
      metaKey: event.metaKey,
      shiftKey: event.shiftKey
    }
    const viewport = {
      width: rootRef.current.clientWidth,
      height: rootRef.current.clientHeight
    }
    setViewState((current) => ({
      ...current,
      camera: cameraAfterWheel(current.camera, wheel, screen, viewport).camera
    }))
  }, [setViewState])

  useEffect(() => {
    const viewport = rootRef.current
    if (!viewport) return undefined
    viewport.addEventListener('wheel', handleWheel, { passive: false })
    return () => viewport.removeEventListener('wheel', handleWheel)
  }, [handleWheel])

  function handlePointerCancel(event) {
    if (!gesture || gesture.pointerId !== event.pointerId) return
    lastTextEditPointerActivationRef.current = null
    cancelActiveGesture()
    setTool('select')
    setStatus({ kind: 'saved', text: '已取消未完成的操作' })
  }

  function handleResizePointerDown(event, shape, handle) {
    event.stopPropagation()
    if (!rootRef.current) return
    const screen = pointerPosition(event, rootRef.current)
    const previousActivation = lastTextEditPointerActivationRef.current
    lastTextEditPointerActivationRef.current = null
    if (shouldBeginTextEditFromPointerDown(shape, previousActivation, {
      altKey: event.altKey,
      button: event.button,
      ctrlKey: event.ctrlKey,
      metaKey: event.metaKey,
      point: screen,
      pointerType: event.pointerType,
      shiftKey: event.shiftKey,
      timeStamp: event.timeStamp
    })) {
      event.preventDefault()
      beginShapeTextEdit(shape)
      return
    }
    const bounds = pageBoundsForShape(snapshot.store, shape)
    const textKind = learningTextEditMode(shape)
    startPointerGesture(event, 'resize', {
      originalShape: shape,
      startBounds: bounds,
      handle,
      textEditActivationCandidate: textKind
        ? {
            shapeId: shape.id,
            point: screen,
            pointerType: event.pointerType,
            timeStamp: event.timeStamp
          }
        : null
    })
  }

  function cancelTextEdit() {
    const mode = noteDraft?.mode
    const wasExisting = Boolean(noteDraft?.shapeId)
    setNoteDraft(null)
    setTool(toolAfterInlineTextEdit(mode, 'cancel'))
    setStatus({
      kind: 'saved',
      text: wasExisting ? '已取消编辑，保留原文字' : '已取消新建文字'
    })
  }

  function saveNote() {
    if (!noteDraft || !snapshotRef.current || !pageId) return
    const text = normalizeInlineLearningText(noteDraft.text)
    if (!text.trim()) {
      const wasExisting = Boolean(noteDraft.shapeId)
      setNoteDraft(null)
      setTool(toolAfterInlineTextEdit(noteDraft.mode))
      setStatus({
        kind: 'saved',
        text: wasExisting ? '内容为空，保留原文字并保持当前工具' : '空文字未保存，可继续单击输入'
      })
      return
    }
    if (noteDraft.shapeId) {
      const original = snapshotRef.current.store[noteDraft.shapeId]
      const updated = updateLearningTextShapeContent(original, text, noteDraft.style)
      commitSnapshot(updateShape(snapshotRef.current, updated), {
        message: noteDraft.mode === 'note' ? '便签已更新，可继续使用便签工具' : '文字已更新，可继续使用文本工具'
      })
      setSelectedIds([updated.id])
    } else {
      const shape = noteDraft.mode === 'text'
        ? createTextShape({ snapshot: snapshotRef.current, pageId, point: noteDraft.point, text, style: noteDraft.style })
        : createNoteShape({ snapshot: snapshotRef.current, pageId, point: noteDraft.point, text, style: noteDraft.style })
      commitSnapshot(addShape(snapshotRef.current, shape), {
        message: noteDraft.mode === 'note' ? '便签已保存，可继续单击创建' : '文字已保存，可继续单击创建'
      })
      setSelectedIds([shape.id])
    }
    setTool(toolAfterInlineTextEdit(noteDraft.mode))
    setNoteDraft(null)
  }

  async function exportCanvas(kind, selectedOnly = false) {
    if (!snapshotRef.current || !pageId || exporting) return
    setExporting(true)
    setOpenMenu(null)
    setStatus({ kind: 'saving', text: '正在准备导出…' })
    let lastReportedProgress = -1
    const downloadExportFile = (args) => downloadHardwareLearningFile({
      ...args,
      ...(exportDirectory.directoryToken
        ? { directoryToken: exportDirectory.directoryToken }
        : { directoryName: 'JLC硬件学习画板' }),
      onProgress: ({ sentBytes, totalBytes }) => {
        if (!totalBytes) return
        const progress = Math.min(100, Math.floor(sentBytes * 100 / totalBytes))
        if (progress < 100 && progress < lastReportedProgress + 5) return
        lastReportedProgress = progress
        setStatus({ kind: 'saving', text: `正在写入下载文件 ${progress}%…` })
      }
    })
    try {
      await new Promise((resolve) => requestAnimationFrame(resolve))
      const selectedShapeIds = selectedOnly ? selectedIds : []
      const filePart = timestampFilePart()
      let exportResult = null
      if (kind === 'json') {
        const json = `${JSON.stringify(snapshotRef.current, null, 2)}\n`
        exportResult = await downloadExportFile({
          dataBase64: textToBase64(json),
          fileName: `jlc-hardware-learning-canvas-${filePart}.json`,
          mimeType: 'application/json'
        })
      } else {
        await ensureAssetSources(pageId, { strict: true })
        const result = buildLearningCanvasSvg({
          snapshot: snapshotRef.current,
          pageId,
          assetSources: assetSourcesRef.current,
          selectedShapeIds
        })
        if (kind === 'svg') {
          exportResult = await downloadExportFile({
            dataUrl: svgDataUrl(result.svg),
            fileName: `jlc-hardware-learning-${selectedOnly ? 'selection' : 'page'}-${filePart}.svg`,
            mimeType: 'image/svg+xml'
          })
        } else {
          const png = await svgToPngDataUrl(result.svg, result.bounds)
          if (kind === 'clipboard') {
            await copyHardwareLearningImageToClipboard({ dataUrl: png.dataUrl, mimeType: 'image/png' })
          } else {
            exportResult = await downloadExportFile({
              dataUrl: png.dataUrl,
              fileName: `jlc-hardware-learning-${selectedOnly ? 'selection' : 'page'}-${filePart}.png`,
              mimeType: 'image/png'
            })
          }
        }
      }
      if (kind === 'clipboard') {
        setStatus({ kind: 'saved', text: '已复制 PNG 到剪贴板' })
      } else {
        const filePath = exportResult?.filePath
        const browserLocation = exportResult?.browserDownload && exportResult?.fileName
          ? `浏览器下载：${exportResult.fileName}`
          : null
        const exportLocation = filePath || browserLocation
        if (!exportLocation) throw new Error('导出服务没有返回文件保存位置。')
        setLastExport({ fileName: exportResult.fileName, filePath: exportLocation })
        setStatus({ kind: 'saved', text: `已导出到：${exportLocation}` })
      }
    } catch (error) {
      console.error(error)
      setStatus({ kind: 'error', text: `导出失败：${error.message}` })
    } finally {
      setExporting(false)
    }
  }

  async function chooseExportDirectory() {
    if (choosingExportDirectory || exporting) return
    setChoosingExportDirectory(true)
    setStatus({ kind: 'saving', text: '正在选择导出位置…' })
    try {
      const result = await chooseHardwareLearningExportDirectory()
      if (result?.canceled) {
        setStatus({ kind: 'saved', text: '已取消选择，保留原导出位置' })
        return
      }
      if (!result?.directoryToken || !result?.directoryPath) {
        throw new Error('目录选择服务没有返回可用位置。')
      }
      setExportDirectory({
        directoryPath: result.directoryPath,
        directoryToken: result.directoryToken
      })
      setStatus({ kind: 'saved', text: `导出位置：${result.directoryPath}` })
    } catch (error) {
      console.error(error)
      setStatus({ kind: 'error', text: `无法选择导出位置：${error.message}` })
    } finally {
      setChoosingExportDirectory(false)
      setOpenMenu('export')
    }
  }

  function resetExportDirectory() {
    setExportDirectory({ directoryPath: DEFAULT_EXPORT_DIRECTORY_LABEL, directoryToken: null })
    setStatus({ kind: 'saved', text: '已恢复默认导出位置' })
    setOpenMenu('export')
  }

  async function copyLastExportPath() {
    if (!lastExport?.filePath) return
    try {
      await navigator.clipboard.writeText(lastExport.filePath)
      setStatus({ kind: 'saved', text: '导出路径已复制' })
    } catch (error) {
      console.error(error)
      setStatus({ kind: 'error', text: `无法复制路径：${error.message}` })
    }
  }

  const previewById = new Map(draftShapes.map((shape) => [shape.id, shape]))
  if (draftShape) previewById.set(draftShape.id, draftShape)
  const selectedShape = selectedIds.length === 1 ? snapshot?.store?.[selectedIds[0]] : null
  const selectedBounds = selectedShape && pageBoundsForShape(snapshot.store, previewById.get(selectedShape.id) || selectedShape)
  const selectionBounds = snapshot && unionBounds(selectedIds
    .map((id) => previewById.get(id) || snapshot.store[id])
    .filter(Boolean)
    .map((shape) => pageBoundsForShape(snapshot.store, shape)))
  const visibleShapes = pageShapes.map((shape) => previewById.get(shape.id) || shape)
  if (draftShape && !snapshot?.store?.[draftShape.id]) visibleShapes.push(draftShape)
  const viewportMargin = viewportBounds ? VIEWPORT_IMAGE_OVERSCAN_PX / camera.z : 0
  const renderedShapes = visibleShapes.filter((shape) => shape.type !== 'image' ||
    (viewportBounds && shapeIntersectsViewport(snapshot.store, shape, viewportBounds, viewportMargin)))
  const canUndo = historyVersion >= 0 && historyRef.current.canUndo
  const canRedo = historyVersion >= 0 && historyRef.current.canRedo
  const effectiveTool = spacePanActive ? 'hand' : tool
  const contentBounds = snapshot && unionBounds(pageShapes.map((shape) => pageBoundsForShape(snapshot.store, shape)))
  const panelStyle = noteDraft?.style ? normalizeLearningStyle(noteDraft.style) : style
  const gridStep = Math.max(2, 28 * camera.z)
  const gridOriginX = ((camera.x % gridStep) + gridStep) % gridStep
  const gridOriginY = ((camera.y % gridStep) + gridStep) % gridStep

  return (
    <main className="learning-canvas-shell" data-engine="jlc-hardware-learning-canvas-v1">
      <section
        className={`learning-canvas-viewport tool-${effectiveTool}`}
        onContextMenu={handleCanvasContextMenu}
        onDoubleClick={handleCanvasDoubleClick}
        onPointerDown={handleCanvasPointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishGesture}
        onPointerCancel={handlePointerCancel}
        ref={rootRef}
      >
        {snapshot && pageId ? (
          <svg
            aria-label="硬件学习画布"
            className="learning-canvas-svg"
            data-rendered-image-count={renderedShapes.filter((shape) => shape.type === 'image').length}
            data-testid="learning-canvas-svg"
          >
            <defs>
              <pattern height={gridStep} id="learning-grid-small" patternUnits="userSpaceOnUse" width={gridStep} x={gridOriginX} y={gridOriginY}>
                {gridStep >= 6 && <circle cx="1" cy="1" fill="#d7dce3" r="1" />}
              </pattern>
              <marker id="learning-arrow" markerHeight="10" markerWidth="10" orient="auto" refX="8" refY="3">
                <path d="M0,0 L0,6 L9,3 z" fill="context-stroke" />
              </marker>
              <clipPath clipPathUnits="userSpaceOnUse" id="learning-canvas-viewport-clip">
                <rect height="100%" width="100%" x="0" y="0" />
              </clipPath>
            </defs>
            <rect className="learning-canvas-grid" fill="url(#learning-grid-small)" height="100%" pointerEvents="none" width="100%" />
            <g clipPath="url(#learning-canvas-viewport-clip)">
              <g transform={`translate(${camera.x} ${camera.y}) scale(${camera.z})`}>
                {renderedShapes.map((shape) => (
                  <LearningShape
                    assetSources={assetSources}
                    cameraZoom={camera.z}
                    editing={noteDraft?.shapeId === shape.id}
                    key={shape.id}
                    onDoubleClick={handleShapeDoubleClick}
                    onPointerDown={handleShapePointerDown}
                    selected={selectedIds.includes(shape.id)}
                    shape={shape}
                    snapshot={snapshot}
                  />
                ))}
                {selectionBounds && (
                  <g className="learning-selection-overlay">
                    <rect fill="none" height={selectionBounds.h} pointerEvents="none" stroke="#2563eb" strokeDasharray="6 4" strokeWidth={2 / camera.z} width={selectionBounds.w} x={selectionBounds.x} y={selectionBounds.y} />
                    {selectedBounds && selectedShape?.type === 'geo' && ['nw', 'ne', 'sw', 'se'].map((handle) => {
                      const x = handle.endsWith('w') ? selectedBounds.x : selectedBounds.x + selectedBounds.w
                      const y = handle.startsWith('n') ? selectedBounds.y : selectedBounds.y + selectedBounds.h
                      return <circle data-jlc-learning-canvas-control="true" key={handle} cx={x} cy={y} onPointerDown={(event) => handleResizePointerDown(event, selectedShape, handle)} r={7 / camera.z} />
                    })}
                  </g>
                )}
                {marqueeBounds && (
                  <rect
                    className="learning-marquee"
                    fill="#3b82f6"
                    fillOpacity="0.08"
                    height={marqueeBounds.h}
                    pointerEvents="none"
                    stroke="#2563eb"
                    strokeDasharray="5 4"
                    strokeWidth={1.5 / camera.z}
                    width={marqueeBounds.w}
                    x={marqueeBounds.x}
                    y={marqueeBounds.y}
                  />
                )}
              </g>
            </g>
          </svg>
        ) : (
          <div className="learning-empty-state">{status.text}</div>
        )}
        {snapshot && pageId && noteDraft && (
          <InlineCanvasTextEditor
            camera={camera}
            draft={noteDraft}
            onCancel={cancelTextEdit}
            onChange={(text) => setNoteDraft((current) => current ? { ...current, text } : current)}
            onCommit={saveNote}
            shape={noteDraft.shapeId ? snapshot.store[noteDraft.shapeId] : null}
            style={style}
          />
        )}
      </section>

      <nav aria-label="画布操作" className="jlc-learning-top-actions">
        <div className="jlc-learning-popover-anchor">
          <MenuButton active={openMenu === 'main'} Icon={Menu} label="菜单" onClick={() => setOpenMenu(openMenu === 'main' ? null : 'main')} testId="learning-main-menu" />
          {openMenu === 'main' && (
            <div className="jlc-learning-menu jlc-learning-menu-left" role="menu">
              <button onClick={() => { setSelectedIds(pageShapes.map((shape) => shape.id)); setOpenMenu(null) }} role="menuitem" type="button">全选 <kbd>Ctrl A</kbd></button>
              <button onClick={() => { fitContent(); setOpenMenu(null) }} role="menuitem" type="button">适合内容 <kbd>Ctrl 0</kbd></button>
              <button onClick={() => { zoomTo100(); setOpenMenu(null) }} role="menuitem" type="button">缩放到 100% <kbd>Ctrl 1</kbd></button>
              <button onClick={() => { setSelectedIds([]); setOpenMenu(null) }} role="menuitem" type="button">取消选择 <kbd>Esc</kbd></button>
            </div>
          )}
        </div>

        <select
          aria-label="切换图页"
          className="jlc-learning-page-select"
          data-testid="learning-page-select"
          onChange={(event) => {
            const nextPageId = event.target.value
            setSelectedIds([])
            setViewState((current) => ({ ...current, currentPageId: nextPageId }))
            window.setTimeout(() => fitContent([], nextPageId), 0)
          }}
          value={pageId || ''}
        >
          {pages.map((page, index) => <option key={page.id} value={page.id}>{page.name || `Page ${index + 1}`}</option>)}
        </select>

        <span className="jlc-learning-control-separator" />
        <MenuButton disabled={!canUndo} Icon={Undo2} label="撤销" onClick={undo} testId="learning-undo" />
        <MenuButton disabled={!canRedo} Icon={Redo2} label="重做" onClick={redo} testId="learning-redo" />
        <MenuButton danger={selectedImageIds.length > 0} disabled={!selectedIds.length} Icon={Trash2} label="删除选中内容" onClick={deleteSelected} testId="learning-delete" />
        <MenuButton disabled={!selectedIds.some((id) => snapshot?.store?.[id]?.type !== 'image')} Icon={Copy} label="复制" onClick={duplicateSelected} testId="learning-duplicate" />
        {selectedImageIds.length > 0 && (
          <MenuButton
            Icon={selectedImageIds.some((id) => snapshot.store[id]?.isLocked !== true) ? Lock : Unlock}
            label={selectedImageIds.some((id) => snapshot.store[id]?.isLocked !== true) ? '锁定原理图' : '解锁原理图'}
            onClick={toggleSelectedImageLock}
            testId="learning-image-lock"
          />
        )}
        <div className="jlc-learning-popover-anchor">
          <MenuButton active={openMenu === 'actions'} Icon={Shapes} label="操作" onClick={() => setOpenMenu(openMenu === 'actions' ? null : 'actions')} testId="learning-actions"><ChevronDown size={12} /></MenuButton>
          {openMenu === 'actions' && (
            <div className="jlc-learning-menu" role="menu">
              <button disabled={!selectedIds.length} onClick={() => { fitContent(selectedIds); setOpenMenu(null) }} role="menuitem" type="button">缩放至选区</button>
              <button disabled={!selectedIds.some((id) => snapshot?.store?.[id]?.type === 'image')} onClick={() => { toggleSelectedImageLock(); setOpenMenu(null) }} role="menuitem" type="button">
                {selectedIds.some((id) => snapshot?.store?.[id]?.type === 'image' && snapshot.store[id]?.isLocked !== true) ? '锁定原理图' : '解锁原理图'}
              </button>
              <button disabled={!selectedIds.length} onClick={() => { duplicateSelected(); setOpenMenu(null) }} role="menuitem" type="button">复制标注 <kbd>Ctrl D</kbd></button>
              <button className={selectedImageIds.length ? 'jlc-learning-danger-menu-item' : undefined} disabled={!selectedIds.length} onClick={() => { deleteSelected(); setOpenMenu(null) }} role="menuitem" type="button">
                删除选中内容{selectedImageIds.length ? '…' : ''}
              </button>
            </div>
          )}
        </div>

        <div className="jlc-learning-popover-anchor">
          <button
            aria-expanded={openMenu === 'export'}
            className="jlc-learning-export-button"
            data-testid="learning-export"
            disabled={exporting || choosingExportDirectory}
            onClick={() => setOpenMenu(openMenu === 'export' ? null : 'export')}
            title="导出"
            type="button"
          >
            {exporting || choosingExportDirectory ? <LoaderCircle className="is-spinning" size={15} /> : <Download size={15} />}
            导出 <ChevronDown size={12} />
          </button>
          {openMenu === 'export' && (
            <div className="jlc-learning-menu jlc-learning-export-menu" role="menu">
              <div className="jlc-learning-export-location" data-testid="learning-export-location">
                <span>保存位置</span>
                <code title={exportDirectory.directoryPath}>{exportDirectory.directoryPath}</code>
              </div>
              <button data-testid="learning-choose-export-directory" onClick={chooseExportDirectory} role="menuitem" type="button"><FolderOpen size={14} />选择文件夹…</button>
              {exportDirectory.directoryToken && (
                <button data-testid="learning-reset-export-directory" onClick={resetExportDirectory} role="menuitem" type="button">恢复默认位置</button>
              )}
              <span className="jlc-learning-menu-separator" />
              <button data-testid="learning-export-page-png" onClick={() => exportCanvas('png')} role="menuitem" type="button">当前图页 PNG</button>
              <button data-testid="learning-export-page-svg" onClick={() => exportCanvas('svg')} role="menuitem" type="button">当前图页 SVG</button>
              <button data-testid="learning-export-selection-png" disabled={!selectedIds.length} onClick={() => exportCanvas('png', true)} role="menuitem" type="button">当前选区 PNG</button>
              <button data-testid="learning-copy-selection-png" disabled={!selectedIds.length} onClick={() => exportCanvas('clipboard', true)} role="menuitem" type="button"><Clipboard size={14} />复制选区 PNG</button>
              <button data-testid="learning-export-canvas-json" onClick={() => exportCanvas('json')} role="menuitem" type="button">画布备份 JSON</button>
            </div>
          )}
        </div>
      </nav>

      <aside
        aria-label="样式"
        className="jlc-learning-style-panel"
        data-jlc-learning-preserve-text-editor="true"
        data-selection-scope={selectedIds.length && !selectedIds.some((id) => snapshot?.store?.[id]?.type !== 'image') ? 'protected' : 'editable'}
        title={selectedIds.length && !selectedIds.some((id) => snapshot?.store?.[id]?.type !== 'image') ? '原理图底图受保护；调整项将用于下一项标注' : '调整当前标注或下一项标注的样式'}
      >
        <div className="jlc-learning-color-grid">
          {STYLE_COLORS.map(([name, value]) => (
            <button
              aria-label={`颜色 ${name}`}
              className="jlc-learning-color-swatch"
              data-active={panelStyle.color === name ? 'true' : 'false'}
              key={name}
              onClick={() => applyStyle({ color: name })}
              style={{ '--swatch': value }}
              title={name}
              type="button"
            />
          ))}
        </div>
        <label className="jlc-learning-opacity-control">
          <span>不透明度</span><output>{Math.round(panelStyle.opacity * 100)}%</output>
          <input max="100" min="10" onInput={(event) => applyStyle({ opacity: Number(event.currentTarget.value) / 100 })} type="range" value={Math.round(panelStyle.opacity * 100)} />
        </label>
        <StyleOptions label="填充" onChange={(fill) => applyStyle({ fill })} options={FILL_OPTIONS} value={panelStyle.fill} />
        <StyleOptions label="线条" onChange={(dash) => applyStyle({ dash })} options={DASH_OPTIONS} value={panelStyle.dash} />
        <StyleOptions label="大小" onChange={(size) => applyStyle({ size })} options={SIZE_OPTIONS} value={panelStyle.size} />
      </aside>

      <nav aria-label="学习画布工具" className="jlc-learning-bottom-toolbar">
        {PRIMARY_TOOLS.map(({ id, label, Icon }, index) => (
          <span className="jlc-learning-tool-slot" key={id}>
            {index === 1 && <span className="jlc-learning-control-separator" />}
            <ToolbarButton active={tool === id} Icon={Icon} label={label} onClick={() => chooseTool(id)} testId={`learning-tool-${id}`} />
          </span>
        ))}
        <span className="jlc-learning-control-separator" />
        <div className="jlc-learning-popover-anchor">
          <ToolbarButton active={MORE_TOOLS.some(({ id }) => id === tool)} Icon={MoreHorizontal} label="更多工具" onClick={() => setOpenMenu(openMenu === 'tools' ? null : 'tools')} testId="learning-tool-more" />
          {openMenu === 'tools' && (
            <div className="jlc-learning-tool-menu" role="menu">
              {MORE_TOOLS.map(({ id, label, Icon }) => (
                <button data-active={tool === id ? 'true' : 'false'} key={id} onClick={() => chooseTool(id)} role="menuitem" type="button"><Icon size={18} />{label}</button>
              ))}
            </div>
          )}
        </div>
      </nav>

      <div className="jlc-learning-zoom-controls">
        <div className="jlc-learning-popover-anchor">
          <button className="jlc-learning-zoom-percent" onClick={() => setOpenMenu(openMenu === 'zoom' ? null : 'zoom')} type="button">{Math.round(camera.z * 100)}% <ChevronDown size={12} /></button>
          {openMenu === 'zoom' && (
            <div className="jlc-learning-menu jlc-learning-zoom-menu" role="menu">
              <button onClick={() => zoomBy(1.2)} role="menuitem" type="button"><ZoomIn size={15} />放大</button>
              <button onClick={() => zoomBy(1 / 1.2)} role="menuitem" type="button"><ZoomOut size={15} />缩小</button>
              <button onClick={zoomTo100} role="menuitem" type="button"><Plus size={15} />100%</button>
              <button onClick={() => fitContent()} role="menuitem" type="button"><Maximize2 size={15} />适合内容</button>
            </div>
          )}
        </div>
        <button aria-label="小地图" className="jlc-learning-minimap-button" data-active={minimapOpen ? 'true' : 'false'} onClick={() => setMinimapOpen((value) => !value)} title="小地图" type="button"><MapIcon size={18} /></button>
      </div>

      {minimapOpen && contentBounds && (
        <div className="jlc-learning-minimap">
          <svg aria-label="小地图" preserveAspectRatio="xMidYMid meet" viewBox={`${contentBounds.x - 40} ${contentBounds.y - 40} ${contentBounds.w + 80} ${contentBounds.h + 80}`}>
            {pageShapes.map((shape) => {
              const bounds = pageBoundsForShape(snapshot.store, shape)
              return <rect fill={shape.type === 'image' ? '#cbd5e1' : shape.meta?.hardwareLearningFrame ? '#c4b5fd' : '#93c5fd'} height={Math.max(2, bounds.h)} key={shape.id} opacity="0.78" width={Math.max(2, bounds.w)} x={bounds.x} y={bounds.y} />
            })}
            {viewportBounds && <rect fill="none" height={viewportBounds.h} stroke="#2563eb" strokeWidth={Math.max(2, contentBounds.w / 160)} width={viewportBounds.w} x={viewportBounds.x} y={viewportBounds.y} />}
          </svg>
        </div>
      )}

      {pendingDeleteIds.length > 0 && pendingImageDeleteIds.length > 0 && (
        <div
          className="learning-confirm-backdrop"
          data-testid="learning-delete-image-dialog-backdrop"
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) cancelSelectedDeletion()
          }}
        >
          <section
            aria-describedby="learning-delete-image-description"
            aria-labelledby="learning-delete-image-title"
            aria-modal="true"
            className="learning-confirm-dialog"
            data-testid="learning-delete-image-dialog"
            role="alertdialog"
          >
            <h2 id="learning-delete-image-title">删除选中的内容？</h2>
            <p id="learning-delete-image-description">
              将从当前画板图页删除 {pendingImageDeleteIds.length} 张原理图
              {pendingAnnotationDeleteIds.length > 0 ? `和 ${pendingAnnotationDeleteIds.length} 个标注` : ''}。
              不会修改嘉立创 EDA 工程，删除后仍可使用“撤销”恢复。
            </p>
            <div className="learning-confirm-actions">
              <button autoFocus data-testid="learning-delete-image-cancel" onClick={cancelSelectedDeletion} type="button">取消</button>
              <button className="is-danger" data-testid="learning-delete-image-confirm" onClick={confirmSelectedDeletion} type="button">删除选中内容</button>
            </div>
          </section>
        </div>
      )}

      <aside className="learning-status" data-kind={status.kind}>
        {status.kind === 'saving' ? <LoaderCircle className="is-spinning" size={15} /> : <Check size={15} />}
        <span>{status.text}</span>
        {selectedIds.length > 0 && <span>已选 {selectedIds.length} 个对象</span>}
      </aside>

      {lastExport?.filePath && (
        <aside className="learning-export-result" data-testid="learning-export-result">
          <Download aria-hidden="true" size={15} />
          <span>已导出</span>
          <code title={lastExport.filePath}>{lastExport.filePath}</code>
          <button onClick={copyLastExportPath} title="复制导出路径" type="button"><Copy aria-hidden="true" size={14} />复制路径</button>
        </aside>
      )}

    </main>
  )
}

function StyleOptions({ label, onChange, options, value }) {
  return (
    <fieldset className="jlc-learning-style-options">
      <legend>{label}</legend>
      <div>
        {options.map(([id, text]) => <button data-active={value === id ? 'true' : 'false'} key={id} onClick={() => onChange(id)} title={text} type="button">{text}</button>)}
      </div>
    </fieldset>
  )
}
