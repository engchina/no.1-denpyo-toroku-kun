# Intent Classifier Service

OCI GenAI Embedding + GradientBoostingClassifier による意図分類サービス。  
Flask / Gunicorn バックエンドと Oracle JET (Redwood) フロントエンドで構成。

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
│  - Dashboard / Predict / Statistics / Model Info  │
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
│     ├─ OCI GenAI Embedding (cohere.embed-v3.0)   │
│     ├─ GradientBoostingClassifier (sklearn)      │
│     ├─ EmbeddingCache (LRU, thread-safe)         │
│     └─ PerformanceMonitor (P95/P99)              │
└──────────────────────────────────────────────────┘
```

---

## 前提条件

| 項目 | 要件 |
|------|------|
| **Python** | 3.9 以上 |
| **Docker** | 20.10 以上 (Docker 起動の場合) |
| **Docker Compose** | v2 以上 (Docker 起動の場合) |
| **OCI CLI / SDK** | OCI config ファイル (`~/.oci/config`) が設定済みであること |
| **OCI GenAI** | Generative AI Inference サービスへのアクセス権 |
| **OS** | Linux (Ubuntu 20.04+ / Oracle Linux 8+) |

---

## プロジェクト構成

```
no.1-intent-classifier/
├── Dockerfile                    # Oracle Linux 8 ベース Docker イメージ
├── docker-compose.yml            # Docker Compose 定義
├── deploy.sh                     # Docker デプロイスクリプト
├── requirements.txt              # Python 依存パッケージ
├── gunicorn_config/
│   └── gunicorn_config.py        # Gunicorn 設定 (gevent, timeout 等)
├── scripts/
│   ├── lib/common.sh             # 共通ユーティリティ (ログ, パス, 環境確認)
│   ├── manage.sh                 # ネイティブ Gunicorn 管理スクリプト
│   ├── restart.sh                # Gunicorn 再起動ショートカット
│   ├── start-backend.sh          # バックエンド起動 (foreground)
│   ├── start-frontend.sh         # フロントエンド起動 (foreground)
│   ├── train.py                  # モデル学習スクリプト
│   ├── test_production.py        # テストスクリプト
│   └── client_example.py         # API クライアント例
└── denpyo_toroku/               # メインアプリケーション
    ├── wsgi.py                   # WSGI エントリポイント
    ├── denpyo_toroku.py         # Flask アプリ初期化
    ├── config.py                 # 設定クラス (環境変数 + config.ini)
    ├── config.ini                # 静的設定値
    ├── auth_config.py            # セキュリティヘッダー定義
    ├── index.html                # Oracle JET SPA エントリ
    ├── css/                      # スタイルシート
    ├── js/
    │   ├── main.js               # RequireJS ブートストラップ
    │   ├── root.js               # Knockout バインディング初期化
    │   ├── appController.js      # メインコントローラー
    │   ├── views/                # HTML テンプレート
    │   └── viewModels/           # Knockout ViewModel
    ├── app/
    │   ├── blueprints/           # Flask Blueprint (api, static)
    │   ├── middlewares/           # CORS, Security headers
    │   ├── error_handlers/       # グローバルエラーハンドラ
    │   ├── exceptions/           # IntentServiceError (ICS-XXXX)
    │   └── util/                 # Logger, Response, ImportUtil 等
    ├── src/denpyo_toroku/
    │   ├── classifier.py         # ProductionIntentClassifier
    │   ├── cache.py              # EmbeddingCache (LRU)
    │   └── monitor.py            # PerformanceMonitor
    ├── models/                   # 学習済みモデル (.pkl)
    └── log/                      # ログファイル出力先
```

---

## OCI 設定

サービスは OCI GenAI の Embedding API を使用するため、OCI 認証設定が必要です。

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
region=us-chicago-1
key_file=~/.oci/oci_api_key.pem
```

### 3. Compartment ID の取得

```bash
oci iam compartment list --compartment-id-in-subtree true --query "data[].{name:name, id:id}" --output table
```

取得した `compartment_id` を環境変数 `OCI_CONFIG_COMPARTMENT` またはトレーニングスクリプトの CONFIG に設定します。

---

## ローカル環境構築 (Docker)

最も簡単な起動方法です。

### 1. リポジトリのクローンとディレクトリ移動

```bash
git clone <repository-url>
cd no.1-intent-classifier
```

### 2. 必要ディレクトリの作成

```bash
mkdir -p denpyo_toroku/log denpyo_toroku/models
```

### 3. ビルドと起動

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

### 4. 動作確認

```bash
# ヘルスチェック
curl http://localhost:8080/api/v1/health

# UI にアクセス
# ブラウザで http://localhost:8080 を開く
```

### 5. 停止

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
cd no.1-intent-classifier

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

```bash
export OCI_CONFIG_PATH=~/.oci/config
export OCI_CONFIG_PROFILE=DEFAULT
export OCI_CONFIG_COMPARTMENT=ocid1.compartment.oc1..xxxxx  # 自身の Compartment ID
export OCI_SERVICE_ENDPOINT=https://inference.generativeai.us-chicago-1.oci.oraclecloud.com
export LOG_LEVEL=INFO
export ENABLE_CACHE=true
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
cd no.1-intent-classifier
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

### 単一テキスト予測

```bash
curl -s -X POST "http://localhost:8080/api/v1/predict/single" \
  -H "Content-Type: application/json" \
  -d '{"text": "注文の配送状況を確認したい", "return_proba": true}' \
  | python3 -m json.tool
```

### バッチ予測

```bash
curl -s -X POST "http://localhost:8080/api/v1/predict" \
  -H "Content-Type: application/json" \
  -d '{
    "texts": [
      "注文の配送状況を確認したい",
      "商品を返品したい",
      "クーポンコードを使いたい"
    ],
    "return_proba": true,
    "confidence_threshold": 0.5
  }' | python3 -m json.tool
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

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/health` | ヘルスチェック |
| `GET` | `/api/v1/version` | サービスバージョン情報 |
| `GET` | `/api/v1/stats` | パフォーマンス統計 (P95/P99、キャッシュ等) |
| `GET` | `/api/v1/model/info` | モデル詳細情報 (クラス一覧、パラメータ) |
| `POST` | `/api/v1/predict` | バッチ予測 (最大100件) |
| `POST` | `/api/v1/predict/single` | 単一テキスト予測 |
| `POST` | `/api/v1/cache/clear` | Embedding キャッシュクリア |

---

## 環境変数一覧

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `OCI_CONFIG_PATH` | `~/.oci/config` | OCI 設定ファイルのパス |
| `OCI_CONFIG_PROFILE` | `DEFAULT` | OCI プロファイル名 |
| `OCI_CONFIG_COMPARTMENT` | (空) | OCI Compartment OCID |
| `OCI_SERVICE_ENDPOINT` | `https://inference.generativeai.us-chicago-1.oci.oraclecloud.com` | GenAI サービスエンドポイント |
| `EMBEDDING_MODEL_ID` | `cohere.embed-v4.0` | Embedding モデル ID |
| `MODEL_PATH` | `denpyo_toroku/models/intent_model_production.pkl` | モデルファイルパス |
| `MODEL_DIR` | `denpyo_toroku/models` | モデルディレクトリ |
| `LOG_LEVEL` | `INFO` | ログレベル (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |
| `ENABLE_CACHE` | `true` | Embedding キャッシュの有効/無効 |
| `CACHE_SIZE` | `10000` | キャッシュ最大エントリ数 |
| `BATCH_SIZE` | `96` | Embedding API バッチサイズ |
| `WEBAPP_PORT` | `5000` | Flask 直接起動時のポート |
| `GUNICORN_BIND` | `0.0.0.0:8080` | Gunicorn バインドアドレス |
| `GUNICORN_DAEMON` | `false` | Gunicorn daemon モード (`scripts/manage.sh` 使用時は自動で `true`) |
| `DENPYO_TOROKU_DEBUG_MODE` | (空) | `true` でデバッグモード有効 |

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

### Docker コンテナが起動しない

```bash
# ログ確認
docker-compose logs intent-classifier

# コンテナ内に入って確認
docker exec -it intent-classifier-service bash
```

- `GUNICORN_DAEMON` が Docker 環境では `false` (デフォルト) であることを確認
- ポート 8080 が別プロセスで使用されていないか確認: `lsof -i :8080`

### キャッシュ関連の問題

```bash
# キャッシュクリア
curl -X POST http://localhost:8080/api/v1/cache/clear

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
