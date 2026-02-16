#!/bin/bash

# Intent Classifier Service - Backend Startup Script
# Runs Gunicorn in foreground mode (logs visible in terminal)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

# Activate virtual environment
activate_venv

# Check if gunicorn is installed
if ! command -v gunicorn >/dev/null 2>&1; then
    log_error "gunicorn is not installed. Please run: uv pip install gunicorn"
    exit 1
fi

log_info "Starting Backend (Gunicorn + Flask)..."
log_info "Service directory: $SERVICE_DIR"
log_info "Press Ctrl+C to stop"
echo ""

cd "$SERVICE_DIR"

# Run Gunicorn in foreground mode (no daemon)
# GUNICORN_DAEMON is not set, so gunicorn runs in foreground
exec gunicorn -c "$GUNICORN_CONFIG" wsgi:app
