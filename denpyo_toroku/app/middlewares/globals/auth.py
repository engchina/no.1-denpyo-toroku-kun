import datetime
from flask import request, session, g, redirect, jsonify


def _verify_token_not_expired(token_expiry_ts):
    if not token_expiry_ts:
        return False
    current_time = datetime.datetime.now().timestamp()
    return current_time < float(token_expiry_ts)


def auth_middleware():
    legacy_static_prefixes = (
        "/js",
        "/css",
        "/styles",
        "/vendor",
    )

    # Backward compatibility:
    # older frontend bundles may still request root-level assets (/js/...).
    # Redirect them to the /studio-prefixed static routes.
    for prefix in legacy_static_prefixes:
        if request.path == prefix or request.path.startswith(prefix + "/"):
            target = f"/studio{request.path}"
            if request.query_string:
                target = f"{target}?{request.query_string.decode('utf-8', errors='ignore')}"
            return redirect(target, code=307)

    static_endpoints = (
        "/studio/js",
        "/studio/css",
        "/studio/styles",
        "/studio/vendor",
        "/studio/v1/version",
        "/studio/api/v1/health"
    )

    endpoints_without_auth = (
        "/studio/login",
        "/studio/logout",
        "/studio/v1/me",
        "/studio/v1/loginValidation",
        "/studio/register",
        "/studio/api/v1/auth/login",
        "/studio/api/v1/auth/logout",
        "/studio/api/v1/auth/me",
        "/studio/api/v1/health",
    )

    ui_endpoint = "/studio"

    if request.path.startswith(static_endpoints) or request.path.startswith(endpoints_without_auth):
        return

    if request.path == ui_endpoint or request.path == ui_endpoint + "/":
        return

    user = session.get("user", None)
    token = session.get("token", None)
    token_expiry_ts = session.get("token_expiry_ts", None)

    if user and token and _verify_token_not_expired(token_expiry_ts):
        g.user_email = user
        g.user_name = user
        g.user_id = session.get("user_id", None)
        current_time = datetime.datetime.now() + datetime.timedelta(minutes=30)
        session["token_expiry_ts"] = int(current_time.timestamp())
        return

    session.pop("token", None)
    session.pop("user", None)
    session.pop("token_expiry_ts", None)
    session.pop("user_id", None)
    session.pop("role", None)

    if request.path.startswith("/studio/v1/") or request.path.startswith("/studio/api/v1/"):
        return jsonify({"error": "Unauthorized", "message": "ログインしてください"}), 401

    return redirect("/studio/login", code=303)


def setup_auth_middleware(app):
    app.before_request(auth_middleware)
