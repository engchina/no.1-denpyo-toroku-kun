"""伝票登録サービスの性能監視モジュール。"""

import numpy as np
import threading
from collections import deque
from typing import Dict


class PerformanceMonitor:
    """予測メトリクスを追跡する性能監視クラス。"""

    def __init__(self, max_history: int = 1000):
        self.prediction_times = deque(maxlen=max_history)
        self.embedding_times = deque(maxlen=max_history)
        self.total_predictions = 0
        self.total_errors = 0
        self.lock = threading.Lock()

    def record_prediction(self, duration: float):
        """予測時間を記録する。"""
        with self.lock:
            self.prediction_times.append(duration)
            self.total_predictions += 1

    def record_embedding(self, duration: float):
        """埋め込み取得時間を記録する。"""
        with self.lock:
            self.embedding_times.append(duration)

    def record_error(self):
        """エラーの発生を記録する。"""
        with self.lock:
            self.total_errors += 1

    def get_stats(self) -> Dict:
        """性能統計を取得する。"""
        with self.lock:
            if not self.prediction_times:
                return {
                    'total_predictions': self.total_predictions,
                    'total_errors': self.total_errors,
                    'avg_prediction_time': 0,
                    'max_prediction_time': 0,
                    'min_prediction_time': 0,
                    'avg_embedding_time': 0,
                    'error_rate': 0,
                    'p95_prediction_time': 0,
                    'p99_prediction_time': 0
                }

            return {
                'total_predictions': self.total_predictions,
                'total_errors': self.total_errors,
                'avg_prediction_time': float(np.mean(self.prediction_times)),
                'max_prediction_time': float(np.max(self.prediction_times)),
                'min_prediction_time': float(np.min(self.prediction_times)),
                'avg_embedding_time': float(np.mean(self.embedding_times)) if self.embedding_times else 0,
                'error_rate': self.total_errors / max(self.total_predictions, 1),
                'p95_prediction_time': float(np.percentile(self.prediction_times, 95)) if len(self.prediction_times) > 1 else 0,
                'p99_prediction_time': float(np.percentile(self.prediction_times, 99)) if len(self.prediction_times) > 1 else 0
            }
