const fs = require('node:fs');
const { chromium } = require('playwright');

async function main() {
  const [input, output, width, height] = process.argv.slice(2);
  if (!input || !output || !width || !height) {
    throw new Error('usage: input.svg output.png widthPx heightPx');
  }
  const widthPx = Math.ceil(Number(width));
  const heightPx = Math.ceil(Number(height));
  if (!Number.isFinite(widthPx) || !Number.isFinite(heightPx) || widthPx < 1 || heightPx < 1) {
    throw new Error('SVG width and height must be positive finite numbers');
  }
  if (widthPx > 32767 || heightPx > 32767) {
    throw new Error(`SVG exceeds the Chromium bitmap limit: ${widthPx}x${heightPx}`);
  }
  const svg = fs.readFileSync(input, 'utf8');
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const context = await browser.newContext({
      offline: true,
      viewport: { width: widthPx, height: heightPx },
      deviceScaleFactor: 1,
    });
    const page = await context.newPage();
    await page.setContent(
      `<style>html,body{margin:0;width:${widthPx}px;height:${heightPx}px;overflow:hidden;background:#fff}svg{display:block}</style>${svg}`,
      { waitUntil: 'load' },
    );
    await page.waitForFunction(() => Array.from(document.images).every(image => image.complete));
    await page.screenshot({
      path: output,
      type: 'png',
      clip: { x: 0, y: 0, width: widthPx, height: heightPx },
      animations: 'disabled',
      omitBackground: false,
    });
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error.stack || String(error));
  process.exit(1);
});
