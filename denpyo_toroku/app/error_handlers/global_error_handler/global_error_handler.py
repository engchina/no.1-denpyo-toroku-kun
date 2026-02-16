import logging
import traceback
from flask import g, jsonify
from werkzeug.exceptions import HTTPException

from denpyo_toroku.config import AppConfig
from denpyo_toroku.app.util.response import Response


def handle_error(e):
    g.response = Response()

    # HTTPException（例: 404 NotFound）は元のステータスコードを保持
    if isinstance(e, HTTPException):
        code = e.code
    else:
        code = 500
        logging.error(traceback.format_exc())

    # デバッグモード
    debug_mode = AppConfig.DENPYO_TOROKU_DEBUG_MODE
    if debug_mode.lower() == "true":
        g.response.add_error_message(str(e))
        return jsonify(g.response.get_result()), code

    # 呼び出し元（UI/非 UI）に応じて返却メッセージを分岐
    if hasattr(g, "request_source"):
        if g.request_source == "Non-UI":
            g.response.add_error_message(str(e))
            return jsonify(g.response.get_result()), code

    # 既定: JSON エラーを返す
    if code == 404:
        g.response.add_error_message("要求されたリソースが見つかりません。")
    else:
        g.response.add_error_message("内部エラーが発生しました。")
        result = g.response.get_result()
        if "errorMessages" in result:
            for entry in result["errorMessages"]:
                logging.error(entry)
        return jsonify(result), code

    return jsonify(g.response.get_result()), code


def setup_global_error_handler(app):
    app.register_error_handler(Exception, handle_error)
