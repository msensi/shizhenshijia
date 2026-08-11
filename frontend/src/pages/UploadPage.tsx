import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Camera,
  Images,
  Landmark,
  Newspaper,
  ShieldAlert,
  Stethoscope,
} from 'lucide-react';
import { BrandMark } from '../components/BrandMark';
import { ErrorState } from '../components/ErrorState';
import { ACCEPT_ATTR, createAnalysis, validateUploadFile } from '../lib/api';
import { errorToShortCode, type ShortErrorCode } from '../lib/errors';
import { clearLastImage } from '../lib/uploadImage';

export function UploadPage() {
  const navigate = useNavigate();
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const albumInputRef = useRef<HTMLInputElement>(null);
  const [submitting, setSubmitting] = useState(false);
  const [tip, setTip] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<ShortErrorCode | null>(null);

  useEffect(() => {
    // 回到首页说明上一次查看已经结束，立即撤销浏览器里的临时缩略图。
    clearLastImage();
  }, []);

  async function handleFile(file: File | null | undefined) {
    if (!file || submitting) return;
    const invalid = validateUploadFile(file);
    if (invalid) {
      setTip(invalid);
      return;
    }
    setTip(null);
    setSubmitting(true);
    try {
      const res = await createAnalysis(file);
      navigate(`/processing/${res.data.analysis_id}`);
    } catch (err) {
      setErrorCode(errorToShortCode(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (errorCode) {
    return (
      <div className="page-shell">
        <div className="page-inner">
          <ErrorState
            code={errorCode}
            onRetry={() => setErrorCode(null)}
            onHome={() => setErrorCode(null)}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="page-shell upload-layout">
      <div className="upload-scroll-region">
        <header className="flex items-center gap-4">
          <BrandMark size={72} />
          <div>
            <h1 className="m-0 text-3xl font-bold leading-title">是真是假</h1>
            <p className="mb-0 mt-1.5 text-sm text-muted">拍张图，帮您看看网上的消息能不能信</p>
          </div>
        </header>

        <main className="mt-7">
          <h2 className="mb-2 mt-0 text-xl font-bold leading-title">可以帮您查这些</h2>
          <div className="scope-row">
            <span className="scope-icon"><Stethoscope size={24} strokeWidth={2} aria-hidden /></span>
            <p>偏方、保健品、用药的说法</p>
          </div>
          <div className="scope-row">
            <span className="scope-icon"><Landmark size={24} strokeWidth={2} aria-hidden /></span>
            <p>养老金、医保、补贴、办事通知</p>
          </div>
          <div className="scope-row">
            <span className="scope-icon"><ShieldAlert size={24} strokeWidth={2} aria-hidden /></span>
            <p>转账、领奖、扫码等防骗信息</p>
          </div>
          <div className="scope-row">
            <span className="scope-icon"><Newspaper size={24} strokeWidth={2} aria-hidden /></span>
            <p>热点事件、疑似 AI 的奇怪画面</p>
          </div>

          <div className="scope-limit-note">
            <span className="scope-limit-dot" aria-hidden>i</span>
            <p>汽车、股票、娱乐八卦，暂时还查不了</p>
          </div>
        </main>
      </div>

      <footer className="upload-action-region">
        <div className="flex w-full flex-col gap-3">
          <button
            type="button"
            className="btn-primary"
            disabled={submitting}
            onClick={() => cameraInputRef.current?.click()}
          >
            <Camera size={22} strokeWidth={2} aria-hidden />
            <span>{submitting ? '正在上传，请稍等' : '拍照'}</span>
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={submitting}
            onClick={() => albumInputRef.current?.click()}
          >
            <Images size={22} strokeWidth={2} aria-hidden />
            <span>{submitting ? '正在上传，请稍等' : '从相册上传图片'}</span>
          </button>
        </div>

        {tip && (
          <p role="alert" className="mb-0 mt-3 text-center text-sm text-status-danger">
            {tip}
          </p>
        )}

        <p className="privacy-note">图片不保存到服务器，查看完即清除</p>
      </footer>

      <input
        ref={cameraInputRef}
        type="file"
        accept={ACCEPT_ATTR}
        capture="environment"
        className="hidden"
        onChange={(e) => {
          handleFile(e.target.files?.[0]);
          e.target.value = '';
        }}
      />
      <input
        ref={albumInputRef}
        type="file"
        accept={ACCEPT_ATTR}
        className="hidden"
        onChange={(e) => {
          handleFile(e.target.files?.[0]);
          e.target.value = '';
        }}
      />
    </div>
  );
}
