const DEFAULT_INITIAL_LAYOUT_FRAMES = 30
const DEFAULT_RECOVERY_INTERVAL_MS = 250

function finiteDimension(value) {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, Math.round(number)) : 0
}

export function readElementViewportSize(element) {
  const bounds = element?.getBoundingClientRect?.()
  return {
    width: finiteDimension(bounds?.width),
    height: finiteDimension(bounds?.height)
  }
}

function hasUsableSize(size) {
  return size.width > 0 && size.height > 0
}

function sameSize(left, right) {
  return left?.width === right?.width && left?.height === right?.height
}

export function observeElementViewportSize(element, onSize, {
  windowTarget = globalThis.window,
  documentTarget = globalThis.document,
  ResizeObserverImpl = windowTarget?.ResizeObserver,
  initialLayoutFrames = DEFAULT_INITIAL_LAYOUT_FRAMES,
  recoveryIntervalMs = DEFAULT_RECOVERY_INTERVAL_MS
} = {}) {
  if (!element || typeof onSize !== 'function') return () => {}

  const requestFrame = windowTarget?.requestAnimationFrame?.bind(windowTarget)
    || ((callback) => globalThis.setTimeout(callback, 16))
  const cancelFrame = windowTarget?.cancelAnimationFrame?.bind(windowTarget)
    || globalThis.clearTimeout
  const setTimer = windowTarget?.setTimeout?.bind(windowTarget)
    || globalThis.setTimeout
  const clearTimer = windowTarget?.clearTimeout?.bind(windowTarget)
    || globalThis.clearTimeout
  const visualViewport = windowTarget?.visualViewport
  let disposed = false
  let frameId = null
  let recoveryTimerId = null
  let remainingInitialFrames = Math.max(0, Math.round(initialLayoutFrames))
  let lastSize = null

  const cancelRecovery = () => {
    if (recoveryTimerId === null) return
    clearTimer(recoveryTimerId)
    recoveryTimerId = null
  }

  const scheduleRecovery = () => {
    if (disposed || recoveryTimerId !== null) return
    recoveryTimerId = setTimer(() => {
      recoveryTimerId = null
      scheduleMeasure()
    }, Math.max(16, Math.round(recoveryIntervalMs)))
  }

  const measure = () => {
    frameId = null
    if (disposed) return

    const nextSize = readElementViewportSize(element)
    if (hasUsableSize(nextSize)) {
      remainingInitialFrames = 0
      cancelRecovery()
      if (!sameSize(lastSize, nextSize)) {
        lastSize = nextSize
        onSize(nextSize)
      }
      return
    }

    if (remainingInitialFrames > 0) {
      remainingInitialFrames -= 1
      frameId = requestFrame(measure)
      return
    }

    scheduleRecovery()
  }

  const scheduleMeasure = () => {
    if (disposed || frameId !== null) return
    cancelRecovery()
    frameId = requestFrame(measure)
  }

  const observer = typeof ResizeObserverImpl === 'function'
    ? new ResizeObserverImpl(scheduleMeasure)
    : null
  observer?.observe(element)

  windowTarget?.addEventListener?.('resize', scheduleMeasure)
  windowTarget?.addEventListener?.('focus', scheduleMeasure)
  windowTarget?.addEventListener?.('pageshow', scheduleMeasure)
  visualViewport?.addEventListener?.('resize', scheduleMeasure)
  documentTarget?.addEventListener?.('visibilitychange', scheduleMeasure)
  scheduleMeasure()

  return () => {
    disposed = true
    observer?.disconnect()
    windowTarget?.removeEventListener?.('resize', scheduleMeasure)
    windowTarget?.removeEventListener?.('focus', scheduleMeasure)
    windowTarget?.removeEventListener?.('pageshow', scheduleMeasure)
    visualViewport?.removeEventListener?.('resize', scheduleMeasure)
    documentTarget?.removeEventListener?.('visibilitychange', scheduleMeasure)
    if (frameId !== null) cancelFrame(frameId)
    cancelRecovery()
    frameId = null
  }
}
