import assert from "node:assert/strict"
import { join } from "node:path"

export async function navigationChecks(browser, sources, origin, output, { loadPage, inspectLayout }) {
  const checks = []
  const screenshots = []
  for (const width of [1280, 390]) for (const height of [360, 480]) for (const theme of ["light", "dark"]) {
    const id = `navigation-${width}x${height}-${theme}`
    const loaded = await loadPage(browser, origin, { locale: "zh-CN", wallpaper: "none" }, width, height, theme)
    const { frame, page } = loaded
    const navigation = frame.locator(".tm-tabs")
    async function capture(suffix) {
      const path = join(output, `${id}-${suffix}.png`)
      const layout = await inspectLayout(frame)
      const diagnostics = await page.evaluate(() => window.qaDiagnostics.filter(message => message.type === "neko-hosted-surface-error"))
      await page.screenshot({ path, animations: "disabled" })
      screenshots.push({ id: `${id}-${suffix}`, path, layout, errors: [...loaded.errors], diagnostics })
      assert(layout.documentOverflow <= 2 && layout.contentOverflow <= 2, "Horizontal overflow")
      assert.deepEqual(layout.issues, [], "Clipped controls")
      assert.deepEqual(loaded.errors, [], "Browser errors")
      assert.deepEqual(diagnostics, [], "Hosted runtime errors")
    }
    async function remember() {
      return navigation.evaluate(element => {
        window.qaNavigationNode = element
        window.qaNavigationButtons = [...element.querySelectorAll(".tm-tab")]
        return element.scrollTop
      })
    }
    async function assertPreserved(before, index) {
      const after = await navigation.evaluate(element => ({
        sameNode: element === window.qaNavigationNode,
        sameButtons: [...element.querySelectorAll(".tm-tab")].every((button, index) => button === window.qaNavigationButtons[index]),
        scrollTop: element.scrollTop,
        active: [...element.querySelectorAll(".tm-tab")].findIndex(button => button.classList.contains("tm-tab-active")),
        focused: [...element.querySelectorAll(".tm-tab")].indexOf(document.activeElement),
      }))
      assert(after.sameNode, "Switching modules replaced the sidebar DOM")
      assert(after.sameButtons, "Switching modules replaced navigation buttons")
      assert(Math.abs(after.scrollTop - before) <= 1, `Sidebar jumped from ${before} to ${after.scrollTop}`)
      assert.equal(after.active, index)
      assert.equal(after.focused, index, "Navigation lost focus")
    }
    try {
      const size = await navigation.evaluate(element => {
        element.scrollTop = element.scrollHeight
        return { scrollHeight: element.scrollHeight, clientHeight: element.clientHeight, scrollTop: element.scrollTop }
      })
      assert(size.scrollTop > 0, `Fixture must overflow vertically: ${JSON.stringify(size)}`)
      await capture("before")
      // Bottom modules expose the scroll reset without programmatic clicks.
      for (const index of [7, 6, 5, 4, 7]) {
        const button = frame.locator(".tm-tab").nth(index)
        await button.scrollIntoViewIfNeeded()
        const before = await remember()
        await button.click()
        await frame.waitForTimeout(100)
        await assertPreserved(before, index)
      }
      await capture("after-switches")
      const beforeRefresh = await remember()
      const context = await page.evaluate(() => window.qaFixture.context)
      await frame.evaluate(context => window.__NekoRefreshHostedPayload(context), context)
      await frame.waitForTimeout(100)
      await assertPreserved(beforeRefresh, 7)
      const keyboardTarget = frame.locator(".tm-tab").nth(6)
      await keyboardTarget.focus()
      await keyboardTarget.scrollIntoViewIfNeeded()
      const beforeKeyboard = await remember()
      await keyboardTarget.press("Enter")
      await frame.waitForTimeout(100)
      await assertPreserved(beforeKeyboard, 6)
      const bounds = await navigation.boundingBox()
      const beforeWheel = await navigation.evaluate(element => element.scrollTop)
      await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
      await page.mouse.wheel(0, -100)
      await frame.waitForFunction(before => document.querySelector(".tm-tabs").scrollTop < before, beforeWheel)
      // Newly mounted content still starts at the top independently of the sidebar.
      await frame.locator(".tm-content").evaluate(element => { element.scrollTop = element.scrollHeight })
      const last = frame.locator(".tm-tab").nth(7)
      await last.scrollIntoViewIfNeeded()
      const beforeLast = await remember()
      await last.click()
      await frame.waitForTimeout(100)
      await assertPreserved(beforeLast, 7)
      assert.equal(await frame.locator(".tm-content").evaluate(element => element.scrollTop), 0)
      await capture("after-keyboard-and-wheel")
      checks.push({ name: id, passed: true })
      console.log(`PASS ${id}`)
    } catch (error) {
      checks.push({ name: id, passed: false, error: error.stack })
      console.log(`FAIL ${id}: ${error.message}`)
    } finally { await loaded.context.close() }
  }
  return { checks, screenshots }
}
