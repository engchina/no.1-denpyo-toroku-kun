/**
 * Dashboard - サービス健全性とモデル品質の運用ダッシュボード。
 */
import { h } from 'preact';
import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { fetchHealth, fetchStats } from '../../redux/slices/classifierSlice';
import { setCurrentView } from '../../redux/slices/applicationSlice';
import { formatDuration, formatPercentage, formatTime } from '../../utils/apiUtils';
import type { HealthData, ModelInfo, StatsData } from '../../types/classifierTypes';
import {
  Activity,
  AlertTriangle,
  ArrowRight,

  CheckCircle,
  Clock,
  Cpu,
  Database,
  Gauge,
  HardDrive,

  Server,
  ShieldAlert,
  XCircle,
  Zap
} from 'lucide-react';

const REFRESH_OPTIONS = [15, 30, 60, 120] as const;
const DEFAULT_REFRESH_SECONDS = 30;

type InsightLevel = 'critical' | 'warning' | 'info';

interface OperationalInsight {
  level: InsightLevel;
  title: string;
  detail: string;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
}

function modelSourceLabel(source: string | null | undefined): string {
  if (!source) return '--';
  const normalized = source.trim().toLowerCase();
  if (normalized === 'disk_loaded') return 'ディスク読み込み';
  if (normalized === 'trained_runtime') return '実行時学習';
  if (normalized === 'initialized') return '初期化';
  if (normalized === 'unknown') return '不明';
  return source;
}

function getStatusInfo(status?: string) {
  if (status === 'healthy') {
    return { icon: CheckCircle, label: '正常', className: 'ics-status-healthy' };
  }
  if (status === 'warning' || status === 'degraded') {
    return { icon: AlertTriangle, label: status === 'warning' ? '注意' : '性能低下', className: 'ics-status-degraded' };
  }
  if (status === 'error') {
    return { icon: XCircle, label: 'エラー', className: 'ics-status-error' };
  }
  return { icon: Activity, label: '不明', className: 'ics-status-unknown' };
}

function modelQualityScore(summary: ModelInfo['training_summary']): number | null {
  if (!summary) return null;
  const test = summary.test_accuracy;
  const gap = summary.overfitting_gap;
  if (test == null || gap == null) return null;
  const score = test * 100 - gap * 60;
  return Math.round(clamp(score, 0, 100));
}

function thresholdGuidance(summary: ModelInfo['training_summary']) {
  if (!summary) return null;
  const test = summary.test_accuracy ?? 0;
  const gap = summary.overfitting_gap ?? 0;

  if (test < 0.75) {
    return {
      range: '0.40 - 0.55',
      note: 'テスト精度がまだ低めです。しきい値は中程度にし、不確実な入力は手動確認へ振り分けてください。'
    };
  }
  if (gap > 0.10) {
    return {
      range: '0.60 - 0.75',
      note: '過学習ギャップが大きめです。しきい値を上げて、過信による誤判定を抑えてください。'
    };
  }
  if (test >= 0.90 && gap < 0.05) {
    return {
      range: '0.45 - 0.60',
      note: 'モデルは安定して高精度です。バランス型のしきい値で再現率と適合率を両立しやすい状態です。'
    };
  }

  return {
    range: '0.50 - 0.65',
    note: '混在する信頼度のトラフィックにはバランス範囲が適します。低信頼度の割合を監視してください。'
  };
}

function buildInsights(health: HealthData | null, stats: StatsData | null): OperationalInsight[] {
  const insights: OperationalInsight[] = [];
  const perf = stats?.performance;
  const cache = stats?.cache;
  const summary = stats?.model?.training_summary;

  if (health && !health.model_loaded) {
    insights.push({
      level: 'critical',
      title: 'モデルが読み込まれていません',
      detail: '予測が失敗するかフォールバックする可能性があります。モデルを再読み込みし、パス/ソースを確認してください。'
    });
  }

  if (perf) {
    if (perf.error_rate >= 0.05) {
      insights.push({
        level: 'critical',
        title: 'エラー率が高い',
        detail: `現在のエラー率は ${formatPercentage(perf.error_rate)} です。入力内容とバックエンド例外を確認してください。`
      });
    } else if (perf.error_rate >= 0.02) {
      insights.push({
        level: 'warning',
        title: 'エラー率が上昇傾向',
        detail: `エラー率は ${formatPercentage(perf.error_rate)} です。失敗入力のサンプル収集と信頼度の挙動確認を開始してください。`
      });
    }

    if (perf.p95_prediction_time > 1.5) {
      insights.push({
        level: 'warning',
        title: 'P95 レイテンシが高い',
        detail: `P95 は ${formatDuration(perf.p95_prediction_time)} です。キャッシュ調整と入力サイズ制御を検討してください。`
      });
    }
  }

  if (cache) {
    if (cache.hit_rate < 0.35) {
      insights.push({
        level: 'warning',
        title: 'キャッシュヒット率が低い',
        detail: `ヒット率は ${formatPercentage(cache.hit_rate)} です。キャッシュ容量の増加や入力正規化を検討してください。`
      });
    }

    const fillRate = cache.max_size > 0 ? cache.cache_size / cache.max_size : 0;
    if (fillRate >= 0.95) {
      insights.push({
        level: 'warning',
        title: 'キャッシュが容量上限に近い',
        detail: '使用率が 95% を超えています。LRU の入れ替え増加によりレイテンシのばらつきが増える可能性があります。'
      });
    }
  }

  if (summary) {
    const test = summary.test_accuracy ?? 0;
    const gap = summary.overfitting_gap ?? 0;

    if (test < 0.75) {
      insights.push({
        level: 'warning',
        title: '汎化性能のリスク',
        detail: `テスト精度は ${formatPercentage(test)} です。自動ルーティングを強める前にデータセットのカバレッジを改善してください。`
      });
    }
    if (gap > 0.1) {
      insights.push({
        level: 'warning',
        title: '過学習ギャップが大きい',
        detail: `学習/テストの差は ${formatPercentage(gap)} です。正則化を強め、検証分割を厳しくしてください。`
      });
    }
  }

  if (insights.length === 0) {
    insights.push({
      level: 'info',
      title: 'システムは安定しています',
      detail: '健全性/性能/キャッシュ/モデル要約の観点で、重大な異常は検出されていません。'
    });
  }

  return insights;
}

export function Dashboard() {
  const dispatch = useAppDispatch();
  const health = useAppSelector(state => state.classifier.health);
  const stats = useAppSelector(state => state.classifier.stats);
  const isHealthLoading = useAppSelector(state => state.classifier.isHealthLoading);
  const isStatsLoading = useAppSelector(state => state.classifier.isStatsLoading);

  const [autoRefresh, setAutoRefresh] = useState(true);
  const [refreshSeconds, setRefreshSeconds] = useState<number>(DEFAULT_REFRESH_SECONDS);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);

  const refreshData = useCallback(async () => {
    try {
      await Promise.all([
        dispatch(fetchHealth()).unwrap(),
        dispatch(fetchStats()).unwrap()
      ]);
      setLastUpdatedAt(new Date().toISOString());
    } catch {
      // keep existing content if a refresh attempt fails
    }
  }, [dispatch]);

  useEffect(() => {
    void refreshData();
  }, [refreshData]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = window.setInterval(() => {
      void refreshData();
    }, refreshSeconds * 1000);
    return () => window.clearInterval(interval);
  }, [autoRefresh, refreshSeconds, refreshData]);

  const isRefreshing = isHealthLoading || isStatsLoading;
  const statusInfo = useMemo(() => getStatusInfo(health?.status), [health?.status]);
  const StatusIcon = statusInfo.icon;

  const perf = stats?.performance;
  const cache = stats?.cache;
  const model = stats?.model;
  const trainingSummary = model?.training_summary;

  const cacheHitRate = cache?.hit_rate ?? 0;
  const cacheFillRate = cache && cache.max_size > 0 ? cache.cache_size / cache.max_size : 0;
  const throughputPerMinute = (() => {
    const totalPredictions = perf?.total_predictions ?? 0;
    const uptimeSeconds = health?.uptime_seconds ?? 0;
    if (totalPredictions <= 0 || uptimeSeconds <= 0) return 0;
    return totalPredictions / Math.max(uptimeSeconds / 60, 1);
  })();

  const qualityScore = modelQualityScore(trainingSummary);
  const recommendedThreshold = thresholdGuidance(trainingSummary);
  const insights = useMemo(() => buildInsights(health, stats), [health, stats]);

  const candidateRows = useMemo(() => {
    if (!trainingSummary?.candidates || trainingSummary.candidates.length === 0) return [];

    return [...trainingSummary.candidates]
      .map(candidate => {
        const score = candidate.test_accuracy * 100 - candidate.overfitting_gap * 45;
        return {
          ...candidate,
          score: Math.round(clamp(score, 0, 100))
        };
      })
      .sort((a, b) => b.score - a.score);
  }, [trainingSummary]);

  return (
    <div class="ics-dashboard ics-dashboard--enhanced">
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>ダッシュボード</h2>
            <p class="ics-ops-hero__subtitle">
              サービス健全性、レイテンシ、キャッシュ効率、モデル品質をまとめて確認できます。
            </p>
          </div>
          <div class="ics-ops-hero__controls">
            <label class="ics-ops-controlToggle">
              <input
                type="checkbox"
                checked={autoRefresh}
                onInput={(event) => setAutoRefresh((event.currentTarget as HTMLInputElement).checked)}
              />
              <span>自動更新</span>
            </label>

            <label class="ics-ops-controlSelect" aria-label="更新間隔">
              <span>間隔</span>
              <select
                value={String(refreshSeconds)}
                disabled={!autoRefresh}
                onInput={(event) => setRefreshSeconds(Number((event.currentTarget as HTMLSelectElement).value))}
              >
                {REFRESH_OPTIONS.map((seconds) => (
                  <option key={seconds} value={seconds}>{seconds}s</option>
                ))}
              </select>
            </label>

            <button class="ics-ops-btn ics-ops-btn--primary" onClick={() => { void refreshData(); }} disabled={isRefreshing}>
              <span>{isRefreshing ? '更新中…' : '今すぐ更新'}</span>
            </button>
          </div>
        </div>

        <div class="ics-ops-hero__meta">
          <span>最終更新: {formatDateTime(lastUpdatedAt)}</span>
          <button class="ics-ops-btn ics-ops-btn--ghost" onClick={() => dispatch(setCurrentView('stats'))}>
            <span>統計を開く</span>
            <span class="ics-btn-icon"><ArrowRight size={14} /></span>
          </button>
          <button class="ics-ops-btn ics-ops-btn--ghost" onClick={() => dispatch(setCurrentView('modelInfo'))}>
            <span>モデル情報を開く</span>
            <span class="ics-btn-icon"><ArrowRight size={14} /></span>
          </button>
        </div>
      </section>

      <section class="ics-ops-kpiGrid">
        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Server size={14} />サービス状態</div>
          <div class="ics-ops-kpiCard__value">{statusInfo.label}</div>
          <div class={`ics-status-badge ${statusInfo.className}`}>
            <StatusIcon size={16} />
            <span>{health?.message || 'アラートはありません'}</span>
          </div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Zap size={14} />予測スループット</div>
          <div class="ics-ops-kpiCard__value">{throughputPerMinute.toFixed(1)}/min</div>
          <div class="ics-ops-kpiCard__meta">合計: {(perf?.total_predictions ?? 0).toLocaleString()}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Gauge size={14} />エラー率</div>
          <div class="ics-ops-kpiCard__value">{formatPercentage(perf?.error_rate ?? 0)}</div>
          <div class="ics-ops-kpiCard__meta">エラー数: {(perf?.total_errors ?? 0).toLocaleString()}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Clock size={14} />レイテンシ</div>
          <div class="ics-ops-kpiCard__value">{formatDuration(perf?.p95_prediction_time ?? 0)}</div>
          <div class="ics-ops-kpiCard__meta">平均: {formatDuration(perf?.avg_prediction_time ?? 0)}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Database size={14} />キャッシュヒット率</div>
          <div class="ics-ops-kpiCard__value">{formatPercentage(cacheHitRate)}</div>
          <div class="ics-ops-kpiCard__meta">サイズ: {cache?.cache_size ?? 0} / {cache?.max_size ?? 0}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Cpu size={14} />モデル品質</div>
          <div class="ics-ops-kpiCard__value">{qualityScore == null ? '--' : `${qualityScore}/100`}</div>
          <div class="ics-ops-kpiCard__meta">クラス数: {model?.num_classes ?? 0}</div>
        </article>
      </section>

      <section class="ics-ops-grid ics-ops-grid--two">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <Server size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">実行環境 / サービス情報</span>
          </div>
          <div class="ics-card-body">
            <table class="ics-table">
              <tbody>
                <tr>
                  <td>サービスバージョン</td>
                  <td class="oj-text-right"><strong>{health?.version || '--'}</strong></td>
                </tr>
                <tr>
                  <td>稼働時間</td>
                  <td class="oj-text-right">{health ? formatTime(health.uptime_seconds) : '--'}</td>
                </tr>
                <tr>
                  <td>モデル読み込み</td>
                  <td class="oj-text-right">
                    {health?.model_loaded ? <span class="ics-badge-success">はい</span> : <span class="ics-badge-danger">いいえ</span>}
                  </td>
                </tr>
                <tr>
                  <td>モニタリング</td>
                  <td class="oj-text-right">{health?.monitoring_enabled ? 'はい' : 'いいえ'}</td>
                </tr>
                <tr>
                  <td>キャッシュ有効</td>
                  <td class="oj-text-right">{health?.cache_enabled ? 'はい' : 'いいえ'}</td>
                </tr>
                <tr>
                  <td>ヘルス時刻</td>
                  <td class="oj-text-right">{formatDateTime(health?.timestamp)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <ShieldAlert size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">運用リスク / 推奨対応</span>
          </div>
          <div class="ics-card-body">
            <div class="ics-ops-insightList">
              {insights.map((insight, index) => (
                <article key={`${insight.title}-${index}`} class={`ics-ops-insight ics-ops-insight--${insight.level}`}>
                  <div class="ics-ops-insight__title">{insight.title}</div>
                  <p>{insight.detail}</p>
                </article>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section class="ics-ops-grid ics-ops-grid--two">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <HardDrive size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">キャッシュ効率</span>
          </div>
          <div class="ics-card-body">
            {cache ? (
              <div class="ics-ops-meterGroup">
                <div class="ics-ops-meterLabel">
                  <span>ヒット率</span>
                  <strong>{formatPercentage(cacheHitRate)}</strong>
                </div>
                <div class="ics-ops-meter"><span style={{ width: `${Math.round(cacheHitRate * 100)}%` }} /></div>

                <div class="ics-ops-meterLabel">
                  <span>容量使用率</span>
                  <strong>{formatPercentage(cacheFillRate)}</strong>
                </div>
                <div class="ics-ops-meter"><span style={{ width: `${Math.round(cacheFillRate * 100)}%` }} /></div>

                <div class="ics-ops-inlineStats">
                  <div>
                    <span>ヒット</span>
                    <strong>{cache.hits.toLocaleString()}</strong>
                  </div>
                  <div>
                    <span>ミス</span>
                    <strong>{cache.misses.toLocaleString()}</strong>
                  </div>
                  <div>
                    <span>現在 / 最大</span>
                    <strong>{cache.cache_size} / {cache.max_size}</strong>
                  </div>
                </div>
              </div>
            ) : (
              <div class="ics-empty-text">キャッシュデータがありません</div>
            )}
          </div>
        </div>

        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <Cpu size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">最新モデルスナップショット</span>
          </div>
          <div class="ics-card-body">
            {model ? (
              <>
                <table class="ics-table">
                  <tbody>
                    <tr>
                      <td>アルゴリズム</td>
                      <td class="oj-text-right"><strong>{model.algorithm}</strong></td>
                    </tr>
                    <tr>
                      <td>モデルソース</td>
                      <td class="oj-text-right">{modelSourceLabel(model.model_source)}</td>
                    </tr>
                    <tr>
                      <td>モデル時刻</td>
                      <td class="oj-text-right">{formatDateTime(model.model_timestamp || undefined)}</td>
                    </tr>
                    <tr>
                      <td>クラス</td>
                      <td class="oj-text-right">{model.num_classes}</td>
                    </tr>
                    <tr>
                      <td>推定器</td>
                      <td class="oj-text-right">{model.n_estimators}</td>
                    </tr>
                    {trainingSummary?.test_accuracy != null && (
                      <tr>
                        <td>テスト精度</td>
                        <td class="oj-text-right">{formatPercentage(trainingSummary.test_accuracy)}</td>
                      </tr>
                    )}
                    {trainingSummary?.overfitting_gap != null && (
                      <tr>
                        <td>過学習ギャップ</td>
                        <td class="oj-text-right">{formatPercentage(trainingSummary.overfitting_gap)}</td>
                      </tr>
                    )}
                  </tbody>
                </table>

                {recommendedThreshold && (
                  <div class="ics-ops-callout oj-sm-margin-3x-top">
                    <div class="ics-ops-callout__title">しきい値の目安: {recommendedThreshold.range}</div>
                    <p>{recommendedThreshold.note}</p>
                  </div>
                )}

                {candidateRows.length > 0 && (
                  <div class="oj-sm-margin-3x-top">
                    <span class="oj-typography-body-sm oj-text-color-secondary">候補ランキング</span>
                    <table class="ics-table oj-sm-margin-2x-top">
                      <thead>
                        <tr>
                          <th>アルゴリズム</th>
                          <th>テスト</th>
                          <th>ギャップ</th>
                          <th>スコア</th>
                        </tr>
                      </thead>
                      <tbody>
                        {candidateRows.map((candidate, index) => (
                          <tr key={`${candidate.algorithm}-${index}`}>
                            <td>{candidate.algorithm}</td>
                            <td>{formatPercentage(candidate.test_accuracy)}</td>
                            <td>{formatPercentage(candidate.overfitting_gap)}</td>
                            <td>{candidate.score}/100</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            ) : (
              <div class="ics-empty-text">モデル情報がありません</div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
