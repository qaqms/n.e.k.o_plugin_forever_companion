"""Panel wallpaper layers and appearance tokens, without a running host."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "ui" / "panel.tsx"
UTILS = ROOT / "ui" / "utils.ts"


@pytest.fixture(scope="module")
def appearance_values():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available; appearance logic check needs Node 22.13+")
    script = r"""
        import * as moduleApi from "node:module";
        import { readFileSync } from "node:fs";
        if (typeof moduleApi.stripTypeScriptTypes !== "function") process.exit(2);
        const source = moduleApi.stripTypeScriptTypes(readFileSync(process.argv[1], "utf8"));
        const m = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
        const zero = m.normAppearance({
            blur: 0, dim: 0, glass: 0, card_alpha: 0, saturate: 0, text_weight: 40,
        });
        const maximum = m.normAppearance({
            blur: 100, dim: 10, glass: 100, card_alpha: 500, text_weight: 500,
        });
        const minimum = m.normAppearance({
            blur: -1, dim: -1, glass: -1, card_alpha: -1, text_weight: -1,
        });
        const defaults = m.normAppearance(null);
        const saved = m.normAppearance({
            blur: 8, dim: 0.3, brightness: 95, saturate: 120, contrast: 110,
            glass: 16, card_alpha: 100, text_weight: 85,
        });
        const fills = {};
        for (const fill of m.APPEARANCE_FILLS) {
            fills[fill] = m.bgLayerStyle(m.normAppearance({fill}), "data:image/png;base64,AA==");
        }
        console.log(JSON.stringify({
            zero, maximum, minimum, defaults, saved,
            zeroVars: m.appearanceVars(zero),
            maximumVars: m.appearanceVars(maximum),
            minimumVars: m.appearanceVars(minimum),
            defaultVars: m.appearanceVars(defaults),
            rawBoundaryVars: m.appearanceVars({glass: 100, card_alpha: 500, text_weight: -1}),
            zeroLayer: m.bgLayerStyle(zero, "data:image/png;base64,AA=="),
            filteredLayer: m.bgLayerStyle(m.normAppearance({
                blur: 12, brightness: 75, saturate: 130, contrast: 120,
            }), "data:image/png;base64,AA=="),
            fills,
        }));
    """
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script, str(UTILS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if proc.returncode == 2:
        pytest.skip("Node's built-in TypeScript parser is not available")
    assert proc.returncode == 0, (proc.stdout or "") + "\n" + (proc.stderr or "")
    return json.loads(proc.stdout)


def test_explicit_zero_appearance_values_are_not_defaults(appearance_values):
    zero = appearance_values["zero"]
    for field in ("blur", "dim", "glass", "card_alpha", "saturate"):
        assert zero[field] == 0
    vars_ = appearance_values["zeroVars"]
    assert vars_["--tm-card-k"] == "0"
    assert vars_["--tm-glass"] == "0px"
    assert vars_["--tm-glass-filter"] == "none"
    assert vars_["--tm-sidebar-glass-filter"] == "none"


def test_visual_tokens_respect_clamped_parameter_bounds(appearance_values):
    maximum = appearance_values["maximum"]
    assert maximum["blur"] == 30
    assert maximum["dim"] == 0.85
    assert maximum["glass"] == 40
    assert maximum["card_alpha"] == 100
    assert maximum["text_weight"] == 100
    assert appearance_values["maximumVars"]["--tm-card-k"] == "1"
    assert appearance_values["maximumVars"]["--tm-glass-filter"] == "blur(40px) saturate(1.08)"
    for field in ("blur", "dim", "glass", "card_alpha"):
        assert appearance_values["minimum"][field] == 0
    assert appearance_values["minimum"]["text_weight"] == 40
    assert appearance_values["rawBoundaryVars"]["--tm-card-k"] == "1"
    assert appearance_values["rawBoundaryVars"]["--tm-glass-filter"] == "blur(40px) saturate(1.08)"


def test_wallpaper_defaults_use_requested_values_and_existing_parameter_names(appearance_values):
    assert appearance_values["defaults"] == {
        "bg_id": "",
        "fill": "cover",
        "position": "center",
        "blur": 0,
        "dim": 0.4,
        "brightness": 100,
        "saturate": 100,
        "contrast": 100,
        "glass": 0,
        "card_alpha": 0,
        "text_weight": 100,
    }
    assert appearance_values["defaultVars"]["--tm-glass-filter"] == "none"
    assert appearance_values["defaultVars"]["--tm-sidebar-glass-filter"] == "none"
    assert appearance_values["defaultVars"]["--tm-card-k"] == "0"


def test_frontend_appearance_defaults_match_backend(appearance_values, tm):
    assert appearance_values["defaults"] == tm.appearance_defaults()


def test_frontend_preserves_saved_appearance_values(appearance_values):
    saved = appearance_values["saved"]
    assert {key: saved[key] for key in ("blur", "dim", "brightness", "saturate", "contrast", "glass", "card_alpha", "text_weight")} == {
        "blur": 8, "dim": 0.3, "brightness": 95, "saturate": 120, "contrast": 110,
        "glass": 16, "card_alpha": 100, "text_weight": 85,
    }


def test_without_wallpaper_keeps_neutral_card_surfaces():
    source = PANEL.read_text(encoding="utf-8")
    assert "bgDataUrl ? draftAp : { ...draftAp, glass: 0, card_alpha: 100 }" in source
    assert "appearanceVars(surfaceAppearance)" in source


def test_readability_keeps_opaque_text_and_a_clear_minimum(appearance_values):
    minimum = appearance_values["zeroVars"]
    assert minimum["--tm-text-color"] == "color-mix(in srgb, var(--text) 88%, var(--muted))"
    assert appearance_values["defaultVars"]["--tm-text-color"] == "var(--text)"
    assert "transparent" not in minimum["--tm-text-color"]
    assert minimum["--tm-text-shadow"] == "0 1px 3px rgba(0, 0, 0, 0.34)"
    assert appearance_values["defaultVars"]["--tm-text-shadow"] == "0 1px 3px rgba(0, 0, 0, 0.24)"


def test_background_filter_and_fill_do_not_modify_mask(appearance_values):
    filtered = appearance_values["filteredLayer"]
    assert filtered["filter"] == "blur(12px) brightness(75%) saturate(130%) contrast(120%)"
    assert filtered["WebkitFilter"] == filtered["filter"]
    assert filtered["inset"] == "-28px"
    assert "opacity" not in filtered
    zero = appearance_values["zeroLayer"]
    assert zero["inset"] == "0px"
    assert zero["filter"] == "saturate(0%)"
    assert appearance_values["fills"]["cover"]["backgroundSize"] == "cover"
    assert appearance_values["fills"]["contain"]["backgroundSize"] == "contain"
    assert appearance_values["fills"]["stretch"]["backgroundSize"] == "100% 100%"
    assert appearance_values["fills"]["repeat"]["backgroundRepeat"] == "repeat"


def test_wallpaper_image_and_mask_are_independent_sibling_layers():
    source = PANEL.read_text(encoding="utf-8")
    assert re.search(
        r'<div key="bg" className="tm-bg" aria-hidden="true">\s*'
        r'<div className="tm-bg-image" style=\{bgLayerStyle\(draftAp, bgDataUrl\)\} />\s*'
        r'<div className="tm-bg-dim" style=\{\{ opacity: String\(draftAp\.dim\) \}\} />\s*'
        r"</div>",
        source,
    ), "Wallpaper filters must be on the image, not the wrapper or mask"


def test_unready_wallpaper_retains_only_an_existing_gallery_image():
    source = PANEL.read_text(encoding="utf-8")
    assert "if (!requestedBgUrl) return" in source
    assert 'image.decode().then(ready).catch(() => { console.warn("[forever_companion] decode panel background failed") })' in source
    assert "image.decode().then(ready).catch(ready)" not in source
    assert "if (!alive) return" in source
    assert "setReadyBg({ id: draftAp.bg_id, dataUrl: requestedBgUrl, theme })" in source
    assert "alive = false" in source
    assert 'setReadyBg({ id: "", dataUrl: "", theme: null })' in source
    assert "galleryItems.some((item) => String(item.id || \"\") === readyBg.id)" in source
    assert "draftAp.bg_id && (readyBg.id === draftAp.bg_id || previousBgExists)" in source


def test_wallpaper_and_cached_colors_share_the_decode_lifecycle():
    source = PANEL.read_text(encoding="utf-8")
    assert "cached?.dataUrl === requestedBgUrl ? cached.theme : readWallpaperTheme(image)" in source
    assert "setReadyBg({ id: draftAp.bg_id, dataUrl: requestedBgUrl, theme })" in source
    assert "bgDataUrl && readyBg.theme ? readyBg.theme : DEFAULT_THEME_COLORS" in source
    assert "themeColorVars(themeColors)" in source
    assert "delete themeCache.current[id]" in source


def test_deleted_images_invalidate_inflight_requests_and_use_current_cache():
    source = PANEL.read_text(encoding="utf-8")
    assert "if (imgInflight.current[id] !== request) return" in source
    assert "if (imgInflight.current[id] === request) delete imgInflight.current[id]" in source
    assert "delete imgInflight.current[id]" in source
    assert re.search(r"setImgCache\(\(prev\) => \{\s*const cache = \{ \.\.\.prev \}\s*delete cache\[id\]", source)
