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
FRONTEND_DEV_PORT="${FRONTEND_DEV_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-8080}"

terminate_matching_processes() {
    local label="$1"
    shift
    local patterns=("$@")
    local pids=""
    local pattern=""

    for pattern in "${patterns[@]}"; do
        [ -n "$pattern" ] || continue
        while IFS= read -r pid; do
            [ -n "$pid" ] || continue
            case " $pids " in
                *" $pid "*) ;;
                *) pids="$pids $pid" ;;
            esac
        done < <(ps -ef | awk -v pat="$pattern" 'index($0, pat) > 0 && $2 != "" && $2 != PROCINFO["pid"] { print $2 }')
    done

    pids="$(echo "$pids" | xargs -n1 2>/dev/null | sort -u 2>/dev/null || true)"
    if [ -z "$pids" ]; then
        log_info "No ${label} processes found"
        return 0
    fi

    log_warn "Stopping ${label} processes: $(echo "$pids" | tr '
' ' ' | xargs)"
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        kill -TERM "$pid" 2>/dev/null || true
    done <<< "$pids"

    sleep 2

    local survivors=""
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        if kill -0 "$pid" 2>/dev/null; then
            survivors="$survivors $pid"
        fi
    done <<< "$pids"

    survivors="$(echo "$survivors" | xargs -n1 2>/dev/null | sort -u 2>/dev/null || true)"
    if [ -n "$survivors" ]; then
        log_warn "Force killing ${label} processes: $(echo "$survivors" | tr '
' ' ' | xargs)"
        while IFS= read -r pid; do
            [ -n "$pid" ] || continue
            kill -9 "$pid" 2>/dev/null || true
        done <<< "$survivors"
    fi
}

terminate_port_listeners() {
    local port="$1"
    local label="$2"
    local pids=""

    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        case " $pids " in
            *" $pid "*) ;;
            *) pids="$pids $pid" ;;
        esac
    done < <(ss -ltnp 2>/dev/null | awk -v port=":${port}" '
        index($4, port) > 0 {
            line = $0
            while (match(line, /pid=[0-9]+/)) {
                print substr(line, RSTART + 4, RLENGTH - 4)
                line = substr(line, RSTART + RLENGTH)
            }
        }
    ')

    pids="$(echo "$pids" | xargs -n1 2>/dev/null | sort -u 2>/dev/null || true)"
    if [ -z "$pids" ]; then
        log_info "No listeners found on ${label} port ${port}"
        return 0
    fi

    log_warn "Killing listeners on ${label} port ${port}: $(echo "$pids" | tr '
' ' ' | xargs)"
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        kill -TERM "$pid" 2>/dev/null || true
    done <<< "$pids"

    sleep 2

    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done <<< "$pids"
}

force_stop_frontend_and_backend() {
    log_info "Force stopping frontend and backend processes..."

    terminate_matching_processes "backend"         "$PROJECT_ROOT/.venv/bin/python .venv/bin/gunicorn -c gunicorn_config/gunicorn_config.py"         "gunicorn: master [denpyo_toroku_service]"         "gunicorn: worker [denpyo_toroku_service]"         "$SERVICE_DIR/wsgi:app"

    terminate_matching_processes "frontend"         "$UI_DIR"         "npm run dev"         "webpack serve --mode development --open"

    terminate_port_listeners "$BACKEND_PORT" "backend"
    terminate_port_listeners "$FRONTEND_DEV_PORT" "frontend"

    rm -f "$SERVICE_DIR/gunicorn.pid"
    rm -f "$SERVICE_DIR/denpyo_toroku.sock"
}

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
force_stop_frontend_and_backend
build_frontend

exec "$SCRIPT_DIR/manage.sh" start
