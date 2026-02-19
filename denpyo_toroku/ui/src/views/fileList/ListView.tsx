/**
 * ListView - 伝票ファイル一覧画面 (SCR-002)
 * テーブル + ステータスフィルタ + ページング + 削除
 */
import { h } from 'preact';
import { useCallback, useEffect, useState } from 'preact/hooks';
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
  Eye
} from 'lucide-react';

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return `${date.toLocaleDateString('ja-JP')} ${date.toLocaleTimeString('ja-JP')}`;
}

function formatFileSize(bytes: number): string {
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

  const handleDelete = useCallback(async (fileId: string, fileName: string) => {
    if (!confirm(t('fileList.confirmDelete', { name: fileName }))) return;
    try {
      await dispatch(deleteFile(fileId)).unwrap();
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
  }, [dispatch]);

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
      loadFiles();
    } catch {
      dispatch(addNotification({
        type: 'error',
        message: t('fileList.notify.bulkDeleteFailed'),
        autoClose: true
      }));
    }
  }, [dispatch, selectedFileIds, loadFiles]);

  const selectableIds = files
    .filter(f => f.status !== 'REGISTERED')
    .map(f => String(f.file_id));
  const isAllSelectedOnPage = selectableIds.length > 0 && selectableIds.every(id => selectedFileIds.includes(id));

  return (
    <div class="ics-dashboard ics-dashboard--enhanced">
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
            <div class="oj-flex oj-sm-align-items-center oj-sm-gap-2">
              <button
                type="button"
                class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
                onClick={handleBulkDelete}
                disabled={isDeleting || selectedFileIds.length === 0}
                title={t('fileList.bulkDelete')}
              >
                <Trash2 size={14} />
                <span>{t('fileList.bulkDelete')}</span>
              </button>
              <Filter size={14} />
              <select
                class="ics-select"
                value={statusFilter || ''}
                onChange={handleStatusChange}
              >
                {STATUS_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{t(opt.labelKey)}</option>
                ))}
              </select>
            </div>
          </div>
          <div class="ics-card-body">
            {files.length > 0 ? (
              <table class="ics-table">
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        checked={isAllSelectedOnPage}
                        onChange={handleSelectAllOnPage}
                        aria-label={t('fileList.selectAll')}
                      />
                    </th>
                    <th>{t('fileList.col.name')}</th>
                    <th>{t('fileList.col.type')}</th>
                    <th>{t('fileList.col.size')}</th>
                    <th>{t('fileList.col.status')}</th>
                    <th>{t('fileList.col.uploadedAt')}</th>
                    <th>{t('fileList.col.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {files.map(file => (
                    <tr key={file.file_id}>
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
                      <td>
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
            ) : (
              <div class="ics-empty-text">
                {isLoading ? t('common.loading') : t('fileList.noFiles')}
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
