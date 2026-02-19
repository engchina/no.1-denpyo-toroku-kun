/**
 * ListView - 伝票ファイル一覧画面 (SCR-002)
 * テーブル + ステータスフィルタ + ページング + 削除
 */
import { h } from 'preact';
import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import {
  fetchFileList,
  deleteFile,
  bulkDeleteFiles,
  analyzeFile,
  setFileListPage,
  setFileListStatusFilter
} from '../../redux/slices/denpyoSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { setCurrentView } from '../../redux/slices/applicationSlice';
import Pagination from '../../components/Pagination';
import { t } from '../../i18n';
import { FileStatus } from '../../types/denpyoTypes';
import {
  RefreshCw,
  Trash2,
  Filter,
  Sparkles,
  Loader2,
  Eye,
  Files,
  CheckCircle2,
  AlertTriangle,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  FolderSearch
} from 'lucide-react';

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

type SortKey = 'file_name' | 'file_size' | 'status' | 'uploaded_at';
type SortDirection = 'asc' | 'desc';
const FILE_LIST_SORT_STORAGE_KEY = 'denpyo.fileList.sort.v1';

const SORT_LABEL_KEYS: Record<SortKey, Parameters<typeof t>[0]> = {
  file_name: 'fileList.col.name',
  file_size: 'fileList.col.size',
  status: 'fileList.col.status',
  uploaded_at: 'fileList.col.uploadedAt'
};

function loadSortPreference(): { sortKey: SortKey; sortDirection: SortDirection } | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(FILE_LIST_SORT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { sortKey?: SortKey; sortDirection?: SortDirection };
    if (!parsed.sortKey || !parsed.sortDirection) return null;
    if (!Object.keys(SORT_LABEL_KEYS).includes(parsed.sortKey)) return null;
    if (parsed.sortDirection !== 'asc' && parsed.sortDirection !== 'desc') return null;
    return {
      sortKey: parsed.sortKey,
      sortDirection: parsed.sortDirection
    };
  } catch {
    return null;
  }
}

function StatusBadge({ status }: { status: FileStatus }) {
  const classMap: Record<FileStatus, string> = {
    UPLOADED: 'ics-badge-info',
    ANALYZING: 'ics-badge-warning',
    ANALYZED: 'ics-badge-success',
    REGISTERED: 'ics-badge-primary',
    ERROR: 'ics-badge-error'
  };
  const keyMap: Record<FileStatus, Parameters<typeof t>[0]> = {
    UPLOADED: 'fileList.status.uploaded',
    ANALYZING: 'fileList.status.analyzing',
    ANALYZED: 'fileList.status.analyzed',
    REGISTERED: 'fileList.status.registered',
    ERROR: 'fileList.status.error'
  };
  return (
    <span class={`ics-badge ${classMap[status] || 'ics-badge-info'}`}>
      {t(keyMap[status] || 'fileList.status.uploaded')}
    </span>
  );
}

export function ListView() {
  const dispatch = useAppDispatch();
  const { files, total, page, pageSize, totalPages, statusFilter } = useAppSelector(
    state => state.denpyo.fileList
  );
  const isLoading = useAppSelector(state => state.denpyo.isFileListLoading);
  const isDeleting = useAppSelector(state => state.denpyo.isDeleting);
  const isAnalyzing = useAppSelector(state => state.denpyo.isAnalyzing);
  const analyzingFileId = useAppSelector(state => state.denpyo.analyzingFileId);
  const [goToPageInput, setGoToPageInput] = useState('');
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>('uploaded_at');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  const loadFiles = useCallback(() => {
    dispatch(fetchFileList({ page, pageSize, status: statusFilter, uploadKind: 'raw' }));
  }, [dispatch, page, pageSize, statusFilter]);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  useEffect(() => {
    const currentIds = new Set(files.map(f => String(f.file_id)));
    setSelectedFileIds(prev => prev.filter(id => currentIds.has(id)));
  }, [files]);

  useEffect(() => {
    const pref = loadSortPreference();
    if (!pref) return;
    setSortKey(pref.sortKey);
    setSortDirection(pref.sortDirection);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(FILE_LIST_SORT_STORAGE_KEY, JSON.stringify({ sortKey, sortDirection }));
    } catch {
      // ignore storage errors
    }
  }, [sortKey, sortDirection]);

  const handleDelete = useCallback(async (fileId: string, fileName: string) => {
    if (!confirm(t('fileList.confirmDelete', { name: fileName }))) return;
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
  }, [dispatch, files.length, page, loadFiles]);

  const handleAnalyze = useCallback(async (fileId: string) => {
    try {
      await dispatch(analyzeFile(fileId)).unwrap();
      dispatch(setCurrentView('analysis'));
      dispatch(addNotification({
        type: 'success',
        message: t('fileList.notify.analyzeOk'),
        autoClose: true
      }));
    } catch {
      dispatch(addNotification({
        type: 'error',
        message: t('fileList.notify.analyzeFailed'),
        autoClose: true
      }));
    }
  }, [dispatch]);

  const handleStatusChange = useCallback((e: Event) => {
    const value = (e.target as HTMLSelectElement).value;
    dispatch(setFileListStatusFilter(value || null));
  }, [dispatch]);

  const handlePageChange = useCallback((newPage: number) => {
    dispatch(setFileListPage(newPage));
  }, [dispatch]);

  const handleGoToPage = useCallback(() => {
    const target = parseInt(goToPageInput, 10);
    if (!Number.isNaN(target) && target >= 1 && target <= totalPages) {
      dispatch(setFileListPage(target));
      setGoToPageInput('');
    }
  }, [dispatch, goToPageInput, totalPages]);

  const handlePreview = useCallback((fileId: string) => {
    window.open(`/studio/api/v1/files/${fileId}/preview`, '_blank', 'noopener,noreferrer');
  }, []);

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

  const handleBulkDelete = useCallback(async () => {
    if (selectedFileIds.length === 0) return;
    if (!confirm(t('fileList.confirmBulkDelete', { count: selectedFileIds.length }))) return;

    try {
      const result = await dispatch(bulkDeleteFiles(selectedFileIds)).unwrap();
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
      const deletedSet = new Set(selectedFileIds);
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
  }, [dispatch, selectedFileIds, loadFiles, files, page]);

  const sortedFiles = useMemo(() => {
    const statusRank: Record<FileStatus, number> = {
      ERROR: 0,
      UPLOADED: 1,
      ANALYZING: 2,
      ANALYZED: 3,
      REGISTERED: 4
    };
    const factor = sortDirection === 'asc' ? 1 : -1;
    return [...files].sort((a, b) => {
      if (sortKey === 'file_name') {
        return factor * a.file_name.localeCompare(b.file_name, 'ja');
      }
      if (sortKey === 'file_size') {
        return factor * ((a.file_size || 0) - (b.file_size || 0));
      }
      if (sortKey === 'status') {
        return factor * (statusRank[a.status] - statusRank[b.status]);
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
  const errorCount = files.filter(file => file.status === 'ERROR').length;

  const renderSortIcon = (key: SortKey) => {
    if (sortKey !== key) return <ArrowUpDown size={13} />;
    return sortDirection === 'asc' ? <ArrowUp size={13} /> : <ArrowDown size={13} />;
  };
  const currentSortDirectionLabel = sortDirection === 'asc' ? t('fileList.sort.asc') : t('fileList.sort.desc');

  return (
    <div class="ics-dashboard ics-dashboard--enhanced ics-fileListView">
      {/* ヘッダー */}
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>{t('fileList.title')}</h2>
            <p class="ics-ops-hero__subtitle">{t('fileList.subtitle')}</p>
          </div>
          <div class="ics-ops-hero__controls">
            <button
              class="ics-ops-btn ics-ops-btn--primary"
              onClick={loadFiles}
              disabled={isLoading}
            >
              <RefreshCw size={14} class={isLoading ? 'ics-spin' : ''} />
              <span>{isLoading ? t('common.loading') : t('fileList.refresh')}</span>
            </button>
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
        <div class="ics-ops-hero__meta">
          <span>{t('fileList.totalFiles', { count: total })}</span>
          {selectedFileIds.length > 0 && (
            <span class="oj-sm-margin-4x-start">{t('fileList.selectedCount', { count: selectedFileIds.length })}</span>
          )}
        </div>
      </section>

      {/* フィルタ + テーブル */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center oj-sm-justify-content-space-between">
            <span class="oj-typography-heading-xs">{t('fileList.tableTitle')}</span>
            <div class="oj-flex oj-sm-align-items-center oj-sm-gap-2 ics-fileListView__toolbar">
              <button
                type="button"
                class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
                onClick={handleBulkDelete}
                disabled={isDeleting || isLoading || selectedFileIds.length === 0}
                title={t('fileList.bulkDelete')}
              >
                <Trash2 size={14} />
                <span>{t('fileList.bulkDelete')}</span>
              </button>
              <span class="ics-fileListView__filterIcon"><Filter size={14} /></span>
              <select
                class="ics-select"
                value={statusFilter || ''}
                onChange={handleStatusChange}
                disabled={isLoading || isDeleting}
              >
                {STATUS_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{t(opt.labelKey)}</option>
                ))}
              </select>
              <span class="ics-fileListView__sortIndicator">
                {sortDirection === 'asc' ? <ArrowUp size={13} /> : <ArrowDown size={13} />}
                {t('fileList.sort.current', {
                  field: t(SORT_LABEL_KEYS[sortKey]),
                  direction: currentSortDirectionLabel
                })}
              </span>
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
                  {sortedFiles.map(file => (
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
                      <td class="ics-table__cell--name">{file.file_name}</td>
                      <td>{t('upload.kind.raw')}</td>
                      <td>{formatFileSize(file.file_size)}</td>
                      <td><StatusBadge status={file.status} /></td>
                      <td class="oj-text-color-secondary">{formatDateTime(file.uploaded_at)}</td>
                      <td class="ics-fileListView__actions">
                        <button
                          type="button"
                          class="ics-ops-btn ics-ops-btn--ghost"
                          onClick={() => handlePreview(String(file.file_id))}
                          title={t('fileList.previewFile')}
                        >
                          <Eye size={14} />
                        </button>
                        {(file.status === 'UPLOADED' || file.status === 'ERROR') && (
                          <button
                            type="button"
                            class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--accent"
                            onClick={() => handleAnalyze(String(file.file_id))}
                            disabled={isAnalyzing}
                            title={t('fileList.analyzeFile')}
                          >
                            {isAnalyzing && String(analyzingFileId) === String(file.file_id)
                              ? <Loader2 size={14} class="ics-spin" />
                              : <Sparkles size={14} />
                            }
                          </button>
                        )}
                        <button
                          type="button"
                          class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
                          onClick={() => handleDelete(String(file.file_id), file.file_name)}
                          disabled={isDeleting || file.status === 'REGISTERED'}
                          title={file.status === 'REGISTERED' ? t('fileList.cannotDeleteRegistered') : t('fileList.deleteFile')}
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
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
          </div>

          <div class="ics-card-footer">
            <Pagination
              currentPage={page}
              totalPages={totalPages}
              totalItems={total}
              goToPageInput={goToPageInput}
              onPageChange={handlePageChange}
              onGoToPageInputChange={setGoToPageInput}
              onGoToPage={handleGoToPage}
              isFirstPage={page <= 1 || isLoading}
              isLastPage={page >= totalPages || isLoading}
              position="bottom"
              show={totalPages > 1}
            />
          </div>
        </div>
      </section>
    </div>
  );
}
