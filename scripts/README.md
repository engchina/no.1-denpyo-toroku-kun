# Scripts Overview

This directory contains operational and development scripts.

## Runtime

- `start-backend.sh`: Run Flask/Gunicorn backend in foreground mode.
- `start-frontend.sh`: Run Oracle JET frontend dev server.
- `manage.sh`: Manage Gunicorn in daemon mode (`start|stop|restart|status|logs`).
- `restart.sh`: Shortcut for `manage.sh restart`.

## Utilities

- `train.py`: Train intent classifier model.
- `test_production.py`: Integration-style production test script.
- `client_example.py`: Example API client usage.

## Shared Library

- `lib/common.sh`: Shared helpers for path resolution, logging, env loading, and dependency checks.

