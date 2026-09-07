// 日记页：页内 Tabs 切换 时光日记（日期分组时间线 + 加载更多）/ 个人日记（目录 + 单页纸质阅读）
// / 我的日记（关于主人的互动评价：目录 + 单篇阅读 + 素材进度）
// hosted-tsx 约束：唯一 export 在任何 JSX 闭合标签之前；辅助组件放文件尾部靠函数声明提升被引用
import { Button, Card, EmptyState, Tabs } from "@neko/plugin-ui"
import { useEffect, useLocalState, useRef, useState } from "@neko/plugin-ui"
import type { DiaryItem, JournalPage, JournalPageHeader, ReviewEntry, ReviewProgress, TFunc } from "./types"
import { fragmentKindKey, journalTrendKey, moodDotColor } from "./utils"

export function DiaryPane(props: {
  t: TFunc
  diary: DiaryItem[]
  diaryTotal: number
  fragmentTotal: number
  journalIndex: JournalPageHeader[]
  invitePending?: boolean
  lanlan?: string
  reviewBrief?: { enabled?: boolean; entries?: number; progress_turns?: number; turns_threshold?: number }
  onClearDiary: () => void
  onDeleteFragment: (ts: string) => void
  onLoadJournal: () => Promise<JournalPage[]>
  onLoadMoreDiary: (offset: number) => Promise<{ items: DiaryItem[]; hasMore: boolean }>
  onInviteJournal: () => void
  onLoadReview: () => Promise<{ entries: ReviewEntry[]; progress: ReviewProgress }>
  onWriteReviewNow: () => void
  onClearReview: () => void
  settingsChildren?: any
}) {
  const {
    t, diary, diaryTotal, fragmentTotal, journalIndex, invitePending, lanlan, reviewBrief,
    onClearDiary, onDeleteFragment, onLoadJournal, onLoadMoreDiary, onInviteJournal,
    onLoadReview, onWriteReviewNow, onClearReview, settingsChildren,
  } = props

  // 页内 Tab 持久化：像顶部页签一样记住上次停留在哪一本
  const [tab, setTab] = useLocalState("tide.diary.tab", "time")

  // ---- 时光日记：dashboard 初始 12 条 + "加载更多"追加分页 ----
  const [fullDiary, setFullDiary] = useState<DiaryItem[] | null>(null)
  const [diaryHasMore, setDiaryHasMore] = useState(false)
  const [diaryLoading, setDiaryLoading] = useState(false)
  const timeline = fullDiary || diary
  // ---- 个人日记：整本（目录数据源）+ 当前翻开页（null = 目录视图）----
  const [pages, setPages] = useState<JournalPage[]>([])
  const [bookLoaded, setBookLoaded] = useState(false)
  const [bookLoading, setBookLoading] = useState(false)
  const [openPageNo, setOpenPageNo] = useState<number | null>(null)
  const openIdx = openPageNo === null ? null : pages.findIndex((p) => (p.page_no || 0) === openPageNo)
  const visiblePage = openIdx !== null && openIdx >= 0 ? pages[openIdx] : null
  // 书页指纹（1.2.3）：页码:段数:末笔时刻 逐页拼接。mood_journal_write 默认
  // 续写在当前页——页数不变，只看页数的旧检测让她续写的段落永远等不到自动
  // 刷新；指纹把"段数/末笔时刻"也纳入观察面
  const bookFingerprint = journalIndex
    .map((p) => `${p.page_no || 0}:${p.entry_count || 0}:${p.last_ts || ""}`)
    .join("|")
  const bookFpSeen = useRef<string | null>(null)
  // ---- 我的日记：全部篇目（倒序）+ 素材进度 + 当前翻开篇（null = 目录视图）----
  const [reviewEntries, setReviewEntries] = useState<ReviewEntry[]>([])
  const [reviewProgress, setReviewProgress] = useState<ReviewProgress>({})
  const [reviewLoaded, setReviewLoaded] = useState(false)
  const [reviewLoading, setReviewLoading] = useState(false)
  const [openReviewTs, setOpenReviewTs] = useState<string | null>(null)
  const visibleReview = openReviewTs === null ? null
    : (reviewEntries.find((item) => String(item.ts || "") === openReviewTs) || null)

  // 重拉我的日记（挂载/切角色/写完新篇/手动刷新共用）
  async function reloadReview() {
    if (reviewLoading) return
    setReviewLoading(true)
    try {
      const loaded = await onLoadReview()
      setReviewEntries(loaded.entries || [])
      setReviewProgress(loaded.progress || {})
      setReviewLoaded(true)
    } catch (err) {
      console.warn("[forever_companion] load review failed:", err)
      setReviewLoaded(true)
    } finally {
      setReviewLoading(false)
    }
  }

  // 重拉个人日记整本（挂载/切角色/"她写了新页"/手动刷新共用）
  async function reloadBook() {
    if (bookLoading) return
    setBookLoading(true)
    try {
      const loaded = await onLoadJournal()
      setPages(loaded)
      setBookLoaded(true)
      } catch (err) {
        // 失败也终止 loading，显示空态；console 留痕便于排查（如动作未暴露 403）
        console.warn("[forever_companion] load journal failed:", err)
        setBookLoaded(true)
      } finally {
      setBookLoading(false)
    }
  }

  // 切角色：重置时光日记分页与翻开的页码 + 重拉日记本与我的日记
  useEffect(() => {
    setFullDiary(null)
    setDiaryHasMore(false)
    setOpenPageNo(null)
    setOpenReviewTs(null)
    bookFpSeen.current = null  // 指纹基线作废，按新角色的书重认（1.2.3）
    reloadBook()
    reloadReview()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lanlan])

  // 她在面板开着的时候写了/续写了：journal_index 指纹变化 → 自动重拉整本
  //（1.2.3：检测面从页数升级为 页码:段数:末笔时刻 指纹——续写不动页数，
  // 旧逻辑下她连写几段面板毫无动静，只能手动刷新）
  useEffect(() => {
    if (bookFpSeen.current === null) {
      bookFpSeen.current = bookFingerprint
      return
    }
    if (bookFingerprint !== bookFpSeen.current) {
      bookFpSeen.current = bookFingerprint
      if (bookLoaded) reloadBook()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookFingerprint])

  // 我的日记写了新篇：dashboard 的 review_brief 篇数变化 → 自动重拉全部篇目
  useEffect(() => {
    if (reviewLoaded && reviewBrief && Number(reviewBrief.entries || 0) !== reviewEntries.length) {
      reloadReview()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewBrief && reviewBrief.entries])

  async function loadMore() {
    if (diaryLoading) return
    setDiaryLoading(true)
    try {
      const base = fullDiary || diary
      const seen = new Set(base.map((item) => String(item.ts || "")))
      const res = await onLoadMoreDiary(base.length)
      const fresh = (res.items || []).filter((item) => !seen.has(String(item.ts || "")))
      setFullDiary([...base, ...fresh])
      setDiaryHasMore(!!res.hasMore)
    } catch (err) {
      // 加载失败静默：按钮恢复可点，下次重试；console 留痕便于排查
      console.warn("[forever_companion] load more diary failed:", err)
    } finally {
      setDiaryLoading(false)
    }
  }

  return (
    <div className="tm-pane">
      <Tabs
        id="tide-diary-tabs"
        activeId={tab}
        onChange={(id: string) => { setTab(id) }}
        items={[
          {
            id: "time",
            label: t("panel.diary.tabTime", { defaultValue: "时光日记" }),
            content: (
              <Card title={t("panel.diary.title", { defaultValue: "时光日记" })}>
                {timeline.length > 0 ? (
                  <div className="tm-diary">
                    <div className="tm-diary-toolbar">
                      <span className="tm-diary-count">
                        {t("panel.diary.summary", { defaultValue: "共 {total} 条 · 她手写 {self} · 自动碎片 {auto}" })
                          .replace("{total}", String(diaryTotal))
                          .replace("{self}", String(diaryTotal - fragmentTotal))
                          .replace("{auto}", String(fragmentTotal))}
                      </span>
                      <Button tone="danger" onClick={onClearDiary}>
                        {t("actions.clear_diary.label", { defaultValue: "清空时光日记" })}
                      </Button>
                    </div>
                    <TimelineView t={t} items={timeline} onDelete={onDeleteFragment} />
                    {fullDiary === null || diaryHasMore ? (
                      <div className="tm-diary-more">
                        <Button onClick={() => { loadMore() }} disabled={diaryLoading}>
                          {diaryLoading
                            ? t("panel.diary.loadingMore", { defaultValue: "翻找中…" })
                            : t("panel.diary.loadMore", { defaultValue: "加载更多" })}
                        </Button>
                      </div>
                    ) : (
                      <div className="tm-diary-end">{t("panel.diary.endReached", { defaultValue: "已经翻到最早的一篇了" })}</div>
                    )}
                  </div>
                ) : (
                  <EmptyState
                    title={t("panel.diary.emptyTitle", { defaultValue: "日记本还是空的" })}
                    description={t("panel.diary.emptyDesc", { defaultValue: "她主动写下的手记、以及小模型从对话里替她记下的重要片段，都会出现在这里。" })}
                  />
                )}
              </Card>
            ),
          },
          {
            id: "journal",
            label: t("panel.journal.tabJournal", { defaultValue: "个人日记" }),
            content: (
              <Card title={t("panel.journal.title", { defaultValue: "个人日记" })}>
                <div className="tm-journal-toolbar">
                  <span className="tm-diary-count">
                    {t("panel.journal.count", { defaultValue: "共 {n} 页" }).replace("{n}", String(pages.length || journalIndex.length))}
                  </span>
                  <span className="tm-journal-actions">
                    <Button onClick={() => { reloadBook() }} disabled={bookLoading}>
                      {t("panel.journal.refresh", { defaultValue: "刷新" })}
                    </Button>
                    <Button tone="primary" onClick={onInviteJournal}>
                      {t("panel.journal.invite", { defaultValue: "请她写一篇" })}
                    </Button>
                  </span>
                </div>
                {invitePending ? (
                  <div className="tm-derived">
                    {t("panel.journal.invitePending", { defaultValue: "邀请已递出，正等她落笔——她说写就写、说缓就缓，下一页会自己出现在这里。" })}
                  </div>
                ) : null}
                <div className="tm-derived">
                  {t("panel.journal.hint", { defaultValue: "她每隔一段时间自己写的一篇日记，只给你看；翻页看看她这段时间在想什么。" })}
                </div>
                {bookLoaded && pages.length === 0 ? (
                  <EmptyState
                    title={t("panel.journal.emptyTitle", { defaultValue: "还没有写过日记" })}
                    description={t("panel.journal.emptyDesc", { defaultValue: "点右上角「请她写一篇」递个邀请；当她愿意写时，第一页会出现在这里。" })}
                  />
                ) : visiblePage ? (
                  <PageReader
                    t={t}
                    page={visiblePage}
                    totalPages={pages.length}
                    hasPrev={openIdx > 0}
                    hasNext={openIdx < pages.length - 1}
                    onBack={() => { setOpenPageNo(null) }}
                    onPrev={() => { if (openIdx > 0) setOpenPageNo(pages[openIdx - 1].page_no || null) }}
                    onNext={() => { if (openIdx < pages.length - 1) setOpenPageNo(pages[openIdx + 1].page_no || null) }}
                  />
                ) : (
                  <TocView t={t} index={pages.length ? pages : journalIndex} onOpen={(no) => { setOpenPageNo(no) }} loading={bookLoading} />
                )}
              </Card>
            ),
          },
          {
            id: "review",
            label: t("panel.review.tabReview", { defaultValue: "我的日记" }),
            content: (
              <Card title={t("panel.review.title", { defaultValue: "我的日记" })}>
                <div className="tm-journal-toolbar">
                  <span className="tm-diary-count">
                    {t("panel.review.count", { defaultValue: "共 {n} 篇" }).replace("{n}", String(reviewEntries.length))}
                  </span>
                  <span className="tm-journal-actions">
                    <Button onClick={() => { reloadReview() }} disabled={reviewLoading}>
                      {t("panel.journal.refresh", { defaultValue: "刷新" })}
                    </Button>
                    <Button
                      tone="primary"
                      onClick={onWriteReviewNow}
                      disabled={reviewLoading || !!(reviewBrief && reviewBrief.writing)}
                    >
                      {reviewBrief && reviewBrief.writing
                        ? t("panel.review.writing", { defaultValue: "正在写…" })
                        : t("panel.review.writeNow", { defaultValue: "立即写一篇" })}
                    </Button>
                    <Button tone="danger" onClick={onClearReview}>
                      {t("panel.review.clear", { defaultValue: "清空" })}
                    </Button>
                  </span>
                </div>
                {reviewBrief && reviewBrief.writing ? (
                  <div className="tm-derived">
                    {t("panel.review.writingHint", { defaultValue: "她正把这段时间写下来，写完会自动出现在这里，不用守着。" })}
                  </div>
                ) : null}
                <div className="tm-derived">
                  {t("panel.review.hint", { defaultValue: "对我的记录" })}
                </div>
                {visibleReview ? (
                  <ReviewReader
                    t={t}
                    entry={visibleReview}
                    onBack={() => { setOpenReviewTs(null) }}
                  />
                ) : (
                  <ReviewProgressView
                    t={t}
                    progress={reviewProgress}
                    entries={reviewEntries}
                    loaded={reviewLoaded}
                    loading={reviewLoading}
                    onOpen={(ts) => { setOpenReviewTs(ts) }}
                  />
                )}
              </Card>
            ),
          },
        ]}
      />
      {settingsChildren}
    </div>
  )
}

// 时光日记时间线：按日期分组的卡片流（组头吸顶），手记暖纸色、碎片蓝调气泡
function TimelineView(props: { t: TFunc; items: DiaryItem[]; onDelete: (ts: string) => void }) {
  const { t, items, onDelete } = props
  const groups: Array<{ day: string; rows: DiaryItem[] }> = []
  for (const item of items) {
    const day = dayKeyOf(item.ts)
    const last = groups[groups.length - 1]
    if (last && last.day === day) last.rows.push(item)
    else groups.push({ day, rows: [item] })
  }
  return (
    <div className="tm-timeline">
      {groups.map((group) => (
        <div className="tm-day-group" key={group.day}>
          <div className="tm-day-head">
            <span>{dayLabelOf(group.day, t)}</span>
            <span className="tm-day-count">{t("panel.diary.dayCount", { defaultValue: "{n} 条" }).replace("{n}", String(group.rows.length))}</span>
          </div>
          {group.rows.map((item) => (
            <DiaryRow key={String(item.ts || "")} t={t} item={item} onDelete={onDelete} />
          ))}
        </div>
      ))}
    </div>
  )
}

// 时间线单行：她手写的显示心情与正文，自动碎片显示类型徽标、原话摘录与删除按钮
//（key 由列表处传入，受限运行时会把它并入 props 做类型检查，故声明在此）
function DiaryRow(props: { key?: string; t: TFunc; item: DiaryItem; onDelete: (ts: string) => void }) {
  const { t, item, onDelete } = props
  const isAuto = String(item.source || "self") === "auto"
  if (isAuto) {
    return (
      <div className="tm-tl-row" data-source="auto">
        <div className="tm-tl-head">
          <span className="tm-tl-badge" data-kind={item.kind || "important"}>
            {t(fragmentKindKey(item.kind), { defaultValue: String(item.kind || "") })}
          </span>
          <span className="tm-tl-ts">{fmtTs(item.ts)}</span>
          <span className="tm-tl-spacer" />
          <button className="tm-tl-delete" type="button" onClick={() => onDelete(String(item.ts || ""))}>
            {t("panel.diary.delete", { defaultValue: "删除" })}
          </button>
        </div>
        <div className="tm-tl-quote">「{item.quote}」</div>
        {item.note ? <div className="tm-tl-note">{item.note}</div> : null}
      </div>
    )
  }
  return (
    <div className="tm-tl-row" data-source="self">
      <div className="tm-tl-head">
        <span className="tm-tl-badge" data-kind="self">{t("panel.diary.selfBadge", { defaultValue: "她写" })}</span>
        {item.mood ? <span className="tm-tl-mood">{item.mood}</span> : null}
        <span className="tm-tl-ts">{fmtTs(item.ts)}</span>
      </div>
      <div className="tm-tl-entry">{item.entry}</div>
    </div>
  )
}

// 个人日记目录：每页一行（页码圆徽 + 日期区间 + 心情彩色圆点 + 段数），点开进入单页阅读
function TocView(props: {
  t: TFunc
  index: Array<JournalPageHeader & { entries?: Array<{ text?: string }> }>
  onOpen: (pageNo: number) => void
  loading: boolean
}) {
  const { t, index, onOpen, loading } = props
  if (!index.length) {
    return <div className="tm-derived">{loading ? t("panel.journal.loading", { defaultValue: "翻开日记本…" }) : ""}</div>
  }
  return (
    <div className="tm-toc">
      {index.map((page) => (
        <button
          key={String(page.page_no || "")}
          type="button"
          className="tm-toc-row"
          onClick={() => onOpen(Number(page.page_no || 0))}
        >
          <span className="tm-toc-no">{t("panel.journal.pageShort", { defaultValue: "页" })}{page.page_no}</span>
          <span className="tm-toc-range">{journalRangeLabel(page) || t("panel.journal.noDate", { defaultValue: "未注明日期" })}</span>
          <span
            className="tm-mood-dot"
            title={t(journalTrendKey(page.mood_avg), { defaultValue: "" })}
            style={{ background: page.mood_avg === null || page.mood_avg === undefined ? "rgba(148,163,184,.5)" : moodDotColor(page.mood_avg) }}
          />
          <span className="tm-toc-meta">
            {t("panel.journal.entryCount", { defaultValue: "{n} 段" }).replace("{n}", String(page.entry_count ?? 0))}
          </span>
          {page.legacy ? <span className="tm-toc-legacy">{t("panel.journal.legacy", { defaultValue: "旧版周记" })}</span> : null}
          <span className="tm-toc-arrow">›</span>
        </button>
      ))}
    </div>
  )
}

// 单页纸质阅读视图：衬线字体 + 大行距 + 纸张底色；顶栏返回目录，底栏上一页/下一页
function PageReader(props: {
  t: TFunc
  page: JournalPage
  totalPages: number
  hasPrev: boolean
  hasNext: boolean
  onBack: () => void
  onPrev: () => void
  onNext: () => void
}) {
  const { t, page, totalPages, hasPrev, hasNext, onBack, onPrev, onNext } = props
  const trendKey = journalTrendKey(page.mood_avg)
  return (
    <div className="tm-book">
      <div className="tm-book-topbar">
        <Button onClick={onBack}>{t("panel.journal.backToToc", { defaultValue: "← 目录" })}</Button>
        <span className="tm-book-pageno">
          {t("panel.journal.pageN", { defaultValue: "第 {n} 页" }).replace("{n}", String(page.page_no || ""))}
          {page.legacy ? ` · ${t("panel.journal.legacy", { defaultValue: "旧版周记" })}` : ""}
        </span>
        <span className="tm-book-meta">{journalRangeLabel(page)}</span>
        <span className="tm-book-trend">
          <span
            className="tm-mood-dot"
            style={{ background: page.mood_avg === null || page.mood_avg === undefined ? "rgba(148,163,184,.5)" : moodDotColor(page.mood_avg) }}
          />
          {t(trendKey, { defaultValue: "" })}
        </span>
      </div>
      <div className="tm-book-entries tm-paper">
        {(page.entries || []).map((entry, idx) => (
          <div className="tm-book-entry" key={String(entry.ts || idx)}>
            <div className="tm-book-entry-ts">{fmtTs(entry.ts)}</div>
            <div className="tm-book-entry-text">{entry.text}</div>
          </div>
        ))}
      </div>
      <div className="tm-book-nav">
        <Button onClick={onPrev} disabled={!hasPrev}>
          {t("panel.journal.prev", { defaultValue: "上一页" })}
        </Button>
        <span className="tm-book-indicator">{page.page_no} / {totalPages}</span>
        <Button onClick={onNext} disabled={!hasNext}>
          {t("panel.journal.next", { defaultValue: "下一页" })}
        </Button>
      </div>
    </div>
  )
}

// ISO 时间戳 → "MM-DD HH:mm"（年月日分组与单页区间各自另切）；坏数据原样返回
function fmtTs(ts?: string): string {
  const raw = String(ts || "")
  if (!raw) return ""
  return raw.replace("T", " ").slice(5, 16)
}

// ts → 日期 key（YYYY-MM-DD）
function dayKeyOf(ts?: string): string {
  return String(ts || "").slice(0, 10) || "----"
}

// 日期 key → 分组头文案："2026年8月29日"；坏 key 回退 i18n 的"未注明日期"
function dayLabelOf(day: string, t: TFunc): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day)
  if (!m) return t("panel.journal.noDate", { defaultValue: "未注明日期" })
  return `${Number(m[1])}年${Number(m[2])}月${Number(m[3])}日`
}

// 页的日期区间：起始日期 ~ 最后落笔日期（同天只显示一个）
function journalRangeLabel(page: JournalPageHeader): string {
  const start = String(page.started_at || "").replace("T", " ").slice(0, 10)
  const last = String(page.last_ts || "").replace("T", " ").slice(0, 10)
  if (!start && !last) return ""
  if (!last || start === last) return start
  return `${start} ~ ${last}`
}

// 我的日记目录 + 素材进度：进度条显示距下一次成文攒了多少轮；点开一篇进入阅读
function ReviewProgressView(props: {
  t: TFunc
  progress: ReviewProgress
  entries: ReviewEntry[]
  loaded: boolean
  loading: boolean
  onOpen: (ts: string) => void
}) {
  const { t, progress, entries, loaded, loading, onOpen } = props
  const turns = Number(progress.turns || 0)
  const threshold = Math.max(1, Number(progress.turns_threshold || 50))
  const ratio = Math.min(1, turns / threshold)
  if (!entries.length) {
    return loaded ? (
      <EmptyState
        title={t("panel.review.emptyTitle", { defaultValue: "还没有写过评价" })}
        description={t("panel.review.emptyDesc", { defaultValue: "攒够一段时间的相处素材后会自动写第一篇；也可以点右上角「立即写一篇」（至少需要 10 轮互动）。" })}
      />
    ) : (
      <div className="tm-derived">{loading ? t("panel.journal.loading", { defaultValue: "翻开日记本…" }) : ""}</div>
    )
  }
  return (
    <div className="tm-review">
      <div className="tm-review-progress">
        <span className="tm-diary-count">
          {t("panel.review.progress", { defaultValue: "下一份素材：{n} / {total} 轮" })
            .replace("{n}", String(turns))
            .replace("{total}", String(threshold))}
        </span>
        <div className="tm-review-bar">
          <div className="tm-review-bar-fill" style={{ width: `${Math.round(ratio * 100)}%` }} />
        </div>
      </div>
      <div className="tm-toc">
        {entries.map((entry) => (
          <button
            key={String(entry.ts || "")}
            type="button"
            className="tm-toc-row"
            onClick={() => onOpen(String(entry.ts || ""))}
          >
            <span className="tm-toc-no">{t("panel.review.pieceShort", { defaultValue: "篇" })}</span>
            <span className="tm-toc-range">{String(entry.ts || "").slice(0, 10) || t("panel.journal.noDate", { defaultValue: "未注明日期" })}</span>
            <span className="tm-toc-meta">
              {t("panel.review.turnsMeta", { defaultValue: "{n} 轮" }).replace("{n}", String(entry.turns ?? 0))}
            </span>
            <span className="tm-toc-arrow">›</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// 我的日记单篇阅读：纸质视图 + 返回目录；评价正文成段展示
function ReviewReader(props: { t: TFunc; entry: ReviewEntry; onBack: () => void }) {
  const { t, entry, onBack } = props
  return (
    <div className="tm-book">
      <div className="tm-book-topbar">
        <Button onClick={onBack}>{t("panel.journal.backToToc", { defaultValue: "← 目录" })}</Button>
        <span className="tm-book-pageno">{String(entry.ts || "").slice(0, 10)}</span>
        <span className="tm-book-meta">
          {t("panel.review.turnsMeta", { defaultValue: "{n} 轮" }).replace("{n}", String(entry.turns ?? 0))}
        </span>
        <span className="tm-book-meta">
          {String(entry.span || "").replace("~", " ~ ")}
        </span>
      </div>
      <div className="tm-book-entries tm-paper">
        <div className="tm-book-entry">
          <div className="tm-book-entry-text">{entry.text}</div>
        </div>
      </div>
    </div>
  )
}
