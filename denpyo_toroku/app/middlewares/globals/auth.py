import datetime
from flask import request, session, g, redirect, jsonify
from denpyo_toroku.auth_config import SESSION_TIMEOUT_SECONDS


def _verify_token_not_expired(token_expiry_ts):
    if token_expiry_ts is None:
        return False
    current_time = datetime.datetime.now().timestamp()
    return current_time < float(token_expiry_ts)


def _redirect_target_with_query(base_target: str) -> str:
    if request.query_string:
        return f"{base_target}?{request.query_string.decode('utf-8', errors='ignore')}"
    return base_target


def _redirect_legacy_static_path():
    static_dirs = ("js", "css", "styles", "vendor")
    path = request.path

    # Keep API endpoints untouched.
    if path.startswith("/api/") or path.startswith("/studio/api/") or path.startswith("/studio/v1/"):
        return None

    # 1) Root legacy static paths: /styles/... -> /studio/styles/...
    for static_dir in static_dirs:
        legacy_prefix = f"/{static_dir}"
        if path == legacy_prefix or path.startswith(legacy_prefix + "/"):
            return redirect(_redirect_target_with_query(f"/studio{path}"), code=307)

    canonical_prefixes = tuple(f"/studio/{static_dir}" for static_dir in static_dirs)
    if path.startswith(canonical_prefixes):
        return None

    # 2) Nested legacy paths from SPA routes:
    #    /settings/styles/... or /studio/settings/styles/... -> /studio/styles/...
    segments = [segment for segment in path.split("/") if segment]
    for index, segment in enumerate(segments):
        if segment in static_dirs and index > 0:
            suffix = "/" + "/".join(segments[index:])
            return redirect(_redirect_target_with_query(f"/studio{suffix}"), code=307)

    return None


def _refresh_session_expiry():
    current_time = datetime.datetime.now() + datetime.timedelta(seconds=SESSION_TIMEOUT_SECONDS)
    session.permanent = True
    session["token_expiry_ts"] = int(current_time.timestamp())


def auth_middleware():
    # Direct host access ("/") should always land on the UI entry path.
    if request.path == "/":
        return redirect(_redirect_target_with_query("/studio/"), code=302)

    static_redirect = _redirect_legacy_static_path()
    if static_redirect:
        return static_redirect

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
        _refresh_session_expiry()
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
