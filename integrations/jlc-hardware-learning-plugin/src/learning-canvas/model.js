import { generateKeyBetween } from 'fractional-indexing'

export const LEARNING_CANVAS_VERSION = 2
export const DEFAULT_PAGE_ID = 'page:page'
export const FRAME_KIND = 'frame'
export const LEARNING_KINDS = new Set([
  'frame', 'pen', 'highlight', 'arrow', 'line', 'note', 'text', 'rectangle', 'ellipse'
])
const LEGACY_METADATA_PREFIXES = [
  ['cowartLearning', 'hardwareLearning'],
  ['cowartHardware', 'hardwareLearning'],
  ['cowartAnnotation', 'hardwareLearningAnnotation'],
  ['cowartAi', 'hardwareLearningAi'],
  ['cowartGenerated', 'hardwareLearningGenerated'],
  ['cowartReplaced', 'hardwareLearningReplaced'],
  ['cowartDuplicated', 'hardwareLearningDuplicated'],
  ['cowartMigrated', 'hardwareLearningMigrated'],
  ['cowartHtml', 'hardwareLearningHtml']
]

export const DEFAULT_LEARNING_STYLE = Object.freeze({
  color: 'black',
  fill: 'none',
  dash: 'draw',
  size: 'm',
  opacity: 1
})

const LEARNING_COLORS = new Set([
  'black', 'grey', 'light-violet', 'violet', 'blue', 'light-blue',
  'yellow', 'orange', 'green', 'light-green', 'light-red', 'red'
])
const LEARNING_FILLS = new Set(['none', 'semi', 'solid'])
const LEARNING_DASHES = new Set(['draw', 'dashed', 'dotted', 'solid'])
const LEARNING_SIZES = new Set(['s', 'm', 'l', 'xl'])
const NEXT_FRAME_NUMBER_META = 'hardwareLearningNextFrameNumber'
const LEARNING_TEXT_METRICS_VERSION = 3
const LEARNING_TEXT_METRICS = Object.freeze({
  s: Object.freeze({ fontSize: 13, lineHeight: 18 }),
  m: Object.freeze({ fontSize: 15, lineHeight: 20 }),
  l: Object.freeze({ fontSize: 20, lineHeight: 27 }),
  xl: Object.freeze({ fontSize: 28, lineHeight: 36 })
})

export function normalizeLearningStyle(style = {}) {
  return {
    color: LEARNING_COLORS.has(style.color) ? style.color : DEFAULT_LEARNING_STYLE.color,
    fill: LEARNING_FILLS.has(style.fill) ? style.fill : DEFAULT_LEARNING_STYLE.fill,
    dash: LEARNING_DASHES.has(style.dash) ? style.dash : DEFAULT_LEARNING_STYLE.dash,
    size: LEARNING_SIZES.has(style.size) ? style.size : DEFAULT_LEARNING_STYLE.size,
    opacity: Math.min(1, Math.max(0.1, finite(style.opacity, DEFAULT_LEARNING_STYLE.opacity)))
  }
}

export function learningTextMetricsForSize(size) {
  return LEARNING_TEXT_METRICS[size] ?? LEARNING_TEXT_METRICS[DEFAULT_LEARNING_STYLE.size]
}

function estimatedGlyphWidth(character, fontSize) {
  if (/\s/u.test(character)) return fontSize * 0.36
  if (/[\u1100-\u11ff\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff01-\uff60\uffe0-\uffe6]/u.test(character)) {
    return fontSize
  }
  return fontSize * 0.62
}

export function estimateLearningTextLineWidth(text, size = DEFAULT_LEARNING_STYLE.size) {
  const { fontSize } = learningTextMetricsForSize(size)
  return Array.from(String(text || '')).reduce(
    (width, character) => width + estimatedGlyphWidth(character, fontSize),
    0
  )
}

function wrapLearningTextLines(text, { width, size, paddingX }) {
  const { fontSize } = learningTextMetricsForSize(size)
  const availableWidth = Math.max(fontSize, width - paddingX * 2)
  const lines = []
  for (const source of String(text || '').split(/\r?\n/u)) {
    if (!source) {
      lines.push('')
      continue
    }
    let current = ''
    let currentWidth = 0
    for (const character of Array.from(source)) {
      const characterWidth = estimatedGlyphWidth(character, fontSize)
      if (current && currentWidth + characterWidth > availableWidth) {
        lines.push(current)
        current = ''
        currentWidth = 0
      }
      current += character
      currentWidth += characterWidth
    }
    lines.push(current)
  }
  return lines.length ? lines : ['']
}

export function layoutLearningText(text, {
  width = 260,
  height = 120,
  size = DEFAULT_LEARNING_STYLE.size,
  paddingX = 14,
  paddingTop = 8,
  maxLines = Number.POSITIVE_INFINITY
} = {}) {
  const metrics = learningTextMetricsForSize(size)
  const firstBaseline = metrics.fontSize + 9
  const allLines = wrapLearningTextLines(text, { width, size, paddingX })
  const heightLineLimit = Number.isFinite(height)
    ? 1 + Math.floor(Math.max(0, height - paddingTop - firstBaseline) / metrics.lineHeight)
    : Number.POSITIVE_INFINITY
  const lineLimit = Math.max(1, Math.min(maxLines, heightLineLimit))
  const lines = allLines.slice(0, lineLimit)
  const requiredHeight = paddingTop + firstBaseline + Math.max(0, allLines.length - 1) * metrics.lineHeight + 8
  return {
    ...metrics,
    firstBaseline,
    lines,
    overflow: allLines.length > lines.length,
    requiredHeight,
    visualLineCount: allLines.length
  }
}

export function learningTextBoundsForContent({
  mode = 'text',
  text = '',
  style,
  currentBounds,
  autoSize = true
} = {}) {
  const normalizedStyle = normalizeLearningStyle(style)
  const note = mode === 'note'
  const minWidth = note ? 180 : 120
  const defaultWidth = note ? 260 : 320
  const maxWidth = 720
  const minHeight = note ? 120 : 54
  const maxHeight = 4096
  const hardLineWidth = Math.max(
    0,
    ...String(text || '').split(/\r?\n/u).map((line) => estimateLearningTextLineWidth(line, normalizedStyle.size))
  )
  const requestedWidth = note || !autoSize
    ? finite(currentBounds?.w, defaultWidth)
    : hardLineWidth + 28
  const width = Math.max(minWidth, Math.min(maxWidth, requestedWidth))
  const layout = layoutLearningText(text, {
    width,
    height: Number.POSITIVE_INFINITY,
    size: normalizedStyle.size
  })
  const contentHeight = Math.max(minHeight, layout.requiredHeight)
  const requestedHeight = autoSize
    ? contentHeight
    : Math.max(finite(currentBounds?.h, minHeight), contentHeight)
  return {
    w: width,
    h: Math.min(maxHeight, requestedHeight),
    contentHeight,
    overflow: requestedHeight > maxHeight,
    visualLineCount: layout.visualLineCount
  }
}

const EMPTY_RICH_TEXT = Object.freeze({
  type: 'doc',
  content: [{ type: 'paragraph' }]
})

export function cloneSnapshot(snapshot) {
  return structuredClone(snapshot)
}

export function createRecordId(prefix = 'shape') {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `${prefix}:${random}`
}

export function emptyRichText(text = '') {
  if (!text) return cloneSnapshot(EMPTY_RICH_TEXT)
  return {
    type: 'doc',
    content: [{
      type: 'paragraph',
      content: [{ type: 'text', text: String(text) }]
    }]
  }
}

function finite(value, fallback = 0) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

export function normalizeBounds(start, end, minimum = 4) {
  const left = Math.min(start.x, end.x)
  const top = Math.min(start.y, end.y)
  return {
    x: left,
    y: top,
    w: Math.max(minimum, Math.abs(end.x - start.x)),
    h: Math.max(minimum, Math.abs(end.y - start.y))
  }
}

export function pageRecords(snapshot) {
  return Object.values(snapshot?.store ?? {})
    .filter((record) => record?.typeName === 'page')
    .sort((left, right) => String(left.index ?? '').localeCompare(String(right.index ?? '')))
}

function normalizePageName(value, fallback) {
  const name = String(value || '').trim()
  return (name || fallback).slice(0, 64)
}

export function createLearningPage(snapshot, name) {
  const pages = pageRecords(snapshot)
  const id = createRecordId('page')
  const page = {
    id,
    typeName: 'page',
    name: normalizePageName(name, `图页 ${pages.length + 1}`),
    index: generateKeyBetween(pages.at(-1)?.index ?? null, null),
    meta: {}
  }
  const next = cloneSnapshot(snapshot)
  next.store[id] = page
  return { snapshot: next, page }
}

export function renameLearningPage(snapshot, pageId, name) {
  const page = snapshot?.store?.[pageId]
  if (page?.typeName !== 'page') return { snapshot, page: null, changed: false }
  const nextName = normalizePageName(name, page.name || '图页')
  if (nextName === page.name) return { snapshot, page, changed: false }
  const next = cloneSnapshot(snapshot)
  next.store[pageId] = { ...page, name: nextName }
  return { snapshot: next, page: next.store[pageId], changed: true }
}

export function deleteLearningPage(snapshot, pageId) {
  const pages = pageRecords(snapshot)
  const page = snapshot?.store?.[pageId]
  if (page?.typeName !== 'page') {
    return { snapshot, deleted: false, reason: 'missing-page', acknowledgedImageShapeDeletes: [] }
  }
  if (pages.length <= 1) {
    return { snapshot, deleted: false, reason: 'last-page', acknowledgedImageShapeDeletes: [] }
  }
  const next = cloneSnapshot(snapshot)
  const removedIds = new Set([pageId, ...shapesForPage(snapshot, pageId).map((shape) => shape.id)])
  const acknowledgedImageShapeDeletes = [...removedIds].filter((id) => snapshot.store[id]?.type === 'image')
  let changed = true
  while (changed) {
    changed = false
    for (const record of Object.values(next.store)) {
      if (removedIds.has(record.id)) continue
      if (removedIds.has(record.parentId) || removedIds.has(record.fromId) || removedIds.has(record.toId)) {
        removedIds.add(record.id)
        changed = true
      }
    }
  }
  for (const id of removedIds) delete next.store[id]
  const referencedAssetIds = new Set(Object.values(next.store)
    .filter((record) => record?.typeName === 'shape' && record.type === 'image')
    .map((record) => record.props?.assetId)
    .filter(Boolean))
  for (const record of Object.values(next.store)) {
    if (record?.typeName === 'asset' && !referencedAssetIds.has(record.id)) delete next.store[record.id]
  }
  const remainingPages = pageRecords(next)
  const deletedIndex = pages.findIndex((candidate) => candidate.id === pageId)
  const nextPage = remainingPages[Math.min(deletedIndex, remainingPages.length - 1)] || remainingPages[0]
  return {
    snapshot: next,
    deleted: true,
    page,
    nextPageId: nextPage?.id ?? null,
    acknowledgedImageShapeDeletes,
  }
}

export function pageIdForShape(store, shape) {
  let record = shape
  const visited = new Set()
  while (record && !visited.has(record.id)) {
    visited.add(record.id)
    if (record.typeName === 'page') return record.id
    const parent = store?.[record.parentId]
    if (parent?.typeName === 'page') return parent.id
    record = parent
  }
  return null
}

export function shapesForPage(snapshot, pageId) {
  const store = snapshot?.store ?? {}
  const byParent = new Map()
  for (const record of Object.values(store)) {
    if (record?.typeName !== 'shape') continue
    const siblings = byParent.get(record.parentId) ?? []
    siblings.push(record)
    byParent.set(record.parentId, siblings)
  }
  const shapes = []
  const queue = [...(byParent.get(pageId) ?? [])]
  while (queue.length > 0) {
    const shape = queue.shift()
    shapes.push(shape)
    queue.push(...(byParent.get(shape.id) ?? []))
  }
  return shapes.sort((left, right) => String(left.index ?? '').localeCompare(String(right.index ?? '')))
}

function positiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0 ? value : null
}

export function learningFrameNumber(shape) {
  if (shape?.meta?.hardwareLearningFrame !== true) return null
  return positiveInteger(shape.meta.hardwareLearningFrameNumber)
}

export function nextLearningFrameNumber(snapshot, pageId) {
  const page = snapshot?.store?.[pageId]
  const storedNext = positiveInteger(page?.meta?.[NEXT_FRAME_NUMBER_META]) ?? 1
  const highestExisting = shapesForPage(snapshot, pageId)
    .filter((shape) => shape.meta?.hardwareLearningFrame === true)
    .reduce((highest, shape) => Math.max(highest, learningFrameNumber(shape) ?? 0), 0)
  return Math.max(storedNext, highestExisting + 1)
}

function reserveLearningFrameNumber(snapshot, pageId, frameNumber) {
  const number = positiveInteger(frameNumber)
  const page = snapshot?.store?.[pageId]
  if (!number || page?.typeName !== 'page') return
  const current = positiveInteger(page.meta?.[NEXT_FRAME_NUMBER_META]) ?? 1
  page.meta = {
    ...page.meta,
    [NEXT_FRAME_NUMBER_META]: Math.max(current, number + 1)
  }
}

export function nextShapeIndex(snapshot, pageId) {
  const indexes = shapesForPage(snapshot, pageId)
    .map((shape) => shape.index)
    .filter((index) => typeof index === 'string')
    .sort()
  return generateKeyBetween(indexes.at(-1) ?? null, null)
}

function baseShape({ id = createRecordId(), pageId, index, x, y, type, opacity = 1, meta = {}, props }) {
  return {
    x,
    y,
    rotation: 0,
    isLocked: false,
    opacity,
    meta,
    id,
    type,
    props,
    parentId: pageId,
    index,
    typeName: 'shape'
  }
}

function learningMeta(kind, extra = {}) {
  return {
    hardwareLearningCanvasVersion: LEARNING_CANVAS_VERSION,
    hardwareLearningKind: kind,
    hardwareLearningAnnotation: true,
    ...extra
  }
}

function rectangleProps(bounds, {
  color = 'violet', dash = 'draw', fill = 'none', text = '', size = 's', geo = 'rectangle'
} = {}) {
  return {
    w: bounds.w,
    h: bounds.h,
    geo,
    dash,
    growY: 0,
    url: '',
    scale: 1,
    color,
    labelColor: color,
    fill,
    size,
    font: 'draw',
    align: 'middle',
    verticalAlign: 'middle',
    richText: emptyRichText(text)
  }
}

export function createFrameShape({ snapshot, pageId, bounds, style, frameNumber, id, index } = {}) {
  const normalizedStyle = normalizeLearningStyle(style ?? {
    color: 'violet',
    fill: 'none',
    dash: 'draw',
    size: 's',
    opacity: 1
  })
  const resolvedFrameNumber = positiveInteger(frameNumber) ?? nextLearningFrameNumber(snapshot, pageId)
  return baseShape({
    id,
    pageId,
    index: index ?? nextShapeIndex(snapshot, pageId),
    x: bounds.x,
    y: bounds.y,
    type: 'geo',
    opacity: normalizedStyle.opacity,
    meta: learningMeta(FRAME_KIND, {
      hardwareLearningFrame: true,
      hardwareLearningFrameNumber: resolvedFrameNumber,
      hardwareLearningBounds: { x: 0, y: 0, w: bounds.w, h: bounds.h }
    }),
    props: rectangleProps(bounds, normalizedStyle)
  })
}

export function createGeoShape({
  snapshot,
  pageId,
  bounds,
  geo = 'rectangle',
  kind = geo,
  style,
  text = '',
  command,
  id,
  index
} = {}) {
  const normalizedStyle = normalizeLearningStyle(style)
  return baseShape({
    id,
    pageId,
    index: index ?? nextShapeIndex(snapshot, pageId),
    x: bounds.x,
    y: bounds.y,
    type: 'geo',
    opacity: normalizedStyle.opacity,
    meta: learningMeta(kind, {
      ...(text ? { hardwareLearningText: String(text) } : {}),
      hardwareLearningBounds: { x: 0, y: 0, w: bounds.w, h: bounds.h },
      ...commandMeta(command)
    }),
    props: rectangleProps(bounds, {
      ...normalizedStyle,
      geo,
      text
    })
  })
}

export function createRectangleShape({ snapshot, pageId, bounds, command, style, id, index } = {}) {
  const kind = command?.kind === 'highlight' ? 'highlight' : 'rectangle'
  return createGeoShape({
    snapshot,
    pageId,
    bounds,
    kind,
    command,
    id,
    index: index ?? nextShapeIndex(snapshot, pageId),
    style: style ?? {
      color: command?.style?.color || (kind === 'highlight' ? 'yellow' : 'blue'),
      dash: command?.style?.dash || 'solid',
      fill: kind === 'highlight' ? 'semi' : 'none',
      size: command?.style?.size || 'm',
      opacity: kind === 'highlight' ? 0.35 : 1
    },
    text: command?.text || ''
  })
}

export function createEllipseShape({ snapshot, pageId, bounds, style, id, index } = {}) {
  return createGeoShape({ snapshot, pageId, bounds, geo: 'ellipse', kind: 'ellipse', style, id, index })
}

export function createTextShape({ snapshot, pageId, point, text, style, bounds, autoSize = bounds ? false : true, id, index } = {}) {
  const normalizedStyle = normalizeLearningStyle(style)
  const dimensions = learningTextBoundsForContent({
    mode: 'text',
    text,
    style: normalizedStyle,
    currentBounds: bounds,
    autoSize
  })
  const shape = createGeoShape({
    snapshot,
    pageId,
    bounds: { x: bounds?.x ?? point.x, y: bounds?.y ?? point.y, w: dimensions.w, h: dimensions.h },
    kind: 'text',
    style: { ...normalizedStyle, fill: 'none', dash: 'solid' },
    text,
    id,
    index
  })
  return {
    ...shape,
    meta: {
      ...shape.meta,
      hardwareLearningTextAutoSize: autoSize,
      hardwareLearningTextMetricsVersion: LEARNING_TEXT_METRICS_VERSION
    }
  }
}

export function createNoteShape({ snapshot, pageId, point, text, bounds, command, style, id, index } = {}) {
  const normalizedStyle = normalizeLearningStyle(style ?? {
    color: 'yellow',
    dash: 'solid',
    fill: 'solid',
    size: 'm',
    opacity: 1
  })
  const autoSize = !bounds
  const noteText = String(text || command?.text || '')
  const dimensions = learningTextBoundsForContent({
    mode: 'note',
    text: noteText,
    style: normalizedStyle,
    currentBounds: bounds,
    autoSize
  })
  const noteBounds = {
    x: bounds?.x ?? point.x,
    y: bounds?.y ?? point.y,
    w: dimensions.w,
    h: dimensions.h
  }
  return baseShape({
    id,
    pageId,
    index: index ?? nextShapeIndex(snapshot, pageId),
    x: noteBounds.x,
    y: noteBounds.y,
    type: 'geo',
    opacity: normalizedStyle.opacity,
    meta: learningMeta('note', {
      hardwareLearningText: noteText,
      hardwareLearningTextAutoSize: autoSize,
      hardwareLearningTextMetricsVersion: LEARNING_TEXT_METRICS_VERSION,
      hardwareLearningBounds: { x: 0, y: 0, w: noteBounds.w, h: noteBounds.h },
      ...commandMeta(command)
    }),
    props: rectangleProps(noteBounds, {
      ...normalizedStyle,
      text: noteText
    })
  })
}

export function updateLearningTextShapeContent(shape, text, style) {
  const mode = shape?.meta?.hardwareLearningKind
  if (!['note', 'text'].includes(mode)) return shape
  const normalizedStyle = normalizeLearningStyle(style ?? {
    color: shape.props?.color,
    fill: shape.props?.fill,
    dash: shape.props?.dash,
    size: shape.props?.size,
    opacity: shape.opacity
  })
  const autoSize = shape.meta?.hardwareLearningTextAutoSize !== false
  const dimensions = learningTextBoundsForContent({
    mode,
    text,
    style: normalizedStyle,
    currentBounds: { w: shape.props?.w, h: shape.props?.h },
    autoSize
  })
  const appliedStyle = mode === 'text'
    ? { ...normalizedStyle, fill: 'none', dash: 'solid' }
    : normalizedStyle
  return {
    ...shape,
    opacity: appliedStyle.opacity,
    meta: {
      ...shape.meta,
      hardwareLearningText: String(text || ''),
      hardwareLearningTextMetricsVersion: LEARNING_TEXT_METRICS_VERSION,
      hardwareLearningBounds: { x: 0, y: 0, w: dimensions.w, h: dimensions.h }
    },
    props: {
      ...shape.props,
      w: dimensions.w,
      h: dimensions.h,
      color: appliedStyle.color,
      labelColor: appliedStyle.color,
      fill: appliedStyle.fill,
      dash: appliedStyle.dash,
      size: appliedStyle.size,
      richText: emptyRichText(text)
    }
  }
}

export function createArrowShape({
  snapshot, pageId, start, end, command, style, kind = 'arrow', id, index
} = {}) {
  const normalizedStyle = normalizeLearningStyle(style ?? command?.style ?? {
    color: 'blue',
    fill: 'none',
    dash: 'draw',
    size: 'm',
    opacity: 1
  })
  const x = Math.min(start.x, end.x)
  const y = Math.min(start.y, end.y)
  const localStart = { x: start.x - x, y: start.y - y }
  const localEnd = { x: end.x - x, y: end.y - y }
  return baseShape({
    id,
    pageId,
    index: index ?? nextShapeIndex(snapshot, pageId),
    x,
    y,
    type: 'arrow',
    opacity: normalizedStyle.opacity,
    meta: learningMeta(kind, commandMeta(command)),
    props: {
      kind: 'arc',
      elbowMidPoint: 0.5,
      dash: normalizedStyle.dash,
      size: normalizedStyle.size,
      fill: 'none',
      color: normalizedStyle.color,
      labelColor: normalizedStyle.color,
      bend: 0,
      start: localStart,
      end: localEnd,
      arrowheadStart: 'none',
      arrowheadEnd: kind === 'line' ? 'none' : 'arrow',
      richText: emptyRichText(command?.text || ''),
      labelPosition: 0.5,
      font: 'draw',
      scale: 1
    }
  })
}

export function createLineShape(options = {}) {
  return createArrowShape({ ...options, kind: 'line' })
}

export function createStrokeShape({ snapshot, pageId, points, kind = 'pen', style, id, index } = {}) {
  if (!Array.isArray(points) || points.length < 2) throw new Error('A learning stroke requires at least two points.')
  const minX = Math.min(...points.map((point) => point.x))
  const minY = Math.min(...points.map((point) => point.y))
  const maxX = Math.max(...points.map((point) => point.x))
  const maxY = Math.max(...points.map((point) => point.y))
  const localPoints = points.map((point) => ({
    x: point.x - minX,
    y: point.y - minY,
    z: finite(point.z, 0.5)
  }))
  const highlight = kind === 'highlight'
  const normalizedStyle = normalizeLearningStyle(style ?? (highlight
    ? { color: 'yellow', size: 'l', opacity: 0.42 }
    : { color: 'violet', size: 'm' }))
  return baseShape({
    id,
    pageId,
    index: index ?? nextShapeIndex(snapshot, pageId),
    x: minX,
    y: minY,
    type: highlight ? 'highlight' : 'draw',
    opacity: normalizedStyle.opacity,
    meta: learningMeta(kind, {
      hardwareLearningPoints: localPoints,
      hardwareLearningBounds: { x: 0, y: 0, w: Math.max(1, maxX - minX), h: Math.max(1, maxY - minY) }
    }),
    props: highlight
      ? {
          segments: [{ type: 'free', points: localPoints }],
          color: normalizedStyle.color, size: normalizedStyle.size, isComplete: true,
          isPen: false, scale: 1, scaleX: 1, scaleY: 1
        }
      : {
          segments: [{ type: 'free', points: localPoints }],
          color: normalizedStyle.color, fill: normalizedStyle.fill,
          dash: normalizedStyle.dash, size: normalizedStyle.size,
          isComplete: true, isClosed: false, isPen: false, scale: 1, scaleX: 1, scaleY: 1
        }
  })
}

function commandMeta(command) {
  if (!command) return {}
  return {
    hardwareLearningOperationId: command.operationId,
    hardwareLearningCommandId: command.commandId,
    hardwareLearningKind: command.kind
  }
}

function stableCommandShapeId(command) {
  const safe = String(command.commandId || createRecordId('command'))
    .replace(/^shape:/, '')
    .replace(/[^a-zA-Z0-9_-]+/g, '-')
  return `shape:jlc-learning-${safe}`
}

export function shapeForAnnotationCommand(snapshot, command) {
  const bounds = {
    x: finite(command?.bounds?.x),
    y: finite(command?.bounds?.y),
    w: Math.max(1, finite(command?.bounds?.width, 320)),
    h: Math.max(1, finite(command?.bounds?.height, 160))
  }
  const shared = {
    snapshot,
    pageId: command.pageId,
    command,
    id: stableCommandShapeId(command)
  }
  if (command.kind === 'note') {
    return createNoteShape({ ...shared, bounds, text: command.text || '' })
  }
  if (command.kind === 'arrow') {
    return createArrowShape({
      ...shared,
      start: { x: bounds.x, y: bounds.y },
      end: { x: bounds.x + bounds.w, y: bounds.y + bounds.h }
    })
  }
  return createRectangleShape({ ...shared, bounds })
}

export function migrateLegacyLearningFrames(snapshot) {
  if (!snapshot?.store) return { snapshot, changed: false, migratedMetadataRecordIds: [], migratedShapeIds: [], numberedFrameIds: [], updatedFrameNumberPageIds: [], repairedStrokeIds: [], reflowedTextShapeIds: [] }
  const next = cloneSnapshot(snapshot)
  const migratedMetadataRecordIds = []
  const migratedShapeIds = []
  const numberedFrameIds = []
  const updatedFrameNumberPageIds = []
  const repairedStrokeIds = []
  const reflowedTextShapeIds = []
  for (const shape of Object.values(next.store)) {
    let metadataChanged = false
    if (shape?.meta && typeof shape.meta === 'object') {
      for (const [legacyPrefix, canonicalPrefix] of LEGACY_METADATA_PREFIXES) {
        for (const key of Object.keys(shape.meta)) {
          if (!key.startsWith(legacyPrefix)) continue
          const canonicalKey = `${canonicalPrefix}${key.slice(legacyPrefix.length)}`
          if (!Object.hasOwn(shape.meta, canonicalKey)) shape.meta[canonicalKey] = shape.meta[key]
          delete shape.meta[key]
          metadataChanged = true
        }
      }
    }
    if (metadataChanged) migratedMetadataRecordIds.push(shape.id)
    if (
      shape?.typeName === 'shape' &&
      ['text', 'note'].includes(shape.meta?.hardwareLearningKind) &&
      shape.meta?.hardwareLearningTextMetricsVersion !== LEARNING_TEXT_METRICS_VERSION
    ) {
      const updated = updateLearningTextShapeContent(shape, shape.meta?.hardwareLearningText || '')
      next.store[shape.id] = updated
      reflowedTextShapeIds.push(shape.id)
      continue
    }
    if (
      shape?.typeName === 'shape' &&
      (shape.type === 'draw' || shape.type === 'highlight') &&
      Array.isArray(shape.meta?.hardwareLearningPoints) &&
      shape.meta.hardwareLearningPoints.length > 1 &&
      !shape.props?.segments?.some((segment) => Array.isArray(segment?.points) && segment.points.length > 1)
    ) {
      shape.props = {
        ...shape.props,
        segments: [{ type: 'free', points: cloneSnapshot(shape.meta.hardwareLearningPoints) }]
      }
      repairedStrokeIds.push(shape.id)
    }
    if (shape?.typeName !== 'shape' || shape.type !== 'geo' || shape.props?.geo !== 'rectangle') continue
    if (shape.meta?.hardwareLearningFrame === true) continue
    const legacyFrame =
      shape.props?.color === 'violet' &&
      shape.props?.fill === 'none' &&
      shape.props?.dash === 'draw'
    if (!legacyFrame) continue
    shape.meta = learningMeta(FRAME_KIND, {
      ...shape.meta,
      hardwareLearningFrame: true,
      hardwareLearningMigratedFromLegacyRectangle: true,
      hardwareLearningBounds: {
        x: 0,
        y: 0,
        w: Math.max(1, finite(shape.props?.w, 1)),
        h: Math.max(1, finite(shape.props?.h, 1))
      }
    })
    migratedShapeIds.push(shape.id)
  }
  for (const page of pageRecords(next)) {
    const frames = shapesForPage(next, page.id)
      .filter((shape) => shape.meta?.hardwareLearningFrame === true)
    const used = new Set()
    const needsNumber = []
    for (const frame of frames) {
      const number = learningFrameNumber(frame)
      if (number && !used.has(number)) {
        used.add(number)
      } else {
        needsNumber.push(frame)
      }
    }
    let candidate = 1
    for (const frame of needsNumber) {
      while (used.has(candidate)) candidate += 1
      frame.meta = {
        ...frame.meta,
        hardwareLearningFrameNumber: candidate
      }
      used.add(candidate)
      numberedFrameIds.push(frame.id)
      candidate += 1
    }
    const nextNumber = Math.max(
      positiveInteger(page.meta?.[NEXT_FRAME_NUMBER_META]) ?? 1,
      ...[...used].map((number) => number + 1)
    )
    if (page.meta?.[NEXT_FRAME_NUMBER_META] !== nextNumber) {
      page.meta = { ...page.meta, [NEXT_FRAME_NUMBER_META]: nextNumber }
      updatedFrameNumberPageIds.push(page.id)
    }
  }
  const changed = migratedMetadataRecordIds.length > 0 || migratedShapeIds.length > 0 || numberedFrameIds.length > 0 || updatedFrameNumberPageIds.length > 0 || repairedStrokeIds.length > 0 || reflowedTextShapeIds.length > 0
  return {
    snapshot: changed ? next : snapshot,
    changed,
    migratedMetadataRecordIds,
    migratedShapeIds,
    numberedFrameIds,
    updatedFrameNumberPageIds,
    repairedStrokeIds,
    reflowedTextShapeIds
  }
}

function identityMatrix() {
  return { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }
}

function multiply(left, right) {
  return {
    a: left.a * right.a + left.c * right.b,
    b: left.b * right.a + left.d * right.b,
    c: left.a * right.c + left.c * right.d,
    d: left.b * right.c + left.d * right.d,
    e: left.a * right.e + left.c * right.f + left.e,
    f: left.b * right.e + left.d * right.f + left.f
  }
}

function shapeMatrix(shape) {
  const angle = finite(shape?.rotation)
  const cosine = Math.cos(angle)
  const sine = Math.sin(angle)
  return {
    a: cosine,
    b: sine,
    c: -sine,
    d: cosine,
    e: finite(shape?.x),
    f: finite(shape?.y)
  }
}

function applyMatrix(matrix, point) {
  return {
    x: matrix.a * point.x + matrix.c * point.y + matrix.e,
    y: matrix.b * point.x + matrix.d * point.y + matrix.f
  }
}

export function localBoundsForShape(shape) {
  const metaBounds = shape?.meta?.hardwareLearningBounds
  if (metaBounds && [metaBounds.x, metaBounds.y, metaBounds.w, metaBounds.h].every(Number.isFinite)) {
    return { x: metaBounds.x, y: metaBounds.y, w: Math.max(1, metaBounds.w), h: Math.max(1, metaBounds.h) }
  }
  if (shape?.type === 'arrow') {
    const start = shape.props?.start ?? { x: 0, y: 0 }
    const end = shape.props?.end ?? { x: 0, y: 0 }
    const x = Math.min(finite(start.x), finite(end.x))
    const y = Math.min(finite(start.y), finite(end.y))
    return {
      x,
      y,
      w: Math.max(1, Math.abs(finite(end.x) - finite(start.x))),
      h: Math.max(1, Math.abs(finite(end.y) - finite(start.y)))
    }
  }
  return {
    x: 0,
    y: 0,
    w: Math.max(1, finite(shape?.props?.w, shape?.type === 'text' ? 160 : 1)),
    h: Math.max(1, finite(shape?.props?.h, shape?.type === 'text' ? 40 : 1))
  }
}

export function pageBoundsForShape(store, shape) {
  const local = localBoundsForShape(shape)
  let matrix = identityMatrix()
  const chain = []
  let current = shape
  const visited = new Set()
  while (current?.typeName === 'shape' && !visited.has(current.id)) {
    visited.add(current.id)
    chain.unshift(current)
    current = store?.[current.parentId]
  }
  for (const entry of chain) matrix = multiply(matrix, shapeMatrix(entry))
  const corners = [
    applyMatrix(matrix, { x: local.x, y: local.y }),
    applyMatrix(matrix, { x: local.x + local.w, y: local.y }),
    applyMatrix(matrix, { x: local.x + local.w, y: local.y + local.h }),
    applyMatrix(matrix, { x: local.x, y: local.y + local.h })
  ]
  const minX = Math.min(...corners.map((corner) => corner.x))
  const minY = Math.min(...corners.map((corner) => corner.y))
  const maxX = Math.max(...corners.map((corner) => corner.x))
  const maxY = Math.max(...corners.map((corner) => corner.y))
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY }
}

export function shapeIntersectsViewport(store, shape, viewport, margin = 0) {
  if (!viewport || !shape) return false
  const values = [viewport.x, viewport.y, viewport.w, viewport.h]
  if (!values.every((value) => Number.isFinite(Number(value))) || viewport.w <= 0 || viewport.h <= 0) {
    return false
  }
  const padding = Math.max(0, Number.isFinite(Number(margin)) ? Number(margin) : 0)
  const bounds = pageBoundsForShape(store, shape)
  return bounds.x + bounds.w >= viewport.x - padding &&
    bounds.y + bounds.h >= viewport.y - padding &&
    bounds.x <= viewport.x + viewport.w + padding &&
    bounds.y <= viewport.y + viewport.h + padding
}

export function unionBounds(bounds) {
  const valid = bounds.filter(Boolean)
  if (!valid.length) return null
  const x = Math.min(...valid.map((item) => item.x))
  const y = Math.min(...valid.map((item) => item.y))
  const right = Math.max(...valid.map((item) => item.x + item.w))
  const bottom = Math.max(...valid.map((item) => item.y + item.h))
  return { x, y, w: right - x, h: bottom - y }
}

export function shapeRole(shape) {
  if (shape?.type === 'image') return 'source-image'
  if (shape?.meta?.hardwareLearningFrame === true) return 'selection-frame'
  if (shape?.meta?.hardwareLearningKind === 'note') return 'question-note'
  if (LEARNING_KINDS.has(shape?.meta?.hardwareLearningKind)) return 'annotation'
  return 'other'
}

export function serializeSelectedShape(snapshot, shape) {
  const asset = shape?.props?.assetId ? snapshot.store[shape.props.assetId] : null
  return {
    id: shape.id,
    type: shape.type,
    parentId: shape.parentId ?? null,
    x: shape.x ?? null,
    y: shape.y ?? null,
    rotation: shape.rotation ?? null,
    meta: shape.meta ?? null,
    role: shapeRole(shape),
    pageBounds: pageBoundsForShape(snapshot.store, shape),
    props: shape.props ?? null,
    asset: asset
      ? {
          id: asset.id,
          type: asset.type,
          name: asset.props?.name ?? null,
          src: asset.props?.src ?? null,
          w: asset.props?.w ?? null,
          h: asset.props?.h ?? null,
          mimeType: asset.props?.mimeType ?? null,
          fileSize: asset.props?.fileSize ?? null,
          meta: asset.meta ?? null
        }
      : null
  }
}

export function selectionState(snapshot, pageId, selectedShapeIds, revision, updatedAt = new Date().toISOString()) {
  const selectedShapes = selectedShapeIds
    .map((id) => snapshot?.store?.[id])
    .filter((shape) => shape?.typeName === 'shape' && pageIdForShape(snapshot.store, shape) === pageId)
    .map((shape) => serializeSelectedShape(snapshot, shape))
  return {
    version: LEARNING_CANVAS_VERSION,
    selectionRevision: revision,
    currentPageId: pageId,
    selectedShapes,
    updatedAt
  }
}

export function addShape(snapshot, shape) {
  const next = cloneSnapshot(snapshot)
  const inserted = cloneSnapshot(shape)
  if (inserted.meta?.hardwareLearningFrame === true) {
    const pageId = pageIdForShape(next.store, inserted) ?? inserted.parentId
    const frameNumber = learningFrameNumber(inserted) ?? nextLearningFrameNumber(next, pageId)
    inserted.meta = { ...inserted.meta, hardwareLearningFrameNumber: frameNumber }
    reserveLearningFrameNumber(next, pageId, frameNumber)
  }
  next.store[inserted.id] = inserted
  return next
}

export function updateShape(snapshot, shape) {
  if (!snapshot?.store?.[shape.id]) return snapshot
  const next = cloneSnapshot(snapshot)
  next.store[shape.id] = shape
  return next
}

export function updateShapes(snapshot, shapes) {
  const valid = shapes.filter((shape) => snapshot?.store?.[shape.id])
  if (!valid.length) return snapshot
  const next = cloneSnapshot(snapshot)
  for (const shape of valid) next.store[shape.id] = shape
  return next
}

export function styleLearningShapes(snapshot, shapeIds, stylePatch) {
  const next = cloneSnapshot(snapshot)
  const updated = []
  for (const id of shapeIds) {
    const shape = next.store[id]
    if (shape?.typeName !== 'shape' || shape.type === 'image') continue
    if (!shape.meta?.hardwareLearningAnnotation && !shape.meta?.hardwareLearningFrame) continue
    const style = normalizeLearningStyle({
      color: shape.props?.color,
      fill: shape.props?.fill,
      dash: shape.props?.dash,
      size: shape.props?.size,
      opacity: shape.opacity,
      ...stylePatch
    })
    shape.opacity = style.opacity
    shape.props = {
      ...shape.props,
      color: style.color,
      labelColor: style.color,
      fill: style.fill,
      dash: style.dash,
      size: style.size
    }
    if (['text', 'note'].includes(shape.meta?.hardwareLearningKind) && Object.hasOwn(stylePatch, 'size')) {
      next.store[id] = updateLearningTextShapeContent(shape, shape.meta?.hardwareLearningText || '', style)
    }
    updated.push(id)
  }
  return { snapshot: updated.length ? next : snapshot, updated }
}

export function duplicateLearningShapes(snapshot, shapeIds, offset = { x: 28, y: 28 }) {
  let next = cloneSnapshot(snapshot)
  const duplicated = []
  for (const id of shapeIds) {
    const source = next.store[id]
    if (source?.typeName !== 'shape' || source.type === 'image') continue
    if (!source.meta?.hardwareLearningAnnotation && !source.meta?.hardwareLearningFrame) continue
    const copy = cloneSnapshot(source)
    copy.id = createRecordId()
    copy.index = nextShapeIndex(next, pageIdForShape(next.store, source))
    copy.x = finite(source.x) + finite(offset.x, 28)
    copy.y = finite(source.y) + finite(offset.y, 28)
    copy.meta = { ...copy.meta, hardwareLearningDuplicatedFrom: source.id }
    if (source.meta?.hardwareLearningFrame === true) {
      const pageId = pageIdForShape(next.store, source)
      const frameNumber = nextLearningFrameNumber(next, pageId)
      copy.meta.hardwareLearningFrameNumber = frameNumber
      reserveLearningFrameNumber(next, pageId, frameNumber)
    }
    next.store[copy.id] = copy
    duplicated.push(copy.id)
  }
  return { snapshot: duplicated.length ? next : snapshot, duplicated }
}

export function deleteLearningShapes(snapshot, shapeIds) {
  const next = cloneSnapshot(snapshot)
  const deleted = []
  for (const id of shapeIds) {
    const shape = next.store[id]
    if (shape?.typeName !== 'shape' || shape.type === 'image') continue
    if (!shape.meta?.hardwareLearningAnnotation && !shape.meta?.hardwareLearningFrame) continue
    delete next.store[id]
    deleted.push(id)
  }
  return { snapshot: deleted.length ? next : snapshot, deleted }
}

export function deleteImportedImages(snapshot, shapeIds) {
  const next = cloneSnapshot(snapshot)
  const deleted = []
  const candidateAssetIds = new Set()
  for (const id of new Set(shapeIds)) {
    const shape = next.store[id]
    if (shape?.typeName !== 'shape' || shape.type !== 'image') continue
    if (typeof shape.props?.assetId === 'string') candidateAssetIds.add(shape.props.assetId)
    delete next.store[id]
    deleted.push(id)
  }

  if (!deleted.length) return { snapshot, deleted, removedAssets: [] }

  const referencedAssetIds = new Set(
    Object.values(next.store)
      .filter((record) => record?.typeName === 'shape' && record.type === 'image')
      .map((shape) => shape.props?.assetId)
      .filter((assetId) => typeof assetId === 'string')
  )
  const removedAssets = []
  for (const assetId of candidateAssetIds) {
    if (referencedAssetIds.has(assetId)) continue
    const asset = next.store[assetId]
    if (asset?.typeName !== 'asset' || asset.type !== 'image') continue
    delete next.store[assetId]
    removedAssets.push(assetId)
  }

  return { snapshot: next, deleted, removedAssets }
}

export function deleteSelectedShapes(snapshot, shapeIds, { includeImages = false } = {}) {
  const requestedIds = [...new Set(shapeIds)]
  const imageIds = includeImages
    ? requestedIds.filter((id) => snapshot?.store?.[id]?.typeName === 'shape' && snapshot.store[id]?.type === 'image')
    : []
  const annotationIds = requestedIds.filter((id) => {
    const shape = snapshot?.store?.[id]
    return shape?.typeName === 'shape' && shape.type !== 'image'
  })
  const imageResult = deleteImportedImages(snapshot, imageIds)
  const annotationResult = deleteLearningShapes(imageResult.snapshot, annotationIds)
  return {
    snapshot: annotationResult.snapshot,
    deleted: [...imageResult.deleted, ...annotationResult.deleted],
    deletedImages: imageResult.deleted,
    deletedAnnotations: annotationResult.deleted,
    removedAssets: imageResult.removedAssets
  }
}

export function setImageLockState(snapshot, shapeIds, isLocked) {
  const requested = new Set(shapeIds)
  const updated = Object.values(snapshot?.store ?? {})
    .filter((shape) => requested.has(shape?.id) && shape.typeName === 'shape' && shape.type === 'image')
    .filter((shape) => shape.isLocked !== isLocked)
    .map((shape) => ({ ...shape, isLocked }))
  return {
    snapshot: updated.length ? updateShapes(snapshot, updated) : snapshot,
    updated: updated.map((shape) => shape.id),
    isLocked
  }
}

export function translateShape(shape, delta) {
  return {
    ...shape,
    x: finite(shape.x) + delta.x,
    y: finite(shape.y) + delta.y
  }
}

export function resizeRectangleShape(shape, bounds) {
  if (shape?.type !== 'geo') return shape
  const mode = shape.meta?.hardwareLearningKind
  const textBounds = ['note', 'text'].includes(mode)
    ? learningTextBoundsForContent({
        mode,
        text: shape.meta?.hardwareLearningText || '',
        style: {
          color: shape.props?.color,
          fill: shape.props?.fill,
          dash: shape.props?.dash,
          size: shape.props?.size,
          opacity: shape.opacity
        },
        currentBounds: bounds,
        autoSize: false
      })
    : bounds
  return {
    ...shape,
    x: bounds.x,
    y: bounds.y,
    meta: {
      ...shape.meta,
      ...(['note', 'text'].includes(mode) ? { hardwareLearningTextAutoSize: false } : {}),
      hardwareLearningBounds: { x: 0, y: 0, w: textBounds.w, h: textBounds.h }
    },
    props: {
      ...shape.props,
      w: textBounds.w,
      h: textBounds.h
    }
  }
}

export const MIN_CAMERA_ZOOM = 0.08
export const MAX_CAMERA_ZOOM = 4

export function normalizeCamera(camera = {}) {
  const rawZoom = Number(camera?.z)
  const z = Number.isFinite(rawZoom) && rawZoom > 0
    ? Math.min(MAX_CAMERA_ZOOM, Math.max(MIN_CAMERA_ZOOM, rawZoom))
    : 1
  return {
    x: Number.isFinite(Number(camera?.x)) ? Number(camera.x) : 0,
    y: Number.isFinite(Number(camera?.y)) ? Number(camera.y) : 0,
    z
  }
}

export function pageToScreen(point, camera) {
  const safeCamera = normalizeCamera(camera)
  return {
    x: point.x * safeCamera.z + safeCamera.x,
    y: point.y * safeCamera.z + safeCamera.y
  }
}

export function screenToPage(point, camera) {
  const safeCamera = normalizeCamera(camera)
  return {
    x: (point.x - safeCamera.x) / safeCamera.z,
    y: (point.y - safeCamera.y) / safeCamera.z
  }
}

export function zoomCameraAt(camera, screenPoint, zoom) {
  const safeCamera = normalizeCamera(camera)
  const requestedZoom = Number(zoom)
  const nextZoom = Number.isFinite(requestedZoom)
    ? Math.min(MAX_CAMERA_ZOOM, Math.max(MIN_CAMERA_ZOOM, requestedZoom))
    : requestedZoom === Number.POSITIVE_INFINITY
      ? MAX_CAMERA_ZOOM
      : requestedZoom === Number.NEGATIVE_INFINITY
        ? MIN_CAMERA_ZOOM
        : safeCamera.z
  const pagePoint = screenToPage(screenPoint, safeCamera)
  return {
    x: screenPoint.x - pagePoint.x * nextZoom,
    y: screenPoint.y - pagePoint.y * nextZoom,
    z: nextZoom
  }
}

export function fitCamera(bounds, viewport, padding = 72) {
  if (!bounds || viewport.width <= 0 || viewport.height <= 0) return { x: 0, y: 0, z: 1 }
  const availableWidth = Math.max(1, viewport.width - padding * 2)
  const availableHeight = Math.max(1, viewport.height - padding * 2)
  const z = Math.min(MAX_CAMERA_ZOOM, Math.max(MIN_CAMERA_ZOOM, Math.min(availableWidth / bounds.w, availableHeight / bounds.h)))
  return {
    x: (viewport.width - bounds.w * z) / 2 - bounds.x * z,
    y: (viewport.height - bounds.h * z) / 2 - bounds.y * z,
    z
  }
}
