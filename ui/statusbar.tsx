// 顶部状态条（精简版）：她是谁 · 今天状态一句话 · 心情胶囊 · 总开关。
// 详细状态（月相环/天数/情绪详情）都在「总览」页——点击状态条任意空白跳转总览。
// hosted-tsx 约束：唯一 export 在任何 JSX 闭合标签之前；辅助组件放文件尾部靠函数声明提升
import { Button, StatusBadge, Tooltip } from "@neko/plugin-ui"
import type { Mood, Status, TFunc } from "./types"
import { moodBadgeTone, moodDotColor, moodWordOf, stripEmoji, valenceScore, arousalScore, phaseColorOf } from "./utils"

type StatusBarProps = {
  t: TFunc
  status: Status
  mood: Mood
  lanlan?: string
  canToggle: boolean
  onToggle: () => void
  onGotoOverview: () => void
}

export function StatusBar(props: StatusBarProps) {
  const { t, status, mood, lanlan, canToggle, onToggle, onGotoOverview } = props

  const enabled = status.enabled !== false
  const phaseColor = phaseColorOf(status)
  // 一句话状态：开启时 = 阶段名 + 周期第 N 天；关闭时只有"已关闭"
  const summary = enabled
    ? `${status.phase_label || "-"} · ${t("panel.ring.cycleDay", { defaultValue: "周期第" })} ${status.cycle_day ?? "-"} ${t("panel.days", { defaultValue: "天" })}`
    : t("panel.off", { defaultValue: "已关闭" })

  return (
    <div className="tm-statusbar tm-statusbar-slim">
      <button type="button" className="tm-status-main" onClick={onGotoOverview} title={t("panel.overview.gotoTip", { defaultValue: "点击查看总览" })}>
        <span className="tm-status-dot" style={{ background: phaseColor }} />
        {lanlan ? <span className="tm-status-name">{lanlan}</span> : null}
        <span className="tm-status-summary" style={{ color: enabled ? phaseColor : undefined }}>{summary}</span>
      </button>
      <div className="tm-status-right">
        {enabled && mood.system_enabled !== false && mood.affect ? (
          <MoodPill t={t} valence={mood.affect.valence} arousal={mood.affect.arousal} />
        ) : null}
        {enabled && mood.system_enabled !== false && mood.active ? (
          mood.reason ? (
            <Tooltip content={mood.reason} placement="bottom">
              <StatusBadge tone={moodBadgeTone(mood.action)} label={stripEmoji(mood.action_label) || mood.action || ""} />
            </Tooltip>
          ) : (
            <StatusBadge tone={moodBadgeTone(mood.action)} label={stripEmoji(mood.action_label) || mood.action || ""} />
          )
        ) : null}
        <Button tone={enabled ? "default" : "primary"} disabled={!canToggle} onClick={onToggle}>
          {enabled ? t("panel.turnOff", { defaultValue: "关闭模拟" }) : t("panel.turnOn", { defaultValue: "开启模拟" })}
        </Button>
      </div>
    </div>
  )
}

// 连续心情胶囊：心情词 + 底色随 valence + arousal 呼吸动画（从旧状态栏原样保留——
// 它是顶栏唯一"活的"信号，也是陪伴感的常驻提示）
function MoodPill(props: { key?: string; t: TFunc; valence: number; arousal: number }) {
  const { t, valence, arousal } = props
  const v = Math.max(-1, Math.min(1, Number(valence) || 0))
  const a = Math.max(0, Math.min(1, Number(arousal) || 0))
  const duration = `${(3.4 - a * 2.2).toFixed(2)}s`
  const haloSize = Math.round(16 + a * 12)
  const word = t(moodWordOf(v, a), { defaultValue: "平静" })
  const title = `${word} · ${t("panel.mood.gauge.valence", { defaultValue: "愉悦度" })} ${valenceScore(v)} · ${t("panel.mood.gauge.arousal", { defaultValue: "活跃度" })} ${arousalScore(a)}`
  return (
    <span className="tm-mood-pill" title={title} style={{ background: moodDotColor(v) }}>
      <span className="tm-mood-pill-word">{word}</span>
      <span
        className="tm-mood-pill-halo"
        style={{ width: `${haloSize}px`, height: `${haloSize}px`, animationDuration: duration }}
      />
    </span>
  )
}
