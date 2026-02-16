/**
 * 分類器に関する列挙体
 */

export enum PredictionMode {
  SINGLE = 'single',
  BATCH = 'batch'
}

export enum ServiceStatus {
  HEALTHY = 'healthy',
  DEGRADED = 'degraded',
  ERROR = 'error',
  LOADING = 'loading',
  UNKNOWN = 'unknown'
}

export enum TrainingStatus {
  IDLE = 'idle',
  RUNNING = 'running',
  COMPLETED = 'completed',
  FAILED = 'failed'
}

export enum ConfidenceLevel {
  HIGH = 'high',
  MEDIUM = 'medium',
  LOW = 'low'
}

export const getConfidenceLevel = (confidence: number): ConfidenceLevel => {
  if (confidence >= 0.7) return ConfidenceLevel.HIGH;
  if (confidence >= 0.4) return ConfidenceLevel.MEDIUM;
  return ConfidenceLevel.LOW;
};

export const getConfidenceLabel = (confidence: number): string => {
  if (confidence >= 0.7) return '自動処理';
  if (confidence >= 0.4) return '要確認';
  return '要エスカレーション';
};

export const getConfidenceClass = (confidence: number): string => {
  if (confidence >= 0.7) return 'ics-badge-success';
  if (confidence >= 0.4) return 'ics-badge-warning';
  return 'ics-badge-danger';
};
