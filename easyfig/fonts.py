"""
Matplotlib font configuration.

Matplotlib's bundled DejaVu Sans has no CJK glyphs, so a Chinese dataset name or
axis label renders as tofu boxes.  :func:`configure_matplotlib_fonts` prepends an
installed CJK-capable family to ``font.sans-serif`` and disables the Unicode
minus sign (U+2212 is missing from most of those families), which is the
standard fix.

The result is cached because scanning the font list is comparatively slow.
"""

from __future__ import annotations

#: Families to look for, best first.  Windows, macOS and common Linux
#: distributions are all covered.
CJK_FONT_CANDIDATES = (
    "PingFang SC",
    "Hiragino Sans GB",
    "Heiti SC",
    "Microsoft YaHei",
    "Microsoft JhengHei",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "Source Han Sans SC",
    "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei",
    "Droid Sans Fallback",
    "SimHei",
    "SimSun",
    "FangSong",
    "KaiTi",
)

_configured_families = None


def installed_cjk_fonts():
    """CJK-capable families matplotlib actually knows about, best first."""
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    return [name for name in CJK_FONT_CANDIDATES if name in available]


def configure_matplotlib_fonts(force=False):
    """Make CJK text renderable and return the families that were installed.

    Safe to call repeatedly; the work happens once unless ``force`` is set.
    """
    global _configured_families
    if _configured_families is not None and not force:
        return list(_configured_families)

    import matplotlib

    families = installed_cjk_fonts()
    if families:
        current = list(matplotlib.rcParams.get("font.sans-serif", []))
        merged = families + [name for name in current if name not in families]
        matplotlib.rcParams["font.sans-serif"] = merged
    # U+2212 is absent from several CJK families, which turns "-1" into a box.
    matplotlib.rcParams["axes.unicode_minus"] = False
    _configured_families = families
    return list(families)


def serif_stack():
    """A serif-first family list that still has CJK coverage.

    Used by the SCI preset, which asks for a serif face: the CJK families are
    listed as fallbacks so mixed Latin/Chinese labels stay readable.
    """
    families = configure_matplotlib_fonts()
    stack = ["DejaVu Serif", "Times New Roman"]
    for name in families:
        if name not in stack:
            stack.append(name)
    return stack
