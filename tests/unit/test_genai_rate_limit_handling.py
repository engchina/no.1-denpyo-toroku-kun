from io import BytesIO
from types import SimpleNamespace
import sys

from flask import Flask

import denpyo_toroku.app.blueprints.api.api_blueprint as api_blueprint_module
from denpyo_toroku.app.blueprints.api import api_blueprint as api_bp
from denpyo_toroku.app.services.ai_service import AIService, AIRateLimitError


class FakeOCIError(Exception):
    def __init__(self, message: str, status: int | None = None, headers: dict | None = None):
        super().__init__(message)
        self.status = status
        self.headers = headers or {}


def _create_client():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(api_bp.api_blueprint, url_prefix="")
    return app.test_client()


def _install_fake_oci(monkeypatch):
    models = SimpleNamespace(
        GenericChatRequest=lambda **kwargs: kwargs,
        UserMessage=lambda **kwargs: kwargs,
        ChatDetails=lambda **kwargs: kwargs,
        OnDemandServingMode=lambda **kwargs: kwargs,
    )
    fake_oci = SimpleNamespace(generative_ai_inference=SimpleNamespace(models=models))
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setattr("os.path.exists", lambda _path: True)
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: BytesIO(b"fake_image_data"))


def test_retry_api_call_raises_rate_limit_without_in_call_retry(monkeypatch):
    service = AIService()
    calls = {"attempts": 0, "cooldowns": []}

    class StubGate:
        def call(self, _operation_name, _func, *args, **kwargs):
            calls["attempts"] += 1
            raise FakeOCIError("Too Many Requests", status=429, headers={"Retry-After": "7"})

        def note_rate_limit(self, retry_after_seconds):
            calls["cooldowns"].append(retry_after_seconds)

    monkeypatch.setattr("denpyo_toroku.app.services.ai_service._GENAI_REQUEST_GATE", StubGate())

    try:
        service._retry_api_call("extract_text_from_images[1]", lambda: None)
        assert False, "Expected AIRateLimitError"
    except AIRateLimitError as exc:
        assert exc.retry_after_seconds == 7.0

    assert calls["attempts"] == 1
    assert calls["cooldowns"] == [7.0]


def test_extract_text_from_images_propagates_rate_limit(monkeypatch):
    service = AIService()
    _install_fake_oci(monkeypatch)
    monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(chat=lambda _detail: None))
    monkeypatch.setattr(
        service,
        "_retry_api_call",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AIRateLimitError(
                "extract_text_from_images[1]",
                9.0,
                FakeOCIError("Too Many Requests", status=429),
            )
        ),
    )

    try:
        service.extract_text_from_images(["/tmp/fake.png"])
        assert False, "Expected AIRateLimitError"
    except AIRateLimitError as exc:
        assert exc.retry_after_seconds == 9.0


def test_queue_raw_file_analysis_requeues_on_rate_limit(monkeypatch):
    calls = {
        "update_file_status": [],
        "log_activity": [],
        "submit": [],
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

        def get_category_table_schema(self, _category_id):
            return {
                "header_table_name": "INV_HEADER",
                "line_table_name": "INV_LINE",
                "header_columns": [],
                "line_columns": [],
            }

        def get_file_by_id(self, file_id):
            return {
                "id": file_id,
                "object_storage_path": "denpyo-raw/sample.zip",
                "original_file_name": "sample.zip",
            }

        def update_file_status(self, file_id, status):
            calls["update_file_status"].append((file_id, status))
            return True

        def log_activity(self, **kwargs):
            calls["log_activity"].append(kwargs["activity_type"])
            return None

    class StubStorageService:
        def download_file(self, _object_name):
            return b"zip-bytes"

    class StubDocumentProcessor:
        def prepare_for_ai(self, _file_data, _file_name):
            return [(b"page-1", "image/png")]

    class StubAIService:
        def extract_text_from_images(self, _paths, log_context=None):
            calls["ocr_log_contexts"].append(log_context)
            raise AIRateLimitError(
                "extract_text_from_images[1]",
                12.0,
                FakeOCIError("Too Many Requests", status=429),
            )

    def _capture_submit(fn, *args, delay_seconds=0.0):
        calls["submit"].append((fn.__name__, args, delay_seconds))
        return None

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)
    monkeypatch.setattr("denpyo_toroku.app.services.database_service.DatabaseService", StubDatabaseService)
    monkeypatch.setattr(
        "denpyo_toroku.app.services.oci_storage_service.OCIStorageService",
        StubStorageService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.document_processor.DocumentProcessor",
        StubDocumentProcessor,
    )
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.AIService", StubAIService)
    monkeypatch.setattr(api_blueprint_module, "_submit_analysis_job", _capture_submit)

    api_blueprint_module._queue_raw_file_analysis(69, 24, "admin")

    assert calls["update_file_status"] == [(69, "ANALYZING")]
    assert calls["ocr_log_contexts"][0]["file_id"] == 69
    assert calls["ocr_log_contexts"][0]["category_id"] == 24
    assert calls["ocr_log_contexts"][0]["request_id"].startswith("bg-raw-analyze-")
    assert "ANALYZE_RETRY" in calls["log_activity"]
    assert len(calls["submit"]) == 1
    job_name, job_args, delay_seconds = calls["submit"][0]
    assert job_name == "_queue_raw_file_analysis"
    assert job_args == (69, 24, "admin", 1)
    assert delay_seconds >= 12.0


def test_sync_analyze_returns_503_when_genai_is_rate_limited(monkeypatch):
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

        def get_category_table_schema(self, _category_id):
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
                "object_storage_path": "denpyo-raw/sample.zip",
                "original_file_name": "sample.zip",
                "content_type": "application/zip",
            }

        def update_file_status(self, file_id, status):
            calls["update_file_status"].append((file_id, status))
            return True

        def log_activity(self, **kwargs):
            calls["log_activity"].append(kwargs["activity_type"])
            return None

    class StubStorageService:
        def download_file(self, _object_name):
            return b"zip-bytes"

    class StubDocumentProcessor:
        def prepare_for_ai(self, _file_data, _file_name):
            return [(b"page-1", "image/png")]

    class StubAIService:
        def extract_text_from_images(self, _paths, log_context=None):
            calls["ocr_log_contexts"].append(log_context)
            raise AIRateLimitError(
                "extract_text_from_images[1]",
                11.0,
                FakeOCIError("Too Many Requests", status=429),
            )

    monkeypatch.setattr(api_blueprint_module, "DatabaseService", StubDatabaseService)
    monkeypatch.setattr("denpyo_toroku.app.services.database_service.DatabaseService", StubDatabaseService)
    monkeypatch.setattr(
        "denpyo_toroku.app.services.oci_storage_service.OCIStorageService",
        StubStorageService,
    )
    monkeypatch.setattr(
        "denpyo_toroku.app.services.document_processor.DocumentProcessor",
        StubDocumentProcessor,
    )
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.AIService", StubAIService)

    response = client.post("/api/v1/files/1/analyze", json={"category_id": 1})

    payload = response.get_json()["data"]
    assert response.status_code == 503, response.get_json()
    assert response.headers["Retry-After"] == "11"
    assert response.headers["X-Request-ID"] == calls["ocr_log_contexts"][0]["request_id"]
    assert calls["ocr_log_contexts"][0]["file_id"] == 1
    assert calls["ocr_log_contexts"][0]["category_id"] == 1
    assert calls["ocr_log_contexts"][0]["request_id"].startswith("req-")
    assert payload["retry_after_seconds"] == 11
    assert calls["update_file_status"] == [(1, "ANALYZING"), (1, "ERROR")]
    assert calls["log_activity"] == ["ANALYZE_START", "ANALYZE_ERROR"]
