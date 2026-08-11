import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { RotateCcw } from 'lucide-react';
import { ErrorState } from '../components/ErrorState';
import {
  AdviceList,
  ClaimQuote,
  ReasonList,
  RiskAlertList,
  SourceList,
  VerdictCard,
  VisualNote,
} from '../components/ResultBlocks';
import { getAnalysis } from '../lib/api';
import { errorToShortCode, mapApiCodeToShort, type ShortErrorCode } from '../lib/errors';
import { getLastImage } from '../lib/uploadImage';
import { STATUS_THEMES } from '../lib/resultStatus';
import type { AnalysisDetailData } from '../types/api';

export function ResultPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<AnalysisDetailData | null>(null);
  const [errorCode, setErrorCode] = useState<ShortErrorCode | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    getAnalysis(id)
      .then((res) => {
        if (cancelled) return;
        const d = res.data;
        if (d.status === 'completed' && d.result_status) {
          setData(d);
        } else if (d.status === 'failed') {
          setErrorCode(typeof d.error_code === 'number' ? mapApiCodeToShort(d.error_code) : 'E-500');
        } else {
          // 任务仍在处理：回到处理中页继续等
          navigate(`/processing/${id}`, { replace: true });
        }
      })
      .catch((err) => {
        if (!cancelled) setErrorCode(errorToShortCode(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, navigate]);

  const goHome = () => navigate('/', { replace: true });

  if (errorCode) {
    return (
      <div className="page-shell">
        <div className="page-inner">
          <ErrorState code={errorCode} onRetry={goHome} onHome={goHome} />
        </div>
      </div>
    );
  }

  if (loading || !data || !data.result_status) {
    return (
      <div className="page-shell">
        <div className="page-inner">
          <p className="m-0 pt-12 text-center text-sm text-muted" role="status">
            正在读取结果…
          </p>
        </div>
      </div>
    );
  }

  const status = data.result_status;
  const theme = STATUS_THEMES[status];
  const adviceItems = (data.advice ?? '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);

  return (
    <div className="page-shell">
      <div className="page-inner">
        {/* 三段式：结论 → 为什么 → 怎么做（AC-10，静态不自动刷新） */}
        <VerdictCard
          status={status}
          title={data.title ?? theme.verdict}
          action={data.summary ?? theme.action}
        />

        {/* 用户上传图片的缩略图：帮老人回忆"我查的是哪张图" */}
        {getLastImage() && (
          <figure className="mb-0 mt-4 flex items-center gap-3.5 rounded-md border border-border bg-surface p-3">
            <img
              src={getLastImage() ?? undefined}
              alt="您上传核验的图片"
              className="h-16 w-16 shrink-0 rounded-sm object-cover"
            />
            <figcaption className="text-sm text-muted">您上传核验的图片</figcaption>
          </figure>
        )}

        {data.primary_claim && <ClaimQuote intro={theme.claimIntro} claim={data.primary_claim} />}

        <ReasonList title={theme.whyTitle} reasons={data.reasons} />

        <SourceList sources={data.sources} />

        {status === 'visual_suspect' && data.visual_note && <VisualNote note={data.visual_note} />}

        <RiskAlertList alerts={data.risk_alerts ?? []} />

        <hr className="my-7 border-0 border-t border-border-soft" />

        <AdviceList title={theme.adviceTitle} items={adviceItems} />

        <div className="mt-8">
          <button type="button" className="btn-primary" onClick={goHome}>
            <RotateCcw size={20} strokeWidth={2} aria-hidden />
            <span>{theme.cta}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
