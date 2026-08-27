import assert from "node:assert/strict";
import test from "node:test";

import { inlineWidget } from "./widget-resource.mjs";

function renderBridge(initialDisplayMode) {
  return inlineWidget({
    html: "<!doctype html><html><head></head><body><main id=\"root\"></main></body></html>",
    appVersion: "0.1.27+codex.resize-test",
    initialDisplayMode,
  });
}

test("JLC Hardware Learning disables the ext-apps ResizeObserver feedback loop", () => {
  const html = renderBridge("fullscreen");

  assert.match(html, /\{ autoResize: false \}/);
  assert.doesNotMatch(html, /\{ autoResize: true \}/);
});

test("fullscreen canvases do not report their host-owned size back to Codex", () => {
  const html = renderBridge("fullscreen");

  assert.match(html, /if \(displayMode === "fullscreen"\) return;/);
  assert.match(html, /lastReportedSize\?\.width === size\.width/);
  assert.match(html, /lastReportedSize\?\.height === size\.height/);
});
