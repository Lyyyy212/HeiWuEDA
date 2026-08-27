import assert from 'node:assert/strict'
import test from 'node:test'

import {
  indentInlineLearningText,
  INLINE_LEARNING_TEXT_LIMIT,
  inlineEditorActionForKey,
  normalizeInlineLearningText,
  toolAfterInlineTextEdit
} from './textEditing.js'

test('inline editor keeps Enter confirmation distinct from newline and IME composition', () => {
  assert.equal(inlineEditorActionForKey({ key: 'Enter' }), 'commit')
  assert.equal(inlineEditorActionForKey({ key: 'Enter', shiftKey: true }), 'newline')
  assert.equal(inlineEditorActionForKey({ key: 'Enter', isComposing: true }), 'none')
  assert.equal(inlineEditorActionForKey({ key: 'Enter', keyCode: 229 }), 'none')
  assert.equal(inlineEditorActionForKey({ key: 'Escape' }), 'cancel')
  assert.equal(inlineEditorActionForKey({ key: 'Tab' }), 'indent')
  assert.equal(inlineEditorActionForKey({ key: 'Tab', shiftKey: true }), 'outdent')
})

test('tab indentation preserves the editable selection and supports outdent', () => {
  const indented = indentInlineLearningText('模块一\n模块二', 0, 7)
  assert.equal(indented.text, '  模块一\n  模块二')
  assert.deepEqual(
    indentInlineLearningText(indented.text, indented.selectionStart, indented.selectionEnd, { outdent: true }),
    { text: '模块一\n模块二', selectionStart: 0, selectionEnd: 7 }
  )

  assert.deepEqual(indentInlineLearningText('测试1', 3, 3), {
    text: '测试1  ',
    selectionStart: 5,
    selectionEnd: 5
  })
})

test('inline editor normalizes line endings and enforces its persisted limit', () => {
  assert.equal(normalizeInlineLearningText('一\r\n二\r三'), '一\n二\n三')
  assert.equal(normalizeInlineLearningText('x'.repeat(INLINE_LEARNING_TEXT_LIMIT + 20)).length, INLINE_LEARNING_TEXT_LIMIT)
})

test('confirmed text and notes keep their tool while Escape returns to select', () => {
  assert.equal(toolAfterInlineTextEdit('text', 'commit'), 'text')
  assert.equal(toolAfterInlineTextEdit('note', 'commit'), 'note')
  assert.equal(toolAfterInlineTextEdit('text', 'cancel'), 'select')
  assert.equal(toolAfterInlineTextEdit('note', 'cancel'), 'select')
  assert.equal(toolAfterInlineTextEdit('unknown', 'commit'), 'select')
})
