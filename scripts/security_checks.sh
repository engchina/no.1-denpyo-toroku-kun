#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate

bandit -q -r denpyo_toroku scripts
pip-audit -r requirements.lock

pushd denpyo_toroku/ui >/dev/null
npm run audit
popd >/dev/null
