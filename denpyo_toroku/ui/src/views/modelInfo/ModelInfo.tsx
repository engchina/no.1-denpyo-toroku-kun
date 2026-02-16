/**
 * ModelInfo - モデル情報（メタデータ/品質/クラス一覧）。
 */
import { h } from 'preact';
import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { fetchModelInfo, reloadModel } from '../../redux/slices/classifierSlice';
import { setCurrentView } from '../../redux/slices/applicationSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { Pagination } from '../../components/Pagination';
import { formatPercentage } from '../../utils/apiUtils';
import type { ModelInfo as ModelInfoType } from '../../types/classifierTypes';
import {
  AlertTriangle,
  ArrowRight,

  Box,


  Cpu,
  Layers,

  Search,
  ShieldAlert,
  Tag,

  XCircle
} from 'lucide-react';

const REFRESH_OPTIONS = [30, 60, 120, 300] as const;
const DEFAULT_REFRESH_SECONDS = 60;
const CLASSES_PER_PAGE = 20;

type ClassSortMode = 'alphabetical' | 'length_desc' | 'length_asc';

interface ModelInsight {
  level: 'critical' | 'warning' | 'info';
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

function toErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function modelReadinessScore(modelInfo: ModelInfoType | null): number | null {
  if (!modelInfo) return null;
  if (modelInfo.model_loaded === false) return 0;

  const summary = modelInfo.training_summary;
  let score = 72;

  if (summary?.test_accuracy != null) {
    score = summary.test_accuracy * 100;
  }

  if (summary?.overfitting_gap != null) {
    score -= summary.overfitting_gap * 60;
  }

  return Math.round(clamp(score, 0, 100));
}

function buildModelInsights(modelInfo: ModelInfoType | null): ModelInsight[] {
  const insights: ModelInsight[] = [];

  if (!modelInfo) {
    return [{
      level: 'critical',
      title: 'モデル情報を取得できません',
      detail: 'モデル詳細の読み込みに失敗しました。更新し、バックエンド API 応答を確認してください。'
    }];
  }

  if (modelInfo.model_loaded === false) {
    insights.push({
      level: 'critical',
      title: 'モデルが読み込まれていません',
      detail: '予測処理やダッシュボードの品質分析を行う前に、モデルを再読み込みしてください。'
    });
  }

  if (modelInfo.num_classes <= 1) {
    insights.push({
      level: 'warning',
      title: 'クラス数が少なすぎます',
      detail: '有用な分類には、少なくとも 2 つ以上の意図クラスが必要です。'
    });
  }

  const summary = modelInfo.training_summary;
  if (summary?.test_accuracy != null && summary.test_accuracy < 0.75) {
    insights.push({
      level: 'warning',
      title: 'テスト精度が低い',
      detail: `現在のテスト精度は ${formatPercentage(summary.test_accuracy)} です。データ品質とクラス境界を見直してください。`
    });
  }

  if (summary?.overfitting_gap != null && summary.overfitting_gap > 0.1) {
    insights.push({
      level: 'warning',
      title: '過学習ギャップが大きい',
      detail: `学習/テスト差は ${formatPercentage(summary.overfitting_gap)} です。正則化の強化やリバランスを検討してください。`
    });
  }

  if (insights.length === 0) {
    insights.push({
      level: 'info',
      title: 'モデル情報は良好です',
      detail: 'モデルおよび学習要約の範囲で、重大な品質異常は検出されませんでした。'
    });
  }

  return insights;
}

export function ModelInfo() {
  const dispatch = useAppDispatch();
  const modelInfo = useAppSelector(state => state.classifier.modelInfo);
  const isLoading = useAppSelector(state => state.classifier.isModelInfoLoading);

  const [isReloading, setIsReloading] = useState(false);
  const [isReloadConfirmOpen, setIsReloadConfirmOpen] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [refreshSeconds, setRefreshSeconds] = useState<number>(DEFAULT_REFRESH_SECONDS);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);

  const [classQuery, setClassQuery] = useState('');
  const [classSort, setClassSort] = useState<ClassSortMode>('alphabetical');
  const [classPage, setClassPage] = useState(1);
  const [goToPageInput, setGoToPageInput] = useState('');

  const refreshData = useCallback(async () => {
    try {
      await dispatch(fetchModelInfo()).unwrap();
      setLastUpdatedAt(new Date().toISOString());
    } catch {
      // keep previous snapshot when refresh fails
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

  useEffect(() => {
    setClassPage(1);
  }, [classQuery, classSort, modelInfo?.classes]);

  const handleReload = useCallback(async () => {
    setIsReloadConfirmOpen(false);
    setIsReloading(true);
    try {
      await dispatch(reloadModel()).unwrap();
      dispatch(addNotification({ type: 'success', message: 'モデルを再読み込みしました', autoClose: true }));
      await refreshData();
    } catch (error: unknown) {
      dispatch(addNotification({ type: 'error', message: toErrorMessage(error, 'モデルの再読み込みに失敗しました') }));
    } finally {
      setIsReloading(false);
    }
  }, [dispatch, refreshData]);

  const classes = modelInfo?.classes ?? [];
  const normalizedQuery = classQuery.trim().toLowerCase();

  const filteredClasses = useMemo(() => {
    const searched = normalizedQuery
      ? classes.filter((cls) => cls.toLowerCase().includes(normalizedQuery))
      : [...classes];

    if (classSort === 'length_asc') {
      return searched.sort((a, b) => a.length - b.length || a.localeCompare(b));
    }

    if (classSort === 'length_desc') {
      return searched.sort((a, b) => b.length - a.length || a.localeCompare(b));
    }

    return searched.sort((a, b) => a.localeCompare(b));
  }, [classes, normalizedQuery, classSort]);

  const totalPages = Math.max(1, Math.ceil(filteredClasses.length / CLASSES_PER_PAGE));
  const currentPage = Math.min(classPage, totalPages);

  const pagedClasses = useMemo(() => {
    const start = (currentPage - 1) * CLASSES_PER_PAGE;
    return filteredClasses.slice(start, start + CLASSES_PER_PAGE);
  }, [filteredClasses, currentPage]);

  const averageClassLength = classes.length > 0
    ? Math.round(classes.reduce((sum, cls) => sum + cls.length, 0) / classes.length)
    : 0;

  const longestClass = classes.reduce<string>((longest, current) => (
    current.length > longest.length ? current : longest
  ), '');

  const readinessScore = modelReadinessScore(modelInfo);
  const insights = buildModelInsights(modelInfo);

  const candidateRows = useMemo(() => {
    const candidates = modelInfo?.training_summary?.candidates;
    if (!candidates || candidates.length === 0) return [];

    return [...candidates]
      .map((candidate) => {
        const score = candidate.test_accuracy * 100 - candidate.overfitting_gap * 45;
        return {
          ...candidate,
          score: Math.round(clamp(score, 0, 100))
        };
      })
      .sort((a, b) => b.score - a.score);
  }, [modelInfo?.training_summary?.candidates]);

  const isBusy = isLoading || isReloading;

  return (
    <div class="ics-model-info ics-model-info--enhanced">
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>モデル情報</h2>
            <p class="ics-ops-hero__subtitle">
              モデルのメタデータ、学習品質、クラス体系を運用向けに確認します。
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

            <button class="ics-ops-btn ics-ops-btn--primary" onClick={() => { void refreshData(); }} disabled={isBusy}>
              <span>{isLoading ? '更新中…' : '更新'}</span>
            </button>

            <button class="ics-ops-btn ics-ops-btn--danger" onClick={() => setIsReloadConfirmOpen(true)} disabled={isBusy}>
              <span>{isReloading ? '再読み込み中…' : 'モデルを再読み込み'}</span>
            </button>
          </div>
        </div>

        <div class="ics-ops-hero__meta">
          <span>最終更新: {formatDateTime(lastUpdatedAt)}</span>
          <button class="ics-ops-btn ics-ops-btn--ghost" onClick={() => dispatch(setCurrentView('train'))}>
            <span>学習を開く</span>
            <span class="ics-btn-icon"><ArrowRight size={14} /></span>
          </button>
          <button class="ics-ops-btn ics-ops-btn--ghost" onClick={() => dispatch(setCurrentView('dashboard'))}>
            <span>ダッシュボードを開く</span>
            <span class="ics-btn-icon"><ArrowRight size={14} /></span>
          </button>
        </div>
      </section>

      <ConfirmDialog
        isOpen={isReloadConfirmOpen}
        title="モデルの再読み込み"
        message="ディスクからモデルを再読み込みしますか？"
        confirmLabel="再読み込み"
        confirmVariant="danger"
        isBusy={isReloading}
        onCancel={() => setIsReloadConfirmOpen(false)}
        onConfirm={() => { void handleReload(); }}
      />

      <section class="ics-ops-kpiGrid">
        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Cpu size={14} />モデル読み込み</div>
          <div class="ics-ops-kpiCard__value">{modelInfo?.model_loaded === false ? 'いいえ' : 'はい'}</div>
          <div class="ics-ops-kpiCard__meta">ソース: {modelSourceLabel(modelInfo?.model_source)}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><ShieldAlert size={14} />準備スコア</div>
          <div class="ics-ops-kpiCard__value">{readinessScore == null ? '--' : `${readinessScore}/100`}</div>
          <div class="ics-ops-kpiCard__meta">モデル時刻: {formatDateTime(modelInfo?.model_timestamp || undefined)}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Tag size={14} />クラス数</div>
          <div class="ics-ops-kpiCard__value">{modelInfo?.num_classes ?? 0}</div>
          <div class="ics-ops-kpiCard__meta">平均長: {averageClassLength} 文字</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Layers size={14} />埋め込み次元</div>
          <div class="ics-ops-kpiCard__value">{modelInfo?.embedding_dimension ?? 0}</div>
          <div class="ics-ops-kpiCard__meta">埋め込みモデル: {modelInfo?.embedding_model || '--'}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Box size={14} />アルゴリズム</div>
          <div class="ics-ops-kpiCard__value">{modelInfo?.algorithm || '--'}</div>
          <div class="ics-ops-kpiCard__meta">推定器数: {modelInfo?.n_estimators ?? 0}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Tag size={14} />最長クラス</div>
          <div class="ics-ops-kpiCard__value">{longestClass || '--'}</div>
          <div class="ics-ops-kpiCard__meta">長さ: {longestClass.length || 0}</div>
        </article>
      </section>

      <section class="ics-ops-grid ics-ops-grid--two">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <Cpu size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">モデルメタデータ</span>
          </div>
          <div class="ics-card-body">
            {modelInfo ? (
              <table class="ics-table">
                <tbody>
                  <tr>
                    <td>アルゴリズム</td>
                    <td class="oj-text-right"><strong>{modelInfo.algorithm}</strong></td>
                  </tr>
                  <tr>
                    <td>埋め込みモデル</td>
                    <td class="oj-text-right">{modelInfo.embedding_model}</td>
                  </tr>
                  <tr>
                    <td>埋め込み次元</td>
                    <td class="oj-text-right">{modelInfo.embedding_dimension}</td>
                  </tr>
                  <tr>
                    <td>推定器数</td>
                    <td class="oj-text-right">{modelInfo.n_estimators}</td>
                  </tr>
                  <tr>
                    <td>クラス数</td>
                    <td class="oj-text-right">{modelInfo.num_classes}</td>
                  </tr>
                  <tr>
                    <td>モデルソース</td>
                    <td class="oj-text-right">{modelSourceLabel(modelInfo.model_source)}</td>
                  </tr>
                  <tr>
                    <td>モデル時刻</td>
                    <td class="oj-text-right">{formatDateTime(modelInfo.model_timestamp)}</td>
                  </tr>
                </tbody>
              </table>
            ) : (
              <div class="ics-empty-text">モデル情報がありません</div>
            )}
          </div>
        </div>

        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <ShieldAlert size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">モデル品質の所見</span>
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

            {modelInfo?.training_summary && (
              <div class="ics-ops-inlineStats oj-sm-margin-3x-top">
                {modelInfo.training_summary.test_accuracy != null && (
                  <div>
                    <span>テスト精度</span>
                    <strong>{formatPercentage(modelInfo.training_summary.test_accuracy)}</strong>
                  </div>
                )}
                {modelInfo.training_summary.overfitting_gap != null && (
                  <div>
                    <span>過学習ギャップ</span>
                    <strong>{formatPercentage(modelInfo.training_summary.overfitting_gap)}</strong>
                  </div>
                )}
                {modelInfo.training_summary.selected_algorithm && (
                  <div>
                    <span>選択アルゴリズム</span>
                    <strong>{modelInfo.training_summary.selected_algorithm}</strong>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      <section class="ics-card ics-ops-panel">
        <div class="ics-card-header oj-flex oj-sm-align-items-center">
          <Tag size={18} class="oj-sm-margin-2x-end" />
          <span class="oj-typography-heading-xs">クラス一覧</span>
        </div>

        <div class="ics-card-body">
          <div class="ics-ops-toolbar">
            <label class="ics-ops-searchInput">
              <Search size={14} />
              <input
                type="text"
                value={classQuery}
                placeholder="クラス名を検索"
                onInput={(event) => setClassQuery((event.currentTarget as HTMLInputElement).value)}
              />
            </label>

            <select
              class="ics-ops-select"
              value={classSort}
              onInput={(event) => setClassSort((event.currentTarget as HTMLSelectElement).value as ClassSortMode)}
            >
              <option value="alphabetical">並び替え: A-Z</option>
              <option value="length_desc">並び替え: 長さ（長い順）</option>
              <option value="length_asc">並び替え: 長さ（短い順）</option>
            </select>
          </div>

          {pagedClasses.length > 0 ? (
            <>
              <div class="ics-ops-tagCloud oj-sm-margin-3x-top">
                {pagedClasses.map(cls => (
                  <span key={cls} class="ics-class-tag">
                    {cls}
                  </span>
                ))}
              </div>

              <Pagination
                currentPage={currentPage}
                totalPages={totalPages}
                totalItems={filteredClasses.length}
                goToPageInput={goToPageInput}
                onPageChange={setClassPage}
                onGoToPageInputChange={setGoToPageInput}
                onGoToPage={() => {
                  const pg = parseInt(goToPageInput, 10);
                  if (pg >= 1 && pg <= totalPages) {
                    setClassPage(pg);
                    setGoToPageInput('');
                  }
                }}
                isFirstPage={currentPage <= 1}
                isLastPage={currentPage >= totalPages}
                position="bottom"
                show={totalPages > 1}
              />
            </>
          ) : (
            <div class="ics-empty-text oj-sm-margin-3x-top">該当するクラスがありません。</div>
          )}
        </div>
      </section>

      {candidateRows.length > 0 && (
        <section class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <Tag size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">候補アルゴリズム順位</span>
          </div>
          <div class="ics-card-body">
            <table class="ics-table">
              <thead>
                <tr>
                  <th>アルゴリズム</th>
                  <th>学習</th>
                  <th>テスト</th>
                  <th>ギャップ</th>
                  <th>スコア</th>
                </tr>
              </thead>
              <tbody>
                {candidateRows.map((row, index) => (
                  <tr key={`${row.algorithm}-${index}`}>
                    <td>{row.algorithm}</td>
                    <td>{formatPercentage(row.train_accuracy)}</td>
                    <td>{formatPercentage(row.test_accuracy)}</td>
                    <td>{formatPercentage(row.overfitting_gap)}</td>
                    <td>{row.score}/100</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {modelInfo?.message && (
        <section class="ics-card ics-card-warning ics-ops-panel">
          <div class="ics-card-body oj-flex oj-sm-align-items-center" style={{ gap: '8px' }}>
            <AlertTriangle size={16} />
            <span>{modelInfo.message}</span>
          </div>
        </section>
      )}

      {modelInfo?.model_loaded === false && (
        <section class="ics-card ics-card-error ics-ops-panel">
          <div class="ics-card-body oj-flex oj-sm-align-items-center" style={{ gap: '8px' }}>
            <XCircle size={16} />
            <span>モデルが正常に読み込まれるまで、予測サービスはリクエストを分類できません。</span>
          </div>
        </section>
      )}
    </div>
  );
}
