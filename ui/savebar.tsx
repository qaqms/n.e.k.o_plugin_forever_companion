// 吸底保存条：各设置页共用，滚动到底仍可见；未运行（无保存动作）时不渲染
// saving 只禁用按钮不改文案：连点会发两趟写盘，落盘在飞时必须挡掉
import { Button } from "@neko/plugin-ui"
import type { TFunc } from "./types"

export function SaveBar(props: { t: TFunc; canSave: boolean; onSave: () => void; saving?: boolean }) {
  const { t, canSave, onSave, saving } = props
  if (!canSave) return null
  return (
    <div className="tm-save">
      <Button tone="primary" disabled={!!saving} onClick={onSave}>
        {t("panel.settings.save", { defaultValue: "保存设置" })}
      </Button>
    </div>
  )
}
