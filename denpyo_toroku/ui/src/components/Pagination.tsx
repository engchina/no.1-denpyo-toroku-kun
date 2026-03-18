/**
 * 共通ページネーション（ページ移動 UI）
 * ページングが必要な画面で再利用可能
 */
import { ChevronLeft, ChevronRight, ArrowRight } from 'lucide-react';
import { t } from '../i18n';

export interface PaginationProps {
  currentPage: number;
  totalPages: number;
  totalItems: number;
  pageSize?: number;
  pageSizeOptions?: number[];
  onPageSizeChange?: (size: number) => void;
  goToPageInput: string;
  onPageChange: (page: number) => void;
  onGoToPageInputChange: (value: string) => void;
  onGoToPage: () => void;
  isFirstPage: boolean;
  isLastPage: boolean;
  rangeStart?: number;
  rangeEnd?: number;
  showGoToPage?: boolean;
  /** Position: 'top' adds bottom border, 'bottom' adds top border */
  position?: 'top' | 'bottom';
  /** Whether to show the component (typically based on totalPages > 1) */
  show?: boolean;
  /** Where to render summary text */
  summaryPlacement?: 'left' | 'controls';
}

/**
 * 再利用可能なページネーション
 *
 * 使用例:
 * ```tsx
 * const pagination = usePagination(items, { pageSize: 20 });
 * const selection = useSelection({ getItemId: (item) => item.id });
 *
 * <Pagination
 *   currentPage={pagination.currentPage}
 *   totalPages={pagination.totalPages}
 *   totalItems={pagination.totalItems}
 *   goToPageInput={pagination.goToPageInput}
 *   onPageChange={pagination.goToPage}
 *   onGoToPageInputChange={pagination.setGoToPageInput}
 *   onGoToPage={pagination.handleGoToPage}
 *   isFirstPage={pagination.isFirstPage}
 *   isLastPage={pagination.isLastPage}
 *   position="bottom"
 *   show={pagination.showPagination}
 * />
 * ```
 */
export function Pagination({
  currentPage,
  totalPages,
  totalItems,
  pageSize,
  pageSizeOptions = [20, 50, 100],
  onPageSizeChange,
  goToPageInput,
  onPageChange,
  onGoToPageInputChange,
  onGoToPage,
  isFirstPage,
  isLastPage,
  rangeStart,
  rangeEnd,
  showGoToPage = true,
  position = 'top',
  show = true,
  summaryPlacement = 'left',
}: PaginationProps) {
  if (!show) {
    return null;
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter') {
      onGoToPage();
    }
  };

  const targetPage = goToPageInput.trim() ? parseInt(goToPageInput, 10) : currentPage;
  const isGoToDisabled = Number.isNaN(targetPage)
    || targetPage < 1
    || targetPage > totalPages;

  const summaryText = typeof rangeStart === 'number' && typeof rangeEnd === 'number'
    ? t('common.paginationRange', {
      start: rangeStart,
      end: rangeEnd,
      totalItems
    })
    : t('common.paginationSummary', {
      current: currentPage,
      total: totalPages,
      totalItems
    });

  return (
    <nav
      aria-label={t('common.paginationNavAria')}
      class={`oj-flex oj-sm-justify-content-space-between oj-sm-align-items-center ics-pagination ics-pagination--${position}`}
    >
      {/* 左側: サマリー */}
      <div class="oj-flex oj-sm-align-items-center ics-pagination__left">
        {summaryPlacement === 'left' && (
          <span class="oj-typography-body-sm oj-text-color-secondary ics-pagination__summary">
            {summaryText}
          </span>
        )}
      </div>

      {/* 右側: ページ移動コントロール */}
      <div class="oj-flex oj-sm-align-items-center ics-pagination__controls">
        {typeof pageSize === 'number' && onPageSizeChange && (
          <label class="ics-pagination__pageSize">
            <span class="oj-typography-body-sm oj-text-color-secondary ics-pagination__pageSizeLabel">
              {t('common.rowsPerPage')}
            </span>
            <select
              class="ics-select"
              value={String(pageSize)}
              aria-label={t('common.pageSizeAria')}
              onChange={(e: any) => onPageSizeChange(parseInt(e.target.value, 10))}
            >
              {pageSizeOptions.map(size => (
                <option key={size} value={String(size)}>{size}</option>
              ))}
            </select>
          </label>
        )}
        {summaryPlacement === 'controls' && (
          <span class="oj-typography-body-sm oj-text-color-secondary ics-pagination__summary ics-pagination__summary--controls">
            {summaryText}
          </span>
        )}
        {showGoToPage && (
          <div class="oj-flex oj-sm-align-items-center ics-pagination__goto oj-sm-margin-4x-end">
            <span class="oj-typography-body-sm oj-text-color-secondary ics-pagination__gotoLabel">
              {t('common.page')}
            </span>
            <input
              type="number"
              class="ics-input ics-pagination__input"
              min="1"
              max={String(totalPages)}
              value={goToPageInput || currentPage.toString()}
              aria-label={t('common.pageInputAria', { current: currentPage })}
              onInput={(e: any) => onGoToPageInputChange(e.target.value)}
              onKeyDown={handleKeyDown as any}
            />
            <button
              type="button"
              class="ics-btn"
              onClick={onGoToPage}
              disabled={isGoToDisabled}
            >
              <ArrowRight size={14} />
              <span>{t('common.go')}</span>
            </button>
          </div>
        )}
        <div class="ics-btn-group">
          <button
            class="ics-btn"
            onClick={() => onPageChange(currentPage - 1)}
            disabled={isFirstPage}
            type="button"
          >
            <ChevronLeft size={16} />
            <span>{t('common.previous')}</span>
          </button>
          <button
            class="ics-btn"
            onClick={() => onPageChange(currentPage + 1)}
            disabled={isLastPage}
            type="button"
          >
            <span>{t('common.next')}</span>
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </nav>
  );
}

export default Pagination;
