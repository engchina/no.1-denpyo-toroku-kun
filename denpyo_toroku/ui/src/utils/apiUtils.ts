/**
 * API utility functions
 */

const BASE_URL = '/studio';

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
