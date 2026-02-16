#!/usr/bin/env python3
"""
Denpyo Toroku - Production Model Training Script

Trains a GradientBoosting classifier using OCI GenAI embeddings.
Includes data quality validation, early stopping, and model backup.

Usage:
    python scripts/train.py
"""

import sys
import os
import json
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

# Add project root to path (so 'denpyo_toroku' package is importable)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from denpyo_toroku.src.denpyo_toroku.classifier import ProductionIntentClassifier

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('training.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============ Configuration ============
CONFIG = {
    # OCI settings
    'config_path': '~/.oci/config',
    'profile': 'DEFAULT',
    'service_endpoint': 'https://inference.generativeai.us-chicago-1.oci.oraclecloud.com',
    'compartment_id': 'ocid1.compartment.oc1..xxxxx',  # Replace with actual ID

    # Embedding model
    'embedding_model_id': 'cohere.embed-v4.0',

    # Training parameters
    'test_size': 0.15,
    'validation_split': 0.15,
    'random_state': 42,

    # Gradient Boosting parameters
    # NOTE: validation_fraction is controlled by 'validation_split' above.
    # Do NOT duplicate it here - classifier.train() maps validation_split -> validation_fraction.
    'classifier_params': {
        'n_estimators': 300,
        'learning_rate': 0.05,
        'max_depth': 6,
        'min_samples_split': 15,
        'min_samples_leaf': 8,
        'subsample': 0.8,
        'n_iter_no_change': 15,
        'tol': 1e-4
    },

    # File paths
    'training_data': 'training_data.json',
    'model_save_path': 'denpyo_toroku/models/intent_model_production.pkl',
    'log_file': 'denpyo_toroku/log/classifier_training.log'
}


def load_training_data(filepath):
    """Load training data from JSON file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    texts = []
    labels = []
    for item in data:
        texts.append(item['text'])
        labels.append(item['label'])

    return texts, labels


def validate_data_quality(texts, labels):
    """Validate data quality for production training"""
    logger.info("=" * 70)
    logger.info("Validating data quality...")
    logger.info("=" * 70)

    issues = []

    # 1. Minimum sample count per class
    min_samples_per_class = 50
    label_counts = {}
    for label in labels:
        label_counts[label] = label_counts.get(label, 0) + 1

    for label, count in label_counts.items():
        if count < min_samples_per_class:
            issues.append(
                f"Class '{label}' has insufficient samples: {count} "
                f"(recommended: >= {min_samples_per_class})"
            )

    # 2. Empty text check
    empty_texts = sum(1 for t in texts if not t.strip())
    if empty_texts > 0:
        issues.append(f"{empty_texts} empty texts found")

    # 3. Duplicate check
    unique_texts = len(set(texts))
    if unique_texts < len(texts):
        duplicates = len(texts) - unique_texts
        issues.append(f"{duplicates} duplicate texts found")

    # 4. Class imbalance check
    max_count = max(label_counts.values())
    min_count = min(label_counts.values())
    imbalance_ratio = max_count / min_count
    if imbalance_ratio > 5:
        issues.append(f"Severe class imbalance (ratio: {imbalance_ratio:.1f}:1)")

    # Report
    if issues:
        logger.warning("Data quality issues detected:")
        for issue in issues:
            logger.warning(f"  - {issue}")

        response = input("\nContinue anyway? (y/n): ")
        if response.lower() != 'y':
            logger.info("Training cancelled")
            return False
    else:
        logger.info("Data quality check passed (no issues)")

    return True


def create_model_backup(model_path):
    """Backup existing model file"""
    if os.path.exists(model_path):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{model_path}.backup_{timestamp}"
        os.rename(model_path, backup_path)
        logger.info(f"Backed up existing model to: {backup_path}")


def main():
    """Main training procedure"""
    logger.info("=" * 70)
    logger.info("Production Model Training")
    logger.info("Start time: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    logger.info("=" * 70)

    # Create directories
    os.makedirs(os.path.dirname(CONFIG['model_save_path']), exist_ok=True)
    os.makedirs(os.path.dirname(CONFIG['log_file']), exist_ok=True)

    # Step 1: Load data
    logger.info("\n[Step 1] Loading training data...")
    try:
        texts, labels = load_training_data(CONFIG['training_data'])
        logger.info(f"Loaded {len(texts)} samples")
    except FileNotFoundError:
        logger.error(f"Data file not found: {CONFIG['training_data']}")
        return
    except Exception as e:
        logger.error(f"Data loading error: {e}", exc_info=True)
        return

    # Show class distribution
    logger.info("\nClass distribution:")
    label_counts = {}
    for label in labels:
        label_counts[label] = label_counts.get(label, 0) + 1

    for label, count in sorted(label_counts.items(), key=lambda x: x[1], reverse=True):
        percentage = count / len(labels) * 100
        logger.info(f"  {label:20s} {count:4d} ({percentage:5.1f}%)")

    # Step 2: Validate data quality
    logger.info("\n[Step 2] Validating data quality...")
    if not validate_data_quality(texts, labels):
        return

    # Step 3: Initialize classifier
    logger.info("\n[Step 3] Initializing production classifier...")
    try:
        classifier = ProductionIntentClassifier(
            config_path=CONFIG['config_path'],
            profile=CONFIG['profile'],
            service_endpoint=CONFIG['service_endpoint'],
            compartment_id=CONFIG['compartment_id'],
            embedding_model_id=CONFIG['embedding_model_id'],
            log_file=CONFIG['log_file'],
            log_level='INFO',
            enable_cache=False,
            enable_monitoring=True
        )
    except Exception as e:
        logger.error(f"Initialization error: {e}", exc_info=True)
        return

    # Step 4: Train model
    logger.info("\n[Step 4] Training model (Early Stopping enabled)...")
    try:
        results = classifier.train(
            texts=texts,
            labels=labels,
            test_size=CONFIG['test_size'],
            random_state=CONFIG['random_state'],
            validation_split=CONFIG['validation_split'],
            early_stopping_rounds=CONFIG['classifier_params'].get('n_iter_no_change', 15),
            **CONFIG['classifier_params']
        )
    except Exception as e:
        logger.error(f"Training error: {e}", exc_info=True)
        return

    # Step 5: Evaluate results
    logger.info("\n[Step 5] Evaluating results...")

    min_test_accuracy = 0.85
    max_overfitting_gap = 0.10
    quality_ok = True

    if results['test_accuracy'] < min_test_accuracy:
        logger.warning(f"Test accuracy below threshold: {results['test_accuracy']:.4f} < {min_test_accuracy}")
        quality_ok = False

    if results['overfitting_gap'] > max_overfitting_gap:
        logger.warning(f"Possible overfitting: gap {results['overfitting_gap']:.4f} > {max_overfitting_gap}")
        quality_ok = False

    if quality_ok:
        logger.info("Model quality meets production standards")
    else:
        logger.warning("Model quality below production standards")
        response = input("\nSave this model anyway? (y/n): ")
        if response.lower() != 'y':
            logger.info("Model not saved")
            return

    # Step 6: Save model
    logger.info("\n[Step 6] Saving model...")
    create_model_backup(CONFIG['model_save_path'])

    try:
        classifier.save_model(CONFIG['model_save_path'], include_metadata=True)
    except Exception as e:
        logger.error(f"Model save error: {e}", exc_info=True)
        return

    # Step 7: Summary
    logger.info("\n" + "=" * 70)
    logger.info("Production Model Training Complete")
    logger.info("=" * 70)
    logger.info(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"\nModel Info:")
    logger.info(f"  Algorithm: Gradient Boosting Classifier")
    logger.info(f"  Train Accuracy: {results['train_accuracy']:.4f} ({results['train_accuracy']*100:.2f}%)")
    logger.info(f"  Test Accuracy: {results['test_accuracy']:.4f} ({results['test_accuracy']*100:.2f}%)")
    logger.info(f"  Overfitting Gap: {results['overfitting_gap']:.4f}")
    logger.info(f"  Classes: {results['num_classes']}")
    logger.info(f"  Estimators Used: {results['n_estimators_used']}")
    logger.info(f"  Train Samples: {results['train_samples']}")
    logger.info(f"  Test Samples: {results['test_samples']}")
    logger.info(f"\nFiles:")
    logger.info(f"  Model: {CONFIG['model_save_path']}")
    logger.info(f"  Log: {CONFIG['log_file']}")
    logger.info("=" * 70)

    logger.info("\nReady for production deployment")
    logger.info("\nNext steps:")
    logger.info("  1. Review docker-compose.yml configuration")
    logger.info("  2. Run ./deploy.sh start to start the service")
    logger.info("  3. Open http://localhost:8080 to access the UI")


if __name__ == "__main__":
    main()
