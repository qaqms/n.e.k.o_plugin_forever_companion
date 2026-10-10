import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { createHash } from "node:crypto"
import { copyFileSync, createReadStream, mkdtempSync, rmSync, statSync } from "node:fs"
import { tmpdir } from "node:os"
import { basename, dirname, join, resolve } from "node:path"
import { recordFixture, largeFixture } from "./hosted_ui_video_checks.mjs"

const VIDEO = "video.tm-bg-video"

async function startProbe(pluginRoot, hostRoot, directory) {
  const child = spawn(join(hostRoot, ".venv/Scripts/python.exe"), [
    "-B", join(pluginRoot, "tools/playback_route_probe.py"),
    "--host", hostRoot, "--directory", directory,
  ], { windowsHide: true, stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } })
  let stderr = ""
  child.stderr.on("data", chunk => { stderr += chunk.toString() })
  try {
    const port = await new Promise((resolve, reject) => {
      let stdout = ""
      const timer = setTimeout(() => reject(new Error(`Playback probe startup timeout: ${stderr}`)), 10000)
      child.once("exit", code => { clearTimeout(timer); reject(new Error(`Playback probe exited ${code}: ${stderr}`)) })
      child.once("error", error => { clearTimeout(timer); reject(error) })
      child.stdout.on("data", chunk => {
        stdout += chunk.toString()
        if (stdout.includes("\n")) {
          clearTimeout(timer)
          try { resolve(JSON.parse(stdout.split("\n")[0]).port) } catch (error) { reject(error) }
        }
      })
    })
    return { child, port }
  } catch (error) { child.kill(); throw error }
}

async function destroyAndReopen(loaded) {
  const removed = loaded.page.waitForEvent("framedetached", { predicate: frame => frame === loaded.frame })
  await loaded.page.locator("#hosted").evaluate(old => {
    window.qaOldSrcdoc = old.srcdoc
    old.remove()
  })
  await removed
  assert.equal(loaded.page.frames().length, 1)
  const attached = loaded.page.waitForEvent("frameattached")
  await loaded.page.evaluate(() => {
    const next = document.createElement("iframe")
    next.id = "hosted"
    next.setAttribute("sandbox", "allow-scripts")
    document.body.appendChild(next)
    next.srcdoc = window.qaOldSrcdoc
  })
  loaded.frame = await attached
  await loaded.frame.waitForSelector(".tm-tabs")
}

async function assertDirectMoving(loaded) {
  await loaded.frame.waitForFunction(() => {
    const video = document.querySelector("video.tm-bg-video")
    return video && video.readyState >= 2 && !video.paused && Number(getComputedStyle(video).opacity) > 0.99
  }, null, { timeout: 12000 })
  const state = () => loaded.frame.locator(VIDEO).evaluate(video => ({
    time: video.currentTime, width: video.videoWidth, height: video.videoHeight,
    source: video.currentSrc, muted: video.muted, loop: video.loop,
  }))
  const first = await state()
  // HTTP video in an opaque iframe correctly taints a canvas. Read rendered
  // pixels through isolated browser screenshots instead of weakening CORS.
  const before = await loaded.page.screenshot({ animations: "disabled" })
  await loaded.frame.waitForTimeout(470)
  const after = await loaded.page.screenshot({ animations: "disabled" })
  const second = await state()
  assert.notEqual(first.time, second.time)
  assert.notEqual(createHash("sha256").update(before).digest("hex"), createHash("sha256").update(after).digest("hex"))
  assert(second.width >= 320 && second.height >= 180 && second.muted && second.loop)
  return second
}

async function chunks(loaded) {
  return loaded.page.evaluate(() => window.qaMessages.filter(message =>
    message.payload?.actionId === "get_gallery_image" && message.payload.args.chunk_index >= 0))
}

export async function directChecks(browser, sources, origin, output, helpers) {
  const { loadPage, inspectLayout, pluginRoot, hostRoot } = helpers
  const checks = []
  const screenshots = []
  const measurements = []
  const fixture = largeFixture(await recordFixture(browser, output), output)
  sources.qaVideoFixture = fixture.source
  sources.qaDirectPath = `/plugin/forever_companion/ui/${fixture.sha256}.webm`
  sources.qaDirectRequests = []
  const directory = mkdtempSync(join(tmpdir(), "neko-direct-playback-"))
  copyFileSync(fixture.assetPath, join(directory, `${fixture.sha256}.webm`))
  const probe = await startProbe(pluginRoot, hostRoot, directory)
  sources.qaPlaybackPort = probe.port
  async function check(name, operation) {
    try {
      await operation()
      checks.push({ name, passed: true })
      console.log(`PASS ${name}`)
    } catch (error) {
      checks.push({ name, passed: false, error: error.stack })
      console.log(`FAIL ${name}: ${error.message}`)
    }
  }
  try {
    await check("direct-host-route-range-mime-cache-and-traversal", async () => {
      const range = await fetch(`${origin}${sources.qaDirectPath}`, { headers: { Range: "bytes=0-255" } })
      assert.equal(range.status, 206)
      assert.equal(range.headers.get("content-type"), "video/webm")
      assert.equal(range.headers.get("accept-ranges"), "bytes")
      assert.equal(range.headers.get("cache-control"), "private, no-cache, max-age=0, must-revalidate")
      assert.equal((await range.arrayBuffer()).byteLength, 256)
      const invalid = await fetch(`${origin}${sources.qaDirectPath}`, { headers: { Range: `bytes=${fixture.size}-` } })
      assert.equal(invalid.status, 416)
      const traversal = await fetch(`http://127.0.0.1:${probe.port}/plugin/forever_companion/ui/..%2Fprivate.db`)
      assert.equal(traversal.status, 403)
    })
    for (const width of [1280, 390]) {
      const started = Date.now()
      const loaded = await loadPage(browser, origin, { locale: "en", wallpaper: "video", direct: "true" }, width, width === 390 ? 700 : 900, "light", "no-preference")
      try {
        await check(`direct-${width}-large-video-without-blob-or-chunk-rpc`, async () => {
          const moving = await assertDirectMoving(loaded)
          measurements.push({ width, phase: "initial", elapsedIncludingPixelChecksMs: Date.now() - started, bytes: fixture.size })
          assert.equal(moving.source, `${origin}${sources.qaDirectPath}`)
          assert.equal((await chunks(loaded)).length, 0)
          assert.equal(await loaded.page.locator("#hosted").getAttribute("sandbox"), "allow-scripts")
          const path = join(output, `direct-${width}-playing.png`)
          await loaded.page.screenshot({ path, animations: "disabled" })
          screenshots.push({ id: `direct-${width}`, path, layout: await inspectLayout(loaded.frame), errors: [...loaded.errors], diagnostics: [] })
        })
        for (let round = 0; round < 2; round++) {
          await check(`direct-${width}-destroyed-iframe-reopen-${round + 1}`, async () => {
            const before = loaded.frame
            const started = Date.now()
            await destroyAndReopen(loaded)
            assert.notEqual(loaded.frame, before)
            assert(before.isDetached())
            await assertDirectMoving(loaded)
            measurements.push({ width, phase: `reopen-${round + 1}`, elapsedIncludingPixelChecksMs: Date.now() - started, bytes: fixture.size })
            assert.equal((await chunks(loaded)).length, 0)
          })
        }
        await check(`direct-${width}-context-refresh-retains-playing-node`, async () => {
          await loaded.frame.locator(VIDEO).evaluate(video => { window.qaDirectNode = video })
          await loaded.frame.evaluate(() => window.NekoUiKit.api.refresh())
          assert(await loaded.frame.locator(VIDEO).evaluate(video => video === window.qaDirectNode))
          await assertDirectMoving(loaded)
        })
        await check(`direct-${width}-runtime-error-recovers-once-through-blob`, async () => {
          await loaded.frame.locator(VIDEO).evaluate(video => video.dispatchEvent(new Event("error")))
          await loaded.frame.waitForFunction(() => document.querySelector("video.tm-bg-video")?.currentSrc.startsWith("blob:"), null, { timeout: 15000 })
          await assertDirectMoving(loaded)
          assert((await chunks(loaded)).length > 0)
          const requests = await loaded.page.evaluate(() => window.qaMessages.filter(message =>
            message.payload?.actionId === "get_gallery_image" && message.payload.args.prefer_direct === false))
          assert(requests.length >= 1)
        })
      } finally { await loaded.context.close() }
    }
    for (const direct of ["missing", "unsafe"]) {
      const loaded = await loadPage(browser, origin, { locale: "en", wallpaper: "video", direct }, 1280, 900, "light", "no-preference")
      try {
        await check(`direct-${direct}-endpoint-falls-back-to-real-blob`, async () => {
          const moving = await assertDirectMoving(loaded)
          assert(moving.source.startsWith("blob:"))
          assert((await chunks(loaded)).length > 0)
        })
      } finally { await loaded.context.close() }
    }
    const reduced = await loadPage(browser, origin, { locale: "en", wallpaper: "video", direct: "true" }, 390, 700, "light", "reduce")
    try {
      await check("direct-reduced-motion-does-not-request-or-prepare-video", async () => {
        assert.equal((await chunks(reduced)).length, 0)
        assert.equal(await reduced.frame.locator(VIDEO).count(), 0)
        const requests = await reduced.page.evaluate(() => window.qaMessages.filter(message =>
          message.payload?.actionId === "get_gallery_image" && message.payload.args.prefer_direct === true))
        assert.equal(requests.length, 0)
      })
    } finally { await reduced.context.close() }
    const actualIndex = process.argv.indexOf("--actual-video")
    if (actualIndex >= 0) {
      const actualPath = resolve(process.argv[actualIndex + 1])
      const hash = createHash("sha256")
      for await (const block of createReadStream(actualPath)) hash.update(block)
      const name = `${hash.digest("hex")}.mp4`
      copyFileSync(actualPath, join(directory, name))
      const size = statSync(actualPath).size
      sources.qaDirectPath = `/plugin/forever_companion/ui/${name}`
      sources.qaVideoFixture = { ...fixture.source, mime: "video/mp4", size,
        chunks: Array(Math.ceil(size / (768 * 1024))).fill("") }
      const started = Date.now()
      const actual = await loadPage(browser, origin, { locale: "en", wallpaper: "video", direct: "true" }, 1280, 900, "light", "no-preference")
      try {
        await check("direct-actual-video-read-only-temporary-copy-and-reopen", async () => {
          await assertDirectMoving(actual)
          measurements.push({ phase: "actual-initial", bytes: size, elapsedIncludingPixelChecksMs: Date.now() - started })
          const restart = Date.now()
          await destroyAndReopen(actual)
          const moving = await assertDirectMoving(actual)
          assert.equal(moving.source, `${origin}${sources.qaDirectPath}`)
          assert.equal((await chunks(actual)).length, 0)
          measurements.push({ phase: "actual-reopen", bytes: size, width: moving.width, height: moving.height,
            elapsedIncludingPixelChecksMs: Date.now() - restart })
        })
      } finally { await actual.context.close() }
    }
    assert(sources.qaDirectRequests.some(request => request.status === 206 && request.range), "Browser did not exercise HTTP Range")
    measurements.push({ httpRequests: sources.qaDirectRequests })
  } finally {
    sources.qaPlaybackPort = null
    const finished = new Promise(resolve => probe.child.once("exit", resolve))
    probe.child.kill()
    await finished
    assert.equal(dirname(resolve(directory)), resolve(tmpdir()))
    assert(basename(directory).startsWith("neko-direct-playback-"))
    rmSync(directory, { recursive: true, force: true })
  }
  return { checks, screenshots, measurements }
}
