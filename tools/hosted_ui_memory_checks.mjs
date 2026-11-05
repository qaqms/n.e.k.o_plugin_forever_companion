import assert from "node:assert/strict"
import { join } from "node:path"

export async function memoryChecks(browser, sources, origin, output, { loadPage, inspectLayout, pagingOnly = false }) {
  const checks = []
  const screenshots = []
  for (const locale of pagingOnly ? [] : Object.keys(sources.messages)) {
    for (const width of [1280, 390]) {
      const id = `memory-${locale}-${width}`
      const loaded = await loadPage(browser, origin, { locale, tab: "diary", wallpaper: "none" }, width, 900, width === 390 ? "dark" : "light")
      const { page, frame, context, errors } = loaded
      const label = key => sources.messages[locale][`panel.memory.${key}`]
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
      const openDetails = async () => {
        const details = frame.locator(".tm-tl-row .tm-memory").first()
        await details.waitFor()
        if (!await details.getAttribute("open").then(value => value !== null)) await details.locator(":scope > summary").click()
        return details
      }
      const choose = async action => {
        const count = await page.evaluate(() => window.qaMessages.filter(item => item.payload?.actionId === "delete_diary_item").length)
        const details = await openDetails()
        await details.locator(".tm-memory-action").selectOption(action)
        if (action !== "correct") {
          await page.waitForFunction(count => window.qaMessages.filter(item => item.payload?.actionId === "delete_diary_item").length > count, count)
          await frame.waitForFunction(() => !document.querySelector(".tm-memory-action")?.disabled)
        }
      }
      try {
        const payload = await page.evaluate(() => {
          const fixture = window.qaFixture
          fixture.diary = [{
            ts: "2026-11-01T12:00:00Z", source: "auto", kind: "like", quote: "Original coffee",
            note: "Original note", status: "active", memory_state: "active",
            memory: { schema: 1, type: "preference", confirmations: 2, last_confirmed_at: "2026-11-03T12:00:00Z",
              condition: "after lunch", evidence: [{ ts: "2026-11-03T12:00:00Z", quote: "Coffee after lunch" }],
              suggestion: { issue: "conflict", reason: "A suggestion only" } },
          }]
          window.qaRefreshDiary()
          return fixture.context
        })
        await frame.evaluate(next => window.__NekoRefreshHostedPayload(next), payload)
        await check("details-and-evidence", async () => {
          const details = await openDetails()
          assert((await details.innerText()).includes(label("active")))
          assert((await details.innerText()).includes(label("confirmations")))
          assert((await details.innerText()).includes("after lunch"))
          assert((await details.innerText()).includes("A suggestion only"))
          await details.locator(".tm-memory-fields details summary").click()
          assert((await details.innerText()).includes("Coffee after lunch"))
        })
        await check("pause-resume-and-preserve-original", async () => {
          await choose("pause")
          await frame.locator(".tm-memory > summary").filter({ hasText: label("paused") }).waitFor()
          await choose("resume")
          await frame.locator(".tm-memory > summary").filter({ hasText: label("active") }).waitFor()
          assert.equal(await frame.locator(".tm-tl-quote").innerText(), "「Original coffee」")
        })
        await check("keep-and-undo", async () => {
          await choose("pin")
          await frame.locator(".tm-memory > summary").filter({ hasText: label("pinned") }).waitFor()
          await choose("undo")
          await frame.waitForFunction(text => !document.querySelector(".tm-memory > summary").textContent.includes(text), label("pinned"))
        })
        await check("literal-correction-and-cancel", async () => {
          await choose("correct")
          await frame.locator(".tm-memory-editor textarea").fill("Unsubmitted text")
          await frame.getByRole("button", { name: label("cancel"), exact: true }).click()
          assert.equal(await page.evaluate(() => window.qaFixture.diary[0].memory.correction), undefined)
          await choose("correct")
          const correction = "<img src=x onerror=alert(1)> Tea"
          await frame.locator(".tm-memory-editor textarea").fill(correction)
          await frame.locator(".tm-memory-editor").getByRole("button", { name: label("save"), exact: true }).click()
          await frame.locator(".tm-memory-editor").waitFor({ state: "detached" })
          const details = await openDetails()
          await details.locator(".tm-memory-correction").filter({ hasText: correction }).waitFor()
          assert.equal(await details.locator("img").count(), 0)
          assert.equal(await frame.locator(".tm-tl-quote").innerText(), "「Original coffee」")
        })
        await check("failed-save-keeps-state", async () => {
          const before = await page.evaluate(() => JSON.stringify(window.qaFixture.diary))
          await page.evaluate(() => { window.qaFailNext = "delete_diary_item" })
          await choose("pause")
          await frame.waitForFunction(() => [...document.querySelectorAll(".neko-toast")].some(node => node.textContent.includes("persist_failed") || node.textContent.length > 0))
          await frame.waitForFunction(() => !document.querySelector(".tm-memory-action")?.disabled)
          assert.equal(await page.evaluate(() => JSON.stringify(window.qaFixture.diary)), before)
          assert((await frame.locator(".tm-memory > summary").innerText()).includes(label("active")))
          assert.equal(await frame.locator(".tm-memory-action").inputValue(), "choose")
        })
        await check("temporary-classification-and-date", async () => {
          const details = await openDetails()
          await details.locator(".tm-memory-fields select").selectOption("temporary")
          await frame.locator(".tm-memory > summary").filter({ hasText: label("pending") }).waitFor()
          const refreshed = await openDetails()
          await refreshed.locator('input[type="date"]').fill("2040-12-31")
          await refreshed.locator(".tm-memory-fields").getByRole("button", { name: label("save"), exact: true }).click()
          await frame.locator(".tm-memory > summary").filter({ hasText: label("active") }).waitFor()
          assert.equal(await (await openDetails()).locator(".tm-memory-fields select").inputValue(), "temporary")
          assert.equal(await frame.locator('input[type="date"]').inputValue(), "2040-12-31")
        })
        await check("archive-entry-visible-after-last-recent-record", async () => {
          await choose("archive")
          await frame.waitForFunction(() => document.querySelectorAll(".tm-tl-row").length === 0)
          for (const [scope, count] of [["recent", "0"], ["archive", "1"]]) {
            const entry = frame.locator(`#tm-memory-scope-${scope}`)
            assert(await entry.isVisible())
            assert.equal(await entry.isEnabled(), true)
            assert((await entry.innerText()).includes(label(scope)))
            assert.equal(await entry.locator(".tm-memory-scope-count").innerText(), count)
          }
          assert.equal(await frame.locator("#tm-memory-scope-recent").getAttribute("aria-selected"), "true")
          const path = join(output, `${id}-archive-entry.png`)
          await frame.waitForFunction(() => document.querySelectorAll(".neko-toast").length === 0)
          await frame.locator(".tm-memory-scopes").scrollIntoViewIfNeeded()
          await page.screenshot({ path, animations: "disabled" })
          const layout = await inspectLayout(frame)
          assert.equal(layout.documentOverflow, 0)
          assert.equal(layout.contentOverflow, 0)
          assert.deepEqual(layout.issues, [])
          screenshots.push({ id: `${id}-archive-entry`, path, layout, errors: [...errors], diagnostics: [] })
        })
        await check("archive-keyboard-retry-and-management", async () => {
          await page.evaluate(() => { window.qaFailNext = "get_diary" })
          await frame.locator("#tm-memory-scope-recent").focus()
          await frame.locator("#tm-memory-scope-recent").press("ArrowRight")
          await frame.getByRole("button", { name: label("retry"), exact: true }).waitFor()
          assert.equal(await frame.locator("#tm-memory-scope-archive").getAttribute("aria-selected"), "true")
          assert.equal(await frame.locator("#tm-memory-records").getAttribute("aria-labelledby"), "tm-memory-scope-archive")
          await frame.getByRole("button", { name: label("retry"), exact: true }).click()
          await frame.locator(".tm-tl-quote").waitFor()
          await choose("pause")
          await frame.locator(".tm-memory > summary").filter({ hasText: label("paused") }).waitFor()
          await choose("resume")
          await frame.locator(".tm-memory > summary").filter({ hasText: label("active") }).waitFor()
          await choose("unpin")
          await frame.waitForFunction(text => !document.querySelector(".tm-memory > summary").textContent.includes(text), label("pinned"))
          await choose("undo")
          await frame.locator(".tm-memory > summary").filter({ hasText: label("pinned") }).waitFor()
          const details = await openDetails()
          const path = join(output, `${id}.png`)
          await frame.waitForFunction(() => document.querySelectorAll(".neko-toast").length === 0)
          await details.scrollIntoViewIfNeeded()
          await page.screenshot({ path, animations: "disabled" })
          const layout = await inspectLayout(frame)
          assert.equal(layout.documentOverflow, 0)
          assert.equal(layout.contentOverflow, 0)
          assert.deepEqual(layout.issues, [])
          screenshots.push({ id, path, layout, errors: [...errors], diagnostics: [] })
          assert(await details.locator('option[value="unarchive"]').count())
          assert.equal(await details.locator(".tm-memory-fields select").inputValue(), "temporary")
          assert.equal(await frame.locator("#tm-memory-scope-archive").getAttribute("aria-selected"), "true")
          assert.equal(await frame.locator(".tm-tl-quote").innerText(), "「Original coffee」")
        })
        await check("unarchive-and-return-to-recent", async () => {
          await choose("unarchive")
          await frame.waitForFunction(() => document.querySelectorAll(".tm-tl-row").length === 0)
          assert.equal(await frame.locator("#tm-memory-scope-recent .tm-memory-scope-count").innerText(), "1")
          assert.equal(await frame.locator("#tm-memory-scope-archive .tm-memory-scope-count").innerText(), "0")
          await frame.locator("#tm-memory-scope-archive").focus()
          await frame.locator("#tm-memory-scope-archive").press("Home")
          await frame.locator(".tm-tl-quote").waitFor()
          assert.equal(await frame.locator("#tm-memory-scope-recent").getAttribute("aria-selected"), "true")
          assert.equal(await frame.locator(".tm-tl-quote").innerText(), "「Original coffee」")
          const call = await page.evaluate(() => window.qaMessages.filter(item => item.payload?.args?.action === "unarchive").at(-1))
          assert.equal(call.payload.actionId, "delete_diary_item")
          assert.equal(call.payload.args.expected_lanlan, payload.state.lanlan)
          assert.deepEqual(errors, [])
        })
      } catch { /* The named check records the failure; continue other locales. */ }
      finally { await context.close() }
    }
  }
  for (const width of [1280, 390]) {
    const id = `memory-paging-${width}`
    const { page, frame, context, errors } = await loadPage(browser, origin, { locale: "zh-CN", tab: "diary", wallpaper: "none" }, width, 900, "light")
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
    const refresh = async () => {
      const payload = await page.evaluate(() => { window.qaRefreshDiary(); return window.qaFixture.context })
      await frame.evaluate(next => window.__NekoRefreshHostedPayload(next), payload)
    }
    const callCount = () => page.evaluate(() => window.qaMessages.filter(item => item.payload?.actionId === "get_diary").length)
    try {
      await page.evaluate(() => {
        window.qaFixture.diary = Array.from({ length: 146 }, (_, index) => ({
          ts: new Date(Date.UTC(2026, 10, 4, 12, 0, -index)).toISOString(),
          source: "auto", kind: "like", quote: `memory-${index}`, status: "active", memory_state: "active",
          memory: { schema: 1, type: "preference", confirmations: 1 },
        }))
      })
      await refresh()
      await check("poll-keeps-pages-details-and-unsaved-correction", async () => {
        await frame.locator(".tm-diary-more button").click()
        await frame.waitForFunction(() => document.querySelectorAll(".tm-tl-row").length === 62)
        await frame.locator(".tm-diary-more button").click()
        await frame.waitForFunction(() => document.querySelectorAll(".tm-tl-row").length === 112)
        const details = frame.locator(".tm-memory").first()
        await details.locator(":scope > summary").click()
        await details.locator(".tm-memory-action").selectOption("correct")
        await details.locator("textarea").fill("Unsaved correction")
        const before = await callCount()
        for (let index = 0; index < 3; index++) await refresh()
        await frame.waitForTimeout(100)
        assert.equal(await callCount(), before)
        assert.equal(await frame.locator(".tm-tl-row").count(), 112)
        assert.equal(await details.locator("textarea").inputValue(), "Unsaved correction")
        await page.evaluate(() => { window.qaFixture.diary[0].memory.paused = true; window.qaFixture.diary[0].memory_state = "paused" })
        await refresh()
        await frame.waitForFunction(text => document.querySelector(".tm-memory > summary").textContent.includes(text), sources.messages["zh-CN"]["panel.memory.paused"])
        await frame.waitForFunction(() => !document.querySelector(".tm-memory-scope-tab").disabled)
        assert.equal(await frame.locator(".tm-tl-row").count(), 112)
        assert.equal(await details.locator("textarea").inputValue(), "Unsaved correction")
      })
      await check("management-beyond-preview-preserves-loaded-pages", async () => {
        const details = frame.locator(".tm-memory").nth(100)
        await details.locator(":scope > summary").click()
        await details.locator(".tm-memory-action").selectOption("pin")
        await details.locator(":scope > summary").filter({ hasText: sources.messages["zh-CN"]["panel.memory.pinned"] }).waitFor()
        await frame.waitForFunction(() => !document.querySelector(".tm-memory-scope-tab").disabled)
        assert.equal(await frame.locator(".tm-tl-row").count(), 112)
        assert.equal(await details.locator(".tm-memory-action").inputValue(), "choose")
        assert.equal(await page.evaluate(() => window.qaFixture.diary[100].memory.pinned), true)
      })
      await check("late-archive-reply-cannot-replace-other-role", async () => {
        await page.evaluate(() => { window.qaHoldReplies.get_diary = true })
        await frame.locator("#tm-memory-scope-archive").click()
        await page.waitForFunction(() => window.qaHeldReplies.get_diary?.length > 0)
        await page.evaluate(() => {
          window.qaFixture.context.state.lanlan = "Other role"
          window.qaFixture.diary = [{ ts: "other", source: "self", entry: "Other role diary" }]
        })
        await refresh()
        await frame.locator(".tm-tl-entry").filter({ hasText: "Other role diary" }).waitFor()
        await page.evaluate(() => window.qaReleaseHeldReplies("get_diary"))
        await frame.waitForTimeout(100)
        assert.equal(await frame.locator(".tm-tl-row").count(), 1)
        assert.equal(await frame.locator(".tm-tl-entry").innerText(), "Other role diary")
        assert.deepEqual(errors, [])
      })
    } catch { /* Continue the other viewport after recording the named failure. */ }
    finally { await context.close() }
  }
  return { checks, screenshots }
}
