import assert from 'node:assert/strict'
import test from 'node:test'

import {
  cameraAfterWheel,
  canMoveCanvasShape,
  completeTextEditPointerActivation,
  escapeAction,
  learningTextEditMode,
  learningTextEditState,
  nudgeDeltaForKey,
  rightClickCanvasAction,
  selectionForShapePointerDown,
  shouldBeginCanvasTextFromDoubleClick,
  shouldBeginTextEditFromActivation,
  shouldBeginTextEditFromPointerDown,
  translateCanvasSelection
} from './interaction.js'

function snapshot() {
  return {
    store: {
      'shape:a': {
        id: 'shape:a', typeName: 'shape', type: 'geo', parentId: 'page:page', x: 10, y: 20,
        meta: { hardwareLearningAnnotation: true }
      },
      'shape:image-unlocked': {
        id: 'shape:image-unlocked', typeName: 'shape', type: 'image', parentId: 'page:page', x: 30, y: 40,
        isLocked: false, meta: { hardwareLearningEvidence: true }
      },
      'shape:image-locked': {
        id: 'shape:image-locked', typeName: 'shape', type: 'image', parentId: 'page:page', x: 50, y: 60,
        isLocked: true, meta: { hardwareLearningEvidence: true }
      }
    }
  }
}

test('shape pointer selection retains an existing multi-selection for dragging', () => {
  assert.deepEqual(selectionForShapePointerDown(['shape:a', 'shape:b'], 'shape:a'), ['shape:a', 'shape:b'])
  assert.deepEqual(selectionForShapePointerDown(['shape:a'], 'shape:b', { shiftKey: true }), ['shape:a', 'shape:b'])
  assert.deepEqual(selectionForShapePointerDown(['shape:a'], 'shape:a', { shiftKey: true }), [])
})

test('text and sticky notes enter editing on a double activation only', () => {
  const text = { id: 'shape:text', type: 'geo', meta: { hardwareLearningKind: 'text', hardwareLearningText: '测试1' } }
  const note = { id: 'shape:note', type: 'geo', meta: { hardwareLearningKind: 'note', hardwareLearningText: '便签1' } }
  const frame = { id: 'shape:frame', type: 'geo', meta: { hardwareLearningFrame: true, hardwareLearningKind: 'frame' } }

  assert.equal(learningTextEditMode(text), 'text')
  assert.equal(learningTextEditMode(note), 'note')
  assert.deepEqual(
    learningTextEditState({ x: 12, y: 34, ...text }),
    { point: { x: 12, y: 34 }, text: '测试1', shapeId: 'shape:text', mode: 'text' }
  )
  assert.equal(shouldBeginTextEditFromActivation(text, { eventType: 'click', detail: 1 }), false)
  assert.equal(shouldBeginTextEditFromActivation(text, { eventType: 'click', detail: 2 }), true)
  assert.equal(shouldBeginTextEditFromActivation(note, { eventType: 'dblclick', detail: 0 }), true)
  assert.equal(shouldBeginTextEditFromActivation(frame, { eventType: 'click', detail: 2 }), false)

  const completed = completeTextEditPointerActivation(
    { shapeId: text.id, point: { x: 80, y: 90 }, pointerType: 'mouse', timeStamp: 100 },
    { point: { x: 82, y: 93 }, pointerType: 'mouse', timeStamp: 140 }
  )
  assert.deepEqual(completed, {
    shapeId: text.id,
    point: { x: 82, y: 93 },
    pointerType: 'mouse',
    timeStamp: 140
  })
  assert.equal(shouldBeginTextEditFromPointerDown(text, completed, {
    button: 0,
    point: { x: 84, y: 95 },
    pointerType: 'mouse',
    timeStamp: 260
  }), true)
  assert.equal(shouldBeginTextEditFromPointerDown(note, completed, {
    button: 0,
    point: { x: 84, y: 95 },
    pointerType: 'mouse',
    timeStamp: 260
  }), false)
  assert.equal(shouldBeginTextEditFromPointerDown(frame, completed, {
    button: 0,
    point: { x: 84, y: 95 },
    pointerType: 'mouse',
    timeStamp: 260
  }), false)
  assert.equal(shouldBeginTextEditFromPointerDown(text, completed, {
    button: 0,
    point: { x: 84, y: 95 },
    pointerType: 'mouse',
    timeStamp: 700
  }), false)
  assert.equal(completeTextEditPointerActivation(
    { shapeId: text.id, point: { x: 80, y: 90 }, pointerType: 'mouse', timeStamp: 100 },
    { point: { x: 100, y: 110 }, pointerType: 'mouse', timeStamp: 140 }
  ), null)
})

test('select-mode double-click places text without stealing existing text edits or resize handles', () => {
  assert.equal(shouldBeginCanvasTextFromDoubleClick({ tool: 'select', button: 0, detail: 2 }), true)
  assert.equal(shouldBeginCanvasTextFromDoubleClick({ tool: 'select', button: 0, detail: 2, targetIsText: true }), false)
  assert.equal(shouldBeginCanvasTextFromDoubleClick({ tool: 'select', button: 0, detail: 2, targetIsControl: true }), false)
  assert.equal(shouldBeginCanvasTextFromDoubleClick({ tool: 'text', button: 0, detail: 2 }), false)
  assert.equal(shouldBeginCanvasTextFromDoubleClick({ tool: 'select', button: 0, detail: 1 }), false)
  assert.equal(shouldBeginCanvasTextFromDoubleClick({ tool: 'select', button: 0, detail: 2, shiftKey: true }), false)
})

test('right click exits active canvas modes while preserving select-mode right-drag pan', () => {
  assert.equal(rightClickCanvasAction({ tool: 'text', hasTextDraft: true }), 'cancel-text')
  assert.equal(rightClickCanvasAction({ tool: 'frame' }), 'select')
  assert.equal(rightClickCanvasAction({ tool: 'select', hasGesture: true }), 'select')
  assert.equal(rightClickCanvasAction({ tool: 'select' }), 'pan')
})

test('multi-selection movement preserves locked schematic evidence', () => {
  const initial = snapshot()
  assert.equal(canMoveCanvasShape(initial.store['shape:image-unlocked']), true)
  assert.equal(canMoveCanvasShape(initial.store['shape:image-locked']), false)
  const moved = translateCanvasSelection(initial, Object.keys(initial.store), { x: 5, y: -3 })
  assert.deepEqual(moved.updated.sort(), ['shape:a', 'shape:image-unlocked'])
  assert.deepEqual({ x: moved.snapshot.store['shape:a'].x, y: moved.snapshot.store['shape:a'].y }, { x: 15, y: 17 })
  assert.deepEqual(
    { x: moved.snapshot.store['shape:image-unlocked'].x, y: moved.snapshot.store['shape:image-unlocked'].y },
    { x: 35, y: 37 }
  )
  assert.deepEqual(
    { x: moved.snapshot.store['shape:image-locked'].x, y: moved.snapshot.store['shape:image-locked'].y },
    { x: 50, y: 60 }
  )
})

test('wheel zooms at the pointer, shift pans horizontally, and ctrl remains zoom-compatible', () => {
  const camera = { x: 10, y: 20, z: 1 }
  const zoomed = cameraAfterWheel(camera, { deltaX: 0, deltaY: -100, deltaMode: 0 }, { x: 100, y: 80 })
  assert.equal(zoomed.kind, 'zoom')
  assert.ok(zoomed.camera.z > 1)
  assert.notEqual(zoomed.camera.x, camera.x)
  assert.deepEqual(
    cameraAfterWheel(camera, { deltaX: 0, deltaY: 30, deltaMode: 0, shiftKey: true }, { x: 100, y: 80 }).camera,
    { x: -20, y: 20, z: 1 }
  )
  const ctrlZoomed = cameraAfterWheel(camera, { deltaX: 0, deltaY: 100, deltaMode: 0, ctrlKey: true }, { x: 100, y: 80 })
  assert.equal(ctrlZoomed.kind, 'zoom')
  assert.ok(ctrlZoomed.camera.z < 1)
})

test('extreme wheel input stays finite and approaches safe zoom limits gradually', () => {
  const pointer = { x: 400, y: 300 }
  const zoomedIn = cameraAfterWheel(
    { x: 0, y: 0, z: 1 },
    { deltaX: 0, deltaY: Number.NEGATIVE_INFINITY, deltaMode: 0 },
    pointer
  ).camera
  const zoomedOut = cameraAfterWheel(
    { x: 0, y: 0, z: 1 },
    { deltaX: 0, deltaY: Number.POSITIVE_INFINITY, deltaMode: 0 },
    pointer
  ).camera
  assert.ok(zoomedIn.z > 1 && zoomedIn.z < 4)
  assert.ok(zoomedOut.z < 1 && zoomedOut.z > 0.08)
  assert.ok(Object.values(zoomedIn).every(Number.isFinite))
  assert.ok(Object.values(zoomedOut).every(Number.isFinite))
})

test('keyboard helpers implement nudge and layered Escape', () => {
  assert.deepEqual(nudgeDeltaForKey('ArrowLeft'), { x: -1, y: 0 })
  assert.deepEqual(nudgeDeltaForKey('ArrowDown', { shiftKey: true }), { x: 0, y: 10 })
  assert.equal(escapeAction({ hasGesture: true, openMenu: 'main', tool: 'pen', selectedCount: 1 }), 'cancel-gesture')
  assert.equal(escapeAction({ hasGesture: false, openMenu: 'main', tool: 'pen', selectedCount: 1 }), 'close-menu')
  assert.equal(escapeAction({ hasGesture: false, openMenu: null, tool: 'pen', selectedCount: 1 }), 'select-tool')
  assert.equal(escapeAction({ hasGesture: false, openMenu: null, tool: 'select', selectedCount: 1 }), 'clear-selection')
})
