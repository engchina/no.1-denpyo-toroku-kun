from pathlib import Path

from flask import Flask

from denpyo_toroku.app.blueprints.static import static_blueprint as static_bp_module


def _create_app(tmp_path: Path) -> Flask:
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (web_dir / "js").mkdir()
    (web_dir / "js" / "app.js").write_text("console.log('ok')", encoding="utf-8")

    static_bp_module.web_dir = str(web_dir)
    static_bp_module.vendor_dir = str(tmp_path / "vendor")

    app = Flask(__name__)
    app.register_blueprint(static_bp_module.static_blueprint)
    return app


def test_spa_route_falls_back_to_index(tmp_path):
    app = _create_app(tmp_path)

    with app.test_client() as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"spa" in response.data


def test_unknown_api_like_path_does_not_fall_back_to_index(tmp_path):
    app = _create_app(tmp_path)

    with app.test_client() as client:
        response = client.get("/api/v1/unknown")

    assert response.status_code == 404


def test_missing_asset_keeps_404(tmp_path):
    app = _create_app(tmp_path)

    with app.test_client() as client:
        response = client.get("/styles/missing.css")

    assert response.status_code == 404


def test_non_api_route_with_api_prefix_text_still_falls_back_to_index(tmp_path):
    app = _create_app(tmp_path)

    with app.test_client() as client:
        response = client.get("/apiary")

    assert response.status_code == 200
    assert b"spa" in response.data
