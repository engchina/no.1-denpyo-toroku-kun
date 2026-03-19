# 伝票登録くん

OCI GenAI (VLM / LLM / Embedding) + GradientBoostingClassifier による伝票登録サービス。
Flask / Gunicorn バックエンドと Oracle JET (Redwood) フロントエンドで構成。
Oracle Autonomous Database (Select AI) を活用した自然言語検索機能を提供。

## Deploy

- v0.0.2: 大阪リージョンのみをサポートしています。（デフォルト：大阪リージョン）

  Click [![Deploy to Oracle Cloud](https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg)](https://cloud.oracle.com/resourcemanager/stacks/create?region=ap-osaka-1&zipUrl=https://github.com/engchina/no.1-denpyo-toroku-kun/releases/download/v0.0.2/v0.0.2.zip)


---

## 目次

- [アーキテクチャ概要](#アーキテクチャ概要)
- [前提条件](#前提条件)
- [プロジェクト構成](#プロジェクト構成)
- [OCI 設定](#oci-設定)
- [ローカル環境構築 (Docker)](#ローカル環境構築-docker)
- [ローカル環境構築 (ネイティブ)](#ローカル環境構築-ネイティブ)
- [モデル学習](#モデル学習)
- [サービス起動](#サービス起動)
- [動作確認](#動作確認)
- [API エンドポイント一覧](#api-エンドポイント一覧)
- [環境変数一覧](#環境変数一覧)
- [トラブルシューティング](#トラブルシューティング)

---

## アーキテクチャ概要

```
┌──────────────────────────────────────────────────┐
│  Browser (Oracle JET 16.1.6 / Redwood CDN)       │
│  - ダッシュボード                                  │
└───────────────────────┬──────────────────────────┘
                        │ HTTP
┌───────────────────────▼──────────────────────────┐
│  Gunicorn (gevent worker)                        │
│  ├─ Flask Application                            │
│  │  ├─ api_blueprint    (/api/v1/*)              │
│  │  ├─ static_blueprint (/, /css/*, /js/*)       │
│  │  ├─ CORS middleware                           │
│  │  ├─ Security headers (CSP, HSTS, etc.)        │
│  │  └─ Global error handler                      │
│  └─ ProductionIntentClassifier                   │
│     ├─ VLM: google.gemini-2.5-flash (OCR/解析)  │
│     ├─ LLM: xai.grok-code-fast-1 (構造化)       │
│     ├─ OCI GenAI Embedding (cohere.embed-v4.0)   │
│     ├─ GradientBoostingClassifier (sklearn)      │
│     ├─ EmbeddingCache (LRU, thread-safe)         │
│     └─ PerformanceMonitor (P95/P99)              │
└──────────────────────────────────────────────────┘
         │                    │
┌────────▼───────┐   ┌────────▼────────────────────┐
│  OCI Object    │   │  Oracle Autonomous Database  │
│  Storage       │   │  - 伝票データ永続化           │
│  - 伝票画像    │   │  - Select AI 自然言語検索     │
└────────────────┘   └─────────────────────────────┘
```

---

## 前提条件

| 項目 | 要件 |
|------|------|
| **Python** | 3.9 以上 (3.12 推奨) |
| **Docker** | 20.10 以上 (Docker 起動の場合) |
| **Docker Compose** | v2 以上 (Docker 起動の場合) |
| **OCI CLI / SDK** | OCI config ファイル (`~/.oci/config`) が設定済みであること |
| **OCI GenAI** | Generative AI Inference サービスへのアクセス権 |
| **Oracle ADB** | Autonomous Database (Select AI 利用時) |
| **OS** | Linux (Ubuntu 20.04+ / Oracle Linux 8+) |

---

## プロジェクト構成

```
no.1-denpyo-toroku-kun/
├── Dockerfile                    # Oracle Linux 8 ベース Docker イメージ
├── docker-compose.yml            # Docker Compose 定義
├── deploy.sh                     # Docker デプロイスクリプト
├── requirements.txt              # Python 依存パッケージ
├── pyproject.toml                # ビルド・Lint 設定 (ruff, black, mypy, bandit)
├── prometheus.yml                # Prometheus 設定
├── .env.example                  # 環境変数テンプレート
├── gunicorn_config/
│   └── gunicorn_config.py        # Gunicorn 設定 (gevent, timeout 等)
├── scripts/
│   ├── lib/common.sh             # 共通ユーティリティ (ログ, パス, 環境確認)
│   ├── manage.sh                 # ネイティブ Gunicorn 管理スクリプト
│   ├── start-backend.sh          # バックエンド起動 (foreground)
│   ├── start-frontend.sh         # フロントエンド起動 (foreground)
│   ├── train.py                  # モデル学習スクリプト
│   ├── test_production.py        # 統合テストスクリプト
│   ├── client_example.py         # API クライアント例
│   ├── quality_gate.sh           # コード品質チェック
│   └── security_checks.sh        # セキュリティ検証
├── terraform/
│   └── stack/                    # OCI Resource Manager 用 Terraform
│       ├── variables.tf          # 変数定義 (リージョン, ADB, Compute)
│       ├── compute.tf            # Compute インスタンス
│       ├── adb.tf                # Autonomous Database
│       ├── bucket.tf             # OCI Object Storage
│       └── schema.yaml           # Resource Manager スキーマ
├── tests/                        # ユニット・統合テスト
│   ├── conftest.py               # Pytest フィクスチャ
│   └── unit/                     # 各種ユニットテスト
└── denpyo_toroku/               # メインアプリケーション
    ├── wsgi.py                   # WSGI エントリポイント (gevent monkey-patch)
    ├── denpyo_toroku.py         # Flask アプリ初期化
    ├── config.py                 # 設定クラス (環境変数 + config.ini)
    ├── config.ini                # 静的設定値
    ├── auth_config.py            # セキュリティヘッダー定義
    ├── index.html                # Oracle JET SPA エントリ
    ├── css/                      # スタイルシート・画像
    ├── js/
    │   ├── main.js               # RequireJS ブートストラップ
    │   ├── root.js               # Knockout バインディング初期化
    │   ├── appController.js      # メインコントローラー
    │   ├── views/                # HTML テンプレート
    │   └── viewModels/           # Knockout ViewModel
    ├── app/
    │   ├── blueprints/           # Flask Blueprint (api, static)
    │   │   └── api/api_blueprint.py  # メイン API エンドポイント (~6,000 行)
    │   ├── services/
    │   │   ├── ai_service.py         # OCI GenAI 統合 (OCR, 解析, リトライ)
    │   │   ├── database_service.py   # Oracle DB 操作
    │   │   ├── document_processor.py # 画像・ファイル処理
    │   │   └── oci_storage_service.py # OCI Object Storage 統合
    │   ├── middlewares/           # CORS, Security headers
    │   ├── error_handlers/       # グローバルエラーハンドラ
    │   └── util/                 # Logger, Response, ImportUtil 等
    ├── models/                   # 学習済みモデル (.pkl)
    └── log/                      # ログファイル出力先
```

---

## OCI 設定

サービスは OCI GenAI の VLM/LLM/Embedding API を使用するため、OCI 認証設定が必要です。

### 1. OCI CLI の設定

```bash
# OCI CLI がない場合はインストール
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"

# 初期設定
oci setup config
```

### 2. config ファイルの確認

`~/.oci/config` が以下の形式で存在することを確認:

```ini
[DEFAULT]
user=ocid1.user.oc1..xxxxx
fingerprint=xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx
tenancy=ocid1.tenancy.oc1..xxxxx
region=ap-osaka-1
key_file=~/.oci/oci_api_key.pem
```

### 3. Compartment ID の取得

```bash
oci iam compartment list --compartment-id-in-subtree true --query "data[].{name:name, id:id}" --output table
```

取得した `compartment_id` を環境変数 `OCI_CONFIG_COMPARTMENT` に設定します。

---

## ローカル環境構築 (Docker)

最も簡単な起動方法です。

### 1. リポジトリのクローンとディレクトリ移動

```bash
git clone <repository-url>
cd no.1-denpyo-toroku-kun
```

### 2. 環境変数ファイルの作成

```bash
cp .env.example .env
# .env を編集して OCI_CONFIG_COMPARTMENT 等を設定
```

### 3. 必要ディレクトリの作成

```bash
mkdir -p denpyo_toroku/log denpyo_toroku/models
```

### 4. ビルドと起動

```bash
# イメージビルド＆起動
docker-compose up -d --build

# ログ確認
docker-compose logs -f
```

または `deploy.sh` を使用:

```bash
chmod +x deploy.sh
./deploy.sh start
```

### 5. 動作確認

```bash
# ヘルスチェック
curl http://localhost:8080/api/v1/health

# UI にアクセス
# ブラウザで http://localhost:8080 を開く
```

### 6. 停止

```bash
docker-compose down
# または
./deploy.sh stop
```

---

## ローカル環境構築 (ネイティブ)

Docker を使わずに直接起動する方法です。

### 1. Python 仮想環境の作成 (uv)

[uv](https://github.com/astral-sh/uv) を使用して Python 3.12 の仮想環境を作成します。

```bash
cd no.1-denpyo-toroku-kun

# uv がインストールされていない場合
curl -LsSf https://astral.sh/uv/install.sh | sh

# Python 3.12 の仮想環境を作成
uv venv --python 3.12 .venv

# 仮想環境を有効化
source .venv/bin/activate
```

### 2. 依存パッケージのインストール

```bash
uv pip install -r requirements.txt
```

### 3. 必要ディレクトリの作成

```bash
mkdir -p denpyo_toroku/log denpyo_toroku/models
```

### 4. 環境変数の設定

`.env.example` をコピーして `.env` を編集するか、直接環境変数を設定:

```bash
export OCI_CONFIG_PATH=~/.oci/config
export OCI_CONFIG_PROFILE=DEFAULT
export OCI_CONFIG_COMPARTMENT=ocid1.compartment.oc1..xxxxx  # 自身の Compartment ID
export OCI_REGION=ap-osaka-1
export OCI_SERVICE_ENDPOINT=https://inference.generativeai.us-chicago-1.oci.oraclecloud.com
export VLM_MODEL_ID=google.gemini-2.5-flash
export LLM_MODEL_ID=xai.grok-code-fast-1
export EMBEDDING_MODEL_ID=cohere.embed-v4.0
export LOG_LEVEL=INFO
export ENABLE_CACHE=true
```

データベース機能を使用する場合は追加で設定:

```bash
export ORACLE_CLIENT_LIB_DIR=/path/to/instantclient
export ORACLE_26AI_CONNECTION_STRING=admin/password@dsn
export ADB_OCID=ocid1.autonomousdatabase.oc1..xxxxx
```

### 5. Gunicorn で起動

起動スクリプトは自動的に `.venv` 仮想環境を有効化します。

```bash
cd scripts

# フォアグラウンド起動 (ログがターミナルに表示)
chmod +x start-backend.sh
./start-backend.sh

# または daemon モード (バックグラウンド起動)
chmod +x manage.sh
./manage.sh start

# ステータス確認
./manage.sh status

# 停止
./manage.sh stop
```

または直接 Gunicorn を起動 (仮想環境を手動で有効化):

```bash
source ../.venv/bin/activate
cd denpyo_toroku
gunicorn -c ../gunicorn_config/gunicorn_config.py wsgi:app
```

### 6. 開発モード (Flask 直接起動)

素早いデバッグ用:

```bash
cd no.1-denpyo-toroku-kun
export DENPYO_TOROKU_DEBUG_MODE=true
export WEBAPP_PORT=5000
python -m denpyo_toroku.denpyo_toroku
```

> **注意**: Flask 直接起動はポート **5000**、Gunicorn 起動はポート **8080** (デフォルト)。

---

## モデル学習

サービスが予測を行うには、学習済みモデル (`.pkl`) が必要です。

### 1. 学習データの準備

リポジトリのルートに `training_data.json` を作成:

```json
[
    {"text": "注文の配送状況を確認したい", "label": "shipping_inquiry"},
    {"text": "商品を返品したい", "label": "return_request"},
    {"text": "クーポンコードを使いたい", "label": "coupon_usage"},
    {"text": "パスワードをリセットしたい", "label": "account_management"}
]
```

> 各クラス最低 50 サンプル以上を推奨。

### 2. 学習スクリプトの設定

`scripts/train.py` 内の CONFIG を環境に合わせて編集:

```python
CONFIG = {
    'compartment_id': 'ocid1.compartment.oc1..xxxxx',  # ← 実際の ID に置換
    # ... 他の設定はデフォルトで OK
}
```

### 3. 学習の実行

```bash
python scripts/train.py
```

学習が完了すると、モデルファイルが以下に出力されます:

```
denpyo_toroku/models/intent_model_production.pkl
```

### 4. サービスの再起動

学習後、モデルをロードするためにサービスを再起動:

```bash
# Docker の場合
docker-compose restart

# ネイティブの場合
./scripts/manage.sh restart
```

---

## サービス起動

### 起動方法の比較

| 方法 | コマンド | ポート | 用途 |
|------|---------|--------|------|
| **Docker Compose** | `./deploy.sh start` | 8080 | 本番 / 標準的なローカル検証 |
| **manage.sh** | `./scripts/manage.sh start` | 8080 | ネイティブ (daemon モード) |
| **Gunicorn 直接** | `cd denpyo_toroku && gunicorn -c ...` | 8080 | ネイティブ (フォアグラウンド) |
| **Flask 直接** | `python -m denpyo_toroku.denpyo_toroku` | 5000 | 開発 / デバッグ用 |

### アクセス先

- **Web UI**: http://localhost:8080 (Gunicorn) / http://localhost:5000 (Flask)
- **API**: http://localhost:8080/api/v1/

---

## 動作確認

### ヘルスチェック

```bash
curl -s http://localhost:8080/api/v1/health | python3 -m json.tool
```

```json
{
    "data": {
        "status": "healthy",
        "model_loaded": true,
        "version": "1.0.0",
        "uptime_seconds": 120.5
    }
}
```

### ファイルアップロード

```bash
curl -s -X POST "http://localhost:8080/api/v1/files/upload" \
  -F "file=@/path/to/invoice.pdf" \
  | python3 -m json.tool
```

### 自然言語検索 (Select AI)

```bash
curl -s -X POST "http://localhost:8080/api/v1/search/nl" \
  -H "Content-Type: application/json" \
  -d '{"query": "先月の売上伝票を見せて", "category_id": 1}' \
  | python3 -m json.tool
```

### 単一テキスト予測

```bash
curl -s -X POST "http://localhost:8080/api/v1/predict/single" \
  -H "Content-Type: application/json" \
  -d '{"text": "注文の配送状況を確認したい", "return_proba": true}' \
  | python3 -m json.tool
```

### テストスクリプトの実行

```bash
python scripts/test_production.py
```

### クライアント例の実行

```bash
python scripts/client_example.py
```

---

## API エンドポイント一覧

### 認証

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/auth/me` | 現在のユーザー情報取得 |
| `POST` | `/api/v1/auth/login` | ログイン |
| `POST` | `/api/v1/auth/logout` | ログアウト |

### システム

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/health` | ヘルスチェック |
| `GET` | `/api/v1/version` | サービスバージョン情報 |
| `GET` | `/api/v1/dashboard/stats` | ダッシュボード統計 |
| `GET` | `/api/v1/metrics` | Prometheus メトリクス |

### OCI 設定

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/oci/settings` | OCI 設定取得 |
| `POST` | `/api/v1/oci/settings` | OCI 設定更新 |
| `GET` | `/api/v1/oci/object-storage/settings` | Object Storage 設定取得 |
| `POST` | `/api/v1/oci/test` | OCI 接続テスト |
| `POST` | `/api/v1/oci/model/test` | AI モデル接続テスト |

### データベース設定

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/database/settings` | DB 設定取得 |
| `POST` | `/api/v1/database/settings` | DB 設定更新 |
| `POST` | `/api/v1/database/settings/test` | DB 接続テスト |
| `POST` | `/api/v1/database/settings/wallet` | Wallet ファイルアップロード |
| `POST` | `/api/v1/database/init` | DB 初期化 |
| `GET` | `/api/v1/database/adb/info` | ADB 情報取得 |
| `POST` | `/api/v1/database/adb/start` | ADB 起動 |
| `POST` | `/api/v1/database/adb/stop` | ADB 停止 |

### ファイル管理

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/files/upload` | ファイルアップロード |
| `GET` | `/api/v1/files` | ファイル一覧取得 |
| `GET` | `/api/v1/files/<file_id>` | ファイル情報取得 |
| `DELETE` | `/api/v1/files/<file_id>` | ファイル削除 |
| `POST` | `/api/v1/files/bulk-delete` | 複数ファイル一括削除 |
| `GET` | `/api/v1/files/<file_id>/preview` | ファイルプレビュー |
| `GET` | `/api/v1/files/<file_id>/preview-pages` | プレビューページ一覧 |
| `GET` | `/api/v1/files/<file_id>/preview-pages/<page_index>` | 指定ページプレビュー |
| `GET` | `/api/v1/files/<file_id>/analysis-result` | 解析結果取得 |
| `POST` | `/api/v1/files/<file_id>/analyze` | ファイル解析 (AI OCR) |
| `POST` | `/api/v1/files/<file_id>/register` | 伝票登録 |

### カテゴリ管理

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/categories` | カテゴリ一覧取得 |
| `POST` | `/api/v1/categories` | カテゴリ作成 |
| `GET` | `/api/v1/categories/<category_id>` | カテゴリ情報取得 |
| `PUT` | `/api/v1/categories/<category_id>` | カテゴリ更新 |
| `DELETE` | `/api/v1/categories/<category_id>` | カテゴリ削除 |
| `PATCH` | `/api/v1/categories/<category_id>/toggle` | カテゴリ有効/無効切替 |
| `POST` | `/api/v1/categories/<category_id>/select-ai-profile` | Select AI プロファイル設定 |
| `POST` | `/api/v1/categories/analyze-slips` | 伝票一括解析 |

### 検索

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/search/tables` | 検索対象テーブル一覧 |
| `GET` | `/api/v1/search/categories/<category_id>/schema` | カテゴリスキーマ取得 |
| `POST` | `/api/v1/search/nl` | 自然言語検索 (Select AI, 同期) |
| `POST` | `/api/v1/search/nl/async` | 自然言語検索 (非同期) |
| `GET` | `/api/v1/search/nl/jobs/<job_id>` | 非同期検索ジョブ結果取得 |
| `GET` | `/api/v1/search/tables/<category_id>/data` | テーブルデータ取得 |
| `GET` | `/api/v1/search/table-browser/tables` | テーブルブラウザ一覧 |
| `GET` | `/api/v1/search/table-browser/data` | テーブルブラウザデータ取得 |
| `POST` | `/api/v1/search/table-browser/delete-row` | テーブルブラウザ行削除 |
| `POST` | `/api/v1/search/table-browser/delete-table` | テーブル削除 |

### プロンプト管理

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/prompts` | プロンプト一覧取得 |
| `POST` | `/api/v1/prompts` | プロンプト更新 |
| `POST` | `/api/v1/prompts/reset` | プロンプトリセット |

### 予測 (ML)

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/predict` | バッチ予測 (最大100件) |
| `POST` | `/api/v1/predict/single` | 単一テキスト予測 |

---

## 環境変数一覧

### OCI 設定 (必須)

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `OCI_CONFIG_PATH` | `~/.oci/config` | OCI 設定ファイルのパス |
| `OCI_CONFIG_PROFILE` | `DEFAULT` | OCI プロファイル名 |
| `OCI_CONFIG_COMPARTMENT` | (空) | OCI Compartment OCID |
| `OCI_REGION` | `ap-osaka-1` | OCI リージョン |
| `OCI_SERVICE_ENDPOINT` | `https://inference.generativeai.us-chicago-1.oci.oraclecloud.com` | GenAI サービスエンドポイント |

### OCI Object Storage

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `OCI_NAMESPACE` | (空) | Object Storage ネームスペース |
| `OCI_BUCKET` | (空) | バケット名 |
| `OCI_SLIPS_RAW_PREFIX` | `denpyo-raw` | 未処理伝票プレフィックス |
| `OCI_SLIPS_CATEGORY_PREFIX` | `denpyo-category` | カテゴリ別伝票プレフィックス |

### AI モデル設定

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `VLM_MODEL_ID` | `google.gemini-2.5-flash` | 画像解析モデル (VLM) |
| `LLM_MODEL_ID` | `xai.grok-code-fast-1` | テキスト処理モデル (LLM) |
| `EMBEDDING_MODEL_ID` | `cohere.embed-v4.0` | Embedding モデル ID |
| `LLM_MAX_TOKENS` | `65536` | LLM 最大トークン数 |
| `LLM_TEMPERATURE` | `0.0` | LLM 温度パラメータ |
| `GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES` | `1` | OCR 空レスポンス時の主リトライ回数 |
| `GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES` | `0` | OCR 空レスポンス時の副リトライ回数 |
| `GENAI_OCR_ROTATION_ANGLES` | `0,90,180,270` | OCR 回転角度候補 |
| `GENAI_OCR_IMAGE_MAX_EDGE_STEPS` | `2400,1800,1400,1100` | OCR 画像リサイズ段階 |

### Select AI 設定

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `SELECT_AI_ENABLED` | `true` | Select AI 機能の有効/無効 |
| `SELECT_AI_REGION` | `us-chicago-1` | Select AI 使用リージョン |
| `SELECT_AI_MODEL_ID` | `xai.grok-code-fast-1` | Select AI 使用モデル |
| `SELECT_AI_EMBEDDING_MODEL_ID` | (`EMBEDDING_MODEL_ID` と同じ) | Select AI Embedding モデル |
| `SELECT_AI_MAX_TOKENS` | `32768` | Select AI 最大トークン数 |
| `SELECT_AI_ENDPOINT_ID` | (空) | Select AI エンドポイント ID |
| `SELECT_AI_OCI_API_FORMAT` | `GENERIC` | OCI API フォーマット |
| `SELECT_AI_ENFORCE_OBJECT_LIST` | `true` | オブジェクトリスト制限の強制 |
| `SELECT_AI_USE_ANNOTATIONS` | `true` | アノテーション使用有無 |
| `SELECT_AI_USE_COMMENTS` | `true` | コメント使用有無 |
| `SELECT_AI_USE_CONSTRAINTS` | `true` | 制約情報使用有無 |

### データベース設定

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `ORACLE_CLIENT_LIB_DIR` | (空) | Oracle Instant Client ディレクトリ |
| `ORACLE_26AI_CONNECTION_STRING` | (空) | Oracle DB 接続文字列 |
| `ADB_OCID` | (空) | Autonomous Database OCID |

### キャッシュ・パフォーマンス

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `ENABLE_CACHE` | `true` | Embedding キャッシュの有効/無効 |
| `CACHE_SIZE` | `10000` | キャッシュ最大エントリ数 |
| `BATCH_SIZE` | `96` | Embedding API バッチサイズ |

### サービス設定

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `LOG_LEVEL` | `INFO` | ログレベル (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |
| `WEBAPP_PORT` | `5000` | Flask 直接起動時のポート |
| `GUNICORN_BIND` | `0.0.0.0:8080` | Gunicorn バインドアドレス |
| `GUNICORN_DAEMON` | `false` | Gunicorn daemon モード (`scripts/manage.sh` 使用時は自動で `true`) |
| `DENPYO_TOROKU_DEBUG_MODE` | (空) | `true` でデバッグモード有効 |
| `UPLOAD_MAX_SIZE_MB` | `50` | アップロード最大ファイルサイズ (MB) |
| `HOSTNAME` | (空) | セキュリティヘッダー用ホスト名 |
| `LOAD_BALANCER_ALIAS` | (空) | ロードバランサーエイリアス |

---

## トラブルシューティング

### モデルが読み込まれない

```
"status": "degraded", "message": "Model not loaded"
```

- モデルファイルが `denpyo_toroku/models/intent_model_production.pkl` に存在するか確認
- 学習スクリプトを実行してモデルを生成: `python scripts/train.py`
- Docker の場合、`volumes` でモデルディレクトリがマウントされているか確認

### OCI 認証エラー

```
Failed to initialize classifier: ...
```

- `~/.oci/config` が正しく設定されているか確認
- API キーのフィンガープリントが一致しているか確認
- `OCI_CONFIG_COMPARTMENT` が設定されているか確認
- GenAI サービスが対象リージョンで利用可能か確認

### データベース接続エラー

- `ORACLE_CLIENT_LIB_DIR` に Oracle Instant Client が正しく配置されているか確認
- `ORACLE_26AI_CONNECTION_STRING` の DSN が正しいか確認
- ADB の Wallet ファイルが `ORACLE_CLIENT_LIB_DIR/network/admin` に配置されているか確認
- `ADB_OCID` が正しく設定されているか確認

### Docker コンテナが起動しない

```bash
# ログ確認
docker-compose logs denpyo-toroku

# コンテナ内に入って確認
docker exec -it denpyo-toroku bash
```

- `GUNICORN_DAEMON` が Docker 環境では `false` (デフォルト) であることを確認
- ポート 8080 が別プロセスで使用されていないか確認: `lsof -i :8080`

### OCR 解析が失敗する

- `VLM_MODEL_ID` が正しいモデル ID (`google.gemini-2.5-flash`) であるか確認
- OCI GenAI サービスへのアクセス権があるか確認
- ファイルサイズが `UPLOAD_MAX_SIZE_MB` (デフォルト: 50MB) 以内であるか確認
- 対応拡張子 (`pdf`, `jpeg`, `jpg`, `png`, `tif`, `tiff`) を使用しているか確認

### キャッシュ関連の問題

```bash
# キャッシュ無効化
export ENABLE_CACHE=false
```

### ログの確認

```bash
# アプリケーションログ
tail -f denpyo_toroku/log/denpyo_toroku.log

# Gunicorn アクセスログ
tail -f denpyo_toroku/log/gunicorn_access.log

# Gunicorn エラーログ
tail -f denpyo_toroku/log/gunicorn.log
```
