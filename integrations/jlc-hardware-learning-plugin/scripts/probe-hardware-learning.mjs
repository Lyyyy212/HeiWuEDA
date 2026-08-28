import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { CANVAS_BRAND_NAME, CANVAS_GITHUB_URL } from "../shared/branding.mjs";

const mainSource = await readFile(new URL("../src/main.jsx", import.meta.url), "utf8");
assert.match(mainSource, /import HardwareLearningCanvas from '.\/learning-canvas\/HardwareLearningCanvas\.jsx'/);
assert.match(mainSource, /render\(<HardwareLearningCanvas \/>\)/);
assert.doesNotMatch(mainSource, /App\.jsx|analytics/);

const learningCanvasSource = await readFile(
  new URL("../src/learning-canvas/HardwareLearningCanvas.jsx", import.meta.url),
  "utf8",
);
assert.match(learningCanvasSource, /data-engine="jlc-hardware-learning-canvas-v1"/);
assert.match(learningCanvasSource, /data-testid="black-five-canvas-watermark"/);
assert.match(learningCanvasSource, /CANVAS_BRAND_NAME/);
assert.match(learningCanvasSource, /href=\{CANVAS_GITHUB_URL\}/);
assert.match(learningCanvasSource, /target="_blank"/);
assert.match(learningCanvasSource, /rel="noreferrer noopener"/);
assert.match(learningCanvasSource, /id: 'frame', label: '学习框'/);
assert.match(learningCanvasSource, /jlc-learning-top-actions/);
assert.match(learningCanvasSource, /jlc-learning-style-panel/);
assert.match(learningCanvasSource, /jlc-learning-bottom-toolbar/);
assert.match(learningCanvasSource, /jlc-learning-zoom-controls/);
assert.match(learningCanvasSource, /<InlineCanvasTextEditor/);
assert.doesNotMatch(learningCanvasSource, /<foreignObject/);
assert.doesNotMatch(learningCanvasSource, /learning-note-dialog|learning-dialog-backdrop|<small>\{label\}<\/small>/);
assert.match(learningCanvasSource, /id: 'eraser', label: '橡皮擦'/);
assert.match(learningCanvasSource, /id: 'rectangle', label: '矩形'/);
assert.match(learningCanvasSource, /duplicateLearningShapes/);
assert.match(learningCanvasSource, /selectionRevisionRef/);
assert.match(learningCanvasSource, /buildLearningCanvasSvg/);
assert.match(learningCanvasSource, /createHistoryManager/);
assert.match(learningCanvasSource, /cameraAfterWheel/);
assert.match(learningCanvasSource, /className="learning-canvas-grid"/);
assert.match(learningCanvasSource, /shapeIntersectsViewport/);
assert.match(learningCanvasSource, /data-rendered-image-count/);
assert.match(learningCanvasSource, /learning-canvas-viewport-clip/);
assert.match(learningCanvasSource, /addEventListener\('wheel', handleWheel, \{ passive: false \}\)/);
assert.doesNotMatch(learningCanvasSource, /onWheel=\{handleWheel\}/);
assert.match(learningCanvasSource, /normalizeCamera\(loaded\.viewState\?\.camera/);
assert.doesNotMatch(learningCanvasSource, /height=\{100000\}|width=\{100000\}|x=\{-50000\}|y=\{-50000\}/);
assert.match(learningCanvasSource, /shouldBeginTextEditFromPointerDown/);
assert.match(learningCanvasSource, /completeTextEditPointerActivation/);
assert.match(learningCanvasSource, /textEditActivationCandidate/);
assert.match(learningCanvasSource, /\['move', 'resize'\]\.includes\(gesture\.type\)/);
assert.match(learningCanvasSource, /shouldBeginCanvasTextFromDoubleClick/);
assert.match(learningCanvasSource, /rightClickCanvasAction/);
assert.match(learningCanvasSource, /deleteSelectedShapes/);
assert.match(learningCanvasSource, /acknowledgedImageShapeDeletes: result\.deletedImages/);
assert.match(learningCanvasSource, /disabled=\{!selectedIds\.length\}[\s\S]*?label="删除选中内容"/);
assert.doesNotMatch(learningCanvasSource, /testId="learning-delete-image"/);
assert.match(learningCanvasSource, /event\.key === 'Delete'[\s\S]*?deleteLearningShapes\(snapshotRef\.current, selectedIds\)/);
assert.match(learningCanvasSource, /data-testid="learning-delete-image-dialog"/);
assert.match(learningCanvasSource, /不会修改嘉立创 EDA 工程/);
assert.match(learningCanvasSource, /onDoubleClick=\{handleCanvasDoubleClick\}/);
assert.match(learningCanvasSource, /onContextMenu=\{handleCanvasContextMenu\}/);
assert.match(learningCanvasSource, /selectionForShapePointerDown/);
assert.match(learningCanvasSource, /translateCanvasSelection/);
assert.match(learningCanvasSource, /onPointerCancel=\{handlePointerCancel\}/);
assert.doesNotMatch(learningCanvasSource, /from ['"]tldraw['"]|tl-watermark|Made with tldraw/);

const inlineEditorSource = await readFile(
  new URL("../src/learning-canvas/InlineCanvasTextEditor.jsx", import.meta.url),
  "utf8",
);
assert.match(inlineEditorSource, /learning-inline-text-editor/);
assert.match(inlineEditorSource, /<div[\s\S]*?className="learning-inline-editor"/);
assert.match(inlineEditorSource, /pageToScreen\(point, camera\)/);
assert.match(inlineEditorSource, /event\.nativeEvent\.isComposing/);
assert.match(inlineEditorSource, /data-jlc-learning-preserve-text-editor/);
assert.match(inlineEditorSource, /learning-inline-editor-hint/);
assert.match(inlineEditorSource, /indentInlineLearningText/);
assert.match(inlineEditorSource, /保持文本工具/);
assert.match(inlineEditorSource, /Esc\/右键退出选择/);
assert.match(learningCanvasSource, /toolAfterInlineTextEdit/);
assert.doesNotMatch(inlineEditorSource, /<foreignObject/);

const modelSource = await readFile(
  new URL("../src/learning-canvas/model.js", import.meta.url),
  "utf8",
);
const learningShapeSource = await readFile(
  new URL("../src/learning-canvas/LearningShape.jsx", import.meta.url),
  "utf8",
);
assert.match(modelSource, /fontSize: 13, lineHeight: 18/);
assert.match(modelSource, /fontSize: 28, lineHeight: 36/);
assert.match(modelSource, /LEARNING_TEXT_METRICS_VERSION = 3/);
assert.match(learningCanvasSource, /字号（13 \/ 15 \/ 20 \/ 28）/);
assert.match(modelSource, /MAX_CAMERA_ZOOM = 4/);
assert.match(modelSource, /MIN_CAMERA_ZOOM = 0\.08/);
assert.match(modelSource, /export function shapeIntersectsViewport/);
assert.match(learningShapeSource, /fontSize="15"/);

const historySource = await readFile(
  new URL("../src/learning-canvas/history.js", import.meta.url),
  "utf8",
);
assert.match(historySource, /createSnapshotDelta/);
assert.match(historySource, /metadata: cloneValue\(delta\.metadata\)/);
assert.match(historySource, /redoStack\.length = 0/);

const interactionSource = await readFile(
  new URL("../src/learning-canvas/interaction.js", import.meta.url),
  "utf8",
);
assert.match(interactionSource, /shape\.type === 'image'\) return shape\.isLocked !== true/);
assert.match(interactionSource, /wheel\.shiftKey && !wheel\.ctrlKey && !wheel\.metaKey/);
assert.match(interactionSource, /kind: 'zoom'/);
assert.match(interactionSource, /nudgeDeltaForKey/);

const stylesSource = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
assert.doesNotMatch(stylesSource, /jlc-learning-hardware-question-panel/);
assert.doesNotMatch(stylesSource, /tl-watermark|SEE-LICENSE/);

const learningStylesSource = await readFile(
  new URL("../src/learning-canvas/styles.css", import.meta.url),
  "utf8",
);
assert.match(learningStylesSource, /\.learning-inline-editor/);
assert.match(learningStylesSource, /\.learning-canvas-viewport \{[\s\S]*?contain: strict;/);
assert.match(learningStylesSource, /\.learning-canvas-svg \{[\s\S]*?overflow: hidden;/);
assert.match(learningStylesSource, /\.black-five-canvas-watermark:hover/);
assert.doesNotMatch(learningStylesSource, /\.learning-note-dialog|\.learning-dialog-backdrop/);

const viteSource = await readFile(new URL("../vite.config.js", import.meta.url), "utf8");
assert.match(viteSource, /JLC_HARDWARE_LEARNING_PROJECT_DIR/);
assert.match(viteSource, /JLC_HARDWARE_LEARNING_CANVAS_DIR/);
assert.match(viteSource, /source: 'jlc-hardware-learning'/);

const widgetSource = await readFile(new URL("../mcp/generated/hardware-learning-widget.html", import.meta.url), "utf8");
assert.match(widgetSource, /jlc-hardware-learning-canvas-v1/);
assert.match(widgetSource, new RegExp(CANVAS_BRAND_NAME));
assert.match(widgetSource, new RegExp(CANVAS_GITHUB_URL.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
assert.doesNotMatch(widgetSource, /tl-watermark|Made with tldraw|production license/i);

const serverSource = await readFile(new URL("../mcp/server.mjs", import.meta.url), "utf8");
assert.match(serverSource, /mode: widgetModeSchema\.optional\(\)/);
assert.match(serverSource, /assertLearningGenerationAllowed\(args, "HTML"\)/);
assert.match(serverSource, /LEARNING_EVIDENCE_SOURCES\.has\(args\.evidenceSource\)/);
assert.match(serverSource, /official-easyeda-pdf-render/);
assert.match(serverSource, /assetMeta\.evidenceSource = evidenceSource/);
assert.match(serverSource, /shapeMeta\.evidenceSource = evidenceSource/);
assert.match(serverSource, /does not match the admitted evidenceSource/);
assert.match(serverSource, /TOOL_SAVE_LEARNING_QUESTION[\s\S]*?visibility: \["model", "app"\]/);
assert.match(serverSource, /buildConversationLearningQuestion/);
assert.match(serverSource, /await ensureHardwareLearningCanvasState\(\{ \.\.\.input, projectDir, canvasDir \}\)/);
assert.match(serverSource, /TOOL_MANAGE_CANVASES/);
assert.match(serverSource, /recycleHardwareLearningCanvas/);

const catalogSource = await readFile(
  new URL("../mcp/lib/canvas-catalog.mjs", import.meta.url),
  "utf8",
);
assert.match(catalogSource, /join\(projectDir, "canvases"\)/);
assert.match(catalogSource, /\.trash/);
assert.match(catalogSource, /DEFAULT_CANVAS_ID = "default"/);
assert.match(catalogSource, /CANVAS_ID_PATTERN/);

const selectionStorageSource = await readFile(
  new URL("../mcp/lib/canvas-storage.mjs", import.meta.url),
  "utf8",
);
assert.match(selectionStorageSource, /lastNonEmptySelection/);

const conversationQuestionSource = await readFile(
  new URL("../mcp/learning/conversation-question.mjs", import.meta.url),
  "utf8",
);
assert.match(conversationQuestionSource, /selectionSource: chosen\.source/);
assert.match(conversationQuestionSource, /roleForShape/);
assert.match(conversationQuestionSource, /hardwareLearningFrame/);
assert.doesNotMatch(conversationQuestionSource, /props\?\.geo === "rectangle"\) return "selection-frame"/);
assert.doesNotMatch(conversationQuestionSource, /imagegen|insert_hardware_learning_image|sendFollowUpMessage/);

console.log("JLC Hardware Learning dedicated canvas probe passed.");
