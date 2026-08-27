const fs = require('node:fs');
const { chromium } = require('playwright');

async function main() {
  const [input, output, width, height] = process.argv.slice(2);
  if (!input || !output || !width || !height) {
    throw new Error('usage: input.svg output.pdf widthPx heightPx');
  }
  const svg = fs.readFileSync(input, 'utf8');
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const context = await browser.newContext({ offline: true });
    const page = await context.newPage();
    await page.setContent(
      `<style>@page{size:${width}px ${height}px;margin:0}html,body{margin:0;width:${width}px;height:${height}px;overflow:hidden}svg{display:block}</style>${svg}`,
      { waitUntil: 'load' },
    );
    await page.waitForFunction(() => Array.from(document.images).every(image => image.complete));
    await page.pdf({
      path: output,
      width: `${width}px`,
      height: `${height}px`,
      margin: { top: '0', right: '0', bottom: '0', left: '0' },
      printBackground: true,
      preferCSSPageSize: true,
    });
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error.stack || String(error));
  process.exit(1);
});
