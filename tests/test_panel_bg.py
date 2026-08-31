"""面板外观（自定义背景图）的单测：data URL 校验、遮罩归一、三入口存取链路。

纯校验函数直接走模块级 _parse_panel_bg / _clamp_panel_bg_dim；
入口链路用 plugin_factory 的 FakeStore 走 set → get → context 标记 → clear。
运行方式：uv run python -m pytest tests -q
"""

import asyncio

PNG_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
SVG_URL = "data:image/svg+xml;base64,PHN2Zy8+"


# ---------- _parse_panel_bg：合法性校验 ----------


def test_parse_accepts_png_and_svg(tm) -> None:
    mime, size = tm._parse_panel_bg(PNG_URL)
    assert mime == "image/png" and size == len(PNG_URL)
    mime, _ = tm._parse_panel_bg(SVG_URL)
    assert mime == "image/svg+xml"


def test_parse_mime_case_insensitive(tm) -> None:
    mime, _ = tm._parse_panel_bg("data:image/PNG;base64,AAA")
    assert mime == "image/png"


def test_parse_rejects_non_data_url(tm) -> None:
    for bad in ("", "https://example.com/a.png", "file:///tmp/a.png", None):
        try:
            tm._parse_panel_bg(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"should reject: {bad!r}")


def test_parse_rejects_unsupported_mime(tm) -> None:
    for bad in ("data:text/plain;base64,AAA", "data:image/tiff;base64,AAA", "data:;base64,AAA"):
        try:
            tm._parse_panel_bg(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"should reject: {bad!r}")


def test_parse_rejects_oversized(tm) -> None:
    big = "data:image/png;base64," + "A" * (tm._PANEL_BG_MAX_CHARS + 1)
    try:
        tm._parse_panel_bg(big)
    except ValueError as exc:
        assert "too large" in str(exc)
    else:
        raise AssertionError("should reject oversized")


def test_parse_rejects_malformed_no_payload(tm) -> None:
    try:
        tm._parse_panel_bg("data:image/png;base64")
    except ValueError as exc:
        assert "malformed" in str(exc)
    else:
        raise AssertionError("should reject malformed")


# ---------- _clamp_panel_bg_dim：遮罩强度归一 ----------


def test_clamp_dim_range_and_bad_values(tm) -> None:
    assert tm._clamp_panel_bg_dim(0.5) == 0.5
    assert tm._clamp_panel_bg_dim(-1) == 0.0
    assert tm._clamp_panel_bg_dim(2.0) == 0.85
    assert tm._clamp_panel_bg_dim("bad") == tm._PANEL_BG_DEFAULT_DIM
    assert tm._clamp_panel_bg_dim(None) == tm._PANEL_BG_DEFAULT_DIM


# ---------- 入口链路：set → get → context → clear ----------


def test_set_get_clear_roundtrip(plugin_factory, tm) -> None:
    p = plugin_factory()

    # 初始：未设置，get 与 context 标记都是 set=False + 默认遮罩；
    # Ok 桩从插件模块名空间取（与插件 isinstance 判定同源，不直接 import conftest）
    res = asyncio.run(p.get_panel_background())
    assert isinstance(res, tm.Ok) and res.value["set"] is False
    meta = asyncio.run(p._panel_bg_meta())
    assert meta == {"set": False, "dim": tm._PANEL_BG_DEFAULT_DIM}

    # 设置：合法 png + 显式遮罩
    res = asyncio.run(p.set_panel_background(data_url=PNG_URL, dim=0.55))
    assert isinstance(res, tm.Ok)
    assert res.value == {"set": True, "mime": "image/png", "size": len(PNG_URL), "dim": 0.55}

    # 读回：本体与遮罩一致
    res = asyncio.run(p.get_panel_background())
    assert res.value["set"] is True
    assert res.value["data_url"] == PNG_URL
    assert res.value["dim"] == 0.55

    # context 轻量标记：只有 set 与 dim，绝不含图片本体
    meta = asyncio.run(p._panel_bg_meta())
    assert meta == {"set": True, "dim": 0.55}

    # 清除后回落默认（store.delete 桩与宿主 PluginStore.delete 对齐）
    res = asyncio.run(p.clear_panel_background())
    assert isinstance(res, tm.Ok) and res.value["set"] is False
    res = asyncio.run(p.get_panel_background())
    assert res.value["set"] is False


def test_set_rejects_invalid_and_keeps_previous(plugin_factory, tm) -> None:
    p = plugin_factory()
    asyncio.run(p.set_panel_background(data_url=PNG_URL))

    res = asyncio.run(p.set_panel_background(data_url="https://evil.example/x.png"))
    assert not isinstance(res, tm.Ok)
    # 非法写入不影响已有背景
    res = asyncio.run(p.get_panel_background())
    assert res.value["set"] is True and res.value["data_url"] == PNG_URL


def test_set_dim_defaults_and_clamps(plugin_factory, tm) -> None:
    p = plugin_factory()
    # 不传 dim：落默认值
    res = asyncio.run(p.set_panel_background(data_url=PNG_URL))
    assert res.value["dim"] == tm._PANEL_BG_DEFAULT_DIM
    # 超界 dim：夹到上限
    res = asyncio.run(p.set_panel_background(data_url=PNG_URL, dim=5))
    assert res.value["dim"] == 0.85
