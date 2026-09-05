# 永远的陪伴 Design Brief

> 定位：第三方作者插件。开发期寄放在仓库内置目录 `plugin/plugins/`（平台会按
> builtin 渠道扫描），但目标是走独立 Git 仓库 → Plugin Market 审核 → 上游 PR 的
> 官方收录流程。发布前必须完成 README「提交到官方」checklist，尤其是作者署名。
>
> 前身：潮汐时刻 (tide_moments)。v1.0.0 起更名并升级定位——从周期模拟插件
> 升维为全面陪伴插件（节律/情绪/日记/相处信号），潮汐/月相/涟漪/港湾意象
> 体系全部保留为插件的内部语言。

## Identity Lock
- plugin_id: `forever_companion`
- folder: `plugin/plugins/forever_companion/`
- name: `永远的陪伴`
- entry: `plugin.plugins.forever_companion:ForeverCompanionPlugin`
- main class: `ForeverCompanionPlugin`

## Purpose

为猫娘提供真实的"身体节律 + 情绪波动"模拟：
以锚点日期起算四阶段周期（潮汐期/回升期/活跃期/平稳期，内部键 menstrual/follicular/ovulatory/luteal），把当前阶段的身体感受以"耳边轻语"
的方式注入模型上下文；同时提供一组情绪动作 LLM 工具（冷战沉默/ebb_tide、已读不回/sea_fog、
敷衍应付/shallow_reef、情绪风暴/storm_surge、想要被安抚/seek_harbor、
心情转晴/rising_tide、心情手记/drift_bottle），由模型自主决定是否使用。插件不替猫娘做任何决定——只递状态、摆工具。

## Package Type and Capabilities
- package type: `plugin`（独立功能）
- capabilities:
  - callable entries：周期设置/查询/快进/重置、情绪状态查询与解除、日记查看与清空、
    碎片删除、个人日记翻阅、开关
  - LLM tools：12 个情绪与记录工具，模型在对话中自主调用
  - timer：每 20 秒轮询用户消息总线 + 检查情绪动作到期自动解除
  - message injection：`push_message(visibility=[], ai_behavior="read")` 把身体感受送入上下文，
    不触发独立回复、用户不可见
  - UI：Hosted TSX panel（周期总览、阶段标签、锚点/快进/重置/开关快捷操作、情绪状态、日记）
  - store：`PluginStore` 持久化周期锚点、偏移天数、情绪状态、日记

## First Version Scope

- 四阶段周期计算（锚点日期 + 周期长度；潮汐期长度/活跃日/活跃窗口默认自动演算，可关闭后手动覆盖），含手动快进天数
- 阶段感受提示词可配置（主体 + 早/午/晚微调），禁用词表防说漏嘴
- 对话注入：轮询 user_message 总线，检测到新用户消息且开启模拟时注入当前身体状态；
  注入频率策略 every_user_message / interval_n / on_trigger_keywords
- 情绪系统：LLM 工具自主决策模式（非原版三段式小模型筛选），动作带到期时间自动解除
- Hosted TSX 面板 + 快捷操作

## 连续心情机制（valence/arousal）

在离散情绪动作之上叠加一层连续心情状态，**只收集、只可视化，默认不注入她的上下文**
（不改动任何注入文本与门控指纹；唯一例外是下面的持续极端邀请）：

- 二维量：`valence ∈ [-1,1]`（坏→好）、`arousal ∈ [0,1]`（平静→激动），
  存在 `_MoodState`（沿用 `mood@<角色>` key，旧数据缺字段容忍、零迁移）
- 余波惰性衰减：不回调度器（插件无常驻事件循环），读取时按 `exp(-Δt/τ)` 把存储值
  折算到当前时刻——arousal 退得快（τ≈30 分钟）、valence 余波拖得长（τ≈4 小时）；
  只在下次有冲量/信号写入时把折算值落盘（`_current_affect`/`_apply_affect_impulse`）。
  arousal 的衰减目标是**静息基线**（`[mood].arousal_baseline`，默认 0.35）：
  高于基线回落、低于基线回升（homeostasis），从未喂过信号时当前值即 `(0, 基线)`——
  安装即显示静息水平；valence 不变（0 基线、向 0 衰减）
- 动作冲量：`_apply_mood_action` 唯一漏斗叠加 `_MOOD_AFFECT_IMPULSES` 映射
  （冷战沉默 -0.45/+0.25、已读不回 -0.35/+0.10、敷衍应付 -0.20/-0.05、情绪风暴 -0.55/+0.60、
  想要被安抚 -0.30/+0.35、心有涟漪 +0.15/+0.20、暖流涌动 +0.35/+0.15、满潮欢喜 +0.55/+0.45），
  先惰性衰减再叠加并 clamp 到域内；动作到期不加反向冲量（余波自然散去）
- `mood_rising_tide`（心情转晴，不落动作状态）给缓解冲量：负 valence 减半、arousal ×0.6，
  正 valence 不动
- 语气信号喂入：`_maybe_tone_sense` 分析成功（筛选/校正两种模式）后按 label 方向积分，
  步长 = confidence × 0.10（valence）/ confidence × 0.12（arousal），**单轮限幅**
  （防一句话打满）；neutral 微拉一格：valence 向 0 拉、arousal 向静息基线拉（不越过）。
  她的回复与用户消息**分开独立分析**（0.6.8 起，此前合并成一段出单 label、用户侧没有
  独立权重）：她的回复权重 1.0，用户消息按 `[emotion_sense].user_affect_weight`
  （默认 0.25，0=关闭）同向传导——互动氛围纳入考虑，但她的情绪表达绝对主导；
  校正模式仍只分析她（校正看她的表现，不该被用户侧稀释）。
  调宿主 `/api/emotion/analysis` 的请求体
  **不带 `lanlan_name`**——纯静默分析，避免宿主把结果推给前端改头像表情的副作用
- 面板实时指示：dashboard 的 mood payload 带 `affect`（两位小数，读取时惰性衰减）；
  状态栏小圆点颜色随 valence（正=暖琥珀/负=灰蓝/近零=中性灰）、arousal 驱动呼吸
  动画速度与光晕大小，tooltip 显示心情词（七档分桶：雀跃/明媚/微暖/平静/有点闷/低落/烦躁）。
  不做历史曲线、不落历史序列
- 持续极端邀请（0.6.8）：valence 越过 ±`[mood].extreme_invite_threshold`（默认 0.4）并持续
  `extreme_invite_after_minutes`（默认 20）→ 向她的上下文 push 一次明确的动作邀请
  （轻型动作排前引导，她仍可自主决定）；回到常态清零计时、换侧重新计时、动作生效中跳过、
  邀请后冷却 `extreme_invite_cooldown_minutes`（默认 30）；threshold 配 0 关闭
- 动作降刚性（0.6.8）：动作 hint 去硬锁（不再"必须先调 rising_tide"，情绪变了随时可调任何
  情绪工具切换）、校正提醒 window_turns 3→2、动作默认时长 20→10 分钟；
  状态栏无动作时不再显示"平静"徽标（避免与心情胶囊词表撞车）
## 时光日记与个人日记（0.7.0 重构）

原"心情手记 + 潮汐周记"重构为两个定位清晰的功能块：

### 时光日记（自动碎片 + 她的手记，混排时间线）

一本混合时间流，条目带 `source` 字段区分来源（`diary@<角色>` key 不变，旧数据
缺 source 按 self 容忍读取，零迁移）：

- **她的手记**（source=self）：原 `mood_drift_bottle` 工具不变，仍镜像 read 推送进
  宿主记忆管线（这是插件内容进入角色长期记忆的唯一受支持路径）
- **自动碎片**（source=auto）：小模型分析**用户消息**，捕获四类值得她记一辈子的片段——
  `like`/`dislike`（明确的喜好厌恶）、`important`（有分量/有含义的话）、`overstep`
  （对她的过激言行）。记**原话摘录**（quote，宿主事实抽取做不到的"原话存档"）
  + 第三人称短注（note）+ 置信度
- **提取通道**：挂进语气感知同一趟 recent 轮询（不增加 HTTP 次数），但**水位独立**
  （`last_fragment_marker`）——语气感知的 check_rate 抽样跳过的轮次仍会进碎片分析，
  碎片不吃概率抽样；提取必须走可自定义 prompt 的**直连槽位**（宿主 /api/emotion/analysis
  只做五分类，不适用），默认 summary 槽（宿主记忆抽取同层级），槽位无模型时功能
  自动休眠（节流 warning），其余不受影响
- **宁漏勿错**：capture 缺省按 false、kind 不在类型表/缺 quote 即丢弃、置信度门槛
  （默认 0.6）、60s 最小间隔；全部面板可见、可单条删除（`delete_diary_item`）、可清空
- **呈现（决定权在她）**：检索工具 `mood_recall_fragments`（按 kind/关键词过滤，
  她随时自主调用——聊到他的喜好时接得住，吵架时翻旧账）；另外重度负面动作
  （`_PROACTIVE_PAUSE_ACTIONS` 白名单）生效中又捕获到 overstep/dislike 类碎片时，
  低频（默认 30 分钟）轻语一句"你记得吗"（附一条相关旧碎片），她可忽略
- **与宿主记忆的边界**（调研结论，见 README"平台机制"）：偏好类事实宿主 Stage-1
  本来就在抽，碎片日记**重点记宿主不抽的**（情绪事件/过激行为/原话），且碎片
  **永不主动全量注入对话**——只有她自主检索 + 重度情绪期间单条轻语，避免与宿主
  记忆抽取重复污染上下文。碎片存储只进 PluginStore，不依赖已废弃的
  `ctx.query_memory`

### 个人日记（书页式连续日记，替代潮汐周记）

- **定位反转**：只给用户翻看，**不再镜像 read 推送**——不进她的对话上下文、
  不随对话历史被宿主记忆抽取（旧周记会镜像，0.7.0 去掉）
- **书页结构**（`journal@<角色>` key）：页列表 `{page_no, started_at, entries[]}`，
  每页至多 8 段（写满自动翻页），`new_page=true` 可主动翻新页；页数上限 52
  （超出淘汰最旧页）；页码按上一页号递增（淘汰后编号仍连续）
- **续写衔接**：工具结果带 `previous_lines`（写入前目标页最后两段）——只存在于
  写日记那轮的工具结果里（即时、不持久注入），让她自然接上上次写到哪，
  不违背"不注入"原则
- **页眉好感度**：每段落笔瞬间快照连续心情 valence，页眉显示该页均值 →
  面板分三档文案（偏暖/平和/偏低落）。宿主没有好感度系统，插件 valence 积累
  是最现成的量化来源；不新增历史序列
- **节奏**：距上一篇日记**最近一次落笔**满 `interval_days`（默认 7）才递邀请
  （续写同样重置计时）；删掉旧周记"攒够 N 条手记"的门槛；邀请文案保留
  "不想写就由你自己决定"
- **迁移**：旧 `weekly@<角色>` 一次性迁成个人日记页（每条周记一页、legacy 标记），
  旧 key 保留作备份；`prune_lanlan` 两把 key 都清

模块落点：碎片纯逻辑在 `fragments.py`（prompt 组装/回复解析/检索过滤/轻语判定）、
日记页纯逻辑在 `journal.py`（写入翻页/节奏判定/迁移/页眉统计），替代原 `weekly.py`。

### 0.7.1：面板重构 + 写作辅助

- **面板**：日记页改为页内 Tabs（时光日记/个人日记）；时光日记按日期分组
  （组头吸顶）+ 碎片原话语气泡样式 + "加载更多"分页（`get_diary` 加 offset，
  dashboard 仍只发最近 12 条）；个人日记改"目录 + 单页纸质阅读"双视图
  （目录行带页码圆徽/日期区间/心情彩色圆点——复用状态栏 `moodDotColor`；
  阅读页衬线字体、大行距）
- **结构化写作**：`mood_journal_write` 拆成引导字段
  events/thoughts/feelings/extra（至少填一），`assemble_journal_entry` 拼装成
  带引导小标题的成段日记（只填 extra 不加标题，尊重自由发挥）；单条上限放宽 900；
  续写衔接行带落笔日期前缀（"（2026-08-22 写的）…"）
- **邀请素材**：邀请文案带自上次落笔以来的心情词频 top3 + 新碎片数；新增
  `invite_journal` 入口（面板「请她写一篇」按钮，force 跳过节奏与 24h 节流，
  仍尊重 [journal].enabled）

### 我的日记（0.8.0）：关于主人的互动评价

第三本日记，**只给用户看**的客观评价（隔离等级比个人日记更严：不注入她的
上下文、不进宿主记忆管线、**不注册任何她可调用的 LLM 工具**——她连知道这本
日记存在的渠道都没有）。纯逻辑在 `review.py`（素材统计累加/双门槛判定/
成文 prompt 组装/回复解析截断/篇目追加淘汰），模型直连与落盘由主类完成：

- **素材纯本地累计**（平时零模型开销，随写随存进 `review@<角色>` 的 stats
  字段，成文后原子清零）：互动轮数+valence 采样（`_handle_new_user_message`
  喂入）、她的语气标签分布（`_feed_tone_affect` weight=1.0 路径喂入，用户侧
  低权重传导不计）、情绪动作事件（`_apply_mood_action` origin=user/self 区分
  命令演示与自主反应）、碎片原话（`_maybe_capture_fragments` 落盘时喂入）
- **双门槛先到先写**：攒满 `turns_threshold`（默认 50）轮或距统计起点满
  `days_threshold`（默认 7）天且期间有互动；挂机不写空篇。成文时一次直连
  槽位调用（碎片同款通道，默认 summary 槽）+ recent 窗口摘样作语境
- **成文口吻**：中性观察者（第三人称"他/她"），纯文字成段、无评分无徽标；
  prompt 明确要求如实记录负面行为不粉饰、不虚构素材外的事实
- **呈现**：面板日记页第三页签（目录 + 单篇纸质阅读 + 素材进度条）；
  `get_review`/`write_review_now`（素材不足 10 轮拒绝硬写）/`clear_review`
  三个入口；dashboard 带 `review_brief` 轻量概要进 5s 轮询
- **数据**：`review@<角色>` 一个 key 存 `{entries, stats}`（成文时篇目追加与
  stats 清零一次写入，避免中途崩溃错位）；保留 52 篇淘汰最旧；prune/reset
  一并清理；调试入口 `debug_review`（素材统计 + 资格判定 + force 成文）

### 0.9.0：陪伴型信息架构重构（总览仪表盘 + 精简状态条 + 模型通道）

定位升级：不做单纯的周期模拟，做"赋予 AI 更全面陪伴感"的插件。信息架构从
"版本地层堆砌"改为按用户心智组织：

- **顶部状态条**：瘦身为"她是谁 · 一句话状态 · 心情胶囊 · 总开关"，
  点击跳总览；月相环/天数/情绪详情全部下放总览页
- **总览页（overview.tsx）**：她的现在（月相环 C 位 + 阶段 + 当前心情卡 +
  情绪徽标）+ 近况与相处（三本日记速览 tile + **相处信号卡**）。
  相处信号卡是陪伴型可视化的标准化阵地：首两个信号 = 近 7 天相处活跃度
  （时光日记近 7 天条目数，纯统计）+ 我的日记素材进度；未来新信号往这里长
- **页签重划**：总览 / 日历 / 周期（她周期+状态注入合并）/ 情绪（情绪系统+
  语气感知+模型通道）/ 日记（三本浏览+日记功能设置同页）/ 设置（时区/调试/
  外观/危险区/角色名单）
- **模型通道卡（settings_tone.tsx 重写）**：三个小模型槽位（语气/碎片/成文）
  集中一处，各带状态灯（dashboard 下发 channel_status，复用
  diagnose_slot_dormancy）：ok / free_route（宿主免费端点服务端校验拒第三方
  直连，面板直说原因与解法）/ no_model / disabled；语气行为设置拆到
  settings_emotion.tsx，槽位只在通道卡
- dashboard 新增轻量字段：channel_status（三通道灯）+ week_activity
  （近 7 天时光日记条目数）；moodgauge.tsx 从情绪页移除（总览的
  MoodSummaryCard 替代），settings 里 diary 卡只留行为开关（槽位归通道卡）

zh-CN / en i18n

### 0.9.1：体验修正（随机锚点 + 总览愉悦度条 + 上传中文化）

- **随机化默认锚点**（cycle.randomized_default_anchor）：锚点缺失时不再默认
  "今天"（旧默认 = 安装当天必是潮汐日第一天，且所有用户都一样）；反推一个
  过去日期使今天落在本轮平稳期的随机位置，预留 3 天尾量（装完前几天不会
  立刻进潮汐期）。锚点经 _refresh_config 写入 shard 即固化，重启不重随；
  极端周期参数（平稳期容不下尾量）有兜底分支。日历据此反推出"过去"的
  阶段--她早就有自己的节律，只是今天才开始被观测
- **总览愉悦度条改为与 0~100 分制同向的左起填充**：旧双向条（中心为零点、
  从中心向两侧延伸）在静息态 50 分时只剩中点一小段颜色、左半全灰，观感
  像"异常"；现改为从左端填到当前分值（静息态=半条），中心刻度保留标出
  "中性 50 分"位置，填充色仍按正负取暖琥珀/灰蓝
- **面板外观上传中文化**：ImageUpload 显式传 placeholder（宿主 runtime 默认
  英文 "Upload image"），文件过大错误消息本地化（8 语言 i18n 新增
  uploadPlaceholder / errorTooLarge / errorTooLargeShort 三键）
- **月相环穿模修复**：扫掠暗盘（.tm-moon-shadow）原为半透明渐变 + backdrop-filter
  压暗下方亮盘，但面板运行环境该滤镜不生效--暗盘只剩自身 10~15% 透明渐变，
  该遮住的区域整个透出亮盘与陨石坑纹理（即用户看到的"穿模"）。改为实体不透明
  暗玻璃（亮色 #ccd5e2/#b3bfd2、暗色 #2a3548/#1e293b 双主题色），无头浏览器
  渲染 21 个月相 × 2 主题逐相验证：暗区零亮斑、零纹理透出、明暗分界干净
- **我的日记提示文案**：panel.review.hint 由"关于这段时间你怎么待她的客观
  评价…"换为"对我的记录…"（8 语言同步；语义更贴"这是关于我的记录"的
  用户视角）

### 1.1.0：相处统计（时光页 = 里程碑 + 热力图 + 月报）

第四块陪伴能力：把"看得见的相处"从 7 天信号升级为长期统计。
纯逻辑在 `stats.py`（按天聚合/徽章/连续天数/热力图窗口/月报封卷/纪念日判定，
与 review.py 同款"数据进数据出"纪律），落盘与埋点由主类完成：

- **数据安全（更新不丢）**：宿主 PluginStore 落在独立数据目录
  （`resolve_plugin_data_dir` → 数据根/plugins/forever_companion/data/store.db，
  与插件源码目录物理分离）——三条更新路径（Market 更新 / 导入 .neko-plugin
  覆盖 / 删除插件）都只动源码目录，`replace_plugin` 原子事务失败自动回滚，
  stats@<角色> 与全部陪伴记录在升级中原样存活。旧用户升级无 stats key 时
  `_ensure_shard` 走回填分支（三本日记时间戳点亮历史天）；卸载后重装数据
  同样留存——用户彻底清除走插件清零入口（README「平台机制」节已说明）
- **存储**：`stats@<角色>`（Store，与我的日记素材同款 per-lanlan 分片），
  `{first_seen, days: {YYYY-MM-DD: {turns, v_sum/v_n, tone, cold, made_up, warm}},
  milestones: {first_diary/first_journal/first_review}, anniversary: {last_pushed},
  months: {YYYY-MM: 封卷月报}}`；days 保留 730 天、月报保留 24 个月，
  首载时从三本日记时间戳回填活跃天（`backfilled` 标记幂等）
- **埋点**（与我的日记共用驱动点但口径独立——不受 [review].enabled 闸、
  成文永不清零）：`_handle_new_user_message`（每轮 + valence 采样）、
  `_feed_tone_affect` weight=1.0 主路径（当日语气分布）、
  `_apply_mood_action`（情绪事件，origin=user 不计）、
  `tool_feeling_better`（previous∈冷战类 → made_up 一次）、
  三本日记的写入点（第一篇里程碑）
- **纪念日**：满 30/60/…/365/… 天当天 `_maybe_anniversary_push` 递一条
  read 轻语（与阶段开场白同构，`[stats].anniversary_inject=false` 可关，
  当天去重水位）；她知不知道由她决定说不说
- **月报封卷**：tick 里 `seal_due_months` 跨月时快照上个月进 months
  （空月不封卷、幂等、超限淘汰最旧）；当月即时聚合实时变
- **口径**（README 有用户版说明）：相伴天数从首条互动起算；冷战只数
  origin=self 的冷战类动作；和好 = 她在负面情绪中主动调转晴（到期自然
  消散不算）；连续天数容忍"今天还没聊"从昨天延续
- **UI**：新「时光」页签 `moment.tsx`（徽章墙 + 数字摘要 + 热力图 div 格 +
  月报翻月）；dashboard 5s 轮询带 `stats_summary`（摘要+徽章，即时计算），
  热力图/月报走 `get_stats` 入口按需拉取；`clear_stats` 危险区入口；
  纪念日开关在日记页设置卡。i18n 8 语言 66 键
- 不注入她的上下文（纪念日轻语是唯一例外，可关）、不注册任何 LLM 工具、
  零模型调用（月报是模板组装不是成文）

### 1.1.6：热力图改日历年视图（起点截断 + 年份选择）

- 旧行为 = 固定滚动近 12 个月窗口，无论有没有数据都铺满网格——
  萌新装完第一眼是一整屏灰空格，与"记录相处的日子"的直觉相悖
- 新行为 = GitHub 式自然年视图：`heatmap_payload(stats, today, year=None)`
  下发 `start/end/years/year`；start = max(first_seen, 视图年 1 月 1 日)，
  end = min(视图年 12 月 31 日, 昨天)；years 从当年降序回退到最早明细年
  （受 730 天保留窗约束，通常至多跨 3 个自然年）
- 前端：铺格窗口改由后端 start/end 决定（`buildCalendarDays` 删除）；
  年份导航复用月报 `tm-month-nav` 样式（‹ ›，仅一年时隐藏，当年显示"今年"）；
  无可展示日子（全新安装 / 首互动就是今天）→ EmptyState，不再铺默认网格
- 窄网格弹性公式换档（`tm-gh-w12/w26`）：列数 ≤12/≤26 时换分母，
  格子不再被 /49 公式压到 7px 下限、缩成左上窄条
- `get_stats` 入口新增 `year` 参数（YYYY 字符串，非法/越界回落当年）；
  翻年份时面板保住当前正在看的月份，月报不跟着跳回当月

### 1.1.7：关闭状态提示并入状态条卡内

- 旧行为：模拟关闭/情绪关闭各渲染一条页级独立 Alert 条（tm-warnstrip），
  带边框底色与外边距，夹在状态条与内容区之间把页面拦腰切割，且与
  状态条"已关闭"徽标、右上角开关按钮信息四重重复
- 新行为：提示收进状态条卡片内部作第二行（.tm-statusbar 本就 flex-wrap，
  整宽子元素自动换行）：「模拟已关闭 · 点击开启」（行内链直接触发总开关，
  走原确认弹窗）、「情绪系统已关闭 · 去「情绪」页开启」（跳转情绪页签）；
  两条同现时并排自动换行；无提示时状态条与旧版完全一致
- 报错 danger Alert 保留原样（真错误需要醒目）；i18n 删
  panel.mood.disabledWarn、增 4 键（panel.offHintState/Action、
  panel.moodOffHintState/Action，8 语言）；旧 panel.disabledHint 本就
  只存在于代码 defaultValue，无 i18n 键残留

### 1.2.0：面板外观升级——图片图库 + 可调背景

旧"单图上传 + 遮罩滑杆"升维为两件事：**图库**（图片留存、自选壁纸、逐张增删）
与**背景调节**（十项参数，实时预览 + 卡底「保存外观」钮整包生效，另有「还原」）。

- **存储**（全部全局一份，与角色无关；均走 Store，不进 plugin.toml——图片
  data URL 是大 payload，`update_own_config` 有 4.5s 硬超时且面板无 config 写通道）：
  `panel_appearance`（归一后的参数 dict）、`gallery_index`（`{items:[{id,name,mime,
  size,added_at,thumb}], next}`，条目不含原图）、`gallery_img/<id>`（每张图一条
  `{data_url,mime,size,added_at}`，本体绝不进 5s 轮询 context）。
  纯逻辑（data URL 校验/参数 clamp/索引操作/旧图迁移）在 `core/appearance.py`，
  顺带消灭了 0.7.2 时代 panel.py 与 `__init__.py` 各写一份校验的"同款复刻"漂移隐患。
- **旧数据迁移**：旧 `panel_bg` 单图记录在首次 `get_panel_gallery` 时以后端
  （无图像库，生成不了缩略图）一次性迁成图库条目 `legacy`（dim 一并带走），
  原 key 保留作回滚备份；缩略图由面板拿到本体后用 canvas 画一张经
  `gallery_set_thumb` 回填（SVG 会污染 canvas，缩略图尽力而为，失败走棋盘占位样式）。
- **上传压缩管线（前端 canvas）**：导入方式二选一（默认自动压缩）——
  auto 缩到长边 2560 转 WebP q0.82（失败降 JPEG；仍不划算则回退原图），
  raw 原样入册（字节闸 4.4MB≈base64 5.9M 字符，卡在后端 6M 字符上限内）；
  GIF/SVG 不转码（动图/矢量语义）等同 raw。256px 缩略图两档都顺手生成。
  图库上限 24 张（4.5MB×24 是 store.db 体积与实用性的折中）。
- **入口**（六个，全 `@ui.action`+`@plugin_entry` 双装饰）：`get_panel_gallery`
  （索引+参数+迁移，一个请求开面板）、`gallery_add`、`gallery_remove`
  （删在用图时后端顺带清 `bg_id` 并回新 appearance）、`gallery_set_thumb`、
  `get_gallery_image`（按需拉本体）、`set_panel_appearance`（**整包替换**语义：
  未传字段回默认；悬空 bg_id 静默解除；参数宽容 clamp 不报错）。
- **渲染参数化**：styles.ts 原本无 CSS 变量，新增经 `tm-appearance-root` 包装层
  （div `display:contents`，不改布局也不改变 .tm-bg 的包含块）落成
  `--tm-glass`（毛玻璃半径）/ `--tm-card-k`（卡片底色不透明度系数，
  `rgba(var(--tm-card-rgb), calc(.72*k))`，主题 rgb 由暗色 media 切换）/
  `--tm-text-color`+`--tm-text-shadow`（文字浓度：`color-mix(in srgb, var(--text)
  N%, transparent)` + 随浓度自动加深的投影；老内核双声明回退原色）。
  背景本体（填充/位置/滤镜链/遮罩 opacity/模糊外扩 bleed）全走 .tm-bg 内联样式，
  blur>0 时 `inset` 负扩防滤镜边缘露底。所有默认值精确复刻 1.1.x 观感。
- **语义分工**：图库是资产库（增删即时持久）；"用哪张+怎么调"是设置
  （draft 实时预览、saved 才生效，切页签不丢 draft，关面板未保存即回退）。
- i18n 净增 63 键 ×8 语言（旧单图链路的 entries/fields/panel.appearance 死键清理）。

### 1.2.1：修复"重启后模拟开关复位"（Store 通电时序）

- **根因不在插件读写链**：toggle 落 `cycle@<角色>.enabled` 正确、`_enabled()` 的
  "分片 > [tide].enabled" 优先级也正确（用生产等价配置做全链路模拟时 enabled 能保住）。
  真因是**宿主启动时序**：SDK 在构造插件实例时 `ctx._effective_config` 还是 None，
  按 `resolve_store_enabled({})` 把 `PluginStore` 建成 `enabled=False`；disabled 态下
  `get` 静默返回 default、`set` 静默丢弃、都不报错。而 `startup()` 第一行就是
  `_load_state()`（全部持久状态在此读），通电只发生在其后的 `_refresh_config()` 里
  第一次 `config.dump()` 回灌时——于是每次重启都"读到空"，开关退回 fail-closed 的
  false、锚点重新随机，且 `shutdown()` 会把这份幻影整体回写，把上次真实保存的
  开关/锚点/快进/三本日记覆写掉（用户机 store.db 里 `enabled:False` +
  `lanlan_index`/`stats@` 两键从未出现，即此路径的痕迹）。
- **修法（只改插件，不动宿主）**：`mixins/shards.py` 新增 `_ensure_store_ready()`，在
  `_load_state()` 读任何东西之前探测 `store.enabled`，未通电则读一次 effective config
  触发宿主 `refresh_runtime_config` 翻转开关，最多 3 次、间隔 0.2s、单次读超时 2s；
  **读配置本身抛错则立即放弃**（宿主不可达时重试唤不醒，硬等会顶到
  `[plugin_runtime].timeout` 拉起超时）。探测只依赖公开属性 `store.enabled`，
  用 `getattr(..., True)` 兜底：FakeStore 等无该属性的实现按可用处理，未来宿主去掉
  门控也自动退化。
- **防覆写降级**：`_load_state()` 首行置 `self._state_trusted`；False 期间
  `shutdown()` 跳过全部分片整体回写并回 `saved:False`，`_ensure_shard` 的
  `lanlan_index`/`stats` 一次性落盘与 0.4.0 legacy 迁移一并推迟（此刻写下去的都是
  从空 store 推出的幻影）。宁可本次不落盘，也不毁历史；会话内单点写入仍各自落。
  `_save_shard_cycle` 在 store 未通电时补一条 warning，让"当场生效、重启即丢"可诊断。
- **默认 `_state_trusted=False`**：startup 之前（含 startup 失败）的任何 shutdown
  都不该覆写。
- **测试**：`tests/test_store_readiness.py` 用 `_GatedStore` 复刻宿主 enabled 门控
  （`get/set` 在未通电时静默空转），5 条覆盖迟通电必须读回 / 永不通电不得覆写 /
  正常路径照常落盘 / 无 enabled 属性不误伤 / 宿主不可达快速降级。已反向验证：
  把源码回退到 1.2.0 后这些测试以正确理由红（`_enabled()` 出 False、盘上
  `enabled`/`advance_days`/`params` 被抹、锚点 2026-08-01 漂到 2026-08-17）。
  `tests/conftest.py` 加 `boot_factory`（不预跑 `_ready`、可注入自定义 store/config）。
- **勘误（1.1.0「数据安全（更新不丢）」那条不成立）**：该节按"数据根与源码目录物理
  分离"断言三条更新路径都不碰数据。实测在**安装版**里
  `resolve_plugin_storage_dir` 与插件安装目录同一个根（
  `%LOCALAPPDATA%/N.E.K.O/plugins/<id>/` 既放源码也放 `data/store.db`），数据目录
  嵌套在插件目录内部，导入覆盖包会连同它一起重建（store.db 的 ctime 与全部行的
  created_at 都等于导入后首次启动时刻，且当天无任何 reset/clear 触发）——记录实际归零。
  开发源码树布局下确实分离，所以这个差异只在安装版显现。已把 README 相应三条改为
  如实描述（升级前不得假定记录保留；Market 路径待验证）。1.2.1 只修"读不回"，
  不修"被清掉"——后者属宿主侧安装布局，不在插件工作区内改。
- **残留风险**：若宿主是靠 startup 返回后才处理的 `CONFIG_UPDATE` 推送通电（startup
  期间下行消息被缓冲），则本次读配置唤不醒 store，走降级分支——症状当次仍在但数据
  不再受损，日志会明确留痕；根治需宿主在绑定 `ctx._instance` 后即刷新 runtime config，
  属平台侧时序，不在插件工作区内改。

### 1.2.2：自动保存链路加固（保存失败传播 + 中途通电门控 + 增量即时落盘）

针对"交互完重启软件丢数据"的全链路审计后分两批修复。审计结论：交互→落盘主干
本身健康（写入口都即时 `await store.set`，宿主 SQLite 逐写 commit，对强杀免疫），
漏洞集中在三处——shutdown 回写覆盖不全、宿主未通电窗口的假成功、不可信载入后的
幻影覆写残余路径。

**批次1（防线）**：
- shutdown 整体回写补 `stats@`/`review@`（此前只回写 cycle/mood/diary/journal：
  语气分布/情绪事件/和好等增量与我的日记素材平时"等下一条用户消息搭车落盘"，
  最后几轮聊完直接关软件必丢，正常退出也丢）。补刷有内容才写，不给空角色造壳键。
- `_ensure_shard` 顶部新增**中途通电门控**（`_retrust_state`）：启动未通电的
  不可信会话里内存分片是从"空"起步的幻影；v1.2.1 只挡住了 shutdown 整体回写,
  入口单路写没有门控——store 会话中后期回电后，任何一次面板操作/消息落盘都会
  把幻影整包覆写盘上真实历史（1.2.1 修复后仅存的毁数据路径）。门控检测到
  "不可信 + 已回电"即重跑 `_load_state` 换回盘上真实数据再放行本次写入；
  `_retrusting` 防重入。仍未回电则维持"当场生效、重启即丢"的既定降级契约。
  所有写路径（面板入口/工具归因/tick）都先过 `_ensure_shard`，挂点即全覆盖。
- 回归：`tests/test_store_readiness.py` +4（中途通电重载/未通电降级不毁盘/
  shutdown 补刷 stats·review/不可信 shutdown 连带跳过新键）；均已反向验证
  （回退修复后以正确理由红）。

**批次2（错误传播与搭车缺口）**：
- 统一出口 `_store_write`（not-ready warning + 真失败 warning + 回传 Result）/
  `_store_read`（读 Err 留痕，与"值不存在 Ok(None)"区分——过去读失败静默表现为
  "数据全空"零线索）/ `_persist_error`（多键聚合）；九个保存方法全部返回
  `Result[None]`。cycle 的 not-ready 文案语义保留（`(enabled=)` 后缀并入统一格式）。
- 用户可见写入口按结果传播 Err（toggle/锚点/快进/重置/update_settings/解除情绪/
  触发情绪/删碎片/三处 clear/write_review_now/prune_lanlan + 12 情绪工具 +
  手记/日记工具）：真写失败（磁盘满/DB 锁）不再"面板显示成功、盘上没写"；
  未通电空转不算失败（降级契约不变）。多键写任一 Err 即报 Err，前面不回滚
  （真失败极罕见、重试幂等，保持简单）。
- `_maybe_write_review` 落盘失败整体回滚：快照还原篇目与素材、不记里程碑、
  返回 `persist_failed`（面板映射为 Err）——过去"先改内存+清零素材再写且不看
  结果"，写失败会同时丢这篇与该段素材，且重启后旧素材复活重复成文。
- 搭车缺口补刷（消灭失真注释）：语气分析收尾 `_save_tone_sense_state`
  （mood+stats+review 同刷）、`_apply_mood_action`（动作事件即时进
  stats@/review@）、rising_tide 和好计数、tool_write_diary 的 first_diary
  里程碑即时落盘（对齐 first_journal/first_review）。
- 回归：`tests/test_persist_errors.py` 10 条（`_ErrStore` 对指定 key 注入真
  Err）；回退批次2 源码后 9/10 以正确理由红。
- 已知残留（有意不动）：tick/whisper/shutdown/host_coord 等非用户入口写失败仅
  留 warning 不回 Err（后台链路不该变成会失败的入口，shutdown 兜底已覆盖）；
  prune_lanlan 部分失败后重试会被"角色不在名单"拒绝（Err 已如实报，残留键可见
  需带外处理）；同轮多 1-2 次本地 SQLite 写（批次1 审计已认可开销可忽略）。

### 1.2.2 审查轮（复核批次1/2 的复审修复，同版未发布故并入 1.2.2）

批次2 的"全链路审计"存在三处漏网与一处文档不实，复核后同轮修复：

- **P1 外观/图库并入统一出口**：图库与外观的全部读写（`gallery_index` /
  `gallery_img/<id>` / `panel_appearance` / `panel_bg` 迁移读）当年直连
  `self.store.set/get/delete`，绕过 `_store_write`/`_store_read`——未通电期间
  导入壁纸/保存外观"面板显示成功、盘上没写"且零 warning（README 却声称
  "外观也有此预警"）。现状：全部改道统一出口（新增 `_store_delete`：未通电留
  not-deleted 预警、真失败留痕回传）；未通电仍走"当场生效"降级契约，但自此
  全键一致留痕。幻影覆写在该块本不成立（图库无内存缓存，每次读盘合并再写）；
  `gallery_remove` 索引写失败回滚 blob 由入口 Err 传播、blob 删除保持
  best-effort（索引先除名即对用户不可见，残留 blob 无引用不致错乱）。
- **P2 主动搭话水位原子化**：`proactive_state` 四处落盘全不检查且顺序为
  "先翻总开关→后存水位"——水位真失败+强杀留下"开关已关+盘上无水位"，重启
  被误判"用户本来就没开"，主动搭话永久卡死。修复：新增 `_snapshot_proactive`
  （纯函数，`core/state.py`）+ `_proactive_persisted` 脏检查快照，
  `_persist_proactive_state` 成为水位唯一落盘出口（成功才同步快照，失败留脏，
  监督循环每趟 10s 收尾自动补写）；暂停改为**水位先落盘才准翻开关**（写失败
  撤销标记、回传 Err、不制造无据可查的关闭），恢复改为**开关先复原再清水位**
  （清除失败保留记录幂等重试）；`_maybe_sync_proactive_pause` 回传 Err，由
  `_apply_mood_action`/`lift_mood`/`reset_all`/`prune_lanlan` 纳入
  `_persist_error` 聚合，对用户可见。存量已卡死用户（修复前产生的状态）无法
  与"用户自己关的"区分，不做猜测恢复，README 如实记为限制。
- **P3 tick 自愈门控上提**：`_ensure_shard` 的中途通电门控要求"先有人碰分片"
  才触发，而 tick 在 `any_shard_enabled` 处即短路（幻影全关），"不可信启动 +
  store 中途回电 + 用户没碰面板/工具"组合下注入与情绪链路整场静默死掉（数据
  安全、功能停摆）。修复：同款门控（三行属性判断零成本）提上 `_supervise_once`
  第一行——tick/面板轮询 dashboard/各入口都先经此，恢复自愈；`_ensure_shard`
  门控保留（覆盖首条 tick 之前的入口调用）。
- **P4 随机锚点可信即落盘**：`_refresh_config` 的随机默认锚点过去只写内存、
  靠"后续任意 cycle 写捎带"，注释却写"立即落盘固化"（自相矛盾）；强杀在首笔
  cycle 写之前 → 锚点重新随机。修复：可信会话当场 `_save_shard_cycle`；
  不可信会话仍只写内存（落盘即幻影覆写）。注释按实际行为改写。
- 回归：`tests/test_save_chain_review.py` 8 条（水位写失败不翻开关+恢复先翻
  后清/未通电外观留痕/索引写失败回滚 blob/外观真失败传播/tick 自愈/锚点即
  落盘）；回退源码后 5/8 以正确理由红（其余 3 条锁的是修复前既有的行为面）。
  全套 294 绿。

## Out of Scope

- 情绪日记的 LLM 自动总结写入（v1 只提供模型手写日记工具与人工查看）
- ~~多角色（多 lanlan）独立周期；v1 单全局状态~~ → **0.5.0 已实现**：per-lanlan 独立状态
  （Store key 按角色分片 `cycle@<角色名>`/`mood@<角色名>`/`diary@<角色名>`，另有 `lanlan_index`、
  全局覆盖层 `settings`、全局主动搭话暂停引用计数 `proactive_state`；旧版单份数据升级后首次启动
  自动迁移归属当前角色，旧 key 保留备份）。面板无手动角色切换器，始终自动跟随宿主当前角色
  （面板 5s 轮询 dashboard + 插件 15s 缓存读 `GET /api/characters/current_catgirl`，切卡后十几秒内跟上），
  dashboard 仍返回 `lanlan_list` 供面板只读展示已有状态的角色名单
- 原版三段式情绪筛选管线（筛选→决策→翻译）

## Inferred Technical Needs
- plugin.toml sections: `[plugin]`, `[plugin.i18n]`, `[plugin.ui]` panel, `[plugin_runtime]`, `[plugin.store]`, `[tide]`
- SDK surfaces: `@neko_plugin`, `@plugin_entry`, `@llm_tool`, `@timer_interval`, `@lifecycle`,
  `push_message`, `self.store`, `self.config`, `tr()`
- UI surfaces: `[[plugin.ui.panel]]` hosted-tsx `ui/panel.tsx`（state:read, config:read, action:call）。
  面板为多文件模块结构：`panel.tsx` 入口组装 + `types.ts` / `utils.ts` / `styles.ts` 共享层，
  六个顶级页签——`calendar.tsx` 日历 / `settings_cycle.tsx` 周期 / `settings_inject.tsx` 注入 /
  `settings_mood.tsx`+`settings_diary.tsx`+`settings_tone.tsx` 情绪（情绪系统+碎片+语气感知）/ `diary.tsx` 日记（时光日记时间线+个人日记书页）/
  `manage.tsx` 管理（危险区+角色名单）；设置类页签各自带 `savebar.tsx` 吸底保存条，
  顶部 `statusbar.tsx`（含 `ring.tsx` 圆环）常驻；
  受 hosted-tsx 约束：仅声明式单绑定导出、无循环依赖、`export const` 类型注解不能含顶层逗号
  （泛型用类型别名绕开），**不支持 SVG**（运行时 mount 用 createElement 而非 createElementNS，
  图形一律用 CSS/div 实现，如 ring.tsx 的月相盘），提交前跑 `npm run check-hosted-tsx -- plugin/plugins/forever_companion`。
  另有一个校验门抓不到的链接器坑（0.6.2 修复）：JSX 闭合标签 `</...>` 的 `/` 会被运行时
  链接器误判为正则字面量起始（前一字符 `<` 在其正则启发式集合内），其后所有 `export` 声明被吞，
  面板整页空白——因此每个 ui 文件内 export 声明必须排在任何 JSX 闭合标签之前
  （辅助组件如 statusbar.tsx 的 MoodDot 放文件尾部，靠函数声明提升被引用）
- state/config: `[tide]` / `[mood]` / `[fragments]` / `[journal]` / `[review]` / `[emotion_sense]` 配置段 +
  PluginStore 键（0.5.0 起按角色分片 `cycle@<角色名>` / `mood@<角色名>` / `diary@<角色名>` /
  `journal@<角色名>`（0.7.0 起，旧 `weekly@` 迁入后保留备份）/ `review@<角色名>`
  （0.8.0 起，`{entries, stats}` 合一存储），加 `lanlan_index` / `settings` /
  `proactive_state` 三个全局键；1.2.0 起另有全局外观键 `panel_appearance` /
  `gallery_index` / `gallery_img/<id>`（旧单图 `panel_bg` 仅迁移读，保留备份））
- lifecycle/background work: startup 时刷新运行配置并注册；timer 每 10s 轮询总线与到期检查；
  plugin_runtime.auto_start=true 随宿主自动启动（切角色卡等操作会重启插件服务，
  不自动启动会静默消失），知情同意由 [tide].enabled=false fail-closed 保证
- external integrations: 无外部服务

## Read Context Plan
- 参考 `game_agent_minecraft`（push_message read 注入）、`memo_reminder`（store+timer）、
  `sts2_autoplay`（llm_tool+tr+ui.action）三个官方插件
- `.agent/skills/neko-plugin/references/*` 全部契约文档

## Write Workspace
`plugin/plugins/forever_companion/`

## Risk Follow-ups
- 平台没有向插件派发用户聊天消息的通道（`@message(source="chat")` 无 emitter，属死代码），
  故采用 warthunder 已验证的总线轮询方案（`ctx.bus.memory.get_sync("default")` 读
  `type="user_message"` 记录），不修改平台代码。
