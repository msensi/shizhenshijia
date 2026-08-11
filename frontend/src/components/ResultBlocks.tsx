import { Check, ExternalLink, Info, TriangleAlert } from 'lucide-react';
import type { Source } from '../types/api';
import { STATUS_THEMES } from '../lib/resultStatus';
import type { ResultStatus } from '../types/api';

/** 结论色块：状态浅底大色块 + 32px 图标 + 24px/700 结论 + 行动指令（AC-10 三通道） */
export function VerdictCard({
  status,
  title,
  action,
}: {
  status: ResultStatus;
  title: string;
  action: string;
}) {
  const theme = STATUS_THEMES[status];
  const Icon = theme.icon;
  return (
    <div className={`rounded-lg p-6 shadow-raised ${theme.bgClass}`} role="status">
      <Icon size={32} strokeWidth={2.25} className={theme.fgClass} aria-hidden />
      <p className={`mb-0 mt-3 text-2xl font-bold leading-verdict ${theme.fgClass}`}>{title}</p>
      <p className="mb-0 mt-3 text-lg font-medium text-fg leading-normal">{action}</p>
    </div>
  );
}

/** 主核验对象引用块 */
export function ClaimQuote({ intro, claim }: { intro: string; claim: string }) {
  return (
    <>
      <p className="mb-2 mt-6 text-sm text-muted">{intro}</p>
      <div className="rounded-md border border-border bg-surface px-4 py-3.5 text-base leading-body text-fg-2">
        “{claim}”
      </div>
    </>
  );
}

/** 理由条目（编号 + 18px/1.6） */
export function ReasonList({ title, reasons }: { title: string; reasons: string[] }) {
  if (reasons.length === 0) return null;
  return (
    <section aria-label={title}>
      <h2 className="mb-3.5 mt-7 text-xl font-bold leading-title">{title}</h2>
      <div className="flex flex-col gap-4">
        {reasons.map((reason, i) => (
          <div key={i} className="flex items-start gap-3">
            <span
              aria-hidden
              className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-pill bg-surface-warm text-sm font-bold text-fg-2"
            >
              {i + 1}
            </span>
            <p className="m-0 text-base leading-body">{reason}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

/** 来源列表：机构名 + 标题 + external-link，整行 ≥48px 热区 */
export function SourceList({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;
  return (
    <section aria-label="依据来自">
      <p className="mb-2 mt-6 text-xs leading-normal text-meta">依据来自</p>
      <div className="flex flex-col gap-2">
        {sources.map((src, i) => (
          <a
            key={i}
            href={src.url}
            target="_blank"
            rel="noreferrer noopener"
            className="flex min-h-touch-min items-center gap-2.5 rounded-sm border border-border-soft bg-surface px-3 py-2.5 no-underline transition-colors duration-fast ease-standard hover:bg-surface-warm focus-visible:outline-none focus-visible:shadow-[var(--focus-ring)]"
          >
            <span className="min-w-0 flex-1">
              <span className="block text-base font-medium text-fg">{src.publisher}</span>
              <span className="mt-0.5 block text-sm text-muted">{src.title}</span>
            </span>
            <ExternalLink size={16} strokeWidth={2} className="shrink-0 text-meta" aria-hidden />
          </a>
        ))}
      </div>
    </section>
  );
}

/** AI 画面边界说明（visual_suspect 态专属，AC-08） */
export function VisualNote({ note }: { note: string }) {
  return (
    <div className="mt-5 flex items-start gap-2.5 rounded-sm border border-border bg-surface p-3.5">
      <Info size={20} strokeWidth={2} className="mt-0.5 shrink-0 text-status-visual" aria-hidden />
      <p className="m-0 text-sm leading-body text-muted">{note}</p>
    </div>
  );
}

/** 非主核验对象里的转账、扫码、停药等危险操作也必须单独提醒 */
export function RiskAlertList({ alerts }: { alerts: string[] }) {
  if (alerts.length === 0) return null;
  return (
    <section className="mt-5 rounded-md border border-status-danger/30 bg-status-danger-bg p-4" aria-label="还要注意">
      <h2 className="m-0 flex items-center gap-2 text-base font-bold text-status-danger">
        <TriangleAlert size={20} strokeWidth={2.2} aria-hidden />
        还要注意
      </h2>
      <div className="mt-2.5 flex flex-col gap-2">
        {alerts.map((alert, i) => (
          <p key={i} className="m-0 text-base leading-body text-fg">{alert}</p>
        ))}
      </div>
    </section>
  );
}

/** 建议条目（check 图标 + 18px） */
export function AdviceList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-label={title}>
      <h2 className="mb-3.5 mt-0 text-xl font-bold leading-title">{title}</h2>
      <div className="flex flex-col gap-3.5">
        {items.map((item, i) => (
          <div key={i} className="flex items-start gap-3">
            <Check size={20} strokeWidth={2} className="mt-1 shrink-0 text-accent" aria-hidden />
            <p className="m-0 text-base leading-body">{item}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
