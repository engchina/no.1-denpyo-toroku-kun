#!/usr/bin/env python3
"""
Gunicorn configuration for Denpyo Toroku Service

Based on reference architecture (ahf_service gunicorn_config pattern).
Uses Unix socket binding with gevent worker class.
"""

import multiprocessing
import os

# Base directory resolution
_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_service_dir = os.path.join(_base_dir, "denpyo_toroku")
_log_dir = os.path.join(_service_dir, "log")
os.makedirs(_log_dir, exist_ok=True)

# Binding - TCP port (default) or unix socket
# Use TCP for direct access / Docker; use unix socket behind Nginx
bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8080")

# Working directory - explicitly set for reliability
chdir = _service_dir

# WSGI application entry point
wsgi_app = "wsgi:app"

# Error log path
errorlog = os.path.join(_log_dir, "gunicorn.log")

# Access log path
accesslog = os.path.join(_log_dir, "gunicorn_access.log")

# Worker processes
# For ML workloads, keep workers low to avoid memory duplication of the model
workers = 1

# Worker class - gevent for async I/O (handles concurrent embedding API calls)
worker_class = "gevent"

# Run as daemon
# IMPORTANT: Must be False for Docker (container needs foreground process)
# Set GUNICORN_DAEMON=true for manage.sh (non-Docker) usage
daemon = os.environ.get("GUNICORN_DAEMON", "false").lower() == "true"

# Request timeout (seconds) - longer for ML inference
timeout = 300

# Graceful timeout for worker shutdown
graceful_timeout = 30

# Maximum number of simultaneous clients (gevent)
worker_connections = 100

# Preload application (shares model across workers)
preload_app = True

# Log level
loglevel = "info"

# Process naming
proc_name = "denpyo_toroku_service"

# Max requests before worker restart (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50
