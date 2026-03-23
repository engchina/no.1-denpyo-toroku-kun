#!/bin/bash

# Denpyo Toroku Service - Quick Restart Script
# Usage: ./scripts/restart.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMMON_SH="${SCRIPT_DIR}/lib/common.sh"

if [ -f "$COMMON_SH" ]; then
    # shellcheck disable=SC1091
    source "$COMMON_SH"
else
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
    SERVICE_DIR="${PROJECT_ROOT}/denpyo_toroku"

    GREEN='[0;32m'
    YELLOW='[1;33m'
    RED='[0;31m'
    NC='[0m'

    log_info() {
        echo -e "${GREEN}[INFO]${NC} $1"
    }

    log_warn() {
        echo -e "${YELLOW}[WARN]${NC} $1"
    }

    log_error() {
        echo -e "${RED}[ERROR]${NC} $1"
    }

    require_command() {
        local cmd="$1"
        local hint="$2"
        if ! command -v "$cmd" >/dev/null 2>&1; then
            log_error "$cmd is not installed"
            if [ -n "$hint" ]; then
                log_error "$hint"
            fi
            return 1
        fi
    }

    load_env_if_present() {
        local env_file="${PROJECT_ROOT}/.env"
        if [ -f "$env_file" ]; then
            set -a
            # shellcheck disable=SC1090
            source "$env_file"
            set +a
        fi
    }
fi

UI_DIR="${SERVICE_DIR}/ui"

build_frontend() {
    require_command "node" "Please install Node.js 20.x"
    require_command "npm" "Please install npm"

    if [ ! -d "$UI_DIR" ]; then
        log_error "Frontend directory not found: $UI_DIR"
        return 1
    fi

    log_info "Building frontend assets..."
    cd "$UI_DIR"

    if [ ! -d "node_modules" ]; then
        log_warn "node_modules not found. Running npm install..."
        npm install --legacy-peer-deps
    fi

    npm run build
}

load_env_if_present
build_frontend

exec "$SCRIPT_DIR/manage.sh" restart
