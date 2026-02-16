/**
 * Stats - 性能分析とキャッシュ診断。
 */
import { h } from 'preact';
import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { clearCache, fetchHealth, fetchStats } from '../../redux/slices/classifierSlice';
import { setCurrentView } from '../../redux/slices/applicationSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { formatDuration, formatPercentage, formatTime } from '../../utils/apiUtils';
import {
  Activity,
  AlertTriangle,
  ArrowRight,

  BarChart3,
  Clock,
  Database,
  Gauge,

  ShieldAlert,

  XCircle,
  Zap
} from 'lucide-react';

const REFRESH_OPTIONS = [15, 30, 60, 120] as const;
const DEFAULT_REFRESH_SECONDS = 30;

interface StatsInsight {
  level: 'critical' | 'warning' | 'info';
  title: string;
  detail: string;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
}

function toErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function buildInsights(
  errorRate: number,
  avgLatency: number,
  p95Latency: number,
  p99Latency: number,
  hitRate: number,
  cacheFillRate: number
): StatsInsight[] {
  const insights: StatsInsight[] = [];

  if (errorRate >= 0.05) {
    insights.push({
      level: 'critical',
      title: 'エラー率が 5% を超えています',
      detail: '強い自動ルーティングを有効にする前に、バックエンド例外とフォールバック挙動を調査してください。'
    });
  } else if (errorRate >= 0.02) {
    insights.push({
      level: 'warning',
      title: 'エラー率に注意が必要です',
      detail: 'エラー率が 2% を超えています。入力種別と信頼度ごとに失敗パターンの分類を開始してください。'
    });
  }

  if (p95Latency > 1.5 || p99Latency > 2.5) {
    insights.push({
      level: 'warning',
      title: 'レイテンシの裾が伸びています',
      detail: 'p95/p99 の増加は SLA に影響します。埋め込み取得とキャッシュ入れ替えをプロファイルしてください。'
    });
  }

  if (p99Latency > 0 && p99Latency > avgLatency * 4) {
    insights.push({
      level: 'warning',
      title: 'レイテンシのばらつきが大きい',
      detail: 'P99 が平均の 4 倍を超えています。入力正規化とワークロード分離を検討してください。'
    });
  }

  if (hitRate < 0.35) {
    insights.push({
      level: 'warning',
      title: 'キャッシュヒット率が低い',
      detail: 'ヒット率が低いと高速化効果が限定されます。キャッシュ容量の増加や、ハッシュ前の入力正規化を検討してください。'
    });
  }

  if (cacheFillRate >= 0.95) {
    insights.push({
      level: 'warning',
      title: 'キャッシュが容量上限に近い',
      detail: '使用率が高いと LRU 退避が増え、コールドミスのコストが上がる可能性があります。'
    });
  }

  if (insights.length === 0) {
    insights.push({
      level: 'info',
      title: '運用指標は安定しています',
      detail: '現在の性能とキャッシュ挙動は、運用監視として安全な範囲にあります。'
    });
  }

  return insights;
}

export function Stats() {
  const dispatch = useAppDispatch();
  const stats = useAppSelector(state => state.classifier.stats);
  const health = useAppSelector(state => state.classifier.health);
  const isStatsLoading = useAppSelector(state => state.classifier.isStatsLoading);
  const isHealthLoading = useAppSelector(state => state.classifier.isHealthLoading);

  const [autoRefresh, setAutoRefresh] = useState(true);
  const [refreshSeconds, setRefreshSeconds] = useState<number>(DEFAULT_REFRESH_SECONDS);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [isClearing, setIsClearing] = useState(false);
  const [isClearConfirmOpen, setIsClearConfirmOpen] = useState(false);

  const refreshData = useCallback(async () => {
    try {
      await Promise.all([
        dispatch(fetchStats()).unwrap(),
        dispatch(fetchHealth()).unwrap()
      ]);
      setLastUpdatedAt(new Date().toISOString());
    } catch {
      // keep existing content if refresh fails
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

  const handleClearCache = useCallback(async () => {
    setIsClearConfirmOpen(false);
    setIsClearing(true);
    try {
      await dispatch(clearCache()).unwrap();
      dispatch(addNotification({ type: 'success', message: 'キャッシュをクリアしました', autoClose: true }));
      await refreshData();
    } catch (error: unknown) {
      dispatch(addNotification({ type: 'error', message: toErrorMessage(error, 'キャッシュのクリアに失敗しました') }));
    } finally {
      setIsClearing(false);
    }
  }, [dispatch, refreshData]);

  const isRefreshing = isStatsLoading || isHealthLoading;
  const perf = stats?.performance;
  const cache = stats?.cache;

  const totalPredictions = perf?.total_predictions ?? 0;
  const totalErrors = perf?.total_errors ?? 0;
  const errorRate = perf?.error_rate ?? 0;
  const successRate = Math.max(0, 1 - errorRate);

  const avgLatency = perf?.avg_prediction_time ?? 0;
  const p95Latency = perf?.p95_prediction_time ?? 0;
  const p99Latency = perf?.p99_prediction_time ?? 0;
  const maxLatency = perf?.max_prediction_time ?? 0;

  const hitRate = cache?.hit_rate ?? 0;
  const cacheFillRate = cache && cache.max_size > 0 ? cache.cache_size / cache.max_size : 0;

  const uptimeSeconds = health?.uptime_seconds ?? 0;
  const throughputPerMinute = totalPredictions > 0 && uptimeSeconds > 0
    ? totalPredictions / Math.max(uptimeSeconds / 60, 1)
    : 0;

  const latencyMax = Math.max(avgLatency, p95Latency, p99Latency, maxLatency, 0.0001);

  const latencyRows = [
    { label: '平均', value: avgLatency },
    { label: 'P95', value: p95Latency },
    { label: 'P99', value: p99Latency },
    { label: '最大', value: maxLatency }
  ];

  const insights = useMemo(
    () => buildInsights(errorRate, avgLatency, p95Latency, p99Latency, hitRate, cacheFillRate),
    [errorRate, avgLatency, p95Latency, p99Latency, hitRate, cacheFillRate]
  );

  const latencyBudgetTarget = 1.0;
  const latencyBudgetRatio = latencyBudgetTarget > 0 ? p95Latency / latencyBudgetTarget : 0;

  return (
    <div class="ics-stats ics-stats--enhanced">
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>統計</h2>
            <p class="ics-ops-hero__subtitle">
              レイテンシ分布、エラーバジェット、キャッシュ使用状況を運用向けに可視化します。
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
          <span>稼働時間: {health ? formatTime(health.uptime_seconds) : '--'}</span>
          <button class="ics-ops-btn ics-ops-btn--ghost" onClick={() => dispatch(setCurrentView('dashboard'))}>
            <span>ダッシュボードへ戻る</span>
            <span class="ics-btn-icon"><ArrowRight size={14} /></span>
          </button>
        </div>
      </section>

      <section class="ics-ops-kpiGrid">
        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Zap size={14} />予測回数（合計）</div>
          <div class="ics-ops-kpiCard__value">{totalPredictions.toLocaleString()}</div>
          <div class="ics-ops-kpiCard__meta">スループット: {throughputPerMinute.toFixed(1)}/min</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><XCircle size={14} />エラー数（合計）</div>
          <div class="ics-ops-kpiCard__value">{totalErrors.toLocaleString()}</div>
          <div class="ics-ops-kpiCard__meta">エラー率: {formatPercentage(errorRate)}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Activity size={14} />成功率</div>
          <div class="ics-ops-kpiCard__value">{formatPercentage(successRate)}</div>
          <div class="ics-ops-kpiCard__meta">エラーバジェット消費: {formatPercentage(errorRate)}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Clock size={14} />平均レイテンシ</div>
          <div class="ics-ops-kpiCard__value">{formatDuration(avgLatency)}</div>
          <div class="ics-ops-kpiCard__meta">P95: {formatDuration(p95Latency)}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Gauge size={14} />P99 レイテンシ</div>
          <div class="ics-ops-kpiCard__value">{formatDuration(p99Latency)}</div>
          <div class="ics-ops-kpiCard__meta">最大: {formatDuration(maxLatency)}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Database size={14} />キャッシュヒット率</div>
          <div class="ics-ops-kpiCard__value">{formatPercentage(hitRate)}</div>
          <div class="ics-ops-kpiCard__meta">使用率: {formatPercentage(cacheFillRate)}</div>
        </article>
      </section>

      <section class="ics-ops-grid ics-ops-grid--two">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <BarChart3 size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">レイテンシ分布</span>
          </div>
          <div class="ics-card-body">
            <div class="ics-ops-latencyBars">
              {latencyRows.map((row) => (
                <div class="ics-ops-latencyRow" key={row.label}>
                  <div class="ics-ops-latencyRow__head">
                    <span>{row.label}</span>
                    <strong>{formatDuration(row.value)}</strong>
                  </div>
                  <div class="ics-ops-meter">
                    <span style={{ width: `${Math.round((row.value / latencyMax) * 100)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <AlertTriangle size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">SLO / エラーバジェット</span>
          </div>
          <div class="ics-card-body">
            <div class="ics-ops-inlineStats">
              <div>
                <span>成功率</span>
                <strong>{formatPercentage(successRate)}</strong>
              </div>
              <div>
                <span>レイテンシ目標（P95 ≤ 1.0s）</span>
                <strong>{latencyBudgetRatio <= 1 ? '目標内' : `${latencyBudgetRatio.toFixed(2)} 倍`}</strong>
              </div>
              <div>
                <span>推定失敗数 / 1,000 リクエスト</span>
                <strong>{Math.round(errorRate * 1000)}</strong>
              </div>
            </div>
            <div class="ics-ops-callout oj-sm-margin-3x-top">
              <div class="ics-ops-callout__title">運用の要点</div>
              <p>
                自動ルーティングを安定させるには、P95 を 1.0 秒未満、エラー率を 2% 未満に保つことを推奨します。
                現在は {formatDuration(p95Latency)} / {formatPercentage(errorRate)} です。
              </p>
            </div>
          </div>
        </div>
      </section>

      <section class="ics-card ics-ops-panel">
        <div class="ics-card-header oj-flex-bar oj-sm-align-items-center">
          <div class="oj-flex-bar-start oj-flex oj-sm-align-items-center">
            <Database size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">Cache Diagnostics</span>
          </div>
          <div class="oj-flex-bar-end">
            <button class="ics-ops-btn ics-ops-btn--danger" onClick={() => setIsClearConfirmOpen(true)} disabled={isClearing}>
              <span>{isClearing ? 'クリア中…' : 'キャッシュをクリア'}</span>
            </button>
          </div>
        </div>

        <div class="ics-card-body">
          {cache ? (
            <>
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
                  <span>サイズ</span>
                  <strong>{cache.cache_size} / {cache.max_size}</strong>
                </div>
              </div>

              <div class="ics-ops-meterGroup oj-sm-margin-3x-top">
                <div class="ics-ops-meterLabel">
                  <span>ヒット率</span>
                  <strong>{formatPercentage(hitRate)}</strong>
                </div>
                <div class="ics-ops-meter"><span style={{ width: `${Math.round(hitRate * 100)}%` }} /></div>

                <div class="ics-ops-meterLabel">
                  <span>容量使用率</span>
                  <strong>{formatPercentage(cacheFillRate)}</strong>
                </div>
                <div class="ics-ops-meter"><span style={{ width: `${Math.round(cacheFillRate * 100)}%` }} /></div>
              </div>
            </>
          ) : (
            <div class="ics-empty-text">キャッシュデータがありません</div>
          )}
        </div>
      </section>

      <section class="ics-card ics-ops-panel">
        <div class="ics-card-header oj-flex oj-sm-align-items-center">
          <ShieldAlert size={18} class="oj-sm-margin-2x-end" />
          <span class="oj-typography-heading-xs">推奨事項</span>
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
      </section>

      <ConfirmDialog
        isOpen={isClearConfirmOpen}
        title="キャッシュのクリア"
        message="キャッシュをクリアし、ヒット/ミスのカウンタをリセットしますか？"
        confirmLabel="クリア"
        confirmVariant="danger"
        isBusy={isClearing}
        onCancel={() => setIsClearConfirmOpen(false)}
        onConfirm={() => { void handleClearCache(); }}
      />
    </div>
  );
}
