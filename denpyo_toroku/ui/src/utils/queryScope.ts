export type QueryPaginationScope = 'fl' | 'cs' | 'cm' | 'sbtl' | 'sbdp';

type ScopeKey = 'p' | 'ps' | 'status';

const ALL_SCOPES: QueryPaginationScope[] = ['fl', 'cs', 'cm', 'sbtl', 'sbdp'];

const VIEW_SCOPES: Record<string, QueryPaginationScope[]> = {
  fileList: ['fl'],
  categorySamples: ['cs'],
  categoryManagement: ['cm'],
  search: ['sbtl', 'sbdp'],
};

const LEGACY_FILE_LIST_KEYS = ['file_page', 'file_page_size', 'file_status'];

function scopedKey(scope: QueryPaginationScope, key: ScopeKey): string {
  return `${scope}_${key}`;
}

export function getCurrentSearchParams(): URLSearchParams {
  if (typeof window === 'undefined') return new URLSearchParams();
  return new URLSearchParams(window.location.search);
}

export function readScopedString(
  params: URLSearchParams,
  scope: QueryPaginationScope,
  key: ScopeKey
): string | null {
  return params.get(scopedKey(scope, key));
}

export function readScopedNumber(
  params: URLSearchParams,
  scope: QueryPaginationScope,
  key: ScopeKey,
  fallback: number
): number {
  const raw = readScopedString(params, scope, key);
  if (!raw) return fallback;
  const n = parseInt(raw, 10);
  return Number.isNaN(n) ? fallback : n;
}

export function setScopedValue(
  params: URLSearchParams,
  scope: QueryPaginationScope,
  key: ScopeKey,
  value: string | number | null | undefined
) {
  const k = scopedKey(scope, key);
  if (value === null || value === undefined || value === '') {
    params.delete(k);
    return;
  }
  params.set(k, String(value));
}

export function replaceSearchParams(params: URLSearchParams) {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  url.search = params.toString();
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
}

export function clearLegacyFileListParams(params: URLSearchParams) {
  LEGACY_FILE_LIST_KEYS.forEach(key => params.delete(key));
}

export function clearPaginationParamsOutsideView(currentView: string) {
  if (typeof window === 'undefined') return;
  const activeScopes = new Set(VIEW_SCOPES[currentView] || []);
  const params = getCurrentSearchParams();
  let changed = false;

  ALL_SCOPES.forEach(scope => {
    if (activeScopes.has(scope)) return;
    (['p', 'ps', 'status'] as ScopeKey[]).forEach(key => {
      const k = scopedKey(scope, key);
      if (params.has(k)) {
        params.delete(k);
        changed = true;
      }
    });
  });

  LEGACY_FILE_LIST_KEYS.forEach(key => {
    if (params.has(key)) {
      params.delete(key);
      changed = true;
    }
  });

  if (changed) {
    replaceSearchParams(params);
  }
}
