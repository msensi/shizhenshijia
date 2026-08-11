/** Mock 数据层：模拟 7 种结果状态 + 6 种异常的 API 响应，开发自测用。
 *  通过 URL 查询参数 ?mock=<场景> 触发；无参数时走真实 API。
 *  例：/processing/mock?mock=refuted 、 /?mock=rate
 */
import type {
  AnalysisCreatedData,
  AnalysisDetailData,
  AdminAnalyticsData,
  ApiEnvelope,
  ResultStatus,
} from '../types/api';
import { ApiError, NetworkError } from '../lib/errors';

const BASE: Pick<AnalysisDetailData, 'advice' | 'reasons' | 'risk_alerts' | 'sources'> = {
  reasons: [],
  risk_alerts: [],
  advice: null,
  sources: [],
};

const MOCK_RESULTS: Record<ResultStatus, Partial<AnalysisDetailData>> = {
  refuted: {
    result_status: 'refuted',
    domain: 'health',
    primary_claim: '血压正常了，就可以把降压药停了',
    reasons: [
      '国家卫健委的资料里写得很清楚：血压正常是药物控制的结果，不是病好了，自己停药血压会反弹',
      '科学辟谣平台也提醒过：擅自停降压药可能诱发心梗、脑卒中，风险比继续吃药大得多',
    ],
    advice: '建议您继续按医生开的方案吃药，不要自己停药或减量\n要是想调整用药，先挂个号问医生，把最近的血压记录带上',
    sources: [
      { title: '《高血压患者能自行停药吗？》', publisher: '国家卫健委', url: 'https://www.nhc.gov.cn/', quote: '血压正常是药物控制的结果' },
      { title: '《血压正常就停药？这个坑别踩》', publisher: '科学辟谣平台 · 科普中国', url: 'https://piyao.kepuchina.cn/', quote: '擅自停降压药可能诱发心梗、脑卒中' },
    ],
  },
  supported: {
    result_status: 'supported',
    domain: 'policy',
    primary_claim: '2026 年高龄津贴申请开始了，80 岁以上老人每月可领 300 元',
    reasons: [
      '市民政局官网有正式通知，内容和图片里说的一致',
      '不过图片里那个"点击链接登记"不是官方办理方式——官方通知写的是去社区服务中心或政务 App 办理',
    ],
    advice: '建议您带上身份证到社区服务中心办理，或者让子女在政务 App 上帮您操作\n图片里那个链接您别点，那不是官方渠道',
    sources: [
      { title: '《关于开展 2026 年高龄津贴申请工作的通知》', publisher: '市民政局', url: 'https://www.gov.cn/', quote: '80 岁以上老人每月可领 300 元' },
    ],
  },
  visual_suspect: {
    result_status: 'visual_suspect',
    domain: 'news',
    primary_claim: '一段视频截图，称"某地江边出现真龙，多人围观"',
    reasons: [
      '中国互联网联合辟谣平台上没有查到这个事件的真实记录',
      '当地官方和权威新闻机构也没有发布相关消息',
    ],
    advice: '先不要转发；请以政府部门或权威新闻机构的正式报道为准',
    visual_note: '单张截图无法证明画面由 AI 生成，也可能是特效、影视片段或旧素材；这里核验的是画面所说的事件有没有可信来源证实',
    sources: [],
  },
  disputed: {
    result_status: 'disputed',
    domain: 'health',
    primary_claim: '每天喝醋可以软化血管、降血脂',
    reasons: [
      '一些科普机构认为适量吃醋没害处，但也明确说"软化血管"没有证据',
      '国家卫健委的科普资料则直接提醒：靠喝醋降血脂不靠谱，空腹大量喝还伤胃——两边对"有没有用"的说法不一致',
    ],
    advice: '建议您血脂高就按医生的方案吃药、按时复查，别指望偏方\n以后拿不准的说法，您就发给子女或社区医生帮您看看',
    sources: [
      { title: '《喝醋能软化血管吗？》', publisher: '国家卫健委', url: 'https://www.nhc.gov.cn/', quote: '靠喝醋降血脂不靠谱' },
    ],
  },
  insufficient_evidence: {
    result_status: 'insufficient_evidence',
    domain: 'health',
    primary_claim: '某款保健品连着吃七天，血糖就能降下来',
    reasons: [
      '国家卫健委、科学辟谣平台这些权威渠道都查了一遍，没找到支持这个说法的依据',
      '另外提醒您，"七天见效"这种承诺是保健品宣传里的常见夸大话术，要格外小心',
    ],
    advice: '建议您在查清楚之前，先不要买、不要吃\n血糖的问题听医生的，别因为保健品停掉降糖药',
    sources: [],
  },
  out_of_scope: {
    result_status: 'out_of_scope',
    domain: 'out_of_scope',
    primary_claim: '一只股票的涨跌分析和推荐买入的说法',
    reasons: [
      '股票、投资类的内容不在核验范围内，投资方面的判断做不了',
      '不过要提醒您一句：群里推荐股票的"老师"和"内部消息"，绝大多数是骗局，您要格外当心',
    ],
    advice: '建议您涉及钱的事先跟子女商量，或者拨打反诈专线 96110 咨询\n如果是健康、补贴、防骗类的图片，欢迎您再来查',
    sources: [],
  },
  unreadable: {
    result_status: 'unreadable',
    domain: null,
    primary_claim: null,
    reasons: ['图片里的文字太模糊了，找不到一条可以核验的完整说法'],
    advice: '直接用手机拍那张图片或那段文字，拍正、拍全\n如果是微信里的消息，直接截屏上传更方便\n光线亮一点、手别抖，字就能拍清楚',
    sources: [],
  },
};

const STAGES = ['reading_image', 'checking_scope', 'finding_evidence', 'summarizing'] as const;

function now(): number {
  return Date.now();
}

/** 每个 analysis_id 的创建时间，用于模拟轮询推进 */
const createdAt = new Map<string, number>();

export const mockScenarios = [
  'refuted', 'supported', 'visual_suspect', 'disputed',
  'insufficient_evidence', 'out_of_scope', 'unreadable',
  'timeout', 'quota', 'maintain', 'error', 'network',
] as const;
export type MockScenario = (typeof mockScenarios)[number];

export function getMockScenario(): MockScenario | null {
  const v = new URLSearchParams(window.location.search).get('mock');
  return v && (mockScenarios as readonly string[]).includes(v) ? (v as MockScenario) : null;
}

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export async function mockCreateAnalysis(
  scenario: MockScenario,
): Promise<ApiEnvelope<AnalysisCreatedData>> {
  await delay(300);
  if (scenario === 'quota') throw new ApiError(3901, '今日额度已用完');
  if (scenario === 'maintain') throw new ApiError(5901, '服务配置异常');
  if (scenario === 'error') throw new ApiError(5000, '内部错误');
  if (scenario === 'network') throw new NetworkError();
  const id = `mock-${scenario}-${now()}`;
  createdAt.set(id, now());
  return {
    code: 0,
    data: {
      analysis_id: id,
      status: 'queued',
      expires_at: null,
    },
  };
}

export async function mockGetAnalysis(
  id: string,
): Promise<ApiEnvelope<AnalysisDetailData>> {
  await delay(200);
  const scenario = getMockScenario() ?? 'refuted';
  const start = createdAt.get(id) ?? now();
  const elapsed = now() - start;

  if (scenario === 'timeout') {
    // 永不完成，交给轮询超时逻辑产出 T-408
    return {
      code: 0,
      data: { ...BASE, analysis_id: id, status: 'processing', progress_stage: 'finding_evidence' },
    };
  }

  if (elapsed < 2400) {
    const stage = STAGES[Math.min(Math.floor(elapsed / 800), STAGES.length - 1)];
    return {
      code: 0,
      data: { ...BASE, analysis_id: id, status: 'processing', progress_stage: stage },
    };
  }

  const result = MOCK_RESULTS[scenario as ResultStatus] ?? MOCK_RESULTS.refuted;
  return {
    code: 0,
    data: {
      ...BASE,
      ...result,
      analysis_id: id,
      status: 'completed',
      progress_stage: null,
      title: null,
      summary: null,
      error_code: null,
    },
  };
}

export async function mockAdminAnalytics(): Promise<ApiEnvelope<AdminAnalyticsData>> {
  await delay(200);
  const items: AdminAnalyticsData['items'] = [
    { analysis_id: 'ana_mock_001', created_at: new Date(now() - 3600_000).toISOString(), domain: 'health', primary_claim: '血压正常就可以停药', result_status: 'refuted', source_count: 2, latency_ms: 6240, error_code: null },
    { analysis_id: 'ana_mock_002', created_at: new Date(now() - 7200_000).toISOString(), domain: 'news', primary_claim: '江边出现真龙视频截图', result_status: 'visual_suspect', source_count: 1, latency_ms: 18930, error_code: null },
    { analysis_id: 'ana_mock_003', created_at: new Date(now() - 10800_000).toISOString(), domain: 'out_of_scope', primary_claim: '股票推荐买入', result_status: 'out_of_scope', source_count: 0, latency_ms: 3120, error_code: null },
    { analysis_id: 'ana_mock_004', created_at: new Date(now() - 14400_000).toISOString(), domain: null, primary_claim: null, result_status: null, source_count: 0, latency_ms: 61000, error_code: 2001 },
  ].map((item) => ({ ...item, reasons: [], risk_alerts: [], sources: [] }));
  return { code: 0, data: { items, total: items.length, page: 1, limit: 20, hasMore: false } };
}
