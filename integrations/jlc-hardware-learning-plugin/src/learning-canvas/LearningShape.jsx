import { layoutLearningText } from './model.js'
import { colorValue, dashArrayForStyle, strokeWidthForSize } from './export.js'

export default function LearningShape({ shape, snapshot, assetSources, cameraZoom = 1, editing, selected, onPointerDown, onDoubleClick }) {
  const common = {
    'data-shape-id': shape.id,
    onDoubleClick: (event) => onDoubleClick(event, shape),
    onPointerDown: (event) => onPointerDown(event, shape),
    style: { cursor: 'inherit' },
    opacity: Math.min(1, Math.max(0.1, Number(shape.opacity) || 1)),
    transform: `translate(${shape.x || 0} ${shape.y || 0}) rotate(${((shape.rotation || 0) * 180) / Math.PI})`
  }
  if (shape.type === 'image') {
    const asset = snapshot.store[shape.props?.assetId]
    const source = assetSources.get(asset?.props?.src) || asset?.props?.src || ''
    return (
      <image
        {...common}
        className={selected ? 'is-selected' : ''}
        height={shape.props?.h || 1}
        href={source}
        preserveAspectRatio="none"
        width={shape.props?.w || 1}
      />
    )
  }
  if (shape.type === 'arrow') {
    const start = shape.props?.start ?? { x: 0, y: 0 }
    const end = shape.props?.end ?? { x: 1, y: 1 }
    const width = strokeWidthForSize(shape.props?.size)
    return (
      <line
        {...common}
        className={selected ? 'is-selected' : ''}
        markerEnd={shape.props?.arrowheadEnd === 'none' ? undefined : 'url(#learning-arrow)'}
        stroke={colorValue(shape.props?.color, '#2563eb')}
        strokeDasharray={dashArrayForStyle(shape.props?.dash, width)}
        strokeLinecap="round"
        strokeWidth={width}
        x1={start.x}
        x2={end.x}
        y1={start.y}
        y2={end.y}
      />
    )
  }
  if (shape.type === 'draw' || shape.type === 'highlight') {
    const points = (shape.meta?.hardwareLearningPoints ?? []).map((point) => `${point.x},${point.y}`).join(' ')
    const width = shape.type === 'highlight'
      ? strokeWidthForSize(shape.props?.size, 5) * 4
      : strokeWidthForSize(shape.props?.size, 4)
    return (
      <polyline
        {...common}
        className={selected ? 'is-selected' : ''}
        fill="none"
        points={points}
        stroke={colorValue(shape.props?.color, shape.type === 'highlight' ? '#facc15' : '#7c3aed')}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={width}
      />
    )
  }
  if (shape.type === 'geo') {
    const kind = shape.meta?.hardwareLearningKind
    const frame = shape.meta?.hardwareLearningFrame === true
    const note = kind === 'note'
    const textOnly = kind === 'text'
    const highlight = kind === 'highlight'
    const text = shape.meta?.hardwareLearningText || ''
    const stroke = colorValue(shape.props?.color, frame ? '#7c3aed' : '#2563eb')
    const fill = shape.props?.fill === 'solid'
        ? stroke
        : shape.props?.fill === 'semi' || highlight
          ? stroke
          : 'transparent'
    const fillOpacity = note
      ? shape.props?.fill === 'solid' ? 0.34 : shape.props?.fill === 'semi' ? 0.18 : 0
      : shape.props?.fill === 'solid' ? 0.92 : 0.22
    const strokeWidth = strokeWidthForSize(shape.props?.size, frame ? 4 : 3)
    const geometry = shape.props?.geo === 'ellipse' ? 'ellipse' : 'rectangle'
    const frameNumber = frame && Number.isSafeInteger(shape.meta?.hardwareLearningFrameNumber) && shape.meta.hardwareLearningFrameNumber > 0
      ? shape.meta.hardwareLearningFrameNumber
      : null
    const badgeWidth = frameNumber === null ? 0 : Math.max(30, String(frameNumber).length * 9 + 18)
    const badgeScale = 1 / Math.max(0.05, Number(cameraZoom) || 1)
    const textLayout = (note || textOnly)
      ? layoutLearningText(text, {
          width: shape.props?.w || (note ? 260 : 120),
          height: shape.props?.h || (note ? 120 : 54),
          size: shape.props?.size
        })
      : null
    return (
      <g {...common} className={selected ? 'is-selected' : ''}>
        {textOnly && (
          <rect
            fill="transparent"
            height={shape.props?.h || 54}
            pointerEvents="all"
            stroke="none"
            width={shape.props?.w || 120}
          />
        )}
        {!textOnly && geometry === 'rectangle' && (
          <rect
            className={frame ? 'learning-frame-shape' : ''}
            fill={fill}
            fillOpacity={fillOpacity}
            height={shape.props?.h || 1}
            rx={note ? 10 : 3}
            stroke={stroke}
            strokeDasharray={dashArrayForStyle(shape.props?.dash, strokeWidth)}
            strokeWidth={strokeWidth}
            width={shape.props?.w || 1}
          />
        )}
        {!textOnly && geometry === 'ellipse' && (
          <ellipse
            cx={(shape.props?.w || 1) / 2}
            cy={(shape.props?.h || 1) / 2}
            fill={fill}
            fillOpacity={fillOpacity}
            rx={(shape.props?.w || 1) / 2}
            ry={(shape.props?.h || 1) / 2}
            stroke={stroke}
            strokeDasharray={dashArrayForStyle(shape.props?.dash, strokeWidth)}
            strokeWidth={strokeWidth}
          />
        )}
        {frameNumber !== null && (
          <g className="learning-frame-number" pointerEvents="none" transform={`translate(7 7) scale(${badgeScale})`}>
            <rect fill={stroke} height="28" rx="14" stroke="#ffffff" strokeWidth="2" width={badgeWidth} />
            <text
              dominantBaseline="middle"
              fill="#ffffff"
              fontFamily="system-ui, sans-serif"
              fontSize="15"
              fontWeight="700"
              textAnchor="middle"
              x={badgeWidth / 2}
              y="14"
            >
              {frameNumber}
            </text>
          </g>
        )}
        {!editing && (note || textOnly) && (
          <text className="learning-note-text" fill={textOnly ? stroke : undefined} fontSize={textLayout.fontSize} x="14" y="8">
            {textLayout.lines.map((line, index) => (
              <tspan key={`${shape.id}-${index}`} x="14" dy={index === 0 ? textLayout.firstBaseline : textLayout.lineHeight}>{line}</tspan>
            ))}
          </text>
        )}
      </g>
    )
  }
  return null
}
