from denpyo_toroku.app.services.ai_service import AIService
import logging
from types import SimpleNamespace
import sys
import time


def test_extract_json_recovers_truncated_string_and_braces():
    service = AIService()
    text = """
```json
{
  "category": "入金伝票",
  "confidence": 1.0,
  "description": "得意先からの入金を記録・仕訳するための
"""

    parsed = service._extract_json(text)

    assert parsed["category"] == "入金伝票"
    assert parsed["confidence"] == 1.0
    assert parsed["description"] == "得意先からの入金を記録・仕訳するための"


def test_extract_json_keeps_valid_json_unchanged():
    service = AIService()
    text = '{"category":"請求書","confidence":0.95,"description":"請求内容"}'

    parsed = service._extract_json(text)

    assert parsed == {
        "category": "請求書",
        "confidence": 0.95,
        "description": "請求内容",
    }


def test_parse_json_with_regeneration_succeeds_on_third_attempt():
    service = AIService()
    attempts = {"count": 0}
    responses = [
        "not-json-response-1",
        "not-json-response-2",
        '{"category":"入金伝票","confidence":1.0,"description":"完成","has_line_items":true}',
    ]

    def generate_text():
        idx = attempts["count"]
        attempts["count"] += 1
        return responses[idx]

    parsed = service._parse_json_with_regeneration("classify_invoice", generate_text, 3)

    assert attempts["count"] == 3
    assert parsed["category"] == "入金伝票"
    assert parsed["description"] == "完成"


def test_normalize_classification_result_returns_fallback_for_invalid_payload():
    service = AIService()
    parsed = service._normalize_classification_result({"confidence": 0.8})

    assert parsed["success"] is True
    assert parsed["is_fallback"] is True
    assert parsed["category"] == "その他"


def test_normalize_classification_result_returns_normalized_payload():
    service = AIService()
    parsed = service._normalize_classification_result({
        "category": " 請求書 ",
        "confidence": "bad",
        "description": "説明",
        "has_line_items": 1,
    })

    assert parsed["success"] is True
    assert parsed["is_fallback"] is False
    assert parsed["category"] == "請求書"
    assert parsed["confidence"] == 0.0
    assert parsed["has_line_items"] is True


def test_normalize_classification_result_clamps_confidence_and_parses_false_string():
    service = AIService()
    parsed = service._normalize_classification_result({
        "category": "領収書",
        "confidence": 1.8,
        "description": "説明",
        "has_line_items": "false",
    })

    assert parsed["confidence"] == 1.0
    assert parsed["has_line_items"] is False


def test_get_tool_arguments_from_chat_response_prefers_function_arguments():
    service = AIService()
    chat_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            name="set_invoice_classification",
                            arguments='{"category":"請求書","confidence":0.9,"description":"x","has_line_items":false}'
                        )
                    ],
                    content=[]
                )
            )
        ]
    )

    payload = service._get_tool_arguments_from_chat_response(chat_response, "set_invoice_classification")
    assert payload.startswith('{"category":"請求書"')


def test_get_text_from_chat_response_falls_back_to_content_text():
    service = AIService()
    chat_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=[
                        SimpleNamespace(text='{"category":"その他","confidence":0.1,"description":"x","has_line_items":false}')
                    ]
                )
            )
        ]
    )

    payload = service._get_text_from_chat_response(chat_response)
    assert '"category":"その他"' in payload


def test_get_text_from_chat_response_supports_dict_and_nested_parts():
    service = AIService()
    chat_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=[
                        {"type": "TEXT", "text": "alpha"},
                        {"type": "WRAPPER", "content": [{"type": "TEXT", "text": "beta"}]},
                        "gamma",
                        SimpleNamespace(parts=[SimpleNamespace(text="delta")]),
                    ]
                )
            )
        ]
    )

    payload = service._get_text_from_chat_response(chat_response)

    assert payload == "alphabetagammadelta"


def test_extract_text_from_images_falls_back_to_optimized_variant(monkeypatch):
    service = AIService()
    monkeypatch.setattr(service, "_get_client", lambda: object())
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.GENAI_OCR_IMAGE_MAX_EDGE_STEPS", (1800,))
    monkeypatch.setattr("os.path.exists", lambda _path: True)

    calls = []
    cleanup_calls = []

    monkeypatch.setattr(
        service,
        "_create_optimized_image_tempfiles",
        lambda _paths, max_long_edge, log_context=None: [f"/tmp/optimized-{max_long_edge}.png"],
    )
    monkeypatch.setattr(service, "_cleanup_tempfiles", lambda paths: cleanup_calls.append(list(paths)))

    def fake_extract_once(_client, paths, variant_label, log_context=None):
        calls.append((list(paths), variant_label))
        if variant_label == "original":
            raise ValueError("payload too large")
        return {
            "success": True,
            "extracted_text": "[PAGE 1]\nscaled",
            "page_texts": [{"page_index": 0, "source_path": paths[0], "text": "scaled"}],
        }

    monkeypatch.setattr(service, "_extract_text_from_image_filepaths_once", fake_extract_once)

    result = service.extract_text_from_images(["/tmp/original.png"])

    assert result["success"] is True
    assert result["extracted_text"] == "[PAGE 1]\nscaled"
    assert calls == [
        (["/tmp/original.png"], "original"),
        (["/tmp/optimized-1800.png"], "long-edge<=1800"),
    ]
    assert cleanup_calls == [[], ["/tmp/optimized-1800.png"]]


def test_extract_text_from_images_retries_when_vlm_returns_empty_text(monkeypatch):
    service = AIService()
    _install_fake_oci(monkeypatch)
    monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(chat=lambda _detail: None))
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES", 1)
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES", 0)
    monkeypatch.setattr(service, "_calculate_backoff_delay", lambda _attempt: 0.25)

    calls = {"retry": 0}
    sleep_calls = []
    responses = [
        SimpleNamespace(
            data=SimpleNamespace(
                chat_response=SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=[]))]
                )
            )
        ),
        SimpleNamespace(
            data=SimpleNamespace(
                chat_response=SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=[{"type": "TEXT", "text": "recovered text"}]
                            )
                        )
                    ]
                )
            )
        ),
    ]

    def fake_retry(*_args, **_kwargs):
        response = responses[calls["retry"]]
        calls["retry"] += 1
        return response

    monkeypatch.setattr(service, "_retry_api_call", fake_retry)
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.time.sleep", lambda delay: sleep_calls.append(delay))

    result = service.extract_text_from_images(["/tmp/fake.png"])

    assert result["success"] is True
    assert result["extracted_text"] == "[PAGE 1]\nrecovered text"
    assert calls["retry"] == 2
    assert sleep_calls == [0.25]


def test_extract_text_from_images_prioritizes_rotated_orientation_for_landscape_source(monkeypatch):
    service = AIService()
    _install_fake_oci(monkeypatch)
    monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(chat=lambda _detail: None))
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.GENAI_OCR_ROTATION_ANGLES", (0, 90, 180, 270))
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES", 1)
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES", 0)
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.GENAI_OCR_IMAGE_MAX_EDGE_STEPS", ())
    monkeypatch.setattr(service, "_calculate_backoff_delay", lambda _attempt: 0.5)
    monkeypatch.setattr(
        service,
        "_collect_image_path_stats",
        lambda _paths: [{"path": "/tmp/fake.png", "bytes": 100, "width": 2000, "height": 1000}],
    )

    cleanup_calls = []
    sleep_calls = []
    operation_names = []
    response = SimpleNamespace(
        data=SimpleNamespace(
            chat_response=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=[{"type": "TEXT", "text": "rotated text"}]
                        )
                    )
                ]
            )
        )
    )

    monkeypatch.setattr(
        service,
        "_create_rotated_image_tempfile",
        lambda _path, rotation_degrees, log_context=None: f"/tmp/rotated-{rotation_degrees}.png",
    )
    monkeypatch.setattr(service, "_cleanup_tempfiles", lambda paths: cleanup_calls.append(list(paths)))
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.time.sleep", lambda delay: sleep_calls.append(delay))

    def fake_retry(operation_name, *_args, **_kwargs):
        operation_names.append(operation_name)
        return response

    monkeypatch.setattr(service, "_retry_api_call", fake_retry)

    result = service.extract_text_from_images(["/tmp/fake.png"])

    assert result["success"] is True
    assert result["extracted_text"] == "[PAGE 1]\nrotated text"
    assert result["page_texts"][0]["rotation_degrees"] == 90
    assert operation_names == ["extract_text_from_images[1]/original/rot90"]
    assert sleep_calls == []
    assert ["/tmp/rotated-90.png"] in cleanup_calls


def test_extract_text_from_images_reports_rotation_details_when_all_directions_are_empty(monkeypatch):
    service = AIService()
    _install_fake_oci(monkeypatch)
    monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(chat=lambda _detail: None))
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.GENAI_OCR_ROTATION_ANGLES", (0, 90, 180, 270))
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES", 1)
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES", 0)
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.GENAI_OCR_IMAGE_MAX_EDGE_STEPS", ())
    monkeypatch.setattr(service, "_calculate_backoff_delay", lambda _attempt: 0.2)
    monkeypatch.setattr(
        service,
        "_collect_image_path_stats",
        lambda _paths: [{"path": "/tmp/fake.png", "bytes": 100, "width": 2000, "height": 1000}],
    )

    sleep_calls = []
    operation_names = []
    monkeypatch.setattr(
        service,
        "_create_rotated_image_tempfile",
        lambda _path, rotation_degrees, log_context=None: f"/tmp/rotated-{rotation_degrees}.png",
    )
    monkeypatch.setattr(service, "_cleanup_tempfiles", lambda _paths: None)
    monkeypatch.setattr("denpyo_toroku.app.services.ai_service.time.sleep", lambda delay: sleep_calls.append(delay))
    def fake_retry(operation_name, *_args, **_kwargs):
        operation_names.append(operation_name)
        return SimpleNamespace(
            data=SimpleNamespace(
                chat_response=SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=[]))]
                )
            )
        )

    monkeypatch.setattr(service, "_retry_api_call", fake_retry)

    result = service.extract_text_from_images(["/tmp/fake.png"])

    assert result["success"] is False
    assert "rotation=180" in result["message"]
    assert "rotation_attempts=4" in result["message"]
    assert "primary_empty_response_attempts=2" in result["message"]
    assert "secondary_empty_response_attempts=1" in result["message"]
    assert "attempts=5" in result["message"]
    assert operation_names == [
        "extract_text_from_images[1]/original/rot90",
        "extract_text_from_images[1]/original/rot90",
        "extract_text_from_images[1]/original/rot270",
        "extract_text_from_images[1]/original/rot0",
        "extract_text_from_images[1]/original/rot180",
    ]
    assert sleep_calls == [0.2, 0.2, 0.2, 0.2]


def test_retry_api_call_emits_start_waiting_and_complete_logs(monkeypatch, caplog):
    service = AIService()

    class StubGate:
        def call(self, _operation_name, func, *args, **kwargs):
            time.sleep(0.05)
            return func(*args, **kwargs)

    monkeypatch.setattr("denpyo_toroku.app.services.ai_service._GENAI_REQUEST_GATE", StubGate())
    monkeypatch.setattr(
        "denpyo_toroku.app.services.ai_service.GENAI_PROGRESS_LOG_INTERVAL_SECONDS",
        0.01,
    )

    with caplog.at_level(logging.INFO, logger="denpyo_toroku.app.services.ai_service"):
        result = service._retry_api_call(
            "extract_data_from_text",
            lambda: "ok",
            log_context={"file_id": 69, "request_id": "req-123"},
        )

    assert result == "ok"
    messages = [record.message for record in caplog.records]
    assert any("OCI GenAI リクエスト送信を開始します" in message for message in messages)
    assert any("OCI GenAI 応答を待機中です" in message for message in messages)
    assert any("OCI GenAI 応答を受信しました" in message for message in messages)


def test_extract_data_from_text_propagates_log_context(monkeypatch):
    service = AIService()
    _install_fake_oci(monkeypatch)
    monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(chat=lambda _: None))

    captured = {}

    def fake_retry(operation_name, func, *args, log_context=None, **kwargs):
        captured["retry_operation_name"] = operation_name
        captured["retry_log_context"] = log_context
        return SimpleNamespace(
            data=SimpleNamespace(
                chat_response=SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=[
                                    SimpleNamespace(
                                        text='{"header_fields":[],"line_fields":[],"raw_lines":[],"line_count":0}'
                                    )
                                ]
                            )
                        )
                    ]
                )
            )
        )

    def fake_parse(operation_name, generate_text_func, max_attempts, log_context=None):
        captured["parse_operation_name"] = operation_name
        captured["parse_log_context"] = log_context
        generate_text_func()
        return {"header_fields": [], "line_fields": [], "raw_lines": [], "line_count": 0}

    monkeypatch.setattr(service, "_retry_api_call", fake_retry)
    monkeypatch.setattr(service, "_parse_json_with_regeneration", fake_parse)

    log_context = {"file_id": 69, "request_id": "req-123"}
    result = service.extract_data_from_text(
        "dummy text",
        category="請求書",
        table_schema={
            "header_table_name": "INV_HEADER",
            "line_table_name": "",
            "header_columns": [],
            "line_columns": [],
        },
        log_context=log_context,
    )

    assert result["success"] is True
    assert captured["retry_operation_name"] == "extract_data_from_text"
    assert captured["parse_operation_name"] == "extract_data_from_text"
    assert captured["retry_log_context"] == log_context
    assert captured["parse_log_context"] == log_context


def _install_fake_oci(monkeypatch):
    models = SimpleNamespace(
        GenericChatRequest=lambda **kwargs: kwargs,
        UserMessage=lambda **kwargs: kwargs,
        ChatDetails=lambda **kwargs: kwargs,
        OnDemandServingMode=lambda **kwargs: kwargs,
    )
    fake_oci = SimpleNamespace(generative_ai_inference=SimpleNamespace(models=models))
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    import os
    monkeypatch.setattr(os.path, "exists", lambda path: True)
    from io import BytesIO
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: BytesIO(b"fake_image_data"))


def test_generate_sql_schema_from_text_maps_columns(monkeypatch):
    service = AIService()
    _install_fake_oci(monkeypatch)
    monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(chat=lambda _: None))
    monkeypatch.setattr(
        service,
        "_parse_json_with_regeneration",
        lambda *_args, **_kwargs: {
            "document_type_ja": "請求書",
            "document_type_en": "invoice",
            "header_table_name": "SEIKYUUSHO",
            "line_table_name": "SEIKYUUSHO_MEISAI",
            "header_columns": [
                {
                    "column_name": "HAKKOOBI",
                    "comment": "発行日",
                    "data_type": "DATE",
                    "data_length": 50,
                    "is_nullable": False,
                },
                {
                    "column_name": "NOTE",
                    "comment": "備考",
                    "data_type": "UNKNOWN",
                    "data_length": 200,
                    "is_nullable": True,
                },
            ],
            "line_columns": [
                {
                    "column_name": "KINGAKU",
                    "comment": "金額",
                    "data_type": "NUMBER",
                    "data_length": 12,
                    "is_nullable": False,
                }
            ],
        },
    )

    result = service.generate_sql_schema_from_text("dummy text", "header_line")

    assert result["success"] is True
    assert result["document_type_ja"] == "請求書"
    assert result["document_type_en"] == "invoice"
    assert result["header_fields"][0] == {
        "field_name_en": "HAKKOOBI",
        "field_name": "発行日",
        "data_type": "DATE",
        "max_length": None,
        "is_required": True,
    }
    assert result["header_fields"][1]["data_type"] == "VARCHAR2"
    assert result["line_fields"][0]["max_length"] is None


def test_generate_sql_schema_from_text_propagates_log_context(monkeypatch):
    service = AIService()
    _install_fake_oci(monkeypatch)
    monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(chat=lambda _: None))

    captured = {}

    def fake_retry(operation_name, func, *args, log_context=None, **kwargs):
        captured["retry_operation_name"] = operation_name
        captured["retry_log_context"] = log_context
        return SimpleNamespace(
            data=SimpleNamespace(
                chat_response=SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=[
                                    SimpleNamespace(
                                        text='{"document_type_ja":"請求書","document_type_en":"invoice","header_table_name":"SEIKYUUSHO","line_table_name":"","header_columns":[],"line_columns":[]}'
                                    )
                                ]
                            )
                        )
                    ]
                )
            )
        )

    def fake_parse(operation_name, generate_text_func, max_attempts, log_context=None):
        captured["parse_operation_name"] = operation_name
        captured["parse_log_context"] = log_context
        generate_text_func()
        return {
            "document_type_ja": "請求書",
            "document_type_en": "invoice",
            "header_table_name": "SEIKYUUSHO",
            "line_table_name": "",
            "header_columns": [],
            "line_columns": [],
        }

    monkeypatch.setattr(service, "_retry_api_call", fake_retry)
    monkeypatch.setattr(service, "_parse_json_with_regeneration", fake_parse)

    log_context = {"file_ids": [1, 2], "request_id": "req-456"}
    result = service.generate_sql_schema_from_text(
        "dummy text",
        "header_only",
        log_context=log_context,
    )

    assert result["success"] is True
    assert captured["retry_operation_name"] == "generate_sql_schema_from_text"
    assert captured["parse_operation_name"] == "generate_sql_schema_from_text"
    assert captured["retry_log_context"] == log_context
    assert captured["parse_log_context"] == log_context


def test_generate_sql_schema_from_text_converts_clob_to_varchar2(monkeypatch):
    service = AIService()
    _install_fake_oci(monkeypatch)
    monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(chat=lambda _: None))
    monkeypatch.setattr(
        service,
        "_parse_json_with_regeneration",
        lambda *_args, **_kwargs: {
            "document_type_ja": "領収書",
            "document_type_en": "receipt",
            "header_table_name": "RYOUSHUUSHO",
            "line_table_name": "",
            "header_columns": [
                {
                    "column_name": "BIKOU",
                    "comment": "備考",
                    "data_type": "CLOB",
                    "data_length": None,
                    "is_nullable": True,
                }
            ],
            "line_columns": [],
        },
    )

    result = service.generate_sql_schema_from_text("dummy text", "header_only")

    assert result["success"] is True
    assert result["header_fields"][0]["data_type"] == "VARCHAR2"
    assert result["header_fields"][0]["max_length"] == 4000


def test_generate_sql_schema_from_text_adds_buffer_to_varchar2_lengths(monkeypatch):
    service = AIService()
    _install_fake_oci(monkeypatch)
    monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(chat=lambda _: None))
    monkeypatch.setattr(
        service,
        "_parse_json_with_regeneration",
        lambda *_args, **_kwargs: {
            "document_type_ja": "領収書",
            "document_type_en": "receipt",
            "header_table_name": "RECEIPT_H",
            "line_table_name": "RECEIPT_L",
            "header_columns": [
                {
                    "column_name": "SHOUHINCODE",
                    "comment": "商品コード",
                    "data_type": "VARCHAR2",
                    "data_length": 20,
                    "is_nullable": False,
                },
                {
                    "column_name": "TORIHIKISAKI_MEI",
                    "comment": "取引先名",
                    "data_type": "VARCHAR2",
                    "data_length": 100,
                    "is_nullable": False,
                },
            ],
            "line_columns": [],
        },
    )

    result = service.generate_sql_schema_from_text("dummy text", "header_only")

    assert result["success"] is True
    assert result["header_fields"][0]["max_length"] == 50
    assert result["header_fields"][1]["max_length"] == 200


def test_generate_sql_schema_from_text_forces_empty_line_fields_in_header_only(monkeypatch):
    service = AIService()
    _install_fake_oci(monkeypatch)
    monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(chat=lambda _: None))
    monkeypatch.setattr(
        service,
        "_parse_json_with_regeneration",
        lambda *_args, **_kwargs: {
            "header_table_name": "RYOUSHUUSHO",
            "line_table_name": "RYOUSHUUSHO_MEISAI",
            "header_columns": [{"column_name": "NO", "comment": "番号", "data_type": "VARCHAR2", "data_length": 20, "is_nullable": False}],
            "line_columns": [{"column_name": "SHOUHIN", "comment": "商品", "data_type": "VARCHAR2", "data_length": 100, "is_nullable": False}],
        },
    )

    result = service.generate_sql_schema_from_text("dummy text", "header_only")

    assert result["success"] is True
    assert result["line_fields"] == []
