// 永远的陪伴面板入口：context 轮询、动作处理、Tab 导航与各页组装
// 顶级页签：日历 / 周期 / 注入 / 情绪（情绪系统+语气感知）/ 手记 / 管理（危险区+角色名单）
import {
  Alert,
  Page,
} from "@neko/plugin-ui"
import { useConfirm, useEffect, useLocalState, useState, useToast } from "@neko/plugin-ui"
import type { HostedAction, PluginSurfaceProps } from "@neko/plugin-ui"
import type { FormValues, Settings, State } from "./types"
import { DATE_RE, settingsToForm } from "./utils"
import { PANEL_STYLES } from "./styles"
import { StatusBar } from "./statusbar"
import { OverviewPane } from "./overview"
import { CalendarPane } from "./calendar"
import { CycleSettingsCard } from "./settings_cycle"
import { InjectSettingsCard } from "./settings_inject"
import { MoodSettingsCard } from "./settings_mood"
import { EmotionSenseSettingsCard } from "./settings_emotion"
import { ChannelSettingsCard } from "./settings_tone"
import { DiarySettingsCard } from "./settings_diary"
import { SaveBar } from "./savebar"
import { ManagePane } from "./manage"
import { DiaryPane } from "./diary"
import { MomentPane } from "./moment"
import { AppearanceCard } from "./appearance"
import type { DiaryItem, JournalPage, Heatmap, MonthReport, ReviewEntry, ReviewProgress } from "./types"
import { unwrapCallResult } from "./utils"

export default function Panel(props: PluginSurfaceProps<State>) {
  const { actions, state, t } = props
  const status = state.status || {}
  const mood = state.mood || {}
  const settings = state.settings || {}
  const toast = useToast()
  const confirmDialog = useConfirm()
  // 默认页签 = 总览；useLocalState 的旧持久化值（0.9.0 前可能是 calendar 等）
  // 会被 VALID_TABS 校验兜回 overview，但初值本身也要指向 overview
  const [tab, setTab] = useLocalState<string>("tide.tab", "overview")
  const [form, setForm] = useState<FormValues>(settingsToForm({}))
  // 面板外观：自定义背景图本体按需拉取（不进 5s 轮询）；遮罩强度随图一起落盘
  const [bgUrl, setBgUrl] = useState<string>("")
  const [bgDim, setBgDim] = useState<number>(0.3)
  const [bgSaving, setBgSaving] = useState(false)
  // 时光页：相处统计的热力图/月报数据量大，进页时按需拉取（不随 5s 轮询）；
  // 切角色时清掉旧数据等下次进页重拉
  const [heatData, setHeatData] = useState<Heatmap | null>(null)
  const [monthData, setMonthData] = useState<MonthReport | null>(null)
  const [monthList, setMonthList] = useState<string[]>([])
  const [statsLoading, setStatsLoading] = useState(false)

  function updateForm(patch: Partial<FormValues>) {
    setForm((prev) => ({ ...prev, ...patch }))
  }

  useEffect(() => {
    setForm(settingsToForm(settings))
  }, [
    settings.auto_derive,
    settings.cycle_length,
    settings.period_length,
    settings.ovulation_day,
    settings.ovulation_window,
    settings.inject_mode,
    settings.inject_interval_n,
    settings.phase_openers,
    settings.timezone,
    settings.mood_enabled,
    settings.default_action_minutes,
    settings.emotion_sense_enabled,
    settings.tone_check_rate,
    settings.tone_phase_sensitivity_enabled,
    settings.tone_phase_sensitivity,
    settings.tone_slot,
    settings.fragments_enabled,
    settings.fragments_slot,
    settings.review_enabled,
    settings.review_slot,
    settings.review_turns_threshold,
    settings.review_days_threshold,
    (settings as Record<string, any>).anniversary_inject,
  ])

  // 面板打开期间周期性同步 context：宿主切换角色后自动跟上，情绪状态/阶段等外部变化
  // （入口点触发、tick 到期、对话中的 LLM 工具调用）无需重进面板即可看到
  useEffect(() => {
    const timer = setInterval(() => {
      try {
        props.api.refresh()
      } catch {
        // 轮询失败静默忽略，下个周期重试
      }
    }, 5000)
    return () => clearInterval(timer)
  }, [])

  // 背景图只在面板打开时拉一次：几 MB 的 data URL 不该进轮询；
  // 应用/移除后立即本地更新，不依赖重拉。拉取失败按默认背景处理，不弹错
  useEffect(() => {
    let alive = true
    Promise.resolve(props.api.call("get_panel_background", {}))
      .then((payload) => {
        if (!alive) return
        const r = (unwrapCallResult(payload) || {}) as Record<string, any>
        if (r.set) {
          setBgUrl(String(r.data_url || ""))
          setBgDim(Number(r.dim ?? 0.3))
        }
      })
      .catch(() => {
        // 背景拉取失败无伤大雅：默认渐变底照旧可用，console 留痕便于排查
        console.warn("[forever_companion] load panel background failed")
      })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function onApplyBg(dataUrl: string, dim: number) {
    if (!dataUrl) return
    setBgSaving(true)
    try {
      const payload = unwrapCallResult(await props.api.call("set_panel_background", { data_url: dataUrl, dim }))
      const r = (payload || {}) as Record<string, any>
      setBgUrl(String(dataUrl))
      setBgDim(Number(r.dim ?? dim))
      toast.success(t("panel.appearance.applied", { defaultValue: "背景已更新" }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setBgSaving(false)
    }
  }

  async function onRemoveBg() {
    setBgSaving(true)
    try {
      await props.api.call("clear_panel_background", {})
      setBgUrl("")
      setBgDim(0.3)
      toast.success(t("panel.appearance.removed", { defaultValue: "已恢复默认背景" }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setBgSaving(false)
    }
  }

  const updateSettingsAction = actions.find((a) => a.id === "update_settings") as HostedAction | undefined
  const setAnchor = actions.find((a) => a.id === "set_anchor") as HostedAction | undefined
  const advance = actions.find((a) => a.id === "advance_days") as HostedAction | undefined
  const toggle = actions.find((a) => a.id === "toggle") as HostedAction | undefined
  const resetAll = actions.find((a) => a.id === "reset_all") as HostedAction | undefined
  const pruneLanlan = actions.find((a) => a.id === "prune_lanlan") as HostedAction | undefined

  // kit 的 useConfirm 默认按钮文案是英文 Confirm/Cancel，必须显式传本地化文案
  const confirmLabels = {
    confirmLabel: t("panel.confirm", { defaultValue: "确认" }),
    cancelLabel: t("panel.cancel", { defaultValue: "取消" }),
  }

  async function saveSettings() {
    if (!updateSettingsAction) {
      toast.error(t("panel.errors.actionUnavailable", { defaultValue: "操作不可用（插件可能未运行）" }))
      return
    }
    try {
      if (!DATE_RE.test(String(state.anchor_date || ""))) {
        throw new Error(t("panel.errors.setAnchorFirst", { defaultValue: "请先设置潮汐首日锚点，再开启模拟" }))
      }
      const result = await props.api.call("update_settings", { ...form })
      // 用入口返回的最新快照立即回填表单，不依赖 context 重取
      const snap = (result && typeof result === "object" && (result as Record<string, any>).enabled !== undefined)
        ? (result as Partial<Settings>)
        : null
      if (snap) {
        setForm(settingsToForm({ ...settings, ...snap }))
      }
      toast.success(t("panel.messages.saved", { defaultValue: "设置已保存" }))
      try {
        await props.api.refresh()
      } catch {
        // context 刷新失败不影响"已保存"结论，表单已本地回填
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  async function onToggle() {
    if (!toggle) {
      toast.error(t("panel.errors.actionUnavailable", { defaultValue: "操作不可用（插件可能未运行）" }))
      return
    }
    const turningOff = status.enabled !== false
    const ok = await confirmDialog({
      title: turningOff ? t("panel.turnOff", { defaultValue: "关闭模拟" }) : t("panel.turnOn", { defaultValue: "开启模拟" }),
      message: t("actions.toggle.confirm", { defaultValue: "切换身体节律模拟的总开关，确认？" }),
      tone: turningOff ? "warning" : "primary",
      ...confirmLabels,
    })
    if (!ok) return
    try {
      await props.api.call("toggle")
      await props.api.refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  async function onClearDiary() {
    const ok = await confirmDialog({
      title: t("actions.clear_diary.label", { defaultValue: "清空时光日记" }),
      message: t("actions.clear_diary.confirm", { defaultValue: "将删除全部时光日记（她的手记与自动碎片），不可恢复，确认？" }),
      tone: "danger",
      ...confirmLabels,
    })
    if (!ok) return
    try {
      await props.api.call("clear_diary")
      await props.api.refresh()
      toast.success(t("panel.diary.cleared", { defaultValue: "时光日记已清空" }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  async function onDeleteFragment(ts: string) {
    const ok = await confirmDialog({
      title: t("actions.delete_diary_item.label", { defaultValue: "删除这条碎片" }),
      message: t("actions.delete_diary_item.confirm", { defaultValue: "将删除这条自动记录的碎片，不可恢复，确认？" }),
      tone: "danger",
      ...confirmLabels,
    })
    if (!ok) return
    try {
      await props.api.call("delete_diary_item", { ts })
      await props.api.refresh()
      toast.success(t("panel.diary.deleted", { defaultValue: "已删除" }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  async function onLoadJournal() {
    try {
      const payload = unwrapCallResult(await props.api.call("get_journal", {}))
      const pages = (payload as Record<string, any>)?.pages
      return Array.isArray(pages) ? (pages as JournalPage[]) : []
    } catch (err) {
      // 宿主不可达/动作被拒：按空日记本处理，面板不报错；console 留痕便于排查
      console.warn("[forever_companion] load journal failed:", err)
      return []
    }
  }

  async function onLoadMoreDiary(offset: number) {
    try {
      const payload = unwrapCallResult(await props.api.call("get_diary", { limit: 50, offset }))
      const r = (payload || {}) as Record<string, any>
      return {
        items: Array.isArray(r.items) ? (r.items as DiaryItem[]) : [],
        hasMore: !!r.has_more,
      }
    } catch (err) {
      console.warn("[forever_companion] load more diary failed:", err)
      return { items: [] as DiaryItem[], hasMore: false }
    }
  }

  async function onInviteJournal() {
    try {
      const payload = unwrapCallResult(await props.api.call("invite_journal", {}))
      await props.api.refresh()
      const r = (payload || {}) as Record<string, any>
      if (r.invited === false) {
        toast.info(String(r.note || t("panel.journal.inviteOff", { defaultValue: "个人日记开关未开启，邀请未发送" })))
      } else {
        toast.success(t("panel.journal.invited", { defaultValue: "邀请已递出，写不写由她自己决定" }))
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  async function onLoadReview() {
    try {
      const payload = unwrapCallResult(await props.api.call("get_review", {}))
      const r = (payload || {}) as Record<string, any>
      return {
        entries: Array.isArray(r.entries) ? (r.entries as ReviewEntry[]) : [],
        progress: (r.progress || {}) as ReviewProgress,
      }
    } catch (err) {
      console.warn("[forever_companion] load review failed:", err)
      return { entries: [] as ReviewEntry[], progress: {} as ReviewProgress }
    }
  }

  async function onWriteReviewNow() {
    try {
      const payload = unwrapCallResult(await props.api.call("write_review_now", {}))
      await props.api.refresh()
      const r = (payload || {}) as Record<string, any>
      if (r.written === false) {
        toast.info(String(r.note || t("panel.review.writeFailed", { defaultValue: "这一篇还没写成，稍后再试" })))
      } else {
        toast.success(t("panel.review.written", { defaultValue: "这一篇已经写好了，翻开看看吧" }))
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  async function onClearReview() {
    const ok = await confirmDialog({
      title: t("actions.clear_review.label", { defaultValue: "清空我的日记" }),
      message: t("actions.clear_review.confirm", { defaultValue: "将删除全部「我的日记」评价（累计素材一并清零），不可恢复，确认？" }),
      tone: "danger",
      ...confirmLabels,
    })
    if (!ok) return
    try {
      await props.api.call("clear_review", {})
      await props.api.refresh()
      toast.success(t("panel.review.cleared", { defaultValue: "我的日记已清空" }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  async function onLoadStats(month?: string) {
    setStatsLoading(true)
    try {
      const payload = unwrapCallResult(await props.api.call("get_stats", month ? { month } : {}))
      const r = (payload || {}) as Record<string, any>
      setHeatData((r.heatmap || {}) as Heatmap)
      setMonthData((r.month || null) as MonthReport | null)
      setMonthList(Array.isArray(r.month_available) ? (r.month_available as string[]) : [])
    } catch (err) {
      console.warn("[forever_companion] load stats failed:", err)
    } finally {
      setStatsLoading(false)
    }
  }

  // 切角色时旧统计立即失效：清到空态，避免上一个角色的热力图残留展示
  useEffect(() => {
    setHeatData(null)
    setMonthData(null)
    setMonthList([])
  }, [state.lanlan])

  // 进时光页时按需拉取一次热力图/月报（徽章与摘要在 5s 轮询里）；
  // 已有数据不重拉，翻月由 onPickMonth 显式触发
  useEffect(() => {
    if (tab === "moment" && !heatData && !statsLoading) {
      onLoadStats()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, heatData])

  async function onPruneLanlan(name: string) {
    if (!pruneLanlan) {
      toast.error(t("panel.errors.actionUnavailable", { defaultValue: "操作不可用（插件可能未运行）" }))
      return
    }
    const ok = await confirmDialog({
      title: t("actions.prune_lanlan.label", { defaultValue: "清除残留数据" }),
      message: t("actions.prune_lanlan.confirm", { defaultValue: "将删除该角色残留的周期、情绪与手记数据，不可恢复，确认？" }),
      tone: "danger",
      ...confirmLabels,
    })
    if (!ok) return
    try {
      await props.api.call("prune_lanlan", { lanlan: name })
      await props.api.refresh()
      toast.success(t("panel.lanlan.pruned", { defaultValue: "残留数据已清除" }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  async function onSetAnchor(date: string): Promise<boolean> {
    if (!setAnchor) return false
    const ok = await confirmDialog({
      title: t("actions.set_anchor.label", { defaultValue: "设置潮汐首日" }),
      message: t("actions.set_anchor.confirm", { defaultValue: "将重设周期锚点并重新计算阶段，确认？" }),
      tone: "warning",
      ...confirmLabels,
    })
    if (!ok) return false
    try {
      await props.api.call("set_anchor", { date })
      await props.api.refresh()
      toast.success(t("panel.messages.anchorSet", { defaultValue: "潮汐首日已更新" }))
      return true
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
      return false
    }
  }

  async function onAdvance() {
    if (!advance) return
    try {
      await props.api.call("advance_days", { days: 1 })
      await props.api.refresh()
      toast.success(t("panel.messages.advanced", { defaultValue: "已快进一天" }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  const VALID_TABS = ["overview", "calendar", "cycle", "mood", "diary", "moment", "settings"]
  const activeTab = VALID_TABS.indexOf(tab) >= 0 ? tab : "overview"

  // 面板始终跟随宿主当前角色（5 秒轮询自动跟上切卡），lanlan_list 提供全部已知角色的状态摘要
  const lanlanKnown = (state.lanlan_list || []).filter((item) => item && item.name)

  // 页签图标用纯 CSS 线框图标（hosted 运行时不支持 SVG，也不用 emoji）
  const tabs = [
    { id: "overview", label: t("panel.tab.overview", { defaultValue: "总览" }) },
    { id: "calendar", label: t("panel.tab.calendar", { defaultValue: "日历" }) },
    { id: "cycle", label: t("panel.tab.cycle", { defaultValue: "周期" }) },
    { id: "mood", label: t("panel.tab.mood", { defaultValue: "情绪" }) },
    { id: "diary", label: t("panel.tab.diary", { defaultValue: "日记" }) },
    { id: "moment", label: t("panel.tab.moment", { defaultValue: "时光" }) },
    { id: "settings", label: t("panel.tab.settings", { defaultValue: "设置" }) },
  ]

  return (
    <Page className={bgUrl ? "tm-has-bg" : ""}>
      <style key="styles">{PANEL_STYLES}</style>

      {bgUrl ? (
        <div key="bg" className="tm-bg" style={{ backgroundImage: `url("${bgUrl}")` }}>
          <div className="tm-bg-dim" style={{ opacity: bgDim }} />
        </div>
      ) : null}

      <StatusBar
        t={t}
        status={status}
        mood={mood}
        lanlan={state.lanlan}
        canToggle={!!toggle}
        onToggle={onToggle}
        onGotoOverview={() => setTab("overview")}
      />

      {status.error ? <div key="warn-error" className="tm-warnstrip"><Alert tone="danger" message={status.error} /></div> : null}
      {status.enabled === false ? (
        <div key="warn-disabled" className="tm-warnstrip">
          <Alert tone="info" message={t("panel.disabledHint", { defaultValue: "模拟当前处于关闭状态，点击右上角「开启模拟」即可恢复。" })} />
        </div>
      ) : null}
      {mood.system_enabled === false ? (
        <div key="warn-mood" className="tm-warnstrip">
          <Alert tone="warning" message={t("panel.mood.disabledWarn", { defaultValue: "情绪系统当前处于关闭状态（可在「情绪」页开启，实验性功能）。" })} />
        </div>
      ) : null}

      <div key="body" className="tm-body">
        <nav className="tm-tabs">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              className={activeTab === item.id ? "tm-tab tm-tab-active" : "tm-tab"}
              onClick={() => setTab(item.id)}
            >
              <span className={`tm-ico tm-ico-${item.id}`} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="tm-content" key={activeTab}>
          {activeTab === "overview" ? (
            <OverviewPane
              t={t}
              status={status}
              mood={mood}
              settings={settings}
              lanlan={state.lanlan}
              diaryTotal={state.diary_total || 0}
              fragmentTotal={state.fragment_total || 0}
              journalIndex={state.journal_index || []}
              reviewBrief={state.review_brief}
              weekActivity={state.week_activity}
              onGoto={(id: string) => setTab(id)}
            />
          ) : null}
          {activeTab === "calendar" ? (
            <CalendarPane
              key={state.lanlan || ""}
              t={t}
              calendar={state.calendar}
              anchorDate={state.anchor_date}
              advanceDays={state.advance_days}
              lanlan={state.lanlan}
              canSetAnchor={!!setAnchor}
              canAdvance={!!advance}
              onSetAnchor={onSetAnchor}
              onAdvance={onAdvance}
            />
          ) : null}
          {activeTab === "cycle" ? (
            <div className="tm-pane">
              {!state.anchor_date ? (
                <Alert tone="warning" message={t("panel.errors.setAnchorFirst", { defaultValue: "请先设置潮汐首日锚点，再开启模拟" })} />
              ) : null}
              <CycleSettingsCard t={t} settings={settings} form={form} updateForm={updateForm} lanlan={state.lanlan} />
              <InjectSettingsCard t={t} form={form} updateForm={updateForm} />
              <SaveBar t={t} canSave={!!updateSettingsAction} onSave={saveSettings} />
            </div>
          ) : null}
          {activeTab === "mood" ? (
            <div className="tm-pane">
              <MoodSettingsCard t={t} form={form} updateForm={updateForm} />
              <EmotionSenseSettingsCard t={t} form={form} updateForm={updateForm} />
              <ChannelSettingsCard
                t={t}
                form={form}
                updateForm={updateForm}
                toneSlotOptions={state.tone_slot_options}
                channelStatus={state.channel_status}
              />
              <SaveBar t={t} canSave={!!updateSettingsAction} onSave={saveSettings} />
            </div>
          ) : null}
          {activeTab === "diary" ? (
            <DiaryPane
              t={t}
              diary={state.diary_recent || []}
              diaryTotal={state.diary_total || 0}
              fragmentTotal={state.fragment_total || 0}
              journalIndex={state.journal_index || []}
              lanlan={state.lanlan}
              reviewBrief={state.review_brief}
              onClearDiary={onClearDiary}
              onDeleteFragment={onDeleteFragment}
              onLoadJournal={onLoadJournal}
              onLoadMoreDiary={onLoadMoreDiary}
              onInviteJournal={onInviteJournal}
              onLoadReview={onLoadReview}
              onWriteReviewNow={onWriteReviewNow}
              onClearReview={onClearReview}
              settingsChildren={(
                <>
                  <DiarySettingsCard t={t} form={form} updateForm={updateForm} />
                  <SaveBar t={t} canSave={!!updateSettingsAction} onSave={saveSettings} />
                </>
              )}
            />
          ) : null}
          {activeTab === "moment" ? (
            <MomentPane
              t={t}
              lanlan={state.lanlan}
              summary={state.stats_summary ? state.stats_summary.summary : undefined}
              badges={state.stats_summary ? state.stats_summary.badges : undefined}
              heatmap={heatData}
              month={monthData}
              monthAvailable={monthList}
              monthLoading={statsLoading}
              onPickMonth={(month: string) => onLoadStats(month)}
            />
          ) : null}
          {activeTab === "settings" ? (
            <ManagePane
              t={t}
              form={form}
              updateForm={updateForm}
              resetAll={resetAll}
              lanlanList={lanlanKnown}
              lanlan={state.lanlan}
              canPrune={!!pruneLanlan}
              onPruneLanlan={onPruneLanlan}
            >
              <AppearanceCard
                key={`${bgUrl ? "set" : "empty"}:${bgDim}`}
                t={t}
                currentUrl={bgUrl}
                dim={bgDim}
                saving={bgSaving}
                onApply={onApplyBg}
                onRemove={onRemoveBg}
              />
            </ManagePane>
          ) : null}
        </div>
      </div>
    </Page>
  )
}
