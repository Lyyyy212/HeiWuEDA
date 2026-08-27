import assert from 'node:assert/strict'
import test from 'node:test'

import { observeElementViewportSize, readElementViewportSize } from './viewport.js'

class FakeEventTarget {
  constructor() {
    this.listeners = new Map()
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || new Set()
    listeners.add(listener)
    this.listeners.set(type, listeners)
  }

  removeEventListener(type, listener) {
    this.listeners.get(type)?.delete(listener)
  }

  dispatch(type) {
    for (const listener of this.listeners.get(type) || []) listener()
  }
}

function fakeWindow() {
  const target = new FakeEventTarget()
  const visualViewport = new FakeEventTarget()
  const frames = new Map()
  const timers = new Map()
  let nextFrameId = 1
  let nextTimerId = 1
  return Object.assign(target, {
    visualViewport,
    requestAnimationFrame(callback) {
      const id = nextFrameId++
      frames.set(id, callback)
      return id
    },
    cancelAnimationFrame(id) {
      frames.delete(id)
    },
    flushFrame() {
      const pending = [...frames.values()]
      frames.clear()
      for (const callback of pending) callback()
    },
    pendingFrames() {
      return frames.size
    },
    setTimeout(callback) {
      const id = nextTimerId++
      timers.set(id, callback)
      return id
    },
    clearTimeout(id) {
      timers.delete(id)
    },
    flushTimer() {
      const pending = [...timers.values()]
      timers.clear()
      for (const callback of pending) callback()
    },
    pendingTimers() {
      return timers.size
    }
  })
}

test('readElementViewportSize rejects non-finite and negative dimensions', () => {
  assert.deepEqual(readElementViewportSize({
    getBoundingClientRect: () => ({ width: Number.NaN, height: -20 })
  }), { width: 0, height: 0 })
})

test('initial layout retries recover when the root becomes visible without a window resize', () => {
  const windowTarget = fakeWindow()
  const documentTarget = new FakeEventTarget()
  const bounds = { width: 0, height: 0 }
  const sizes = []
  const dispose = observeElementViewportSize(
    { getBoundingClientRect: () => bounds },
    (size) => sizes.push(size),
    { windowTarget, documentTarget, initialLayoutFrames: 4 }
  )

  windowTarget.flushFrame()
  assert.deepEqual(sizes, [])
  assert.equal(windowTarget.pendingFrames(), 1)

  bounds.width = 1280.4
  bounds.height = 719.6
  windowTarget.flushFrame()
  assert.deepEqual(sizes, [{ width: 1280, height: 720 }])
  assert.equal(windowTarget.pendingFrames(), 0)

  dispose()
})

test('slow recovery survives a delayed first host layout without resize or focus events', () => {
  const windowTarget = fakeWindow()
  const documentTarget = new FakeEventTarget()
  const bounds = { width: 0, height: 0 }
  const sizes = []
  const dispose = observeElementViewportSize(
    { getBoundingClientRect: () => bounds },
    (size) => sizes.push(size),
    {
      windowTarget,
      documentTarget,
      initialLayoutFrames: 2,
      recoveryIntervalMs: 250
    }
  )

  windowTarget.flushFrame()
  windowTarget.flushFrame()
  windowTarget.flushFrame()
  assert.deepEqual(sizes, [])
  assert.equal(windowTarget.pendingFrames(), 0)
  assert.equal(windowTarget.pendingTimers(), 1)

  bounds.width = 1440
  bounds.height = 900
  windowTarget.flushTimer()
  assert.equal(windowTarget.pendingFrames(), 1)
  windowTarget.flushFrame()
  assert.deepEqual(sizes, [{ width: 1440, height: 900 }])
  assert.equal(windowTarget.pendingTimers(), 0)

  dispose()
})

test('slow recovery timer is removed when the viewport observer is disposed', () => {
  const windowTarget = fakeWindow()
  const documentTarget = new FakeEventTarget()
  const dispose = observeElementViewportSize(
    { getBoundingClientRect: () => ({ width: 0, height: 0 }) },
    () => {},
    { windowTarget, documentTarget, initialLayoutFrames: 0 }
  )

  windowTarget.flushFrame()
  assert.equal(windowTarget.pendingTimers(), 1)
  dispose()
  assert.equal(windowTarget.pendingTimers(), 0)
  assert.equal(windowTarget.pendingFrames(), 0)
})

test('root ResizeObserver publishes real size changes once and disconnects cleanly', () => {
  const windowTarget = fakeWindow()
  const documentTarget = new FakeEventTarget()
  const bounds = { width: 0, height: 0 }
  const sizes = []
  let observerCallback = null
  let observedElement = null
  let disconnected = false

  class FakeResizeObserver {
    constructor(callback) {
      observerCallback = callback
    }

    observe(element) {
      observedElement = element
    }

    disconnect() {
      disconnected = true
    }
  }

  const element = { getBoundingClientRect: () => bounds }
  const dispose = observeElementViewportSize(element, (size) => sizes.push(size), {
    windowTarget,
    documentTarget,
    ResizeObserverImpl: FakeResizeObserver,
    initialLayoutFrames: 0
  })

  assert.equal(observedElement, element)
  windowTarget.flushFrame()
  bounds.width = 900
  bounds.height = 600
  observerCallback()
  windowTarget.flushFrame()
  assert.deepEqual(sizes, [{ width: 900, height: 600 }])

  observerCallback()
  windowTarget.flushFrame()
  assert.deepEqual(sizes, [{ width: 900, height: 600 }])

  bounds.width = 940
  observerCallback()
  windowTarget.flushFrame()
  assert.deepEqual(sizes, [
    { width: 900, height: 600 },
    { width: 940, height: 600 }
  ])

  dispose()
  assert.equal(disconnected, true)
  assert.equal(windowTarget.pendingFrames(), 0)
  assert.equal(windowTarget.listeners.get('resize')?.size, 0)
  assert.equal(documentTarget.listeners.get('visibilitychange')?.size, 0)
})
