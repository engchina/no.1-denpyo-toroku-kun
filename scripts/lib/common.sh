#!/bin/bash

# Shared helpers for project scripts.

SCRIPT_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_LIB_DIR")")"
SERVICE_DIR="${PROJECT_ROOT}/denpyo_toroku"
GUNICORN_CONFIG="${PROJECT_ROOT}/gunicorn_config/gunicorn_config.py"
VENV_DIR="${PROJECT_ROOT}/.venv"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

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
    local line=""
    local key=""
    local value=""
    if [ -f "$env_file" ]; then
        while IFS= read -r line || [ -n "$line" ]; do
            if [[ "$line" =~ ^[[:space:]]*# ]] || [[ "$line" =~ ^[[:space:]]*$ ]]; then
                continue
            fi

            if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$ ]]; then
                key="${BASH_REMATCH[2]}"
                value="${BASH_REMATCH[3]}"

                # Trim leading/trailing whitespace around the raw value.
                value="${value#"${value%%[![:space:]]*}"}"
                value="${value%"${value##*[![:space:]]}"}"

                # Strip one layer of surrounding quotes if present.
                if [[ "$value" =~ ^\"(.*)\"$ ]]; then
                    value="${BASH_REMATCH[1]}"
                elif [[ "$value" =~ ^\'(.*)\'$ ]]; then
                    value="${BASH_REMATCH[1]}"
                fi

                if [ -z "${!key+x}" ]; then
                    export "${key}=${value}"
                fi

                # Backward compatibility for older typoed key names.
                case "$key" in
                    OCI_SLIP_RAW_PREFIX)
                        if [ -z "${OCI_SLIPS_RAW_PREFIX+x}" ]; then
                            export "OCI_SLIPS_RAW_PREFIX=${value}"
                        fi
                        ;;
                    OCI_SLIP_CATEGORY_PREFIX)
                        if [ -z "${OCI_SLIPS_CATEGORY_PREFIX+x}" ]; then
                            export "OCI_SLIPS_CATEGORY_PREFIX=${value}"
                        fi
                        ;;
                esac
            else
                log_warn "Skipping invalid .env line: $line"
            fi
        done < "$env_file"
    fi
}

activate_venv() {
    if [ -d "$VENV_DIR" ]; then
        log_info "Activating virtual environment: $VENV_DIR"
        # shellcheck disable=SC1091
        source "${VENV_DIR}/bin/activate"
    else
        log_error "Virtual environment not found: $VENV_DIR"
        log_error "Please create it with: uv venv --python 3.12 .venv"
        return 1
    fi
}

docker_compose_cmd() {
    if command -v docker-compose >/dev/null 2>&1; then
        echo "docker-compose"
        return 0
    fi

    if docker compose version >/dev/null 2>&1; then
        echo "docker compose"
        return 0
    fi

    return 1
}
