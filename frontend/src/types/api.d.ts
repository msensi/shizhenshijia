/** 与 docs/api/openapi.yaml 对齐的前后端共享契约类型 */

export type AnalysisStatus = 'queued' | 'processing' | 'completed' | 'failed';

export type ProgressStage =
  | 'reading_image'
  | 'checking_scope'
  | 'finding_evidence'
  | 'summarizing'
  | null;

/** 7 种结果状态（后 6 种 + supported） */
export type ResultStatus =
  | 'supported'
  | 'refuted'
  | 'disputed'
  | 'insufficient_evidence'
  | 'out_of_scope'
  | 'unreadable'
  | 'visual_suspect';

export type Domain =
  | 'health'
  | 'policy'
  | 'scam'
  | 'news'
  | 'non_factual'
  | 'out_of_scope'
  | null;

export interface Source {
  title: string;
  publisher: string;
  url: string;
  quote: string;
  published_at?: string | null;
}

export interface AnalysisCreatedData {
  analysis_id: string;
  status: 'queued';
  expires_at: string | null;
}

export interface AnalysisDetailData {
  analysis_id: string;
  status: AnalysisStatus;
  progress_stage?: ProgressStage;
  result_status?: ResultStatus | null;
  title?: string | null;
  summary?: string | null;
  primary_claim?: string | null;
  domain?: Domain;
  reasons: string[];
  risk_alerts: string[];
  advice?: string | null;
  visual_note?: string | null;
  sources: Source[];
  error_code?: number | null;
}

export interface ApiEnvelope<T> {
  code: number;
  data: T;
  message?: string;
}

export interface ApiErrorBody {
  code: number;
  message: string;
  data?: object | null;
}

export interface AdminAnalyticsItem {
  analysis_id: string;
  created_at: string;
  domain?: string | null;
  primary_claim?: string | null;
  result_status?: string | null;
  title?: string | null;
  summary?: string | null;
  advice?: string | null;
  reasons: string[];
  risk_alerts: string[];
  sources: Source[];
  source_count: number;
  latency_ms: number;
  error_code?: number | null;
}

export interface AdminAnalyticsData {
  items: AdminAnalyticsItem[];
  total: number;
  page: number;
  limit: number;
  hasMore: boolean;
}
