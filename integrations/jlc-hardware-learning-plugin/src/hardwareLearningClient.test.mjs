import assert from 'node:assert/strict'
import test from 'node:test'

import {
  chooseHardwareLearningExportDirectory,
  downloadHardwareLearningFile,
  loadHardwareLearningCanvasState
} from './hardwareLearningClient.js'

test('JLC Hardware Learning waits through host-only globals until the tool result provides its storage target', async () => {
  const calls = []
  const windowTarget = new EventTarget()
  windowTarget.setTimeout = globalThis.setTimeout.bind(globalThis)
  windowTarget.clearTimeout = globalThis.clearTimeout.bind(globalThis)
  windowTarget.openai = {}
  windowTarget.hardwareLearningMcp = {
    async callServerTool(request) {
      calls.push(request)
      return {
        structuredContent: {
          snapshot: { store: {}, schema: { schemaVersion: 2, sequences: {} } },
          viewState: { currentPageId: 'page:page', camera: { x: 1, y: 2, z: 3 } },
          storage: 'per-page'
        }
      }
    }
  }
  globalThis.window = windowTarget

  try {
    const loading = loadHardwareLearningCanvasState()

    windowTarget.openai = { hostCapabilities: { serverTools: {} } }
    windowTarget.dispatchEvent(new Event('openai:set_globals'))
    await new Promise((resolve) => setTimeout(resolve, 0))
    assert.equal(calls.length, 0)

    windowTarget.openai.toolOutput = {
      projectDir: 'D:\\fixture',
      canvasDir: 'D:\\fixture\\canvas'
    }
    windowTarget.dispatchEvent(new Event('openai:set_globals'))

    const state = await loading
    assert.equal(state.storage, 'per-page')
    assert.deepEqual(state.viewState.camera, { x: 1, y: 2, z: 3 })
    assert.equal(calls.length, 1)
    assert.equal(calls[0].name, 'get_hardware_learning_canvas_state')
    assert.equal(calls[0].arguments.projectDir, 'D:\\fixture')
    assert.equal(calls[0].arguments.canvasDir, 'D:\\fixture\\canvas')
  } finally {
    delete globalThis.window
  }
})

test('large JLC Hardware Learning widget exports use ordered chunked Bridge calls', async () => {
  const calls = []
  const progress = []
  globalThis.window = {
    openai: { toolOutput: { projectDir: 'D:\\fixture' } },
    hardwareLearningMcp: {
      async callServerTool(request) {
        calls.push(request)
        const action = request.arguments.action
        if (action === 'begin') return { structuredContent: { downloadId: '4dd91ef0-144d-4a97-94a8-a0d0afef96ee' } }
        if (action === 'finish') return { structuredContent: { ok: true, filePath: 'D:\\Downloads\\fixture.png' } }
        return { structuredContent: { ok: true } }
      }
    }
  }

  try {
    const dataBase64 = 'QUJD'.repeat(200_000)
    const result = await downloadHardwareLearningFile({
      dataBase64,
      directoryToken: '58b830c4-9aa2-43d4-90cd-92912557ea62',
      fileName: 'fixture.png',
      mimeType: 'image/png',
      onProgress: (event) => progress.push(event)
    })
    assert.equal(result.ok, true)
    assert.equal(calls[0].arguments.action, 'begin')
    assert.equal(calls[0].arguments.directoryToken, '58b830c4-9aa2-43d4-90cd-92912557ea62')
    assert.equal(calls.at(-1).arguments.action, 'finish')
    const appendCalls = calls.filter((call) => call.arguments.action === 'append')
    assert.ok(appendCalls.length > 1)
    assert.deepEqual(appendCalls.map((call) => call.arguments.chunkIndex), appendCalls.map((_call, index) => index))
    assert.equal(appendCalls.map((call) => call.arguments.chunkBase64).join(''), dataBase64)
    assert.ok(appendCalls.every((call) => call.arguments.chunkBase64.length <= 48 * 1024))
    assert.equal(progress.at(-1).phase, 'finish')
    assert.equal(progress.at(-1).sentBytes, progress.at(-1).totalBytes)
    assert.ok(calls.every((call) => call.arguments.onProgress === undefined))
  } finally {
    delete globalThis.window
  }
})

test('JLC Hardware Learning export directory selection stays app-driven and canvas-bound', async () => {
  const calls = []
  globalThis.window = {
    openai: { toolOutput: { projectDir: 'D:\\fixture' } },
    hardwareLearningMcp: {
      async callServerTool(request, options) {
        calls.push({ request, options })
        return {
          structuredContent: {
            ok: true,
            canceled: false,
            directoryPath: 'D:\\Exports',
            directoryToken: '58b830c4-9aa2-43d4-90cd-92912557ea62'
          }
        }
      }
    }
  }

  try {
    const result = await chooseHardwareLearningExportDirectory()
    assert.equal(result.directoryPath, 'D:\\Exports')
    assert.equal(calls.length, 1)
    assert.equal(calls[0].request.name, 'choose_hardware_learning_export_directory')
    assert.equal(calls[0].request.arguments.projectDir, 'D:\\fixture')
    assert.equal(calls[0].options.timeoutMs, 65_000)
  } finally {
    delete globalThis.window
  }
})

test('JLC Hardware Learning chunk Bridge retries a transient host failure with the same session and chunk', async () => {
  const calls = []
  let failedOnce = false
  globalThis.window = {
    openai: { toolOutput: { projectDir: 'D:\\fixture' } },
    hardwareLearningMcp: {
      async callServerTool(request, options) {
        calls.push({ request, options })
        const action = request.arguments.action
        if (action === 'begin') return { structuredContent: { downloadId: request.arguments.downloadId } }
        if (action === 'append' && request.arguments.chunkIndex === 0 && !failedOnce) {
          failedOnce = true
          throw new Error('temporary host bridge failure')
        }
        if (action === 'finish') return { structuredContent: { ok: true, filePath: 'D:\\Downloads\\fixture.png' } }
        return { structuredContent: { ok: true } }
      }
    }
  }

  try {
    const dataBase64 = 'QUJD'.repeat(40_000)
    const result = await downloadHardwareLearningFile({ dataBase64, fileName: 'fixture.png', mimeType: 'image/png' })
    assert.equal(result.ok, true)
    const firstChunkCalls = calls.filter(({ request }) => request.arguments.action === 'append' && request.arguments.chunkIndex === 0)
    assert.equal(firstChunkCalls.length, 2)
    assert.equal(firstChunkCalls[0].request.arguments.downloadId, firstChunkCalls[1].request.arguments.downloadId)
    assert.equal(firstChunkCalls[0].request.arguments.chunkBase64, firstChunkCalls[1].request.arguments.chunkBase64)
    assert.ok(calls.every(({ options }) => options?.timeoutMs === 45_000))
  } finally {
    delete globalThis.window
  }
})
