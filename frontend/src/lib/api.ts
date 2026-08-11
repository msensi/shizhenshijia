import type {
  AdminAnalyticsData,
  AnalysisCreatedData,
  AnalysisDetailData,
  ApiEnvelope,
} from '../types/api';
import { ApiError, NetworkError } from './errors';
import { compressForUpload, setLastImage } from './uploadImage';
import { getMockScenario, mockAdminAnalytics, mockCreateAnalysis, mockGetAnalysis } from '../mocks/data';

/** 上传白名单（AC-01：JPG/JPEG/PNG/HEIF，≤10MB） */
export const ACCEPT_ATTR = '.jpg,.jpeg,.png,.heic,.heif,image/jpeg,image/png,image/heic,image/heif';
const MAX_SIZE = 10 * 1024 * 1024;

/** 返回 null 表示通过；否则为老人友好提示 */
export function validateUploadFile(file: File): string | null {
  const okType =
    /\.(jpe?g|png|heic|heif)$/i.test(file.name) ||
    ['image/jpeg', 'image/png', 'image/heic', 'image/heif'].includes(file.type);
  if (!okType) return '这种图片格式查不了，请上传 JPG、PNG 或 HEIF 格式的图片';
  if (file.size > MAX_SIZE) return '这张图片太大了，请选择不超过 10MB 的图片';
  return null;
}

async function parseEnvelope<T>(res: Response): Promise<ApiEnvelope<T>> {
  let body: { code?: number; data?: T; message?: string };
  try {
    body = await res.json();
  } catch {
    throw new ApiError(5000, '响应解析失败');
  }
  const code = typeof body.code === 'number' ? body.code : 5000;
  if (!res.ok || code !== 0) {
    throw new ApiError(code, body.message ?? '请求失败');
  }
  return body as ApiEnvelope<T>;
}

async function safeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch {
    throw new NetworkError();
  }
}

export async function createAnalysis(file: File): Promise<ApiEnvelope<AnalysisCreatedData>> {
  const scenario = getMockScenario();
  if (scenario) return mockCreateAnalysis(scenario);

  // 上传前压缩（长边 1280 / JPEG 0.85），并暂存缩略图供处理中/结果页展示
  const upload = await compressForUpload(file);
  setLastImage(upload);
  const form = new FormData();
  form.append('file', upload);
  const res = await safeFetch('/api/v1/analyses', { method: 'POST', body: form });
  return parseEnvelope<AnalysisCreatedData>(res);
}

export async function getAnalysis(id: string): Promise<ApiEnvelope<AnalysisDetailData>> {
  const scenario = getMockScenario();
  if (scenario) return mockGetAnalysis(id);

  const res = await safeFetch(`/api/v1/analyses/${encodeURIComponent(id)}`);
  return parseEnvelope<AnalysisDetailData>(res);
}

export async function getAdminAnalytics(
  token: string,
  page = 1,
): Promise<ApiEnvelope<AdminAnalyticsData>> {
  const scenario = getMockScenario();
  if (scenario) return mockAdminAnalytics();

  const res = await safeFetch(`/api/v1/admin/analytics?page=${page}&limit=20`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseEnvelope<AdminAnalyticsData>(res);
}
