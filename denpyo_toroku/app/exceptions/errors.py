# Denpyo Toroku Service のエラーコード定義

# 内部エラー
ERR_INTERNAL = 1000

# OCI Object Storage 関連
ERR_STORAGE_UPLOAD_FAILED = 2001
ERR_STORAGE_DOWNLOAD_FAILED = 2002
ERR_STORAGE_DELETE_FAILED = 2003
ERR_STORAGE_LIST_FAILED = 2004
ERR_STORAGE_NOT_CONFIGURED = 2005

# AI 分析関連
ERR_AI_ANALYSIS_FAILED = 3001
ERR_AI_TIMEOUT = 3002
ERR_AI_INVALID_INPUT = 3003
ERR_AI_MODEL_NOT_AVAILABLE = 3004

# データベース関連
ERR_DB_CONNECTION_FAILED = 4001
ERR_DB_QUERY_FAILED = 4002
ERR_DB_TABLE_CREATE_FAILED = 4003
ERR_DB_REGISTRATION_FAILED = 4004

# 伝票処理関連
ERR_DENPYO_INVALID_FILE = 5001
ERR_DENPYO_CLASSIFICATION_FAILED = 5002
ERR_DENPYO_FIELD_EXTRACTION_FAILED = 5003

# 設定関連
ERR_CONFIG_INVALID = 6001
ERR_OCI_CONFIG_MISSING = 6002


ERR_MESSAGES = {
    ERR_INTERNAL: {
        "message": "内部エラー: {error}",
        "cause": "予期しない内部エラーが発生しました。",
        "action": "詳細はログを確認してください。解決しない場合はサポートへ連絡してください。",
        "exit_code": 1
    },
    ERR_STORAGE_UPLOAD_FAILED: {
        "message": "ファイルのアップロードに失敗しました: {error}",
        "cause": "OCI Object Storage へのアップロード中にエラーが発生しました。",
        "action": "OCI 設定とネットワーク接続を確認してください。",
        "exit_code": 1
    },
    ERR_STORAGE_DOWNLOAD_FAILED: {
        "message": "ファイルのダウンロードに失敗しました: {error}",
        "cause": "OCI Object Storage からのダウンロード中にエラーが発生しました。",
        "action": "オブジェクト名とバケット設定を確認してください。",
        "exit_code": 1
    },
    ERR_STORAGE_DELETE_FAILED: {
        "message": "ファイルの削除に失敗しました: {error}",
        "cause": "OCI Object Storage のオブジェクト削除中にエラーが発生しました。",
        "action": "オブジェクト名と権限を確認してください。",
        "exit_code": 1
    },
    ERR_STORAGE_LIST_FAILED: {
        "message": "ファイル一覧の取得に失敗しました: {error}",
        "cause": "OCI Object Storage のオブジェクト一覧取得中にエラーが発生しました。",
        "action": "バケット設定と権限を確認してください。",
        "exit_code": 1
    },
    ERR_STORAGE_NOT_CONFIGURED: {
        "message": "OCI Object Storage が設定されていません。",
        "cause": "バケット名またはネームスペースが未設定です。",
        "action": "OCI_BUCKET と OCI_NAMESPACE 環境変数を設定してください。",
        "exit_code": 1
    },
    ERR_AI_ANALYSIS_FAILED: {
        "message": "AI 分析に失敗しました: {error}",
        "cause": "Generative AI API の呼び出し中にエラーが発生しました。",
        "action": "OCI 設定とモデル ID を確認してください。",
        "exit_code": 1
    },
    ERR_AI_TIMEOUT: {
        "message": "AI 分析がタイムアウトしました。",
        "cause": "Generative AI API がタイムアウト時間内に応答しませんでした。",
        "action": "リトライするか、画像サイズを小さくしてください。",
        "exit_code": 1
    },
    ERR_AI_INVALID_INPUT: {
        "message": "AI 分析の入力が不正です: {error}",
        "cause": "入力ファイルが不正、または対応していない形式です。",
        "action": "対応ファイル形式（PDF, JPEG, PNG）を確認してください。",
        "exit_code": 1
    },
    ERR_AI_MODEL_NOT_AVAILABLE: {
        "message": "AI モデルが利用できません: {model}",
        "cause": "指定されたモデルが使用できない状態です。",
        "action": "モデル ID と OCI リージョンを確認してください。",
        "exit_code": 1
    },
    ERR_DB_CONNECTION_FAILED: {
        "message": "データベース接続に失敗しました: {error}",
        "cause": "Oracle Database への接続中にエラーが発生しました。",
        "action": "接続文字列、Wallet、データベースの状態を確認してください。",
        "exit_code": 1
    },
    ERR_DB_QUERY_FAILED: {
        "message": "クエリの実行に失敗しました: {error}",
        "cause": "SQL クエリの実行中にエラーが発生しました。",
        "action": "SQL 文とテーブル構造を確認してください。",
        "exit_code": 1
    },
    ERR_DB_TABLE_CREATE_FAILED: {
        "message": "テーブルの作成に失敗しました: {error}",
        "cause": "DDL の実行中にエラーが発生しました。",
        "action": "テーブル名と権限を確認してください。",
        "exit_code": 1
    },
    ERR_DB_REGISTRATION_FAILED: {
        "message": "伝票の登録に失敗しました: {error}",
        "cause": "伝票データのデータベース登録中にエラーが発生しました。",
        "action": "データ形式とテーブル構造を確認してください。",
        "exit_code": 1
    },
    ERR_DENPYO_INVALID_FILE: {
        "message": "無効なファイルです: {error}",
        "cause": "アップロードされたファイルが処理できません。",
        "action": "対応ファイル形式（PDF, JPEG, PNG）と最大サイズを確認してください。",
        "exit_code": 1
    },
    ERR_DENPYO_CLASSIFICATION_FAILED: {
        "message": "伝票の分類に失敗しました: {error}",
        "cause": "AI による伝票種別の判定中にエラーが発生しました。",
        "action": "画像の品質と AI 設定を確認してください。",
        "exit_code": 1
    },
    ERR_DENPYO_FIELD_EXTRACTION_FAILED: {
        "message": "フィールド抽出に失敗しました: {error}",
        "cause": "AI による伝票フィールドの読み取り中にエラーが発生しました。",
        "action": "画像の品質を確認してください。",
        "exit_code": 1
    },
    ERR_CONFIG_INVALID: {
        "message": "設定が不正です: {error}",
        "cause": "設定に必須の値が不足しています。",
        "action": "config.ini と環境変数を確認してください。",
        "exit_code": 1
    },
    ERR_OCI_CONFIG_MISSING: {
        "message": "OCI 設定ファイルが見つかりません: {path}",
        "cause": "OCI 設定ファイルが存在しません。",
        "action": "OCI 設定ファイルを作成するか、OCI_CONFIG_PATH 環境変数を設定してください。",
        "exit_code": 1
    },
}
