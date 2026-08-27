import assert from 'node:assert/strict'
import test from 'node:test'

import { applySnapshotDelta, createHistoryManager, createSnapshotDelta } from './history.js'

function snapshot() {
  return {
    schema: { schemaVersion: 2 },
    store: {
      'page:page': { id: 'page:page', typeName: 'page', meta: { next: 1 } },
      'asset:image': { id: 'asset:image', typeName: 'asset', props: { src: '/source.png' } },
      'shape:a': { id: 'shape:a', typeName: 'shape', parentId: 'page:page', x: 10, y: 20 }
    }
  }
}

test('snapshot delta only stores changed records and restores both directions', () => {
  const before = snapshot()
  const after = structuredClone(before)
  after.store['shape:a'].x = 40
  after.store['shape:b'] = { id: 'shape:b', typeName: 'shape', parentId: 'page:page', x: 2, y: 3 }
  const delta = createSnapshotDelta(before, after, '移动')
  assert.deepEqual(Object.keys(delta.records).sort(), ['shape:a', 'shape:b'])
  assert.equal(delta.records['asset:image'], undefined)
  assert.deepEqual(applySnapshotDelta(after, delta, 'before'), before)
  assert.deepEqual(applySnapshotDelta(before, delta, 'after'), after)
})

test('history keeps selection-free updates out and clears redo only on scene record', () => {
  const history = createHistoryManager({ limit: 2 })
  const initial = snapshot()
  assert.equal(history.record(initial, structuredClone(initial), '无变化'), false)
  const moved = structuredClone(initial)
  moved.store['shape:a'].x += 1
  assert.equal(history.record(initial, moved, '移动'), true)
  const undone = history.undo(moved)
  assert.deepEqual(undone.snapshot, initial)
  assert.equal(history.canRedo, true)
  assert.equal(history.record(initial, structuredClone(initial), '仅选择'), false)
  assert.equal(history.canRedo, true)
  const redone = history.redo(initial)
  assert.deepEqual(redone.snapshot, moved)
})

test('history limit evicts the oldest scene delta', () => {
  const history = createHistoryManager({ limit: 2 })
  let current = snapshot()
  for (let x = 11; x <= 13; x += 1) {
    const next = structuredClone(current)
    next.store['shape:a'].x = x
    history.record(current, next, `移动到 ${x}`)
    current = next
  }
  assert.equal(history.undoCount, 2)
  current = history.undo(current).snapshot
  current = history.undo(current).snapshot
  assert.equal(current.store['shape:a'].x, 11)
  assert.equal(history.undo(current), null)
})

test('history preserves explicit image-delete authorization for redo', () => {
  const history = createHistoryManager()
  const before = snapshot()
  before.store['shape:image'] = {
    id: 'shape:image',
    typeName: 'shape',
    type: 'image',
    parentId: 'page:page',
    props: { assetId: 'asset:image', w: 100, h: 80 }
  }
  const after = structuredClone(before)
  delete after.store['shape:image']
  delete after.store['asset:image']
  const metadata = { acknowledgedImageShapeDeletes: ['shape:image'] }

  assert.equal(history.record(before, after, '删除原理图', metadata), true)
  const undone = history.undo(after)
  assert.deepEqual(undone.snapshot, before)
  assert.deepEqual(undone.metadata, metadata)
  const redone = history.redo(before)
  assert.deepEqual(redone.snapshot, after)
  assert.deepEqual(redone.metadata, metadata)
})
