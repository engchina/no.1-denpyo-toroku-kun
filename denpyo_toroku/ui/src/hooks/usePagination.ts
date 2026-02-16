/**
 * Common pagination hook for managing paginated data
 * Can be used across all views that need pagination functionality
 */
import { useState, useCallback, useMemo } from 'preact/hooks';

export interface PaginationOptions {
  pageSize?: number;
  initialPage?: number;
}

export interface PaginationState {
  currentPage: number;
  totalItems: number;
  totalPages: number;
  pageSize: number;
  goToPageInput: string;
}

export interface UsePaginationResult<T> {
  // Current page data
  paginatedItems: T[];
  // Pagination state
  currentPage: number;
  totalPages: number;
  totalItems: number;
  pageSize: number;
  goToPageInput: string;
  // Navigation functions
  goToPage: (page: number) => void;
  goToNextPage: () => void;
  goToPrevPage: () => void;
  setGoToPageInput: (value: string) => void;
  handleGoToPage: () => void;
  // Calculated values
  isFirstPage: boolean;
  isLastPage: boolean;
  showPagination: boolean;
  // Display info
  startIndex: number;
  endIndex: number;
  // Reset function
  reset: () => void;
}

/**
 * Client-side pagination hook
 * Use this when you have all the data in memory and need to paginate it on the client
 * 
 * @param items - Full array of items to paginate
 * @param options - Pagination options (pageSize, initialPage)
 * @returns Pagination state and controls
 */
export function usePagination<T>(
  items: T[],
  options: PaginationOptions = {}
): UsePaginationResult<T> {
  const { pageSize = 20, initialPage = 1 } = options;

  const [currentPage, setCurrentPage] = useState(initialPage);
  const [goToPageInput, setGoToPageInput] = useState('');

  const totalItems = items.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

  // Ensure current page is valid
  const validCurrentPage = useMemo(() => {
    if (currentPage < 1) return 1;
    if (currentPage > totalPages) return totalPages;
    return currentPage;
  }, [currentPage, totalPages]);

  // Calculate paginated items
  const paginatedItems = useMemo(() => {
    const startIdx = (validCurrentPage - 1) * pageSize;
    const endIdx = startIdx + pageSize;
    return items.slice(startIdx, endIdx);
  }, [items, validCurrentPage, pageSize]);

  // Navigation functions
  const goToPage = useCallback((page: number) => {
    if (page >= 1 && page <= totalPages) {
      setCurrentPage(page);
    }
  }, [totalPages]);

  const goToNextPage = useCallback(() => {
    if (validCurrentPage < totalPages) {
      setCurrentPage(validCurrentPage + 1);
    }
  }, [validCurrentPage, totalPages]);

  const goToPrevPage = useCallback(() => {
    if (validCurrentPage > 1) {
      setCurrentPage(validCurrentPage - 1);
    }
  }, [validCurrentPage]);

  const handleGoToPage = useCallback(() => {
    const page = parseInt(goToPageInput, 10);
    if (!isNaN(page) && page >= 1 && page <= totalPages) {
      setCurrentPage(page);
      setGoToPageInput('');
    }
  }, [goToPageInput, totalPages]);

  const reset = useCallback(() => {
    setCurrentPage(1);
    setGoToPageInput('');
  }, []);

  // Calculate display indices
  const startIndex = (validCurrentPage - 1) * pageSize + 1;
  const endIndex = Math.min(validCurrentPage * pageSize, totalItems);

  return {
    paginatedItems,
    currentPage: validCurrentPage,
    totalPages,
    totalItems,
    pageSize,
    goToPageInput,
    goToPage,
    goToNextPage,
    goToPrevPage,
    setGoToPageInput,
    handleGoToPage,
    isFirstPage: validCurrentPage <= 1,
    isLastPage: validCurrentPage >= totalPages,
    showPagination: totalPages > 1,
    startIndex,
    endIndex,
    reset
  };
}

export default usePagination;
