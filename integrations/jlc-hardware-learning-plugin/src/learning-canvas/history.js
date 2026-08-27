function cloneValue(value) {
  return value === undefined ? undefined : structuredClone(value)
}

function stableEqual(left, right) {
  if (left === right) return true
  return JSON.stringify(left) === JSON.stringify(right)
}

function snapshotRoot(snapshot) {
  if (!snapshot) return {}
  const root = { ...snapshot }
  delete root.store
  return root
}

export function createSnapshotDelta(before, after, label = '画布更新', metadata = null) {
  if (!before?.store || !after?.store) return null
  const records = {}
  const ids = new Set([...Object.keys(before.store), ...Object.keys(after.store)])
  for (const id of ids) {
    const previous = before.store[id]
    const next = after.store[id]
    if (stableEqual(previous, next)) continue
    records[id] = {
      before: cloneValue(previous),
      after: cloneValue(next)
    }
  }

  const beforeRoot = snapshotRoot(before)
  const afterRoot = snapshotRoot(after)
  const rootChanged = !stableEqual(beforeRoot, afterRoot)
  if (!Object.keys(records).length && !rootChanged) return null

  return {
    label,
    metadata: cloneValue(metadata),
    records,
    root: rootChanged
      ? { before: cloneValue(beforeRoot), after: cloneValue(afterRoot) }
      : null
  }
}

export function applySnapshotDelta(snapshot, delta, direction) {
  if (!snapshot?.store || !delta || !['before', 'after'].includes(direction)) return snapshot
  const next = structuredClone(snapshot)
  if (delta.root) {
    for (const key of Object.keys(next)) {
      if (key !== 'store') delete next[key]
    }
    Object.assign(next, cloneValue(delta.root[direction]))
  }
  for (const [id, change] of Object.entries(delta.records)) {
    const record = change[direction]
    if (record === undefined) delete next.store[id]
    else next.store[id] = cloneValue(record)
  }
  return next
}

export function createHistoryManager({ limit = 100 } = {}) {
  const undoStack = []
  const redoStack = []

  return {
    get canUndo() {
      return undoStack.length > 0
    },
    get canRedo() {
      return redoStack.length > 0
    },
    get undoCount() {
      return undoStack.length
    },
    get redoCount() {
      return redoStack.length
    },
    clear() {
      undoStack.length = 0
      redoStack.length = 0
    },
    record(before, after, label, metadata = null) {
      const delta = createSnapshotDelta(before, after, label, metadata)
      if (!delta) return false
      undoStack.push(delta)
      if (undoStack.length > limit) undoStack.shift()
      redoStack.length = 0
      return true
    },
    undo(snapshot) {
      const delta = undoStack.pop()
      if (!delta) return null
      redoStack.push(delta)
      return {
        label: delta.label,
        metadata: cloneValue(delta.metadata),
        snapshot: applySnapshotDelta(snapshot, delta, 'before')
      }
    },
    redo(snapshot) {
      const delta = redoStack.pop()
      if (!delta) return null
      undoStack.push(delta)
      return {
        label: delta.label,
        metadata: cloneValue(delta.metadata),
        snapshot: applySnapshotDelta(snapshot, delta, 'after')
      }
    }
  }
}
