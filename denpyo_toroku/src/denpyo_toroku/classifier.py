"""
本番向け意図分類器
エラーハンドリング、ロギング、性能監視、キャッシュを含む。
"""

import oci
import numpy as np
import pickle
import logging
import time
import json
import random
from typing import List, Tuple, Dict, Optional, Callable, Any
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score
from sklearn.model_selection import train_test_split
from datetime import datetime
from pathlib import Path
from functools import wraps
import threading

from denpyo_toroku.src.denpyo_toroku.cache import EmbeddingCache
from denpyo_toroku.src.denpyo_toroku.monitor import PerformanceMonitor
from denpyo_toroku.app.exceptions.exceptions import IntentServiceError
from denpyo_toroku.app.exceptions import errors as svc_errors


_RETRYABLE_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
_RETRYABLE_ERROR_HINTS = (
    "too many requests",
    "rate limit",
    "throttl",
    "timeout",
    "temporar",
    "connection reset",
    "connection aborted",
    "service unavailable",
)


def _extract_status_code(exc: Exception) -> Optional[int]:
    """例外オブジェクトから HTTP ステータスコードを抽出する。"""
    for attr in ("status", "status_code", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def _extract_retry_after_seconds(exc: Exception) -> Optional[float]:
    """Retry-After ヘッダーがある場合は待機秒数を返す。"""
    headers = getattr(exc, "headers", None)
    if not isinstance(headers, dict):
        return None

    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None

    try:
        retry_after = float(raw)
    except (TypeError, ValueError):
        return None
    return retry_after if retry_after > 0 else None


def _is_retryable_oci_error(exc: Exception) -> bool:
    """OCI 呼び出しで一時的な障害とみなせる例外かを判定する。"""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True

    status = _extract_status_code(exc)
    if status in _RETRYABLE_HTTP_STATUS:
        return True

    message = str(exc).lower()
    return any(token in message for token in _RETRYABLE_ERROR_HINTS)


def retry_on_failure(
    max_retries: int = 3,
    delay: float = 1.0,
    max_delay: float = 8.0,
    jitter_ratio: float = 0.2,
    retryable_checker: Optional[Callable[[Exception], bool]] = None,
):
    """指数バックオフ + ジッター付きの API リトライデコレータ。"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = getattr(args[0], "logger", None) if args else None
            checker = retryable_checker or _is_retryable_oci_error
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if not checker(e):
                        raise

                    if attempt >= max_retries:
                        break

                    backoff = min(max_delay, delay * (2 ** (attempt - 1)))
                    jitter_range = backoff * max(0.0, jitter_ratio)
                    jitter = random.uniform(-jitter_range, jitter_range)
                    wait_seconds = max(0.0, backoff + jitter)

                    retry_after = _extract_retry_after_seconds(e)
                    if retry_after is not None:
                        wait_seconds = max(wait_seconds, retry_after)

                    if logger:
                        logger.warning(
                            "OCI API 呼び出し失敗（試行 %d/%d）: %s。%.2f 秒後にリトライします。",
                            attempt,
                            max_retries,
                            e,
                            wait_seconds,
                        )

                    time.sleep(wait_seconds)
            raise last_exception
        return wrapper
    return decorator


class ProductionIntentClassifier:
    """
    本番向け意図分類器

    特徴:
    - エラーハンドリング
    - 性能監視
    - 埋め込みキャッシュ
    - リトライ機構
    - 詳細ログ
    - スレッドセーフ
    """

    def __init__(self,
                 config_path: str = "~/.oci/config",
                 profile: str = "DEFAULT",
                 service_endpoint: str = None,
                 compartment_id: str = None,
                 embedding_model_id: str = "cohere.embed-v4.0",
                 log_file: str = None,
                 log_level: str = "INFO",
                 enable_cache: bool = True,
                 cache_size: int = 10000,
                 enable_monitoring: bool = True):
        """
        本番向け意図分類器を初期化する。

        Args:
            config_path: OCI config file path
            profile: OCI profile name
            service_endpoint: GenAI service endpoint
            compartment_id: OCI compartment ID
            embedding_model_id: Embedding model ID
            log_file: Log file path (None for console only)
            log_level: Log level
            enable_cache: Enable embedding cache
            cache_size: Max cache size
            enable_monitoring: Enable performance monitoring
        """
        self._setup_logger(log_level, log_file)
        self.logger.info("=" * 70)
        self.logger.info("本番向け意図分類器を初期化しています…")
        self.logger.info("=" * 70)

        try:
            # OCI 設定
            self.logger.info("OCI 設定を読み込み: %s", config_path)
            self.config = oci.config.from_file(config_path, profile)
            self.compartment_id = compartment_id or self.config.get("tenancy")

            # GenAI クライアント
            self.logger.info("GenAI クライアントを初期化しています…")
            self.genai_client = oci.generative_ai_inference.GenerativeAiInferenceClient(
                config=self.config,
                service_endpoint=service_endpoint
            )

            self.embedding_model_id = embedding_model_id
            self.logger.info("埋め込みモデル: %s", embedding_model_id)

            # 分類器
            self.classifier = None
            self.algorithm_name = "Untrained"
            self.model_source = "initialized"
            self.model_timestamp = None
            self.last_training_summary = None
            self.label_encoder = {}
            self.reverse_label_encoder = {}

            # 稼働時間計測の開始時刻
            self._start_time = time.time()

            # キャッシュ
            self.enable_cache = enable_cache
            if enable_cache:
                self.cache = EmbeddingCache(max_size=cache_size)
                self.logger.info("埋め込みキャッシュ有効（サイズ: %d）", cache_size)
            else:
                self.cache = None

            # 性能監視
            self.enable_monitoring = enable_monitoring
            if enable_monitoring:
                self.monitor = PerformanceMonitor()
                self.logger.info("性能監視を有効化しました")
            else:
                self.monitor = None

            # スレッドロック
            self.lock = threading.RLock()

            self.logger.info("初期化が完了しました")

        except Exception as e:
            self.logger.error("初期化エラー: %s", e, exc_info=True)
            raise

    def _setup_logger(self, log_level: str, log_file: Optional[str]):
        """ロガー設定を初期化する。"""
        self.logger = logging.getLogger('ProductionIntentClassifier')
        self.logger.setLevel(getattr(logging, log_level.upper()))
        self.logger.handlers.clear()

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(threadName)s] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        if log_file:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    @retry_on_failure(max_retries=3, delay=1.0)
    def _get_embeddings_batch(self, texts: List[str], input_type: str = "CLASSIFICATION") -> list:
        """リトライ付きで埋め込みをバッチ取得する。"""
        embed_text_detail = oci.generative_ai_inference.models.EmbedTextDetails(
            inputs=texts,
            serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                model_id=self.embedding_model_id
            ),
            compartment_id=self.compartment_id,
            input_type=input_type,
            truncate="END"
        )

        embed_text_response = self.genai_client.embed_text(embed_text_detail)
        # OCI SDK returns embeddings as list[list[float]] directly
        return embed_text_response.data.embeddings

    def get_embeddings(self,
                       texts: List[str],
                       batch_size: int = 96,
                       use_cache: bool = True) -> np.ndarray:
        """
        キャッシュとバッチ処理で埋め込みを取得する。

        Args:
            texts: List of texts
            batch_size: Batch size for API calls
            use_cache: Whether to use cache

        Returns:
            Embedding array
        """
        start_time = time.time()
        self.logger.info("埋め込み取得: %d 件", len(texts))

        all_embeddings = []
        texts_to_fetch = []
        fetch_indices = []

        # キャッシュ確認
        if self.enable_cache and use_cache:
            for i, text in enumerate(texts):
                cached = self.cache.get(text)
                if cached is not None:
                    all_embeddings.append((i, cached))
                else:
                    texts_to_fetch.append(text)
                    fetch_indices.append(i)
        else:
            texts_to_fetch = texts
            fetch_indices = list(range(len(texts)))

        # API から取得
        if texts_to_fetch:
            try:
                fetched_embeddings = []
                for i in range(0, len(texts_to_fetch), batch_size):
                    batch = texts_to_fetch[i:i + batch_size]
                    batch_embeddings = self._get_embeddings_batch(batch)
                    fetched_embeddings.extend(batch_embeddings)
                    self.logger.debug("バッチ進捗: %d/%d",
                                      min(i + batch_size, len(texts_to_fetch)),
                                      len(texts_to_fetch))

                # キャッシュへ保存
                if self.enable_cache and use_cache:
                    for text, emb in zip(texts_to_fetch, fetched_embeddings):
                        self.cache.set(text, np.array(emb))

                # 結果を統合
                for idx, emb in zip(fetch_indices, fetched_embeddings):
                    all_embeddings.append((idx, emb))

            except Exception as e:
                self.logger.error("埋め込み取得エラー: %s", e, exc_info=True)
                if self.monitor:
                    self.monitor.record_error()
                raise

        # インデックス順に並べ替え
        all_embeddings.sort(key=lambda x: x[0])
        result = np.array([emb for _, emb in all_embeddings])

        duration = time.time() - start_time
        if self.monitor:
            self.monitor.record_embedding(duration)

        self.logger.info("埋め込み取得完了: %.2fs", duration)
        return result

    def prepare_labels(self, labels: List[str]) -> np.ndarray:
        """ラベルをエンコードする。"""
        with self.lock:
            unique_labels = sorted(list(set(labels)))
            self.label_encoder = {label: idx for idx, label in enumerate(unique_labels)}
            self.reverse_label_encoder = {idx: label for label, idx in self.label_encoder.items()}

            encoded_labels = np.array([self.label_encoder[label] for label in labels])
            self.logger.info("ラベルエンコード完了: %d クラス", len(unique_labels))
            return encoded_labels

    def _rebalance_training_set(self,
                                X_train: np.ndarray,
                                y_train: np.ndarray,
                                strategy: str,
                                random_state: int) -> Tuple[np.ndarray, np.ndarray]:
        """必要に応じて、少数クラスの単純アップサンプルで学習データをリバランスする。"""
        mode = (strategy or "none").strip().lower()
        if mode != "balanced_upsample":
            return X_train, y_train

        classes, counts = np.unique(y_train, return_counts=True)
        if len(classes) <= 1:
            return X_train, y_train

        max_count = int(np.max(counts))
        if max_count <= 0:
            return X_train, y_train

        rng = np.random.default_rng(random_state)
        sampled_indices: List[int] = []
        for cls, count in zip(classes, counts):
            cls_indices = np.where(y_train == cls)[0]
            if cls_indices.size == 0:
                continue
            sampled_indices.extend(cls_indices.tolist())
            if count < max_count:
                extra = rng.choice(cls_indices, size=max_count - int(count), replace=True)
                sampled_indices.extend(extra.tolist())

        if not sampled_indices:
            return X_train, y_train

        sampled_array = np.array(sampled_indices, dtype=int)
        rng.shuffle(sampled_array)
        return X_train[sampled_array], y_train[sampled_array]

    def train(self,
              texts: List[str],
              labels: List[str],
              test_size: float = 0.2,
              random_state: int = 42,
              validation_split: float = 0.1,
              early_stopping_rounds: int = 10,
              compare_baselines: bool = True,
              preferred_algorithm: str = "auto",
              auto_tune: bool = False,
              rebalance_strategy: str = "none",
              progress_callback: Optional[Callable[[str], None]] = None,
              **classifier_params) -> Dict:
        """
        早期終了に対応したモデル学習を行う。

        Args:
            texts: Training texts
            labels: Labels
            test_size: Test set ratio
            random_state: Random seed
            validation_split: Validation set ratio
            early_stopping_rounds: Early stopping rounds
            auto_tune: Whether to try multiple GBDT variants
            rebalance_strategy: Training-set balancing strategy
            progress_callback: Optional callback for progress updates
            **classifier_params: Classifier parameters

        Returns:
            Training results dictionary
        """
        with self.lock:
            self.logger.info("=" * 70)
            self.logger.info("モデル学習を開始します")
            self.logger.info("=" * 70)

            try:
                overall_start_time = time.time()

                def report_progress(message: str):
                    self.logger.info("%s", message)
                    if callable(progress_callback):
                        try:
                            progress_callback(message)
                        except Exception:
                            self.logger.debug("学習進捗コールバックの呼び出しに失敗しました", exc_info=True)

                # Step 1: 埋め込み生成
                report_progress("[1/5] 埋め込みを生成中")
                embeddings = self.get_embeddings(texts, use_cache=False)

                # Step 2: ラベルエンコード
                report_progress("[2/5] ラベルをエンコード中")
                encoded_labels = self.prepare_labels(labels)

                # Step 3: データ分割
                report_progress("[3/5] データセットを分割中")
                X_train, X_test, y_train, y_test = train_test_split(
                    embeddings, encoded_labels,
                    test_size=test_size,
                    random_state=random_state,
                    stratify=encoded_labels
                )

                self.logger.info("学習データ: %d 件", X_train.shape[0])
                self.logger.info("テストデータ: %d 件", X_test.shape[0])

                X_train_fit, y_train_fit = self._rebalance_training_set(
                    X_train,
                    y_train,
                    strategy=rebalance_strategy,
                    random_state=random_state
                )
                if X_train_fit.shape[0] != X_train.shape[0]:
                    self.logger.info(
                        "学習データをリバランス（%s）: %d -> %d 件",
                        rebalance_strategy,
                        X_train.shape[0],
                        X_train_fit.shape[0]
                    )

                # Step 4: 候補モデル学習
                report_progress("[4/5] 候補モデルを学習中")

                default_params = {
                    'n_estimators': 200,
                    'learning_rate': 0.1,
                    'max_depth': 5,
                    'min_samples_split': 20,
                    'min_samples_leaf': 10,
                    'subsample': 0.8,
                    'random_state': random_state,
                    'verbose': 1,
                    'validation_fraction': validation_split if validation_split > 0 else 0.1,
                    'n_iter_no_change': early_stopping_rounds,
                    'tol': 1e-4
                }
                default_params.update(classifier_params)

                strategy = (preferred_algorithm or "auto").strip().lower()
                labels_order = list(range(len(self.label_encoder)))
                target_names = [self.reverse_label_encoder[i] for i in labels_order]
                candidate_results: List[Dict[str, Any]] = []

                def evaluate_candidate(name: str, model: Any) -> Dict[str, Any]:
                    model.fit(X_train_fit, y_train_fit)
                    y_train_pred = model.predict(X_train_fit)
                    y_test_pred = model.predict(X_test)

                    train_accuracy = float(accuracy_score(y_train_fit, y_train_pred))
                    test_accuracy = float(accuracy_score(y_test, y_test_pred))

                    train_report = classification_report(
                        y_train_fit,
                        y_train_pred,
                        labels=labels_order,
                        target_names=target_names,
                        output_dict=True,
                        zero_division=0
                    )
                    test_report = classification_report(
                        y_test,
                        y_test_pred,
                        labels=labels_order,
                        target_names=target_names,
                        output_dict=True,
                        zero_division=0
                    )

                    train_macro_f1 = float(train_report.get("macro avg", {}).get("f1-score", 0.0))
                    test_macro_f1 = float(test_report.get("macro avg", {}).get("f1-score", 0.0))
                    test_weighted_f1 = float(test_report.get("weighted avg", {}).get("f1-score", 0.0))
                    overfitting_gap = float(train_accuracy - test_accuracy)
                    macro_f1_gap = float(train_macro_f1 - test_macro_f1)
                    selection_score = float(
                        round(
                            (0.70 * test_macro_f1) +
                            (0.25 * test_accuracy) +
                            (0.05 * test_weighted_f1) -
                            (max(0.0, overfitting_gap - 0.05) * 0.30) -
                            (max(0.0, macro_f1_gap - 0.05) * 0.30),
                            6
                        )
                    )

                    return {
                        'name': name,
                        'model': model,
                        'train_accuracy': train_accuracy,
                        'test_accuracy': test_accuracy,
                        'overfitting_gap': overfitting_gap,
                        'train_macro_f1': train_macro_f1,
                        'test_macro_f1': test_macro_f1,
                        'test_weighted_f1': test_weighted_f1,
                        'macro_f1_gap': macro_f1_gap,
                        'selection_score': selection_score,
                        'y_test_pred': y_test_pred,
                        'test_report': test_report
                    }

                if strategy in ("auto", "gbdt"):
                    gbdt_candidates: List[Tuple[str, Dict[str, Any]]] = [("base", dict(default_params))]
                    if auto_tune:
                        shallow = dict(default_params)
                        shallow.update({
                            "max_depth": max(2, int(default_params.get("max_depth", 5)) - 2),
                            "learning_rate": max(0.01, float(default_params.get("learning_rate", 0.1)) * 0.85),
                            "n_estimators": min(1000, int(default_params.get("n_estimators", 200)) + 80)
                        })
                        deeper = dict(default_params)
                        deeper.update({
                            "max_depth": min(10, int(default_params.get("max_depth", 5)) + 1),
                            "learning_rate": min(0.30, float(default_params.get("learning_rate", 0.1)) * 1.1),
                            "n_estimators": max(50, int(default_params.get("n_estimators", 200)) - 40)
                        })
                        conservative = dict(default_params)
                        conservative.update({
                            "subsample": min(1.0, float(default_params.get("subsample", 0.8)) + 0.1),
                            "min_samples_leaf": max(4, int(default_params.get("min_samples_leaf", 10)) + 2),
                            "learning_rate": max(0.01, float(default_params.get("learning_rate", 0.1)) * 0.9)
                        })
                        gbdt_candidates.extend([
                            ("shallow", shallow),
                            ("deeper", deeper),
                            ("conservative", conservative),
                        ])

                    seen_signatures = set()
                    dedup_candidates: List[Tuple[str, Dict[str, Any]]] = []
                    for variant_name, variant_params in gbdt_candidates:
                        signature = tuple(sorted(variant_params.items()))
                        if signature in seen_signatures:
                            continue
                        seen_signatures.add(signature)
                        dedup_candidates.append((variant_name, variant_params))

                    for idx, (variant_name, variant_params) in enumerate(dedup_candidates, start=1):
                        report_progress(
                            "[Step 4/5] Training GBDT candidate %d/%d (%s)" %
                            (idx, len(dedup_candidates), variant_name)
                        )
                        gbdt_model = GradientBoostingClassifier(**variant_params)
                        candidate_results.append(
                            evaluate_candidate(
                                name="GradientBoostingClassifier" if len(dedup_candidates) == 1
                                else "GradientBoostingClassifier:%s" % variant_name,
                                model=gbdt_model
                            )
                        )

                if strategy in ("auto", "lr") and (strategy == "lr" or compare_baselines):
                    report_progress("[Step 4/5] Training Logistic Regression baseline")
                    lr_model = LogisticRegression(
                        max_iter=1200,
                        class_weight='balanced',
                        random_state=random_state
                    )
                    candidate_results.append(evaluate_candidate("LogisticRegression", lr_model))

                if not candidate_results:
                    raise ValueError("候補モデルが学習されませんでした。preferred_algorithm と compare_baselines を確認してください。")

                best_candidate = sorted(
                    candidate_results,
                    key=lambda c: (c['selection_score'], c['test_macro_f1'], c['test_accuracy']),
                    reverse=True
                )[0]
                self.classifier = best_candidate['model']
                self.algorithm_name = best_candidate['name']
                y_test_pred = best_candidate['y_test_pred']
                train_accuracy = float(best_candidate['train_accuracy'])
                test_accuracy = float(best_candidate['test_accuracy'])
                test_macro_f1 = float(best_candidate['test_macro_f1'])
                test_weighted_f1 = float(best_candidate['test_weighted_f1'])
                train_macro_f1 = float(best_candidate['train_macro_f1'])
                selection_score = float(best_candidate['selection_score'])

                self.logger.info("選択モデル: %s", self.algorithm_name)
                for candidate in candidate_results:
                    self.logger.info(
                        "  候補 %s -> 学習精度: %.4f テスト精度: %.4f テストMacro-F1: %.4f スコア: %.4f",
                        candidate['name'],
                        candidate['train_accuracy'],
                        candidate['test_accuracy'],
                        candidate['test_macro_f1'],
                        candidate['selection_score']
                    )

                self.logger.info("学習精度: %.4f", train_accuracy)
                self.logger.info("テスト精度: %.4f", test_accuracy)
                self.logger.info("テスト Macro-F1: %.4f", test_macro_f1)

                report = classification_report(
                    y_test, y_test_pred,
                    labels=labels_order,
                    target_names=target_names,
                    zero_division=0
                )
                self.logger.info("\n%s", report)

                per_class_metrics = []
                best_report = best_candidate.get("test_report", {}) or {}
                for class_name in target_names:
                    class_metrics = best_report.get(class_name)
                    if not isinstance(class_metrics, dict):
                        continue
                    per_class_metrics.append({
                        "intent": class_name,
                        "precision": float(class_metrics.get("precision", 0.0)),
                        "recall": float(class_metrics.get("recall", 0.0)),
                        "f1_score": float(class_metrics.get("f1-score", 0.0)),
                        "support": int(class_metrics.get("support", 0)),
                    })

                report_progress("[5/5] 学習サマリーを作成中")

                training_summary = {
                    'train_accuracy': train_accuracy,
                    'test_accuracy': test_accuracy,
                    'overfitting_gap': train_accuracy - test_accuracy,
                    'train_macro_f1': train_macro_f1,
                    'test_macro_f1': test_macro_f1,
                    'test_weighted_f1': test_weighted_f1,
                    'macro_f1_gap': train_macro_f1 - test_macro_f1,
                    'selection_score': selection_score,
                    'selected_algorithm': self.algorithm_name,
                    'requested_algorithm': strategy,
                    'auto_tune_used': bool(auto_tune),
                    'rebalance_strategy_used': (rebalance_strategy or "none").strip().lower(),
                    'num_classes': len(self.label_encoder),
                    'train_samples': X_train.shape[0],
                    'test_samples': X_test.shape[0],
                    'n_estimators_used': getattr(self.classifier, 'n_estimators_', 0),
                    'candidate_count': len(candidate_results),
                    'training_duration_seconds': float(round(time.time() - overall_start_time, 3)),
                    'per_class_metrics': per_class_metrics,
                    'candidates': [
                        {
                            'algorithm': c['name'],
                            'train_accuracy': float(c['train_accuracy']),
                            'test_accuracy': float(c['test_accuracy']),
                            'overfitting_gap': float(c['overfitting_gap']),
                            'train_macro_f1': float(c['train_macro_f1']),
                            'test_macro_f1': float(c['test_macro_f1']),
                            'test_weighted_f1': float(c['test_weighted_f1']),
                            'macro_f1_gap': float(c['macro_f1_gap']),
                            'selection_score': float(c['selection_score'])
                        }
                        for c in candidate_results
                    ]
                }
                self.last_training_summary = dict(training_summary)
                self.model_source = "trained_runtime"
                return training_summary

            except Exception as e:
                self.logger.error("学習エラー: %s", e, exc_info=True)
                raise

    def predict(self,
                texts: List[str],
                return_proba: bool = False,
                confidence_threshold: float = 0.0,
                top_k: int = 3,
                unknown_on_low_conf: bool = True,
                unknown_intent_label: str = "UNKNOWN") -> List[Dict]:
        """
        予測を実行する（本番向け）。

        Args:
            texts: Texts to predict
            return_proba: Whether to return probabilities
            confidence_threshold: Confidence threshold for warnings

        Returns:
            List of prediction results
        """
        start_time = time.time()

        if self.classifier is None:
            self.logger.error("モデルが読み込まれていません")
            raise IntentServiceError(svc_errors.ERR_MODEL_NOT_LOADED)

        with self.lock:
            try:
                embeddings = self.get_embeddings(texts, use_cache=True)
                predictions = self.classifier.predict(embeddings)

                results = []
                need_proba = return_proba or unknown_on_low_conf
                probas = self.classifier.predict_proba(embeddings) if need_proba else None
                for i, pred in enumerate(predictions):
                    intent = self.reverse_label_encoder[pred]
                    confidence = None
                    low_confidence = False
                    top_k_intents = None
                    proba_dict = None

                    if probas is not None:
                        confidence = float(probas[i][pred])
                        low_confidence = confidence < confidence_threshold
                        if low_confidence:
                            self.logger.warning(
                                "低信頼度の予測: '%s…' -> %s（%.2f%%）",
                                texts[i][:50], intent, confidence * 100
                            )
                            if unknown_on_low_conf:
                                intent = unknown_intent_label

                        if return_proba:
                            proba_dict = {
                                self.reverse_label_encoder[j]: float(prob)
                                for j, prob in enumerate(probas[i])
                            }
                            # 確率の高い順に上位 K 件を返す
                            k = max(1, min(int(top_k), len(probas[i])))
                            sorted_idx = np.argsort(probas[i])[::-1][:k]
                            top_k_intents = [
                                {
                                    'intent': self.reverse_label_encoder[int(j)],
                                    'probability': float(probas[i][int(j)])
                                }
                                for j in sorted_idx
                            ]

                    item = {
                        'text': texts[i],
                        'intent': intent
                    }
                    if confidence is not None:
                        item['confidence'] = confidence
                        item['low_confidence'] = low_confidence
                        item['threshold_applied'] = float(confidence_threshold)
                    if proba_dict is not None:
                        item['all_probabilities'] = proba_dict
                    if top_k_intents is not None:
                        item['top_k_intents'] = top_k_intents
                    results.append(item)

                duration = time.time() - start_time
                if self.monitor:
                    self.monitor.record_prediction(duration)

                self.logger.info("予測完了: %d 件, %.2fs", len(results), duration)
                return results

            except IntentServiceError:
                raise
            except Exception as e:
                self.logger.error("予測エラー: %s", e, exc_info=True)
                if self.monitor:
                    self.monitor.record_error()
                raise

    def save_model(self, filepath: str, include_metadata: bool = True):
        """メタデータ付きでモデルを保存する。"""
        with self.lock:
            if self.classifier is None:
                raise IntentServiceError(svc_errors.ERR_MODEL_NOT_TRAINED)

            self.logger.info("モデル保存: %s", filepath)

            model_data = {
                'classifier': self.classifier,
                'label_encoder': self.label_encoder,
                'reverse_label_encoder': self.reverse_label_encoder,
                'embedding_model_id': self.embedding_model_id,
                'algorithm': self.algorithm_name,
                'model_source': self.model_source,
                'timestamp': datetime.now().isoformat()
            }
            self.model_timestamp = model_data['timestamp']

            if include_metadata:
                model_data['metadata'] = {
                    'performance_stats': self.monitor.get_stats() if self.monitor else None,
                    'cache_stats': self.cache.get_stats() if self.cache else None,
                    'training_summary': self.last_training_summary
                }

            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'wb') as f:
                pickle.dump(model_data, f)

            self.logger.info("モデルを保存しました")

    def load_model(self, filepath: str):
        """ファイルからモデルを読み込む。"""
        with self.lock:
            self.logger.info("モデル読み込み: %s", filepath)

            with open(filepath, 'rb') as f:
                model_data = pickle.load(f)

            self.classifier = model_data['classifier']
            self.label_encoder = model_data['label_encoder']
            self.reverse_label_encoder = model_data['reverse_label_encoder']
            self.embedding_model_id = model_data['embedding_model_id']
            self.algorithm_name = model_data.get('algorithm', 'GradientBoostingClassifier')
            self.model_timestamp = model_data.get('timestamp')
            self.last_training_summary = (
                model_data.get('metadata', {}).get('training_summary')
                if isinstance(model_data.get('metadata'), dict)
                else None
            )
            self.model_source = 'disk_loaded'

            self.logger.info("モデルを読み込みました")
            self.logger.info("  クラス数: %d", len(self.label_encoder))
            self.logger.info("  保存時刻: %s", model_data.get('timestamp', '不明'))

    def get_stats(self) -> Dict:
        """サービス統計を返す。"""
        stats = {}

        if self.monitor:
            stats['performance'] = self.monitor.get_stats()

        if self.cache:
            stats['cache'] = self.cache.get_stats()

        if self.classifier:
            stats['model'] = {
                'algorithm': self.algorithm_name,
                'model_source': self.model_source,
                'model_timestamp': self.model_timestamp,
                'training_summary': self.last_training_summary,
                'num_classes': len(self.label_encoder),
                'classes': list(self.label_encoder.keys()),
                'n_estimators': getattr(self.classifier, 'n_estimators_', 0)
            }

        return stats

    def clear_cache(self):
        """埋め込みキャッシュをクリアする。"""
        if self.cache:
            self.cache.clear()
            self.logger.info("キャッシュをクリアしました")

    def health_check(self) -> Dict:
        """ヘルスチェック。"""
        uptime = time.time() - self._start_time
        health = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'version': '1.0.0',
            'uptime_seconds': round(uptime, 1),
            'model_loaded': self.classifier is not None,
            'cache_enabled': self.enable_cache,
            'monitoring_enabled': self.enable_monitoring
        }

        if self.monitor:
            stats = self.monitor.get_stats()
            health['error_rate'] = stats['error_rate']
            health['total_predictions'] = stats['total_predictions']

            if stats['error_rate'] > 0.05:
                health['status'] = 'warning'
                health['message'] = 'エラー率が高いです'

        if not self.classifier:
            health['status'] = 'degraded'
            health['message'] = 'モデルが読み込まれていません'

        return health


def load_training_data(filepath: str) -> Tuple[List[str], List[str]]:
    """ファイルから学習データを読み込む。"""
    texts = []
    labels = []

    if filepath.endswith('.json'):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for item in data:
                texts.append(item['text'])
                labels.append(item['label'])
    elif filepath.endswith('.jsonl'):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                item = json.loads(line)
                texts.append(item['text'])
                labels.append(item['label'])
    elif filepath.endswith('.csv'):
        import csv
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                texts.append(row['text'])
                labels.append(row['label'])

    return texts, labels
