import os
import logging
from flask import request, jsonify, make_response

from denpyo_toroku.config import AppConfig

webapp_port = os.environ.get("WEBAPP_PORT", None)

ALLOWED_ORIGINS = [
    "https://localhost:5000",
    "http://localhost:5000",
    "https://localhost:8080",
    "http://localhost:8080",
]

if AppConfig.LOAD_BALANCER_ALIAS and webapp_port:
    ALLOWED_ORIGINS.append(f"https://{AppConfig.LOAD_BALANCER_ALIAS}:{webapp_port}")


def setup_headers_after_request(response):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    if request.method == "OPTIONS":
        response.status_code = 204
    return response


def handle_cors_options():
    origin = request.headers.get("Origin")

    if origin in ALLOWED_ORIGINS:
        if request.method == "OPTIONS":
            response = make_response('', 204)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            return response

    return None


def setup_cors_middleware(app):
    app.after_request(setup_headers_after_request)
    app.before_request(handle_cors_options)
