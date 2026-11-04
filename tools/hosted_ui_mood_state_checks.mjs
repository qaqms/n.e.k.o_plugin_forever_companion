import assert from "node:assert/strict"
import { join } from "node:path"

const STATES = [
  ["ebb_tide", -0.6, 0.35],
  ["sea_fog", -0.5, 0.25],
  ["shallow_reef", -0.3, 0.3],
  ["storm_surge", -0.8, 0.9],
  ["seek_harbor", -0.3, 0.6],
  ["ripple", 0.15, 0.4],
  ["warm_current", 0.6, 0.4],
  ["spring_tide", 0.8, 0.85],
]
const WORDS = [
  ["elated", 0.7, 0.8], ["bright", 0.7, 0.3], ["warm", 0.25, 0.4],
  ["calm", 0, 0.4], ["muffled", -0.25, 0.4],
  ["restless", -0.7, 0.8], ["low", -0.7, 0.3],
]

export async function moodStateChecks(browser, sources, origin, output, { loadPage, inspectLayout }) {
  const checks = []
  const screenshots = []
  for (const locale of Object.keys(sources.messages)) for (const width of [1280, 320]) {
    const id = `mood-states-${locale}-${width}`
    const { page, frame, context, errors } = await loadPage(browser, origin, { locale, moodCase: "active" }, width, 900, width === 320 ? "dark" : "light")
    const text = sources.messages[locale]
    const check = async (name, operation) => {
      try { await operation(); checks.push({ name: `${id}-${name}`, passed: true }); console.log(`PASS ${id}-${name}`) }
      catch (error) { checks.push({ name: `${id}-${name}`, passed: false, error: error.stack }); console.log(`FAIL ${id}-${name}: ${error.message}`) }
    }
    const refresh = async patch => {
      await page.evaluate(patch => {
        Object.assign(window.qaFixture.context.state.mood, patch)
        window.qaFixture.context.state.status.enabled = true
      }, patch)
      await frame.evaluate(payload => window.__NekoRefreshHostedPayload(payload), await page.evaluate(() => window.qaFixture.context))
    }
    const capture = async suffix => {
      const path = join(output, `${id}-${suffix}.png`)
      await page.screenshot({ path, animations: "disabled" })
      const diagnostics = await page.evaluate(() => window.qaDiagnostics.filter(item => item.type === "neko-hosted-surface-error"))
      screenshots.push({ id: `${id}-${suffix}`, path, layout: await inspectLayout(frame), errors: [...errors], diagnostics })
    }
    const assertTooltip = async (trigger, reason) => {
      await trigger.scrollIntoViewIfNeeded()
      await page.waitForTimeout(60)
      await page.mouse.move(1, 1)
      await trigger.hover()
      const tip = frame.locator("body > .tm-tip")
      await tip.waitFor({ state: "visible" })
      assert.equal(await tip.count(), 1)
      assert.equal(await tip.innerText(), reason)
      assert.equal(await tip.locator("img").count(), 0)
      const visible = await tip.evaluate(node => {
        const r = node.getBoundingClientRect()
        return r.left >= 8 && r.right <= innerWidth - 8 && r.top >= 8 && r.bottom <= innerHeight - 8
          && node.scrollWidth <= node.clientWidth + 1
          && [[r.left + 3, r.top + 3], [r.right - 3, r.top + 3], [r.left + 3, r.bottom - 3], [r.right - 3, r.bottom - 3]]
            .every(([x, y]) => node.contains(document.elementFromPoint(x, y)))
      })
      assert(visible, "Tooltip must remain inside the viewport and above cards")
    }
    try {
      for (const [action, valence, arousal] of STATES) await check(action, async () => {
        const label = text[`mood.${action}`]
        assert(label && label !== action, `Missing translated label for ${action}`)
        const reason = `${label}: <img src=x onerror=alert(1)> ${"LongUnbrokenReason".repeat(30)}`
        await refresh({
          active: true, system_enabled: true, action, action_label: label, reason,
          expires_at: action === "seek_harbor" ? null : Date.now() / 1000 + 1800,
          affect: { valence, arousal }, origin: "self",
        })
        const tone = action === "warm_current" || action === "spring_tide" ? "success" : "warning"
        for (const selector of [".tm-status-right .neko-badge", ".tm-ov-mood-chip .neko-badge"]) {
          assert.equal(await frame.locator(selector).innerText(), label)
          assert.equal(await frame.locator(selector).getAttribute("data-tone"), tone)
          assert(await frame.locator(selector).evaluate(node => {
            const r = node.getBoundingClientRect()
            return r.left >= 0 && r.right <= innerWidth && node.scrollWidth <= node.clientWidth + 1
          }), "State badge must not clip its translated label")
        }
        await assertTooltip(frame.locator(".tm-status-right .tm-tooltip-trigger"), reason)
        await assertTooltip(frame.locator(".tm-ov-mood-chip .tm-tooltip-trigger"), reason)
        if (locale === "zh-CN") await capture(action)
        assert.equal(await frame.locator(".tm-ov-mood-chip .tm-status-sub").count(), action === "seek_harbor" ? 0 : 1)
        const layout = await inspectLayout(frame)
        assert.equal(layout.documentOverflow, 0)
        assert.equal(layout.contentOverflow, 0)
        assert.deepEqual(layout.issues, [])
        await page.mouse.move(1, 1)
        await frame.locator("body > .tm-tip").waitFor({ state: "detached" })
        await frame.locator(".tm-tab").nth(4).click()
        assert.equal(await frame.locator(".tm-mood-choice strong").innerText(), label)
        await frame.locator(".tm-mood-reason > summary").first().click()
        assert.equal(await frame.locator(".tm-mood-reason > p").first().innerText(), reason)
        assert.equal(await frame.locator(".tm-mood-reason img").count(), 0)
        await frame.locator(".tm-tab").first().click()
      })
      for (const [word, valence, arousal] of WORDS) await check(`word-${word}`, async () => {
        await refresh({ active: false, system_enabled: true, affect: { valence, arousal } })
        const expected = text[`panel.mood.word.${word}`]
        assert.equal(await frame.locator(".tm-mood-pill-word").innerText(), expected)
        assert.equal(await frame.locator(".tm-ov-mood-word").innerText(), expected)
        assert.equal(await frame.locator(".tm-status-right .neko-badge").count(), 0)
      })
      await check("no-reason-and-inactive", async () => {
        await refresh({ active: true, system_enabled: true, action: "warm_current", action_label: text["mood.warm_current"], reason: "" })
        assert.equal(await frame.locator(".tm-status-right .neko-badge").count(), 1)
        assert.equal(await frame.locator(".tm-ov-mood-chip .neko-badge").count(), 1)
        assert.equal(await frame.locator(".tm-tooltip-trigger").count(), 0)
        assert.equal(await frame.locator("body > .tm-tip").count(), 0)
        await refresh({ active: false })
        assert.equal(await frame.locator(".tm-ov-mood-chip").count(), 0)
        assert.equal(await frame.locator(".tm-status-right .neko-badge").count(), 0)
      })
      await check("system-off-and-master-off", async () => {
        await refresh({ active: true, system_enabled: false })
        assert.equal(await frame.locator(".tm-mood-pill").count(), 0)
        assert.equal(await frame.locator(".tm-ov-mood-chip").count(), 0)
        assert.equal(await frame.locator(".tm-status-right .neko-badge").count(), 0)
        await refresh({ active: true, system_enabled: true })
        await page.evaluate(() => { window.qaFixture.context.state.status.enabled = false })
        await frame.evaluate(payload => window.__NekoRefreshHostedPayload(payload), await page.evaluate(() => window.qaFixture.context))
        assert.equal(await frame.locator(".tm-mood-pill").count(), 0)
        assert.equal(await frame.locator(".tm-ov-mood-chip").count(), 0)
        assert.equal(await frame.locator(".tm-status-right .neko-badge").count(), 0)
        assert.equal(await frame.locator("body > .tm-tip").count(), 0)
      })
      assert.deepEqual(errors, [])
    } finally { await context.close() }
  }
  return { checks, screenshots }
}
