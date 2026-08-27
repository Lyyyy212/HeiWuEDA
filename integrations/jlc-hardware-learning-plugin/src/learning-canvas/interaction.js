import { translateShape, updateShapes, zoomCameraAt } from './model.js'

const LINE_DELTA_PIXELS = 16
const MAX_WHEEL_ZOOM_DELTA = 160
const TEXT_EDIT_DOUBLE_ACTIVATION_MS = 500
const TEXT_EDIT_POINTER_HOLD_MS = 700
const TEXT_EDIT_POINTER_TOLERANCE_PX = 8

export function isTextEditingTarget(target) {
  const tagName = String(target?.tagName || '').toUpperCase()
  return tagName === 'INPUT' || tagName === 'TEXTAREA' || target?.isContentEditable === true
}

export function isSpaceKey(event) {
  return event?.code === 'Space' || event?.key === ' ' || event?.key === 'Spacebar'
}

export function learningTextEditMode(shape) {
  const mode = shape?.meta?.hardwareLearningKind
  return ['text', 'note'].includes(mode) ? mode : null
}

export function learningTextEditState(shape) {
  const mode = learningTextEditMode(shape)
  if (!mode || typeof shape?.id !== 'string') return null
  return {
    point: { x: Number(shape.x) || 0, y: Number(shape.y) || 0 },
    text: String(shape.meta?.hardwareLearningText || ''),
    shapeId: shape.id,
    mode
  }
}

export function shouldBeginTextEditFromActivation(shape, { eventType = 'click', detail = 0 } = {}) {
  if (!learningTextEditMode(shape)) return false
  if (eventType === 'dblclick') return true
  return eventType === 'click' && Number(detail) >= 2
}

function pointerDistance(first, second) {
  if (!first || !second) return Number.POSITIVE_INFINITY
  return Math.hypot(Number(second.x) - Number(first.x), Number(second.y) - Number(first.y))
}

export function completeTextEditPointerActivation(candidate, release = {}) {
  if (!candidate?.shapeId || !candidate.point || !release.point) return null
  const elapsed = Number(release.timeStamp) - Number(candidate.timeStamp)
  if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed > TEXT_EDIT_POINTER_HOLD_MS) return null
  if (pointerDistance(candidate.point, release.point) > TEXT_EDIT_POINTER_TOLERANCE_PX) return null
  return {
    shapeId: candidate.shapeId,
    point: { x: Number(release.point.x), y: Number(release.point.y) },
    pointerType: String(release.pointerType || candidate.pointerType || 'mouse'),
    timeStamp: Number(release.timeStamp)
  }
}

export function shouldBeginTextEditFromPointerDown(shape, previous, current = {}) {
  if (!learningTextEditMode(shape) || !previous || previous.shapeId !== shape?.id) return false
  if (Number(current.button ?? 0) !== 0 || current.shiftKey || current.ctrlKey || current.metaKey || current.altKey) return false
  if (String(previous.pointerType || 'mouse') !== String(current.pointerType || 'mouse')) return false
  const elapsed = Number(current.timeStamp) - Number(previous.timeStamp)
  if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed > TEXT_EDIT_DOUBLE_ACTIVATION_MS) return false
  return pointerDistance(previous.point, current.point) <= TEXT_EDIT_POINTER_TOLERANCE_PX
}

export function shouldBeginCanvasTextFromDoubleClick({
  tool = 'select',
  button = 0,
  detail = 0,
  targetIsText = false,
  targetIsControl = false,
  shiftKey = false,
  ctrlKey = false,
  metaKey = false,
  altKey = false
} = {}) {
  return tool === 'select' && Number(button) === 0 && Number(detail) >= 2 &&
    !targetIsText && !targetIsControl &&
    !shiftKey && !ctrlKey && !metaKey && !altKey
}

export function rightClickCanvasAction({ tool = 'select', hasTextDraft = false, hasGesture = false } = {}) {
  if (hasTextDraft) return 'cancel-text'
  if (hasGesture || tool !== 'select') return 'select'
  return 'pan'
}

export function selectionForShapePointerDown(selectedIds, shapeId, { shiftKey = false } = {}) {
  const current = Array.isArray(selectedIds) ? selectedIds : []
  if (shiftKey) {
    return current.includes(shapeId)
      ? current.filter((id) => id !== shapeId)
      : [...current, shapeId]
  }
  return current.includes(shapeId) ? current : [shapeId]
}

export function canMoveCanvasShape(shape) {
  if (!shape || shape.typeName !== 'shape') return false
  if (shape.type === 'image') return shape.isLocked !== true
  return shape.meta?.hardwareLearningAnnotation === true || shape.meta?.hardwareLearningFrame === true
}

export function movableShapeIds(snapshot, shapeIds) {
  return [...new Set(shapeIds)]
    .filter((id) => canMoveCanvasShape(snapshot?.store?.[id]))
}

export function translateCanvasSelection(snapshot, shapeIds, delta) {
  if (!snapshot?.store || (!delta?.x && !delta?.y)) return { snapshot, updated: [] }
  const updatedShapes = movableShapeIds(snapshot, shapeIds)
    .map((id) => translateShape(snapshot.store[id], delta))
  return {
    snapshot: updatedShapes.length ? updateShapes(snapshot, updatedShapes) : snapshot,
    updated: updatedShapes.map((shape) => shape.id)
  }
}

export function nudgeDeltaForKey(key, { shiftKey = false } = {}) {
  const amount = shiftKey ? 10 : 1
  if (key === 'ArrowLeft') return { x: -amount, y: 0 }
  if (key === 'ArrowRight') return { x: amount, y: 0 }
  if (key === 'ArrowUp') return { x: 0, y: -amount }
  if (key === 'ArrowDown') return { x: 0, y: amount }
  return null
}

function wheelPixels(value, deltaMode, pageSize) {
  if (deltaMode === 1) return value * LINE_DELTA_PIXELS
  if (deltaMode === 2) return value * Math.max(1, pageSize)
  return value
}

export function cameraAfterWheel(camera, wheel, screenPoint, viewport = {}) {
  const deltaX = wheelPixels(wheel.deltaX || 0, wheel.deltaMode, viewport.width || 1)
  const deltaY = wheelPixels(wheel.deltaY || 0, wheel.deltaMode, viewport.height || 1)
  if (wheel.shiftKey && !wheel.ctrlKey && !wheel.metaKey) {
    const panX = Math.abs(deltaX) >= Math.abs(deltaY) ? deltaX : deltaY
    return {
      camera: {
        ...camera,
        x: camera.x - panX
      },
      kind: 'pan'
    }
  }

  const boundedDeltaY = Math.min(MAX_WHEEL_ZOOM_DELTA, Math.max(-MAX_WHEEL_ZOOM_DELTA, deltaY))
  return {
    camera: zoomCameraAt(camera, screenPoint, camera.z * Math.exp(-boundedDeltaY * 0.002)),
    kind: 'zoom'
  }
}

export function escapeAction({ hasGesture, openMenu, tool, selectedCount }) {
  if (hasGesture) return 'cancel-gesture'
  if (openMenu) return 'close-menu'
  if (tool !== 'select') return 'select-tool'
  if (selectedCount > 0) return 'clear-selection'
  return 'none'
}
