import { useCallback, useState } from 'preact/hooks';
import { Trash2 } from 'lucide-react';
import { t } from '../i18n';
import { apiPost } from '../utils/apiUtils';
import type { DeleteTableBrowserRowResponse } from '../types/denpyoTypes';
import type { UseSelectionResult } from './useSelection';
import type { ToastConfirmRequest } from './useToastConfirm';

type NotificationType = 'success' | 'warning' | 'error';

type PreviewRow = Record<string, unknown>;

interface UseTablePreviewRowDeletionOptions {
  tableName: string;
  hasLinkedLineTable: boolean;
  totalRows: number;
  currentPage: number;
  pageSize: number;
  selection: UseSelectionResult<PreviewRow>;
  requestConfirm: (request: ToastConfirmRequest) => void;
  notify: (type: NotificationType, message: string) => void;
  refreshPage: (nextPage: number) => void;
  refreshMeta?: () => void;
}

export function getTablePreviewRowId(row: PreviewRow): string | null {
  const raw = row.ROW_ID_META;
  if (raw === null || raw === undefined || raw === '') return null;
  return String(raw);
}

export function useTablePreviewRowDeletion({
  tableName,
  hasLinkedLineTable,
  totalRows,
  currentPage,
  pageSize,
  selection,
  requestConfirm,
  notify,
  refreshPage,
  refreshMeta,
}: UseTablePreviewRowDeletionOptions) {
  const [deletingRowId, setDeletingRowId] = useState<string | null>(null);
  const [isBulkDeletingRows, setIsBulkDeletingRows] = useState(false);

  const getNextPageAfterDelete = useCallback((deletedRows: number) => {
    const remainingRows = Math.max(0, totalRows - Math.max(0, deletedRows));
    const maxPageAfterDelete = Math.max(1, Math.ceil(remainingRows / pageSize));
    return Math.min(currentPage, maxPageAfterDelete);
  }, [currentPage, pageSize, totalRows]);

  const handleDeleteSuccess = useCallback((deletedRows: number) => {
    refreshMeta?.();
    refreshPage(getNextPageAfterDelete(deletedRows));
  }, [getNextPageAfterDelete, refreshMeta, refreshPage]);

  const handleDeleteRow = useCallback((row: PreviewRow) => {
    const rowId = getTablePreviewRowId(row);
    if (!rowId || !tableName) return;

    requestConfirm({
      message: hasLinkedLineTable
        ? t('search.browser.deleteHeaderRowConfirm')
        : t('search.browser.deleteRowConfirm'),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      confirmIcon: Trash2,
      onConfirm: async () => {
        setDeletingRowId(rowId);
        try {
          const result = await apiPost<DeleteTableBrowserRowResponse>('/api/v1/search/table-browser/delete-row', {
            table_name: tableName,
            row_id: rowId,
          });
          selection.deselectIds([rowId]);
          handleDeleteSuccess(result.deleted || 1);
          notify(
            'success',
            result.detail_deleted && result.detail_deleted > 0
              ? t('search.browser.deleteHeaderRowSuccess', { detailCount: result.detail_deleted })
              : t('search.browser.deleteRowSuccess'),
          );
        } catch {
          notify('error', t('search.browser.deleteRowFailed'));
        } finally {
          setDeletingRowId(null);
        }
      },
    });
  }, [tableName, hasLinkedLineTable, requestConfirm, selection, handleDeleteSuccess, notify]);

  const handleBulkDeleteRows = useCallback(() => {
    if (!tableName || selection.selectedCount === 0) return;

    const targetRowIds = Array.from(selection.selectedIds);
    requestConfirm({
      message: hasLinkedLineTable
        ? t('search.browser.confirmBulkDeleteHeaderRows', { count: targetRowIds.length })
        : t('search.browser.confirmBulkDelete', { count: targetRowIds.length }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      confirmIcon: Trash2,
      onConfirm: async () => {
        setIsBulkDeletingRows(true);
        try {
          let deletedCount = 0;
          let detailDeletedCount = 0;
          let failedCount = 0;

          for (const rowId of targetRowIds) {
            try {
              const result = await apiPost<DeleteTableBrowserRowResponse>('/api/v1/search/table-browser/delete-row', {
                table_name: tableName,
                row_id: rowId,
              });
              deletedCount += 1;
              detailDeletedCount += result.detail_deleted || 0;
            } catch {
              failedCount += 1;
            }
          }

          selection.deselectAll();

          if (deletedCount > 0) {
            handleDeleteSuccess(deletedCount);
          }

          if (deletedCount > 0 && failedCount === 0) {
            notify(
              'success',
              detailDeletedCount > 0
                ? t('search.browser.bulkDeleteHeaderRowsSuccess', { count: deletedCount, detailCount: detailDeletedCount })
                : t('search.browser.bulkDeleteSuccess', { count: deletedCount }),
            );
          } else if (deletedCount > 0) {
            notify(
              'warning',
              detailDeletedCount > 0
                ? t('search.browser.bulkDeleteHeaderRowsPartial', {
                    deleted: deletedCount,
                    detailCount: detailDeletedCount,
                    errors: failedCount,
                  })
                : t('search.browser.bulkDeletePartial', { deleted: deletedCount, errors: failedCount }),
            );
          } else {
            notify('error', t('search.browser.bulkDeleteFailed'));
          }
        } finally {
          setIsBulkDeletingRows(false);
        }
      },
    });
  }, [tableName, selection, requestConfirm, hasLinkedLineTable, handleDeleteSuccess, notify]);

  return {
    deletingRowId,
    isBulkDeletingRows,
    getRowId: getTablePreviewRowId,
    handleDeleteRow,
    handleBulkDeleteRows,
  };
}
