import { APP_ROUTES } from '../constants/routes';

export type QueryPaginationScope = 'fl' | 'cs' | 'cm' | 'cmh' | 'cml' | 'sbnr' | 'sbtl' | 'sbdp';

type ScopeKey = 'p' | 'ps';
const PAGINATION_SCOPE_KEYS: ScopeKey[] = ['p', 'ps'];

const ALL_SCOPES: QueryPaginationScope[] = ['fl', 'cs', 'cm', 'cmh', 'cml', 'sbnr', 'sbtl', 'sbdp'];

const VIEW_SCOPES: Record<string, QueryPaginationScope[]> = {
  fileList: ['fl'],
  categorySamples: ['cs'],
  categoryManagement: ['cm', 'cmh', 'cml'],
  search: ['sbnr', 'sbtl', 'sbdp'],
  [APP_ROUTES.fileList]: ['fl'],
  [APP_ROUTES.categorySamples]: ['cs'],
  [APP_ROUTES.categoryManagement]: ['cm', 'cmh', 'cml'],
  [APP_ROUTES.search]: ['sbnr', 'sbtl', 'sbdp'],
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
  const orderedParams = new URLSearchParams();
  const scopedParamNames = new Set<string>();

  ALL_SCOPES.forEach(scope => {
    PAGINATION_SCOPE_KEYS.forEach(key => {
      scopedParamNames.add(scopedKey(scope, key));
    });
  });

  Array.from(params.entries()).forEach(([key, value]) => {
    if (!scopedParamNames.has(key)) {
      orderedParams.append(key, value);
    }
  });

  ALL_SCOPES.forEach(scope => {
    PAGINATION_SCOPE_KEYS.forEach(key => {
      const scopedParam = scopedKey(scope, key);
      const value = params.get(scopedParam);
      if (value !== null) {
        orderedParams.append(scopedParam, value);
      }
    });
  });

  url.search = orderedParams.toString();
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
}

export function clearLegacyFileListParams(params: URLSearchParams) {
  LEGACY_FILE_LIST_KEYS.forEach(key => params.delete(key));
}

function normalizeRouteKey(key: string): string {
  if (!key) return key;
  if (!key.startsWith('/')) return key;
  if (key.length > 1 && key.endsWith('/')) {
    return key.slice(0, -1);
  }
  return key;
}

function resolveScopes(routeKey: string): QueryPaginationScope[] {
  const normalized = normalizeRouteKey(routeKey);

  if (VIEW_SCOPES[normalized]) {
    return VIEW_SCOPES[normalized];
  }

  if (normalized.startsWith(APP_ROUTES.fileList)) {
    return ['fl'];
  }
  if (normalized.startsWith(APP_ROUTES.categorySamples)) {
    return ['cs'];
  }
  if (normalized.startsWith(APP_ROUTES.categoryManagement)) {
    return ['cm', 'cmh', 'cml'];
  }
  if (normalized.startsWith(APP_ROUTES.search)) {
    return ['sbnr', 'sbtl', 'sbdp'];
  }

  return [];
}

export function clearPaginationParamsOutsideView(routeKey: string) {
  if (typeof window === 'undefined') return;
  const activeScopes = new Set(resolveScopes(routeKey));
  const params = getCurrentSearchParams();
  let changed = false;

  ALL_SCOPES.forEach(scope => {
    if (activeScopes.has(scope)) return;
    PAGINATION_SCOPE_KEYS.forEach(key => {
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
