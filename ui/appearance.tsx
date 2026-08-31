// 面板外观卡：自定义背景图（上传 → 预览 → 应用/移除）+ 遮罩强度调节。
// 背景图本体由 panel.tsx 经 get/set/clear_panel_background 三个入口存取，
// 本卡只管交互：ImageUpload 产出 data URL，点「应用背景」才真正落盘。
// hosted-tsx 约束：唯一 export 在任何 JSX 闭合标签之前；不支持 <svg>（纯 CSS 预览）
import { Button, Card, Field, ImageUpload, Slider } from "@neko/plugin-ui"
import { useState } from "@neko/plugin-ui"
import type { TFunc } from "./types"

export function AppearanceCard(props: {
  key?: string
  t: TFunc
  currentUrl?: string
  dim: number
  saving: boolean
  onApply: (dataUrl: string, dim: number) => void
  onRemove: () => void
}) {
  const { t, currentUrl, dim, saving, onApply, onRemove } = props
  // pending = 选了还没应用的图；遮罩强度同样先本地调、随应用一起落盘；
  // 应用成功后 panel 层用 key={bgUrl:bgDim} 重挂本卡，内部态自然复位
  const [pending, setPending] = useState<string | null>(null)
  const [pendingDim, setPendingDim] = useState<number>(dim)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const preview = pending || currentUrl || ""
  const dirty = pending !== null || Math.abs(pendingDim - dim) > 0.001

  return (
    <Card title={t("panel.appearance.title", { defaultValue: "面板外观" })}>
      <div className="tm-appearance">
        <div className="tm-derived">
          {t("panel.appearance.hint", { defaultValue: "导入一张图片作为面板背景，与磨砂卡片叠出透明质感；遮罩用来压暗背景保证文字可读。" })}
        </div>
        <Field
          label={t("panel.appearance.upload", { defaultValue: "背景图" })}
          help={t("panel.appearance.uploadHelp", { defaultValue: "支持 PNG / JPG / WebP / GIF / SVG，建议不超过 4MB" })}
          error={uploadError || undefined}
        >
          <ImageUpload
            value={preview || undefined}
            alt={t("panel.appearance.previewAlt", { defaultValue: "面板背景预览" })}
            placeholder={t("panel.appearance.uploadPlaceholder", { defaultValue: "点击或拖拽图片到这里" })}
            accept="image/*"
            maxBytes={4500000}
            onChange={(artifact) => {
              const url = String((artifact && artifact.dataUrl) || "")
              setUploadError(null)
              setPending(url || null)
            }}
            onError={(error) => {
              setUploadError(localizeUploadError(t, error))
            }}
          />
        </Field>
        <Field
          label={t("panel.appearance.dim", { defaultValue: "遮罩强度" })}
          help={t("panel.appearance.dimHelp", { defaultValue: "越高越暗；背景偏亮时调高一些，文字更清晰" })}
        >
          <Slider
            value={pendingDim}
            min={0}
            max={0.85}
            step={0.05}
            showValue
            onChange={(value) => { setPendingDim(Number(value)) }}
          />
        </Field>
        {preview ? (
          <div
            className="tm-bg-preview"
            title={t("panel.appearance.previewAlt", { defaultValue: "面板背景预览" })}
            style={{ backgroundImage: `url("${preview}")` }}
          >
            <div className="tm-bg-preview-dim" style={{ opacity: pendingDim }} />
          </div>
        ) : null}
        <div className="tm-appearance-actions">
          <Button tone="primary" disabled={!dirty || saving || !preview} onClick={() => {
            onApply(pending || currentUrl || "", pendingDim)
          }}>
            {saving
              ? t("panel.appearance.saving", { defaultValue: "保存中…" })
              : t("panel.appearance.apply", { defaultValue: "应用背景" })}
          </Button>
          {currentUrl ? (
            <Button tone="danger" disabled={saving} onClick={onRemove}>
              {t("panel.appearance.remove", { defaultValue: "移除背景" })}
            </Button>
          ) : null}
        </div>
      </div>
    </Card>
  )
}

// 宿主 ImageUpload 抛的运行时错误是英文（"File is too large (x MB)"等），
// 这里映射成中文给用户看；未知错误保留原文不吞信息
function localizeUploadError(t: TFunc, error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error || "")
  const tooLarge = raw.match(/File is too large \((\d+) MB\)/)
  if (tooLarge) {
    return t("panel.appearance.errorTooLarge", { defaultValue: "图片太大了（{n} MB），请压缩到 4MB 以内" })
      .replace("{n}", tooLarge[1])
  }
  if (/too large/i.test(raw)) {
    return t("panel.appearance.errorTooLargeShort", { defaultValue: "图片太大了，请压缩到 4MB 以内" })
  }
  return raw
}
