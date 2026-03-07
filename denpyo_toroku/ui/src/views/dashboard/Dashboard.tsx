/**
 * Dashboard - 伝票処理状況の概要ダッシュボード
 */
import { useCallback, useEffect, useState } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { useNavigate } from 'react-router-dom';
import { fetchHealth, fetchDashboardStats } from '../../redux/slices/denpyoSlice';
import { FEATURE_ROUTES, type FeatureRouteKey } from '../../constants/routes';
import { t } from '../../i18n';
import {
  Activity,
  ArrowRight,
  CheckCircle,
  Database,
  FileText,
  Files,
  FolderOpen,
  Layers,
  RefreshCw,
  Search,
  Server,
  Tags,
  Upload,
  ClipboardList,
  type LucideIcon,
} from 'lucide-react';
import { StatusBadge } from '../../components/common/StatusBadge';

interface DashboardActivityItem {
  type?: string;
  status?: string;
  description?: string;
  file_name?: string;
  timestamp?: string;
  created_at?: string;
}

interface FeatureCard {
  id: FeatureRouteKey;
  titleKey: Parameters<typeof t>[0];
  descriptionKey: Parameters<typeof t>[0];
  metricKey: Parameters<typeof t>[0];
  metricValue: (stats: any) => number;
  Icon: LucideIcon;
}

const featureCards: FeatureCard[] = [
  {
    id: 'upload',
    titleKey: 'nav.upload',
    descriptionKey: 'dashboard.feature.upload.description',
    metricKey: 'dashboard.metric.totalUploads',
    metricValue: stats => stats?.upload_stats?.total_files ?? 0,
    Icon: Upload
  },
  {
    id: 'fileList',
    titleKey: 'nav.fileList',
    descriptionKey: 'dashboard.feature.fileList.description',
    metricKey: 'dashboard.metric.totalRegistrations',
    metricValue: stats => stats?.registration_stats?.total_registrations ?? 0,
    Icon: ClipboardList
  },
  {
    id: 'categorySamples',
    titleKey: 'nav.categorySamples',
    descriptionKey: 'dashboard.feature.categorySamples.description',
    metricKey: 'dashboard.metric.totalCategories',
    metricValue: stats => stats?.category_stats?.total_categories ?? 0,
    Icon: Files
  },
  {
    id: 'categoryManagement',
    titleKey: 'nav.categoryManagement',
    descriptionKey: 'dashboard.feature.categoryManagement.description',
    metricKey: 'dashboard.metric.activeCategories',
    metricValue: stats => stats?.category_stats?.active_categories ?? 0,
    Icon: Tags
  },
  {
    id: 'search',
    titleKey: 'nav.dataSearch',
    descriptionKey: 'dashboard.feature.search.description',
    metricKey: 'dashboard.metric.searchableRows',
    metricValue: stats => stats?.registration_stats?.total_registrations ?? 0,
    Icon: Search
  }
];

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
  const navigate = useNavigate();

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
  const activities = (stats?.recent_activities ?? []) as DashboardActivityItem[];

  const statusLabel = health?.status === 'healthy' ? '正常' : health?.status || '不明';
  const StatusIcon = health?.status === 'healthy' ? CheckCircle : Activity;

  const goToView = (viewId: FeatureCard['id']) => {
    navigate(FEATURE_ROUTES[viewId]);
  };

  const getActivityLabel = (item: DashboardActivityItem) => {
    const type = (item.type || '').toUpperCase();
    if (type.includes('UPLOAD')) return t('dashboard.activity.upload');
    if (type.includes('REGISTER')) return t('dashboard.activity.registration');
    return t('dashboard.activity.other');
  };

  const getActivityMessage = (item: DashboardActivityItem) => {
    return item.file_name || item.description || '--';
  };

  const getActivityAt = (item: DashboardActivityItem) => {
    return formatDateTime(item.timestamp || item.created_at);
  };

  return (
    <div class="ics-dashboard ics-dashboard--enhanced">
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

      <section class="ics-ops-kpiGrid">
        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Server size={14} />{t('dashboard.card.serviceStatus')}</div>
          <div class="ics-ops-kpiCard__value">{statusLabel}</div>
          <StatusBadge
            variant={health?.status === 'healthy' ? 'success' : 'unknown'}
            icon={StatusIcon}
          >
            {health?.message || 'v' + (health?.version || '--')}
          </StatusBadge>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label"><Upload size={14} />{t('dashboard.card.totalFiles')}</div>
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

      <section class="ics-ops-panel">
        <header class="ics-card-header">
          <strong>{t('dashboard.featureHub.title')}</strong>
          <span class="ics-text-muted">{t('dashboard.featureHub.subtitle')}</span>
        </header>
        <div class="ics-card-body">
          <div class="ics-dashboard-featureGrid">
            {featureCards.map(item => (
              <article key={item.id} class="ics-dashboard-featureCard">
                <div class="ics-dashboard-featureCard__head">
                  <div class="ics-dashboard-featureCard__icon"><item.Icon size={16} /></div>
                  <strong>{t(item.titleKey)}</strong>
                </div>
                <p>{t(item.descriptionKey)}</p>
                <div class="ics-dashboard-featureCard__meta">
                  <span>{t(item.metricKey)}</span>
                  <strong>{item.metricValue(stats)}</strong>
                </div>
                <button
                  class="ics-ops-btn ics-ops-btn--ghost"
                  type="button"
                  onClick={() => goToView(item.id)}
                >
                  <span>{t('dashboard.feature.open')}</span>
                  <ArrowRight size={14} />
                </button>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section class="ics-ops-grid ics-ops-grid--two">
        <article class="ics-ops-panel">
          <header class="ics-card-header">
            <strong>{t('dashboard.workflow.title')}</strong>
            <span class="ics-text-muted">{t('dashboard.workflow.subtitle')}</span>
          </header>
          <div class="ics-card-body">
            <div class="ics-dashboard-workflow">
              {featureCards.map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  class="ics-dashboard-workflowStep"
                  onClick={() => goToView(item.id)}
                >
                  <span class="ics-dashboard-workflowStep__index">{index + 1}</span>
                  <span class="ics-dashboard-workflowStep__name">{t(item.titleKey)}</span>
                  <ArrowRight size={14} />
                </button>
              ))}
            </div>
          </div>
        </article>

        <article class="ics-ops-panel">
          <header class="ics-card-header">
            <strong>{t('dashboard.activity.title')}</strong>
            <span class="ics-text-muted">{t('dashboard.activity.subtitle')}</span>
          </header>
          <div class="ics-card-body">
            {activities.length > 0 ? (
              <div class="ics-dashboard-activityList">
                {activities.slice(0, 6).map((item, idx) => (
                  <div key={`${item.created_at || item.timestamp || 'activity'}-${idx}`} class="ics-dashboard-activityItem">
                    <div class="ics-dashboard-activityItem__head">
                      <StatusBadge variant="info">{getActivityLabel(item)}</StatusBadge>
                      <span>{getActivityAt(item)}</span>
                    </div>
                    <div class="ics-dashboard-activityItem__body">{getActivityMessage(item)}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div class="ics-ops-callout">
                <div class="ics-ops-callout__title">{t('dashboard.activity.empty')}</div>
                <p>{t('dashboard.activity.emptyHint')}</p>
              </div>
            )}
          </div>
        </article>
      </section>

      <section class="ics-ops-panel">
        <header class="ics-card-header">
          <strong>{t('dashboard.system.title')}</strong>
        </header>
        <div class="ics-card-body">
          <div class="ics-ops-inlineStats">
            <div>
              <span>{t('dashboard.system.serviceStatus')}</span>
              <strong>{statusLabel}</strong>
            </div>
            <div>
              <span>{t('dashboard.system.version')}</span>
              <strong>{health?.version || '--'}</strong>
            </div>
            <div>
              <span>{t('dashboard.system.registeredRows')}</span>
              <strong>{stats?.registration_stats?.total_registrations ?? 0}</strong>
            </div>
          </div>
          <div class="ics-dashboard-systemHint">
            <Database size={14} />
            <span>{t('dashboard.system.hint')}</span>
          </div>
        </div>
      </section>

    </div>
  );
}
