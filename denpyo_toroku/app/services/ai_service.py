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

JSON形式のみで回答してください:
{
  "category": "伝票の種類（例: 請求書, 納品書, 領収書, 注文書, 見積書, 発注書, 仕入伝票, 売上伝票, 出荷伝票, 入荷伝票, 支払伝票, 入金伝票, 振替伝票, 経費精算書, 検収書, 工事請負契約書, その他）",
  "confidence": 0.0〜1.0の確信度,
  "description": "この伝票の内容・用途の説明（40字以内）",
  "has_line_items": true/false（品目・明細行を示すテーブルや繰り返し行があるかどうか）
}

JSONのみを出力し、他のテキストは含めないでください。"""

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
                max_tokens=1024,
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

            response = self._retry_api_call("classify_invoice", client.chat, chat_detail)

            # レスポンスからテキストを抽出
            result_text = ""
            chat_response = response.data.chat_response
            if hasattr(chat_response, "choices") and chat_response.choices:
                message = chat_response.choices[0].message
                if hasattr(message, "content"):
                    for part in message.content:
                        if hasattr(part, "text"):
                            result_text += part.text

            # JSONパース
            result_text = result_text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            parsed = json.loads(result_text)
            parsed["success"] = True
            return parsed

        except json.JSONDecodeError as e:
            logger.error("AI応答のJSONパースエラー: %s (response=%s)", e, result_text[:200])
            return {"success": False, "message": f"AI応答の解析に失敗しました: {str(e)}"}
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

        category_hint = f"この伝票は「{category}」です。" if category else ""

        prompt = f"""あなたは伝票データ登録の専門家です。
この画像は伝票（ビジネス文書）です。{category_hint}

【目的】
この伝票をデータベースに登録するため、画像に含まれる全ての入力・印字項目をフィールドとして抽出し、Oracle Database のテーブル定義を設計してください。

【抽出ルール】
- 印字済みの値・手書きの記入欄・空欄のラベルも含めて、全ての項目を漏れなく抽出すること
- 合計・小計・消費税・税率などの集計項目も含めること
- 承認欄・担当者印・受領印などの管理項目も含めること（VARCHAR2で）
- 備考・摘要・メモ欄も含めること

【データ型の選択基準】
- VARCHAR2: 文字列全般（コード、名称、住所、電話番号、メモ、承認印など）
- NUMBER: 純粋な数値（金額、数量、単価、税率、個数など）
- DATE: 日付のみ（伝票日付、納品日、支払期限、有効期限など）

【VARCHAR2のmax_length目安】
- 伝票番号・コード・型番: 50
- 担当者名・氏名: 100
- 会社名・取引先名・部署名: 200
- 住所: 300
- 品名・商品名・件名: 200
- 電話番号・FAX番号: 20
- メールアドレス: 200
- 備考・摘要・メモ: 500
- その他一般的な文字列: 100

【is_required の判定基準】
- true: その伝票の種類として必ず記入・印字される必須項目（伝票番号・日付・取引先名・合計金額など）
- false: 任意記入・状況によって空欄になりうる項目

以下のJSON形式のみで回答してください:
{{
  "header_fields": [
    {{"field_name": "フィールド名（日本語）", "field_name_en": "英語名（snake_case）", "value": "読み取った値（空欄は空文字）", "data_type": "VARCHAR2|NUMBER|DATE", "max_length": 推定最大長（VARCHAR2の場合のみ、他はnull）, "is_required": true/false}}
  ],
  "line_fields": [
    {{"field_name": "フィールド名（日本語）", "field_name_en": "英語名（snake_case）", "value": "1行目の値", "data_type": "VARCHAR2|NUMBER|DATE", "max_length": 推定最大長（VARCHAR2の場合のみ、他はnull）, "is_required": true/false}}
  ],
  "line_count": 明細行の数（明細なしは0）
}}

注意:
- header_fields: 伝票ヘッダー部分の全項目（番号・日付・取引先・金額・税額・備考など）
- line_fields: 明細行の各カラム定義（品名・数量・単価・金額など）。明細がない場合は空配列
- field_name_en はスネークケースで統一（例: invoice_date, customer_name, total_amount）
- JSONのみを出力し、前後に説明文やコードブロックを含めないでください"""

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

            result_text = result_text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            parsed = json.loads(result_text)
            parsed["success"] = True
            return parsed

        except json.JSONDecodeError as e:
            logger.error("AI応答のJSONパースエラー: %s", e)
            return {"success": False, "message": f"AI応答の解析に失敗しました: {str(e)}"}
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

以下のJSON形式で回答してください:
{{
  "table_prefix": "テーブル名プレフィックス（英語、大文字、例: INV, PO, RCV）",
  "header_table_name": "ヘッダーテーブル名",
  "line_table_name": "明細テーブル名",
  "header_ddl": "CREATE TABLE文（ヘッダー）",
  "line_ddl": "CREATE TABLE文（明細、ヘッダーへの外部キー付き）"
}}

注意:
- ヘッダーテーブルにはID（NUMBER主キー）、登録日時、ファイル名カラムを自動追加
- 明細テーブルにはID、HEADER_ID（外部キー）、LINE_NO カラムを自動追加
- JSONのみを出力してください"""

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

            result_text = result_text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            parsed = json.loads(result_text)
            parsed["success"] = True
            return parsed

        except json.JSONDecodeError as e:
            logger.error("AI応答のJSONパースエラー: %s", e)
            return {"success": False, "message": f"AI応答の解析に失敗しました: {str(e)}"}
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

        prompt = f"""以下のデータベーステーブルに対して、ユーザーの質問に答える Oracle Database 互換の SELECT 文を生成してください。

利用可能なテーブルとカラム:
{schema_text}

ユーザーの質問: {query}

以下の JSON 形式で回答してください:
{{
  "sql": "生成した SELECT 文",
  "explanation": "このクエリの簡単な説明（日本語）"
}}

注意:
- SELECT 文のみ生成してください（INSERT, UPDATE, DELETE は禁止）
- 上記のテーブルのみ使用してください
- Oracle Database の構文に従ってください
- JSON のみを出力し、他のテキストは含めないでください"""

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

            result_text = result_text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            parsed = json.loads(result_text)
            parsed["success"] = True
            return parsed

        except json.JSONDecodeError as e:
            logger.error("AI応答のJSONパースエラー: %s", e)
            return {"success": False, "message": f"AI応答の解析に失敗しました: {str(e)}"}
        except Exception as e:
            logger.error("Text-to-SQL変換エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"SQL生成に失敗しました: {str(e)}"}
