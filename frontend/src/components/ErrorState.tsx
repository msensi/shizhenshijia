import type { LucideIcon } from 'lucide-react';
import {
  CalendarX,
  CircleAlert,
  CloudOff,
  House,
  RotateCcw,
  TimerOff,
  Wrench,
} from 'lucide-react';
import type { ShortErrorCode } from '../lib/errors';

interface ErrorSpec {
  icon: LucideIcon;
  lines: [string, string];
  note: string;
  cta: 'retry' | 'home';
}

/** 6 态异常规格（屏 11-16 定稿文案，描述文案无句尾标点） */
const ERROR_SPECS: Record<ShortErrorCode, ErrorSpec> = {
  'T-408': {
    icon: TimerOff,
    lines: ['这次核验花的时间太长了', '请稍后再试'],
    note: '您的图片没出问题，是查找依据花的时间太久了',
    cta: 'retry',
  },
  'Q-429': {
    icon: CalendarX,
    lines: ['今天的核验次数用完啦', '您明天再来吧'],
    note: '为了能帮更多人核验，每天有一定的次数限制',
    cta: 'home',
  },
  'S-503': {
    icon: Wrench,
    lines: ['服务正在维护中', '您稍后再试'],
    note: '维护好了就能正常用了，您的图片不会被保存',
    cta: 'home',
  },
  'E-500': {
    icon: CircleAlert,
    lines: ['出了点小问题', '您稍后再试'],
    note: '不是您操作的问题，再试一次一般就好了',
    cta: 'retry',
  },
  'N-001': {
    icon: CloudOff,
    lines: ['网络好像不太顺畅', '检查一下网络再试'],
    note: '您可以走到信号好一点的地方，或者看看 Wi-Fi 是不是断了',
    cta: 'retry',
  },
};

interface ErrorStateProps {
  code: ShortErrorCode;
  onRetry: () => void;
  onHome: () => void;
}

/** 异常/边界状态统一组件：88px 中性徽章 + 40px 图标 + 两行大白话
 *  + 补充说明 + 主按钮 + 14px 浅灰错误码右下角（屏 11-16） */
export function ErrorState({ code, onRetry, onHome }: ErrorStateProps) {
  const spec = ERROR_SPECS[code];
  const Icon = spec.icon;
  const isRetry = spec.cta === 'retry';
  const CtaIcon = isRetry ? RotateCcw : House;

  return (
    <div className="flex min-h-[560px] flex-col">
      <div className="flex flex-1 flex-col items-center justify-center gap-5 py-12 text-center">
        <span className="flex h-[88px] w-[88px] items-center justify-center rounded-pill bg-status-unclear-bg">
          <Icon size={40} strokeWidth={2} className="text-status-unclear" aria-hidden />
        </span>
        <p className="m-0 text-lg font-bold leading-normal">
          {spec.lines[0]}
          <br />
          {spec.lines[1]}
        </p>
        <p className="m-0 text-sm text-muted">{spec.note}</p>
      </div>
      <button type="button" className="btn-primary" onClick={isRetry ? onRetry : onHome}>
        <CtaIcon size={20} strokeWidth={2} aria-hidden />
        <span>{isRetry ? '再试一次' : '回到首页'}</span>
      </button>
      <p className="mb-0 mt-4 text-right text-xs text-meta">{code}</p>
    </div>
  );
}
