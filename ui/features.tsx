// 功能管理页（1.2.7 能力中心）：全部功能能力的开关总览。
// 数据源 = list_capabilities 入口（按宿主当前角色解析）；开关经 set_capability
// 写"否决集"——关闭即否决、打开回落既有配置默认（不会强行点亮配置里关着的项）。
// 高级选项 hide_disabled_tools 全局一份：开启后，对所有角色都不生效的能力，
// 其 LLM 工具从模型可见面摘除（面板保存后经 props 上的 api.refresh 拉回最新状态）。
import { Card, Field, StatusBadge, Switch, Alert } from "@neko/plugin-ui"
import type { CapabilitiesPayload, CapItem, TFunc } from "./types"

// LLM 触点徽标：让"关掉它能省什么"一眼可见
const LLM_BADGES: Record<string, { key: string; def: string; tone: "warning" | "success" | "default" }> = {
  tool: { key: "panel.features.llm.tool", def: "LLM 工具", tone: "warning" },
  direct: { key: "panel.features.llm.direct", def: "直连模型", tone: "warning" },
  host_http: { key: "panel.features.llm.host", def: "宿主模型", tone: "warning" },
  injection: { key: "panel.features.llm.injection", def: "上下文注入", tone: "default" },
  none: { key: "panel.features.llm.local", def: "纯本地", tone: "success" },
}

const GROUP_ORDER = ["rhythm", "mood", "diary"]

export function FeaturesPane(props: {
  t: TFunc
  caps: CapabilitiesPayload | null
  loading?: boolean
  busyId?: string
  onToggleCap: (id: string, enabled: boolean) => void
  onToggleHideTools: (value: boolean) => void
}) {
  const { t, caps, loading, busyId, onToggleCap, onToggleHideTools } = props
  const items = (caps && caps.capabilities) || []
  const masterOn = !!caps && caps.master_enabled !== false

  function capLabel(id: string): string {
    return t(`panel.features.cap.${id}.label`, { defaultValue: id })
  }

  function groupLabel(group: string): string {
    return t(`panel.features.group.${group}`, { defaultValue: group })
  }

  function offHint(item: CapItem): string {
    if (item.source === "master_off") {
      return t("panel.features.hint.masterOff", { defaultValue: "该角色的总开关未开启" })
    }
    if (item.source === "config_off") {
      return t("panel.features.hint.configOff", { defaultValue: "功能配置里已关闭（到对应设置页打开）" })
    }
    if (item.source === "upstream_off") {
      const deps = (item.blocked_by || []).map(capLabel).join("、")
      return t("panel.features.hint.upstream", { defaultValue: `依赖的功能未生效：${deps}` })
    }
    if (item.source === "user_off") {
      return t("panel.features.hint.userOff", { defaultValue: "已在功能管理里关闭" })
    }
    return ""
  }

  return (
    <div className="tm-pane">
      {!masterOn ? (
        <Alert
          tone="warning"
          message={t("panel.features.masterBanner", {
            defaultValue: "该角色的总开关未开启：下面所有功能都不会生效（这里改的开关仍会记住）。",
          })}
        />
      ) : null}

      {GROUP_ORDER.map((group) => {
        const inGroup = items.filter((item) => item.group === group)
        if (!inGroup.length) return null
        return (
          <Card key={group} title={groupLabel(group)}>
            <div className="tm-feat-list">
              {inGroup.map((item) => {
                const badge = LLM_BADGES[item.llm] || LLM_BADGES.none
                const busy = busyId === item.id
                return (
                  <div key={item.id} className="tm-feat-row">
                    <Field
                      label={capLabel(item.id)}
                      help={
                        (item.enabled ? "" : offHint(item)) ||
                        t(`panel.features.cap.${item.id}.desc`, { defaultValue: "" })
                      }
                    >
                      <span className="tm-feat-side">
                        <StatusBadge tone={badge.tone} label={t(badge.key, { defaultValue: badge.def })} />
                        <Switch
                          checked={!!item.enabled}
                          disabled={busy || loading}
                          onChange={(value: boolean) => onToggleCap(item.id, value)}
                        />
                      </span>
                    </Field>
                  </div>
                )
              })}
            </div>
          </Card>
        )
      })}

      <Card title={t("panel.features.advanced", { defaultValue: "高级选项" })}>
        <Switch
          checked={!!(caps && caps.hide_disabled_tools)}
          disabled={loading}
          label={t("panel.features.hideTools", { defaultValue: "关闭的功能从模型可见面摘除工具" })}
          onChange={(value: boolean) => onToggleHideTools(value)}
        />
        <div className="tm-feat-note">
          {t("panel.features.hideToolsHelp", {
            defaultValue:
              "默认温和模式：关闭的功能其工具仍在位、调用时被拒绝。开启后，对所有角色都不生效的功能，其工具会真正对模型隐藏（省上下文）；恢复生效自动重挂。",
          })}
        </div>
      </Card>
    </div>
  )
}
