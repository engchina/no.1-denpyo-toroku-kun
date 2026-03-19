/**
 * ListView - 伝票ファイル一覧画面 (SCR-002)
 * テーブル + ステータスフィルタ + ページング + 削除
 */
import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import {
  fetchFileList,
  deleteFile,
  bulkDeleteFiles,
  analyzeFile,
  fetchAnalysisResult,
  fetchCategories,
  setFileListPage,
  setFileListPageSize,
  setFileListStatusFilter
} from '../../redux/slices/denpyoSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { useNavigate } from 'react-router-dom';
import { APP_ROUTES } from '../../constants/routes';
import Pagination from '../../components/Pagination';
import { useToastConfirm } from '../../hooks/useToastConfirm';
import { t } from '../../i18n';
import { clearLegacyFileListParams, getCurrentSearchParams, readScopedNumber, readScopedString, replaceSearchParams, setScopedValue } from '../../utils/queryScope';
import type { DenpyoFile, FileStatus } from '../../types/denpyoTypes';
import {
  RefreshCw,
  Trash2,
  Sparkles,
  Loader2,
  Eye,
  Files,
  CheckCircle2,
  AlertTriangle,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  FolderSearch,
  X,
  UploadCloud,
  Database as DatabaseIcon,
  XCircle,
  FileSearch
} from 'lucide-react';
import { StatusBadge } from '../../components/common/StatusBadge';
import { DocumentPreviewWorkspace } from '../../components/DocumentPreviewWorkspace';

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return `${date.toLocaleDateString('ja-JP')} ${date.toLocaleTimeString('ja-JP')}`;
}

function formatFileSize(bytes: number | null | undefined): string {
  if (typeof bytes !== 'number' || Number.isNaN(bytes) || bytes < 0) return '--';
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

const STATUS_OPTIONS: { value: FileStatus | ''; labelKey: Parameters<typeof t>[0] }[] = [
  { value: '', labelKey: 'fileList.filter.all' },
  { value: 'UPLOADED', labelKey: 'fileList.status.uploaded' },
  { value: 'ANALYZING', labelKey: 'fileList.status.analyzing' },
  { value: 'ANALYZED', labelKey: 'fileList.status.analyzed' },
  { value: 'REGISTERED', labelKey: 'fileList.status.registered' },
  { value: 'ERROR', labelKey: 'fileList.status.error' }
];
const FILE_LIST_PAGE_SIZE_OPTIONS = [20, 50, 100];
const FILE_LIST_QUERY_SCOPE = 'fl';

type SortKey = 'file_name' | 'file_size' | 'status' | 'uploaded_at';
type SortDirection = 'asc' | 'desc';
const DEFAULT_FILE_LIST_SORT_KEY: SortKey = 'uploaded_at';
const DEFAULT_FILE_LIST_SORT_DIRECTION: SortDirection = 'desc';

function FileStatusBadge({ file }: { file: DenpyoFile }) {
  if (file.is_analysis_stalled) {
    return (
      <StatusBadge variant="error" icon={AlertTriangle}>
        {t('fileList.status.stalled')}
      </StatusBadge>
    );
  }

  const status = file.status;
  const variantMap: Record<FileStatus, 'info' | 'warning' | 'success' | 'primary' | 'error'> = {
    UPLOADED: 'info',
    ANALYZING: 'warning',
    ANALYZED: 'success',
    REGISTERED: 'primary',
    ERROR: 'error'
  };
  const iconMap: Record<FileStatus, any> = {
    UPLOADED: UploadCloud,
    ANALYZING: Loader2,
    ANALYZED: CheckCircle2,
    REGISTERED: DatabaseIcon,
    ERROR: XCircle
  };
  const keyMap: Record<FileStatus, Parameters<typeof t>[0]> = {
    UPLOADED: 'fileList.status.uploaded',
    ANALYZING: 'fileList.status.analyzing',
    ANALYZED: 'fileList.status.analyzed',
    REGISTERED: 'fileList.status.registered',
    ERROR: 'fileList.status.error'
  };
  const IconComponent = iconMap[status] || UploadCloud;
  return (
    <StatusBadge variant={variantMap[status] || 'info'} icon={status === 'ANALYZING' ? () => <IconComponent size={14} class="ics-spin" /> : IconComponent}>
      {t(keyMap[status] || 'fileList.status.uploaded')}
    </StatusBadge>
  );
}

function hasViewableResult(file: { status: FileStatus; has_analysis_result?: boolean }): boolean {
  return Boolean(file.has_analysis_result) || file.status === 'ANALYZED' || file.status === 'REGISTERED';
}

function canAnalyzeFile(file: Pick<DenpyoFile, 'status' | 'can_retry_analysis'>): boolean {
  return Boolean(file.can_retry_analysis) || ['UPLOADED', 'ERROR'].includes(file.status);
}

export function ListView() {
  const dispatch = useAppDispatch();
  const { requestConfirm, confirmToast } = useToastConfirm();
  const { files, total, page, pageSize, totalPages, statusFilter } = useAppSelector(
    state => state.denpyo.fileList
  );
  const isLoading = useAppSelector(state => state.denpyo.isFileListLoading);
  const isDeleting = useAppSelector(state => state.denpyo.isDeleting);
  const isAnalyzing = useAppSelector(state => state.denpyo.isAnalyzing);
  const analyzingFileId = useAppSelector(state => state.denpyo.analyzingFileId);
  const categories = useAppSelector(state => state.denpyo.categories);
  const navigate = useNavigate();
  const isCategoriesLoading = useAppSelector(state => state.denpyo.isCategoriesLoading);
  const [goToPageInput, setGoToPageInput] = useState('');
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>(DEFAULT_FILE_LIST_SORT_KEY);
  const [sortDirection, setSortDirection] = useState<SortDirection>(DEFAULT_FILE_LIST_SORT_DIRECTION);
  const [previewTarget, setPreviewTarget] = useState<{ fileId: string; fileName: string } | null>(null);
  const [analyzeTarget, setAnalyzeTarget] = useState<{ fileId: string; fileName: string } | null>(null);
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
  const [isQueryReady, setIsQueryReady] = useState(false);

  const loadFiles = useCallback(() => {
    dispatch(fetchFileList({ page, pageSize, status: statusFilter, uploadKind: 'raw' }));
  }, [dispatch, page, pageSize, statusFilter]);

  useEffect(() => {
    if (!isQueryReady) return;
    loadFiles();
  }, [isQueryReady, loadFiles]);

  useEffect(() => {
    void dispatch(fetchCategories());
  }, [dispatch]);

  useEffect(() => {
    if (!isQueryReady) return;
    const hasAnalyzingFiles = files.some(file => file.status === 'ANALYZING' && !file.is_analysis_stalled);
    if (!hasAnalyzingFiles) return;
    const timer = window.setInterval(() => {
      loadFiles();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [files, isQueryReady, loadFiles]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = getCurrentSearchParams();
    const rawStatus = readScopedString(params, FILE_LIST_QUERY_SCOPE, 'status') || params.get('file_status');
    const rawPage = readScopedNumber(params, FILE_LIST_QUERY_SCOPE, 'p', parseInt(params.get('file_page') || '1', 10));
    const rawPageSize = readScopedNumber(params, FILE_LIST_QUERY_SCOPE, 'ps', parseInt(params.get('file_page_size') || '20', 10));
    const nextStatus = STATUS_OPTIONS.some(opt => opt.value === rawStatus && rawStatus !== '') ? rawStatus as FileStatus : null;
    const nextPage = Number.isNaN(rawPage) ? null : rawPage;
    const nextPageSize = Number.isNaN(rawPageSize) ? null : rawPageSize;

    if (nextStatus !== null) {
      dispatch(setFileListStatusFilter(nextStatus));
    }
    if (typeof nextPageSize === 'number' && FILE_LIST_PAGE_SIZE_OPTIONS.includes(nextPageSize)) {
      dispatch(setFileListPageSize(nextPageSize));
    }
    if (typeof nextPage === 'number' && !Number.isNaN(nextPage) && nextPage >= 1) {
      dispatch(setFileListPage(nextPage));
    }
    clearLegacyFileListParams(params);
    setScopedValue(params, FILE_LIST_QUERY_SCOPE, 'p', Math.max(1, nextPage || 1));
    if (typeof nextPageSize === 'number' && FILE_LIST_PAGE_SIZE_OPTIONS.includes(nextPageSize)) {
      setScopedValue(params, FILE_LIST_QUERY_SCOPE, 'ps', nextPageSize);
    }
    if (nextStatus) {
      setScopedValue(params, FILE_LIST_QUERY_SCOPE, 'status', nextStatus);
    }
    replaceSearchParams(params);
    setIsQueryReady(true);
  }, [dispatch]);

  useEffect(() => {
    if (!isQueryReady || typeof window === 'undefined') return;
    const params = getCurrentSearchParams();
    setScopedValue(params, FILE_LIST_QUERY_SCOPE, 'p', page);
    setScopedValue(params, FILE_LIST_QUERY_SCOPE, 'ps', pageSize);
    setScopedValue(params, FILE_LIST_QUERY_SCOPE, 'status', statusFilter || null);
    clearLegacyFileListParams(params);
    replaceSearchParams(params);
  }, [isQueryReady, page, pageSize, statusFilter]);

  useEffect(() => {
    const currentIds = new Set(files.map(f => String(f.file_id)));
    setSelectedFileIds(prev => prev.filter(id => currentIds.has(id)));
  }, [files]);

  useEffect(() => {
    if (!analyzeTarget || selectedCategoryId) return;
    const activeCategories = categories.filter(c => c.is_active);
    if (activeCategories.length > 0) {
      setSelectedCategoryId(activeCategories[0].id);
    }
  }, [analyzeTarget, categories, selectedCategoryId]);

  const handleDelete = useCallback((fileId: string, fileName: string) => {
    requestConfirm({
      message: t('fileList.confirmDelete', { name: fileName }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      confirmIcon: Trash2,
      onConfirm: async () => {
        try {
          await dispatch(deleteFile(fileId)).unwrap();
          const willBeEmptyOnPage = files.length <= 1 && page > 1;
          if (willBeEmptyOnPage) {
            dispatch(setFileListPage(page - 1));
          } else {
            loadFiles();
          }
          dispatch(addNotification({
            type: 'success',
            message: t('fileList.notify.deleted', { name: fileName }),
            autoClose: true
          }));
        } catch {
          dispatch(addNotification({
            type: 'error',
            message: t('fileList.notify.deleteFailed', { name: fileName }),
            autoClose: true
          }));
        }
      }
    });
  }, [dispatch, files.length, page, loadFiles, requestConfirm]);

  const handleAnalyze = useCallback(async (fileId: string, fileName: string) => {
    try {
      const latestCategories = await dispatch(fetchCategories()).unwrap();
      const activeCategories = latestCategories.filter(c => c.is_active);
      if (activeCategories.length === 0) {
        dispatch(addNotification({
          type: 'error',
          message: t('fileList.analyze.noActiveCategory'),
          autoClose: true
        }));
        return;
      }

      setAnalyzeTarget({ fileId, fileName });
      setSelectedCategoryId(activeCategories[0]?.id ?? null);
    } catch (e: any) {
      dispatch(addNotification({
        type: 'error',
        message: e?.message || t('fileList.notify.analyzeFailed'),
        autoClose: true
      }));
    }
  }, [dispatch]);

  const closeAnalyzeModal = useCallback(() => {
    setAnalyzeTarget(null);
    setSelectedCategoryId(null);
  }, []);

  const handleAnalyzeConfirm = useCallback(async () => {
    if (!analyzeTarget || !selectedCategoryId) {
      dispatch(addNotification({
        type: 'error',
        message: t('fileList.analyze.required'),
        autoClose: true
      }));
      return;
    }

    try {
      await dispatch(analyzeFile({
        fileId: analyzeTarget.fileId,
        categoryId: selectedCategoryId
      })).unwrap();
      closeAnalyzeModal();
      loadFiles();
      dispatch(addNotification({
        type: 'success',
        message: t('fileList.notify.analyzeQueued'),
        autoClose: true
      }));
    } catch (e: any) {
      dispatch(addNotification({
        type: 'error',
        message: e?.message || t('fileList.notify.analyzeFailed'),
        autoClose: true
      }));
    }
  }, [analyzeTarget, closeAnalyzeModal, dispatch, loadFiles, selectedCategoryId]);

  const handleViewResult = useCallback(async (fileId: string) => {
    try {
      await dispatch(fetchAnalysisResult(fileId)).unwrap();
      navigate(`${APP_ROUTES.registration}?fileId=${encodeURIComponent(fileId)}`);
    } catch (e: any) {
      dispatch(addNotification({
        type: 'error',
        message: e?.message || t('analysis.noStoredResult'),
        autoClose: true
      }));
    }
  }, [dispatch, navigate]);

  const handleStatusChange = useCallback((e: Event) => {
    const value = (e.target as HTMLSelectElement).value;
    dispatch(setFileListStatusFilter(value || null));
  }, [dispatch]);

  const handlePageChange = useCallback((newPage: number) => {
    dispatch(setFileListPage(newPage));
  }, [dispatch]);

  const handlePageSizeChange = useCallback((nextPageSize: number) => {
    if (!FILE_LIST_PAGE_SIZE_OPTIONS.includes(nextPageSize)) return;
    setSelectedFileIds([]);
    dispatch(setFileListPageSize(nextPageSize));
  }, [dispatch]);

  const handleGoToPage = useCallback(() => {
    const target = parseInt(goToPageInput, 10);
    if (!Number.isNaN(target) && target >= 1 && target <= totalPages) {
      dispatch(setFileListPage(target));
      setGoToPageInput('');
    }
  }, [dispatch, goToPageInput, totalPages]);

  const handlePreview = useCallback((fileId: string, fileName: string) => {
    setPreviewTarget({ fileId, fileName });
  }, []);

  const closePreview = useCallback(() => {
    setPreviewTarget(null);
  }, []);

  useEffect(() => {
    if (!previewTarget) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closePreview();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [previewTarget, closePreview]);

  const handleSort = useCallback((nextKey: SortKey) => {
    setSortKey(prevKey => {
      if (prevKey === nextKey) {
        setSortDirection(prevDir => (prevDir === 'asc' ? 'desc' : 'asc'));
        return prevKey;
      }
      setSortDirection('asc');
      return nextKey;
    });
  }, []);
  const toggleFileSelection = useCallback((fileId: string) => {
    setSelectedFileIds(prev => (
      prev.includes(fileId) ? prev.filter(id => id !== fileId) : [...prev, fileId]
    ));
  }, []);

  const handleSelectAllOnPage = useCallback(() => {
    const selectableIds = files
      .filter(f => f.status !== 'REGISTERED')
      .map(f => String(f.file_id));
    const allSelected = selectableIds.length > 0 && selectableIds.every(id => selectedFileIds.includes(id));
    setSelectedFileIds(allSelected ? [] : selectableIds);
  }, [files, selectedFileIds]);

  const handleBulkDelete = useCallback(() => {
    if (selectedFileIds.length === 0) return;
    const targetIds = [...selectedFileIds];

    requestConfirm({
      message: t('fileList.confirmBulkDelete', { count: targetIds.length }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      confirmIcon: Trash2,
      onConfirm: async () => {
        try {
          const result = await dispatch(bulkDeleteFiles(targetIds)).unwrap();
          setSelectedFileIds([]);
          if (result.errors.length > 0) {
            dispatch(addNotification({
              type: 'warning',
              message: t('fileList.notify.bulkDeletedWithErrors', {
                deleted: result.deleted_file_ids.length,
                errors: result.errors.length
              }),
              autoClose: true
            }));
          } else {
            dispatch(addNotification({
              type: 'success',
              message: t('fileList.notify.bulkDeleted', { count: result.deleted_file_ids.length }),
              autoClose: true
            }));
          }
          const deletedSet = new Set(targetIds);
          const remainingOnPage = files.filter(f => !deletedSet.has(String(f.file_id))).length;
          if (remainingOnPage === 0 && page > 1) {
            dispatch(setFileListPage(page - 1));
          } else {
            loadFiles();
          }
        } catch {
          dispatch(addNotification({
            type: 'error',
            message: t('fileList.notify.bulkDeleteFailed'),
            autoClose: true
          }));
        }
      }
    });
  }, [dispatch, selectedFileIds, loadFiles, files, page, requestConfirm]);

  const sortedFiles = useMemo(() => {
    const statusRank: Record<FileStatus, number> = {
      ERROR: 0,
      UPLOADED: 1,
      ANALYZING: 2,
      ANALYZED: 3,
      REGISTERED: 4
    };
    const factor = sortDirection === 'asc' ? 1 : -1;
    const getStatusRank = (file: DenpyoFile): number => (
      file.is_analysis_stalled ? 0.5 : statusRank[file.status]
    );
    return [...files].sort((a, b) => {
      if (sortKey === 'file_name') {
        return factor * a.file_name.localeCompare(b.file_name, 'ja');
      }
      if (sortKey === 'file_size') {
        return factor * ((a.file_size || 0) - (b.file_size || 0));
      }
      if (sortKey === 'status') {
        return factor * (getStatusRank(a) - getStatusRank(b));
      }
      const aTime = new Date(a.uploaded_at || '').getTime() || 0;
      const bTime = new Date(b.uploaded_at || '').getTime() || 0;
      return factor * (aTime - bTime);
    });
  }, [files, sortDirection, sortKey]);

  const selectableIds = sortedFiles
    .filter(f => f.status !== 'REGISTERED')
    .map(f => String(f.file_id));
  const isAllSelectedOnPage = selectableIds.length > 0 && selectableIds.every(id => selectedFileIds.includes(id));
  const uploadedCount = files.filter(file => file.status === 'UPLOADED').length;
  const analyzedCount = files.filter(file => file.status === 'ANALYZED' || file.status === 'REGISTERED').length;
  const errorCount = files.filter(file => file.status === 'ERROR' || file.is_analysis_stalled).length;

  const renderSortIcon = (key: SortKey) => {
    if (sortKey !== key) return <ArrowUpDown size={13} />;
    return sortDirection === 'asc' ? <ArrowUp size={13} /> : <ArrowDown size={13} />;
  };
  const rangeStart = total === 0 ? 0 : ((page - 1) * pageSize) + 1;
  const rangeEnd = total === 0 ? 0 : Math.min(page * pageSize, total);

  return (
    <div class="ics-dashboard ics-dashboard--enhanced ics-fileListView">
      {/* ヘッダー */}
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>{t('fileList.title')}</h2>
            <p class="ics-ops-hero__subtitle">{t('fileList.subtitle')}</p>
          </div>
        </div>
        <div class="ics-fileListView__heroStats">
          <div class="ics-fileListView__heroStat">
            <span class="ics-fileListView__heroStatLabel"><Files size={13} /> {t('fileList.kpi.total')}</span>
            <strong class="ics-fileListView__heroStatValue">{total}</strong>
          </div>
          <div class="ics-fileListView__heroStat">
            <span class="ics-fileListView__heroStatLabel"><CheckCircle2 size={13} /> {t('fileList.kpi.ready')}</span>
            <strong class="ics-fileListView__heroStatValue">{uploadedCount + analyzedCount}</strong>
          </div>
          <div class="ics-fileListView__heroStat">
            <span class="ics-fileListView__heroStatLabel"><AlertTriangle size={13} /> {t('fileList.kpi.error')}</span>
            <strong class="ics-fileListView__heroStatValue">{errorCount}</strong>
          </div>
        </div>
      </section>

      {/* フィルタ + テーブル */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header ics-card-header--table-toolbar">
            <div class="ics-unified-table-header">
              <span class="oj-typography-heading-xs">{t('fileList.tableTitle')}</span>
              <div class="ics-unified-table-toolbar">
                <div class="ics-unified-table-toolbar__group">
                  <button
                    type="button"
                    class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger ics-ops-btn--bulk-danger"
                    onClick={handleBulkDelete}
                    disabled={isDeleting || isLoading || selectedFileIds.length === 0}
                    title={t('fileList.bulkDelete')}
                  >
                    <Trash2 size={14} />
                    <span>{t('fileList.bulkDelete')}</span>
                  </button>
                  <span class="ics-unified-table-toolbar__meta">
                    {t('fileList.selectedCount', { count: selectedFileIds.length })}
                  </span>
                </div>
                <div class="ics-unified-table-toolbar__group ics-unified-table-toolbar__group--secondary">
                  <select
                    class="ics-select"
                    value={statusFilter || ''}
                    onChange={handleStatusChange}
                    disabled={isLoading || isDeleting}
                    aria-label={t('fileList.filter.all')}
                  >
                    {STATUS_OPTIONS.map(opt => (
                      <option key={opt.value} value={opt.value}>{t(opt.labelKey)}</option>
                    ))}
                  </select>
                  <button
                    class="ics-ops-btn ics-ops-btn--ghost"
                    onClick={loadFiles}
                    disabled={isLoading}
                  >
                    <RefreshCw size={14} class={isLoading ? 'ics-spin' : ''} />
                    <span>{isLoading ? t('common.loading') : t('fileList.refresh')}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
          <div class="ics-card-body">
            {files.length > 0 ? (
              <div class="ics-fileListView__tableWrap">
                <table class="ics-table ics-fileListView__table">
                  <thead>
                    <tr>
                      <th>
                        <input
                          type="checkbox"
                          checked={isAllSelectedOnPage}
                          ref={(el) => {
                            if (!el) return;
                            el.indeterminate = selectedFileIds.length > 0 && !isAllSelectedOnPage;
                          }}
                          onChange={handleSelectAllOnPage}
                          disabled={isDeleting || isLoading || selectableIds.length === 0}
                          aria-label={t('fileList.selectAll')}
                        />
                      </th>
                      <th>
                        <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleSort('file_name')}>
                          {t('fileList.col.name')}
                          {renderSortIcon('file_name')}
                        </button>
                      </th>
                      <th>{t('fileList.col.type')}</th>
                      <th>
                        <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleSort('file_size')}>
                          {t('fileList.col.size')}
                          {renderSortIcon('file_size')}
                        </button>
                      </th>
                      <th>
                        <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleSort('status')}>
                          {t('fileList.col.status')}
                          {renderSortIcon('status')}
                        </button>
                      </th>
                      <th>
                        <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleSort('uploaded_at')}>
                          {t('fileList.col.uploadedAt')}
                          {renderSortIcon('uploaded_at')}
                        </button>
                      </th>
                      <th>{t('fileList.col.actions')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedFiles.map(file => {
                      const displayName = file.original_file_name || file.file_name;
                      return (
                      <tr key={file.file_id} class={selectedFileIds.includes(String(file.file_id)) ? 'ics-fileListView__row--selected' : ''}>
                        <td>
                          <input
                            type="checkbox"
                            checked={selectedFileIds.includes(String(file.file_id))}
                            onChange={() => toggleFileSelection(String(file.file_id))}
                            disabled={file.status === 'REGISTERED' || isDeleting}
                            aria-label={t('fileList.selectFile')}
                          />
                        </td>
                        <td class="ics-table__cell--name ics-fileListView__fileNameCell">{file.original_file_name || file.file_name}</td>
                        <td>{t('upload.kind.raw')}</td>
                        <td>{formatFileSize(file.file_size)}</td>
                        <td>
                          <FileStatusBadge file={file} />
                        </td>
                        <td class="oj-text-color-secondary">{formatDateTime(file.uploaded_at)}</td>
                        <td class="ics-fileListView__actions">
                          <button
                            type="button"
                            class="ics-ops-btn ics-ops-btn--ghost"
                            onClick={() => handlePreview(String(file.file_id), displayName)}
                            title={t('fileList.previewFile')}
                          >
                            <Eye size={14} />
                          </button>
                          <button
                            type="button"
                            class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--accent"
                            onClick={() => handleAnalyze(String(file.file_id), displayName)}
                            disabled={isAnalyzing || !canAnalyzeFile(file)}
                            title={file.is_analysis_stalled ? t('fileList.analyze.retry') : t('fileList.analyzeFile')}
                          >
                            {isAnalyzing && String(analyzingFileId) === String(file.file_id)
                              ? <Loader2 size={14} class="ics-spin" />
                              : <Sparkles size={14} />
                            }
                          </button>
                          <button
                            type="button"
                            class="ics-ops-btn ics-ops-btn--ghost"
                            onClick={() => handleViewResult(String(file.file_id))}
                            title={t('fileList.viewResult')}
                            disabled={!hasViewableResult(file)}
                          >
                            <FileSearch size={14} />
                          </button>
                          <button
                            type="button"
                            class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
                            onClick={() => handleDelete(String(file.file_id), displayName)}
                            disabled={isDeleting || file.status === 'REGISTERED'}
                            title={file.status === 'REGISTERED' ? t('fileList.cannotDeleteRegistered') : t('fileList.deleteFile')}
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div class="ics-empty-text ics-fileListView__emptyState">
                {isLoading ? (
                  t('common.loading')
                ) : (
                  <div class="ics-fileListView__emptyContent">
                    <FolderSearch size={30} />
                    <div class="ics-fileListView__emptyTitle">{t('fileList.noFiles')}</div>
                    <div class="ics-fileListView__emptyHint">{t('fileList.emptyHint')}</div>
                  </div>
                )}
              </div>
            )}
            <Pagination
              currentPage={page}
              totalPages={totalPages}
              totalItems={total}
              pageSize={pageSize}
              pageSizeOptions={FILE_LIST_PAGE_SIZE_OPTIONS}
              onPageSizeChange={handlePageSizeChange}
              goToPageInput={goToPageInput}
              onPageChange={handlePageChange}
              onGoToPageInputChange={setGoToPageInput}
              onGoToPage={handleGoToPage}
              rangeStart={rangeStart}
              rangeEnd={rangeEnd}
              showGoToPage={false}
              isFirstPage={page <= 1 || isLoading}
              isLastPage={page >= totalPages || isLoading}
              position="bottom"
              show
              summaryPlacement="controls"
            />
          </div>
        </div>
      </section>
      {previewTarget && (
        <div class="ics-modal-overlay" onClick={closePreview}>
          <div class="ics-modal ics-modal--xl ics-fileListView__previewModal" onClick={(e: Event) => e.stopPropagation()}>
            <div class="ics-modal__header">
              <h3>{previewTarget.fileName || t('fileList.previewFile')}</h3>
              <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={closePreview} title={t('common.close')}>
                <X size={16} />
              </button>
            </div>
            <div class="ics-modal__body ics-fileListView__previewBody">
              <DocumentPreviewWorkspace
                fileIds={[previewTarget.fileId]}
                title={t('fileList.previewFile')}
              />
            </div>
          </div>
        </div>
      )}
      {analyzeTarget && (
        <div class="ics-modal-overlay" onClick={closeAnalyzeModal}>
          <div class="ics-modal" style={{ maxWidth: '520px' }} onClick={(e: Event) => e.stopPropagation()}>
            <div class="ics-modal__header">
              <h3>{t('fileList.analyze.categoryTitle')}</h3>
              <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={closeAnalyzeModal} title={t('common.close')}>
                <X size={16} />
              </button>
            </div>
            <div class="ics-modal__body">
              <p class="ics-form-hint" style={{ marginBottom: '12px' }}>
                {t('fileList.analyze.categoryDesc', { name: analyzeTarget.fileName })}
              </p>
              <div class="ics-form-group">
                <label class="ics-form-label">{t('fileList.analyze.categoryLabel')}</label>
                <select
                  class="ics-form-select"
                  value={selectedCategoryId ? String(selectedCategoryId) : ''}
                  onChange={(e: Event) => {
                    const next = parseInt((e.target as HTMLSelectElement).value, 10);
                    setSelectedCategoryId(Number.isNaN(next) ? null : next);
                  }}
                  disabled={isCategoriesLoading || isAnalyzing}
                >
                  {(categories || []).filter(c => c.is_active).map(c => (
                    <option key={c.id} value={c.id}>{c.category_name}</option>
                  ))}
                </select>
              </div>
            </div>
            <div class="ics-modal__footer">
              <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={closeAnalyzeModal} disabled={isAnalyzing}>
                {t('common.cancel')}
              </button>
              <button
                type="button"
                class="ics-ops-btn ics-ops-btn--primary"
                onClick={handleAnalyzeConfirm}
                disabled={isAnalyzing || !selectedCategoryId}
              >
                {isAnalyzing ? <Loader2 size={14} class="ics-spin" /> : <Sparkles size={14} />}
                <span>{isAnalyzing ? t('analysis.analyzing') : t('fileList.analyzeFile')}</span>
              </button>
            </div>
          </div>
        </div>
      )}
      {confirmToast}
    </div>
  );
}
