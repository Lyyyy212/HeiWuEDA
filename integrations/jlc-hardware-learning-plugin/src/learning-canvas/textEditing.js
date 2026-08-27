export const INLINE_LEARNING_TEXT_LIMIT = 2000
export const INLINE_LEARNING_TEXT_INDENT = '  '

export function normalizeInlineLearningText(value) {
  return String(value ?? '')
    .replace(/\r\n?/gu, '\n')
    .slice(0, INLINE_LEARNING_TEXT_LIMIT)
}

export function inlineEditorActionForKey({
  key,
  shiftKey = false,
  isComposing = false,
  keyCode = 0
} = {}) {
  if (key === 'Escape') return 'cancel'
  if (key === 'Tab') return shiftKey ? 'outdent' : 'indent'
  if (key !== 'Enter') return 'none'
  if (isComposing || keyCode === 229) return 'none'
  return shiftKey ? 'newline' : 'commit'
}

export function toolAfterInlineTextEdit(mode, outcome = 'commit') {
  if (outcome === 'cancel') return 'select'
  return ['text', 'note'].includes(mode) ? mode : 'select'
}

export function indentInlineLearningText(text, selectionStart, selectionEnd, { outdent = false } = {}) {
  const value = normalizeInlineLearningText(text)
  const start = Math.max(0, Math.min(value.length, Number(selectionStart) || 0))
  const end = Math.max(start, Math.min(value.length, Number(selectionEnd) || start))
  if (!outdent && start === end) {
    const next = `${value.slice(0, start)}${INLINE_LEARNING_TEXT_INDENT}${value.slice(end)}`
    const caret = start + INLINE_LEARNING_TEXT_INDENT.length
    return { text: next, selectionStart: caret, selectionEnd: caret }
  }

  const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1
  const trailingBreak = value.indexOf('\n', end)
  const lineEnd = trailingBreak === -1 ? value.length : trailingBreak
  const block = value.slice(lineStart, lineEnd)
  let removedBeforeStart = 0
  let totalDelta = 0
  const lines = block.split('\n').map((line, index) => {
    if (!outdent) {
      totalDelta += INLINE_LEARNING_TEXT_INDENT.length
      return `${INLINE_LEARNING_TEXT_INDENT}${line}`
    }
    const removable = Math.min(INLINE_LEARNING_TEXT_INDENT.length, line.match(/^ */u)?.[0].length || 0)
    if (index === 0) removedBeforeStart = Math.min(removable, Math.max(0, start - lineStart))
    totalDelta -= removable
    return line.slice(removable)
  })
  const nextBlock = lines.join('\n')
  const next = `${value.slice(0, lineStart)}${nextBlock}${value.slice(lineEnd)}`
  const nextStart = outdent
    ? Math.max(lineStart, start - removedBeforeStart)
    : start + INLINE_LEARNING_TEXT_INDENT.length
  const nextEnd = Math.max(nextStart, end + totalDelta)
  return { text: next, selectionStart: nextStart, selectionEnd: nextEnd }
}
