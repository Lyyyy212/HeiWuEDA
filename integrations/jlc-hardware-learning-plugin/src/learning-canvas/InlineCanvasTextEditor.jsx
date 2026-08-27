import { useLayoutEffect, useRef } from 'react'

import {
  learningTextBoundsForContent,
  learningTextMetricsForSize,
  normalizeLearningStyle,
  pageToScreen
} from './model.js'
import { colorValue } from './export.js'
import {
  indentInlineLearningText,
  INLINE_LEARNING_TEXT_LIMIT,
  inlineEditorActionForKey,
  normalizeInlineLearningText
} from './textEditing.js'

export default function InlineCanvasTextEditor({ camera, draft, shape, style, onCancel, onChange, onCommit }) {
  const inputRef = useRef(null)
  const composingRef = useRef(false)
  const finishedRef = useRef(false)
  const editingStyle = normalizeLearningStyle(draft.style ?? style)
  const point = shape ? { x: shape.x, y: shape.y } : draft.point
  const bounds = learningTextBoundsForContent({
    mode: draft.mode,
    text: draft.text,
    style: editingStyle,
    currentBounds: shape ? { w: shape.props?.w, h: shape.props?.h } : null,
    autoSize: shape ? shape.meta?.hardwareLearningTextAutoSize !== false : true
  })
  const screenPoint = pageToScreen(point, camera)
  const screenWidth = Math.max(draft.mode === 'note' ? 210 : 120, bounds.w * camera.z)
  const screenHeight = Math.max(draft.mode === 'note' ? 104 : 54, bounds.h * camera.z)
  const color = colorValue(editingStyle.color, draft.mode === 'note' ? '#eab308' : '#1f2937')
  const textMetrics = learningTextMetricsForSize(editingStyle.size)
  const fillOpacity = editingStyle.fill === 'solid' ? (draft.mode === 'note' ? 0.34 : 0.92) : editingStyle.fill === 'semi' ? 0.18 : 0
  const background = fillOpacity > 0 ? `${color}${Math.round(fillOpacity * 255).toString(16).padStart(2, '0')}` : 'transparent'

  function finish(action) {
    if (finishedRef.current) return
    finishedRef.current = true
    action()
  }

  function keepFocusForStyleInteraction(event) {
    const nextTarget = event.relatedTarget
    if (!nextTarget?.closest?.('[data-jlc-learning-preserve-text-editor="true"]')) return false
    const selectionStart = inputRef.current?.selectionStart ?? 0
    const selectionEnd = inputRef.current?.selectionEnd ?? selectionStart
    requestAnimationFrame(() => {
      const input = inputRef.current
      if (!input || finishedRef.current) return
      input.focus({ preventScroll: true })
      input.setSelectionRange(selectionStart, selectionEnd)
    })
    return true
  }

  useLayoutEffect(() => {
    const input = inputRef.current
    if (!input) return
    let frame = 0
    let attempts = 0
    const focusEditor = () => {
      attempts += 1
      input.focus({ preventScroll: true })
      if (draft.shapeId && attempts === 1) {
        const caret = input.value.length
        input.setSelectionRange(caret, caret)
      }
      if (document.activeElement !== input && attempts < 8) {
        frame = requestAnimationFrame(focusEditor)
      }
    }
    focusEditor()
    return () => cancelAnimationFrame(frame)
  }, [draft.mode, draft.shapeId])

  return (
    <div
      className="learning-inline-editor"
      data-mode={draft.mode}
      onContextMenu={(event) => {
        event.preventDefault()
        event.stopPropagation()
        finish(onCancel)
      }}
      onDoubleClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
      style={{
        height: screenHeight,
        left: screenPoint.x,
        top: screenPoint.y,
        width: screenWidth
      }}
    >
      <div
        className="learning-inline-editor-surface"
        style={{ '--editor-color': color, '--editor-background': background }}
      >
        <textarea
          aria-label={draft.mode === 'note' ? '便签文字' : '画布文字'}
          autoFocus
          data-jlc-learning-inline-editor="true"
          data-testid="learning-inline-text-editor"
          dir="auto"
          maxLength={INLINE_LEARNING_TEXT_LIMIT}
          onBlur={(event) => {
            if (keepFocusForStyleInteraction(event)) return
            finish(onCommit)
          }}
          onChange={(event) => onChange(normalizeInlineLearningText(event.target.value))}
          onCompositionEnd={() => { composingRef.current = false }}
          onCompositionStart={() => { composingRef.current = true }}
          onKeyDown={(event) => {
            event.stopPropagation()
            const action = inlineEditorActionForKey({
              key: event.key,
              shiftKey: event.shiftKey,
              isComposing: composingRef.current || event.nativeEvent.isComposing,
              keyCode: event.nativeEvent.keyCode
            })
            if (action === 'cancel') {
              event.preventDefault()
              finish(onCancel)
            } else if (action === 'commit') {
              event.preventDefault()
              finish(onCommit)
            } else if (action === 'indent' || action === 'outdent') {
              event.preventDefault()
              const input = event.currentTarget
              const result = indentInlineLearningText(
                input.value,
                input.selectionStart,
                input.selectionEnd,
                { outdent: action === 'outdent' }
              )
              onChange(result.text)
              requestAnimationFrame(() => inputRef.current?.setSelectionRange(result.selectionStart, result.selectionEnd))
            }
          }}
          onPointerDown={(event) => event.stopPropagation()}
          onWheel={(event) => event.stopPropagation()}
          placeholder={draft.mode === 'note' ? '输入便签…' : '输入文字…'}
          ref={inputRef}
          spellCheck="false"
          style={{
            fontSize: `${textMetrics.fontSize * camera.z}px`,
            lineHeight: `${textMetrics.lineHeight * camera.z}px`,
            overflowY: bounds.overflow ? 'auto' : 'hidden'
          }}
          value={draft.text}
          wrap="soft"
        />
      </div>
      <div className="learning-inline-editor-hint" role="status">
        <span>{draft.mode === 'note' ? 'Enter 完成并保持便签工具' : 'Enter 完成并保持文本工具'} · Shift+Enter 换行 · Esc/右键退出选择</span>
        <span>{draft.text.length}/{INLINE_LEARNING_TEXT_LIMIT}</span>
      </div>
    </div>
  )
}
