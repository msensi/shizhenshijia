/** API code → 对外短码映射（SPEC §9.1 锁定） */

export type ShortErrorCode =
  | 'T-408'
  | 'Q-429'
  | 'S-503'
  | 'E-500'
  | 'N-001';

/** 网络层错误专用标记（fetch reject / 断网） */
export class NetworkError extends Error {
  constructor() {
    super('network request failed');
    this.name = 'NetworkError';
  }
}

/** 业务错误：携带 API code */
export class ApiError extends Error {
  readonly code: number;
  constructor(code: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
  }
}

/**
 * 对内错误段 → 对外短码（SPEC §9.1）：
 * 3901→Q-429、5901-5903→S-503、5000→E-500、
 * 网络层捕获→N-001、轮询超时→T-408（由调用方在超时场景直接指定）
 */
export function mapApiCodeToShort(code: number): ShortErrorCode {
  if (code === 3901) return 'Q-429';
  if (code >= 5901 && code <= 5903) return 'S-503';
  if (code >= 2000 && code < 3000) return 'T-408';
  if (code >= 5000 && code < 6000) return 'E-500';
  return 'E-500';
}

export function errorToShortCode(err: unknown): ShortErrorCode {
  if (err instanceof NetworkError) return 'N-001';
  if (err instanceof ApiError) return mapApiCodeToShort(err.code);
  return 'E-500';
}
