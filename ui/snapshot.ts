import { useEffect, useRef, useState } from "@neko/plugin-ui"
import type { PluginSurfaceProps } from "@neko/plugin-ui"
import type { State } from "./types"
import { unwrapCallResult } from "./utils"

export function usePanelSnapshot(props: PluginSurfaceProps<State>) {
  const [polled, setPolled] = useState<{ context: any; state: State } | null>(null)
  const latest = useRef(props)
  latest.current = props
  const good = useRef<State | null>(null)
  const rawState = ((polled?.context === props.state ? polled.state : props.state) || {}) as State
  const frameUsable = !!rawState.backup_recovery_required || (!!rawState.settings && typeof rawState.lanlan === "string")
  if (frameUsable) good.current = rawState
  const staleFrame = !frameUsable && good.current !== null
  const state = staleFrame ? good.current as State : rawState
  const ready = useRef(frameUsable)
  ready.current = frameUsable
  const api: typeof props.api = { ...props.api, call: (actionId, args, options) => {
    if (!ready.current && actionId !== "poll_dashboard" && actionId !== "data_backup") {
      return Promise.reject(new Error("backup_busy"))
    }
    return props.api.call(actionId, args, options)
  } }
  useEffect(() => {
    let alive = true
    let refreshing = false
    let polls = 0
    const refresh = () => {
      if (!alive || document.hidden || refreshing) return
      refreshing = true
      const current = latest.current
      const context = current.state
      const light = current.actions.some(action => action.id === "poll_dashboard") && ++polls % 6 !== 0
      const request = light
        ? current.api.call("poll_dashboard", {}).then(payload => {
            if (alive && latest.current.state === context) {
              setPolled({ context, state: unwrapCallResult<State>(payload) })
            }
          })
        : current.api.refresh()
      Promise.resolve(request).catch(err => {
        if (alive && latest.current.state === context) {
          setPolled({ context, state: { backup_busy: String(err?.message || err).includes("backup_busy") } })
        }
      }).finally(() => { refreshing = false })
    }
    const timer = setInterval(refresh, 5000)
    document.addEventListener("visibilitychange", refresh)
    return () => {
      alive = false
      clearInterval(timer)
      document.removeEventListener("visibilitychange", refresh)
    }
  }, [])
  return { state, rawState, staleFrame, frameUsable, hasState: good.current !== null, api }
}
