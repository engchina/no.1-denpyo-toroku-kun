/**
 * Classifier-related type definitions
 */

export interface HealthData {
  status: string;
  model_loaded: boolean;
  version: string;
  cache_enabled: boolean;
  monitoring_enabled: boolean;
  uptime_seconds: number;
  timestamp?: string;
  message?: string;
  error_rate?: number;
  total_predictions?: number;
}

export interface PerformanceStats {
  total_predictions: number;
  total_errors: number;
  error_rate: number;
  avg_prediction_time: number;
  p95_prediction_time: number;
  p99_prediction_time: number;
  min_prediction_time: number;
  max_prediction_time: number;
  avg_embedding_time: number;
}

export interface CacheStats {
  hits: number;
  misses: number;
  hit_rate: number;
  cache_size: number;
  max_size: number;
}

export interface StatsData {
  performance: PerformanceStats;
  cache: CacheStats;
  model: ModelInfo | null;
  message?: string;
}

export interface ModelInfo {
  classes: string[];
  num_classes: number;
  embedding_model: string;
  algorithm: string;
  n_estimators: number;
  embedding_dimension: number;
  model_source?: string;
  model_timestamp?: string | null;
  training_summary?: {
    train_accuracy?: number;
    test_accuracy?: number;
    overfitting_gap?: number;
    requested_algorithm?: string;
    selected_algorithm?: string;
    candidates?: Array<{
      algorithm: string;
      train_accuracy: number;
      test_accuracy: number;
      overfitting_gap: number;
    }>;
  } | null;
  model_loaded?: boolean;
  message?: string;
}

export interface PredictionResult {
  text: string;
  intent: string;
  confidence?: number;
  low_confidence?: boolean;
  threshold_applied?: number;
  top_k_intents?: Array<{ intent: string; probability: number }>;
  all_probabilities?: Record<string, number>;
}

export interface BatchPredictionResponse {
  results: PredictionResult[];
  total: number;
  processing_time: number;
}

export interface TrainingState {
  status: 'idle' | 'running' | 'completed' | 'failed';
  progress: string;
  results: TrainingResults | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  dataset_profile?: TrainingProfile;
  params?: Partial<TrainingParams>;
  previous_model_summary?: PreviousModelSummary | null;
}

export interface TrainingResults {
  train_accuracy: number;
  test_accuracy: number;
  overfitting_gap: number;
  train_macro_f1?: number;
  test_macro_f1?: number;
  test_weighted_f1?: number;
  macro_f1_gap?: number;
  selection_score?: number;
  selected_algorithm?: string;
  requested_algorithm?: string;
  params_used?: Partial<TrainingParams>;
  candidates?: Array<{
    algorithm: string;
    train_accuracy: number;
    test_accuracy: number;
    overfitting_gap: number;
    train_macro_f1?: number;
    test_macro_f1?: number;
    test_weighted_f1?: number;
    macro_f1_gap?: number;
    selection_score?: number;
  }>;
  per_class_metrics?: Array<{
    intent: string;
    precision: number;
    recall: number;
    f1_score: number;
    support: number;
  }>;
  num_classes: number;
  train_samples: number;
  test_samples: number;
  n_estimators_used: number;
  training_duration_seconds?: number;
  dataset_profile?: TrainingProfile;
  recommendations?: string[];
  previous_model_summary?: PreviousModelSummary | null;
  comparison_with_previous?: ModelComparison | null;
  quality_ok: boolean;
  quality_issues: string[];
  model_path: string;
}

export interface TrainingDataItem {
  text: string;
  label: string;
}

export interface TrainingParams {
  test_size: number;
  n_estimators: number;
  learning_rate: number;
  max_depth: number;
  algorithm_strategy?: 'auto' | 'gbdt' | 'lr';
  compare_baselines?: boolean;
  auto_tune?: boolean;
  rebalance_strategy?: 'none' | 'balanced_upsample' | 'auto';
  random_state?: number;
}

export interface TrainingProfileIssue {
  level: 'error' | 'warning' | 'info';
  message: string;
}

export interface TrainingProfile {
  total_samples: number;
  num_classes: number;
  class_distribution: Record<string, number>;
  class_distribution_percent?: Record<string, number>;
  min_class_count: number;
  max_class_count: number;
  imbalance_ratio: number;
  duplicate_count: number;
  duplicate_ratio: number;
  short_text_count?: number;
  long_text_count?: number;
  text_length_stats?: {
    avg: number;
    median: number;
    p95: number;
    min: number;
    max: number;
  };
  health_score: number;
  readiness: 'high' | 'medium' | 'low';
  quality_gate_passed: boolean;
  issue_details: TrainingProfileIssue[];
  issues: string[];
  recommendations: string[];
  suggested_params: Partial<TrainingParams>;
  rejected?: {
    invalid_item_count: number;
    missing_field_count: number;
    empty_text_count: number;
    empty_label_count: number;
  };
  source?: 'request_payload' | 'in_memory_store';
}

export interface PreviousModelSummary {
  algorithm?: string | null;
  model_timestamp?: string | null;
  test_accuracy?: number | null;
  test_macro_f1?: number | null;
  test_weighted_f1?: number | null;
  overfitting_gap?: number | null;
  selection_score?: number | null;
}

export interface ModelComparison {
  improved: boolean | null;
  summary: string;
  test_accuracy_delta?: number | null;
  test_macro_f1_delta?: number | null;
  overfitting_gap_delta?: number | null;
  selection_score_delta?: number | null;
}

export interface ValidationResult {
  valid: boolean;
  total_samples: number;
  num_classes: number;
  class_distribution: Record<string, number>;
  issues: string[];
  issue_levels?: {
    errors: string[];
    warnings: string[];
    info: string[];
  };
  health_score?: number;
  readiness?: 'high' | 'medium' | 'low';
  imbalance_ratio?: number;
  duplicate_ratio?: number;
  text_length_stats?: {
    avg: number;
    median: number;
    p95: number;
    min: number;
    max: number;
  };
  recommendations?: string[];
  suggested_params?: Partial<TrainingParams>;
  rejected?: {
    invalid_item_count: number;
    missing_field_count: number;
    empty_text_count: number;
    empty_label_count: number;
  };
}

export interface ApiResponse<T> {
  data?: T;
  errorMessages?: string[];
  warningMessages?: string[];
}

export interface ClassifierSliceState {
  health: HealthData | null;
  stats: StatsData | null;
  modelInfo: ModelInfo | null;
  trainingState: TrainingState;
  isHealthLoading: boolean;
  isStatsLoading: boolean;
  isModelInfoLoading: boolean;
  error: string | null;
}
