#!/usr/bin/env python3
"""
Intent Classifier API - Client Example

Demonstrates usage of the Intent Classifier Service REST API.
Adapted to use the Flask-based service with /api/v1/ prefix.

Usage:
    python scripts/client_example.py
"""

import requests
import json
from typing import List, Dict, Optional
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class IntentClassifierClient:
    """
    Intent Classifier API Client

    Usage:
        client = IntentClassifierClient("http://localhost:8080")
        result = client.predict_single("注文状況を確認したい")
        print(result['intent'])
    """

    def __init__(self, base_url: str = "http://localhost:8080", timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.api_prefix = f"{self.base_url}/api/v1"
        self.timeout = timeout
        self.session = requests.Session()

        # Health check on init
        try:
            health = self.health_check()
            status = health.get('status', health.get('data', {}).get('status', 'unknown'))
            if status != 'healthy':
                logger.warning(f"API status is not healthy: {status}")
        except Exception as e:
            logger.error(f"Cannot connect to API: {e}")
            raise

    def health_check(self) -> Dict:
        """Check service health"""
        response = self.session.get(
            f"{self.api_prefix}/health",
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get('data', data)

    def predict_single(self, text: str, return_proba: bool = True) -> Dict:
        """Predict intent for a single text"""
        response = self.session.post(
            f"{self.api_prefix}/predict/single",
            params={
                'text': text,
                'return_proba': return_proba
            },
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get('data', data)

    def predict_batch(self, texts: List[str],
                      return_proba: bool = True,
                      confidence_threshold: float = 0.5) -> Dict:
        """Predict intents for multiple texts"""
        response = self.session.post(
            f"{self.api_prefix}/predict",
            json={
                'texts': texts,
                'return_proba': return_proba,
                'confidence_threshold': confidence_threshold
            },
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get('data', data)

    def get_model_info(self) -> Dict:
        """Get model metadata"""
        response = self.session.get(
            f"{self.api_prefix}/model/info",
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get('data', data)

    def get_stats(self) -> Dict:
        """Get service statistics"""
        response = self.session.get(
            f"{self.api_prefix}/stats",
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get('data', data)

    def clear_cache(self) -> Dict:
        """Clear embedding cache"""
        response = self.session.post(
            f"{self.api_prefix}/cache/clear",
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get('data', data)


# ============ Usage Examples ============

def example_single_prediction():
    """Example 1: Single text prediction"""
    print("=" * 70)
    print("Example 1: Single Text Prediction")
    print("=" * 70)

    client = IntentClassifierClient()

    text = "商品を返品したいのですが"
    result = client.predict_single(text, return_proba=True)

    print(f"\nInput: {result['text']}")
    print(f"Intent: {result['intent']}")
    print(f"Confidence: {result['confidence']:.2%}")
    if 'all_probabilities' in result:
        print(f"\nTop probabilities:")
        for intent, prob in sorted(result['all_probabilities'].items(),
                                   key=lambda x: x[1], reverse=True)[:5]:
            print(f"  {intent}: {prob:.2%}")


def example_batch_prediction():
    """Example 2: Batch prediction"""
    print("\n" + "=" * 70)
    print("Example 2: Batch Prediction")
    print("=" * 70)

    client = IntentClassifierClient()

    texts = [
        "注文の配送状況を教えてください",
        "クーポンコードを使いたい",
        "支払いができません",
        "商品の在庫はありますか",
        "領収書を発行してください"
    ]

    result = client.predict_batch(texts, return_proba=True)

    print(f"\nResults: {result['total']} texts")
    print(f"Processing time: {result['processing_time']:.2f}s")
    print(f"\nDetails:")

    for i, pred in enumerate(result['results'], 1):
        print(f"\n{i}. Text: {pred['text']}")
        print(f"   Intent: {pred['intent']} (confidence: {pred['confidence']:.2%})")


def example_model_info():
    """Example 3: Model information"""
    print("\n" + "=" * 70)
    print("Example 3: Model Information")
    print("=" * 70)

    client = IntentClassifierClient()

    info = client.get_model_info()

    print(f"\nModel Info:")
    print(f"  Algorithm: {info.get('algorithm', '-')}")
    print(f"  Classes: {info.get('num_classes', 0)}")
    print(f"  Estimators: {info.get('n_estimators', 0)}")
    print(f"  Embedding Model: {info.get('embedding_model', '-')}")
    if info.get('classes'):
        print(f"\nClasses:")
        for cls in info['classes']:
            print(f"  - {cls}")


def example_stats():
    """Example 4: Statistics"""
    print("\n" + "=" * 70)
    print("Example 4: Statistics")
    print("=" * 70)

    client = IntentClassifierClient()

    stats = client.get_stats()

    if 'performance' in stats:
        perf = stats['performance']
        print(f"\nPerformance:")
        print(f"  Total Predictions: {perf.get('total_predictions', 0)}")
        print(f"  Total Errors: {perf.get('total_errors', 0)}")
        print(f"  Error Rate: {perf.get('error_rate', 0):.2%}")
        print(f"  Avg Prediction Time: {perf.get('avg_prediction_time', 0):.3f}s")
        print(f"  P95 Prediction Time: {perf.get('p95_prediction_time', 0):.3f}s")

    if 'cache' in stats:
        cache = stats['cache']
        print(f"\nCache:")
        print(f"  Hits: {cache.get('hits', 0)}")
        print(f"  Misses: {cache.get('misses', 0)}")
        print(f"  Hit Rate: {cache.get('hit_rate', 0):.2%}")
        print(f"  Size: {cache.get('cache_size', 0)}/{cache.get('max_size', 0)}")


def example_error_handling():
    """Example 5: Error handling"""
    print("\n" + "=" * 70)
    print("Example 5: Error Handling")
    print("=" * 70)

    client = IntentClassifierClient()

    try:
        result = client.predict_single("")
        print("Prediction succeeded (empty text was accepted)")
    except requests.exceptions.HTTPError as e:
        print(f"Expected error: {e}")
        print("Empty text is not allowed")
    except Exception as e:
        print(f"Unexpected error: {e}")


def example_production_usage():
    """Example 6: Production usage pattern"""
    print("\n" + "=" * 70)
    print("Example 6: Production Usage Pattern")
    print("=" * 70)

    client = IntentClassifierClient()

    user_messages = [
        "こんにちは、注文状況を確認したいです",
        "商品が届かないので返金してください",
        "カスタマーサポートに連絡したい"
    ]

    print("\nProcessing user messages:")
    for msg in user_messages:
        try:
            result = client.predict_single(msg, return_proba=True)

            if result['confidence'] < 0.7:
                print(f"\n  Low confidence: {msg}")
                print(f"  -> Escalate to human operator")
            else:
                print(f"\n  High confidence: {msg}")
                print(f"  -> Intent: {result['intent']} ({result['confidence']:.2%})")
                print(f"  -> Process automatically")

        except Exception as e:
            print(f"\n  Error: {msg}")
            print(f"  -> {e}")
            print(f"  -> Fallback processing")


def main():
    """Run all examples"""
    print("=" * 70)
    print("Intent Classifier API - Client Examples")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    try:
        example_single_prediction()
        example_batch_prediction()
        example_model_info()
        example_stats()
        example_error_handling()
        example_production_usage()

        print("\n" + "=" * 70)
        print("All examples completed successfully")
        print("=" * 70)

    except Exception as e:
        print(f"\nError occurred: {e}")
        print("Make sure the service is running:")
        print("  ./deploy.sh start")
        print("  or")
        print("  ./manage.sh start")


if __name__ == "__main__":
    main()
