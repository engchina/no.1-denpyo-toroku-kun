#!/bin/bash

# Denpyo Toroku Service - Gunicorn Management Script
# Usage: ./manage.sh [start|stop|restart|status]
# Manages the Gunicorn process (daemon mode)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"
PID_FILE="${SERVICE_DIR}/gunicorn.pid"
SOCK_FILE="${SERVICE_DIR}/denpyo_toroku.sock"
LOG_DIR="${SERVICE_DIR}/log"

# Start Gunicorn (daemon mode)
start_gunicorn() {
    activate_venv
    log_info "Starting Gunicorn (daemon mode)..."
    mkdir -p "$LOG_DIR"

    # Check if already running
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            log_warn "Gunicorn is already running (PID: $PID)"
            return 0
        fi
    fi

    cd "$SERVICE_DIR"
    GUNICORN_DAEMON=true gunicorn -c "$GUNICORN_CONFIG" --pid "$PID_FILE" wsgi:app

    sleep 2
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        log_info "Gunicorn started (PID: $PID)"
        log_info "Logs: $LOG_DIR/gunicorn.log"
    else
        log_error "Failed to start Gunicorn"
        exit 1
    fi
}

# Stop Gunicorn
stop_gunicorn() {
    log_info "Stopping Gunicorn..."

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill -TERM "$PID"
            sleep 2

            # Force kill if still running
            if kill -0 "$PID" 2>/dev/null; then
                log_warn "Forcing shutdown..."
                kill -9 "$PID"
            fi

            log_info "Gunicorn stopped"
        else
            log_warn "Gunicorn process not found (stale PID file)"
        fi
        rm -f "$PID_FILE"
    else
        log_warn "PID file not found, Gunicorn may not be running"
    fi

    # Cleanup socket file
    rm -f "$SOCK_FILE"
}

# Restart Gunicorn
restart_gunicorn() {
    stop_gunicorn
    sleep 1
    start_gunicorn
}

# Gunicorn status
status_gunicorn() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            log_info "Gunicorn is running (PID: $PID)"
            return 0
        else
            log_warn "Gunicorn PID file exists but process not running"
            return 1
        fi
    else
        log_info "Gunicorn is not running"
        return 1
    fi
}

# View logs
view_logs() {
    if [ -f "$LOG_DIR/gunicorn.log" ]; then
        log_info "Showing logs (Ctrl+C to exit):"
        tail -f "$LOG_DIR/gunicorn.log"
    else
        log_warn "Log file not found: $LOG_DIR/gunicorn.log"
    fi
}

# Main
case "$1" in
    start)
        start_gunicorn
        ;;
    stop)
        stop_gunicorn
        ;;
    restart)
        restart_gunicorn
        ;;
    status)
        status_gunicorn
        ;;
    logs)
        view_logs
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start Gunicorn (daemon mode)"
        echo "  stop    - Stop Gunicorn"
        echo "  restart - Restart Gunicorn"
        echo "  status  - Check Gunicorn status"
        echo "  logs    - View Gunicorn logs (tail -f)"
        echo ""
        echo "For foreground mode (visible logs), use:"
        echo "  ./start-backend.sh   - Start backend in foreground"
        echo "  ./start-frontend.sh  - Start frontend in foreground"
        exit 1
        ;;
esac

exit 0
