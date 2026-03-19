from flask import Flask
import denpyo_toroku.app.blueprints.api.api_blueprint as api_blueprint_module

from denpyo_toroku.app.blueprints.api import api_blueprint as api_bp
from denpyo_toroku.app.services.ai_service import AIRateLimitError


def _create_client():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(api_bp.api_blueprint, url_prefix="")
    return app.test_client()


def test_analyze_category_slips_uses_slips_category_records_and_status_methods(monkeypatch):
    client = _create_client()
    calls = {
        "get_files_by_ids": 0,
        "get_slips_category_file_by_object_name": [],
        "update_category_file_status": [],
        "save_category_analysis_result": [],
        "save_analysis_result": [],
        "update_file_status": [],
        "ocr_log_contexts": [],
        "schema_log_contexts": [],
    }

    class StubDatabaseService:
        def __init__(self):
            pass

        def get_files_by_ids(self, ids):
            calls["get_files_by_ids"] += 1
            return [
                {
                    "id": 1,
                    "object_name": "denpyo-category/sample-101.png",
                    "object_storage_path": "denpyo-category/sample-101.png",
                    "file_name": "sample-101.png",
                    "original_file_name": "sample-101.png",
                    "status": "UPLOADED",
                }
            ]

        def get_slips_category_file_by_object_name(self, object_name):
            calls["get_slips_category_file_by_object_name"].append(object_name)
            return {
                "id": 101,
                "object_name": object_name,
                "file_name": "sample-101.png",
                "original_file_name": "sample-101.png",
                "status": "UPLOADED",
            }

        def update_category_file_status(self, file_id, status):
            calls["update_category_file_status"].append((file_id, status))
            return True

        def save_category_analysis_result(self, file_id, result):
            calls["save_category_analysis_result"].append((file_id, result))
            return True

        def save_analysis_result(self, file_id, analysis_kind, result):
            calls["save_analysis_result"].append((file_id, analysis_kind, result))
            return True

        def update_file_status(self, file_id, status):
            calls["update_file_status"].append((file_id, status))
            return True

        def log_activity(self, **kwargs):
            return None

    class StubStorageService:
        def download_file(self, object_name):
            return b"fake-image-bytes"

    class StubDocumentProcessor:
        def prepare_for_ai(self, file_data, file_name):
            return [(b"image-bytes", "image/png")]

    class StubAIService:
        def extract_text_from_images(self, paths, log_context=None):
            calls["ocr_log_contexts"].append(log_context)
            return {"success": True, "extracted_text": "OCR text"}

        def generate_sql_schema_from_text(self, extracted_text, analysis_mode, log_context=None):
            calls["schema_log_contexts"].append(log_context)
            return {
                "success": True,
                "document_type_ja": "請求書",
                "document_type_en": "invoice",
                "header_fields": [
                    {
                        "field_name": "請求番号",
                        "field_name_en": "invoice_no",
                        "data_type": "VARCHAR2",
                        "max_length": 50,
                        "is_required": True,
                    }
                ],
                "line_fields": [],
            }

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)
    monkeypatch.setattr(
        "denpyo_toroku.app.services.oci_storage_service.OCIStorageService",
        StubStorageService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.document_processor.DocumentProcessor",
        StubDocumentProcessor,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.ai_service.AIService",
        StubAIService,
    )

    response = client.post(
        "/api/v1/categories/analyze-slips",
        json={"file_ids": [1], "analysis_mode": "header_only"},
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()["data"]
    assert calls["ocr_log_contexts"][0]["file_ids"] == [1]
    assert calls["ocr_log_contexts"][0]["analysis_mode"] == "header_only"
    assert calls["ocr_log_contexts"][0]["request_id"].startswith("req-")
    assert calls["schema_log_contexts"][0] == calls["ocr_log_contexts"][0]
    assert response.headers["X-Request-ID"] == calls["ocr_log_contexts"][0]["request_id"]
    assert payload["category_guess"] == "請求書"
    assert payload["category_guess_en"] == "invoice"
    assert calls["get_files_by_ids"] == 1
    assert calls["get_slips_category_file_by_object_name"] == ["denpyo-category/sample-101.png"]
    assert calls["update_file_status"] == [(1, "ANALYZING"), (1, "ANALYZED")]
    assert calls["update_category_file_status"] == [(101, "ANALYZING"), (101, "ANALYZED")]
    assert len(calls["save_category_analysis_result"]) == 1
    assert calls["save_category_analysis_result"][0][0] == 101
    assert len(calls["save_analysis_result"]) == 1
    assert calls["save_analysis_result"][0][0] == 1
    assert calls["save_analysis_result"][0][1] == "category"


def test_queue_category_slip_analysis_logs_structured_empty_ocr_failure(monkeypatch):
    calls = {
        "update_file_status": [],
        "update_category_file_status": [],
        "log_activity": [],
    }

    class StubDatabaseService:
        def __init__(self):
            pass

        def get_files_by_ids(self, ids):
            return [
                {
                    "id": 1,
                    "object_name": "denpyo-category/sample-101.png",
                    "object_storage_path": "denpyo-category/sample-101.png",
                    "file_name": "sample-101.png",
                    "original_file_name": "sample-101.png",
                    "status": "UPLOADED",
                }
            ]

        def get_slips_category_file_by_object_name(self, object_name):
            return {
                "id": 101,
                "object_name": object_name,
                "file_name": "sample-101.png",
                "original_file_name": "sample-101.png",
                "status": "UPLOADED",
            }

        def update_category_file_status(self, file_id, status):
            calls["update_category_file_status"].append((file_id, status))
            return True

        def update_file_status(self, file_id, status):
            calls["update_file_status"].append((file_id, status))
            return True

        def log_activity(self, **kwargs):
            calls["log_activity"].append(kwargs)
            return None

    class StubStorageService:
        def download_file(self, object_name):
            return b"fake-image-bytes"

    class StubDocumentProcessor:
        def prepare_for_ai(self, file_data, file_name):
            return [(b"image-bytes", "image/png")]

    class StubAIService:
        def extract_text_from_images(self, paths, log_context=None):
            return {
                "success": False,
                "message": (
                    "テキスト抽出失敗: "
                    "VLMによるテキスト抽出結果が空でした "
                    "(page=1, variant=original, attempts=5, rotation=180, "
                    "rotation_attempts=4, primary_empty_response_attempts=2, "
                    "secondary_empty_response_attempts=1)"
                ),
            }

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)
    monkeypatch.setattr(
        "denpyo_toroku.app.services.oci_storage_service.OCIStorageService",
        StubStorageService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.document_processor.DocumentProcessor",
        StubDocumentProcessor,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.ai_service.AIService",
        StubAIService,
    )

    api_blueprint_module._queue_category_slip_analysis([1], "header_only", "admin")

    assert calls["update_file_status"] == [(1, "ERROR")]
    assert calls["update_category_file_status"] == [(101, "ERROR")]
    error_logs = [
        kwargs for kwargs in calls["log_activity"]
        if kwargs["activity_type"] == "CATEGORY_ANALYZE_ERROR"
    ]
    assert len(error_logs) == 1
    description = error_logs[0]["description"]
    assert "OCR空応答が最終的に解消されませんでした" in description
    assert "page=1" in description
    assert "variant=original" in description
    assert "rotation=180" in description
    assert "rotation_attempts=4" in description
    assert "primary_attempts=2" in description
    assert "secondary_attempts=1" in description
    assert "total_attempts=5" in description
    assert "[request_id=bg-category-analyze-" in description


def test_fetch_category_analysis_result_reads_from_slips_category_via_denpyo_file_mapping(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def __init__(self):
            pass

        def get_file_by_id(self, file_id):
            return {
                "id": file_id,
                "status": "ANALYZED",
                "file_name": "denpyo-category/sample-101.png",
                "original_file_name": "sample-101.png",
                "object_storage_path": "denpyo-category/sample-101.png",
                "has_analysis_result": False,
            }

        def get_analysis_result(self, file_id):
            return None

        def get_slips_category_file_by_object_name(self, object_name):
            return {
                "id": 101,
                "status": "ANALYZED",
                "file_name": "sample-101.png",
                "object_name": object_name,
                "has_analysis_result": True,
            }

        def get_slips_category_analysis_result_by_object_name(self, object_name):
            return {
                "analysis_kind": "category",
                "result": {
                    "category_guess": "請求書",
                    "category_guess_en": "invoice",
                    "analysis_mode": "header_only",
                    "header_columns": [],
                    "line_columns": [],
                    "analyzed_file_ids": [1],
                },
                "analyzed_at": "2026-03-07T08:00:00",
            }

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)

    response = client.get("/api/v1/files/1/analysis-result")

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()["data"]
    assert payload["analysis_kind"] == "category"
    assert payload["result"]["category_guess_en"] == "invoice"


def test_fetch_category_analysis_result_reads_from_slips_category_when_file_not_in_denpyo_files(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def __init__(self):
            pass

        def get_file_by_id(self, file_id):
            return None

        def get_file_by_object_storage_path(self, object_storage_path):
            return None

        def get_slips_category_files_by_ids(self, ids):
            return [
                {
                    "id": 101,
                    "status": "ANALYZED",
                    "file_name": "sample-101.png",
                    "object_name": "denpyo-category/sample-101.png",
                }
            ]

        def get_slips_category_analysis_result(self, file_id):
            return {
                "analysis_kind": "category",
                "result": {
                    "category_guess": "請求書",
                    "category_guess_en": "invoice",
                    "analysis_mode": "header_only",
                    "header_columns": [],
                    "line_columns": [],
                    "analyzed_file_ids": [101],
                },
                "analyzed_at": "2026-03-07T08:00:00",
            }

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)

    response = client.get("/api/v1/files/101/analysis-result")

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()["data"]
    assert payload["analysis_kind"] == "category"
    assert payload["result"]["category_guess_en"] == "invoice"


def test_fetch_category_analysis_result_returns_409_for_analyzing_slips_category_file(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def __init__(self):
            pass

        def get_file_by_id(self, file_id):
            return None

        def get_file_by_object_storage_path(self, object_storage_path):
            return None

        def get_slips_category_files_by_ids(self, ids):
            return [
                {
                    "id": 101,
                    "status": "ANALYZING",
                    "file_name": "sample-101.png",
                    "object_name": "denpyo-category/sample-101.png",
                }
            ]

        def get_slips_category_analysis_result(self, file_id):
            return None

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)

    response = client.get("/api/v1/files/101/analysis-result")

    assert response.status_code == 409
    assert response.get_json()["errorMessages"][0] == "AI分析はまだ完了していません"


def test_fetch_category_analysis_result_returns_retry_message_for_stalled_slips_category_file(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def __init__(self):
            pass

        def get_file_by_id(self, file_id):
            return None

        def get_file_by_object_storage_path(self, object_storage_path):
            return None

        def get_slips_category_files_by_ids(self, ids):
            return [
                {
                    "id": 101,
                    "status": "ANALYZING",
                    "file_name": "sample-101.png",
                    "object_name": "denpyo-category/sample-101.png",
                    "updated_at": "2026-03-01 08:00:00",
                    "has_analysis_result": False,
                }
            ]

        def get_slips_category_analysis_result(self, file_id):
            return None

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)

    response = client.get("/api/v1/files/101/analysis-result")

    assert response.status_code == 409
    assert response.get_json()["errorMessages"][0] == "AI分析が長時間完了していません。再分析してください"


def test_build_category_analysis_result_payload_merges_sample_values_and_uses_first_line_row_only():
    class StubAIService:
        def extract_data_from_text(self, ocr_text, category, table_schema, log_context=None):
            return {
                "success": True,
                "header_fields": [
                    {"field_name_en": "INVOICE_NO", "value": "INV-001"},
                    {"field_name_en": "TOTAL_AMOUNT", "value": "12345"},
                ],
                "line_fields": [
                    {"field_name_en": "ITEM_NAME", "value": "fallback-item"},
                    {"field_name_en": "QUANTITY", "value": "99"},
                ],
                "raw_lines": [
                    {"ITEM_NAME": "商品A", "QUANTITY": "2"},
                    {"ITEM_NAME": "商品B", "QUANTITY": "4"},
                ],
                "line_count": 2,
            }

    result = api_blueprint_module._build_category_analysis_result_payload(
        ai_service=StubAIService(),
        schema_result={
            "document_type_ja": "請求書",
            "document_type_en": "invoice",
            "header_fields": [
                {
                    "field_name": "請求番号",
                    "field_name_en": "INVOICE_NO",
                    "data_type": "VARCHAR2",
                    "max_length": 50,
                    "is_required": True,
                },
                {
                    "field_name": "合計金額",
                    "field_name_en": "TOTAL_AMOUNT",
                    "data_type": "NUMBER",
                    "is_required": False,
                },
            ],
            "line_fields": [
                {
                    "field_name": "品名",
                    "field_name_en": "ITEM_NAME",
                    "data_type": "VARCHAR2",
                    "max_length": 100,
                    "is_required": True,
                },
                {
                    "field_name": "数量",
                    "field_name_en": "QUANTITY",
                    "data_type": "NUMBER",
                    "is_required": True,
                },
            ],
        },
        analysis_mode="header_line",
        processed_file_ids=[10, 10, 11],
        sample_ocr_text="[PAGE 1]\nOCR text",
        log_context={"request_id": "req-test"},
    )

    header_columns = {column["column_name"]: column for column in result["header_columns"]}
    line_columns = {column["column_name"]: column for column in result["line_columns"]}

    assert header_columns["INVOICE_NO"]["sample_data"] == "INV-001"
    assert header_columns["TOTAL_AMOUNT"]["sample_data"] == "12345"
    assert line_columns["ITEM_NAME"]["sample_data"] == "商品A"
    assert line_columns["QUANTITY"]["sample_data"] == "2"
    assert result["analyzed_file_ids"] == [10, 11]


def test_build_category_analysis_result_payload_skips_sample_values_when_auxiliary_extraction_is_rate_limited():
    class StubAIService:
        def extract_data_from_text(self, ocr_text, category, table_schema, log_context=None):
            raise AIRateLimitError("extract_data_from_text", 8.0, Exception("rate limited"))

    result = api_blueprint_module._build_category_analysis_result_payload(
        ai_service=StubAIService(),
        schema_result={
            "document_type_ja": "請求書",
            "document_type_en": "invoice",
            "header_fields": [
                {
                    "field_name": "請求番号",
                    "field_name_en": "INVOICE_NO",
                    "data_type": "VARCHAR2",
                    "max_length": 50,
                    "is_required": True,
                }
            ],
            "line_fields": [],
        },
        analysis_mode="header_only",
        processed_file_ids=[1],
        sample_ocr_text="[PAGE 1]\nOCR text",
        log_context={"request_id": "req-test"},
    )

    assert result["category_guess"] == "請求書"
    assert result["header_columns"][0]["column_name"] == "INVOICE_NO"
    assert result["header_columns"][0]["sample_data"] == ""
