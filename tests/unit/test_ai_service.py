from denpyo_toroku.app.services.ai_service import AIService
from types import SimpleNamespace


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
