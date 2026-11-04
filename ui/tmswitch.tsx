// 动画开关（1.3.1）：面板全部"是/否"类开关的统一自绘组件，替换宿主 Kit 的
// Switch（那枚本质是 16px 原生 checkbox、零动画）。经典顺滑型：滑块 0.25s
// 缓动平移 + 轨道渐变换色；开启态浅蓝色系，与面板淡蓝磨砂底（rgba(147,197,253)
// 弥散光）同族。样式在 styles.ts 的 .tm-sw 段（含暗色孪生）。
//
// 乐观回滚契约（状态条/功能管理这类"点击后经确认+服务端往返才落定"的开关需要）：
// onChange 可返回 Promise——resolve 值 === false（取消/失败/被拒）时开关立即回落
// 到权威值 checked；其余情况本地保持，待父级刷新后 checked 变化时自动收编。
// 同步表单类调用点（设置页 updateForm）checked 立刻变化，天然满足。
import { h, useEffect, useRef, useState } from "@neko/plugin-ui"

// Shared custom controls stay in one module to respect the host's dependency limit.
let activeTip: { owner: HTMLElement; node: HTMLElement; close: () => void } | null = null
let tipSequence = 0

function closeAdaptiveTip(owner?: HTMLElement | null) {
  if (activeTip && (!owner || activeTip.owner === owner)) activeTip.close()
}

export function AdaptiveTip(props: { key?: string; content: string; place?: string; inline?: boolean; children?: any }) {
  const ref = useRef<HTMLElement | null>(null)
  const scheduleRef = useRef<(() => void) | null>(null)
  const show = () => {
    const owner = ref.current
    if (!owner) return
    closeAdaptiveTip()
    const modal = document.querySelector(".neko-modal-backdrop")
    if (!props.content || (modal && !modal.contains(owner))) return

    // Body placement avoids card clipping and transformed containing blocks.
    const node = document.createElement("span")
    node.className = props.inline ? "tm-tip tm-tip-detail" : "tm-tip"
    node.id = `tm-tooltip-${++tipSequence}`
    node.setAttribute("role", "tooltip")
    node.textContent = props.content
    node.style.visibility = "hidden"
    node.style.left = "0px"
    node.style.top = "0px"
    document.body.appendChild(node)

    const margin = 8
    const gap = 7
    const vw = document.documentElement.clientWidth
    const vh = document.documentElement.clientHeight
    node.style.maxWidth = `${Math.max(1, Math.min(props.inline ? 280 : 240, vw - margin * 2))}px`
    node.style.maxHeight = `${Math.max(1, vh - margin * 2)}px`
    const r = owner.getBoundingClientRect()
    const height = node.getBoundingClientRect().height
    const above = Math.max(0, r.top - gap - margin)
    const below = Math.max(0, vh - r.bottom - gap - margin)
    const preferBelow = props.place === "bottom"
    const onBottom = preferBelow
      ? below >= height || (above < height && below >= above)
      : !(above >= height || (below < height && above >= below))
    node.style.maxHeight = `${Math.max(1, onBottom ? below : above)}px`
    const bounds = node.getBoundingClientRect()
    const x = Math.max(margin, Math.min(vw - margin - bounds.width, r.left + r.width / 2 - bounds.width / 2))
    const y = Math.max(margin, Math.min(vh - margin - bounds.height, onBottom ? r.bottom + gap : r.top - gap - bounds.height))
    node.style.left = `${x}px`
    node.style.top = `${y}px`
    node.style.visibility = ""
    node.dataset.placement = onBottom ? "bottom" : "top"
    if (node.scrollHeight > node.clientHeight) node.tabIndex = 0
    owner.setAttribute("aria-describedby", [owner.getAttribute("aria-describedby"), node.id].filter(Boolean).join(" "))

    let timer: ReturnType<typeof setTimeout> | null = null
    const cancelClose = () => { if (timer !== null) clearTimeout(timer); timer = null }
    const close = () => {
      cancelClose()
      window.removeEventListener("scroll", onScroll, true)
      window.removeEventListener("resize", close)
      window.removeEventListener("blur", close)
      window.removeEventListener("pointerdown", onPointerDown, true)
      window.removeEventListener("keydown", onKeyDown, true)
      document.removeEventListener("visibilitychange", onVisibilityChange)
      observer.disconnect()
      const ids = (owner.getAttribute("aria-describedby") || "").split(/\s+/).filter(id => id && id !== node.id)
      if (ids.length) owner.setAttribute("aria-describedby", ids.join(" "))
      else owner.removeAttribute("aria-describedby")
      node.remove()
      if (activeTip?.node === node) activeTip = null
    }
    const scheduleClose = () => {
      cancelClose()
      timer = setTimeout(() => {
        if (!owner.matches(":hover, :focus-within") && !node.matches(":hover, :focus-within")) close()
      }, 100)
    }
    const onScroll = (event: Event) => { if (event.target !== node) close() }
    const onPointerDown = (event: Event) => { if (!node.contains(event.target as Node)) close() }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" || ((event.key === "Enter" || event.key === " ") && !node.contains(event.target as Node))) close()
    }
    const onVisibilityChange = () => { if (document.hidden) close() }
    const observer = new MutationObserver(() => {
      const dialog = document.querySelector(".neko-modal-backdrop")
      if (!owner.isConnected || (dialog && !dialog.contains(owner))) close()
    })
    observer.observe(document.body, { childList: true, subtree: true })
    node.addEventListener("mouseenter", cancelClose)
    node.addEventListener("mouseleave", scheduleClose)
    node.addEventListener("focusin", cancelClose)
    node.addEventListener("focusout", scheduleClose)
    window.addEventListener("scroll", onScroll, true)
    window.addEventListener("resize", close)
    window.addEventListener("blur", close)
    window.addEventListener("pointerdown", onPointerDown, true)
    window.addEventListener("keydown", onKeyDown, true)
    document.addEventListener("visibilitychange", onVisibilityChange)
    activeTip = { owner, node, close }
    scheduleRef.current = scheduleClose
  }
  useEffect(() => {
    const owner = ref.current
    return () => { if (owner) closeAdaptiveTip(owner) }
  }, [])
  useEffect(() => {
    if (activeTip?.owner === ref.current) show()
  }, [props.content, props.place])
  return h("span", {
    ref,
    className: props.inline ? "tm-tooltip-trigger" : "tm-tip-wrap",
    tabIndex: 0,
    onMouseEnter: show,
    onMouseLeave: () => { if (activeTip?.owner === ref.current) scheduleRef.current?.() },
    onFocusIn: show,
    onFocusOut: () => { if (activeTip?.owner === ref.current) scheduleRef.current?.() },
  }, props.children)
}

export function TmSwitch(props: {
  checked: boolean
  onChange: (value: boolean) => any
  disabled?: boolean
  label?: any
  title?: string
  small?: boolean
  className?: string
}) {
  const { checked, onChange, disabled, label, title, small, className } = props
  const [ovr, setOvr] = useState<boolean | null>(null)
  // 权威值每次变化（含服务端刷新回写）→ 丢弃本地乐观值，回归受控
  useEffect(() => { setOvr(null) }, [checked])
  const shown = ovr === null ? !!checked : ovr

  async function fire() {
    if (disabled) return
    const next = !shown
    setOvr(next)
    try {
      const res = await Promise.resolve(onChange(next))
      if (res === false) setOvr(null)
    } catch {
      setOvr(null)
    }
  }

  const cls = "tm-sw"
    + (shown ? " tm-sw--on" : "")
    + (disabled ? " tm-sw--dis" : "")
    + (small ? " tm-sw--sm" : "")
    + (className ? " " + className : "")
  return (
    <label className={cls} title={title || undefined}>
      <input
        className="tm-sw-input"
        type="checkbox"
        checked={shown}
        disabled={!!disabled}
        onChange={() => { fire() }}
      />
      <span className="tm-sw-track"><span className="tm-sw-knob" /></span>
      {label ? <span className="tm-sw-text">{label}</span> : null}
    </label>
  )
}
