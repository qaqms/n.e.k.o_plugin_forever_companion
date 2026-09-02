"""与宿主主动搭话的协调 + LLM 工具注册韧性 + 宿主 HTTP 直连胶水。

拆分自 __init__.py（方法逐字搬移，仅换文件与导入）；经 Mixin 组合回
ForeverCompanionPlugin——SDK 的 entry 发现遍历 type(self)，与定义文件无关。

与宿主主动搭话的协调——最小侵入原则：暂停/恢复只写 proactiveChatEnabled
这一个总开关字段（前端与引擎里所有主动搭话路径都是 总开关 && 子开关 的与门，
关总开关即完全静默），绝不触碰用户的任何子开关/间隔配置。
多角色后是引用计数：paused_by = 有生效情绪的角色集，非空暂停、
空则恢复；原值水位 prev 存 proactive_state（不再放 _MoodState）。
优先经 proactive_controller（官方协调入口），它未运行时直连宿主
HTTP API（proactive_controller 内部调用的同一批端点）。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from plugin.sdk.plugin import Ok

try:
    from .state import _PROACTIVE_PAUSE_ACTIONS as _PROACTIVE_PAUSE_ACTIONS
except ImportError:  # pragma: no cover - 无父包上下文的兜底（同 __init__.py 惯例）
    from state import _PROACTIVE_PAUSE_ACTIONS as _PROACTIVE_PAUSE_ACTIONS  # type: ignore[no-redef]

JsonObject = dict[str, Any]


class HostCoordMixin:
    """宿主协调：主动搭话暂停/恢复（引用计数）、HTTP 直连、工具健康扫描重注册。"""

    def _proactive_api_base(self) -> str:
        # 首次解析后缓存到实例：宿主端口运行期不变，独立/测试环境每次调用都
        # 白构造一次 ImportError；config_change 时清缓存重解析。
        # 保持运行时延迟 import（不提顶层）：测试靠打桩 sys.modules 工作
        if self._proactive_api_base_cache is not None:
            return self._proactive_api_base_cache
        port = 48911
        try:
            from config import MAIN_SERVER_PORT

            port = int(MAIN_SERVER_PORT)
        except Exception:  # noqa: BLE001 - 缺省端口即可
            pass
        base = f"http://127.0.0.1:{port}"
        self._proactive_api_base_cache = base
        return base

    async def _proactive_http(
        self,
        method: str,
        path: str,
        body: JsonObject | None = None,
        headers: dict[str, str] | None = None,
    ) -> JsonObject | None:
        """直连宿主 HTTP API（stdlib urllib，零外部依赖；to_thread 不阻塞事件循环）。

        返回解析后的 JSON dict；任何失败返回 None（调用方按 best-effort 处理）。
        """
        import json as _json
        import urllib.request

        url = f"{self._proactive_api_base()}{path}"
        data = _json.dumps(body).encode("utf-8") if body is not None else None
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers=req_headers,
        )

        def _do() -> JsonObject:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                payload = _json.loads(resp.read().decode("utf-8"))
                return payload if isinstance(payload, dict) else {}

        try:
            return await asyncio.to_thread(_do)
        except Exception as exc:  # noqa: BLE001 - best-effort
            self.logger.debug("proactive http {} {} failed: {}", method, path, exc)
            return None

    async def _tool_health_scan(self) -> tuple[bool, list[str]]:
        """返回 (main_server 是否可达, 缺失的本插件工具名列表)。

        注意 GET /api/tools 的实际返回结构是
        ``{"ok": true, "tools_by_role": {"<lanlan>": [{"name": ...}]}}``，
        工具列表嵌在 tools_by_role 下；平铺结构仅作兜底兼容。

        tool_registry 是 LLMSessionManager 的内存属性，main_server 重启即全丢
        （docs/plugins/tool-calling.md）；插件周期性校验在位情况，缺失则重新
        广播 LLM_TOOL_REGISTER IPC（宿主侧 replace 语义，重复注册幂等）。
        """
        llm_tools = getattr(self, "_llm_tools", None)
        if not isinstance(llm_tools, dict) or not llm_tools:
            return True, []
        payload = await self._proactive_http("GET", "/api/tools")
        if not isinstance(payload, dict):
            return False, []  # main_server 不可达：等下一趟再试，不盲重注册
        by_role = payload.get("tools_by_role")
        groups = by_role.values() if isinstance(by_role, dict) else payload.values()
        present: set[str] = set()
        for tools in groups:
            if isinstance(tools, list):
                for item in tools:
                    if isinstance(item, dict) and item.get("name"):
                        present.add(str(item["name"]))
        return True, [name for name in llm_tools if name not in present]

    def _reemit_missing_tools(self, missing: list[str]) -> None:
        llm_tools = getattr(self, "_llm_tools", None)
        notify = getattr(self, "_notify_llm_tool_registered", None)
        if not isinstance(llm_tools, dict) or not callable(notify):
            return
        for name in missing:
            meta = llm_tools.get(name)
            if meta is None:
                continue
            try:
                notify(meta)
            except Exception as exc:  # noqa: BLE001 - 单工具失败不影响其余
                self.logger.debug("re-emit tool register failed for {}: {}", name, exc)

    async def _ensure_tools_registered(self) -> None:
        if time.time() - self._last_tool_health_ts < 300:
            return
        self._last_tool_health_ts = time.time()
        # 情绪系统关闭时工具调用会被拒绝，但仍在位即可，无需校验在位性之外的动作
        reachable, missing = await self._tool_health_scan()
        if not reachable or not missing:
            return
        self._reemit_missing_tools(missing)
        self.logger.info("re-registered {} missing llm tools: {}", len(missing), ", ".join(missing))

    async def _proactive_get_master(self) -> bool | None:
        """读总开关 proactiveChatEnabled 当前值；读取失败返回 None。"""
        payload = await self._proactive_http("GET", "/api/proactive/settings")
        settings = payload.get("settings") if isinstance(payload, dict) else None
        if isinstance(settings, dict) and "proactiveChatEnabled" in settings:
            return bool(settings["proactiveChatEnabled"])
        # HTTP 失败时尝试官方协调入口兜底
        state_res = await self.plugins.call_entry_json(
            "proactive_controller:get_state", timeout=3.0
        )
        if isinstance(state_res, Ok) and isinstance(state_res.value, dict):
            settings = state_res.value.get("settings")
            if isinstance(settings, dict) and "proactiveChatEnabled" in settings:
                return bool(settings["proactiveChatEnabled"])
        return None

    async def _proactive_set_master(self, enabled: bool) -> bool:
        """只写总开关一个字段；任何子开关/间隔都不碰。HTTP 优先。

        注意：该端点的请求体要求字段平铺在顶层
        （``{"proactiveChatEnabled": false}``），不是嵌套在 "settings" 下。
        """
        patch = {"proactiveChatEnabled": bool(enabled)}
        payload = await self._proactive_http("POST", "/api/proactive/settings", patch)
        if payload is not None and payload.get("success") is not False:
            return True
        res = await self.plugins.call_entry(
            "proactive_controller:set_settings",
            {"settings": patch},
            timeout=3.0,
        )
        return isinstance(res, Ok)

    async def _pause_host_proactive(self) -> None:
        """任一角色情绪动作开始时临时关闭主动搭话总开关（引用计数见 _maybe_sync_proactive_pause）。

        只记录总开关的原值：恢复时原样写回——原本开着就恢复开，
        原本关着就保持关。不套任何预设，不动任何子设置。
        """
        if self._proactive_state.get("prev") is not None:
            return  # 已在暂停中，避免覆盖原始值
        master = await self._proactive_get_master()
        if master is None:
            self.logger.debug("proactive master unreadable; will retry next tick")
            return
        if not master:
            # 本来就没开：无需暂停，也不必在结束后替用户打开
            self._proactive_state["prev"] = {"master": False}
            await self._save_proactive_state()
            self.logger.info("proactive already off; nothing to pause")
            return
        if not await self._proactive_set_master(False):
            self.logger.warning("pause host proactive failed (both paths); retry next tick")
            return
        self._proactive_state["prev"] = {"master": True}
        await self._save_proactive_state()
        self.logger.info("host proactive master switched off for active mood action")

    async def _resume_host_proactive(self) -> None:
        """所有角色的情绪动作都解除后，把总开关恢复为进入前的原值。"""
        prev = self._proactive_state.get("prev")
        self._proactive_state["prev"] = None
        await self._save_proactive_state()
        if not prev:
            self.logger.info("no recorded previous proactive state; skip restore")
            return
        was_on = bool(prev.get("master"))
        if not was_on:
            # 原本就是关着的：什么都不做
            self.logger.info("proactive was off before; keep it off")
            return
        if not await self._proactive_set_master(True):
            self.logger.warning("restore proactive master on failed")
            return
        self.logger.info("host proactive master restored to on")

    async def _reassert_proactive_off(self) -> None:
        """情绪期内周期加固：若服务端总开关被外部（如前端陈旧的 60s 周期
        同步）写回 true，则重新关掉。不动水位，幂等。"""
        if self._proactive_state.get("prev") is None:
            return
        master = await self._proactive_get_master()
        if master is True:
            if await self._proactive_set_master(False):
                self.logger.info("proactive master drifted back on during silence; re-asserted off")
        elif master is None:
            self.logger.debug("proactive master unreadable during re-assert")

    async def _maybe_sync_proactive_pause(self) -> None:
        """引用计数同步（同步 await，见 _supervise_once 注释）。

        paused_by = 当前有生效情绪的角色集（现算而非增量维护，崩溃重启后
        也能从 shard 状态自愈）；非空且未暂停→暂停，空且暂停中→恢复。
        """
        paused_by = self._mood_active_lanlans()
        if paused_by and self._proactive_state.get("prev") is None:
            await self._pause_host_proactive()
        elif not paused_by and self._proactive_state.get("prev") is not None:
            await self._resume_host_proactive()
        if paused_by != list(self._proactive_state.get("paused_by") or []):
            self._proactive_state["paused_by"] = paused_by
            await self._save_proactive_state()
