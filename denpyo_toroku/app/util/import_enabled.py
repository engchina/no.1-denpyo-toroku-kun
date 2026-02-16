# モジュール登録
# key: モジュール名
# value: Python ファイルのパス

import_enabled = {
    "blueprints": {
        "api_blueprint": "denpyo_toroku.app.blueprints.api.api_blueprint",
        "static_blueprint": "denpyo_toroku.app.blueprints.static.static_blueprint",
    },
    "global_middlewares": {
        "setup_cors_middleware": "denpyo_toroku.app.middlewares.globals.cors",
        "setup_response_headers": "denpyo_toroku.app.middlewares.globals.setup_headers",
        "setup_auth_middleware": "denpyo_toroku.app.middlewares.globals.auth",
    },
    "error_handlers": {
        "setup_global_error_handler": "denpyo_toroku.app.error_handlers.global_error_handler.global_error_handler"
    }
}
