import { layoutLearningText, localBoundsForShape, pageBoundsForShape, shapesForPage, unionBounds } from './model.js'

const COLOR_MAP = {
  black: '#1f2937',
  blue: '#2563eb',
  green: '#16a34a',
  grey: '#64748b',
  'light-blue': '#38bdf8',
  'light-green': '#86efac',
  'light-red': '#fca5a5',
  'light-violet': '#c4b5fd',
  orange: '#f97316',
  red: '#dc2626',
  violet: '#7c3aed',
  yellow: '#eab308'
}

const SIZE_STROKES = { s: 2, m: 3, l: 5, xl: 8 }

export function strokeWidthForSize(size, fallback = 3) {
  return SIZE_STROKES[size] || fallback
}

export function dashArrayForStyle(dash, width = 3) {
  if (dash === 'dashed') return `${width * 3} ${width * 2}`
  if (dash === 'dotted') return `${width * 0.5} ${width * 2}`
  if (dash === 'draw') return `${width * 2.4} ${width * 1.5}`
  return 'none'
}

export function colorValue(color, fallback = '#7c3aed') {
  return COLOR_MAP[color] || fallback
}

function escapeXml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;')
}

function polylinePoints(shape) {
  return (shape.meta?.hardwareLearningPoints ?? [])
    .map((point) => `${Number(point.x).toFixed(2)},${Number(point.y).toFixed(2)}`)
    .join(' ')
}

function shapeSvg(shape, snapshot, assetSources) {
  const transform = `translate(${shape.x || 0} ${shape.y || 0}) rotate(${((shape.rotation || 0) * 180) / Math.PI})`
  const opacity = Math.min(1, Math.max(0.1, Number(shape.opacity) || 1))
  if (shape.type === 'image') {
    const asset = snapshot.store[shape.props?.assetId]
    const href = assetSources.get(asset?.props?.src) || asset?.props?.src || ''
    return `<image data-shape-id="${escapeXml(shape.id)}" href="${escapeXml(href)}" width="${shape.props?.w || 1}" height="${shape.props?.h || 1}" transform="${transform}" opacity="${opacity}" preserveAspectRatio="none"/>`
  }
  if (shape.type === 'arrow') {
    const start = shape.props?.start ?? { x: 0, y: 0 }
    const end = shape.props?.end ?? { x: 1, y: 1 }
    const stroke = colorValue(shape.props?.color, '#2563eb')
    const width = strokeWidthForSize(shape.props?.size)
    const marker = shape.props?.arrowheadEnd === 'none' ? '' : ' marker-end="url(#hardware-learning-arrow)"'
    return `<line data-shape-id="${escapeXml(shape.id)}" x1="${start.x}" y1="${start.y}" x2="${end.x}" y2="${end.y}" transform="${transform}" opacity="${opacity}" stroke="${stroke}" stroke-width="${width}" stroke-dasharray="${dashArrayForStyle(shape.props?.dash, width)}"${marker}/>`
  }
  if (shape.type === 'draw' || shape.type === 'highlight') {
    const points = polylinePoints(shape)
    const stroke = colorValue(shape.props?.color, shape.type === 'highlight' ? '#facc15' : '#7c3aed')
    const width = shape.type === 'highlight'
      ? strokeWidthForSize(shape.props?.size, 5) * 4
      : strokeWidthForSize(shape.props?.size, 4)
    return `<polyline data-shape-id="${escapeXml(shape.id)}" points="${points}" transform="${transform}" fill="none" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" opacity="${opacity}"/>`
  }
  if (shape.type === 'geo') {
    const width = shape.props?.w || 1
    const height = shape.props?.h || 1
    const kind = shape.meta?.hardwareLearningKind
    const frame = shape.meta?.hardwareLearningFrame === true
    const note = kind === 'note'
    const textOnly = kind === 'text'
    const highlight = kind === 'highlight'
    const stroke = colorValue(shape.props?.color, frame ? '#7c3aed' : '#2563eb')
    const fill = shape.props?.fill === 'solid'
        ? stroke
        : shape.props?.fill === 'semi' || highlight
          ? stroke
          : 'none'
    const fillOpacity = note
      ? shape.props?.fill === 'solid' ? 0.34 : shape.props?.fill === 'semi' ? 0.18 : 0
      : shape.props?.fill === 'solid' ? 0.92 : 0.22
    const strokeWidth = strokeWidthForSize(shape.props?.size, frame ? 4 : 3)
    const dash = dashArrayForStyle(shape.props?.dash, strokeWidth)
    const text = shape.meta?.hardwareLearningText || ''
    const frameNumber = frame && Number.isSafeInteger(shape.meta?.hardwareLearningFrameNumber) && shape.meta.hardwareLearningFrameNumber > 0
      ? shape.meta.hardwareLearningFrameNumber
      : null
    const badgeWidth = frameNumber === null ? 0 : Math.max(30, String(frameNumber).length * 9 + 18)
    const frameBadge = frameNumber === null
      ? ''
      : `<g class="learning-frame-number"><rect x="7" y="7" width="${badgeWidth}" height="28" rx="14" fill="${stroke}" stroke="#ffffff" stroke-width="2"/><text x="${7 + badgeWidth / 2}" y="21" dominant-baseline="middle" text-anchor="middle" font-family="system-ui,sans-serif" font-size="15" font-weight="700" fill="#ffffff">${frameNumber}</text></g>`
    const textLayout = layoutLearningText(text, { width, height, size: shape.props?.size })
    const textSvg = textLayout.lines.map((line, index) =>
      `<tspan x="14" dy="${index === 0 ? textLayout.firstBaseline : textLayout.lineHeight}">${escapeXml(line)}</tspan>`
    ).join('')
    const geometry = shape.props?.geo === 'ellipse'
      ? `<ellipse cx="${width / 2}" cy="${height / 2}" rx="${width / 2}" ry="${height / 2}" fill="${fill}" fill-opacity="${fillOpacity}" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-dasharray="${dash}"/>`
      : textOnly
        ? ''
        : `<rect width="${width}" height="${height}" rx="${note ? 10 : 3}" fill="${fill}" fill-opacity="${fillOpacity}" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-dasharray="${dash}"/>`
    return `<g data-shape-id="${escapeXml(shape.id)}" transform="${transform}" opacity="${opacity}">${geometry}${frameBadge}<text font-family="system-ui,sans-serif" font-size="${textLayout.fontSize}" fill="${textOnly ? stroke : '#1f2937'}">${textSvg}</text></g>`
  }
  const bounds = localBoundsForShape(shape)
  return `<rect data-shape-id="${escapeXml(shape.id)}" x="${bounds.x}" y="${bounds.y}" width="${bounds.w}" height="${bounds.h}" transform="${transform}" fill="none" stroke="#94a3b8" stroke-width="2"/>`
}

export function exportBoundsForPage(snapshot, pageId, selectedShapeIds = []) {
  const requested = selectedShapeIds.length
    ? selectedShapeIds.map((id) => snapshot.store[id]).filter(Boolean)
    : shapesForPage(snapshot, pageId)
  return unionBounds(requested.map((shape) => pageBoundsForShape(snapshot.store, shape)))
}

function boundsIntersect(left, right) {
  return left.x <= right.x + right.w
    && left.x + left.w >= right.x
    && left.y <= right.y + right.h
    && left.y + left.h >= right.y
}

export function buildLearningCanvasSvg({ snapshot, pageId, assetSources = new Map(), selectedShapeIds = [], padding = 32 } = {}) {
  const selected = new Set(selectedShapeIds)
  const pageShapes = shapesForPage(snapshot, pageId)
  const selectedShapes = selectedShapeIds.map((id) => snapshot.store[id]).filter(Boolean)
  const selectionBounds = selected.size
    ? unionBounds(selectedShapes.map((shape) => pageBoundsForShape(snapshot.store, shape)))
    : null
  const shapes = selectionBounds
    ? pageShapes.filter((shape) => boundsIntersect(pageBoundsForShape(snapshot.store, shape), selectionBounds))
    : pageShapes
  const rawBounds = selectionBounds
    ?? unionBounds(shapes.map((shape) => pageBoundsForShape(snapshot.store, shape)))
    ?? { x: 0, y: 0, w: 1, h: 1 }
  const bounds = {
    x: rawBounds.x - padding,
    y: rawBounds.y - padding,
    w: rawBounds.w + padding * 2,
    h: rawBounds.h + padding * 2
  }
  const body = shapes.map((shape) => shapeSvg(shape, snapshot, assetSources)).join('')
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${Math.ceil(bounds.w)}" height="${Math.ceil(bounds.h)}" viewBox="${bounds.x} ${bounds.y} ${bounds.w} ${bounds.h}"><defs><marker id="hardware-learning-arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="context-stroke"/></marker></defs><rect x="${bounds.x}" y="${bounds.y}" width="${bounds.w}" height="${bounds.h}" fill="#f8fafc"/>${body}</svg>`
  return { svg, bounds, shapeIds: shapes.map((shape) => shape.id) }
}

export function textToBase64(value) {
  const bytes = new TextEncoder().encode(value)
  let binary = ''
  const chunkSize = 0x8000
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize))
  }
  return btoa(binary)
}

export function svgDataUrl(svg) {
  return `data:image/svg+xml;base64,${textToBase64(svg)}`
}

export async function svgToPngDataUrl(svg, bounds, { maxPixels = 8_000_000, maxDimension = 4096 } = {}) {
  const scale = Math.min(
    2,
    maxDimension / Math.max(bounds.w, bounds.h, 1),
    Math.sqrt(maxPixels / Math.max(bounds.w * bounds.h, 1))
  )
  const width = Math.max(1, Math.round(bounds.w * scale))
  const height = Math.max(1, Math.round(bounds.h * scale))
  const sourceUrl = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
  try {
    const image = await new Promise((resolve, reject) => {
      const element = new Image()
      element.onload = () => resolve(element)
      element.onerror = () => reject(new Error('学习画布 SVG 无法转换为 PNG。'))
      element.src = sourceUrl
    })
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    context.fillStyle = '#f8fafc'
    context.fillRect(0, 0, width, height)
    context.drawImage(image, 0, 0, width, height)
    return { dataUrl: canvas.toDataURL('image/png'), width, height }
  } finally {
    URL.revokeObjectURL(sourceUrl)
  }
}
