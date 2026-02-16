# @app.after_request

def setup_response_headers(app):
    def apply_response_headers(response):
        # 設定に基づいてレスポンスヘッダを適用
        for header, value in app.config.get("RESPONSE_HEADERS", {}).items():
            response.headers[header] = value
        return response

    app.after_request(apply_response_headers)
