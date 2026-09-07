"""新手引导与配置引导（1.2.6）纯逻辑层：guide 记录规整 + 就绪清单判定。

数据进数据出、零 SDK 依赖（与 fragments/journal/review/stats 同款纪律）。
``guide`` 是安装级一次性记录（全局 Store key，不 per-lanlan）：

    {"wizard": "" | "done" | "skip", "at": iso_str, "version": "1.2.6"}

向导完成/跳过之后不再自动弹（管理页可 reopen 清回 ""）；角色级"还差什么"
由就绪清单（readiness）从当前状态即时计算，无额外持久化。
"""

from typing import Any

JsonObject = dict[str, Any]

# 当前引导版本：写进 guide 记录，日后引导流程改版时可据此判定旧记录是否失效
_GUIDE_VERSION = "1"
_WIZARD_STATES = frozenset({"", "done", "skip"})


def norm_guide_record(raw: Any) -> JsonObject:
    """宽容规整任意盘上/内存记录 → 规范形状（缺字段/坏类型容忍，零迁移）。

    非法 wizard 值一律按 ""（未引导）处理——宁可多看一次向导，不可把
    用户永久关在引导之外（记录被旧版/手工写坏时的自愈）。
    """
    if not isinstance(raw, dict):
        return {"wizard": "", "at": "", "version": ""}
    wizard = raw.get("wizard")
    if not isinstance(wizard, str) or wizard not in _WIZARD_STATES:
        wizard = ""
    return {
        "wizard": wizard,
        "at": str(raw.get("at") or ""),
        "version": str(raw.get("version") or ""),
    }


def wizard_pending(record: Any) -> bool:
    """是否应当自动弹向导：仅"从未完成/跳过"时为 True（幂等，含坏记录自愈）。"""
    return norm_guide_record(record)["wizard"] == ""


def make_guide_record(action: str, now_iso: str) -> JsonObject:
    """按面板动作生成新记录：done/skip 收尾，reopen 清回未引导态。

    未知 action 按 done 处理（入口 schema 已限 enum，此处只是防御）。
    """
    if action == "reopen":
        return {"wizard": "", "at": now_iso, "version": _GUIDE_VERSION}
    wizard = "skip" if action == "skip" else "done"
    return {"wizard": wizard, "at": now_iso, "version": _GUIDE_VERSION}


# ---- 就绪清单（GuideCard 数据源，纯即时计算）----

# 每项 signals 的取值都是 bool；level: must（必办）/ suggest（建议）。
# tab 为面板直达页签（"" = 无跳转动作项）。落点在 core，文案键在 i18n，
# 面板按 id 组装本地化文案——逻辑层不碰 tr()。
_READINESS_DEFS = (
    ("rhythm", "must", "cycle"),      # ①开启她的节律（总开关）
    ("anchor", "must", "cycle"),      # ②周期起点已确认
    ("mood", "suggest", "mood"),      # ③情绪系统已开启
    ("channels", "suggest", "mood"),  # ④至少一个模型通道在线
    ("together", "suggest", ""),      # ⑤你们已开始相处（仅展示）
)


def build_readiness(signals: JsonObject) -> JsonObject:
    """从当前状态信号算就绪清单。

    signals 键（缺失按 False 容忍）：
      rhythm    —— 该角色总开关已开
      anchor    —— 周期锚点已确认（非空）
      mood      —— 情绪系统开启
      channels  —— 语气/碎片/成文至少一路可用
      together  —— 已有首次互动（stats.first_seen）

    返回 {items: [{id, ok, level, tab}], must_ok, all_ok, pending}。
    """
    items: list[JsonObject] = []
    for item_id, level, tab in _READINESS_DEFS:
        items.append({
            "id": item_id,
            "ok": bool(signals.get(item_id)),
            "level": level,
            "tab": tab,
        })
    must_ok = all(i["ok"] for i in items if i["level"] == "must")
    all_ok = all(i["ok"] for i in items)
    pending = sum(1 for i in items if not i["ok"])
    return {"items": items, "must_ok": must_ok, "all_ok": all_ok, "pending": pending}
