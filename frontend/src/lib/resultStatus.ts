import type { LucideIcon } from 'lucide-react';
import {
  CircleMinus,
  FileQuestion,
  GitFork,
  ImageOff,
  SearchX,
  ShieldCheck,
  XOctagon,
} from 'lucide-react';
import type { ResultStatus } from '../types/api';

export interface StatusTheme {
  /** 结论色块背景类（状态浅底） */
  bgClass: string;
  /** 状态主色文本/图标类 */
  fgClass: string;
  icon: LucideIcon;
  /** 结论文案（后端 title 缺失时的兜底，设计稿定稿） */
  verdict: string;
  /** 行动指令（后端 advice 无结论文案时的兜底） */
  action: string;
  /** 「为什么」区块标题 */
  whyTitle: string;
  /** 「怎么做」区块标题 */
  adviceTitle: string;
  /** 主核验对象引导语 */
  claimIntro: string;
  /** 主按钮文案 */
  cta: string;
}

export const STATUS_THEMES: Record<ResultStatus, StatusTheme> = {
  supported: {
    bgClass: 'bg-status-safe-bg',
    fgClass: 'text-status-safe',
    icon: ShieldCheck,
    verdict: '这条消息有官方依据，可以信',
    action: '建议：通过官方渠道办理，别点图片里的链接',
    whyTitle: '为什么',
    adviceTitle: '怎么做',
    claimIntro: '您上传的图片里说：',
    cta: '再查一张',
  },
  refuted: {
    bgClass: 'bg-status-danger-bg',
    fgClass: 'text-status-danger',
    icon: XOctagon,
    verdict: '这条说法与可信来源不符',
    action: '建议：不要按它说的做',
    whyTitle: '为什么',
    adviceTitle: '怎么做',
    claimIntro: '您上传的图片里说：',
    cta: '再查一张',
  },
  disputed: {
    bgClass: 'bg-status-dispute-bg',
    fgClass: 'text-status-dispute',
    icon: GitFork,
    verdict: '权威来源对这件事说法不一',
    action: '建议：先别照做，问问医生或子女',
    whyTitle: '为什么',
    adviceTitle: '怎么做',
    claimIntro: '您上传的图片里说：',
    cta: '再查一张',
  },
  insufficient_evidence: {
    bgClass: 'bg-status-unknown-bg',
    fgClass: 'text-status-unknown',
    icon: SearchX,
    verdict: '没查到足够依据，这既不是真的也不是假的',
    action: '建议：在查清楚之前，先别信、别照做',
    whyTitle: '为什么',
    adviceTitle: '怎么做',
    claimIntro: '您上传的图片里说：',
    cta: '再查一张',
  },
  visual_suspect: {
    bgClass: 'bg-status-visual-bg',
    fgClass: 'text-status-visual',
    icon: ImageOff,
    verdict: '暂时找不到可信来源证实这个画面',
    action: '建议：先别转发，等权威来源证实',
    whyTitle: '为什么',
    adviceTitle: '怎么做',
    claimIntro: '您上传的图片里是：',
    cta: '再查一张',
  },
  out_of_scope: {
    bgClass: 'bg-status-scope-bg',
    fgClass: 'text-status-scope',
    icon: CircleMinus,
    verdict: '这类内容暂时查不了',
    action: '目前只查健康、政策、防骗和热点画面这四类',
    whyTitle: '为什么查不了',
    adviceTitle: '怎么做',
    claimIntro: '您上传的图片是关于：',
    cta: '再查一张',
  },
  unreadable: {
    bgClass: 'bg-status-unclear-bg',
    fgClass: 'text-status-unclear',
    icon: FileQuestion,
    verdict: '这张图片没看清',
    action: '建议：换一张清楚一点的，再试一次',
    whyTitle: '为什么没看清',
    adviceTitle: '怎么拍才清楚',
    claimIntro: '您上传的图片里说：',
    cta: '重新上传一张',
  },
};
