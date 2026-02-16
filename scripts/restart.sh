#!/bin/bash

# Intent Classifier Service - Quick Restart Script
# Usage: ./restart.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"
load_env_if_present

exec "$SCRIPT_DIR/manage.sh" restart
