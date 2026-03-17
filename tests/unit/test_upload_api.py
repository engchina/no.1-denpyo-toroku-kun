from io import BytesIO
import base64
import zipfile

from flask import Flask

import denpyo_toroku.app.blueprints.api.api_blueprint as api_blueprint_module
from denpyo_toroku.app.blueprints.api import api_blueprint as api_bp


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a6d8AAAAASUVORK5CYII="
)


def _create_client():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(api_bp.api_blueprint, url_prefix="")
    return app.test_client()


def _build_zip_file(entries):
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for name, data in entries.items():
            zip_file.writestr(name, data)
    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def test_upload_rolls_back_object_when_slip_insert_fails(monkeypatch):
    client = _create_client()
    calls = {"delete_file": 0, "deleted_object_name": ""}

    class StubStorageService:
        def __init__(self):
            self.is_configured = True
            self._bucket_name = "bucket-a"
            self._namespace = "namespace-a"

        def upload_file(self, **kwargs):
            return {"success": True}

        def delete_file(self, object_name):
            calls["delete_file"] += 1
            calls["deleted_object_name"] = object_name
            return {"success": True}

    class StubDatabaseService:
        def insert_slip_record(self, **kwargs):
            return None

        def insert_file_record(self, **kwargs):
            raise AssertionError("insert_file_record should not be called")

        def log_activity(self, **kwargs):
            raise AssertionError("log_activity should not be called")

    class StubDocumentProcessor:
        def __init__(self, max_size_mb=50):
            pass

        def validate_file(self, filename, file_data):
            return {"valid": True}

        def detect_content_type(self, filename, file_data):
            return "image/png"

        def generate_object_name(self, filename, prefix="denpyo-raw"):
            return f"{prefix}/generated.png"

    monkeypatch.setattr(
        "denpyo_toroku.app.services.oci_storage_service.OCIStorageService",
        StubStorageService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.document_processor.DocumentProcessor",
        StubDocumentProcessor,
    )

    response = client.post(
        "/api/v1/files/upload",
        data={
            "upload_kind": "raw",
            "files": (BytesIO(b"fake-png-data"), "sample.png"),
        },
        content_type="multipart/form-data",
    )

    payload = response.get_json()["data"]
    assert response.status_code == 200
    assert payload["success"] is False
    assert calls["delete_file"] == 1
    assert calls["deleted_object_name"] == "denpyo-raw/generated.png"
    assert any("SLIPS テーブル登録失敗" in err for err in payload["errors"])


def test_upload_rolls_back_object_when_file_record_insert_fails(monkeypatch):
    client = _create_client()
    calls = {"delete_file": 0, "delete_slip_record": []}

    class StubStorageService:
        def __init__(self):
            self.is_configured = True
            self._bucket_name = "bucket-a"
            self._namespace = "namespace-a"

        def upload_file(self, **kwargs):
            return {"success": True}

        def delete_file(self, object_name):
            calls["delete_file"] += 1
            return {"success": True}

    class StubDatabaseService:
        def insert_slip_record(self, **kwargs):
            return 123

        def insert_file_record(self, **kwargs):
            return None

        def delete_slip_record(self, slip_kind, slip_id):
            calls["delete_slip_record"].append((slip_kind, slip_id))
            return {"success": True}

        def log_activity(self, **kwargs):
            raise AssertionError("log_activity should not be called")

    class StubDocumentProcessor:
        def __init__(self, max_size_mb=50):
            pass

        def validate_file(self, filename, file_data):
            return {"valid": True}

        def detect_content_type(self, filename, file_data):
            return "image/png"

        def generate_object_name(self, filename, prefix="denpyo-raw"):
            return f"{prefix}/generated.png"

    monkeypatch.setattr(
        "denpyo_toroku.app.services.oci_storage_service.OCIStorageService",
        StubStorageService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.document_processor.DocumentProcessor",
        StubDocumentProcessor,
    )

    response = client.post(
        "/api/v1/files/upload",
        data={
            "upload_kind": "raw",
            "files": (BytesIO(b"fake-png-data"), "sample.png"),
        },
        content_type="multipart/form-data",
    )

    payload = response.get_json()["data"]
    assert response.status_code == 200
    assert payload["success"] is False
    assert calls["delete_file"] == 1
    assert calls["delete_slip_record"] == [("raw", 123)]
    assert any("データベース登録失敗" in err for err in payload["errors"])


def test_upload_zip_validates_members_and_uploads_archive_only(monkeypatch):
    client = _create_client()
    calls = {"upload_file": []}

    class StubStorageService:
        def __init__(self):
            self.is_configured = True
            self._bucket_name = "bucket-a"
            self._namespace = "namespace-a"

        def upload_file(self, **kwargs):
            calls["upload_file"].append(kwargs)
            return {"success": True}

        def delete_file(self, object_name):
            raise AssertionError("delete_file should not be called")

    class StubDatabaseService:
        def __init__(self):
            self._slip_id = 100
            self._file_id = 200

        def insert_slip_record(self, **kwargs):
            self._slip_id += 1
            return self._slip_id

        def insert_file_record(self, **kwargs):
            self._file_id += 1
            return self._file_id

        def log_activity(self, **kwargs):
            return None

    monkeypatch.setattr(
        "denpyo_toroku.app.services.oci_storage_service.OCIStorageService",
        StubStorageService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )

    zip_bytes = _build_zip_file({
        "invoice-1.jpg": b"\xff\xd8\xff\xe0fake-jpeg-data",
        "nested/invoice-2.png": b"\x89PNG\r\n\x1a\nfake-png-data",
    })

    response = client.post(
        "/api/v1/files/upload",
        data={
            "upload_kind": "raw",
            "files": (BytesIO(zip_bytes), "batch.zip"),
        },
        content_type="multipart/form-data",
    )

    payload = response.get_json()["data"]
    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["errors"] == []
    assert len(payload["uploaded_files"]) == 1
    assert len(calls["upload_file"]) == 1
    assert calls["upload_file"][0]["original_filename"] == "batch.zip"
    assert calls["upload_file"][0]["content_type"] == "application/zip"


def test_upload_zip_rejects_non_image_member_and_skips_upload(monkeypatch):
    client = _create_client()
    calls = {"upload_file": 0}

    class StubStorageService:
        def __init__(self):
            self.is_configured = True
            self._bucket_name = "bucket-a"
            self._namespace = "namespace-a"

        def upload_file(self, **kwargs):
            calls["upload_file"] += 1
            return {"success": True}

        def delete_file(self, object_name):
            raise AssertionError("delete_file should not be called")

    class StubDatabaseService:
        def insert_slip_record(self, **kwargs):
            raise AssertionError("insert_slip_record should not be called")

        def insert_file_record(self, **kwargs):
            raise AssertionError("insert_file_record should not be called")

        def log_activity(self, **kwargs):
            raise AssertionError("log_activity should not be called")

    monkeypatch.setattr(
        "denpyo_toroku.app.services.oci_storage_service.OCIStorageService",
        StubStorageService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )

    zip_bytes = _build_zip_file({
        "ok.png": b"\x89PNG\r\n\x1a\nvalid-png-data",
        "bad.pdf": b"%PDF-invalid-in-zip",
    })

    response = client.post(
        "/api/v1/files/upload",
        data={
            "upload_kind": "raw",
            "files": (BytesIO(zip_bytes), "invalid-batch.zip"),
        },
        content_type="multipart/form-data",
    )

    payload = response.get_json()["data"]
    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["uploaded_files"] == []
    assert calls["upload_file"] == 0
    assert any("対応外のファイル形式" in err for err in payload["errors"])


def test_upload_zip_rolls_back_archive_when_file_record_insert_fails(monkeypatch):
    client = _create_client()
    calls = {"delete_file": [], "delete_slip_record": []}

    class StubStorageService:
        def __init__(self):
            self.is_configured = True
            self._bucket_name = "bucket-a"
            self._namespace = "namespace-a"

        def upload_file(self, **kwargs):
            return {"success": True}

        def delete_file(self, object_name):
            calls["delete_file"].append(object_name)
            return {"success": True}

    class StubDatabaseService:
        def __init__(self):
            self._slip_id = 10

        def insert_slip_record(self, **kwargs):
            self._slip_id += 1
            return self._slip_id

        def insert_file_record(self, **kwargs):
            return None

        def delete_slip_record(self, slip_kind, slip_id):
            calls["delete_slip_record"].append((slip_kind, slip_id))
            return {"success": True}

        def log_activity(self, **kwargs):
            return None

    monkeypatch.setattr(
        "denpyo_toroku.app.services.oci_storage_service.OCIStorageService",
        StubStorageService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )

    zip_bytes = _build_zip_file({
        "ok1.jpg": b"\xff\xd8\xff\xe0ok-jpeg-data",
        "ok2.png": b"\x89PNG\r\n\x1a\nok-png-data",
    })

    response = client.post(
        "/api/v1/files/upload",
        data={
            "upload_kind": "raw",
            "files": (BytesIO(zip_bytes), "rollback.zip"),
        },
        content_type="multipart/form-data",
    )

    payload = response.get_json()["data"]
    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["uploaded_files"] == []
    assert len(calls["delete_file"]) == 1
    assert calls["delete_slip_record"] == [("raw", 11)]
    assert any("データベース登録失敗" in err for err in payload["errors"])


def test_preview_pages_returns_generated_pages_for_zip_file(monkeypatch):
    client = _create_client()
    calls = {
        "download_file": [],
        "prepare_document_pages": [],
    }

    class StubDatabaseService:
        def get_file_by_id(self, file_id):
            return {
                "id": file_id,
                "object_storage_path": "denpyo-raw/batch.zip",
                "original_file_name": "batch.zip",
                "content_type": "application/zip",
            }

    class StubStorageService:
        def download_file(self, object_name):
            calls["download_file"].append(object_name)
            return b"zip-bytes"

    class StubDocumentProcessor:
        def __init__(self, max_size_mb=50):
            self.max_size_mb = max_size_mb

        def prepare_document_pages(self, file_data, file_name):
            calls["prepare_document_pages"].append((file_data, file_name))
            return [
                {
                    "page_index": 0,
                    "page_label": "ページ 1",
                    "source_name": "invoice-1.png",
                    "content_type": "image/png",
                    "image_data": b"page-1",
                },
                {
                    "page_index": 1,
                    "page_label": "ページ 2",
                    "source_name": "invoice-2.png",
                    "content_type": "image/png",
                    "image_data": b"page-2",
                },
            ]

    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.oci_storage_service.OCIStorageService",
        StubStorageService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.document_processor.DocumentProcessor",
        StubDocumentProcessor,
    )

    response = client.get("/api/v1/files/1/preview-pages")

    payload = response.get_json()
    assert response.status_code == 200, payload
    assert calls["download_file"] == ["denpyo-raw/batch.zip"]
    assert calls["prepare_document_pages"] == [(b"zip-bytes", "batch.zip")]
    assert payload["data"]["file_id"] == "1"
    assert payload["data"]["page_count"] == 2
    assert payload["data"]["pages"][0]["source_name"] == "invoice-1.png"
    assert payload["data"]["pages"][1]["page_label"] == "ページ 2"


def test_preview_page_image_returns_zip_entry_image_bytes(monkeypatch):
    client = _create_client()
    zip_bytes = _build_zip_file({
        "invoice-1.png": PNG_BYTES,
        "nested/invoice-2.png": PNG_BYTES,
    })

    class StubDatabaseService:
        def get_file_by_id(self, file_id):
            return {
                "id": file_id,
                "object_storage_path": "denpyo-raw/batch.zip",
                "original_file_name": "batch.zip",
                "content_type": "application/zip",
            }

    class StubStorageService:
        def download_file(self, object_name):
            assert object_name == "denpyo-raw/batch.zip"
            return zip_bytes

    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.oci_storage_service.OCIStorageService",
        StubStorageService,
    )

    response = client.get("/api/v1/files/1/preview-pages/0")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"
    assert response.data == PNG_BYTES


def test_list_files_marks_stalled_analysis_as_retryable(monkeypatch):
    client = _create_client()

    class StubDatabaseService:
        def get_files(self, status=None, limit=20, offset=0, upload_kind=None):
            return [
                {
                    "file_id": "1",
                    "file_name": "stalled-invoice.png",
                    "original_file_name": "stalled-invoice.png",
                    "content_type": "image/png",
                    "file_size": 1024,
                    "status": "ANALYZING",
                    "uploaded_by": "tester",
                    "uploaded_at": "2026-03-01 08:00:00",
                    "updated_at": "2026-03-01 08:00:00",
                    "has_analysis_result": False,
                }
            ]

        def get_files_count(self, status=None, upload_kind=None):
            return 1

    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )

    response = client.get("/api/v1/files")

    payload = response.get_json()["data"]
    assert response.status_code == 200, response.get_json()
    assert payload["total"] == 1
    assert payload["files"][0]["status"] == "ANALYZING"
    assert payload["files"][0]["status_detail"] == "ANALYSIS_TIMEOUT"
    assert payload["files"][0]["is_analysis_stalled"] is True
    assert payload["files"][0]["can_retry_analysis"] is True


def test_analyze_file_allows_retry_when_analysis_is_stalled(monkeypatch):
    client = _create_client()
    calls = {
        "update_file_status": [],
        "submit": [],
    }

    class StubDatabaseService:
        def get_category_by_id(self, category_id):
            return {
                "id": category_id,
                "is_active": True,
                "category_name": "請求書",
                "header_table_name": "INV_HEADER",
                "line_table_name": "INV_LINE",
            }

        def get_category_table_schema(self, category_id):
            return {
                "header_table_name": "INV_HEADER",
                "line_table_name": "INV_LINE",
                "header_columns": [],
                "line_columns": [],
            }

        def get_file_by_id(self, file_id):
            return {
                "id": file_id,
                "status": "ANALYZING",
                "updated_at": "2026-03-01 08:00:00",
                "has_analysis_result": False,
                "object_storage_path": "denpyo-raw/stalled.png",
                "original_file_name": "stalled.png",
                "content_type": "image/png",
            }

        def update_file_status(self, file_id, status):
            calls["update_file_status"].append((file_id, status))
            return True

        def log_activity(self, **kwargs):
            return None

    class StubExecutor:
        def submit(self, fn, *args):
            calls["submit"].append((fn.__name__, args))
            return None

    monkeypatch.setattr(api_blueprint_module, "_ANALYSIS_EXECUTOR", StubExecutor())
    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)
    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )

    response = client.post(
        "/api/v1/files/1/analyze",
        json={"category_id": 1, "async": True},
    )

    payload = response.get_json()["data"]
    assert response.status_code == 202, response.get_json()
    assert payload["status"] == "ANALYZING"
    assert calls["update_file_status"] == [(1, "ANALYZING")]
    assert calls["submit"] == [("_queue_raw_file_analysis", (1, 1, ""))]


def test_analyze_file_processes_zip_file(monkeypatch):
    client = _create_client()
    calls = {
        "update_file_status": [],
        "log_activity": [],
        "save_analysis_result": [],
        "download_file": [],
        "prepare_for_ai": [],
        "extract_text_from_images": [],
        "field_log_contexts": [],
        "ocr_log_contexts": [],
        "extract_data_from_text": [],
    }

    class StubDatabaseService:
        def get_category_by_id(self, category_id):
            return {
                "id": category_id,
                "is_active": True,
                "category_name": "請求書",
                "header_table_name": "INV_HEADER",
                "line_table_name": "INV_LINE",
            }

        def get_category_table_schema(self, category_id):
            return {
                "header_table_name": "INV_HEADER",
                "line_table_name": "INV_LINE",
                "header_columns": [],
                "line_columns": [],
            }

        def get_file_by_id(self, file_id):
            return {
                "id": file_id,
                "status": "UPLOADED",
                "object_storage_path": "denpyo-raw/batch.zip",
                "original_file_name": "batch.zip",
                "content_type": "application/zip",
            }

        def update_file_status(self, file_id, status):
            calls["update_file_status"].append((file_id, status))
            return True

        def log_activity(self, **kwargs):
            calls["log_activity"].append(kwargs["activity_type"])
            return None

        def save_analysis_result(self, file_id, analysis_kind, result):
            calls["save_analysis_result"].append((file_id, analysis_kind, result))
            return True

    monkeypatch.setattr("denpyo_toroku.app.blueprints.api.api_blueprint.DatabaseService", StubDatabaseService)
    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )

    class StubStorageService:
        def download_file(self, object_name):
            calls["download_file"].append(object_name)
            return b"zip-bytes"

    class StubDocumentProcessor:
        def __init__(self, max_size_mb=50):
            self.max_size_mb = max_size_mb

        def prepare_for_ai(self, file_data, file_name):
            calls["prepare_for_ai"].append((file_data, file_name))
            return [
                (b"page-1", "image/png"),
                (b"page-2", "image/png"),
            ]

    class StubAIService:
        def extract_text_from_images(self, paths, log_context=None):
            calls["extract_text_from_images"].append(list(paths))
            calls["ocr_log_contexts"].append(log_context)
            return {
                "success": True,
                "extracted_text": "[PAGE 1]\nfirst page\n\n[PAGE 2]\nsecond page",
            }

        def extract_data_from_text(self, ocr_text, category, table_schema, log_context=None):
            calls["extract_data_from_text"].append((ocr_text, category, table_schema))
            calls["field_log_contexts"].append(log_context)
            return {
                "success": True,
                "header_fields": [{"field_name": "請求番号", "field_name_en": "INVOICE_NO"}],
                "line_fields": [{"line_no": 1}],
                "line_count": 1,
                "raw_lines": [{"description": "item"}],
            }

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
        "/api/v1/files/1/analyze",
        json={"category_id": 1},
    )

    payload = response.get_json()["data"]
    assert response.status_code == 200, response.get_json()
    assert payload["status"] == "ANALYZED"
    assert payload["extraction"]["line_count"] == 1
    assert calls["update_file_status"] == [(1, "ANALYZING"), (1, "ANALYZED")]
    assert calls["log_activity"] == ["ANALYZE_START", "ANALYZE_COMPLETE"]
    assert calls["download_file"] == ["denpyo-raw/batch.zip"]
    assert calls["prepare_for_ai"] == [(b"zip-bytes", "batch.zip")]
    assert len(calls["extract_text_from_images"]) == 1
    assert len(calls["extract_text_from_images"][0]) == 2
    assert calls["ocr_log_contexts"][0]["file_id"] == 1
    assert calls["ocr_log_contexts"][0]["category_id"] == 1
    assert calls["ocr_log_contexts"][0]["request_id"].startswith("req-")
    assert calls["field_log_contexts"][0] == calls["ocr_log_contexts"][0]
    assert response.headers["X-Request-ID"] == calls["ocr_log_contexts"][0]["request_id"]
    assert calls["extract_data_from_text"][0][0].startswith("[PAGE 1]")
    assert calls["save_analysis_result"][0][0:2] == (1, "raw")


def test_analyze_file_logs_structured_activity_when_ocr_response_is_empty(monkeypatch):
    client = _create_client()
    calls = {
        "update_file_status": [],
        "log_activity": [],
        "ocr_log_contexts": [],
    }

    class StubDatabaseService:
        def get_category_by_id(self, category_id):
            return {
                "id": category_id,
                "is_active": True,
                "category_name": "請求書",
                "header_table_name": "INV_HEADER",
                "line_table_name": "INV_LINE",
            }

        def get_category_table_schema(self, category_id):
            return {
                "header_table_name": "INV_HEADER",
                "line_table_name": "INV_LINE",
                "header_columns": [],
                "line_columns": [],
            }

        def get_file_by_id(self, file_id):
            return {
                "id": file_id,
                "status": "UPLOADED",
                "object_storage_path": "denpyo-raw/empty-ocr.zip",
                "original_file_name": "empty-ocr.zip",
                "content_type": "application/zip",
            }

        def update_file_status(self, file_id, status):
            calls["update_file_status"].append((file_id, status))
            return True

        def log_activity(self, **kwargs):
            calls["log_activity"].append(kwargs)
            return None

    class StubStorageService:
        def download_file(self, object_name):
            return b"zip-bytes"

    class StubDocumentProcessor:
        def __init__(self, max_size_mb=50):
            self.max_size_mb = max_size_mb

        def prepare_for_ai(self, file_data, file_name):
            return [(b"page-1", "image/png")]

    class StubAIService:
        def extract_text_from_images(self, paths, log_context=None):
            calls["ocr_log_contexts"].append(log_context)
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

    monkeypatch.setattr("denpyo_toroku.app.blueprints.api.api_blueprint.DatabaseService", StubDatabaseService)
    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )
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
        "/api/v1/files/1/analyze",
        json={"category_id": 1},
    )

    assert response.status_code == 500, response.get_json()
    assert calls["update_file_status"] == [(1, "ANALYZING"), (1, "ERROR")]
    assert response.headers["X-Request-ID"] == calls["ocr_log_contexts"][0]["request_id"]

    error_logs = [
        kwargs for kwargs in calls["log_activity"]
        if kwargs["activity_type"] == "ANALYZE_ERROR"
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
    assert calls["ocr_log_contexts"][0]["request_id"] in description


def test_category_analyze_slips_processes_zip_files_without_selection_limit(monkeypatch):
    client = _create_client()
    calls = {
        "update_file_status": [],
        "update_category_file_status": [],
        "save_category_analysis_result": [],
        "log_activity": [],
        "download_file": [],
        "prepare_for_ai": [],
        "extract_text_from_images": [],
        "ocr_log_contexts": [],
        "schema_log_contexts": [],
        "generate_sql_schema_from_text": [],
    }

    class StubDatabaseService:
        def get_files_by_ids(self, file_ids):
            return []

        def get_slips_category_files_by_ids(self, file_ids):
            return [{
                "id": file_id,
                "object_name": f"denpyo-category/sample-{file_id}.zip",
                "file_name": f"sample-{file_id}.zip",
                "original_file_name": f"sample-{file_id}.zip",
                "content_type": "application/zip",
                "status": "UPLOADED",
            } for file_id in file_ids]

        def get_slips_category_file_by_object_name(self, object_name):
            file_id = int(object_name.rsplit("-", 1)[-1].split(".", 1)[0])
            return {
                "id": file_id,
                "object_name": object_name,
                "file_name": f"sample-{file_id}.zip",
                "original_file_name": f"sample-{file_id}.zip",
                "content_type": "application/zip",
                "status": "UPLOADED",
            }

        def get_file_by_object_storage_path(self, object_name):
            file_id = int(object_name.rsplit("-", 1)[-1].split(".", 1)[0])
            return {
                "id": file_id,
                "object_storage_path": object_name,
                "original_file_name": f"sample-{file_id}.zip",
                "content_type": "application/zip",
                "status": "UPLOADED",
            }

        def update_file_status(self, file_id, status):
            calls["update_file_status"].append((file_id, status))
            return True

        def update_category_file_status(self, file_id, status):
            calls["update_category_file_status"].append((file_id, status))
            return True

        def save_analysis_result(self, file_id, analysis_kind, result):
            calls.setdefault("save_analysis_result", []).append((file_id, analysis_kind, result))
            return True

        def save_category_analysis_result(self, file_id, result):
            calls["save_category_analysis_result"].append((file_id, result))
            return True

        def log_activity(self, **kwargs):
            calls["log_activity"].append((kwargs["activity_type"], kwargs.get("file_id")))
            return None

    class StubStorageService:
        def download_file(self, object_name):
            calls["download_file"].append(object_name)
            return b"zip-bytes"

    class StubDocumentProcessor:
        def prepare_for_ai(self, file_data, file_name):
            calls["prepare_for_ai"].append((file_data, file_name))
            return [
                (f"{file_name}-page-1".encode(), "image/png"),
                (f"{file_name}-page-2".encode(), "image/png"),
            ]

    class StubAIService:
        def extract_text_from_images(self, paths, log_context=None):
            calls["extract_text_from_images"].append(list(paths))
            calls["ocr_log_contexts"].append(log_context)
            return {
                "success": True,
                "extracted_text": "\n".join(f"[PAGE {idx + 1}] text" for idx, _ in enumerate(paths)),
            }

        def generate_sql_schema_from_text(self, extracted_text, analysis_mode, log_context=None):
            calls["generate_sql_schema_from_text"].append((extracted_text, analysis_mode))
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

    monkeypatch.setattr(
        "denpyo_toroku.app.services.database_service.DatabaseService",
        StubDatabaseService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.blueprints.api.api_blueprint.DatabaseService",
        StubDatabaseService,
    )
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
        json={"file_ids": [1, 2, 3, 4, 5, 6], "analysis_mode": "header_only"},
    )

    payload = response.get_json()["data"]
    assert response.status_code == 200, response.get_json()
    assert payload["category_guess"] == "請求書"
    assert payload["analyzed_file_ids"] == [1, 2, 3, 4, 5, 6]
    assert calls["update_file_status"] == [
        (1, "ANALYZING"),
        (2, "ANALYZING"),
        (3, "ANALYZING"),
        (4, "ANALYZING"),
        (5, "ANALYZING"),
        (6, "ANALYZING"),
        (1, "ANALYZED"),
        (2, "ANALYZED"),
        (3, "ANALYZED"),
        (4, "ANALYZED"),
        (5, "ANALYZED"),
        (6, "ANALYZED"),
    ]
    assert calls["update_category_file_status"] == [
        (1, "ANALYZING"),
        (2, "ANALYZING"),
        (3, "ANALYZING"),
        (4, "ANALYZING"),
        (5, "ANALYZING"),
        (6, "ANALYZING"),
        (1, "ANALYZED"),
        (2, "ANALYZED"),
        (3, "ANALYZED"),
        (4, "ANALYZED"),
        (5, "ANALYZED"),
        (6, "ANALYZED"),
    ]
    assert len(calls["download_file"]) == 6
    assert len(calls["prepare_for_ai"]) == 6
    assert len(calls["extract_text_from_images"]) == 1
    assert len(calls["extract_text_from_images"][0]) == 12
    assert calls["ocr_log_contexts"][0]["file_ids"] == [1, 2, 3, 4, 5, 6]
    assert calls["ocr_log_contexts"][0]["analysis_mode"] == "header_only"
    assert calls["ocr_log_contexts"][0]["request_id"].startswith("req-")
    assert calls["schema_log_contexts"][0] == calls["ocr_log_contexts"][0]
    assert response.headers["X-Request-ID"] == calls["ocr_log_contexts"][0]["request_id"]
    assert calls["generate_sql_schema_from_text"][0][1] == "header_only"
    assert [file_id for file_id, _ in calls["save_category_analysis_result"]] == [1, 2, 3, 4, 5, 6]
