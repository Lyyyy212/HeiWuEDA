#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CALLER_DIR="$PWD"
PORT="${JLC_HARDWARE_LEARNING_PORT:-43217}"
PROJECT_DIR="${JLC_HARDWARE_LEARNING_PROJECT_DIR:-${COWART_PROJECT_DIR:-${1:-$CALLER_DIR}}}"
CANVAS_DIR="${JLC_HARDWARE_LEARNING_CANVAS_DIR:-${COWART_CANVAS_DIR:-$PROJECT_DIR/canvas}}"

export JLC_HARDWARE_LEARNING_PROJECT_DIR="$PROJECT_DIR"
export JLC_HARDWARE_LEARNING_CANVAS_DIR="$CANVAS_DIR"

cd "$ROOT_DIR"

if [ ! -d node_modules ] || [ ! -x node_modules/.bin/vite ]; then
  npm install
fi

echo "JLC Hardware Learning canvas: http://127.0.0.1:${PORT}"
echo "JLC Hardware Learning canvas data: ${CANVAS_DIR}/pages/<page-id>/hardware-learning-canvas.json"
echo "JLC Hardware Learning page assets: ${CANVAS_DIR}/pages/<page-id>/assets -> http://127.0.0.1:${PORT}/page-assets/<page-id>/"
exec npm run dev -- --host 127.0.0.1 --port "$PORT"
