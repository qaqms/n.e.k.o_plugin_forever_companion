"""调试模式入口（[tide].debug_mode = true 时才注册）。

把难以自然触发的内部机制"快进"到秒级可验证：兜底超时、
限时到期、活动感知分支、注入内容、工具韧性、消息水位。
关闭时不注册任何入口，面板/命令面板零痕迹；生产包默认关闭。
带角色维度的入口支持可选 lanlan 参数（缺省 = 宿主当前角色）。

拆分自 __init__.py（方法逐字搬移，仅换文件与导入）；经 Mixin 组合回
ForeverCompanionPlugin——SDK 的 entry 发现遍历 type(self)，与定义文件无关。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from plugin.sdk.plugin import Err, Ok, SdkError

from ..core.fragments import build_fragment_prompt, parse_fragment_response
from ..core.journal import journal_due
from ..core.review import review_due
from ..core.state import (
    _FRAGMENT_DEFAULT_CONFIDENCE,
    _FRAGMENT_DEFAULT_SLOT,
    _JOURNAL_DEFAULT_INTERVAL_DAYS,
    _TIMED_ACTIONS,
    _TONE_COLD_LABELS,
    _LanlanShard,
    _stats_key,
)
from ..core.stats import (
    fabricate_demo_stats,
    heatmap_payload,
    new_stats,
    summary_payload,
)
from ..services.tone_slot import diagnose_slot_dormancy

JsonObject = dict[str, Any]


def _slot_dormancy_hint(core_cfg: JsonObject, slot: str) -> str:
    """槽位休眠原因 → 一句可操作的中文提示（与 __init__.py 同款，本地复刻避免循环导入）。"""
    reason = diagnose_slot_dormancy(core_cfg, slot)
    if reason == "free_route":
        return (
            "宿主正在使用免费路由（lanlan.tech），该端点只接受 N.E.K.O 客户端调用，"
            "插件无法直连——在宿主设置里配置自己的 API 服务商后本功能即可使用"
        )
    return "所选槽位在宿主未配置模型（或未保存服务商 URL），去宿主设置配置该槽位的模型"


class DebugEntriesMixin:
    """全部 debug_* 调试入口。宿主运行时经 type(self) 发现，定义位置无关。"""

    _DEBUG_LANLAN_PROP: JsonObject = {
        "lanlan": {"type": "string", "description": "目标角色名（缺省 = 宿主当前角色）"},
    }

    _DEBUG_ENTRIES: tuple[tuple[str, str, str, JsonObject], ...] = (
        (
            "debug_inject",
            "调试：立即注入一次身体轻语",
            "绕过变化门控立即注入，并返回实际注入的全部文本（含活动感知/情绪行），用于验证注入内容。",
            {"type": "object", "properties": dict(_DEBUG_LANLAN_PROP)},
        ),
        (
            "debug_simulate_user_message",
            "调试：模拟一条用户消息",
            "按真实消息路径推进注入状态机（水位/interval_n 计数/变化门控），返回是否注入与计数。",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "模拟的消息文本（供触发词匹配）"},
                    **_DEBUG_LANLAN_PROP,
                },
            },
        ),
        (
            "debug_set_mood",
            "调试：直接设置情绪动作",
            "直接设置指定情绪动作，可选把开始时间拨到 N 分钟前，用于快速验证兜底/到期解除。",
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "ebb_tide", "sea_fog", "shallow_reef", "storm_surge", "seek_harbor",
                            "ripple", "warm_current", "spring_tide",
                        ],
                    },
                    "minutes_ago": {"type": "integer", "description": "把开始时间拨到多少分钟前（默认 0）"},
                    "duration_minutes": {"type": "integer", "description": "限时动作的时长（分钟），不填用默认值"},
                    **_DEBUG_LANLAN_PROP,
                },
                "required": ["action"],
            },
        ),
        (
            "debug_expire_mood",
            "调试：立即让当前限时情绪到期",
            "把当前限时情绪动作的到期时间拨到过去，下一趟监督循环（面板轮询约 5 秒）即触发到期恢复台词。",
            {"type": "object", "properties": dict(_DEBUG_LANLAN_PROP)},
        ),
        (
            "debug_force_activity",
            "调试：覆写活动感知快照",
            "模拟系统活动信号（空闲时长/前台类别/隐私态）验证生活感知全部分支；三个参数全空则清除覆写回到真实信号。",
            {
                "type": "object",
                "properties": {
                    "idle_seconds": {"type": "integer", "description": "模拟的系统空闲秒数（≥1800 触发离开分支）"},
                    "category": {"type": "string", "description": "模拟的前台类别：work / gaming / entertainment / communication"},
                    "privacy": {"type": "string", "description": "模拟隐私态：visible / private / unavailable"},
                    **_DEBUG_LANLAN_PROP,
                },
            },
        ),
        (
            "debug_check_tools",
            "调试：立即校验 LLM 工具在位情况",
            "不等 5 分钟周期，立即 GET /api/tools 校验全部情绪/日记工具是否在位，缺失则当场重注册并返回结果。",
            {"type": "object", "properties": {}},
        ),
        (
            "debug_journal",
            "调试：检查个人日记资格并可选立即邀请",
            "返回当前角色的个人日记资格判定（due/reason/页数）；force=true 时清零节流并立即推一次日记邀请。",
            {
                "type": "object",
                "properties": {
                    "force": {"type": "boolean", "description": "true = 清零 24h 节流并立即推一次邀请（默认 false）"},
                    **_DEBUG_LANLAN_PROP,
                },
            },
        ),
        (
            "debug_capture_fragment",
            "调试：立即对最近一轮做碎片提取",
            "绕过水位/间隔门控，立即对最近一轮用户消息做碎片提取，返回提取原文、解析结果与是否落盘。",
            {"type": "object", "properties": dict(_DEBUG_LANLAN_PROP)},
        ),
        (
            "debug_emotion_sense",
            "调试：立即分析最近一轮互动的语气",
            "绕过水位/概率/节流门控，立即对最近一轮回复做语气分析，返回 label/置信度/生效阈值/命中分支等全链路判定细节。",
            {"type": "object", "properties": dict(_DEBUG_LANLAN_PROP)},
        ),
        (
            "debug_review",
            "调试：检查我的日记资格与素材统计",
            "返回当前角色的我的日记素材统计（轮数/语气分布/动作事件/碎片数）与双门槛资格判定；force=true 时立即成文一篇。",
            {
                "type": "object",
                "properties": {
                    "force": {"type": "boolean", "description": "true = 跳过门槛立即成文（素材不足仍会拒绝）"},
                    **_DEBUG_LANLAN_PROP,
                },
            },
        ),
        (
            "debug_stats",
            "调试：相处统计假数据注入/还原",
            "为时光页（热力图/徽章/月报/数字摘要）注入 120 天确定性假数据用于界面验证；真实 stats 先备份，restore=true 还原，clear=true 清空。",
            {
                "type": "object",
                "properties": {
                    "seed": {"type": "boolean", "description": "true = 备份现有数据并注入假数据（默认 false）"},
                    "restore": {"type": "boolean", "description": "true = 从备份还原真实数据（默认 false）"},
                    "clear": {"type": "boolean", "description": "true = 清空为空白统计（不自动备份，默认 false）"},
                    **_DEBUG_LANLAN_PROP,
                },
            },
        ),
    )

    def _sync_debug_entries(self) -> None:
        """按 debug_mode 开关同步调试入口的注册/注销（幂等）。"""
        enabled = bool(self._tide_cfg.get("debug_mode", False))
        if enabled == self._debug_registered:
            return
        register = getattr(self, "register_dynamic_entry", None)
        if enabled:
            if not callable(register):
                return
            count = 0
            for entry_id, name, description, schema in self._DEBUG_ENTRIES:
                handler = getattr(self, f"_{entry_id}", None)
                if not callable(handler):
                    continue
                try:
                    register(
                        entry_id=entry_id,
                        handler=handler,
                        name=name,
                        description=description,
                        input_schema=schema,
                        kind="action",
                    )
                    count += 1
                except Exception as exc:  # noqa: BLE001 - 单个入口失败不阻塞其余
                    self.logger.warning("debug entry {} register failed: {}", entry_id, exc)
            self._debug_registered = True
            self.logger.info("debug mode on: {} debug entries registered", count)
        else:
            unregister = getattr(self, "unregister_dynamic_entry", None)
            if callable(unregister):
                for entry_id, *_ in self._DEBUG_ENTRIES:
                    try:
                        unregister(entry_id)
                    except Exception:  # noqa: BLE001 - 注销失败最多残留一个入口，无害
                        pass
            self._debug_registered = False
            self.logger.info("debug mode off: debug entries unregistered")

    async def _debug_target_shard(self, lanlan: str = "") -> tuple[str, _LanlanShard]:
        """调试入口的角色解析：显式 lanlan → 宿主当前角色。"""
        name = str(lanlan or "").strip() or await self._resolve_current_lanlan()
        return name, await self._ensure_shard(name)

    async def _debug_inject(self, lanlan: str = "", **_: Any):
        name, shard = await self._debug_target_shard(lanlan)
        shard.last_injected_whisper_key = ""  # 绕过变化门控，强制来一次
        parts = await self._inject_now(name, shard)
        return Ok({
            "pushed": bool(parts),
            "lanlan": name,
            "texts": [str(p.get("text") or "") for p in parts],
            "activity_key": shard.last_activity_context_key,
            "whisper_key": shard.last_injected_whisper_key,
        })

    async def _debug_simulate_user_message(self, text: str = "", lanlan: str = "", **_: Any):
        name, shard = await self._debug_target_shard(lanlan)
        # 连续调用时系统时钟可能落在同一粒度刻度（Windows 约 15ms），
        # 强制水位单调递增，否则第二条会被 ts 门控误判为重复消息
        ts = max(time.time(), shard.last_injected_message_ts + 0.001)
        injected = await self._handle_new_user_message(ts, str(text or ""), name)
        return Ok({
            "ts": ts,
            "lanlan": name,
            "injected": injected,
            "message_counter": shard.user_message_count_since_inject,
        })

    async def _debug_set_mood(
        self,
        action: str = "",
        minutes_ago: int = 0,
        duration_minutes: int = 0,
        lanlan: str = "",
        **_: Any,
    ):
        name, shard = await self._debug_target_shard(lanlan)
        action = str(action or "").strip()
        if action not in (*_TIMED_ACTIONS, "seek_harbor"):
            return Err(SdkError(f"unknown mood action: {action!r}"))
        timed = action in _TIMED_ACTIONS
        await self._apply_mood_action(
            action=action,
            minutes=int(duration_minutes) if duration_minutes else None,
            reason="调试设定",
            timed=timed,
            lanlan=name,
        )
        minutes_ago = max(0, int(minutes_ago or 0))
        if minutes_ago:
            shift = minutes_ago * 60.0
            shard.mood.started_at -= shift
            if timed and shard.mood.expires_at > 0:
                shard.mood.expires_at -= shift
            await self._save_shard_mood(name, shard)
        remaining = ""
        if timed and shard.mood.expires_at > 0:
            seconds = shard.mood.expires_at - time.time()
            remaining = (
                f"将在 {max(0, int(seconds))} 秒后到期（下一趟监督循环触发恢复台词）"
                if seconds > 0 else "已过期，下一趟监督循环即触发恢复台词"
            )
        elif action == "seek_harbor":
            limit = self._mood_cfg.get("open_action_timeout_minutes")
            remaining = f"兜底阈值 {limit if limit is not None else 120} 分钟；把 minutes_ago 调到超过阈值即可验证自动解除"
        return Ok({
            "action": action,
            "lanlan": name,
            "started_at": shard.mood.started_at,
            "expires_at": shard.mood.expires_at,
            "note": remaining,
        })

    async def _debug_expire_mood(self, lanlan: str = "", **_: Any):
        name, shard = await self._debug_target_shard(lanlan)
        state = shard.mood
        if state.action not in _TIMED_ACTIONS or not state.is_active():
            return Ok({"forced": False, "note": "当前没有生效的限时情绪动作。"})
        state.expires_at = time.time() - 1
        await self._save_shard_mood(name, shard)
        return Ok({
            "forced": True,
            "action": state.action,
            "lanlan": name,
            "note": "已把到期时间拨到过去；面板开着时约 5 秒内、否则下一趟 10 秒轮询即触发恢复台词。",
        })

    async def _debug_journal(self, force: bool = False, lanlan: str = "", **_: Any):
        name, shard = await self._debug_target_shard(lanlan)
        interval = self._journal_int_cfg("interval_days", _JOURNAL_DEFAULT_INTERVAL_DAYS)
        due, reason = journal_due(shard.journal, interval_days=interval)
        payload: JsonObject = {
            "due": due,
            "reason": reason,
            "pages_total": len(shard.journal),
            "interval_days": interval,
            "lanlan": name,
        }
        if force:
            shard.last_journal_invite_ts = 0.0
            # 清零节流水位 → 必走 respond 当面递到档；deliver 回显投递方式（1.2.3）
            invited, deliver = await self._maybe_journal_invite(name, shard)
            payload["invited"] = invited
            payload["deliver"] = deliver
            payload["note"] = "已清零节流并尝试推送邀请（资格/开关不满足则 invited=false）。"
        return Ok(payload)

    async def _debug_capture_fragment(self, lanlan: str = "", **_: Any):
        """立即对最近一轮用户消息做碎片提取（绕过水位/间隔门控），返回全链路细节。"""
        name, shard = await self._debug_target_shard(lanlan)
        turn = await self._poll_recent_turns(shard, lanlan=name, peek=True)
        if turn is None:
            return Ok({"captured": False, "lanlan": name, "note": "recent.json 里没有可分析的轮次。"})
        user_text, her_text = turn
        slot = str(self._fragments_cfg.get("slot") or "").strip() or _FRAGMENT_DEFAULT_SLOT
        resolved = self._resolve_tone_slot(self._load_core_config(), slot)
        if resolved is None:
            return Ok({
                "captured": False,
                "lanlan": name,
                "slot": slot,
                "note": _slot_dormancy_hint(self._load_core_config(), slot),
            })
        raw = await asyncio.to_thread(
            self._post_chat_completion,
            resolved["base_url"], resolved["api_key"], resolved["model"],
            build_fragment_prompt(user_text, her_text),
        )
        parsed = parse_fragment_response(raw or "")
        payload: JsonObject = {
            "lanlan": name,
            "slot": slot,
            "user_text": user_text[:200],
            "raw": (raw or "")[:400],
            "parsed": parsed,
            "threshold": self._fragments_float_cfg("confidence_threshold", _FRAGMENT_DEFAULT_CONFIDENCE),
        }
        if parsed and parsed.get("capture"):
            payload["captured"] = True
            payload["total_fragments"] = sum(
                1 for item in shard.diary if str(item.get("source") or "self") == "auto"
            )
        else:
            payload["captured"] = False
            payload["note"] = "模型判定本轮无需记（capture=false）或回复无法解析。"
        return Ok(payload)

    async def _debug_emotion_sense(self, lanlan: str = "", **_: Any):
        """立即对最近一轮互动做语气分析（peek 不推进水位），返回全链路判定细节。"""
        name, shard = await self._debug_target_shard(lanlan)
        turn = await self._poll_recent_turns(shard, lanlan=name, peek=True)
        if turn is None:
            return Ok({"analyzed": False, "lanlan": name, "note": "recent.json 里没有可分析的回复。"})
        user_text, her_text = turn
        mood_active = self._mood_enabled(shard) and shard.mood.is_active()
        text = her_text[:500] if mood_active else f"用户：{user_text[:300]}\n她：{her_text[:500]}"
        result = await self._analyze_turn_tone(text, name)
        slot = str(self._emotion_sense_cfg.get("slot") or "").strip()
        payload: JsonObject = {
            "analyzed": result is not None,
            "lanlan": name,
            "mode": "correction" if mood_active else "screen",
            "mood_action": shard.mood.action if mood_active else "",
            "enabled": self._emotion_sense_enabled(shard),
            "check_rate": self._tone_float_cfg("check_rate", 1.0),
            "effective_threshold": self._effective_tone_threshold(shard),
            "tone_window": list(shard.tone_window),
            "her_reply_preview": her_text[:80],
            "slot": slot,
        }
        if slot and slot != "emotion":
            # 直连路径：回显解析出的 model/脱敏 base_url（只留协议+主机），永不输出 key
            resolved = self._resolve_tone_slot(self._load_core_config(), slot)
            if resolved is not None:
                from urllib.parse import urlparse

                host = urlparse(str(resolved["base_url"]))
                payload["resolved_model"] = resolved["model"]
                payload["resolved_base_url"] = (
                    f"{host.scheme}://{host.netloc}/…" if host.netloc else "（已配置）"
                )
            else:
                payload["resolved"] = None
        if result is not None:
            label, confidence = result
            payload["emotion"] = label
            payload["confidence"] = confidence
            payload["would_screen_nudge"] = (
                not mood_active
                and confidence >= self._effective_tone_threshold(shard)
                and (label in _TONE_COLD_LABELS or label == "happy")
            )
        else:
            payload["note"] = (
                "分析失败/降级：检查宿主情感模型配置（或 [emotion_sense].slot 所选槽位的"
                "端点可达性）、CSRF token 获取；详见插件日志。"
            )
        return Ok(payload)

    async def _debug_review(self, force: bool = False, lanlan: str = "", **_: Any):
        """返回我的日记素材统计与资格判定；force=true 立即成文（素材不足拒绝）。"""
        name, shard = await self._debug_target_shard(lanlan)
        due, reason = review_due(
            shard.review_stats,
            turns_threshold=self._review_turns_threshold(),
            days_threshold=self._review_days_threshold(),
        )
        payload: JsonObject = {
            "lanlan": name,
            "enabled": self._review_enabled(shard),
            "due": due,
            "reason": reason,
            "entries_total": len(shard.review),
            "stats": {
                "turns": int(shard.review_stats.get("turns") or 0),
                "tone": dict(shard.review_stats.get("tone") or {}),
                "affect_samples": len(shard.review_stats.get("affect_samples") or []),
                "actions": len(shard.review_stats.get("actions") or []),
                "fragments": len(shard.review_stats.get("fragments") or []),
                "started_at": str(shard.review_stats.get("started_at") or ""),
            },
            "thresholds": {
                "turns": self._review_turns_threshold(),
                "days": self._review_days_threshold(),
            },
        }
        if force:
            written, write_reason = await self._maybe_write_review(name, shard, force=True)
            payload["forced_write"] = written
            payload["write_reason"] = write_reason
        return Ok(payload)

    async def _debug_stats(
        self,
        seed: bool = False,
        restore: bool = False,
        clear: bool = False,
        lanlan: str = "",
        **_: Any,
    ):
        """相处统计假数据注入/还原（时光页界面验证，零随机可复现）。

        seed：真实 stats 备份到 stats@<角色>|pre-debug 后覆盖为 fabricate_demo_stats
        的 120 天分布（热力图全档位/色条、徽章、月报、数字摘要全覆盖）；
        restore：从备份还原；clear：清空为空白（不备份，适合反复 seed 用）。
        三个参数互斥，都不带时只回显当前统计概要。只动当前角色的 stats 分片，
        周期/情绪/日记等其他数据一概不碰。
        """
        name, shard = await self._debug_target_shard(lanlan)
        flags = [bool(seed), bool(restore), bool(clear)]
        if sum(flags) > 1:
            return Err(SdkError("seed / restore / clear 互斥，一次只传一个"))
        backup_key = f"{_stats_key(name)}|pre-debug"
        today = self._stats_today()
        if seed:
            backup = await self.store.get(backup_key)
            if not isinstance(backup, Err) and backup.value is None:
                # 首次 seed 才备份：连续 seed 不覆盖最早的备份（还原永远回到最初真实数据）
                saved = await self.store.set(backup_key, dict(shard.stats))
                if isinstance(saved, Err):
                    return Err(SdkError("备份真实数据失败，已中止注入"))
            shard.stats = fabricate_demo_stats(today)
            await self._save_shard_stats(name, shard)
            self.logger.info("debug stats seeded for {}", name)
            return Ok({
                "seeded": True,
                "lanlan": name,
                "note": "已注入 120 天假数据；打开时光页即可验证热力图/徽章/月报/摘要。"
                        "测完 restore=true 还原真实数据。",
                **self._debug_stats_brief(shard, today),
            })
        if restore:
            backup = await self.store.get(backup_key)
            if isinstance(backup, Err) or backup.value is None:
                return Ok({"restored": False, "lanlan": name, "note": "没有可还原的备份（从未 seed 过）。"})
            shard.stats = dict(backup.value)
            await self._save_shard_stats(name, shard)
            await self.store.set(backup_key, None)
            self.logger.info("debug stats restored for {}", name)
            return Ok({
                "restored": True,
                "lanlan": name,
                "note": "真实相处统计已还原，备份已清除。",
                **self._debug_stats_brief(shard, today),
            })
        if clear:
            shard.stats = new_stats()
            await self._save_shard_stats(name, shard)
            return Ok({"cleared": True, "lanlan": name, **self._debug_stats_brief(shard, today)})
        return Ok({
            "lanlan": name,
            "note": "带 seed=true 注入假数据 / restore=true 还原 / clear=true 清空。",
            **self._debug_stats_brief(shard, today),
        })

    def _debug_stats_brief(self, shard: _LanlanShard, today: str) -> JsonObject:
        """debug_stats 回显用的统计概要（与面板时光页同源的派生视图）。"""
        return {
            "summary": summary_payload(shard.stats, today),
            "heat_days": len(heatmap_payload(shard.stats, today).get("days") or []),
        }

    async def _debug_force_activity(
        self,
        idle_seconds: int | None = None,
        category: str = "",
        privacy: str = "",
        lanlan: str = "",
        **_: Any,
    ):
        # 覆写本身是全局的（模拟的是"用户"这一个真实人的系统信号）；
        # lanlan 只决定清哪个 shard 的注入指纹、用哪个 shard 预览
        name, shard = await self._debug_target_shard(lanlan)
        if idle_seconds is None and not str(category or "").strip() and not str(privacy or "").strip():
            self._activity_override = None
            shard.last_injected_whisper_key = ""
            return Ok({"override": None, "lanlan": name, "note": "已清除覆写，恢复真实系统信号。"})
        self._activity_override = {
            "idle": int(idle_seconds) if idle_seconds is not None else None,
            "category": str(category or "").strip().lower() or None,
            "privacy": str(privacy or "visible").strip() or "visible",
        }
        shard.last_injected_whisper_key = ""  # 让下次注入立即反映覆写
        line = await self._build_activity_context_line(self._current_phase_state(shard), shard)
        return Ok({"override": self._activity_override, "lanlan": name, "preview_line": line})

    async def _debug_check_tools(self, **_: Any):
        self._last_tool_health_ts = 0.0
        reachable, missing = await self._tool_health_scan()
        re_emitted = False
        if reachable and missing:
            self._reemit_missing_tools(missing)
            re_emitted = True
        llm_tools = getattr(self, "_llm_tools", None)
        total = len(llm_tools) if isinstance(llm_tools, dict) else 0
        return Ok({
            "main_server_reachable": reachable,
            "local_tool_count": total,
            "missing": missing,
            "re_emitted": re_emitted,
            "note": (
                "全部在位" if reachable and not missing
                else ("main_server 不可达" if not reachable else f"已重注册 {len(missing)} 个缺失工具")
            ),
        })
