/**
 * Dashboard - 伝票処理状況の概要ダッシュボード
 */
import { useCallback, useEffect, useState } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { fetchHealth, fetchDashboardStats } from '../../redux/slices/denpyoSlice';
import { t } from '../../i18n';
import {
  Activity,
  CheckCircle,
  FileUp,
  FolderOpen,
  Layers,
  RefreshCw,
  Server,
} from 'lucide-react';

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return `${date.toLocaleDateString('ja-JP')} ${date.toLocaleTimeString('ja-JP')}`;
}


export function Dashboard() {
  const dispatch = useAppDispatch();
  const health = useAppSelector(state => state.denpyo.health);
  const dashboardStats = useAppSelector(state => state.denpyo.dashboardStats);
  const isHealthLoading = useAppSelector(state => state.denpyo.isHealthLoading);
  const isDashboardLoading = useAppSelector(state => state.denpyo.isDashboardLoading);

  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);

  const refreshData = useCallback(async () => {
    try {
      await Promise.all([
        dispatch(fetchHealth()).unwrap(),
        dispatch(fetchDashboardStats()).unwrap()
      ]);
      setLastUpdatedAt(new Date().toISOString());
    } catch {
      // エラー時も既存データを保持
      setLastUpdatedAt(new Date().toISOString());
    }
  }, [dispatch]);

  useEffect(() => {
    void refreshData();
  }, [refreshData]);

  const isRefreshing = isHealthLoading || isDashboardLoading;
  const stats = dashboardStats;

  const statusLabel = health?.status === 'healthy' ? '正常' : health?.status || '不明';
  const StatusIcon = health?.status === 'healthy' ? CheckCircle : Activity;

  return (
    <div class="ics-dashboard ics-dashboard--enhanced">
      {/* ヘッダー */}
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>{t('dashboard.title')}</h2>
            <p class="ics-ops-hero__subtitle">{t('dashboard.subtitle')}</p>
          </div>
          <div class="ics-ops-hero__controls">
            <button
              class="ics-ops-btn ics-ops-btn--primary"
              onClick={() => { void refreshData(); }}
              disabled={isRefreshing}
            >
              <RefreshCw size={14} class={isRefreshing ? 'ics-spin' : ''} />
              <span>{isRefreshing ? t('dashboard.refreshing') : t('dashboard.refresh')}</span>
            </button>
          </div>
        </div>
        <div class="ics-ops-hero__meta">
          <span>{t('dashboard.lastUpdated')}: {formatDateTime(lastUpdatedAt)}</span>
        </div>
      </section>

      {/* KPI カード */}
      <section class="ics-ops-kpiGrid">
        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Server size={14} />{t('dashboard.card.serviceStatus')}</div>
          <div class="ics-ops-kpiCard__value">{statusLabel}</div>
          <div class={`ics-status-badge ${health?.status === 'healthy' ? 'ics-status-healthy' : 'ics-status-unknown'}`}>
            <StatusIcon size={16} />
            <span>{health?.message || 'v' + (health?.version || '--')}</span>
          </div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><FileUp size={14} />{t('dashboard.card.totalFiles')}</div>
          <div class="ics-ops-kpiCard__value">{stats?.upload_stats?.total_files ?? 0}</div>
          <div class="ics-ops-kpiCard__meta">{t('dashboard.card.thisMonth')}: {stats?.upload_stats?.this_month ?? 0}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><FolderOpen size={14} />{t('dashboard.card.totalRegistrations')}</div>
          <div class="ics-ops-kpiCard__value">{stats?.registration_stats?.total_registrations ?? 0}</div>
          <div class="ics-ops-kpiCard__meta">{t('dashboard.card.thisMonth')}: {stats?.registration_stats?.this_month ?? 0}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Layers size={14} />{t('dashboard.card.totalCategories')}</div>
          <div class="ics-ops-kpiCard__value">{stats?.category_stats?.total_categories ?? 0}</div>
          <div class="ics-ops-kpiCard__meta">{t('dashboard.card.activeCategories')}: {stats?.category_stats?.active_categories ?? 0}</div>
        </article>
      </section>

    </div>
  );
}
