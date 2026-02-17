/**
 * SearchView - データ検索画面 (SCR-006)
 * - 自然言語検索 (NL -> SQL)
 * - テーブルブラウザ (直接閲覧)
 */
import { useState, useEffect, useCallback } from 'preact/hooks';
import { useAppSelector, useAppDispatch } from '../../redux/store';
import {
  fetchSearchableTables,
  nlSearch,
  fetchTableData,
  clearSearchResults,
  clearSearchError
} from '../../redux/slices/denpyoSlice';
import { t } from '../../i18n';
import { Search, Database, Copy, Check, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';

type TabType = 'nlSearch' | 'tableBrowser';

export function SearchView() {
  const dispatch = useAppDispatch();
  const {
    searchableTables,
    isSearchableTablesLoading,
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
    return () => {
      dispatch(clearSearchResults());
    };
  }, [dispatch]);

  const handleTabChange = (tab: TabType) => {
    setActiveTab(tab);
    dispatch(clearSearchError());
  };

  return (
    <div class="ics-view-container">
      <header class="ics-view-header">
        <h1 class="oj-typography-heading-md">{t('search.title')}</h1>
        <p class="oj-typography-body-sm oj-sm-margin-2x-top">{t('search.subtitle')}</p>
      </header>

      {/* Tab Bar */}
      <div class="ics-search-tabs">
        <button
          type="button"
          class={`ics-search-tab ${activeTab === 'nlSearch' ? 'ics-search-tab--active' : ''}`}
          onClick={() => handleTabChange('nlSearch')}
        >
          <Search size={16} />
          <span>{t('search.tab.nlSearch')}</span>
        </button>
        <button
          type="button"
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
            isLoading={isTableBrowsing}
            isTablesLoading={isSearchableTablesLoading}
            result={tableBrowseResult}
          />
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// NL Search Tab
// ─────────────────────────────────────────────────────────────────────────────

interface NLSearchTabProps {
  searchableTables: any[];
  isLoading: boolean;
  isTablesLoading: boolean;
  result: any;
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
  searchableTables: any[];
  isLoading: boolean;
  isTablesLoading: boolean;
  result: any;
}

function TableBrowserTab({ searchableTables, isLoading, isTablesLoading, result }: TableBrowserTabProps) {
  const dispatch = useAppDispatch();
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
  const [tableType, setTableType] = useState<'header' | 'line'>('header');
  const [page, setPage] = useState(1);
  const pageSize = 50;

  // Load data when category or table type changes
  useEffect(() => {
    if (selectedCategoryId !== null) {
      dispatch(fetchTableData({ categoryId: selectedCategoryId, page, pageSize, tableType }));
    }
  }, [dispatch, selectedCategoryId, tableType, page]);

  const handleCategoryChange = (e: Event) => {
    const value = (e.target as HTMLSelectElement).value;
    setSelectedCategoryId(value ? Number(value) : null);
    setPage(1);
  };

  const handleTableTypeChange = (type: 'header' | 'line') => {
    setTableType(type);
    setPage(1);
  };

  const noTables = !isTablesLoading && searchableTables.length === 0;
  const totalPages = result?.total_pages || 1;

  // Check if selected category has line table
  const selectedCategory = searchableTables.find(t => t.category_id === selectedCategoryId);
  const hasLineTable = selectedCategory?.line_table_name;

  return (
    <div class="ics-table-browser">
      {/* Category selector */}
      <div class="ics-form-group">
        <label class="ics-form-label">{t('search.browser.selectCategory')}</label>
        <select
          class="ics-form-input"
          value={selectedCategoryId ?? ''}
          onChange={handleCategoryChange}
          disabled={noTables}
        >
          <option value="">{t('search.browser.selectCategory')}</option>
          {searchableTables.map(table => (
            <option key={table.category_id} value={table.category_id}>
              {table.category_name}
            </option>
          ))}
        </select>
      </div>

      {/* Table type toggle */}
      {selectedCategoryId !== null && (
        <div class="ics-form-group">
          <label class="ics-form-label">{t('search.browser.tableType')}</label>
          <div class="ics-table-type-toggle">
            <button
              type="button"
              class={`ics-toggle-btn ${tableType === 'header' ? 'ics-toggle-btn--active' : ''}`}
              onClick={() => handleTableTypeChange('header')}
            >
              {t('search.browser.header')}
            </button>
            <button
              type="button"
              class={`ics-toggle-btn ${tableType === 'line' ? 'ics-toggle-btn--active' : ''}`}
              onClick={() => handleTableTypeChange('line')}
              disabled={!hasLineTable}
            >
              {t('search.browser.line')}
            </button>
          </div>
        </div>
      )}

      {noTables && (
        <p class="oj-typography-body-sm oj-sm-margin-4x-top">{t('search.error.noTables')}</p>
      )}

      {/* Loading indicator */}
      {isLoading && (
        <div class="ics-loading oj-sm-margin-4x-top">
          <Loader2 size={24} class="ics-spinner" />
          <span>{t('common.loading')}</span>
        </div>
      )}

      {/* Results */}
      {!isLoading && result && selectedCategoryId !== null && (
        <div class="ics-browser-results oj-sm-margin-4x-top">
          <div class="ics-results-header">
            <span class="oj-typography-body-sm">
              {t('search.browser.totalRows').replace('{count}', String(result.total || 0))}
              {result.table_name && ` - ${result.table_name}`}
            </span>
          </div>

          {result.rows && result.rows.length > 0 ? (
            <>
              <ResultsTable columns={result.columns} rows={result.rows} />

              {/* Pagination */}
              {totalPages > 1 && (
                <div class="ics-pagination oj-sm-margin-4x-top">
                  <button
                    type="button"
                    class="ics-pagination-btn"
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page <= 1}
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span class="ics-pagination-info">
                    {page} / {totalPages}
                  </span>
                  <button
                    type="button"
                    class="ics-pagination-btn"
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              )}
            </>
          ) : (
            <p class="oj-typography-body-sm oj-sm-margin-4x-top">{t('search.browser.noData')}</p>
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Results Table (shared)
// ─────────────────────────────────────────────────────────────────────────────

interface ResultsTableProps {
  columns: string[];
  rows: Record<string, any>[];
}

function ResultsTable({ columns, rows }: ResultsTableProps) {
  if (!columns || columns.length === 0) return null;

  return (
    <div class="ics-table-wrapper">
      <table class="ics-table">
        <thead>
          <tr>
            {columns.map(col => (
              <th key={col}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx}>
              {columns.map(col => (
                <td key={col}>{formatCellValue(row[col])}</td>
              ))}
            </tr>
          ))}
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
