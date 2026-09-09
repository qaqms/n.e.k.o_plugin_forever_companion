"""1.3.0 藏书阁（journal_archive@）回归：淘汰不再静默丢弃，而是搬进合订本。

锁死四条纪律：
1. 工具路径：写满活架后 journal_write 带出的 evicted 页必须落进
   journal_archive@<角色>（只追加、不入当前书 blob）；
2. 载入路径：_save_shard_journal 兜住一切截断（旧版磁盘残留 / 迁移超长），
   截掉的溢出页同样入阁；
3. 阁内再满才从最旧一页真删（翻阅按"距最近一本"倒计数，删旧不挪位）；
4. archive_brief 只显存储里现成的事实（页码/日期），不派生会随淘汰平移的序号。

运行方式（插件目录内）：uv run python -m pytest tests -q
"""

import asyncio
from datetime import datetime, timedelta, timezone


def run(coro):
    return asyncio.run(coro)


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _pages(count: int, *, start_no: int = 1) -> list[dict]:
    return [
        {
            "page_no": start_no + i,
            "started_at": (NOW + timedelta(days=i)).isoformat(timespec="seconds"),
            "entries": [{"ts": (NOW + timedelta(days=i)).isoformat(timespec="seconds"), "text": f"内容{i}"}],
        }
        for i in range(count)
    ]


def _write_page(p, tm, lanlan: str, text: str, *, new_page: bool = True):
    res = run(p.tool_write_journal(
        events=text, new_page=new_page, _ctx={"lanlan_name": lanlan},
    ))
    assert isinstance(res, tm.Ok), f"tool write failed: {res.error}"
    return res


# ---------------------------------------------------------------------------
# 1. 工具路径：写满活架 → 淘汰页入阁并落盘
# ---------------------------------------------------------------------------


def test_tool_eviction_archives_page(tm, plugin_factory):
    p = plugin_factory()
    lanlan = "灵"
    # 写满 52 页 + 再写 1 页：第 53 次写入把第 1 页挤下活架
    for i in range(53):
        _write_page(p, tm, lanlan, f"第{i}页的故事")
    shard = p._get_shard(lanlan)
    assert len(shard.journal) == 52
    assert shard.journal[0]["page_no"] == 2, "活架最旧应为第 2 页"
    # 被淘汰的第 1 页没有消失：进阁 + 落盘
    assert [pg["page_no"] for pg in shard.journal_archive] == [1]
    archived = shard.journal_archive[0]
    assert "第0页的故事" in archived["entries"][0]["text"]
    assert p.store.data.get("journal_archive@灵"), "合订本必须落盘（独立 key）"
    # 当前书 blob 不含阁页：两本分开，写热路径不重写阁
    assert all(pg["page_no"] != 1 for pg in p.store.data["journal@灵"])


def test_get_journal_archive_entry(tm, plugin_factory_full):
    p = plugin_factory_full(current_lanlan="灵")
    shard = p._get_shard("灵")
    shard.journal = _pages(2, start_no=1)
    run(p._append_journal_archive("灵", shard, _pages(1)))
    res = run(p.get_journal_archive())
    assert isinstance(res, tm.Ok), res
    payload = res.value
    assert len(payload["pages"]) == 1
    page = payload["pages"][0]
    assert page["page_no"] == 1
    assert page["entry_count"] == 1
    assert page["entries"][0]["text"] == "内容0"


# ---------------------------------------------------------------------------
# 2. 载入/保存路径：溢出截断同样入阁（旧 blob 超长的兜底）
# ---------------------------------------------------------------------------


def test_save_shard_journal_archives_overflow(tm, plugin_factory):
    p = plugin_factory()
    lanlan = "灵"
    shard = p._get_shard(lanlan)
    shard.journal = _pages(55)
    res = run(p._save_shard_journal(lanlan, shard))
    assert isinstance(res, tm.Ok), res
    assert len(shard.journal) == 52
    assert [pg["page_no"] for pg in shard.journal_archive] == [1, 2, 3]
    assert [pg["page_no"] for pg in shard.journal] == list(range(4, 56))
    assert len(p.store.data["journal@灵"]) == 52
    assert len(p.store.data["journal_archive@灵"]) == 3


def test_save_shard_journal_without_overflow_skips_archive_write(plugin_factory):
    """零淘汰的常态写不多花一次存储写：archive key 不被触碰。"""
    p = plugin_factory()
    shard = p._get_shard("灵")
    shard.journal = _pages(3)
    run(p._save_shard_journal("灵", shard))
    assert "journal_archive@灵" not in p.store.data


# ---------------------------------------------------------------------------
# 3. 阁内再满：从最旧一页真删（新页永远在末尾，倒计数不挪位）
# ---------------------------------------------------------------------------


def test_archive_cap_drops_oldest(tm, plugin_factory):
    p = plugin_factory()
    shard = p._get_shard("灵")
    shard.journal_archive = _pages(100)
    run(p._append_journal_archive("灵", shard, _pages(6, start_no=101)))
    archive = shard.journal_archive
    assert len(archive) == tm._JOURNAL_ARCHIVE_MAX_PAGES
    assert archive[0]["page_no"] == 3, "106 进 104 出：最旧两页被裁"
    assert archive[-1]["page_no"] == 106, "新入阁页永远在末尾"


# ---------------------------------------------------------------------------
# 4. brief 只显事实 + 载入回读
# ---------------------------------------------------------------------------


def test_archive_brief_reports_facts_only(tm):
    empty = tm.archive_brief([])
    assert empty == {"pages": 0}
    pages = _pages(3)
    brief = tm.archive_brief(pages)
    assert brief["pages"] == 3
    assert brief["first_ts"] == pages[0]["started_at"]
    assert brief["last_ts"] == pages[-1]["entries"][-1]["ts"]


def test_archive_loaded_with_shard(plugin_factory):
    """重开（新实例）后合订本原样回来：加载路径读 journal_archive@。"""
    p = plugin_factory()
    shard = p._get_shard("灵")
    run(p._append_journal_archive("灵", shard, _pages(2)))
    initial = dict(p.store.data)
    p2 = plugin_factory()
    p2.store.data.update(initial)
    shard2 = p2._get_shard("灵")
    shard2.loaded = False
    run(p2._ensure_shard("灵"))
    assert [pg["page_no"] for pg in shard2.journal_archive] == [1, 2]
