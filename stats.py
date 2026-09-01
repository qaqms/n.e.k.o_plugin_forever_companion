"""永远的陪伴 —— 相处统计（1.1.0）的纯逻辑：按天聚合、里程碑、热力图、月报。

不持有宿主上下文、不做 IO：数据进、数据出，落盘与埋点由主类完成。
与 review.py 同款纪律——stats@<角色> 是独立的长期累计（成文不清零、
不受 [review].enabled 闸控制），只为用户可视化服务，绝不注入她的上下文。

数据结构（shard.stats，Store key stats@<角色>）：
    {"first_seen": "首条互动记录的时刻（ISO）",
     "days": { "2026-09-01": {"turns": int,        # 当天互动轮数（用户消息数）
                              "v_sum": float,      # 当天心情 valence 采样和
                              "v_n": int,          # 当天采样数
                              "tone": {label: int},# 当天她的语气分布
                              "cold": int,         # 当天她自主发起的冷战类动作次数
                              "made_up": int,      # 当天她主动调转晴结束负面情绪的次数
                              "warm": int},        # 当天正面情绪动作次数（自主）
              ... },
     "milestones": {"first_diary": iso, "first_journal": iso, "first_review": iso},
     "anniversary": {"last_pushed": "YYYY-MM-DD"}, # 纪念日当天注入的去重水位
     "months": { "2026-08": {月报封卷数据} }}      # 过完的月份一次性封卷

猴补丁兼容性（硬约束，同 state.py/affect.py）：必须 ``import time`` 后调
``time.time()``；不得 ``from time import time``。

日期口径：所有 day key 按 [tide].timezone 折算的本地日期（与潮汐日历一致，
用户看统计的天与看日历的天是同一天）；纯函数层不做时区折算——主类把
折算好的 day 字符串传进来，这里只认字符串。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

try:
    from .state import (
        _COLD_ACTIONS,
        _POSITIVE_ACTIONS,
        _STATS_DAYS_MAX,
        _STATS_HEATMAP_MONTHS,
        _STATS_MONTHS_MAX,
        _now_utc,
        _parse_iso_ts,
    )
except ImportError:  # pragma: no cover - 无父包上下文的兜底（裸导入，同 cycle.py 先例）
    from state import (  # type: ignore[no-redef]
        _COLD_ACTIONS,
        _POSITIVE_ACTIONS,
        _STATS_DAYS_MAX,
        _STATS_HEATMAP_MONTHS,
        _STATS_MONTHS_MAX,
        _now_utc,
        _parse_iso_ts,
    )

JsonObject = dict[str, Any]

# 里程碑徽章定义（id → 天数/事件类型）。「相伴 N 天」类徽章按天解锁，
# 解锁时刻 = first_seen + N 天；事件类徽章（第一篇日记）由主类喂 milestone 解锁
_MILESTONE_DAY_BADGES: tuple[tuple[str, int], ...] = (
    ("d7", 7),
    ("d30", 30),
    ("d100", 100),
    ("d365", 365),
    ("d730", 730),
)

# 里程碑事件类型 → 存储字段名（milestones dict 里的 key）
_MILESTONE_EVENT_FIELDS = {
    "first_diary": "first_diary",
    "first_journal": "first_journal",
    "first_review": "first_review",
}


def new_stats() -> JsonObject:
    """一份空白的相处统计。"""
    return {"first_seen": "", "days": {}, "milestones": {}, "anniversary": {}, "months": {}}


def _day_bucket(days: JsonObject, day: str) -> JsonObject:
    """取某天的聚合桶（不存在则建空桶；旧数据缺字段按 0 补齐）。"""
    bucket = days.get(day)
    if not isinstance(bucket, dict):
        bucket = {}
        days[day] = bucket
    bucket.setdefault("turns", 0)
    bucket.setdefault("v_sum", 0.0)
    bucket.setdefault("v_n", 0)
    bucket.setdefault("tone", {})
    bucket.setdefault("cold", 0)
    bucket.setdefault("made_up", 0)
    bucket.setdefault("warm", 0)
    return bucket


def _trim_days(days: JsonObject, today: str) -> None:
    """days 上限裁剪：只保留最近 _STATS_DAYS_MAX 天（含今天）。

    超出窗口的旧天数丢弃——徽章/累计总数另由 badges/summary 即时重算，
    丢弃的只有"很久以前哪天聊了多少轮"这种热度细节；封卷的月报保留月级摘要。
    """
    if len(days) <= _STATS_DAYS_MAX:
        return
    try:
        cutoff = (date.fromisoformat(today) - timedelta(days=_STATS_DAYS_MAX)).isoformat()
    except ValueError:
        return
    for key in [k for k in days if k < cutoff]:
        del days[key]


def record_turn(stats: JsonObject, day: str, *, valence: float | None = None) -> JsonObject:
    """记一轮互动（主类在每条新用户消息时调用，day 已按本地时区折算）。

    first_seen 只在为空时写入（相伴起点 = 最早互动）。不 mutate 入参。
    """
    fresh = dict(stats)
    days = dict(fresh.get("days") if isinstance(fresh.get("days"), dict) else {})
    if not str(fresh.get("first_seen") or ""):
        fresh["first_seen"] = _now_utc().isoformat(timespec="seconds")
    bucket = _day_bucket(days, day)
    bucket["turns"] = int(bucket.get("turns") or 0) + 1
    if valence is not None:
        bucket["v_sum"] = round(float(bucket.get("v_sum") or 0.0) + float(valence), 3)
        bucket["v_n"] = int(bucket.get("v_n") or 0) + 1
    _trim_days(days, day)
    fresh["days"] = days
    return fresh


def record_tone(stats: JsonObject, day: str, label: str) -> JsonObject:
    """记一次她的语气分析结果（weight=1.0 的主路径才喂）。"""
    key = str(label or "").strip()
    if not key:
        return stats
    fresh = dict(stats)
    days = dict(fresh.get("days") if isinstance(fresh.get("days"), dict) else {})
    bucket = _day_bucket(days, day)
    tone = dict(bucket.get("tone") if isinstance(bucket.get("tone"), dict) else {})
    tone[key] = int(tone.get(key) or 0) + 1
    bucket["tone"] = tone
    fresh["days"] = days
    return fresh


def record_mood_event(stats: JsonObject, day: str, action: str, *, origin: str) -> JsonObject:
    """记一次情绪动作事件。

    origin != "self"（主人命令的演示）不计——与她自主的情绪分开，与我的日记同款口径。
    和好（rising_tide）不在这里记：它由主类在"结束过负面状态"时单独喂 made_up，
    这里只统计动作本身。
    """
    if str(origin or "self") != "self":
        return stats
    key = str(action or "").strip()
    if not key:
        return stats
    fresh = dict(stats)
    days = dict(fresh.get("days") if isinstance(fresh.get("days"), dict) else {})
    bucket = _day_bucket(days, day)
    if key in _COLD_ACTIONS:
        bucket["cold"] = int(bucket.get("cold") or 0) + 1
    elif key in _POSITIVE_ACTIONS:
        bucket["warm"] = int(bucket.get("warm") or 0) + 1
    fresh["days"] = days
    return fresh


def record_made_up(stats: JsonObject, day: str) -> JsonObject:
    """记一次和好：她在负面情绪生效中主动调心情转晴（主类判定后喂）。"""
    fresh = dict(stats)
    days = dict(fresh.get("days") if isinstance(fresh.get("days"), dict) else {})
    bucket = _day_bucket(days, day)
    bucket["made_up"] = int(bucket.get("made_up") or 0) + 1
    fresh["days"] = days
    return fresh


def record_milestone(stats: JsonObject, kind: str, *, now: datetime | None = None) -> JsonObject:
    """记一个"第一次"里程碑（第一篇手记/第一页个人日记/第一篇我的日记）。

    已有值不覆盖——"第一篇"永远是最早的那次。
    """
    field = _MILESTONE_EVENT_FIELDS.get(str(kind or "").strip())
    if field is None:
        return stats
    fresh = dict(stats)
    milestones = dict(fresh.get("milestones") if isinstance(fresh.get("milestones"), dict) else {})
    if not str(milestones.get(field) or ""):
        milestones[field] = (now or _now_utc()).isoformat(timespec="seconds")
    fresh["milestones"] = milestones
    return fresh


def backfill_day(stats: JsonObject, day: str) -> JsonObject:
    """从三本日记时间戳回填"那天有互动"的活跃标记（升级安装时一次性）。

    轮数无法回填（没有留痕），只把天数点亮，让热力图不至于新版当天才起步。
    只点亮缺失的天，不碰已有数据。
    """
    fresh = dict(stats)
    days = dict(fresh.get("days") if isinstance(fresh.get("days"), dict) else {})
    bucket = days.get(day)
    if isinstance(bucket, dict) and int(bucket.get("turns") or 0) > 0:
        return stats  # 已有真实数据，不覆盖
    if not isinstance(bucket, dict):
        bucket = {}
    bucket["turns"] = max(int(bucket.get("turns") or 0), 1)
    days[day] = bucket
    if not str(fresh.get("first_seen") or ""):
        fresh["first_seen"] = _now_utc().isoformat(timespec="seconds")
    _trim_days(days, day)
    fresh["days"] = days
    return fresh


# ---- 汇总与派生视图（面板消费，全部即时计算零存储）----

def _iter_days(stats: JsonObject):
    days = stats.get("days") if isinstance(stats.get("days"), dict) else {}
    for day, bucket in days.items():
        if isinstance(bucket, dict):
            yield day, bucket


def total_turns(stats: JsonObject) -> int:
    return sum(int(bucket.get("turns") or 0) for _day, bucket in _iter_days(stats))


def active_day_count(stats: JsonObject) -> int:
    return sum(1 for _day, bucket in _iter_days(stats) if int(bucket.get("turns") or 0) > 0)


def cold_wars(stats: JsonObject) -> int:
    return sum(int(bucket.get("cold") or 0) for _day, bucket in _iter_days(stats))


def made_ups(stats: JsonObject) -> int:
    return sum(int(bucket.get("made_up") or 0) for _day, bucket in _iter_days(stats))


def warm_moments(stats: JsonObject) -> int:
    return sum(int(bucket.get("warm") or 0) for _day, bucket in _iter_days(stats))


def day_valence(bucket: JsonObject) -> float | None:
    """某天的心情均值（valence 采样）；无采样返回 None。"""
    n = int(bucket.get("v_n") or 0)
    if n <= 0:
        return None
    return float(bucket.get("v_sum") or 0.0) / n


def streaks(stats: JsonObject, today: str) -> tuple[int, int]:
    """(最长连续聊天天数, 当前连续天数)。

    "有聊天" = turns > 0 的天。当前连续从 today 往回数；today 本身没聊
    仍允许从昨天延续（今天刚开始不算断——深夜 00:01 不该把连续归零）。
    """
    active = sorted(day for day, bucket in _iter_days(stats) if int(bucket.get("turns") or 0) > 0)
    if not active:
        return 0, 0
    longest = 1
    run = 1
    for prev, cur in zip(active, active[1:]):
        try:
            gap = (date.fromisoformat(cur) - date.fromisoformat(prev)).days
        except ValueError:
            gap = 0
        run = run + 1 if gap == 1 else 1
        longest = max(longest, run)
    # 当前连续：从"今天或昨天"里最新的活跃天往回数
    try:
        anchor = date.fromisoformat(today)
    except ValueError:
        return longest, 0
    current = 0
    cursor = anchor
    while str(cursor.isoformat()) in active:
        current += 1
        cursor -= timedelta(days=1)
    if current == 0:
        cursor = anchor - timedelta(days=1)
        while str(cursor.isoformat()) in active:
            current += 1
            cursor -= timedelta(days=1)
    return longest, current


def days_together(stats: JsonObject, today: str) -> int:
    """已相伴天数：today − first_seen 的本地日期差 + 1（安装当天算第 1 天）。"""
    first = _parse_iso_ts(stats.get("first_seen"))
    if first is None:
        return 0
    try:
        anchor = date.fromisoformat(today)
    except ValueError:
        return 0
    return max(0, (anchor - first.date()).days + 1)


def next_anniversary(stats: JsonObject, today: str) -> tuple[int, int]:
    """下一个纪念日：(第 N 天, 距今天数)。纪念日 = 30/100/200/365/500/730/… 天。

    规则：从相伴第 1 天起，每逢满 30 的倍数或满 365 的倍数即纪念日；
    返回第一个"今天或之后"的节点；已相伴不足 30 天时首个节点是第 30 天。
    """
    total = days_together(stats, today)
    if total <= 0:
        return 0, 0
    candidates: list[int] = []
    for mult in range(1, 40):
        for base in (30, 365):
            node = base * mult
            if node >= total:
                candidates.append(node)
    node = min(candidates) if candidates else total
    return node, max(0, node - total)


def badges_payload(stats: JsonObject, today: str) -> list[JsonObject]:
    """徽章墙数据：相伴天数类 + 事件类，每枚 {id, unlocked, date, days?}。

    未解锁的占位（unlocked=false）让面板灰显，形成"还差 X 天"的期待感。
    """
    total = days_together(stats, today)
    out: list[JsonObject] = []
    for badge_id, days in _MILESTONE_DAY_BADGES:
        unlocked = total >= days
        achieved = ""
        if unlocked:
            first = _parse_iso_ts(stats.get("first_seen"))
            if first is not None:
                achieved = (first.date() + timedelta(days=days - 1)).isoformat()
        out.append({"id": badge_id, "days": days, "unlocked": unlocked, "date": achieved})
    milestones = stats.get("milestones") if isinstance(stats.get("milestones"), dict) else {}
    for event_id in _MILESTONE_EVENT_FIELDS:
        ts = str(milestones.get(event_id) or "")
        out.append({"id": event_id, "unlocked": bool(ts), "date": ts[:10] if ts else ""})
    return out


def summary_payload(stats: JsonObject, today: str) -> JsonObject:
    """数字摘要条（徽章墙顶部的关键数字）。"""
    total = days_together(stats, today)
    longest, current = streaks(stats, today)
    _node, until_next = next_anniversary(stats, today)
    return {
        "days_together": total,
        "next_anniversary_in": until_next if total > 0 else 0,
        "total_turns": total_turns(stats),
        "active_days": active_day_count(stats),
        "cold_wars": cold_wars(stats),
        "made_ups": made_ups(stats),
        "warm_moments": warm_moments(stats),
        "longest_streak": longest,
        "current_streak": current,
    }


def heatmap_payload(stats: JsonObject, today: str) -> JsonObject:
    """热力图数据：最近 _STATS_HEATMAP_MONTHS 个月（含当月）逐日 {date, turns, tone, valence}。

    tone = 当天主导语气 label（次数最多的；平票按 happy>neutral>surprised>sad>angry 排），
    valence = 当天心情均值（无采样为 None）。面板按 turns 分档染色、悬停显示明细。
    只下发窗口内存在的**已完结天**（今天的数据未统计完，明天才亮格；缺失天由面板留白）。
    """
    try:
        anchor = date.fromisoformat(today)
    except ValueError:
        return {"months": [], "days": []}
    # 窗口起点 = 当月往回 _STATS_HEATMAP_MONTHS - 1 个月（含当月共 N 个月）。
    # 月减法不用 timedelta（31 天近似会跨月漂移）：直接按 (year, month) 整数回退
    total_months = anchor.year * 12 + (anchor.month - 1) - (_STATS_HEATMAP_MONTHS - 1)
    start_month = date(total_months // 12, total_months % 12 + 1, 1)
    month_keys = []
    cursor = start_month
    while cursor <= anchor:
        month_keys.append(cursor.isoformat()[:7])
        next_month = cursor.month + 1
        cursor = date(cursor.year + (next_month > 12), (next_month - 1) % 12 + 1, 1)
    days_out: list[JsonObject] = []
    tone_order = {"happy": 0, "neutral": 1, "surprised": 2, "sad": 3, "angry": 4}
    for day, bucket in sorted(_iter_days(stats)):
        if day < month_keys[0]:
            continue
        if day >= today:  # 今天尚未过完，数据不完整，明天才进热力图
            continue
        tone = ""
        tone_map = bucket.get("tone") if isinstance(bucket.get("tone"), dict) else {}
        if tone_map:
            ranked = sorted(
                ((label, count) for label, count in tone_map.items() if int(count or 0) > 0),
                key=lambda kv: (-int(kv[1]), tone_order.get(kv[0], 9)),
            )
            tone = ranked[0][0] if ranked else ""
        valence = day_valence(bucket)
        days_out.append({
            "date": day,
            "turns": int(bucket.get("turns") or 0),
            "tone": tone,
            "valence": round(valence, 2) if valence is not None else None,
        })
    return {"months": month_keys, "days": days_out}


def month_view(stats: JsonObject, month: str, *, diary: list[JsonObject] | None = None) -> JsonObject:
    """单月数据视图（月报）：优先读封卷的 months[month]，否则从 days 即时聚合。

    封卷数据是月份过完时快照的（固定不变）；当月与未封卷的历史月即时计算。
    diary 传入该角色的时光日记（手记），用于摘「本月声音」——她当月写的
    最长一条手记原话（情感浓度最高的一条，纯摘录不改写）。
    """
    months = stats.get("months") if isinstance(stats.get("months"), dict) else {}
    sealed = months.get(month)
    if isinstance(sealed, dict) and sealed.get("sealed"):
        return sealed
    agg = _aggregate_month(stats, month, diary=diary)
    agg["sealed"] = False
    return agg


def _month_days(stats: JsonObject, month: str) -> list[tuple[str, JsonObject]]:
    prefix = str(month or "")[:7]
    if len(prefix) < 7:
        return []
    return sorted((day, bucket) for day, bucket in _iter_days(stats) if day.startswith(prefix))


def _pick_month_voice(diary: list[JsonObject] | None, month: str) -> JsonObject | None:
    """「本月声音」：该月她写的手记（source=self）里正文最长的一条。

    长度是"写得最走心"的廉价代理；返回 {ts, mood, entry} 摘录视图。
    """
    if not diary:
        return None
    best: JsonObject | None = None
    for item in diary:
        if not isinstance(item, dict) or str(item.get("source") or "self") != "self":
            continue
        ts = _parse_iso_ts(item.get("ts"))
        if ts is None or ts.date().isoformat()[:7] != str(month or "")[:7]:
            continue
        entry = str(item.get("entry") or "")
        if not entry.strip():
            continue
        if best is None or len(entry) > len(str(best.get("entry") or "")):
            best = {"ts": ts.isoformat(timespec="seconds"), "mood": str(item.get("mood") or ""), "entry": entry[:120]}
    return best


def _aggregate_month(
    stats: JsonObject, month: str, *, diary: list[JsonObject] | None = None
) -> JsonObject:
    """从 days 即时聚合一个月（月报的全部数字字段）。"""
    day_items = _month_days(stats, month)
    turns_total = 0
    active_days = 0
    busiest: tuple[str, int] = ("", 0)
    v_sum, v_n = 0.0, 0
    tone_tally: dict[str, int] = {}
    cold = made_up = warm = 0
    longest_run = current_run = 0
    prev_day: date | None = None
    for day, bucket in day_items:
        day_turns = int(bucket.get("turns") or 0)
        turns_total += day_turns
        if day_turns > 0:
            active_days += 1
            if day_turns > busiest[1]:
                busiest = (day, day_turns)
            if prev_day is not None:
                try:
                    gap = (date.fromisoformat(day) - prev_day).days
                except ValueError:
                    gap = 0
                current_run = current_run + 1 if gap == 1 else 1
            else:
                current_run = 1
            longest_run = max(longest_run, current_run)
            try:
                prev_day = date.fromisoformat(day)
            except ValueError:
                prev_day = None
        cold += int(bucket.get("cold") or 0)
        made_up += int(bucket.get("made_up") or 0)
        warm += int(bucket.get("warm") or 0)
        v_sum += float(bucket.get("v_sum") or 0.0)
        v_n += int(bucket.get("v_n") or 0)
        tone_map = bucket.get("tone") if isinstance(bucket.get("tone"), dict) else {}
        for label, count in tone_map.items():
            tone_tally[str(label)] = tone_tally.get(str(label), 0) + int(count or 0)
    tone_order = {"happy": 0, "neutral": 1, "surprised": 2, "sad": 3, "angry": 4}
    tone_ranked = sorted(
        tone_tally.items(), key=lambda kv: (-kv[1], tone_order.get(kv[0], 9))
    )
    return {
        "month": str(month or "")[:7],
        "turns": turns_total,
        "active_days": active_days,
        "busiest_day": busiest[0],
        "busiest_turns": busiest[1],
        "longest_streak": longest_run,
        "cold_wars": cold,
        "made_ups": made_up,
        "warm_moments": warm,
        "tone": dict(tone_ranked[:3]),
        "valence_avg": round(v_sum / v_n, 2) if v_n > 0 else None,
        "voice": _pick_month_voice(diary, month),
    }


def seal_month(stats: JsonObject, month: str, *, diary: list[JsonObject] | None = None) -> JsonObject:
    """封卷一个月份（月份过完时调用一次）：快照月报进 months，超出上限淘汰最旧。

    当月永不封卷（调用方保证）；封卷数据 month_view 优先返回。
    """
    fresh = dict(stats)
    months = dict(fresh.get("months") if isinstance(fresh.get("months"), dict) else {})
    agg = _aggregate_month(fresh, month, diary=diary)
    if agg["turns"] <= 0 and not agg["active_days"]:
        return fresh  # 空月份不封卷（挂机月没有月报）
    agg["sealed"] = True
    months[str(month)[:7]] = agg
    while len(months) > _STATS_MONTHS_MAX:
        oldest = min(months)
        del months[oldest]
    fresh["months"] = months
    return fresh


def seal_due_months(stats: JsonObject, today: str, *, diary: list[JsonObject] | None = None) -> tuple[JsonObject, list[str]]:
    """封卷判定：today 进入新月时，把 today 之前的所有未封卷月份依次封卷。

    返回 (新 stats, 本次封卷的月份列表)。幂等：已封卷的月（数据在 months 里
    且 sealed=true）跳过；days 窗口裁剪掉的古早日子的月份跳过（无从聚合）。
    """
    try:
        anchor = date.fromisoformat(today)
    except ValueError:
        return stats, []
    current_month = anchor.replace(day=1).isoformat()[:7]
    days = stats.get("days") if isinstance(stats.get("days"), dict) else {}
    months = stats.get("months") if isinstance(stats.get("months"), dict) else {}
    # 找出 days 里出现过的、早于当月、尚未封卷的月份
    pending = sorted({
        day[:7] for day in days
        if isinstance(day, str) and len(day) >= 7 and day[:7] < current_month
    })
    fresh = stats
    sealed: list[str] = []
    for month in pending:
        if isinstance(months.get(month), dict) and months[month].get("sealed"):
            continue
        before = fresh
        fresh = seal_month(fresh, month, diary=diary)
        if fresh is not before:
            sealed.append(month)
    return fresh, sealed


def anniversary_due(stats: JsonObject, today: str) -> tuple[bool, int]:
    """纪念日注入判定：今天是否恰好是相伴第 N 天（N 为 30/100/… 节点）。

    去重水位 anniversary.last_pushed（YYYY-MM-DD）防止当天重复注入。
    只判定不改水位——主类推送成功后再调 mark_anniversary_pushed。
    """
    total = days_together(stats, today)
    if total <= 0:
        return False, 0
    is_node = total >= 30 and (total % 30 == 0 or total % 365 == 0)
    if not is_node:
        return False, 0
    ann = stats.get("anniversary") if isinstance(stats.get("anniversary"), dict) else {}
    if str(ann.get("last_pushed") or "") == str(today):
        return False, 0
    return True, total


def mark_anniversary_pushed(stats: JsonObject, today: str) -> JsonObject:
    """纪念日注入成功后盖水位（当天不再重复）。"""
    fresh = dict(stats)
    fresh["anniversary"] = {**dict(fresh.get("anniversary") if isinstance(fresh.get("anniversary"), dict) else {}), "last_pushed": str(today)}
    return fresh
