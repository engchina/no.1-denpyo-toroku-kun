/**
 * 共通ページネーション（ページ移動 UI）
 * ページングが必要な画面で再利用可能
 */
import { h } from 'preact';
import { Button } from '@oracle/oraclejet-preact/UNSAFE_Button';
import { t } from '../i18n';

export interface PaginationProps {
  currentPage: number;
  totalPages: number;
  totalItems: number;
  goToPageInput: string;
  onPageChange: (page: number) => void;
  onGoToPageInputChange: (value: string) => void;
  onGoToPage: () => void;
  isFirstPage: boolean;
  isLastPage: boolean;
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
  goToPageInput,
  onPageChange,
  onGoToPageInputChange,
  onGoToPage,
  isFirstPage,
  isLastPage,
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

  const summaryText = t('common.paginationSummary', {
    current: currentPage,
    total: totalPages,
    totalItems
  });

  return (
    <div
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
        {summaryPlacement === 'controls' && (
          <span class="oj-typography-body-sm oj-text-color-secondary ics-pagination__summary ics-pagination__summary--controls">
            {summaryText}
          </span>
        )}
        <Button
          label={t('common.previous')}
          variant="outlined"
          size="sm"
          onAction={() => onPageChange(currentPage - 1)}
          isDisabled={isFirstPage}
        />
        <div class="oj-flex oj-sm-align-items-center ics-pagination__goto">
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
          <Button
            label={t('common.go')}
            variant="outlined"
            size="sm"
            onAction={onGoToPage}
            isDisabled={isGoToDisabled}
          />
        </div>
        <Button
          label={t('common.next')}
          variant="outlined"
          size="sm"
          onAction={() => onPageChange(currentPage + 1)}
          isDisabled={isLastPage}
        />
      </div>
    </div>
  );
}

export default Pagination;
