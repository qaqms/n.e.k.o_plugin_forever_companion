import assert from "node:assert/strict"
import { join } from "node:path"

export async function chooseOption(frame, control, value) {
  await control.click()
  await frame.locator(`.tm-select-menu [role="option"][data-value=${JSON.stringify(String(value))}]`).click()
}

export async function selectChecks(browser, sources, origin, output, { loadPage, inspectLayout, quick = false, edgesOnly = false }) {
  const checks = []
  const screenshots = []
  const locales = edgesOnly ? [] : quick ? ["zh-CN"] : Object.keys(sources.messages)
  for (const locale of locales) for (const width of [1280, 390]) {
    const id = `select-${locale}-${width}`
    const loaded = await loadPage(browser, origin, { locale, tab: "cycle", wallpaper: width === 390 ? "bright" : "none" }, width, 900, width === 390 ? "dark" : "light")
    const { page, frame, context, errors } = loaded
    const text = sources.messages[locale]
    const check = async (name, operation) => {
      try {
        await operation()
        checks.push({ name: `${id}-${name}`, passed: true })
        console.log(`PASS ${id}-${name}`)
      } catch (error) {
        checks.push({ name: `${id}-${name}`, passed: false, error: error.stack })
        console.log(`FAIL ${id}-${name}: ${error.message}`)
        throw error
      }
    }
    const capture = async suffix => {
      const path = join(output, `${id}-${suffix}.png`)
      const geometry = await frame.locator(".tm-select-menu").evaluate(menu => {
        const rect = menu.getBoundingClientRect()
        const option = [...menu.children].find(child => {
          const bounds = child.getBoundingClientRect()
          return bounds.top >= rect.top && bounds.bottom <= rect.bottom
        })
        const target = option?.getBoundingClientRect() || rect
        const hit = document.elementFromPoint(target.left + target.width / 2, target.top + target.height / 2)
        const style = getComputedStyle(menu)
        return {
          left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
          width: innerWidth, height: innerHeight, hit: menu.contains(hit),
          inCard: !!menu.closest(".neko-card,.tm-card"), color: style.color,
          background: style.backgroundColor, radius: style.borderRadius, shadow: style.boxShadow,
        }
      })
      assert(geometry.left >= 0 && geometry.right <= geometry.width && geometry.top >= 0 && geometry.bottom <= geometry.height, JSON.stringify(geometry))
      assert(geometry.hit && !geometry.inCard, JSON.stringify(geometry))
      assert.notEqual(geometry.color, geometry.background)
      assert.notEqual(geometry.background, "rgba(0, 0, 0, 0)")
      assert.notEqual(geometry.shadow, "none")
      assert.equal(geometry.radius, "8px")
      const layout = await inspectLayout(frame)
      assert.equal(layout.documentOverflow, 0)
      assert.equal(layout.contentOverflow, 0)
      assert.deepEqual(layout.issues, [])
      await page.screenshot({ path, animations: "disabled" })
      screenshots.push({ id: `${id}-${suffix}`, path, layout, errors: [...errors], diagnostics: [], geometry })
    }
    try {
      const inject = frame.getByRole("combobox", { name: text["panel.settings.injectMode"], exact: true })
      await check("styled-popup-and-selection", async () => {
        assert.equal(await frame.locator("select").count(), 0)
        await inject.click()
        assert.equal(await inject.getAttribute("aria-expanded"), "true")
        assert.equal(await frame.getByRole("listbox").count(), 1)
        const value = await inject.getAttribute("data-value")
        assert.equal(await frame.locator(`.tm-select-option[data-value=${JSON.stringify(value)}]`).getAttribute("aria-selected"), "true")
        await capture("inject")
        await frame.locator('.tm-select-option[data-value="off"]').click()
        assert.equal(await inject.getAttribute("data-value"), "off")
        assert.equal(await frame.getByRole("listbox").count(), 0)
        await chooseOption(frame, inject, "interval_n")
      })
      await check("keyboard-cancel-commit-and-tab", async () => {
        await inject.focus()
        await inject.press("ArrowDown")
        await inject.press("End")
        const active = await inject.getAttribute("aria-activedescendant")
        assert.equal(await frame.locator(`[id=${JSON.stringify(active)}]`).getAttribute("data-value"), "off")
        await inject.press("Escape")
        assert.equal(await inject.getAttribute("data-value"), "interval_n")
        assert(await inject.evaluate(element => document.activeElement === element))
        await inject.press("ArrowUp")
        await inject.press("Home")
        await inject.press("Enter")
        assert.equal(await inject.getAttribute("data-value"), "every_user_message")
        await inject.press("Enter")
        await inject.press("Tab")
        assert.equal(await frame.getByRole("listbox").count(), 0)
        assert(!await inject.evaluate(element => document.activeElement === element))
      })
      await check("outside-scroll-and-page-change-dismiss", async () => {
        await inject.click()
        await frame.locator(".neko-card-title").first().click()
        assert.equal(await frame.getByRole("listbox").count(), 0)
        await inject.click()
        await frame.locator(".tm-content").evaluate(element => element.dispatchEvent(new Event("scroll")))
        await frame.waitForFunction(() => !document.querySelector(".tm-select-menu"))
        await inject.click()
        await frame.locator(".tm-tab").nth(4).click()
        assert.equal(await frame.getByRole("listbox").count(), 0)
      })
      await check("model-slots-empty-value-and-long-labels", async () => {
        const channels = frame.locator(".tm-channel-control .tm-select")
        assert.equal(await channels.count(), 5)
        await chooseOption(frame, channels.nth(0), "agent")
        await chooseOption(frame, channels.nth(0), "")
        assert.equal(await channels.nth(0).getAttribute("data-value"), "")
        await channels.nth(0).click()
        assert.equal(await frame.locator('.tm-select-option[data-value=""]').getAttribute("aria-selected"), "true")
        await capture("models")
        await channels.nth(0).press("Escape")
        await chooseOption(frame, channels.nth(2), "custom")
        await chooseOption(frame, channels.nth(3), "conversation")
        await chooseOption(frame, channels.nth(3), "agent")
        await frame.locator(".tm-save button").click()
        await page.waitForFunction(() => window.qaFixture.context.state.settings.fragments_mode === "custom")
        assert.equal(await page.evaluate(() => window.qaFixture.context.state.settings.tone_slot), "")
        assert.equal(await page.evaluate(() => window.qaFixture.context.state.settings.review_slot), "agent")
      })
      await check("timezone-typeahead-and-refresh", async () => {
        await frame.locator(".tm-tab").nth(7).click()
        await frame.locator("#tm-settings-tab-general").click()
        const timezone = frame.locator("#tm-settings-general .tm-select")
        await timezone.click()
        await timezone.press("e")
        await timezone.press("Enter")
        assert.equal(await timezone.getAttribute("data-value"), "Europe/London")
        await chooseOption(frame, timezone, "Asia/Tokyo")
        const payload = await page.evaluate(() => window.qaFixture.context)
        await frame.evaluate(next => window.__NekoRefreshHostedPayload(next), payload)
        assert.equal(await timezone.getAttribute("data-value"), "Asia/Tokyo")
        await timezone.click()
        await capture("timezone")
        await timezone.press("Escape")
      })
      await check("memory-actions-remain-user-initiated", async () => {
        const payload = await page.evaluate(() => {
          window.qaFixture.diary = [{
            ts: "2026-11-01T12:00:00Z", source: "auto", kind: "like", quote: "Original memory",
            status: "active", memory_state: "active", memory: { schema: 1, type: "preference" },
          }]
          window.qaRefreshDiary()
          return window.qaFixture.context
        })
        await frame.evaluate(next => window.__NekoRefreshHostedPayload(next), payload)
        await frame.locator(".tm-tab").nth(2).click()
        await frame.locator(".tm-memory > summary").click()
        const type = frame.locator(".tm-memory-fields .tm-select")
        await chooseOption(frame, type, "preference")
        await type.click()
        await capture("memory")
        await frame.locator('.tm-select-option[data-value="event"]').click()
        await frame.waitForFunction(() => document.querySelector(".tm-memory-fields .tm-select")?.dataset.value === "event")
        const control = frame.locator(".tm-memory-action")
        await chooseOption(frame, control, "pause")
        await frame.locator(".tm-memory > summary").filter({ hasText: text["panel.memory.paused"] }).waitFor()
        assert.equal(await control.getAttribute("data-value"), "")
        const calls = await page.evaluate(() => window.qaMessages.filter(message => message.payload?.actionId === "delete_diary_item"))
        assert.equal(calls.length, 2)
        assert(calls.every(call => call.userInitiated === true), JSON.stringify(calls))
        assert.equal(calls[0].payload.args.action, "classify")
        assert.equal(calls[1].payload.args.action, "pause")
        await control.click()
        await capture("commands")
        await control.press("Escape")
        assert.deepEqual(errors, [])
      })
    } catch { /* The named check records failures; continue other viewports. */ }
    finally { await context.close() }
  }
  for (const width of [900, 390]) {
    const id = `select-edge-${width}`
    const { page, frame, context, errors } = await loadPage(browser, origin, { locale: "zh-CN", tab: "cycle", wallpaper: "none" }, width, 480, width === 390 ? "light" : "dark")
    const check = async (name, operation) => {
      try {
        await operation()
        checks.push({ name: `${id}-${name}`, passed: true })
        console.log(`PASS ${id}-${name}`)
      } catch (error) {
        checks.push({ name: `${id}-${name}`, passed: false, error: error.stack })
        console.log(`FAIL ${id}-${name}: ${error.message}`)
        throw error
      }
    }
    try {
      await check("short-viewport-opens-upward", async () => {
        const trigger = frame.getByRole("combobox").first()
        await trigger.scrollIntoViewIfNeeded()
        await trigger.evaluate(element => {
          element.focus({ preventScroll: true })
          const content = document.querySelector(".tm-content")
          content.scrollTop += element.getBoundingClientRect().bottom - (innerHeight - 72)
        })
        await frame.waitForTimeout(80)
        await trigger.press("ArrowDown")
        const menu = frame.getByRole("listbox")
        const anchor = await trigger.boundingBox()
        assert.equal(await menu.getAttribute("data-placement"), "top", JSON.stringify(anchor))
        const bounds = await menu.boundingBox()
        assert(bounds.y >= 0 && bounds.y + bounds.height <= 480, JSON.stringify(bounds))
        const layout = await inspectLayout(frame)
        assert.deepEqual(layout.issues, [])
        const path = join(output, `${id}-upward.png`)
        await page.screenshot({ path, animations: "disabled" })
        screenshots.push({ id, path, layout, errors: [...errors], diagnostics: [] })
        await trigger.press("Escape")
      })
      await frame.locator(".tm-tab").nth(7).click()
      await frame.locator("#tm-settings-tab-general").click()
      const timezone = frame.locator("#tm-settings-general .tm-select")
      await check("list-scroll-does-not-dismiss", async () => {
        await timezone.click()
        const menu = frame.getByRole("listbox")
        assert(await menu.evaluate(element => element.scrollHeight > element.clientHeight))
        await menu.evaluate(element => { element.scrollTop = 90 })
        await frame.waitForFunction(() => document.querySelector(".tm-select-menu")?.scrollTop > 0)
        assert.equal(await timezone.getAttribute("aria-expanded"), "true")
        await timezone.press("Escape")
      })
      await check("disabled-owner-dismisses", async () => {
        await timezone.click()
        await timezone.evaluate(element => { element.disabled = true })
        await frame.waitForFunction(() => !document.querySelector(".tm-select-menu"))
        assert.equal(await timezone.getAttribute("aria-expanded"), "false")
        await timezone.evaluate(element => { element.disabled = false })
      })
      await check("role-change-dismisses-without-submitting", async () => {
        const before = await page.evaluate(() => window.qaMessages.filter(message => message.method === "call" && message.payload.actionId === "update_settings").length)
        await timezone.click()
        const payload = await page.evaluate(() => {
          window.qaFixture.context.state.lanlan = "Other role"
          return window.qaFixture.context
        })
        await frame.evaluate(next => window.__NekoRefreshHostedPayload(next), payload)
        await frame.waitForFunction(() => !document.querySelector(".tm-select-menu"))
        assert.equal(await timezone.getAttribute("aria-expanded"), "false")
        assert.equal(await page.evaluate(() => window.qaMessages.filter(message => message.method === "call" && message.payload.actionId === "update_settings").length), before)
        assert.deepEqual(errors, [])
      })
    } catch { /* Continue the other viewport after recording the named failure. */ }
    finally { await context.close() }
  }
  return { checks, screenshots }
}
