import numpy as np

from denpyo_toroku.src.denpyo_toroku.cache import EmbeddingCache


def test_cache_get_set_and_hit_miss_stats():
    cache = EmbeddingCache(max_size=2)

    assert cache.get("missing") is None

    v1 = np.array([1.0, 2.0, 3.0])
    cache.set("hello", v1)

    got = cache.get("hello")
    assert got is not None
    assert np.array_equal(got, v1)

    stats = cache.get_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["cache_size"] == 1
    assert stats["max_size"] == 2


def test_cache_lru_eviction():
    cache = EmbeddingCache(max_size=2)

    cache.set("a", np.array([1]))
    cache.set("b", np.array([2]))
    assert cache.get("a") is not None  # mark a as recently used

    cache.set("c", np.array([3]))  # should evict b

    assert cache.get("b") is None
    assert cache.get("a") is not None
    assert cache.get("c") is not None


def test_cache_clear_resets_stats_and_entries():
    cache = EmbeddingCache(max_size=2)

    cache.set("x", np.array([9]))
    _ = cache.get("x")
    _ = cache.get("y")

    cache.clear()

    stats = cache.get_stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["cache_size"] == 0
