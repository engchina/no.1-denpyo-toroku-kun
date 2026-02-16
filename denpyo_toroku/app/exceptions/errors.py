# Intent Classifier Service のエラーコード定義

# 内部エラー
ERR_INTERNAL = 1000

# モデル関連
ERR_MODEL_NOT_LOADED = 2001
ERR_MODEL_LOAD_FAILED = 2002
ERR_MODEL_SAVE_FAILED = 2003
ERR_MODEL_NOT_TRAINED = 2004

# 埋め込み関連
ERR_EMBEDDING_FAILED = 3001
ERR_EMBEDDING_TIMEOUT = 3002
ERR_EMBEDDING_INVALID_INPUT = 3003

# 予測関連
ERR_PREDICTION_FAILED = 4001
ERR_PREDICTION_EMPTY_INPUT = 4002
ERR_PREDICTION_BATCH_TOO_LARGE = 4003

# 学習関連
ERR_TRAINING_FAILED = 5001
ERR_TRAINING_DATA_INVALID = 5002
ERR_TRAINING_INSUFFICIENT_DATA = 5003

# 設定関連
ERR_CONFIG_INVALID = 6001
ERR_OCI_CONFIG_MISSING = 6002

# 分類器タイプ関連
ERR_INVALID_CLASSIFIER_TYPE = 7001


ERR_MESSAGES = {
    ERR_INTERNAL: {
        "message": "内部エラー: {error}",
        "cause": "予期しない内部エラーが発生しました。",
        "action": "詳細はログを確認してください。解決しない場合はサポートへ連絡してください。",
        "exit_code": 1
    },
    ERR_MODEL_NOT_LOADED: {
        "message": "モデルが読み込まれていません。",
        "cause": "分類モデルがメモリに読み込まれていません。",
        "action": "学習済みモデルを読み込むか、新しく学習してください。",
        "exit_code": 1
    },
    ERR_MODEL_LOAD_FAILED: {
        "message": "モデルの読み込みに失敗しました: {path}",
        "cause": "モデルファイルを読み込めない、または破損している可能性があります。",
        "action": "モデルファイルの存在と形式（pickle）を確認してください。",
        "exit_code": 1
    },
    ERR_MODEL_SAVE_FAILED: {
        "message": "モデルの保存に失敗しました: {path}",
        "cause": "モデルをディスクに書き込めませんでした。",
        "action": "ディスク容量と権限を確認してください。",
        "exit_code": 1
    },
    ERR_MODEL_NOT_TRAINED: {
        "message": "保存できる学習済みモデルがありません。",
        "cause": "分類器がまだ学習されていません。",
        "action": "保存する前に学習してください。",
        "exit_code": 1
    },
    ERR_EMBEDDING_FAILED: {
        "message": "埋め込みの取得に失敗しました: {error}",
        "cause": "埋め込み API の呼び出しに失敗しました。",
        "action": "OCI 設定とネットワーク接続を確認してください。",
        "exit_code": 1
    },
    ERR_EMBEDDING_TIMEOUT: {
        "message": "埋め込みリクエストがタイムアウトしました。",
        "cause": "埋め込み API がタイムアウト時間内に応答しませんでした。",
        "action": "タイムアウトを延長するか、バッチサイズを小さくしてください。",
        "exit_code": 1
    },
    ERR_EMBEDDING_INVALID_INPUT: {
        "message": "埋め込み入力が不正です: {error}",
        "cause": "入力テキストが不正、または空です。",
        "action": "入力が空でないことと文字コードを確認してください。",
        "exit_code": 1
    },
    ERR_PREDICTION_FAILED: {
        "message": "予測に失敗しました: {error}",
        "cause": "予測処理中にエラーが発生しました。",
        "action": "入力データとモデル状態を確認してください。",
        "exit_code": 1
    },
    ERR_PREDICTION_EMPTY_INPUT: {
        "message": "予測対象のテキストが指定されていません。",
        "cause": "予測リクエストのテキスト一覧が空です。",
        "action": "少なくとも 1 件のテキストを指定してください。",
        "exit_code": 1
    },
    ERR_PREDICTION_BATCH_TOO_LARGE: {
        "message": "バッチサイズ {size} は上限 {max_size} を超えています。",
        "cause": "1 回の予測リクエストに含まれるテキストが多すぎます。",
        "action": "テキスト数を減らすか、複数回に分割してください。",
        "exit_code": 1
    },
    ERR_TRAINING_FAILED: {
        "message": "学習に失敗しました: {error}",
        "cause": "モデル学習中にエラーが発生しました。",
        "action": "学習データとパラメータを確認してください。",
        "exit_code": 1
    },
    ERR_TRAINING_DATA_INVALID: {
        "message": "学習データ形式が不正です。",
        "cause": "学習データが期待する形式と一致しません。",
        "action": "（text, label）の組の一覧であることを確認してください。",
        "exit_code": 1
    },
    ERR_TRAINING_INSUFFICIENT_DATA: {
        "message": "学習データが不足しています: {count} 件（最小: {minimum} 件）。",
        "cause": "信頼できるモデルを作るにはサンプル数が足りません。",
        "action": "少数クラスのデータを中心に追加してください。",
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
    ERR_INVALID_CLASSIFIER_TYPE: {
        "message": "分類器タイプの指定が不正です。",
        "cause": "指定された分類器タイプはサポートされていません。",
        "action": "サポートされる分類器タイプ（例: 'GradientBoosting', 'LogisticRegression'）を指定してください。",
        "exit_code": 1
    },
}
