"""面板依赖预算守卫：宿主对 hosted TSX 面板的运行时依赖有硬上限，超了整块面板加载失败。

宿主口径（plugin/server/application/plugins/ui_query_service.py）：
- ``_HOSTED_TSX_DEPENDENCIES_MAX_FILES = 32``：入口之外经相对 import 可达的文件数；
- ``_HOSTED_TSX_DEPENDENCIES_MAX_BYTES = 512 * 1024``：这些文件的磁盘字节数之和；
- 入口文件自身不计；``import type`` 与全部绑定都是 ``type X`` 的 import 被擦除，不计。

越线时宿主返回 PLUGIN_UI_DEPENDENCIES_TOO_MANY / TOO_LARGE，用户看到的是整个面板打不开。
这里按同一口径在本地重算，并要求留出余量：快撞线时测试先红，而不是发版后面板白屏。
1.4.7 时曾到过 32/32 个文件、523,379/524,288 字节（只剩 909 字节）。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HOST_MAX_FILES = 32
HOST_MAX_BYTES = 512 * 1024
# 余量：低于此值即判失败，给下一次改动留出发现问题的窗口
MIN_FREE_FILES = 2
MIN_FREE_BYTES = 8 * 1024

_CODE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs")
_IMPORT_FROM = re.compile(r"""^import\s+([\s\S]*?)\s+from\s+["']([^"']+)["']""", re.MULTILINE)
_IMPORT_BARE = re.compile(r"""^import\s+["']([^"']+)["']""", re.MULTILINE)
_IDENT = r"[A-Za-z_$][\w$]*"


def _is_type_only_binding(raw: str) -> bool:
    # 与宿主 _hosted_is_type_only_binding 同口径
    text = raw.strip()
    if re.match(r"type\s*\{", text):
        return True
    if re.fullmatch(rf"type\s+\*\s+as\s+{_IDENT}", text):
        return True
    if re.match(rf"type\s+{_IDENT}\s*,", text):
        return True
    return bool(re.fullmatch(rf"type\s+{_IDENT}(?:\s+as\s+{_IDENT})?", text))


def _import_is_type_only(raw_bindings: str) -> bool:
    # 与宿主 _hosted_import_is_type_only 同口径
    bindings = raw_bindings.strip()
    if not bindings:
        return False
    if _is_type_only_binding(bindings):
        return True
    start = bindings.find("{")
    if start < 0 or bindings[:start].strip().rstrip(",").strip():
        return False
    inner = bindings[start:].strip()
    if re.fullmatch(r"\{\s*\}", inner) or not inner.endswith("}"):
        return False
    items = [item for item in inner[1:-1].split(",") if item.strip()]
    return all(_is_type_only_binding(item) for item in items)


def _relative_imports(source: str) -> list[str]:
    found: list[str] = []
    for bindings, spec in _IMPORT_FROM.findall(source):
        if bindings.lstrip().startswith(("'", '"')) or _import_is_type_only(bindings):
            continue
        if spec.startswith(("./", "../")):
            found.append(spec)
    found.extend(spec for spec in _IMPORT_BARE.findall(source) if spec.startswith(("./", "../")))
    return found


def _resolve(from_path: Path, spec: str) -> Path:
    base = (from_path.parent / spec.split("?", 1)[0].split("#", 1)[0]).resolve()
    candidates = [base, *(Path(f"{base}{ext}") for ext in _CODE_EXTENSIONS)]
    candidates += [base / f"index{ext}" for ext in _CODE_EXTENSIONS]
    for candidate in candidates:
        if candidate.suffix.lower() in _CODE_EXTENSIONS and candidate.is_file():
            return candidate
    raise AssertionError(f"{from_path.name}: unresolved import {spec!r}")


def _dependencies(entry: Path) -> list[Path]:
    seen: list[Path] = []
    stack = [entry]
    while stack:
        current = stack.pop()
        for spec in _relative_imports(current.read_text(encoding="utf-8")):
            dep = _resolve(current, spec)
            if dep != entry and dep not in seen:
                seen.append(dep)
                stack.append(dep)
    return seen


def _panel_entries() -> list[Path]:
    manifest = tomllib.loads((ROOT / "plugin.toml").read_text(encoding="utf-8"))
    panels = manifest["plugin"]["ui"]["panel"]
    return [ROOT / panel["entry"] for panel in panels]


def test_panel_entries_are_declared() -> None:
    entries = _panel_entries()
    assert entries
    for entry in entries:
        assert entry.is_file(), entry


def test_type_only_imports_are_not_counted() -> None:
    assert _relative_imports('import type { A } from "./types"') == []
    assert _relative_imports('import { type A, type B } from "./types"') == []
    assert _relative_imports('import { type A, b } from "./utils"') == ["./utils"]
    assert _relative_imports('import { h } from "@neko/plugin-ui"') == []
    assert _relative_imports('import "./side"') == ["./side"]


def test_panel_dependencies_stay_within_host_budget() -> None:
    for entry in _panel_entries():
        deps = _dependencies(entry)
        total = sum(dep.stat().st_size for dep in deps)
        biggest = ", ".join(
            f"{dep.name}={dep.stat().st_size}" for dep in sorted(deps, key=lambda d: -d.stat().st_size)[:5]
        )
        assert len(deps) <= HOST_MAX_FILES - MIN_FREE_FILES, (
            f"{entry.name}: {len(deps)} runtime dependency files; host hard limit is {HOST_MAX_FILES} "
            f"and we keep {MIN_FREE_FILES} free. Merge small modules instead of adding files."
        )
        assert total <= HOST_MAX_BYTES - MIN_FREE_BYTES, (
            f"{entry.name}: dependencies total {total} bytes; host hard limit is {HOST_MAX_BYTES} "
            f"and we keep {MIN_FREE_BYTES} free. Largest: {biggest}"
        )
