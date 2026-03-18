from flask import Flask

import denpyo_toroku.app.blueprints.api.api_blueprint as api_blueprint_module
from denpyo_toroku.app.blueprints.api import api_blueprint as api_bp


def _create_client():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(api_bp.api_blueprint, url_prefix="")
    return app.test_client()


def test_natural_language_search_rejects_invalid_category_id(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def get_allowed_table_names(self):
            return [
                {
                    "category_id": 1,
                    "category_name": "領収書",
                    "header_table_name": "RECEIPT_H",
                    "line_table_name": "",
                }
            ]

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)

    response = client.post(
        "/api/v1/search/nl",
        json={"query": "領収書を検索", "category_id": "not-a-number"},
    )

    assert response.status_code == 400
    assert response.get_json()["errorMessages"][0] == "category_id は整数で指定してください"


def test_natural_language_search_requires_category_id():
    client = _create_client()

    response = client.post(
        "/api/v1/search/nl",
        json={"query": "領収書を検索"},
    )

    assert response.status_code == 400
    assert response.get_json()["errorMessages"][0] == "伝票分類を選択してください"


def test_natural_language_search_falls_back_to_direct_llm_when_select_ai_agent_fails(monkeypatch):
    client = _create_client()
    calls = {
        "run_select_ai_agent_search": 0,
        "get_table_columns": [],
        "text_to_sql": 0,
        "execute_select_query": 0,
    }

    class StubDatabaseService:
        def get_allowed_table_names(self):
            return [
                {
                    "category_id": 1,
                    "category_name": "領収書",
                    "header_table_name": "RECEIPT_H",
                    "line_table_name": "",
                }
            ]

        @staticmethod
        def _build_allowed_table_set_from_entries(table_entries):
            allowed = set()
            for entry in table_entries:
                if entry.get("header_table_name"):
                    allowed.add(entry["header_table_name"].upper())
                if entry.get("line_table_name"):
                    allowed.add(entry["line_table_name"].upper())
            return allowed

        def run_select_ai_agent_search(self, **kwargs):
            calls["run_select_ai_agent_search"] += 1
            return {
                "success": False,
                "message": 'ORA-00904: "TEAM_NAME": invalid identifier',
            }

        def get_table_columns(self, table_name):
            calls["get_table_columns"].append(table_name)
            return [
                {
                    "column_name": "HEADER_ID",
                    "data_type": "VARCHAR2",
                    "data_length": 32,
                    "nullable": "N",
                }
            ]

        def execute_select_query(self, sql, max_rows=500, allowed_tables=None):
            calls["execute_select_query"] += 1
            assert sql == "SELECT HEADER_ID FROM RECEIPT_H"
            assert max_rows == 500
            assert allowed_tables == {"RECEIPT_H"}
            return {
                "success": True,
                "columns": ["HEADER_ID"],
                "rows": [{"HEADER_ID": "RECEIPT-H-0001"}],
                "total": 1,
            }

    class StubAIService:
        def text_to_sql(self, query, table_schemas):
            calls["text_to_sql"] += 1
            assert query == "最新の領収書を1件表示"
            assert table_schemas == [
                {
                    "table_name": "RECEIPT_H",
                    "columns": [
                        {
                            "column_name": "HEADER_ID",
                            "data_type": "VARCHAR2",
                            "data_length": 32,
                            "nullable": "N",
                        }
                    ],
                }
            ]
            return {
                "success": True,
                "sql": "SELECT HEADER_ID FROM RECEIPT_H",
                "explanation": "direct llm fallback",
            }

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)
    monkeypatch.setattr(
        api_blueprint_module,
        "_load_oci_settings_snapshot",
        lambda: {"settings": {"select_ai_enabled": True}},
    )
    monkeypatch.setattr(
        api_blueprint_module,
        "_build_oci_test_config",
        lambda settings: {"region": "ap-osaka-1"},
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.ai_service.AIService",
        StubAIService,
    )

    response = client.post(
        "/api/v1/search/nl",
        json={"query": "最新の領収書を1件表示", "category_id": 1},
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()["data"]
    assert payload["engine"] == "direct_llm"
    assert payload["generated_sql"] == "SELECT HEADER_ID FROM RECEIPT_H"
    assert payload["results"]["rows"] == [{"HEADER_ID": "RECEIPT-H-0001"}]
    assert calls["run_select_ai_agent_search"] == 1
    assert calls["get_table_columns"] == ["RECEIPT_H"]
    assert calls["text_to_sql"] == 1
    assert calls["execute_select_query"] == 1


def test_natural_language_search_falls_back_to_direct_llm_on_select_ai_endpoint_error(monkeypatch):
    client = _create_client()
    calls = {
        "run_select_ai_agent_search": 0,
        "text_to_sql": 0,
    }

    class StubDatabaseService:
        def get_allowed_table_names(self):
            return [
                {
                    "category_id": 1,
                    "category_name": "領収書",
                    "header_table_name": "RECEIPT_H",
                    "line_table_name": "",
                }
            ]

        @staticmethod
        def _build_allowed_table_set_from_entries(table_entries):
            return {"RECEIPT_H"}

        def run_select_ai_agent_search(self, **kwargs):
            calls["run_select_ai_agent_search"] += 1
            return {
                "success": False,
                "message": "ORA-20404: Object not found - https://inference.generativeai.ap-osaka-1.oci.my$cloud_domain/20231130/actions/chat",
                "fallback_to_direct_llm": True,
            }

        def get_table_columns(self, table_name):
            return [
                {
                    "column_name": "HEADER_ID",
                    "data_type": "VARCHAR2",
                    "data_length": 32,
                    "nullable": "N",
                }
            ]

        def execute_select_query(self, sql, max_rows=500, allowed_tables=None):
            return {
                "success": True,
                "columns": ["HEADER_ID"],
                "rows": [{"HEADER_ID": "RECEIPT-H-0001"}],
                "total": 1,
            }

    class StubAIService:
        def text_to_sql(self, query, table_schemas):
            calls["text_to_sql"] += 1
            return {
                "success": True,
                "sql": "SELECT HEADER_ID FROM RECEIPT_H",
                "explanation": "direct llm fallback",
            }

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)
    monkeypatch.setattr(
        api_blueprint_module,
        "_load_oci_settings_snapshot",
        lambda: {"settings": {"select_ai_enabled": True}},
    )
    monkeypatch.setattr(
        api_blueprint_module,
        "_build_oci_test_config",
        lambda settings: {"region": "ap-osaka-1"},
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.ai_service.AIService",
        StubAIService,
    )

    response = client.post(
        "/api/v1/search/nl",
        json={"query": "最新の領収書を1件表示", "category_id": 1},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["engine"] == "direct_llm"
    assert calls["run_select_ai_agent_search"] == 1
    assert calls["text_to_sql"] == 1


def test_delete_table_browser_row_requires_table_name():
    client = _create_client()

    response = client.post(
        "/api/v1/search/table-browser/delete-row",
        json={"row_id": "AAABBB=="},
    )

    assert response.status_code == 400
    assert response.get_json()["errorMessages"][0] == "table_name を指定してください"


def test_table_browser_returns_json_error_when_response_payload_is_not_serializable(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def get_table_data(self, table_name, limit=50, offset=0):
            return {
                "success": True,
                "table_name": table_name,
                "columns": ["BAD_VALUE"],
                "rows": [{"ROW_ID_META": "AAABBB==", "BAD_VALUE": object()}],
                "total": 1,
            }

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)

    response = client.get("/api/v1/search/table-browser/data?table_name=SLIPS_CATEGORY")

    assert response.status_code == 500
    payload = response.get_json()
    assert "data" not in payload
    assert "データ取得に失敗しました" in payload["errorMessages"][0]


def test_delete_table_browser_row_requires_row_id():
    client = _create_client()

    response = client.post(
        "/api/v1/search/table-browser/delete-row",
        json={"table_name": "SLIPS_RAW"},
    )

    assert response.status_code == 400
    assert response.get_json()["errorMessages"][0] == "row_id を指定してください"


def test_delete_table_browser_row_returns_success_payload(monkeypatch):
    client = _create_client()
    calls = []

    class StubDatabaseService:
        def delete_table_row_by_rowid(self, table_name, row_id):
            calls.append((table_name, row_id))
            return {"success": True, "deleted": 1}

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)

    response = client.post(
        "/api/v1/search/table-browser/delete-row",
        json={"table_name": "SLIPS_RAW", "row_id": "AAABBB=="},
    )

    assert response.status_code == 200, response.get_json()
    assert calls == [("SLIPS_RAW", "AAABBB==")]
    assert response.get_json()["data"] == {"success": True, "deleted": 1}


def test_delete_table_browser_row_returns_service_validation_error(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def delete_table_row_by_rowid(self, table_name, row_id):
            assert table_name == "SLIPS_RAW"
            assert row_id == "bad-rowid"
            return {"success": False, "message": "不正な row_id 形式です"}

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)

    response = client.post(
        "/api/v1/search/table-browser/delete-row",
        json={"table_name": "SLIPS_RAW", "row_id": "bad-rowid"},
    )

    assert response.status_code == 400
    assert response.get_json()["errorMessages"][0] == "不正な row_id 形式です"


def test_delete_table_browser_row_returns_500_on_unexpected_error(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def delete_table_row_by_rowid(self, table_name, row_id):
            raise RuntimeError("db down")

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)

    response = client.post(
        "/api/v1/search/table-browser/delete-row",
        json={"table_name": "SLIPS_RAW", "row_id": "AAABBB=="},
    )

    assert response.status_code == 500
    assert response.get_json()["errorMessages"][0] == "削除に失敗しました: db down"
