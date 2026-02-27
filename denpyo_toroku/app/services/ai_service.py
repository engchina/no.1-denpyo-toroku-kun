"""
AI 分析サービス

OCI Generative AI (google.gemini-2.5-flash) を使用した伝票画像の分析を提供します。
- 伝票種別の分類
- フィールド情報の抽出
- テーブル構造（DDL）の提案

参考: no.1-semantic-doc-search/backend/app/services/ai_copilot.py
"""
import json
import logging
import os
import random
import time
import requests
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# レート制限対応のリトライ設定（Generative AI API用）
GENAI_API_MAX_RETRIES = int(os.environ.get("GENAI_API_MAX_RETRIES", "5"))
GENAI_API_BASE_DELAY = float(os.environ.get("GENAI_API_BASE_DELAY", "2.0"))
GENAI_API_MAX_DELAY = float(os.environ.get("GENAI_API_MAX_DELAY", "180.0"))
GENAI_API_JITTER = float(os.environ.get("GENAI_API_JITTER", "0.15"))
GENAI_JSON_PARSE_RETRIES = max(1, int(os.environ.get("GENAI_JSON_PARSE_RETRIES", "3")))
GENAI_RECOVERY_MAX_RETRIES = max(1, int(os.environ.get("GENAI_RECOVERY_MAX_RETRIES", "2")))


class AIService:
    """AI 分析サービス

    OCI Generative AI のマルチモーダルモデルを使用して伝票画像を分析します。
    - 伝票種別の自動分類
    - フィールド名・型・値の抽出
    - HEADER + LINE テーブル構造の DDL 提案
    """

    def __init__(self):
        self._client = None
        self._region = os.environ.get("OCI_REGION", "ap-osaka-1")
        self._compartment_id = os.environ.get("OCI_CONFIG_COMPARTMENT", "")
        self._llm_model_id = os.environ.get("LLM_MODEL_ID", "xai.grok-code-fast-1")
        self._vlm_model_id = os.environ.get("VLM_MODEL_ID", "google.gemini-2.5-flash")
        self._max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "65536"))
        self._temperature = float(os.environ.get("LLM_TEMPERATURE", "0.0"))
        self._service_endpoint = os.environ.get(
            "OCI_SERVICE_ENDPOINT",
            f"https://inference.generativeai.{self._region}.oci.oraclecloud.com"
        )

    def _get_client(self):
        """OCI Generative AI クライアントを取得（遅延初期化）"""
        if self._client is not None:
            return self._client

        try:
            import oci
            config_path = os.path.expanduser(
                os.environ.get("OCI_CONFIG_PATH", "~/.oci/config")
            )
            profile = os.environ.get("OCI_CONFIG_PROFILE", "DEFAULT")

            if not os.path.exists(config_path):
                logger.warning("OCI 設定ファイルが見つかりません: %s", config_path)
                return None

            config = oci.config.from_file(config_path, profile)
            self._client = oci.generative_ai_inference.GenerativeAiInferenceClient(
                config=config,
                service_endpoint=self._service_endpoint,
                timeout=(10, 240),
            )
            logger.info("OCI Generative AI クライアントを初期化しました (model=%s)", self._llm_model_id)
        except Exception as e:
            logger.error("OCI Generative AI クライアント初期化エラー: %s", e, exc_info=True)
            return None

        return self._client

    def _is_rate_limit_error(self, error: Exception) -> bool:
        error_str = str(error).lower()
        return (
            '429' in error_str
            or 'too many requests' in error_str
            or 'rate limit exceeded' in error_str
        )

    def _calculate_backoff_delay(self, attempt: int, is_rate_limit: bool = False) -> float:
        base_multiplier = 4.0 if is_rate_limit else 2.0
        delay = GENAI_API_BASE_DELAY * (base_multiplier ** attempt)
        delay = min(delay, GENAI_API_MAX_DELAY)
        jitter = random.uniform(-GENAI_API_JITTER, GENAI_API_JITTER) * delay
        return max(0.1, delay + jitter)

    def _retry_api_call(self, operation_name: str, func, *args, **kwargs):
        """リトライ付きAPI呼び出し"""
        last_error = None
        for attempt in range(GENAI_API_MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                is_rate_limit = self._is_rate_limit_error(e)
                if attempt < GENAI_API_MAX_RETRIES - 1:
                    delay = self._calculate_backoff_delay(attempt, is_rate_limit)
                    logger.warning(
                        "%s: 試行 %d/%d 失敗 (%s)。%.1f秒後にリトライ...",
                        operation_name, attempt + 1, GENAI_API_MAX_RETRIES, str(e)[:100], delay
                    )
                    time.sleep(delay)
                else:
                    logger.error("%s: 最大リトライ回数に到達: %s", operation_name, e)
        raise last_error

    def _extract_json(self, text: str) -> Any:
        """AI レスポンスから JSON を抽出してパースする（堅牢版）

        対応するケース:
        - ```json ... ``` コードブロック囲み
        - 前後の説明テキスト
        - // コメント
        - 末尾カンマ (trailing commas)
        - 配列要素間の欠落カンマ (missing commas between } and {)
        """
        import re

        def remove_line_comments(s: str) -> str:
            """// コメントを除去（文字列リテラル内は保持）"""
            lines = []
            for line in s.split('\n'):
                in_string = False
                escape_next = False
                for i, ch in enumerate(line):
                    if escape_next:
                        escape_next = False
                        continue
                    if ch == '\\' and in_string:
                        escape_next = True
                        continue
                    if ch == '"':
                        in_string = not in_string
                        continue
                    if ch == '/' and not in_string and i + 1 < len(line) and line[i + 1] == '/':
                        line = line[:i].rstrip()
                        break
                lines.append(line)
            return '\n'.join(lines)

        def repair_json(s: str) -> str:
            """よくある AI 生成 JSON の破損を修復"""
            def close_unterminated_string_and_brackets(text: str) -> str:
                """未終了の文字列や括弧を閉じる（レスポンス途中切れ対策）"""
                stack: List[str] = []
                in_string = False
                escape_next = False

                for ch in text:
                    if escape_next:
                        escape_next = False
                        continue
                    if in_string:
                        if ch == '\\':
                            escape_next = True
                        elif ch == '"':
                            in_string = False
                        continue

                    if ch == '"':
                        in_string = True
                    elif ch in '{[':
                        stack.append(ch)
                    elif ch == '}' and stack and stack[-1] == '{':
                        stack.pop()
                    elif ch == ']' and stack and stack[-1] == '[':
                        stack.pop()

                if in_string:
                    text += '"'

                while stack:
                    opener = stack.pop()
                    text += '}' if opener == '{' else ']'
                return text

            # 末尾カンマを除去: {"a":1,} → {"a":1}
            s = re.sub(r',\s*([}\]])', r'\1', s)
            # 配列要素間の欠落カンマを補完: }\n{ → },\n{
            s = re.sub(r'([}\]])\s*\n(\s*)([{\[])', r'\1,\n\2\3', s)
            # 途中で切れたJSONの未終了要素を補完
            s = close_unterminated_string_and_brackets(s)
            return s

        text = text.strip()

        # Step 1: コードブロック除去（```json / ``` など）
        text = re.sub(r'^```[a-zA-Z]*\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
        text = text.strip()

        # Step 2: そのままパース
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Step 3: 前後テキストを除去して JSON 部分だけ抽出
        match = re.search(r'\{[\s\S]*\}|\[[\s\S]*\]', text)
        if match:
            candidate = match.group(0)
        else:
            object_pos = text.find('{')
            array_pos = text.find('[')
            starts = [pos for pos in (object_pos, array_pos) if pos >= 0]
            candidate = text[min(starts):] if starts else text

        # Step 4: // コメント除去 → パース
        candidate = remove_line_comments(candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # Step 5: 末尾カンマ + 欠落カンマ修復 → パース
        repaired = repair_json(candidate)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        # Step 6: 修復を2回適用（ネストが深い場合）→ 最終試行（失敗時は例外を伝播）
        repaired = repair_json(repaired)
        return json.loads(repaired)

    def _parse_json_with_regeneration(self, operation_name: str, generate_text_func, max_attempts: int) -> Any:
        """JSON 解析失敗時に AI 再生成して再試行する

        空レスポンス・不正JSON・生成エラーのいずれも再試行対象とする。
        """
        last_error: Optional[Exception] = None
        last_text = ""
        for attempt in range(1, max_attempts + 1):
            try:
                result_text = generate_text_func()
            except Exception as gen_error:
                # 生成自体のエラー（API障害など）も再試行対象
                last_error = gen_error
                if attempt < max_attempts:
                    logger.warning(
                        "%s: AI生成エラー。再生成を実行します (%d/%d): %s",
                        operation_name, attempt, max_attempts, str(gen_error)[:200]
                    )
                    continue
                else:
                    logger.error(
                        "%s: AI生成エラー。再試行上限に到達: %s",
                        operation_name, str(gen_error)[:200]
                    )
                    raise gen_error

            last_text = result_text

            # 空レスポンスのチェック（JSONDecodeError より先に検知）
            if not result_text or not result_text.strip():
                last_error = json.JSONDecodeError("AI returned empty response", "", 0)
                if attempt < max_attempts:
                    logger.warning(
                        "%s: AI応答が空です。再生成を実行します (%d/%d)",
                        operation_name, attempt, max_attempts
                    )
                    continue
                else:
                    logger.error(
                        "%s: AI応答が空のまま再試行上限に到達",
                        operation_name
                    )
                    raise last_error

            try:
                return self._extract_json(result_text)
            except json.JSONDecodeError as e:
                last_error = e
                if attempt < max_attempts:
                    logger.warning(
                        "%s: AI応答のJSON解析失敗。再生成を実行します (%d/%d): %s (response=%s)",
                        operation_name, attempt, max_attempts, e, result_text[:600]
                    )
                else:
                    logger.error(
                        "%s: AI応答のJSON解析失敗。再試行上限に到達: %s (response=%s)",
                        operation_name, e, result_text[:600]
                    )
        raise last_error if last_error else json.JSONDecodeError("empty response", last_text, 0)

    def _build_fallback_classification(self) -> Dict[str, Any]:
        """分類失敗時の保底結果"""
        return {
            "category": "その他",
            "confidence": 0.0,
            "description": "AI応答の解析に失敗したため、保底分類を適用しました",
            "has_line_items": False,
            "is_fallback": True,
            "success": True,
        }

    def _get_text_from_chat_response(self, chat_response: Any) -> str:
        """ChatResponse からテキストを連結抽出"""
        if not hasattr(chat_response, "choices") or not chat_response.choices:
            return ""

        message = chat_response.choices[0].message
        if not hasattr(message, "content") or not message.content:
            return ""

        text = ""
        for part in message.content:
            if hasattr(part, "text") and part.text:
                text += part.text
        return text

    def _get_tool_arguments_from_chat_response(self, chat_response: Any, function_name: str = "") -> str:
        """Assistant tool_calls から function arguments(JSON文字列)を抽出"""
        if not hasattr(chat_response, "choices") or not chat_response.choices:
            return ""

        message = chat_response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        for tool_call in tool_calls:
            name = getattr(tool_call, "name", "")
            arguments = getattr(tool_call, "arguments", "")
            if function_name and name != function_name:
                continue
            if isinstance(arguments, str) and arguments.strip():
                return arguments
            if isinstance(arguments, dict):
                return json.dumps(arguments, ensure_ascii=False)
        return ""

    def _build_classification_tool_schema(self) -> Dict[str, Any]:
        """分類出力のJSON Schema"""
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [
                        "請求書", "納品書", "領収書", "注文書", "見積書", "発注書", "仕入伝票", "売上伝票",
                        "出荷伝票", "入荷伝票", "支払伝票", "入金伝票", "振替伝票", "経費精算書", "検収書", "その他"
                    ],
                },
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "description": {"type": "string", "maxLength": 120},
                "has_line_items": {"type": "boolean"},
            },
            "required": ["category", "confidence", "description", "has_line_items"],
            "additionalProperties": False,
        }

    def _build_repair_prompt_for_classification(self, malformed_payload: str) -> str:
        """分類JSON修復専用プロンプト（第2フェーズ）"""
        payload = (malformed_payload or "").strip()[:4000]
        return f"""あなたはJSON修復エージェントです。以下の壊れた出力を、分類用の有効なJSON 1つに修復してください。
説明文、コードブロック、コメントは禁止です。JSONのみ返してください。

必須スキーマ:
{{
  "category": "請求書|納品書|領収書|注文書|見積書|発注書|仕入伝票|売上伝票|出荷伝票|入荷伝票|支払伝票|入金伝票|振替伝票|経費精算書|検収書|その他",
  "confidence": 0.0-1.0 の数値,
  "description": "文字列",
  "has_line_items": true|false
}}

壊れた出力:
{payload}
"""

    def _normalize_classification_result(self, parsed: Any) -> Dict[str, Any]:
        """分類結果を検証・正規化し、不正なら保底結果を返す"""
        def coerce_bool(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes", "y", "on"}:
                    return True
                if normalized in {"false", "0", "no", "n", "off", ""}:
                    return False
                return False
            if isinstance(value, (int, float)):
                return value != 0
            return False

        if not isinstance(parsed, dict):
            logger.warning("分類結果が辞書形式ではないため保底分類を返却します")
            return self._build_fallback_classification()

        category = parsed.get("category")
        description = parsed.get("description")
        if not isinstance(category, str) or not category.strip() or not isinstance(description, str):
            logger.warning("分類結果の必須項目が不正のため保底分類を返却します: %s", parsed)
            return self._build_fallback_classification()

        confidence = parsed.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        confidence = max(0.0, min(1.0, float(confidence)))

        has_line_items = parsed.get("has_line_items", False)
        has_line_items = coerce_bool(has_line_items)

        parsed["category"] = category.strip()
        parsed["description"] = description
        parsed["confidence"] = confidence
        parsed["has_line_items"] = has_line_items
        parsed["is_fallback"] = False
        parsed["success"] = True
        return parsed

    def _build_image_content(self, image_data: bytes, content_type: str = "image/jpeg") -> Dict[str, Any]:
        """画像データからOCI GenAI用のコンテンツブロックを構築"""
        import base64
        encoded = base64.b64encode(image_data).decode("ascii")
        return {
            "type": "IMAGE",
            "imageUrl": {
                "url": f"data:{content_type};base64,{encoded}"
            }
        }

    def classify_invoice(self, image_data: bytes, content_type: str = "image/jpeg") -> Dict[str, Any]:
        """伝票画像を分類する

        Args:
            image_data: 画像のバイトデータ
            content_type: MIMEタイプ

        Returns:
            分類結果 (category, confidence, description)
        """
        client = self._get_client()
        if not client:
            return {"success": False, "message": "AI クライアントが初期化されていません"}

        prompt = """あなたは日本語業務文書（帳票）の分析を専門とするエキスパートです。
提示された画像が日本企業の業務伝票であることを前提に、文書種別を正確に判定してください。

【判定カテゴリ】（以下のいずれか1つを選択）
請求書 / 納品書 / 領収書 / 注文書 / 見積書 / 発注書 /
仕入伝票 / 売上伝票 / 出荷伝票 / 入荷伝票 / 支払伝票 /
入金伝票 / 振替伝票 / 経費精算書 / 検収書 / その他

【判定手順】
1. 文書タイトル・ヘッダー記載を最優先で参照する
2. タイトルが判読不能な場合は、記載内容・フォーム構成から推定する
3. 上記16種に合致しない場合のみ「その他」を選択する

【confidence（確信度）の基準】
- 0.95〜1.00: タイトルが明示されており疑いなし
- 0.80〜0.94: タイトルはないが内容・構成から確実に判断できる
- 0.60〜0.79: 複数種別の可能性があるが最有力を選択
- 0.40〜0.59: 画像が不鮮明または一部のみ視認可能で推定
- 0.00〜0.39: ほぼ判断不能（この場合は category を「その他」にする）

【has_line_items の判定】
- true: 品番・品名・数量・単価・金額等の列を持つ「明細行テーブル」が文書内に存在する
- false: 明細行テーブルがなく、ヘッダー情報のみで構成された文書

【出力規則】
以下のJSON 1行のみを返してください。説明文・マークダウン（```）・コメント（//）は禁止です。
{"category": "請求書", "confidence": 0.95, "description": "製品の購入代金を請求する文書", "has_line_items": true}

- description: この文書の用途・内容を40字以内で簡潔に記述する"""

        try:
            import oci
            image_content = self._build_image_content(image_data, content_type)
            text_content = {"type": "TEXT", "text": prompt}

            function_name = "set_invoice_classification"
            schema = self._build_classification_tool_schema()

            structured_chat_request = oci.generative_ai_inference.models.GenericChatRequest(
                api_format="GENERIC",
                messages=[
                    oci.generative_ai_inference.models.UserMessage(
                        content=[image_content, text_content]
                    )
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                is_stream=False,
                tools=[
                    oci.generative_ai_inference.models.FunctionDefinition(
                        name=function_name,
                        description="伝票画像の分類結果を返却する",
                        parameters=schema,
                    )
                ],
                tool_choice=oci.generative_ai_inference.models.ToolChoiceFunction(
                    name=function_name
                ),
            )

            fallback_chat_request = oci.generative_ai_inference.models.GenericChatRequest(
                api_format="GENERIC",
                messages=[
                    oci.generative_ai_inference.models.UserMessage(
                        content=[image_content, text_content]
                    )
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                is_stream=False,
            )

            structured_chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=self._compartment_id,
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                    model_id=self._vlm_model_id
                ),
                chat_request=structured_chat_request,
            )

            fallback_chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=self._compartment_id,
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                    model_id=self._vlm_model_id
                ),
                chat_request=fallback_chat_request,
            )

            state = {
                "structured_supported": True,
                "repair_structured_supported": True,
                "last_payload": "",
            }

            def generate_text() -> str:
                if state["structured_supported"]:
                    try:
                        response = self._retry_api_call(
                            "classify_invoice_structured",
                            client.chat,
                            structured_chat_detail
                        )
                        chat_response = response.data.chat_response
                        payload = self._get_tool_arguments_from_chat_response(chat_response, function_name)
                        if not payload:
                            payload = self._get_text_from_chat_response(chat_response)
                        # 空レスポンスの検出とログ出力
                        if not payload or not payload.strip():
                            logger.warning(
                                "classify_invoice_structured: 構造化出力が空。chat_response=%s",
                                getattr(chat_response, '__dict__', str(chat_response))[:500]
                            )
                        state["last_payload"] = payload
                        return payload
                    except Exception as e:
                        # モデル/リージョンが tool calling 非対応の場合は通常生成へフォールバック
                        state["structured_supported"] = False
                        logger.warning("構造化出力モードを無効化して通常モードへ切替: %s", str(e)[:200])

                response = self._retry_api_call("classify_invoice", client.chat, fallback_chat_detail)
                chat_response = response.data.chat_response
                payload = self._get_text_from_chat_response(chat_response)
                # 空レスポンスの検出とログ出力
                if not payload or not payload.strip():
                    logger.warning(
                        "classify_invoice: テキスト出力が空。chat_response=%s",
                        getattr(chat_response, '__dict__', str(chat_response))[:500]
                    )
                state["last_payload"] = payload
                return payload

            def generate_repair_text() -> str:
                repair_prompt = self._build_repair_prompt_for_classification(state["last_payload"])
                repair_text_request = oci.generative_ai_inference.models.GenericChatRequest(
                    api_format="GENERIC",
                    messages=[
                        oci.generative_ai_inference.models.UserMessage(
                            content=[{"type": "TEXT", "text": repair_prompt}]
                        )
                    ],
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    is_stream=False,
                )
                repair_structured_request = oci.generative_ai_inference.models.GenericChatRequest(
                    api_format="GENERIC",
                    messages=[
                        oci.generative_ai_inference.models.UserMessage(
                            content=[{"type": "TEXT", "text": repair_prompt}]
                        )
                    ],
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    is_stream=False,
                    tools=[
                        oci.generative_ai_inference.models.FunctionDefinition(
                            name=function_name,
                            description="壊れた分類JSONを修復して返却する",
                            parameters=schema,
                        )
                    ],
                    tool_choice=oci.generative_ai_inference.models.ToolChoiceFunction(
                        name=function_name
                    ),
                )
                repair_text_detail = oci.generative_ai_inference.models.ChatDetails(
                    compartment_id=self._compartment_id,
                    serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                        model_id=self._vlm_model_id
                    ),
                    chat_request=repair_text_request,
                )
                repair_structured_detail = oci.generative_ai_inference.models.ChatDetails(
                    compartment_id=self._compartment_id,
                    serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                        model_id=self._vlm_model_id
                    ),
                    chat_request=repair_structured_request,
                )

                if state["repair_structured_supported"]:
                    try:
                        response = self._retry_api_call(
                            "classify_invoice_repair_structured",
                            client.chat,
                            repair_structured_detail
                        )
                        chat_response = response.data.chat_response
                        payload = self._get_tool_arguments_from_chat_response(chat_response, function_name)
                        if not payload:
                            payload = self._get_text_from_chat_response(chat_response)
                        # 空レスポンスの検出とログ出力
                        if not payload or not payload.strip():
                            logger.warning(
                                "classify_invoice_repair_structured: 修復出力が空。chat_response=%s",
                                getattr(chat_response, '__dict__', str(chat_response))[:500]
                            )
                        state["last_payload"] = payload
                        return payload
                    except Exception as e:
                        state["repair_structured_supported"] = False
                        logger.warning("修復フェーズの構造化モードを無効化して通常モードへ切替: %s", str(e)[:200])

                response = self._retry_api_call("classify_invoice_repair", client.chat, repair_text_detail)
                chat_response = response.data.chat_response
                payload = self._get_text_from_chat_response(chat_response)
                # 空レスポンスの検出とログ出力
                if not payload or not payload.strip():
                    logger.warning(
                        "classify_invoice_repair: 修復テキスト出力が空。chat_response=%s",
                        getattr(chat_response, '__dict__', str(chat_response))[:500]
                    )
                state["last_payload"] = payload
                return payload

            try:
                parsed = self._parse_json_with_regeneration(
                    "classify_invoice",
                    generate_text,
                    GENAI_JSON_PARSE_RETRIES
                )
            except json.JSONDecodeError as e:
                logger.warning("第1フェーズ失敗。第2フェーズ(JSON修復)を実行: %s", e)
                try:
                    parsed = self._parse_json_with_regeneration(
                        "classify_invoice_repair",
                        generate_repair_text,
                        GENAI_RECOVERY_MAX_RETRIES
                    )
                except Exception as repair_error:
                    logger.warning("第2フェーズも失敗。保底分類へフォールバック: %s", repair_error)
                    return self._build_fallback_classification()

            return self._normalize_classification_result(parsed)
        except Exception as e:
            logger.error("伝票分類エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"分類失敗: {str(e)}"}

    def extract_fields(
        self,
        image_data: bytes,
        category: str = "",
        content_type: str = "image/jpeg",
        table_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """伝票画像からフィールド情報を抽出する

        Args:
            image_data: 画像のバイトデータ
            category: 伝票の種別（分類結果から）
            content_type: MIMEタイプ
            table_schema: カテゴリのテーブル構造情報

        Returns:
            抽出結果 (header_fields, line_fields)
        """
        client = self._get_client()
        if not client:
            return {"success": False, "message": "AI クライアントが初期化されていません"}

        category_hint = f"この伝票の種別は「{category}」です。" if category else ""

        # ── スキーマ情報のフォーマット ────────────────────────────────────────
        def _fmt_cols(columns: list) -> str:
            if not columns:
                return "  （定義なし）"
            lines = []
            for col in columns:
                comment = col.get("comment", "")
                comment_str = f"  -- {comment}" if comment else ""
                dt = col.get("data_type", "VARCHAR2")
                length = col.get("data_length")
                if dt == "VARCHAR2" and length:
                    type_str = f"VARCHAR2({length})"
                elif dt == "NUMBER":
                    prec = col.get("precision")
                    scale = col.get("scale")
                    if prec and scale is not None:
                        type_str = f"NUMBER({prec},{scale})"
                    elif prec:
                        type_str = f"NUMBER({prec})"
                    else:
                        type_str = "NUMBER"
                else:
                    type_str = dt
                lines.append(f"  {col['column_name']}  {type_str}{comment_str}")
            return "\n".join(lines)

        # ── モード分岐：テーブルスキーマの有無で目的が異なる ──────────────────
        if table_schema:
            # ================================================================
            # ■ データ抽出モード（本登録用伝票）
            #   目的: 定義済みDBテーブルの各カラムに対応する値を画像から正確に読む
            # ================================================================
            header_cols_fmt = _fmt_cols(table_schema.get("header_columns", []))
            line_cols_fmt = _fmt_cols(table_schema.get("line_columns", []))
            header_tbl = table_schema.get("header_table_name", "")
            line_tbl = table_schema.get("line_table_name", "")
            has_line_tbl = bool(line_tbl and table_schema.get("line_columns"))

            prompt = f"""あなたはOracleデータベースへの伝票データ登録を専門とするデータ入力エキスパートです。
提示された伝票画像から、定義済みDBテーブルの各カラムに対応する値を正確に読み取り、JSONで返してください。
{category_hint}

【対象テーブル構造】（カラム名・データ型は厳守。右側の -- が日本語ラベル）
▶ HEADERテーブル: {header_tbl}
{header_cols_fmt}

▶ LINEテーブル: {line_tbl if has_line_tbl else '（明細なし）'}
{line_cols_fmt if has_line_tbl else '  （定義なし）'}

【値読み取りルール】
1. 各カラムの日本語ラベル（-- 以降）に対応する項目を画像内で探し、値を転記する
2. 数値（金額・数量・単価）: 桁区切りカンマ・通貨記号を除去した数字文字列（例: "¥1,234,567" → "1234567"）
3. 日付: ISO 8601形式 YYYY-MM-DD（例: "令和6年1月15日" → "2024-01-15"）
4. テキスト: 画像の文字をそのまま転記。手書き等で判読不能な場合は ""
5. 画像に該当項目が存在しない場合: "" （null は使わない）
6. スキーマに存在する全カラムを header_fields に出力する（値がなくても省略禁止）

【カラム名の厳守】
- header_fields[].field_name_en: 必ず HEADERテーブルの COLUMN_NAME をそのまま使用（UPPERCASE、変名・追加・省略禁止）
- raw_lines[] のキー: 必ず LINEテーブルの COLUMN_NAME をそのまま使用（UPPERCASE）
- スキーマに存在しないカラム名は絶対に作成しない

【出力形式】（JSON のみ。マークダウン・コードブロック・コメント禁止）
{{
  "header_fields": [
    {{"field_name": "請求書番号", "field_name_en": "INVOICE_NO", "value": "INV-2024-001", "data_type": "VARCHAR2", "max_length": 50, "is_required": true}},
    {{"field_name": "請求日", "field_name_en": "INVOICE_DATE", "value": "2024-01-15", "data_type": "DATE", "max_length": null, "is_required": true}},
    {{"field_name": "請求金額合計", "field_name_en": "TOTAL_AMOUNT", "value": "110000", "data_type": "NUMBER", "max_length": null, "is_required": true}}
  ],
  "line_fields": [
    {{"field_name": "品名", "field_name_en": "ITEM_NAME", "value": "製品A", "data_type": "VARCHAR2", "max_length": 200, "is_required": true}},
    {{"field_name": "数量", "field_name_en": "QUANTITY", "value": "10", "data_type": "NUMBER", "max_length": null, "is_required": true}}
  ],
  "line_count": 2,
  "raw_lines": [
    {{"ITEM_NAME": "製品A", "QUANTITY": "10", "UNIT_PRICE": "5000", "AMOUNT": "50000"}},
    {{"ITEM_NAME": "製品B", "QUANTITY": "5", "UNIT_PRICE": "8000", "AMOUNT": "40000"}}
  ]
}}

各フィールドの説明:
- header_fields: HEADERテーブルの全カラムに対応するエントリ（省略禁止）
  - field_name: カラムの日本語ラベル（コメントから取得。コメントなしはカラム名から推測）
  - field_name_en: HEADERテーブルの COLUMN_NAME（UPPERCASE、厳守）
  - value: 画像から読み取った値（文字列。空欄・不存在は ""）
  - data_type: HEADERテーブルのカラム定義に従う
  - max_length: VARCHAR2 の場合は定義の数値、それ以外は null
  - is_required: カラムが NOT NULL なら true、NULLABLE なら false
- line_fields: LINEテーブルのカラム定義（明細なしは []）
- line_count: 実際の明細行数（整数。明細なしは 0）
- raw_lines: 各明細行の実データ配列。キーは LINEテーブルの COLUMN_NAME（明細なしは []）

出力は有効なJSON1つのみ。```や//や説明文を含めないこと。"""

        else:
            # ================================================================
            # ■ スキーマ設計モード（分類用サンプル伝票）
            #   目的: 伝票画像から最適なOracleテーブル構造を発見・設計する
            # ================================================================
            prompt = f"""あなたはOracle Database設計と日本語業務文書処理を専門とするエキスパートです。
提示された伝票画像を解析し、Oracle DBに登録するための最適なテーブル構造を設計してください。
{category_hint}

【設計方針】
ヘッダー部（1伝票=1レコードのマスター情報）と明細部（複数行の繰り返しデータ）を分離して設計します。
明細テーブルが不要な場合（領収書・単行伝票等）は line_fields と raw_lines を空配列にします。

【フィールド抽出の完全性】
- 画像内の印字済み項目・手書き記入欄・空欄ラベルを全て漏れなく抽出する
- 伝票番号・日付・取引先など管理項目は必ず含める
- 合計・小計・消費税額・税率などの集計項目も全て含める
- 承認印・受領印・担当者名・部署名などの運用管理項目も含める
- 備考・摘要・特記事項欄も含める

【Oracleカラム設計基準】
▶ field_name_en（カラム名）: 英語UPPERCASE + アンダースコア区切り
  例: INVOICE_NO, CUSTOMER_NAME, TOTAL_AMOUNT, ISSUE_DATE
  Oracle 12c互換のため30文字以内を強く推奨する

▶ データ型の選択:
  - VARCHAR2: 文字列・コード・番号類・名称・住所・メモ・承認印
    （「003」等の先頭ゼロを保持する必要があるコード・番号は VARCHAR2 を選択）
  - NUMBER: 計算・集計対象の純粋な数値のみ（金額・数量・単価・税率・個数）
  - DATE: 日付（時刻を含む場合も DATE で可）

▶ VARCHAR2の max_length（文字数）目安:
  コード・番号: 50 / 氏名・担当者名: 100 / 会社名・部署名: 200 / 住所: 300 /
  品名・件名・商品名: 200 / 電話番号・FAX: 20 / メールアドレス: 200 /
  備考・摘要・特記事項: 500 / その他テキスト: 100

▶ is_required の判定:
  - true: 常に印字・記入される必須項目（伝票番号・日付・取引先・合計金額等）
  - false: 状況により空欄になりうる任意項目

【出力形式】（JSON のみ。マークダウン・コードブロック・コメント禁止）
{{
  "header_fields": [
    {{"field_name": "請求書番号", "field_name_en": "INVOICE_NO", "value": "INV-2024-001", "data_type": "VARCHAR2", "max_length": 50, "is_required": true}},
    {{"field_name": "請求日", "field_name_en": "INVOICE_DATE", "value": "2024-01-15", "data_type": "DATE", "max_length": null, "is_required": true}},
    {{"field_name": "取引先名", "field_name_en": "CUSTOMER_NAME", "value": "株式会社サンプル", "data_type": "VARCHAR2", "max_length": 200, "is_required": true}},
    {{"field_name": "請求金額合計", "field_name_en": "TOTAL_AMOUNT", "value": "110000", "data_type": "NUMBER", "max_length": null, "is_required": true}},
    {{"field_name": "消費税額", "field_name_en": "TAX_AMOUNT", "value": "10000", "data_type": "NUMBER", "max_length": null, "is_required": false}}
  ],
  "line_fields": [
    {{"field_name": "品名", "field_name_en": "ITEM_NAME", "value": "製品A", "data_type": "VARCHAR2", "max_length": 200, "is_required": true}},
    {{"field_name": "数量", "field_name_en": "QUANTITY", "value": "10", "data_type": "NUMBER", "max_length": null, "is_required": true}},
    {{"field_name": "単価", "field_name_en": "UNIT_PRICE", "value": "5000", "data_type": "NUMBER", "max_length": null, "is_required": true}},
    {{"field_name": "金額", "field_name_en": "AMOUNT", "value": "50000", "data_type": "NUMBER", "max_length": null, "is_required": true}}
  ],
  "line_count": 2,
  "raw_lines": [
    {{"ITEM_NAME": "製品A", "QUANTITY": "10", "UNIT_PRICE": "5000", "AMOUNT": "50000"}},
    {{"ITEM_NAME": "製品B", "QUANTITY": "5", "UNIT_PRICE": "8000", "AMOUNT": "40000"}}
  ]
}}

各フィールドの説明:
- header_fields: 伝票ヘッダーの全項目（番号・日付・取引先・金額・税額・承認欄・備考など）
  - field_name: 日本語ラベル（簡潔な名称。例: 「請求書番号」「取引先名」）
  - field_name_en: Oracleカラム名（UPPERCASE、30字以内推奨）
  - value: 画像から読み取った代表的なサンプル値（空欄・不読は ""）
  - data_type: "VARCHAR2" / "NUMBER" / "DATE" のいずれか
  - max_length: VARCHAR2 の場合は整数値、NUMBER / DATE の場合は null
  - is_required: true（必須）/ false（任意）
- line_fields: 明細テーブルのカラム定義（明細なしは []）
- line_count: 画像内の実際の明細行数（整数。明細なしは 0）
- raw_lines: 各明細行の実データ配列。キーは field_name_en と一致させること（明細なしは []）

出力は有効なJSON1つのみ。```や//や説明文を含めないこと。"""

        try:
            import oci
            image_content = self._build_image_content(image_data, content_type)
            text_content = {"type": "TEXT", "text": prompt}

            chat_request = oci.generative_ai_inference.models.GenericChatRequest(
                api_format="GENERIC",
                messages=[
                    oci.generative_ai_inference.models.UserMessage(
                        content=[image_content, text_content]
                    )
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                is_stream=False,
            )

            chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=self._compartment_id,
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                    model_id=self._vlm_model_id
                ),
                chat_request=chat_request,
            )

            def generate_text() -> str:
                response = self._retry_api_call("extract_fields", client.chat, chat_detail)
                return self._get_text_from_chat_response(response.data.chat_response)

            parsed = self._parse_json_with_regeneration(
                "extract_fields",
                generate_text,
                GENAI_JSON_PARSE_RETRIES
            )

            if not isinstance(parsed, dict):
                return {"success": False, "message": "AI応答形式が不正です"}

            header_fields = parsed.get("header_fields")
            line_fields = parsed.get("line_fields")
            raw_lines = parsed.get("raw_lines")
            line_count = parsed.get("line_count")

            if not isinstance(header_fields, list):
                header_fields = []
            if not isinstance(line_fields, list):
                line_fields = []
            if not isinstance(raw_lines, list):
                raw_lines = []
            if not isinstance(line_count, int):
                line_count = len(raw_lines)

            parsed["header_fields"] = header_fields
            parsed["line_fields"] = line_fields
            parsed["raw_lines"] = raw_lines
            parsed["line_count"] = line_count
            parsed["success"] = True
            return parsed

        except Exception as e:
            logger.error("フィールド抽出エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"フィールド抽出失敗: {str(e)}"}

    def extract_data_from_text(
        self,
        ocr_text: str,
        category: str = "",
        table_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """OCR抽出テキストからフィールド情報を抽出する

        Args:
            ocr_text: OCR抽出されたテキスト
            category: 伝票の種別（分類結果から）
            table_schema: カテゴリのテーブル構造情報

        Returns:
            抽出結果 (header_fields, line_fields)
        """
        client = self._get_client()
        if not client:
            return {"success": False, "message": "AI クライアントが初期化されていません"}

        if not table_schema:
            return {"success": False, "message": "テーブルスキーマ情報が必要です"}

        category_hint = f"この伝票の種別は「{category}」です。" if category else ""

        # ── スキーマ情報のフォーマット ────────────────────────────────────────
        def _fmt_cols(columns: list) -> str:
            if not columns:
                return "  （定義なし）"
            lines = []
            for col in columns:
                comment = col.get("comment", "")
                comment_str = f"  -- {comment}" if comment else ""
                dt = col.get("data_type", "VARCHAR2")
                length = col.get("data_length")
                if dt == "VARCHAR2" and length:
                    type_str = f"VARCHAR2({length})"
                elif dt == "NUMBER":
                    prec = col.get("precision")
                    scale = col.get("scale")
                    if prec and scale is not None:
                        type_str = f"NUMBER({prec},{scale})"
                    elif prec:
                        type_str = f"NUMBER({prec})"
                    else:
                        type_str = "NUMBER"
                else:
                    type_str = dt
                lines.append(f"  {col['column_name']}  {type_str}{comment_str}")
            return "\n".join(lines)

        header_cols_fmt = _fmt_cols(table_schema.get("header_columns", []))
        line_cols_fmt = _fmt_cols(table_schema.get("line_columns", []))
        header_tbl = table_schema.get("header_table_name", "")
        line_tbl = table_schema.get("line_table_name", "")
        has_line_tbl = bool(line_tbl and table_schema.get("line_columns"))

        prompt = f"""あなたはOracleデータベースへの伝票データ登録を専門とするデータ入力エキスパートです。
以下のOCR抽出テキストから、定義済みDBテーブルの各カラムに対応する値を正確に読み取り、JSONで返してください。
{category_hint}

【OCR抽出テキスト】
{ocr_text}

【対象テーブル構造】（カラム名・データ型は厳守。右側の -- が日本語ラベル）
▶ HEADERテーブル: {header_tbl}
{header_cols_fmt}

▶ LINEテーブル: {line_tbl if has_line_tbl else '（明細なし）'}
{line_cols_fmt if has_line_tbl else '  （定義なし）'}

【値読み取りルール】
1. 各カラムの日本語ラベル（-- 以降）に対応する項目をテキスト内で探し、値を転記する
2. 数値（金額・数量・単価）: 桁区切りカンマ・通貨記号を除去した数字文字列（例: "¥1,234,567" → "1234567"）
3. 日付: ISO 8601形式 YYYY-MM-DD（例: "令和6年1月15日" → "2024-01-15"）
4. テキスト: OCRテキストの文字をそのまま転記。
5. テキストに該当項目が存在しない場合: "" （null は使わない）
6. スキーマに存在する全カラムを header_fields に出力する（値がなくても省略禁止）

【カラム名の厳守】
- header_fields[].field_name_en: 必ず HEADERテーブルの COLUMN_NAME をそのまま使用（UPPERCASE、変名・追加・省略禁止）
- raw_lines[] のキー: 必ず LINEテーブルの COLUMN_NAME をそのまま使用（UPPERCASE）
- スキーマに存在しないカラム名は絶対に作成しない

【出力形式】（JSON のみ。マークダウン・コードブロック・コメント禁止）
{{
  "header_fields": [
    {{"field_name": "請求書番号", "field_name_en": "INVOICE_NO", "value": "INV-2024-001", "data_type": "VARCHAR2", "max_length": 50, "is_required": true}},
    {{"field_name": "請求日", "field_name_en": "INVOICE_DATE", "value": "2024-01-15", "data_type": "DATE", "max_length": null, "is_required": true}},
    {{"field_name": "請求金額合計", "field_name_en": "TOTAL_AMOUNT", "value": "110000", "data_type": "NUMBER", "max_length": null, "is_required": true}}
  ],
  "line_fields": [
    {{"field_name": "品名", "field_name_en": "ITEM_NAME", "value": "製品A", "data_type": "VARCHAR2", "max_length": 200, "is_required": true}},
    {{"field_name": "数量", "field_name_en": "QUANTITY", "value": "10", "data_type": "NUMBER", "max_length": null, "is_required": true}}
  ],
  "line_count": 2,
  "raw_lines": [
    {{"ITEM_NAME": "製品A", "QUANTITY": "10", "UNIT_PRICE": "5000", "AMOUNT": "50000"}},
    {{"ITEM_NAME": "製品B", "QUANTITY": "5", "UNIT_PRICE": "8000", "AMOUNT": "40000"}}
  ]
}}

各フィールドの説明:
- header_fields: HEADERテーブルの全カラムに対応するエントリ（省略禁止）
  - field_name: カラムの日本語ラベル（コメントから取得。コメントなしはカラム名から推測）
  - field_name_en: HEADERテーブルの COLUMN_NAME（UPPERCASE、厳守）
  - value: テキストから読み取った値（文字列。空欄・不存在は ""）
  - data_type: HEADERテーブルのカラム定義に従う
  - max_length: VARCHAR2 の場合は定義の数値、それ以外は null
  - is_required: カラムが NOT NULL なら true、NULLABLE なら false
- line_fields: LINEテーブルのカラム定義（明細なしは []）
- line_count: 実際の明細行数（整数。明細なしは 0）
- raw_lines: 各明細行の実データ配列。キーは LINEテーブルの COLUMN_NAME（明細なしは []）

出力は有効なJSON1つのみ。```や//や説明文を含めないこと。"""

        try:
            import oci
            
            text_content = {"type": "TEXT", "text": prompt}

            chat_request = oci.generative_ai_inference.models.GenericChatRequest(
                api_format="GENERIC",
                messages=[
                    oci.generative_ai_inference.models.UserMessage(
                        content=[text_content]
                    )
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                is_stream=False,
            )

            chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=self._compartment_id,
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                    model_id=self._llm_model_id
                ),
                chat_request=chat_request,
            )

            def generate_text() -> str:
                response = self._retry_api_call("extract_data_from_text", client.chat, chat_detail)
                return self._get_text_from_chat_response(response.data.chat_response)

            parsed = self._parse_json_with_regeneration(
                "extract_data_from_text",
                generate_text,
                GENAI_JSON_PARSE_RETRIES
            )

            if not isinstance(parsed, dict):
                return {"success": False, "message": "AI応答形式が不正です"}

            header_fields = parsed.get("header_fields")
            line_fields = parsed.get("line_fields")
            raw_lines = parsed.get("raw_lines")
            line_count = parsed.get("line_count")

            if not isinstance(header_fields, list):
                header_fields = []
            if not isinstance(line_fields, list):
                line_fields = []
            if not isinstance(raw_lines, list):
                raw_lines = []
            if not isinstance(line_count, int):
                line_count = len(raw_lines)

            parsed["header_fields"] = header_fields
            parsed["line_fields"] = line_fields
            parsed["raw_lines"] = raw_lines
            parsed["line_count"] = line_count
            parsed["success"] = True
            return parsed

        except Exception as e:
            logger.error("テキストからのデータ抽出エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"テキストからのデータ抽出失敗: {str(e)}"}


    def extract_text_from_images(self, image_filepaths: List[str]) -> Dict[str, Any]:
        """伝票画像群からVLMを用いてテキストを抽出する"""
        client = self._get_client()
        if not client:
            return {"success": False, "message": "AI クライアントが初期化されていません"}

        prompt = """Extract all text from the image exactly as it appears. 
Preserve the original formatting, layout, line breaks, and structure. 
Output only the extracted text with no additional commentary, explanations, or metadata."""

        try:
            import oci
            import base64
            import mimetypes

            contents = []
            for filepath in image_filepaths:
                if not os.path.exists(filepath):
                    continue
                with open(filepath, "rb") as f:
                    image_data = f.read()
                content_type = mimetypes.guess_type(filepath)[0] or "image/jpeg"
                encoded = base64.b64encode(image_data).decode("ascii")
                contents.append({
                    "type": "IMAGE",
                    "imageUrl": {
                        "url": f"data:{content_type};base64,{encoded}"
                    }
                })

            if not contents:
                return {"success": False, "message": "有効な画像ファイルがありません"}

            contents.append({"type": "TEXT", "text": prompt})

            chat_request = oci.generative_ai_inference.models.GenericChatRequest(
                api_format="GENERIC",
                messages=[
                    oci.generative_ai_inference.models.UserMessage(
                        content=contents
                    )
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                is_stream=False,
            )

            chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=self._compartment_id,
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                    model_id=self._vlm_model_id
                ),
                chat_request=chat_request,
            )

            response = self._retry_api_call("extract_text_from_images", client.chat, chat_detail)
            extracted_text = self._get_text_from_chat_response(response.data.chat_response)
            
            if not extracted_text.strip():
                return {"success": False, "message": "VLMによるテキスト抽出結果が空でした"}

            return {"success": True, "extracted_text": extracted_text}

        except Exception as e:
            logger.error("VLM テキスト抽出エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"テキスト抽出失敗: {str(e)}"}

    def generate_sql_schema_from_text(self, ocr_text: str, analysis_mode: str) -> Dict[str, Any]:
        """OCR抽出されたテキストから、最適なJSONスキーマ（テーブル構造）を提案する"""
        client = self._get_client()
        if not client:
            return {"success": False, "message": "AI クライアントが初期化されていません"}

        header_only_hint = ""
        if analysis_mode == "header_only":
            header_only_hint = "今回はヘッダーのみ（1伝票=1レコード）の設計を求めています。明細テーブル（line_table）は作成せず、line_table_name は空文字列とし、line_columns は空配列にしてください。"
        else:
            header_only_hint = "伝票内に繰り返しの明細行がある場合は、明細テーブル（line_table）を分離して設計してください。ない場合は header のみとしてください。"

        prompt = f"""You are a database schema designer. Analyze the following OCR-extracted text from a Japanese business document (伝票) and design Oracle CREATE TABLE structures to store all the structured information found in it.

## OCR Content:
{ocr_text}

## Requirements:

### 1. Document Type Detection
- First, identify the document type (e.g., 領収書, 請求書, 納品書, 見積書, 注文書, 発注書, etc.).
- Design the table name and structure accordingly.

### 2. Naming Conventions
- **Table name**: Romanized Katakana in UPPERCASE alphabet (e.g., RYOUSHUUSHO for 領収書, SEIKYUUSHO for 請求書, NOUHINNSHO for 納品書).
- **Physical column names**: Romanized Katakana in UPPERCASE alphabet with underscores (e.g., HAKKOOBI for 発行日, GOUKEI_KINGAKU for 合計金額, ATESAKI_MEI for 宛先名).
- **Logical column names**: Japanese (Kanji) via comment (e.g., 発行日, 合計金額).
- Use consistent Hepburn romanization rules (e.g., しょ→SHO, きゅう→KYUU, おう→OU).

### 3. Schema Design Rules
- Choose appropriate Oracle data types: VARCHAR2, NUMBER, DATE, CLOB, etc.
- Make columns NULLABLE unless they are clearly always present.
- Add appropriate length for VARCHAR2 based on the data observed.
- {header_only_hint}

### 4. Capture ALL information present in the document, such as:
- Document metadata (document number, date, type)
- Party information (sender/receiver name, address, phone, registration number)
- Amount summary (subtotal, tax, total)
- Tax breakdown by rate if present
- Line item details if present (item name, quantity, unit price, amount, tax rate)
- Any stamps, notes, remarks, or payment terms

### 5. Output Format
Output ONLY a valid JSON object matching this structure (No explanation or markdown code fences needed):
{{
  "document_type_ja": "請求書",
  "document_type_en": "invoice",
  "header_table_name": "SEIKYUUSHO",
  "line_table_name": "SEIKYUUSHO_MEISAI",
  "header_columns": [
    {{
      "column_name": "HAKKOOBI",
      "comment": "発行日",
      "data_type": "DATE",
      "data_length": null,
      "is_nullable": false
    }},
    {{
       "column_name": "ATESAKI_MEI",
       "comment": "宛先名",
       "data_type": "VARCHAR2",
       "data_length": 100,
       "is_nullable": false
    }}
  ],
  "line_columns": [
    {{
      "column_name": "SHOUHIN_MEI",
      "comment": "商品名",
      "data_type": "VARCHAR2",
      "data_length": 200,
      "is_nullable": false
    }}
  ]
}}
If no line table is needed, set "line_table_name" to "" and "line_columns" to [].
"""

        try:
            import oci
            
            text_content = {"type": "TEXT", "text": prompt}

            chat_request = oci.generative_ai_inference.models.GenericChatRequest(
                api_format="GENERIC",
                messages=[
                    oci.generative_ai_inference.models.UserMessage(
                        content=[text_content]
                    )
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                is_stream=False,
            )

            chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=self._compartment_id,
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                    model_id=self._llm_model_id
                ),
                chat_request=chat_request,
            )

            def generate_text() -> str:
                response = self._retry_api_call("generate_sql_schema_from_text", client.chat, chat_detail)
                return self._get_text_from_chat_response(response.data.chat_response)

            parsed = self._parse_json_with_regeneration(
                "generate_sql_schema_from_text",
                generate_text,
                GENAI_JSON_PARSE_RETRIES
            )

            if not isinstance(parsed, dict):
                return {"success": False, "message": "AI応答形式が不正です"}

            header_columns = parsed.get("header_columns")
            line_columns = parsed.get("line_columns")

            # Map the JSON schema output back to the format expected by the frontend.
            def _to_bool(value: Any, default: bool = True) -> bool:
                if value is None:
                    return default
                if isinstance(value, bool):
                    return value
                if isinstance(value, (int, float)):
                    return bool(value)
                if isinstance(value, str):
                    raw = value.strip().lower()
                    if raw in ("1", "true", "yes", "y", "on"):
                        return True
                    if raw in ("0", "false", "no", "n", "off"):
                        return False
                return default

            def _to_int_or_none(value: Any) -> Optional[int]:
                if value in (None, ""):
                    return None
                try:
                    i = int(value)
                    return i if i > 0 else None
                except Exception:
                    return None

            def _normalize_table_name(name: Any) -> str:
                raw = str(name or "").strip().upper()
                cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in raw).strip("_")
                if not cleaned:
                    return ""
                if not cleaned[0].isalpha():
                    cleaned = f"T_{cleaned}"
                return cleaned[:128]

            def _map_columns(cols):
                if not isinstance(cols, list):
                    return []
                mapped = []
                for c in cols:
                    data_type = str(c.get("data_type", "VARCHAR2")).upper()
                    if data_type not in {"VARCHAR2", "NUMBER", "DATE", "TIMESTAMP", "CLOB"}:
                        data_type = "VARCHAR2"
                    max_length = _to_int_or_none(c.get("data_length")) if data_type == "VARCHAR2" else None

                    mapped.append({
                        "field_name_en": str(c.get("column_name", "")).strip(),
                        "field_name": str(c.get("comment", "")).strip(),
                        "data_type": data_type,
                        "max_length": max_length,
                        "is_required": not _to_bool(c.get("is_nullable"), default=True),
                    })
                return mapped

            mapped_header_fields = _map_columns(header_columns)
            mapped_line_fields = _map_columns(line_columns)
            if analysis_mode == "header_only":
                mapped_line_fields = []

            line_table_name = _normalize_table_name(parsed.get("line_table_name", ""))
            if analysis_mode == "header_only":
                line_table_name = ""

            result = {
                "success": True,
                "document_type_ja": str(parsed.get("document_type_ja", "")).strip(),
                "document_type_en": str(parsed.get("document_type_en", "")).strip().lower(),
                "header_table_name": _normalize_table_name(parsed.get("header_table_name", "")),
                "line_table_name": line_table_name,
                "header_fields": mapped_header_fields,
                "line_fields": mapped_line_fields,
            }
            return result

        except Exception as e:
            logger.error("スキーマ生成エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"スキーマ生成失敗: {str(e)}"}

    def suggest_ddl(self, category: str, header_fields: List[Dict], line_fields: List[Dict]) -> Dict[str, Any]:
        """フィールド情報からテーブルDDLを提案する

        Args:
            category: 伝票種別
            header_fields: ヘッダーフィールド定義
            line_fields: 明細フィールド定義

        Returns:
            DDL提案 (header_ddl, line_ddl, table_prefix)
        """
        client = self._get_client()
        if not client:
            return {"success": False, "message": "AI クライアントが初期化されていません"}

        prompt = f"""以下の伝票フィールド情報に基づいて、Oracle Database用のCREATE TABLE文を生成してください。

伝票種別: {category}

ヘッダーフィールド:
{json.dumps(header_fields, ensure_ascii=False, indent=2)}

明細フィールド:
{json.dumps(line_fields, ensure_ascii=False, indent=2)}

【出力形式】
以下の JSON をそのまま出力してください（説明文・コードブロック・コメントは一切不要）:
{{
  "table_prefix": "INV",
  "header_table_name": "INV_H",
  "line_table_name": "INV_L",
  "header_ddl": "CREATE TABLE INV_H (\\n  ID NUMBER NOT NULL,\\n  ...\\n)",
  "line_ddl": "CREATE TABLE INV_L (\\n  ID NUMBER NOT NULL,\\n  HEADER_ID NUMBER NOT NULL,\\n  ...\\n)"
}}

注意:
- table_prefix: 伝票種別に合わせた英語大文字（例: INV, PO, RCV, SLS）
- header_table_name: ヘッダーテーブル名（table_prefix + "_H"）
- line_table_name: 明細テーブル名（table_prefix + "_L"）
- header_ddl・line_ddl: 改行を \\n でエスケープした CREATE TABLE 文の文字列
- ヘッダーテーブルには ID（NUMBER 主キー）、CREATED_AT（DATE）、FILE_NAME（VARCHAR2(500)）を自動追加
- 明細テーブルには ID（NUMBER 主キー）、HEADER_ID（外部キー）、LINE_NO（NUMBER）を自動追加
- 出力は必ず有効な JSON のみ。前後に説明文・コードブロック（```）・コメント（//）を含めないでください"""

        try:
            import oci
            text_content = {"type": "TEXT", "text": prompt}

            chat_request = oci.generative_ai_inference.models.GenericChatRequest(
                api_format="GENERIC",
                messages=[
                    oci.generative_ai_inference.models.UserMessage(
                        content=[text_content]
                    )
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                is_stream=False,
            )

            chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=self._compartment_id,
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                    model_id=self._llm_model_id
                ),
                chat_request=chat_request,
            )

            response = self._retry_api_call("suggest_ddl", client.chat, chat_detail)

            result_text = ""
            chat_response = response.data.chat_response
            if hasattr(chat_response, "choices") and chat_response.choices:
                message = chat_response.choices[0].message
                if hasattr(message, "content"):
                    for part in message.content:
                        if hasattr(part, "text"):
                            result_text += part.text

            try:
                parsed = self._extract_json(result_text)
            except json.JSONDecodeError as e:
                logger.error("AI応答のJSONパースエラー: %s (response=%s)", e, result_text[:600])
                return {"success": False, "message": f"AI応答の解析に失敗しました: {str(e)}"}
            parsed["success"] = True
            return parsed

        except Exception as e:
            logger.error("DDL提案エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"DDL提案失敗: {str(e)}"}

    def text_to_sql(self, query: str, table_schemas: List[Dict[str, Any]]) -> Dict[str, Any]:
        """自然言語クエリを SELECT 文に変換する

        Args:
            query: ユーザーの自然言語クエリ
            table_schemas: 利用可能なテーブルとカラム情報のリスト
                [{table_name: str, columns: [{column_name, data_type, ...}]}]

        Returns:
            変換結果 (success, sql, explanation)
        """
        client = self._get_client()
        if not client:
            return {"success": False, "message": "AI クライアントが初期化されていません"}

        if not query or not query.strip():
            return {"success": False, "message": "検索クエリが空です"}

        if not table_schemas:
            return {"success": False, "message": "検索可能なテーブルがありません"}

        # スキーマ情報をテキスト形式に変換
        schema_text = ""
        for table in table_schemas:
            table_name = table.get("table_name", "")
            columns = table.get("columns", [])
            if table_name and columns:
                cols_str = ", ".join([
                    f"{c.get('column_name', '')} ({c.get('data_type', '')})"
                    for c in columns
                ])
                schema_text += f"- {table_name}: {cols_str}\n"

        prompt = f"""以下のOracleデータベーステーブルに対して、ユーザーの質問に答えるSELECT文を生成してください。

【利用可能なテーブルとカラム】
{schema_text}

【ユーザーの質問】
{query}

【出力形式】
以下の JSON をそのまま出力してください（説明文・コードブロック・コメントは一切不要）:
{{
  "sql": "SELECT * FROM TABLE_NAME WHERE ...",
  "explanation": "このクエリの説明（日本語）"
}}

制約:
- SELECT 文のみ生成（INSERT, UPDATE, DELETE, DROP などは絶対に禁止）
- 上記に示したテーブルとカラムのみ使用
- Oracle Database 構文に従う（ROWNUM, NVL, TO_CHAR, TO_DATE など使用可）
- sql フィールドの値は SQL 文字列（改行は \\n でエスケープ）
- 出力は必ず有効な JSON のみ。前後に説明文・コードブロック（```）・コメント（//）を含めないでください"""

        try:
            import oci
            text_content = {"type": "TEXT", "text": prompt}

            chat_request = oci.generative_ai_inference.models.GenericChatRequest(
                api_format="GENERIC",
                messages=[
                    oci.generative_ai_inference.models.UserMessage(
                        content=[text_content]
                    )
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                is_stream=False,
            )

            chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=self._compartment_id,
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                    model_id=self._llm_model_id
                ),
                chat_request=chat_request,
            )

            response = self._retry_api_call("text_to_sql", client.chat, chat_detail)

            result_text = ""
            chat_response = response.data.chat_response
            if hasattr(chat_response, "choices") and chat_response.choices:
                message = chat_response.choices[0].message
                if hasattr(message, "content"):
                    for part in message.content:
                        if hasattr(part, "text"):
                            result_text += part.text

            try:
                parsed = self._extract_json(result_text)
            except json.JSONDecodeError as e:
                logger.error("AI応答のJSONパースエラー: %s (response=%s)", e, result_text[:600])
                return {"success": False, "message": f"AI応答の解析に失敗しました: {str(e)}"}
            parsed["success"] = True
            return parsed

        except Exception as e:
            logger.error("Text-to-SQL変換エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"SQL生成に失敗しました: {str(e)}"}
