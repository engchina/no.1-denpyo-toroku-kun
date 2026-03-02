/**
 * SearchView - データ検索画面 (SCR-006)
 * - 自然言語検索 (NL -> SQL)
 * - テーブルブラウザ (直接閲覧)
 */
import type { ComponentChildren } from 'preact';
import { useState, useEffect, useCallback, useRef, useMemo } from 'preact/hooks';
import { useAppSelector, useAppDispatch } from '../../redux/store';
import {
  fetchSearchableTables,
  fetchTableBrowserTables,
  nlSearch,
  fetchTableDataByName,
  clearSearchResults,
  clearSearchError
} from '../../redux/slices/denpyoSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import Pagination from '../../components/Pagination';
import { usePagination } from '../../hooks/usePagination';
import { useSelection } from '../../hooks/useSelection';
import type { UseSelectionResult } from '../../hooks/useSelection';
import { useToastConfirm } from '../../hooks/useToastConfirm';
import { t } from '../../i18n';
import { apiPost } from '../../utils/apiUtils';
import { getCurrentSearchParams, readScopedNumber, replaceSearchParams, setScopedValue } from '../../utils/queryScope';
import type { NLSearchResponse, SearchableTable, TableBrowseResult, TableBrowserTable } from '../../types/denpyoTypes';
import { Search, Database, Copy, Check, Loader2, RefreshCw, Trash2, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';

type TabType = 'nlSearch' | 'tableBrowser';
const SEARCH_PAGINATION_PAGE_SIZE_OPTIONS = [20, 50, 100];
const SEARCH_TABLE_LIST_QUERY_SCOPE = 'sbtl';
const SEARCH_DATA_PREVIEW_QUERY_SCOPE = 'sbdp';
type SortDirection = 'asc' | 'desc';
type TableListSortKey = 'table_name' | 'category_name' | 'table_type' | 'row_count' | 'column_count' | 'created_at';

function compareValues(a: unknown, b: unknown): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return -1;
  if (b === null || b === undefined) return 1;

  if (typeof a === 'number' && typeof b === 'number') {
    return a - b;
  }

  const aDate = new Date(String(a)).getTime();
  const bDate = new Date(String(b)).getTime();
  if (!Number.isNaN(aDate) && !Number.isNaN(bDate)) {
    return aDate - bDate;
  }

  const aNum = Number(a);
  const bNum = Number(b);
  if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) {
    return aNum - bNum;
  }

  return String(a).localeCompare(String(b), 'ja');
}

function getDefaultDataSortColumn(columns: string[]): string {
  if (!columns.length) return '';
  const target = new Set(['created_at', 'uploaded_at', 'create_time', 'upload_time', 'created_date', 'uploaded_date']);
  const matched = columns.find((col) => target.has(col.trim().toLowerCase()));
  return matched || columns[0];
}

export function SearchView() {
  const dispatch = useAppDispatch();
  const {
    searchableTables,
    isSearchableTablesLoading,
    tableBrowserTables,
    isTableBrowserTablesLoading,
    nlSearchResult,
    isNLSearching,
    tableBrowseResult,
    isTableBrowsing,
    searchError
  } = useAppSelector(state => state.denpyo);

  const [activeTab, setActiveTab] = useState<TabType>('nlSearch');

  // Load searchable tables on mount
  useEffect(() => {
    dispatch(fetchSearchableTables());
    dispatch(fetchTableBrowserTables());
    return () => {
      dispatch(clearSearchResults());
    };
  }, [dispatch]);

  const handleTabChange = (tab: TabType) => {
    setActiveTab(tab);
    dispatch(clearSearchError());
  };

  return (
    <div class="ics-view-container ics-search-view">
      <header class="ics-view-header">
        <h1 class="oj-typography-heading-md">{t('search.title')}</h1>
        <p class="oj-typography-body-sm oj-sm-margin-2x-top">{t('search.subtitle')}</p>
      </header>

      <div class="ics-search-workspace">
        {/* Tab Bar */}
        <div class="ics-search-tabs" role="tablist" aria-label={t('search.title')}>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'nlSearch'}
            class={`ics-search-tab ${activeTab === 'nlSearch' ? 'ics-search-tab--active' : ''}`}
            onClick={() => handleTabChange('nlSearch')}
          >
            <Search size={16} />
            <span>{t('search.tab.nlSearch')}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'tableBrowser'}
            class={`ics-search-tab ${activeTab === 'tableBrowser' ? 'ics-search-tab--active' : ''}`}
            onClick={() => handleTabChange('tableBrowser')}
          >
            <Database size={16} />
            <span>{t('search.tab.tableBrowser')}</span>
          </button>
        </div>

        {/* Error display */}
        {searchError && (
          <div class="ics-error-message oj-sm-margin-4x-top">
            {searchError}
          </div>
        )}

        {/* Tab content */}
        <div class="ics-search-content oj-sm-margin-4x-top">
          {activeTab === 'nlSearch' ? (
            <NLSearchTab
              searchableTables={searchableTables}
              isLoading={isNLSearching}
              isTablesLoading={isSearchableTablesLoading}
              result={nlSearchResult}
            />
          ) : (
            <TableBrowserTab
              searchableTables={searchableTables}
              tableBrowserTables={tableBrowserTables}
              isLoading={isTableBrowsing}
              isTablesLoading={isSearchableTablesLoading}
              isTableListLoading={isTableBrowserTablesLoading}
              result={tableBrowseResult}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// NL Search Tab
// ─────────────────────────────────────────────────────────────────────────────

interface NLSearchTabProps {
  searchableTables: SearchableTable[];
  isLoading: boolean;
  isTablesLoading: boolean;
  result: NLSearchResponse | null;
}

function NLSearchTab({ searchableTables, isLoading, isTablesLoading, result }: NLSearchTabProps) {
  const dispatch = useAppDispatch();
  const [query, setQuery] = useState('');
  const [categoryId, setCategoryId] = useState<number | undefined>(undefined);
  const [copied, setCopied] = useState(false);

  const handleSearch = useCallback(() => {
    if (!query.trim()) return;
    dispatch(nlSearch({ query: query.trim(), category_id: categoryId }));
  }, [dispatch, query, categoryId]);

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && e.ctrlKey) {
      handleSearch();
    }
  };

  const handleCopySQL = useCallback(() => {
    if (result?.generated_sql) {
      navigator.clipboard.writeText(result.generated_sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [result]);

  const noTables = !isTablesLoading && searchableTables.length === 0;

  return (
    <div class="ics-nl-search">
      <div class="ics-search-controls-card">
        {/* Category filter */}
        <div class="ics-form-group">
          <label class="ics-form-label">{t('search.common.categoryFilter')}</label>
          <select
            class="ics-form-input"
            value={categoryId ?? ''}
            onChange={(e) => setCategoryId(e.currentTarget.value ? Number(e.currentTarget.value) : undefined)}
            disabled={noTables}
          >
            <option value="">{t('search.common.allCategories')}</option>
            {searchableTables.map(table => (
              <option key={table.category_id} value={table.category_id}>
                {table.category_name}
              </option>
            ))}
          </select>
        </div>

        {/* Query input */}
        <div class="ics-form-group">
          <div class="ics-form-label-row">
            <label class="ics-form-label">{t('search.nl.queryLabel')}</label>
            <span class="ics-form-hint">Ctrl + Enter</span>
          </div>
          <textarea
            class="ics-form-textarea ics-search-query"
            placeholder={t('search.nl.queryPlaceholder')}
            value={query}
            onInput={(e) => setQuery(e.currentTarget.value)}
            onKeyDown={handleKeyDown}
            disabled={noTables || isLoading}
            rows={3}
          />
        </div>

        {/* Search button */}
        <div class="ics-search-actions">
          <button
            type="button"
            class="ics-ops-btn ics-ops-btn--primary"
            onClick={handleSearch}
            disabled={!query.trim() || noTables || isLoading}
          >
            {isLoading ? (
              <>
                <Loader2 size={16} class="ics-spinner" />
                <span>{t('search.nl.searching')}</span>
              </>
            ) : (
              <>
                <Search size={16} />
                <span>{t('search.nl.search')}</span>
              </>
            )}
          </button>
        </div>
      </div>

      {noTables && (
        <p class="oj-typography-body-sm oj-sm-margin-4x-top">{t('search.error.noTables')}</p>
      )}

      {/* Results */}
      {result && (
        <div class="ics-nl-results oj-sm-margin-6x-top">
          {/* Generated SQL */}
          {result.generated_sql && (
            <div class="ics-form-group">
              <div class="ics-sql-header">
                <label class="ics-form-label">{t('search.nl.generatedSql')}</label>
                <button
                  type="button"
                  class="ics-copy-btn"
                  onClick={handleCopySQL}
                  title={t('search.nl.copySql')}
                >
                  {copied ? <Check size={14} /> : <Copy size={14} />}
                  <span>{copied ? t('search.nl.copiedSql') : t('search.nl.copySql')}</span>
                </button>
              </div>
              <pre class="ics-search-sql"><code>{result.generated_sql}</code></pre>
            </div>
          )}

          {/* Explanation */}
          {result.explanation && (
            <div class="ics-form-group">
              <label class="ics-form-label">{t('search.nl.explanation')}</label>
              <p class="oj-typography-body-sm">{result.explanation}</p>
            </div>
          )}

          {/* Results table */}
          {result.results && (
            <div class="ics-form-group">
              <label class="ics-form-label">
                {t('search.nl.resultCount').replace('{count}', String(result.results.total || 0))}
              </label>
              {result.results.rows && result.results.rows.length > 0 ? (
                <ResultsTable columns={result.results.columns} rows={result.results.rows} />
              ) : (
                <p class="oj-typography-body-sm">{t('search.nl.noResult')}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Table Browser Tab
// ─────────────────────────────────────────────────────────────────────────────

interface TableBrowserTabProps {
  searchableTables: SearchableTable[];
  tableBrowserTables: TableBrowserTable[];
  isLoading: boolean;
  isTablesLoading: boolean;
  isTableListLoading: boolean;
  result: TableBrowseResult | null;
}

function TableBrowserTab({
  searchableTables,
  tableBrowserTables,
  isLoading,
  isTablesLoading,
  isTableListLoading,
  result
}: TableBrowserTabProps) {
  const dispatch = useAppDispatch();
  const { requestConfirm, confirmToast } = useToastConfirm();
  const initialSearchParams = getCurrentSearchParams();
  const [tableListPageSize, setTableListPageSize] = useState(() => {
    const next = readScopedNumber(initialSearchParams, SEARCH_TABLE_LIST_QUERY_SCOPE, 'ps', 20);
    return SEARCH_PAGINATION_PAGE_SIZE_OPTIONS.includes(next) ? next : 20;
  });
  const [tableListInitialPage] = useState(() => {
    const next = readScopedNumber(initialSearchParams, SEARCH_TABLE_LIST_QUERY_SCOPE, 'p', 1);
    return next >= 1 ? next : 1;
  });
  const [dataPageSize, setDataPageSize] = useState(() => {
    const next = readScopedNumber(initialSearchParams, SEARCH_DATA_PREVIEW_QUERY_SCOPE, 'ps', 20);
    return SEARCH_PAGINATION_PAGE_SIZE_OPTIONS.includes(next) ? next : 20;
  });
  const [selectedTable, setSelectedTable] = useState<TableBrowserTable | null>(null);
  const [page, setPage] = useState(() => {
    const next = readScopedNumber(initialSearchParams, SEARCH_DATA_PREVIEW_QUERY_SCOPE, 'p', 1);
    return next >= 1 ? next : 1;
  });
  const [goToPageInput, setGoToPageInput] = useState('');
  const [deletingRowId, setDeletingRowId] = useState<string | null>(null);
  const [isBulkDeletingRows, setIsBulkDeletingRows] = useState(false);
  const [tableListSortKey, setTableListSortKey] = useState<TableListSortKey>('created_at');
  const [tableListSortDirection, setTableListSortDirection] = useState<SortDirection>('desc');
  const [dataSortColumn, setDataSortColumn] = useState('');
  const [dataSortDirection, setDataSortDirection] = useState<SortDirection>('desc');
  const isTableListPageSizeInitRef = useRef(true);

  const sortedTableBrowserTables = useMemo(() => {
    const factor = tableListSortDirection === 'asc' ? 1 : -1;
    return [...tableBrowserTables].sort((a, b) => {
      if (tableListSortKey === 'table_name') {
        return factor * a.table_name.localeCompare(b.table_name, 'ja');
      }
      if (tableListSortKey === 'category_name') {
        return factor * a.category_name.localeCompare(b.category_name, 'ja');
      }
      if (tableListSortKey === 'table_type') {
        return factor * a.table_type.localeCompare(b.table_type, 'en');
      }
      if (tableListSortKey === 'row_count') {
        return factor * ((a.row_count || 0) - (b.row_count || 0));
      }
      if (tableListSortKey === 'column_count') {
        return factor * ((a.column_count || 0) - (b.column_count || 0));
      }
      const aTime = new Date(a.created_at || '').getTime() || 0;
      const bTime = new Date(b.created_at || '').getTime() || 0;
      return factor * (aTime - bTime);
    });
  }, [tableBrowserTables, tableListSortDirection, tableListSortKey]);

  const sortedDataRows = useMemo(() => {
    if (!result?.rows || result.rows.length === 0 || !dataSortColumn) {
      return result?.rows || [];
    }
    const factor = dataSortDirection === 'asc' ? 1 : -1;
    return [...result.rows].sort((a, b) => factor * compareValues(a[dataSortColumn], b[dataSortColumn]));
  }, [result?.rows, dataSortColumn, dataSortDirection]);

  // テーブル一覧ページネーション (client-side via usePagination hook)
  const tableListPagination = usePagination(sortedTableBrowserTables, {
    pageSize: tableListPageSize,
    initialPage: tableListInitialPage
  });

  // テーブル一覧選択
  const tableListSelection = useSelection<TableBrowserTable>({
    getItemId: (table) => `${table.category_id}-${table.table_type}-${table.table_name}`,
  });

  // テーブルデータプレビュー行選択
  const dataRowSelection = useSelection<Record<string, any>>({
    getItemId: (row) => {
      const raw = row.ROW_ID_META;
      return (raw === null || raw === undefined || raw === '') ? '' : String(raw);
    },
    isSelectable: (row) => {
      const raw = row.ROW_ID_META;
      return raw !== null && raw !== undefined && raw !== '';
    },
  });

  // データプレビューの行選択をページ/テーブル変更時にリセット
  useEffect(() => {
    dataRowSelection.reset();
  }, [selectedTable, page]);

  useEffect(() => {
    if (isTableListPageSizeInitRef.current) {
      isTableListPageSizeInitRef.current = false;
      return;
    }
    tableListPagination.reset();
    tableListSelection.deselectAll();
  }, [tableListPageSize]);

  useEffect(() => {
    tableListPagination.reset();
    tableListSelection.deselectAll();
  }, [tableListSortKey, tableListSortDirection]);

  useEffect(() => {
    const params = getCurrentSearchParams();
    setScopedValue(params, SEARCH_TABLE_LIST_QUERY_SCOPE, 'p', tableListPagination.currentPage);
    setScopedValue(params, SEARCH_TABLE_LIST_QUERY_SCOPE, 'ps', tableListPageSize);
    replaceSearchParams(params);
  }, [tableListPagination.currentPage, tableListPageSize]);

  useEffect(() => {
    const params = getCurrentSearchParams();
    setScopedValue(params, SEARCH_DATA_PREVIEW_QUERY_SCOPE, 'p', page);
    setScopedValue(params, SEARCH_DATA_PREVIEW_QUERY_SCOPE, 'ps', dataPageSize);
    replaceSearchParams(params);
  }, [page, dataPageSize]);

  useEffect(() => {
    if (!selectedTable && sortedTableBrowserTables.length > 0) {
      setSelectedTable(sortedTableBrowserTables[0]);
      return;
    }
    if (selectedTable) {
      const stillExists = sortedTableBrowserTables.some(table =>
        table.table_name === selectedTable.table_name &&
        table.table_type === selectedTable.table_type &&
        table.category_id === selectedTable.category_id
      );
      if (!stillExists) {
        setSelectedTable(sortedTableBrowserTables[0] || null);
        setPage(1);
        tableListPagination.reset();
      }
    }
  }, [sortedTableBrowserTables, selectedTable]);

  useEffect(() => {
    if (!result?.columns || result.columns.length === 0) {
      setDataSortColumn('');
      return;
    }
    if (!dataSortColumn || !result.columns.includes(dataSortColumn)) {
      setDataSortColumn(getDefaultDataSortColumn(result.columns));
      setDataSortDirection('desc');
    }
  }, [result?.columns, dataSortColumn]);

  // Load data when selected table or page changes
  useEffect(() => {
    if (selectedTable?.table_name) {
      dispatch(fetchTableDataByName({
        tableName: selectedTable.table_name,
        tableType: selectedTable.table_type,
        page,
        pageSize: dataPageSize
      }));
    }
  }, [dispatch, selectedTable, page, dataPageSize]);

  const noTables = !isTablesLoading && searchableTables.length === 0;
  const totalPages = result?.total_pages || 1;

  const handleRefreshTables = useCallback(() => {
    dispatch(fetchTableBrowserTables());
  }, [dispatch]);
  const handleRefreshData = useCallback(() => {
    if (!selectedTable?.table_name) return;
    dispatch(fetchTableDataByName({
      tableName: selectedTable.table_name,
      tableType: selectedTable.table_type,
      page,
      pageSize: dataPageSize,
    }));
  }, [dispatch, selectedTable, page, dataPageSize]);
  const handleTableListSort = useCallback((nextKey: TableListSortKey) => {
    setTableListSortKey(prevKey => {
      if (prevKey === nextKey) {
        setTableListSortDirection(prevDir => (prevDir === 'asc' ? 'desc' : 'asc'));
        return prevKey;
      }
      setTableListSortDirection('asc');
      return nextKey;
    });
  }, []);
  const handleDataSort = useCallback((nextColumn: string) => {
    if (!nextColumn) return;
    setDataSortColumn(prevColumn => {
      if (prevColumn === nextColumn) {
        setDataSortDirection(prevDir => (prevDir === 'asc' ? 'desc' : 'asc'));
        return prevColumn;
      }
      setDataSortDirection('asc');
      return nextColumn;
    });
  }, []);

  const handleTableSelect = useCallback((table: TableBrowserTable) => {
    setSelectedTable(table);
    setPage(1);
    setGoToPageInput('');
  }, []);
  const handleTableRowKeyDown = useCallback((e: KeyboardEvent, table: TableBrowserTable) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleTableSelect(table);
    }
  }, [handleTableSelect]);

  const handlePageChange = useCallback((nextPage: number) => {
    if (nextPage >= 1 && nextPage <= totalPages) {
      setPage(nextPage);
    }
  }, [totalPages]);

  const handleGoToPage = useCallback(() => {
    const target = parseInt(goToPageInput, 10);
    if (!Number.isNaN(target) && target >= 1 && target <= totalPages) {
      setPage(target);
      setGoToPageInput('');
    }
  }, [goToPageInput, totalPages]);

  const getRowId = useCallback((row: Record<string, any>): string | null => {
    const raw = row.ROW_ID_META;
    if (raw === null || raw === undefined || raw === '') return null;
    return String(raw);
  }, []);

  const handleDeleteRow = useCallback((row: Record<string, any>) => {
    const rowId = getRowId(row);
    if (!rowId || !selectedTable) return;
    requestConfirm({
      message: t('search.browser.deleteRowConfirm'),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      onConfirm: async () => {
        setDeletingRowId(rowId);
        try {
          await apiPost<{ success: boolean }>('/api/v1/search/table-browser/delete-row', {
            table_name: selectedTable.table_name,
            row_id: rowId
          });
          dispatch(addNotification({
            type: 'success',
            message: t('search.browser.deleteRowSuccess')
          }));
          dispatch(fetchTableBrowserTables());
          dispatch(fetchTableDataByName({
            tableName: selectedTable.table_name,
            tableType: selectedTable.table_type,
            page,
            pageSize: dataPageSize
          }));
        } catch {
          dispatch(addNotification({
            type: 'error',
            message: t('search.browser.deleteRowFailed')
          }));
        } finally {
          setDeletingRowId(null);
        }
      }
    });
  }, [dispatch, getRowId, selectedTable, page, dataPageSize, requestConfirm]);

  const handleBulkDeleteRows = useCallback(() => {
    if (!selectedTable || dataRowSelection.selectedCount === 0) return;
    const targetRowIds = Array.from(dataRowSelection.selectedIds);
    requestConfirm({
      message: t('search.browser.confirmBulkDelete', { count: targetRowIds.length }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      onConfirm: async () => {
        setIsBulkDeletingRows(true);
        let deletedCount = 0;
        let failedCount = 0;
        for (const rowId of targetRowIds) {
          try {
            await apiPost<{ success: boolean }>('/api/v1/search/table-browser/delete-row', {
              table_name: selectedTable.table_name,
              row_id: rowId,
            });
            deletedCount += 1;
          } catch {
            failedCount += 1;
          }
        }
        dataRowSelection.deselectAll();
        dispatch(fetchTableBrowserTables());
        dispatch(fetchTableDataByName({
          tableName: selectedTable.table_name,
          tableType: selectedTable.table_type,
          page,
          pageSize: dataPageSize,
        }));
        if (deletedCount > 0 && failedCount === 0) {
          dispatch(addNotification({
            type: 'success',
            message: t('search.browser.bulkDeleteSuccess', { count: deletedCount }),
          }));
        } else if (deletedCount > 0) {
          dispatch(addNotification({
            type: 'warning',
            message: t('search.browser.bulkDeletePartial', { deleted: deletedCount, errors: failedCount }),
          }));
        } else {
          dispatch(addNotification({
            type: 'error',
            message: t('search.browser.bulkDeleteFailed'),
          }));
        }
        setIsBulkDeletingRows(false);
      },
    });
  }, [selectedTable, dataRowSelection.selectedCount, dataRowSelection.selectedIds, requestConfirm, dispatch, page, dataPageSize]);

  const handleDataPageSizeChange = useCallback((nextPageSize: number) => {
    if (!SEARCH_PAGINATION_PAGE_SIZE_OPTIONS.includes(nextPageSize)) return;
    setDataPageSize(nextPageSize);
    setPage(1);
    setGoToPageInput('');
  }, []);

  const tableListRangeStart = tableListPagination.totalItems === 0 ? 0 : tableListPagination.startIndex;
  const tableListRangeEnd = tableListPagination.totalItems === 0 ? 0 : tableListPagination.endIndex;
  const dataRangeStart = (result?.total || 0) === 0 ? 0 : ((page - 1) * dataPageSize) + 1;
  const dataRangeEnd = (result?.total || 0) === 0 ? 0 : Math.min(page * dataPageSize, result?.total || 0);
  const renderTableListSortIcon = (key: TableListSortKey) => {
    if (tableListSortKey !== key) return <ArrowUpDown size={13} />;
    return tableListSortDirection === 'asc' ? <ArrowUp size={13} /> : <ArrowDown size={13} />;
  };

  return (
    <div class="ics-table-browser">
      <div class="ics-card ics-ops-panel">
        <div class="ics-card-header ics-card-header--table-toolbar">
          <div class="ics-unified-table-header">
            <span class="oj-typography-heading-xs">{t('search.browser.tableListTitle')}</span>
            <div class="ics-unified-table-toolbar">
              <div class="ics-unified-table-toolbar__group">
                <span class="ics-unified-table-toolbar__meta">
                  {t('search.browser.selectedTables', { count: tableListSelection.selectedCount })}
                </span>
              </div>
              <div class="ics-unified-table-toolbar__group ics-unified-table-toolbar__group--secondary">
                <button
                  type="button"
                  class="ics-ops-btn ics-ops-btn--ghost"
                  onClick={handleRefreshTables}
                  disabled={isTableListLoading}
                >
                  {isTableListLoading ? <Loader2 size={14} class="ics-spinner" /> : <RefreshCw size={14} />}
                  <span>{t('search.browser.refresh')}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="ics-card-body">
          {tableBrowserTables.length > 0 ? (
            <>
              <div class="ics-table-wrapper">
                <table class="ics-table">
                  <thead>
                    <tr>
                      <th style={{ width: '40px' }}>
                        <input
                          type="checkbox"
                          checked={tableListSelection.isAllSelected(tableListPagination.paginatedItems)}
                          ref={(el) => {
                            if (!el) return;
                            const pageItems = tableListPagination.paginatedItems;
                            const allSelected = tableListSelection.isAllSelected(pageItems);
                            const hasSelectedOnPage = pageItems.some(item =>
                              tableListSelection.isSelected(`${item.category_id}-${item.table_type}-${item.table_name}`)
                            );
                            el.indeterminate = !allSelected && hasSelectedOnPage;
                          }}
                          onChange={() => {
                            if (tableListSelection.isAllSelected(tableListPagination.paginatedItems)) {
                              tableListSelection.deselectAll();
                            } else {
                              tableListSelection.selectAll(tableListPagination.paginatedItems);
                            }
                          }}
                          aria-label={t('common.selectAll')}
                        />
                      </th>
                      <th>
                        <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleTableListSort('table_name')}>
                          {t('search.browser.col.tableName')}
                          {renderTableListSortIcon('table_name')}
                        </button>
                      </th>
                      <th>
                        <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleTableListSort('category_name')}>
                          {t('search.browser.col.category')}
                          {renderTableListSortIcon('category_name')}
                        </button>
                      </th>
                      <th>
                        <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleTableListSort('table_type')}>
                          {t('search.browser.col.type')}
                          {renderTableListSortIcon('table_type')}
                        </button>
                      </th>
                      <th>
                        <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleTableListSort('row_count')}>
                          {t('search.browser.col.rows')}
                          {renderTableListSortIcon('row_count')}
                        </button>
                      </th>
                      <th>
                        <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleTableListSort('column_count')}>
                          {t('search.browser.col.columns')}
                          {renderTableListSortIcon('column_count')}
                        </button>
                      </th>
                      <th>
                        <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleTableListSort('created_at')}>
                          {t('search.browser.col.createdAt')}
                          {renderTableListSortIcon('created_at')}
                        </button>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableListPagination.paginatedItems.map(table => {
                      const tableKey = `${table.category_id}-${table.table_type}-${table.table_name}`;
                      return (
                        <tr
                          key={tableKey}
                          role="button"
                          tabIndex={0}
                          class={
                            selectedTable &&
                              selectedTable.table_name === table.table_name &&
                              selectedTable.table_type === table.table_type &&
                              selectedTable.category_id === table.category_id
                              ? 'ics-table-row--selected'
                              : ''
                          }
                          onClick={() => handleTableSelect(table)}
                          onKeyDown={(e) => handleTableRowKeyDown(e, table)}
                        >
                          <td class="ics-table__cell--center" onClick={(e: Event) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={tableListSelection.isSelected(tableKey)}
                              onChange={() => tableListSelection.toggle(tableKey)}
                            />
                          </td>
                          <td>{table.table_name}</td>
                          <td>{table.category_name}</td>
                          <td>{table.table_type === 'header' ? t('search.browser.header') : t('search.browser.line')}</td>
                          <td>{table.row_count.toLocaleString()}</td>
                          <td>{table.column_count}</td>
                          <td>{formatDateTime(table.created_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <Pagination
                currentPage={tableListPagination.currentPage}
                totalPages={tableListPagination.totalPages}
                totalItems={tableListPagination.totalItems}
                pageSize={tableListPageSize}
                pageSizeOptions={SEARCH_PAGINATION_PAGE_SIZE_OPTIONS}
                onPageSizeChange={setTableListPageSize}
                goToPageInput={tableListPagination.goToPageInput}
                onPageChange={tableListPagination.goToPage}
                onGoToPageInputChange={tableListPagination.setGoToPageInput}
                onGoToPage={tableListPagination.handleGoToPage}
                rangeStart={tableListRangeStart}
                rangeEnd={tableListRangeEnd}
                showGoToPage={false}
                isFirstPage={tableListPagination.isFirstPage}
                isLastPage={tableListPagination.isLastPage}
                position="bottom"
                show
                summaryPlacement="controls"
              />
            </>
          ) : (
            <p class="oj-typography-body-sm oj-sm-margin-4x-top">{t('search.browser.noTableList')}</p>
          )}
        </div>
      </div>

      {selectedTable && (
        <div class="ics-card ics-ops-panel oj-sm-margin-4x-top">
          <div class="ics-card-header ics-card-header--table-toolbar">
            <div class="ics-unified-table-header">
              <div class="ics-browser-title-wrap">
                <span class="oj-typography-heading-xs">
                  {t('search.browser.previewTitle')}
                </span>
                <span class="ics-browser-table-chip">{selectedTable.table_name}</span>
              </div>
              <div class="ics-unified-table-toolbar">
                <div class="ics-unified-table-toolbar__group">
                  <button
                    type="button"
                    class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
                    onClick={handleBulkDeleteRows}
                    disabled={dataRowSelection.selectedCount === 0 || isBulkDeletingRows || isLoading}
                  >
                    <Trash2 size={14} />
                    <span>{t('fileList.bulkDelete')}</span>
                  </button>
                  <span class="ics-unified-table-toolbar__meta">
                    {t('search.browser.selectedRows', { count: dataRowSelection.selectedCount })}
                  </span>
                </div>
                <div class="ics-unified-table-toolbar__group ics-unified-table-toolbar__group--secondary">
                  <button
                    type="button"
                    class="ics-ops-btn ics-ops-btn--ghost"
                    onClick={handleRefreshData}
                    disabled={isLoading}
                  >
                    {isLoading ? <Loader2 size={14} class="ics-spinner" /> : <RefreshCw size={14} />}
                    <span>{t('search.browser.refresh')}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
          <div class="ics-card-body">
            {isLoading && (
              <div class="ics-loading oj-sm-margin-4x-top">
                <Loader2 size={24} class="ics-spinner" />
                <span>{t('common.loading')}</span>
              </div>
            )}

            {!isLoading && result && (
              <div class="ics-browser-results oj-sm-margin-4x-top">
                {result.rows && result.rows.length > 0 ? (
                  <>
                    <ResultsTable
                      columns={result.columns}
                      rows={sortedDataRows}
                      sortColumn={dataSortColumn}
                      sortDirection={dataSortDirection}
                      onSortColumn={handleDataSort}
                      actionColumnLabel={t('search.browser.col.actions')}
                      renderRowActions={(row) => {
                        const rowId = getRowId(row);
                        if (!rowId) return null;
                        return (
                          <button
                            type="button"
                            class="ics-ops-btn ics-ops-btn--ghost"
                            onClick={() => handleDeleteRow(row)}
                            disabled={deletingRowId === rowId}
                            title={t('common.delete')}
                          >
                            {deletingRowId === rowId
                              ? <Loader2 size={14} class="ics-spinner" />
                              : <Trash2 size={14} />
                            }
                          </button>
                        );
                      }}
                      selection={dataRowSelection}
                    />

                    <Pagination
                      currentPage={page}
                      totalPages={totalPages}
                      totalItems={result.total || 0}
                      pageSize={dataPageSize}
                      pageSizeOptions={SEARCH_PAGINATION_PAGE_SIZE_OPTIONS}
                      onPageSizeChange={handleDataPageSizeChange}
                      goToPageInput={goToPageInput}
                      onPageChange={handlePageChange}
                      onGoToPageInputChange={setGoToPageInput}
                      onGoToPage={handleGoToPage}
                      rangeStart={dataRangeStart}
                      rangeEnd={dataRangeEnd}
                      showGoToPage={false}
                      isFirstPage={page <= 1 || isLoading}
                      isLastPage={page >= totalPages || isLoading}
                      position="bottom"
                      show
                      summaryPlacement="controls"
                    />
                  </>
                ) : (
                  <p class="oj-typography-body-sm oj-sm-margin-4x-top">{t('search.browser.noData')}</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {noTables && (
        <p class="oj-typography-body-sm oj-sm-margin-4x-top">{t('search.error.noTables')}</p>
      )}
      {confirmToast}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Results Table (shared)
// ─────────────────────────────────────────────────────────────────────────────

interface ResultsTableProps {
  columns: string[];
  rows: Record<string, any>[];
  sortColumn?: string;
  sortDirection?: SortDirection;
  onSortColumn?: (column: string) => void;
  actionColumnLabel?: string;
  renderRowActions?: (row: Record<string, any>) => ComponentChildren;
  /** Optional selection support via useSelection hook */
  selection?: UseSelectionResult<Record<string, any>>;
}

function ResultsTable({
  columns,
  rows,
  sortColumn,
  sortDirection,
  onSortColumn,
  actionColumnLabel,
  renderRowActions,
  selection
}: ResultsTableProps) {
  if (!columns || columns.length === 0) return null;

  return (
    <div class="ics-table-wrapper">
      <table class="ics-table">
        <thead>
          <tr>
            {selection && (
              <th style={{ width: '40px' }}>
                <input
                  type="checkbox"
                  checked={selection.isAllSelected(rows)}
                  ref={(el) => {
                    if (!el) return;
                    const selectableRowIds = rows
                      .map((row) => row.ROW_ID_META)
                      .filter((raw) => raw !== null && raw !== undefined && raw !== '')
                      .map((raw) => String(raw));
                    const allSelected = selection.isAllSelected(rows);
                    const hasSelected = selectableRowIds.some(id => selection.isSelected(id));
                    el.indeterminate = !allSelected && hasSelected;
                  }}
                  onChange={() => {
                    if (selection.isAllSelected(rows)) {
                      selection.deselectAll();
                    } else {
                      selection.selectAll(rows);
                    }
                  }}
                  aria-label={t('common.selectAll')}
                />
              </th>
            )}
            {columns.map(col => (
              <th key={col}>
                {onSortColumn ? (
                  <button type="button" class="ics-fileListView__sortBtn" onClick={() => onSortColumn(col)}>
                    {col}
                    {sortColumn !== col
                      ? <ArrowUpDown size={13} />
                      : sortDirection === 'asc'
                        ? <ArrowUp size={13} />
                        : <ArrowDown size={13} />
                    }
                  </button>
                ) : (
                  col
                )}
              </th>
            ))}
            {renderRowActions && <th>{actionColumnLabel || ''}</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => {
            const rowId = selection ? (() => {
              const raw = row.ROW_ID_META;
              return (raw === null || raw === undefined || raw === '') ? '' : String(raw);
            })() : '';
            return (
              <tr key={idx} class={selection && rowId && selection.isSelected(rowId) ? 'ics-table__row--selected' : ''}>
                {selection && (
                  <td class="ics-table__cell--center">
                    <input
                      type="checkbox"
                      checked={rowId ? selection.isSelected(rowId) : false}
                      onChange={() => rowId && selection.toggle(rowId)}
                      disabled={!rowId}
                    />
                  </td>
                )}
                {columns.map(col => (
                  <td key={col}>{formatCellValue(row[col])}</td>
                ))}
                {renderRowActions && <td>{renderRowActions(row)}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function formatCellValue(value: any): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') {
    // Handle Date objects or complex types
    return JSON.stringify(value);
  }
  return String(value);
}

function formatDateTime(value?: string): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('ja-JP');
}
