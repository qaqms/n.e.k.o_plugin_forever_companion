import assert from "node:assert/strict"
import { join } from "node:path"

export async function tooltipChecks(browser, sources, origin, output, { loadPage, inspectLayout }) {
  const checks = []
  const screenshots = []
  const cases = [
    [1280, 900, "light", "none", "zh-CN"],
    [390, 900, "dark", "none", "zh-CN"],
    [320, 400, "light", "bright", "en"],
    [1280, 300, "dark", "dark", "en"],
    [390, 360, "dark", "none", "ru"],
    [390, 900, "light", "bright", "ja"],
    [320, 900, "dark", "none", "ko"],
    [390, 900, "dark", "dark", "es"],
    [390, 900, "light", "none", "pt"],
    [390, 900, "light", "bright", "zh-TW"],
  ]
  for (const [width, height, theme, wallpaper, locale] of cases) {
    const id = `tooltip-${width}x${height}-${locale}-${theme}-${wallpaper}`
    const { page, frame, context, errors } = await loadPage(browser, origin, { locale, wallpaper, moodCase: "active" }, width, height, theme)
    const tip = frame.locator("body > .tm-tip")
    const check = async (name, operation) => {
      try { await operation(); checks.push({ name: `${id}-${name}`, passed: true }); console.log(`PASS ${id}-${name}`) }
      catch (error) { checks.push({ name: `${id}-${name}`, passed: false, error: error.stack }); console.log(`FAIL ${id}-${name}: ${error.message}`) }
    }
    const hover = async trigger => {
      await trigger.scrollIntoViewIfNeeded()
      await page.waitForTimeout(80)
      await page.mouse.move(1, 1)
      await trigger.hover()
      await tip.waitFor({ state: "visible" })
    }
    const assertVisible = async () => {
      assert.equal(await tip.count(), 1, "Only one tooltip may exist")
      const visible = await tip.evaluate(node => {
        const rect = node.getBoundingClientRect()
        const points = [[rect.left + 3, rect.top + 3], [rect.right - 3, rect.top + 3], [rect.left + 3, rect.bottom - 3], [rect.right - 3, rect.bottom - 3]]
        return {
          left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width,
          vw: innerWidth, vh: innerHeight, placement: node.dataset.placement,
          textFits: node.scrollWidth <= node.clientWidth + 1,
          uncovered: points.every(([x, y]) => node.contains(document.elementFromPoint(x, y))),
        }
      })
      assert(visible.left >= 7.5 && visible.right <= visible.vw - 7.5, `Horizontal overflow: ${JSON.stringify(visible)}`)
      assert(visible.top >= 7.5 && visible.bottom <= visible.vh - 7.5, `Vertical overflow: ${JSON.stringify(visible)}`)
      assert(visible.textFits, "Long words must wrap inside the tooltip")
      assert(visible.uncovered, `Tooltip is covered or clipped: ${JSON.stringify(visible)}`)
      return visible
    }
    const capture = async suffix => {
      const path = join(output, `${id}-${suffix}.png`)
      await page.screenshot({ path, animations: "disabled" })
      const layout = await inspectLayout(frame)
      const diagnostics = await page.evaluate(() => window.qaDiagnostics.filter(item => item.type === "neko-hosted-surface-error"))
      screenshots.push({ id: `${id}-${suffix}`, path, layout, errors: [...errors], diagnostics })
    }
    const refreshReason = async reason => {
      await page.evaluate(reason => { window.qaFixture.context.state.mood.reason = reason }, reason)
      await frame.evaluate(payload => window.__NekoRefreshHostedPayload(payload), await page.evaluate(() => window.qaFixture.context))
    }
    try {
      await check("header-hover-and-keyboard", async () => {
        const trigger = frame.locator(".tm-status-right .tm-tooltip-trigger")
        await hover(trigger)
        await assertVisible()
        assert.equal(await tip.locator("img").count(), 0)
        const tipId = await tip.getAttribute("id")
        assert.equal(await trigger.getAttribute("aria-describedby"), tipId)
        await page.mouse.move(1, 1)
        await trigger.focus()
        await assertVisible()
        await trigger.press("Tab")
        await tip.waitFor({ state: "detached" })
        assert.equal(await trigger.getAttribute("aria-describedby"), null)
      })
      await check("overview-card-clipping-and-long-text", async () => {
        const trigger = frame.locator(".tm-ov-mood-chip .tm-tooltip-trigger")
        await refreshReason("The current emotional state has a detailed explanation. ".repeat(6))
        await hover(trigger)
        await assertVisible()
        await capture("overview")
        await refreshReason("<img src=x onerror=alert(1)> " + "LongUnbrokenReason".repeat(500))
        await hover(trigger)
        await assertVisible()
        assert.equal(await tip.locator("img").count(), 0)
        assert(await tip.evaluate(node => node.scrollHeight > node.clientHeight))
        await tip.hover()
        await tip.evaluate(node => { node.scrollTop = node.scrollHeight })
        await page.waitForTimeout(80)
        assert(await tip.evaluate(node => node.scrollTop > 0), "Long explanations must remain scrollable")
        await assertVisible()
        await refreshReason("Updated explanation")
        assert.equal(await tip.innerText(), "Updated explanation", "Polling must not leave stale text")
        await trigger.focus()
        await trigger.press("Escape")
        await tip.waitFor({ state: "detached" })
      })
      await check("calendar-hover-and-button-focus", async () => {
        await frame.locator(".tm-tab").nth(1).click()
        const trigger = frame.locator(".tm-card-header .tm-tooltip-trigger")
        await hover(trigger)
        await assertVisible()
        await page.mouse.move(1, 1)
        await trigger.locator("button").focus()
        await assertVisible()
        await capture("calendar")
      })
      await frame.locator(".tm-tab").nth(3).click()
      await frame.waitForSelector(".tm-gh [data-date]")
      for (const [kind, selector, last] of [
        ["days", ".tm-hero-days", false],
        ["anniversary", ".tm-hero-ring", false],
        ["stat-first", ".tm-stat-cell", false],
        ["stat-last", ".tm-stat-cell", true],
        ["heat-first", ".tm-gh [data-date]", false],
        ["heat-last", ".tm-gh [data-date]", true],
        ["badge-first", ".tm-ach", false],
        ["badge-last", ".tm-ach", true],
      ]) {
        await check(kind, async () => {
          const target = last ? frame.locator(selector).last() : frame.locator(selector).first()
          await hover(target)
          const visible = await assertVisible()
          if (kind.startsWith("heat")) assert(visible.width >= 100, "Edge cells must not squeeze tooltips into thin columns")
          if (kind === "stat-last" && height <= 400) {
            const space = await target.evaluate(node => {
              const rect = node.getBoundingClientRect()
              return { below: innerHeight - rect.bottom - 15, above: rect.top - 15 }
            })
            const tipHeight = visible.bottom - visible.top
            if (space.below < tipHeight && space.above >= tipHeight) assert.equal(visible.placement, "top", "Insufficient space below should flip statistics upwards")
          }
          if (kind === "heat-last" || (kind === "stat-last" && height <= 400)) await capture(kind)
        })
      }
      await check("glass-scroll-resize-and-unmount", async () => {
        await frame.locator(".tm-appearance-root").evaluate(node => {
          node.style.setProperty("--tm-glass-filter", "blur(12px) saturate(1.08)")
          node.style.setProperty("--tm-card-k", "0.85")
        })
        const trigger = frame.locator(".tm-stat-cell").first()
        await hover(trigger)
        await assertVisible()
        await frame.locator(".tm-content").evaluate(node => { node.scrollTop += 17 })
        await tip.waitFor({ state: "detached" })
        await hover(trigger)
        await page.setViewportSize({ width, height: height + 20 })
        await tip.waitFor({ state: "detached" })
        await page.setViewportSize({ width, height })
        await hover(trigger)
        // A programmatic tab change exercises unmount cleanup without pointer dismissal.
        await frame.locator(".tm-tab").first().evaluate(node => node.click())
        await tip.waitFor({ state: "detached" })
      })
      await check("confirmation-dismisses-tip-and-covers-header", async () => {
        await hover(frame.locator(".tm-ov-mood-chip .tm-tooltip-trigger"))
        await frame.locator(".tm-status-right .tm-sw-input").evaluate(node => node.click())
        await frame.getByRole("dialog").waitFor()
        await tip.waitFor({ state: "detached" })
        const covered = await frame.locator(".tm-statusbar").evaluate(node => {
          const rect = node.getBoundingClientRect()
          return !!document.elementFromPoint(rect.right - 20, rect.top + rect.height / 2)?.closest(".neko-modal-backdrop")
        })
        assert(covered, "Confirmation backdrop must remain above the status bar")
        await frame.getByRole("button", { name: sources.messages[locale]["panel.cancel"], exact: true }).last().click()
        await frame.getByRole("dialog").waitFor({ state: "detached" })
        assert(await page.evaluate(() => window.qaFixture.context.state.status.enabled))
        assert.equal(await page.evaluate(() => window.qaMessages.filter(message => message.method === "call" && message.payload.actionId === "toggle").length), 0)
      })
      assert.deepEqual(errors, [])
    } finally { await context.close() }
  }
  return { checks, screenshots }
}
