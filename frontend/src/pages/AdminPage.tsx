import { useState } from 'react';
import { ChevronDown, KeyRound, RefreshCw } from 'lucide-react';
import { getAdminAnalytics } from '../lib/api';
import type { AdminAnalyticsItem } from '../types/api';

const RESULT_LABELS: Record<string, string> = {
  supported: '可信',
  refuted: '不符',
  disputed: '分歧',
  insufficient_evidence: '证据不足',
  visual_suspect: '画面存疑',
  out_of_scope: '范围外',
  unreadable: '看不清',
};

const DOMAIN_LABELS: Record<string, string> = {
  health: '健康',
  policy: '政策',
  scam: '诈骗',
  news: '热点',
  non_factual: '非事实',
  out_of_scope: '范围外',
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function AdminPage() {
  const [token, setToken] = useState(() => sessionStorage.getItem('admin_token') ?? '');
  const [items, setItems] = useState<AdminAnalyticsItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    if (!token.trim()) {
      setError('请输入管理口令');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await getAdminAnalytics(token.trim());
      setItems(res.data.items);
      sessionStorage.setItem('admin_token', token.trim());
    } catch (err) {
      setItems(null);
      setError(err instanceof Error && 'code' in err && (err as { code: number }).code === 401
        ? '口令不正确，请检查后重试'
        : '获取数据失败，请稍后再试');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-shell">
      <div className="page-inner">
        <h1 className="mb-6 mt-0 text-xl font-bold leading-title">使用记录</h1>

        <div className="flex gap-3">
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="输入管理口令"
            aria-label="管理口令"
            className="min-h-touch-min flex-1 rounded-md border border-border bg-surface px-4 text-base text-fg placeholder:text-meta focus-visible:outline-none focus-visible:shadow-[var(--focus-ring)]"
          />
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="flex min-h-touch-min shrink-0 items-center gap-2 rounded-md bg-accent px-5 text-base font-bold text-accent-on transition-colors duration-fast ease-standard hover:bg-accent-hover focus-visible:outline-none focus-visible:shadow-[var(--focus-ring)] disabled:opacity-60"
          >
            {loading ? (
              <RefreshCw size={20} strokeWidth={2} className="mb-spin" aria-hidden />
            ) : (
              <KeyRound size={20} strokeWidth={2} aria-hidden />
            )}
            查询
          </button>
        </div>

        {error && (
          <p role="alert" className="mb-0 mt-4 text-sm text-status-danger">
            {error}
          </p>
        )}

        {items && items.length === 0 && (
          <p className="mt-8 text-center text-sm text-muted">暂无使用记录</p>
        )}

        {items && items.length > 0 && (
          <div className="mt-6 flex flex-col gap-3">
            {items.map((item) => (
              <details key={item.analysis_id} className="group rounded-md border border-border bg-surface">
                <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3.5">
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm text-muted">
                      {formatTime(item.created_at)} · {(item.domain && DOMAIN_LABELS[item.domain]) ?? '未分类'}
                    </span>
                    <span className="mt-1 block truncate text-base font-medium text-fg">
                      {item.primary_claim || item.title || '未能提取核验内容'}
                    </span>
                  </span>
                  <span className="shrink-0 text-sm font-medium text-fg-2">
                    {(item.result_status && RESULT_LABELS[item.result_status]) ?? '失败'}
                  </span>
                  <ChevronDown size={18} className="shrink-0 text-muted transition-transform group-open:rotate-180" aria-hidden />
                </summary>
                <div className="border-t border-border-soft px-4 py-4 text-sm leading-body text-fg-2">
                  {item.summary && <p className="m-0"><strong>回复：</strong>{item.summary}</p>}
                  {item.advice && <p className="mb-0 mt-2"><strong>建议：</strong>{item.advice}</p>}
                  {item.risk_alerts?.length > 0 && (
                    <p className="mb-0 mt-2 text-status-danger"><strong>额外风险：</strong>{item.risk_alerts.join('；')}</p>
                  )}
                  <p className="mb-0 mt-2 text-muted">
                    依据 {item.source_count} 条 · 耗时 {(item.latency_ms / 1000).toFixed(1)} 秒 · 错误码 {item.error_code ?? '无'}
                  </p>
                </div>
              </details>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
