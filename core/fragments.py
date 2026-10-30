"""永远的陪伴 —— 时光日记·自动碎片的纯逻辑（提取 prompt 组装 / 模型回复解析 / 检索过滤）。

不持有宿主上下文、不做 IO：小模型调用与落盘由主类（经 EmotionSenseService 的
直连通道）完成，本模块只负责"调之前"与"拿到回复之后"的纯数据处理。
常量（类型表/截断上限/prompt 模板）来自 state.py；导入用 try/except 双路径，
兼容包加载（plugins.forever_companion）与裸导入（同 cycle.py 被 test_cycle.py
裸导入的先例）两种姿势。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from .state import (
    _DIARY_MAX_ENTRIES,
    _FRAGMENT_EXTRACTION_PROMPT,
    _FRAGMENT_KINDS,
    _FRAGMENT_NOTE_MAX_CHARS,
    _FRAGMENT_NUDGE_KINDS,
    _FRAGMENT_QUOTE_MAX_CHARS,
    _FRAGMENT_RELATIONS,
    _FRAGMENT_REVIEW_ISSUES,
    _FRAGMENT_REVIEW_PROMPT,
    _FRAGMENT_STATUS_ACTIVE,
    _now_utc,
)

JsonObject = dict[str, Any]


def fabricate_demo_diary(count: int = 24, *, now: datetime | None = None) -> list[JsonObject]:
    """生成混合手记与四类碎片的调试时间线，时间递增、每条带 demo 标记。"""
    current = now or _now_utc()
    count = max(1, min(int(count), _DIARY_MAX_ENTRIES))
    notes = (
        ("开心", "今天聊起了一件小事，听他说完以后，心里暖暖的。"),
        ("平静", "一起安静地待了一会儿。没有很多话，也觉得很踏实。"),
        ("委屈", "刚才有一点不开心，想等心情平复以后再慢慢说。"),
        ("期待", "记住了下次想一起做的事，开始有一点期待了。"),
    )
    fragments = (
        ("like", "我喜欢下雨的时候听轻音乐。", "记下他明确说过的喜好。"),
        ("dislike", "我不喜欢休息的时候被催着做事。", "记下他希望被尊重的边界。"),
        ("important", "以后遇到事情，我们都慢慢说清楚。", "记下这句认真说过的约定。"),
        ("overstep", "刚才我说你很烦，那句话确实太重了。", "记下伤人的表达，不替任何一方判断释怀。"),
    )
    records: list[JsonObject] = []
    for i in range(count):
        ts = (current - timedelta(hours=(count - i - 1) * 8)).isoformat(timespec="seconds")
        if i % 2 == 0:
            mood, text = notes[(i // 2) % len(notes)]
            item = {"ts": ts, "source": "self", "phase": "follicular", "mood": mood,
                    "entry": text}
        else:
            kind, quote, note = fragments[(i // 2) % len(fragments)]
            item = fragment_record(ts, "follicular", {
                "kind": kind, "quote": quote,
                "note": note, "confidence": 0.95,
            })
        item["demo"] = True
        records.append(item)
    return records


def diary_display_record(item: JsonObject) -> JsonObject:
    """旧调试记录只在显示时去掉前缀，保留原始记录及还原备份。"""
    visible = dict(item)
    if item.get("demo") is True:
        for field in ("entry", "quote"):
            if isinstance(item.get(field), str):
                visible[field] = re.sub(r"^【调试示例\s*\d*\s*】", "", item[field], count=1)
    return visible


def _format_line(index: int, item: JsonObject) -> str:
    """清单里的一行：编号 + 类型 + 日期 + 原话。

    日期是判"谁更新"的唯一线索——没有它，模型面对两条矛盾记录只能靠猜。缺 ts 时
    省掉日期段（旧调试数据/手工构造的条目），不影响其余格式。
    """
    kind = str(item.get("kind") or "")
    quote = str(item.get("quote") or "")[:_FRAGMENT_QUOTE_MAX_CHARS]
    day = str(item.get("ts") or "")[:10]
    return f"[{index}] [{kind}] {day} {quote}" if day else f"[{index}] [{kind}] {quote}"


def _format_existing(existing: list[JsonObject]) -> str:
    """把已有碎片排成编号清单塞进 prompt（编号就是模型回填的 target）。

    调用方传的是 recall_fragments 的结果（时间倒序），所以编号 1 是最新一条——这一点
    必须在段落标题里写明，否则模型会把编号当成时间正序，把"更新"判反。
    空列表时明确写"（无）"——不能让模型对着一个空标题自己猜有没有记忆。
    """
    lines = [
        _format_line(index, item)
        for index, item in enumerate(existing, start=1)
        if str(item.get("quote") or "").strip()
    ]
    if not lines:
        return "已有记忆：（无）\n"
    return "已有记忆（编号 1 为最近，按时间倒序；编号用于 target 字段）：\n" + "\n".join(lines) + "\n"


def build_fragment_prompt(
    user_text: str, her_text: str, existing: list[JsonObject] | None = None
) -> str:
    """组装碎片提取请求：主人的话是分析对象，她的回复只作语境（截断防 prompt 膨胀）。

    existing = 已有碎片（调用方传 recall_fragments 的最近若干条），让模型判断这句是
    新的 / 重复的 / 更新了某条旧记忆；缺省 None 等价空列表（旧调用点与旧测试不受影响）。
    """
    context = f"（猫娘当时的回复：{her_text[:120]}）" if str(her_text or "").strip() else ""
    return (
        f"{_FRAGMENT_EXTRACTION_PROMPT}"
        f"{_format_existing(list(existing or []))}"
        f"主人的话：\n{str(user_text or '')[:300]}{context}"
    )


def parse_fragment_response(raw: str) -> JsonObject | None:
    """解析小模型的碎片提取回复 → 归一化 dict；解析不出/字段坏返回 None。

    容忍模型在 JSON 前后附带解释文本（取第一个 {...} 块）；capture 缺省按 False
    处理（宁可漏记不可错记）；kind 不在类型表或缺 quote → None；
    confidence 钳制到 [0,1]；relation 缺失/未知按 "new"，target 只在 supersede 时
    解析（编号是否越界由调用方按「已有记忆」实际长度判定）。返回结构：
    {capture, kind, quote, note, confidence, relation, target}。
    """
    import json as _json

    text = str(raw or "").strip()
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = _json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    if not data.get("capture"):
        return {"capture": False, "confidence": confidence}
    kind = str(data.get("kind") or "").strip()
    if kind not in _FRAGMENT_KINDS:
        return None
    quote = str(data.get("quote") or "").strip()
    if not quote:
        return None  # 没有原话摘录的碎片无从对证，按解析失败丢弃
    # 关系字段宽容解析：缺失/乱写一律按 "new"（主体内容合法时不该因关系坏了整条丢弃）。
    # target 只做类型兜底，编号是否越界由调用方按「已有记忆」实际长度判定。
    relation = str(data.get("relation") or "").strip().lower()
    if relation not in _FRAGMENT_RELATIONS:
        relation = "new"
    target = 0
    if relation == "supersede":
        try:
            target = int(data.get("target") or 0)
        except (TypeError, ValueError):
            target = 0
    return {
        "capture": True,
        "kind": kind,
        "quote": quote,
        "note": str(data.get("note") or "").strip(),
        "confidence": confidence,
        "relation": relation,
        "target": target,
    }


def fragment_record(
    ts_iso: str, phase: str, parsed: JsonObject, *, supersedes: str = ""
) -> JsonObject:
    """解析结果 → 时光日记时间线条目（source=auto，quote/note 截断到记录上限）。

    新记录一律以 status=active 落盘：它是"现行事实"，可被 mood_recall_fragments 翻到。
    supersedes = 被这条取代的旧条 ts（仅 relation="supersede" 且编号有效时由调用方传入），
    写进记录供追溯"这条改了哪一条"；把旧条切到 superseded 是调用方的事，本函数只造
    自己的条目，不碰列表里别的记录。
    """
    record = {
        "ts": ts_iso,
        "source": "auto",
        "phase": phase,
        "kind": str(parsed["kind"]),
        "quote": str(parsed["quote"])[:_FRAGMENT_QUOTE_MAX_CHARS],
        "note": str(parsed.get("note") or "")[:_FRAGMENT_NOTE_MAX_CHARS],
        "confidence": round(float(parsed.get("confidence") or 0.0), 2),
        "status": _FRAGMENT_STATUS_ACTIVE,
    }
    if supersedes:
        record["supersedes"] = supersedes
    return record


def recall_fragments(
    diary: list[JsonObject],
    kind: str = "",
    query: str = "",
    limit: int = 10,
) -> list[JsonObject]:
    """时光日记检索（她自主调用的"翻旧账/回忆喜好"工具的取数纯函数）。

    只返回自动碎片（source=auto；她的手记不在此列）且仍处于 active 生命周期的条目；
    kind 过滤、query 对 quote+note 做不区分大小写的子串匹配；按时间倒序
    （最近的先想起），截 limit 条。limit 钳制到 1..30。
    """
    try:
        cap = max(1, min(30, int(limit)))
    except (TypeError, ValueError):
        cap = 10
    wanted_kind = str(kind or "").strip()
    needle = str(query or "").strip().lower()
    hits: list[JsonObject] = []
    for item in reversed(diary):
        if str(item.get("source") or "") != "auto":
            continue
        # 生命周期闸：只把"现行事实"递给她。superseded 的旧条留在时间线上可追溯，
        # 但不再冒充现状（例：先说"最喜欢咖啡"、后来"心悸戒了"）。旧记录缺 status
        # 字段一律按 active 处理——1.4.2 及之前的存量碎片必须照常翻得到（零迁移）。
        if str(item.get("status") or _FRAGMENT_STATUS_ACTIVE) != _FRAGMENT_STATUS_ACTIVE:
            continue
        if wanted_kind and str(item.get("kind") or "") != wanted_kind:
            continue
        if needle:
            haystack = f"{item.get('quote') or ''} {item.get('note') or ''}".lower()
            if needle not in haystack:
                continue
        hits.append(item)
        if len(hits) >= cap:
            break
    return hits


def build_review_prompt(items: list[JsonObject]) -> str:
    """组装记忆自检请求：碎片排成编号清单，编号就是模型回填的 index。

    与提取 prompt 共用 _format_line（1-based 编号 + 类型 + 日期 + 原话）：日期对自检
    尤其重要——判"哪条过时"必须知道先后。编号 1 是最新一条（调用方传时间倒序）。
    """
    lines = [
        _format_line(index, item)
        for index, item in enumerate(items, start=1)
        if str(item.get("quote") or "").strip()
    ]
    return f"{_FRAGMENT_REVIEW_PROMPT}" + ("\n".join(lines) if lines else "（无）")


def parse_review_response(raw: str) -> list[JsonObject] | None:
    """解析自检回复 → 归一化的 findings 列表；整体结构坏返回 None。

    两层宽容：
    - JSON 前后可夹解释文本（取第一个 {...} 块）；
    - 单条 finding 坏（issue 不在闭集、index 非正整数）只丢那一条，不作废整次自检。
    `findings: []` 是合法结果（真的没问题），与解析失败返回 None 严格区分。
    index 是否越界由调用方按清单实际长度判定（这里不知道给了几条）。
    """
    import json as _json

    text = str(raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = _json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    raw_findings = data.get("findings")
    if not isinstance(raw_findings, list):
        return None
    findings: list[JsonObject] = []
    for entry in raw_findings:
        if not isinstance(entry, dict):
            continue
        issue = str(entry.get("issue") or "").strip().lower()
        if issue not in _FRAGMENT_REVIEW_ISSUES:
            continue
        try:
            index = int(entry.get("index") or 0)
        except (TypeError, ValueError):
            continue
        if index < 1:
            continue
        findings.append({
            "index": index,
            "issue": issue,
            "reason": str(entry.get("reason") or "").strip()[:120],
        })
    return findings


def should_nudge_fight(
    record: JsonObject,
    mood_action: str,
    pause_actions: frozenset[str],
    nudge_kinds: frozenset[str] = _FRAGMENT_NUDGE_KINDS,
) -> bool:
    """吵架轻语判定（纯判定，节流由调用方按 shard 时间戳处理）：
    只有重度负面动作生效中、新碎片是"过激/厌恶"类才值得提醒她"你记得吗"。"""
    return bool(
        mood_action
        and mood_action in pause_actions
        and str(record.get("kind") or "") in nudge_kinds
    )
