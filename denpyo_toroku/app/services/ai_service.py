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
        self._llm_model_id = os.environ.get("LLM_MODEL_ID", "google.gemini-2.5-flash")
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
        """JSON 解析失敗時に AI 再生成して再試行する"""
        last_error = None
        last_text = ""
        for attempt in range(1, max_attempts + 1):
            result_text = generate_text_func()
            last_text = result_text
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

        prompt = """あなたは伝票・ビジネス文書の分析専門家です。
この画像に写っている伝票（ビジネス文書）を分類してください。

【分類候補】
請求書 / 納品書 / 領収書 / 注文書 / 見積書 / 発注書 / 仕入伝票 / 売上伝票 /
出荷伝票 / 入荷伝票 / 支払伝票 / 入金伝票 / 振替伝票 / 経費精算書 / 検収書 / その他

【出力形式】
以下の JSON をそのまま出力してください（説明文・コードブロック・コメントは一切不要）:
{
  "category": "請求書",
  "confidence": 0.95,
  "description": "仕入先への支払いを求める文書",
  "has_line_items": true
}

フィールドの説明:
- category: 上記の分類候補から最も近いもの（文字列）
- confidence: 判断の確信度（0.0〜1.0 の数値）
- description: この伝票の内容・用途（40字以内の文字列）
- has_line_items: 品目・明細行テーブルがあれば true、なければ false（Boolean）

出力は必ず有効な JSON のみ。前後に説明文・コードブロック（```）・コメント（//）を含めないでください。"""

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
                max_tokens=1024,
                temperature=0.1,
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
                max_tokens=1024,
                temperature=0.1,
                is_stream=False,
            )

            structured_chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=self._compartment_id,
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                    model_id=self._llm_model_id
                ),
                chat_request=structured_chat_request,
            )

            fallback_chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=self._compartment_id,
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                    model_id=self._llm_model_id
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
                        state["last_payload"] = payload
                        return payload
                    except Exception as e:
                        # モデル/リージョンが tool calling 非対応の場合は通常生成へフォールバック
                        state["structured_supported"] = False
                        logger.warning("構造化出力モードを無効化して通常モードへ切替: %s", str(e)[:200])

                response = self._retry_api_call("classify_invoice", client.chat, fallback_chat_detail)
                chat_response = response.data.chat_response
                payload = self._get_text_from_chat_response(chat_response)
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
                    max_tokens=512,
                    temperature=0.0,
                    is_stream=False,
                )
                repair_structured_request = oci.generative_ai_inference.models.GenericChatRequest(
                    api_format="GENERIC",
                    messages=[
                        oci.generative_ai_inference.models.UserMessage(
                            content=[{"type": "TEXT", "text": repair_prompt}]
                        )
                    ],
                    max_tokens=512,
                    temperature=0.0,
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
                        model_id=self._llm_model_id
                    ),
                    chat_request=repair_text_request,
                )
                repair_structured_detail = oci.generative_ai_inference.models.ChatDetails(
                    compartment_id=self._compartment_id,
                    serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                        model_id=self._llm_model_id
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
                        state["last_payload"] = payload
                        return payload
                    except Exception as e:
                        state["repair_structured_supported"] = False
                        logger.warning("修復フェーズの構造化モードを無効化して通常モードへ切替: %s", str(e)[:200])

                response = self._retry_api_call("classify_invoice_repair", client.chat, repair_text_detail)
                chat_response = response.data.chat_response
                payload = self._get_text_from_chat_response(chat_response)
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

    def extract_fields(self, image_data: bytes, category: str = "", content_type: str = "image/jpeg") -> Dict[str, Any]:
        """伝票画像からフィールド情報を抽出する

        Args:
            image_data: 画像のバイトデータ
            category: 伝票の種別（分類結果から）
            content_type: MIMEタイプ

        Returns:
            抽出結果 (header_fields, line_fields)
        """
        client = self._get_client()
        if not client:
            return {"success": False, "message": "AI クライアントが初期化されていません"}

        category_hint = f"この伝票の種別は「{category}」です。" if category else ""

        prompt = f"""あなたは伝票データ登録の専門家です。
この画像は伝票（ビジネス文書）です。{category_hint}

【目的】
この伝票をOracleデータベースに登録するため、画像に含まれる全ての項目をフィールドとして抽出し、テーブル定義を設計してください。

【抽出ルール】
- 印字済みの値・手書き記入欄・空欄のラベルを含め、全ての項目を漏れなく抽出する
- 合計・小計・消費税・税率などの集計項目も含める
- 承認欄・担当者印・受領印などの管理項目も含める（VARCHAR2として）
- 備考・摘要・メモ欄も含める

【データ型の選択基準】
- VARCHAR2: 文字列全般（コード、名称、住所、電話番号、メモ、承認印など）
- NUMBER: 純粋な数値（金額、数量、単価、税率、個数など）
- DATE: 日付のみ（伝票日付、納品日、支払期限など）

【VARCHAR2の最大長の目安（max_length に整数値で指定）】
伝票番号・コード: 50 / 氏名・担当者名: 100 / 会社名・取引先名・部署名: 200 /
住所: 300 / 品名・商品名・件名: 200 / 電話番号・FAX: 20 / メール: 200 /
備考・摘要・メモ: 500 / その他: 100

【is_required の判定】
- true: 必ず記入・印字される必須項目（伝票番号・日付・取引先名・合計金額など）
- false: 任意記入・空欄になりうる項目

【出力形式】
以下の JSON をそのまま出力してください（説明文・コードブロック・コメントは一切不要）:
{{
  "header_fields": [
    {{
      "field_name": "伝票番号",
      "field_name_en": "slip_number",
      "value": "A-001",
      "data_type": "VARCHAR2",
      "max_length": 50,
      "is_required": true
    }},
    {{
      "field_name": "伝票日付",
      "field_name_en": "slip_date",
      "value": "2026-01-15",
      "data_type": "DATE",
      "max_length": null,
      "is_required": true
    }},
    {{
      "field_name": "合計金額",
      "field_name_en": "total_amount",
      "value": "10000",
      "data_type": "NUMBER",
      "max_length": null,
      "is_required": true
    }}
  ],
  "line_fields": [
    {{
      "field_name": "品名",
      "field_name_en": "item_name",
      "value": "商品A",
      "data_type": "VARCHAR2",
      "max_length": 200,
      "is_required": true
    }},
    {{
      "field_name": "数量",
      "field_name_en": "quantity",
      "value": "5",
      "data_type": "NUMBER",
      "max_length": null,
      "is_required": true
    }}
  ],
  "line_count": 3
}}

フィールドの説明:
- header_fields: 伝票ヘッダー部分の全項目（番号・日付・取引先・金額・税額・備考など）
- line_fields: 明細行の各カラム定義（品名・数量・単価・金額など）。明細がない場合は空配列 []
- field_name: フィールド名（日本語）
- field_name_en: フィールド名（英語スネークケース。例: invoice_date, customer_name）
- value: 画像から読み取った値（空欄は ""）
- data_type: "VARCHAR2" または "NUMBER" または "DATE" のいずれか
- max_length: VARCHAR2 の場合は整数値、NUMBER または DATE の場合は null
- is_required: true または false（必ず Boolean 型で）
- line_count: 明細行の数（整数）。明細なしは 0

出力は必ず有効な JSON のみ。前後に説明文・コードブロック（```）・コメント（//）を含めないでください。"""

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
                max_tokens=4096,
                temperature=0.1,
                is_stream=False,
            )

            chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=self._compartment_id,
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                    model_id=self._llm_model_id
                ),
                chat_request=chat_request,
            )

            response = self._retry_api_call("extract_fields", client.chat, chat_detail)

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
            logger.error("フィールド抽出エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"フィールド抽出失敗: {str(e)}"}

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
                max_tokens=4096,
                temperature=0.1,
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
                max_tokens=2048,
                temperature=0.1,
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
