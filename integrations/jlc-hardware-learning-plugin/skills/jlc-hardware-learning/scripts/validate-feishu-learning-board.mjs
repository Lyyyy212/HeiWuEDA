import fs from 'node:fs';

const WIDTH = 29.2544002532959;
const HEIGHT = 28.414939880371094;
const OFFSET = -8;
const TOLERANCE = 0.05;
const STATUS_PLACEHOLDERS = new Set(['待学习', '学习中', '问题待解决', '已总结', '需复查']);

function argument(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index === -1 ? fallback : process.argv[index + 1];
}

function close(actual, expected) {
  return Math.abs(Number(actual) - Number(expected)) <= TOLERANCE;
}

function fail(message) {
  throw new Error(message);
}

const rawPath = argument('--raw');
const role = argument('--role', 'module-index');
const expected = argument('--expected', '')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean)
  .sort((a, b) => Number(a) - Number(b));
if (!rawPath) fail('--raw is required.');
if (!['main', 'module-index'].includes(role)) fail('--role must be main or module-index.');

const board = JSON.parse(fs.readFileSync(rawPath, 'utf8'));
if (!Array.isArray(board.nodes)) fail('Raw export must contain a nodes array.');

const shapes = board.nodes.filter((node) => node.type === 'composite_shape');
const badges = shapes
  .filter((node) => /^\d+$/u.test(String(node.text?.text ?? '')))
  .sort((left, right) => Number(left.text.text) - Number(right.text.text));
const numbers = badges.map((node) => String(node.text.text));
if (expected.length && JSON.stringify(numbers) !== JSON.stringify(expected)) {
  fail(`Badge numbers differ: expected ${expected.join(',')}, got ${numbers.join(',')}.`);
}
if (badges.length === 0) fail('No numbered learning-frame badges found.');

const frameByNumber = new Map();
for (const badge of badges) {
  const number = String(badge.text.text);
  if (!close(badge.width, WIDTH) || !close(badge.height, HEIGHT)) {
    fail(`Badge ${number} must stay fixed at ${WIDTH} x ${HEIGHT}; got ${badge.width} x ${badge.height}.`);
  }
  if (Number(badge.text?.font_size) !== 12) fail(`Badge ${number} font size must be 12.`);
  if (badge.composite_shape?.type !== 'round_rect') fail(`Badge ${number} must be a round rectangle.`);
  if (badge.style?.border_opacity !== 50 || badge.style?.fill_opacity !== 50
      || badge.style?.border_width !== 'narrow') {
    fail(`Badge ${number} must use 50% border/fill opacity and a narrow border.`);
  }
  const candidates = shapes.filter((node) =>
    node.text?.text === ''
    && node.style?.fill_opacity === 0
    && node.style?.border_color === badge.style?.border_color
    && node.style?.border_opacity === 50
    && node.style?.border_width === 'narrow'
  );
  const frame = candidates.find((node) =>
    close(badge.x, Number(node.x) + OFFSET) && close(badge.y, Number(node.y) + OFFSET)
  );
  if (!frame) fail(`Badge ${number} is not fixed at -8/-8 on a matching learning frame.`);
  frameByNumber.set(number, frame);
}

const colors = badges.map((badge) => badge.style?.border_color);
if (badges.length <= 8 && new Set(colors).size !== badges.length) {
  fail('Learning-frame colors must be distinct until the standard palette is exhausted.');
}

if (role === 'module-index') {
  const images = board.nodes.filter((node) => node.type === 'image');
  if (images.length !== 1) fail(`Module index must contain exactly one schematic image; got ${images.length}.`);
  const labels = board.nodes.filter((node) => /^框\d+\s/u.test(String(node.text?.text ?? '')));
  for (const badge of badges) {
    const number = String(badge.text.text);
    const label = labels.find((node) => new RegExp(`^框${number}\\s`, 'u').test(String(node.text?.text ?? '')));
    if (!label) fail(`Module-index label for frame ${number} is missing.`);
    if (label.style?.border_color !== badge.style?.border_color
        || label.style?.border_opacity !== 50
        || label.style?.fill_opacity !== 50
        || label.style?.border_width !== 'narrow') {
      fail(`Module-index label for frame ${number} does not follow the learning-frame style.`);
    }
    const detail = board.nodes.find((node) => node.mind_map?.parent_id === label.id);
    if (!detail || detail.style?.border_color !== badge.style?.border_color
        || detail.style?.border_opacity !== 50
        || detail.style?.border_width !== 'narrow') {
      fail(`Module-index detail branch for frame ${number} does not follow the learning-frame style.`);
    }
    const summary = String(detail.text?.text ?? '').trim();
    if (!summary || STATUS_PLACEHOLDERS.has(summary)) {
      fail(`Module-index detail for frame ${number} must be a one-sentence module summary, not a status placeholder.`);
    }
    if (summary.length > 80) {
      fail(`Module-index detail for frame ${number} must stay concise (80 characters or fewer).`);
    }
  }
}

console.log(JSON.stringify({
  ok: true,
  standard: 'JLC-FN-1.2',
  role,
  nodeCount: board.nodes.length,
  imageCount: board.nodes.filter((node) => node.type === 'image').length,
  badges: badges.map((badge) => ({
    number: Number(badge.text.text),
    color: badge.style.border_color,
    x: badge.x,
    y: badge.y,
    frameId: frameByNumber.get(String(badge.text.text))?.id ?? null,
  })),
}, null, 2));
