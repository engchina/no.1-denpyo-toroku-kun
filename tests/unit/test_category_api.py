from flask import Flask

from denpyo_toroku.app.blueprints.api import api_blueprint as api_bp


def _create_client():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(api_bp.api_blueprint, url_prefix="")
    return app.test_client()


def test_create_category_requires_english_name():
    client = _create_client()

    response = client.post(
        "/api/v1/categories",
        json={
            "category_name": "領収書",
            "category_name_en": "",
            "header_table_name": "RECEIPT_H",
            "header_columns": [
                {
                    "column_name": "TENPOU_MEI",
                    "column_name_jp": "店舗名",
                    "data_type": "VARCHAR2",
                    "max_length": 100,
                    "is_nullable": True,
                    "is_primary_key": False,
                }
            ],
        },
    )

    assert response.status_code == 400
    assert response.get_json()["errorMessages"][0] == "伝票分類名（英語）は必須です"


def test_create_category_requires_japanese_column_name():
    client = _create_client()

    response = client.post(
        "/api/v1/categories",
        json={
            "category_name": "領収書",
            "category_name_en": "receipt",
            "header_table_name": "RECEIPT_H",
            "header_columns": [
                {
                    "column_name": "TENPOU_MEI",
                    "column_name_jp": "",
                    "data_type": "VARCHAR2",
                    "max_length": 100,
                    "is_nullable": True,
                    "is_primary_key": False,
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "日本語名は必須" in response.get_json()["errorMessages"][0]


def test_create_category_rejects_header_only_system_column():
    client = _create_client()

    response = client.post(
        "/api/v1/categories",
        json={
            "category_name": "領収書",
            "category_name_en": "receipt",
            "header_table_name": "RECEIPT_H",
            "header_columns": [
                {
                    "column_name": "HEADER_ID",
                    "column_name_jp": "ヘッダーID",
                    "data_type": "VARCHAR2",
                    "max_length": 32,
                    "is_nullable": False,
                    "is_primary_key": True,
                }
            ],
        },
    )

    assert response.status_code == 400
    assert response.get_json()["errorMessages"][0] == "ヘッダーテーブルに HEADER_ID 以外のカラムを1つ以上定義してください"


def test_create_category_rejects_legacy_id_column_name():
    client = _create_client()

    response = client.post(
        "/api/v1/categories",
        json={
            "category_name": "領収書",
            "category_name_en": "receipt",
            "header_table_name": "RECEIPT_H",
            "header_columns": [
                {
                    "column_name": "ID",
                    "column_name_jp": "ID",
                    "data_type": "VARCHAR2",
                    "max_length": 32,
                    "is_nullable": False,
                    "is_primary_key": True,
                },
                {
                    "column_name": "TENPOU_MEI",
                    "column_name_jp": "店舗名",
                    "data_type": "VARCHAR2",
                    "max_length": 100,
                    "is_nullable": True,
                    "is_primary_key": False,
                },
            ],
        },
    )

    assert response.status_code == 400
    assert response.get_json()["errorMessages"][0] == (
        "ヘッダーカラム定義エラー: カラム名 'ID' は使用できません。ヘッダーは HEADER_ID、明細は LINE_ID / HEADER_ID を使用してください"
    )


def test_create_category_rejects_line_only_system_columns():
    client = _create_client()

    response = client.post(
        "/api/v1/categories",
        json={
            "category_name": "領収書",
            "category_name_en": "receipt",
            "header_table_name": "RECEIPT_H",
            "header_columns": [
                {
                    "column_name": "TENPOU_MEI",
                    "column_name_jp": "店舗名",
                    "data_type": "VARCHAR2",
                    "max_length": 100,
                    "is_nullable": True,
                    "is_primary_key": False,
                }
            ],
            "line_table_name": "RECEIPT_L",
            "line_columns": [
                {
                    "column_name": "LINE_ID",
                    "column_name_jp": "明細ID",
                    "data_type": "VARCHAR2",
                    "max_length": 32,
                    "is_nullable": False,
                    "is_primary_key": True,
                },
                {
                    "column_name": "HEADER_ID",
                    "column_name_jp": "ヘッダーID",
                    "data_type": "VARCHAR2",
                    "max_length": 32,
                    "is_nullable": False,
                    "is_primary_key": False,
                },
            ],
        },
    )

    assert response.status_code == 400
    assert response.get_json()["errorMessages"][0] == "明細テーブルに LINE_ID / HEADER_ID 以外のカラムを1つ以上定義してください"


def test_create_category_rejects_line_id_in_header_columns():
    client = _create_client()

    response = client.post(
        "/api/v1/categories",
        json={
            "category_name": "領収書",
            "category_name_en": "receipt",
            "header_table_name": "RECEIPT_H",
            "header_columns": [
                {
                    "column_name": "HEADER_ID",
                    "column_name_jp": "ヘッダーID",
                    "data_type": "VARCHAR2",
                    "max_length": 32,
                    "is_nullable": False,
                    "is_primary_key": True,
                },
                {
                    "column_name": "LINE_ID",
                    "column_name_jp": "明細ID",
                    "data_type": "VARCHAR2",
                    "max_length": 32,
                    "is_nullable": False,
                    "is_primary_key": False,
                },
            ],
        },
    )

    assert response.status_code == 400
    assert response.get_json()["errorMessages"][0] == "ヘッダーカラム定義エラー: カラム名 'LINE_ID' はこのテーブルでは使用できません"


def test_update_category_returns_conflict_when_names_are_duplicated(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def get_category_by_id(self, category_id):
            return {
                "id": category_id,
                "category_name": "領収書",
                "category_name_en": "receipt",
                "header_table_name": "RECEIPT_H",
                "line_table_name": "",
            }

        def find_category_conflicts(self, **kwargs):
            return ["伝票分類名（英語） 'invoice' は既に使用されています"]

    monkeypatch.setattr(api_bp, "DatabaseService", StubDatabaseService)

    response = client.put(
        "/api/v1/categories/1",
        json={
            "category_name": "請求書",
            "category_name_en": "invoice",
            "description": "仕入先請求書",
        },
    )

    assert response.status_code == 409
    assert response.get_json()["errorMessages"][0] == "伝票分類名（英語） 'invoice' は既に使用されています"


def test_create_category_select_ai_profile_returns_success(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def get_category_by_id(self, category_id):
            return {
                "id": category_id,
                "category_name": "領収書",
                "header_table_name": "RECEIPT_H",
                "line_table_name": "",
            }

        def create_select_ai_profile_for_category(self, **kwargs):
            assert kwargs["category_id"] == 1
            assert kwargs["oci_auth_config"] == {"region": "ap-osaka-1"}
            assert kwargs["model_settings"] == {"llm_model_id": "cohere.command-r"}
            return {
                "success": True,
                "category_id": 1,
                "category_name": "領収書",
                "profile_name": "DTAIPR_TEST000001",
                "team_name": "DTAITM_TEST000001",
                "config_hash": "ABC123",
            }

    monkeypatch.setattr(api_bp, "DatabaseService", StubDatabaseService)
    monkeypatch.setattr(
        api_bp,
        "_load_oci_settings_snapshot",
        lambda: {"settings": {"llm_model_id": "cohere.command-r"}},
    )
    monkeypatch.setattr(
        api_bp,
        "_build_oci_test_config",
        lambda settings: {"region": "ap-osaka-1"},
    )

    response = client.post("/api/v1/categories/1/select-ai-profile", json={})

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["profile_name"] == "DTAIPR_TEST000001"


def test_create_category_select_ai_profile_returns_404_for_missing_category(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def get_category_by_id(self, category_id):
            return None

    monkeypatch.setattr(api_bp, "DatabaseService", StubDatabaseService)

    response = client.post("/api/v1/categories/999/select-ai-profile", json={})

    assert response.status_code == 404
    assert response.get_json()["errorMessages"][0] == "カテゴリが見つかりません"


def test_delete_category_returns_success_for_missing_physical_table_inconsistency(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def get_category_by_id(self, category_id):
            return {
                "id": category_id,
                "category_name": "歯科検診問診票",
                "header_table_name": "DENTAL_CHECKUP_QUESTIONNAIRE_H",
                "line_table_name": "",
            }

        def delete_category(self, category_id):
            return {
                "success": True,
                "message": "カテゴリを削除しました",
                "category_name": "歯科検診問診票",
                "dropped_tables": [],
            }

    monkeypatch.setattr(api_bp, "DatabaseService", StubDatabaseService)

    response = client.delete("/api/v1/categories/1")

    assert response.status_code == 200
    assert response.get_json()["data"]["success"] is True
    assert response.get_json()["data"]["message"] == "カテゴリを削除しました"


def test_delete_category_returns_success_when_category_is_already_missing(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def delete_category(self, category_id):
            return {
                "success": True,
                "message": "カテゴリは既に削除されています",
                "category_name": "",
                "dropped_tables": [],
                "already_missing": True,
            }

    monkeypatch.setattr(api_bp, "DatabaseService", StubDatabaseService)

    response = client.delete("/api/v1/categories/1")

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "success": True,
        "message": "カテゴリは既に削除されています",
        "already_missing": True,
    }
