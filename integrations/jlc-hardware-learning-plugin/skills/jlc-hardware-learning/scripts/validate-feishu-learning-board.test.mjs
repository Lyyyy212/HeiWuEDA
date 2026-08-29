import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const validator = path.join(path.dirname(fileURLToPath(import.meta.url)), 'validate-feishu-learning-board.mjs');

function nodeStyle(borderColor, fillOpacity) {
  return {
    border_color: borderColor,
    border_opacity: 50,
    border_width: 'narrow',
    fill_opacity: fillOpacity,
  };
}

function fixture(summary) {
  return {
    nodes: [
      { id: 'image', type: 'image', image: { token: 'schematic' } },
      {
        id: 'frame', type: 'composite_shape', x: 100, y: 100, width: 80, height: 50,
        composite_shape: { type: 'round_rect' }, text: { text: '' }, style: nodeStyle('#5178c6', 0),
      },
      {
        id: 'badge', type: 'composite_shape', x: 92, y: 92,
        width: 29.2544002532959, height: 28.414939880371094,
        composite_shape: { type: 'round_rect' }, text: { text: '4', font_size: 12 },
        style: nodeStyle('#5178c6', 50),
      },
      {
        id: 'label', type: 'mind_map', text: { text: '框4 串行接口' },
        style: nodeStyle('#5178c6', 50), mind_map: { parent_id: 'root' },
      },
      {
        id: 'detail', type: 'mind_map', text: { text: summary },
        style: nodeStyle('#5178c6', 100), mind_map: { parent_id: 'label' },
      },
    ],
  };
}

function run(summary, role = 'schematic-page') {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'jlc-fn-validator-'));
  const rawPath = path.join(tempDir, 'board.json');
  fs.writeFileSync(rawPath, JSON.stringify(fixture(summary)));
  try {
    return spawnSync(process.execPath, [
      validator,
      '--raw', rawPath,
      '--role', role,
      '--expected', '4',
    ], { encoding: 'utf8' });
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

test('schematic-page board accepts a concise one-sentence module summary', () => {
  const result = run('通过串行接口完成主控板调试通信。');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /"standard": "JLC-FN-1.3"/u);
});

test('schematic-page board rejects a learning-status placeholder as its detail', () => {
  const result = run('待学习');
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /one-sentence module summary/u);
});

test('project overview board contains every schematic image and no learning frames', () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'jlc-fn-overview-validator-'));
  const rawPath = path.join(tempDir, 'board.json');
  fs.writeFileSync(rawPath, JSON.stringify({
    nodes: [
      { id: 'page-a', type: 'image', image: { token: 'schematic-a' } },
      { id: 'page-b', type: 'image', image: { token: 'schematic-b' } },
    ],
  }));
  try {
    const result = spawnSync(process.execPath, [
      validator,
      '--raw', rawPath,
      '--role', 'project-overview',
      '--expected-images', '2',
    ], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /"imageCount": 2/u);
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});
