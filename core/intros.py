"""功能介绍的静态文案与原理流程（1.2.7 · 面板「功能介绍」卡片的唯一文案源）。

定位：这是**数据层**，不是渲染层——只声明"每个功能对外介绍时说什么"，
怎么排版、怎么画图全部在前端（ui/capintro.tsx）。能力中心新增功能时，
在 CAP_INTROS 补一条即可自动获得介绍卡片（缺条目时面板会如实显示「介绍
暂缺」而不是瞎编）。

i18n 契约（与 core/capabilities.py 的 label 兜底同一套思路）：

- 这里存的是**中文原文**；面板协议里的字符串统一以 ``{"$i18n": key,
  "default": 中文}`` 引用下发，前端 ``t(key, {defaultValue})`` 按宿主语言
  解析（zh 走 default、en 及以后的小语种进 i18n/*.json 补 key 即可，
  不用动本文件）。
- key 命名由 cap id 派生、规则唯一（见 ``purpose_key`` 等小函数）：
  本文件是文案的**事实源**，i18n JSON 只是它的翻译登记表。

流程演示图（flow）：3~6 个节点串成一条「输入 → 处理 → 输出」的链，
每个节点 = ``FlowNode(kind, 中文标签)``（无图标字段，1.2.7 去 emoji）：

- kind 只影响配色（前端不认识新 kind 时回落中性色，向前兼容）：
  ``src`` 输入源 / ``proc`` 处理 / ``gate`` 判定闸门（虚线框）/ ``out`` 输出
- 节点为纯文字胶囊，无图标（1.2.7 用户反馈去 emoji，配色即类型语言）

字符串纪律：正文里的引用一律用「」角括号——ASCII 双引号会截断 Python
字符串，全角弯引号在部分工具链里会被规范化掉（都踩过）。

依赖链 / LLM 触点 / 占用工具等结构化事实**不在这里重复维护**——
前端从既有 capabilities 数据（deps/llm/tools/blocked_by）现场拼装，
保证介绍卡片和功能状态永远是同一口径。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

JsonObject = dict[str, Any]

# 流程节点 kind 词表（稳定字符串，前端按此上色；新增 kind 需同步样式层）
FLOW_KINDS = ("src", "proc", "gate", "out")


@dataclass(frozen=True)
class FlowNode:
    """原理图上的一个节点：kind 决定配色，label 中文原文。

    （1.2.7 用户反馈：不要 emoji 图标——类型区分全靠配色胶囊与虚线框，
    节点退化为纯文字胶囊；新增字段前先想清楚，别把图标需求又加回来。）
    """

    kind: str
    label: str


@dataclass(frozen=True)
class CapIntro:
    """一项功能的介绍内容（全部字段为中文原文，经 key 引用下发）。

    purpose:   这个功能做什么（一段话）
    scenarios: 主要场景（2~4 条「你会看到什么」）
    limits:    限制与注意事项（2~5 条，如实说边界，不粉饰）
    flow:      原理演示链（3~6 节点）
    """

    purpose: str
    scenarios: tuple[str, ...]
    limits: tuple[str, ...]
    flow: tuple[FlowNode, ...]


# ---- i18n key 派生（唯一规则，改不得：i18n JSON 按此登记翻译）----

def _base(cap_id: str) -> str:
    return f"panel.capintro.{cap_id}"


def purpose_key(cap_id: str) -> str:
    return f"{_base(cap_id)}.purpose"


def scenario_key(cap_id: str, idx: int) -> str:
    """idx 从 1 起（JSON key 用 scene1/scene2…，避免 0 起始的歧义）。"""
    return f"{_base(cap_id)}.scene{idx}"


def limit_key(cap_id: str, idx: int) -> str:
    return f"{_base(cap_id)}.limit{idx}"


def flow_key(cap_id: str, idx: int) -> str:
    return f"{_base(cap_id)}.flow{idx}"


CAP_INTROS: dict[str, CapIntro] = {
    # ---- 状态与提醒（rhythm）----
    "whisper": CapIntro(
        purpose=(
            "根据当前阶段提供简短状态提示，作为角色聊天时的参考。"
            "提示在后台加入对话上下文，不单独弹出消息；实际回复由角色使用的模型决定。"
        ),
        scenarios=(
            "角色可以参考当前状态，使用安静或轻快的语气回应",
            "询问「今天状态怎么样」时，角色可以参考阶段提示回答",
            "同一条提示会结合角色设定，产生不同的表达",
        ),
        limits=(
            "活动感知依赖此功能；关闭后，不再添加状态与活动提示",
            "默认每 3 条用户消息检查一次，提示未变化时不重复添加；频率可在设置中调整",
            "提示会过滤部分不适合日常聊天的词语，但不能保证模型始终按提示表达",
        ),
        flow=(
            FlowNode("src", "用户消息"),
            FlowNode("proc", "检查新消息"),
            FlowNode("gate", "检查提示频率"),
            FlowNode("proc", "计算当前阶段"),
            FlowNode("out", "添加后台状态提示"),
        ),
    ),
    "phase_openers": CapIntro(
        purpose=(
            "阶段变化时，向角色发送一次问候提示，让聊天自然带出近期状态。"
            "具体如何表达，由角色使用的模型决定。"
        ),
        scenarios=(
            "进入新的阶段时，角色可能主动说一句近况",
            "状态更活跃时，问候的语气可能更轻快",
        ),
        limits=(
            "需要开启模拟总开关；暂停回复的情绪状态下，不发送问候提示",
            "同一阶段只提示一次，跨天或重启不会重复；再次进入该阶段时可重新提示",
            "不需要主动问候时，可单独关闭阶段问候",
        ),
        flow=(
            FlowNode("src", "阶段变化"),
            FlowNode("gate", "本阶段尚未提示"),
            FlowNode("out", "发送问候提示"),
        ),
    ),
    "activity_sense": CapIntro(
        purpose=(
            "使用宿主提供的在场与忙碌状态，让角色的回应参考你的活动节奏。"
            "插件不使用摄像头，也不读取屏幕内容。"
        ),
        scenarios=(
            "离开电脑一段时间后，角色可以参考离开状态回应",
            "专注工作时，角色可以参考忙碌状态，使用简短的表达",
        ),
        limits=(
            "需要开启状态提示，活动信息会随状态提示加入对话上下文",
            "隐私模式或活动信号不可用时，不添加活动提示",
            "只使用在场、忙碌等概括状态；这些提示可能随对话发送给宿主配置的模型服务",
        ),
        flow=(
            FlowNode("src", "宿主活动状态"),
            FlowNode("gate", "检查隐私设置"),
            FlowNode("proc", "整理在场与忙碌状态"),
            FlowNode("out", "加入状态提示"),
        ),
    ),
    "anniversary": CapIntro(
        purpose=(
            "相伴达到 30、60、90、365 天等纪念节点时，向角色发送一条后台提醒。"
            "角色可能在聊天中提起这个日子，不会强制弹出庆祝消息。"
        ),
        scenarios=(
            "相伴第 60 天时，角色可能在聊天中提起这段相处",
            "角色没有回应提醒时，聊天仍照常进行",
        ),
        limits=(
            "纪念日期根据本地相处统计计算，关闭提醒不会清除统计",
            "只在纪念节点当天提醒一次，不重复发送",
            "可在功能页或日记页的相处统计设置中关闭纪念日提醒",
        ),
        flow=(
            FlowNode("src", "每日日期检查"),
            FlowNode("gate", "到达纪念节点"),
            FlowNode("out", "添加后台纪念日提醒"),
        ),
    ),
    "birthday": CapIntro(
        purpose=(
            "填写生日后，在生日当天首次聊天时向角色发送一条后台提醒。"
            "角色可以用自己的方式送上祝福，但不保证一定回应。年份仅用于校验日期，不计算年龄。"
        ),
        scenarios=(
            "生日当天聊天时，角色可能向你送上祝福",
            "开启记录选项后，时光日记会保存一条生日记录",
            "未填写生日时，不发送生日提醒",
        ),
        limits=(
            "生日为 2 月 29 日时，非闰年在 2 月 28 日提醒",
            "暂停回复期间不发送提醒；当天恢复后的下一条消息可再次触发检查",
            "当天只提醒一次，不重复发送，也不会向角色提供年龄",
            "生日记录使用插件的固定文案，并非角色亲笔；可在时光日记中删除",
            "需要开启当前角色的模拟总开关，否则功能页会显示未启用原因",
        ),
        flow=(
            FlowNode("src", "设置的生日日期"),
            FlowNode("gate", "生日当天且尚未提醒"),
            FlowNode("proc", "添加提醒与可选记录"),
            FlowNode("out", "由角色决定如何祝福"),
        ),
    ),
    # ---- 情绪与感知（mood）----
    "mood_engine": CapIntro(
        purpose=(
            "让角色通过情绪工具表达平静、低落或愉快等状态，并记录心情变化。"
            "部分状态会调整回应方式或暂停主动消息；限时状态结束后会自动恢复。"
        ),
        scenarios=(
            "角色可以通过工具表达当前心情，让面板状态与聊天有所关联",
            "愉快时可能使用轻快语气，低落时可能减少回应",
            "限时情绪结束后自动恢复，无需手动操作",
        ),
        limits=(
            "语气感知、对话片段、个人日记和我的日记依赖此功能，关闭后会一并停用",
            "部分情绪状态会临时暂停宿主主动消息，结束后恢复原设置",
            "手动演示与角色自主触发的情绪分开记录，不混入自主情绪统计",
        ),
        flow=(
            FlowNode("src", "互动信号"),
            FlowNode("gate", "角色调用情绪工具"),
            FlowNode("proc", "更新情绪状态与时限"),
            FlowNode("out", "记录状态与心情变化"),
        ),
    ),
    "tone_sense": CapIntro(
        purpose=(
            "回复完成后，后台模型分析近期互动的语气，帮助记录心情变化。"
            "需要时会提醒角色记录心情或调整情绪状态；提醒不会直接切换情绪，聊天也无需等待分析完成。"
        ),
        scenarios=(
            "语气逐渐缓和时，角色可能收到调整情绪状态的提醒",
            "互动中的情绪较明显时，角色可能收到记录心情的邀请",
        ),
        limits=(
            "需要开启情绪系统；分析和提醒不保证完全准确，也不保证角色一定采用",
            "默认使用宿主配置的情感模型服务；选择其他模型槽位时会读取本地配置直连。分析文本可能发送至外部服务",
            "宿主接口或模型服务不可用时，暂停语气分析，不影响其他功能",
            "部分阶段会提高筛选灵敏度，可在设置中单独关闭",
        ),
        flow=(
            FlowNode("src", "近期互动文本"),
            FlowNode("proc", "后台分析语气"),
            FlowNode("gate", "检查提醒条件"),
            FlowNode("out", "提醒记录或调整状态"),
        ),
    ),
    # ---- 三本日记（diary）----
    "fragments": CapIntro(
        purpose=(
            "后台模型从用户消息中提取明确的喜好和重要表达，连同原话保存到时光日记。"
            "角色可以通过检索工具参考这些片段，方便在以后的聊天中回顾。"
        ),
        scenarios=(
            "明确提到喜欢的食物或活动时，相关原话可能被保存",
            "以后聊到相关话题时，角色可以检索已保存的片段",
            "在面板中查看、搜索或删除保存的对话片段",
        ),
        limits=(
            "低置信度内容不会保存；模型仍可能遗漏或理解有误，可在面板查看并删除",
            "默认通过宿主使用 agent 模型槽位；必要时读取本地配置直连。用户消息可能发送至外部服务，不需要时可关闭",
            "片段通常供角色自主检索；部分情绪状态下，会低频提醒角色参考新片段",
            "需要开启情绪系统，并受模型可用性、调用间隔和每日预算限制",
        ),
        flow=(
            FlowNode("src", "用户消息"),
            FlowNode("proc", "后台提取重要表达"),
            FlowNode("gate", "检查置信度"),
            FlowNode("out", "保存原话，供角色检索"),
        ),
    ),
    "journal": CapIntro(
        purpose=(
            "角色自己的日记本。插件按照写作间隔发送邀请，默认距上次写作满 7 天后再邀请，"
            "由角色决定是否写下近期感受。日记按书页保存，供你在面板翻阅。"
        ),
        scenarios=(
            "在日记页阅读角色写下的近期感受与心情变化",
            "角色可以续写已有书页，也可以开始新的一页",
        ),
        limits=(
            "需要开启情绪系统；邀请可附带心情和片段素材。保存的日记不会自动加入后续聊天或宿主记忆",
            "插件只发送邀请，不代替角色写作，也不保证收到邀请后立即生成日记",
            "点击「邀请写日记」可发送写作请求；短时间重复点击会改为后台提示，避免反复发起回应",
        ),
        flow=(
            FlowNode("src", "达到写作间隔"),
            FlowNode("proc", "发送邀请与参考素材"),
            FlowNode("gate", "角色决定是否写作"),
            FlowNode("out", "保存书页，供你翻阅"),
        ),
    ),
    "review": CapIntro(
        purpose=(
            "后台模型根据互动次数、语气、心情变化和对话片段，整理近期相处记录。"
            "内容不是角色亲笔，也不是对你的评分；生成结果可能有偏差，仅供你在面板回顾。"
        ),
        scenarios=(
            "在日记页阅读一篇后台整理的相处总结",
            "回看近期互动和心情变化，了解这段时间的相处情况",
        ),
        limits=(
            "只在面板中展示，不自动加入角色对话或宿主记忆，也不提供角色访问这本日记的工具",
            "达到互动次数或天数条件后生成，期间需要有聊天；素材不足时无法立即生成",
            "默认通过宿主使用 agent 模型槽位；必要时读取本地配置直连。素材可能发送至外部服务，并受模型与调用预算限制",
            "手动演示与角色自主触发的情绪分开标注，避免混淆",
        ),
        flow=(
            FlowNode("src", "累计相处素材"),
            FlowNode("gate", "达到次数或天数条件"),
            FlowNode("proc", "后台整理相处总结"),
            FlowNode("out", "保存到我的日记"),
        ),
    ),
}


def intro_for(cap_id: str) -> CapIntro | None:
    """按能力 id 取介绍条目（未登记返回 None，面板据此显示「介绍暂缺」）。"""
    return CAP_INTROS.get(cap_id)


def build_intro_payload(spec: Any, ref: Callable[[str, str], JsonObject]) -> JsonObject:
    """把声明表组装成面板协议 payload（纯函数、零 IO、不认识 SDK）。

    spec: core.capabilities.CapabilitySpec（鸭子类型，测试可用简单对象）
    ref:  (key, default_zh) -> i18n 引用 的构造函数（mixin 层注入 SDK 的 tr）

    依赖链 / LLM 触点 / 占用工具等结构化事实从 spec 现场取，保证介绍卡片
    与功能状态永远同一口径；这里只携带文案引用。未登记介绍的能力返回
    ``{"id", "found": False}``，前端如实展示「介绍暂缺」。
    """
    intro = CAP_INTROS.get(spec.id)
    if intro is None:
        return {"id": spec.id, "found": False}
    # strip("[]") 防御：声明表里段名本不带括号（"mood"），但手滑写成
    # "[mood]" 也不会渲染出 "[[mood]]"（TOML 里那是数组表）
    config_keys = [] if spec.config is None else [f"[{str(spec.config[0]).strip('[]')}].{spec.config[1]}"]
    return {
        "id": spec.id,
        "found": True,
        "purpose": ref(purpose_key(spec.id), intro.purpose),
        "scenarios": [ref(scenario_key(spec.id, i), s) for i, s in enumerate(intro.scenarios, 1)],
        "limits": [ref(limit_key(spec.id, i), s) for i, s in enumerate(intro.limits, 1)],
        "flow": [
            {"kind": n.kind, "label": ref(flow_key(spec.id, i), n.label)}
            for i, n in enumerate(intro.flow, 1)
        ],
        "deps": list(spec.depends),
        "config_keys": config_keys,
        "llm": spec.llm,
        "tools": list(spec.tools),
    }
