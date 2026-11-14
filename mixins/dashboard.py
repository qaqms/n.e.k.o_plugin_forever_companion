"""Read panel snapshots without driving host coordination or model work."""

from __future__ import annotations

import time
from typing import Any

from plugin.sdk.plugin import (
    Ok,
    plugin_entry,
    tr,
    ui,
)

from ..core.birthday import (
    parse_birthday,
)
from ..core.cycle import (
    TideConfigError,
    build_month_calendar,
    build_status_payload,
)
from ..core.fragments import diary_display_record
from ..core.journal import archive_brief, page_header
from ..core.memory import (
    diary_partition,
    lifecycle_view,
)
from ..core.onboarding import build_readiness, wizard_pending
from ..core.review import (
    review_archive_brief,
)
from ..core.state import (
    _CHANNEL_BREAK_REASON,
    _CHANNEL_BUDGET_REASON,
    _CHANNEL_MODE_CUSTOM,
    _CHANNEL_TRANSPORT_DIRECT,
    _CHANNEL_TRANSPORT_HOST,
    _FRAGMENT_DEFAULT_SLOT,
    _REVIEW_DEFAULT_SLOT,
    _TONE_SLOT_OPTIONS_CACHE_TTL,
    _TONE_SLOT_PREFIXES,
    _channel_route,
    _LanlanShard,
    _now_utc,
    _parse_iso_ts,
    tier_budget_used,
)
from ..core.stats import (
    badges_payload,
    summary_payload,
)
from ..services.tone_slot import _channel_mode, diagnose_slot_dormancy

JsonObject = dict[str, Any]


class DashboardMixin:
    """Panel snapshots, channel readiness, and lightweight polling."""

    async def _tone_slot_options(self) -> list[JsonObject]:
        """面板"语气分析模型槽位"下拉数据源：固定槽位列表 + 各槽当前 ModelId 显示值。

        GET /api/config/core_api 取不到（宿主不可达/超时）时退回静态列表（model 空串），
        整体 try/except，绝不能拖垮 dashboard 渲染。
        成功结果缓存 60s（面板 5s 轮询，槽位模型名变化频率极低）；
        失败缓存 5s，避免一次面板操作的多次上下文查询重复等待离线宿主。
        """
        cached, ts = self._tone_slot_options_cache
        if cached is not None and time.monotonic() - ts < _TONE_SLOT_OPTIONS_CACHE_TTL:
            return [*cached, {"value": "gateway", "model": ""}]
        options: list[JsonObject] = [{"value": "", "model": ""}] + [
            {"value": slot, "model": ""} for slot in _TONE_SLOT_PREFIXES
        ]
        if cached is None and time.monotonic() - ts < 5.0:
            return [*options, {"value": "gateway", "model": ""}]
        loaded = False
        try:
            payload = await self._proactive_http("GET", "/api/config/core_api")
            if isinstance(payload, dict):
                for opt in options[1:]:
                    model = str(payload.get(f"{_TONE_SLOT_PREFIXES[str(opt['value'])]}ModelId") or "").strip()
                    opt["model"] = model
                loaded = True
        except Exception as exc:  # noqa: BLE001 - best-effort，静态兜底已可用
            self.logger.debug("fetch tone slot options failed: {}", exc)
        self._tone_slot_options_cache = (options if loaded else None, time.monotonic())
        return [*options, {"value": "gateway", "model": ""}]

    @ui.context(id="dashboard")
    async def dashboard(self) -> JsonObject:
        lanlan, shard = await self._current_shard_async()
        try:
            phase = self._current_phase_state(shard)
            status = build_status_payload(phase, enabled=self._enabled(shard))
        except TideConfigError as exc:
            status = {"enabled": self._enabled(shard), "error": str(exc)}
        mood_active = self._mood_enabled(shard) and shard.mood.is_active()
        # 连续心情（只可视化不注入）：读取时惰性衰减到当前时刻，保留两位小数下发
        valence, arousal = self._current_affect(shard)
        mood_payload: JsonObject = {
            "active": mood_active,
            "history": [dict(item) for item in reversed(shard.mood.history[-12:])],
            # 系统级开关态（忽略总开关，防双重提示）：配置 ∧ 能力否决集
            # （1.2.7 能力中心：功能页关掉情绪引擎，状态条提示也要如实跟上）
            "system_enabled": self._cap_config_on("mood_engine", lanlan),
            "affect": {
                "valence": round(valence, 2),
                "arousal": round(arousal, 2),
                # 静息基线下发给仪表盘画"平复回归位"刻度
                "arousal_baseline": round(self._affect_arousal_baseline(), 2),
            },
        }
        if mood_active:
            mood_payload.update(
                {
                    "action": shard.mood.action,
                    "action_label": self._action_label(shard.mood.action),
                    "reason": shard.mood.reason,
                    "origin": shard.mood.origin,
                    "started_at": shard.mood.started_at,
                    "expires_at": shard.mood.expires_at or None,
                }
            )
        # 潮汐日历：当前月前后各一个月的逐日推算（委婉显示，一律以"潮汐"代称）。
        # 结果按（角色, 当天日期, 周期参数指纹）缓存：面板 5s 轮询，同日同参数直接复用；
        # 改参数/锚点/快进、跨天、切角色都会改变 key 自然失效，无需显式清理
        calendar = None
        try:
            params = self._cycle_params(shard)
            today = self._today_str()
            cal_key = (
                lanlan,
                today.isoformat(),
                params["anchor"].isoformat(),
                int(params["cycle_length"]),
                int(params["period_length"]),
                int(params["ovulation_day"]),
                int(params["ovulation_window"]),
                int(params["advance_days"]),
                bool(self._auto_derive(shard)),
            )
            cached_key, cached_months = self._calendar_cache
            if cached_months is not None and cached_key == cal_key:
                months = cached_months
            else:
                months = build_month_calendar(
                    today=today,
                    anchor=params["anchor"],
                    cycle_length=params["cycle_length"],
                    period_length=params["period_length"],
                    ovulation_day=params["ovulation_day"],
                    ovulation_window=params["ovulation_window"],
                    advance_days=params["advance_days"],
                )
                self._calendar_cache = (cal_key, months)
            calendar = {"months": months}
        except TideConfigError as exc:
            calendar = {"error": str(exc)}
        # 各角色状态摘要（含孤儿标注）：orphan = 在 lanlan_index 但不在宿主现存名单。
        # 名单不可达（None=未知）时一律标 False，绝不误标。
        known = await self._fetch_known_catgirls()
        lanlan_list: list[JsonObject] = []
        for name in self._lanlan_index:
            item_shard = self._get_shard(name)
            try:
                item_phase = self._current_phase_state(item_shard).phase
            except TideConfigError:
                item_phase = "error"
            except Exception:  # noqa: BLE001 - 摘要尽力而为，单角色异常不拖垮面板
                item_phase = ""
            lanlan_list.append(
                {
                    "name": name,
                    "enabled": self._enabled(item_shard),
                    "phase": item_phase,
                    "mood_active": self._mood_enabled(item_shard) and item_shard.mood.is_active(),
                    # 动作 id 一并下发：面板管理区徽标按语气分色（正面 success/其余 warning）
                    "mood_action": item_shard.mood.action if item_shard.mood.is_active() else "",
                    "orphan": bool(known is not None and name not in known),
                }
            )

        # 时光日记时间线（混排她的手记与自动碎片，按时间倒序）：碎片仅截 12 条防膨胀；
        # source 缺省按 self 处理（0.6.x 旧数据零迁移）
        def _diary_view(item: JsonObject) -> JsonObject:
            item = diary_display_record(item)
            return {
                "ts": item.get("ts"),
                "source": str(item.get("source") or "self"),
                "kind": item.get("kind"),
                "mood": item.get("mood"),
                "entry": item.get("entry"),
                "quote": item.get("quote"),
                "note": item.get("note"),
                # 生命周期状态（写入后治理）：缺省 active，与 recall_fragments 同口径。
                # 面板用它区分现行碎片与已被更新的旧记录。
                "status": str(item.get("status") or "active"),
                **{key: value for key, value in lifecycle_view(item).items() if key in {"memory", "memory_state"}},
            }

        recent_diary = diary_partition(shard.diary)
        auto_count = sum(1 for item in recent_diary if str(item.get("source") or "self") == "auto")
        # 模型通道状态灯（情绪页"模型通道"卡 + 总览共用）：三个小模型通道各自
        # 能否工作 + 休眠原因 + 实际走的那条路（transport）。语气走宿主情感端点
        # （enabled 判定），碎片/成文按各自 mode 走宿主管线或自定义直连
        tone_slot = str(self._emotion_sense_cfg.get("slot") or "").strip()
        channel_status = {
            "tone": {
                "enabled": self._emotion_sense_enabled(shard),
                "dormant_reason": "",
                # 语气没有 mode 旋钮：槽位留空/emotion = 经宿主端点，选了别的槽才是直连
                "transport": (
                    "gateway" if tone_slot == "gateway" else
                    _CHANNEL_TRANSPORT_DIRECT if tone_slot and tone_slot != "emotion" else _CHANNEL_TRANSPORT_HOST
                ),
            },
            "fragments": await self._channel_dormancy(
                self._fragments_enabled(shard),
                self._fragments_cfg,
                default_slot=_FRAGMENT_DEFAULT_SLOT,
                lanlan=lanlan,
                channel="fragments",
                shard=shard,
            ),
            "review": await self._channel_dormancy(
                self._review_enabled(shard),
                self._review_cfg,
                default_slot=_REVIEW_DEFAULT_SLOT,
                lanlan=lanlan,
                channel="review",
                shard=shard,
            ),
        }
        if tone_slot == "gateway":
            channel_status["tone"]["dormant_reason"] = self._model_gateway.readiness("tone")
            if self._agent_tier_gate(shard, "agent", ignore_pace=True):
                channel_status["tone"]["dormant_reason"] = _CHANNEL_BUDGET_REASON
        # 近 7 天互动轮数（总览"相处信号"卡）：从时光日记/手记时间戳聚合太粗，
        # 直接看 review_stats 太短视（成文即清零）——改为统计 diary 时间线里
        # 最近 7 天的条目数（她的手记+碎片都是互动的沉淀，可作相处活跃度的代理）
        week_turns = self._week_activity_count(shard)
        snapshot = {
            # 面板只读角色列表数据源：lanlan=宿主当前角色（自动跟随），lanlan_list=全部已知角色摘要
            "lanlan": lanlan,
            "lanlan_list": lanlan_list,
            "status": status,
            "anchor_date": str(shard.cycle.get("anchor_date") or self._tide_cfg.get("anchor_date") or ""),
            "advance_days": int(shard.cycle.get("advance_days") or 0),
            "mood": mood_payload,
            "settings": self._settings_snapshot(shard),
            # 面板外观（1.2.0）：图库/外观参数不进轮询，面板打开时走
            # get_panel_gallery 一次性按需拉取（原"轻量标记"通道前端从未消费，已删）
            # 语气分析模型槽位下拉选项（含各槽当前模型名；拉取失败时静态兜底）
            "tone_slot_options": await self._tone_slot_options(),
            "calendar": calendar,
            "diary_recent": [_diary_view(item) for item in reversed(recent_diary[-12:])],
            "diary_total": len(recent_diary),
            "diary_archive_total": len(shard.diary) - len(recent_diary),
            "fragment_total": auto_count,
            # 个人日记（书页式）：index 供面板展示页数概览（极轻量，进 5s 轮询）；
            # 全量翻阅走 get_journal 入口按需拉取，不进轮询
            "journal_index": [page_header(page) for page in shard.journal],
            # 藏书阁（1.3.0）：合订本概览（极轻量：本数 + 时段）——面板据此在书架
            # 末尾决定画不画那根横放书脊；全量翻阅走 get_journal_archive 按需拉取
            "journal_archive_brief": archive_brief(shard.journal_archive),
            # 邀请挂起态（1.2.3）：递过邀请、她还没落笔——日记页显示"等她"提示，
            # 免得"点了没反应、过一会凭空多一页"
            "journal_invite_pending": self._journal_invite_pending(shard),
            "journal_write": {
                "writing": shard.pending_journal_write is not None or lanlan in self._journal_writing,
                "last_result": shard.journal_write_result,
            },
            # 我的日记（0.8.0）：篇数 + 素材进度（极轻量）；全量翻阅走
            # get_review 入口按需拉取，成文正文不进 5s 轮询。
            # writing / last_result（1.2.3）：面板「立即写一篇」改排队成文后的
            # 回流通道——写作中点亮按钮禁用态；last_result={ts,written,reason}
            # 是队列成文的成败结论，面板按 ts 去重弹一次 toast（内存即弃）
            "review_brief": {
                "last_ts": str(shard.review[-1].get("ts") or "") if shard.review else "",
                "enabled": self._review_enabled(shard),
                "entries": len(shard.review),
                "progress_turns": int(shard.review_stats.get("turns") or 0),
                "turns_threshold": self._review_turns_threshold(),
                "writing": bool(shard.pending_review_write) or lanlan in self._review_writing,
                "last_result": shard.review_write_result,
            },
            # 档案室（1.3.0）：旧卷宗合档概览（极轻量：卷数 + 时段）——面板据此
            # 决定画不画档案架末尾那只档案盒；全量翻阅走 get_review(scope=archive)
            "review_archive_brief": review_archive_brief(shard.review_archive),
            # 模型通道状态灯（情绪页"模型通道"卡）：""(正常) / free_route / no_model / disabled
            "channel_status": channel_status,
            # agent 档当日消耗读数（1.3.3 修订轮）：预算是全局配置、消耗按角色记，
            # 所以这一份随 shard 下发而不塞进 settings 快照；面板只给读数
            "agent_tier_usage": {
                "used": tier_budget_used(shard.cycle, str(self._today_str())),
                "budget": self._agent_tier_budget(),
            },
            # 能力中心总览（1.2.7）：功能页数据源随 5s 轮询下发（纯内存小载荷）。
            # 与总开关/设置页/后台变化同帧一致——"按需拉一次就定格"的窗口不存在；
            # list_capabilities 入口保留（API/调试），同一构建器口径唯一
            "capabilities": self._cap_view(lanlan),
            # 近 7 天相处活跃度（总览"相处信号"卡）：时光日记近 7 天条目数
            "week_activity": week_turns,
            # 相处统计（1.1.0）：数字摘要 + 徽章墙进 5s 轮询（纯本地即时计算，
            # 开销可忽略）；热力图/月报数据量大，走 get_stats 入口按需拉取
            "stats_summary": self._stats_summary_view(shard),
            # 生日轻语（1.3.1）：时光页生日设置卡数据（纯本地，零 IO）。
            # 1.3.1 改版：倒数/当天视图字段随总览生日卡一同退役
            "birthday": self._birthday_view(),
            # 新手引导 + 就绪清单（1.2.6）：wizard_pending 读内存位（面板关闭
            # 向导时同步更新，5s 轮询滞后期不会重复弹窗）；清单纯本地即时计算，
            # 零模型开销、零新增 IO
            "onboarding": {
                "wizard_pending": wizard_pending(self._guide),
                "guide": dict(self._guide),
                "readiness": build_readiness(
                    {
                        "rhythm": self._enabled(shard),
                        "anchor": bool(str(shard.cycle.get("anchor_date") or self._tide_cfg.get("anchor_date") or "")),
                        "mood": self._cap_config_on("mood_engine", lanlan),
                        "channels": self._channels_any_live(channel_status),
                        "together": bool(shard.stats.get("first_seen")),
                    }
                ),
            },
        }

        self._dashboard_snapshot = snapshot
        self._dashboard_snapshot_at = time.monotonic()
        return snapshot

    @ui.action(label=tr("actions.refresh.label", default="刷新"), refresh_context=False)
    @plugin_entry(
        id="poll_dashboard",
        name=tr("actions.refresh.label", default="刷新"),
        description="Refresh panel state.",
        metadata={"agent_hidden": True},
    )
    async def poll_dashboard(self, **_: Any):
        # Hosted action authorization has just queried dashboard. Reuse that
        # frame instead of computing it twice or returning all locale bundles.
        if time.monotonic() - getattr(self, "_dashboard_snapshot_at", -1000.0) > 1.0:
            return Ok(await self.dashboard())
        return Ok(self._dashboard_snapshot)

    def _birthday_view(self) -> JsonObject:
        """生日设置卡轮询视图：哪天/设没设/留不留纪念手记（全局日期，各角色同值）。"""
        cfg = getattr(self, "_birthday_cfg", None) or {}
        raw = str(cfg.get("date") or "").strip()
        return {
            "date": raw,
            "set": parse_birthday(raw) is not None,
            "keep_diary": cfg.get("keep_diary", True) is not False,
        }

    @staticmethod
    def _channels_any_live(channel_status: JsonObject) -> bool:
        """语气/碎片/成文三条模型通道是否至少一路可用（就绪清单信号）。"""
        for key in ("tone", "fragments", "review"):
            item = channel_status.get(key) or {}
            if item.get("enabled") and not item.get("dormant_reason"):
                return True
        return False

    def _stats_summary_view(self, shard: _LanlanShard) -> JsonObject:
        """相处统计的轮询轻量视图：数字摘要 + 徽章墙（无热力图/月报本体）。"""
        try:
            today = self._stats_today()
            return {
                "summary": summary_payload(shard.stats, today, tz=self._stats_tz()),
                "badges": badges_payload(shard.stats, today, tz=self._stats_tz()),
            }
        except Exception as exc:  # noqa: BLE001 - 统计视图尽力而为，不拖垮 dashboard
            self.logger.debug("stats summary view failed: {}", exc)
            return {"summary": {}, "badges": []}

    async def _channel_dormancy(
        self,
        enabled: bool,
        cfg: JsonObject,
        *,
        default_slot: str,
        lanlan: str = "",
        channel: str = "",
        shard: _LanlanShard | None = None,
    ) -> JsonObject:
        """模型通道状态灯：{enabled, dormant_reason, transport}。

        dormant_reason 的下发值是 ""(正常) / free_route / no_model / rejected / budget /
        disabled 六个，"正常"用空串表示（没有 "ok" 这个字面量，面板灯按空串走正常分支）；
        disabled 这个分支根本没发请求，也就没有"实际走了哪条路"可言，故它不带 transport 键。
        判据与运行时完全同源（_resolve_channel_endpoint 的镜像）：mode=host 先问
        宿主管线能不能给出该槽端点，能就绿灯；宿主模块不可用才回落直连诊断——
        所以灯报的永远是"这条路实际会怎么走"，不是配置字面。mode=custom 直接按
        直连诊断（free_route = 免费路由的端点/模型名不在存盘配置里，直连拼不出；
        no_model = 槽位没配模型）。

        rejected 是 1.3.3 修订轮补的一层：**解析得到端点只证明"知道往哪发"，不证明
        "发得通"**。灯先看熔断器（真发过请求、连续被拒到阈值才开闸），开着就不给绿灯。
        缺这一层的代价实机付过：免费路由文字档 15 次全被服务端拒，面板一路绿灯。
        budget 是同轮的第二层：agent 档带服务端日配额（宿主自己定 500 次/天，且与宿主
        agent 功能共用），当日预算用完时这条通道**是我们自己按下不发**——那既不是故障
        也不该显示成正常。两个都命中时先报 budget：那是"今天还会不会动"的直接答案，
        而 rejected 描述的那次失败早已被预算闸挡在门外、不会再发生。
        lanlan/channel 两个键供调用方点名要看哪条通道的熔断态（总览与成文回执都传）。
        """
        if not enabled:
            return {"enabled": False, "dormant_reason": "disabled"}
        slot = str(cfg.get("slot") or "").strip() or default_slot
        if _channel_mode(cfg) == "gateway":
            usage = "writing" if channel == "review" else "fragments"
            reason = self._model_gateway.readiness(usage)
            if shard is not None and self._agent_tier_gate(shard, "agent") == _CHANNEL_BUDGET_REASON:
                reason = _CHANNEL_BUDGET_REASON
            elif self._channel_break_open(lanlan, channel, "gateway|agent"):
                reason = _CHANNEL_BREAK_REASON
            return {"enabled": True, "dormant_reason": reason, "transport": "gateway"}
        if shard is not None and self._agent_tier_gate(shard, slot) == _CHANNEL_BUDGET_REASON:
            return {
                "enabled": True,
                "dormant_reason": _CHANNEL_BUDGET_REASON,
                "transport": (
                    _CHANNEL_TRANSPORT_DIRECT if _channel_mode(cfg) == _CHANNEL_MODE_CUSTOM else _CHANNEL_TRANSPORT_HOST
                ),
            }
        host = await self._resolve_host_slot(slot) if _channel_mode(cfg) != _CHANNEL_MODE_CUSTOM else None
        if host is not None:
            if channel and self._channel_break_open(lanlan, channel, _channel_route(slot, host)):
                return {
                    "enabled": True,
                    "dormant_reason": _CHANNEL_BREAK_REASON,
                    "transport": _CHANNEL_TRANSPORT_HOST,
                }
            return {"enabled": True, "dormant_reason": "", "transport": _CHANNEL_TRANSPORT_HOST}
        reason = diagnose_slot_dormancy(await self._aload_core_config(), slot)
        # 直连侧同理：诊断说"这端点能拼出来"之后，还要看真发出去的请求有没有被拒
        if not reason and channel and self._channel_break_open(lanlan, channel, _channel_route(slot, None)):
            reason = _CHANNEL_BREAK_REASON
        return {"enabled": True, "dormant_reason": reason, "transport": _CHANNEL_TRANSPORT_DIRECT}

    def _week_activity_count(self, shard: _LanlanShard) -> int:
        """近 7 天相处活跃度：时光日记时间线（手记+碎片）里 7 天内的条目数。

        手记/碎片都是互动的沉淀物，比 review_stats（成文即清零）更能反映
        "最近我们还在频繁相处吗"；纯统计零模型开销。
        """
        cutoff = _now_utc().timestamp() - 7 * 86400
        count = 0
        for item in shard.diary:
            ts = _parse_iso_ts(item.get("ts"))
            if ts is not None and ts.timestamp() >= cutoff:
                count += 1
        return count
