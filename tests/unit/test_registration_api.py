from flask import Flask

from denpyo_toroku.app.blueprints.api import api_blueprint as api_bp


def _create_client():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(api_bp.api_blueprint, url_prefix="")
    return app.test_client()


def test_register_file_returns_error_when_insert_fails(monkeypatch):
    client = _create_client()
    calls = {
        "insert_registration": 0,
        "update_file_status": 0,
        "log_activity": 0,
    }

    class StubDatabaseService:
        def get_file_by_id(self, file_id):
            return {"id": file_id, "status": "ANALYZED"}

        def get_category_by_id(self, category_id):
            return {
                "id": category_id,
                "header_table_name": "RECEIPT_H_2",
                "line_table_name": "",
            }

        def insert_extracted_data(self, **kwargs):
            return {
                "success": False,
                "header_inserted": 0,
                "line_inserted": 0,
                "message": "ヘッダーINSERTエラー: ORA-00942: table or view does not exist",
            }

        def insert_registration(self, **kwargs):
            calls["insert_registration"] += 1
            return 99

        def update_file_status(self, file_id, status):
            calls["update_file_status"] += 1
            return True

        def log_activity(self, **kwargs):
            calls["log_activity"] += 1

    monkeypatch.setattr(api_bp, "DatabaseService", StubDatabaseService)

    response = client.post(
        "/api/v1/files/12/register",
        json={
            "category_id": 3,
            "category_name": "領収書_2",
            "category_name_en": "receipt_2",
            "header_table_name": "RECEIPT_H_2",
            "line_table_name": "",
            "header_fields": [{"field_name_en": "TENPOU_MEI", "value": "経堂駅前店"}],
            "raw_lines": [],
            "ai_confidence": 1.0,
            "line_count": 0,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["data"]["success"] is False
    assert "ヘッダーINSERTエラー" in response.get_json()["data"]["message"]
    assert calls["insert_registration"] == 0
    assert calls["update_file_status"] == 0
    assert calls["log_activity"] == 0


def test_register_file_returns_error_when_zero_header_rows_are_written(monkeypatch):
    client = _create_client()
    calls = {
        "insert_registration": 0,
        "update_file_status": 0,
    }

    class StubDatabaseService:
        def get_file_by_id(self, file_id):
            return {"id": file_id, "status": "ANALYZED"}

        def get_category_by_id(self, category_id):
            return {
                "id": category_id,
                "header_table_name": "RECEIPT_H_2",
                "line_table_name": "",
            }

        def insert_extracted_data(self, **kwargs):
            return {
                "success": True,
                "header_inserted": 0,
                "line_inserted": 0,
                "message": "登録対象データがありませんでした",
            }

        def insert_registration(self, **kwargs):
            calls["insert_registration"] += 1
            return 100

        def update_file_status(self, file_id, status):
            calls["update_file_status"] += 1
            return True

        def log_activity(self, **kwargs):
            return None

    monkeypatch.setattr(api_bp, "DatabaseService", StubDatabaseService)

    response = client.post(
        "/api/v1/files/12/register",
        json={
            "category_id": 3,
            "category_name": "領収書_2",
            "category_name_en": "receipt_2",
            "header_table_name": "RECEIPT_H_2",
            "line_table_name": "",
            "header_fields": [{"field_name_en": "TENPOU_MEI", "value": "経堂駅前店"}],
            "raw_lines": [],
            "ai_confidence": 1.0,
            "line_count": 0,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["data"]["success"] is False
    assert calls["insert_registration"] == 0
    assert calls["update_file_status"] == 0


def test_register_file_passes_category_id_to_insert_registration(monkeypatch):
    client = _create_client()
    captured = {}

    class StubDatabaseService:
        def get_file_by_id(self, file_id):
            return {"id": file_id, "status": "ANALYZED"}

        def get_category_by_id(self, category_id):
            return {
                "id": category_id,
                "header_table_name": "RECEIPT_H_5",
                "line_table_name": "RECEIPT_L_5",
            }

        def insert_extracted_data(self, **kwargs):
            return {
                "success": True,
                "header_inserted": 1,
                "line_inserted": 2,
                "message": "ok",
            }

        def insert_registration(self, **kwargs):
            captured.update(kwargs)
            return 101

        def update_file_status(self, file_id, status):
            return True

        def log_activity(self, **kwargs):
            return None

    monkeypatch.setattr(api_bp, "DatabaseService", StubDatabaseService)

    response = client.post(
        "/api/v1/files/12/register",
        json={
            "category_id": 5,
            "category_name": "領収証_5",
            "category_name_en": "receipt_5",
            "header_table_name": "RECEIPT_H_5",
            "line_table_name": "RECEIPT_L_5",
            "header_fields": [{"field_name_en": "TENPOU_MEI", "value": "経堂駅前店"}],
            "raw_lines": [{"SHOUHIN_MEI": "コーヒー"}, {"SHOUHIN_MEI": "サンドイッチ"}],
            "ai_confidence": 0.98,
            "line_count": 2,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["success"] is True
    assert captured["category_id"] == 5
    assert captured["header_table"] == "RECEIPT_H_5"
    assert captured["line_table"] == "RECEIPT_L_5"
