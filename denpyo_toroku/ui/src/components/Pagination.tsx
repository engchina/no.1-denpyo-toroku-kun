/**
 * 共通ページネーション（ページ移動 UI）
 * Training 画面のデータセット用ページネーションの見た目に合わせる
 * ページングが必要な画面で再利用可能
 */
import { h } from 'preact';
import { Button } from '@oracle/oraclejet-preact/UNSAFE_Button';

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
}

/**
 * 再利用可能なページネーション
 *
 * 使用例:
 * ```tsx
 * const pagination = usePagination(items, { pageSize: 20 });
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
 *   position="top"
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
  show = true
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

  return (
    <div 
      class={`oj-flex oj-sm-justify-content-space-between oj-sm-align-items-center ics-pagination ics-pagination--${position}`}
    >
      <span class="oj-typography-body-sm oj-text-color-secondary ics-pagination__summary">
        {currentPage} / {totalPages} ページ（合計 {totalItems} 件）
      </span>
      <div class="oj-flex oj-sm-align-items-center ics-pagination__controls">
        <Button
          label="前へ"
          variant="outlined"
          size="sm"
          onAction={() => onPageChange(currentPage - 1)}
          isDisabled={isFirstPage}
        />
        <div class="oj-flex oj-sm-align-items-center ics-pagination__goto">
          <span class="oj-typography-body-sm oj-text-color-secondary ics-pagination__gotoLabel">ページ</span>
          <input
            type="number"
            class="ics-input ics-pagination__input"
            min={1}
            max={totalPages}
            value={goToPageInput || currentPage.toString()}
            aria-label={`ページ移動（現在: ${currentPage}）`}
            onInput={(e: any) => onGoToPageInputChange(e.target.value)}
            onKeyDown={handleKeyDown as any}
          />
          <Button
            label="移動"
            variant="outlined"
            size="sm"
            onAction={onGoToPage}
            isDisabled={isGoToDisabled}
          />
        </div>
        <Button
          label="次へ"
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
