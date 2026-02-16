import os

SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
PERMANENT_SESSION_LIFETIME = 1800
PROPAGATE_EXCEPTIONS = False
SESSION_COOKIE_NAME = "denpyo_toroku_session"

RESPONSE_HEADERS = {
    "Cache-Control": "no-store, private",
    "X-Content-Type-Options": "nosniff",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "; ".join([
        "default-src 'self'",
        "script-src 'self' 'unsafe-eval'",
        "object-src 'none'",
        "font-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "frame-src 'self'",
        "connect-src 'self' ws: wss:",
        "media-src 'self'",
        "upgrade-insecure-requests",
        "form-action 'self'",
        "frame-ancestors 'self'"
    ])
}
