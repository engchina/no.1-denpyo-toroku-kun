import time

from flask import Flask

from denpyo_toroku.app.middlewares.globals.auth import auth_middleware
from denpyo_toroku.auth_config import SESSION_TIMEOUT_SECONDS


def _create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.before_request(auth_middleware)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def passthrough(path: str):
        return f"ok:{path}", 200

    return app


def test_root_legacy_styles_path_redirects_to_studio():
    app = _create_app()

    with app.test_client() as client:
        response = client.get("/styles/images/JET-Favicon-Red-32x32.png")

    assert response.status_code == 307
    assert response.headers["Location"].endswith("/studio/styles/images/JET-Favicon-Red-32x32.png")


def test_root_path_redirects_to_studio_entry():
    app = _create_app()

    with app.test_client() as client:
        response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/studio/")


def test_nested_styles_path_redirects_to_studio_styles():
    app = _create_app()

    with app.test_client() as client:
        response = client.get("/settings/styles/images/JET-Favicon-Red-32x32.png?x=1")

    assert response.status_code == 307
    assert response.headers["Location"].endswith("/studio/styles/images/JET-Favicon-Red-32x32.png?x=1")


def test_studio_nested_styles_path_redirects_to_canonical_static_root():
    app = _create_app()

    with app.test_client() as client:
        response = client.get("/studio/settings/styles/images/JET-Favicon-Red-32x32.png")

    assert response.status_code == 307
    assert response.headers["Location"].endswith("/studio/styles/images/JET-Favicon-Red-32x32.png")


def test_canonical_studio_styles_path_does_not_redirect():
    app = _create_app()

    with app.test_client() as client:
        response = client.get("/studio/styles/images/JET-Favicon-Red-32x32.png")

    assert response.status_code == 200


def test_authenticated_request_refreshes_expiry_for_24_hours():
    app = _create_app()
    now = int(time.time())

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = "admin"
            sess["token"] = "token"
            sess["token_expiry_ts"] = now + 10

        response = client.get("/studio/dashboard")

        assert response.status_code == 200

        with client.session_transaction() as sess:
            refreshed_expiry = sess["token_expiry_ts"]
            assert sess.permanent is True

    assert refreshed_expiry >= now + SESSION_TIMEOUT_SECONDS - 5
    assert refreshed_expiry <= now + SESSION_TIMEOUT_SECONDS + 5


def test_authenticated_request_keeps_non_persistent_session_non_persistent():
    app = _create_app()
    now = int(time.time())

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = "admin"
            sess["token"] = "token"
            sess["token_expiry_ts"] = now + 10
            sess["remember_me"] = False
            sess.permanent = False

        response = client.get("/studio/dashboard")

        assert response.status_code == 200

        with client.session_transaction() as sess:
            refreshed_expiry = sess["token_expiry_ts"]
            assert sess.permanent is False
            assert sess["remember_me"] is False

    assert refreshed_expiry >= now + SESSION_TIMEOUT_SECONDS - 5
    assert refreshed_expiry <= now + SESSION_TIMEOUT_SECONDS + 5


def test_expired_api_request_returns_unauthorized():
    app = _create_app()
    now = int(time.time())

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = "admin"
            sess["token"] = "token"
            sess["token_expiry_ts"] = now - 1

        response = client.get("/studio/api/v1/protected")

    assert response.status_code == 401
    assert response.get_json() == {"error": "Unauthorized", "message": "ログインしてください"}
