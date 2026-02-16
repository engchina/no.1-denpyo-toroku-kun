#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate

ruff check denpyo_toroku scripts tests
black --check denpyo_toroku scripts tests
mypy denpyo_toroku
pytest

pushd denpyo_toroku/ui >/dev/null
npm run lint
npm run format:check
npm run type-check
popd >/dev/null
