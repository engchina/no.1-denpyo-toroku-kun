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
  nlSearchStartAsync,
  nlSearchPollJob,
  fetchTableDataByName,
  clearSearchResults,
  clearSearchError,
  setSearchActiveTab,
  setNlSearchQuery,
  setNlSearchCategoryId
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
import type { NLSearchResponse, NLSearchJobStatus, SearchableTable, TableBrowseResult, TableBrowserTable } from '../../types/denpyoTypes';
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
    nlSearchAsyncJobId,
    nlSearchAsyncJobStatus,
    nlSearchAsyncJobStartedAt,
    tableBrowseResult,
    isTableBrowsing,
    searchError,
    searchActiveTab: activeTab,
    nlSearchQuery,
    nlSearchCategoryId
  } = useAppSelector(state => state.denpyo);

  // Load searchable tables on mount
  // クリーンアップで clearSearchResults を呼ばない:
  //   - 処理中ジョブのステータスを保持するため
  //   - 完了済み結果を保持して、戻ってきた際にそのまま表示するため
  // 結果のクリアは「新しい検索開始時」と「カテゴリ変更時」のみ行う
  useEffect(() => {
    dispatch(fetchSearchableTables());
    dispatch(fetchTableBrowserTables());
  }, [dispatch]);

  const handleTabChange = (tab: TabType) => {
    dispatch(setSearchActiveTab(tab));
    dispatch(clearSearchError());
  };

  return (
    <div class="ics-dashboard ics-dashboard--enhanced ics-search-view">
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>{t('search.title')}</h2>
            <p class="ics-ops-hero__subtitle">{t('search.subtitle')}</p>
          </div>
        </div>
      </section>

      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel ics-search-tabPanel">
          <div class="ics-card-body ics-search-tabPanel__body">
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
          </div>
        </div>
      </section>

      {searchError && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-error-message">
            {searchError}
          </div>
        </section>
      )}

      {activeTab === 'nlSearch' ? (
        <NLSearchTab
          searchableTables={searchableTables}
          isLoading={isNLSearching}
          isTablesLoading={isSearchableTablesLoading}
          result={nlSearchResult}
          persistedQuery={nlSearchQuery}
          persistedCategoryId={nlSearchCategoryId}
          asyncJobId={nlSearchAsyncJobId}
          asyncJobStatus={nlSearchAsyncJobStatus}
          asyncJobStartedAt={nlSearchAsyncJobStartedAt}
        />
      ) : (
        <TableBrowserTab
          tableBrowserTables={tableBrowserTables}
          isLoading={isTableBrowsing}
          isTableListLoading={isTableBrowserTablesLoading}
          result={tableBrowseResult}
        />
      )}
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
  persistedQuery: string;
  persistedCategoryId: number | undefined;
  asyncJobId: string | null;
  asyncJobStatus: NLSearchJobStatus | null;
  asyncJobStartedAt: number | null;
}

function NLSearchTab({ searchableTables, isLoading, isTablesLoading, result, persistedQuery, persistedCategoryId, asyncJobId, asyncJobStatus, asyncJobStartedAt }: NLSearchTabProps) {
  const dispatch = useAppDispatch();
  const query = persistedQuery;
  const categoryId = persistedCategoryId;
  const setQuery = (value: string) => dispatch(setNlSearchQuery(value));
  const setCategoryId = (value: number | undefined) => dispatch(setNlSearchCategoryId(value));
  const [copied, setCopied] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [nlResultPageSize, setNlResultPageSize] = useState(20);
  const nlRows = result?.results?.rows ?? [];
  const nlResultPagination = usePagination(nlRows, { pageSize: nlResultPageSize });
  const nlRangeStart = (nlResultPagination.currentPage - 1) * nlResultPageSize + 1;
  const nlRangeEnd = Math.min(nlResultPagination.currentPage * nlResultPageSize, nlRows.length);

  // 開始時刻から経過秒数を計算する関数
  const calcElapsed = () =>
    asyncJobStartedAt ? Math.floor((Date.now() - asyncJobStartedAt) / 1000) : 0;
  const pollingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const selectedCategory = useMemo(
    () => searchableTables.find((table) => table.category_id === categoryId) || null,
    [categoryId, searchableTables],
  );

  useEffect(() => {
    if (searchableTables.length === 0) {
      setCategoryId(undefined);
      return;
    }
    const hasCurrent = searchableTables.some((table) => table.category_id === categoryId);
    if (!hasCurrent) {
      setCategoryId(searchableTables[0].category_id);
    }
  }, [categoryId, searchableTables]);

  // 新しい検索結果が来たらページをリセット
  const prevResultRef = useRef(result);
  useEffect(() => {
    if (result !== prevResultRef.current) {
      nlResultPagination.reset();
      prevResultRef.current = result;
    }
  }, [result]);

  // カテゴリ変更時のみ結果をクリアする（初回マウント時はスキップ）
  // 初回マウント時にクリアすると、画面遷移後の復帰時に非同期ジョブ状態が消えてしまう
  const isCategoryInitialMount = useRef(true);
  useEffect(() => {
    if (isCategoryInitialMount.current) {
      isCategoryInitialMount.current = false;
      return;
    }
    dispatch(clearSearchResults());
  }, [dispatch, categoryId]);

  // 非同期ジョブのポーリング
  useEffect(() => {
    if (!asyncJobId || !isLoading) {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
      return;
    }
    pollingIntervalRef.current = setInterval(() => {
      dispatch(nlSearchPollJob(asyncJobId));
    }, 3000);
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    };
  }, [asyncJobId, isLoading, dispatch]);

  // ポーリング完了後にテーブル一覧を更新
  useEffect(() => {
    if (asyncJobStatus === 'done' || asyncJobStatus === 'error') {
      dispatch(fetchSearchableTables());
    }
  }, [asyncJobStatus, dispatch]);

  // 経過時間カウンター（処理中の場合のみ）
  // 開始時刻（asyncJobStartedAt）から計算するため、画面遷移後も正確な経過時間を表示する
  useEffect(() => {
    if (isLoading && asyncJobId) {
      setElapsedSeconds(calcElapsed());
      elapsedTimerRef.current = setInterval(() => {
        setElapsedSeconds(calcElapsed());
      }, 1000);
    } else {
      if (elapsedTimerRef.current) {
        clearInterval(elapsedTimerRef.current);
        elapsedTimerRef.current = null;
      }
    }
    return () => {
      if (elapsedTimerRef.current) {
        clearInterval(elapsedTimerRef.current);
        elapsedTimerRef.current = null;
      }
    };
  }, [isLoading, asyncJobId, asyncJobStartedAt]);

  const handleSearch = useCallback(() => {
    if (!query.trim() || !selectedCategory) return;
    dispatch(nlSearchStartAsync({ query: query.trim(), category_id: selectedCategory.category_id }));
  }, [dispatch, query, selectedCategory]);

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

  const asyncStatusLabel = asyncJobStatus === 'running'
    ? t('search.nl.asyncStatus.running')
    : t('search.nl.asyncStatus.pending');

  return (
    <div class="ics-nl-search ics-search-stack">
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-body ics-search-panelBody">
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
                  {searchableTables.map(table => (
                    <option key={table.category_id} value={table.category_id}>
                      {table.category_name}
                    </option>
                  ))}
                </select>
                {selectedCategory && (
                  <div class="ics-search-profileMeta">
                    <span class="ics-search-profileMeta__label">{t('search.common.profileLabel')}</span>
                    <code class="ics-search-profileMeta__value">
                      {selectedCategory.select_ai_profile_name || t('search.common.profilePending')}
                    </code>
                    <span class="ics-search-profileMeta__status">
                      {selectedCategory.select_ai_profile_ready
                        ? t('search.common.profileReady')
                        : t('search.common.profileAutoCreate')}
                    </span>
                  </div>
                )}
                {selectedCategory?.select_ai_last_error && !selectedCategory.select_ai_profile_ready && (
                  <p class="ics-search-panelMessage">{selectedCategory.select_ai_last_error}</p>
                )}
              </div>

              {/* Query input */}
              <div class="ics-form-group">
                <label class="ics-form-label">{t('search.nl.queryLabel')}</label>
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
                  disabled={!query.trim() || !selectedCategory || noTables || isLoading}
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

              {/* 処理ステータス */}
              {isLoading && asyncJobId && (
                <div class="ics-search-asyncStatus">
                  <Loader2 size={15} class="ics-spinner" />
                  <span class="ics-search-asyncStatus__label">
                    {t('search.nl.asyncStatus.processing')}
                  </span>
                  <span class="ics-search-asyncStatus__status">
                    ({asyncStatusLabel})
                  </span>
                  <code class="ics-search-asyncStatus__jobId" title={asyncJobId}>
                    {asyncJobId.slice(0, 8)}…
                  </code>
                  <span class="ics-search-asyncStatus__elapsed">
                    {t('search.nl.asyncStatus.elapsed').replace('{elapsed}', String(elapsedSeconds))}
                  </span>
                </div>
              )}
            </div>

            {noTables && (
              <p class="ics-search-panelMessage">{t('search.error.noTables')}</p>
            )}
          </div>
        </div>
      </section>

      {result && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-card ics-ops-panel">
            <div class="ics-card-body">
              <div class="ics-nl-results">
                <div class="ics-search-engineStrip">
                  <span class="ics-search-engineStrip__label">{t('search.nl.engineLabel')}</span>
                  <span class="ics-search-engineBadge">
                    {result.engine === 'direct_llm' ? t('search.nl.engine.directLlm') : t('search.nl.engine.selectAiAgent')}
                  </span>
                  {result.engine_meta?.api_format && (
                    <span class="ics-search-engineMeta">
                      {t('search.nl.meta.apiFormat').replace('{value}', result.engine_meta.api_format)}
                    </span>
                  )}
                  {typeof result.engine_meta?.use_comments === 'boolean' && (
                    <span class="ics-search-engineMeta">
                      {result.engine_meta.use_comments ? t('search.nl.meta.commentsOn') : t('search.nl.meta.commentsOff')}
                    </span>
                  )}
                </div>

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
                      <div class="ics-browser-results">
                        <ResultsTable columns={result.results.columns} rows={nlResultPagination.currentItems} />
                        <Pagination
                          currentPage={nlResultPagination.currentPage}
                          totalPages={nlResultPagination.totalPages}
                          totalItems={nlResultPagination.totalItems}
                          pageSize={nlResultPageSize}
                          pageSizeOptions={SEARCH_PAGINATION_PAGE_SIZE_OPTIONS}
                          onPageSizeChange={(size) => { setNlResultPageSize(size); nlResultPagination.reset(); }}
                          goToPageInput={nlResultPagination.goToPageInput}
                          onPageChange={nlResultPagination.goToPage}
                          onGoToPageInputChange={nlResultPagination.setGoToPageInput}
                          onGoToPage={nlResultPagination.handleGoToPage}
                          isFirstPage={nlResultPagination.isFirstPage}
                          isLastPage={nlResultPagination.isLastPage}
                          rangeStart={nlRangeStart}
                          rangeEnd={nlRangeEnd}
                          showGoToPage={false}
                          show={nlResultPagination.showPagination}
                          position="bottom"
                          summaryPlacement="controls"
                        />
                      </div>
                    ) : (
                      <p class="oj-typography-body-sm">{t('search.nl.noResult')}</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Table Browser Tab
// ─────────────────────────────────────────────────────────────────────────────

interface TableBrowserTabProps {
  tableBrowserTables: TableBrowserTable[];
  isLoading: boolean;
  isTableListLoading: boolean;
  result: TableBrowseResult | null;
}

function TableBrowserTab({
  tableBrowserTables,
  isLoading,
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
    <div class="ics-table-browser ics-search-stack">
      <section class="ics-ops-grid ics-ops-grid--one">
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
              <div class="ics-browser-results">
                <div class="ics-table-wrapper">
                  <table class="ics-table ics-search-tableBrowserTableList">
                    <thead>
                      <tr>
                        <th>
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
                            <td onClick={(e: Event) => e.stopPropagation()}>
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
              </div>
            ) : (
              <p class="ics-search-panelMessage">{t('search.browser.noTableList')}</p>
            )}
          </div>
        </div>
      </section>

      {selectedTable && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-card ics-ops-panel">
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
                <div class="ics-loading">
                  <Loader2 size={24} class="ics-spinner" />
                  <span>{t('common.loading')}</span>
                </div>
              )}

              {!isLoading && result && (
                <div class="ics-browser-results">
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
                    <p class="ics-search-panelMessage">{t('search.browser.noData')}</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </section>
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
              <th>
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
                  <td>
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
