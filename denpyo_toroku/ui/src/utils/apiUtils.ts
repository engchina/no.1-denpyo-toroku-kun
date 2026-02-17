/**
 * API utility functions
 */

const BASE_URL = '/studio';

/**
 * DB接続テスト用のタイムアウト設定（秒）
 * バックエンドの _DB_TEST_TIMEOUT_SECONDS と合わせる
 */
const DB_TEST_TIMEOUT_MS = 20000; // 20秒（バックエンドの15秒 + 余裕）

export const apiGet = async <T>(endpoint: string): Promise<T> => {
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    method: 'GET',
    credentials: 'same-origin',
    headers: { 'Accept': 'application/json' }
  });
  let body: any;
  try {
    body = await response.json();
  } catch {
    throw new Error(`サーバーが JSON ではない応答を返しました（HTTP ${response.status}）`);
  }
  if (!response.ok) {
    const errMsg = (body.errorMessages && body.errorMessages[0]) || `HTTP ${response.status}`;
    throw new Error(errMsg);
  }
  return body.data !== undefined ? body.data : body;
};

export const apiPost = async <T>(endpoint: string, data?: any): Promise<T> => {
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Accept': 'application/json',
      'Content-Type': 'application/json'
    },
    body: data ? JSON.stringify(data) : undefined
  });
  let body: any;
  try {
    body = await response.json();
  } catch {
    throw new Error(`サーバーが JSON ではない応答を返しました（HTTP ${response.status}）`);
  }
  if (!response.ok) {
    const errMsg = (body.errorMessages && body.errorMessages[0]) || `HTTP ${response.status}`;
    throw new Error(errMsg);
  }
  return body.data !== undefined ? body.data : body;
};

/**
 * タイムアウト付きPOSTリクエスト
 * DB接続テストなど時間がかかる可能性のあるリクエスト用
 * 
 * @param endpoint APIエンドポイント
 * @param data リクエストデータ
 * @param timeoutMs タイムアウト時間（ミリ秒）
 * @returns レスポンスデータ
 * @throws Error タイムアウトまたはネットワークエラー
 */
export const apiPostWithTimeout = async <T>(
  endpoint: string,
  data?: any,
  timeoutMs: number = DB_TEST_TIMEOUT_MS
): Promise<T> => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  
  try {
    const response = await fetch(`${BASE_URL}${endpoint}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
      },
      body: data ? JSON.stringify(data) : undefined,
      signal: controller.signal
    });
    
    let body: any;
    try {
      body = await response.json();
    } catch {
      throw new Error(`サーバーが JSON ではない応答を返しました（HTTP ${response.status}）`);
    }
    if (!response.ok) {
      const errMsg = (body.errorMessages && body.errorMessages[0]) || `HTTP ${response.status}`;
      throw new Error(errMsg);
    }
    return body.data !== undefined ? body.data : body;
  } catch (error: any) {
    if (error.name === 'AbortError') {
      throw new Error(`リクエストがタイムアウトしました（${Math.round(timeoutMs / 1000)}秒）。データベースが起動しているか確認してください。`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
};

export const formatTime = (seconds: number): string => {
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hours}時間 ${mins}分`;
};

export const formatPercentage = (value: number, decimals: number = 2): string => {
  return `${(value * 100).toFixed(decimals)}%`;
};

export const formatDuration = (seconds: number): string => {
  return `${seconds.toFixed(3)}秒`;
};
