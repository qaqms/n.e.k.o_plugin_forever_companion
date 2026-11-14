// 设置卡合集：六张设置卡同住一个模块。宿主对面板运行时依赖限 32 个文件 / 512 KiB
// （tests/test_ui_dependency_budget.py 守着），小卡片合并以腾出文件名额。
import { Button, Card, Field, Grid, NumberInput } from "@neko/plugin-ui"
import { TmSelect, TmSwitch } from "./tmswitch"
import type { AgentTierUsage, ChannelStatusItem, FormValues, Mood, MoodEvent, Settings, TFunc, ToneSlotOption } from "./types"
import { arousalColor, arousalScore, moodDotColor, moodWordOf, stripEmoji, valenceBarColor, valenceScore } from "./utils"

// 宿主链接器的导出扫描不懂 JSX（`</tag>` 里的 `/` 会被当成正则起点），扫过第一段 JSX
// 之后的 export 都可能漏采、整面白屏（见 ui/capintro.tsx 签名纪律）。故六个导出只做
// 单行转发、集中在 JSX 之前，卡片本体（render*）与辅助函数一律排在后面。

// 通道模式：与 core/state.py 的 _CHANNEL_MODE_* 一字不差
const MODE_HOST = "host"
const MODE_CUSTOM = "custom"
const MODE_GATEWAY = "gateway"

type CycleSettingsCardProps = {
  t: TFunc
  settings: Settings
  form: FormValues
  updateForm: (patch: Partial<FormValues>) => void
  lanlan?: string
}

type InjectSettingsCardProps = {
  t: TFunc
  form: FormValues
  updateForm: (patch: Partial<FormValues>) => void
}

type MoodSettingsCardProps = {
  key?: string
  t: TFunc
  form: FormValues
  updateForm: (patch: Partial<FormValues>) => void
  mood: Mood
  enabled: boolean
  canEnd: boolean
  ending: boolean
  onEnd: () => void
}

type EmotionSenseSettingsCardProps = {
  t: TFunc
  form: FormValues
  updateForm: (patch: Partial<FormValues>) => void
}

type ChannelSettingsCardProps = {
  t: TFunc
  form: FormValues
  updateForm: (patch: Partial<FormValues>) => void
  toneSlotOptions?: ToneSlotOption[]
  channelStatus?: { tone?: ChannelStatusItem; fragments?: ChannelStatusItem; review?: ChannelStatusItem }
  agentUsage?: AgentTierUsage
}

type DiarySettingsCardProps = {
  t: TFunc
  form: FormValues
  updateForm: (patch: Partial<FormValues>) => void
}

// 对外导出：只做转发、不含 JSX，必须排在文件里第一段 JSX 之前
export function CycleSettingsCard(props: CycleSettingsCardProps) { return renderCycleSettings(props) }
export function InjectSettingsCard(props: InjectSettingsCardProps) { return renderInjectSettings(props) }
export function MoodSettingsCard(props: MoodSettingsCardProps) { return renderMoodSettings(props) }
export function EmotionSenseSettingsCard(props: EmotionSenseSettingsCardProps) { return renderEmotionSenseSettings(props) }
export function ChannelSettingsCard(props: ChannelSettingsCardProps) { return renderChannelSettings(props) }
export function DiarySettingsCard(props: DiarySettingsCardProps) { return renderDiarySettings(props) }

// 设置 · 她的周期（每角色）：自动演算开关 + 周期参数
function renderCycleSettings(props: CycleSettingsCardProps) {
  const { t, settings, form, updateForm, lanlan } = props

  return (
    <Card title={t("panel.settings.sectionCycle", { defaultValue: "周期设置" })}>
      {lanlan ? (
        <div className="tm-derived">
          {t("panel.settings.sectionCycleHint", { defaultValue: "仅作用于当前查看的角色" })}：{lanlan}
        </div>
      ) : null}
      <TmSwitch
        checked={form.auto_derive}
        label={t("panel.settings.autoDerive", { defaultValue: "自动计算阶段参数" })}
        onChange={(value: boolean) => updateForm({ auto_derive: value })}
      />
      {form.auto_derive ? (
        <div className="tm-derived">
          {t("panel.settings.derivedResult", { defaultValue: "计算结果" })}：
          {t("panel.settings.tideNDays", { n: String(settings.period_length ?? 5), defaultValue: "潮汐期 {n} 天" })}
          {" · "}
          {t("panel.settings.activeDayN", { n: String(settings.ovulation_day ?? 14), defaultValue: "活跃日 第 {n} 天" })}
          {" · "}
          {t("panel.settings.activeWindowN", { n: String(settings.ovulation_window ?? 3), defaultValue: "活跃窗口 ±{n} 天" })}
        </div>
      ) : null}
      <Grid cols={2}>
        <Field className="tm-reserve-help" label={t("panel.settings.cycleLength", { defaultValue: "周期长度（天）" })}>
          <NumberInput value={form.cycle_length} min={10} max={90} step={1} onChange={(v: number | string) => updateForm({ cycle_length: typeof v === "number" ? v : 28 })} />
        </Field>
        {form.auto_derive ? null : (
          <Field className="tm-reserve-help" label={t("panel.settings.periodLength", { defaultValue: "潮汐期长度（天）" })}>
            <NumberInput value={form.period_length} min={1} max={14} step={1} onChange={(v: number | string) => updateForm({ period_length: typeof v === "number" ? v : 5 })} />
          </Field>
        )}
        {form.auto_derive ? null : (
          <Field className="tm-reserve-help" label={t("panel.settings.ovulationDay", { defaultValue: "活跃日（周期第几天）" })}>
            <NumberInput value={form.ovulation_day} min={2} max={89} step={1} onChange={(v: number | string) => updateForm({ ovulation_day: typeof v === "number" ? v : 14 })} />
          </Field>
        )}
        {form.auto_derive ? null : (
          <Field className="tm-reserve-help" label={t("panel.settings.ovulationWindow", { defaultValue: "活跃窗口半径（天）" })}>
            <NumberInput value={form.ovulation_window} min={1} max={5} step={1} onChange={(v: number | string) => updateForm({ ovulation_window: typeof v === "number" ? v : 3 })} />
          </Field>
        )}
      </Grid>
    </Card>
  )
}

// 设置 · 状态注入（全局）：身体状态以何种频率/方式进入对话上下文。
// 时区在「设置」页；这张卡只管注入行为。周期参数（角色独立）在「周期」页的她周期卡。
function renderInjectSettings(props: InjectSettingsCardProps) {
  const { t, form, updateForm } = props

  const injectModes = [
    { value: "every_user_message", label: t("panel.settings.modeEvery", { defaultValue: "每次消息" }) },
    { value: "interval_n", label: t("panel.settings.modeInterval", { defaultValue: "每 N 条消息" }) },
    { value: "on_trigger", label: t("panel.settings.modeTrigger", { defaultValue: "关键词触发" }) },
    { value: "off", label: t("panel.settings.modeOff", { defaultValue: "关闭提示" }) },
  ]

  return (
    <Card title={t("panel.settings.sectionInject", { defaultValue: "状态提示" })}>
      <div className="tm-derived">
        {t("panel.settings.sectionGlobalHint", { defaultValue: "以下设置对所有角色生效" })}
      </div>
      <Grid cols={2}>
        <Field label={t("panel.settings.injectMode", { defaultValue: "状态提示方式" })} help={t("panel.settings.injectModeHelp", { defaultValue: "设置后台状态提示加入对话的频率" })}>
          <TmSelect label={t("panel.settings.injectMode", { defaultValue: "状态提示方式" })} value={form.inject_mode} options={injectModes} onChange={(v: string) => updateForm({ inject_mode: v })} />
        </Field>
        {form.inject_mode === "interval_n" ? (
          <Field className="tm-reserve-help" label={t("panel.settings.intervalN", { defaultValue: "每 N 条消息检查一次" })}>
            <NumberInput value={form.inject_interval_n} min={1} max={50} step={1} onChange={(v: number | string) => updateForm({ inject_interval_n: typeof v === "number" ? v : 3 })} />
          </Field>
        ) : null}
      </Grid>
      <TmSwitch
        checked={form.phase_openers}
        label={t("panel.settings.phaseOpeners", { defaultValue: "阶段问候（阶段变化时提示一次）" })}
        onChange={(value: boolean) => updateForm({ phase_openers: value })}
      />
    </Card>
  )
}

// 情绪页：只读选择与事件记录；参数仍通过页面保存入口提交。
function renderMoodSettings(props: MoodSettingsCardProps) {
  const { t, form, updateForm } = props

  return (
    <>
    <MoodExperience {...props} />
    <Card title={t("panel.settings.sectionMood", { defaultValue: "情绪系统" })}>
      <div className="tm-derived">
        {t("panel.settings.sectionGlobalHint", { defaultValue: "以下设置对所有角色生效" })}
      </div>
      <TmSwitch
        checked={form.mood_enabled}
        label={t("panel.settings.moodEnabled", { defaultValue: "启用情绪系统（实验性）" })}
        onChange={(value: boolean) => updateForm({ mood_enabled: value })}
      />
      {form.mood_enabled ? (
        <Field className="tm-reserve-help" label={t("panel.settings.actionMinutes", { defaultValue: "限时情绪动作默认时长（分钟）" })}>
          <NumberInput value={form.default_action_minutes} min={1} max={720} step={1} onChange={(v: number | string) => updateForm({ default_action_minutes: typeof v === "number" ? v : 20 })} />
        </Field>
      ) : null}
    </Card>
    </>
  )
}

// 设置 · 语气感知（全局）：回复后异步分析互动情绪，只提醒不自动改状态。
// 槽位选择在「模型通道」卡；这张卡只管行为（启用/分析间隔/抽查频率/阶段灵敏度）。
function renderEmotionSenseSettings(props: EmotionSenseSettingsCardProps) {
  const { t, form, updateForm } = props

  const toneCheckRates = [
    { value: "1", label: t("panel.settings.toneCheckRateEvery", { defaultValue: "每轮" }) },
    { value: "0.5", label: t("panel.settings.toneCheckRateHalf", { defaultValue: "约一半" }) },
    { value: "0.25", label: t("panel.settings.toneCheckRateRare", { defaultValue: "偶尔" }) },
    { value: "0", label: t("panel.settings.toneCheckRateOff", { defaultValue: "关闭检查" }) },
  ]
  const toneSensitivities = [
    { value: "0.1", label: t("panel.settings.toneSensitivityGentle", { defaultValue: "温和" }) },
    { value: "0.15", label: t("panel.settings.toneSensitivityModerate", { defaultValue: "适中" }) },
    { value: "0.25", label: t("panel.settings.toneSensitivitySensitive", { defaultValue: "敏感" }) },
  ]

  return (
    <Card title={t("panel.settings.emotionSense", { defaultValue: "语气感知" })}>
      <div className="tm-derived">
        {t("panel.settings.sectionGlobalHint", { defaultValue: "以下设置对所有角色生效" })}
      </div>
      <TmSwitch
        checked={form.emotion_sense_enabled}
        label={t("panel.settings.emotionSenseEnabled", { defaultValue: "启用语气感知" })}
        onChange={(value: boolean) => updateForm({ emotion_sense_enabled: value })}
      />
      {form.emotion_sense_enabled ? (
        <>
          <div className="tm-derived">
            {t("panel.settings.emotionSenseHint", { defaultValue: "回复完成后在后台分析，只发送提醒，不自动改变情绪状态" })}
          </div>
          <Grid cols={2}>
            <Field className="tm-reserve-help" label={t("panel.settings.toneMinIntervalSec", { defaultValue: "分析间隔（秒）" })}>
              <NumberInput value={form.tone_min_interval_sec} min={10} max={3600} step={1} onChange={(v: number | string) => updateForm({ tone_min_interval_sec: typeof v === "number" ? v : 20 })} />
            </Field>
            <Field className="tm-reserve-help" label={t("panel.settings.toneCheckRate", { defaultValue: "语气检查频率" })}>
              <TmSelect label={t("panel.settings.toneCheckRate", { defaultValue: "语气检查频率" })} value={String(form.tone_check_rate)} options={toneCheckRates} onChange={(v: string) => updateForm({ tone_check_rate: Number(v) })} />
            </Field>
            {form.tone_phase_sensitivity_enabled ? (
              <Field className="tm-reserve-help" label={t("panel.settings.tonePhaseSensitivity", { defaultValue: "灵敏度调整幅度" })}>
                <TmSelect label={t("panel.settings.tonePhaseSensitivity", { defaultValue: "灵敏度调整幅度" })} value={String(form.tone_phase_sensitivity)} options={toneSensitivities} onChange={(v: string) => updateForm({ tone_phase_sensitivity: Number(v) })} />
              </Field>
            ) : null}
          </Grid>
          <TmSwitch
            checked={form.tone_phase_sensitivity_enabled}
            label={t("panel.settings.tonePhaseSensitivityEnabled", { defaultValue: "随阶段调整语气灵敏度" })}
            onChange={(value: boolean) => updateForm({ tone_phase_sensitivity_enabled: value })}
          />
        </>
      ) : null}
    </Card>
  )
}

// 全局模型通道：槽位选择模型，通道选择宿主管线或读取宿主配置直连。
// 状态灯反映实际通道与休眠原因，具体行为在各自功能卡配置。
// 自绘下拉直接保留宿主默认槽位的空串。
function renderChannelSettings(props: ChannelSettingsCardProps) {
  const { t, form, updateForm } = props

  // 槽位下拉：label = i18n 槽位显示名 + （拿到宿主配置时）· 当前模型名；后端失败时静态兜底
  const slotFallback = ["", "conversation", "summary", "correction", "emotion", "vision", "agent"]
  const allSlots = (Array.isArray(props.toneSlotOptions) && props.toneSlotOptions.length
    ? props.toneSlotOptions
    : slotFallback.map((value) => ({ value, model: "" }))
  ).map((opt) => {
    const value = String(opt.value || "")
    const name = t(`panel.settings.tone_slot_names.${value || "default"}`, { defaultValue: value || "default" })
    const model = String(opt.model || "").trim()
    return {
      value,
      label: model ? `${name} · ${model}` : name,
    }
  })
  // 碎片/成文的下拉不给空串与 emotion：空串档是"跟随宿主情感端点"（五分类专用，
  // 对这两条要自定义 prompt 的通道无意义），emotion 槽只由语气分析那张卡暴露
  if (!allSlots.some(opt => opt.value === MODE_GATEWAY)) allSlots.push({
    value: MODE_GATEWAY, label: t("panel.settings.gateway", { defaultValue: "插件模型 API" }),
  })
  const directSlots = allSlots.filter((opt) => opt.value !== "" && opt.value !== "emotion" && opt.value !== MODE_GATEWAY)
  const modeOptions = [
    { value: MODE_HOST, label: t("panel.settings.channelModeHost", { defaultValue: "通过宿主" }) },
    { value: MODE_CUSTOM, label: t("panel.settings.channelModeCustom", { defaultValue: "自定义直连" }) },
    { value: MODE_GATEWAY, label: t("panel.settings.gateway", { defaultValue: "插件模型 API" }) },
  ]

  const cs = props.channelStatus || {}
  const toneCh = cs.tone
  const fragCh = cs.fragments
  const reviewCh = cs.review

  return (
    <Card title={t("panel.settings.channels", { defaultValue: "模型通道" })}>
      <div className="tm-derived">
        {t("panel.settings.sectionGlobalHint", { defaultValue: "以下设置对所有角色生效" })}
      </div>

      {/* 语气分析：默认跟随宿主情感模型（经宿主端点调用） */}
      <ChannelRow
        t={t}
        label={t("panel.settings.channelTone", { defaultValue: "语气分析" })}
        hint={form.tone_slot === MODE_GATEWAY ? channelHint(t, MODE_GATEWAY) : t("panel.settings.channelToneHint", { defaultValue: "默认通过宿主调用情感模型；选择其他槽位时改为直连。互动文本可能发送给配置的模型服务。" })}
        light={channelLight(t, toneCh, form.emotion_sense_enabled)}
      >
        <TmSelect
          label={t("panel.settings.channelTone", { defaultValue: "语气分析" })}
          value={form.tone_slot}
          options={allSlots}
          onChange={(v: string) => updateForm({ tone_slot: v })}
        />
      </ChannelRow>

      <div className="tm-channel-divider" />

      {/* 碎片提取：默认复用宿主管线，可切自定义直连 */}
      <ChannelRow
        t={t}
        label={t("panel.settings.channelFragments", { defaultValue: "对话片段提取" })}
        hint={channelHint(t, form.fragments_mode)}
        light={channelLight(t, fragCh, form.fragments_enabled, form.fragments_mode || MODE_HOST)}
      >
        {form.fragments_mode !== MODE_GATEWAY ? <TmSelect label={t("panel.settings.channelFragments", { defaultValue: "对话片段提取" })} value={form.fragments_slot} options={directSlots} onChange={(v: string) => updateForm({ fragments_slot: v })} /> : null}
        <TmSelect
          label={`${t("panel.settings.channelFragments", { defaultValue: "对话片段提取" })} · ${t("panel.settings.channels", { defaultValue: "模型通道" })}`}
          value={form.fragments_mode || MODE_HOST}
          options={modeOptions}
          onChange={(v: any) => updateForm({ fragments_mode: String(v) })}
        />
      </ChannelRow>

      {/* 我的日记成文：与碎片提取同款通道 */}
      <ChannelRow
        t={t}
        label={t("panel.settings.channelReview", { defaultValue: "我的日记生成" })}
        hint={channelHint(t, form.review_mode)}
        light={channelLight(t, reviewCh, form.review_enabled, form.review_mode || MODE_HOST)}
      >
        {form.review_mode !== MODE_GATEWAY ? <TmSelect label={t("panel.settings.channelReview", { defaultValue: "我的日记生成" })} value={form.review_slot} options={directSlots} onChange={(v: string) => updateForm({ review_slot: v })} /> : null}
        <TmSelect
          label={`${t("panel.settings.channelReview", { defaultValue: "我的日记生成" })} · ${t("panel.settings.channels", { defaultValue: "模型通道" })}`}
          value={form.review_mode || MODE_HOST}
          options={modeOptions}
          onChange={(v: any) => updateForm({ review_mode: String(v) })}
        />
      </ChannelRow>

      <div className="tm-channel-divider" />

      {/* agent 档节流（1.3.3 修订轮）：碎片与成文只要走 agent 槽就合记一份当日计数
          （按角色分账），用完休眠到次日。这里给的是全局预算旋钮 + 当前角色的已用读数；
          300 秒间隔地板刻意不开放配置（它防的是自动节拍砸配额，用户没有调它的理由），
          只在说明里讲清"还有一道在代码里"。5/150/100 三个字面量与后端同值，
          由 test_ui_budget_input_range_matches_backend_bounds / 出厂值同源门钉住 */}
      <div className="tm-derived">
        {t("panel.settings.agentBudgetHelp", { defaultValue: "对话片段和我的日记使用 agent 模型时，共享此上限，按角色分别计数；用完后次日恢复。默认 100 次，可设为 5～150 次。调用间隔至少 300 秒，宿主服务还可能有额外额度限制。" })}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span>{t("panel.settings.agentBudget", { defaultValue: "agent 模型每日调用上限" })}</span>
        <NumberInput
          value={form.agent_daily_budget}
          min={5}
          max={150}
          step={1}
          onChange={(v: number | string) => updateForm({ agent_daily_budget: typeof v === "number" ? v : 100 })}
        />
        <span>
          {t("panel.settings.agentBudgetUsed", {
            defaultValue: "今日已用 {used}/{budget} 次",
            used: String(props.agentUsage?.used ?? 0),
            budget: String(props.agentUsage?.budget ?? form.agent_daily_budget),
          })}
        </span>
      </div>

      {/* 免费路由说明只在"直连这条路确实因为免费路由而不通"时说：自定义模式选了
          免费路由，或宿主模式回落到直连后仍拼不出端点——其余状态各灯自己解释 */}
      {isFreeRoute(fragCh) || isFreeRoute(reviewCh) ? (
        <div className="tm-channel-warn">
          {t("panel.settings.freeRouteWarn", { defaultValue: "免费路由不支持自定义直连。可选择通过宿主使用 agent 模型（受宿主调用额度限制），或在宿主中配置自己的模型服务。" })}
        </div>
      ) : null}
    </Card>
  )
}

// 设置 · 日记功能行为（全局）：碎片捕获与我的日记的开关/门槛（放在日记页，
// 与浏览同页）。槽位选择统一在「情绪」页的模型通道卡。
function renderDiarySettings(props: DiarySettingsCardProps) {
  const { t, form, updateForm } = props

  return (
    <Card title={t("panel.settings.diary", { defaultValue: "时光日记（对话片段）" })}>
      <div className="tm-derived">
        {t("panel.settings.sectionGlobalHint", { defaultValue: "以下设置对所有角色生效" })}
      </div>

      {/* 时光日记 · 自动碎片 */}
      <TmSwitch
        checked={form.fragments_enabled}
        label={t("panel.settings.fragmentsEnabled", { defaultValue: "自动保存喜好和重要表达" })}
        onChange={(value: boolean) => updateForm({ fragments_enabled: value })}
      />
      {form.fragments_enabled ? (
        <>
          <div className="tm-derived">
            {t("panel.settings.fragmentsHint", { defaultValue: "用户消息会交给配置的模型分析，片段保存在本地，供角色检索。模型可能遗漏或误判，可在时光日记中查看和删除。" })}
          </div>
          {/* 碎片日限（1.5.0）：这条闸保的是"你自己的花费"——槽位切到付费模型后，
              agent 日上限与 300 秒间隔地板双双失效，就只剩它管"一天总共几次"。
              0 是合法值（= 今天不分析）；上下界与后端 _FRAGMENT_MIN/MAX_DAILY_LIMIT
              同源，由 test_ui_fragments_limit_range_matches_backend_bounds 钉住 */}
          <Field
            className="tm-reserve-help"
            label={t("panel.settings.fragmentsDailyLimit", { defaultValue: "每天最多分析次数" })}
            help={t("panel.settings.fragmentsDailyLimitHelp", { defaultValue: "设 0 表示今天不分析（等于暂停自动保存，已存片段仍可检索）。用付费模型时可调低以控制花费。" })}
          >
            <NumberInput
              value={form.fragments_daily_limit}
              min={0}
              max={500}
              step={1}
              onChange={(v: number | string) => updateForm({ fragments_daily_limit: typeof v === "number" ? v : 60 })}
            />
          </Field>
        </>
      ) : null}

      <div className="tm-review-settings">
        <div className="tm-subcard-title">{t("panel.settings.stats", { defaultValue: "相处统计（时光页）" })}</div>
        <TmSwitch
          checked={form.anniversary_inject}
          label={t("settings.anniversary.title", { defaultValue: "纪念日提醒" })}
          onChange={(value: boolean) => updateForm({ anniversary_inject: value })}
        />
        <div className="tm-derived">
          {t("settings.anniversary.desc", { defaultValue: "到达 30、60 等相伴纪念节点时提醒角色，是否在聊天中提起由角色决定。" })}
        </div>
      </div>

      <div className="tm-review-settings">
        <div className="tm-subcard-title">{t("panel.settings.review", { defaultValue: "我的日记（相处记录）" })}</div>
        <TmSwitch
          checked={form.review_enabled}
          label={t("panel.settings.reviewEnabled", { defaultValue: "定期生成近期相处记录" })}
          onChange={(value: boolean) => updateForm({ review_enabled: value })}
        />
        {form.review_enabled ? (
          <>
            <div className="tm-derived">
              {t("panel.settings.reviewHint", { defaultValue: "互动素材会交给配置的模型整理，结果可能有偏差，仅供回顾。记录不自动加入角色对话或宿主记忆，也不提供角色读取工具。" })}
            </div>
            <Field
              className="tm-reserve-help"
              label={t("panel.settings.review_turns", { defaultValue: "生成条件：互动轮数" })}
              help={t("panel.settings.review_turns_help", { defaultValue: "达到互动轮数或天数条件之一即可生成" })}
            >
              <NumberInput value={form.review_turns_threshold} min={10} max={500} step={1} onChange={(v: number | string) => updateForm({ review_turns_threshold: typeof v === "number" ? v : 50 })} />
            </Field>
            <Field
              className="tm-reserve-help"
              label={t("panel.settings.review_days", { defaultValue: "生成条件：累计天数" })}
              help={t("panel.settings.review_days_help", { defaultValue: "达到设定天数且期间有聊天时生成；无互动时不生成" })}
            >
              <NumberInput value={form.review_days_threshold} min={1} max={90} step={1} onChange={(v: number | string) => updateForm({ review_days_threshold: typeof v === "number" ? v : 7 })} />
            </Field>
          </>
        ) : null}
      </div>
    </Card>
  )
}

// ---- 内部辅助 ----

function MoodExperience(props: {
  t: TFunc; mood: Mood; enabled: boolean; canEnd: boolean; ending: boolean
  onEnd: () => void
}) {
  const { t, mood, enabled, canEnd, ending, onEnd } = props
  const systemOn = enabled && mood.system_enabled !== false
  const active = systemOn && !!mood.active
  const events = Array.isArray(mood.history) ? mood.history : []
  const recent = events.slice(0, 5)
  const earlier = events.slice(5)
  const v = Math.max(-1, Math.min(1, Number(mood.affect?.valence) || 0))
  const a = Math.max(0, Math.min(1, Number(mood.affect?.arousal) || 0))
  const label = active ? actionName(mood.action || "", t) : t("panel.mood.noChoice", { defaultValue: "暂无生效的工具选择" })
  const word = systemOn ? t(moodWordOf(v, a), { defaultValue: "平静" }) : "—"
  const remaining = active && mood.expires_at
    ? t("panel.mood.recordUntil", { time: eventTime(mood.expires_at), defaultValue: "记录有效至 {time}" }) : ""
  return (
    <>
      <Card title={t("panel.mood.currentChoice", { defaultValue: "当前选择" })}>
        <div className="tm-mood-current" aria-live="polite">
          <div className="tm-mood-choice">
            <span className={active ? "tm-mood-choice-dot tm-mood-choice-dot-active" : "tm-mood-choice-dot"} />
            <strong>{systemOn ? label : t("panel.off", { defaultValue: "已关闭" })}</strong>
            {active ? <span className="tm-mood-source">{sourceName(mood.origin || "", t)}</span> : null}
          </div>
          {remaining ? <div className="tm-derived">{remaining}</div> : null}
        </div>
        {active && mood.reason ? (
          <details className="tm-mood-reason">
            <summary>{t("panel.mood.recordedReason", { defaultValue: "记录的原因" })}</summary>
            <p>{mood.reason}</p>
          </details>
        ) : null}
        <div className="tm-mood-observation">
          <div className="tm-mood-observation-title">
            <span>{t("panel.mood.observation", { defaultValue: "心情观察" })}</span>
            <span style={{ color: moodDotColor(systemOn ? v : 0) }}>{word}</span>
          </div>
          <div className="tm-mood-observation-bars">
            <ObservationBar label={t("panel.mood.gauge.valence", { defaultValue: "愉悦度" })}
              score={systemOn ? valenceScore(v) : null} color={valenceBarColor(v)} />
            <ObservationBar label={t("panel.mood.gauge.arousal", { defaultValue: "活跃度" })}
              score={systemOn ? arousalScore(a) : null} color={arousalColor(a)} />
          </div>
        </div>
        {active && canEnd ? (
          <div className="tm-mood-actions">
            <Button disabled={ending} onClick={onEnd}>{t("actions.liftMood.label", { defaultValue: "结束当前状态" })}</Button>
          </div>
        ) : null}
      </Card>
      <Card title={t("panel.mood.historyTitle", { defaultValue: "最近变化" })}>
        {events.length ? (
          <>
            <ol className="tm-mood-history">
              {recent.map((event, i) => <EventRow key={`${event.ts}:${i}`} event={event} t={t} />)}
            </ol>
            {earlier.length ? (
              <details className="tm-mood-earlier">
                <summary>{t("panel.mood.historyMore", { n: earlier.length, defaultValue: "更早的记录 · {n} 条" })}</summary>
                <ol className="tm-mood-history">
                  {earlier.map((event, i) => <EventRow key={`${event.ts}:${i}`} event={event} t={t} />)}
                </ol>
              </details>
            ) : null}
          </>
        ) : <div className="tm-derived tm-mood-empty">{t("panel.mood.historyEmpty", { defaultValue: "还没有情绪工具变化记录" })}</div>}
      </Card>
    </>
  )
}

function ObservationBar(props: { label: string; score: number | null; color: string }) {
  return (
    <div className="tm-mood-observation-bar">
      <span>{props.label}</span>
      <div className="tm-mood-observation-track" aria-hidden="true">
        <div style={{ width: `${props.score === null ? 0 : props.score}%`, background: props.color }} />
      </div>
      <span className="tm-mood-observation-value">{props.score === null ? "—" : props.score}</span>
    </div>
  )
}

function EventRow(props: { key?: string; event: MoodEvent; t: TFunc }) {
  const { event, t } = props
  const action = actionName(event.action, t)
  const title = event.kind === "switch"
    ? t("panel.mood.eventSwitch", { previous: actionName(event.previous_action || "", t), action, defaultValue: "{previous} → {action}" })
    : event.kind === "release"
      ? t("panel.mood.eventRelease", { action, defaultValue: "结束了「{action}」" })
      : event.kind === "expire"
        ? t("panel.mood.eventExpire", { action, defaultValue: "「{action}」记录到期" })
        : t("panel.mood.eventChoose", { action, defaultValue: "选择了「{action}」" })
  return (
    <li className="tm-mood-event">
      <time>{eventTime(event.ts)}</time>
      <div className="tm-mood-event-body">
        <div>{title}</div>
        <span className="tm-mood-source">{sourceName(event.origin, t)}</span>
        {event.reason ? (
          <details className="tm-mood-reason">
            <summary>{t("panel.mood.recordedReason", { defaultValue: "记录的原因" })}</summary>
            <p>{event.reason}</p>
          </details>
        ) : null}
      </div>
    </li>
  )
}

function sourceName(origin: string, t: TFunc): string {
  if (origin === "self") return t("panel.mood.sourceSelf", { defaultValue: "角色自主选择" })
  if (origin === "user") return t("panel.mood.sourceUser", { defaultValue: "用户明确要求" })
  if (origin === "timer") return t("panel.mood.sourceTimer", { defaultValue: "记录到期" })
  return t("panel.mood.sourceUnknown", { defaultValue: "来源未记录" })
}

function actionName(action: string, t: TFunc): string {
  return stripEmoji(t(`mood.${action}`, { defaultValue: action }))
}

function eventTime(ts: number): string {
  const date = new Date(ts * 1000)
  if (!Number.isFinite(date.getTime())) return "—"
  return date.toLocaleString(undefined, {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  })
}

// 通道说明文案：两种模式的代价/收益不同，说清各自那一句
function channelHint(t: TFunc, mode: string | undefined): string {
  if (mode === MODE_GATEWAY) return t("panel.settings.gatewayHint", { defaultValue: "在宿主插件详情中绑定对应模型用途。不自动改用其他通道；计入本插件每日上限，片段调用间隔至少 300 秒。" })
  return (mode || MODE_HOST) === MODE_CUSTOM
    ? t("panel.settings.channelHintCustom", { defaultValue: "读取宿主本地模型配置，直接调用所选服务。未配置模型或使用免费路由时，直连功能不可用。" })
    : t("panel.settings.channelHintHost", { defaultValue: "通过宿主模型通道调用，默认使用 agent 槽位。可用性取决于宿主配置和服务权限；通道不可用时可能尝试直连。" })
}

// 通道行：名称 + 状态灯 + 说明 + 槽位/通道下拉
function ChannelRow(props: { t: TFunc; label: string; hint: string; light: { cls: string; text: string }; children?: any }) {
  const { label, hint, light, children } = props
  return (
    <div className="tm-channel-row">
      <div className="tm-channel-head">
        <span className="tm-channel-label">{label}</span>
        <span className={`tm-channel-light ${light.cls}`} title={light.text}>{light.text}</span>
      </div>
      <div className="tm-derived">{hint}</div>
      {children ? <div className="tm-channel-control">{children}</div> : null}
    </div>
  )
}

// 通道 → 状态灯（cls 控配色，text 是一句话状态）。mode = 这条通道用户选的走法：
// 只有"选了宿主管线却实际落在直连上"才是一次该如实说的回落。语气分析没有 mode
// 旋钮（槽位留空走宿主端点、选别的槽本就是插件直连），调用方不传 mode 即不参与该判定。
function channelLight(
  t: TFunc,
  ch: ChannelStatusItem | undefined,
  featureOn: boolean,
  mode?: string,
): { cls: string; text: string } {
  if (!featureOn) {
    return { cls: "tm-light-off", text: t("panel.channel.off", { defaultValue: "未启用" }) }
  }
  if (!ch) return { cls: "tm-light-ok", text: t("panel.channel.ok", { defaultValue: "正常" }) }
  if (ch.dormant_reason === "free_route") {
    return { cls: "tm-light-dormant", text: t("panel.channel.freeRoute", { defaultValue: "免费路由不支持直连" }) }
  }
  if (ch.dormant_reason === "no_model") {
    return { cls: "tm-light-dormant", text: t("panel.channel.noModel", { defaultValue: "未配置模型" }) }
  }
  if (ch.dormant_reason === "unverified") {
    return { cls: "tm-light-dormant", text: t("panel.channel.unverified", { defaultValue: "等待首次调用验证" }) }
  }
  // 端点解析得到、真发出去却被服务端连着拒 → 已熔断（不再发请求）。这一档必须单独
  // 有灯：1.3.3 实机就是"解析成功=绿灯 + 15 次静默失败"，用户看不出任何异常
  if (ch.dormant_reason === "rejected") {
    return { cls: "tm-light-dormant", text: t("panel.channel.rejected", { defaultValue: "请求被拒绝 · 通道已暂停" }) }
  }
  // 当日 agent 档预算用完：这是我们自己按下不发（不是故障），说明与"改路"无关，
  // 所以不和 rejected 共用文案，免得用户以为服务端把他拒了
  if (ch.dormant_reason === "budget") {
    return { cls: "tm-light-dormant", text: t("panel.channel.budget", { defaultValue: "今日额度已用完 · 次日恢复" }) }
  }
  if (ch.dormant_reason === "disabled") {
    return { cls: "tm-light-off", text: t("panel.channel.off", { defaultValue: "未启用" }) }
  }
  // 选的是宿主通道却实际在直连（宿主模块没给到端点）：能干活，但不是用户选的那条路，
  // 如实说——否则"正常"灯会藏住一次静默回落。反之 mode=custom 走 direct 是用户自己
  // 选的，报"回落"就等于把一次正常配置说成故障，所以这里必须带上 mode 判据。
  if (mode === MODE_HOST && ch.transport === "direct") {
    return { cls: "tm-light-dormant", text: t("panel.channel.fellBackDirect", { defaultValue: "宿主通道不可用 · 已改用直连" }) }
  }
  return { cls: "tm-light-ok", text: t("panel.channel.ok", { defaultValue: "正常" }) }
}

// 这条通道此刻是不是"直连被免费路由挡住"（免费路由警告只在这种状态下才说得出道理）
function isFreeRoute(ch: ChannelStatusItem | undefined): boolean {
  return !!ch && ch.dormant_reason === "free_route"
}
