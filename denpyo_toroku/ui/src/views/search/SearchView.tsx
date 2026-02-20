/**
 * SearchView - データ検索画面 (SCR-006)
 * - 自然言語検索 (NL -> SQL)
 * - テーブルブラウザ (直接閲覧)
 */
import type { ComponentChildren } from 'preact';
import { useState, useEffect, useCallback } from 'preact/hooks';
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
import { useToastConfirm } from '../../hooks/useToastConfirm';
import { t } from '../../i18n';
import { apiPost } from '../../utils/apiUtils';
import type { NLSearchResponse, SearchableTable, TableBrowseResult, TableBrowserTable } from '../../types/denpyoTypes';
import { Search, Database, Copy, Check, Loader2, RefreshCw, Trash2 } from 'lucide-react';

type TabType = 'nlSearch' | 'tableBrowser';

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
            class="oj-button oj-button-primary"
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
  const [selectedTable, setSelectedTable] = useState<TableBrowserTable | null>(null);
  const [page, setPage] = useState(1);
  const [goToPageInput, setGoToPageInput] = useState('');
  const [deletingRowId, setDeletingRowId] = useState<string | null>(null);
  const pageSize = 20;

  // テーブル一覧ページネーション (client-side via usePagination hook)
  const tableListPagination = usePagination(tableBrowserTables, { pageSize: 20 });

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
    if (!selectedTable && tableBrowserTables.length > 0) {
      setSelectedTable(tableBrowserTables[0]);
      return;
    }
    if (selectedTable) {
      const stillExists = tableBrowserTables.some(table =>
        table.table_name === selectedTable.table_name &&
        table.table_type === selectedTable.table_type &&
        table.category_id === selectedTable.category_id
      );
      if (!stillExists) {
        setSelectedTable(tableBrowserTables[0] || null);
        setPage(1);
        tableListPagination.reset();
      }
    }
  }, [tableBrowserTables, selectedTable]);

  // Load data when selected table or page changes
  useEffect(() => {
    if (selectedTable?.table_name) {
      dispatch(fetchTableDataByName({
        tableName: selectedTable.table_name,
        tableType: selectedTable.table_type,
        page,
        pageSize
      }));
    }
  }, [dispatch, selectedTable, page]);

  const noTables = !isTablesLoading && searchableTables.length === 0;
  const totalPages = result?.total_pages || 1;
  const tableListStatusLabel = isTableListLoading
    ? t('search.browser.tableListStatus.loading')
    : tableBrowserTables.length > 0
      ? t('search.browser.tableListStatus.loaded')
      : t('search.browser.tableListStatus.empty');
  const tableListStatusClass = isTableListLoading
    ? 'ics-browser-status-badge ics-browser-status-badge--loading'
    : tableBrowserTables.length > 0
      ? 'ics-browser-status-badge ics-browser-status-badge--success'
      : 'ics-browser-status-badge';

  const handleRefreshTables = useCallback(() => {
    dispatch(fetchTableBrowserTables());
  }, [dispatch]);

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
            pageSize
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
  }, [dispatch, getRowId, selectedTable, page, pageSize, requestConfirm]);

  return (
    <div class="ics-table-browser">
      <div class="ics-browser-panel">
        <div class="ics-browser-panel__header">
          <span class="ics-browser-panel__title">{t('search.browser.tableListTitle')}</span>
          <div class="ics-browser-panel__actions">
            <button
              type="button"
              class="ics-copy-btn"
              onClick={handleRefreshTables}
              disabled={isTableListLoading}
            >
              {isTableListLoading ? <Loader2 size={14} class="ics-spinner" /> : <RefreshCw size={14} />}
              <span>{t('search.browser.refresh')}</span>
            </button>
            <span class={tableListStatusClass}>{tableListStatusLabel}</span>
          </div>
        </div>

        {tableBrowserTables.length > 0 ? (
          <div class="ics-table-list-wrapper">
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
                  <th>{t('search.browser.col.tableName')}</th>
                  <th>{t('search.browser.col.category')}</th>
                  <th>{t('search.browser.col.type')}</th>
                  <th>{t('search.browser.col.rows')}</th>
                  <th>{t('search.browser.col.columns')}</th>
                  <th>{t('search.browser.col.createdAt')}</th>
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
            <Pagination
              currentPage={tableListPagination.currentPage}
              totalPages={tableListPagination.totalPages}
              totalItems={tableListPagination.totalItems}
              goToPageInput={tableListPagination.goToPageInput}
              onPageChange={tableListPagination.goToPage}
              onGoToPageInputChange={tableListPagination.setGoToPageInput}
              onGoToPage={tableListPagination.handleGoToPage}
              isFirstPage={tableListPagination.isFirstPage}
              isLastPage={tableListPagination.isLastPage}
              position="bottom"
              show
            />
          </div>
        ) : (
          <p class="oj-typography-body-sm oj-sm-margin-4x-top">{t('search.browser.noTableList')}</p>
        )}
      </div>

      {selectedTable && (
        <div class="ics-browser-panel oj-sm-margin-4x-top">
          <div class="ics-browser-panel__header">
            <div class="ics-browser-title-wrap">
              <span class="ics-browser-panel__title">
                {t('search.browser.previewTitle')}
              </span>
              <span class="ics-browser-table-chip">{selectedTable.table_name}</span>
            </div>
            <div class="ics-results-header">
              <span class="oj-typography-body-sm">
                {t('search.browser.totalRows').replace('{count}', String(result?.total || 0))}
              </span>
              <span class="oj-typography-body-sm">
                {t('search.browser.lastAnalyzed').replace('{value}', formatDateTime(selectedTable.last_analyzed))}
              </span>
            </div>
          </div>

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
                    rows={result.rows}
                    actionColumnLabel={t('search.browser.col.actions')}
                    renderRowActions={(row) => {
                      const rowId = getRowId(row);
                      if (!rowId) return null;
                      return (
                        <button
                          type="button"
                          class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
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
                    goToPageInput={goToPageInput}
                    onPageChange={handlePageChange}
                    onGoToPageInputChange={setGoToPageInput}
                    onGoToPage={handleGoToPage}
                    isFirstPage={page <= 1 || isLoading}
                    isLastPage={page >= totalPages || isLoading}
                    position="bottom"
                    show
                  />
                </>
              ) : (
                <p class="oj-typography-body-sm oj-sm-margin-4x-top">{t('search.browser.noData')}</p>
              )}
            </div>
          )}
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
  actionColumnLabel?: string;
  renderRowActions?: (row: Record<string, any>) => ComponentChildren;
  /** Optional selection support via useSelection hook */
  selection?: import('../../hooks/useSelection').UseSelectionResult<Record<string, any>>;
}

function ResultsTable({ columns, rows, actionColumnLabel, renderRowActions, selection }: ResultsTableProps) {
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
              <th key={col}>{col}</th>
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
