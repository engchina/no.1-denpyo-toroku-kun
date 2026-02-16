/**
 * Custom fetch hook for API calls with loading/error state
 */
import { useState, useCallback } from 'preact/hooks';

interface FetchState<T> {
  data: T | null;
  isLoading: boolean;
  error: string | null;
}

export function useFetch<T>() {
  const [state, setState] = useState<FetchState<T>>({
    data: null,
    isLoading: false,
    error: null
  });

  const execute = useCallback(async (fetchFn: () => Promise<T>) => {
    setState({ data: null, isLoading: true, error: null });
    try {
      const data = await fetchFn();
      setState({ data, isLoading: false, error: null });
      return data;
    } catch (err: any) {
      const message = err.message || 'An error occurred';
      setState({ data: null, isLoading: false, error: message });
      throw err;
    }
  }, []);

  const reset = useCallback(() => {
    setState({ data: null, isLoading: false, error: null });
  }, []);

  return { ...state, execute, reset };
}
