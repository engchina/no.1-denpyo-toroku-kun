#!/bin/bash

# Denpyo Toroku Service - Frontend Startup Script
# Runs Oracle JET development server in foreground mode

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"
UI_DIR="${SERVICE_DIR}/ui"

# Check if node is installed
require_command "node" "Please install Node.js 16+"

# Check if npm is installed
require_command "npm" "Please install npm"

log_info "Starting Frontend (Oracle JET 18.0.3 + Preact)..."
log_info "UI directory: $UI_DIR"

cd "$UI_DIR"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    log_warn "node_modules not found. Running npm install..."
    npm install --legacy-peer-deps
fi

log_info "Starting development server..."
log_info "Press Ctrl+C to stop"
echo ""

# Run webpack dev server in foreground
exec npm run dev
