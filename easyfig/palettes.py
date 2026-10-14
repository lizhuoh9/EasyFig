"""
Colour utilities and the built-in scientific palette library.

This module is intentionally dependency-free (standard library only) so both the
Tk colour picker and the chart engine can import it without pulling in numpy or
matplotlib.

Palette source
--------------
The ten palettes below are transcribed from the Zhihu series
《SCI论文插图经典配色实例》 by 「阿昆的科研日常」 (hei-gou-52), issues 32, 33 and
35-42 (the series has no issue 34).

* Colour values were read from the R/G/B annotations printed on each card and
  verified against the card pixels (error <= 2/255).
* The source citation for each palette is transcribed from the card image; it
  was not re-verified against the publisher, so check it before citing.
* These are the author's published colour readings, not an official journal
  palette; treat them as a curated starting point.

Use :func:`palette_colors` to take a palette, optionally sub-sampled or
reversed, and :func:`normalize_color` to validate user input.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

NAMED_COLORS = frozenset({
    "black", "white", "red", "green", "blue", "yellow", "cyan", "magenta",
    "orange", "purple", "brown", "pink", "gray", "grey", "olive", "navy",
    "teal", "lime", "aqua", "fuchsia", "silver", "maroon", "gold", "coral",
    "salmon", "violet", "indigo", "tan", "beige", "ivory", "khaki", "plum",
    "orchid", "azure", "mintcream", "crimson", "darkred", "darkgreen",
    "darkblue", "darkorange", "darkviolet", "lightblue", "lightgreen",
    "lightgray", "lightgrey", "steelblue", "skyblue", "forestgreen",
})

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def is_hex_color(value):
    """True when ``value`` is ``#rgb``, ``#rrggbb`` or the same without ``#``."""
    if not isinstance(value, str):
        return False
    body = value.strip()
    if body.startswith("#"):
        body = body[1:]
    return len(body) in (3, 6) and all(char in _HEX_DIGITS for char in body)


def normalize_color(value, fallback=None):
    """Return ``value`` as a canonical colour string.

    Accepts ``#rgb``, ``#rrggbb``, the same forms without ``#``, and the
    matplotlib named colours in :data:`NAMED_COLORS`.  Hex input is lowercased
    and 3-digit shorthand is expanded.  Named colours are passed through as
    written.  Empty or ``None`` input yields ``fallback``; anything else raises
    ``ValueError``.
    """
    if value is None:
        return fallback
    if not isinstance(value, str):
        raise ValueError(f"colour must be a string, got {value!r}")
    text = value.strip()
    if not text:
        return fallback
    if text.lower() in NAMED_COLORS:
        return text
    if is_hex_color(text):
        body = text[1:] if text.startswith("#") else text
        if len(body) == 3:
            body = "".join(char * 2 for char in body)
        return "#" + body.lower()
    raise ValueError(
        f"invalid colour {value!r}: expected #rgb, #rrggbb or a colour name"
    )


#: Named colours light enough to need dark text on top.  Any other name is
#: assumed to be dark; pass a hex value when exact contrast matters.
LIGHT_NAMED_COLORS = frozenset({
    "white", "ivory", "beige", "mintcream", "lightgray", "lightgrey",
    "silver", "yellow", "gold", "khaki", "lightblue", "lightgreen",
    "skyblue", "azure", "aqua", "cyan", "lime", "palegreen",
})


def text_color_for(background, dark="#000000", light="#ffffff"):
    """Pick a readable text colour for ``background`` (relative luminance)."""
    hex_value = normalize_color(background, "#ffffff")
    if not hex_value.startswith("#"):
        # A named colour: use the light/dark name table rather than guessing.
        return dark if hex_value.lower() in LIGHT_NAMED_COLORS else light
    body = hex_value[1:]
    if len(body) == 3:
        body = "".join(char * 2 for char in body)
    red, green, blue = (int(body[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    def _linear(channel):
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    luminance = (0.2126 * _linear(red) + 0.7152 * _linear(green)
                 + 0.0722 * _linear(blue))
    return dark if luminance > 0.45 else light


# ---------------------------------------------------------------------------
# Scientific palette library
# ---------------------------------------------------------------------------

#: ``key -> {issue, journal, kind, title, colors, ...}`` in no particular order.
SCIENTIFIC_PALETTES = {
    "akun42_nature": {
        "issue": 42,
        "journal": "Nature",
        "kind": "暖色顺序色阶 + 冷色对照 / warm sequential with a cool counterpoint",
        "citation": (
            "Elmarakeby H A, Hwang J, Arafeh R, et al. Biologically informed "
            "deep neural network for prostate cancer discovery[J]. Nature, "
            "2021, 598(7880): 348-352."
        ),
        "url": "https://zhuanlan.zhihu.com/p/1946524087938704592",
        "title": "跟顶刊学配色~SCI论文插图经典配色实例第42期",
        "note": "图中另有 1 个橙色 #E9A375 用于 alteration 图例，卡片版色板未含。",
        "colors": [
            "#4E74B3", "#96D1DF", "#FEE0D5", "#FDBCA8",
            "#FB9780", "#EB6E68", "#C85A5D", "#944D55",
        ],
    },
    "akun41_nature": {
        "issue": 41,
        "journal": "Nature",
        "kind": "蓝绿—黄顺序色阶 / blue-green to yellow sequential",
        "citation": (
            "Kim R M, Huh J H, Yoo S J, et al. Enantioselective sensing by "
            "collective circular dichroism[J]. Nature, 2022, 612(7940): 470-476."
        ),
        "url": "https://zhuanlan.zhihu.com/p/1942132635817210707",
        "title": "配色没新意？看这里！SCI论文插图经典配色实例第41期",
        "colors": [
            "#485098", "#4660AD", "#5A96CC", "#68B4CE",
            "#80CDBB", "#A5C582", "#D6CF67", "#F3DE67",
            "#F9EF7C",
        ],
    },
    "akun40_tibet": {
        "issue": 40,
        "journal": "原文未标注 / not stated",
        "kind": "8 色分类色板（高对比） / high-contrast categorical",
        "citation": "原文未在正文标注来源期刊，原图亦未附引文。",
        "url": "https://zhuanlan.zhihu.com/p/1926915650737140096",
        "title": "配色没灵感？看这里~SCI论文插图经典配色实例第40期",
        "note": "含中灰 #5F6B6D，作线条色时在深底上对比不足。",
        "colors": [
            "#00B8AA", "#374649", "#FD625E", "#F2C811",
            "#5F6B6D", "#8AD4EB", "#FE9666", "#A66999",
        ],
    },
    "akun39_echarts": {
        "issue": 39,
        "journal": "原文未标注 / not stated",
        "kind": "8 色分类色板（通用） / general-purpose categorical",
        "citation": (
            "原文未在正文标注来源期刊；本组色值与 ECharts 默认分类色板基本一致。"
        ),
        "url": "https://zhuanlan.zhihu.com/p/1924402462409855748",
        "title": "不会配色？看这里~SCI论文插图经典配色实例第39期",
        "note": "与 ECharts 默认 color 数组基本一致，最百搭的一组。",
        "colors": [
            "#546FC6", "#91CB74", "#FAC859", "#EE6666",
            "#73C0DE", "#3BA372", "#FC8452", "#9A60B4",
        ],
    },
    "akun38_latlf_m": {
        "issue": 38,
        "journal": "Nature Climate Change",
        "kind": "红—黄—白—蓝 双向（diverging）色阶 / red-yellow-white-blue diverging",
        "citation": (
            "Latif M, Sun J, Visbeck M, et al. Natural variability has dominated "
            "Atlantic meridional overturning circulation since 1900[J]. Nature "
            "Climate Change, 2022, 12(5): 455-460."
        ),
        "url": "https://zhuanlan.zhihu.com/p/717140005",
        "title": "同顶刊学配色~SCI论文插图经典配色实例第38期",
        "note": "中间一格是纯白 #FFFFFF；在白色画布上做分类色会“消失”，只适合做色阶。",
        "colors": [
            "#8E0028", "#BD3C33", "#E4945A", "#F9C676",
            "#FBECAB", "#FFFFFF", "#D1E2EF", "#7FA9CD",
            "#527CB4", "#3F60A3", "#30327D",
        ],
    },
    "akun37_nature": {
        "issue": 37,
        "journal": "Nature",
        "kind": "深青—浅青 顺序色阶 / dark teal to pale teal sequential",
        "citation": (
            "Davis J T, Chinazzi M, Perra N, et al. Cryptic transmission of "
            "SARS-CoV-2 and the first COVID-19 wave[J]. Nature, 2021, "
            "600(7887): 127-132."
        ),
        "url": "https://zhuanlan.zhihu.com/p/703061395",
        "title": "配色好看，不会用也是白搭…SCI论文插图经典配色实例第37期",
        "note": "明度跨度大，转灰度后仍可区分，适合热图/填充图。",
        "colors": [
            "#334454", "#185D7A", "#0178A2", "#0892AE",
            "#13AFBE", "#53C3C4", "#99D7CC", "#CCE7E2",
            "#FAFCFB",
        ],
    },
    "akun36_nature": {
        "issue": 36,
        "journal": "Nature",
        "kind": "蓝紫—绿 顺序色阶 / blue-violet to green sequential",
        "citation": (
            "Du J, Mix A C, Haley B A, et al. Volcanic trigger of ocean "
            "deoxygenation during early Cenozoic hyperthermals[J]. Nature, "
            "2022, 611(7934): 74-80."
        ),
        "url": "https://zhuanlan.zhihu.com/p/700657234",
        "title": "不会配色？看这里~SCI论文插图经典配色实例第36期",
        "colors": [
            "#2A1773", "#1E3096", "#10528E", "#226C87",
            "#348286", "#479A88", "#5AB37D", "#82CD66",
            "#C5DD6D", "#F8EE97",
        ],
    },
    "akun35_science": {
        "issue": 35,
        "journal": "Science",
        "kind": "红—米—蓝 双向（diverging）色阶 / red-cream-blue diverging",
        "citation": (
            "Dahlke F T, Wohlrab S, Butzin M, et al. Thermal bottlenecks in the "
            "life cycle define the climate-driven range of Antarctic krill[J]. "
            "Science, 2020, 369(6499): 65-70."
        ),
        "url": "https://zhuanlan.zhihu.com/p/698250144",
        "title": "不会配色？看这里！SCI论文插图经典配色实例第35期",
        "note": "白色卡片刻了 #0B70B7 / #C1282D 两个主色。",
        "colors": [
            "#C1282D", "#D75728", "#ED8622", "#F6B66B",
            "#FCE7CE", "#C9DFEF", "#5CA0CF", "#0D67A6",
            "#174263", "#211D1F",
        ],
    },
    "akun33_science": {
        "issue": 33,
        "journal": "Science",
        "kind": "橙红—浅蓝 双向（diverging）色阶 / orange-red to pale blue diverging",
        "citation": (
            "Qin B, Fei C, Bridges A A, et al. Cell position fates and "
            "collective fountain flow during avian gastrulation revealed by "
            "light-sheet microscopy[J]. Science, 2020, 369(6499)."
        ),
        "url": "https://zhuanlan.zhihu.com/p/694228593",
        "title": "不会配色？看这里！SCI论文插图经典配色实例第33期",
        "colors": [
            "#F37252", "#F7935A", "#FCB461", "#FED297",
            "#FFF0DC", "#E3F5F6", "#ABE0E4", "#7FC6D3",
            "#779FC6", "#6F78B9",
        ],
    },
    "akun32_nature": {
        "issue": 32,
        "journal": "Nature",
        "kind": "蓝—白—紫 双向（diverging）色阶 / blue-white-purple diverging",
        "citation": (
            "Fuhr L, Mor U, Kolodziejczyk A A, et al. Gut microbiota modulates "
            "weight gain in mice after discontinued smoke exposure[J]. Nature, "
            "2021, 600(7890): 713-719."
        ),
        "url": "https://zhuanlan.zhihu.com/p/688009793",
        "title": "当你说不会配色……SCI论文插图经典配色实例第32期",
        "note": "中间一格 #FEFDFE 几乎与白底同色，只适合做色阶中间点。",
        "colors": [
            "#224767", "#6FAEE0", "#A1CAED", "#D1E6F8",
            "#FEFDFE", "#E4CCE4", "#CA95C3", "#A85EA2",
            "#8E338A",
        ],
    },
}

#: Recommended display order: newest issue first.
PALETTE_ORDER = [
    "akun42_nature",
    "akun41_nature",
    "akun40_tibet",
    "akun39_echarts",
    "akun38_latlf_m",
    "akun37_nature",
    "akun36_nature",
    "akun35_science",
    "akun33_science",
    "akun32_nature",
]

# Short series label used for palette colour names, e.g. "P42 Nature".
PALETTE_PREFIX = "P"


def palette_names():
    """Palette keys, newest issue first."""
    return list(PALETTE_ORDER)


def palette_metadata(name):
    """Metadata mapping for ``name`` (raises ``KeyError`` when unknown)."""
    return SCIENTIFIC_PALETTES[name]


def palette_series_label(name):
    """Compact label such as ``"P42 Nature"`` or ``"P40 未标注"``."""
    meta = SCIENTIFIC_PALETTES[name]
    journal = meta["journal"].split("/")[0].strip()
    if journal.startswith("原文未标注"):
        journal = "未标注"
    return f"{PALETTE_PREFIX}{meta['issue']} {journal}"


def palette_label(name):
    """Human readable one-line description used in pickers."""
    meta = SCIENTIFIC_PALETTES[name]
    return (f"{palette_series_label(name)} · {len(meta['colors'])} colors"
            f" · {meta['kind'].split('/')[0].strip()}")


def palette_colors(name, count=None, reverse=False):
    """Return the colours of ``name``.

    ``count`` sub-samples evenly when smaller than the palette and wraps around
    when larger; ``reverse`` flips the order (useful for sequential ramps).
    """
    palette = list(SCIENTIFIC_PALETTES[name]["colors"])
    if reverse:
        palette = palette[::-1]
    if count is None:
        return palette
    if count <= 0:
        return []
    if count >= len(palette):
        return [palette[i % len(palette)] for i in range(count)]
    step = len(palette) / count
    return [palette[int(i * step)] for i in range(count)]


def palettes_with_at_least(count):
    """Palette keys that supply ``count`` distinct colours."""
    return [key for key in PALETTE_ORDER
            if len(SCIENTIFIC_PALETTES[key]["colors"]) >= count]


def all_palette_colors():
    """Every palette colour, in :data:`PALETTE_ORDER`, de-duplicated."""
    seen = set()
    result = []
    for key in PALETTE_ORDER:
        for color in SCIENTIFIC_PALETTES[key]["colors"]:
            lowered = color.lower()
            if lowered not in seen:
                seen.add(lowered)
                result.append(color)
    return result


def palette_color_items():
    """``[(display_name, hex), ...]`` for every palette colour.

    Names look like ``"P42 Nature 1"`` so they can be used as dictionary keys in
    a colour dropdown while staying readable.
    """
    items = []
    for key in PALETTE_ORDER:
        label = palette_series_label(key)
        for position, color in enumerate(SCIENTIFIC_PALETTES[key]["colors"], start=1):
            items.append((f"{label} {position}", color))
    return items


def describe_palette(name):
    """One-line metadata summary, e.g. ``"第42期 | Nature | 8色"``."""
    meta = SCIENTIFIC_PALETTES[name]
    return (f"第{meta['issue']}期 | {meta['journal']} | "
            f"{len(meta['colors'])}色 | {meta['kind']}")


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    for key in PALETTE_ORDER:
        print(f"{key:<18} {describe_palette(key)}")
        print("    " + " ".join(SCIENTIFIC_PALETTES[key]["colors"]))
