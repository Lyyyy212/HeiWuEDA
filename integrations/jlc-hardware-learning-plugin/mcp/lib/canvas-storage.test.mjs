import assert from 'node:assert/strict'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { createTLStore } from 'tldraw'

import {
  readHardwareLearningCanvasState,
  readHardwareLearningSelectionState,
  readHardwareLearningViewState,
  saveHardwareLearningCanvasSnapshot,
  writeHardwareLearningSelectionState,
  writeHardwareLearningViewState,
} from './canvas-storage.mjs'

test('legacy canvas files and metadata migrate to JLC hardware-learning storage', async () => {
  const projectDir = await mkdtemp(path.join(tmpdir(), 'jlc-hardware-learning-migration-'))
  try {
    const pageDir = path.join(projectDir, 'canvas', 'pages', 'page')
    await mkdir(pageDir, { recursive: true })

    const store = createTLStore()
    store.put([{
      id: 'page:page',
      typeName: 'page',
      name: 'Page 1',
      index: 'a1',
      meta: { cowartLearningNextFrameNumber: 4 },
    }])
    const legacySnapshot = store.getStoreSnapshot()
    store.dispose()
    await writeFile(
      path.join(pageDir, 'cowart-canvas.json'),
      `${JSON.stringify(legacySnapshot, null, 2)}\n`,
    )
    await writeFile(
      path.join(projectDir, 'canvas', 'cowart-selection.json'),
      `${JSON.stringify({ version: 1, currentPageId: 'page:page', selectedShapes: [], updatedAt: null })}\n`,
    )
    await writeFile(
      path.join(projectDir, 'canvas', 'cowart-view-state.json'),
      `${JSON.stringify({ version: 1, currentPageId: 'page:page', camera: { x: 1, y: 2, z: 1 }, updatedAt: null })}\n`,
    )

    const state = await readHardwareLearningCanvasState({ projectDir })
    assert.equal(state.snapshot.store['page:page'].meta.hardwareLearningNextFrameNumber, 4)
    assert.equal(Object.keys(state.snapshot.store['page:page'].meta).some((key) => key.startsWith('cowart')), false)
    assert.match(state.path, /[\\/]canvas[\\/]pages$/)

    const selection = await readHardwareLearningSelectionState({ projectDir })
    const view = await readHardwareLearningViewState({ projectDir })
    assert.match(selection.selectionFile, /cowart-selection\.json$/)
    assert.match(view.viewStateFile, /cowart-view-state\.json$/)

    await writeHardwareLearningSelectionState({ projectDir }, selection.selection)
    await writeHardwareLearningViewState({ projectDir }, view.viewState)
    await saveHardwareLearningCanvasSnapshot({ projectDir }, state.snapshot)

    const canonicalCanvas = await readFile(
      path.join(pageDir, 'hardware-learning-canvas.json'),
      'utf8',
    )
    assert.doesNotMatch(canonicalCanvas, /cowart/i)
    await readFile(path.join(projectDir, 'canvas', 'hardware-learning-selection.json'), 'utf8')
    await readFile(path.join(projectDir, 'canvas', 'hardware-learning-view-state.json'), 'utf8')
  } finally {
    await rm(projectDir, { recursive: true, force: true })
  }
})
