// 设置 · 模型通道（全局）：三个小模型槽位集中一处，各自带状态灯——
// 语气分析（默认走宿主情感端点）、碎片提取与我的日记成文（默认复用宿主 LLM 管线）。
// 每张卡两个正交旋钮：槽位 = 用宿主哪个槽的模型，通道 = 由谁去调它。
// 通道选「宿主」时零配置即用（端点、模型名、免费路由、客户端身份都由宿主给出）；
// 选「自定义」则插件读宿主本地配置自己直连该槽端点——留给要接本地模型/独立服务商
// 的空间，代价是宿主免费路由下拼不出可用端点（那些值不在存盘配置里），会休眠。
// 状态灯直说"为什么不能用/怎么办"，并如实显示这次实际走了哪条路（宿主模式回落直连时不说"正常"）。
// 行为开关（启用/频率/灵敏度）在各自功能的设置卡里，这张卡只管"走哪条模型通道"。
//
// ⚠️ 空值哨兵：UI kit 受控 Select 在 option value='' 时有 mount 竞态——select.value
// 先于 options 设置会进 dirty 态，selectedIndex 停在 -1，change 事件回传的是 option
// 的 label 文本而不是空串（实测复现）。因此"宿主默认"选项的 value 用哨兵 "__default"，
// onChange 时翻译回空串再进表单；后端校验只认空串。哨兵不会出现在表单/存储里。
import { Card, Select } from "@neko/plugin-ui"
import type { ChannelStatusItem, FormValues, TFunc, ToneSlotOption } from "./types"

const DEFAULT_SLOT_SENTINEL = "__default__"

// 通道模式：与 core/state.py 的 _CHANNEL_MODE_* 一字不差
const MODE_HOST = "host"
const MODE_CUSTOM = "custom"

export function ChannelSettingsCard(props: {
  t: TFunc
  form: FormValues
  updateForm: (patch: Partial<FormValues>) => void
  toneSlotOptions?: ToneSlotOption[]
  channelStatus?: { tone?: ChannelStatusItem; fragments?: ChannelStatusItem; review?: ChannelStatusItem }
}) {
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
      // 空值选项用哨兵，规避 UI kit Select 的 value='' mount 竞态（见文件头注释）
      value: value === "" ? DEFAULT_SLOT_SENTINEL : value,
      label: model ? `${name} · ${model}` : name,
    }
  })
  // 碎片/成文的下拉不给空串与 emotion：空串档是"跟随宿主情感端点"（五分类专用，
  // 对这两条要自定义 prompt 的通道无意义），emotion 槽只由语气分析那张卡暴露
  const directSlots = allSlots.filter((opt) => String(opt.value) !== DEFAULT_SLOT_SENTINEL && String(opt.value) !== "emotion")
  const modeOptions = [
    { value: MODE_HOST, label: t("panel.settings.channelModeHost", { defaultValue: "宿主（开箱即用）" }) },
    { value: MODE_CUSTOM, label: t("panel.settings.channelModeCustom", { defaultValue: "自定义直连" }) },
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
        hint={t("panel.settings.channelToneHint", { defaultValue: "默认跟随宿主情感模型（经宿主端点调用，免费路由下也可用）；选其他槽位时改为插件直连" })}
        light={channelLight(t, toneCh, form.emotion_sense_enabled)}
      >
        <Select
          value={form.tone_slot === "" ? DEFAULT_SLOT_SENTINEL : form.tone_slot}
          options={allSlots}
          onChange={(v: any) => updateForm({ tone_slot: String(v) === DEFAULT_SLOT_SENTINEL ? "" : String(v) })}
        />
      </ChannelRow>

      <div className="tm-channel-divider" />

      {/* 碎片提取：默认复用宿主管线，可切自定义直连 */}
      <ChannelRow
        t={t}
        label={t("panel.settings.channelFragments", { defaultValue: "碎片提取" })}
        hint={channelHint(t, form.fragments_mode)}
        light={channelLight(t, fragCh, form.fragments_enabled, form.fragments_mode || MODE_HOST)}
      >
        <Select value={form.fragments_slot} options={directSlots} onChange={(v: any) => updateForm({ fragments_slot: String(v) })} />
        <Select
          value={form.fragments_mode || MODE_HOST}
          options={modeOptions}
          onChange={(v: any) => updateForm({ fragments_mode: String(v) })}
        />
      </ChannelRow>

      {/* 我的日记成文：与碎片提取同款通道 */}
      <ChannelRow
        t={t}
        label={t("panel.settings.channelReview", { defaultValue: "我的日记成文" })}
        hint={channelHint(t, form.review_mode)}
        light={channelLight(t, reviewCh, form.review_enabled, form.review_mode || MODE_HOST)}
      >
        <Select value={form.review_slot} options={directSlots} onChange={(v: any) => updateForm({ review_slot: String(v) })} />
        <Select
          value={form.review_mode || MODE_HOST}
          options={modeOptions}
          onChange={(v: any) => updateForm({ review_mode: String(v) })}
        />
      </ChannelRow>

      {/* 免费路由说明只在"直连这条路确实因为免费路由而不通"时说：自定义模式选了
          免费路由，或宿主模式回落到直连后仍拼不出端点——其余状态各灯自己解释 */}
      {isFreeRoute(fragCh) || isFreeRoute(reviewCh) ? (
        <div className="tm-channel-warn">
          {t("panel.settings.freeRouteWarn", { defaultValue: "直连通道要从宿主本地配置拼出端点，而免费路由的端点与模型名并不写在配置里，所以拼不出可用端点、功能休眠。把上方通道切回「宿主」即可零配置使用；想继续用直连，先在宿主设置里配置自己的 API 服务商。" })}
        </div>
      ) : null}
    </Card>
  )
}

// 通道说明文案：两种模式的代价/收益不同，说清各自那一句
function channelHint(t: TFunc, mode: string | undefined): string {
  return (mode || MODE_HOST) === MODE_CUSTOM
    ? t("panel.settings.channelHintCustom", { defaultValue: "插件读宿主本地配置直连该槽端点；该槽未配模型、或宿主在用免费路由时拼不出可用端点，功能自动休眠" })
    : t("panel.settings.channelHintHost", { defaultValue: "复用宿主自己的模型管线（与宿主内置插件同一条路）：不用配任何东西，免费路由下也可用；宿主管线不可用时自动回落直连" })
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
    return { cls: "tm-light-dormant", text: t("panel.channel.freeRoute", { defaultValue: "免费路由 · 直连不可用" }) }
  }
  if (ch.dormant_reason === "no_model") {
    return { cls: "tm-light-dormant", text: t("panel.channel.noModel", { defaultValue: "槽位未配模型 · 休眠" }) }
  }
  if (ch.dormant_reason === "disabled") {
    return { cls: "tm-light-off", text: t("panel.channel.off", { defaultValue: "未启用" }) }
  }
  // 选的是宿主通道却实际在直连（宿主模块没给到端点）：能干活，但不是用户选的那条路，
  // 如实说——否则"正常"灯会藏住一次静默回落。反之 mode=custom 走 direct 是用户自己
  // 选的，报"回落"就等于把一次正常配置说成故障，所以这里必须带上 mode 判据。
  if (mode === MODE_HOST && ch.transport === "direct") {
    return { cls: "tm-light-dormant", text: t("panel.channel.fellBackDirect", { defaultValue: "宿主管线未生效 · 已回落直连" }) }
  }
  return { cls: "tm-light-ok", text: t("panel.channel.ok", { defaultValue: "正常" }) }
}

// 这条通道此刻是不是"直连被免费路由挡住"（免费路由警告只在这种状态下才说得出道理）
function isFreeRoute(ch: ChannelStatusItem | undefined): boolean {
  return !!ch && ch.dormant_reason === "free_route"
}
