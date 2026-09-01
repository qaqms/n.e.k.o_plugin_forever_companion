// 时光页（1.1.0）· 相处统计：相处里程碑（徽章墙 + 数字摘要）
// + 相处热力图（近 12 个月，悬停看当日互动与她的心情）
// + 我们的一月（月报，可翻历史月份）。
// hosted-tsx 约束：唯一 export 排在任何 JSX 闭合标签之前；辅助组件放文件尾部靠函数声明提升
import { Card, EmptyState, StatusBadge, Tooltip } from "@neko/plugin-ui"
import type { Heatmap, MonthReport, StatsBadge, StatsSummary, TFunc } from "./types"
import { heatDayMoodKey, heatLevel, monthLabel, moodDotColor, toneLabelKey } from "./utils"

export function MomentPane(props: {
  t: TFunc
  lanlan?: string
  summary?: StatsSummary
  badges?: StatsBadge[]
  heatmap: Heatmap | null
  month: MonthReport | null
  monthAvailable: string[]
  monthLoading: boolean
  onPickMonth: (month: string) => void
}) {
  const { t, lanlan, summary, badges, heatmap, month, monthAvailable, monthLoading, onPickMonth } = props
  const days = (summary && summary.days_together) || 0

  if (days <= 0 && (!summary || !summary.total_turns)) {
    return (
      <div className="tm-pane">
        <Card title={t("panel.stats.title", { defaultValue: "我们的时光" })}>
          <EmptyState
            title={t("panel.stats.empty", { defaultValue: "还没有相处记录" })}
            description={t("panel.stats.emptySub", { defaultValue: "和她聊聊天，你们的第一天就从现在开始。" })}
          />
        </Card>
      </div>
    )
  }

  return (
    <div className="tm-pane">
      {/* ---- 相处里程碑：数字摘要 + 徽章墙 ---- */}
      <Card title={t("panel.stats.milestones", { defaultValue: "相处里程碑" })}>
        <SummaryStrip t={t} summary={summary} lanlan={lanlan} />
        <BadgeWall t={t} badges={badges} />
      </Card>

      {/* ---- 相处热力图 ---- */}
      <Card title={t("panel.stats.heatmap", { defaultValue: "相处热力图" })}>
        <HeatGrid t={t} heatmap={heatmap} />
      </Card>

      {/* ---- 我们的一月 ---- */}
      <Card title={t("panel.stats.monthReport", { defaultValue: "我们的一月" })}>
        <MonthNav
          t={t}
          month={month}
          monthAvailable={monthAvailable}
          monthLoading={monthLoading}
          onPickMonth={onPickMonth}
        />
        <MonthReportView t={t} month={month} />
      </Card>
    </div>
  )
}

// 数字摘要条：相伴天数/互动轮数/连续天数/冷战与和好/开心时刻
function SummaryStrip(props: { t: TFunc; summary?: StatsSummary; lanlan?: string }) {
  const { t, summary, lanlan } = props
  const s = summary || {}
  const items = [
    {
      key: "days",
      value: String(s.days_together ?? 0),
      label: t("panel.stats.sum.days", { defaultValue: "相伴天数" }),
      hint: lanlan
        ? t("panel.stats.sum.daysHint", { defaultValue: "自你们的第一句互动起算（跟随 {n}）" }).replace("{n}", String(lanlan))
        : t("panel.stats.sum.daysHintPlain", { defaultValue: "自你们的第一句互动起算" }),
    },
    {
      key: "turns",
      value: String(s.total_turns ?? 0),
      label: t("panel.stats.sum.turns", { defaultValue: "互动轮数" }),
      hint: t("panel.stats.sum.turnsHint", { defaultValue: "你发给她的消息总数" }),
    },
    {
      key: "streak",
      value: String(s.current_streak ?? 0),
      label: t("panel.stats.sum.streak", { defaultValue: "当前连续" }),
      hint: t("panel.stats.sum.streakHint", { defaultValue: "最长连续 {n} 天" }).replace("{n}", String(s.longest_streak ?? 0)),
    },
    {
      key: "fight",
      value: t("panel.stats.sum.fightValue", { defaultValue: "{c} / {m}" })
        .replace("{c}", String(s.cold_wars ?? 0))
        .replace("{m}", String(s.made_ups ?? 0)),
      label: t("panel.stats.sum.fight", { defaultValue: "冷战 / 和好" }),
      hint: t("panel.stats.sum.fightHint", { defaultValue: "只数她自己起的情绪；和好 = 她主动转晴" }),
    },
    {
      key: "warm",
      value: String(s.warm_moments ?? 0),
      label: t("panel.stats.sum.warm", { defaultValue: "开心时刻" }),
      hint: t("panel.stats.sum.warmHint", { defaultValue: "她自己起的暖流与满潮" }),
    },
    {
      key: "next",
      value: String(s.next_anniversary_in ?? 0),
      label: t("panel.stats.sum.next", { defaultValue: "距纪念日" }),
      hint: t("panel.stats.sum.nextHint", { defaultValue: "满 30/100/… 天的日子，她当天会知道" }),
    },
  ]
  return (
    <div className="tm-stat-strip">
      {items.map((item) => (
        <Tooltip key={item.key} content={item.hint} placement="bottom">
          <div className="tm-stat-cell">
            <span className="tm-stat-value">{item.value}</span>
            <span className="tm-stat-label">{item.label}</span>
          </div>
        </Tooltip>
      ))}
    </div>
  )
}

// 徽章墙：天数徽章 + 第一次徽章；未解锁灰显（占位形成"还差 X 天"的期待感）
function BadgeWall(props: { t: TFunc; badges?: StatsBadge[] }) {
  const { t, badges } = props
  const list = badges || []
  if (!list.length) return null
  return (
    <div className="tm-badge-wall">
      {list.map((badge) => {
        const unlocked = !!badge.unlocked
        const label = badgeLabel(t, badge)
        const sub = unlocked
          ? String(badge.date || "")
          : (badge.days
              ? t("panel.stats.badge.inDays", { defaultValue: "还差 {n} 天" }).replace("{n}", String(badge.days))
              : t("panel.stats.badge.locked", { defaultValue: "还未发生" }))
        return (
          <div key={badge.id || label} className={`tm-badge ${unlocked ? "tm-badge-on" : ""}`}>
            <span className={`tm-badge-medal tm-badge-lv-${unlocked ? "on" : "off"}`}>{unlocked ? "✦" : "·"}</span>
            <span className="tm-badge-name">{label}</span>
            <span className="tm-badge-date">{sub}</span>
          </div>
        )
      })}
    </div>
  )
}

// 徽章 id → 展示文案（天数类带数字）
function badgeLabel(t: TFunc, badge: StatsBadge): string {
  const id = String(badge.id || "")
  if (badge.days) {
    return t("panel.stats.badge.days", { defaultValue: "相伴 {n} 天" }).replace("{n}", String(badge.days))
  }
  const map: Record<string, string> = {
    first_diary: t("panel.stats.badge.firstDiary", { defaultValue: "第一篇手记" }),
    first_journal: t("panel.stats.badge.firstJournal", { defaultValue: "第一页日记" }),
    first_review: t("panel.stats.badge.firstReview", { defaultValue: "第一篇我的日记" }),
  }
  return map[id] || id
}

// 热力图：近 12 个月逐日格子（列=周，GitHub 式横向布局用 CSS 网格实现）。
// hosted-tsx 无 SVG：格子用 div + 档位色；悬停 Tooltip 显示当日明细
function HeatGrid(props: { t: TFunc; heatmap: Heatmap | null }) {
  const { t, heatmap } = props
  const days = (heatmap && heatmap.days) || []
  if (!days.length) {
    return (
      <EmptyState
        title={t("panel.stats.heatEmpty", { defaultValue: "还没有可展示的日子" })}
        description={t("panel.stats.heatEmptySub", { defaultValue: "互动过的日子会在这里亮起来。" })}
      />
    )
  }
  const byDate: Record<string, typeof days[number]> = {}
  days.forEach((day) => {
    if (day && day.date) byDate[String(day.date)] = day
  })
  // 布局：按月分块横向排（12 个月一行放不下时自动换行），每块内 7 列周网格
  const months: Record<string, string[]> = {}
  days.forEach((day) => {
    const date = String((day && day.date) || "")
    if (date.length < 7) return
    const month = date.slice(0, 7)
    if (!months[month]) months[month] = []
    months[month].push(date)
  })
  const monthKeys = Object.keys(months).sort()
  const today = days.length ? String(days[days.length - 1].date) : ""
  return (
    <div>
      <div className="tm-heat-legend">
        <span className="tm-heat-legend-label">{t("panel.stats.heatLess", { defaultValue: "少" })}</span>
        {[0, 1, 2, 3, 4].map((lv) => (
          <span key={lv} className={`tm-heat-cell tm-heat-lv${lv}`} />
        ))}
        <span className="tm-heat-legend-label">{t("panel.stats.heatMore", { defaultValue: "多" })}</span>
      </div>
      <div className="tm-heat-scroll">
        <div className="tm-heat-wrap">
          {monthKeys.map((month) => (
            <div key={month} className="tm-heat-month">
              <div className="tm-heat-month-label">{monthLabel(t, month)}</div>
              <div className="tm-heat-grid">
                {months[month].map((date) => {
                  const day = byDate[date]
                  const lv = heatLevel(day ? day.turns : 0)
                  const isToday = date === today
                  const moodKey = day ? heatDayMoodKey(day) : ""
                  const moodWord = moodKey ? t(moodKey, { defaultValue: "" }) : ""
                  const tip = [
                    date,
                    t("panel.stats.heatTipTurns", { defaultValue: "互动 {n} 轮" }).replace("{n}", String((day && day.turns) || 0)),
                    moodWord ? t("panel.stats.heatTipMood", { defaultValue: "她那天：{m}" }).replace("{m}", moodWord) : "",
                  ].filter(Boolean).join(" · ")
                  return (
                    <Tooltip key={date} content={tip} placement="top">
                      <span
                        className={`tm-heat-cell tm-heat-lv${lv} ${isToday ? "tm-heat-today" : ""} ${moodWord ? "" : "tm-heat-muted"}`}
                      />
                    </Tooltip>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="tm-heat-note">{t("panel.stats.heatNote", { defaultValue: "颜色深浅 = 当天互动轮数；悬停查看她那天的心情" })}</div>
    </div>
  )
}

// 月报导航：左右翻月 + 月份下拉（历史封卷月固定，当月实时）
function MonthNav(props: {
  t: TFunc
  month?: MonthReport | null
  monthAvailable: string[]
  monthLoading: boolean
  onPickMonth: (month: string) => void
}) {
  const { t, month, monthAvailable, monthLoading, onPickMonth } = props
  const list = monthAvailable || []
  const current = String((month && month.month) || "")
  const idx = list.indexOf(current)
  const prev = idx > 0 ? list[idx - 1] : ""
  const next = idx >= 0 && idx < list.length - 1 ? list[idx + 1] : ""
  return (
    <div className="tm-month-nav">
      <button
        type="button"
        className="tm-month-btn"
        disabled={!prev}
        onClick={() => prev && onPickMonth(prev)}
      >
        ‹
      </button>
      <span className="tm-month-label">
        {current ? monthLabel(t, current) : t("panel.stats.monthNone", { defaultValue: "还没有月份" })}
        {month && month.sealed === false ? (
          <StatusBadge tone="info" label={t("panel.stats.monthLive", { defaultValue: "进行中" })} />
        ) : null}
        {monthLoading ? <span className="tm-month-loading">…</span> : null}
      </span>
      <button
        type="button"
        className="tm-month-btn"
        disabled={!next}
        onClick={() => next && onPickMonth(next)}
      >
        ›
      </button>
    </div>
  )
}

// 月报正文：数字网格 + 语气主色 + 本月声音（她当月写过的最长一条手记）
function MonthReportView(props: { t: TFunc; month?: MonthReport | null }) {
  const { t, month } = props
  if (!month || !month.month) {
    return (
      <EmptyState
        title={t("panel.stats.monthEmpty", { defaultValue: "这个月还没有记录" })}
        description={t("panel.stats.monthEmptySub", { defaultValue: "等这个月过完，这里会为你们留一份小结。" })}
      />
    )
  }
  const m = month
  const toneEntries = Object.entries(m.tone || {}).slice(0, 3)
  const valence = m.valence_avg === null || m.valence_avg === undefined ? null : Number(m.valence_avg)
  const valenceWord = valence === null
    ? t("panel.journal.trend.unknown", { defaultValue: "暂无" })
    : t(valence > 0.2 ? "panel.journal.trend.warm" : valence >= -0.2 ? "panel.journal.trend.calm" : "panel.journal.trend.cold", { defaultValue: "" })
  return (
    <div className="tm-month-report">
      <div className="tm-month-grid">
        <MonthCell
          label={t("panel.stats.month.turns", { defaultValue: "本月互动" })}
          value={t("panel.stats.month.turnsValue", { defaultValue: "{n} 轮" }).replace("{n}", String(m.turns || 0))}
        />
        <MonthCell
          label={t("panel.stats.month.activeDays", { defaultValue: "活跃天数" })}
          value={t("panel.stats.month.daysValue", { defaultValue: "{n} 天" }).replace("{n}", String(m.active_days || 0))}
        />
        <MonthCell
          label={t("panel.stats.month.busiest", { defaultValue: "最热闹的一天" })}
          value={m.busiest_day
            ? t("panel.stats.month.busiestValue", { defaultValue: "{d}（{n} 轮）" })
                .replace("{d}", String(m.busiest_day).slice(5))
                .replace("{n}", String(m.busiest_turns || 0))
            : "-"}
        />
        <MonthCell
          label={t("panel.stats.month.streak", { defaultValue: "最长连续" })}
          value={t("panel.stats.month.daysValue", { defaultValue: "{n} 天" }).replace("{n}", String(m.longest_streak || 0))}
        />
        <MonthCell
          label={t("panel.stats.month.fight", { defaultValue: "冷战 / 和好" })}
          value={t("panel.stats.month.fightValue", { defaultValue: "{c} / {m}" })
            .replace("{c}", String(m.cold_wars || 0))
            .replace("{m}", String(m.made_ups || 0))}
        />
        <MonthCell
          label={t("panel.stats.month.warm", { defaultValue: "开心时刻" })}
          value={t("panel.stats.month.daysValue", { defaultValue: "{n} 天" }).replace("{n}", String(m.warm_moments || 0))}
        />
      </div>

      {/* 语气主色：她这个月回复的整体色调 */}
      {toneEntries.length ? (
        <div className="tm-month-tone">
          <span className="tm-month-tone-label">{t("panel.stats.month.toneLabel", { defaultValue: "她的语气" })}</span>
          {toneEntries.map(([label, count]) => (
            <span key={label} className="tm-month-tone-item">
              {t(toneLabelKey(label) || "panel.stats.tone.neutral", { defaultValue: label })}
              <span className="tm-month-tone-count">×{count}</span>
            </span>
          ))}
          {valence !== null ? (
            <span className="tm-month-tone-item">
              <span className="tm-month-tone-dot" style={{ background: moodDotColor(valence) }} />
              {valenceWord}
            </span>
          ) : null}
        </div>
      ) : null}

      {/* 本月声音：她当月写过的最长一条手记（原话摘录，不改写） */}
      {m.voice && m.voice.entry ? (
        <div className="tm-month-voice">
          <div className="tm-month-voice-label">
            {t("panel.stats.month.voiceLabel", { defaultValue: "这个月她写下的一句话" })}
            {m.voice.mood ? <StatusBadge tone="default" label={String(m.voice.mood)} /> : null}
          </div>
          <div className="tm-month-voice-text">「{String(m.voice.entry)}」</div>
        </div>
      ) : (
        <div className="tm-month-voice-empty">
          {t("panel.stats.month.voiceEmpty", { defaultValue: "这个月她还没有写过手记。" })}
        </div>
      )}
    </div>
  )
}

// 月报数字格
function MonthCell(props: { label: string; value: string }) {
  const { label, value } = props
  return (
    <div className="tm-month-cell">
      <span className="tm-month-cell-value">{value}</span>
      <span className="tm-month-cell-label">{label}</span>
    </div>
  )
}
