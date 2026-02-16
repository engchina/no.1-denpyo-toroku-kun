#!/usr/bin/env python3
"""
Intent Classifier Service - Production Test Suite

Includes unit tests, integration tests, and performance tests.
Requires a running service instance.

Usage:
    pytest scripts/test_production.py -v
    python scripts/test_production.py
"""

import pytest
import requests
import time
import json
from concurrent.futures import ThreadPoolExecutor
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
API_BASE_URL = "http://localhost:8080/api/v1"
TEST_TIMEOUT = 30


class TestHealthCheck:
    """Health check endpoint tests"""

    def test_health_endpoint(self):
        """Health endpoint returns 200 with status"""
        response = requests.get(f"{API_BASE_URL}/health", timeout=TEST_TIMEOUT)
        assert response.status_code == 200

        data = response.json()
        result = data.get('data', data)
        assert result['status'] in ['healthy', 'warning', 'degraded']

    def test_version_endpoint(self):
        """Version endpoint returns version info"""
        response = requests.get(f"{API_BASE_URL}/version", timeout=TEST_TIMEOUT)
        assert response.status_code == 200

        data = response.json()
        result = data.get('data', data)
        assert 'version' in result
        assert 'service' in result


class TestPrediction:
    """Prediction endpoint tests"""

    def test_single_prediction(self):
        """Single text prediction returns valid result"""
        response = requests.post(
            f"{API_BASE_URL}/predict/single",
            params={
                'text': '注文の配送状況を確認したい',
                'return_proba': True
            },
            timeout=TEST_TIMEOUT
        )
        assert response.status_code == 200

        data = response.json()
        result = data.get('data', data)
        assert 'text' in result
        assert 'intent' in result
        assert 'confidence' in result
        assert 0 <= result['confidence'] <= 1

    def test_batch_prediction(self):
        """Batch prediction processes multiple texts"""
        test_texts = [
            "商品を返品したい",
            "配送料はいくらですか",
            "クーポンコードを使いたい"
        ]

        response = requests.post(
            f"{API_BASE_URL}/predict",
            json={
                'texts': test_texts,
                'return_proba': True,
                'confidence_threshold': 0.5
            },
            timeout=TEST_TIMEOUT
        )
        assert response.status_code == 200

        data = response.json()
        result = data.get('data', data)
        assert result['total'] == len(test_texts)
        assert len(result['results']) == len(test_texts)
        assert 'processing_time' in result

        for pred in result['results']:
            assert 'intent' in pred
            assert 'confidence' in pred

    def test_empty_text(self):
        """Empty text returns error or handles gracefully"""
        response = requests.post(
            f"{API_BASE_URL}/predict",
            json={'texts': ['']},
            timeout=TEST_TIMEOUT
        )
        assert response.status_code in [200, 400, 500]

    def test_large_batch(self):
        """Large batch (100 texts) processes correctly"""
        test_texts = [f"テストテキスト{i}" for i in range(100)]

        response = requests.post(
            f"{API_BASE_URL}/predict",
            json={'texts': test_texts},
            timeout=60
        )
        assert response.status_code == 200

        data = response.json()
        result = data.get('data', data)
        assert result['total'] == 100


class TestModelInfo:
    """Model info endpoint tests"""

    def test_model_info(self):
        """Model info returns required fields"""
        response = requests.get(f"{API_BASE_URL}/model/info", timeout=TEST_TIMEOUT)
        assert response.status_code == 200

        data = response.json()
        result = data.get('data', data)
        assert 'classes' in result
        assert 'num_classes' in result
        assert 'embedding_model' in result
        assert len(result['classes']) == result['num_classes']


class TestStats:
    """Statistics endpoint tests"""

    def test_stats_endpoint(self):
        """Stats endpoint returns statistics data"""
        response = requests.get(f"{API_BASE_URL}/stats", timeout=TEST_TIMEOUT)
        assert response.status_code == 200

        data = response.json()
        result = data.get('data', data)
        if 'performance' in result:
            assert 'total_predictions' in result['performance']


class TestPerformance:
    """Performance tests"""

    def test_response_time(self):
        """Single prediction responds within 5 seconds"""
        max_response_time = 5.0

        start_time = time.time()
        response = requests.post(
            f"{API_BASE_URL}/predict/single",
            params={'text': 'テストテキスト'},
            timeout=TEST_TIMEOUT
        )
        duration = time.time() - start_time

        assert response.status_code == 200
        assert duration < max_response_time, f"Response too slow: {duration:.2f}s"

    def test_concurrent_requests(self):
        """Service handles 10 concurrent requests"""
        num_requests = 10

        def make_request(_):
            response = requests.post(
                f"{API_BASE_URL}/predict/single",
                params={'text': 'テスト'},
                timeout=TEST_TIMEOUT
            )
            return response.status_code == 200

        with ThreadPoolExecutor(max_workers=num_requests) as executor:
            results = list(executor.map(make_request, range(num_requests)))

        assert all(results), "Some concurrent requests failed"


class TestCacheManagement:
    """Cache management tests"""

    def test_cache_clear(self):
        """Cache clear endpoint works"""
        response = requests.post(f"{API_BASE_URL}/cache/clear", timeout=TEST_TIMEOUT)
        assert response.status_code == 200

        data = response.json()
        result = data.get('data', data)
        assert 'message' in result


class TestErrorHandling:
    """Error handling tests"""

    def test_invalid_endpoint(self):
        """Non-existent endpoint returns 404"""
        response = requests.get(f"{API_BASE_URL}/nonexistent", timeout=TEST_TIMEOUT)
        assert response.status_code == 404

    def test_invalid_json(self):
        """Invalid JSON body returns error"""
        response = requests.post(
            f"{API_BASE_URL}/predict",
            data="not json",
            headers={'Content-Type': 'application/json'},
            timeout=TEST_TIMEOUT
        )
        assert response.status_code in [400, 500]


# Load test (manual execution)
class TestLoadTest:
    """Load tests (optional, skip by default)"""

    @pytest.mark.skip(reason="Manual execution only")
    def test_sustained_load(self):
        """Service handles sustained load for 60 seconds"""
        duration = 60
        requests_per_second = 10

        start_time = time.time()
        successful = 0
        failed = 0

        while time.time() - start_time < duration:
            try:
                response = requests.post(
                    f"{API_BASE_URL}/predict/single",
                    params={'text': '負荷テスト'},
                    timeout=5
                )
                if response.status_code == 200:
                    successful += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

            time.sleep(1 / requests_per_second)

        logger.info(f"Success: {successful}, Failed: {failed}")
        assert failed / (successful + failed) < 0.05  # <5% error rate


def run_tests():
    """Run all tests"""
    logger.info("=" * 70)
    logger.info("Running production tests")
    logger.info("=" * 70)

    pytest.main([
        __file__,
        '-v',
        '--tb=short',
        '--color=yes'
    ])


if __name__ == "__main__":
    run_tests()
