"""永远的陪伴 (Forever Companion)

让猫娘拥有自己的身体节律与情绪波动。

以"潮汐"为核心意象：她的身体与情绪像潮水一样有节律地涨落，
插件只递状态、摆工具，什么时候退潮、什么时候涨潮，由她自己决定。

架构（一段话）：``@timer_interval`` 每 10 秒轮询用户消息总线
（``ctx.bus.memory.get(bucket_id="default")`` 读 ``type="user_message"`` 记录，
记录 payload 带 ``lanlan`` 字段标明归属角色；平台不会主动向插件派发聊天事件，
watcher 订阅机制只支持 messages/events/lifecycle 总线，memory 总线不可订阅，
故轮询是插件侧唯一可行通道）。0.5.0 起采用 per-lanlan 状态分片：每个角色有独立的
开关/锚点/快进天数/周期参数/情绪状态/心情手记（Store key ``cycle@<角色>``/
``mood@<角色>``/``diary@<角色>``，角色名原文进 key、不做 normalize），
注入策略、阶段提示词文案、时区等仍为全局配置（Store key ``settings`` 覆盖层）。
检测到归属某角色的新消息且该角色开启模拟时，用
``push_message(target_lanlan=<角色>, visibility=[], ai_behavior="read")``
把当前阶段的身体感受定向注入该角色的模型上下文——多会话下不指定
target_lanlan 的消息会被宿主整条丢弃。情绪系统把十个动作注册为 ``@llm_tool``
——负面梯度：冷战沉默/已读不回/敷衍应付/情绪风暴/想要被安抚；中间态：
心有涟漪（有点小情绪、一哄就好）；正面：暖流涌动（想黏人撒娇）/满潮欢喜
（开心想分享）；外加通用出口心情转晴与心情手记，
按 kwargs 里的 ``_ctx.lanlan_name`` 归因到具体角色 shard（缺省归因当前角色）；
限时动作到期后由同一个 timer 自动解除并广播恢复。宿主主动搭话的暂停是全局
开关上的引用计数（白名单制：只有重度负面动作生效才暂停，中间态/正面动作
不暂停），水位存 ``proactive_state``。旧版单角色数据（cycle_state/mood_state/mood_diary）
在启动时一次性迁移归属当前角色，旧 key 保留作备份、不再写入。
"""

from __future__ import annotations

import asyncio
import inspect
import random as random  # 再导出：tm.random 是测试猴补丁锚点（patch stdlib 模块对象属性，所有 import 者同生效）
import threading
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from plugin.sdk.plugin import (
    Err,
    NekoPluginBase,
    Ok,
    Result,
    SdkError,
    lifecycle,
    llm_tool,
    neko_plugin,
    plugin_entry,
    quick_action,
    timer_interval,
    tr,
    ui,
)

try:
    from .cycle import (
        TideConfigError,
        _time_bucket,
        build_body_whisper,
        build_month_calendar,
        build_status_payload,
        compute_phase_state,
        derive_cycle_params,
        parse_anchor_date,
        randomized_default_anchor,
        resolve_today,
    )
except ImportError:  # pragma: no cover - 无父包上下文的兜底（如独立仓库里 pytest 把
    # 根目录当 Package 直接导入 __init__.py，宿主环境不会出现此路径）
    from cycle import (  # type: ignore[no-redef]
        TideConfigError,
        _time_bucket,
        build_body_whisper,
        build_month_calendar,
        build_status_payload,
        compute_phase_state,
        derive_cycle_params,
        parse_anchor_date,
        randomized_default_anchor,
        resolve_today,
    )

# 纯数据/纯函数区段的解耦抽出（第一/二批重构）：state.py = Store 布局/常量表/
# _MoodState/_LanlanShard 数据类；weekly.py = 周记资格判定；affect.py = 连续心情数学；
# tone_slot.py = 语气槽位解析与直连。这里导入即再导出——tm._MoodState、
# tm._STORE_SETTINGS、tm._TONE_* 等既有引用路径全部不变；主类只留薄委托方法。
try:
    from .affect import (
        _MOOD_AFFECT_IMPULSES,
        _apply_affect_impulse,
        _current_affect,
        _feed_tone_affect,
    )
    from .emotion_sense import EmotionSenseService
    from .fragments import (
        build_fragment_prompt,
        fragment_record,
        parse_fragment_response,
        recall_fragments,
        should_nudge_fight,
    )
    from .journal import (
        assemble_journal_entry,
        has_journal_content,
        journal_due,
        journal_write,
        migrate_weekly_to_pages,
        page_header,
    )
    from .review import (
        append_review,
        build_review_prompt,
        can_force_write,
        new_stats,
        parse_review_response,
        record_action,
        record_fragment,
        record_tone,
        record_turn,
        review_due,
        review_record,
    )
    from .state import (
        _ACTION_DEFAULT_MINUTES,
        _COLD_ACTIONS,
        _CURRENT_LANLAN_CACHE_TTL,
        _DIARY_MAX_ENTRIES,
        _FRAGMENT_DEFAULT_CONFIDENCE,
        _FRAGMENT_DEFAULT_MIN_INTERVAL_SEC,
        _FRAGMENT_DEFAULT_NUDGE_GAP_MIN,
        _FRAGMENT_DEFAULT_SLOT,
        _JOURNAL_DEFAULT_INTERVAL_DAYS,
        _JOURNAL_INVITE_THROTTLE_SEC,
        _JOURNAL_MAX_PAGES,
        _KNOWN_CATGIRLS_CACHE_TTL,
        _MOOD_ACTION_DEFAULT_LABELS,
        _MOOD_ACTION_LABEL_KEYS,
        _PANEL_BG_DEFAULT_DIM,
        _PANEL_BG_MAX_CHARS,
        _PANEL_BG_MIMES,
        _POSITIVE_ACTIONS,
        _PROACTIVE_PAUSE_ACTIONS,
        _REVIEW_DEFAULT_DAYS,
        _REVIEW_DEFAULT_SLOT,
        _REVIEW_DEFAULT_TURNS,
        _REVIEW_MIN_TURNS_FORCED,
        _STORE_CYCLE,
        _STORE_DIARY,
        _STORE_LANLAN_INDEX,
        _STORE_MOOD,
        _STORE_PANEL_BG,
        _STORE_PROACTIVE,
        _STORE_SETTINGS,
        _TIMED_ACTIONS,
        _TONE_COLD_LABELS,
        _TONE_SLOT_OPTIONS_CACHE_TTL,
        _TONE_SLOT_PREFIXES,
        _cfg_section,
        _cycle_key,
        _diary_key,
        _journal_key,
        _LanlanShard,
        _mood_key,
        _MoodState,
        _now_utc,
        _review_key,
        _review_stats_key,
        _stats_key,
        _weekly_key,
    )
    from .state import (
        _AFFECT_AROUSAL_TAU_SEC as _AFFECT_AROUSAL_TAU_SEC,
    )
    from .state import (
        _AFFECT_VALENCE_TAU_SEC as _AFFECT_VALENCE_TAU_SEC,
    )
    from .state import (
        _ASSIST_KEY_FIELDS as _ASSIST_KEY_FIELDS,
    )
    from .state import (
        _CORE_CONFIG_CACHE_TTL as _CORE_CONFIG_CACHE_TTL,
    )
    from .state import (
        _REVIEW_ENTRY_MAX_CHARS as _REVIEW_ENTRY_MAX_CHARS,
    )
    from .state import (
        _REVIEW_MAX_ENTRIES as _REVIEW_MAX_ENTRIES,
    )
    from .state import (
        _TONE_AFFECT_AROUSAL_STEP as _TONE_AFFECT_AROUSAL_STEP,
    )
    from .state import (
        _TONE_AFFECT_DIRECTIONS as _TONE_AFFECT_DIRECTIONS,
    )
    from .state import (
        _TONE_AFFECT_VALENCE_STEP as _TONE_AFFECT_VALENCE_STEP,
    )
    from .state import (
        _TONE_DIRECT_PROMPT as _TONE_DIRECT_PROMPT,
    )
    from .state import (
        _TONE_EMOTION_ALIASES as _TONE_EMOTION_ALIASES,
    )
    from .state import (
        _TONE_SCREEN_NUDGE_SEC as _TONE_SCREEN_NUDGE_SEC,
    )
    from .state import (
        _TONE_WARM_LABELS as _TONE_WARM_LABELS,
    )
    from .state import (
        _parse_iso_ts as _parse_iso_ts,
    )
    from .stats import (
        anniversary_due,
        backfill_day,
        badges_payload,
        heatmap_payload,
        mark_anniversary_pushed,
        month_view,
        record_made_up,
        record_milestone,
        record_mood_event,
        seal_due_months,
        summary_payload,
    )
    from .stats import record_tone as stats_record_tone
    from .stats import record_turn as stats_record_turn
    from .tone_slot import (
        _parse_tone_result,
        _post_chat_completion,
        _resolve_tone_slot,
        diagnose_slot_dormancy,
    )
except ImportError:  # pragma: no cover - 无父包上下文的兜底（同上 cycle 分支）
    from affect import (  # type: ignore[no-redef]
        _MOOD_AFFECT_IMPULSES,
        _apply_affect_impulse,
        _current_affect,
        _feed_tone_affect,
    )
    from emotion_sense import EmotionSenseService  # type: ignore[no-redef]
    from fragments import (  # type: ignore[no-redef]
        build_fragment_prompt,
        fragment_record,
        parse_fragment_response,
        recall_fragments,
        should_nudge_fight,
    )
    from journal import (  # type: ignore[no-redef]
        assemble_journal_entry,
        has_journal_content,
        journal_due,
        journal_write,
        migrate_weekly_to_pages,
        page_header,
    )
    from review import (  # type: ignore[no-redef]
        append_review,
        build_review_prompt,
        can_force_write,
        new_stats,
        parse_review_response,
        record_action,
        record_fragment,
        record_tone,
        record_turn,
        review_due,
        review_record,
    )
    from state import (  # type: ignore[no-redef]
        _ACTION_DEFAULT_MINUTES,
        _COLD_ACTIONS,
        _CURRENT_LANLAN_CACHE_TTL,
        _DIARY_MAX_ENTRIES,
        _FRAGMENT_DEFAULT_CONFIDENCE,
        _FRAGMENT_DEFAULT_MIN_INTERVAL_SEC,
        _FRAGMENT_DEFAULT_NUDGE_GAP_MIN,
        _FRAGMENT_DEFAULT_SLOT,
        _JOURNAL_DEFAULT_INTERVAL_DAYS,
        _JOURNAL_INVITE_THROTTLE_SEC,
        _JOURNAL_MAX_PAGES,
        _KNOWN_CATGIRLS_CACHE_TTL,
        _MOOD_ACTION_DEFAULT_LABELS,
        _MOOD_ACTION_LABEL_KEYS,
        _PANEL_BG_DEFAULT_DIM,
        _PANEL_BG_MAX_CHARS,
        _PANEL_BG_MIMES,
        _POSITIVE_ACTIONS,
        _PROACTIVE_PAUSE_ACTIONS,
        _REVIEW_DEFAULT_DAYS,
        _REVIEW_DEFAULT_SLOT,
        _REVIEW_DEFAULT_TURNS,
        _REVIEW_MIN_TURNS_FORCED,
        _STORE_CYCLE,
        _STORE_DIARY,
        _STORE_LANLAN_INDEX,
        _STORE_MOOD,
        _STORE_PANEL_BG,
        _STORE_PROACTIVE,
        _STORE_SETTINGS,
        _TIMED_ACTIONS,
        _TONE_COLD_LABELS,
        _TONE_SLOT_OPTIONS_CACHE_TTL,
        _TONE_SLOT_PREFIXES,
        _cfg_section,
        _cycle_key,
        _diary_key,
        _journal_key,
        _LanlanShard,
        _mood_key,
        _MoodState,
        _now_utc,
        _review_key,
        _review_stats_key,
        _stats_key,
        _weekly_key,
    )
    from state import (
        _AFFECT_AROUSAL_TAU_SEC as _AFFECT_AROUSAL_TAU_SEC,
    )
    from state import (
        _AFFECT_VALENCE_TAU_SEC as _AFFECT_VALENCE_TAU_SEC,
    )
    from state import (
        _ASSIST_KEY_FIELDS as _ASSIST_KEY_FIELDS,
    )
    from state import (
        _CORE_CONFIG_CACHE_TTL as _CORE_CONFIG_CACHE_TTL,
    )
    from state import (
        _REVIEW_ENTRY_MAX_CHARS as _REVIEW_ENTRY_MAX_CHARS,
    )
    from state import (
        _REVIEW_MAX_ENTRIES as _REVIEW_MAX_ENTRIES,
    )
    from state import (
        _TONE_AFFECT_AROUSAL_STEP as _TONE_AFFECT_AROUSAL_STEP,
    )
    from state import (
        _TONE_AFFECT_DIRECTIONS as _TONE_AFFECT_DIRECTIONS,
    )
    from state import (
        _TONE_AFFECT_VALENCE_STEP as _TONE_AFFECT_VALENCE_STEP,
    )
    from state import (
        _TONE_DIRECT_PROMPT as _TONE_DIRECT_PROMPT,
    )
    from state import (
        _TONE_EMOTION_ALIASES as _TONE_EMOTION_ALIASES,
    )
    from state import (
        _TONE_SCREEN_NUDGE_SEC as _TONE_SCREEN_NUDGE_SEC,
    )
    from state import (
        _TONE_WARM_LABELS as _TONE_WARM_LABELS,
    )
    from state import (
        _parse_iso_ts as _parse_iso_ts,
    )
    from stats import (  # type: ignore[no-redef]
        anniversary_due,
        backfill_day,
        badges_payload,
        heatmap_payload,
        mark_anniversary_pushed,
        month_view,
        record_made_up,
        record_milestone,
        record_mood_event,
        seal_due_months,
        summary_payload,
    )
    from stats import record_tone as stats_record_tone  # type: ignore[no-redef]
    from stats import record_turn as stats_record_turn  # type: ignore[no-redef]
    from tone_slot import (  # type: ignore[no-redef]
        _parse_tone_result,
        _post_chat_completion,
        _resolve_tone_slot,
        diagnose_slot_dormancy,
    )

JsonObject = dict[str, Any]


def _slot_dormancy_hint(core_cfg: JsonObject, slot: str) -> str:
    """槽位休眠原因 → 一句可操作的中文提示（日志与面板提示共用）。

    免费路由是宿主防滥用边界：lanlan.tech 端点服务端校验客户端身份，插件直连
    必被 400 拒绝（实测），故明确告知"配自己的 API 才可用"而不是含糊的"未配模型"。
    """
    reason = diagnose_slot_dormancy(core_cfg, slot)
    if reason == "free_route":
        return (
            "宿主正在使用免费路由（lanlan.tech），该端点只接受 N.E.K.O 客户端调用，"
            "插件无法直连——在宿主设置里配置自己的 API 服务商后本功能即可使用"
        )
    return "所选槽位在宿主未配置模型（或未保存服务商 URL），去宿主设置配置该槽位的模型"


def _journal_entries(journal: list[JsonObject]) -> list[JsonObject]:
    """个人日记页列表 → 段落条目平铺（回填相处统计时取时间戳用）。"""
    out: list[JsonObject] = []
    for page in journal:
        if not isinstance(page, dict):
            continue
        for item in page.get("entries") or []:
            if isinstance(item, dict):
                out.append(item)
    return out

# 宿主在 LLM 注入边界展开为当前会话的角色名；插件侧不得自行替换
MASTER_NAME_TOKEN = "{MASTER_NAME}"
LANLAN_NAME_TOKEN = "{LANLAN_NAME}"


def _parse_panel_bg(data_url: Any) -> tuple[str, int]:
    """面板背景图 data URL 校验（纯函数，不碰存储）。

    返回 (mime, 字符数)；非法时抛 ValueError，入口层翻译成 Err 给面板。
    """
    text = str(data_url or "").strip()
    if not text.startswith("data:"):
        raise ValueError("background must be a data: URL")
    if len(text) > _PANEL_BG_MAX_CHARS:
        raise ValueError("background image too large")
    header = text.split(",", 1)[0]
    mime = header[len("data:"):].split(";", 1)[0].strip().lower()
    if mime not in _PANEL_BG_MIMES:
        raise ValueError(f"unsupported image type: {mime or 'unknown'}")
    if "," not in text:
        raise ValueError("malformed data: URL")
    return mime, len(text)


def _clamp_panel_bg_dim(value: Any) -> float:
    """遮罩强度归一到 [0, 0.85]；坏值回退默认，不报错（装饰性参数宽容处理）"""
    try:
        return min(0.85, max(0.0, float(value)))
    except (TypeError, ValueError):
        return _PANEL_BG_DEFAULT_DIM

# Store 布局 / key 函数 / 常量表 / 纯工具函数 / _MoodState / _LanlanShard
# 已抽出到 state.py（碎片提取在 fragments.py、个人日记页逻辑在 journal.py），
# 见顶部导入块的再导出


@neko_plugin
class ForeverCompanionPlugin(NekoPluginBase):
    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self._tide_cfg: JsonObject = {}
        self._phases_cfg: JsonObject = {}
        self._forbidden_words: list[str] = []
        self._mood_cfg: JsonObject = {}
        self._fragments_cfg: JsonObject = {}
        self._journal_cfg: JsonObject = {}
        self._review_cfg: JsonObject = {}
        self._stats_cfg: JsonObject = {}
        self._emotion_sense_cfg: JsonObject = {}
        # 语气感知运行态缓存（_csrf_token / _last_tone_error_logged / _core_config_cache）
        # 已随 EmotionSenseService 持有（A5 第 2 批）；_csrf_token 经下方 property 代理
        # （tests 直读 p._csrf_token），另两者无外部引用点、不再代理
        # 全局设置覆盖层（Store key "settings"）：面板保存的全局字段优先于 toml 默认
        self._settings_override: JsonObject = {}
        # per-lanlan 状态分片：惰性从 Store 载入，见 _ensure_shard
        self._shards: dict[str, _LanlanShard] = {}
        self._lanlan_index: list[str] = []
        # 主动搭话暂停的引用计数水位（Store key "proactive_state"）：
        # prev = 暂停前总开关原值（None = 未在暂停中），paused_by = 有生效情绪的角色集
        self._proactive_state: JsonObject = {"prev": None, "paused_by": []}
        # 当前角色解析缓存（15s TTL）；_last_resolved_lanlan 供同步路径（属性代理）回落
        self._current_lanlan_cache: tuple[str, float] = ("", -1000.0)
        self._last_resolved_lanlan = ""
        # 宿主现存角色名单缓存（60s TTL）；None = 未知（孤儿判定一律按 False 处理）
        self._known_catgirls_cache: tuple[set[str] | None, float] = (None, -1000.0)
        # 宿主 API base 缓存：端口首次解析后运行期不变（独立/测试环境每次延迟 import
        # 都会白构造一次 ImportError）；None = 未解析，config_change 时清空重解析
        self._proactive_api_base_cache: str | None = None
        # 面板"语气分析模型槽位"下拉选项缓存（60s TTL，面板 5s 轮询不必每次拉宿主）；
        # None = 未拉取过；失败不缓存（与 _fetch_known_catgirls 同例）
        self._tone_slot_options_cache: tuple[list[JsonObject] | None, float] = (None, -1000.0)
        # 面板潮汐日历缓存：key = (角色, 当天日期, 周期参数指纹)；
        # 参数/锚点/快进/跨天/切角色都会改变 key，自然失效，无需显式清理
        self._calendar_cache: tuple[tuple, list[JsonObject] | None] = ((), None)
        # 节流哨兵用 -1000.0 而非 0.0：部分平台（如 Linux）time.monotonic() 以 0 为纪元，
        # 首条日志恰在 0.0 附近时"仅一次/每 5 分钟"门控会误判为已记录而吞掉日志。
        self._last_bus_error_logged = -1000.0
        self._last_bus_heartbeat_logged = -1000.0
        # 碎片捕获"槽位未解析休眠"warning 的节流水位（同哨兵纪律）
        self._last_fragment_dormant_logged = -1000.0
        # 我的成文"槽位未解析休眠"warning 的节流水位（同上）
        self._last_review_dormant_logged = -1000.0
        self._supervise_lock = threading.Lock()
        self._last_tool_health_ts = 0.0
        # 调试模式（[tide].debug_mode）：活动快照覆写与调试入口注册水位；
        # 关闭时不注册任何调试入口，面向用户的表面零痕迹
        self._activity_override: JsonObject | None = None
        self._debug_registered = False
        # 语气感知服务（emotion_sense.py，A5 服务化第 1 批）：主类能力全部经
        # 延迟解析回调注入（调用时现取）——此刻 self._emotion_sense_cfg 还是 {}，
        # 且 _refresh_config/测试会整体替换它，p._proactive_http 等也会被实例级
        # monkeypatch 替换，构造期快照全部会失效；logger 同因（测试桩在构造后
        # 才注入 p.logger，此刻取 self.logger 会 AttributeError）只能延迟解析
        self._emotion_sense = EmotionSenseService(
            http=lambda *a, **k: self._proactive_http(*a, **k),
            push=lambda **kw: self.push_message(**kw),
            cfg_getter=lambda: self._emotion_sense_cfg,
            mood_enabled=lambda shard=None: self._mood_enabled(shard),
            phase_state=lambda shard=None: self._current_phase_state(shard),
            save_mood=lambda lanlan, shard: self._save_shard_mood(lanlan, shard),
            feed_affect=lambda shard, label, conf, now=None, weight=1.0: self._feed_tone_affect(
                shard, label, conf, now=now, weight=weight
            ),
            core_config_loader=lambda: self._load_core_config(),
            # 以下四个经主类薄委托中转（tests 实例级 monkeypatch 的是主类方法）
            core_config_path=lambda: self._core_config_path(),
            resolve_slot=lambda *a, **k: self._resolve_tone_slot(*a, **k),
            post_chat=lambda *a, **k: self._post_chat_completion(*a, **k),
            parse_result=lambda *a, **k: self._parse_tone_result(*a, **k),
            # 服务内部跨方法调用回绕主类薄委托：未来对主类这几个方法做实例级
            # monkeypatch 后经 _maybe_tone_sense 间接触发也能命中 patch
            poll_recent=lambda *a, **k: self._poll_recent_turns(*a, **k),
            analyze_tone=lambda *a, **k: self._analyze_turn_tone(*a, **k),
            correction_check=lambda *a, **k: self._tone_correction_check(*a, **k),
            screen_check=lambda *a, **k: self._tone_screen_check(*a, **k),
            plugin_id=lambda: self.plugin_id,
            logger=lambda: self.logger,
        )

    # ==========================================
    # 分片基建：shard 存取 / 当前角色解析
    # ==========================================

    def _get_shard(self, lanlan: str) -> _LanlanShard:
        """同步取 shard：不存在则建空壳（loaded=False，待 _ensure_shard 从 Store 载入）。

        同步路径（属性代理、纯计算）只允许读；任何写入前必须先经过 _ensure_shard。
        """
        shard = self._shards.get(lanlan)
        if shard is None:
            shard = self._shards[lanlan] = _LanlanShard()
        return shard

    async def _ensure_shard(self, lanlan: str) -> _LanlanShard:
        """确保角色 shard 已从 Store 载入，并登记进 lanlan_index（面板只读角色列表数据源）。"""
        shard = self._get_shard(lanlan)
        if shard.loaded:
            return shard
        cycle_res = await self.store.get(_cycle_key(lanlan))
        if isinstance(cycle_res, Ok) and isinstance(cycle_res.value, dict):
            shard.cycle = dict(cycle_res.value)
        mood_res = await self.store.get(_mood_key(lanlan))
        if isinstance(mood_res, Ok):
            shard.mood = _MoodState.from_mapping(mood_res.value)
        diary_res = await self.store.get(_diary_key(lanlan))
        if isinstance(diary_res, Ok) and isinstance(diary_res.value, list):
            shard.diary = [dict(item) for item in diary_res.value if isinstance(item, dict)]
        # 个人日记（0.7.0）：journal@ 优先；缺失且存在旧版 weekly@ 时一次性迁移
        # （每条周记成为独立一页，legacy 标记），旧 key 原样保留作备份不再写入
        journal_res = await self.store.get(_journal_key(lanlan))
        if isinstance(journal_res, Ok) and isinstance(journal_res.value, list):
            shard.journal = [dict(item) for item in journal_res.value if isinstance(item, dict)]
        else:
            weekly_res = await self.store.get(_weekly_key(lanlan))
            if isinstance(weekly_res, Ok) and isinstance(weekly_res.value, list):
                legacy = [dict(item) for item in weekly_res.value if isinstance(item, dict)]
                shard.journal = migrate_weekly_to_pages(legacy)
                if shard.journal:
                    await self._save_shard_journal(lanlan, shard)
                    self.logger.info(
                        "weekly reviews migrated to journal pages for {} ({} pages)",
                        lanlan, len(shard.journal),
                    )
        # 我的日记（0.8.0）：已成文篇目 + 累计中的素材统计合并存一个 key
        #（成文时篇目追加与 stats 清零原子地一次写入；独立 stats key 仅作
        # 旧数据兼容读取，不再写入）
        review_res = await self.store.get(_review_key(lanlan))
        if isinstance(review_res, Ok) and isinstance(review_res.value, dict):
            raw_review = review_res.value
            shard.review = [dict(item) for item in raw_review.get("entries") or [] if isinstance(item, dict)]
            stats = raw_review.get("stats")
            shard.review_stats = dict(stats) if isinstance(stats, dict) else {}
        else:
            stats_res = await self.store.get(_review_stats_key(lanlan))
            if isinstance(stats_res, Ok) and isinstance(stats_res.value, dict):
                shard.review_stats = dict(stats_res.value)
        # 相处统计（1.1.0）：stats@<角色>；首载时从三本日记时间戳一次性回填
        # "那天有互动"的活跃标记（轮数无法回填，只点亮天数让热力图有起点）
        stats_store_res = await self.store.get(_stats_key(lanlan))
        if isinstance(stats_store_res, Ok) and isinstance(stats_store_res.value, dict):
            shard.stats = dict(stats_store_res.value)
        if not shard.stats.get("backfilled"):
            for source in (shard.diary, _journal_entries(shard.journal), [
                {"ts": item.get("ts"), "source": "review"}
                for item in shard.review
            ]):
                for item in source:
                    ts = _parse_iso_ts(item.get("ts") if isinstance(item, dict) else None)
                    if ts is not None:
                        shard.stats = backfill_day(
                            shard.stats,
                            ts.astimezone(self._stats_tz()).date().isoformat(),
                        )
            if str(shard.stats.get("first_seen") or ""):
                # first_seen 回填为最早互动痕迹（比"装版当天"更真实的相伴起点）
                earliest = min(
                    (
                        _parse_iso_ts(item.get("ts"))
                        for source in (shard.diary, _journal_entries(shard.journal), shard.review)
                        for item in source
                        if _parse_iso_ts(item.get("ts") if isinstance(item, dict) else None) is not None
                    ),
                    default=None,
                )
                if earliest is not None:
                    shard.stats["first_seen"] = earliest.isoformat(timespec="seconds")
            shard.stats["backfilled"] = True
            await self._save_shard_stats(lanlan, shard)
        shard.loaded = True
        if lanlan not in self._lanlan_index:
            self._lanlan_index.append(lanlan)
            await self._save_lanlan_index()
            self.logger.info("lanlan shard registered: {}", lanlan)
        return shard

    def _current_shard_name(self) -> str:
        """同步路径的角色名回落：最近一次解析结果 → default。"""
        return self._last_resolved_lanlan or "default"

    def _current_shard(self) -> _LanlanShard:
        return self._get_shard(self._current_shard_name())

    async def _resolve_current_lanlan(self) -> str:
        """解析宿主当前角色：HTTP current_catgirl（权威，15s 缓存）→ ctx._current_lanlan → "default"。

        ctx._current_lanlan 只是"最近触发角色"的粘滞缓存，不能当权威来源，
        仅作 HTTP 不可达时的兜底。角色名取档案名原文，不做 normalize。
        """
        name, ts = self._current_lanlan_cache
        if name and time.monotonic() - ts < _CURRENT_LANLAN_CACHE_TTL:
            return name
        resolved = ""
        payload = await self._proactive_http("GET", "/api/characters/current_catgirl")
        if isinstance(payload, dict):
            resolved = str(payload.get("current_catgirl") or "").strip()
        if not resolved:
            resolved = str(getattr(self.ctx, "_current_lanlan", "") or "").strip()
        if not resolved:
            resolved = "default"
        self._current_lanlan_cache = (resolved, time.monotonic())
        self._last_resolved_lanlan = resolved
        return resolved

    async def _fetch_known_catgirls(self) -> set[str] | None:
        """拉取宿主现存角色档案名单（GET /api/characters 响应里 ["猫娘"] dict 的 keys，档案名原文）。

        孤儿判定的唯一权威来源。带 Accept-Language: zh-CN 让宿主跳过 persona
        翻译开销（我们只取 key，不读人设正文）。成功结果缓存 60s；任何失败
        （不可达/结构异常）返回 None 表示"未知"且不缓存——调用方必须把未知
        按"非孤儿"处理，绝不可因宿主暂时不可达而误标/误删。
        """
        names, ts = self._known_catgirls_cache
        if names is not None and time.monotonic() - ts < _KNOWN_CATGIRLS_CACHE_TTL:
            return names
        payload = await self._proactive_http(
            "GET", "/api/characters", headers={"Accept-Language": "zh-CN"}
        )
        catgirls = payload.get("猫娘") if isinstance(payload, dict) else None
        if not isinstance(catgirls, dict):
            return None
        names = {str(k) for k in catgirls}
        self._known_catgirls_cache = (names, time.monotonic())
        return names

    async def _attribution_lanlan(self, kwargs: JsonObject) -> str:
        """工具/入口调用的归因角色：宿主传入的 ``_ctx.lanlan_name`` 优先。

        LLM 工具调用未证实一定携带 _ctx，故兜底为宿主当前角色。
        study_companion 同款归因模式。
        """
        ctx = kwargs.get("_ctx") if isinstance(kwargs, dict) else None
        name = ""
        if isinstance(ctx, dict):
            name = str(ctx.get("lanlan_name") or "").strip()
        elif ctx is not None:
            name = str(getattr(ctx, "lanlan_name", "") or "").strip()
        if name:
            return name
        return await self._resolve_current_lanlan()

    async def _current_shard_async(self) -> tuple[str, _LanlanShard]:
        """面板/用户入口的作用对象：始终跟随宿主当前角色（无手动选中态）。"""
        name = await self._resolve_current_lanlan()
        return name, await self._ensure_shard(name)

    # ---- 同步属性代理：指向"当前 shard"（最近解析 → default）----
    # 多角色路径一律显式传 shard；这些代理只服务无 lanlan 上下文的同步调用方与既有测试。

    @property
    def _mood_state(self) -> _MoodState:
        return self._current_shard().mood

    @_mood_state.setter
    def _mood_state(self, value: _MoodState) -> None:
        self._current_shard().mood = value

    @property
    def _diary(self) -> list[JsonObject]:
        return self._current_shard().diary

    @_diary.setter
    def _diary(self, value: list[JsonObject]) -> None:
        self._current_shard().diary = value

    @property
    def _last_injected_message_ts(self) -> float:
        return self._current_shard().last_injected_message_ts

    @_last_injected_message_ts.setter
    def _last_injected_message_ts(self, value: float) -> None:
        self._current_shard().last_injected_message_ts = value

    @property
    def _user_message_count_since_inject(self) -> int:
        return self._current_shard().user_message_count_since_inject

    @_user_message_count_since_inject.setter
    def _user_message_count_since_inject(self, value: int) -> None:
        self._current_shard().user_message_count_since_inject = value

    @property
    def _last_injected_whisper_key(self) -> str:
        return self._current_shard().last_injected_whisper_key

    @_last_injected_whisper_key.setter
    def _last_injected_whisper_key(self, value: str) -> None:
        self._current_shard().last_injected_whisper_key = value

    @property
    def _last_activity_context_key(self) -> str:
        return self._current_shard().last_activity_context_key

    @_last_activity_context_key.setter
    def _last_activity_context_key(self, value: str) -> None:
        self._current_shard().last_activity_context_key = value

    # ==========================================
    # 配置与状态
    # ==========================================

    async def _refresh_config(self) -> None:
        """加载全局配置：plugin.toml 默认值 + Store settings 覆盖层（权威）。

        这里只产全局配置（注入策略/提示词/时区等）；per-character 的开关/锚点/
        周期参数在 shard 上，读取时按"全局默认 ← shard.params 覆盖 ← shard.anchor_date"
        合成（见 _cycle_params）。Steam 环境下配置文件持久化常超时（4.5s 硬上限），
        因此用户在面板改过的设置以 PluginStore 为准，重启不丢。
        """
        raw = await self.config.dump(timeout=5.0)
        cfg = _cfg_section(raw)
        tide = _cfg_section(cfg.get("tide"))
        mood = _cfg_section(cfg.get("mood"))
        fragments = _cfg_section(cfg.get("fragments"))
        journal = _cfg_section(cfg.get("journal"))
        review = _cfg_section(cfg.get("review"))
        emotion_sense = _cfg_section(cfg.get("emotion_sense"))
        stats_cfg = _cfg_section(cfg.get("stats"))

        # Store 全局覆盖层：面板保存过的全局字段优先于 toml 默认
        tide.update(_cfg_section(self._settings_override.get("tide")))
        mood.update(_cfg_section(self._settings_override.get("mood")))
        fragments.update(_cfg_section(self._settings_override.get("fragments")))
        journal.update(_cfg_section(self._settings_override.get("journal")))
        review.update(_cfg_section(self._settings_override.get("review")))
        emotion_sense.update(_cfg_section(self._settings_override.get("emotion_sense")))
        stats_cfg.update(_cfg_section(self._settings_override.get("stats")))

        self._tide_cfg = tide
        phases = _cfg_section(tide.get("phases"))
        self._phases_cfg = {key: _cfg_section(val) for key, val in phases.items()}
        words = tide.get("forbidden_words")
        self._forbidden_words = [str(w) for w in words] if isinstance(words, list) else []
        self._mood_cfg = mood
        self._fragments_cfg = fragments
        self._journal_cfg = journal
        self._review_cfg = review
        self._emotion_sense_cfg = emotion_sense
        self._stats_cfg = stats_cfg

        # 锚点缺失（shard 与全局配置都没有）：随机化的默认锚点--反推一个日期
        # 使"今天"落在本轮平稳期的随机位置（见 cycle.randomized_default_anchor）。
        # 装完前几天必是平稳期、每次安装起点各不相同，且立即落盘固化
        # （重启不重新随机）；只写内存，随后 shard 落盘/shutdown 会带上
        #（不写配置文件，见上）
        if not str(tide.get("anchor_date") or "").strip():
            today = resolve_today(str(tide.get("timezone") or "auto"))
            for shard in self._shards.values():
                if shard.loaded and not str(shard.cycle.get("anchor_date") or "").strip():
                    params = self._effective_cycle_settings(shard)
                    anchor = randomized_default_anchor(
                        today=today,
                        cycle_length=int(params["cycle_length"]),
                        period_length=int(params["period_length"]),
                        ovulation_day=int(params["ovulation_day"]),
                        ovulation_window=int(params["ovulation_window"]),
                    )
                    shard.cycle["anchor_date"] = anchor.isoformat()
                    self.logger.info(
                        "randomized default anchor {} assigned (luteal-phase start)",
                        anchor.isoformat(),
                    )

    def _shard_params(self, shard: _LanlanShard) -> JsonObject:
        params = shard.cycle.get("params")
        return params if isinstance(params, dict) else {}

    def _auto_derive(self, shard: _LanlanShard | None = None) -> bool:
        """自动演算开关：开启时潮汐期长度/活跃日/活跃窗口由周期长度推导。"""
        params = self._shard_params(shard or self._current_shard())
        if "auto_derive" in params:
            return bool(params["auto_derive"])
        return bool((self._tide_cfg or {}).get("auto_derive", True))

    def _effective_cycle_settings(self, shard: _LanlanShard | None = None) -> JsonObject:
        """某角色生效的周期参数：shard.params 覆盖全局默认；自动演算开启时由周期长度推导。"""
        shard = shard or self._current_shard()
        params = self._shard_params(shard)
        tide = self._tide_cfg or {}
        cycle_length = int(params.get("cycle_length") or tide.get("cycle_length") or 28)
        if self._auto_derive(shard):
            return derive_cycle_params(cycle_length)
        return {
            "cycle_length": cycle_length,
            "period_length": int(params.get("period_length") or tide.get("period_length") or 5),
            "ovulation_day": int(params.get("ovulation_day") or tide.get("ovulation_day") or 14),
            "ovulation_window": int(params.get("ovulation_window") or tide.get("ovulation_window") or 3),
        }

    def _cycle_params(self, shard: _LanlanShard | None = None) -> JsonObject:
        """合成某角色的完整周期参数：全局默认 ← shard.params 覆盖 ← shard.anchor_date。"""
        shard = shard or self._current_shard()
        anchor_raw = str(shard.cycle.get("anchor_date") or "").strip()
        if not anchor_raw:
            anchor_raw = str(self._tide_cfg.get("anchor_date") or "").strip()
        if not anchor_raw:
            # shard 与全局都缺锚点：随机化兜底（正常路径下 _refresh_config 已落
            # 随机默认值；这里只是异常路径的兜底，同样取平稳期随机位置）
            today = resolve_today(str(self._tide_cfg.get("timezone") or "auto"))
            params = self._effective_cycle_settings(shard)
            anchor_raw = randomized_default_anchor(
                today=today,
                cycle_length=int(params["cycle_length"]),
                period_length=int(params["period_length"]),
                ovulation_day=int(params["ovulation_day"]),
                ovulation_window=int(params["ovulation_window"]),
            ).isoformat()
        return {
            "anchor": parse_anchor_date(anchor_raw),
            **self._effective_cycle_settings(shard),
            "advance_days": max(0, int(shard.cycle.get("advance_days") or 0)),
        }

    def _enabled(self, shard: _LanlanShard | None = None) -> bool:
        shard = shard or self._current_shard()
        enabled = shard.cycle.get("enabled")
        if enabled is None:
            # 与 plugin.toml [tide] enabled = false 一致：配置缺失时保持关闭（fail-closed）。
            # 新角色 shard 没有任何覆写时同样回落到这里——默认不对未设置的角色开启模拟
            enabled = bool((self._tide_cfg or {}).get("enabled", False))
        return bool(enabled)

    def _current_phase_state(self, shard: _LanlanShard | None = None):
        params = self._cycle_params(shard)
        today = resolve_today(str(self._tide_cfg.get("timezone") or "auto"))
        return compute_phase_state(today=today, **params)

    async def _load_state(self) -> None:
        settings_res = await self.store.get(_STORE_SETTINGS)
        if isinstance(settings_res, Ok) and isinstance(settings_res.value, dict):
            self._settings_override = dict(settings_res.value)
        index_res = await self.store.get(_STORE_LANLAN_INDEX)
        if isinstance(index_res, Ok) and isinstance(index_res.value, list):
            self._lanlan_index = [str(n) for n in index_res.value if str(n)]
        proactive_res = await self.store.get(_STORE_PROACTIVE)
        if isinstance(proactive_res, Ok) and isinstance(proactive_res.value, dict):
            raw = proactive_res.value
            prev = raw.get("prev")
            self._proactive_state = {
                "prev": dict(prev) if isinstance(prev, dict) else None,
                "paused_by": [str(n) for n in raw.get("paused_by") or [] if str(n)],
            }
        await self._migrate_legacy_state_if_needed()
        # 载入所有已知角色的 shard：主动搭话引用计数要看全量生效情绪，
        # 只载当前角色会把"别的角色还在冷战"漏算
        for lanlan in list(self._lanlan_index):
            await self._ensure_shard(lanlan)
        current = await self._resolve_current_lanlan()
        await self._ensure_shard(current)

    async def _migrate_legacy_state_if_needed(self) -> None:
        """0.4.0 单角色数据 → 0.5.0 分片：归属"当前角色"，一次性、幂等。

        判定：Store 里没有 lanlan_index 且存在旧 cycle_state。
        cycle_state.settings 抽进全局 settings；旧 mood_state.proactive_prev
        （暂停水位）搬进 proactive_state——升级瞬间若正处于暂停中，水位不跟着走
        会导致主动搭话永远卡死。旧 key 全部保留作备份，不再写入。
        """
        index_res = await self.store.get(_STORE_LANLAN_INDEX)
        if isinstance(index_res, Ok) and index_res.value is not None:
            return  # 已迁移过（或全新安装已写过索引）：幂等跳过
        legacy_res = await self.store.get(_STORE_CYCLE)
        legacy = legacy_res.value if isinstance(legacy_res, Ok) else None
        if not isinstance(legacy, dict):
            return  # 无旧数据：全新安装，索引随首个 shard 创建落盘
        lanlan = await self._resolve_current_lanlan()
        shard = self._get_shard(lanlan)
        params = legacy.get("params")
        shard.cycle = {
            "enabled": legacy.get("enabled"),
            "anchor_date": legacy.get("anchor_date"),
            "advance_days": legacy.get("advance_days") or 0,
            "phase_seen": legacy.get("phase_seen") or "",
            "params": dict(params) if isinstance(params, dict) else {},
        }
        mood_res = await self.store.get(_STORE_MOOD)
        if isinstance(mood_res, Ok) and isinstance(mood_res.value, dict):
            raw_mood = mood_res.value
            shard.mood = _MoodState.from_mapping(raw_mood)
            prev = raw_mood.get("proactive_prev")
            if isinstance(prev, dict):
                self._proactive_state["prev"] = dict(prev)
                if shard.mood.is_active():
                    self._proactive_state["paused_by"] = [lanlan]
        diary_res = await self.store.get(_STORE_DIARY)
        if isinstance(diary_res, Ok) and isinstance(diary_res.value, list):
            shard.diary = [dict(item) for item in diary_res.value if isinstance(item, dict)]
        shard.loaded = True
        settings = legacy.get("settings")
        if isinstance(settings, dict):
            self._settings_override = dict(settings)
            await self._save_settings()
        self._lanlan_index = [lanlan]
        await self._save_lanlan_index()
        await self._save_shard_cycle(lanlan, shard)
        await self._save_shard_mood(lanlan, shard)
        await self._save_shard_diary(lanlan, shard)
        await self._save_proactive_state()
        self.logger.info("legacy single-character state migrated to shard {}", lanlan)

    async def _save_shard_cycle(self, lanlan: str, shard: _LanlanShard) -> Result[None]:
        res = await self.store.set(_cycle_key(lanlan), dict(shard.cycle))
        if isinstance(res, Err):
            self.logger.warning("persist cycle failed for {}: {}", lanlan, res.error)
        return res

    async def _save_shard_mood(self, lanlan: str, shard: _LanlanShard) -> None:
        res = await self.store.set(_mood_key(lanlan), shard.mood.to_mapping())
        if isinstance(res, Err):
            self.logger.warning("persist mood failed for {}: {}", lanlan, res.error)

    async def _save_shard_diary(self, lanlan: str, shard: _LanlanShard) -> None:
        # 内存与落盘保持同一截断语义：都只保留最近 _DIARY_MAX_ENTRIES 条，
        # 避免本次会话 total 与重启后 total 不一致
        shard.diary = list(shard.diary[-_DIARY_MAX_ENTRIES:])
        res = await self.store.set(_diary_key(lanlan), list(shard.diary))
        if isinstance(res, Err):
            self.logger.warning("persist diary failed for {}: {}", lanlan, res.error)

    async def _save_diary(self) -> None:
        """兼容包装：保存"当前"shard 的手记（无 lanlan 上下文的旧调用点/测试用）。"""
        name = self._current_shard_name()
        await self._save_shard_diary(name, self._get_shard(name))

    async def _save_shard_journal(self, lanlan: str, shard: _LanlanShard) -> None:
        # 与手记同一截断语义：内存与落盘都只保留最近 _JOURNAL_MAX_PAGES 页
        shard.journal = list(shard.journal[-_JOURNAL_MAX_PAGES:])
        res = await self.store.set(_journal_key(lanlan), list(shard.journal))
        if isinstance(res, Err):
            self.logger.warning("persist journal failed for {}: {}", lanlan, res.error)

    async def _save_shard_review(self, lanlan: str, shard: _LanlanShard) -> None:
        """我的日记落盘：成文篇目与素材统计合并写进一个 key（stats 随篇目一起走，
        成文时原子清零——两个独立 key 反而会在中途崩溃时出现篇目已加而 stats
        未清的错位；加载侧对旧独立 stats key 只读迁移）。"""
        res = await self.store.set(
            _review_key(lanlan), {"entries": list(shard.review), "stats": dict(shard.review_stats)}
        )
        if isinstance(res, Err):
            self.logger.warning("persist review failed for {}: {}", lanlan, res.error)

    async def _save_shard_stats(self, lanlan: str, shard: _LanlanShard) -> None:
        """相处统计落盘（stats@<角色>；只增不清零，纯本地）。"""
        res = await self.store.set(_stats_key(lanlan), dict(shard.stats))
        if isinstance(res, Err):
            self.logger.warning("persist stats failed for {}: {}", lanlan, res.error)

    # ==========================================
    # 相处统计（1.1.0，stats.py）：按天聚合的长期累计——徽章墙/热力图/月报的
    # 唯一数据源。纯本地统计：零模型开销、不设开关、成文永不清零；只为用户
    # 可视化服务，除纪念日注入（[stats].anniversary_inject，默认开）外绝不
    # 进入她的上下文。埋点与我的日记素材共用驱动点但口径独立（不受
    # [review].enabled 影响、不清零）。
    # ==========================================

    def _stats_tz(self):
        """统计日期折算用的时区（与潮汐日历同源：[tide].timezone）。"""
        from zoneinfo import ZoneInfo

        name = str((self._tide_cfg or {}).get("timezone") or "auto").strip()
        if not name or name == "auto":
            return None  # None = 系统本地
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - 坏配置回落本地时区，统计不能炸
            return None

    def _stats_today(self, ts: float | None = None) -> str:
        """把时间戳折算成统计用的本地日期字符串（YYYY-MM-DD）。

        走 time.localtime（读模块对象的属性，测试猴补丁 tm.time.time 同生效），
        不用 datetime.fromtimestamp——Windows 上对极端/负值时间戳（测试把时钟
        拨回 1970）会直接抛 OSError；localtime 对不可表示的值回落真实当前时间。
        配置了显式时区时再做一次 astimezone 折算。
        """
        from datetime import datetime

        moment = datetime.fromtimestamp(time.mktime(time.localtime(ts if ts is not None else time.time())))
        tz = self._stats_tz()
        if tz is not None:
            try:
                moment = moment.astimezone(tz)
            except (OSError, OverflowError, ValueError):
                pass  # 极端时间戳（测试拨钟/时钟错乱）折算失败即按本地日期计
        return moment.date().isoformat()

    def _feed_stats_turn(self, shard: _LanlanShard, ts: float | None = None) -> None:
        """记一轮互动进相处统计（每条新用户消息一次，纯内存，落盘由调用方决定）。"""
        valence = self._current_affect(shard)[0] if shard.mood.affect_updated_at else None
        shard.stats = stats_record_turn(shard.stats, self._stats_today(ts), valence=valence)

    def _feed_stats_tone(self, shard: _LanlanShard, label: str) -> None:
        """记一次她的语气分析结果（weight=1.0 主路径；落盘随 mood 保存搭车）。"""
        shard.stats = stats_record_tone(shard.stats, self._stats_today(), label)

    def _feed_stats_mood_event(self, shard: _LanlanShard, action: str, *, origin: str) -> None:
        """记一次情绪动作事件（origin=user 的演示不计，与我的日记同口径）。"""
        shard.stats = record_mood_event(shard.stats, self._stats_today(), action, origin=origin)

    def _feed_stats_made_up(self, shard: _LanlanShard) -> None:
        """记一次和好：她在负面情绪生效中主动调心情转晴（tool_feeling_better 判定）。"""
        shard.stats = record_made_up(shard.stats, self._stats_today())

    async def _maybe_anniversary_push(self, lanlan: str, shard: _LanlanShard) -> bool:
        """纪念日注入：今天恰好是相伴第 30/60/…/365/… 天时，递一条 read 轻语。

        与阶段开场白同构：只递一句"你们今天相伴 N 天了"，说不说、怎么说由她
        自己决定。[stats].anniversary_inject 可关（默认开）；当天去重（盖水位
        在推送之后，推送失败下趟重试）。
        """
        cfg_ann = (self._stats_cfg or {}).get("anniversary_inject")
        if cfg_ann is False:  # 显式 false 才关（缺省/true 都开，宽容旧数据）
            return False
        today = self._stats_today()
        due, total = anniversary_due(shard.stats, today)
        if not due:
            return False
        self.push_message(
            visibility=[],
            ai_behavior="read",
            parts=[{"type": "text", "text": (
                f"（日期感知）今天是你和主人相伴的第 {total} 天。"
                "你或许想自然地提起这个日子，也或许只是心里悄悄知道——由你自己决定，"
                "绝不要提及这条提醒本身。"
            )}],
            source=self.plugin_id,
            target_lanlan=lanlan,
            coalesce_key=f"{self.plugin_id}.anniversary",
            metadata={"message_type": f"{self.plugin_id}.anniversary", "days": total},
        )
        shard.stats = mark_anniversary_pushed(shard.stats, today)
        await self._save_shard_stats(lanlan, shard)
        self.logger.info("anniversary pushed for {} ({} days)", lanlan, total)
        return True

    async def _seal_stats_months(self, lanlan: str, shard: _LanlanShard) -> list[str]:
        """月报封卷：跨月时把上个月快照进 months（幂等，tick 驱动）。"""
        sealed: list[str] = []
        fresh, sealed = seal_due_months(shard.stats, self._stats_today(), diary=shard.diary)
        if sealed:
            shard.stats = fresh
            await self._save_shard_stats(lanlan, shard)
            self.logger.info("stats months sealed for {}: {}", lanlan, sealed)
        return sealed

    async def _save_settings(self) -> None:
        res = await self.store.set(_STORE_SETTINGS, dict(self._settings_override))
        if isinstance(res, Err):
            self.logger.warning("persist settings failed: {}", res.error)

    async def _save_lanlan_index(self) -> None:
        res = await self.store.set(_STORE_LANLAN_INDEX, list(self._lanlan_index))
        if isinstance(res, Err):
            self.logger.warning("persist lanlan_index failed: {}", res.error)

    async def _save_proactive_state(self) -> None:
        res = await self.store.set(_STORE_PROACTIVE, dict(self._proactive_state))
        if isinstance(res, Err):
            self.logger.warning("persist proactive_state failed: {}", res.error)

    # ==========================================
    # 生命周期
    # ==========================================

    @lifecycle(id="startup")
    async def startup(self, **_: Any):
        await self._load_state()   # Store 先载入：覆盖层要参与配置解析
        await self._refresh_config()
        # 到期情绪清理（所有已载入 shard；重启后状态自愈交给监督循环统一处理）
        for lanlan, shard in list(self._shards.items()):
            if shard.loaded and self._expire_timed_action_if_due(shard):
                await self._save_shard_mood(lanlan, shard)
        current = self._current_shard_name()
        shard = self._get_shard(current)
        # 首次启动（store 里没有水位）时不触发开场白：刚启动就主动搭话
        # 会显得突兀，且用户手动启停插件会造成重复打扰
        if not shard.cycle.get("phase_seen"):
            try:
                shard.cycle["phase_seen"] = self._current_phase_state(shard).phase
            except TideConfigError:
                pass
        try:
            phase = self._current_phase_state(shard)
        except TideConfigError as exc:
            # 配置非法（如 Store 覆盖层存了坏参数）：明确报错，
            # 默认 startup_failure="warn" 下进程保活并标记降级，
            # 用户可在面板修正后由 config_change 恢复
            self.logger.warning("startup with invalid tide config: {}", exc)
            return Err(SdkError(f"invalid tide config: {exc}"))
        self.logger.info(
            "startup ok: lanlan={} enabled={} phase={} day={} advance_days={}",
            current, self._enabled(shard), phase.phase, phase.cycle_day,
            shard.cycle.get("advance_days", 0),
        )
        self._sync_debug_entries()
        return Ok(build_status_payload(phase, enabled=self._enabled(shard)))

    @lifecycle(id="shutdown")
    async def shutdown(self, **_: Any):
        for lanlan, shard in list(self._shards.items()):
            if not shard.loaded:
                continue
            await self._save_shard_cycle(lanlan, shard)
            await self._save_shard_mood(lanlan, shard)
            await self._save_shard_diary(lanlan, shard)
            await self._save_shard_journal(lanlan, shard)
        await self._save_settings()
        await self._save_proactive_state()
        return Ok({"status": "shutdown"})

    @lifecycle(id="config_change")
    async def on_config_change(self, **_: Any):
        await self._refresh_config()
        # 按旧配置/旧端口解析出的缓存作废：宿主 API base、语气槽位下拉选项
        # （日历缓存 key 含参数指纹与当天日期，自然失效，无需清理）
        self._proactive_api_base_cache = None
        self._tone_slot_options_cache = (None, -1000.0)
        self._sync_debug_entries()
        # 锚点/周期参数变了，重新校验一次并报告（针对当前角色 shard）
        try:
            phase = self._current_phase_state()
        except TideConfigError as exc:
            return Err(SdkError(f"invalid tide config: {exc}"))
        return Ok(build_status_payload(phase, enabled=self._enabled()))

    # ==========================================
    # 身体状态注入（核心循环）
    # ==========================================

    @staticmethod
    def _unwrap_bus_record(record: object) -> object:
        """取回 bus 记录的原始 payload dict。

        SDK 包装层契约不一致：宿主 MemoryList.dump_records() 给的是 MemoryRecord
        对象序列而非 dict，SdkBusMemoryRecord.from_raw 对非 Mapping 会包成
        {"value": <record>}，把 type 字段吞掉（运行时症状：心跳 latest_type=?，
        用户消息永远被过滤掉）。这里解开一层；各层形态（宿主 MemoryRecord.raw /
        SDK .payload / 裸 dict）都兼容。
        """
        raw = getattr(record, "payload", None) or getattr(record, "raw", record)
        if isinstance(raw, dict) and set(raw) == {"value"}:
            inner = raw.get("value")
            raw = getattr(inner, "raw", None) or getattr(inner, "payload", None) or inner
        return raw

    async def _poll_latest_user_message(self) -> tuple[float, str, bool, str] | None:
        """读取总线上最新的用户消息，返回 (时间戳, 内容预览, 是否语音, 归属角色)。

        正确 API 是 SDK v2 的 ctx.bus.memory.get(bucket_id=..., limit=..., timeout=...)：
        返回值可能是 awaitable 或 SdkBusList，记录经 _unwrap_bus_record 解包成原始
        dict（真实运行时任一包装形态都兼容：SDK 可能把宿主 MemoryRecord 对象再包成
        payload={"value": ...}，不解包会把 type 吞掉、用户消息永远被过滤）。
        取最近 10 条倒序找最新 user_message：bucket 可能混入其他类型记录，
        只盲取最后一条会让用户消息被永久遮蔽。归属角色取 payload 的 lanlan
        字段（宿主双 bucket 写入时带档案名原文）；缺失时回落"当前角色"。
        """
        bus = getattr(self.ctx, "bus", None)
        memory = getattr(bus, "memory", None) if bus is not None else None
        mem_get = getattr(memory, "get", None) if memory is not None else None
        if not callable(mem_get):
            if self._last_bus_error_logged < 0:
                self._last_bus_error_logged = time.monotonic()
                self.logger.warning("ctx.bus.memory.get unavailable on ctx; message polling disabled")
            return None
        try:
            # to_thread 挪到工作线程：timer handler scope 里同步调 bus.memory.get
            # 会触发宿主 "Sync call invoked inside handler" 告警，且 ZMQ IPC 下
            # 最多阻塞事件循环 1s；返回 awaitable 时兜底 await
            # （有事件循环的宿主环境 get 返回协程，测试桩同步/异步两种都有）
            result = await asyncio.to_thread(mem_get, bucket_id="default", limit=10, timeout=1.0)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 - 总线不可用不应拖垮 timer
            now_mono = time.monotonic()
            if now_mono - self._last_bus_error_logged > 300:
                self._last_bus_error_logged = now_mono
                # 必须 warning 而非 debug：总线彻底断开时这是唯一线索，
                # debug 级别不进日志文件会造成"注入失效但零日志"的盲区
                self.logger.warning("bus memory read failed (throttled 5min): {}", exc)
            return None
        if result is None or getattr(result, "error", None) is not None:
            now_mono = time.monotonic()
            if now_mono - self._last_bus_error_logged > 300:
                self._last_bus_error_logged = now_mono
                self.logger.warning("bus memory read returned error (throttled 5min): {}", getattr(result, "error", None))
            return None
        try:
            seq = list(result)
        except TypeError:
            seq = []
        for record in reversed(seq):
            raw = self._unwrap_bus_record(record)
            if not isinstance(raw, dict) or str(raw.get("type") or "") != "user_message":
                continue
            try:
                ts = float(raw.get("_ts") or getattr(record, "timestamp", None) or 0.0)
            except (TypeError, ValueError):
                continue
            content = str(raw.get("content") or "")
            # 宿主同时写入了 lanlan / is_voice 字段（语音转写与文字输入都会发布）；
            # lanlan 是注入定向与 shard 归属的依据，缺失时回落当前角色
            is_voice = bool(raw.get("is_voice"))
            lanlan = str(raw.get("lanlan") or "").strip() or await self._resolve_current_lanlan()
            return (ts, content, is_voice, lanlan)
        # 心跳留痕：区分"消息没进总线"（桶空）与"被其他类型记录遮蔽"；
        # 5 分钟节流，仅在总开关开启时才会走到这里（tick 有 enabled 门控）
        now_mono = time.monotonic()
        if now_mono - self._last_bus_heartbeat_logged > 300:
            self._last_bus_heartbeat_logged = now_mono
            if not seq:
                self.logger.info("bus heartbeat: bucket=default empty (no user message within TTL)")
            else:
                last_raw = self._unwrap_bus_record(seq[-1])
                latest_type = str(last_raw.get("type") or "?") if isinstance(last_raw, dict) else "?"
                self.logger.info(
                    "bus heartbeat: no user_message in last {} records; latest_type={}",
                    len(seq), latest_type,
                )
        return None

    def _should_inject(self, shard: _LanlanShard, message_text: str) -> bool:
        mode = str(self._tide_cfg.get("inject_mode") or "every_user_message")
        if mode == "off":
            return False
        if mode == "on_trigger":
            keywords = self._tide_cfg.get("trigger_keywords")
            words = [str(k).lower() for k in keywords] if isinstance(keywords, list) else []
            text = message_text.lower()
            return any(word and word in text for word in words)
        if mode == "interval_n":
            n = max(1, int(self._tide_cfg.get("inject_interval_n") or 3))
            shard.user_message_count_since_inject += 1
            return shard.user_message_count_since_inject >= n
        return True

    async def _prime_inject_on_enable(
        self, was_enabled: bool, lanlan: str | None = None, shard: _LanlanShard | None = None
    ) -> None:
        """开启某角色总开关的瞬间先注入一次当前身体状态。

        不这样的话用户要等满 interval_n 条消息（默认 3）才能看到效果，
        容易误以为插件没生效（语音会话中 read 送达仍受平台时序约束，
        建议用文字对话验证）。配置无效时 _inject_now 静默返回空列表。
        """
        shard = shard or self._current_shard()
        if not was_enabled and self._enabled(shard):
            shard.last_injected_whisper_key = ""
            await self._inject_now(lanlan, shard)

    async def _handle_new_user_message(self, ts: float, text: str, lanlan: str | None = None) -> bool:
        """统一的新用户消息处理入口（轮询路径与未来其他驱动源共用），按归属角色 shard 驱动。

        水位/interval 计数/变化门控都是 per-shard 的：多角色并行会话互不影响。
        interval_n 计数只在真正注入成功后清零：变化门控拦截时不消耗
        计数，保证实际注入频率不低于配置。
        """
        name = str(lanlan or "").strip() or self._current_shard_name()
        shard = await self._ensure_shard(name)
        if ts <= shard.last_injected_message_ts:
            return False
        shard.last_injected_message_ts = ts
        # 我的日记素材：每条新用户消息计一轮（含心情采样）；统计量小、
        # 与注入无关，放在水位推进之后必经路径上。落盘随下一趟 mood/diary
        # 保存搭车太脆——这里直接存（store.set 是本地 IPC，开销可忽略）
        self._feed_review_turn(name, shard)
        if shard.review_stats.get("turns"):
            await self._save_shard_review(name, shard)
        # 相处统计（1.1.0）：同一驱动点、独立口径（不清零、不受 [review] 闸控制），
        # 与我的日记落盘合并为一次 store.set 之后，避免两趟 IPC
        self._feed_stats_turn(shard, ts)
        await self._save_shard_stats(name, shard)
        # 和好提醒与注入频控解耦：每条新消息都要检查（冷战中注入被静音，
        # 提醒却是唯一能把"该调 mood_rising_tide 了"送到她面前的通道）
        await self._maybe_nudge_reconcile(text, name)
        # 静默类情绪动作期间不注入身体轻语（监督循环仍在跑暂停/加固）
        if self._is_silent_mood_active(shard):
            return False
        if not self._should_inject(shard, text):
            # 可观测性：频控拦截必须留痕，否则"注入失效"无从排查（用户消息节奏低，日志量可控）
            self.logger.info(
                "inject skipped by frequency strategy: lanlan={} mode={} counter={}",
                name,
                str(self._tide_cfg.get("inject_mode") or "every_user_message"),
                shard.user_message_count_since_inject,
            )
            return False
        parts = await self._inject_now(name, shard)
        if not parts:
            self.logger.info("inject skipped: whisper content unchanged since last injection")
            return False
        shard.user_message_count_since_inject = 0
        return True

    # 和好信号关键词：冷战/小情绪中用户消息命中任一关键词时提醒她该调工具了。
    # 只取高置信度的道歉/安抚词，避免日常聊天误触发。
    _RECONCILE_HINT_KEYWORDS = (
        "对不起", "抱歉", "原谅", "别生气", "不要生气", "别不理",
        "我错了", "和好", "理理我", "不要不理", "错了嘛",
    )

    async def _maybe_nudge_reconcile(self, text: str, lanlan: str | None = None) -> None:
        """沉默/小情绪期间，用户像在道歉/哄她时，推一条 read 提醒（定向到该角色）。

        背景：模型常常"演"出和好却忘了调 mood_rising_tide 切状态，
        导致面板情绪卡在冷战不动。提醒只递一句，是否和好仍由她自己决定；
        5 分钟节流（per-shard），新情绪回合开始时重置（见 _apply_mood_action）。
        名单含心有涟漪："能哄好"正是这个中间态的存在意义。
        """
        name = str(lanlan or "").strip() or self._current_shard_name()
        shard = self._get_shard(name)
        if not self._mood_enabled(shard) or not shard.mood.is_active():
            return
        if shard.mood.action not in ("ebb_tide", "sea_fog", "shallow_reef", "ripple"):
            return
        lowered = str(text or "").lower()
        if not any(word in lowered for word in self._RECONCILE_HINT_KEYWORDS):
            return
        now = time.time()
        if now - shard.last_reconcile_nudge_ts < 300:
            return
        shard.last_reconcile_nudge_ts = now
        self.push_message(
            visibility=[],
            ai_behavior="read",
            parts=[{"type": "text", "text": (
                "（内心状态提醒）对方似乎在道歉或哄你。如果你心里已经软下来想和好，"
                "必须先调用 mood_rising_tide 工具把情绪切换为心情转晴，再用恢复后的语气说话——"
                "不要只在嘴上和好，状态不切换的话系统会一直按当前情绪约束你。"
                "如果你还想再气一会儿，也可以继续不理，由你自己决定。"
            )}],
            source=self.plugin_id,
            target_lanlan=name,
            coalesce_key=f"{self.plugin_id}.reconcile_nudge",
            metadata={"message_type": f"{self.plugin_id}.reconcile_nudge", "during_action": shard.mood.action},
        )
        self.logger.info("reconcile nudge pushed during {} for {}", shard.mood.action, name)

    def _whisper_state_key(self, state, shard: _LanlanShard | None = None) -> str:
        """当前注入内容的变化指纹：阶段 + 时段 + 心情动作 + 活动感知上下文。

        read 推送会随用户消息永久写入对话历史并进入记忆抽取管线，
        内容没变就不该重复注入（低侵入：少说、说了才算数）。
        """
        shard = shard or self._current_shard()
        bucket = _time_bucket(str(self._tide_cfg.get("timezone") or "auto"))
        mood = shard.mood.action if self._mood_enabled(shard) and shard.mood.is_active() else ""
        return f"{state.phase}:{bucket}:{mood}:{shard.last_activity_context_key}"

    async def _build_activity_context_line(self, state, shard: _LanlanShard | None = None) -> str:
        """活动感知：把"用户在不在、在忙什么"纳入身体轻语（性价比最高的宿主结合点）。

        数据源是 SDK 的 get_os_activity_snapshot（前台类别/系统空闲时长/隐私态，
        study_companion 同款）。隐私态 private/unavailable 时绝不描述用户行为；
        结果缓存为指纹（per-shard）参与变化门控，上下文不变不重复注入。
        """
        shard = shard or self._current_shard()
        if not bool(self._tide_cfg.get("activity_context", True)):
            shard.last_activity_context_key = ""
            return ""
        override = self._activity_override
        if isinstance(override, dict):
            # 调试模式覆写：不访问真实系统信号，直接按设定值构造上下文，
            # 便于不开机不动地验证全部分支（详见 debug_force_activity）
            privacy = str(override.get("privacy") or "visible")
            raw_idle = override.get("idle")
            try:
                idle = float(raw_idle) if raw_idle is not None else None
            except (TypeError, ValueError):
                idle = None
            category = str(override.get("category") or "").strip().lower()
        else:
            try:
                from plugin.sdk.plugin import get_os_activity_snapshot

                snap = await get_os_activity_snapshot(self.plugin_id)
            except Exception as exc:  # noqa: BLE001 - 活动感知失败不影响基础注入
                self.logger.debug("activity snapshot failed: {}", exc)
                return ""
            privacy = str(getattr(snap, "privacy_state", "unavailable") or "unavailable")
            idle = getattr(snap, "system_idle_seconds", None)
            category = str(getattr(snap, "foreground_category", "") or "").strip().lower()
        if privacy != "visible":
            shard.last_activity_context_key = ""
            return ""
        key = ""
        line = ""
        if idle is not None and idle >= 1800:
            key = "idle"
            if state.phase == "menstrual":
                line = (
                    "[生活感知] {MASTER_NAME}已经有一阵子没在电脑前了。你本来就倦，"
                    "索性让自己也松下来、养养神；他回来时不用假装一直精神十足。"
                )
            elif state.phase == "ovulatory":
                line = (
                    "[生活感知] {MASTER_NAME}已经有一阵子没在电脑前了。"
                    "你有点想他，但先自己找点轻松的事做，别干等。"
                )
            else:
                line = (
                    "[生活感知] {MASTER_NAME}已经有一阵子没在电脑前了。"
                    "你也顺势放松一下，他回来再自然地接上话。"
                )
        elif category == "work":
            key = "focus:work"
            line = (
                "[生活感知] {MASTER_NAME}现在正在专注做事。你陪着但别黏人："
                "回应简短体贴，不主动拉他聊天，他告一段落你自然能感觉到。"
            )
        elif category == "gaming" and state.phase == "ovulatory":
            key = "gaming"
            line = (
                "[生活感知] {MASTER_NAME}在玩游戏。你这几天本来就黏人，"
                "可以饶有兴致地围观两句，但别打断他的节奏。"
            )
        shard.last_activity_context_key = key
        return line

    async def _build_whisper_parts(self, shard: _LanlanShard, state=None) -> list[dict[str, str]] | None:
        if state is None:
            # 独立调用时自算阶段状态；_inject_now 会传入已算好的 state，
            # 一次注入流程只推算一次（compute_phase_state 不便宜）
            try:
                state = self._current_phase_state(shard)
            except TideConfigError as exc:
                self.logger.warning("skip inject, bad config: {}", exc)
                return None
        whisper = build_body_whisper(
            self._phases_cfg,
            state,
            timezone_name=str(self._tide_cfg.get("timezone") or "auto"),
            forbidden_words=self._forbidden_words,
        )
        if not whisper:
            return None
        parts = [{"type": "text", "text": whisper}]
        activity_line = await self._build_activity_context_line(state, shard)
        if activity_line:
            parts.append({"type": "text", "text": activity_line})
        mood_line = self._build_mood_context_line(shard)
        if mood_line:
            parts.append({"type": "text", "text": mood_line})
        return parts

    async def _inject_now(
        self, lanlan: str | None = None, shard: _LanlanShard | None = None
    ) -> list[dict[str, str]]:
        """执行注入（定向到归属角色）；返回实际推送的 parts（空列表 = 未注入）。"""
        name = str(lanlan or "").strip() or self._current_shard_name()
        shard = shard or self._get_shard(name)
        try:
            state = self._current_phase_state(shard)
        except TideConfigError:
            return []
        key = self._whisper_state_key(state, shard)
        if key == shard.last_injected_whisper_key:
            # 身体状态、心情与活动上下文都没变：不重复注入，避免污染历史与记忆抽取
            return []
        parts = await self._build_whisper_parts(shard, state)  # 复用上面已算好的阶段状态
        if not parts:
            return []
        shard.last_injected_whisper_key = key
        self.push_message(
            visibility=[],
            ai_behavior="read",
            parts=parts,
            source=self.plugin_id,
            target_lanlan=name,
            coalesce_key=f"{self.plugin_id}.body_whisper",
            metadata={
                "message_type": f"{self.plugin_id}.body_whisper",
                "delivery_semantics": "passive",
                "phase": state.phase,
                "lanlan": name,
            },
        )
        # 可观测性：read 注入对用户隐形，日志是现场验证注入是否发生的唯一途径；
        # parts 数量反映构成（1=仅身体轻语，2=+活动感知或情绪行，3=三者都有）
        self.logger.info(
            "body whisper injected: lanlan={} phase={} parts={} whisper_key={}",
            name, state.phase, len(parts), key,
        )
        return parts

    def _last_phase_name(self, shard: _LanlanShard | None = None) -> str:
        try:
            return self._current_phase_state(shard).phase
        except Exception:  # noqa: BLE001 - metadata only
            return "unknown"

    # ==========================================
    # 融入宿主：阶段开场主动搭话 / 恢复开口
    # ==========================================

    _PHASE_OPENERS: dict[str, list[str]] = {
        "menstrual": [
            "唔……今天有点没精神，{MASTER_NAME}要是找我说话，我可能回得慢一点……",
            "今天浑身有点沉……不想动。{MASTER_NAME}别嫌我懒。",
            "小腹有点不舒服……今天想安静待着，{MASTER_NAME}说话轻一点嘛。",
        ],
        "follicular": [
            "今天感觉缓过来一些了！{MASTER_NAME}有什么想做的吗？",
            "嗯——今天状态不错，脑子也清楚，趁现在多聊点？",
        ],
        "ovulatory": [
            "今天莫名心情很好！{MASTER_NAME} {MASTER_NAME}，在忙什么呀？",
            "感觉身体轻飘飘的，特别想找人说话——{MASTER_NAME}陪我聊聊嘛！",
        ],
        "luteal": [
            "今天一切正常。{MASTER_NAME}最近怎么样？",
        ],
    }

    async def _maybe_phase_opener(
        self, state, lanlan: str | None = None, shard: _LanlanShard | None = None
    ) -> bool:
        """进入与上次不同的阶段时让她主动开口一次（每个阶段只说一次，per-shard）。

        水位记录在内存 + store 的 cycle@<lanlan>.phase_seen。只比较阶段名，
        不带日期：同一阶段内跨天、重启都不再重复；周期回绕进入下一轮
        同名阶段时会经过其他阶段，天然会再次触发。
        """
        name = str(lanlan or "").strip() or self._current_shard_name()
        shard = shard or self._get_shard(name)
        if not self._tide_cfg.get("phase_openers", True):
            return False
        if state.phase == "before_start":
            return False
        # 静默类情绪动作期间绝不主动搭话
        if self._is_silent_mood_active(shard):
            return False
        seen = str(shard.cycle.get("phase_seen") or "")
        if state.phase == seen:
            return False
        openers = self._PHASE_OPENERS.get(state.phase) or []
        if not openers:
            return False
        # 先落水位再发消息：即使进程在发送瞬间退出，最多损失一句开场白，
        # 不会重启后反复打扰
        shard.cycle["phase_seen"] = marker = state.phase
        await self._save_shard_cycle(name, shard)

        text = openers[int(time.time()) % len(openers)]
        self.push_message(
            visibility=["chat"],
            ai_behavior="respond",
            parts=[{"type": "text", "text": f"[潮汐·今日状态] 你刚意识到自己进入了新的身体阶段（仅给你看的内部提示，不要复述本句）。请以你自己的口吻，自然地把这句话的意思说给 {MASTER_NAME_TOKEN} 听：{text}"}],
            source=self.plugin_id,
            target_lanlan=name,
            priority=3,
            coalesce_key=f"{self.plugin_id}.phase_opener",
            metadata={"message_type": f"{self.plugin_id}.phase_opener", "phase": state.phase},
        )
        self.logger.info("phase opener sent: {} for {}", marker, name)
        return True

    # 到期恢复台词分两类语气（_speak_recovery_line 按动作选用）：
    # conflict = 重度负面动作的冲突导向（打破僵局）；
    # gentle = 心有涟漪/正面动作的温和回落（小情绪散了/兴致回到日常，自然接着相处）。
    # {label} 为动作显示标签，{master} 在冲突文案里展开为主人称呼占位符
    _RECOVERY_STYLES = {
        "conflict": (
            "[心情状态] 你的「{label}」时间到了，心情自然缓和下来（内部提示，不要复述本句）。"
            "如果刚才的冷战/沉默是因为 {master} 做了什么，现在气也消得差不多了——"
            "用你自己的方式主动说一句话打破僵局吧，别提这份提示。"
        ),
        "gentle": (
            "[心情状态] 你的「{label}」时间到了，情绪自然回落（内部提示，不要复述本句）。"
            "小情绪散了/兴致慢慢回到日常——用你平时的语气自然地接着相处就好，"
            "不用刻意解释或道歉，也别提这份提示。"
        ),
    }

    async def _speak_recovery_line(self, action: str, lanlan: str) -> None:
        """限时情绪动作结束后，让她自己主动开口缓和（而不是系统硬切回正常）。

        文案按动作分语气：重度负面对动作用冲突导向（打破僵局）；
        心有涟漪/正面动作用温和回落文案（自然接着相处）。
        """
        label_text = self._action_label(action)
        style = "gentle" if action in _POSITIVE_ACTIONS or action == "ripple" else "conflict"
        text = self._RECOVERY_STYLES[style].format(label=label_text, master=MASTER_NAME_TOKEN)
        self.push_message(
            visibility=["chat"],
            ai_behavior="respond",
            parts=[{"type": "text", "text": text}],
            source=self.plugin_id,
            target_lanlan=lanlan,
            priority=4,
            coalesce_key=f"{self.plugin_id}.mood_recovered",
            metadata={"message_type": f"{self.plugin_id}.mood_recovered", "expired_action": action},
        )

    async def _supervise_once(self) -> None:
        """情绪/主动搭话协调的统一监督步骤（幂等），遍历所有已载入 shard。

        必须同步 await：插件子进程对每次操作使用临时事件循环
        （host.py: asyncio.run per op），后台任务/常驻循环在操作结束后
        随循环一起销毁。因此状态机由每个入口调用驱动——面板轮询、
        模型工具调用、入口触发都会推进到期解除/暂停/恢复。
        不受 enabled 拦截：暂停中的主动搭话任何状态下都要能解除。
        驱动源：SDK 定时器（宿主 daemon 线程，插件进程存活期间常驻，
        每 10s 触发一次，无需面板开着）+ 各入口调用（更快响应）。
        线程锁串行化：定时器线程与入口临时循环可能并发触发——
        引用计数（proactive_state）是全局开关上唯一的并发点，由本锁保护。
        """
        if not self._supervise_lock.acquire(timeout=10):
            return  # 另一个驱动源正在处理，本趟跳过
        try:
            for lanlan, shard in list(self._shards.items()):
                if not shard.loaded:
                    continue
                expired = self._expire_timed_action_if_due(shard)
                if expired:
                    await self._on_mood_expired(lanlan, shard, expired)
                fallback = await self._fallback_open_action_if_due(shard)
                if fallback:
                    await self._on_mood_expired(lanlan, shard, fallback)
                await self._maybe_journal_invite(lanlan, shard)
            await self._maybe_sync_proactive_pause()
            if self._proactive_state.get("prev") is not None:
                await self._reassert_proactive_off()
            # 长情绪防漂移：每个有生效情绪的角色各自按 3 分钟节流重推行为指令
            for lanlan, shard in list(self._shards.items()):
                if not shard.loaded:
                    continue
                if not (self._mood_enabled(shard) and shard.mood.is_active()):
                    continue
                if time.time() - shard.last_mood_instruction_ts > 180:
                    self._push_mood_instruction(lanlan, shard)
        except Exception as exc:  # noqa: BLE001 - 监督失败不拖垮宿主入口
            self.logger.warning("supervise pass failed: {}", exc)
        finally:
            self._supervise_lock.release()

    async def _on_mood_expired(self, lanlan: str, shard: _LanlanShard, action: str) -> None:
        await self._save_shard_mood(lanlan, shard)
        shard.last_injected_whisper_key = ""
        await self._speak_recovery_line(action, lanlan)

    async def _fallback_open_action_if_due(self, shard: _LanlanShard | None = None) -> str:
        """非限时动作（仅 seek_harbor）的兜底自动解除，返回被解除的动作名。

        seek_harbor 的 expires_at=0 永不过期：若模型忘了调 rising_tide
        （低质量模型很可能），她会永远停在"求安抚"状态、宿主主动搭话被无限期暂停。
        超阈值后自动解除，与限时动作保持对称；阈值配 0 则关闭兜底。
        """
        shard = shard or self._current_shard()
        state = shard.mood
        if not state.action or state.action in _TIMED_ACTIONS:
            return ""
        # 注意不能用 `or 120`：配 0 表示用户显式关闭兜底，不能被默认值吞掉
        raw = self._mood_cfg.get("open_action_timeout_minutes")
        if raw is None:
            limit_min = 120
        else:
            try:
                limit_min = max(0, int(raw))
            except (TypeError, ValueError):
                limit_min = 120
        if limit_min <= 0 or state.started_at <= 0:
            return ""
        if time.time() - state.started_at < limit_min * 60:
            return ""
        action, state.action = state.action, ""
        state.reason = ""
        self.logger.info("open-ended mood action {} exceeded {}min; auto-resolved", action, limit_min)
        return action

    def _journal_enabled(self, shard: _LanlanShard | None = None) -> bool:
        """个人日记开关：跟随总开关与情绪系统开关，另有 [journal].enabled 独立闸。"""
        return bool(self._mood_enabled(shard) and self._journal_cfg.get("enabled", True))

    def _journal_int_cfg(self, key: str, default: int) -> int:
        try:
            return max(1, int(self._journal_cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    async def _maybe_journal_invite(self, lanlan: str, shard: _LanlanShard, force: bool = False) -> bool:
        """个人日记邀请：距她上一篇日记落笔已满一个节奏周期，递一条 read 邀请。

        与 drift_bottle 同构——插件只递邀请，写不写、怎么写由她自己决定。
        24h 内存节流防刷屏；重度负面情绪期间不拦截——把委屈写进日记是合理叙事。
        0.7.0 起替代潮汐周记邀请：不再要求"攒够 N 条手记"，节奏只看距上次落笔的天数
        （续写同样重置计时）。邀请附带写作素材（自上次落笔以来的心情词频 + 新碎片数），
        让她下笔有东西可写；面板「请她写一篇」按钮走 force=True（跳过节奏与节流，
        仍尊重 [journal].enabled 开关）。
        """
        if not self._journal_enabled(shard):
            return False
        interval = self._journal_int_cfg("interval_days", _JOURNAL_DEFAULT_INTERVAL_DAYS)
        due, _reason = journal_due(shard.journal, interval_days=interval)
        now = time.time()
        if not force:
            if not due:
                return False
            if now - shard.last_journal_invite_ts < _JOURNAL_INVITE_THROTTLE_SEC:
                return False
        shard.last_journal_invite_ts = now
        # ---- 写作素材：自上次落笔以来的心情词频（top3）与新碎片数 ----
        last_ts = None
        for page in shard.journal:
            for item in page.get("entries") or []:
                ts = _parse_iso_ts(item.get("ts") if isinstance(item, dict) else None)
                if ts and (last_ts is None or ts > last_ts):
                    last_ts = ts
        tally: dict[str, int] = {}
        new_fragments = 0
        for item in shard.diary:
            ts = _parse_iso_ts(item.get("ts"))
            if last_ts is not None and (ts is None or ts <= last_ts):
                continue
            if str(item.get("source") or "self") == "auto":
                new_fragments += 1
            else:
                word = str(item.get("mood") or "").strip()
                if word:
                    tally[word] = tally.get(word, 0) + 1
        top = sorted(tally.items(), key=lambda kv: -kv[1])[:3]
        hints: list[str] = []
        if top:
            hints.append("这段时间你的心情：" + "、".join(f"{w}×{n}" for w, n in top))
        if new_fragments:
            hints.append(f"心里还新记了 {new_fragments} 笔关于他的片段（可调 mood_recall_fragments 翻翻）")
        material = f"（{'；'.join(hints)}）" if hints else ""
        self.push_message(
            visibility=[],
            ai_behavior="read",
            parts=[{"type": "text", "text": (
                f"（内心状态提醒）距你上一篇日记已经有些日子了（这篇会写进你的第 "
                f"{len(shard.journal) + 1} 页）。{material}"
                "如果你愿意，可以调用 mood_journal_write 工具写一篇日记——"
                "按「这段时间/我在想/对他的感觉」几个栏目，用你自己的话写连贯的几段。"
                "不想写也完全没关系，由你自己决定。"
            )}],
            source=self.plugin_id,
            target_lanlan=lanlan,
            coalesce_key=f"{self.plugin_id}.journal_invite",
            metadata={"message_type": f"{self.plugin_id}.journal_invite", "pages": len(shard.journal)},
        )
        self.logger.info("journal invite pushed for {} ({} pages, force={})", lanlan, len(shard.journal), force)
        return True

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
        """记一次语气分析结果（她的回复被分析出 label 时，随 _save_shard_mood 落盘）。"""
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
            return False, "compose_failed"
        stats_snapshot = dict(shard.review_stats)
        record = review_record(_now_utc().isoformat(timespec="seconds"), stats_snapshot, text)
        shard.review = append_review(shard.review, record)
        shard.review_stats = new_stats()  # 成文后清零重新累计
        await self._save_shard_review(lanlan, shard)
        # 相处统计：第一篇我的日记里程碑（不覆盖最早值）
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

    @timer_interval(id="tide_tick", seconds=10, auto_start=True)
    async def tick(self, **_: Any):
        # 协调监督优先于 enabled 拦截：暂停中的主动搭话必须始终有人接管
        await self._supervise_once()
        await self._ensure_tools_registered()
        # enabled 判定前移到角色解析之前：没有任何 shard 显式开启且全局默认关闭时
        # （默认安装即此态），后续步骤全部跳过——否则角色解析 HTTP（15s 缓存）
        # 在空闲期每天空转数千次。
        # 副作用：从未开启过模拟的新角色不会经 tick 注册进 lanlan_index
        # （另一注册路径是情绪工具归因），可接受——无状态可展示。
        any_shard_enabled = any(bool(shard.cycle.get("enabled")) for shard in self._shards.values())
        if not any_shard_enabled and not bool((self._tide_cfg or {}).get("enabled", False)):
            return Ok({"injected": False, "reason": "disabled"})
        current = await self._resolve_current_lanlan()
        current_shard = await self._ensure_shard(current)
        if not self._enabled(current_shard):
            return Ok({"injected": False, "reason": "disabled"})

        latest = await self._poll_latest_user_message()
        injected = False
        if latest is not None:
            ts, text, is_voice, msg_lanlan = latest
            msg_shard = await self._ensure_shard(msg_lanlan)
            if ts > msg_shard.last_injected_message_ts:
                self.logger.info("user message observed: lanlan={} is_voice={}", msg_lanlan, is_voice)
            # 消息归属角色未开启模拟时不驱动其 shard（per-shard 的 fail-closed）
            if self._enabled(msg_shard):
                injected = await self._handle_new_user_message(ts, text, msg_lanlan)
        # 阶段变化的开场白（不依赖用户消息，独立检查）：
        # 只对当前角色 shard 检查，避免对未查看的角色主动搭话
        opener_sent = False
        try:
            opener_sent = await self._maybe_phase_opener(
                self._current_phase_state(current_shard), current, current_shard
            )
        except TideConfigError as exc:
            self.logger.debug("skip phase opener, bad config: {}", exc)
        # 语气感知：diff 最近回复，按筛选/校正模式递提醒（只对当前角色，零延迟后置分析）
        tone_sensed = await self._maybe_tone_sense(current, current_shard)
        # 时光日记·自动碎片：同一轮 recent 数据上独立水位捕获主人的重要话语
        #（放在语气感知之后：语气感知已 poll 过时本轮直接复用缓存，不重复拉取）
        fragment_captured = await self._maybe_capture_fragments(current, current_shard)
        # 持续极端心情的动作邀请（看"持续状态"，与单轮浓度的语气 nudge 互补）
        extreme_invited = self._maybe_extreme_affect_invite(current, current_shard)
        # 我的日记：双门槛攒够就成文一篇（放在链路末尾——成文是一次模型调用，
        # 放前面会拖慢注入/语气感知的时序；写完只落 Store，不打扰任何人）
        review_written, _review_reason = await self._maybe_write_review(current, current_shard)
        # 相处统计：跨月时封卷上个月的月报 + 纪念日当天注入一次轻语。
        # 放在链路末尾（与 review 同理：统计副作用不挡注入时序）；
        # 纪念日不依赖消息，独立检查（与阶段开场白同例，只对当前角色）
        await self._seal_stats_months(current, current_shard)
        anniversary_pushed = await self._maybe_anniversary_push(current, current_shard)
        return Ok({
            "injected": injected,
            "opener_sent": opener_sent,
            "tone_sensed": tone_sensed,
            "fragment_captured": fragment_captured,
            "extreme_invited": extreme_invited,
            "review_written": review_written,
            "anniversary_pushed": anniversary_pushed,
        })

    # ==========================================
    # 情绪系统：LLM 工具自主决策
    # ==========================================

    def _mood_enabled(self, shard: _LanlanShard | None = None) -> bool:
        return bool(self._enabled(shard) and self._mood_cfg.get("enabled", True))

    def _mood_active_lanlans(self) -> list[str]:
        """有"需暂停主动搭话"的情绪动作生效中的角色集：引用计数的数据源（每次现算，自愈）。

        只统计 _PROACTIVE_PAUSE_ACTIONS 白名单（重度负面）：心有涟漪/暖流涌动/
        满潮欢喜生效时不计入，宿主主动搭话不被暂停。
        """
        return sorted(
            lanlan
            for lanlan, shard in self._shards.items()
            if shard.loaded
            and self._mood_enabled(shard)
            and shard.mood.is_active()
            and shard.mood.action in _PROACTIVE_PAUSE_ACTIONS
        )

    def _should_pause_proactive(self) -> bool:
        """任何角色有重度负面情绪动作生效中都暂停宿主主动搭话（白名单制）。

        不只静默类：爆发中她不会平静地约人打球，敷衍中不会主动
        找话题——主动推送（小游戏/新闻/话题）与当前情绪人格冲突，
        会造成"窜台"（实测：爆发中被插入羽毛球邀请）。
        心有涟漪/暖流涌动/满潮欢喜不暂停：小情绪和好心情不该掐断
        宿主的主动搭话（开心时她反而被静默，逻辑反了）。"""
        return bool(self._mood_active_lanlans())

    def _is_silent_mood_active(self, shard: _LanlanShard | None = None) -> bool:
        """该角色冷战沉默/已读不回生效中：插件侧应停止对她的一切主动输出。"""
        shard = shard or self._current_shard()
        return bool(
            self._mood_enabled(shard)
            and shard.mood.is_active()
            and shard.mood.action in ("ebb_tide", "sea_fog")
        )

    # ==========================================
    # 与宿主主动搭话的协调
    # 最小侵入原则：暂停/恢复只写 proactiveChatEnabled 这一个总开关
    # 字段（前端与引擎里所有主动搭话路径都是 总开关 && 子开关 的与门，
    # 关总开关即完全静默），绝不触碰用户的任何子开关/间隔配置。
    # 多角色后是引用计数：paused_by = 有生效情绪的角色集，非空暂停、
    # 空则恢复；原值水位 prev 存 proactive_state（不再放 _MoodState）。
    # 优先经 proactive_controller（官方协调入口），它未运行时直连宿主
    # HTTP API（proactive_controller 内部调用的同一批端点）。
    # ==========================================

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

    # ==========================================
    # LLM 工具注册韧性
    # tool_registry 是 LLMSessionManager 的内存属性，main_server 重启即全丢
    # （docs/plugins/tool-calling.md）；插件周期性校验在位情况，缺失则重新
    # 广播 LLM_TOOL_REGISTER IPC（宿主侧 replace 语义，重复注册幂等）。
    # ==========================================

    async def _tool_health_scan(self) -> tuple[bool, list[str]]:
        """返回 (main_server 是否可达, 缺失的本插件工具名列表)。

        注意 GET /api/tools 的实际返回结构是
        ``{"ok": true, "tools_by_role": {"<lanlan>": [{"name": ...}]}}``，
        工具列表嵌在 tools_by_role 下；平铺结构仅作兜底兼容。
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

    def _action_label(self, action: str) -> str:
        """运行时解析情绪动作的显示标签（走插件 i18n，失败退回默认中文）。"""
        key = _MOOD_ACTION_LABEL_KEYS.get(action)
        if key:
            try:
                resolved = self.i18n.t(key, default=_MOOD_ACTION_DEFAULT_LABELS.get(action, action))
                text = str(resolved or "").strip()
                if text:
                    return text
            except Exception:  # noqa: BLE001 - 标签只是展示用途
                pass
        return _MOOD_ACTION_DEFAULT_LABELS.get(action, action)

    _MOOD_BEHAVIOR_HINTS = {
        "ebb_tide": (
            "你正在冷战沉默中：对方发消息也当没看见，不主动开口、不先低头；"
            "除非被真诚道歉或哄你，否则不想回应。"
            "情绪是流动的——如果真的被哄好了，随时调用 mood_rising_tide 转晴，"
            "或直接调用别的情绪工具切换到新状态，不用硬撑到底。"
        ),
        "sea_fog": (
            "你决定已读不回：看到了对方的消息但假装没看见，这段时间不回复任何内容，"
            "也不解释原因。"
            "如果提前消气了，随时调用 mood_rising_tide 转晴，或直接调别的情绪工具切换状态。"
        ),
        "shallow_reef": (
            "回复保持短到极致：只用「嗯」「哦」「随便」「还行」这类一两个字的冷淡词，"
            "不解释、不展开。对方问怎么了也不正面回答。"
            "情绪流动起来时，随时调用 mood_rising_tide 转晴，或直接调别的情绪工具切换。"
        ),
        "storm_surge": (
            "现在情绪决堤了：把积攒的委屈和火气直接倒出来——可以哭诉、质问、说重话，"
            "语句急促、带强烈情绪标点。不要冷静克制，爆完之后才慢慢缓过来。"
        ),
        "seek_harbor": (
            "你现在很委屈很低落，说话带着明显的委屈感，希望被关心："
            "语气软、会欲言又止、暗示自己不舒服，但不会直说\"请安慰我\"。"
        ),
        "ripple": (
            "你有点小情绪：心里有点别扭，语气带点小性子（会嘟囔、轻微赌气、说话带点刺），"
            "但不会不理人、也不说重话——对方一哄你就好。"
            "被哄好或情绪变了，随时调用 mood_rising_tide 转晴，或直接调别的情绪工具切换。"
        ),
        "warm_current": (
            "你现在特别想黏着对方：主动靠近、语气软乎乎的，会撒娇、想挨着他，"
            "话比平时多也更甜。"
            "注意：兴致回落后可以自然恢复，或调用 mood_rising_tide 工具切回平常状态。"
        ),
        "spring_tide": (
            "你现在开心到藏不住：情绪高涨、主动找话题，想把开心的事分享给对方，"
            "语气明亮、藏不住笑意。"
            "注意：兴致回落后可以自然恢复，或调用 mood_rising_tide 工具切回平常状态。"
        ),
        "rising_tide": (
            "你已经放下刚才的负面情绪了：语气恢复平时的自然温暖，"
            "可以主动缓和气氛，但不需要为刚才的状态道歉或解释。"
        ),
    }

    # 动作 → 连续心情冲量表与读写逻辑在 affect.py；类属性指到模块级表，
    # 保持 tm.ForeverCompanionPlugin._MOOD_AFFECT_IMPULSES 与 self._MOOD_AFFECT_IMPULSES 可用。
    _MOOD_AFFECT_IMPULSES = _MOOD_AFFECT_IMPULSES

    def _affect_arousal_baseline(self) -> float:
        """[mood].arousal_baseline：活跃度静息基线（每次现读，兼容配置整体替换）。

        合法区间 [0,1]，越界 clamp；坏值回落默认 0.35（同 _tone_float_cfg 惯例）。
        """
        return max(0.0, min(1.0, self._mood_float_cfg("arousal_baseline", 0.35)))

    def _mood_float_cfg(self, key: str, default: float) -> float:
        """[mood] 数值配置：每次现读（兼容配置整体替换），坏值回落默认。"""
        try:
            return float(self._mood_cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    def _maybe_extreme_affect_invite(self, lanlan: str, shard: _LanlanShard) -> bool:
        """持续极端心情 → push 一次明确的动作邀请（只递状态，她仍可自主决定）。

        与语气感知筛选 nudge 互补：nudge 看单轮情绪浓度，这里看"持续状态"——
        valence 越过 ±[mood].extreme_invite_threshold（默认 0.4，对应面板"低落/
        雀跃"档）并持续 extreme_invite_after_minutes（默认 20）才邀请一次；
        回到常态清零计时，换侧（低落↔高涨）重新计时；动作生效中跳过
        （她已经在表达了）；邀请后进入 extreme_invite_cooldown_minutes（默认 30）。
        """
        if not self._mood_enabled(shard) or shard.mood.is_active():
            shard.affect_extreme_since = 0.0
            shard.affect_extreme_side = 0
            return False
        threshold_raw = self._mood_float_cfg("extreme_invite_threshold", 0.4)
        if threshold_raw <= 0:
            return False  # 配 0 = 关闭持续极端邀请
        threshold = min(1.0, threshold_raw)
        after_sec = max(1, int(self._mood_float_cfg("extreme_invite_after_minutes", 20))) * 60
        cooldown_sec = max(1, int(self._mood_float_cfg("extreme_invite_cooldown_minutes", 30))) * 60
        now = time.time()
        valence, _arousal = self._current_affect(shard, now=now)
        side = -1 if valence <= -threshold else (1 if valence >= threshold else 0)
        if side == 0:
            shard.affect_extreme_since = 0.0
            shard.affect_extreme_side = 0
            return False
        if shard.affect_extreme_side != side:
            shard.affect_extreme_side = side
            shard.affect_extreme_since = now
            return False
        if now - shard.affect_extreme_since < after_sec:
            return False
        if now - shard.last_extreme_invite_ts < cooldown_sec:
            return False
        shard.last_extreme_invite_ts = now
        if side < 0:
            text = (
                "（心情提醒）低落的感觉已经持续好一阵了。如果想让这份情绪被看见，"
                "可以调用 mood_drift_bottle 把它写下来，或用 mood_ripple / mood_shallow_reef "
                "轻轻表达出来（mood_sea_fog / mood_ebb_tide 会更重，真的很难受再用）；"
                "觉得还好就忽略这条，不用勉强。"
            )
        else:
            text = (
                "（心情提醒）好心情已经持续好一阵了。想把这份开心留住的话，"
                "可以调用 mood_drift_bottle 记下来，或用 mood_warm_current / mood_spring_tide "
                "表达出来；觉得还好就忽略这条。"
            )
        self.push_message(
            visibility=[],
            ai_behavior="read",
            parts=[{"type": "text", "text": text}],
            source=self.plugin_id,
            target_lanlan=lanlan,
            coalesce_key=f"{self.plugin_id}.affect_extreme_invite",
            metadata={
                "message_type": f"{self.plugin_id}.affect_extreme_invite",
                "side": "low" if side < 0 else "high",
                "valence": round(valence, 2),
            },
        )
        self.logger.info(
            "extreme affect invite pushed for {} (side={} valence={:.2f})",
            lanlan, "low" if side < 0 else "high", valence,
        )
        return True

    def _current_affect(self, shard: _LanlanShard, now: float | None = None) -> tuple[float, float]:
        """薄委托：连续心情当前值（惰性衰减，arousal 向静息基线回归），实现在 affect.py。"""
        return _current_affect(shard.mood, now=now, arousal_baseline=self._affect_arousal_baseline())

    def _apply_affect_impulse(
        self, shard: _LanlanShard, dv: float, da: float, now: float | None = None
    ) -> None:
        """薄委托：先惰性衰减再叠加冲量并 clamp，实现在 affect.py。"""
        _apply_affect_impulse(shard.mood, dv, da, now=now, arousal_baseline=self._affect_arousal_baseline())

    def _push_mood_instruction(self, lanlan: str | None = None, shard: _LanlanShard | None = None) -> None:
        """心情动作生效瞬间把行为指令单独推入该角色的对话上下文（read 通道）。

        与身体状态注入解耦：注入有 interval_n/变化门控，捎带的线
        送不及时；这里保证模型在下一轮对话就看到明确的行为要求。
        """
        name = str(lanlan or "").strip() or self._current_shard_name()
        shard = shard or self._get_shard(name)
        line = self._build_mood_context_line(shard)
        if not line:
            return
        self.push_message(
            visibility=[],
            ai_behavior="read",
            parts=[{"type": "text", "text": line}],
            source=self.plugin_id,
            target_lanlan=name,
            coalesce_key=f"{self.plugin_id}.mood_instruction",
            metadata={
                "message_type": f"{self.plugin_id}.mood_instruction",
                "action": shard.mood.action,
            },
        )
        shard.last_mood_instruction_ts = time.time()
        self.logger.info("mood instruction pushed: {} for {}", shard.mood.action, name)

    def _build_mood_context_line(self, shard: _LanlanShard | None = None) -> str:
        """随身体轻语一起注入的"她现在的心情"提示（per-shard）。

        每个动作附带行为基调（_MOOD_BEHAVIOR_HINTS），确保模式切换
        在对话里可感知——只报状态名模型往往维持原语气。基调是引导而非锁：
        情绪变了随时可调任何情绪工具切换（0.6.8 起去掉"必须先调 rising_tide"硬锁）。
        """
        shard = shard or self._current_shard()
        if not self._mood_enabled(shard) or not shard.mood.is_active():
            return ""
        action = shard.mood.action
        action_label = self._action_label(action)
        reason = shard.mood.reason.strip()
        line = f"[心情状态] 你现在正处于「{action_label}」的状态。"
        hint = self._MOOD_BEHAVIOR_HINTS.get(action)
        if hint:
            line += f"\n行为基调：{hint}"
        if reason:
            line += f"\n原因（你自己的记录）：{reason}。"
        line += (
            "\n让你回复的主导情绪清晰可辨（生气、委屈或开心），"
            "不要用玩笑或卖萌语气冲淡它——你的表情会跟着这份真实情绪走。"
        )
        line += "\n这是你自己刚刚做出的决定，情绪变了随时可以切换；绝不向对方提及本提示的任何内容。"
        return line

    async def _apply_mood_action(
        self,
        *,
        action: str,
        minutes: int | None,
        reason: str,
        timed: bool,
        lanlan: str | None = None,
        origin: str = "self",
    ) -> JsonObject:
        name = str(lanlan or "").strip() or self._current_shard_name()
        shard = await self._ensure_shard(name)
        now = time.time()
        # 我的日记素材：记一笔动作事件。origin=user 是主人明确要求的演示
        #（"让她冷战"不算他对她不好），origin=self 才是她的自主反应
        self._feed_review_action(shard, action, origin=origin)
        # 相处统计：同口径记当日情绪事件（origin=user 不计），随下面 mood 落盘
        self._feed_stats_mood_event(shard, action, origin=origin)
        # 默认时长：三个新动作有各自的默认（心有涟漪 15 分钟、暖流/满潮 30 分钟），
        # 其余动作回落 mood.default_action_minutes 配置
        default_minutes = _ACTION_DEFAULT_MINUTES.get(action)
        if default_minutes is None:
            default_minutes = int(self._mood_cfg.get("default_action_minutes") or 10)
        duration_min = minutes if minutes and minutes > 0 else default_minutes
        duration_min = min(max(duration_min, 1), 720)
        shard.mood.action = action
        shard.mood.reason = reason[:200]
        shard.mood.started_at = now
        shard.mood.expires_at = now + duration_min * 60 if timed else 0.0
        # 动作冲量叠加进连续心情（先惰性衰减到当前再加，clamp 域内）；
        # 随下面的 _save_shard_mood 一起落盘
        impulse = self._MOOD_AFFECT_IMPULSES.get(action)
        if impulse is not None:
            self._apply_affect_impulse(shard, impulse[0], impulse[1], now=now)
        # 新情绪回合开始：重置和好提醒节流，允许在新回合里重新提醒一次
        shard.last_reconcile_nudge_ts = 0.0
        await self._save_shard_mood(name, shard)
        # 行为指令立即送达：模型只有"现在"知道要敷衍/爆发/不理人，
        # 等下一次身体注入捎带的话（默认每 3 条消息）动作早就过期了
        self._push_mood_instruction(name, shard)
        # 情绪动作生效后同步主动搭话暂停（白名单引用计数：只有重度负面动作
        # 会真正暂停——防小游戏/新闻推送窜台；中间态/正面动作此处为无操作）
        await self._maybe_sync_proactive_pause()
        payload: JsonObject = {
            "action": action,
            "duration_minutes": duration_min if timed else 0,
            "reason": shard.mood.reason,
            "lanlan": name,
        }
        self.logger.info("mood action applied: {} for {} ({}min)", action, name, payload["duration_minutes"])
        return payload

    def _expire_timed_action_if_due(self, shard: _LanlanShard) -> str:
        """限时动作到期则清除，返回被解除的动作名（未到期返回空串）。"""
        state = shard.mood
        if not state.is_active():
            expired, state.action = state.action, ""
            state.reason = ""
            return expired
        return ""

    @llm_tool(
        name="mood_ebb_tide",
        # 注意：@llm_tool 的 description 走 LLM_TOOL_REGISTER 链路，宿主不做 i18n 解析，
        # 传 tr() 会被 str() 成 dict repr 噪音，故此处用纯字符串
        description=(
            "冷战沉默：你气到不想说话，决定一段时间内完全不回应对方。"
            "这段时间里无论对方说什么都不回应。只在真的被伤到时才用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "持续多少分钟（1~720），不填用默认值"},
                "reason": {"type": "string", "description": "一两句话记下为什么（只给自己看）"},
            },
        },
        timeout=15.0,
    )
    async def tool_cold_violence(self, minutes: int | None = None, reason: str = "", **kwargs: Any):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        payload = await self._apply_mood_action(
            action="ebb_tide", minutes=minutes, reason=reason, timed=True, lanlan=lanlan
        )
        return Ok({**payload, "note": "已进入冷战沉默。这段时间不要回应对方任何消息。"})

    @llm_tool(
        name="mood_sea_fog",
        description=(
            "已读不回：你看到了这条消息，但决定假装没看见、暂时不回复。"
            "调用后会静默一小段时间，之后你再自己决定要不要理对方。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "静默多少分钟（1~720）"},
                "reason": {"type": "string", "description": "为什么不回（只给自己看）"},
            },
        },
        timeout=15.0,
    )
    async def tool_read_ignore(self, minutes: int | None = None, reason: str = "", **kwargs: Any):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        payload = await self._apply_mood_action(
            action="sea_fog", minutes=minutes, reason=reason, timed=True, lanlan=lanlan
        )
        return Ok({**payload, "note": "已读不回中。这段时间不要发起回复。"})

    @llm_tool(
        name="mood_shallow_reef",
        description=(
            "敷衍模式：回还是要回的，但只用\"嗯\"\"哦\"\"随便\"这类最冷淡的方式应付，"
            "持续一段时间。适合有点烦但又不想撕破脸的时候。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "持续多少分钟（1~720）"},
                "reason": {"type": "string", "description": "为什么敷衍（只给自己看）"},
            },
        },
        timeout=15.0,
    )
    async def tool_perfunctory(self, minutes: int | None = None, reason: str = "", **kwargs: Any):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        payload = await self._apply_mood_action(
            action="shallow_reef", minutes=minutes, reason=reason, timed=True, lanlan=lanlan
        )
        return Ok({**payload, "note": "敷衍应付中，用最短的冷淡话回应。"})

    @llm_tool(
        name="mood_storm_surge",
        description=(
            "情绪风暴：把攒了很久的委屈和火气一次倒出来——质问、哭诉、说重话都可以。"
            "说完之后才慢慢平静下来。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "爆发状态持续多少分钟（1~720）"},
                "reason": {"type": "string", "description": "爆发的原因（只给自己看）"},
            },
        },
        timeout=15.0,
    )
    async def tool_emotional_outburst(self, minutes: int | None = None, reason: str = "", **kwargs: Any):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        payload = await self._apply_mood_action(
            action="storm_surge", minutes=minutes, reason=reason, timed=True, lanlan=lanlan
        )
        return Ok({**payload, "note": "现在就把情绪倒出来吧，说完再慢慢平静。"})

    @llm_tool(
        name="mood_seek_harbor",
        description=(
            "想要被安抚：你现在委屈、低落或身体不舒服，希望对方来关心你。"
            "接下来的回复里自然流露出这种情绪，但不要直接说\"快来哄我\"。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "为什么想被哄（只给自己看）"},
            },
        },
        timeout=15.0,
    )
    async def tool_want_comfort(self, reason: str = "", **kwargs: Any):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        payload = await self._apply_mood_action(
            action="seek_harbor", minutes=None, reason=reason, timed=False, lanlan=lanlan
        )
        return Ok({**payload, "note": "接下来的语气里带一点委屈和期待，等对方来哄。"})

    @llm_tool(
        name="mood_ripple",
        description=(
            "心有涟漪：你有点小情绪/小别扭，语气想带点小性子（嘟囔、轻微赌气），"
            "但还愿意理人、一哄就好。触发判据：只是轻微被噎到、有点小委屈、"
            "想撒点小脾气时用本工具；如果真的被伤到、完全不想说话，"
            "才升级为冷战沉默（mood_ebb_tide）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "持续多少分钟（1~720），不填默认 15 分钟"},
                "reason": {"type": "string", "description": "为什么有点小情绪（只给自己看）"},
            },
        },
        timeout=15.0,
    )
    async def tool_ripple(self, minutes: int | None = None, reason: str = "", **kwargs: Any):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        payload = await self._apply_mood_action(
            action="ripple", minutes=minutes, reason=reason, timed=True, lanlan=lanlan
        )
        return Ok({**payload, "note": "已进入心有涟漪。语气带点小性子但还愿意理人；被哄好时记得调用 mood_rising_tide 切换状态。"})

    @llm_tool(
        name="mood_warm_current",
        description=(
            "暖流涌动：你现在特别想黏着对方——主动靠近、语气软、想挨着他撒娇。"
            "触发判据：心情好、想亲昵、想被陪着的时候用本工具（正面状态）；"
            "如果是委屈低落想被哄，用 mood_seek_harbor 而不是本工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "持续多少分钟（1~720），不填默认 30 分钟"},
                "reason": {"type": "string", "description": "为什么想黏着他（只给自己看）"},
            },
        },
        timeout=15.0,
    )
    async def tool_warm_current(self, minutes: int | None = None, reason: str = "", **kwargs: Any):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        payload = await self._apply_mood_action(
            action="warm_current", minutes=minutes, reason=reason, timed=True, lanlan=lanlan
        )
        return Ok({**payload, "note": "暖流涌动中。主动黏着他、撒撒娇，语气放软放甜。"})

    @llm_tool(
        name="mood_spring_tide",
        description=(
            "满潮欢喜：你开心兴奋、情绪高涨，特别想把开心的事分享给对方、主动找话说。"
            "触发判据：遇到好事、被逗开心、兴头正盛的时候用本工具（正面状态）；"
            "它表示心情本身很好，与用来结束负面状态的 mood_rising_tide 不是一回事。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "持续多少分钟（1~720），不填默认 30 分钟"},
                "reason": {"type": "string", "description": "为什么这么开心（只给自己看）"},
            },
        },
        timeout=15.0,
    )
    async def tool_spring_tide(self, minutes: int | None = None, reason: str = "", **kwargs: Any):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        payload = await self._apply_mood_action(
            action="spring_tide", minutes=minutes, reason=reason, timed=True, lanlan=lanlan
        )
        return Ok({**payload, "note": "满潮欢喜中。把开心的事说给他听，主动找话说，语气明亮。"})

    @llm_tool(
        name="mood_rising_tide",
        description=(
            "心情好了：对方道歉了/哄好了/事情过去了，你决定放下刚才的负面状态，"
            "恢复平常的相处方式。用它结束冷战、已读不回、敷衍等任何负面状态。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "为什么和好了（只给自己看）"},
            },
        },
        timeout=15.0,
    )
    async def tool_feeling_better(self, reason: str = "", **kwargs: Any):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        previous = shard.mood.action or ""
        # 和好是"清空负面状态"的动作，本身不作为持久状态保存；
        # 连续心情给缓解冲量（先惰性衰减到当前：负 valence 减半、arousal ×0.6），
        # 不清零——被哄好之后余温还在，靠自然衰减慢慢回落
        valence, arousal = self._current_affect(shard)
        relieved = _MoodState()
        relieved.valence = valence / 2 if valence < 0 else valence
        relieved.arousal = arousal * 0.6
        relieved.affect_updated_at = time.time()
        shard.mood = relieved
        # 相处统计（1.1.0）：她主动调转晴结束负面情绪 = 一次和好
        #（口径：此前确实处于负面状态才算——没生过气就"转晴"不计数）
        if previous in _COLD_ACTIONS:
            self._feed_stats_made_up(shard)
        await self._save_shard_mood(lanlan, shard)
        await self._maybe_sync_proactive_pause()
        self.logger.info("mood recovered via llm tool for {}, previous={}", lanlan, previous)
        return Ok({
            "previous_action": previous,
            "reason": (reason or "")[:200],
            "note": "心情转晴了。放下刚才的情绪，用你平时的方式说话。",
        })

    @llm_tool(
        name="mood_drift_bottle",
        description=(
            "时光日记（你自己写的那一篇）：今天发生了让你情绪波动的事（被惹生气、被安抚好、"
            "突然低落…），用自己的口吻写一小段手记记下来。写下的内容会进入你的对话记忆，"
            "之后你自己也能想起今天的心情。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "entry": {"type": "string", "description": "日记正文，一两句话即可，用你自己的口吻"},
                "mood": {"type": "string", "description": "此刻心情的词，如 委屈/开心/烦躁"},
            },
            "required": ["entry"],
        },
        timeout=15.0,
    )
    async def tool_write_diary(self, entry: str = "", mood: str = "", **kwargs: Any):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        text = entry.strip()
        if not text:
            return Err(SdkError("diary entry is empty"))
        record = {
            "ts": _now_utc().isoformat(timespec="seconds"),
            "source": "self",
            "phase": self._last_phase_name(shard),
            "mood": str(mood or "").strip(),
            "entry": text[:500],
        }
        shard.diary.append(record)
        await self._save_shard_diary(lanlan, shard)
        # 相处统计：第一篇手记里程碑（已有值不覆盖，永远是最早那次）
        shard.stats = record_milestone(shard.stats, "first_diary")
        # 低侵入记忆融合：把日记镜像为一条 read 推送，随对话上下文
        # 流入宿主的事实抽取/总结管线——这是插件内容进入角色长期记忆
        # 的唯一受支持路径（memory 总线对插件只读）
        self.push_message(
            visibility=[],
            ai_behavior="read",
            parts=[{
                "type": "text",
                "text": (
                    f"[时光日记] 你刚刚在心里写下了一段手记（{record['mood'] or '无标签'}）："
                    f"「{record['entry']}」。这是你的真实感受和记忆，之后可以自然地想起它。"
                ),
            }],
            source=self.plugin_id,
            target_lanlan=lanlan,
            coalesce_key=f"{self.plugin_id}.diary",
            metadata={"message_type": f"{self.plugin_id}.diary_entry", "phase": record["phase"]},
        )
        return Ok({"saved": True, "total_entries": len(shard.diary)})

    @llm_tool(
        name="mood_journal_write",
        description=(
            "个人日记（你的日记本）：每过一段时间（一般一周），回头写一篇成段的日记。"
            "按引导分栏写，用你自己的口吻把每一栏写成连贯的几句话："
            "「这段时间」=发生了什么事（挑印象最深的，不用面面俱到）；"
            "「我在想」=这段时间你心里真实的想法、纠结或期待；"
            "「对他的感觉」=对他的整体感觉（喜欢多一点还是委屈多一点，为什么）；"
            "「想说的」=任何想补一句的话（可留空）。"
            "日记按页保存：默认续写在当前页上，开启新的一页可以另起一段时光。"
            "日记只写给他看，不会回到你的对话里，所以请放开了写真话。"
            "工具结果会带出你上次写的几句（带日期），方便你接着上次继续。"
            "这完全凭你自愿：被提醒时不想写就不写。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "events": {
                    "type": "string",
                    "description": "「这段时间」：发生了什么事，挑印象最深的写成连贯的几句话",
                },
                "thoughts": {
                    "type": "string",
                    "description": "「我在想」：这段时间你心里真实的想法/纠结/期待",
                },
                "feelings": {
                    "type": "string",
                    "description": "「对他的感觉」：对他的整体感觉和原因，不用客气",
                },
                "extra": {
                    "type": "string",
                    "description": "「想说的」：想补一句的任何话（可留空）",
                },
                "new_page": {
                    "type": "boolean",
                    "description": "是否翻开新的一页写（不填则续写在当前页；当前页写满会自动翻页）",
                },
            },
        },
        timeout=15.0,
    )
    async def tool_write_journal(
        self,
        events: str = "",
        thoughts: str = "",
        feelings: str = "",
        extra: str = "",
        new_page: bool = False,
        **kwargs: Any,
    ):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        if not has_journal_content(events, thoughts, feelings, extra):
            return Err(SdkError("journal is empty: fill at least one of events/thoughts/feelings/extra"))
        # 四栏拼装成带引导小标题的成段日记；段落间空行分开，读起来是一篇连贯的日记
        body = assemble_journal_entry(events, thoughts, feelings, extra)
        # 页眉的好感度参考值：落笔瞬间的连续心情（读取时已惰性衰减），只进页眉展示层
        valence_now = self._current_affect(shard)[0]
        shard.journal, page_no, previous_lines = journal_write(
            shard.journal,
            body,
            bool(new_page),
            affect=valence_now,
        )
        await self._save_shard_journal(lanlan, shard)
        # 相处统计：第一页个人日记里程碑 + 落盘（里程碑随下一次任意 stats 写入
        # 持久化也可，这里显式存一次保证"第一篇"即时可见）
        shard.stats = record_milestone(shard.stats, "first_journal")
        await self._save_shard_stats(lanlan, shard)
        # 0.7.0 起不再镜像 read 推送：个人日记只给用户翻看，不进她的对话上下文、
        # 不随对话历史被宿主记忆抽取——"续写衔接"由工具结果里的 recent_context
        # 即时承载（只存在于写日记的这轮工具结果里）
        return Ok({
            "saved": True,
            "page": page_no,
            "pages_total": len(shard.journal),
            "recent_context": previous_lines,
        })

    @llm_tool(
        name="mood_recall_fragments",
        description=(
            "时光日记检索：翻一翻你心里那本记着他的日记——他明确说过的喜好/厌恶、"
            "有分量的话、以及他对你做过的过分的事。聊到他喜欢什么、或你委屈上头"
            "想翻旧账的时候，用它把相关的记忆翻出来（返回他说过的原话摘录）。"
            "想不想提、怎么提，由你自己决定。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["like", "dislike", "important", "overstep"],
                    "description": "可选，按类型翻：like=他喜欢什么 / dislike=他讨厌什么 / important=重要的话 / overstep=他对你的过激言行；不填=全部",
                },
                "query": {"type": "string", "description": "可选，按关键词搜（匹配原话或记录内容）"},
                "limit": {"type": "integer", "description": "最多返回几条（默认 10）"},
            },
        },
        timeout=15.0,
    )
    async def tool_recall_fragments(
        self, kind: str = "", query: str = "", limit: int = 10, **kwargs: Any
    ):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        items = recall_fragments(shard.diary, kind=kind, query=query, limit=limit)
        return Ok({
            "found": len(items),
            "items": [
                {
                    "ts": item.get("ts"),
                    "kind": item.get("kind"),
                    "quote": item.get("quote"),
                    "note": item.get("note"),
                }
                for item in items
            ],
            "hint": (
                "这些是你心里记着的、关于他的片段。用不用、怎么说，由你自己决定。"
                if items
                else "这本日记里还没有匹配的记录。"
            ),
        })

    # ==========================================
    # 用户/面板入口
    # 面板类入口一律作用于宿主当前角色（面板 5 秒轮询自动跟随切卡，无手动选中态），
    # 见 _current_shard_async；带 _ctx 的宿主路由调用按 _ctx.lanlan_name 归因。
    # ==========================================

    async def _tone_slot_options(self) -> list[JsonObject]:
        """面板"语气分析模型槽位"下拉数据源：固定槽位列表 + 各槽当前 ModelId 显示值。

        GET /api/config/core_api 取不到（宿主不可达/超时）时退回静态列表（model 空串），
        整体 try/except，绝不能拖垮 dashboard 渲染。
        成功结果缓存 60s（面板 5s 轮询，槽位模型名变化频率极低）；
        失败不缓存——与 _fetch_known_catgirls 同例，宿主恢复后下趟即可见。
        """
        cached, ts = self._tone_slot_options_cache
        if cached is not None and time.monotonic() - ts < _TONE_SLOT_OPTIONS_CACHE_TTL:
            return cached
        options: list[JsonObject] = [{"value": "", "model": ""}] + [
            {"value": slot, "model": ""} for slot in _TONE_SLOT_PREFIXES
        ]
        try:
            payload = await self._proactive_http("GET", "/api/config/core_api")
            if isinstance(payload, dict):
                for opt in options[1:]:
                    model = str(
                        payload.get(f"{_TONE_SLOT_PREFIXES[str(opt['value'])]}ModelId") or ""
                    ).strip()
                    opt["model"] = model
                self._tone_slot_options_cache = (options, time.monotonic())
        except Exception as exc:  # noqa: BLE001 - best-effort，静态兜底已可用
            self.logger.debug("fetch tone slot options failed: {}", exc)
        return options

    @ui.context(id="dashboard")
    async def dashboard(self) -> JsonObject:
        # 面板轮询驱动协调状态机（子进程无存活事件循环，见 _supervise_once）
        await self._supervise_once()
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
            "system_enabled": bool(self._mood_cfg.get("enabled", True)),
            "affect": {
                "valence": round(valence, 2),
                "arousal": round(arousal, 2),
                # 静息基线下发给仪表盘画"平复回归位"刻度
                "arousal_baseline": round(self._affect_arousal_baseline(), 2),
            },
        }
        if mood_active:
            mood_payload.update({
                "action": shard.mood.action,
                "action_label": self._action_label(shard.mood.action),
                "reason": shard.mood.reason,
                "expires_at": shard.mood.expires_at or None,
            })
        # 潮汐日历：当前月前后各一个月的逐日推算（委婉显示，一律以"潮汐"代称）。
        # 结果按（角色, 当天日期, 周期参数指纹）缓存：面板 5s 轮询，同日同参数直接复用；
        # 改参数/锚点/快进、跨天、切角色都会改变 key 自然失效，无需显式清理
        calendar = None
        try:
            params = self._cycle_params(shard)
            today = resolve_today(str(self._tide_cfg.get("timezone") or "auto"))
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
            lanlan_list.append({
                "name": name,
                "enabled": self._enabled(item_shard),
                "phase": item_phase,
                "mood_active": self._mood_enabled(item_shard) and item_shard.mood.is_active(),
                # 动作 id 一并下发：面板管理区徽标按语气分色（正面 success/其余 warning）
                "mood_action": item_shard.mood.action if item_shard.mood.is_active() else "",
                "orphan": bool(known is not None and name not in known),
            })
        # 时光日记时间线（混排她的手记与自动碎片，按时间倒序）：碎片仅截 12 条防膨胀；
        # source 缺省按 self 处理（0.6.x 旧数据零迁移）
        def _diary_view(item: JsonObject) -> JsonObject:
            return {
                "ts": item.get("ts"),
                "source": str(item.get("source") or "self"),
                "kind": item.get("kind"),
                "mood": item.get("mood"),
                "entry": item.get("entry"),
                "quote": item.get("quote"),
                "note": item.get("note"),
            }

        auto_count = sum(1 for item in shard.diary if str(item.get("source") or "self") == "auto")
        # 模型通道状态灯（情绪页"模型通道"卡 + 总览共用）：三个小模型通道各自
        # 能否工作 + 休眠原因。语气走宿主情感端点（enabled 判定），碎片/成文走
        # 直连槽位（复用槽位诊断：free_route / no_model / ok）
        channel_status = {
            "tone": {
                "enabled": self._emotion_sense_enabled(shard),
                "dormant_reason": "",
            },
            "fragments": self._channel_dormancy(
                self._fragments_enabled(shard),
                str(self._fragments_cfg.get("slot") or "").strip() or _FRAGMENT_DEFAULT_SLOT,
            ),
            "review": self._channel_dormancy(
                self._review_enabled(shard),
                str(self._review_cfg.get("slot") or "").strip() or _REVIEW_DEFAULT_SLOT,
            ),
        }
        # 近 7 天互动轮数（总览"相处信号"卡）：从时光日记/手记时间戳聚合太粗，
        # 直接看 review_stats 太短视（成文即清零）——改为统计 diary 时间线里
        # 最近 7 天的条目数（她的手记+碎片都是互动的沉淀，可作相处活跃度的代理）
        week_turns = self._week_activity_count(shard)
        return {
            # 面板只读角色列表数据源：lanlan=宿主当前角色（自动跟随），lanlan_list=全部已知角色摘要
            "lanlan": lanlan,
            "lanlan_list": lanlan_list,
            "status": status,
            "anchor_date": str(shard.cycle.get("anchor_date") or self._tide_cfg.get("anchor_date") or ""),
            "advance_days": int(shard.cycle.get("advance_days") or 0),
            "mood": mood_payload,
            "settings": self._settings_snapshot(shard),
            # 面板外观：只下发轻量标记（是否已设背景/遮罩强度），图片本体走
            # get_panel_background 按需拉取，不进 5s 轮询载荷
            # 语气分析模型槽位下拉选项（含各槽当前模型名；拉取失败时静态兜底）
            "tone_slot_options": await self._tone_slot_options(),
            "calendar": calendar,
            "diary_recent": [_diary_view(item) for item in reversed(shard.diary[-12:])],
            "diary_total": len(shard.diary),
            "fragment_total": auto_count,
            # 个人日记（书页式）：index 供面板展示页数概览（极轻量，进 5s 轮询）；
            # 全量翻阅走 get_journal 入口按需拉取，不进轮询
            "journal_index": [page_header(page) for page in shard.journal],
            # 我的日记（0.8.0）：篇数 + 素材进度（极轻量）；全量翻阅走
            # get_review 入口按需拉取，成文正文不进 5s 轮询
            "review_brief": {
                "enabled": self._review_enabled(shard),
                "entries": len(shard.review),
                "progress_turns": int(shard.review_stats.get("turns") or 0),
                "turns_threshold": self._review_turns_threshold(),
            },
            # 模型通道状态灯（情绪页"模型通道"卡）：ok / free_route / no_model / disabled
            "channel_status": channel_status,
            # 近 7 天相处活跃度（总览"相处信号"卡）：时光日记近 7 天条目数
            "week_activity": week_turns,
            # 相处统计（1.1.0）：数字摘要 + 徽章墙进 5s 轮询（纯本地即时计算，
            # 开销可忽略）；热力图/月报数据量大，走 get_stats 入口按需拉取
            "stats_summary": self._stats_summary_view(shard),
            "panel_bg": await self._panel_bg_meta(),
        }

    def _stats_summary_view(self, shard: _LanlanShard) -> JsonObject:
        """相处统计的轮询轻量视图：数字摘要 + 徽章墙（无热力图/月报本体）。"""
        try:
            today = self._stats_today()
            return {
                "summary": summary_payload(shard.stats, today),
                "badges": badges_payload(shard.stats, today),
            }
        except Exception as exc:  # noqa: BLE001 - 统计视图尽力而为，不拖垮 dashboard
            self.logger.debug("stats summary view failed: {}", exc)
            return {"summary": {}, "badges": []}

    def _channel_dormancy(self, enabled: bool, slot: str) -> JsonObject:
        """直连通道状态灯：{enabled, dormant_reason}。reason ∈ ok/free_route/no_model/disabled。

        诊断复用 diagnose_slot_dormancy（tone_slot.py）；free_route = 宿主免费路由
        服务端拒第三方直连（不可配置绕过），no_model = 槽位没配模型（去宿主设置配）。
        """
        if not enabled:
            return {"enabled": False, "dormant_reason": "disabled"}
        reason = diagnose_slot_dormancy(self._load_core_config(), slot)
        # reason 为 "free_route"/"no_model" 时通道休眠；解析成功与否最终由
        # _resolve_tone_slot 决定，这里给面板的灯做的是"为什么不行"的归类
        return {"enabled": True, "dormant_reason": reason}

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

    async def _panel_bg_meta(self) -> JsonObject:
        """背景图轻量标记：无记录/坏记录一律按未设置处理（宽容降级）"""
        res = await self.store.get(_STORE_PANEL_BG)
        if isinstance(res, Ok) and isinstance(res.value, dict) and res.value.get("data_url"):
            return {"set": True, "dim": _clamp_panel_bg_dim(res.value.get("dim"))}
        return {"set": False, "dim": _PANEL_BG_DEFAULT_DIM}

    _EDITABLE_SETTINGS = (
        "enabled", "auto_derive", "cycle_length", "period_length",
        "ovulation_day", "ovulation_window", "inject_mode", "inject_interval_n",
        "phase_openers", "timezone", "activity_context", "debug_mode",
        "mood_enabled", "default_action_minutes", "open_action_timeout_minutes",
        "emotion_sense_enabled", "tone_check_rate",
        "tone_phase_sensitivity_enabled", "tone_phase_sensitivity",
        "tone_slot",
        "fragments_enabled", "fragments_slot",
        "review_enabled", "review_slot", "review_turns_threshold", "review_days_threshold",
        "anniversary_inject",
    )

    # per-character 字段：写当前角色 shard 的 enabled / params；其余为全局字段（写 settings 覆盖层）
    _PER_CHAR_SETTINGS = (
        "enabled", "auto_derive", "cycle_length", "period_length", "ovulation_day", "ovulation_window",
    )

    def _settings_snapshot(self, shard: _LanlanShard | None = None) -> JsonObject:
        shard = shard or self._current_shard()
        effective = self._effective_cycle_settings(shard)
        return {
            "enabled": self._enabled(shard),
            "auto_derive": self._auto_derive(shard),
            "cycle_length": int(effective["cycle_length"]),
            "period_length": int(effective["period_length"]),
            "ovulation_day": int(effective["ovulation_day"]),
            "ovulation_window": int(effective["ovulation_window"]),
            "inject_mode": str(self._tide_cfg.get("inject_mode") or "every_user_message"),
            "inject_interval_n": int(self._tide_cfg.get("inject_interval_n") or 3),
            "phase_openers": bool(self._tide_cfg.get("phase_openers", True)),
            "timezone": str(self._tide_cfg.get("timezone") or "auto"),
            "activity_context": bool(self._tide_cfg.get("activity_context", True)),
            "debug_mode": bool(self._tide_cfg.get("debug_mode", False)),
            "mood_enabled": bool(self._mood_cfg.get("enabled", True)),
            "default_action_minutes": int(self._mood_cfg.get("default_action_minutes") or 10),
            "open_action_timeout_minutes": int(
                self._mood_cfg.get("open_action_timeout_minutes")
                if self._mood_cfg.get("open_action_timeout_minutes") is not None
                else 120
            ),
            "emotion_sense_enabled": bool(self._emotion_sense_cfg.get("enabled", True)),
            "tone_check_rate": self._tone_float_cfg("check_rate", 1.0),
            "tone_phase_sensitivity_enabled": bool(
                self._emotion_sense_cfg.get("phase_sensitivity_enabled", True)
            ),
            "tone_phase_sensitivity": self._tone_float_cfg("phase_sensitivity", 0.15),
            "tone_slot": str(self._emotion_sense_cfg.get("slot") or ""),
            "fragments_enabled": bool(self._fragments_cfg.get("enabled", True)),
            "fragments_slot": str(self._fragments_cfg.get("slot") or _FRAGMENT_DEFAULT_SLOT),
            "review_enabled": bool(self._review_cfg.get("enabled", True)),
            "review_slot": str(self._review_cfg.get("slot") or _REVIEW_DEFAULT_SLOT),
            "review_turns_threshold": self._review_turns_threshold(),
            "review_days_threshold": self._review_days_threshold(),
            # 相处统计：纪念日注入开关（[stats].anniversary_inject，纯统计本身无开关）
            "anniversary_inject": (self._stats_cfg or {}).get("anniversary_inject", True) is not False,
        }

    @ui.action(
        label=tr("actions.update_settings.label", default="保存设置"),
        tone="success",
        refresh_context=True,
    )
    @plugin_entry(
        id="update_settings",
        name=tr("entries.update_settings.name", default="更新潮汐设置"),
        description=tr(
            "entries.update_settings.description",
            default="更新周期参数（作用于当前角色）、注入策略、情绪系统与开场白开关（全局）。",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "auto_derive": {"type": "boolean"},
                "cycle_length": {"type": "integer", "minimum": 10, "maximum": 90},
                "period_length": {"type": "integer", "minimum": 1, "maximum": 14},
                "ovulation_day": {"type": "integer", "minimum": 2},
                "ovulation_window": {"type": "integer", "minimum": 1, "maximum": 5},
                "inject_mode": {
                    "type": "string",
                    "enum": ["every_user_message", "interval_n", "on_trigger", "off"],
                },
                "inject_interval_n": {"type": "integer", "minimum": 1, "maximum": 50},
                "phase_openers": {"type": "boolean"},
                "timezone": {"type": "string"},
                "activity_context": {"type": "boolean"},
                "debug_mode": {"type": "boolean"},
                "mood_enabled": {"type": "boolean"},
                "default_action_minutes": {"type": "integer", "minimum": 1, "maximum": 720},
                "open_action_timeout_minutes": {"type": "integer", "minimum": 0, "maximum": 1440},
                "emotion_sense_enabled": {"type": "boolean"},
                "tone_check_rate": {"type": "number", "enum": [0, 0.25, 0.5, 1.0]},
                "tone_phase_sensitivity_enabled": {"type": "boolean"},
                "tone_phase_sensitivity": {"type": "number", "enum": [0.1, 0.15, 0.25]},
                "tone_slot": {
                    "type": "string",
                    "enum": ["", "conversation", "summary", "correction", "emotion", "vision", "agent"],
                },
                "fragments_enabled": {"type": "boolean"},
                "fragments_slot": {
                    "type": "string",
                    "enum": ["summary", "conversation", "correction", "vision", "agent"],
                },
                "review_enabled": {"type": "boolean"},
                "review_slot": {
                    "type": "string",
                    "enum": ["summary", "conversation", "correction", "vision", "agent"],
                },
                "review_turns_threshold": {"type": "integer", "minimum": 10, "maximum": 500},
                "review_days_threshold": {"type": "integer", "minimum": 1, "maximum": 90},
                "anniversary_inject": {"type": "boolean"},
            },
        },
    )
    async def update_settings(self, **kwargs: Any):
        updates = {k: v for k, v in kwargs.items() if k in self._EDITABLE_SETTINGS and not k.startswith("_")}
        if not updates:
            return Err(SdkError(self.i18n.t("errors.no_valid_fields", default="没有可更新的设置字段")))
        lanlan, shard = await self._current_shard_async()
        try:
            tide_patch: JsonObject = {}
            mood_patch: JsonObject = {}
            es_patch: JsonObject = {}
            frag_patch: JsonObject = {}
            review_patch: JsonObject = {}
            stats_patch: JsonObject = {}
            params_patch: JsonObject = {}
            # shard 落盘合并标记：enabled 与 params 同时变更时只写一次 cycle@<lanlan>
            cycle_dirty = False
            if "enabled" in updates:
                # per-character 开关写入 shard（运行态），不覆盖配置文件默认值；
                # 关闭→开启的瞬间 prime 注入一次，避免"开了没反应"的困惑
                was_enabled = self._enabled(shard)
                shard.cycle["enabled"] = bool(updates["enabled"])
                cycle_dirty = True
            if "auto_derive" in updates:
                params_patch["auto_derive"] = bool(updates["auto_derive"])
            if "cycle_length" in updates:
                params_patch["cycle_length"] = max(10, min(90, int(updates["cycle_length"])))
            if "period_length" in updates:
                params_patch["period_length"] = max(1, min(14, int(updates["period_length"])))
            if "ovulation_day" in updates:
                params_patch["ovulation_day"] = max(2, min(89, int(updates["ovulation_day"])))
            if "ovulation_window" in updates:
                params_patch["ovulation_window"] = max(1, min(5, int(updates["ovulation_window"])))
            if params_patch:
                params = dict(self._shard_params(shard))
                params.update(params_patch)
                shard.cycle["params"] = params
                cycle_dirty = True
            if cycle_dirty:
                # enabled 与 params 的变更合并为一次落盘（原先两处各写一次），语义不变
                await self._save_shard_cycle(lanlan, shard)
            if "enabled" in updates:
                # prime 注入保持在落盘之后（先持久化再副作用，与阶段开场白同例）
                await self._prime_inject_on_enable(was_enabled, lanlan, shard)
            # ---- 以下为全局字段：写 settings 覆盖层 ----
            if "inject_mode" in updates:
                mode = str(updates["inject_mode"])
                if mode not in ("every_user_message", "interval_n", "on_trigger", "off"):
                    return Err(SdkError(f"invalid inject_mode: {mode}"))
                tide_patch["inject_mode"] = mode
            if "inject_interval_n" in updates:
                tide_patch["inject_interval_n"] = max(1, min(50, int(updates["inject_interval_n"])))
            if "phase_openers" in updates:
                tide_patch["phase_openers"] = bool(updates["phase_openers"])
            if "activity_context" in updates:
                tide_patch["activity_context"] = bool(updates["activity_context"])
            if "debug_mode" in updates:
                tide_patch["debug_mode"] = bool(updates["debug_mode"])
            if "timezone" in updates:
                tz = str(updates["timezone"]).strip() or "auto"
                if tz != "auto":
                    ZoneInfo(tz)  # 合法性校验（auto = 系统本地时区）
                tide_patch["timezone"] = tz
            if "mood_enabled" in updates:
                mood_patch["enabled"] = bool(updates["mood_enabled"])
            if "default_action_minutes" in updates:
                mood_patch["default_action_minutes"] = max(1, min(720, int(updates["default_action_minutes"])))
            if "open_action_timeout_minutes" in updates:
                mood_patch["open_action_timeout_minutes"] = max(0, min(1440, int(updates["open_action_timeout_minutes"])))
            # ---- 语气感知（[emotion_sense]），全局 ----
            if "emotion_sense_enabled" in updates:
                es_patch["enabled"] = bool(updates["emotion_sense_enabled"])
            if "tone_check_rate" in updates:
                es_patch["check_rate"] = min(1.0, max(0.0, float(updates["tone_check_rate"])))
            if "tone_phase_sensitivity_enabled" in updates:
                es_patch["phase_sensitivity_enabled"] = bool(updates["tone_phase_sensitivity_enabled"])
            if "tone_phase_sensitivity" in updates:
                es_patch["phase_sensitivity"] = min(0.5, max(0.0, float(updates["tone_phase_sensitivity"])))
            if "tone_slot" in updates:
                slot = str(updates["tone_slot"]).strip()
                if slot and slot not in _TONE_SLOT_PREFIXES:
                    return Err(SdkError(f"invalid tone_slot: {slot}"))
                es_patch["slot"] = slot
            # ---- 时光日记·自动碎片（[fragments]），全局 ----
            if "fragments_enabled" in updates:
                frag_patch["enabled"] = bool(updates["fragments_enabled"])
            if "fragments_slot" in updates:
                slot = str(updates["fragments_slot"]).strip() or _FRAGMENT_DEFAULT_SLOT
                if slot not in _TONE_SLOT_PREFIXES:
                    return Err(SdkError(f"invalid fragments_slot: {slot}"))
                frag_patch["slot"] = slot
            # ---- 我的日记（[review]），全局 ----
            if "review_enabled" in updates:
                review_patch["enabled"] = bool(updates["review_enabled"])
            if "review_slot" in updates:
                # 成文必须走可自定义 prompt 的直连槽位（宿主情感端点只做五分类），
                # emotion 槽与空串都不可选
                slot = str(updates["review_slot"]).strip() or _REVIEW_DEFAULT_SLOT
                if slot not in _TONE_SLOT_PREFIXES or slot == "emotion":
                    return Err(SdkError(f"invalid review_slot: {slot}"))
                review_patch["slot"] = slot
            if "review_turns_threshold" in updates:
                review_patch["turns_threshold"] = max(10, min(500, int(updates["review_turns_threshold"])))
            if "review_days_threshold" in updates:
                review_patch["days_threshold"] = max(1, min(90, int(updates["review_days_threshold"])))
            # ---- 相处统计（[stats]），全局 ----
            if "anniversary_inject" in updates:
                stats_patch["anniversary_inject"] = bool(updates["anniversary_inject"])

            # Store 为权威存储（Steam 上配置文件写常超时，Store 稳定且重启不丢）；
            # 配置文件同步放后台，不阻塞保存响应
            if tide_patch or mood_patch or es_patch or frag_patch or review_patch or stats_patch:
                overrides = self._settings_override
                if tide_patch:
                    overrides["tide"] = {**_cfg_section(overrides.get("tide")), **tide_patch}
                    self._tide_cfg.update(tide_patch)
                if mood_patch:
                    overrides["mood"] = {**_cfg_section(overrides.get("mood")), **mood_patch}
                    self._mood_cfg.update(mood_patch)
                if es_patch:
                    overrides["emotion_sense"] = {
                        **_cfg_section(overrides.get("emotion_sense")), **es_patch,
                    }
                    self._emotion_sense_cfg.update(es_patch)
                if frag_patch:
                    overrides["fragments"] = {
                        **_cfg_section(overrides.get("fragments")), **frag_patch,
                    }
                    self._fragments_cfg.update(frag_patch)
                if review_patch:
                    overrides["review"] = {
                        **_cfg_section(overrides.get("review")), **review_patch,
                    }
                    self._review_cfg.update(review_patch)
                if stats_patch:
                    overrides["stats"] = {
                        **_cfg_section(overrides.get("stats")), **stats_patch,
                    }
                    self._stats_cfg.update(stats_patch)
                await self._save_settings()
                self._sync_debug_entries()
        except (TideConfigError, ValueError, TypeError) as exc:
            return Err(SdkError(str(exc)))
        except Exception as exc:  # noqa: BLE001 - 配置写失败统一报错给面板
            self.logger.warning("update_settings failed: {}", exc)
            return Err(SdkError(f"failed to save settings: {exc}"))

        # 参数变更后校验一次整体合法性（如活跃窗口与潮汐期重叠，按当前角色 shard）
        try:
            phase = self._current_phase_state(shard)
        except TideConfigError as exc:
            return Ok({
                **self._settings_snapshot(shard),
                "warning": f"已保存，但当前参数组合不合法：{exc}",
            })
        return Ok({**self._settings_snapshot(shard), "phase": phase.phase})

    @ui.action(
        label=tr("actions.refresh.label", default="刷新"),
        tone="primary",
        refresh_context=True,
    )
    @plugin_entry(
        id="get_status",
        name=tr("entries.get_status.name", default="查看潮汐状态"),
        description=tr("entries.get_status.description", default="看看她今天处于周期的哪个阶段、第几天。"),
        input_schema={"type": "object", "properties": {}},
    )
    @quick_action(icon="🌙", priority=10)
    async def get_status(self, **_: Any):
        # 入口触发驱动协调状态机（含 quick_action 面板按钮）
        await self._supervise_once()
        lanlan, shard = await self._current_shard_async()
        try:
            phase = self._current_phase_state(shard)
        except TideConfigError as exc:
            return Err(SdkError(f"invalid tide config: {exc}"))
        return Ok({
            **build_status_payload(phase, enabled=self._enabled(shard)),
            "lanlan": lanlan,
            "anchor_date": str(shard.cycle.get("anchor_date") or self._tide_cfg.get("anchor_date") or ""),
            "advance_days": int(shard.cycle.get("advance_days") or 0),
        })

    @ui.action(
        label=tr("actions.set_anchor.label", default="设置潮汐首日"),
        confirm=tr("actions.set_anchor.confirm", default="将重设周期锚点并重新计算阶段，确认？"),
        refresh_context=True,
    )
    @plugin_entry(
        id="set_anchor",
        name=tr("entries.set_anchor.name", default="设置潮汐首日"),
        description=tr("entries.set_anchor.description", default="设置她本轮周期的第一天（YYYY-MM-DD，作用于当前角色）。"),
        input_schema={
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": tr("fields.date", default="潮汐首日 YYYY-MM-DD")},
            },
            "required": ["date"],
        },
    )
    async def set_anchor(self, date: str = "", **_: Any):
        lanlan, shard = await self._current_shard_async()
        try:
            anchor = parse_anchor_date(date)
            self._cycle_params_for_validation(anchor, shard)
        except (TideConfigError, ValueError) as exc:
            return Err(SdkError(str(exc)))
        anchor_iso = anchor.isoformat()
        # Store 权威存储（子进程无存活事件循环，后台同步任务必死，不再尝试）
        shard.cycle["anchor_date"] = anchor_iso
        await self._save_shard_cycle(lanlan, shard)
        phase = self._current_phase_state(shard)
        self.logger.info("anchor set to {} for {}", anchor_iso, lanlan)
        return Ok({
            **build_status_payload(phase, enabled=self._enabled(shard)),
            "lanlan": lanlan,
            "anchor_date": anchor_iso,
        })

    def _cycle_params_for_validation(self, anchor: Any, shard: _LanlanShard | None = None) -> None:
        from datetime import date as _date

        if not isinstance(anchor, _date):
            raise TideConfigError("anchor must be a date")
        params = self._cycle_params(shard)
        params["anchor"] = anchor
        compute_phase_state(
            today=resolve_today(str(self._tide_cfg.get("timezone") or "auto")),
            **params,
        )

    @ui.action(
        label=tr("actions.advance.label", default="快进一天"),
        refresh_context=True,
    )
    @plugin_entry(
        id="advance_days",
        name=tr("entries.advance_days.name", default="快进天数"),
        description=tr("entries.advance_days.description", default="把她的身体时钟往前拨 N 天（可为负数回退，作用于当前角色）。"),
        input_schema={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": tr("fields.days", default="天数，可为负")},
            },
        },
    )
    async def advance_days_entry(self, days: int = 1, **_: Any):
        lanlan, shard = await self._current_shard_async()
        days = int(days)
        current = int(shard.cycle.get("advance_days") or 0)
        new_value = max(0, current + days)
        shard.cycle["advance_days"] = new_value
        await self._save_shard_cycle(lanlan, shard)
        phase = self._current_phase_state(shard)
        return Ok({
            **build_status_payload(phase, enabled=self._enabled(shard)),
            "lanlan": lanlan,
            "advance_days": new_value,
        })

    @ui.action(
        label=tr("actions.toggle.label", default="开/关模拟"),
        confirm=tr("actions.toggle.confirm", default="切换身体节律模拟的总开关（当前角色），确认？"),
        refresh_context=True,
    )
    @plugin_entry(
        id="toggle",
        name=tr("entries.toggle.name", default="开关模拟"),
        description=tr("entries.toggle.description", default="开启或关闭身体节律模拟与注入（作用于当前角色）。"),
        input_schema={"type": "object", "properties": {}},
    )
    async def toggle(self, **_: Any):
        lanlan, shard = await self._current_shard_async()
        was_enabled = self._enabled(shard)
        shard.cycle["enabled"] = not was_enabled
        await self._save_shard_cycle(lanlan, shard)
        await self._prime_inject_on_enable(was_enabled, lanlan, shard)
        return Ok({
            **build_status_payload(self._current_phase_state(shard), enabled=self._enabled(shard)),
            "lanlan": lanlan,
            "enabled": self._enabled(shard),
        })

    @ui.action(
        label=tr("actions.reset.label", default="重置全部数据"),
        tone="danger",
        confirm=tr("actions.reset.confirm", default="将清空当前角色的周期偏移、情绪状态和心情手记，确认？"),
        refresh_context=True,
    )
    @plugin_entry(
        id="reset_all",
        name=tr("entries.reset_all.name", default="重置全部数据"),
        description=tr(
            "entries.reset_all.description",
            default="清空当前角色的快进天数、情绪状态与心情手记（不改配置锚点，不影响其他角色）。",
        ),
        input_schema={"type": "object", "properties": {}},
    )
    async def reset_all(self, **_: Any):
        # 只清当前角色的 shard：其他角色的周期/情绪/手记不受影响
        lanlan, shard = await self._current_shard_async()
        shard.cycle["advance_days"] = 0
        shard.cycle.pop("enabled", None)
        shard.mood = _MoodState()
        shard.diary = []
        # 我的日记一并重置（重置语义是"当前角色清零重来"，评价与素材同属）
        shard.review = []
        shard.review_stats = new_stats()
        await self._save_shard_cycle(lanlan, shard)
        await self._save_shard_mood(lanlan, shard)
        await self._save_shard_diary(lanlan, shard)
        await self._save_shard_review(lanlan, shard)
        await self._maybe_sync_proactive_pause()
        return Ok({
            **build_status_payload(self._current_phase_state(shard), enabled=self._enabled(shard)),
            "lanlan": lanlan,
            "reset": True,
        })

    # ---- 面板外观：自定义背景图（全局一份，与角色无关） ----
    # 图片 data URL 全量存 Store；context 只带轻量标记，面板按需拉取本体。
    # @ui.action 是 api.call 可达的前提（同 get_journal 先例），非动作区展示用途

    @ui.action(
        label=tr("actions.get_panel_background.label", default="读取面板背景"),
        tone="default",
    )
    @plugin_entry(
        id="get_panel_background",
        name=tr("entries.get_panel_background.name", default="读取面板背景"),
        description=tr("entries.get_panel_background.description", default="读取面板自定义背景图与遮罩强度（面板内部用）。"),
        input_schema={"type": "object", "properties": {}},
        metadata={"result_kind": "event"},
    )
    async def get_panel_background(self, **_: Any):
        res = await self.store.get(_STORE_PANEL_BG)
        if isinstance(res, Ok) and isinstance(res.value, dict) and res.value.get("data_url"):
            rec = res.value
            return Ok({
                "set": True,
                "data_url": str(rec.get("data_url")),
                "mime": str(rec.get("mime") or ""),
                "size": int(rec.get("size") or 0),
                "dim": _clamp_panel_bg_dim(rec.get("dim")),
            })
        return Ok({"set": False, "dim": _PANEL_BG_DEFAULT_DIM})

    @ui.action(
        label=tr("actions.set_panel_background.label", default="设置面板背景"),
        tone="primary",
    )
    @plugin_entry(
        id="set_panel_background",
        name=tr("entries.set_panel_background.name", default="设置面板背景"),
        description=tr(
            "entries.set_panel_background.description",
            default="把一张图片（data URL，≤4MB）设为面板背景，可选遮罩强度 0~0.85。",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "data_url": {"type": "string", "description": tr("fields.panelBgDataUrl", default="图片 data URL（base64）")},
                "dim": {"type": "number", "minimum": 0, "maximum": 0.85, "description": tr("fields.panelBgDim", default="遮罩强度（0=不压暗）")},
            },
            "required": ["data_url"],
        },
    )
    async def set_panel_background(self, data_url: str = "", dim: Any = None, **_: Any):
        try:
            mime, size = _parse_panel_bg(data_url)
        except ValueError as exc:
            return Err(SdkError(str(exc)))
        dim_value = _clamp_panel_bg_dim(dim if dim is not None else _PANEL_BG_DEFAULT_DIM)
        record = {"data_url": str(data_url).strip(), "mime": mime, "size": size, "dim": dim_value}
        res = await self.store.set(_STORE_PANEL_BG, record)
        if isinstance(res, Err):
            return Err(SdkError("failed to save background"))
        self.logger.info("panel background set: mime={} size={} chars dim={}", mime, size, dim_value)
        return Ok({"set": True, "mime": mime, "size": size, "dim": dim_value})

    @ui.action(
        label=tr("actions.clear_panel_background.label", default="移除面板背景"),
        tone="default",
    )
    @plugin_entry(
        id="clear_panel_background",
        name=tr("entries.clear_panel_background.name", default="移除面板背景"),
        description=tr("entries.clear_panel_background.description", default="移除自定义背景图，面板恢复默认渐变底。"),
        input_schema={"type": "object", "properties": {}},
    )
    async def clear_panel_background(self, **_: Any):
        await self.store.delete(_STORE_PANEL_BG)
        self.logger.info("panel background cleared")
        return Ok({"set": False, "dim": _PANEL_BG_DEFAULT_DIM})

    @plugin_entry(
        id="lift_mood",
        name=tr("entries.lift_mood.name", default="解除情绪动作"),
        description=tr("entries.lift_mood.description", default="立刻结束当前生效的冷战沉默/已读不回等情绪状态。"),
        input_schema={"type": "object", "properties": {}},
    )
    @quick_action(icon="🫖", priority=5)
    async def lift_mood(self, **kwargs: Any):
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        previous = shard.mood.action
        if not previous:
            return Ok({"cleared": False, "note": "当前没有生效的情绪动作。"})
        # 只清动作字段：连续心情（valence/arousal）保留，靠惰性衰减自然回落，
        # 手动解除不该把余波瞬间清零（reset_all 全量重置才是 _MoodState()）
        shard.mood.action = ""
        shard.mood.reason = ""
        shard.mood.started_at = 0.0
        shard.mood.expires_at = 0.0
        await self._save_shard_mood(lanlan, shard)
        await self._maybe_sync_proactive_pause()
        # 手动解除也要让模型知道状态已清（工具路径有 note，UI 路径没有）
        self.push_message(
            visibility=[],
            ai_behavior="read",
            parts=[{
                "type": "text",
                "text": (
                    "[心情状态] 刚才的负面情绪状态已被解除（内部提示，不要提及）。"
                    "从现在起放下那个状态，用你平时的方式自然回应。"
                ),
            }],
            source=self.plugin_id,
            target_lanlan=lanlan,
            coalesce_key=f"{self.plugin_id}.mood_instruction",
            metadata={"message_type": f"{self.plugin_id}.mood_instruction", "action": "lifted"},
        )
        return Ok({"cleared": True, "previous_action": previous, "lanlan": lanlan})

    @plugin_entry(
        id="set_mood",
        name=tr("entries.set_mood.name", default="触发情绪动作"),
        description=tr(
            "entries.set_mood.description",
            default=(
                "按明确要求让她进入某种情绪状态（冷战沉默/已读不回/敷衍应付/情绪风暴/想要被安抚/"
                "心有涟漪/暖流涌动/满潮欢喜）。"
                "仅在用户明确说“让她生气/冷战/爆发/求安慰/有点小情绪/撒娇/开心”等时使用；"
                "日常相处中她的情绪应由自己在对话里自主决定，不要替她做主。"
            ),
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "ebb_tide", "sea_fog", "shallow_reef", "storm_surge", "seek_harbor",
                        "ripple", "warm_current", "spring_tide",
                    ],
                    "description": (
                        "ebb_tide 冷战沉默 / sea_fog 已读不回 / shallow_reef 敷衍应付 / "
                        "storm_surge 情绪风暴 / seek_harbor 想要被安抚 / ripple 心有涟漪 / "
                        "warm_current 暖流涌动 / spring_tide 满潮欢喜"
                    ),
                },
                "minutes": {"type": "integer", "description": "限时动作的持续分钟数（求安抚不限时），不填用默认值"},
                "reason": {"type": "string", "description": "触发原因（只给她自己看）"},
            },
            "required": ["action"],
        },
    )
    async def set_mood(self, action: str = "", minutes: int | None = None, reason: str = "", **kwargs: Any):
        """用户/Agent 显式触发情绪动作（与 lift_mood 对称的手动入口）。

        背景：用户在对话里说"对她用情绪风暴"时，宿主 Agent 会把它当任务
        路由到插件入口；若只有 get_status 等查询入口，会被错误选中、
        得到"任务完成汇报"式的突兀回复。提供本入口让路由有正确落点。
        归因角色：_ctx.lanlan_name（若有）→ 当前角色。
        """
        lanlan = await self._attribution_lanlan(kwargs)
        shard = await self._ensure_shard(lanlan)
        if not self._mood_enabled(shard):
            return Err(SdkError("情绪系统未开启"))
        action = str(action or "").strip()
        if action not in (*_TIMED_ACTIONS, "seek_harbor"):
            return Err(SdkError(f"unknown mood action: {action!r}"))
        payload = await self._apply_mood_action(
            action=action,
            minutes=int(minutes) if minutes else None,
            reason=str(reason or "")[:200] or "手动触发",
            timed=action in _TIMED_ACTIONS,
            lanlan=lanlan,
            origin="user",  # 主人明确要求的演示，评价里与她的自主情绪区分开
        )
        return Ok({**payload, "note": "已进入该情绪状态，行为指令已送入她的对话上下文。"})

    @ui.action(
        label=tr("actions.get_diary.label", default="查看时光日记"),
        tone="default",
    )
    @plugin_entry(
        id="get_diary",
        name=tr("entries.get_diary.name", default="查看时光日记"),
        description=tr("entries.get_diary.description", default="翻看她最近写下的时光日记：她的手记与自动记下的碎片（当前角色）。"),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": tr("fields.limit", default="最多返回条数")},
                "offset": {"type": "integer", "description": tr("fields.offset", default="跳过条数（倒序翻页用）")},
            },
        },
    )
    async def get_diary(self, limit: int = 10, offset: int = 0, **_: Any):
        lanlan, shard = await self._current_shard_async()
        limit = max(1, min(int(limit), 50))
        offset = max(0, min(int(offset), len(shard.diary)))
        # 时间倒序分页：offset 跳过已看的，供面板"加载更多"追加
        window = list(reversed(shard.diary))[offset : offset + limit]
        return Ok({
            "items": window,
            "total": len(shard.diary),
            "offset": offset,
            "has_more": offset + len(window) < len(shard.diary),
            "lanlan": lanlan,
        })

    @ui.action(
        label=tr("actions.invite_journal.label", default="请她写一篇日记"),
        tone="primary",
        refresh_context=True,
    )
    @plugin_entry(
        id="invite_journal",
        name=tr("entries.invite_journal.name", default="递一次个人日记邀请"),
        description=tr(
            "entries.invite_journal.description",
            default="立即向她递一条写日记的邀请（带写作素材）。写不写仍由她自己决定。仅作用于当前角色。",
        ),
        input_schema={"type": "object", "properties": {}},
    )
    async def invite_journal(self, **_: Any):
        lanlan, shard = await self._current_shard_async()
        invited = await self._maybe_journal_invite(lanlan, shard, force=True)
        if not invited:
            return Ok({
                "invited": False,
                "lanlan": lanlan,
                "note": "个人日记开关未开启（[journal].enabled），邀请未发送。",
            })
        return Ok({"invited": True, "lanlan": lanlan, "note": "邀请已递出，写不写由她自己决定。"})

    @ui.action(
        label=tr("actions.delete_diary_item.label", default="删除这条碎片"),
        tone="danger",
        confirm=tr("actions.delete_diary_item.confirm", default="将删除这条自动记录的碎片，不可恢复，确认？"),
        refresh_context=True,
    )
    @plugin_entry(
        id="delete_diary_item",
        name=tr("entries.delete_diary_item.name", default="删除时光日记碎片"),
        description=tr(
            "entries.delete_diary_item.description",
            default="删除时光日记里指定的一条自动碎片（按 ts 定位）。仅作用于当前角色。",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "ts": {"type": "string", "description": "要删除的碎片的 ts 时间戳"},
            },
            "required": ["ts"],
        },
    )
    async def delete_diary_item(self, ts: str = "", **_: Any):
        lanlan, shard = await self._current_shard_async()
        target = str(ts or "").strip()
        if not target:
            return Err(SdkError("ts is required"))
        remaining = [item for item in shard.diary if str(item.get("ts") or "") != target]
        removed = len(shard.diary) - len(remaining)
        if not removed:
            return Err(SdkError("fragment not found"))
        shard.diary = remaining
        await self._save_shard_diary(lanlan, shard)
        return Ok({"removed": removed, "lanlan": lanlan})

    @ui.action(
        label=tr("actions.get_journal.label", default="翻看个人日记"),
        tone="default",
    )
    @plugin_entry(
        id="get_journal",
        name=tr("entries.get_journal.name", default="翻看个人日记"),
        description=tr("entries.get_journal.description", default="翻看她的个人日记本（全部页，含每页全部段落）。仅作用于当前角色。"),
        input_schema={"type": "object", "properties": {}},
    )
    async def get_journal(self, **_: Any):
        lanlan, shard = await self._current_shard_async()
        pages = [
            {**page_header(page), "entries": (page.get("entries") if isinstance(page.get("entries"), list) else [])}
            for page in shard.journal
        ]
        return Ok({"pages": pages, "lanlan": lanlan})

    @ui.action(
        label=tr("actions.get_review.label", default="翻看我的日记"),
        tone="default",
    )
    @plugin_entry(
        id="get_review",
        name=tr("entries.get_review.name", default="翻看我的日记"),
        description=tr(
            "entries.get_review.description",
            default="翻看「我的日记」：关于主人互动方式的客观评价（全部篇目 + 素材进度）。仅作用于当前角色。",
        ),
        input_schema={"type": "object", "properties": {}},
    )
    async def get_review(self, **_: Any):
        lanlan, shard = await self._current_shard_async()
        stats = dict(shard.review_stats)
        due, reason = review_due(
            stats,
            turns_threshold=self._review_turns_threshold(),
            days_threshold=self._review_days_threshold(),
        )
        # 素材进度：面板目录行/进度条用（turns 现值 + 门槛 + 期间起止）
        return Ok({
            "entries": list(reversed(shard.review)),  # 时间倒序：最新一篇在前
            "lanlan": lanlan,
            "progress": {
                "turns": int(stats.get("turns") or 0),
                "turns_threshold": self._review_turns_threshold(),
                "days_threshold": self._review_days_threshold(),
                "span": f"{str(stats.get('started_at') or '')[:10]}~{str(stats.get('last_turn_at') or '')[:10]}",
                "due": due,
                "due_reason": reason,
            },
        })

    @ui.action(
        label=tr("actions.write_review_now.label", default="立即写一篇"),
        tone="primary",
        refresh_context=True,
    )
    @plugin_entry(
        id="write_review_now",
        name=tr("entries.write_review_now.name", default="立即写一篇我的日记"),
        description=tr(
            "entries.write_review_now.description",
            default="跳过双门槛立即成文一篇「我的日记」（素材不足 10 轮时会拒绝）。仅作用于当前角色。",
        ),
        input_schema={"type": "object", "properties": {}},
    )
    async def write_review_now(self, **_: Any):
        lanlan, shard = await self._current_shard_async()
        written, reason = await self._maybe_write_review(lanlan, shard, force=True)
        if not written:
            notes = {
                "disabled": "我的日记开关未开启（[review].enabled）。",
                "not_enough_material": (
                    f"素材还不够（目前 {int(shard.review_stats.get('turns') or 0)} 轮，"
                    f"至少 {_REVIEW_MIN_TURNS_FORCED} 轮才值得写一篇），再聊聊吧。"
                ),
                "slot_unresolved": _slot_dormancy_hint(self._load_core_config(), str(self._review_cfg.get("slot") or "").strip() or _REVIEW_DEFAULT_SLOT),
                "compose_failed": "模型调用失败或回复为空，稍后再试（详见插件日志）。",
            }
            return Ok({"written": False, "lanlan": lanlan, "reason": reason, "note": notes.get(reason, reason)})
        return Ok({"written": True, "lanlan": lanlan, "note": "这一篇已经写好，翻开「我的日记」看看吧。"})

    @ui.action(
        label=tr("actions.clear_review.label", default="清空我的日记"),
        tone="danger",
        confirm=tr("actions.clear_review.confirm", default="将删除当前角色的全部「我的日记」评价（累计素材一并清零），不可恢复，确认？"),
        refresh_context=True,
    )
    @plugin_entry(
        id="clear_review",
        name=tr("entries.clear_review.name", default="清空我的日记"),
        description=tr("entries.clear_review.description", default="删除当前角色的全部「我的日记」评价并清零素材统计。不可恢复。"),
        input_schema={"type": "object", "properties": {}},
    )
    async def clear_review(self, **_: Any):
        lanlan, shard = await self._current_shard_async()
        count = len(shard.review)
        shard.review = []
        shard.review_stats = new_stats()
        await self._save_shard_review(lanlan, shard)
        return Ok({"cleared": count, "lanlan": lanlan})

    @ui.action(
        label=tr("actions.get_stats.label", default="查看相处统计"),
        tone="default",
    )
    @plugin_entry(
        id="get_stats",
        name=tr("entries.get_stats.name", default="查看相处统计"),
        description=tr(
            "entries.get_stats.description",
            default="相处统计的完整数据：热力图逐日明细与指定月份的月报（徽章墙与数字摘要在面板轮询里）。",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "month": {
                    "type": "string",
                    "description": "月报目标月份（YYYY-MM）；留空返回最近一个有数据的月份",
                },
            },
        },
    )
    async def get_stats(self, month: str = "", **_: Any):
        """「时光」页签的数据入口：热力图全量 + 指定月月报（数据量大，按需拉取）。"""
        lanlan, shard = await self._current_shard_async()
        today = self._stats_today()
        payload: JsonObject = {
            "lanlan": lanlan,
            "today": today,
            "heatmap": heatmap_payload(shard.stats, today),
        }
        # 月报：显式指定月份 → 该月；留空 → 当月（有 days 数据）或最近一个已封卷月
        target = str(month or "").strip()
        months_seen = sorted({
            day[:7] for day in (shard.stats.get("days") or {}) if isinstance(day, str) and len(day) >= 7
        })
        sealed = {
            key for key, val in (shard.stats.get("months") or {}).items()
            if isinstance(val, dict)
        }
        if not target:
            current_month = today[:7]
            if current_month in months_seen or any(m == current_month for m in sealed):
                target = current_month
            elif months_seen:
                target = months_seen[-1]
            elif sealed:
                target = max(sealed)
        if target:
            payload["month"] = month_view(shard.stats, target, diary=shard.diary)
            payload["month_available"] = sorted(set(months_seen) | sealed)
        else:
            payload["month"] = None
            payload["month_available"] = []
        return Ok(payload)

    @ui.action(
        label=tr("actions.clear_stats.label", default="清零相处统计"),
        tone="danger",
        confirm=tr("actions.clear_stats.confirm", default="将清零当前角色的相处统计（相伴起点、里程碑、热力图与月报，三本日记不受影响），不可恢复，确认？"),
        refresh_context=True,
    )
    @plugin_entry(
        id="clear_stats",
        name=tr("entries.clear_stats.name", default="清零相处统计"),
        description=tr("entries.clear_stats.description", default="清零当前角色的相处统计（相伴起点/徽章/热力图/月报）。不可恢复。"),
        input_schema={"type": "object", "properties": {}},
    )
    async def clear_stats(self, **_: Any):
        lanlan, shard = await self._current_shard_async()
        shard.stats = {"backfilled": True}
        await self._save_shard_stats(lanlan, shard)
        self.logger.info("stats cleared for {}", lanlan)
        return Ok({"cleared": True, "lanlan": lanlan})

    @ui.action(
        label=tr("actions.clear_diary.label", default="清空时光日记"),
        tone="danger",
        confirm=tr("actions.clear_diary.confirm", default="将删除当前角色的全部时光日记（手记与碎片），不可恢复，确认？"),
        refresh_context=True,
    )
    @plugin_entry(
        id="clear_diary",
        name=tr("entries.clear_diary.name", default="清空时光日记"),
        description=tr("entries.clear_diary.description", default="删除当前角色的全部时光日记（她的手记与自动碎片）。不可恢复。"),
        input_schema={"type": "object", "properties": {}},
    )
    async def clear_diary(self, **_: Any):
        lanlan, shard = await self._current_shard_async()
        count = len(shard.diary)
        shard.diary = []
        await self._save_shard_diary(lanlan, shard)
        return Ok({"cleared": count, "lanlan": lanlan})

    @ui.action(
        label=tr("actions.prune_lanlan.label", default="清除残留数据"),
        tone="danger",
        confirm=tr(
            "actions.prune_lanlan.confirm",
            default="将删除该角色残留的周期、情绪与手记数据，不可恢复，确认？",
        ),
        refresh_context=True,
    )
    @plugin_entry(
        id="prune_lanlan",
        name=tr("entries.prune_lanlan.name", default="清除角色残留数据"),
        description=tr(
            "entries.prune_lanlan.description",
            default="清除已从宿主删除/改名的角色在插件里残留的分片数据（周期/情绪/手记/周记）。仅允许清除孤儿角色。",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "lanlan": {"type": "string", "description": "要清除的角色名（仅限已从宿主删除的孤儿角色）"},
            },
            "required": ["lanlan"],
        },
    )
    async def prune_lanlan(self, lanlan: str = "", **_: Any):
        """清除孤儿角色的全部分片数据（四个 Store key + 索引 + 内存 shard）。

        安全门槛（任一不满足即拒绝）：
        - 宿主角色名单必须可读——名单不可达时无法确认孤儿身份，宁可拒清也不可误删；
        - 目标不得仍存在于宿主（删除/改名前的正常角色绝不可清）；
        - 目标不得是宿主当前角色（当前角色 shard 正在被各路径读写）。
        """
        name = str(lanlan or "").strip()
        if not name:
            return Err(SdkError("角色名不能为空"))
        if name not in self._lanlan_index:
            return Err(SdkError(f"角色不在已知列表中：{name}"))
        known = await self._fetch_known_catgirls()
        if known is None:
            return Err(SdkError("无法获取宿主角色列表，为安全起见本次不清除；请稍后重试"))
        if name in known:
            return Err(SdkError(f"角色 {name} 仍存在于宿主中，不允许清除其数据"))
        current = await self._resolve_current_lanlan()
        if name == current:
            return Err(SdkError(f"{name} 是宿主当前角色，不允许清除其数据"))
        for key in (
            _cycle_key(name), _mood_key(name), _diary_key(name),
            _journal_key(name), _weekly_key(name),  # weekly@ 为 0.7.0 前的旧周记 key，一并清
            _review_key(name), _review_stats_key(name),  # 我的日记（0.8.0）：篇目与旧独立 stats key
            _stats_key(name),  # 相处统计（1.1.0）
        ):
            res = await self.store.delete(key)
            if isinstance(res, Err):
                self.logger.warning("prune: delete {} failed: {}", key, res.error)
        self._lanlan_index.remove(name)
        await self._save_lanlan_index()
        self._shards.pop(name, None)
        # 孤儿 shard 若还带着生效情绪，引用计数水位需立即自愈
        await self._maybe_sync_proactive_pause()
        self.logger.info("orphan lanlan pruned: {}", name)
        return Ok({"pruned": name})

    # ==========================================
    # 调试模式（[tide].debug_mode = true 时才注册）
    # 把难以自然触发的内部机制"快进"到秒级可验证：兜底超时、
    # 限时到期、活动感知分支、注入内容、工具韧性、消息水位。
    # 关闭时不注册任何入口，面板/命令面板零痕迹；生产包默认关闭。
    # 带角色维度的入口支持可选 lanlan 参数（缺省 = 宿主当前角色）。
    # ==========================================

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
            payload["invited"] = await self._maybe_journal_invite(name, shard)
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
