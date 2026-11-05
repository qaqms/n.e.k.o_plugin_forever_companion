// Shared switches, tooltips and selects. TmSwitch rolls back when onChange
// rejects or resolves false, then follows the parent's authoritative checked value.
import { h, useEffect, useRef, useState } from "@neko/plugin-ui"
import type { OpenSelectMenu, TmSelectProps } from "./types"

// Shared custom controls stay in one module to respect the host's dependency limit.
let activeTip: { owner: HTMLElement; node: HTMLElement; close: () => void } | null = null
let tipSequence = 0

let activeSelect: OpenSelectMenu | null = null
let selectSequence = 0
const selectListeners = new Set<() => void>()

function notifySelect() { selectListeners.forEach(listener => listener()) }
function closeSelect() {
  const current = activeSelect
  if (!current) return
  activeSelect = null
  current.owner.removeAttribute("aria-activedescendant")
  current.onClose()
  notifySelect()
}
function setSelectIndex(index: number) {
  const current = activeSelect
  if (!current || index < 0) return
  current.index = index
  current.owner.setAttribute("aria-activedescendant", `${current.id}-option-${index}`)
  notifySelect()
}
function chooseSelect(index: number) {
  const current = activeSelect
  const option = current?.props.current.options[index]
  if (!current || current.owner.disabled || !option || option.disabled) return
  closeSelect()
  if (option.value !== current.props.current.value) current.props.current.onChange(option.value)
}
function selectKeyDown(event: any) {
  const current = activeSelect
  if (!current || event.currentTarget !== current.owner || event.isComposing) return
  const options = current.props.current.options
  const enabled = options.map((option, index) => option.disabled ? -1 : index).filter(index => index >= 0)
  if (event.key === "Escape" || event.key === "Tab") {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation() }
    closeSelect()
  } else if (event.key === "Enter" || event.key === " ") {
    event.preventDefault()
    chooseSelect(current.index)
  } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
    event.preventDefault()
    const at = enabled.indexOf(current.index)
    const next = event.key === "Home" ? 0 : event.key === "End" ? enabled.length - 1
      : Math.max(0, Math.min(enabled.length - 1, at + (event.key === "ArrowDown" ? 1 : -1)))
    setSelectIndex(enabled[next] ?? -1)
  } else if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) {
    event.preventDefault()
    const now = Date.now()
    const letter = event.key.toLocaleLowerCase()
    current.search = now - current.searchedAt > 700 ? letter : current.search + letter
    current.searchedAt = now
    const repeated = [...current.search].every(char => char === letter)
    const query = repeated ? letter : current.search
    const start = enabled.indexOf(current.index)
    const ordered = [...enabled.slice(start + 1), ...enabled.slice(0, start + 1)]
    setSelectIndex(ordered.find(index => options[index].label.toLocaleLowerCase().startsWith(query)) ?? -1)
  }
}

export function TmSelect(props: TmSelectProps) {
  const owner = useRef<HTMLButtonElement | null>(null)
  const latest = useRef(props)
  latest.current = props
  const id = useRef("")
  if (!id.current) id.current = `tm-select-${++selectSequence}`
  const [opened, setOpened] = useState(false)
  const signature = JSON.stringify([props.value, props.options, props.disabled, props.label])
  const selected = props.options.find(option => option.value === props.value)
  const text = selected?.label || props.placeholder || props.value
  function open(last = false) {
    if (!owner.current || props.disabled || !props.options.some(option => !option.disabled)) return
    closeSelect()
    closeAdaptiveTip()
    const enabled = props.options.map((option, index) => option.disabled ? -1 : index).filter(index => index >= 0)
    const selectedIndex = props.options.findIndex(option => option.value === props.value && !option.disabled)
    activeSelect = {
      owner: owner.current, props: latest, signature, id: id.current,
      index: selectedIndex >= 0 ? selectedIndex : enabled[last ? enabled.length - 1 : 0],
      search: "", searchedAt: 0, onClose: () => setOpened(false),
    }
    owner.current.focus({ preventScroll: true })
    setOpened(true)
    setSelectIndex(activeSelect.index)
  }
  useEffect(() => {
    if (activeSelect?.owner === owner.current && activeSelect.signature !== signature) closeSelect()
  }, [signature])
  useEffect(() => {
    const element = owner.current
    return () => { if (activeSelect?.owner === element) closeSelect() }
  }, [])
  // Menu clicks stay in the hosted renderer's trusted event path.
  return h("button", {
    ref: owner, type: "button", role: "combobox", className: `tm-select ${props.className || ""}`,
    "aria-label": props.label, "aria-haspopup": "listbox", "aria-expanded": opened ? "true" : "false",
    "aria-controls": opened ? id.current : undefined, "data-value": props.value, disabled: !!props.disabled,
    onClick: () => { if (activeSelect?.owner === owner.current) closeSelect(); else open() },
    onKeyDown: (event: any) => {
      if (activeSelect?.owner === owner.current) selectKeyDown(event)
      else if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
        event.preventDefault()
        open(event.key === "ArrowUp")
      }
    },
    onBlur: () => { if (activeSelect?.owner === owner.current) closeSelect() },
  },
  h("span", { className: "tm-select-value", title: text }, text),
  h("span", { className: "tm-demo-icon tm-select-chevron", "data-icon": "next", "aria-hidden": "true" }))
}

export function useSelectMenu() {
  const [, redraw] = useState(0)
  useEffect(() => {
    const listener = () => redraw(value => value + 1)
    selectListeners.add(listener)
    return () => { selectListeners.delete(listener); closeSelect() }
  }, [])
  return { current: activeSelect, close: closeSelect, choose: chooseSelect, highlight: setSelectIndex }
}

function closeAdaptiveTip(owner?: HTMLElement | null) {
  if (activeTip && (!owner || activeTip.owner === owner)) activeTip.close()
}

export function AdaptiveTip(props: { key?: string; content: string; place?: string; inline?: boolean; children?: any }) {
  const ref = useRef<HTMLElement | null>(null)
  const scheduleRef = useRef<(() => void) | null>(null)
  const show = () => {
    const owner = ref.current
    if (!owner || activeSelect) return
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
