#!/bin/bash

# Denpyo Toroku Service - Deploy Script
# Usage: ./deploy.sh [start|stop|restart|status|logs]

set -e

PROJECT_NAME="denpyo-toroku"
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${BASE_DIR}/scripts/lib/common.sh"
LOG_DIR="${BASE_DIR}/denpyo_toroku/log"
DOCKER_COMPOSE_CMD=""

# Create required directories
setup_directories() {
    log_info "Creating required directories..."
    mkdir -p "$LOG_DIR"
    log_info "Directories ready"
}

# Check environment
check_environment() {
    log_info "Checking environment..."

    # Docker check
    require_command "docker" "Please install Docker"

    # Docker Compose check
    if ! DOCKER_COMPOSE_CMD="$(docker_compose_cmd)"; then
        log_error "Docker Compose is not installed"
        exit 1
    fi

    # OCI config check
    if [ ! -f ~/.oci/config ]; then
        log_warn "OCI config file (~/.oci/config) not found"
        log_warn "Complete OCI configuration before deploying"
    fi

    log_info "Environment check complete"
}

# Start service
start_service() {
    log_info "Starting Denpyo Toroku Service..."
    setup_directories
    check_environment

    cd "$BASE_DIR"
    $DOCKER_COMPOSE_CMD up -d

    log_info "Service starting..."
    log_info "UI: http://localhost:8080"
    log_info "API: http://localhost:8080/api/v1/"

    # Health check
    log_info "Running health check..."
    sleep 5

    for i in {1..10}; do
        if curl -s http://localhost:8080/api/v1/health > /dev/null 2>&1; then
            log_info "Service is running and healthy"
            break
        else
            if [ $i -eq 10 ]; then
                log_error "Service failed to start"
                $DOCKER_COMPOSE_CMD logs
                exit 1
            fi
            log_info "Waiting... ($i/10)"
            sleep 3
        fi
    done
}

# Stop service
stop_service() {
    log_info "Stopping Denpyo Toroku Service..."
    cd "$BASE_DIR"
    if [ -z "$DOCKER_COMPOSE_CMD" ]; then
        if ! DOCKER_COMPOSE_CMD="$(docker_compose_cmd)"; then
            log_error "Docker Compose is not installed"
            exit 1
        fi
    fi
    $DOCKER_COMPOSE_CMD down
    log_info "Service stopped"
}

# Restart service
restart_service() {
    log_info "Restarting Denpyo Toroku Service..."
    stop_service
    sleep 2
    start_service
}

# Service status
status_service() {
    log_info "Service Status:"
    cd "$BASE_DIR"
    if [ -z "$DOCKER_COMPOSE_CMD" ]; then
        if ! DOCKER_COMPOSE_CMD="$(docker_compose_cmd)"; then
            log_error "Docker Compose is not installed"
            exit 1
        fi
    fi
    $DOCKER_COMPOSE_CMD ps

    echo ""
    log_info "Health Check:"
    if curl -s http://localhost:8080/api/v1/health 2>/dev/null | python3 -m json.tool 2>/dev/null; then
        log_info "Service is healthy"
    else
        log_error "Service is not responding"
    fi
}

# Show logs
show_logs() {
    log_info "Showing logs..."
    cd "$BASE_DIR"
    if [ -z "$DOCKER_COMPOSE_CMD" ]; then
        if ! DOCKER_COMPOSE_CMD="$(docker_compose_cmd)"; then
            log_error "Docker Compose is not installed"
            exit 1
        fi
    fi
    $DOCKER_COMPOSE_CMD logs -f --tail=100
}

# Main
case "$1" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        status_service
        ;;
    logs)
        show_logs
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the service"
        echo "  stop    - Stop the service"
        echo "  restart - Restart the service"
        echo "  status  - Show service status"
        echo "  logs    - Show service logs"
        exit 1
        ;;
esac

exit 0
