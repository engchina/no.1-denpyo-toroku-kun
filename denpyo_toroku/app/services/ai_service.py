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
import threading
import time
import requests
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# レート制限対応のリトライ設定（Generative AI API用）
GENAI_API_MAX_RETRIES = max(1, int(os.environ.get("GENAI_API_MAX_RETRIES", "3")))
GENAI_API_BASE_DELAY = max(0.1, float(os.environ.get("GENAI_API_BASE_DELAY", "1.0")))
GENAI_API_MAX_DELAY = max(GENAI_API_BASE_DELAY, float(os.environ.get("GENAI_API_MAX_DELAY", "8.0")))
GENAI_API_BACKOFF_MULTIPLIER = max(1.5, float(os.environ.get("GENAI_API_BACKOFF_MULTIPLIER", "2.0")))
GENAI_API_JITTER = min(0.5, max(0.0, float(os.environ.get("GENAI_API_JITTER", "0.5"))))
GENAI_GLOBAL_MAX_CONCURRENCY = max(1, int(os.environ.get("GENAI_GLOBAL_MAX_CONCURRENCY", "1")))
GENAI_MIN_REQUEST_INTERVAL_SECONDS = max(
    0.0,
    float(os.environ.get("GENAI_MIN_REQUEST_INTERVAL_SECONDS", "1.0")),
)
GENAI_RATE_LIMIT_COOLDOWN_SECONDS = max(
    GENAI_MIN_REQUEST_INTERVAL_SECONDS,
    float(os.environ.get("GENAI_RATE_LIMIT_COOLDOWN_SECONDS", "30.0")),
)
GENAI_PROGRESS_LOG_INTERVAL_SECONDS = max(
    0.0,
    float(os.environ.get("GENAI_PROGRESS_LOG_INTERVAL_SECONDS", "15.0")),
)
GENAI_JSON_PARSE_RETRIES = max(1, int(os.environ.get("GENAI_JSON_PARSE_RETRIES", "3")))
GENAI_RECOVERY_MAX_RETRIES = max(1, int(os.environ.get("GENAI_RECOVERY_MAX_RETRIES", "2")))
GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES = max(
    0,
    int(os.environ.get("GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES", "1")),
)
GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES = max(
    0,
    int(
        os.environ.get(
            "GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES",
            str(GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES),
        )
    ),
)
GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES = max(
    0,
    int(os.environ.get("GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES", "0")),
)


def _parse_ocr_max_edge_steps(raw_value: str) -> tuple[int, ...]:
    default_steps = (2400, 1800, 1400, 1100)
    candidates: List[int] = []
    seen = set()
    for raw_part in (raw_value or "").split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            max_edge = int(part)
        except ValueError:
            continue
        if max_edge <= 0:
            continue
        if max_edge in seen:
            continue
        seen.add(max_edge)
        candidates.append(max_edge)

    return tuple(candidates or default_steps)


GENAI_OCR_IMAGE_MAX_EDGE_STEPS = _parse_ocr_max_edge_steps(
    os.environ.get("GENAI_OCR_IMAGE_MAX_EDGE_STEPS", "2400,1800,1400,1100")
)


def _parse_ocr_rotation_angles(raw_value: str) -> tuple[int, ...]:
    default_angles = (0, 90, 180, 270)
    candidates: List[int] = []
    seen = set()
    for raw_part in (raw_value or "").split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            angle = int(part) % 360
        except ValueError:
            continue
        if angle in seen:
            continue
        seen.add(angle)
        candidates.append(angle)

    if not candidates:
        return default_angles
    if 0 in candidates:
        candidates = [0] + [angle for angle in candidates if angle != 0]
    else:
        candidates.insert(0, 0)
    return tuple(candidates)


GENAI_OCR_ROTATION_ANGLES = _parse_ocr_rotation_angles(
    os.environ.get("GENAI_OCR_ROTATION_ANGLES", "0,90,180,270")
)


def _format_rotation_angles(rotation_angles: List[int] | tuple[int, ...]) -> str:
    return ",".join(str(int(angle) % 360) for angle in rotation_angles)


def _format_ocr_max_edge_steps(max_edge_steps: List[int] | tuple[int, ...]) -> str:
    return ",".join(str(int(max_edge)) for max_edge in max_edge_steps if int(max_edge) > 0)


def refresh_runtime_ocr_settings() -> Dict[str, Any]:
    global GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES
    global GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES
    global GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES
    global GENAI_OCR_IMAGE_MAX_EDGE_STEPS
    global GENAI_OCR_ROTATION_ANGLES

    GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES = max(
        0,
        int(os.environ.get("GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES", "1")),
    )
    GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES = max(
        0,
        int(
            os.environ.get(
                "GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES",
                str(GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES),
            )
        ),
    )
    GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES = max(
        0,
        int(os.environ.get("GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES", "0")),
    )
    GENAI_OCR_IMAGE_MAX_EDGE_STEPS = _parse_ocr_max_edge_steps(
        os.environ.get("GENAI_OCR_IMAGE_MAX_EDGE_STEPS", "2400,1800,1400,1100")
    )
    GENAI_OCR_ROTATION_ANGLES = _parse_ocr_rotation_angles(
        os.environ.get("GENAI_OCR_ROTATION_ANGLES", "0,90,180,270")
    )
    return {
        "empty_response_max_retries": GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES,
        "empty_response_primary_max_retries": GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES,
        "empty_response_secondary_max_retries": GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES,
        "image_max_edge_steps": GENAI_OCR_IMAGE_MAX_EDGE_STEPS,
        "rotation_angles": GENAI_OCR_ROTATION_ANGLES,
    }


refresh_runtime_ocr_settings()


# ─────────────────────────────────────────────────────────────────────────────
# Shared prompt fragments
#   _PROMPT_OCR_OUTPUT_RULES        : VLM OCR output format specification
#   _PROMPT_STRUCTURED_DATA_READING : How to interpret structured OCR markers
#                                     (works for both image-direct and text modes)
#   _PROMPT_SELECTION_SCHEMA_DESIGN : DB schema design rules for selection fields
# ─────────────────────────────────────────────────────────────────────────────

_PROMPT_OCR_OUTPUT_RULES: str = """\
You are an intelligent document parser. Extract all content from this document \
image and output it in a structured, machine-readable format following the rules below.

## Rule 1: Tables and Grid-Based Forms
- Render every table or grid using GitHub-Flavored Markdown table syntax.
- Each LOGICAL row must occupy exactly ONE Markdown table row, even if that row \
visually wraps across multiple lines in the image.
- If a cell's content spans multiple visual lines within the same cell boundary, \
join them with a single space.
- Always include a header row; if no headers are printed, infer short descriptive \
ones (Column1, Column2, ...).
- CRITICAL — column integrity: First identify ALL column headers and fix the total \
column count for the entire table. Every data row MUST have exactly that many \
columns. Never merge values from adjacent columns into one cell.
- To detect column boundaries when grid lines are faint or absent, align each \
value with the header directly above it. If a data cell appears to contain text \
that belongs to the next column (e.g., a part number immediately following an item \
name), split them at the boundary implied by the header alignment.

## Rule 2: Key-Value / Label-Value Fields
- Output as "Label: Value" on a single line.
- If a field value wraps visually across multiple lines, join them into one line.

## Rule 3: Selection and Choice Fields
Mark every visually indicated selection regardless of the indicator style:
- Circled (○ ◯ ●), checked (✓ ✗ ☑ ☒), underlined, boxed, filled, or otherwise \
highlighted options.
- Append [SELECTED] immediately after the chosen option.
- Append [REJECTED] immediately after any option that is explicitly crossed out \
or struck through.
- For checkbox lists, prefix each item with [CHECKED] or [ ] on its own line.
- Example inline:   "Yes[SELECTED] / No"
- Example checkbox: "[CHECKED] Option A / [ ] Option B / [CHECKED] Option C"

## Rule 4: Free Text Regions
- Preserve paragraph breaks with a blank line.
- Do NOT add artificial line breaks that do not exist in the original.

## Rule 5: Special Visual Elements
- Stamps or seals:     <STAMP: text>
- Handwritten notes:   <HANDWRITTEN: text>
- Signatures:          <SIGNATURE>
- Barcodes / QR codes: <BARCODE: value_if_readable>
- Illegible text:      <ILLEGIBLE>
- Redacted / masked:   <REDACTED>

## Rule 6: Document Sections
When the document has clearly separated sections, prefix each with a Markdown \
heading (## Section Name).

Output ONLY the extracted content. No explanations, no commentary, no markdown \
code fences."""

_PROMPT_STRUCTURED_DATA_READING: str = """\
- Table rows: Each logical row — visually bounded in the image or formatted as a \
Markdown table row with | separators in the text — must map to exactly one record. \
Do not split a single logical row into multiple records even if it wraps across \
visual lines.
- Selection fields: The selected option is identified either by visual marking in \
the image (circled ○, filled ●, checked ✓, underlined, boxed) or by the [SELECTED] \
marker in the text. Record only the selected option's text as the field value, \
without any marker (e.g., "Yes[SELECTED] / No" → "Yes").
- Checkbox fields: Checked items (visually ticked in the image, or prefixed \
[CHECKED] in the text) → "1". Unchecked items ([ ] prefix or no mark) → "0".
- Special OCR tags: <STAMP: text> and <HANDWRITTEN: text> → use only the inner \
text value. <SIGNATURE> → "1". <ILLEGIBLE> and <REDACTED> → empty string ""."""

_PROMPT_SELECTION_SCHEMA_DESIGN: str = """\
- Selection / choice fields (options visually marked in the image with ○/✓/underline, \
or tagged [SELECTED] in OCR text): design the column as VARCHAR2 sized to \
accommodate the longest option value.
- Checkbox fields (visually ticked boxes in the image, or [CHECKED] / [ ] markers \
in OCR text): design each distinct checkbox as NUMBER(1) (1 = checked, \
0 = unchecked). If checkboxes represent mutually exclusive choices, a single \
VARCHAR2 column may be used instead.
- Stamp / seal (<STAMP:...> in OCR, or visible ink stamps in the image): VARCHAR2(200).
- Handwritten annotation (<HANDWRITTEN:...> in OCR): VARCHAR2(500).
- Signature (<SIGNATURE> in OCR, or dedicated signature fields): VARCHAR2(1) or \
NUMBER(1)."""


# ─────────────────────────────────────────────────────────────────────────────
# Function-specific prompt default fragments (extracted for customization)
# ─────────────────────────────────────────────────────────────────────────────

_PROMPT_CLASSIFY_INVOICE_DEFAULT: str = """\
あなたは日本語業務文書（帳票）の分析を専門とするエキスパートです。
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

_PROMPT_EXTRACT_DATA_VALUE_RULES_DEFAULT: str = """\
1. 各カラムの日本語ラベル（-- 以降）に対応する項目を画像内で探し、値を転記する
2. 数値（金額・数量・単価）: 桁区切りカンマ・通貨記号を除去した数字文字列（例: "¥1,234,567" → "1234567"）
3. 日付: ISO 8601形式 YYYY-MM-DD（例: "令和6年1月15日" → "2024-01-15"）
4. テキスト: 画像の文字をそのまま転記。手書き等で判読不能な場合は ""
5. 画像に該当項目が存在しない場合: "" （null は使わない）
6. スキーマに存在する全カラムを header_fields に出力する（値がなくても省略禁止）
7. テーブルセルの折り返し（セルが狭いため内容が複数の視覚的行に渡る場合）: 同一セル内の折り返し行を全てスペースで結合し、完全な文字列として1つの値に転記する（例: 1行目「室名札（ピクトサイン）」2行目「アクリルUV印刷」→ "室名札（ピクトサイン） アクリルUV印刷"）"""

_PROMPT_EXTRACT_TEXT_VALUE_RULES_DEFAULT: str = """\
1. 各カラムの日本語ラベル（-- 以降）に対応する項目をテキスト内で探し、値を転記する
2. 数値（金額・数量・単価）: 桁区切りカンマ・通貨記号を除去した数字文字列（例: "¥1,234,567" → "1234567"）
3. 日付: ISO 8601形式 YYYY-MM-DD（例: "令和6年1月15日" → "2024-01-15"）
4. テキスト: OCRテキストの文字をそのまま転記。
5. テキストに該当項目が存在しない場合: "" （null は使わない）
6. スキーマに存在する全カラムを header_fields に出力する（値がなくても省略禁止）
7. テーブルセルの折り返し（セルが狭いため内容が複数の視覚的行に渡る場合）: 同一セル内の折り返し行を全てスペースで結合し、完全な文字列として1つの値に転記する（例: 1行目「室名札（ピクトサイン）」2行目「アクリルUV印刷」→ "室名札（ピクトサイン） アクリルUV印刷"）"""

_PROMPT_EXTRACT_SCHEMA_COMPLETENESS_DEFAULT: str = """\
- 画像内の印字済み項目・手書き記入欄・空欄ラベルを全て漏れなく抽出する
- 伝票番号・日付・取引先など管理項目は必ず含める
- 合計・小計・消費税額・税率などの集計項目も全て含める
- 承認印・受領印・担当者名・部署名などの運用管理項目も含める
- 備考・摘要・特記事項欄も含める
- テーブルセルの折り返し: セルが狭く内容が複数の視覚的行に渡る場合、同一セル内の全行をスペースで結合して完全な文字列として読み取る"""

_PROMPT_EXTRACT_SCHEMA_ORACLE_DESIGN_DEFAULT: str = """\
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
  - false: 状況により空欄になりうる任意項目"""

_PROMPT_GENERATE_SQL_REQUIREMENTS_DEFAULT: str = """\
### 1. Document Type Detection
- First, identify the document type (e.g., 領収書, 請求書, 納品書, 見積書, 注文書, 発注書, etc.).
- Design the table name and structure accordingly.

### 2. Naming Conventions
- **Table name**: Romanized Katakana in UPPERCASE alphabet (e.g., RYOUSHUUSHO for 領収書, SEIKYUUSHO for 請求書, NOUHINNSHO for 納品書).
- **Physical column names**: Romanized Katakana in UPPERCASE alphabet with underscores (e.g., HAKKOOBI for 発行日, GOUKEI_KINGAKU for 合計金額, ATESAKI_MEI for 宛先名).
- **Logical column names**: Japanese (Kanji) via comment (e.g., 発行日, 合計金額).
- Use consistent Hepburn romanization rules (e.g., しょ→SHO, きゅう→KYUU, おう→OU).

### 3. Schema Design Rules
- Choose appropriate Oracle data types: VARCHAR2, NUMBER, DATE, TIMESTAMP.
- Do NOT use CLOB. Even long text fields must use VARCHAR2 with an appropriate length up to 4000.
- Make columns NULLABLE unless they are clearly always present.
- Do not set VARCHAR2 length to the exact observed character count. Add generous safety buffer because actual production data can be longer.
- Prefer safer bucket sizes such as 50, 100, 200, 300, 500, 1000, 2000, or 4000.
- For short-looking codes / IDs / numbers, still keep enough room instead of matching the sample exactly.
- {header_only_hint}

### 4. Capture ALL information present in the document, such as:
- Document metadata (document number, date, type)
- Party information (sender/receiver name, address, phone, registration number)
- Amount summary (subtotal, tax, total)
- Tax breakdown by rate if present
- Line item details if present (item name, quantity, unit price, amount, tax rate)
- Any stamps, notes, remarks, or payment terms"""

_PROMPT_SUGGEST_DDL_RULES_DEFAULT: str = """\
- table_prefix: 伝票種別に合わせた英語大文字（例: INV, PO, RCV, SLS）
- header_table_name: ヘッダーテーブル名（table_prefix + "_H"）
- line_table_name: 明細テーブル名（table_prefix + "_L"）
- header_ddl・line_ddl: 改行を \\n でエスケープした CREATE TABLE 文の文字列
- ヘッダーテーブルには HEADER_ID（NUMBER 主キー）、CREATED_AT（DATE）、FILE_NAME（VARCHAR2(500)）を自動追加
- 明細テーブルには LINE_ID（NUMBER 主キー）、HEADER_ID（外部キー）、LINE_NO（NUMBER）を自動追加
- 出力は必ず有効な JSON のみ。前後に説明文・コードブロック（```）・コメント（//）を含めないでください"""

_PROMPT_TEXT_TO_SQL_CONSTRAINTS_DEFAULT: str = """\
- SELECT 文のみ生成（INSERT, UPDATE, DELETE, DROP などは絶対に禁止）
- 上記に示したテーブルとカラムのみ使用
- テーブル名にスキーマ名は付けない（例: RECEIPT_H を使い、ADMIN.RECEIPT_H は使わない）
- Oracle Database 構文に従う（ROWNUM, NVL, TO_CHAR, TO_DATE など使用可）
- sql フィールドの値は SQL 文字列（改行は \\n でエスケープ）
- 出力は必ず有効な JSON のみ。前後に説明文・コードブロック（```）・コメント（//）を含めないでください"""

# ─────────────────────────────────────────────────────────────────────────────
# Prompt customization support
#   プロンプト設定は prompt_settings.json に保存され、
#   _get_prompt(key) で取得する。未設定はデフォルトに fallback。
# ─────────────────────────────────────────────────────────────────────────────

# All configurable prompt keys with their defaults
PROMPT_KEYS: Dict[str, str] = {
    "ocr_output_rules": _PROMPT_OCR_OUTPUT_RULES,
    "structured_data_reading": _PROMPT_STRUCTURED_DATA_READING,
    "selection_schema_design": _PROMPT_SELECTION_SCHEMA_DESIGN,
    "classify_invoice": _PROMPT_CLASSIFY_INVOICE_DEFAULT,
    "extract_data_value_rules": _PROMPT_EXTRACT_DATA_VALUE_RULES_DEFAULT,
    "extract_text_value_rules": _PROMPT_EXTRACT_TEXT_VALUE_RULES_DEFAULT,
    "extract_schema_completeness": _PROMPT_EXTRACT_SCHEMA_COMPLETENESS_DEFAULT,
    "extract_schema_oracle_design": _PROMPT_EXTRACT_SCHEMA_ORACLE_DESIGN_DEFAULT,
    "generate_sql_requirements": _PROMPT_GENERATE_SQL_REQUIREMENTS_DEFAULT,
    "suggest_ddl_rules": _PROMPT_SUGGEST_DDL_RULES_DEFAULT,
    "text_to_sql_constraints": _PROMPT_TEXT_TO_SQL_CONSTRAINTS_DEFAULT,
}

_prompt_overrides: Dict[str, str] = {}


def _prompt_settings_path() -> "Path":
    from pathlib import Path
    return Path(__file__).resolve().parents[3] / "prompt_settings.json"


def reload_prompt_settings() -> None:
    """JSONファイルからカスタムプロンプトを再読み込みする。APIエンドポイントから呼び出し可能。"""
    global _prompt_overrides
    from pathlib import Path
    path = _prompt_settings_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _prompt_overrides = {
                k: v for k, v in data.items()
                if k in PROMPT_KEYS and isinstance(v, str) and v.strip()
            }
        except Exception as exc:
            logger.warning("プロンプト設定の読み込みに失敗しました: %s", exc)
            _prompt_overrides = {}
    else:
        _prompt_overrides = {}


def _get_prompt(key: str) -> str:
    """カスタムプロンプトがある場合はそれを返し、なければデフォルトを返す。"""
    return _prompt_overrides.get(key) or PROMPT_KEYS.get(key, "")


# モジュールロード時に読み込む
reload_prompt_settings()


class AIRateLimitError(Exception):
    """OCI GenAI の 429 を上位へ透過するための例外"""

    def __init__(self, operation_name: str, retry_after_seconds: float, original_error: Exception):
        self.operation_name = operation_name
        self.retry_after_seconds = max(1.0, float(retry_after_seconds))
        self.original_error = original_error
        super().__init__(
            f"{operation_name}: OCI GenAI request throttled; retry after {self.retry_after_seconds:.1f}s"
        )


class _GenAIRequestGate:
    """全 AIService インスタンスで共有する簡易レート制御"""

    def __init__(self):
        self._semaphore = threading.BoundedSemaphore(GENAI_GLOBAL_MAX_CONCURRENCY)
        self._lock = threading.Lock()
        self._next_allowed_monotonic = 0.0

    def _reserve_slot(self, operation_name: str) -> None:
        semaphore_wait_started_at: Optional[float] = None
        if GENAI_PROGRESS_LOG_INTERVAL_SECONDS > 0:
            while not self._semaphore.acquire(timeout=GENAI_PROGRESS_LOG_INTERVAL_SECONDS):
                if semaphore_wait_started_at is None:
                    semaphore_wait_started_at = time.monotonic()
                logger.info(
                    "%s: GenAI 実行枠の空きを待機中です (elapsed=%.1fs)",
                    operation_name,
                    time.monotonic() - semaphore_wait_started_at,
                )
        else:
            self._semaphore.acquire()

        if semaphore_wait_started_at is not None:
            logger.info(
                "%s: GenAI 実行枠を取得しました (waited=%.1fs)",
                operation_name,
                time.monotonic() - semaphore_wait_started_at,
            )
        try:
            while True:
                with self._lock:
                    wait_seconds = max(0.0, self._next_allowed_monotonic - time.monotonic())
                    if wait_seconds <= 0:
                        self._next_allowed_monotonic = (
                            time.monotonic() + GENAI_MIN_REQUEST_INTERVAL_SECONDS
                        )
                        return
                logger.info(
                    "%s: GenAI グローバルレート制御により %.2fs 待機します",
                    operation_name,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
        except Exception:
            self._semaphore.release()
            raise

    def call(self, operation_name: str, func, *args, **kwargs):
        self._reserve_slot(operation_name)
        try:
            return func(*args, **kwargs)
        finally:
            self._semaphore.release()

    def note_rate_limit(self, retry_after_seconds: float) -> None:
        cooldown = max(GENAI_RATE_LIMIT_COOLDOWN_SECONDS, float(retry_after_seconds))
        with self._lock:
            self._next_allowed_monotonic = max(
                self._next_allowed_monotonic,
                time.monotonic() + cooldown,
            )


_GENAI_REQUEST_GATE = _GenAIRequestGate()


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
        self._vlm_max_tokens = int(os.environ.get("VLM_MAX_TOKENS", "8192"))
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
                retry_strategy=oci.retry.NoneRetryStrategy(),
                timeout=(10, 240),
            )
            logger.info("OCI Generative AI クライアントを初期化しました (model=%s)", self._llm_model_id)
        except Exception as e:
            logger.error("OCI Generative AI クライアント初期化エラー: %s", e, exc_info=True)
            return None

        return self._client

    def _build_log_extra(self, log_context: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        extra: Dict[str, Any] = {}
        if log_context:
            extra.update({key: value for key, value in log_context.items() if value is not None})
        extra.update({key: value for key, value in kwargs.items() if value is not None})
        return extra

    def _build_operation_log_extra(
        self,
        operation_name: str,
        attempt: Optional[int],
        max_attempts: Optional[int],
        log_context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"operation_name": operation_name}
        if attempt is not None:
            payload["genai_attempt"] = attempt
        if max_attempts is not None:
            payload["genai_max_attempts"] = max_attempts
        payload.update(kwargs)
        return self._build_log_extra(log_context, **payload)

    @staticmethod
    def _coerce_positive_int(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except Exception:
            return None
        return parsed if parsed > 0 else None

    @classmethod
    def _buffer_varchar2_length(
        cls,
        declared_length: Any,
        original_data_type: str = "VARCHAR2",
    ) -> int:
        if str(original_data_type or "").upper() == "CLOB":
            return 4000

        observed_length = cls._coerce_positive_int(declared_length)
        if observed_length is None:
            return 100

        buffered_length = min(4000, observed_length + max(10, (observed_length + 1) // 2))
        for candidate in (50, 100, 200, 300, 500, 1000, 2000, 4000):
            if buffered_length <= candidate:
                return candidate
        return 4000

    def _start_request_progress_logger(
        self,
        operation_name: str,
        attempt: int,
        max_attempts: int,
        started_at: float,
        log_context: Optional[Dict[str, Any]] = None,
    ) -> tuple[Optional[threading.Event], Optional[threading.Thread]]:
        if GENAI_PROGRESS_LOG_INTERVAL_SECONDS <= 0:
            return None, None

        stop_event = threading.Event()

        def _emit_progress() -> None:
            while not stop_event.wait(GENAI_PROGRESS_LOG_INTERVAL_SECONDS):
                elapsed = time.monotonic() - started_at
                logger.info(
                    "%s: OCI GenAI 応答を待機中です (attempt %d/%d, elapsed=%.1fs)",
                    operation_name,
                    attempt,
                    max_attempts,
                    elapsed,
                    extra=self._build_operation_log_extra(
                        operation_name,
                        attempt,
                        max_attempts,
                        log_context,
                        elapsed_seconds=round(elapsed, 3),
                    ),
                )

        progress_thread = threading.Thread(
            target=_emit_progress,
            name=f"genai_progress_{threading.get_ident()}",
            daemon=True,
        )
        progress_thread.start()
        return stop_event, progress_thread

    def _stop_request_progress_logger(
        self,
        stop_event: Optional[threading.Event],
        progress_thread: Optional[threading.Thread],
    ) -> None:
        if stop_event is not None:
            stop_event.set()
        if progress_thread is not None:
            progress_thread.join(timeout=0.2)

    def _is_rate_limit_error(self, error: Exception) -> bool:
        status = getattr(error, "status", None)
        if status == 429:
            return True
        error_str = str(error).lower()
        return (
            '429' in error_str
            or 'too many requests' in error_str
            or 'rate limit exceeded' in error_str
            or 'request is throttled' in error_str
        )

    def _extract_retry_after_seconds(self, error: Exception) -> Optional[float]:
        headers = getattr(error, "headers", None) or {}
        if isinstance(headers, dict):
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            if retry_after is not None:
                try:
                    return max(1.0, float(retry_after))
                except (TypeError, ValueError):
                    pass
        return None

    def _is_retryable_error(self, error: Exception) -> bool:
        if self._is_rate_limit_error(error):
            return False
        status = getattr(error, "status", None)
        if isinstance(status, int) and status in {408, 409, 425, 500, 502, 503, 504}:
            return True
        if isinstance(error, (requests.Timeout, requests.ConnectionError)):
            return True
        error_str = str(error).lower()
        return any(
            token in error_str
            for token in (
                "timeout",
                "timed out",
                "connection reset",
                "connection aborted",
                "temporarily unavailable",
                "transient",
                "service unavailable",
            )
        )

    def _raise_if_rate_limited(self, error: Exception) -> None:
        if isinstance(error, AIRateLimitError):
            raise error

    def _calculate_backoff_delay(self, attempt: int) -> float:
        exponential_delay = GENAI_API_BASE_DELAY * (GENAI_API_BACKOFF_MULTIPLIER ** attempt)
        capped_delay = min(exponential_delay, GENAI_API_MAX_DELAY)
        lower_bound = max(0.1, capped_delay * (1.0 - GENAI_API_JITTER))
        return random.uniform(lower_bound, capped_delay)

    def _retry_api_call(
        self,
        operation_name: str,
        func,
        *args,
        log_context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        """リトライ付きAPI呼び出し"""
        last_error = None
        for attempt in range(GENAI_API_MAX_RETRIES):
            attempt_no = attempt + 1
            started_at = time.monotonic()
            logger.info(
                "%s: OCI GenAI リクエスト送信を開始します (attempt %d/%d)",
                operation_name,
                attempt_no,
                GENAI_API_MAX_RETRIES,
                extra=self._build_operation_log_extra(
                    operation_name,
                    attempt_no,
                    GENAI_API_MAX_RETRIES,
                    log_context,
                ),
            )
            stop_event: Optional[threading.Event] = None
            progress_thread: Optional[threading.Thread] = None
            try:
                stop_event, progress_thread = self._start_request_progress_logger(
                    operation_name,
                    attempt_no,
                    GENAI_API_MAX_RETRIES,
                    started_at,
                    log_context=log_context,
                )
                result = _GENAI_REQUEST_GATE.call(operation_name, func, *args, **kwargs)
                elapsed = time.monotonic() - started_at
                logger.info(
                    "%s: OCI GenAI 応答を受信しました (attempt %d/%d, elapsed=%.1fs)",
                    operation_name,
                    attempt_no,
                    GENAI_API_MAX_RETRIES,
                    elapsed,
                    extra=self._build_operation_log_extra(
                        operation_name,
                        attempt_no,
                        GENAI_API_MAX_RETRIES,
                        log_context,
                        elapsed_seconds=round(elapsed, 3),
                    ),
                )
                return result
            except Exception as e:
                last_error = e
                elapsed = time.monotonic() - started_at
                if self._is_rate_limit_error(e):
                    retry_after_seconds = (
                        self._extract_retry_after_seconds(e) or GENAI_RATE_LIMIT_COOLDOWN_SECONDS
                    )
                    _GENAI_REQUEST_GATE.note_rate_limit(retry_after_seconds)
                    logger.warning(
                        "%s: OCI GenAI の 429 を検知しました。ジョブ全体を %.1f 秒以上遅延して再試行してください: %s",
                        operation_name,
                        retry_after_seconds,
                        str(e)[:200],
                        extra=self._build_operation_log_extra(
                            operation_name,
                            attempt_no,
                            GENAI_API_MAX_RETRIES,
                            log_context,
                            retry_after_seconds=retry_after_seconds,
                            elapsed_seconds=round(elapsed, 3),
                        ),
                    )
                    raise AIRateLimitError(operation_name, retry_after_seconds, e) from e
                if attempt < GENAI_API_MAX_RETRIES - 1 and self._is_retryable_error(e):
                    delay = self._calculate_backoff_delay(attempt)
                    logger.warning(
                        "%s: 試行 %d/%d 失敗 (%s)。%.1f秒後に指数バックオフでリトライします",
                        operation_name,
                        attempt_no,
                        GENAI_API_MAX_RETRIES,
                        str(e)[:100],
                        delay,
                        extra=self._build_operation_log_extra(
                            operation_name,
                            attempt_no,
                            GENAI_API_MAX_RETRIES,
                            log_context,
                            retry_after_seconds=delay,
                            elapsed_seconds=round(elapsed, 3),
                        ),
                    )
                    time.sleep(delay)
                    continue
                logger.error(
                    "%s: 最大リトライ回数に到達、または非再試行エラーです: %s",
                    operation_name,
                    e,
                    extra=self._build_operation_log_extra(
                        operation_name,
                        attempt_no,
                        GENAI_API_MAX_RETRIES,
                        log_context,
                        elapsed_seconds=round(elapsed, 3),
                    ),
                )
            finally:
                self._stop_request_progress_logger(stop_event, progress_thread)
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

    def _parse_json_with_regeneration(
        self,
        operation_name: str,
        generate_text_func,
        max_attempts: int,
        log_context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """JSON 解析失敗時に AI 再生成して再試行する

        空レスポンス・不正JSON・生成エラーのいずれも再試行対象とする。
        """
        last_error: Optional[Exception] = None
        last_text = ""
        for attempt in range(1, max_attempts + 1):
            try:
                result_text = generate_text_func()
            except Exception as gen_error:
                self._raise_if_rate_limited(gen_error)
                # 生成自体のエラー（API障害など）も再試行対象
                last_error = gen_error
                if attempt < max_attempts:
                    logger.warning(
                        "%s: AI生成エラー。再生成を実行します (%d/%d): %s",
                        operation_name, attempt, max_attempts, str(gen_error)[:200],
                        extra=self._build_log_extra(
                            log_context,
                            operation_name=operation_name,
                            json_regen_attempt=attempt,
                            json_regen_max_attempts=max_attempts,
                        ),
                    )
                    continue
                else:
                    logger.error(
                        "%s: AI生成エラー。再試行上限に到達: %s",
                        operation_name, str(gen_error)[:200],
                        extra=self._build_log_extra(
                            log_context,
                            operation_name=operation_name,
                            json_regen_attempt=attempt,
                            json_regen_max_attempts=max_attempts,
                        ),
                    )
                    raise gen_error

            last_text = result_text

            # 空レスポンスのチェック（JSONDecodeError より先に検知）
            if not result_text or not result_text.strip():
                last_error = json.JSONDecodeError("AI returned empty response", "", 0)
                if attempt < max_attempts:
                    logger.warning(
                        "%s: AI応答が空です。再生成を実行します (%d/%d)",
                        operation_name, attempt, max_attempts,
                        extra=self._build_log_extra(
                            log_context,
                            operation_name=operation_name,
                            json_regen_attempt=attempt,
                            json_regen_max_attempts=max_attempts,
                        ),
                    )
                    continue
                else:
                    logger.error(
                        "%s: AI応答が空のまま再試行上限に到達",
                        operation_name,
                        extra=self._build_log_extra(
                            log_context,
                            operation_name=operation_name,
                            json_regen_attempt=attempt,
                            json_regen_max_attempts=max_attempts,
                        ),
                    )
                    raise last_error

            try:
                return self._extract_json(result_text)
            except json.JSONDecodeError as e:
                last_error = e
                if attempt < max_attempts:
                    logger.warning(
                        "%s: AI応答のJSON解析失敗。再生成を実行します (%d/%d): %s (response=%s)",
                        operation_name, attempt, max_attempts, e, result_text[:600],
                        extra=self._build_log_extra(
                            log_context,
                            operation_name=operation_name,
                            json_regen_attempt=attempt,
                            json_regen_max_attempts=max_attempts,
                        ),
                    )
                else:
                    logger.error(
                        "%s: AI応答のJSON解析失敗。再試行上限に到達: %s (response=%s)",
                        operation_name, e, result_text[:600],
                        extra=self._build_log_extra(
                            log_context,
                            operation_name=operation_name,
                            json_regen_attempt=attempt,
                            json_regen_max_attempts=max_attempts,
                        ),
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
        content = getattr(message, "content", None)
        if isinstance(content, str) and content:
            return content
        if content:
            if isinstance(content, list):
                return "".join(self._get_text_from_chat_content_part(part) for part in content)
            return self._get_text_from_chat_content_part(content)

        direct_text = getattr(message, "text", None)
        if isinstance(direct_text, str):
            return direct_text
        return ""

    def _get_text_from_chat_content_part(self, part: Any) -> str:
        if part is None:
            return ""
        if isinstance(part, str):
            return part
        if isinstance(part, dict):
            direct_text = part.get("text")
            if isinstance(direct_text, str) and direct_text:
                return direct_text
            for key in ("content", "parts"):
                nested = part.get(key)
                if isinstance(nested, str) and nested:
                    return nested
                if isinstance(nested, list):
                    return "".join(self._get_text_from_chat_content_part(item) for item in nested)
            return ""

        direct_text = getattr(part, "text", None)
        if isinstance(direct_text, str) and direct_text:
            return direct_text

        for attr_name in ("content", "parts"):
            nested = getattr(part, attr_name, None)
            if isinstance(nested, str) and nested:
                return nested
            if isinstance(nested, list):
                return "".join(self._get_text_from_chat_content_part(item) for item in nested)
        return ""

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

    def _cleanup_tempfiles(self, paths: List[str]) -> None:
        for path in paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception as cleanup_error:
                logger.warning("OCR縮小画像の削除に失敗しました: %s (%s)", path, cleanup_error)

    def _collect_image_path_stats(self, image_filepaths: List[str]) -> List[Dict[str, Any]]:
        stats: List[Dict[str, Any]] = []

        try:
            from PIL import Image
        except ImportError:
            Image = None  # type: ignore[assignment]

        for filepath in image_filepaths:
            try:
                file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
            except OSError:
                file_size = 0
            stat: Dict[str, Any] = {
                "path": filepath,
                "bytes": file_size,
                "width": None,
                "height": None,
            }
            if Image is not None and os.path.exists(filepath):
                try:
                    with Image.open(filepath) as image:
                        stat["width"], stat["height"] = image.size
                except Exception as image_error:
                    logger.debug("画像サイズ取得に失敗しました: %s (%s)", filepath, image_error)
            stats.append(stat)
        return stats

    def _format_image_stats_preview(self, image_stats: List[Dict[str, Any]], limit: int = 3) -> str:
        if not image_stats:
            return "n/a"

        previews: List[str] = []
        for index, stat in enumerate(image_stats[:limit], start=1):
            width = stat.get("width")
            height = stat.get("height")
            dims = f"{width}x{height}" if width and height else "unknown"
            previews.append(f"p{index}:{dims}/{stat.get('bytes', 0)}B")
        omitted = len(image_stats) - limit
        if omitted > 0:
            previews.append(f"...(+{omitted} pages)")
        return ", ".join(previews)

    def _select_ocr_rotation_angles_for_page(
        self,
        filepath: str,
        rotation_angles: tuple[int, ...],
        log_context: Optional[Dict[str, Any]] = None,
    ) -> tuple[int, ...]:
        if len(rotation_angles) <= 1:
            return rotation_angles

        image_stats = self._collect_image_path_stats([filepath])
        stat = image_stats[0] if image_stats else {}
        width = stat.get("width")
        height = stat.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            return rotation_angles
        if width == height:
            return rotation_angles

        if width > height:
            primary_angles = [angle for angle in rotation_angles if angle % 180 == 90]
            secondary_angles = [angle for angle in rotation_angles if angle % 180 != 90]
            strategy = "landscape_source_prioritize_portrait"
        else:
            primary_angles = [angle for angle in rotation_angles if angle % 180 == 0]
            secondary_angles = [angle for angle in rotation_angles if angle % 180 != 0]
            strategy = "portrait_source_prioritize_upright"

        prioritized = tuple(primary_angles + secondary_angles) or rotation_angles
        if prioritized != rotation_angles:
            logger.info(
                "OCR 回転順序を調整しました: source=%dx%d strategy=%s order=%s",
                width,
                height,
                strategy,
                _format_rotation_angles(prioritized),
                extra=self._build_log_extra(
                    log_context,
                    image_width=width,
                    image_height=height,
                    ocr_rotation_strategy=strategy,
                    ocr_rotation_order=_format_rotation_angles(prioritized),
                ),
            )
        return prioritized

    def _create_rotated_image_tempfile(
        self,
        filepath: str,
        rotation_degrees: int,
        log_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        import mimetypes
        import tempfile

        normalized_rotation = int(rotation_degrees) % 360
        if normalized_rotation == 0:
            return filepath

        try:
            from PIL import Image, ImageOps
        except ImportError as e:
            raise RuntimeError("Pillow が未導入のため OCR 画像の回転フォールバックを利用できません") from e

        content_type = mimetypes.guess_type(filepath)[0] or "image/jpeg"
        output_type = "image/jpeg" if content_type in ("image/jpeg", "image/jpg") else "image/png"
        suffix = ".jpg" if output_type == "image/jpeg" else ".png"

        with Image.open(filepath) as original_image:
            normalized_image = ImageOps.exif_transpose(original_image)
            source_image = normalized_image.copy()
        rotated_image = source_image.rotate(normalized_rotation, expand=True)

        fd, temp_path = tempfile.mkstemp(suffix=suffix, dir="/tmp")
        try:
            with os.fdopen(fd, "wb") as temp_file:
                if output_type == "image/jpeg":
                    rotated_image.convert("RGB").save(
                        temp_file,
                        format="JPEG",
                        quality=88,
                        optimize=True,
                        progressive=True,
                    )
                else:
                    save_image = rotated_image
                    if save_image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
                        save_image = save_image.convert("RGBA" if "A" in save_image.mode else "RGB")
                    save_image.save(temp_file, format="PNG", optimize=True, compress_level=9)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            self._cleanup_tempfiles([temp_path])
            raise

        logger.info(
            "OCR画像を回転しました: rotation=%d source=%s output=%s",
            normalized_rotation,
            filepath,
            temp_path,
            extra=self._build_log_extra(
                log_context,
                ocr_rotation_degrees=normalized_rotation,
                source_path=filepath,
                output_path=temp_path,
            ),
        )
        return temp_path

    def _create_optimized_image_tempfiles(
        self,
        image_filepaths: List[str],
        max_long_edge: int,
        log_context: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        import mimetypes
        import tempfile

        try:
            from PIL import Image, ImageOps
        except ImportError as e:
            raise RuntimeError("Pillow が未導入のため OCR 画像の縮小フォールバックを利用できません") from e

        temp_paths: List[str] = []
        optimization_stats: List[Dict[str, Any]] = []
        try:
            for filepath in image_filepaths:
                content_type = mimetypes.guess_type(filepath)[0] or "image/jpeg"
                output_type = "image/jpeg" if content_type in ("image/jpeg", "image/jpg") else "image/png"
                suffix = ".jpg" if output_type == "image/jpeg" else ".png"

                with Image.open(filepath) as original_image:
                    normalized_image = ImageOps.exif_transpose(original_image)
                    source_image = normalized_image.copy()
                original_width, original_height = source_image.size
                try:
                    original_bytes = os.path.getsize(filepath) if os.path.exists(filepath) else 0
                except OSError:
                    original_bytes = 0

                resized_image = source_image.copy()
                resized_image.thumbnail((max_long_edge, max_long_edge), Image.LANCZOS)
                resized_width, resized_height = resized_image.size

                fd, temp_path = tempfile.mkstemp(suffix=suffix, dir="/tmp")
                with os.fdopen(fd, "wb") as temp_file:
                    if output_type == "image/jpeg":
                        resized_image.convert("RGB").save(
                            temp_file,
                            format="JPEG",
                            quality=88,
                            optimize=True,
                            progressive=True,
                        )
                    else:
                        save_image = resized_image
                        if save_image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
                            save_image = save_image.convert("RGBA" if "A" in save_image.mode else "RGB")
                        save_image.save(temp_file, format="PNG", optimize=True, compress_level=9)
                temp_paths.append(temp_path)
                try:
                    optimized_bytes = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
                except OSError:
                    optimized_bytes = 0
                optimization_stats.append({
                    "source_path": filepath,
                    "output_path": temp_path,
                    "original_width": original_width,
                    "original_height": original_height,
                    "optimized_width": resized_width,
                    "optimized_height": resized_height,
                    "original_bytes": original_bytes,
                    "optimized_bytes": optimized_bytes,
                })

            total_original_bytes = sum(stat["original_bytes"] for stat in optimization_stats)
            total_optimized_bytes = sum(stat["optimized_bytes"] for stat in optimization_stats)
            preview_parts: List[str] = []
            for index, stat in enumerate(optimization_stats[:3], start=1):
                preview_parts.append(
                    (
                        f"p{index}:{stat['original_width']}x{stat['original_height']}/{stat['original_bytes']}B"
                        f" -> {stat['optimized_width']}x{stat['optimized_height']}/{stat['optimized_bytes']}B"
                    )
                )
            omitted = len(optimization_stats) - 3
            if omitted > 0:
                preview_parts.append(f"...(+{omitted} pages)")
            logger.info(
                "OCR画像を最適化しました: long_edge<=%d pages=%d total_bytes=%d -> %d preview=%s",
                max_long_edge,
                len(optimization_stats),
                total_original_bytes,
                total_optimized_bytes,
                ", ".join(preview_parts) if preview_parts else "n/a",
                extra=self._build_log_extra(
                    log_context,
                    ocr_variant=f"long-edge<={max_long_edge}",
                    ocr_pages=len(optimization_stats),
                    original_total_bytes=total_original_bytes,
                    optimized_total_bytes=total_optimized_bytes,
                ),
            )

            return temp_paths
        except Exception:
            self._cleanup_tempfiles(temp_paths)
            raise

    def _extract_text_from_image_filepaths_once(
        self,
        client,
        image_filepaths: List[str],
        variant_label: str,
        log_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        import base64
        import mimetypes
        import oci

        prompt = _get_prompt("ocr_output_rules")

        page_texts: List[Dict[str, Any]] = []
        merged_texts: List[str] = []

        for index, filepath in enumerate(image_filepaths):
            page_no = index + 1
            page_started_at = time.monotonic()
            page_log_context = self._build_log_extra(
                log_context,
                ocr_variant=variant_label,
                ocr_page=page_no,
                ocr_pages=len(image_filepaths),
            )
            extracted_text = ""
            primary_empty_response_attempts = GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES + 1
            secondary_empty_response_attempts = GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES + 1
            rotation_angles = self._select_ocr_rotation_angles_for_page(
                filepath,
                GENAI_OCR_ROTATION_ANGLES or (0,),
                log_context=page_log_context,
            )
            total_request_attempts = 0
            last_rotation_degrees = 0
            rotation_total_attempts = len(rotation_angles)

            for rotation_index, rotation_degrees in enumerate(rotation_angles, start=1):
                candidate_path = filepath
                cleanup_paths: List[str] = []
                last_rotation_degrees = rotation_degrees
                try:
                    if rotation_degrees != 0:
                        candidate_path = self._create_rotated_image_tempfile(
                            filepath,
                            rotation_degrees,
                            log_context=page_log_context,
                        )
                        cleanup_paths.append(candidate_path)

                    with open(candidate_path, "rb") as f:
                        image_data = f.read()
                    content_type = mimetypes.guess_type(candidate_path)[0] or "image/jpeg"
                    encoded = base64.b64encode(image_data).decode("ascii")

                    logger.info(
                        "VLM OCR ページ送信を開始します: variant=%s page=%d/%d rotation=%d bytes=%d content_type=%s",
                        variant_label,
                        page_no,
                        len(image_filepaths),
                        rotation_degrees,
                        len(image_data),
                        content_type,
                        extra=self._build_log_extra(
                            page_log_context,
                            ocr_rotation_degrees=rotation_degrees,
                            ocr_rotation_attempt=rotation_index,
                            ocr_rotation_total_attempts=rotation_total_attempts,
                            ocr_rotation_priority="primary" if rotation_index == 1 else "secondary",
                            page_bytes=len(image_data),
                            page_content_type=content_type,
                        ),
                    )

                    chat_request = oci.generative_ai_inference.models.GenericChatRequest(
                        api_format="GENERIC",
                        messages=[
                            oci.generative_ai_inference.models.UserMessage(
                                content=[
                                    {
                                        "type": "IMAGE",
                                        "imageUrl": {
                                            "url": f"data:{content_type};base64,{encoded}"
                                        }
                                    },
                                    {"type": "TEXT", "text": prompt},
                                ]
                            )
                        ],
                        max_tokens=self._vlm_max_tokens,
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

                    operation_name = (
                        f"extract_text_from_images[{page_no}]/{variant_label}/rot{rotation_degrees}"
                    )
                    empty_response_attempts = (
                        primary_empty_response_attempts
                        if rotation_index == 1
                        else secondary_empty_response_attempts
                    )
                    for empty_response_attempt in range(1, empty_response_attempts + 1):
                        total_request_attempts += 1
                        response = self._retry_api_call(
                            operation_name,
                            client.chat,
                            chat_detail,
                            log_context=self._build_log_extra(
                                page_log_context,
                                ocr_rotation_degrees=rotation_degrees,
                                ocr_rotation_attempt=rotation_index,
                                ocr_rotation_total_attempts=rotation_total_attempts,
                                ocr_rotation_priority="primary" if rotation_index == 1 else "secondary",
                            ),
                        )
                        chat_response = getattr(getattr(response, "data", None), "chat_response", None)
                        extracted_text = self._get_text_from_chat_response(chat_response).strip()
                        if extracted_text:
                            if total_request_attempts > 1:
                                logger.info(
                                    "%s: VLM OCR 空応答から復帰しました (rotation=%d request_attempt=%d)",
                                    operation_name,
                                    rotation_degrees,
                                    total_request_attempts,
                                    extra=self._build_log_extra(
                                        page_log_context,
                                        ocr_rotation_degrees=rotation_degrees,
                                        ocr_rotation_attempt=rotation_index,
                                        ocr_rotation_total_attempts=rotation_total_attempts,
                                        ocr_rotation_priority="primary" if rotation_index == 1 else "secondary",
                                        empty_response_attempt=empty_response_attempt,
                                        empty_response_total_attempts=empty_response_attempts,
                                        total_request_attempts=total_request_attempts,
                                    ),
                                )
                            break

                        is_last_request_for_rotation = empty_response_attempt >= empty_response_attempts
                        is_last_rotation = rotation_index >= rotation_total_attempts
                        if is_last_request_for_rotation and is_last_rotation:
                            raise ValueError(
                                "VLMによるテキスト抽出結果が空でした "
                                f"(page={page_no}, variant={variant_label}, attempts={total_request_attempts}, "
                                f"rotation={rotation_degrees}, rotation_attempts={rotation_total_attempts}, "
                                f"primary_empty_response_attempts={primary_empty_response_attempts}, "
                                f"secondary_empty_response_attempts={secondary_empty_response_attempts})"
                            )

                        delay = min(3.0, self._calculate_backoff_delay(total_request_attempts - 1))
                        if is_last_request_for_rotation:
                            next_rotation = rotation_angles[rotation_index]
                            logger.warning(
                                "%s: VLM OCR 応答が空でした。%.1f秒後に %d 度回転して再試行します "
                                "(rotation_attempt %d/%d, total_request_attempt=%d)",
                                operation_name,
                                delay,
                                next_rotation,
                                rotation_index,
                                rotation_total_attempts,
                                total_request_attempts,
                                extra=self._build_log_extra(
                                    page_log_context,
                                    ocr_rotation_degrees=rotation_degrees,
                                    ocr_rotation_attempt=rotation_index,
                                    ocr_rotation_total_attempts=rotation_total_attempts,
                                    ocr_rotation_priority="primary" if rotation_index == 1 else "secondary",
                                    empty_response_attempt=empty_response_attempt,
                                    empty_response_total_attempts=empty_response_attempts,
                                    total_request_attempts=total_request_attempts,
                                    retry_after_seconds=delay,
                                ),
                            )
                        else:
                            logger.warning(
                                "%s: VLM OCR 応答が空でした。%.1f秒後に同一向きで再試行します "
                                "(rotation=%d attempt %d/%d, total_request_attempt=%d)",
                                operation_name,
                                delay,
                                rotation_degrees,
                                empty_response_attempt,
                                empty_response_attempts,
                                total_request_attempts,
                                extra=self._build_log_extra(
                                    page_log_context,
                                    ocr_rotation_degrees=rotation_degrees,
                                    ocr_rotation_attempt=rotation_index,
                                    ocr_rotation_total_attempts=rotation_total_attempts,
                                    ocr_rotation_priority="primary" if rotation_index == 1 else "secondary",
                                    empty_response_attempt=empty_response_attempt,
                                    empty_response_total_attempts=empty_response_attempts,
                                    total_request_attempts=total_request_attempts,
                                    retry_after_seconds=delay,
                                ),
                            )
                        time.sleep(delay)

                    if extracted_text:
                        break
                finally:
                    self._cleanup_tempfiles(cleanup_paths)

                if extracted_text:
                    break

            if not extracted_text:
                raise ValueError(
                    "VLMによるテキスト抽出結果が空でした "
                    f"(page={page_no}, variant={variant_label}, attempts={total_request_attempts}, "
                    f"rotation={last_rotation_degrees}, rotation_attempts={rotation_total_attempts}, "
                    f"primary_empty_response_attempts={primary_empty_response_attempts}, "
                    f"secondary_empty_response_attempts={secondary_empty_response_attempts})"
                )

            elapsed = time.monotonic() - page_started_at
            logger.info(
                "VLM OCR ページ抽出が完了しました: variant=%s page=%d/%d text_length=%d elapsed=%.1fs",
                variant_label,
                page_no,
                len(image_filepaths),
                len(extracted_text),
                elapsed,
                extra=self._build_log_extra(
                    log_context,
                    ocr_variant=variant_label,
                    ocr_page=page_no,
                    ocr_pages=len(image_filepaths),
                    ocr_rotation_degrees=last_rotation_degrees,
                    ocr_rotation_priority="primary" if last_rotation_degrees == rotation_angles[0] else "secondary",
                    text_length=len(extracted_text),
                    elapsed_seconds=round(elapsed, 3),
                ),
            )

            page_texts.append({
                "page_index": index,
                "source_path": filepath,
                "rotation_degrees": last_rotation_degrees,
                "text": extracted_text,
            })
            merged_texts.append(f"[PAGE {index + 1}]\n{extracted_text}")

        return {
            "success": True,
            "extracted_text": "\n\n".join(merged_texts).strip(),
            "page_texts": page_texts,
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

        prompt = _get_prompt("classify_invoice")

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
                max_tokens=self._vlm_max_tokens,
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
                max_tokens=self._vlm_max_tokens,
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
                        self._raise_if_rate_limited(e)
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
                    max_tokens=self._vlm_max_tokens,
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
                    max_tokens=self._vlm_max_tokens,
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
                        self._raise_if_rate_limited(e)
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
                    self._raise_if_rate_limited(repair_error)
                    logger.warning("第2フェーズも失敗。保底分類へフォールバック: %s", repair_error)
                    return self._build_fallback_classification()

            return self._normalize_classification_result(parsed)
        except Exception as e:
            self._raise_if_rate_limited(e)
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
{_get_prompt("extract_data_value_rules")}
{_get_prompt("structured_data_reading")}

【カラム名の厳守】
- header_fields[].field_name_en: 必ず HEADERテーブルの COLUMN_NAME をそのまま使用（UPPERCASE、変名・追加・省略禁止）
- raw_lines[] のキー: 必ず LINEテーブルの COLUMN_NAME をそのまま使用（UPPERCASE）
- スキーマに存在しないカラム名は絶対に作成しない

【出力形式】（JSON のみ。マークダウン・コードブロック・コメント禁止）
{{
  "header_fields": [
    {{"field_name": "あああ", "field_name_en": "AAA", "value": "あああ", "data_type": "VARCHAR2", "max_length": 50, "is_required": true}},
    {{"field_name": "いいい", "field_name_en": "BBB", "value": "2000-01-01", "data_type": "DATE", "max_length": null, "is_required": true}},
    {{"field_name": "ううう", "field_name_en": "CCC", "value": "0", "data_type": "NUMBER", "max_length": null, "is_required": true}}
  ],
  "line_fields": [
    {{"field_name": "あああ", "field_name_en": "AAA", "value": "あああ", "data_type": "VARCHAR2", "max_length": 200, "is_required": true}},
    {{"field_name": "いいい", "field_name_en": "BBB", "value": "0", "data_type": "NUMBER", "max_length": null, "is_required": true}}
  ],
  "line_count": 2,
  "raw_lines": [
    {{"AAA": "あああ", "BBB": "0", "CCC": "0", "DDD": "0"}},
    {{"AAA": "いいい", "BBB": "0", "CCC": "0", "DDD": "0"}}
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
{_get_prompt("extract_schema_completeness")}
{_get_prompt("selection_schema_design")}

【Oracleカラム設計基準】
{_get_prompt("extract_schema_oracle_design")}

【出力形式】（JSON のみ。マークダウン・コードブロック・コメント禁止）
{{
  "header_fields": [
    {{"field_name": "あああ", "field_name_en": "AAA", "value": "あああ", "data_type": "VARCHAR2", "max_length": 50, "is_required": true}},
    {{"field_name": "いいい", "field_name_en": "BBB", "value": "2000-01-01", "data_type": "DATE", "max_length": null, "is_required": true}},
    {{"field_name": "ううう", "field_name_en": "CCC", "value": "あああ", "data_type": "VARCHAR2", "max_length": 200, "is_required": true}},
    {{"field_name": "えええ", "field_name_en": "DDD", "value": "0", "data_type": "NUMBER", "max_length": null, "is_required": true}},
    {{"field_name": "おおお", "field_name_en": "EEE", "value": "0", "data_type": "NUMBER", "max_length": null, "is_required": false}}
  ],
  "line_fields": [
    {{"field_name": "あああ", "field_name_en": "AAA", "value": "あああ", "data_type": "VARCHAR2", "max_length": 200, "is_required": true}},
    {{"field_name": "いいい", "field_name_en": "BBB", "value": "0", "data_type": "NUMBER", "max_length": null, "is_required": true}},
    {{"field_name": "ううう", "field_name_en": "CCC", "value": "0", "data_type": "NUMBER", "max_length": null, "is_required": true}},
    {{"field_name": "えええ", "field_name_en": "DDD", "value": "0", "data_type": "NUMBER", "max_length": null, "is_required": true}}
  ],
  "line_count": 2,
  "raw_lines": [
    {{"AAA": "あああ", "BBB": "0", "CCC": "0", "DDD": "0"}},
    {{"AAA": "いいい", "BBB": "0", "CCC": "0", "DDD": "0"}}
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
                max_tokens=self._vlm_max_tokens,
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
            self._raise_if_rate_limited(e)
            logger.error("フィールド抽出エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"フィールド抽出失敗: {str(e)}"}

    def extract_data_from_text(
        self,
        ocr_text: str,
        category: str = "",
        table_schema: Optional[Dict[str, Any]] = None,
        log_context: Optional[Dict[str, Any]] = None,
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
{_get_prompt("extract_text_value_rules")}
{_get_prompt("structured_data_reading")}

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
            extraction_started_at = time.monotonic()

            logger.info(
                "LLMフィールド抽出リクエストを準備しました: category=%s ocr_chars=%d header_columns=%d line_columns=%d header_table=%s line_table=%s",
                category or "-",
                len(ocr_text),
                len(table_schema.get("header_columns", [])),
                len(table_schema.get("line_columns", [])),
                header_tbl or "-",
                line_tbl or "-",
                extra=self._build_log_extra(
                    log_context,
                    category=category or "",
                    ocr_chars=len(ocr_text),
                    header_column_count=len(table_schema.get("header_columns", [])),
                    line_column_count=len(table_schema.get("line_columns", [])),
                    header_table_name=header_tbl,
                    line_table_name=line_tbl,
                ),
            )
            
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
                response = self._retry_api_call(
                    "extract_data_from_text",
                    client.chat,
                    chat_detail,
                    log_context=self._build_log_extra(log_context),
                )
                return self._get_text_from_chat_response(response.data.chat_response)

            parsed = self._parse_json_with_regeneration(
                "extract_data_from_text",
                generate_text,
                GENAI_JSON_PARSE_RETRIES,
                log_context=self._build_log_extra(log_context),
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

            elapsed = time.monotonic() - extraction_started_at
            logger.info(
                "LLMフィールド抽出が完了しました: header_fields=%d line_fields=%d raw_lines=%d line_count=%d elapsed=%.1fs",
                len(header_fields),
                len(line_fields),
                len(raw_lines),
                line_count,
                elapsed,
                extra=self._build_log_extra(
                    log_context,
                    header_field_count=len(header_fields),
                    line_field_count=len(line_fields),
                    raw_line_count=len(raw_lines),
                    line_count=line_count,
                    elapsed_seconds=round(elapsed, 3),
                ),
            )
            return parsed

        except Exception as e:
            self._raise_if_rate_limited(e)
            logger.error(
                "テキストからのデータ抽出エラー: %s",
                e,
                exc_info=True,
                extra=self._build_log_extra(log_context),
            )
            return {"success": False, "message": f"テキストからのデータ抽出失敗: {str(e)}"}


    def extract_text_from_images(
        self,
        image_filepaths: List[str],
        log_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """伝票画像群からVLMを用いてテキストを抽出する

        VLM は画像1枚ずつ実行し、結果だけを最後に結合して返す。
        原寸で失敗した場合のみ、長辺上限ベースの最適化画像で段階再試行する。
        """
        client = self._get_client()
        if not client:
            return {"success": False, "message": "AI クライアントが初期化されていません"}

        try:
            valid_filepaths = [filepath for filepath in image_filepaths if os.path.exists(filepath)]
            if not valid_filepaths:
                return {"success": False, "message": "有効な画像ファイルがありません"}

            original_image_stats = self._collect_image_path_stats(valid_filepaths)
            logger.info(
                "VLM OCR 入力画像を受け付けました: pages=%d total_bytes=%d preview=%s",
                len(original_image_stats),
                sum(stat.get("bytes", 0) for stat in original_image_stats),
                self._format_image_stats_preview(original_image_stats),
                extra=self._build_log_extra(
                    log_context,
                    ocr_variant="original",
                    ocr_pages=len(original_image_stats),
                    ocr_total_bytes=sum(stat.get("bytes", 0) for stat in original_image_stats),
                ),
            )

            variant_sequence: List[tuple[str, Optional[int]]] = [("original", None)]
            variant_sequence.extend(
                [(f"long-edge<={max_edge}", max_edge) for max_edge in (GENAI_OCR_IMAGE_MAX_EDGE_STEPS or ())]
            )

            last_error: Optional[Exception] = None
            total_attempts = len(variant_sequence)

            for attempt_index, (variant_label, max_long_edge) in enumerate(variant_sequence, start=1):
                variant_paths = valid_filepaths
                cleanup_paths: List[str] = []
                variant_stats = original_image_stats

                try:
                    if max_long_edge is not None:
                        variant_paths = self._create_optimized_image_tempfiles(
                            valid_filepaths,
                            max_long_edge,
                            log_context=log_context,
                        )
                        cleanup_paths = list(variant_paths)
                        variant_stats = self._collect_image_path_stats(variant_paths)

                    logger.info(
                        "VLM OCR を開始します: variant=%s pages=%d total_bytes=%d attempt=%d/%d preview=%s",
                        variant_label,
                        len(variant_stats),
                        sum(stat.get("bytes", 0) for stat in variant_stats),
                        attempt_index,
                        total_attempts,
                        self._format_image_stats_preview(variant_stats),
                        extra=self._build_log_extra(
                            log_context,
                            ocr_variant=variant_label,
                            ocr_pages=len(variant_stats),
                            ocr_total_bytes=sum(stat.get("bytes", 0) for stat in variant_stats),
                            ocr_attempt=attempt_index,
                            ocr_total_attempts=total_attempts,
                        ),
                    )
                    result = self._extract_text_from_image_filepaths_once(
                        client,
                        variant_paths,
                        variant_label,
                        log_context=log_context,
                    )
                    if max_long_edge is not None:
                        logger.info(
                            "VLM OCR フォールバック成功: variant=%s attempt=%d/%d text_length=%d",
                            variant_label,
                            attempt_index,
                            total_attempts,
                            len(result.get("extracted_text", "")),
                            extra=self._build_log_extra(
                                log_context,
                                ocr_variant=variant_label,
                                ocr_attempt=attempt_index,
                                ocr_total_attempts=total_attempts,
                                text_length=len(result.get("extracted_text", "")),
                            ),
                        )
                    else:
                        logger.info(
                            "VLM OCR 原寸成功: variant=%s attempt=%d/%d text_length=%d",
                            variant_label,
                            attempt_index,
                            total_attempts,
                            len(result.get("extracted_text", "")),
                            extra=self._build_log_extra(
                                log_context,
                                ocr_variant=variant_label,
                                ocr_attempt=attempt_index,
                                ocr_total_attempts=total_attempts,
                                text_length=len(result.get("extracted_text", "")),
                            ),
                        )
                    return result
                except AIRateLimitError:
                    raise
                except Exception as e:
                    last_error = e
                    if attempt_index < total_attempts:
                        if max_long_edge is None:
                            logger.warning(
                                "VLM OCR 原寸試行に失敗したため、画像最適化フォールバックへ切り替えます: pages=%d total_bytes=%d error=%s",
                                len(variant_stats),
                                sum(stat.get("bytes", 0) for stat in variant_stats),
                                str(e)[:200],
                                extra=self._build_log_extra(
                                    log_context,
                                    ocr_variant=variant_label,
                                    ocr_pages=len(variant_stats),
                                    ocr_total_bytes=sum(stat.get("bytes", 0) for stat in variant_stats),
                                    ocr_attempt=attempt_index,
                                    ocr_total_attempts=total_attempts,
                                ),
                            )
                        else:
                            logger.warning(
                                "VLM OCR 試行失敗。より小さい長辺上限で再試行します: variant=%s total_bytes=%d error=%s",
                                variant_label,
                                sum(stat.get("bytes", 0) for stat in variant_stats),
                                str(e)[:200],
                                extra=self._build_log_extra(
                                    log_context,
                                    ocr_variant=variant_label,
                                    ocr_total_bytes=sum(stat.get("bytes", 0) for stat in variant_stats),
                                    ocr_attempt=attempt_index,
                                    ocr_total_attempts=total_attempts,
                                ),
                            )
                        continue
                    raise
                finally:
                    self._cleanup_tempfiles(cleanup_paths)

            raise last_error or RuntimeError("OCR画像の処理に失敗しました")

        except Exception as e:
            self._raise_if_rate_limited(e)
            logger.error(
                "VLM テキスト抽出エラー: %s",
                e,
                exc_info=True,
                extra=self._build_log_extra(log_context),
            )
            return {"success": False, "message": f"テキスト抽出失敗: {str(e)}"}

    def generate_sql_schema_from_text(
        self,
        ocr_text: str,
        analysis_mode: str,
        log_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
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

{_get_prompt("generate_sql_requirements").replace("{header_only_hint}", header_only_hint)}
{_get_prompt("selection_schema_design")}

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
                response = self._retry_api_call(
                    "generate_sql_schema_from_text",
                    client.chat,
                    chat_detail,
                    log_context=self._build_log_extra(log_context),
                )
                return self._get_text_from_chat_response(response.data.chat_response)

            parsed = self._parse_json_with_regeneration(
                "generate_sql_schema_from_text",
                generate_text,
                GENAI_JSON_PARSE_RETRIES,
                log_context=self._build_log_extra(log_context),
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
                    original_data_type = str(c.get("data_type", "VARCHAR2")).upper()
                    data_type = original_data_type
                    if data_type not in {"VARCHAR2", "NUMBER", "DATE", "TIMESTAMP"}:
                        data_type = "VARCHAR2"
                    max_length = (
                        self._buffer_varchar2_length(c.get("data_length"), original_data_type)
                        if data_type == "VARCHAR2"
                        else None
                    )

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
            self._raise_if_rate_limited(e)
            logger.error(
                "スキーマ生成エラー: %s",
                e,
                exc_info=True,
                extra=self._build_log_extra(log_context),
            )
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
  "header_ddl": "CREATE TABLE INV_H (\\n  HEADER_ID NUMBER NOT NULL,\\n  ...\\n)",
  "line_ddl": "CREATE TABLE INV_L (\\n  LINE_ID NUMBER NOT NULL,\\n  HEADER_ID NUMBER NOT NULL,\\n  ...\\n)"
}}

注意:
{_get_prompt("suggest_ddl_rules")}"""

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
            self._raise_if_rate_limited(e)
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
{_get_prompt("text_to_sql_constraints")}"""

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
            self._raise_if_rate_limited(e)
            logger.error("Text-to-SQL変換エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"SQL生成に失敗しました: {str(e)}"}
