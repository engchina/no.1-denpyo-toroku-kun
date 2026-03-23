"""
AI 分析サービス

OCI Generative AI (google.gemini-2.5-pro) を使用した伝票画像の分析を提供します。
- OCR テキストの抽出
- OCR テキストからのフィールド抽出
- OCR テキストからのテーブル構造推定
- 自然言語検索の SQL 生成

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

## Rule 0: Faithful Transcription (Overrides All Other Rules)
CRITICAL — transcribe every character EXACTLY as it appears in the image. \
Do NOT apply linguistic knowledge, spelling correction, word normalization, \
or substitution of visually similar characters.
- Each character must be read independently from its visual shape in the image. \
Do not infer or replace a character based on what word would be more common, \
more grammatically natural, or more familiar in the language.
- Abbreviated, domain-specific, or unconventional terms that exist in the document \
must be preserved verbatim. Do NOT replace them with standard or more common \
equivalents (e.g., a field label that appears to be a domain-specific abbreviation \
must be copied exactly — do not substitute a more common word that looks similar).
- If two characters look visually similar but are distinct (e.g., different kanji \
with similar strokes), transcribe the one actually present in the image, not the \
more frequently occurring one.
- When uncertain between two visually similar characters, choose the one whose \
visual shape more closely matches the actual ink strokes in the image.

## Rule 1: Tables and Grid-Based Forms

### Step A — Column structure (analyze BEFORE transcribing any row)
0. Identify the row-label area FIRST: determine how many leftmost columns serve \
exclusively as row-label columns (they contain categorical labels that organize \
the rows, NOT measured or recorded values). Call this count M (M = 0 when all \
columns are data columns, M ≥ 1 when row labels occupy one or more columns). \
CRITICAL — a cell that spans the intersection of the row-label area and the \
column-header rows (the top-left corner cell) is a descriptor for the row axis \
only; do NOT treat it as a data column header.
1. Count how many header rows are stacked at the top of the DATA-column area — \
the columns to the right of the M row-label columns (there may be multiple layers).
2. Determine the total number of LEAF DATA columns — the finest-grained columns \
to the right of the row-label area that actually hold data values.
3. Build a fully-qualified name for each leaf data column by concatenating the \
texts of all ancestor header cells from outermost (top) to innermost (bottom), \
joined with a single space. A header cell that visually spans N leaf columns \
contributes its text as a prefix to all N leaf-column names beneath it. If a \
header cell is visually empty (blank or contains only whitespace), skip it — do \
not insert a space segment for it; use only the non-empty ancestor and leaf texts.
4. Fix M, the leaf-data-column count, and all fully-qualified column names for \
the entire table. These values must not change for any data row.
5. Body-embedded column-group labels: Some tables embed a column-group label as a \
VERTICALLY MERGED cell within the data body rather than in the column-header rows \
at the top. Identify these cells BEFORE transcribing any row by the following \
criteria — ALL must hold: \
(a) the cell spans two or more data rows (rowspan ≥ 2); \
(b) the cell is NOT within the M leftmost row-label columns; \
(c) the cell does NOT appear in the column-header rows at the top; \
(d) the cell contains descriptive text (a category name, measurement-dimension \
label, or unit group name) rather than a numeric or structured data value. \
When this pattern is detected: treat the cell's text as an additional column-group \
prefix for every leaf data column that falls within the same visual column region \
(the span covered by that merged cell horizontally); prepend this prefix — \
separated by a single space — to the fully-qualified name of each affected leaf \
column, exactly as if it had appeared as a spanning header in the column-header \
rows. Do NOT emit the cell's text as a data value in any row. If multiple such \
body-embedded labels exist in the same table, process each one independently and \
apply its prefix only to the columns within its horizontal span.

### Step B — Row label hierarchy (analyze BEFORE transcribing any row)
1. Row labels occupy the M leftmost columns identified in Step A-0. They may \
span two or more levels of nesting across those columns (outermost level in the \
leftmost column, innermost level in the M-th column).
2. A cell in the row-label area that visually spans multiple rows (merged cell, \
bold/indented section title, or a cell with no corresponding data value in that \
row) is a group-header. Propagate its exact text to every data row it covers.
3. Build the fully-qualified row label for each data row by concatenating ALL \
ancestor group-header texts and the row's own label, separated by a single space, \
from outermost to innermost. Use the EXACT text as printed — do NOT rephrase, \
abbreviate, or reorder any segment. Always preserve the outermost group label \
even when the column axis also carries a group label of its own — the full row \
path must be retained verbatim so that downstream tools can look up values by \
matching on a trailing segment of the row label.
4. CRITICAL — pre-enumerate all rows: before writing any output, scan the entire \
table and list every data row with its fully-qualified row label. This prevents \
row labels from shifting or being lost mid-table.

### Step C — Output
- Render every table using GitHub-Flavored Markdown table syntax.
- The Markdown header row must use the fully-qualified column names from Step A.
- If the table has row labels (M ≥ 1 from Step A-0): the first (leftmost) \
Markdown column must contain the fully-qualified row label. Use the corner cell \
text (Step A-0) as that column's header; if the corner cell is empty or contains \
only whitespace, use a generic descriptor (e.g., "項目"). For tables with NO \
row-label columns (M = 0), the first column is simply the first data column.
- Each LOGICAL data row occupies exactly ONE Markdown table row.
- CRITICAL — column integrity: every row must have exactly (1 + leaf-data-column-count) \
cells when M ≥ 1, or exactly leaf-data-column-count cells when M = 0 — as fixed \
in Step A. Never merge values from adjacent columns into one cell, and never \
shift a value left or right into a wrong column.
- Merged data cells (colspan): repeat the cell's value in each column it spans.
- Merged data cells (rowspan): repeat the cell's value in each row it spans.
- CRITICAL — cross-indexed tables (M ≥ 1 AND the column headers have two or more \
levels of hierarchy, i.e., any column's fully-qualified name contains a space from \
ancestor concatenation) MUST be output as ONE complete, standalone Markdown table \
with the following requirements: \
(1) Output ALL data rows identified in Step B and ALL leaf data columns identified \
in Step A — no row and no column may be omitted or combined. \
(2) Every (row, column) cell must appear. If a physical cell is blank or empty, \
output an empty string "" for that cell — do NOT skip the cell or collapse \
adjacent cells. \
(3) Do NOT split the table into multiple sub-tables grouped by row-group section \
or column group. One physical table in the document → exactly one Markdown table \
in the output, regardless of how many row-group levels or column-group levels exist. \
(4) Do NOT insert any text, commentary, or heading BETWEEN the rows of the table. \
(5) Precede the Markdown table with a Markdown section heading (## descriptive title) \
derived from the document context (section title, form label, or the dominant \
measurement-category name visible near the table); if no clear title exists, \
compose a brief descriptor from the row-group label and column-group labels \
separated by " / ".
- To locate column boundaries when grid lines are faint or absent, align each \
value with its fully-qualified header. If a cell appears to contain text belonging \
to the next column, split at the header-alignment boundary.
- If a cell's content wraps across multiple visual lines within the same cell \
boundary, join them with a single space.
- If a single cell contains multiple sub-values separated by "/" or a line break \
that are NOT divided by separate grid columns, preserve them as-is in one cell value.
- Always include a header row; if no headers are printed, infer short descriptive \
names (Column1, Column2, …).

### Step D — Form-style tables (alternating label / value columns)
Japanese inspection and specification forms (検査表, 仕様書, etc.) often use a \
grid where each row intermixes label cells and value cells horizontally. The \
pattern looks like: "| CategoryA | SubLabel1 | Primary | (value) | SubLabel2 | \
(value) | SubLabel3 | (value) |", where CategoryA and each SubLabel are labels \
and the parenthesized cells are their corresponding values. \
In this pattern there is no dedicated header row; the "header" information is \
encoded inside the leftmost cells and the alternating sub-label cells.
Detect this pattern when: (a) most rows contain cells that serve as category or \
sub-category labels followed immediately by value cells, and (b) there is no \
distinct top-level header row whose cells span the full column set. \
For such tables, DO NOT use generic column names (e.g., "Section", "Specification", \
"Value", "Column1"). Instead, reconstruct fully-qualified column names by \
concatenating ALL ancestor label cells that precede each value cell in reading \
order (left to right within the row, top to bottom across rows), joined with a \
single space. If a row spans multiple visual rows for the same logical record, \
propagate ancestor labels across those rows. Emit the result as a Markdown table \
whose header row uses those fully-qualified names and whose single data row \
contains the corresponding values. Apply this same logic within each section \
block when a document has multiple such sections.

## Rule 2: Key-Value / Label-Value Fields
Applies ONLY to standalone label-value fields that are NOT part of a formal table or grid structure (Rule 1 takes precedence inside tables).
- Horizontal layout (label and value appear on the same line, or in adjacent cells of the same row): output as "Label: Value" on a single line.
- Vertical layout (label appears in one row or cell and its corresponding value is directly below in the same column, with no other column separating them): treat each such column as an independent key-value pair and output as "Label: Value" on a single line.
- If a field value wraps visually across multiple lines, join them into one line.

## Rule 3: Selection and Choice Fields
Mark every visually indicated selection regardless of the indicator style:
- Circled (○ ◯ ●), checked (✓ ✗ ☑ ☒), underlined, boxed, filled, or otherwise \
highlighted options → append [SELECTED] immediately after the chosen option.
- CRITICAL — strikethrough overrides any encircling or highlighting mark: if an \
option carries BOTH a circle/highlight AND a strikethrough or deletion line drawn \
through it at the same time, treat it as [REJECTED], NOT [SELECTED]. A strikethrough \
always takes priority over an encircling mark.
- Append [REJECTED] immediately after any option that is explicitly crossed out \
or struck through (including options that are simultaneously circled and struck through).
- For checkbox lists, prefix each item with [CHECKED] or [ ] on its own line.
- Example inline:   "Yes[SELECTED] / No"
- Example checkbox: "[CHECKED] Option A / [ ] Option B / [CHECKED] Option C"

## Rule 4: Free Text Regions
- Preserve paragraph breaks with a blank line.
- Do NOT add artificial line breaks that do not exist in the original.

## Rule 5: Special Visual Elements
- Stamps or seals: <STAMP: text>
  Recognition guidance: ink stamps typically appear as circular or rectangular \
  impressions in red, blue, or black ink, often containing characters (names, \
  organization names, or dates) arranged in a linear or circular layout within \
  the boundary. Read the characters by following the layout direction (left-to-right \
  for linear; clockwise from the top for circular). If only partial characters are \
  legible, record what can be read. If completely illegible, use <STAMP: >.
  NEVER skip this tag when a stamp impression is visually present — always output \
  <STAMP: text> or <STAMP: > regardless of legibility.
- Handwritten notes:   <HANDWRITTEN: text>
- Signatures:          <SIGNATURE>
- Barcodes / QR codes: <BARCODE: value_if_readable>
- Illegible text:      <ILLEGIBLE>
- Redacted / masked:   <REDACTED>
- CRITICAL — stamps inside table cells: When a stamp or seal image appears inside \
a table cell (Rule 1), embed the <STAMP: text> tag as the cell's content. NEVER \
leave a cell empty when a stamp image is visually present in that cell. The column \
header of that cell serves as the field label; the <STAMP: text> tag is its value.

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
- Hierarchical row labels: When the OCR text contains row labels that were formed \
by concatenating multiple ancestor group-header labels and a leaf label \
(e.g., "GrandParent Parent LeafLabel"), treat the full concatenated string as the \
unique field identifier. Map the corresponding value to the column whose logical \
name matches that exact concatenated label. Do not attempt to re-split or \
re-interpret any part of the concatenated label, regardless of nesting depth.
- Hierarchical column names: When the OCR text uses fully-qualified column names \
formed by concatenating ancestor header labels (e.g., "OuterHeader InnerHeader"), \
treat the full concatenated string as the column identifier. Do not re-split it.
- Cell lookup in two-dimensional tables: When a logical name combines a \
fully-qualified row label AND a column header (e.g., "RowPath ColumnHeader"), \
locate the value by (1) finding the Markdown table row whose first cell equals \
the row-label portion, and (2) reading the value from the column whose header \
equals the column-header portion. To identify the split point, cross-reference \
the actual column headers of the Markdown table: the longest trailing segment of \
the logical name that matches a column header is the column-header portion; the \
remaining leading segment is the row-label portion. \
CRITICAL — cross-indexed Markdown tables: When the OCR output contains a \
standalone Markdown table where (a) the first column contains concatenated \
multi-level row-path strings and (b) the remaining column headers are \
fully-qualified multi-level names (containing spaces from ancestor concatenation), \
treat it as a cross-indexed table. Look up each value by: \
(i) scanning the first column for the row whose text exactly equals the \
row-label portion of the logical name; \
(ii) scanning the header row for the column whose text exactly equals the \
column-header portion; \
(iii) reading the cell at that (row, column) intersection. \
Never attempt to re-interpret, re-split, or partially match either the row \
label or the column header — both portions must match exactly as they appear \
in the Markdown table.
- Measurement-dimension precedence in logical names: Some column logical names \
are formed using the measurement-dimension precedence rule — the name starts with \
a column-group measurement label, followed by row sub-labels (WITHOUT the \
outermost row-group label), followed by the column sub-path without the \
column-group prefix. \
Example: logical name "MeasureB ItemP SubQ Cond(unit)" means: column group = \
"MeasureB", row sub-labels = "ItemP SubQ", column sub-path = "Cond(unit)". \
To look up the value: \
(1) Identify the column-group label as the leading token(s) that appear as a \
top-level column group header in the OCR Markdown table. \
(2) The remaining tokens before the final parenthesized unit are the row \
sub-labels. \
(3) The final token(s) including any unit suffix in parentheses are the column \
sub-path. \
(4) Find the Markdown table row whose first-column label ENDS WITH the row \
sub-labels — the OCR row label contains a longer prefix from the outermost row \
group (e.g., the row is "MeasureA ItemP SubQ", which ends with "ItemP SubQ"). \
(5) Read the value from the column whose header equals \
column-group + " " + column-sub-path (e.g., "MeasureB Cond(unit)").
- Selection fields: The selected option is identified either by visual marking in \
the image (circled ○, filled ●, checked ✓, underlined, boxed — but WITHOUT a \
simultaneous strikethrough) or by the [SELECTED] marker in the text. An option \
that is visually circled or highlighted but also has a strikethrough drawn through \
it is NOT selected; it will carry [REJECTED] in the OCR text and must be ignored. \
Record only the selected option's text as the field value, without any marker \
(e.g., "Yes[SELECTED] / No" → "Yes").
- Checkbox fields: Checked items (visually ticked in the image, or prefixed \
[CHECKED] in the text) → "1". Unchecked items ([ ] prefix or no mark) → "0".
- Special OCR tags:
  - <STAMP: text>: if inner text is non-empty, use it as the field value; \
if the stamp is present but the text is illegible (inner text is empty, \
i.e., <STAMP: >), use "1" to record stamp presence rather than leaving the \
field empty.
  - <HANDWRITTEN: text>: use only the inner text value.
  - <SIGNATURE>: use "1".
  - <ILLEGIBLE> and <REDACTED>: use empty string ""."""

_PROMPT_SELECTION_SCHEMA_DESIGN: str = """\
- Selection / choice fields (options visually marked in the image with ○/✓/underline \
without a simultaneous strikethrough, or tagged [SELECTED] in OCR text): design \
the column as VARCHAR2 sized to accommodate the longest VALID option value. \
Options tagged [REJECTED] (circled but struck through) are cancelled and must NOT \
be counted when sizing the column.
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

_PROMPT_EXTRACT_TEXT_VALUE_RULES_DEFAULT: str = """\
1. 各カラムの日本語ラベル（-- 以降）に対応する項目をテキスト内で探し、値を転記する。ラベルは文書に記載された原文テキストをそのまま使用しており、意味解釈や言い換えを行っていない。階層的な行ラベルの場合は全ての祖先ラベルと末端ラベルを外側から内側の順にスペースで連結した形（例: "祖父 親 子"）で表現されているため、その連結表記のまま（どの階層も分割・再解釈せずに）対応する値を検索すること。ただし「計測次元優先形式」の論理名（列グループ名が先頭にあり、行サブラベル、列サブパスが続く形式）については、後掲の「Cell lookup」および「Measurement-dimension precedence」ルールを優先的に適用し、行ラベルのサフィックス一致で行を特定してから列ヘッダーで値を読み取ること
2. 数値（金額・数量・単価）: 桁区切りカンマ・通貨記号を除去した数字文字列（例: "¥1,234,567" → "1234567"）
3. 日付: ISO 8601形式 YYYY-MM-DD（例: "令和6年1月15日" → "2024-01-15"）
4. テキスト: OCRテキストの文字をそのまま転記。
5. テキストに該当項目が存在しない場合: "" （null は使わない）
6. スキーマに存在する全カラムを header_fields に出力する（値がなくても省略禁止）
7. テーブルセルの折り返し（セルが狭いため内容が複数の視覚的行に渡る場合）: 同一セル内の折り返し行を全てスペースで結合し、完全な文字列として1つの値に転記する（例: 1行目「室名札（ピクトサイン）」2行目「アクリルUV印刷」→ "室名札（ピクトサイン） アクリルUV印刷"）"""

_PROMPT_GENERATE_SQL_REQUIREMENTS_DEFAULT: str = """\
### 1. Document Type Detection
- First, identify the document type. Documents may be business documents (e.g., 領収書, 請求書, 納品書, 見積書, 注文書, 発注書) or non-business documents (e.g., 検査証明書, 検査記録, 試験成績書, 点検表, 定期自主検査表, 性能検査記録, 仕様書, 許可証, 届出書, 申請書, 報告書, etc.).
- Design the table name and structure accordingly.

### 2. Naming Conventions
- **Table name**: Romanized Katakana in UPPERCASE alphabet (e.g., RYOUSHUUSHO for 領収書, SEIKYUUSHO for 請求書, NOUHINNSHO for 納品書).
- **Physical column names**: Romanized Katakana in UPPERCASE alphabet with underscores (e.g., HAKKOOBI for 発行日, GOUKEI_KINGAKU for 合計金額, ATESAKI_MEI for 宛先名).
- **Logical column names**: Japanese (Kanji) via comment. CRITICAL — always derive the logical name from the **exact label text as it appears in the document**. For hierarchical tables where ancestor group-headers (two or more levels) apply to sub-rows, form the logical name by concatenating ALL ancestor labels and the leaf label with single spaces, in order from outermost to innermost, exactly as written in the document (e.g., grandparent label + " " + parent label + " " + leaf label). Never reinterpret, paraphrase, restructure, or infer new terminology that does not appear in the document.
- **Strict verbatim rule for logical names**: The logical name MUST be an exact copy of the document label — do NOT append, prepend, or insert any qualifier or descriptor of any kind (e.g., do NOT add 印, 欄, コード, フラグ, 番号, or any similar suffix/prefix). The physical column name and Oracle data type already communicate the field's role; the logical name exists solely so that the value-extraction step can locate the correct label in the OCR output by exact string matching. Any deviation from the verbatim label will cause extraction to fail.
- **Physical column names for hierarchical or parenthesized labels**: When deriving the romanized physical name from a concatenated hierarchical logical name, apply the following in order: (1) remove all parentheses and the text enclosed within them from the label before romanizing; (2) romanize the remaining words and join them with underscores; (3) if the resulting name would exceed 30 characters, abbreviate each component to its most meaningful prefix while keeping the name uniquely identifiable. The romanization itself must still follow Hepburn rules.
- Use consistent Hepburn romanization rules (e.g., しょ→SHO, きゅう→KYUU, おう→OU).

### 3. Schema Design Rules
- Choose appropriate Oracle data types: VARCHAR2, NUMBER, DATE, TIMESTAMP.
- Do NOT use CLOB. Even long text fields must use VARCHAR2 with an appropriate length up to 4000.
- Make columns NULLABLE unless they are clearly always present.
- Do not set VARCHAR2 length to the exact observed character count. Add generous safety buffer because actual production data can be longer.
- Prefer safer bucket sizes such as 50, 100, 200, 300, 500, 1000, 2000, or 4000.
- For short-looking codes / IDs / numbers, still keep enough room instead of matching the sample exactly.
- {header_only_hint}

### 4. Capture ALL information present in the document
CRITICAL — every labeled field, cell, and value visible in the OCR text MUST be mapped to a column. Do NOT omit any field because it looks technical, unusual, or hard to name.

**Column count**: For dense inspection forms, equipment test records, specification tables, or multi-table documents, the schema may legitimately contain 50, 100, or more columns. This is expected and correct — never consolidate, merge, or drop columns to simplify the schema. Completeness is mandatory.

Categories of information to capture (applicable categories depend on document type):
- **Document metadata**: document number, issue date, validity period, document type, reference numbers
- **Party information**: names, addresses, phone numbers, registration/license numbers, organization codes
- **Subject / target information**: item name, model number, serial number, capacity, rating, classification
- **Specifications and configurations**: all labeled specification fields, settings, modes, options. \
For specification tables where BOTH the row axis and the column axis carry meaningful labels \
(cross-indexed tables — e.g., rows list equipment components and columns list specification aspects \
such as type, capacity, model number, serial number), generate one column per unique \
(row-label × column-header) combination by concatenating the fully-qualified row label and the \
fully-qualified column header with a single space as the logical name. \
Even if the OCR output uses generic column names (e.g., "Value", "Specification", "Column1", \
"Column2"), infer the intended column meaning from the surrounding row and positional context, \
and create individually named columns for each distinct data cell.
- **Measurement and test data**: all numeric readings, measured values, ratings, tolerances — \
including every cell in measurement tables.
  - **Row-hierarchical tables** (rows grouped under two or more levels of section headers, \
single or simple column headers): generate one column per unique leaf-row-path × column-header \
combination, naming it by concatenating ALL ancestor row labels, the leaf row label, and the \
column header with single spaces, from outermost to innermost.
  - **Cross-indexed measurement tables** (BOTH rows AND columns carry hierarchical labels — \
e.g., rows: equipment category > sub-category > direction, columns: measurement type > unit variant): \
Identify in the OCR text by the following signature: the Markdown table's first column \
contains multi-segment concatenated row-path strings (ancestor labels joined by spaces) AND \
at least one data column header itself contains a space-joined multi-level name. \
For such tables: generate exactly one DB column per data cell — that is, one column per \
unique (fully-qualified row path, fully-qualified column path) pair. \
CRITICAL — no cell may be omitted, even if its value appears blank or repeated. \
Column count = (number of distinct fully-qualified row paths) × (number of leaf data \
columns). Follow the **measurement-dimension precedence rule** below for naming.
  - **Measurement-dimension precedence rule**: Applies when the outermost row-group label \
names a measurement dimension AND one or more column groups also name a DIFFERENT measurement \
dimension. Determine for each (row, column) pair which naming pattern to use: \
(A) If the column belongs to a column group whose label denotes a different measurement \
dimension from the outermost row-group label → use: \
  [column_group_label] + " " + [row_path_without_outermost_group] + " " + [column_leaf_label_without_group_prefix]. \
(B) If the column has no distinct column-group measurement label (it falls under the same \
dimension as the row group, or the column header has only one level with no parent group) → use: \
  [full_row_path] + " " + [column_label]. \
The outermost row-group label is the topmost merged cell in the row-label area. \
The column group is the parent-level header spanning multiple leaf columns (identified in \
Step A of the OCR rules). The column leaf label is the innermost column header text \
(without the group prefix that was concatenated in Step A). \
**How to decide Format A vs Format B**: Inspect the OCR Markdown table's column header \
row. If a column's fully-qualified name STARTS WITH a token that also appears as an \
outermost column-group header in the OCR table AND that token is different from the \
outermost row-group label, apply Format A for that column. Otherwise apply Format B. \
Apply this determination consistently across ALL columns before generating any logical \
names — do not mix formats for columns belonging to the same column group.
  - When the OCR output uses generic or positional column headers for a measurement table, \
derive the intended column meaning from document context (surrounding labels, units, measurement \
section title) and still create individually named columns — do NOT collapse multiple distinct \
measured values into one column.
- **Financial data** (if present): subtotal, tax, total amount, unit price, quantity, tax rate
- **Inspection and compliance data**: test results, pass/fail judgments, inspection dates, inspector information
- **Free-text sections**: remarks, special notes, conditions, payment terms — each distinct labeled free-text area gets its own column
- **Stamps and signatures**: each stamp or signature field gets its own column"""

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
    "extract_text_value_rules": _PROMPT_EXTRACT_TEXT_VALUE_RULES_DEFAULT,
    "generate_sql_requirements": _PROMPT_GENERATE_SQL_REQUIREMENTS_DEFAULT,
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
                    # Record start time on the FIRST failed attempt so subsequent
                    # logs show accurate elapsed time (not always 0.0s).
                    semaphore_wait_started_at = time.monotonic() - GENAI_PROGRESS_LOG_INTERVAL_SECONDS
                logger.info(
                    "%s: GenAI 実行枠の空きを待機中です (elapsed=%.1fs)",
                    operation_name,
                    time.monotonic() - semaphore_wait_started_at,
                )
        else:
            semaphore_wait_started_at = time.monotonic()
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
        # _reserve_slot acquires the semaphore and releases it itself on exception,
        # so only release in finally when _reserve_slot succeeded.
        acquired = False
        try:
            self._reserve_slot(operation_name)
            acquired = True
            return func(*args, **kwargs)
        finally:
            if acquired:
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
        self._llm_model_id = os.environ.get("LLM_MODEL_ID", "xai.grok-4-1-fast-reasoning")
        self._vlm_model_id = os.environ.get("VLM_MODEL_ID", "google.gemini-2.5-pro")
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
                break  # 非リトライエラーは残りの試行を行わず即終了
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
                    raise
        raise last_error if last_error else json.JSONDecodeError("empty response", last_text, 0)

    def _get_text_from_chat_response(self, chat_response: Any) -> str:
        """ChatResponse からテキストを連結抽出"""
        if not hasattr(chat_response, "choices") or not chat_response.choices:
            logger.warning(
                "_get_text_from_chat_response: choices なし。chat_response_type=%s has_choices=%s choices_len=%s",
                type(chat_response).__name__,
                hasattr(chat_response, "choices"),
                len(chat_response.choices) if hasattr(chat_response, "choices") and chat_response.choices is not None else "N/A",
            )
            return ""

        message = chat_response.choices[0].message
        content = getattr(message, "content", None)
        logger.debug(
            "_get_text_from_chat_response: message_type=%s content_type=%s content_is_empty=%s",
            type(message).__name__,
            type(content).__name__,
            not content,
        )
        if isinstance(content, str) and content:
            return content
        if content:
            if isinstance(content, list):
                return "".join(self._get_text_from_chat_content_part(part) for part in content)
            return self._get_text_from_chat_content_part(content)

        direct_text = getattr(message, "text", None)
        if isinstance(direct_text, str) and direct_text:
            return direct_text
        logger.warning(
            "_get_text_from_chat_response: テキスト抽出失敗。message_type=%s content=%r direct_text=%r",
            type(message).__name__,
            repr(content)[:300] if content is not None else None,
            repr(direct_text)[:300] if direct_text is not None else None,
        )
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
                # Append before writing so that cleanup catches this path even if save() raises.
                temp_paths.append(temp_path)
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
                        "VLM OCR ページ送信を開始します: variant=%s page=%d/%d rotation=%d bytes=%d content_type=%s max_tokens=%d",
                        variant_label,
                        page_no,
                        len(image_filepaths),
                        rotation_degrees,
                        len(image_data),
                        content_type,
                        self._max_tokens,
                        extra=self._build_log_extra(
                            page_log_context,
                            ocr_rotation_degrees=rotation_degrees,
                            ocr_rotation_attempt=rotation_index,
                            ocr_rotation_total_attempts=rotation_total_attempts,
                            ocr_rotation_priority="primary" if rotation_index == 1 else "secondary",
                            page_bytes=len(image_data),
                            page_content_type=content_type,
                            ocr_max_tokens=self._max_tokens,
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
                        max_tokens=self._max_tokens,
                        temperature=0.0,
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
                        _response_data = getattr(response, "data", None)
                        chat_response = getattr(_response_data, "chat_response", None)
                        logger.debug(
                            "%s: VLM APIレスポンス構造: response_type=%s data_type=%s "
                            "chat_response_type=%s status=%s",
                            operation_name,
                            type(response).__name__,
                            type(_response_data).__name__,
                            type(chat_response).__name__,
                            getattr(response, "status", "N/A"),
                            extra=self._build_log_extra(
                                page_log_context,
                                ocr_rotation_degrees=rotation_degrees,
                                vlm_response_type=type(response).__name__,
                                vlm_data_type=type(_response_data).__name__,
                                vlm_chat_response_type=type(chat_response).__name__,
                            ),
                        )
                        if chat_response is None:
                            logger.warning(
                                "%s: chat_response が None です。response.data=%r",
                                operation_name,
                                _response_data,
                                extra=self._build_log_extra(
                                    page_log_context,
                                    ocr_rotation_degrees=rotation_degrees,
                                    vlm_data_repr=repr(_response_data)[:500],
                                ),
                            )
                        extracted_text = self._get_text_from_chat_response(chat_response).strip()
                        logger.debug(
                            "%s: VLM テキスト抽出結果: length=%d preview=%r",
                            operation_name,
                            len(extracted_text),
                            extracted_text[:200] if extracted_text else "",
                            extra=self._build_log_extra(
                                page_log_context,
                                ocr_rotation_degrees=rotation_degrees,
                                vlm_extracted_length=len(extracted_text),
                            ),
                        )
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
                # Note: no redundant `if extracted_text: break` here —
                # the break above is inside try and already exits the rotation
                # loop (Python executes finally then applies the break).

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
                _data = getattr(response, "data", None)
                return self._get_text_from_chat_response(getattr(_data, "chat_response", None))

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

        prompt = f"""You are a database schema designer. Analyze the following OCR-extracted text from a Japanese document (文書) — which may be a business document, inspection record, test report, specification sheet, or any other form — and design Oracle CREATE TABLE structures to store all the structured information found in it.

## OCR Content:
{ocr_text}

## Requirements:

{_get_prompt("generate_sql_requirements").replace("{header_only_hint}", header_only_hint)}
{_get_prompt("selection_schema_design")}

### 5. Output Format
Output ONLY a valid JSON object with this exact structure. The header_columns array MUST contain one entry for EVERY labeled field, cell, and data value present in the OCR content — for dense inspection or measurement documents this may be 50 to 100 or more entries. Do not truncate or omit columns. No explanation or markdown code fences.
{{
  "document_type_ja": "<日本語文書種別>",
  "document_type_en": "<document_type_in_english>",
  "header_table_name": "<TABLE_NAME>",
  "line_table_name": "<LINE_TABLE_NAME_OR_EMPTY>",
  "header_columns": [
    {{
      "column_name": "<UPPERCASE_COLUMN_NAME>",
      "comment": "<日本語ラベル（文書の原文そのまま）>",
      "data_type": "<VARCHAR2|NUMBER|DATE|TIMESTAMP>",
      "data_length": <integer_or_null>,
      "is_nullable": <true|false>
    }},
    {{
      "column_name": "<NEXT_COLUMN_NAME>",
      "comment": "<次のラベル>",
      "data_type": "VARCHAR2",
      "data_length": 200,
      "is_nullable": true
    }}
  ],
  "line_columns": [
    {{
      "column_name": "<LINE_COLUMN_NAME>",
      "comment": "<明細ラベル>",
      "data_type": "VARCHAR2",
      "data_length": 200,
      "is_nullable": true
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
                _data = getattr(response, "data", None)
                return self._get_text_from_chat_response(getattr(_data, "chat_response", None))

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
                col_parts = []
                for c in columns:
                    col_name = c.get("column_name", "")
                    data_type = c.get("data_type", "")
                    comment = c.get("comment", "")
                    constraints = c.get("constraints", [])
                    annotations = c.get("annotations", [])
                    part = f"{col_name} ({data_type})"
                    if constraints:
                        part += f" [{', '.join(constraints)}]"
                    if comment:
                        part += f" -- {comment}"
                    if annotations:
                        annot_str = ", ".join(
                            f"{a['name']}={a['value']}" if a.get("value") else a["name"]
                            for a in annotations
                            if a.get("name")
                        )
                        if annot_str:
                            part += f" <annotation: {annot_str}>"
                    col_parts.append(part)
                schema_text += f"- {table_name}: {', '.join(col_parts)}\n"

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

            def generate_text() -> str:
                response = self._retry_api_call("text_to_sql", client.chat, chat_detail)
                _data = getattr(response, "data", None)
                return self._get_text_from_chat_response(getattr(_data, "chat_response", None))

            try:
                parsed = self._parse_json_with_regeneration(
                    "text_to_sql",
                    generate_text,
                    GENAI_JSON_PARSE_RETRIES,
                )
            except json.JSONDecodeError as e:
                logger.error("AI応答のJSONパースエラー: %s", e)
                return {"success": False, "message": f"AI応答の解析に失敗しました: {str(e)}"}
            if not isinstance(parsed, dict):
                return {"success": False, "message": "AI応答形式が不正です"}
            parsed["success"] = True
            return parsed

        except Exception as e:
            self._raise_if_rate_limited(e)
            logger.error("Text-to-SQL変換エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"SQL生成に失敗しました: {str(e)}"}
