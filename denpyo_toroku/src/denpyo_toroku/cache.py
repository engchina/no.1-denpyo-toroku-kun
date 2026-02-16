"""意図分類サービスの埋め込みキャッシュモジュール。"""

import hashlib
import threading
import numpy as np
from collections import OrderedDict
from typing import Dict, Optional


class EmbeddingCache:
    """本番環境向けのスレッドセーフな LRU 埋め込みキャッシュ。"""

    def __init__(self, max_size: int = 10000):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
        self.lock = threading.Lock()

    def _hash_text(self, text: str) -> str:
        """テキストのハッシュ値を生成する。"""
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    def get(self, text: str) -> Optional[np.ndarray]:
        """キャッシュから埋め込みを取得する（LRU のため末尾に移動）。"""
        with self.lock:
            key = self._hash_text(text)
            if key in self.cache:
                self.hits += 1
                self.cache.move_to_end(key)  # 最近使用したとしてマーク
                return self.cache[key]
            else:
                self.misses += 1
                return None

    def set(self, text: str, embedding: np.ndarray):
        """LRU 退避付きで埋め込みをキャッシュに保存する。"""
        with self.lock:
            key = self._hash_text(text)
            if key in self.cache:
                self.cache.move_to_end(key)
                self.cache[key] = embedding
            else:
                if len(self.cache) >= self.max_size:
                    self.cache.popitem(last=False)  # LRU（最古）を削除
                self.cache[key] = embedding

    def get_stats(self) -> Dict:
        """キャッシュ統計を取得する。"""
        with self.lock:
            total = self.hits + self.misses
            return {
                'hits': self.hits,
                'misses': self.misses,
                'hit_rate': self.hits / total if total > 0 else 0,
                'cache_size': len(self.cache),
                'max_size': self.max_size
            }

    def clear(self):
        """キャッシュをクリアする。"""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0
