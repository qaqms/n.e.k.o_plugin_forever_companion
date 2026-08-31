// 设置 · 日记功能行为（全局）：碎片捕获与我的日记的开关/门槛（放在日记页，
// 与浏览同页）。槽位选择统一在「情绪」页的模型通道卡。
import { Card, Field, NumberInput, Switch } from "@neko/plugin-ui"
import type { FormValues, TFunc } from "./types"

export function DiarySettingsCard(props: {
  t: TFunc
  form: FormValues
  updateForm: (patch: Partial<FormValues>) => void
}) {
  const { t, form, updateForm } = props

  return (
    <Card title={t("panel.settings.diary", { defaultValue: "日记功能" })}>
      <div className="tm-derived">
        {t("panel.settings.sectionGlobalHint", { defaultValue: "以下设置对所有角色生效" })}
      </div>

      {/* 时光日记 · 自动碎片 */}
      <Switch
        checked={form.fragments_enabled}
        label={t("panel.settings.fragmentsEnabled", { defaultValue: "自动记下他说过的重要的话（喜好/厌恶/有分量的话/过激言行）" })}
        onChange={(value: boolean) => updateForm({ fragments_enabled: value })}
      />
      {form.fragments_enabled ? (
        <div className="tm-derived">
          {t("panel.settings.fragmentsHint", { defaultValue: "碎片只存进她的日记本，由她自主翻看使用，不会主动改变她的行为；聊天中判定不明确的内容不会记录" })}
        </div>
      ) : null}

      <div className="tm-review-settings">
        <div className="tm-subcard-title">{t("panel.settings.review", { defaultValue: "我的日记（互动评价）" })}</div>
        <Switch
          checked={form.review_enabled}
          label={t("panel.settings.reviewEnabled", { defaultValue: "定期把这段时间他对她的互动方式写成一篇客观评价" })}
          onChange={(value: boolean) => updateForm({ review_enabled: value })}
        />
        {form.review_enabled ? (
          <>
            <div className="tm-derived">
              {t("panel.settings.reviewHint", { defaultValue: "评价只给你看：不进她的对话上下文、不进宿主记忆、她没有任何工具能读到。如实记录，负面言行不会粉饰" })}
            </div>
            <Field
              className="tm-reserve-help"
              label={t("panel.settings.review_turns", { defaultValue: "成文门槛：攒满轮数" })}
              help={t("panel.settings.review_turns_help", { defaultValue: "攒满这么多轮互动就写一篇（与天数门槛先到先写）" })}
            >
              <NumberInput value={form.review_turns_threshold} min={10} max={500} step={1} onChange={(v: number | string) => updateForm({ review_turns_threshold: typeof v === "number" ? v : 50 })} />
            </Field>
            <Field
              className="tm-reserve-help"
              label={t("panel.settings.review_days", { defaultValue: "成文门槛：距统计起点天数" })}
              help={t("panel.settings.review_days_help", { defaultValue: "满这么多天且期间有聊天就写一篇（挂机没聊天不写空篇）" })}
            >
              <NumberInput value={form.review_days_threshold} min={1} max={90} step={1} onChange={(v: number | string) => updateForm({ review_days_threshold: typeof v === "number" ? v : 7 })} />
            </Field>
          </>
        ) : null}
      </div>
    </Card>
  )
}
