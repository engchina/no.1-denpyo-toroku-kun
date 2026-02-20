/**
 * 共通ページネーション（ページ移動 UI）+ 選択操作
 * ページングが必要な画面で再利用可能
 *
 * 選択操作（すべて選択 / すべて解除）はオプション。
 * selectedCount を渡すと選択 UI が表示される。
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

  // ── 選択操作（オプション）──────────────────────────────────────
  /** 現在の選択件数。undefined の場合、選択 UI は非表示 */
  selectedCount?: number;
  /** 「すべて選択」ハンドラ */
  onSelectAll?: () => void;
  /** 「すべて解除」ハンドラ */
  onDeselectAll?: () => void;
}

/**
 * 再利用可能なページネーション + 選択操作
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
 *   selectedCount={selection.selectedCount}
 *   onSelectAll={() => selection.selectAll(pagination.paginatedItems)}
 *   onDeselectAll={selection.deselectAll}
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
  selectedCount,
  onSelectAll,
  onDeselectAll,
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

  const showSelection = selectedCount !== undefined && onSelectAll && onDeselectAll;

  return (
    <div
      class={`oj-flex oj-sm-justify-content-space-between oj-sm-align-items-center ics-pagination ics-pagination--${position}`}
    >
      {/* 左側: 選択操作 + サマリー */}
      <div class="oj-flex oj-sm-align-items-center ics-pagination__left">
        {showSelection && (
          <div class="oj-flex oj-sm-align-items-center ics-pagination__selection">
            <Button
              label={t('common.selectAll')}
              variant="outlined"
              size="sm"
              onAction={onSelectAll}
            />
            <Button
              label={t('common.deselectAll')}
              variant="outlined"
              size="sm"
              onAction={onDeselectAll}
              isDisabled={selectedCount === 0}
            />
            {selectedCount > 0 && (
              <span class="oj-typography-body-sm ics-pagination__selectionCount">
                {t('common.selectedCount', { count: selectedCount })}
              </span>
            )}
          </div>
        )}
        <span class="oj-typography-body-sm oj-text-color-secondary ics-pagination__summary">
          {currentPage} / {totalPages} ページ（合計 {totalItems} 件）
        </span>
      </div>

      {/* 右側: ページ移動コントロール */}
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
            min="1"
            max={String(totalPages)}
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
