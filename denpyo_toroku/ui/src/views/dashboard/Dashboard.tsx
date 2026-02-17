/**
 * Dashboard - 伝票処理状況の概要ダッシュボード
 */
import { h } from 'preact';
import { useCallback, useEffect, useState } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { fetchHealth, fetchDashboardStats } from '../../redux/slices/denpyoSlice';
import { t } from '../../i18n';
import {
  Activity,
  CheckCircle,
  Clock,
  FileUp,
  FolderOpen,
  Layers,
  RefreshCw,
  Server,
  XCircle
} from 'lucide-react';

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return `${date.toLocaleDateString('ja-JP')} ${date.toLocaleTimeString('ja-JP')}`;
}

function formatRelativeTime(timestamp: string): string {
  const now = Date.now();
  const then = new Date(timestamp).getTime();
  const diff = Math.floor((now - then) / 1000);
  if (diff < 60) return `${diff}秒前`;
  if (diff < 3600) return `${Math.floor(diff / 60)}分前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}時間前`;
  return `${Math.floor(diff / 86400)}日前`;
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
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

      {/* 最近のアクティビティ */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <Clock size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">{t('dashboard.recentActivity')}</span>
          </div>
          <div class="ics-card-body">
            {stats?.recent_activities && stats.recent_activities.length > 0 ? (
              <table class="ics-table">
                <thead>
                  <tr>
                    <th>種別</th>
                    <th>ファイル名</th>
                    <th>状態</th>
                    <th>日時</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.recent_activities.map((activity) => (
                    <tr key={activity.id}>
                      <td>
                        <span class={`ics-badge ${activity.type === 'UPLOAD' ? 'ics-badge-info' : 'ics-badge-success'}`}>
                          {activity.type === 'UPLOAD' ? t('dashboard.activity.upload') : t('dashboard.activity.registration')}
                        </span>
                      </td>
                      <td>{activity.file_name}</td>
                      <td>
                        {activity.status === 'SUCCESS'
                          ? <CheckCircle size={14} class="ics-icon-success" />
                          : <XCircle size={14} class="ics-icon-error" />
                        }
                      </td>
                      <td class="oj-text-color-secondary">{formatRelativeTime(activity.timestamp)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div class="ics-empty-text">{t('dashboard.noData')}</div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
