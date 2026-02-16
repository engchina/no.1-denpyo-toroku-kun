from denpyo_toroku.src.denpyo_toroku.monitor import PerformanceMonitor


def test_monitor_empty_stats_shape():
    monitor = PerformanceMonitor()

    stats = monitor.get_stats()

    assert stats["total_predictions"] == 0
    assert stats["total_errors"] == 0
    assert stats["avg_prediction_time"] == 0
    assert stats["p95_prediction_time"] == 0
    assert stats["p99_prediction_time"] == 0


def test_monitor_records_prediction_embedding_and_errors():
    monitor = PerformanceMonitor(max_history=10)

    monitor.record_prediction(0.1)
    monitor.record_prediction(0.3)
    monitor.record_embedding(0.05)
    monitor.record_error()

    stats = monitor.get_stats()

    assert stats["total_predictions"] == 2
    assert stats["total_errors"] == 1
    assert stats["avg_prediction_time"] > 0
    assert stats["max_prediction_time"] >= stats["min_prediction_time"]
    assert stats["avg_embedding_time"] == 0.05
    assert stats["error_rate"] == 0.5
    assert stats["p95_prediction_time"] > 0
    assert stats["p99_prediction_time"] > 0


def test_monitor_respects_history_limit():
    monitor = PerformanceMonitor(max_history=2)

    monitor.record_prediction(1.0)
    monitor.record_prediction(2.0)
    monitor.record_prediction(3.0)

    stats = monitor.get_stats()

    # with max_history=2, only [2.0, 3.0] contribute to metrics
    assert abs(stats["avg_prediction_time"] - 2.5) < 1e-9
    assert stats["min_prediction_time"] == 2.0
    assert stats["max_prediction_time"] == 3.0
