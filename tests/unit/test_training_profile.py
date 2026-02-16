from denpyo_toroku.app.blueprints.api.api_blueprint import (
    _sanitize_training_items,
    _build_training_profile,
    _build_model_comparison,
)


def test_sanitize_training_items_rejects_invalid_rows():
    raw = [
        {"text": "hello", "label": "greet"},
        {"text": "", "label": "greet"},
        {"label": "missing_text"},
        {"text": "missing label"},
        "invalid-type",
        {"text": "  bye  ", "label": "  close  "},
    ]

    accepted, stats = _sanitize_training_items(raw)

    assert accepted == [
        {"text": "hello", "label": "greet"},
        {"text": "bye", "label": "close"},
    ]
    assert stats["empty_text_count"] == 1
    assert stats["missing_field_count"] == 2
    assert stats["invalid_item_count"] == 1


def test_training_profile_detects_quality_gate_blockers():
    data = [
        {"text": "hi", "label": "greet"},
        {"text": "hello", "label": "greet"},
        {"text": "bye", "label": "farewell"},
        {"text": "see you", "label": "farewell"},
        {"text": "need help", "label": "support"},
    ]

    profile = _build_training_profile(data)

    assert profile["quality_gate_passed"] is False
    assert profile["total_samples"] == 5
    assert profile["num_classes"] == 3
    assert sum(1 for item in profile["issue_details"] if item["level"] == "error") >= 2


def test_training_profile_recommends_rebalance_for_imbalance():
    data = []
    for i in range(30):
        data.append({"text": f"major sample {i}", "label": "major"})
    for i in range(4):
        data.append({"text": f"minor sample {i}", "label": "minor"})

    profile = _build_training_profile(data)

    assert profile["imbalance_ratio"] >= 7
    assert profile["suggested_params"]["rebalance_strategy"] == "balanced_upsample"
    assert profile["health_score"] < 90
    assert profile["quality_gate_passed"] is True


def test_training_profile_reports_healthy_dataset():
    data = []
    intents = ["greet", "farewell", "support", "billing"]
    for intent in intents:
        for i in range(35):
            data.append({"text": f"{intent} sample sentence {i}", "label": intent})

    profile = _build_training_profile(data)

    assert profile["quality_gate_passed"] is True
    assert profile["readiness"] in ("high", "medium")
    assert profile["num_classes"] == 4
    assert profile["total_samples"] == 140
    assert profile["suggested_params"]["test_size"] >= 0.05
    assert profile["suggested_params"]["test_size"] <= 0.40


def test_model_comparison_reports_improvement():
    previous = {
        "test_accuracy": 0.88,
        "test_macro_f1": 0.83,
        "overfitting_gap": 0.09,
        "selection_score": 0.80,
    }
    current = {
        "test_accuracy": 0.90,
        "test_macro_f1": 0.86,
        "overfitting_gap": 0.07,
        "selection_score": 0.84,
    }

    comparison = _build_model_comparison(previous, current)

    assert comparison is not None
    assert comparison["improved"] is True
    assert comparison["test_accuracy_delta"] > 0
    assert comparison["test_macro_f1_delta"] > 0
    assert comparison["overfitting_gap_delta"] < 0


def test_model_comparison_handles_missing_previous():
    current = {
        "test_accuracy": 0.90,
        "test_macro_f1": 0.86,
        "overfitting_gap": 0.07,
        "selection_score": 0.84,
    }
    assert _build_model_comparison(None, current) is None
