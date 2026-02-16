/**
 * Train - 学習ワークフロー。
 * データ診断、パラメータ戦略、学習評価を提供。
 */
import { h } from 'preact';
import { useState, useEffect, useCallback, useRef } from 'preact/hooks';
import { useAppSelector, useAppDispatch } from '../../redux/store';
import {
  startTraining,
  fetchTrainingStatus,
  resetTrainingState
} from '../../redux/slices/classifierSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { TrainingStatus } from '../../enums/classifierEnums';
import {
  TrainingDataItem,
  TrainingParams,
  TrainingProfile
} from '../../types/classifierTypes';
import { formatPercentage, formatDuration, apiGet } from '../../utils/apiUtils';
import { Button } from '@oracle/oraclejet-preact/UNSAFE_Button';
import { ProgressCircle } from '@oracle/oraclejet-preact/UNSAFE_ProgressCircle';
import { Pagination } from '../../components/Pagination';
import {
  CheckCircle,
  XCircle,
  Loader,
  Upload,
  Database,
  Settings,
  AlertTriangle,
  GraduationCap,
  Sparkles,
  BarChart3,
  Target,
  Wand2,
  ShieldCheck,
  Zap
} from 'lucide-react';

const DEFAULT_PARAMS: TrainingParams = {
  test_size: 0.15,
  n_estimators: 300,
  learning_rate: 0.05,
  max_depth: 6,
  algorithm_strategy: 'auto',
  compare_baselines: true,
  auto_tune: true,
  rebalance_strategy: 'auto',
  random_state: 42
};

const PAGE_SIZE = 20;
const DISPLAY_ROWS = 10;
const STATUS_POLL_INTERVAL = 3000;

interface PaginatedData {
  items: TrainingDataItem[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

interface ParamTemplate {
  id: 'small_data' | 'imbalanced_data' | 'high_class_count';
  name: string;
  description: string;
  overrides: Partial<TrainingParams>;
}

const PARAM_TEMPLATES: ParamTemplate[] = [
  {
    id: 'small_data',
    name: '少量データ',
    description: 'データが少ない場合の過学習リスクを抑える設定です。',
    overrides: {
      test_size: 0.20,
      n_estimators: 180,
      learning_rate: 0.08,
      max_depth: 4,
      algorithm_strategy: 'auto',
      auto_tune: false,
      compare_baselines: true,
      rebalance_strategy: 'auto'
    }
  },
  {
    id: 'imbalanced_data',
    name: '不均衡データ',
    description: 'リバランスを有効にし、少数クラスの再現率を優先します。',
    overrides: {
      test_size: 0.18,
      n_estimators: 320,
      learning_rate: 0.04,
      max_depth: 5,
      algorithm_strategy: 'auto',
      auto_tune: true,
      compare_baselines: true,
      rebalance_strategy: 'balanced_upsample'
    }
  },
  {
    id: 'high_class_count',
    name: '多クラス',
    description: '意図クラスが多い場合でも学習を安定させます。',
    overrides: {
      test_size: 0.15,
      n_estimators: 420,
      learning_rate: 0.04,
      max_depth: 5,
      algorithm_strategy: 'auto',
      auto_tune: true,
      compare_baselines: true,
      rebalance_strategy: 'auto'
    }
  }
];

function healthClass(score: number | undefined): string {
  if (score == null) return 'trainView__health--neutral';
  if (score >= 80) return 'trainView__health--good';
  if (score >= 60) return 'trainView__health--warn';
  return 'trainView__health--bad';
}

function readinessLabel(readiness: string | undefined): string {
  if (!readiness) return '不明';
  if (readiness === 'high') return '高';
  if (readiness === 'medium') return '中';
  return '低';
}

export function Train() {
  const dispatch = useAppDispatch();
  const trainingState = useAppSelector(state => state.classifier.trainingState);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [params, setParams] = useState<TrainingParams>(DEFAULT_PARAMS);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageData, setPageData] = useState<PaginatedData | null>(null);
  const [isDataLoading, setIsDataLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isProfiling, setIsProfiling] = useState(false);
  const [profile, setProfile] = useState<TrainingProfile | null>(null);
  const [goToPageInput, setGoToPageInput] = useState('');
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);

  const fetchProfile = useCallback(async () => {
    setIsProfiling(true);
    try {
      const p = await apiGet<TrainingProfile>('/api/v1/train/profile');
      setProfile(p);
      return p;
    } catch (err: any) {
      setProfile(null);
      dispatch(addNotification({ type: 'error', message: err.message || '学習データの診断に失敗しました' }));
      return null;
    } finally {
      setIsProfiling(false);
    }
  }, [dispatch]);

  const fetchPageData = useCallback(async (page: number) => {
    setIsDataLoading(true);
    try {
      const data = await apiGet<PaginatedData>(
        `/api/v1/train/data?page=${page}&page_size=${PAGE_SIZE}`
      );
      setPageData(data);
      setCurrentPage(page);
      return data;
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || '学習データの読み込みに失敗しました' }));
      return null;
    } finally {
      setIsDataLoading(false);
    }
  }, [dispatch]);

  useEffect(() => {
    (async () => {
      const data = await fetchPageData(1);
      if (data && data.total > 0) {
        await fetchProfile();
      }
    })();
  }, [fetchPageData, fetchProfile]);

  useEffect(() => {
    if (trainingState.status === TrainingStatus.RUNNING) {
      const interval = setInterval(() => { dispatch(fetchTrainingStatus()); }, STATUS_POLL_INTERVAL);
      return () => clearInterval(interval);
    }
  }, [trainingState.status, dispatch]);

  useEffect(() => {
    if (trainingState.dataset_profile) {
      setProfile(trainingState.dataset_profile);
    }
  }, [trainingState.dataset_profile]);

  const handleFileUpload = useCallback(async (e: Event) => {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    const lowerName = file.name.toLowerCase();
    const isXlsx = lowerName.endsWith('.xlsx');
    const isCsv = lowerName.endsWith('.csv');

    if (!isXlsx && !isCsv) {
      dispatch(addNotification({ type: 'error', message: 'ファイル形式が不正です。.xlsx / .csv を使用してください。' }));
      if (input) input.value = '';
      return;
    }

    setIsUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch('/studio/api/v1/train/data/upload', {
        method: 'POST',
        body: formData,
        credentials: 'same-origin'
      });

      const result = await response.json();

      if (!response.ok) {
        const errorMsg = result.error_messages?.[0] || result.errorMessages?.[0] || result.message || 'アップロードに失敗しました';
        throw new Error(errorMsg);
      }

      const successMsg = result.data?.message || 'アップロードしました';
      dispatch(addNotification({ type: 'success', message: successMsg, autoClose: true }));
      setUploadedFileName(file.name);
      if (result.data?.profile) {
        setProfile(result.data.profile as TrainingProfile);
      }
      await fetchPageData(1);
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || 'アップロードに失敗しました' }));
    } finally {
      setIsUploading(false);
      if (input) input.value = '';
    }
  }, [dispatch, fetchPageData]);

  const handleDownload = useCallback(() => {
    window.open('/studio/api/v1/train/data/download', '_blank');
  }, []);

  const handleClearData = useCallback(async () => {
    try {
      await fetch('/studio/api/v1/train/data', { method: 'DELETE', credentials: 'same-origin' });
      dispatch(addNotification({ type: 'success', message: '学習データをクリアしました', autoClose: true }));
      setUploadedFileName(null);
      setProfile(null);
      await fetchPageData(1);
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || 'データのクリアに失敗しました' }));
    }
  }, [dispatch, fetchPageData]);

  const applySuggestedParams = useCallback(() => {
    if (!profile?.suggested_params) return;
    setParams(prev => ({
      ...prev,
      ...(profile.suggested_params as Partial<TrainingParams>)
    }));
    dispatch(addNotification({ type: 'info', message: '推奨パラメータを適用しました', autoClose: true }));
  }, [profile, dispatch]);

  const refreshDiagnostics = useCallback(async () => {
    const p = await fetchProfile();
    if (p) {
      dispatch(addNotification({ type: 'success', message: 'データ診断を更新しました', autoClose: true }));
    }
  }, [fetchProfile, dispatch]);

  const applyParamTemplate = useCallback((templateId: ParamTemplate['id']) => {
    const template = PARAM_TEMPLATES.find(t => t.id === templateId);
    if (!template) return;
    setParams(prev => ({ ...prev, ...template.overrides }));
    setSelectedTemplate(templateId);
    dispatch(addNotification({
      type: 'info',
      message: `テンプレートを適用しました: ${template.name}`,
      autoClose: true
    }));
  }, [dispatch]);

  const updateNumberParam = (key: keyof TrainingParams, value: string) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return;
    setParams(prev => ({ ...prev, [key]: n }));
  };

  const handleStartTraining = useCallback(async () => {
    if (!pageData || pageData.total === 0) {
      dispatch(addNotification({ type: 'warning', message: '先に学習データをアップロードしてください' }));
      return;
    }

    if (profile && !profile.quality_gate_passed) {
      dispatch(addNotification({ type: 'warning', message: 'データが品質ゲートを通過していません。問題を修正してから学習してください。' }));
      return;
    }

    if (params.test_size < 0.05 || params.test_size > 0.4) {
      dispatch(addNotification({ type: 'warning', message: 'テスト割合は 0.05〜0.40 の範囲にしてください' }));
      return;
    }
    if (params.n_estimators < 50 || params.n_estimators > 1000) {
      dispatch(addNotification({ type: 'warning', message: '推定器数は 50〜1000 の範囲にしてください' }));
      return;
    }
    if (params.learning_rate < 0.01 || params.learning_rate > 0.3) {
      dispatch(addNotification({ type: 'warning', message: '学習率は 0.01〜0.30 の範囲にしてください' }));
      return;
    }
    if (params.max_depth < 2 || params.max_depth > 10) {
      dispatch(addNotification({ type: 'warning', message: '最大深さは 2〜10 の範囲にしてください' }));
      return;
    }

    try {
      await dispatch(startTraining({ training_data: [], params: params as any })).unwrap();
      dispatch(addNotification({ type: 'info', message: '学習を開始しました', autoClose: true }));
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || '学習の開始に失敗しました' }));
    }
  }, [pageData, params, dispatch, profile]);

  const handleReset = () => {
    dispatch(resetTrainingState());
  };

  const isRunning = trainingState.status === TrainingStatus.RUNNING;
  const isCompleted = trainingState.status === TrainingStatus.COMPLETED;
  const isFailed = trainingState.status === TrainingStatus.FAILED;
  const totalData = pageData?.total ?? 0;
  const classEntries = Object.entries(profile?.class_distribution || {});
  const formatOptionalPercent = (value?: number | null): string => (
    value == null ? '--' : formatPercentage(value)
  );
  const formatOptionalNumber = (value?: number | null): string => (
    value == null ? '--' : value.toFixed(4)
  );
  const formatDeltaPercent = (delta?: number | null): string => (
    delta == null ? '--' : `${delta >= 0 ? '+' : ''}${(delta * 100).toFixed(2)}%`
  );
  const formatDeltaNumber = (delta?: number | null): string => (
    delta == null ? '--' : `${delta >= 0 ? '+' : ''}${delta.toFixed(4)}`
  );
  const deltaColor = (delta?: number | null, reverse: boolean = false): string => {
    if (delta == null) return 'var(--aai-neutral-dark-1)';
    if (delta === 0) return 'var(--aai-neutral-dark-1)';
    const good = reverse ? delta < 0 : delta > 0;
    return good ? 'var(--aai-accent2-dark-1)' : 'var(--aai-accent1-solid-1)';
  };

  return (
    <div class="trainView trainView--enhanced">
      <section class="trainView__hero">
        <div class="trainView__heroHeader">
          <div class="genericHeading">
            <div class="genericHeading--headings">
              <h1 class="genericHeading--headings__title genericHeading--headings__title--default">学習</h1>
              <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
                データ診断からパラメータ戦略・評価まで、より安定した高品質な意図モデル作成を支援します。
              </p>
            </div>
          </div>

          <div class="trainView__heroMeta">
            <span class="trainView__heroBadge"><ShieldCheck size={14} /> 健全性: {profile ? `${profile.health_score.toFixed(0)}/100` : '--'}</span>
            <span class="trainView__heroBadge"><Database size={14} /> サンプル: {profile ? profile.total_samples : totalData}</span>
            <span class="trainView__heroBadge"><BarChart3 size={14} /> クラス数: {profile ? profile.num_classes : '--'}</span>
          </div>
        </div>

        <div class="trainView__heroMetrics">
          <div class="trainView__heroMetric">
            <div class="trainView__heroMetricLabel">データ健全性</div>
            <div class="trainView__heroMetricValue">{profile ? `${profile.health_score.toFixed(1)}/100` : '--'}</div>
          </div>
          <div class="trainView__heroMetric">
            <div class="trainView__heroMetricLabel">準備度</div>
            <div class="trainView__heroMetricValue">{readinessLabel(profile?.readiness)}</div>
          </div>
          <div class="trainView__heroMetric">
            <div class="trainView__heroMetricLabel">不均衡比</div>
            <div class="trainView__heroMetricValue">{profile ? `${profile.imbalance_ratio.toFixed(2)}:1` : '--'}</div>
          </div>
          <div class="trainView__heroMetric">
            <div class="trainView__heroMetricLabel">品質ゲート</div>
            <div class="trainView__heroMetricValue">{profile ? (profile.quality_gate_passed ? '通過' : '要修正') : '--'}</div>
          </div>
        </div>
      </section>

      <div class="genericHeading oj-sm-margin-8x-top">
        <div class="genericHeading--headings">
          <h1 class="genericHeading--headings__title genericHeading--headings__title--default">学習データ</h1>
          <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
            学習前にデータをアップロードし、確認・診断します。
          </p>
        </div>
      </div>

      <div class="oj-panel oj-sm-padding-7x oj-sm-margin-4x-top trainView__panel">
        <div class="trainView__panelHeader">
          <div class="trainView__panelHeaderLeft">
            <figure class="genericIcon genericIcon__extra-small genericIcon__primaryDark">
              <Database size={20} strokeWidth={2} />
            </figure>
            <div>
              <span class="oj-typography-subheading-xs">データセット</span>
              <p class="oj-typography-body-sm oj-text-color-secondary trainView__panelSubtitle">
                {totalData > 0 ? `${totalData} 件を読み込み済み` : '学習データをアップロードしてください'}
              </p>
            </div>
          </div>
          <div class="trainView__panelHeaderActions">
            <Button
              label={isProfiling ? '分析中…' : 'データを分析'}
              variant="outlined"
              onAction={() => { void refreshDiagnostics(); }}
              isDisabled={isProfiling || isRunning || totalData === 0}
            />
            <Button
              label="推奨パラメータを適用"
              variant="outlined"
              onAction={applySuggestedParams}
              isDisabled={!profile?.suggested_params || isRunning}
            />
          </div>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.csv"
          class="trainView__hiddenFileInput"
          onChange={handleFileUpload}
        />

        <div
          class={`predictView__dropZone${isRunning || isUploading ? ' trainView__dropZone--disabled' : ''}`}
          onClick={() => !isRunning && !isUploading && fileInputRef.current?.click()}
          onDragOver={(e: DragEvent) => {
            if (isRunning || isUploading) return;
            e.preventDefault();
            e.stopPropagation();
            (e.currentTarget as HTMLElement).classList.add('predictView__dropZone--active');
          }}
          onDragLeave={(e: DragEvent) => {
            e.preventDefault();
            (e.currentTarget as HTMLElement).classList.remove('predictView__dropZone--active');
          }}
          onDrop={(e: DragEvent) => {
            if (isRunning || isUploading) return;
            e.preventDefault();
            (e.currentTarget as HTMLElement).classList.remove('predictView__dropZone--active');
            const file = e.dataTransfer?.files?.[0];
            if (file) {
              const dt = new DataTransfer();
              dt.items.add(file);
              if (fileInputRef.current) {
                fileInputRef.current.files = dt.files;
                fileInputRef.current.dispatchEvent(new Event('change', { bubbles: true }));
              }
            }
          }}
        >
          {isUploading ? (
            <Loader size={24} strokeWidth={1.5} class="ics-spin trainView__dropZoneIcon" />
          ) : (
            <Upload size={24} strokeWidth={1.5} class="trainView__dropZoneIcon" />
          )}
          <span class="oj-typography-body-md">
            {isUploading ? (
              <span>アップロード中…</span>
            ) : uploadedFileName ? (
              <span>現在: <strong>{uploadedFileName}</strong></span>
            ) : (
              'ここにファイルをドロップするか、クリックしてアップロード'
            )}
          </span>
          <span class="oj-typography-body-sm oj-text-color-secondary trainView__dropZoneHint">
            対応形式: .xlsx / .csv（"text" と "label" 列）
          </span>
        </div>

        <div class="trainView__panelFooterActions oj-sm-margin-4x-top">
          <Button label="ダウンロード" variant="outlined" onAction={handleDownload} isDisabled={totalData === 0} />
          <Button label="クリア" variant="outlined" onAction={() => { void handleClearData(); }} isDisabled={isRunning || totalData === 0} />
        </div>

        {profile && (
          <div class="trainView__diagnostics oj-sm-margin-4x-top">
            <div class="trainView__diagnosticsHead">
              <div class="trainView__diagnosticsTitle"><Sparkles size={15} /> データ診断</div>
              <span class={`trainView__gateBadge ${profile.quality_gate_passed ? 'trainView__gateBadge--ok' : 'trainView__gateBadge--blocked'}`}>
                {profile.quality_gate_passed ? '品質ゲート: 通過' : '品質ゲート: 要修正'}
              </span>
            </div>

            {profile.issue_details.length > 0 ? (
              <div class="trainView__issueList">
                {profile.issue_details.map((issue, idx) => (
                  <div key={`${issue.level}-${idx}`} class={`trainView__issueItem trainView__issueItem--${issue.level}`}>
                    <AlertTriangle size={13} />
                    <span>{issue.message}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div class="trainView__issueItem trainView__issueItem--info">
                <CheckCircle size={13} />
                <span>重大な品質問題は検出されませんでした。</span>
              </div>
            )}

            {profile.recommendations.length > 0 && (
              <div class="trainView__recommendations">
                <div class="trainView__diagnosticsTitle"><Wand2 size={15} /> 推奨事項</div>
                {profile.recommendations.map((r, idx) => (
                  <div key={`rec-${idx}`} class="trainView__recommendationItem">{r}</div>
                ))}
              </div>
            )}
          </div>
        )}

        <div class="oj-sm-margin-4x-top">
          {isDataLoading ? (
            <div class="trainView__loadingRow">
              <ProgressCircle value={-1} size="sm" />
              <span class="oj-typography-body-md oj-text-color-secondary trainView__loadingText">読み込み中…</span>
            </div>
          ) : totalData === 0 ? (
            <div class="trainView__emptyState">
              <Database size={40} strokeWidth={1.5} class="trainView__emptyIcon" />
              <p class="oj-typography-body-md trainView__emptyTitle">学習データがまだありません。</p>
              <p class="oj-typography-body-sm oj-text-color-secondary trainView__emptySubtitle">
                "text" と "label" 列を含む Excel（.xlsx）をアップロードしてください。
              </p>
            </div>
          ) : (
            <div>
              {pageData && (
                <Pagination
                  currentPage={currentPage}
                  totalPages={pageData.total_pages}
                  totalItems={pageData.total}
                  goToPageInput={goToPageInput}
                  onPageChange={(page) => fetchPageData(page)}
                  onGoToPageInputChange={setGoToPageInput}
                  onGoToPage={() => {
                    const pg = parseInt(goToPageInput, 10);
                    if (pg >= 1 && pg <= pageData.total_pages) {
                      fetchPageData(pg);
                      setGoToPageInput('');
                    }
                  }}
                  isFirstPage={currentPage <= 1}
                  isLastPage={currentPage >= pageData.total_pages}
                  position="top"
                  show={pageData.total_pages > 1}
                />
              )}

              <div class="trainView__tableContainer" style={{ maxHeight: `${DISPLAY_ROWS * 41 + 42}px` }}>
                <table class="ics-table ics-table--sticky">
                  <thead>
                    <tr>
                      <th style={{ width: '60px' }}>#</th>
                      <th>テキスト</th>
                      <th style={{ width: '160px' }}>ラベル</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pageData!.items.map((item, idx) => (
                      <tr key={idx}>
                        <td class="ics-text-muted">
                          {(currentPage - 1) * PAGE_SIZE + idx + 1}
                        </td>
                        <td>{item.text}</td>
                        <td><span class="ics-class-tag">{item.label}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {pageData && (
                <Pagination
                  currentPage={currentPage}
                  totalPages={pageData.total_pages}
                  totalItems={pageData.total}
                  goToPageInput={goToPageInput}
                  onPageChange={(page) => fetchPageData(page)}
                  onGoToPageInputChange={setGoToPageInput}
                  onGoToPage={() => {
                    const pg = parseInt(goToPageInput, 10);
                    if (pg >= 1 && pg <= pageData.total_pages) {
                      fetchPageData(pg);
                      setGoToPageInput('');
                    }
                  }}
                  isFirstPage={currentPage <= 1}
                  isLastPage={currentPage >= pageData.total_pages}
                  position="bottom"
                  show={pageData.total_pages > 1}
                />
              )}
            </div>
          )}
        </div>

        {classEntries.length > 0 && (
          <div class="oj-sm-margin-4x-top">
            <div class="trainView__diagnosticsTitle"><BarChart3 size={15} /> クラス分布</div>
            <div class="trainView__distributionGrid">
              {classEntries.slice(0, 16).map(([label, count]) => {
                const percent = profile?.class_distribution_percent?.[label] || 0;
                return (
                  <div class="trainView__distributionItem" key={label}>
                    <div class="trainView__distributionLabel">{label}</div>
                    <div class="trainView__distributionMeta">{count} 件 - {percent.toFixed(1)}%</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div class="genericHeading oj-sm-margin-8x-top">
        <div class="genericHeading--headings">
          <h1 class="genericHeading--headings__title genericHeading--headings__title--default">学習戦略</h1>
          <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
            ハイパーパラメータと最適化戦略を設定して汎化性能を改善します。
          </p>
        </div>
      </div>

      <div class="trainView__templateGrid oj-sm-margin-4x-top">
        {PARAM_TEMPLATES.map(template => {
          const isRecommended = (
            (template.id === 'small_data' && (profile?.total_samples || 0) > 0 && (profile?.total_samples || 0) < 120) ||
            (template.id === 'imbalanced_data' && (profile?.imbalance_ratio || 0) >= 3) ||
            (template.id === 'high_class_count' && (profile?.num_classes || 0) >= 20)
          );
          return (
            <div
              key={template.id}
              class={`trainView__templateCard ${selectedTemplate === template.id ? 'trainView__templateCard--selected' : ''}`}
            >
              <div class="trainView__templateHead">
                <div class="trainView__templateName">{template.name}</div>
                {isRecommended && <span class="trainView__templateBadge">推奨</span>}
              </div>
              <div class="trainView__templateDesc">{template.description}</div>
              <Button
                label="テンプレートを適用"
                variant="outlined"
                onAction={() => applyParamTemplate(template.id)}
                isDisabled={isRunning}
              />
            </div>
          );
        })}
      </div>

      <div class="trainView__paramsGrid oj-sm-margin-4x-top">
        {[
          { label: 'テスト割合', key: 'test_size', min: 0.05, max: 0.4, step: 0.05, desc: '評価に確保する割合' },
          { label: '推定器数', key: 'n_estimators', min: 50, max: 1000, step: 50, desc: 'ブースティングの反復回数' },
          { label: '学習率', key: 'learning_rate', min: 0.01, max: 0.3, step: 0.01, desc: '各ステージの更新幅' },
          { label: '最大深さ', key: 'max_depth', min: 2, max: 10, step: 1, desc: '木の最大深さ' }
        ].map(p => (
          <div key={p.key} class="oj-panel oj-sm-padding-7x trainView__panel">
            <div class="trainView__panelMiniHeader">
              <figure class="genericIcon genericIcon__extra-small genericIcon__neutralLight">
                <Settings size={18} strokeWidth={2} />
              </figure>
              <span class="oj-typography-subheading-xs">{p.label}</span>
            </div>
            <p class="oj-typography-body-sm oj-text-color-secondary trainView__panelDesc">{p.desc}</p>
            <input
              type="number"
              class="ics-input"
              min={p.min}
              max={p.max}
              step={p.step}
              value={(params as any)[p.key]}
              onInput={(e: any) => updateNumberParam(p.key as keyof TrainingParams, e.target.value)}
              disabled={isRunning}
            />
          </div>
        ))}

        <div class="oj-panel oj-sm-padding-7x trainView__panel">
          <div class="trainView__panelMiniHeader">
            <figure class="genericIcon genericIcon__extra-small genericIcon__neutralLight">
              <Zap size={18} strokeWidth={2} />
            </figure>
            <span class="oj-typography-subheading-xs">高度な最適化</span>
          </div>

          <p class="oj-typography-body-sm oj-text-color-secondary trainView__panelDesc">
            自動チューニングとリバランス戦略で、不均衡データでの汎化性能を改善します。
          </p>

          <div class="trainView__controlGroup">
            <label class="trainView__fieldLabel">アルゴリズム戦略</label>
            <select
              class="ics-input"
              value={params.algorithm_strategy || 'auto'}
              onChange={(e: any) => setParams({ ...params, algorithm_strategy: e.target.value })}
              disabled={isRunning}
            >
              <option value="auto">自動（GBDT + LR ベースライン）</option>
              <option value="gbdt">GBDT のみ</option>
              <option value="lr">ロジスティック回帰のみ</option>
            </select>
          </div>

          <div class="trainView__controlGroup">
            <label class="trainView__fieldLabel">リバランス戦略</label>
            <select
              class="ics-input"
              value={params.rebalance_strategy || 'auto'}
              onChange={(e: any) => setParams({ ...params, rebalance_strategy: e.target.value as any })}
              disabled={isRunning}
            >
              <option value="auto">自動（診断に基づく）</option>
              <option value="balanced_upsample">バランス・アップサンプル</option>
              <option value="none">なし</option>
            </select>
          </div>

          <div class="trainView__controlGroup">
            <label class="trainView__fieldLabel">乱数シード</label>
            <input
              type="number"
              class="ics-input"
              min={0}
              step={1}
              value={params.random_state || 42}
              onInput={(e: any) => updateNumberParam('random_state', e.target.value)}
              disabled={isRunning}
            />
          </div>

          <div class="trainView__switchRow">
            <label class="trainView__switchItem">
              <input
                type="checkbox"
                checked={Boolean(params.auto_tune)}
                onChange={(e: any) => setParams({ ...params, auto_tune: Boolean(e.target.checked) })}
                disabled={isRunning}
              />
              <span>自動チューニングを有効化</span>
            </label>
            <label class="trainView__switchItem">
              <input
                type="checkbox"
                checked={Boolean(params.compare_baselines)}
                onChange={(e: any) => setParams({ ...params, compare_baselines: Boolean(e.target.checked) })}
                disabled={isRunning}
              />
              <span>ベースラインを比較</span>
            </label>
          </div>
        </div>
      </div>

      <div class="genericHeading oj-sm-margin-8x-top">
        <div class="genericHeading--headings">
          <h1 class="genericHeading--headings__title genericHeading--headings__title--default">モデル学習</h1>
          <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
            現在の設定で学習を開始し、品質指標をリアルタイムに確認します。
          </p>
        </div>
      </div>

      <div class="oj-panel oj-sm-padding-7x oj-sm-margin-4x-top trainView__panel">
        <div class="trainView__panelHeader">
          <div class="trainView__panelHeaderLeft">
            <figure class="genericIcon genericIcon__extra-small genericIcon__accent2Dark">
              <GraduationCap size={20} strokeWidth={2} />
            </figure>
            <div>
              <span class="oj-typography-subheading-xs">モデル学習</span>
              <p class="oj-typography-body-sm oj-text-color-secondary trainView__panelSubtitle">
                {totalData > 0 ? `${totalData} 件で準備完了` : '学習データをアップロードしてください'}
              </p>
            </div>
          </div>

          {profile && (
            <div class={`trainView__gateBadge ${profile.quality_gate_passed ? 'trainView__gateBadge--ok' : 'trainView__gateBadge--blocked'}`}>
              {profile.quality_gate_passed ? '学習可能' : '先にデータを修正'}
            </div>
          )}
        </div>

        <div class="trainView__runActions oj-sm-margin-4x-bottom">
          <Button
            label={isRunning ? '学習中…' : '学習を開始'}
            onAction={() => { void handleStartTraining(); }}
            isDisabled={isRunning || totalData === 0 || (profile ? !profile.quality_gate_passed : false)}
          />
          {(isCompleted || isFailed) && (
            <Button
              label="リセット"
              variant="outlined"
              onAction={handleReset}
            />
          )}
        </div>

        {trainingState.status !== TrainingStatus.IDLE && (
          <div
            class="trainView__statusPanel"
            style={{
              backgroundColor: isCompleted
              ? 'var(--aai-accent2-light-2)'
              : isFailed
                ? 'var(--aai-accent1-light-2)'
                : 'var(--aai-neutral-light-3)',
              border: `1px solid ${isCompleted
              ? 'var(--aai-accent2-lines-2)'
              : isFailed
                ? 'var(--aai-accent1-lines-2)'
                : 'var(--aai-neutral-interactive-1)'}`
            }}
          >
            <div class="trainView__statusHeader">
              {isRunning && <ProgressCircle value={-1} size="sm" />}
              {isCompleted && <CheckCircle size={18} class="trainView__qualityGood" />}
              {isFailed && <XCircle size={18} class="trainView__qualityIssues" />}
              <span class="oj-typography-subheading-xs">
                {isRunning ? '学習を実行中' : isCompleted ? '学習が完了しました' : '学習に失敗しました'}
              </span>
            </div>

            <p class="oj-typography-body-md trainView__statusText">{trainingState.progress}</p>
            {trainingState.error && (
              <p class="oj-typography-body-md trainView__statusError">
                {trainingState.error}
              </p>
            )}

            {trainingState.results && (
              <div class="trainView__resultsGrid oj-sm-margin-4x-top">
                <div class="trainView__resultItem">
                    <span class="oj-typography-body-sm oj-text-color-secondary">学習精度</span>
                  <span class="oj-typography-subheading-xs">{formatPercentage(trainingState.results.train_accuracy)}</span>
                </div>
                <div class="trainView__resultItem">
                    <span class="oj-typography-body-sm oj-text-color-secondary">テスト精度</span>
                  <span class="oj-typography-subheading-xs">{formatPercentage(trainingState.results.test_accuracy)}</span>
                </div>
                <div class="trainView__resultItem">
                    <span class="oj-typography-body-sm oj-text-color-secondary">テスト Macro-F1</span>
                  <span class="oj-typography-subheading-xs">
                    {trainingState.results.test_macro_f1 != null ? formatPercentage(trainingState.results.test_macro_f1) : '--'}
                  </span>
                </div>
                <div class="trainView__resultItem">
                    <span class="oj-typography-body-sm oj-text-color-secondary">Weighted-F1</span>
                  <span class="oj-typography-subheading-xs">
                    {trainingState.results.test_weighted_f1 != null ? formatPercentage(trainingState.results.test_weighted_f1) : '--'}
                  </span>
                </div>
                <div class="trainView__resultItem">
                    <span class="oj-typography-body-sm oj-text-color-secondary">過学習ギャップ</span>
                  <span class="oj-typography-subheading-xs">{(trainingState.results.overfitting_gap * 100).toFixed(2)}%</span>
                </div>
                <div class="trainView__resultItem">
                    <span class="oj-typography-body-sm oj-text-color-secondary">Macro-F1 ギャップ</span>
                  <span class="oj-typography-subheading-xs">
                    {trainingState.results.macro_f1_gap != null ? `${(trainingState.results.macro_f1_gap * 100).toFixed(2)}%` : '--'}
                  </span>
                </div>
                <div class="trainView__resultItem">
                    <span class="oj-typography-body-sm oj-text-color-secondary">選択アルゴリズム</span>
                  <span class="oj-typography-subheading-xs">{trainingState.results.selected_algorithm || '--'}</span>
                </div>
                <div class="trainView__resultItem">
                    <span class="oj-typography-body-sm oj-text-color-secondary">学習時間</span>
                  <span class="oj-typography-subheading-xs">
                    {trainingState.results.training_duration_seconds != null
                      ? formatDuration(trainingState.results.training_duration_seconds)
                      : '--'}
                  </span>
                </div>

                <div class="trainView__resultItem">
                    <span class="oj-typography-body-sm oj-text-color-secondary">品質</span>
                  <span class="oj-typography-subheading-xs">
                    {trainingState.results.quality_ok
                      ? <span class="trainView__qualityGood">良好</span>
                      : <span class="trainView__qualityIssues">要対応</span>}
                  </span>
                </div>

                {trainingState.results.quality_issues.length > 0 && (
                  <div class="trainView__gridFull">
                    {trainingState.results.quality_issues.map((q, i) => (
                      <div key={i} class="trainView__questionRow">
                        <AlertTriangle size={13} class="trainView__questionIcon" />
                        <span class="oj-typography-body-sm trainView__questionText">{q}</span>
                      </div>
                    ))}
                  </div>
                )}

                {trainingState.results.previous_model_summary && trainingState.results.comparison_with_previous && (
                  <div class="trainView__gridFull oj-sm-margin-2x-top">
                    <span class="oj-typography-body-sm oj-text-color-secondary">現行モデルとの比較</span>
                    <p class="oj-typography-body-sm trainView__comparisonSummary">
                      {trainingState.results.comparison_with_previous.summary}
                    </p>
                    <table class="ics-table">
                      <thead>
                        <tr>
                          <th>指標</th>
                          <th style={{ width: '120px' }}>以前</th>
                          <th style={{ width: '120px' }}>現在</th>
                          <th style={{ width: '120px' }}>差分</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>テスト精度</td>
                          <td>{formatOptionalPercent(trainingState.results.previous_model_summary.test_accuracy)}</td>
                          <td>{formatOptionalPercent(trainingState.results.test_accuracy)}</td>
                          <td style={{ color: deltaColor(trainingState.results.comparison_with_previous.test_accuracy_delta) }}>
                            {formatDeltaPercent(trainingState.results.comparison_with_previous.test_accuracy_delta)}
                          </td>
                        </tr>
                        <tr>
                          <td>テスト Macro-F1</td>
                          <td>{formatOptionalPercent(trainingState.results.previous_model_summary.test_macro_f1)}</td>
                          <td>{formatOptionalPercent(trainingState.results.test_macro_f1)}</td>
                          <td style={{ color: deltaColor(trainingState.results.comparison_with_previous.test_macro_f1_delta) }}>
                            {formatDeltaPercent(trainingState.results.comparison_with_previous.test_macro_f1_delta)}
                          </td>
                        </tr>
                        <tr>
                          <td>過学習ギャップ</td>
                          <td>{formatOptionalPercent(trainingState.results.previous_model_summary.overfitting_gap)}</td>
                          <td>{formatOptionalPercent(trainingState.results.overfitting_gap)}</td>
                          <td style={{ color: deltaColor(trainingState.results.comparison_with_previous.overfitting_gap_delta, true) }}>
                            {formatDeltaPercent(trainingState.results.comparison_with_previous.overfitting_gap_delta)}
                          </td>
                        </tr>
                        <tr>
                          <td>選択スコア</td>
                          <td>{formatOptionalNumber(trainingState.results.previous_model_summary.selection_score)}</td>
                          <td>{formatOptionalNumber(trainingState.results.selection_score)}</td>
                          <td style={{ color: deltaColor(trainingState.results.comparison_with_previous.selection_score_delta) }}>
                            {formatDeltaNumber(trainingState.results.comparison_with_previous.selection_score_delta)}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                )}

                {trainingState.results.candidates && trainingState.results.candidates.length > 0 && (
                  <div class="trainView__gridFull oj-sm-margin-2x-top">
                    <span class="oj-typography-body-sm oj-text-color-secondary">候補比較</span>
                    <table class="ics-table oj-sm-margin-2x-top">
                      <thead>
                        <tr>
                          <th>アルゴリズム</th>
                          <th style={{ width: '110px' }}>学習</th>
                          <th style={{ width: '110px' }}>テスト</th>
                          <th style={{ width: '120px' }}>Macro-F1</th>
                          <th style={{ width: '100px' }}>ギャップ</th>
                          <th style={{ width: '100px' }}>スコア</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trainingState.results.candidates.map((c, idx) => (
                          <tr key={`${c.algorithm}-${idx}`}>
                            <td>{c.algorithm}</td>
                            <td>{formatPercentage(c.train_accuracy)}</td>
                            <td>{formatPercentage(c.test_accuracy)}</td>
                            <td>{c.test_macro_f1 != null ? formatPercentage(c.test_macro_f1) : '--'}</td>
                            <td>{(c.overfitting_gap * 100).toFixed(2)}%</td>
                            <td>{c.selection_score != null ? c.selection_score.toFixed(4) : '--'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {trainingState.results.per_class_metrics && trainingState.results.per_class_metrics.length > 0 && (
                  <div class="trainView__gridFull oj-sm-margin-2x-top">
                    <span class="oj-typography-body-sm oj-text-color-secondary">クラス別品質（サポート上位 12 件）</span>
                    <table class="ics-table oj-sm-margin-2x-top">
                      <thead>
                        <tr>
                          <th>意図</th>
                          <th style={{ width: '100px' }}>適合率</th>
                          <th style={{ width: '100px' }}>再現率</th>
                          <th style={{ width: '100px' }}>F1</th>
                          <th style={{ width: '80px' }}>Support</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...trainingState.results.per_class_metrics]
                          .sort((a, b) => b.support - a.support)
                          .slice(0, 12)
                          .map((m, idx) => (
                            <tr key={`${m.intent}-${idx}`}>
                              <td>{m.intent}</td>
                              <td>{formatPercentage(m.precision)}</td>
                              <td>{formatPercentage(m.recall)}</td>
                              <td>{formatPercentage(m.f1_score)}</td>
                              <td>{m.support}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {trainingState.results.params_used && (
                  <div class="trainView__gridFull oj-sm-margin-1x-top">
                    <span class="oj-typography-body-sm oj-text-color-secondary">使用パラメータ</span>
                    <div class="trainView__paramBadges oj-sm-margin-2x-top">
                      {Object.entries(trainingState.results.params_used).map(([k, v]) => (
                        <span key={k} class="trainView__paramBadge">{k}: {String(v)}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
