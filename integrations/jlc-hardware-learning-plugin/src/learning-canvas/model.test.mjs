import assert from 'node:assert/strict'
import test from 'node:test'

import { applyLearningAnnotationOperations } from './annotations.js'
import { buildLearningCanvasSvg } from './export.js'
import {
  addShape,
  createArrowShape,
  createEllipseShape,
  createFrameShape,
  createLearningPage,
  createLineShape,
  createNoteShape,
  createRectangleShape,
  createStrokeShape,
  createTextShape,
  deleteImportedImages,
  deleteLearningPage,
  deleteLearningShapes,
  deleteSelectedShapes,
  duplicateLearningShapes,
  layoutLearningText,
  learningTextBoundsForContent,
  learningTextMetricsForSize,
  learningFrameNumber,
  MAX_CAMERA_ZOOM,
  migrateLegacyLearningFrames,
  MIN_CAMERA_ZOOM,
  nextLearningFrameNumber,
  normalizeCamera,
  pageBoundsForShape,
  resizeRectangleShape,
  renameLearningPage,
  screenToPage,
  selectionState,
  setImageLockState,
  shapeIntersectsViewport,
  shapeRole,
  styleLearningShapes,
  updateLearningTextShapeContent,
  zoomCameraAt
} from './model.js'

test('learning pages can be created, renamed, and deleted without touching another page', () => {
  const initial = fixtureSnapshot()
  const created = createLearningPage(initial, '电源页')
  assert.equal(created.page.name, '电源页')
  assert.equal(Object.keys(initial.store).includes(created.page.id), false)

  const renamed = renameLearningPage(created.snapshot, created.page.id, '接口页')
  assert.equal(renamed.changed, true)
  assert.equal(renamed.snapshot.store[created.page.id].name, '接口页')

  const removed = deleteLearningPage(renamed.snapshot, 'page:page')
  assert.equal(removed.deleted, true)
  assert.deepEqual(removed.acknowledgedImageShapeDeletes, ['shape:source'])
  assert.equal(removed.snapshot.store['page:page'], undefined)
  assert.equal(removed.snapshot.store['shape:source'], undefined)
  assert.equal(removed.snapshot.store['asset:source'], undefined)
  assert.equal(removed.snapshot.store[created.page.id].name, '接口页')
  assert.equal(removed.nextPageId, created.page.id)
})

test('learning page deletion refuses to remove the final page', () => {
  const result = deleteLearningPage(fixtureSnapshot(), 'page:page')
  assert.equal(result.deleted, false)
  assert.equal(result.reason, 'last-page')
})

function fixtureSnapshot() {
  return {
    schema: { schemaVersion: 2, sequences: {} },
    store: {
      'page:page': { id: 'page:page', typeName: 'page', name: 'Page 1', index: 'a1', meta: {} },
      'asset:source': {
        id: 'asset:source',
        typeName: 'asset',
        type: 'image',
        props: { name: 'source.png', src: '/page-assets/page/source.png', w: 600, h: 400, mimeType: 'image/png' },
        meta: { evidenceSource: 'official-easyeda-export' }
      },
      'shape:source': {
        id: 'shape:source',
        typeName: 'shape',
        type: 'image',
        parentId: 'page:page',
        index: 'a1',
        x: 100,
        y: 80,
        rotation: 0,
        isLocked: false,
        opacity: 1,
        props: { assetId: 'asset:source', w: 600, h: 400 },
        meta: { hardwareLearningEvidence: true }
      }
    }
  }
}

test('camera normalization repairs invalid state and zoom remains within render-safe bounds', () => {
  assert.deepEqual(normalizeCamera({ x: Number.NaN, y: Number.POSITIVE_INFINITY, z: 0 }), { x: 0, y: 0, z: 1 })
  assert.deepEqual(normalizeCamera({ x: 12, y: -8, z: 100 }), { x: 12, y: -8, z: MAX_CAMERA_ZOOM })

  const anchor = { x: 320, y: 240 }
  const camera = { x: -120, y: 35, z: 1.5 }
  const pageBefore = screenToPage(anchor, camera)
  const zoomedIn = zoomCameraAt(camera, anchor, Number.POSITIVE_INFINITY)
  const zoomedOut = zoomCameraAt(camera, anchor, Number.NEGATIVE_INFINITY)
  assert.equal(zoomedIn.z, MAX_CAMERA_ZOOM)
  assert.equal(zoomedOut.z, MIN_CAMERA_ZOOM)
  assert.deepEqual(screenToPage(anchor, zoomedIn), pageBefore)
  assert.ok(Object.values(zoomedIn).every(Number.isFinite))
  assert.ok(Object.values(zoomedOut).every(Number.isFinite))
})

test('viewport intersection culls distant high-resolution evidence without changing records', () => {
  const snapshot = fixtureSnapshot()
  const source = snapshot.store['shape:source']
  const distant = {
    ...source,
    id: 'shape:distant-source',
    x: 12_000,
    props: { ...source.props, assetId: 'asset:source' }
  }
  const viewport = { x: 0, y: 0, w: 1600, h: 900 }

  assert.equal(shapeIntersectsViewport(snapshot.store, source, viewport, 256), true)
  assert.equal(shapeIntersectsViewport(snapshot.store, distant, viewport, 256), false)
  assert.equal(shapeIntersectsViewport(snapshot.store, distant, { x: 10_500, y: 0, w: 1600, h: 900 }, 256), true)
  assert.equal(shapeIntersectsViewport(snapshot.store, distant, null, 256), false)
  assert.equal(snapshot.store['shape:source'].x, 100)
})

test('confirmed imported-image deletion removes only images and orphaned asset records', () => {
  const initial = fixtureSnapshot()
  const annotation = createRectangleShape({
    snapshot: initial,
    pageId: 'page:page',
    bounds: { x: 120, y: 100, w: 160, h: 90 },
    id: 'shape:annotation'
  })
  const snapshot = addShape(initial, annotation)
  const result = deleteImportedImages(snapshot, ['shape:source', annotation.id, 'shape:missing'])

  assert.deepEqual(result.deleted, ['shape:source'])
  assert.deepEqual(result.removedAssets, ['asset:source'])
  assert.equal(result.snapshot.store['shape:source'], undefined)
  assert.equal(result.snapshot.store['asset:source'], undefined)
  assert.ok(result.snapshot.store[annotation.id])
  assert.ok(snapshot.store['shape:source'])
  assert.ok(snapshot.store['asset:source'])
})

test('confirmed imported-image deletion keeps an asset that another image still references', () => {
  const snapshot = fixtureSnapshot()
  snapshot.store['shape:shared-source'] = {
    ...structuredClone(snapshot.store['shape:source']),
    id: 'shape:shared-source',
    index: 'a2',
    x: 760
  }
  const result = deleteImportedImages(snapshot, ['shape:source'])

  assert.deepEqual(result.deleted, ['shape:source'])
  assert.deepEqual(result.removedAssets, [])
  assert.ok(result.snapshot.store['shape:shared-source'])
  assert.ok(result.snapshot.store['asset:source'])
})

test('toolbar deletion removes a mixed image and annotation selection as one result', () => {
  const initial = fixtureSnapshot()
  const annotation = createRectangleShape({
    snapshot: initial,
    pageId: 'page:page',
    bounds: { x: 120, y: 100, w: 160, h: 90 },
    id: 'shape:annotation'
  })
  const snapshot = addShape(initial, annotation)
  const result = deleteSelectedShapes(snapshot, [annotation.id, 'shape:source'], { includeImages: true })

  assert.deepEqual(result.deletedImages, ['shape:source'])
  assert.deepEqual(result.deletedAnnotations, [annotation.id])
  assert.deepEqual(result.removedAssets, ['asset:source'])
  assert.equal(result.snapshot.store['shape:source'], undefined)
  assert.equal(result.snapshot.store[annotation.id], undefined)
  assert.equal(result.snapshot.store['asset:source'], undefined)
  assert.ok(snapshot.store['shape:source'])
  assert.ok(snapshot.store[annotation.id])
})

test('keyboard-style deletion keeps imported images protected in a mixed selection', () => {
  const initial = fixtureSnapshot()
  const annotation = createRectangleShape({
    snapshot: initial,
    pageId: 'page:page',
    bounds: { x: 120, y: 100, w: 160, h: 90 },
    id: 'shape:annotation'
  })
  const snapshot = addShape(initial, annotation)
  const result = deleteSelectedShapes(snapshot, [annotation.id, 'shape:source'])

  assert.deepEqual(result.deletedImages, [])
  assert.deepEqual(result.deletedAnnotations, [annotation.id])
  assert.ok(result.snapshot.store['shape:source'])
  assert.ok(result.snapshot.store['asset:source'])
  assert.equal(result.snapshot.store[annotation.id], undefined)
})

test('learning frame has explicit semantics and selection revision', () => {
  const initial = fixtureSnapshot()
  const frame = createFrameShape({
    snapshot: initial,
    pageId: 'page:page',
    bounds: { x: 160, y: 120, w: 180, h: 120 },
    id: 'shape:frame'
  })
  const snapshot = addShape(initial, frame)
  assert.equal(frame.meta.hardwareLearningFrame, true)
  assert.equal(learningFrameNumber(frame), 1)
  assert.equal(snapshot.store['page:page'].meta.hardwareLearningNextFrameNumber, 2)
  assert.equal(shapeRole(frame), 'selection-frame')
  const selected = selectionState(snapshot, 'page:page', [frame.id], 42, '2026-08-25T00:00:00.000Z')
  assert.equal(selected.version, 2)
  assert.equal(selected.selectionRevision, 42)
  assert.equal(selected.selectedShapes[0].role, 'selection-frame')
  assert.deepEqual(selected.selectedShapes[0].pageBounds, { x: 160, y: 120, w: 180, h: 120 })

  const styled = styleLearningShapes(snapshot, [frame.id], {
    color: 'red', fill: 'semi', dash: 'dotted', size: 'xl', opacity: 0.6
  })
  assert.deepEqual(styled.updated, [frame.id])
  assert.equal(styled.snapshot.store[frame.id].meta.hardwareLearningFrame, true)
  assert.equal(styled.snapshot.store[frame.id].props.color, 'red')
  assert.equal(styled.snapshot.store[frame.id].props.fill, 'semi')
  assert.equal(styled.snapshot.store[frame.id].props.dash, 'dotted')
  assert.equal(styled.snapshot.store[frame.id].props.size, 'xl')
  assert.equal(styled.snapshot.store[frame.id].opacity, 0.6)
})

test('ordinary rectangle is not a learning frame', () => {
  const shape = {
    id: 'shape:ordinary', typeName: 'shape', type: 'geo', parentId: 'page:page',
    x: 0, y: 0, rotation: 0, props: { geo: 'rectangle', w: 100, h: 100 }, meta: {}
  }
  assert.equal(shapeRole(shape), 'other')
})

test('learning frame numbers stay monotonic after delete and duplicate', () => {
  let snapshot = fixtureSnapshot()
  const first = createFrameShape({
    snapshot,
    pageId: 'page:page',
    bounds: { x: 20, y: 30, w: 100, h: 80 },
    id: 'shape:frame-one'
  })
  snapshot = addShape(snapshot, first)
  const second = createFrameShape({
    snapshot,
    pageId: 'page:page',
    bounds: { x: 160, y: 30, w: 100, h: 80 },
    id: 'shape:frame-two'
  })
  snapshot = addShape(snapshot, second)
  assert.equal(learningFrameNumber(snapshot.store[first.id]), 1)
  assert.equal(learningFrameNumber(snapshot.store[second.id]), 2)
  assert.equal(nextLearningFrameNumber(snapshot, 'page:page'), 3)

  snapshot = deleteLearningShapes(snapshot, [first.id]).snapshot
  const third = createFrameShape({
    snapshot,
    pageId: 'page:page',
    bounds: { x: 300, y: 30, w: 100, h: 80 },
    id: 'shape:frame-three'
  })
  snapshot = addShape(snapshot, third)
  assert.equal(learningFrameNumber(snapshot.store[third.id]), 3)

  const duplicated = duplicateLearningShapes(snapshot, [second.id])
  const copy = duplicated.snapshot.store[duplicated.duplicated[0]]
  assert.equal(learningFrameNumber(copy), 4)
  assert.equal(duplicated.snapshot.store['page:page'].meta.hardwareLearningNextFrameNumber, 5)
})

test('legacy violet hand-drawn rectangle migrates once', () => {
  const snapshot = fixtureSnapshot()
  snapshot.store['shape:legacy'] = {
    id: 'shape:legacy', typeName: 'shape', type: 'geo', parentId: 'page:page', index: 'a2',
    x: 25, y: 30, rotation: 0, isLocked: false, opacity: 1,
    props: { geo: 'rectangle', w: 80, h: 60, color: 'violet', fill: 'none', dash: 'draw' }, meta: {}
  }
  const migrated = migrateLegacyLearningFrames(snapshot)
  assert.equal(migrated.changed, true)
  assert.deepEqual(migrated.migratedShapeIds, ['shape:legacy'])
  assert.equal(migrated.snapshot.store['shape:legacy'].meta.hardwareLearningFrame, true)
  assert.equal(migrated.snapshot.store['shape:legacy'].meta.hardwareLearningFrameNumber, 1)
  assert.deepEqual(migrated.numberedFrameIds, ['shape:legacy'])
  assert.deepEqual(migrated.updatedFrameNumberPageIds, ['page:page'])
  assert.equal(migrateLegacyLearningFrames(migrated.snapshot).changed, false)
})

test('legacy metadata migrates to neutral hardware-learning keys once', () => {
  const snapshot = fixtureSnapshot()
  snapshot.store['shape:legacy-meta'] = {
    id: 'shape:legacy-meta', typeName: 'shape', type: 'geo', parentId: 'page:page', index: 'a2',
    x: 25, y: 30, rotation: 0, isLocked: false, opacity: 1,
    props: { geo: 'rectangle', w: 80, h: 60, color: 'blue', fill: 'none', dash: 'solid' },
    meta: { cowartLearningFrame: true, cowartLearningFrameNumber: 7, cowartHardwareAnnotation: true }
  }
  const migrated = migrateLegacyLearningFrames(snapshot)
  const meta = migrated.snapshot.store['shape:legacy-meta'].meta
  assert.equal(migrated.changed, true)
  assert.deepEqual(migrated.migratedMetadataRecordIds, ['shape:legacy-meta'])
  assert.equal(meta.hardwareLearningFrame, true)
  assert.equal(meta.hardwareLearningFrameNumber, 7)
  assert.equal(meta.hardwareLearningAnnotation, true)
  assert.equal(Object.keys(meta).some((key) => key.startsWith('cowart')), false)
  assert.equal(migrateLegacyLearningFrames(migrated.snapshot).changed, false)
})

test('legacy learning strokes repair empty tldraw segments', () => {
  const snapshot = fixtureSnapshot()
  snapshot.store['shape:legacy-stroke'] = {
    id: 'shape:legacy-stroke', typeName: 'shape', type: 'draw', parentId: 'page:page', index: 'a2',
    x: 10, y: 20, rotation: 0, isLocked: false, opacity: 1,
    props: { segments: [], color: 'violet', fill: 'none', dash: 'draw', size: 'm', isComplete: true, isClosed: false, isPen: false, scale: 1, scaleX: 1, scaleY: 1 },
    meta: { hardwareLearningAnnotation: true, hardwareLearningKind: 'pen', hardwareLearningPoints: [{ x: 0, y: 0, z: 0.5 }, { x: 25, y: 40, z: 0.5 }] }
  }
  const migrated = migrateLegacyLearningFrames(snapshot)
  assert.equal(migrated.changed, true)
  assert.deepEqual(migrated.repairedStrokeIds, ['shape:legacy-stroke'])
  assert.equal(migrated.snapshot.store['shape:legacy-stroke'].props.segments[0].points.length, 2)
  assert.equal(migrateLegacyLearningFrames(migrated.snapshot).changed, false)
})

test('pen, highlight, arrow and note preserve page bounds without tldraw runtime', () => {
  let snapshot = fixtureSnapshot()
  const shapes = [
    createStrokeShape({ snapshot, pageId: 'page:page', points: [{ x: 10, y: 20 }, { x: 35, y: 60 }], kind: 'pen', id: 'shape:pen' }),
    createStrokeShape({ snapshot, pageId: 'page:page', points: [{ x: 40, y: 50 }, { x: 90, y: 75 }], kind: 'highlight', id: 'shape:highlight' }),
    createArrowShape({ snapshot, pageId: 'page:page', start: { x: 5, y: 8 }, end: { x: 105, y: 58 }, id: 'shape:arrow' }),
    createNoteShape({ snapshot, pageId: 'page:page', point: { x: 200, y: 220 }, text: '电源路径', id: 'shape:note' })
  ]
  for (const shape of shapes) snapshot = addShape(snapshot, shape)
  assert.deepEqual(pageBoundsForShape(snapshot.store, snapshot.store['shape:pen']), { x: 10, y: 20, w: 25, h: 40 })
  assert.deepEqual(pageBoundsForShape(snapshot.store, snapshot.store['shape:arrow']), { x: 5, y: 8, w: 100, h: 50 })
  assert.equal(snapshot.store['shape:note'].meta.hardwareLearningText, '电源路径')
})

test('original JLC Hardware Learning geometry tools keep explicit learning semantics and styles', () => {
  let snapshot = fixtureSnapshot()
  const style = { color: 'red', fill: 'semi', dash: 'dashed', size: 'l', opacity: 0.7 }
  const shapes = [
    createRectangleShape({ snapshot, pageId: 'page:page', bounds: { x: 10, y: 20, w: 80, h: 60 }, style, id: 'shape:rectangle' }),
    createEllipseShape({ snapshot, pageId: 'page:page', bounds: { x: 110, y: 20, w: 70, h: 50 }, style, id: 'shape:ellipse' }),
    createLineShape({ snapshot, pageId: 'page:page', start: { x: 20, y: 110 }, end: { x: 180, y: 140 }, style, id: 'shape:line' }),
    createTextShape({ snapshot, pageId: 'page:page', point: { x: 30, y: 160 }, text: '信号链', style, id: 'shape:text' }),
    createNoteShape({ snapshot, pageId: 'page:page', point: { x: 210, y: 160 }, text: '控制说明', style, id: 'shape:note' })
  ]
  for (const shape of shapes) snapshot = addShape(snapshot, shape)
  assert.equal(snapshot.store['shape:rectangle'].meta.hardwareLearningKind, 'rectangle')
  assert.equal(snapshot.store['shape:ellipse'].props.geo, 'ellipse')
  assert.equal(snapshot.store['shape:line'].props.arrowheadEnd, 'none')
  assert.equal(snapshot.store['shape:text'].meta.hardwareLearningText, '信号链')
  assert.equal(shapeRole(snapshot.store['shape:rectangle']), 'annotation')

  const styled = styleLearningShapes(snapshot, ['shape:rectangle'], { color: 'green', opacity: 0.5 })
  assert.deepEqual(styled.updated, ['shape:rectangle'])
  assert.equal(styled.snapshot.store['shape:rectangle'].props.color, 'green')
  assert.equal(styled.snapshot.store['shape:rectangle'].opacity, 0.5)

  const duplicated = duplicateLearningShapes(styled.snapshot, ['shape:rectangle', 'shape:source'])
  assert.equal(duplicated.duplicated.length, 1)
  const copy = duplicated.snapshot.store[duplicated.duplicated[0]]
  assert.equal(copy.x, styled.snapshot.store['shape:rectangle'].x + 28)
  assert.equal(copy.meta.hardwareLearningDuplicatedFrom, 'shape:rectangle')

  const styledNote = styleLearningShapes(snapshot, ['shape:note'], { color: 'red', fill: 'semi' })
  assert.equal(styledNote.snapshot.store['shape:note'].props.color, 'red')
  assert.equal(styledNote.snapshot.store['shape:note'].props.fill, 'semi')

  const styledText = styleLearningShapes(snapshot, ['shape:text'], { size: 'xl' })
  assert.equal(styledText.snapshot.store['shape:text'].props.size, 'xl')
})

test('text size is preserved in the standalone SVG export', () => {
  let snapshot = fixtureSnapshot()
  const text = createTextShape({
    snapshot,
    pageId: 'page:page',
    point: { x: 20, y: 30 },
    text: '可调字号',
    style: { size: 'xl' },
    id: 'shape:large-text'
  })
  snapshot = addShape(snapshot, text)
  const result = buildLearningCanvasSvg({ snapshot, pageId: 'page:page' })
  assert.match(result.svg, /font-size="28"/u)
  assert.match(result.svg, /dy="37">可调字号<\/tspan>/u)
})

test('text and notes derive visible bounds from their full content', () => {
  const wrapped = layoutLearningText('电源路径'.repeat(24), { width: 180, height: Number.POSITIVE_INFINITY, size: 'm' })
  assert.ok(wrapped.visualLineCount > 1)
  assert.equal(wrapped.overflow, false)
  assert.ok(wrapped.requiredHeight > 54)

  const textBounds = learningTextBoundsForContent({ mode: 'text', text: '测试1继续补充说明', style: { size: 'l' } })
  assert.ok(textBounds.w > 120)
  assert.ok(textBounds.h >= 54)

  const noteBounds = learningTextBoundsForContent({ mode: 'note', text: '电源路径说明'.repeat(40), style: { size: 'm' } })
  assert.equal(noteBounds.w, 260)
  assert.ok(noteBounds.h > 120)
  assert.equal(noteBounds.overflow, false)
})

test('re-editing extends existing text and keeps manually resized note width', () => {
  const snapshot = fixtureSnapshot()
  const originalText = createTextShape({
    snapshot,
    pageId: 'page:page',
    point: { x: 20, y: 30 },
    text: '测试1',
    id: 'shape:editable-text'
  })
  const updatedText = updateLearningTextShapeContent(originalText, '测试1，继续编写后续说明', { size: 'l', color: 'blue' })
  assert.equal(updatedText.id, originalText.id)
  assert.equal(updatedText.meta.hardwareLearningText, '测试1，继续编写后续说明')
  assert.equal(updatedText.props.size, 'l')
  assert.ok(updatedText.props.w > originalText.props.w)

  const note = createNoteShape({
    snapshot,
    pageId: 'page:page',
    point: { x: 200, y: 220 },
    text: '短便签',
    id: 'shape:manual-note'
  })
  const resized = resizeRectangleShape(note, { x: 200, y: 220, w: 190, h: 120 })
  assert.equal(resized.meta.hardwareLearningTextAutoSize, false)
  const edited = updateLearningTextShapeContent(resized, '手动宽度下自动换行的便签内容'.repeat(16), { size: 'm' })
  assert.equal(edited.props.w, 190)
  assert.ok(edited.props.h > 120)
})

test('font size changes grow notes so persisted and exported text is not clipped', () => {
  let snapshot = fixtureSnapshot()
  const noteText = '模块作用与信号关系'.repeat(18)
  const note = createNoteShape({
    snapshot,
    pageId: 'page:page',
    point: { x: 40, y: 50 },
    text: noteText,
    style: { size: 's' },
    id: 'shape:long-note'
  })
  snapshot = addShape(snapshot, note)
  const styled = styleLearningShapes(snapshot, [note.id], { size: 'xl' })
  assert.equal(styled.snapshot.store[note.id].props.size, 'xl')
  assert.ok(styled.snapshot.store[note.id].props.h > note.props.h)
  const result = buildLearningCanvasSvg({ snapshot: styled.snapshot, pageId: 'page:page' })
  assert.match(result.svg, /font-size="28"/u)
  const exportedText = [...result.svg.matchAll(/<tspan[^>]*>(.*?)<\/tspan>/gu)].map((match) => match[1]).join('')
  assert.equal(exportedText, noteText)
})

test('text size controls use half-size metrics without changing learning frame bounds', () => {
  assert.deepEqual(learningTextMetricsForSize('s'), { fontSize: 13, lineHeight: 18 })
  assert.deepEqual(learningTextMetricsForSize('m'), { fontSize: 15, lineHeight: 20 })
  assert.deepEqual(learningTextMetricsForSize('l'), { fontSize: 20, lineHeight: 27 })
  assert.deepEqual(learningTextMetricsForSize('xl'), { fontSize: 28, lineHeight: 36 })

  let snapshot = fixtureSnapshot()
  const frame = createFrameShape({
    snapshot,
    pageId: 'page:page',
    bounds: { x: 120, y: 100, w: 200, h: 140 },
    id: 'shape:fixed-frame'
  })
  snapshot = addShape(snapshot, frame)
  const before = structuredClone(snapshot.store[frame.id])
  const styled = styleLearningShapes(snapshot, [frame.id], { size: 'xl' })
  const after = styled.snapshot.store[frame.id]

  assert.deepEqual({ x: after.x, y: after.y, w: after.props.w, h: after.props.h }, {
    x: before.x,
    y: before.y,
    w: before.props.w,
    h: before.props.h
  })
  assert.deepEqual(after.meta.hardwareLearningBounds, before.meta.hardwareLearningBounds)
  assert.equal(after.meta.hardwareLearningFrameNumber, before.meta.hardwareLearningFrameNumber)
})

test('version 2 text reflows once for half-size metrics while frames remain untouched', () => {
  let snapshot = fixtureSnapshot()
  const frame = createFrameShape({
    snapshot,
    pageId: 'page:page',
    bounds: { x: 20, y: 30, w: 180, h: 110 },
    id: 'shape:migration-frame'
  })
  snapshot = addShape(snapshot, frame)
  const note = createNoteShape({
    snapshot,
    pageId: 'page:page',
    point: { x: 240, y: 30 },
    text: '字号迁移后仍需完整显示'.repeat(12),
    style: { size: 'm' },
    id: 'shape:legacy-font-note'
  })
  note.meta.hardwareLearningTextMetricsVersion = 2
  note.props.h = 300
  note.meta.hardwareLearningBounds.h = 300
  snapshot = addShape(snapshot, note)
  const frameBefore = structuredClone(snapshot.store[frame.id])

  const migrated = migrateLegacyLearningFrames(snapshot)
  assert.deepEqual(migrated.reflowedTextShapeIds, [note.id])
  assert.ok(migrated.snapshot.store[note.id].props.h >= 120)
  assert.ok(migrated.snapshot.store[note.id].props.h < 300)
  assert.equal(migrated.snapshot.store[note.id].meta.hardwareLearningTextMetricsVersion, 3)
  assert.deepEqual(migrated.snapshot.store[frame.id], frameBefore)
  assert.equal(migrateLegacyLearningFrames(migrated.snapshot).changed, false)
})

test('schematic evidence lock state is explicit and does not affect annotations', () => {
  const initial = fixtureSnapshot()
  const frame = createFrameShape({
    snapshot: initial,
    pageId: 'page:page',
    bounds: { x: 120, y: 100, w: 200, h: 140 },
    id: 'shape:frame'
  })
  const snapshot = addShape(initial, frame)
  const locked = setImageLockState(snapshot, ['shape:source', 'shape:frame'], true)
  assert.deepEqual(locked.updated, ['shape:source'])
  assert.equal(locked.snapshot.store['shape:source'].isLocked, true)
  assert.equal(locked.snapshot.store['shape:frame'].isLocked, false)

  const unlocked = setImageLockState(locked.snapshot, ['shape:source'], false)
  assert.deepEqual(unlocked.updated, ['shape:source'])
  assert.equal(unlocked.snapshot.store['shape:source'].isLocked, false)
})

test('queued teaching annotations apply idempotently with stable IDs', () => {
  const snapshot = fixtureSnapshot()
  const operation = {
    operationId: 'operation:one',
    pageId: 'page:page',
    commands: [{
      operationId: 'operation:one',
      commandId: 'command:one',
      pageId: 'page:page',
      kind: 'rectangle',
      bounds: { x: 20, y: 30, width: 100, height: 70 }
    }]
  }
  const first = applyLearningAnnotationOperations(snapshot, 'page:page', [operation])
  assert.equal(first.changed, true)
  assert.deepEqual(first.appliedCommands, ['command:one'])
  const second = applyLearningAnnotationOperations(first.snapshot, 'page:page', [operation])
  assert.equal(second.changed, false)
})

test('standalone SVG export contains the selected evidence and no tldraw watermark', () => {
  const initial = fixtureSnapshot()
  const frame = createFrameShape({ snapshot: initial, pageId: 'page:page', bounds: { x: 120, y: 100, w: 200, h: 140 }, id: 'shape:frame' })
  const snapshot = addShape(initial, frame)
  const result = buildLearningCanvasSvg({
    snapshot,
    pageId: 'page:page',
    assetSources: new Map([['/page-assets/page/source.png', 'data:image/png;base64,AA==']])
  })
  assert.match(result.svg, /data:image\/png;base64,AA==/)
  assert.match(result.svg, /shape:frame/)
  assert.match(result.svg, /learning-frame-number/)
  assert.match(result.svg, />1<\/text>/)
  assert.doesNotMatch(result.svg, /tldraw|tl-watermark/i)
})

test('selection export crops to the learning frame and keeps intersecting schematic evidence', () => {
  const initial = fixtureSnapshot()
  const frame = createFrameShape({ snapshot: initial, pageId: 'page:page', bounds: { x: 160, y: 120, w: 180, h: 120 }, id: 'shape:frame' })
  const snapshot = addShape(initial, frame)
  const result = buildLearningCanvasSvg({
    snapshot,
    pageId: 'page:page',
    selectedShapeIds: [frame.id],
    assetSources: new Map([['/page-assets/page/source.png', 'data:image/png;base64,AA==']])
  })
  assert.match(result.svg, /shape:source/)
  assert.match(result.svg, /shape:frame/)
  assert.deepEqual(result.bounds, { x: 128, y: 88, w: 244, h: 184 })
  assert.deepEqual(result.shapeIds, ['shape:source', 'shape:frame'])
})
