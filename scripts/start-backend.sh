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

# Enable auto-reload in local development by default.
# Can be disabled with BACKEND_AUTO_RELOAD=false ./scripts/start-backend.sh
BACKEND_AUTO_RELOAD="${BACKEND_AUTO_RELOAD:-true}"

if [ "$BACKEND_AUTO_RELOAD" = "true" ]; then
    log_info "Auto-reload is enabled"
    # Gunicorn reload mode is incompatible with preloaded apps.
    export GUNICORN_PRELOAD_APP=false
    exec gunicorn --reload -c "$GUNICORN_CONFIG" wsgi:app
fi

log_info "Auto-reload is disabled"
# Run Gunicorn in foreground mode (no daemon)
# GUNICORN_DAEMON is not set, so gunicorn runs in foreground
exec gunicorn -c "$GUNICORN_CONFIG" wsgi:app
