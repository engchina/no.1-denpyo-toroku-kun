/**
 * 共通選択フック - ページネーションと連携可能な選択状態管理
 * すべて選択 / すべて解除を統一的に提供する
 */
import { useState, useCallback, useMemo } from 'preact/hooks';

export interface UseSelectionOptions<T> {
  /** 各アイテムの一意なIDを返す関数 */
  getItemId: (item: T) => string;
  /** アイテムが選択可能かどうかを判定する関数（省略時は全て選択可能） */
  isSelectable?: (item: T) => boolean;
  /** 選択上限数（省略時は無制限） */
  maxSelection?: number;
}

export interface UseSelectionResult<T> {
  /** 選択中のIDセット */
  selectedIds: Set<string>;
  /** 選択件数 */
  selectedCount: number;
  /** 指定IDが選択中か判定 */
  isSelected: (id: string) => boolean;
  /** 単一アイテムの選択トグル */
  toggle: (id: string) => void;
  /** 指定ID群を選択 */
  selectIds: (ids: Iterable<string>) => void;
  /** 指定ID群の選択を解除 */
  deselectIds: (ids: Iterable<string>) => void;
  /** 指定アイテム群をすべて選択（ページ単位で使用） */
  selectAll: (pageItems: T[]) => void;
  /** すべて解除 */
  deselectAll: () => void;
  /** 指定アイテム群がすべて選択済みか判定 */
  isAllSelected: (pageItems: T[]) => boolean;
  /** 選択状態をリセット */
  reset: () => void;
}

/**
 * ページネーション対応の選択状態管理フック
 *
 * 使用例:
 * ```tsx
 * const selection = useSelection<DenpyoFile>({
 *   getItemId: (file) => String(file.file_id),
 *   isSelectable: (file) => file.status !== 'REGISTERED',
 *   maxSelection: 5,
 * });
 *
 * // Pagination コンポーネントと連携
 * <Pagination
 *   ...paginationProps
 *   selectedCount={selection.selectedCount}
 *   onSelectAll={() => selection.selectAll(currentPageItems)}
 *   onDeselectAll={selection.deselectAll}
 * />
 * ```
 */
export function useSelection<T>(
  options: UseSelectionOptions<T>
): UseSelectionResult<T> {
  const { getItemId, isSelectable, maxSelection } = options;
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const selectedCount = selectedIds.size;

  const isSelected = useCallback(
    (id: string) => selectedIds.has(id),
    [selectedIds]
  );

  const toggle = useCallback(
    (id: string) => {
      setSelectedIds(prev => {
        const next = new Set(prev);
        if (next.has(id)) {
          next.delete(id);
        } else {
          if (maxSelection !== undefined && next.size >= maxSelection) {
            return prev;
          }
          next.add(id);
        }
        return next;
      });
    },
    [maxSelection]
  );

  const selectIds = useCallback(
    (ids: Iterable<string>) => {
      setSelectedIds(prev => {
        const next = new Set(prev);
        for (const id of ids) {
          if (!id || next.has(id)) continue;
          if (maxSelection !== undefined && next.size >= maxSelection) {
            break;
          }
          next.add(id);
        }
        return next;
      });
    },
    [maxSelection]
  );

  const deselectIds = useCallback((ids: Iterable<string>) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      for (const id of ids) {
        if (!id) continue;
        next.delete(id);
      }
      return next;
    });
  }, []);

  const selectAll = useCallback(
    (pageItems: T[]) => {
      const selectableItems = isSelectable
        ? pageItems.filter(isSelectable)
        : pageItems;
      const ids = selectableItems.map(getItemId);

      if (maxSelection !== undefined) {
        const limited = ids.slice(0, maxSelection);
        setSelectedIds(new Set(limited));
      } else {
        setSelectedIds(prev => {
          const next = new Set(prev);
          ids.forEach(id => next.add(id));
          return next;
        });
      }
    },
    [getItemId, isSelectable, maxSelection]
  );

  const deselectAll = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const isAllSelected = useCallback(
    (pageItems: T[]) => {
      const selectableItems = isSelectable
        ? pageItems.filter(isSelectable)
        : pageItems;
      if (selectableItems.length === 0) return false;

      const ids = selectableItems.map(getItemId);
      if (maxSelection !== undefined) {
        const limited = ids.slice(0, maxSelection);
        return limited.every(id => selectedIds.has(id));
      }
      return ids.every(id => selectedIds.has(id));
    },
    [getItemId, isSelectable, maxSelection, selectedIds]
  );

  const reset = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  return {
    selectedIds,
    selectedCount,
    isSelected,
    toggle,
    selectIds,
    deselectIds,
    selectAll,
    deselectAll,
    isAllSelected,
    reset,
  };
}

export default useSelection;
