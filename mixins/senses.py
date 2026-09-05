"""感知与日记编排：语气感知委派 / 自动碎片捕获 / 我的日记成文 / 个人日记邀请。

拆分自 __init__.py（方法逐字搬移，仅换文件与导入）；经 Mixin 组合回
ForeverCompanionPlugin。三个链路共用"分析发生在回复落盘之后"的后置形态：

- 语气感知（[emotion_sense]）：EmotionSenseService 的同名薄委派
  （实例级 monkeypatch 链路经服务的延迟解析回调保持不变）；
- 时光日记·自动碎片（[fragments]）：recent 轮询 + 直连槽位提取 + 吵架轻语；
- 我的日记（[review]）：素材累计 + 双门槛成文 + 落盘；
- 个人日记邀请（[journal]）：节奏判定 + 素材组装 + read 邀请推送。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from plugin.sdk.plugin import Err, Result

from ..core.affect import _feed_tone_affect
from ..core.fragments import (
    build_fragment_prompt,
    fragment_record,
    parse_fragment_response,
    recall_fragments,
    should_nudge_fight,
)
from ..core.review import (
    append_review,
    build_review_prompt,
    can_force_write,
    parse_review_response,
    record_action,
    record_fragment,
    record_tone,
    record_turn,
    review_due,
    review_record,
)
from ..core.review import new_stats as review_new_stats
from ..core.state import (
    _FRAGMENT_DEFAULT_CONFIDENCE,
    _FRAGMENT_DEFAULT_MIN_INTERVAL_SEC,
    _FRAGMENT_DEFAULT_NUDGE_GAP_MIN,
    _FRAGMENT_DEFAULT_SLOT,
    _PROACTIVE_PAUSE_ACTIONS,
    _REVIEW_DEFAULT_DAYS,
    _REVIEW_DEFAULT_SLOT,
    _REVIEW_DEFAULT_TURNS,
    _LanlanShard,
    _now_utc,
)
from ..core.stats import record_milestone
from ..services.tone_slot import (
    _parse_tone_result,
    _post_chat_completion,
    _resolve_tone_slot,
    diagnose_slot_dormancy,
)

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


class SensesMixin:
    """语气感知/碎片/我的日记/个人日记邀请的主链路与配置开关。"""

    # ==========================================
    # 语气感知（[emotion_sense]）：回复完成后异步分析互动情绪
    #
    # 两种模式：
    # - 筛选（无情绪动作生效）：check_rate 概率抽查，互动情绪浓度超阈值
    #   → 中性提醒"想记录此刻心情就调情绪工具/手记"，绝大多数闲聊直接跳过；
    # - 校正（情绪动作生效中）：每轮都分析（量小），语气趋势窗口判定
    #   偏暖/偏冷 → 提醒她把面板状态切回（根治"演和好忘调工具"）。
    # 全程只递提醒、绝不自动切状态。分析发生在回复落盘之后，
    # 对生成链路零延迟（宿主没有给插件拦生成的钩子，后置是唯一解）。
    # 依赖宿主内部端点（recent_file / emotion.analysis / health；选了非默认
    # 模型槽位时另读宿主本地 core_config.json 直连该槽端点），
    # 任何一步失败都静默降级（一次性节流 warning），不影响主功能。
    # ==========================================

    # ---- 纯判定方法（配置读取/开关）已迁入 emotion_sense.py 的 EmotionSenseService
    # （A5 服务化第 1 批）；以下保留同名薄委托（名称/签名/语义不变），整体替换
    # p._emotion_sense_cfg 与实例级 monkeypatch 的链路经服务的延迟解析回调保持不变 ----

    def _emotion_sense_enabled(self, shard: _LanlanShard | None = None) -> bool:
        return self._emotion_sense._emotion_sense_enabled(shard)

    def _tone_float_cfg(self, key: str, default: float) -> float:
        return self._emotion_sense._tone_float_cfg(key, default)

    def _tone_int_cfg(self, key: str, default: int) -> int:
        return self._emotion_sense._tone_int_cfg(key, default)

    # ---- 主链路（水位 diff/门控/判定推送）已迁入 emotion_sense.py（A5 第 3 批）；
    # 以下保留同名薄委托（名称/签名/语义不变），shard 字段原地读写、tick 调用面
    # 与判定时机不变；docstring 留主类作调用面文档，实现注释见服务侧 ----

    async def _poll_recent_turns(
        self, shard: _LanlanShard, *, lanlan: str, peek: bool = False, advance: bool = True
    ) -> tuple[str, str] | None:
        """薄委托：emotion_sense._poll_recent_turns（逻辑与水位语义见该实现）。"""
        return await self._emotion_sense._poll_recent_turns(shard, lanlan=lanlan, peek=peek, advance=advance)

    # ---- HTTP 分析通道已迁入 emotion_sense.py（A5 第 2 批）；以下保留同名薄委托
    # （名称/签名/语义不变），实例级 monkeypatch（tests 打 _proactive_http/_load_core_config
    # /_post_chat_completion/_core_config_path 等）经服务的延迟解析回调依旧生效 ----

    # CSRF token 缓存随服务持有；主类留 property 代理（tests 直读 p._csrf_token）
    @property
    def _csrf_token(self) -> str | None:
        return self._emotion_sense._csrf_token

    @_csrf_token.setter
    def _csrf_token(self, value: str | None) -> None:
        self._emotion_sense._csrf_token = value

    async def _get_csrf_token(self) -> str | None:
        """宿主 CSRF token = GET /health 的 instance_id（本机回环设计如此）；缓存复用。"""
        return await self._emotion_sense._get_csrf_token()

    async def _analyze_turn_tone(self, text: str, lanlan: str) -> tuple[str, float] | None:
        """分析文本情绪，返回 (label, confidence)；失败/降级返回 None。

        [emotion_sense].slot 为空或 "emotion"（默认）→ 走宿主 /api/emotion/analysis
        （宿主情感模型槽）；选其他文本槽位 → 读宿主本地 core_config.json 解析
        该槽位的 model/base_url/api_key 直连其端点（见 _analyze_turn_tone_direct）。
        宿主未配模型时端点返回 200+error 字段——检测到即休眠（节流 warning），不当异常处理。
        请求体只带 text、不带 lanlan_name：纯静默分析，不触发宿主把结果推给前端
        改头像表情的副作用（本插件只收集情绪信号，不接管表情）。
        """
        return await self._emotion_sense._analyze_turn_tone(text, lanlan)

    # ---- 直连槽位解析：读宿主 core_config.json，把槽位配置翻译成 model/base_url/api_key ----

    def _core_config_path(self) -> Path | None:
        """宿主 core_config.json 的磁盘路径（storage_dir = <root>/plugins/<id> → 上两级是 <root>）。"""
        try:
            return Path(self.storage_dir).parents[1] / "config" / "core_config.json"
        except Exception:  # noqa: BLE001 - storage_dir 不可用时降级为"无配置"
            return None

    def _load_core_config(self) -> JsonObject:
        """读宿主 core_config.json（含明文 key），5 秒内存缓存；文件缺失/JSON 坏 → {}。"""
        return self._emotion_sense._load_core_config()

    # ---- 槽位解析与直连的纯逻辑已抽到 tone_slot.py；以下保留薄委托（名称/签名/语义不变），
    # 实例级 monkeypatch（如 tests 打 _post_chat_completion/_load_core_config）的链路不变 ----

    def _resolve_tone_slot(
        self, core_cfg: JsonObject, slot: str, _seen: frozenset[str] = frozenset()
    ) -> JsonObject | None:
        """把槽位选择解析成 {"model", "api_key", "base_url"}（解析链逻辑在 tone_slot.py）。"""
        return _resolve_tone_slot(core_cfg, slot, _seen)

    def _post_chat_completion(self, base_url: str, api_key: str, model: str, prompt: str) -> str | None:
        """同步直连 OpenAI 兼容 /chat/completions（逻辑在 tone_slot.py）；任何失败 → None。"""
        return _post_chat_completion(base_url, api_key, model, prompt, logger=self.logger)

    def _parse_tone_result(self, raw: str) -> tuple[str, float] | None:
        """解析直连模型的五分类 JSON 回复（容错与归一化逻辑在 tone_slot.py）。"""
        return _parse_tone_result(raw)

    async def _analyze_turn_tone_direct(self, text: str, slot: str) -> tuple[str, float] | None:
        """直连所选槽位的端点做五分类分析；解析不出可用端点/请求失败/回复坏 → None 静默降级。"""
        return await self._emotion_sense._analyze_turn_tone_direct(text, slot)

    # 已迁入 emotion_sense.py（A5 服务化第 1 批），同名薄委托
    def _effective_tone_threshold(self, shard: _LanlanShard) -> float:
        """筛选模式的置信度阈值 × 阶段灵敏度：潮汐期/回升期/活跃期阈值下移（更激进）。

        这是"阶段×情绪"的机制层耦合形态：阶段不改触发概率，改筛选灵敏度。
        """
        return self._emotion_sense._effective_tone_threshold(shard)

    def _feed_tone_affect(
        self, shard: _LanlanShard, label: str, confidence: float, now: float | None = None,
        weight: float = 1.0,
    ) -> None:
        """语气信号积分进连续心情（筛选/校正两种模式都喂；积分数学在 affect.py）。"""
        _feed_tone_affect(
            shard.mood, label, confidence, now=now,
            arousal_baseline=self._affect_arousal_baseline(), weight=weight,
        )
        # 我的日记素材：她的语气分布（weight<1 的用户侧传导不计——评价看
        # 的是"她的回复是什么语气"，不是用户的语气被如何传导）
        if weight >= 1.0:
            self._feed_review_tone(shard, label)
            # 相处统计：当日语气分布（热力图悬停/月报语气主色），同口径只记主路径
            self._feed_stats_tone(shard, label)

    async def _save_tone_sense_state(self, lanlan: str, shard: _LanlanShard) -> Result[None]:
        """语气感知收尾落盘（1.2.2 批次2）：mood 之外补刷 stats 与我的日记素材。

        _feed_tone_affect 把当日语气分布喂进 stats 与 review 素材（纯内存），
        过去"落盘随 mood 保存搭车"的说法是失真的——_save_shard_mood 只写 mood@
        一个 key，这批增量实际要等下一条用户消息（whisper）或 shutdown 才被
        冲刷。这里在语气分析收尾随 mood 一起即时补刷，消灭"内存有、盘上没有"
        的窗口。stats/review 写失败仅留 warning（_store_write）：感知是后台
        链路，不该变成会失败的入口；入口语义的 Err 传播见面板与情绪工具。
        """
        res = await self._save_shard_mood(lanlan, shard)
        await self._save_shard_stats(lanlan, shard)
        if self._review_enabled(shard) and (shard.review or shard.review_stats):
            await self._save_shard_review(lanlan, shard)
        return res

    async def _maybe_tone_sense(self, lanlan: str, shard: _LanlanShard) -> bool:
        """语气感知主入口（tick 驱动，只对当前角色 shard）：门控链 → 分析 → 分模式判定。"""
        return await self._emotion_sense._maybe_tone_sense(lanlan, shard)

    def _tone_correction_check(self, lanlan: str, shard: _LanlanShard, label: str) -> bool:
        """校正模式：label 入趋势窗口，攒满 window_turns 判定一次（多数派），判定后清空。"""
        return self._emotion_sense._tone_correction_check(lanlan, shard, label)

    def _tone_screen_check(
        self, lanlan: str, shard: _LanlanShard, label: str, confidence: float
    ) -> bool:
        """筛选模式：互动情绪浓度超阈值（敏感期下移）→ 中性提醒，10 分钟节流。"""
        return self._emotion_sense._tone_screen_check(lanlan, shard, label, confidence)

    # ==========================================
    # 时光日记·自动碎片（[fragments]，0.7.0）：小模型从用户消息里捕获
    # "值得她记一辈子的片段"——明确的喜好厌恶、有分量的话、对她的过激言行。
    # 复用语气感知的 recent.json 轮询与槽位直连基建，但水位独立：
    # 语气感知采样跳过的轮次仍会进碎片分析（碎片不吃 check_rate 抽样）。
    # ==========================================

    def _fragments_float_cfg(self, key: str, default: float) -> float:
        try:
            return float(self._fragments_cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    def _fragments_enabled(self, shard: _LanlanShard | None = None) -> bool:
        """碎片捕获开关：跟随总开关与情绪系统开关，另有 [fragments].enabled 独立闸。"""
        return bool(self._mood_enabled(shard) and self._fragments_cfg.get("enabled", True))

    async def _maybe_capture_fragments(self, lanlan: str, shard: _LanlanShard) -> bool:
        """碎片捕获主入口（tick 驱动，只对当前角色 shard）。

        门控链：开关 → 最小间隔 → 独立水位（新轮判定，复用同趟 recent 数据）→
        直连槽位提取 → 置信度门槛 → 落盘时间线 → 吵架轻语判定。
        首趟只建基线不分析历史（与语气感知同款：插件启动不补记旧对话）。
        模型槽位在宿主 core_config.json 解析不出 key 时功能休眠（节流 warning），
        其余功能不受影响；捕获失败静默降级，绝不拖垮 tick。
        """
        if not self._fragments_enabled(shard):
            return False
        now = time.time()
        min_interval = self._fragments_float_cfg(
            "min_interval_sec", _FRAGMENT_DEFAULT_MIN_INTERVAL_SEC
        )
        if now - shard.last_fragment_analysis_ts < max(0.0, min_interval):
            return False
        # advance=False：这轮是否"新"由碎片自己的水位判定（语气感知的抽样/门控不牵连）
        turn = await self._poll_recent_turns(shard, lanlan=lanlan, advance=False)
        if turn is None:
            return False
        user_text, her_text = turn
        marker = shard.last_recent_marker
        if not shard.last_fragment_marker:
            shard.last_fragment_marker = marker  # 基线：不分析历史
            return False
        if marker == shard.last_fragment_marker:
            return False
        user_text = (user_text or "").strip()
        if not user_text:
            shard.last_fragment_marker = marker
            return False
        slot = str(self._fragments_cfg.get("slot") or "").strip() or _FRAGMENT_DEFAULT_SLOT
        core_cfg = self._load_core_config()
        resolved = self._resolve_tone_slot(core_cfg, slot)
        if resolved is None:
            shard.last_fragment_marker = marker
            shard.last_fragment_analysis_ts = now
            now_mono = time.monotonic()
            if now_mono - self._last_fragment_dormant_logged > 300:
                self._last_fragment_dormant_logged = now_mono
                self.logger.warning(
                    "fragment capture dormant: slot {} unresolved in host core_config ({}), (throttled 5min)",
                    slot, _slot_dormancy_hint(core_cfg, slot),
                )
            return False
        shard.last_fragment_marker = marker
        shard.last_fragment_analysis_ts = now
        raw = await asyncio.to_thread(
            self._post_chat_completion,
            resolved["base_url"], resolved["api_key"], resolved["model"],
            build_fragment_prompt(user_text, her_text),
        )
        parsed = parse_fragment_response(raw or "")
        if parsed is None or not parsed.get("capture"):
            return False
        threshold = self._fragments_float_cfg("confidence_threshold", _FRAGMENT_DEFAULT_CONFIDENCE)
        if float(parsed.get("confidence") or 0.0) < threshold:
            self.logger.debug(
                "fragment dropped below confidence: kind={} conf={:.2f} threshold={:.2f}",
                parsed.get("kind"), parsed.get("confidence") or 0.0, threshold,
            )
            return False
        record = fragment_record(_now_utc().isoformat(timespec="seconds"), self._last_phase_name(shard), parsed)
        shard.diary.append(record)
        # 我的日记素材：碎片原话是"他说话方式"的最硬例证（含过激言行）
        self._feed_review_fragment(shard, record)
        await self._save_shard_diary(lanlan, shard)
        self.logger.info(
            "fragment captured: lanlan={} kind={} quote={!r}", lanlan, record["kind"], record["quote"]
        )
        await self._maybe_fragment_fight_nudge(lanlan, shard, record, now)
        return True

    async def _maybe_fragment_fight_nudge(
        self, lanlan: str, shard: _LanlanShard, record: JsonObject, now: float
    ) -> None:
        """吵架轻语：重度负面动作生效中又捕获到"过激/厌恶"类碎片时，
        低频提醒一句"你记得吗"（附一条相关的旧碎片作佐证）——她可以忽略，
        用不用、怎么用仍由她自己决定。"""
        action = shard.mood.action if shard.mood.is_active() else ""
        if not should_nudge_fight(record, action, _PROACTIVE_PAUSE_ACTIONS):
            return
        gap_min = self._fragments_float_cfg("nudge_gap_minutes", _FRAGMENT_DEFAULT_NUDGE_GAP_MIN)
        if now - shard.last_fragment_nudge_ts < max(60.0, gap_min * 60):
            return
        related = recall_fragments(shard.diary, kind=str(record["kind"]), limit=2)
        related_hint = ""
        for item in related:
            if item is record:
                continue
            related_hint = f"之前还记过一笔：「{item.get('quote')}」。"
            break
        shard.last_fragment_nudge_ts = now
        self.push_message(
            visibility=[],
            ai_behavior="read",
            parts=[{"type": "text", "text": (
                f"（时光日记提醒）你刚刚在心里记下了一笔：他说「{record.get('quote')}」"
                f"（{record.get('note') or '此刻的事'}）。{related_hint}"
                "如果这笔账你还放在心上，可以调用 mood_recall_fragments 翻翻这本日记，"
                "再用你自己的方式让他知道。想翻篇的话，忽略就好。"
            )}],
            source=self.plugin_id,
            target_lanlan=lanlan,
            coalesce_key=f"{self.plugin_id}.fragment_nudge",
            metadata={"message_type": f"{self.plugin_id}.fragment_nudge", "kind": record["kind"]},
        )
        self.logger.info("fragment fight nudge pushed for {} (kind={})", lanlan, record["kind"])

    # ==========================================
    # 我的日记（[review]，0.8.0）：关于主人的互动评价
    #
    # 第三本日记，只给用户看：不注入她的上下文、不进宿主记忆管线、不注册
    # 任何她可调用的 LLM 工具（隔离等级比个人日记更严——她连知道这本日记
    # 存在的渠道都没有）。素材纯本地累计（轮数/语气分布/心情采样/情绪动作
    # 事件/碎片原话），平时零模型开销；双门槛先到先写（满 N 轮或满 N 天
    # 且期间有聊天），成文时一次小模型调用（碎片同款直连槽位），中性观察者
    # 口吻、纯文字无评分、负面行为如实记录不粉饰。
    # ==========================================

    def _review_enabled(self, shard: _LanlanShard | None = None) -> bool:
        """我的日记开关：跟随总开关与情绪系统开关（素材来自语气感知/碎片等
        情绪链路），另有 [review].enabled 独立闸。"""
        return bool(self._mood_enabled(shard) and self._review_cfg.get("enabled", True))

    def _review_int_cfg(self, key: str, default: int) -> int:
        try:
            return max(1, int(self._review_cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _review_turns_threshold(self) -> int:
        return self._review_int_cfg("turns_threshold", _REVIEW_DEFAULT_TURNS)

    def _review_days_threshold(self) -> int:
        return self._review_int_cfg("days_threshold", _REVIEW_DEFAULT_DAYS)

    def _feed_review_turn(self, lanlan: str, shard: _LanlanShard) -> None:
        """记一轮互动进素材统计（每条新用户消息一次，随 _save 落盘由调用方决定）。

        valence 采样与语气分析异步不同步（这里取的是"此刻"的惰性衰减值，
        成文看的是趋势不是精确对应），足够刻画相处氛围的走向。
        """
        if not self._review_enabled(shard):
            return
        valence = self._current_affect(shard)[0] if shard.mood.affect_updated_at else None
        shard.review_stats = record_turn(shard.review_stats, valence=valence)

    def _feed_review_tone(self, shard: _LanlanShard, label: str) -> None:
        """记一次语气分析结果（她的回复被分析出 label 时）。纯内存累加，
        即时落盘由语气感知收尾 _save_tone_sense_state 随 mood 一起补刷
        （stats 与 review 素材同步冲刷，不再等下一条用户消息）。"""
        if not self._review_enabled(shard):
            return
        shard.review_stats = record_tone(shard.review_stats, label)

    def _feed_review_action(self, shard: _LanlanShard, action: str, *, origin: str) -> None:
        """记一次情绪动作事件。origin=user 的（主人命令触发的演示）也记——
        评价是客观记录，"他让她演示了一次冷战"本身是相处方式的一部分，
        只是成文 prompt 里单独标注、与"她自己起的情绪"区分开。"""
        if not self._review_enabled(shard):
            return
        shard.review_stats = record_action(shard.review_stats, action, origin=origin)

    def _feed_review_fragment(self, shard: _LanlanShard, record: JsonObject) -> None:
        """记一条新捕获碎片的原话（成文时作为"他说话方式"的具体例证）。"""
        if not self._review_enabled(shard):
            return
        shard.review_stats = record_fragment(shard.review_stats, str(record.get("kind") or ""), str(record.get("quote") or ""))

    async def _maybe_write_review(self, lanlan: str, shard: _LanlanShard, *, force: bool = False) -> tuple[bool, str]:
        """我的日记主入口（tick 驱动 + 面板「立即写一篇」共用）。

        门控链：开关 → （force 时最小素材量 / 平时双门槛）→ 直连槽位成文 →
        解析截断 → 篇目追加 + stats 原子清零落盘。槽位解析不出 key 时功能
        休眠（节流 warning），失败静默降级绝不拖垮 tick。返回 (是否写了, 原因)。
        """
        if not self._review_enabled(shard):
            return False, "disabled"
        # 门槛先于槽位休眠判定：素材不足/未到期时无论槽位状态都该报"未到节奏"，
        # 面板调试时才不会被休眠日志误导
        if force:
            if not can_force_write(shard.review_stats):
                return False, "not_enough_material"
        else:
            due, reason = review_due(
                shard.review_stats,
                turns_threshold=self._review_turns_threshold(),
                days_threshold=self._review_days_threshold(),
            )
            if not due:
                return False, reason
        slot = str(self._review_cfg.get("slot") or "").strip() or _REVIEW_DEFAULT_SLOT
        core_cfg = self._load_core_config()
        resolved = self._resolve_tone_slot(core_cfg, slot)
        if resolved is None:
            now_mono = time.monotonic()
            if now_mono - self._last_review_dormant_logged > 300:
                self._last_review_dormant_logged = now_mono
                self.logger.warning(
                    "review compose dormant: slot {} unresolved in host core_config ({}), (throttled 5min)",
                    slot, _slot_dormancy_hint(core_cfg, slot),
                )
            return False, "slot_unresolved"
        # 成文素材：累计统计 + 最近几轮对话摘样（一次性拉取宿主 recent 窗口）
        sample_turns = await self._collect_review_sample_turns(shard, lanlan)
        prompt = build_review_prompt(shard.review_stats, sample_turns=sample_turns)
        raw = await asyncio.to_thread(
            self._post_chat_completion,
            resolved["base_url"], resolved["api_key"], resolved["model"], prompt,
        )
        text = parse_review_response(raw or "")
        if not text:
            # 留痕分级（1.2.2 审查轮）：面板提示"稍后再试（详见插件日志）"，
            # 过去这条路径完全静默（请求失败也只有 debug 级）——让用户查无可查。
            # raw=None 请求失败（_post_chat_completion 已另有 warning）；
            # 否则是回复为空/剥壳后无正文，带上长度与前 40 字符预览便于判断话风
            if raw is None:
                detail = "request failed (see 'tone direct chat completion' warning above)"
            else:
                detail = f"empty or unparsable reply (len={len(raw)}, head={str(raw)[:40]!r})"
            self.logger.warning("review compose failed for {}: {}", lanlan, detail)
            return False, "compose_failed"
        stats_snapshot = dict(shard.review_stats)
        record = review_record(_now_utc().isoformat(timespec="seconds"), stats_snapshot, text)
        # 写入前快照：落盘失败要整体回滚——过去"先追加内存+清零素材、再写
        # （且不检查结果）"，真失败（磁盘满/DB 锁）会让这一篇与整段素材永久丢失，
        # 面板却显示成功
        prev_review = list(shard.review)
        prev_stats = dict(shard.review_stats)
        shard.review = append_review(shard.review, record)
        shard.review_stats = review_new_stats()  # 成文后清零重新累计（review 的 new_stats，勿与 stats 的同名混淆）
        res = await self._save_shard_review(lanlan, shard)
        if isinstance(res, Err):
            # 回滚内存到快照：盘上还是旧内容，内存必须与盘上同构，否则篇目
            # "存在"于本次会话、重启即人间蒸发；素材清零同样撤销，门槛仍成立，
            # 下一趟 tick / 下一次面板触发可重试（不因一次写失败永久卡死）
            shard.review = prev_review
            shard.review_stats = prev_stats
            return False, "persist_failed"
        # 相处统计：第一篇我的日记里程碑（不覆盖最早值）；这次 stats 写失败仅
        # _store_write 留 warning，篇目已安全落盘，可接受
        shard.stats = record_milestone(shard.stats, "first_review")
        await self._save_shard_stats(lanlan, shard)
        self.logger.info(
            "review composed for {} (turns={}, entries={})", lanlan, record["turns"], len(shard.review)
        )
        return True, "written"

    async def _collect_review_sample_turns(
        self, shard: _LanlanShard, lanlan: str
    ) -> list[tuple[str, str]]:
        """成文时取最近几轮对话摘样（peek 不动水位，复用 recent 轮询基建）。

        拉不到（宿主不可达/没有记录）就给空列表——素材统计仍够成文，
        摘样只是锦上添花的语境。
        """
        try:
            turn = await self._poll_recent_turns(shard, lanlan=lanlan, peek=True)
        except Exception:  # noqa: BLE001 - 摘样是锦上添花，任何失败都不拦成文
            return []
        return [turn] if turn is not None else []
