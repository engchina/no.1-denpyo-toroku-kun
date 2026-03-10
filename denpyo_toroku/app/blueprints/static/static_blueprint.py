import os
from flask import Blueprint, abort, send_from_directory

denpyo_toroku_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 参照アーキテクチャ: ui/web/ の Webpack ビルド成果物を配信する
static_blueprint = Blueprint("static_blueprint", __name__)

web_dir = os.path.join(denpyo_toroku_base, "ui", "web")
vendor_dir = os.path.join(denpyo_toroku_base, "vendor")


@static_blueprint.route("/")
def home():
    """Oracle JET 18 VDOM アプリのメインページを配信する。"""
    return send_from_directory(web_dir, "index.html")


@static_blueprint.route("/login")
def login():
    """ログイン入口ページを配信する（ERP 互換パス）。"""
    return send_from_directory(web_dir, "index.html")


@static_blueprint.route("/js/<path:path>")
def send_js(path):
    """バンドル済み JavaScript を配信する。"""
    web_js_dir = os.path.join(web_dir, "js")
    if os.path.isfile(os.path.join(web_js_dir, path)):
        return send_from_directory(web_js_dir, path)
    # denpyo_toroku/js へフォールバック（レガシー資産）
    return send_from_directory(os.path.join(denpyo_toroku_base, "js"), path)


@static_blueprint.route("/styles/<path:path>")
def send_styles(path):
    """CSS/スタイルファイルを配信する。"""
    return send_from_directory(os.path.join(web_dir, "styles"), path)


@static_blueprint.route("/vendor/<path:path>")
def send_vendor(path):
    """vendor ファイルを配信する（ローカル CDN 代替）。"""
    # まず webpack ビルド出力の vendor ディレクトリを確認
    web_vendor = os.path.join(web_dir, "vendor")
    if os.path.isfile(os.path.join(web_vendor, path)):
        return send_from_directory(web_vendor, path)
    # denpyo_toroku/vendor へフォールバック（レガシー資産）
    return send_from_directory(vendor_dir, path)


@static_blueprint.route("/css/<path:path>")
def send_css(path):
    """CSS ファイルを配信する（レガシーパス対応）。"""
    css_dir = os.path.join(web_dir, "css")
    if os.path.isdir(css_dir):
        return send_from_directory(css_dir, path)
    return send_from_directory(os.path.join(denpyo_toroku_base, "css"), path)


@static_blueprint.route("/<path:path>")
def send_files(path):
    """ui/web/ 配下のその他静的ファイルを配信する。"""
    file_path = os.path.join(web_dir, path)
    if os.path.isfile(file_path):
        return send_from_directory(web_dir, path)

    # API 風パスは SPA フォールバック対象外（404 を返す）
    if path.startswith("api/"):
        return abort(404)

    return send_from_directory(web_dir, "index.html")
