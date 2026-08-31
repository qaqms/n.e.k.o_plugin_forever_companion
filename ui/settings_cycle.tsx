// 设置 · 她的周期（每角色）：自动演算开关 + 周期参数
import { Card, Field, Grid, NumberInput, Switch } from "@neko/plugin-ui"
import type { FormValues, Settings, TFunc } from "./types"

export function CycleSettingsCard(props: {
  t: TFunc
  settings: Settings
  form: FormValues
  updateForm: (patch: Partial<FormValues>) => void
  lanlan?: string
}) {
  const { t, settings, form, updateForm, lanlan } = props

  return (
    <Card title={t("panel.settings.sectionCycle", { defaultValue: "她的周期" })}>
      {lanlan ? (
        <div className="tm-derived">
          {t("panel.settings.sectionCycleHint", { defaultValue: "仅作用于当前查看的角色" })}：{lanlan}
        </div>
      ) : null}
      <Switch
        checked={form.auto_derive}
        label={t("panel.settings.autoDerive", { defaultValue: "自动演算（潮汐期长度、活跃日、活跃窗口由周期长度自动推导）" })}
        onChange={(value: boolean) => updateForm({ auto_derive: value })}
      />
      {form.auto_derive ? (
        <div className="tm-derived">
          {t("panel.settings.derivedResult", { defaultValue: "演算结果" })}：
          {t("panel.settings.tidePhaseShort", { defaultValue: "潮汐期" })} {settings.period_length ?? 5} {t("panel.days", { defaultValue: "天" })}
          {" · "}
          {t("panel.settings.activeDayShort", { defaultValue: "活跃日" })} {t("panel.settings.dayOrdinal", { defaultValue: "第" })} {settings.ovulation_day ?? 14} {t("panel.days", { defaultValue: "天" })}
          {" · "}
          {t("panel.settings.activeWindowShort", { defaultValue: "活跃窗口" })} ±{settings.ovulation_window ?? 3} {t("panel.days", { defaultValue: "天" })}
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
