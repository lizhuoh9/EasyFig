"""
Multi-panel figure composition (拼图).

Turns several one-panel charts into a single publication-style figure: a grid of
panels, an ``a``/``b``/``c`` marker on each, and one font stack plus one set of
font sizes shared by every panel.

Layouts are not limited to a uniform grid.  A layout is described by

* ``rows`` / ``cols`` - the grid;
* ``row_heights`` / ``col_widths`` - ratios, so one row or column can be
  deliberately larger;
* per panel ``rowspan`` / ``colspan`` - so one chart can occupy a 2x2 block
  while its neighbours stay small;
* optional per panel ``row`` / ``col`` - exact placement instead of the default
  reading-order flow.

Everything is expressible in one JSON spec, which is what ``easyfig compose``
consumes: a layout can be written, reviewed and iterated on without touching the
interface.  :func:`compose_spec_schema` dumps the schema, :func:`layout_diagram`
renders an ASCII picture of a resolved layout, and :func:`list_presets` lists
ready-made shapes.

The single-chart path (:func:`easyfig.chart_builder.render_chart`) is untouched.
Composition builds its own figure and asks
:class:`~easyfig.chart_manager.ChartManager` to draw into cells it already owns,
so no panel can rearrange the layout.

Deliberate limitations of a composed figure:

* a panel never gets a broken axis - nesting a broken-axis grid inside a panel
  would fight the outer grid;
* a panel legend always sits inside its cell - the engine's "outside right"
  placement adjusts the *figure* margins, which would move every other panel.
"""

from __future__ import annotations

import json
import math
import sys

from . import chart_builder
from .chart_builder import DEFAULT_SETTINGS, HeadlessCanvas, new_figure
from .data_processor import prepare_chart_data
from .fonts import configure_matplotlib_fonts

# ---------------------------------------------------------------------------
# Option tables shared with the interface and the CLI
# ---------------------------------------------------------------------------

LAYOUT_MODE_OPTIONS = [("自动网格", "auto"), ("手动行列", "manual")]

LABEL_STYLE_OPTIONS = [
    ("a b c", "abc"),
    ("(a) (b) (c)", "paren"),
    ("A B C", "ABC"),
    ("a. b. c.", "dot"),
]

LABEL_POSITION_OPTIONS = [("面板外左上", "outside"), ("面板内左上", "inside")]

#: Font families offered by the interface.  An empty value keeps whatever the
#: renderer already picked (the CJK stack, or the serif stack under SCI).
FONT_FAMILY_OPTIONS = [
    ("跟随预设", ""),
    ("Times New Roman", "Times New Roman"),
    ("Arial", "Arial"),
    ("Helvetica", "Helvetica"),
    ("Calibri", "Calibri"),
    ("Georgia", "Georgia"),
    ("微软雅黑", "Microsoft YaHei"),
    ("黑体", "SimHei"),
    ("宋体", "SimSun"),
]

#: Widest column/row ratio an automatic grid may use (1x3 is fine, 1x7 is not).
MAX_AUTO_ASPECT = 3.2

#: Narrowest column/row ratio an automatic grid may use.  Automatic layouts read
#: as landscape figures; ask for a portrait one with the 2x1/3x1 preset.
MIN_AUTO_ASPECT = 0.75

#: Aspect an automatic grid aims for; a little wider than tall reads as a
#: typical journal figure.
TARGET_AUTO_ASPECT = 1.5


# ---------------------------------------------------------------------------
# Layout presets
# ---------------------------------------------------------------------------
#
# ``spans`` lists ``[rowspan, colspan]`` per panel in reading order; ``positions``
# may pin a panel to an exact cell (``[row, col]``) when the flow cannot express
# the shape (a tall panel on the right, for example).  ``panels`` is how many
# panels the preset is designed for.

LAYOUT_PRESETS = {
    "auto": {"label": "自动网格（按面板数计算）", "rows": 0, "cols": 0},

    "1x2": {"label": "左右两栏", "rows": 1, "cols": 2},
    "2x1": {"label": "上下两栏", "rows": 2, "cols": 1},
    "1x3": {"label": "横排三栏", "rows": 1, "cols": 3},
    "3x1": {"label": "竖排三栏", "rows": 3, "cols": 1},
    "1x4": {"label": "横排四栏", "rows": 1, "cols": 4},
    "2x2": {"label": "田字四格", "rows": 2, "cols": 2},
    "2x3": {"label": "两行三列", "rows": 2, "cols": 3},
    "3x2": {"label": "三行两列", "rows": 3, "cols": 2},
    "2x4": {"label": "两行四列", "rows": 2, "cols": 4},
    "4x2": {"label": "四行两列", "rows": 4, "cols": 2},
    "3x3": {"label": "三行三列", "rows": 3, "cols": 3},

    "wide-narrow": {
        "label": "左宽右窄", "rows": 1, "cols": 2, "col_widths": [2.0, 1.0],
    },
    "narrow-wide": {
        "label": "左窄右宽", "rows": 1, "cols": 2, "col_widths": [1.0, 2.0],
    },
    "tall-short": {
        "label": "上大下小", "rows": 2, "cols": 1, "row_heights": [2.0, 1.0],
    },
    "short-tall": {
        "label": "上小下大", "rows": 2, "cols": 1, "row_heights": [1.0, 2.0],
    },

    "big-left-1": {
        "label": "左大 + 右侧一小", "rows": 2, "cols": 2, "panels": 2,
        "col_widths": [1.35, 1.0], "spans": [[2, 1], [2, 1]],
    },
    "big-left-2": {
        "label": "左大 + 右侧两小", "rows": 2, "cols": 2, "panels": 3,
        "col_widths": [1.35, 1.0], "spans": [[2, 1], [1, 1], [1, 1]],
    },
    "big-left-3": {
        "label": "左大 + 右侧三小", "rows": 3, "cols": 2, "panels": 4,
        "col_widths": [1.35, 1.0], "spans": [[3, 1], [1, 1], [1, 1], [1, 1]],
    },
    "big-left-4": {
        "label": "左大 + 右侧四小", "rows": 4, "cols": 2, "panels": 5,
        "col_widths": [1.35, 1.0],
        "spans": [[4, 1], [1, 1], [1, 1], [1, 1], [1, 1]],
    },
    "big-right-2": {
        "label": "左侧两小 + 右大", "rows": 2, "cols": 2, "panels": 3,
        "col_widths": [1.0, 1.35],
        "spans": [[1, 1], [1, 1], [2, 1]],
        "positions": [None, None, [0, 1]],
    },
    "big-top-2": {
        "label": "上横跨 + 下两小", "rows": 2, "cols": 2, "panels": 3,
        "row_heights": [1.4, 1.0], "spans": [[1, 2], [1, 1], [1, 1]],
    },
    "big-top-3": {
        "label": "上横跨 + 下三小", "rows": 2, "cols": 3, "panels": 4,
        "row_heights": [1.4, 1.0],
        "spans": [[1, 3], [1, 1], [1, 1], [1, 1]],
    },
    "big-bottom-2": {
        "label": "上两小 + 下横跨", "rows": 2, "cols": 2, "panels": 3,
        "row_heights": [1.0, 1.4], "spans": [[1, 1], [1, 1], [1, 2]],
    },
    "big-top-4": {
        "label": "上横跨 + 下四小", "rows": 3, "cols": 2, "panels": 5,
        "row_heights": [1.4, 1.0, 1.0],
        "spans": [[1, 2], [1, 1], [1, 1], [1, 1], [1, 1]],
    },
}

PRESET_ORDER = list(LAYOUT_PRESETS)


# ---------------------------------------------------------------------------
# Canonical compose settings
# ---------------------------------------------------------------------------

COMPOSE_DEFAULT_SETTINGS = {
    # Layout
    "layout_mode": "auto",
    "layout_preset": "",
    "grid_rows": 2,
    "grid_cols": 4,
    "row_heights": [],
    "col_widths": [],
    "gap_x": 0.22,
    "gap_y": 0.34,
    "margin_left": 0.055,
    "margin_right": 0.985,
    "margin_bottom": 0.075,
    "margin_top": 0.94,
    # Panel markers
    "label_show": True,
    "label_style": "abc",
    "label_position": "outside",
    "label_font_size": 14,
    "label_bold": True,
    # Whole-figure title
    "suptitle": "",
    "suptitle_font_size": 18,
    # Panel titles
    "show_panel_titles": True,
    # Unified typography
    "unify_font_sizes": True,
    "font_family": "",
    "title_font_size": 13,
    "axis_label_font_size": 11,
    "tick_label_size": 9,
    "legend_font_size": 9,
    "data_label_font_size": 8,
    "tick_label_bold": False,
    # Canvas
    "auto_size": True,
    "panel_width": 3.0,
    "panel_height": 2.8,
    "fig_width": 12.0,
    "fig_height": 5.0,
    "export_dpi": 300,
    "export_tight_bbox": True,
}

COMPOSE_SETTING_NAMES = tuple(sorted(COMPOSE_DEFAULT_SETTINGS))

_COMPOSE_BOOL_KEYS = {k for k, v in COMPOSE_DEFAULT_SETTINGS.items()
                      if isinstance(v, bool)}
_COMPOSE_INT_KEYS = {k for k, v in COMPOSE_DEFAULT_SETTINGS.items()
                     if isinstance(v, int) and not isinstance(v, bool)}
_COMPOSE_FLOAT_KEYS = {k for k, v in COMPOSE_DEFAULT_SETTINGS.items()
                       if isinstance(v, float)}

#: Keys a panel entry may carry besides ``settings``.
PANEL_KEYS = ("datasets", "names", "title", "settings", "rowspan", "colspan",
              "row", "col")

#: Keys a spec may carry at the top level.
SPEC_KEYS = ("datasets", "settings", "compose", "layout", "panels")

#: Keys allowed inside a spec's ``layout`` object.
LAYOUT_SPEC_KEYS = ("preset", "mode", "rows", "cols", "row_heights", "col_widths",
                    "gap_x", "gap_y", "margin_left", "margin_right",
                    "margin_bottom", "margin_top", "margins")


def _fresh_compose_defaults():
    """A copy of the defaults with the list values copied too."""
    return {key: (list(value) if isinstance(value, list) else value)
            for key, value in COMPOSE_DEFAULT_SETTINGS.items()}


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off", ""):
        return False
    raise ValueError(f"cannot interpret {value!r} as a boolean")


def _coerce_ratios(value, key):
    """Validate a list of positive ratios (an empty list means "uniform")."""
    if value is None or value == "":
        return []
    if isinstance(value, (int, float)):
        value = [value]
    if isinstance(value, str):
        value = [part for part in value.replace(",", " ").split() if part]
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"setting {key!r} expects a list of ratios")
    ratios = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            raise ValueError(
                f"setting {key!r} expects numbers, got {item!r}") from None
        if not math.isfinite(number) or number <= 0:
            raise ValueError(
                f"setting {key!r} expects positive ratios, got {item!r}")
        ratios.append(number)
    return ratios


def make_compose_settings(overrides=None, **kwargs):
    """Return a complete, validated compose settings dictionary.

    Unknown keys raise ``ValueError`` - a typo must fail loudly rather than be
    silently ignored.
    """
    raw = {}
    if overrides:
        raw.update(dict(overrides))
    if kwargs:
        raw.update(kwargs)

    unknown = sorted(set(raw) - set(COMPOSE_DEFAULT_SETTINGS))
    if unknown:
        raise ValueError(
            "unknown compose setting(s): " + ", ".join(unknown)
            + "\nvalid settings: " + ", ".join(COMPOSE_SETTING_NAMES))

    options = _fresh_compose_defaults()
    for key, value in raw.items():
        if value is None:
            continue
        if key in _COMPOSE_BOOL_KEYS:
            options[key] = _coerce_bool(value)
        elif key in _COMPOSE_INT_KEYS:
            options[key] = int(round(float(value)))
        elif key in _COMPOSE_FLOAT_KEYS:
            options[key] = float(value)
        else:
            options[key] = value

    options["layout_mode"] = chart_builder.normalize_option_value(
        options["layout_mode"], LAYOUT_MODE_OPTIONS, "auto")
    options["label_style"] = chart_builder.normalize_option_value(
        options["label_style"], LABEL_STYLE_OPTIONS, "abc")
    options["label_position"] = chart_builder.normalize_option_value(
        options["label_position"], LABEL_POSITION_OPTIONS, "outside")

    preset = str(options.get("layout_preset") or "").strip()
    options["layout_preset"] = preset
    if preset:
        if preset not in LAYOUT_PRESETS:
            raise ValueError(
                f"unknown layout preset {preset!r}; available: "
                + ", ".join(PRESET_ORDER))
        recipe = LAYOUT_PRESETS[preset]
        if preset == "auto" or not recipe.get("rows"):
            options["layout_mode"] = "auto"
        else:
            options["layout_mode"] = "manual"
            # A grid the caller spelled out wins over the preset's own shape;
            # the preset still contributes its spans and ratios.
            if "grid_rows" not in raw:
                options["grid_rows"] = int(recipe["rows"])
            if "grid_cols" not in raw:
                options["grid_cols"] = int(recipe["cols"])
            if recipe.get("row_heights") and not options["row_heights"]:
                options["row_heights"] = list(recipe["row_heights"])
            if recipe.get("col_widths") and not options["col_widths"]:
                options["col_widths"] = list(recipe["col_widths"])

    options["row_heights"] = _coerce_ratios(options["row_heights"], "row_heights")
    options["col_widths"] = _coerce_ratios(options["col_widths"], "col_widths")

    options["grid_rows"] = int(max(options["grid_rows"], 0))
    options["grid_cols"] = int(max(options["grid_cols"], 0))
    options["gap_x"] = float(min(max(options["gap_x"], 0.0), 3.0))
    options["gap_y"] = float(min(max(options["gap_y"], 0.0), 3.0))
    for key in ("margin_left", "margin_right", "margin_bottom", "margin_top"):
        options[key] = float(min(max(options[key], 0.0), 1.0))
    # A margin pair that crossed over would make matplotlib raise.
    if options["margin_left"] >= options["margin_right"]:
        options["margin_left"] = COMPOSE_DEFAULT_SETTINGS["margin_left"]
        options["margin_right"] = COMPOSE_DEFAULT_SETTINGS["margin_right"]
    if options["margin_bottom"] >= options["margin_top"]:
        options["margin_bottom"] = COMPOSE_DEFAULT_SETTINGS["margin_bottom"]
        options["margin_top"] = COMPOSE_DEFAULT_SETTINGS["margin_top"]

    options["label_font_size"] = int(min(max(options["label_font_size"], 4), 96))
    options["suptitle_font_size"] = int(
        min(max(options["suptitle_font_size"], 4), 96))
    for key in ("title_font_size", "axis_label_font_size", "tick_label_size",
                "legend_font_size", "data_label_font_size"):
        options[key] = int(min(max(options[key], 4), 96))
    options["panel_width"] = float(min(max(options["panel_width"], 0.5), 30.0))
    options["panel_height"] = float(min(max(options["panel_height"], 0.5), 30.0))
    options["fig_width"] = float(min(max(options["fig_width"], 0.5), 100.0))
    options["fig_height"] = float(min(max(options["fig_height"], 0.5), 100.0))
    options["export_dpi"] = int(min(max(options["export_dpi"], 10), 2400))
    options["suptitle"] = str(options["suptitle"] or "")
    options["font_family"] = str(options["font_family"] or "").strip()
    return options


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

def normalize_panels(panels, dataset_names):
    """Validate the panel list and return the internal panel specs.

    Each entry names the datasets it shows, may set
    ``rowspan``/``colspan``/``row``/``col``, and may override any single-chart
    setting for that panel only.
    """
    if panels is None:
        raise ValueError("'panels' is required to compose a figure")
    if not isinstance(panels, (list, tuple)) or not panels:
        raise ValueError("a composed figure needs at least one panel")

    known = list(dataset_names)
    specs = []

    for position, entry in enumerate(panels, start=1):
        if isinstance(entry, str):
            entry = {"datasets": [entry]}
        elif isinstance(entry, (list, tuple)):
            entry = {"datasets": list(entry)}
        if not isinstance(entry, dict):
            raise ValueError(f"面板 {position} 必须是一个对象")

        unknown_keys = sorted(set(entry) - set(PANEL_KEYS))
        if unknown_keys:
            raise ValueError(
                f"面板 {position} 有未知键： " + ", ".join(unknown_keys)
                + "\n可用键： " + ", ".join(PANEL_KEYS))

        raw_names = entry.get("datasets", entry.get("names"))
        if isinstance(raw_names, str):
            raw_names = [raw_names]
        if not raw_names:
            raise ValueError(f"面板 {position} 没有指定任何数据集")

        names = []
        for name in raw_names:
            name = str(name)
            if name not in known:
                raise ValueError(f"面板 {position} 引用了不存在的数据集 {name!r}")
            if name not in names:
                names.append(name)

        overrides = entry.get("settings") or {}
        if not isinstance(overrides, dict):
            raise ValueError(f"面板 {position} 的 settings 必须是一个对象")
        unknown = sorted(set(overrides) - set(DEFAULT_SETTINGS))
        if unknown:
            raise ValueError(f"面板 {position} 有未知设置： " + ", ".join(unknown))
        if "title" in entry:
            overrides = dict(overrides, title=entry["title"])

        try:
            rowspan = 1 if entry.get("rowspan") in (None, "") \
                else int(entry["rowspan"])
            colspan = 1 if entry.get("colspan") in (None, "") \
                else int(entry["colspan"])
        except (TypeError, ValueError):
            raise ValueError(
                f"面板 {position} 的 rowspan/colspan 必须是整数") from None
        if rowspan < 1 or colspan < 1:
            raise ValueError(f"面板 {position} 的 rowspan/colspan 必须至少为 1")

        spec = {"names": names, "settings": dict(overrides),
                "rowspan": rowspan, "colspan": colspan}
        for key in ("row", "col"):
            value = entry.get(key)
            if value is None:
                spec[key] = None
            else:
                try:
                    spec[key] = int(value)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"面板 {position} 的 {key} 必须是整数") from None
                if spec[key] < 0:
                    raise ValueError(f"面板 {position} 的 {key} 不能是负数")
        if (spec["row"] is None) != (spec["col"] is None):
            raise ValueError(
                f"面板 {position} 的 row 和 col 必须同时给出，或者都不给")
        specs.append(spec)
    return specs


def apply_preset_layout(specs, options):
    """Apply the spans and positions a preset prescribes.

    A panel that set its own span (anything other than the default 1x1) or its
    own position always wins.
    """
    preset = options.get("layout_preset")
    if not preset or preset == "auto" or preset not in LAYOUT_PRESETS:
        return specs
    recipe = LAYOUT_PRESETS[preset]
    spans = recipe.get("spans") or []
    positions = recipe.get("positions") or []
    for index, spec in enumerate(specs):
        if index < len(spans):
            default_rowspan, default_colspan = (int(v) for v in spans[index])
            if spec["rowspan"] == 1 and spec["colspan"] == 1:
                spec["rowspan"] = default_rowspan
                spec["colspan"] = default_colspan
        if spec["row"] is None and index < len(positions) and positions[index]:
            spec["row"] = int(positions[index][0])
            spec["col"] = int(positions[index][1])
    return specs


def unassigned_datasets(datasets, panels):
    """Names of datasets no panel shows, in their original order."""
    used = set()
    for entry in panels or []:
        if isinstance(entry, dict):
            names = entry.get("datasets", entry.get("names")) or []
        else:
            names = entry or []
        if isinstance(names, str):
            names = [names]
        used.update(str(name) for name in names)
    return [str(name) for name in datasets if str(name) not in used]


def panels_from_datasets(datasets):
    """One panel per dataset - the default grouping the interface starts from."""
    return [{"datasets": [str(name)]} for name in datasets]


# ---------------------------------------------------------------------------
# Grid, placement and labels
# ---------------------------------------------------------------------------

def auto_grid(count):
    """Return the ``(rows, cols)`` an automatic layout should use.

    Prefers the fewest empty cells, then a shape close to
    :data:`TARGET_AUTO_ASPECT`, never wider than :data:`MAX_AUTO_ASPECT` and
    never narrower than :data:`MIN_AUTO_ASPECT`, so 7 panels land on 2x4 and
    3 panels on 1x3.
    """
    count = int(count)
    if count <= 1:
        return (1, 1)

    best_key = None
    best_shape = (1, count)
    for rows in range(1, count + 1):
        cols = int(math.ceil(count / rows))
        aspect = cols / rows
        if aspect > MAX_AUTO_ASPECT or aspect < MIN_AUTO_ASPECT:
            continue
        key = (rows * cols - count, abs(aspect - TARGET_AUTO_ASPECT), rows)
        if best_key is None or key < best_key:
            best_key = key
            best_shape = (rows, cols)
    return best_shape


def resolve_grid(options, specs):
    """Return the ``(rows, cols)`` of the layout for ``specs``.

    An automatic grid is grown until the panels' spans fit; a manual grid is
    used exactly as asked and :func:`place_panels` reports what does not fit.
    """
    count = len(specs)
    max_rowspan = max((spec["rowspan"] for spec in specs), default=1)
    max_colspan = max((spec["colspan"] for spec in specs), default=1)

    if options["layout_mode"] == "manual" or options["layout_preset"]:
        rows = int(options["grid_rows"])
        cols = int(options["grid_cols"])
        if rows < 1 or cols < 1:
            if options["layout_preset"]:
                return auto_grid(count)
            raise ValueError("手动布局需要至少 1 行、1 列")
        return rows, cols

    rows, cols = auto_grid(count)
    rows = max(rows, min(max_rowspan, count))
    cols = max(cols, min(max_colspan, count))
    # A tall/wide panel needs more cells than the plain count suggests.
    needed = sum(spec["rowspan"] * spec["colspan"] for spec in specs)
    while rows * cols < needed and rows < count * 2:
        rows += 1
    return rows, cols


def place_panels(rows, cols, specs):
    """Return ``[(row, col, rowspan, colspan)]`` for every panel.

    Panels that name an explicit ``row``/``col`` are placed first; the rest flow
    into the first free cell (reading order) that fits their span.
    """
    occupied = [[False] * cols for _ in range(rows)]
    placements = [None] * len(specs)

    def fits(row, col, rowspan, colspan):
        if row < 0 or col < 0:
            return False
        if row + rowspan > rows or col + colspan > cols:
            return False
        for r in range(row, row + rowspan):
            for c in range(col, col + colspan):
                if occupied[r][c]:
                    return False
        return True

    def claim(row, col, rowspan, colspan):
        for r in range(row, row + rowspan):
            for c in range(col, col + colspan):
                occupied[r][c] = True

    for index, spec in enumerate(specs):
        row, col = spec["row"], spec["col"]
        if row is None or col is None:
            continue
        rowspan, colspan = spec["rowspan"], spec["colspan"]
        if not fits(row, col, rowspan, colspan):
            raise ValueError(
                f"面板 {index + 1} 无法放在第 {row + 1} 行第 {col + 1} 列"
                f"（跨 {rowspan} 行 {colspan} 列）：超出网格或与其它面板重叠")
        claim(row, col, rowspan, colspan)
        placements[index] = (row, col, rowspan, colspan)

    for index, spec in enumerate(specs):
        if placements[index] is not None:
            continue
        rowspan, colspan = spec["rowspan"], spec["colspan"]
        found = None
        for row in range(rows):
            for col in range(cols):
                if fits(row, col, rowspan, colspan):
                    found = (row, col)
                    break
            if found:
                break
        if found is None:
            raise ValueError(
                f"{rows}×{cols} 的网格放不下第 {index + 1} 个面板"
                f"（跨 {rowspan} 行 {colspan} 列）；请增加行数或列数，"
                "或减少跨格数量")
        claim(found[0], found[1], rowspan, colspan)
        placements[index] = (found[0], found[1], rowspan, colspan)
    return placements


def layout_and_placements(options, specs):
    """Resolve the grid and where every panel sits.

    A preset describes a shape for the number of panels it was designed for.
    When more panels arrive, extra rows are added instead of failing, so
    "左大 + 右侧三小" still works with nine datasets.
    """
    rows, cols = resolve_grid(options, specs)
    preset = str(options.get("layout_preset") or "")
    if not preset or preset == "auto" or options["layout_mode"] != "manual":
        return rows, cols, place_panels(rows, cols, specs)

    last_error = None
    for _ in range(24):
        try:
            return rows, cols, place_panels(rows, cols, specs)
        except ValueError as exc:
            last_error = exc
            rows += 1
    raise last_error


def panel_label(index, style="abc"):
    """Return the marker for panel ``index`` (0-based) in ``style``.

    Beyond ``z`` the letters continue the way spreadsheets do: ``aa``, ``ab``.
    """
    index = int(index)
    if index < 0:
        raise ValueError("panel index must not be negative")

    name = ""
    value = index
    while True:
        name = chr(ord("a") + value % 26) + name
        value = value // 26 - 1
        if value < 0:
            break

    if style == "paren":
        return f"({name})"
    if style == "ABC":
        return name.upper()
    if style == "dot":
        return f"{name}."
    return name


def draw_panel_label(ax, text, options):
    """Draw one ``a``/``b``/``c`` marker in the top-left of ``ax``."""
    size = int(options["label_font_size"])
    weight = "bold" if options["label_bold"] else "normal"
    if options["label_position"] == "inside":
        offset = (size * 0.35, -size * 0.25)
        horizontal = "left"
        vertical = "top"
    else:
        # Outside: the marker's right edge sits just left of the axes, its
        # bottom just above the top edge.
        offset = (-size * 0.25, size * 0.15)
        horizontal = "right"
        vertical = "bottom"

    ax.annotate(
        str(text),
        xy=(0.0, 1.0), xycoords="axes fraction",
        xytext=offset, textcoords="offset points",
        ha=horizontal, va=vertical,
        fontsize=size, fontweight=weight, color="black",
        annotation_clip=False,
    )


def figure_size(options, rows, cols):
    """Overall canvas size in inches for a ``rows`` x ``cols`` grid."""
    if options["auto_size"]:
        return (cols * float(options["panel_width"]),
                rows * float(options["panel_height"]))
    return (float(options["fig_width"]), float(options["fig_height"]))


def build_grid(fig, rows, cols, options, figsize=None, extra_top_in=0.0):
    """Attach a gridspec with the layout's ratios and text-aware margins."""
    row_heights = list(options["row_heights"]) or None
    col_widths = list(options["col_widths"]) or None
    if row_heights and len(row_heights) != rows:
        row_heights = None
    if col_widths and len(col_widths) != cols:
        col_widths = None

    figsize = figsize or fig.get_size_inches()
    gap_x, gap_y = effective_gaps(options, figsize, rows, cols)
    margins = effective_margins(options, figsize, extra_top_in=extra_top_in)
    return fig.add_gridspec(
        rows, cols,
        left=margins["margin_left"], right=margins["margin_right"],
        bottom=margins["margin_bottom"], top=margins["margin_top"],
        wspace=gap_x, hspace=gap_y,
        height_ratios=row_heights, width_ratios=col_widths,
    )


def effective_gaps(options, figsize, rows, cols):
    """``(gap_x, gap_y)`` for the gridspec, never smaller than the text needs.

    ``gap_x``/``gap_y`` are floors: a row needs room for the tick labels, the
    axis label and the next row's panel title, so enlarging the unified font
    sizes without enlarging the gaps would collide.  The engine therefore
    widens a gap whenever the typography asks for more space, and never
    narrows one the user asked for.
    """
    width_in = max(float(figsize[0]), 0.5)
    height_in = max(float(figsize[1]), 0.5)
    axes_w = width_in * max(options["margin_right"] - options["margin_left"],
                            0.1) / max(cols, 1)
    axes_h = height_in * max(options["margin_top"] - options["margin_bottom"],
                             0.1) / max(rows, 1)

    # Line height plus the padding matplotlib puts around labels, in points.
    LINE = 1.6 / 72.0
    stack_y = float(options["axis_label_font_size"]) \
        + float(options["tick_label_size"])
    if options["show_panel_titles"]:
        stack_y += float(options["title_font_size"]) * 1.6 + 12.0
    needed_y = (stack_y * LINE) / max(axes_h, 0.05)

    stack_x = float(options["axis_label_font_size"]) \
        + float(options["tick_label_size"])
    needed_x = (stack_x * LINE) / max(axes_w, 0.05)

    return (max(float(options["gap_x"]), needed_x),
            max(float(options["gap_y"]), needed_y))


def effective_margins(options, figsize, extra_top_in=0.0):
    """Figure margins that leave room for everything drawn outside the axes.

    Ticks, axis labels, panel titles and the a/b/c markers all live outside the
    axes.  A margin expressed only as a fraction of the canvas clips them on a
    small figure, so each margin is at least as large as its text needs and
    never smaller than the value the caller asked for.
    """
    width_in = max(float(figsize[0]), 0.5)
    height_in = max(float(figsize[1]), 0.5)
    LINE = 1.6 / 72.0

    marker = float(options["label_font_size"]) if options["label_show"] else 0.0
    title = float(options["title_font_size"]) if options["show_panel_titles"] else 0.0
    axis = float(options["axis_label_font_size"])
    tick = float(options["tick_label_size"])

    slack = 0.05
    top_in = max(marker, title) * LINE + slack + float(extra_top_in)
    left_in = max(axis + tick, marker) * LINE + slack
    bottom_in = (axis + tick) * LINE + slack
    right_in = slack * 0.5

    left = max(options["margin_left"], left_in / width_in)
    right = min(options["margin_right"], 1.0 - right_in / width_in)
    bottom = max(options["margin_bottom"], bottom_in / height_in)
    top = min(options["margin_top"], 1.0 - top_in / height_in)

    # Never let the reserved margins swallow the drawing area.
    left = min(left, max(right - 0.2, 0.02))
    bottom = min(bottom, max(top - 0.2, 0.02))
    right = max(right, left + 0.1)
    top = max(top, bottom + 0.1)
    return {"margin_left": left, "margin_right": right,
            "margin_bottom": bottom, "margin_top": top}


def suptitle_placement(options, figsize):
    """How much room the whole-figure title needs, and where it sits.

    Returns ``(reserved_inches, y)``; ``reserved_inches`` is ``0`` without a
    title, and ``y`` is the anchor for ``fig.suptitle(..., va="top")``.
    """
    title = str(options.get("suptitle") or "").strip()
    if not title:
        return 0.0, None
    height_in = max(float(figsize[1]), 0.5)
    size = int(options["suptitle_font_size"])
    reserved = (size * 1.6) / 72.0 + 0.04
    y = 1.0 - (size * 0.5) / (height_in * 72.0) - 0.005
    return reserved, y


# ---------------------------------------------------------------------------
# Layout diagrams
# ---------------------------------------------------------------------------

#: Interior width of one grid cell in a diagram, in characters.
DIAGRAM_CELL_WIDTH = 7

_JUNCTIONS = {
    (True, True, True, True): "┼",
    (True, True, True, False): "┤",
    (True, True, False, True): "├",
    (True, True, False, False): "│",
    (True, False, True, True): "┴",
    (True, False, True, False): "┘",
    (True, False, False, True): "└",
    (True, False, False, False): "│",
    (False, True, True, True): "┬",
    (False, True, True, False): "┐",
    (False, True, False, True): "┌",
    (False, True, False, False): "│",
    (False, False, True, True): "─",
    (False, False, True, False): "─",
    (False, False, False, True): "─",
    (False, False, False, False): " ",
}


def layout_diagram(rows, cols, placements, markers=None,
                   cell_width=DIAGRAM_CELL_WIDTH):
    """Render a resolved layout as an ASCII picture.

    ``placements`` is :func:`place_panels` output.  A cell no panel covers keeps
    its own box with a ``·``, so an empty slot is visible at a glance.
    """
    rows, cols = int(rows), int(cols)
    if rows < 1 or cols < 1:
        return ""
    step_x = cell_width + 1
    step_y = 2
    width = cols * step_x + 1
    height = rows * step_y + 1

    # owner[r][c] is the index of the panel covering that cell.  Uncovered cells
    # get a unique negative id so two empty neighbours stay separate boxes.
    owner = [[0] * cols for _ in range(rows)]
    empty_cells = []
    covered = [[False] * cols for _ in range(rows)]
    for index, (row, col, rowspan, colspan) in enumerate(placements or []):
        for r in range(row, min(row + rowspan, rows)):
            for c in range(col, min(col + colspan, cols)):
                owner[r][c] = index + 1
                covered[r][c] = True
    for r in range(rows):
        for c in range(cols):
            if not covered[r][c]:
                owner[r][c] = -(r * cols + c + 1)
                empty_cells.append((r, c))

    def owner_at(row, col):
        if 0 <= row < rows and 0 <= col < cols:
            return owner[row][col]
        return None

    def differs(row1, col1, row2, col2):
        return owner_at(row1, col1) != owner_at(row2, col2)

    canvas = [[" "] * width for _ in range(height)]

    # Straight segments: drawn wherever the two cells they separate belong to
    # different panels (the outside of the grid counts as different).
    for col in range(cols + 1):
        for row in range(rows):
            if differs(row, col - 1, row, col):
                x = col * step_x
                for y in range(row * step_y + 1, (row + 1) * step_y):
                    canvas[y][x] = "│"
    for row in range(rows + 1):
        for col in range(cols):
            if differs(row - 1, col, row, col):
                y = row * step_y
                for x in range(col * step_x + 1, (col + 1) * step_x):
                    canvas[y][x] = "─"

    # Junctions pick their glyph from the four segments meeting there.
    for row in range(rows + 1):
        for col in range(cols + 1):
            up = differs(row - 1, col - 1, row - 1, col)
            down = differs(row, col - 1, row, col)
            left = differs(row - 1, col - 1, row, col - 1)
            right = differs(row - 1, col, row, col)
            canvas[row * step_y][col * step_x] = _JUNCTIONS[
                (up, down, left, right)]

    # Markers, centred in the panel each one belongs to.
    labels = list(markers or [])
    for index, (row, col, rowspan, colspan) in enumerate(placements or []):
        text = str(labels[index]) if index < len(labels) else panel_label(index)
        rowspan = max(int(rowspan), 1)
        colspan = max(int(colspan), 1)
        text_y = (row * step_y + (row + rowspan) * step_y) // 2
        text_x = (col * step_x + (col + colspan) * step_x) // 2
        room = colspan * step_x - 1
        text = text[:max(room, 1)]
        start = text_x - (len(text) // 2)
        for offset, character in enumerate(text):
            x = start + offset
            if 0 <= x < width and canvas[text_y][x] == " ":
                canvas[text_y][x] = character

    for row, col in empty_cells:
        text_y = row * step_y + 1
        text_x = (col * step_x + (col + 1) * step_x) // 2
        if canvas[text_y][text_x] == " ":
            canvas[text_y][text_x] = "·"

    return "\n".join("".join(line).rstrip() for line in canvas)


def preset_layout(key, panel_count=None):
    """The ``(rows, cols, specs)`` a preset implies.

    Without an explicit count the preset's own panel count is used, which is
    what ``easyfig layouts`` lists.
    """
    if key not in LAYOUT_PRESETS:
        raise ValueError(f"unknown layout preset {key!r}")
    recipe = LAYOUT_PRESETS[key]
    rows = int(recipe.get("rows") or 0)
    cols = int(recipe.get("cols") or 0)
    spans = [list(span) for span in recipe.get("spans") or []]
    positions = list(recipe.get("positions") or [])

    count = panel_count if panel_count is not None else (
        recipe.get("panels") or (len(spans) if spans else rows * cols))
    count = int(count)
    if count < 1:
        count = 1

    if not rows or not cols:
        rows, cols = auto_grid(count)

    specs = []
    for index in range(count):
        rowspan, colspan = (spans[index] if index < len(spans) else [1, 1])
        position = positions[index] if index < len(positions) else None
        spec = {"rowspan": int(rowspan), "colspan": int(colspan),
                "row": None, "col": None}
        if position:
            spec["row"], spec["col"] = int(position[0]), int(position[1])
        specs.append(spec)
    return rows, cols, specs


def describe_preset(key, panel_count=None):
    """Metadata, diagram and JSON snippet for one preset."""
    recipe = LAYOUT_PRESETS[key]
    if key == "auto":
        count = int(panel_count or 7)
        rows, cols = auto_grid(count)
        specs = [{"rowspan": 1, "colspan": 1, "row": None, "col": None}
                 for _ in range(count)]
        layout = {"preset": "auto"}
    else:
        rows, cols, specs = preset_layout(key, panel_count)
        layout = {"preset": key}
        if recipe.get("row_heights"):
            layout["row_heights"] = list(recipe["row_heights"])
        if recipe.get("col_widths"):
            layout["col_widths"] = list(recipe["col_widths"])
    placements = place_panels(rows, cols, specs)
    return {
        "key": key,
        "label": recipe.get("label", key),
        "rows": rows,
        "cols": cols,
        "panels": len(specs),
        "diagram": layout_diagram(rows, cols, placements),
        "layout": layout,
        "spans": [[spec["rowspan"], spec["colspan"]] for spec in specs],
    }


def list_presets():
    """Every preset with its diagram, in a stable, readable order."""
    return [describe_preset(key) for key in PRESET_ORDER]


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------

def font_stack(family):
    """``family`` first, then the installed CJK families as fallbacks.

    Without the fallback a Chinese label in "Times New Roman" would render as
    tofu boxes; with it Latin text still uses the chosen face.
    """
    family = str(family or "").strip()
    if not family:
        return None
    stack = [family]
    for name in configure_matplotlib_fonts():
        if name not in stack:
            stack.append(name)
    return stack


def _figure_texts(fig):
    """Every text object a reader sees, so unification cannot miss one."""
    for ax in fig.get_axes():
        yield ax.title
        yield ax.xaxis.label
        yield ax.yaxis.label
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            yield label
        legend = ax.get_legend()
        if legend is not None:
            yield from legend.get_texts()
            if legend.get_title() is not None:
                yield legend.get_title()
        for text in ax.texts:
            yield text
    suptitle = getattr(fig, "_suptitle", None)
    if suptitle is not None:
        yield suptitle


def unify_fonts(fig, options):
    """Apply the compose font family to every text in ``fig``."""
    stack = font_stack(options.get("font_family"))
    if not stack:
        return 0
    changed = 0
    for text in _figure_texts(fig):
        if text is None:
            continue
        try:
            text.set_fontfamily(stack)
            changed += 1
        except Exception:
            continue
    return changed


def available_font_families():
    """The offered families, each flagged with whether matplotlib can find it."""
    from matplotlib import font_manager

    installed = {font.name for font in font_manager.fontManager.ttflist}
    result = []
    for label, value in FONT_FAMILY_OPTIONS:
        result.append({
            "label": label,
            "value": value,
            "installed": (not value) or (value in installed),
        })
    return result


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def _panel_settings(global_settings, options, spec):
    """Effective single-chart settings for one panel."""
    settings = dict(global_settings)
    overrides = dict(spec["settings"])

    # A panel that picks its own chart type also gets that type's implied series
    # toggles (a scatter panel must not draw a connecting line) unless it says
    # otherwise.  The table lives in chart_builder with the single-chart rules.
    if "chart_type" in overrides:
        implied = getattr(chart_builder, "CHART_TYPE_SERIES_DEFAULTS", {})
        for key, value in implied.get(str(overrides["chart_type"]), {}).items():
            overrides.setdefault(key, value)

    settings.update(overrides)

    # A panel is one cell of the outer grid, so it never splits itself.
    settings["use_broken_y_axis"] = False
    settings["use_broken_x_axis"] = False
    # "auto"/"outside right" legends call figure level margin adjustments,
    # which would move every other panel; keep the legend inside the cell.
    if settings.get("legend_loc") in ("auto", "outside right"):
        settings["legend_loc"] = "upper right"

    # The single-chart title is not reused: seven identical titles would be
    # noise.  A panel keeps its own title, else the dataset name(s).
    if "title" in spec["settings"]:
        settings["title"] = str(spec["settings"]["title"] or "")
    elif options["show_panel_titles"]:
        settings["title"] = " / ".join(spec["names"])
    else:
        settings["title"] = ""

    if options["unify_font_sizes"]:
        settings["title_font_size"] = int(options["title_font_size"])
        settings["axis_label_font_size"] = int(options["axis_label_font_size"])
        settings["tick_label_size"] = int(options["tick_label_size"])
        settings["legend_font_size"] = int(options["legend_font_size"])
        settings["label_font_size"] = int(options["data_label_font_size"])
        settings["tick_label_bold"] = bool(options["tick_label_bold"])
    return settings


def plan_layout(datasets, panels, compose=None):
    """Resolve the layout without drawing anything.

    Returns the grid, the placement of every panel, the resolved markers and an
    ASCII diagram - the quickest way to check a spec before rendering.
    """
    options = make_compose_settings(compose)
    specs = apply_preset_layout(normalize_panels(panels, list(datasets)),
                                options)
    rows, cols, placements = layout_and_placements(options, specs)
    labels = [panel_label(index, options["label_style"])
              for index in range(len(specs))]
    width, height = figure_size(options, rows, cols)
    return {
        "rows": rows,
        "cols": cols,
        "panelCount": len(specs),
        "figureWidth": width,
        "figureHeight": height,
        "labels": labels,
        "panels": [
            {
                "index": index,
                "label": labels[index],
                "datasets": list(spec["names"]),
                "row": placements[index][0],
                "col": placements[index][1],
                "rowspan": placements[index][2],
                "colspan": placements[index][3],
            }
            for index, spec in enumerate(specs)
        ],
        "preset": options["layout_preset"],
        "diagram": layout_diagram(rows, cols, placements, labels),
    }


def _apply_fit(chart_data, fit):
    """Apply the single-chart processing pipeline to one panel's data."""
    if not fit:
        return chart_data
    method = str(fit.get("method") or "none").strip().lower()
    if method in ("", "none"):
        return chart_data
    return chart_builder.apply_processing(
        chart_data,
        method=method,
        degree=int(fit.get("degree", 2) or 2),
        show_raw=bool(fit.get("showRaw", True)),
        show_fit=bool(fit.get("showFit", True)),
        add_jitter=bool(fit.get("addJitter", False)),
    )


def compose_figure(datasets, panels, settings=None, compose=None,
                   figsize=None, dpi=None, fit=None):
    """Draw ``panels`` into one figure and return it.

    ``datasets`` is the engine's usual ``{name: dataset}`` mapping; each panel
    names the datasets it shows, so the data itself is stored once.  ``fit``
    applies the shared processing step (mean +- SD, fitting, smoothing) to
    every panel.
    """
    from .chart_manager import ChartManager  # late import avoids a cycle

    global_settings = chart_builder.make_settings(settings)
    options = make_compose_settings(compose)

    specs = apply_preset_layout(normalize_panels(panels, list(datasets)),
                                options)
    rows, cols, placements = layout_and_placements(options, specs)

    if figsize is None:
        figsize = figure_size(options, rows, cols)
    if dpi is None:
        dpi = options["export_dpi"]

    fig = new_figure(figsize=figsize, dpi=dpi)
    canvas = HeadlessCanvas(fig)

    # A whole-figure title needs room above the first row's panel titles.
    title_reserve, title_y = suptitle_placement(options, figsize)
    grid = build_grid(fig, rows, cols, options, figsize=figsize,
                      extra_top_in=title_reserve)

    for index, spec in enumerate(specs):
        row, col, rowspan, colspan = placements[index]
        ax = fig.add_subplot(grid[row:row + rowspan, col:col + colspan])

        subset = {name: datasets[name] for name in spec["names"]}
        chart_data = prepare_chart_data(subset)
        if not chart_data:
            raise ValueError(
                f"面板 {index + 1}（{' / '.join(spec['names'])}）没有可绘制的数据")
        chart_data = _apply_fit(chart_data, fit)

        panel_settings = _panel_settings(global_settings, options, spec)
        manager = ChartManager(ax, canvas, toolbar=None)
        manager.generate_chart(chart_data, panel_settings, clear=False)

        if options["label_show"]:
            draw_panel_label(
                ax, panel_label(index, options["label_style"]), options)

    if str(options["suptitle"]).strip():
        fig.suptitle(str(options["suptitle"]).strip(),
                     fontsize=int(options["suptitle_font_size"]),
                     fontweight="bold", y=title_y, va="top")

    unify_fonts(fig, options)
    return fig


def compose_figure_data(datasets, panels, settings=None, compose=None,
                        figsize=None, dpi=None, fit=None):
    """:func:`compose_figure` plus the resolved layout description."""
    layout = plan_layout(datasets, panels, compose=compose)
    fig = compose_figure(datasets, panels, settings=settings, compose=compose,
                         figsize=figsize, dpi=dpi, fit=fit)
    return fig, layout


# ---------------------------------------------------------------------------
# Spec files
# ---------------------------------------------------------------------------

def layout_to_compose(layout):
    """Translate a spec's ``layout`` object into compose setting overrides."""
    if layout is None:
        return {}
    if not isinstance(layout, dict):
        raise ValueError("'layout' must be an object")

    unknown = sorted(set(layout) - set(LAYOUT_SPEC_KEYS))
    if unknown:
        raise ValueError("unknown layout key(s): " + ", ".join(unknown)
                         + "\nvalid keys: " + ", ".join(LAYOUT_SPEC_KEYS))

    overrides = {}
    mapping = {
        "preset": "layout_preset",
        "mode": "layout_mode",
        "rows": "grid_rows",
        "cols": "grid_cols",
        "row_heights": "row_heights",
        "col_widths": "col_widths",
        "gap_x": "gap_x",
        "gap_y": "gap_y",
        "margin_left": "margin_left",
        "margin_right": "margin_right",
        "margin_bottom": "margin_bottom",
        "margin_top": "margin_top",
    }
    for key, target in mapping.items():
        if layout.get(key) is not None:
            overrides[target] = layout[key]

    if layout.get("margins") is not None:
        values = list(layout["margins"])
        if len(values) != 4:
            raise ValueError("'margins' expects [left, right, bottom, top]")
        for target, value in zip(("margin_left", "margin_right",
                                  "margin_bottom", "margin_top"), values):
            overrides[target] = value

    # Naming rows/cols (or a preset) means that grid was asked for, not the
    # automatic one.
    if "mode" not in overrides:
        preset = str(overrides.get("layout_preset") or "")
        if preset:
            overrides["layout_mode"] = "auto" if preset == "auto" else "manual"
        elif "grid_rows" in overrides or "grid_cols" in overrides:
            overrides["layout_mode"] = "manual"
    return overrides


def load_compose_spec(source):
    """Load a compose spec from a path, ``"-"``/``None`` for stdin, or a mapping.

    Returns ``{"datasets", "settings", "compose", "panels", "origin"}``.
    """
    if isinstance(source, dict):
        payload, origin = source, "<inline>"
    else:
        if source in (None, "-"):
            text = sys.stdin.read()
            origin = "<stdin>"
        else:
            try:
                with open(source, "r", encoding="utf-8-sig") as handle:
                    text = handle.read()
            except OSError as exc:
                raise ValueError(f"cannot read {source}: {exc}") from None
            origin = str(source)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{origin} is not valid JSON: {exc}") from None

    if not isinstance(payload, dict):
        raise ValueError(
            f"{origin} must be a JSON object with 'datasets' and 'panels'")

    unknown = sorted(set(payload) - set(SPEC_KEYS))
    if unknown:
        raise ValueError("unknown spec key(s): " + ", ".join(unknown)
                         + "\nvalid keys: " + ", ".join(SPEC_KEYS))

    if "datasets" not in payload:
        raise ValueError(
            f"{origin} has no 'datasets'; a composed figure needs data")

    datasets = chart_builder.datasets_from_json(payload["datasets"])

    settings = payload.get("settings") or {}
    if not isinstance(settings, dict):
        raise ValueError("'settings' must be an object")

    compose = payload.get("compose") or {}
    if not isinstance(compose, dict):
        raise ValueError("'compose' must be an object")
    compose = dict(compose)
    compose.update(layout_to_compose(payload.get("layout")))

    panels = payload.get("panels")
    if panels is None:
        panels = panels_from_datasets(datasets)
    return {"datasets": datasets, "settings": settings, "compose": compose,
            "panels": panels, "origin": origin}


def parse_panel_groups(text, dataset_names):
    """Parse ``"A;B,C;D"`` into a panel list.

    Groups are separated by ``;``, datasets inside a group by ``,``.  An entry
    may be a dataset name or a 1-based index; ``*`` or ``all`` means every
    dataset no earlier group claimed.
    """
    names = [str(name) for name in dataset_names]
    if text is None:
        return None
    if isinstance(text, (list, tuple)):
        groups = list(text)
    else:
        groups = str(text).split(";")

    panels = []
    claimed = []
    for group in groups:
        group = str(group).strip()
        if not group:
            continue
        if group.lower() in ("*", "all"):
            remaining = [name for name in names if name not in claimed]
            if remaining:
                panels.append({"datasets": remaining})
                claimed.extend(remaining)
            continue
        members = []
        for token in group.replace(",", " ").split():
            if token.lower() in ("*", "all"):
                # "*" inside a group means "everything no earlier group took".
                for name in names:
                    if name not in claimed and name not in members:
                        members.append(name)
                continue
            if token.isdigit():
                index = int(token) - 1
                if index < 0 or index >= len(names):
                    raise ValueError(
                        f"面板序号 {token} 超出范围（共 {len(names)} 个数据集）")
                member = names[index]
            else:
                if token not in names:
                    raise ValueError(
                        f"未知数据集 {token!r}；可用： " + ", ".join(names))
                member = token
            if member not in members:
                members.append(member)
        if not members:
            continue
        claimed.extend(member for member in members if member not in claimed)
        panels.append({"datasets": members})
    if not panels:
        raise ValueError("--panels 没有解析出任何面板")
    return panels


def compose_spec_schema():
    """The complete description of a compose spec, for humans and for AI."""
    example = {
        "datasets": [
            {"name": "Sample A", "sizes": [1, 2, 3],
             "data": [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]], "color": "#1f77b4"},
            {"name": "Sample B", "sizes": [1, 2, 3],
             "data": [[2.0, 2.2], [3.0, 3.1], [4.0, 3.9]], "color": "#d62728"},
            {"name": "Sample C", "sizes": [1, 2, 3],
             "data": [[3.0, 3.3], [4.0, 4.2], [5.0, 4.8]], "color": "#2ca02c"},
        ],
        "layout": {"preset": "big-left-2", "gap_x": 0.22, "gap_y": 0.34},
        "panels": [
            {"datasets": ["Sample A"], "title": "对照组",
             "settings": {"chart_type": "line", "ylabel": "Thrust (kg)"}},
            {"datasets": ["Sample B"], "settings": {"chart_type": "scatter"}},
            {"datasets": ["Sample C"]},
        ],
        "compose": {
            "label_style": "abc",
            "font_family": "Times New Roman",
            "tick_label_size": 9,
            "export_dpi": 300,
        },
        "settings": {"xlabel": "Size (in)", "visual_preset": "sci"},
    }
    return {
        "file": "一个 JSON 对象，可用的顶层键： datasets / settings / compose / layout / panels",
        "keys": {
            "datasets": {
                "required": True,
                "shape": "[{name, sizes, data, color?}] 或 {name: {sizes, data}}",
                "note": "面板用 name 引用数据，数据只存一份",
            },
            "panels": {
                "required": False,
                "shape": "[{datasets: [name...], rowspan?, colspan?, row?, col?, "
                         "title?, settings?}]",
                "note": "省略时每个数据集一格；title/settings 只作用于该格",
                "geometry": {
                    "rowspan/colspan": "整数且 >= 1；把某格放大，例如 2x2",
                    "row/col": "可选的 0 基精确位置；不给就按阅读顺序填第一个空位",
                    "title": "该格标题；不给则用数据集名，可用 show_panel_titles 关掉",
                },
            },
            "layout": {
                "required": False,
                "shape": {
                    "preset": "见 presets，例如 big-left-2 / big-top-3 / 2x2",
                    "rows": "整数，网格行数",
                    "cols": "整数，网格列数",
                    "row_heights": "每行高度比，例如 [1.4, 1]",
                    "col_widths": "每列宽度比，例如 [2, 1]",
                    "gap_x": "列间距，0-3",
                    "gap_y": "行间距，0-3",
                    "margins": "[左, 右, 下, 上]，0-1 的小数",
                },
                "note": "给出 rows/cols 或 preset 就切换成手动布局；"
                        "row_heights/col_widths 用来把某些格子做大",
            },
            "compose": {
                "required": False,
                "defaults": _fresh_compose_defaults(),
                "note": "面板标记、字体统一、整图尺寸",
            },
            "settings": {
                "required": False,
                "defaults": dict(DEFAULT_SETTINGS),
                "note": "单图设置，作为所有面板的全局默认值",
            },
        },
        "presets": list_presets(),
        "layoutPresetKeys": PRESET_ORDER,
        "labelStyles": [value for _, value in LABEL_STYLE_OPTIONS],
        "labelPositions": [value for _, value in LABEL_POSITION_OPTIONS],
        "fontFamilies": [value for _, value in FONT_FAMILY_OPTIONS],
        "examples": [
            "easyfig compose --spec figure.json -o figure.png",
            "easyfig compose --table data.csv --layout big-left-2 "
            "--panels 'A;B;C' -o figure.png",
            "easyfig compose --spec figure.json --print-layout",
            "easyfig layouts",
        ],
        "example": example,
    }


def compose_schema():
    """Everything the interface needs to build the compose inspector."""
    return {
        "composeDefaults": _fresh_compose_defaults(),
        "composeSettingKeys": list(COMPOSE_SETTING_NAMES),
        "layoutModes": [{"label": l, "value": v} for l, v in LAYOUT_MODE_OPTIONS],
        "labelStyles": [{"label": l, "value": v} for l, v in LABEL_STYLE_OPTIONS],
        "labelPositions": [{"label": l, "value": v} for l, v in LABEL_POSITION_OPTIONS],
        "fontFamilies": available_font_families(),
        "layoutPresets": list_presets(),
    }
