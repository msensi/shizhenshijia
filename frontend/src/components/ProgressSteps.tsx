import { Check, Circle, LoaderCircle } from 'lucide-react';
import type { ProgressStage } from '../types/api';

interface StepDef {
  key: Exclude<ProgressStage, null>;
  label: string;
}

/** 四步进度（处理中页，屏 2 定稿文案） */
const STEPS: StepDef[] = [
  { key: 'reading_image', label: '读取图片上的字' },
  { key: 'checking_scope', label: '判断这件事能不能查' },
  { key: 'finding_evidence', label: '正在帮您查找官方依据…' },
  { key: 'summarizing', label: '整理成您能看懂的结果' },
];

type StepState = 'done' | 'doing' | 'waiting';

function stepStates(current: ProgressStage): StepState[] {
  const activeIdx = current ? STEPS.findIndex((s) => s.key === current) : 0;
  const idx = activeIdx < 0 ? 0 : activeIdx;
  return STEPS.map((_, i) => (i < idx ? 'done' : i === idx ? 'doing' : 'waiting'));
}

export function ProgressSteps({ stage }: { stage: ProgressStage }) {
  const states = stepStates(stage);
  return (
    <ol className="m-0 mt-5 list-none p-0" aria-label="核验进度">
      {STEPS.map((step, i) => {
        const state = states[i];
        return (
          <li key={step.key} className="flex items-center gap-3.5 py-3.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center">
              {state === 'done' && (
                <Check size={24} strokeWidth={2} className="text-accent" aria-hidden />
              )}
              {state === 'doing' && (
                <LoaderCircle size={24} strokeWidth={2} className="mb-spin text-accent" aria-hidden />
              )}
              {state === 'waiting' && (
                <Circle size={24} strokeWidth={2} className="text-meta" aria-hidden />
              )}
            </span>
            <p
              className={`m-0 text-base ${
                state === 'doing' ? 'font-bold text-fg' : state === 'done' ? 'text-fg' : 'text-meta'
              }`}
              aria-current={state === 'doing' ? 'step' : undefined}
            >
              {step.label}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
