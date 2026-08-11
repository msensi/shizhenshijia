import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Image } from 'lucide-react';
import { ErrorState } from '../components/ErrorState';
import { ProgressSteps } from '../components/ProgressSteps';
import { getAnalysis } from '../lib/api';
import { errorToShortCode, mapApiCodeToShort, type ShortErrorCode } from '../lib/errors';
import { getLastImage } from '../lib/uploadImage';
import type { ProgressStage } from '../types/api';

const POLL_INTERVAL = 1000;
const LONG_WAIT_HINT = 8000;
const POLL_TIMEOUT = 60_000;

export function ProcessingPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [stage, setStage] = useState<ProgressStage>('reading_image');
  const [slow, setSlow] = useState(false);
  const [errorCode, setErrorCode] = useState<ShortErrorCode | null>(null);
  const retryRef = useRef(0);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    const startedAt = Date.now();
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      if (cancelled) return;
      const elapsed = Date.now() - startedAt;
      if (elapsed >= POLL_TIMEOUT) {
        setErrorCode('T-408');
        return;
      }
      if (elapsed >= LONG_WAIT_HINT) setSlow(true);
      try {
        const res = await getAnalysis(id);
        if (cancelled) return;
        const data = res.data;
        if (data.status === 'completed') {
          navigate(`/result/${id}`, { replace: true });
          return;
        }
        if (data.status === 'failed') {
          setErrorCode(
            typeof data.error_code === 'number' ? mapApiCodeToShort(data.error_code) : 'E-500',
          );
          return;
        }
        setStage(data.progress_stage ?? 'reading_image');
      } catch (err) {
        if (cancelled) return;
        setErrorCode(errorToShortCode(err));
        return;
      }
      timer = setTimeout(poll, POLL_INTERVAL);
    }

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [id, navigate, retryRef.current]);

  if (errorCode) {
    return (
      <div className="page-shell">
        <div className="page-inner">
          <ErrorState
            code={errorCode}
            onRetry={() => {
              setErrorCode(null);
              retryRef.current += 1;
            }}
            onHome={() => navigate('/', { replace: true })}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="page-shell">
      <div className="page-inner">
        <h1 className="mb-4 mt-0 text-xl font-bold leading-title">正在帮您核验</h1>

        {/* 上传图片缩略图卡片 */}
        <div className="flex items-center gap-3.5 rounded-md border border-border bg-surface p-3">
          {getLastImage() ? (
            <img
              src={getLastImage() ?? undefined}
              alt="您上传的图片"
              className="h-16 w-16 shrink-0 rounded-sm object-cover"
            />
          ) : (
            <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-sm bg-surface-warm">
              <Image size={24} strokeWidth={2} className="text-meta" aria-hidden />
            </div>
          )}
          <p className="m-0 text-sm text-muted">
            您上传的图片已收到
            <br />
            正在逐条核验
          </p>
        </div>

        <ProgressSteps stage={stage} />

        <p className="mb-0 mt-6 text-center text-sm text-muted" role="status">
          {slow ? '正在继续深查，可能还需要一点时间' : '一般 10 秒内就好，您稍等一下'}
        </p>
      </div>
    </div>
  );
}
