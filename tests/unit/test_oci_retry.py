from denpyo_toroku.src.denpyo_toroku.classifier import retry_on_failure


class FakeOCIError(Exception):
    def __init__(self, message: str, status: int | None = None, headers: dict | None = None):
        super().__init__(message)
        self.status = status
        self.headers = headers or {}


def test_retry_on_429_uses_exponential_backoff(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)

    attempts = {"count": 0}

    @retry_on_failure(max_retries=3, delay=0.5, jitter_ratio=0.0)
    def flaky_call():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise FakeOCIError("Too Many Requests", status=429)
        return "ok"

    assert flaky_call() == "ok"
    assert attempts["count"] == 3
    assert sleep_calls == [0.5, 1.0]


def test_retry_on_429_honors_retry_after_header(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)

    attempts = {"count": 0}

    @retry_on_failure(max_retries=2, delay=0.5, jitter_ratio=0.0)
    def throttled_call():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise FakeOCIError("Too Many Requests", status=429, headers={"Retry-After": "3"})
        return "ok"

    assert throttled_call() == "ok"
    assert sleep_calls == [3.0]


def test_do_not_retry_on_non_retryable_error(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleep_calls.append(seconds))

    attempts = {"count": 0}

    @retry_on_failure(max_retries=3, delay=0.5, jitter_ratio=0.0)
    def bad_request_call():
        attempts["count"] += 1
        raise FakeOCIError("Bad Request", status=400)

    try:
        bad_request_call()
        assert False, "Expected FakeOCIError"
    except FakeOCIError:
        pass

    assert attempts["count"] == 1
    assert sleep_calls == []
