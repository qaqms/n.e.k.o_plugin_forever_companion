// 面板共享逻辑：阶段配色/文案映射、情绪徽标语气、设置快照 → 表单初值
import type { FormValues, Settings, Status, TFunc } from "./types"

export const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

// 面板展示层去 emoji：情绪动作标签带 emoji 是给模型辨语气用的（后端不动），
// 面板渲染前统一剔掉，保持纯文字观感；仅去图形符号区，不动正常文字与标点
export function stripEmoji(text?: string): string {
  return String(text || "")
    .replace(/[\u{1F000}-\u{1FAFF}\u{2190}-\u{2BFF}\u{2600}-\u{27BF}\u{2100}-\u{214F}\u{FE0F}\u{200D}]/gu, "")
    .trim()
}

// 情绪徽标语气：正面动作（暖流涌动/满潮欢喜）用 success，心有涟漪与 5 个负面动作维持 warning
export const POSITIVE_MOOD_ACTIONS = new Set(["warm_current", "spring_tide"])

export function moodBadgeTone(action?: string): "warning" | "success" {
  return action && POSITIVE_MOOD_ACTIONS.has(action) ? "success" : "warning"
}

// 连续心情二维量 → 心情词 i18n key 分桶：valence 定冷暖、arousal 定强弱
// （雀跃=好且激动，烦躁=坏且激动，低落=坏且平静）
export function moodWordOf(valence: number, arousal: number): string {
  if (valence > 0.4) return arousal > 0.5 ? "panel.mood.word.elated" : "panel.mood.word.bright"
  if (valence > 0.1) return "panel.mood.word.warm"
  if (valence >= -0.1) return "panel.mood.word.calm"
  if (valence >= -0.4) return "panel.mood.word.muffled"
  return arousal > 0.5 ? "panel.mood.word.restless" : "panel.mood.word.low"
}

// 心情指示点配色：valence 插值——负=灰蓝、近零=中性灰、正=暖琥珀
export function moodDotColor(valence: number): string {
  const v = Math.max(-1, Math.min(1, valence))
  const to = v < 0 ? [110, 141, 171] : [245, 176, 77]
  const ratio = Math.abs(v)
  const mix = (zero: number, target: number) => Math.round(zero + (target - zero) * ratio)
  return `rgb(${mix(148, to[0])}, ${mix(163, to[1])}, ${mix(184, to[2])})`
}

// 愉悦度双向条填充色：正侧恒暖琥珀、负侧恒灰蓝（与 moodDotColor 的"近零=灰"不同——
// 条形图需要每侧有辨识色，否则静息态（valence=0，显示 50 分）整条灰掉，
// 与"未启用"视觉混淆；心情词/胶囊仍用 moodDotColor，两套语义并存）
export function valenceBarColor(valence: number): string {
  return valence < 0 ? "rgb(110, 141, 171)" : "rgb(245, 176, 77)"
}

// 活跃度配色：arousal 三段插值——低=中性灰、中=天蓝、高=活跃红，
// 与轨道"左灰→中蓝→右红"渐变同一色标，填充/游标随当前值取色
export function arousalColor(arousal: number): string {
  const a = Math.max(0, Math.min(1, arousal))
  const from = a < 0.5 ? [100, 116, 139] : [96, 165, 250]
  const to = a < 0.5 ? [96, 165, 250] : [244, 63, 94]
  const ratio = a < 0.5 ? a * 2 : (a - 0.5) * 2
  const mix = (f: number, t: number) => Math.round(f + (t - f) * ratio)
  return `rgb(${mix(from[0], to[0])}, ${mix(from[1], to[1])}, ${mix(from[2], to[2])})`
}

// api.call 的返回值是宿主信封 {plugin_id, action_id, result: <入口载荷>}，
// iframe 侧不做解包；这里兼容两种形态取出真实载荷（信封判据：同时带 action_id 与 result 键）
export function unwrapCallResult<T = Record<string, any>>(payload: any): T {
  if (payload && typeof payload === "object" && "result" in payload && "action_id" in payload) {
    return payload.result as T
  }
  return payload as T
}

// 时光日记自动碎片的类型 → i18n key 后缀（panel.diary.kind.*）
export function fragmentKindKey(kind?: string): string {
  const known = ["like", "dislike", "important", "overstep"]
  return known.indexOf(String(kind || "")) >= 0 ? `panel.diary.kind.${kind}` : "panel.diary.kind.important"
}

// 个人日记页眉的心情走向：该页各段落笔瞬间的愉悦度均值 → 文案分档
//（与状态栏心情胶囊同款冷暖语义，但只看 valence、不分强弱档）
export function journalTrendKey(moodAvg?: number | null): string {
  if (moodAvg === null || moodAvg === undefined) return "panel.journal.trend.unknown"
  if (moodAvg > 0.2) return "panel.journal.trend.warm"
  if (moodAvg >= -0.2) return "panel.journal.trend.calm"
  return "panel.journal.trend.cold"
}

// 愉悦度显示分制：内部 [-1,1] 映射为 0~100 整数分（50=中性）——静息态显示 50，
// 避免 "0.00" 看起来像"没有愉悦"；仅显示层换算，数据语义不变
export function valenceScore(valence: number): number {
  const v = Math.max(-1, Math.min(1, Number(valence) || 0))
  return Math.round(v * 50 + 50)
}

// 活跃度显示分制：内部 [0,1] 映射为 0~100 整数分，与愉悦度分制观感一致
export function arousalScore(arousal: number): number {
  const a = Math.max(0, Math.min(1, Number(arousal) || 0))
  return Math.round(a * 100)
}

// 注意：hosted-tsx 校验器不识别泛型尖括号层级，export const 的类型注解里不能带逗号，
// 所以先起类型别名再注解（直接写 Record<string, string> 会被误判为多声明符）
export type PhaseColorMap = Record<string, string>

export const PHASE_COLOR: PhaseColorMap = {
  menstrual: "var(--danger)",
  follicular: "var(--success)",
  ovulatory: "var(--info)",
  luteal: "var(--text)",
  // 锚点前：展示层按平稳期呈现（与 cycle.py 标签映射同语义），配色同平稳期
  before_start: "var(--text)",
}

export function phaseColorOf(status: Status): string {
  return status.enabled === false ? "var(--muted)" : PHASE_COLOR[status.phase || ""] || "var(--text)"
}

export function phaseLabels(t: TFunc): Record<string, string> {
  return {
    menstrual: t("panel.ring.phase.menstrual", { defaultValue: "潮汐期" }),
    follicular: t("panel.ring.phase.follicular", { defaultValue: "回升期" }),
    ovulatory: t("panel.ring.phase.ovulatory", { defaultValue: "活跃期" }),
    luteal: t("panel.ring.phase.luteal", { defaultValue: "平稳期" }),
  }
}

// 名单行的阶段 id → 阶段名：复用四阶段映射（before_start 展示层按平稳期，同后端语义）
export function lanlanPhaseLabel(t: TFunc, phase?: string): string {
  if (!phase || phase === "error") return ""
  return phaseLabels(t)[phase] || ""
}

export function settingsToForm(settings: Settings): FormValues {
  return {
    auto_derive: settings.auto_derive !== false,
    cycle_length: Number(settings.cycle_length ?? 28),
    period_length: Number(settings.period_length ?? 5),
    ovulation_day: Number(settings.ovulation_day ?? 14),
    ovulation_window: Number(settings.ovulation_window ?? 3),
    inject_mode: String(settings.inject_mode || "every_user_message"),
    inject_interval_n: Number(settings.inject_interval_n ?? 3),
    phase_openers: settings.phase_openers !== false,
    timezone: String(settings.timezone || "auto"),
    mood_enabled: settings.mood_enabled !== false,
    default_action_minutes: Number(settings.default_action_minutes ?? 20),
    emotion_sense_enabled: settings.emotion_sense_enabled !== false,
    tone_check_rate: Number(settings.tone_check_rate ?? 1),
    tone_phase_sensitivity_enabled: settings.tone_phase_sensitivity_enabled !== false,
    tone_phase_sensitivity: Number(settings.tone_phase_sensitivity ?? 0.15),
    tone_slot: String(settings.tone_slot || ""),
    fragments_enabled: settings.fragments_enabled !== false,
    fragments_slot: String(settings.fragments_slot || "summary"),
    review_enabled: settings.review_enabled !== false,
    review_slot: String(settings.review_slot || "summary"),
    review_turns_threshold: Number(settings.review_turns_threshold ?? 50),
    review_days_threshold: Number(settings.review_days_threshold ?? 7),
    debug_mode: settings.debug_mode === true,
  }
}
