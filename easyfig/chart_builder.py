"""
UI-independent chart building utilities for EasyFig.

The Tk GUI (``application.py``) and the command line interface (``cli.py``)
both render through this module, so a figure produced from a terminal is
identical to the one shown in the preview window.

Contents
--------
* :data:`DEFAULT_SETTINGS` / :func:`make_settings` - one canonical, validated
  settings dictionary shared by both front ends.
* :func:`render_chart` / :func:`export_figure` - headless rendering.
* :func:`apply_processing` - fitting / outlier removal / smoothing.
* Table, multi-line and JSON loaders used by the CLI.
"""

from __future__ import annotations

import json
import math
import os

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from .config import (
    AVAILABLE_COLORS,
    AVAILABLE_MARKERS,
    DEFAULT_CHART_TITLE,
    DEFAULT_DPI,
    DEFAULT_FIG_HEIGHT,
    DEFAULT_FIG_WIDTH,
    DEFAULT_XLABEL,
    DEFAULT_YLABEL,
)
from .data_processor import (
    calculate_statistics,
    fit_linear_regression,
    fit_polynomial,
    load_table_dataframe,
    prepare_chart_data,
    process_multiline_excel,
    remove_outliers_iqr,
    smooth_data_moving_average,
    validate_dataset,
)
from .palettes import normalize_color  # noqa: F401  (re-exported for callers)

# ---------------------------------------------------------------------------
# Option tables: (label, internal value).  Shared by the GUI and the CLI.
# ---------------------------------------------------------------------------

VISUAL_PRESET_OPTIONS = [("Default", "default"), ("SCI", "sci")]

FIT_METHOD_OPTIONS = [
    ("None", "none"),
    ("Mean +- SD", "mean_error"),
    ("Linear Fit", "linear"),
    ("Polynomial Fit", "polynomial"),
    ("Remove Outliers", "remove_outliers"),
    ("Smooth Curve", "smooth"),
]

ERRORBAR_MODE_OPTIONS = [("Summary", "summary"), ("Per Size", "per_size")]

LABEL_CONTENT_OPTIONS = [("Y Only", "y"), ("X + Y", "xy")]

EXPORT_MODE_OPTIONS = [
    ("Match Preview", "match_preview"),
    ("Custom Size", "custom_size"),
]

CHART_TYPE_OPTIONS = [
    ("Line", "line"),
    ("Scatter", "scatter"),
    ("Line/Scatter", "line_scatter"),
    ("Pie", "pie"),
    ("Error Bar", "errorbar"),
    ("Bar", "bar"),
]

XAXIS_MODE_OPTIONS = [("Categorical", "categorical"), ("Numeric", "numeric")]

ERRORBAR_METRIC_OPTIONS = [("SD", "SD"), ("SEM", "SEM")]

BAR_STYLE_OPTIONS = [
    ("Solid", "solid"),
    ("White", "white"),
    ("Outline", "none"),
    ("Mesh", "mesh"),
    ("Diagonal", "diagonal"),
    ("Dots", "dots"),
]

LEGEND_LOC_OPTIONS = [
    "auto", "best", "upper right", "upper left", "lower left", "lower right",
    "right", "center left", "center right", "lower center", "upper center",
    "center", "outside right",
]

TABLE_EXTENSIONS = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls")

CHART_TYPE_VALUES = [value for _, value in CHART_TYPE_OPTIONS]


def get_option_labels(options):
    return [label for label, _ in options]


def get_option_values(options):
    return [internal for _, internal in options]


def normalize_option_value(value, options, default):
    if value is None:
        return default
    normalized = str(value).strip().lower()
    for label, internal in options:
        if normalized in (label.lower(), internal.lower()):
            return internal
    return default


def get_option_label(value, options, default_label):
    if value is None:
        return default_label
    normalized = str(value).strip().lower()
    for label, internal in options:
        if normalized in (label.lower(), internal.lower()):
            return label
    return default_label


# ---------------------------------------------------------------------------
# Canonical settings
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    # Titles and axis labels
    "title": DEFAULT_CHART_TITLE,
    "xlabel": DEFAULT_XLABEL,
    "ylabel": DEFAULT_YLABEL,
    "x_unit": "",
    "y_unit": "",
    # Chart type / axes
    "chart_type": "line",
    "xaxis_mode": "categorical",
    "visual_preset": "default",
    # Series display
    "show_mean": False,
    "show_max": False,
    "show_min": False,
    "show_connecting_line": True,
    "show_error_bars_line": False,
    "line_color": "#d62728",
    "line_style": "solid",
    "line_width": 2.0,
    "bar_color": "#1f77b4",
    "bar_style": "solid",
    "bar_edge_width": 1.0,
    "errorbar_color": "#d62728",
    "point_alpha": 0.7,
    "marker_size": 10,
    # Error bar options
    "errorbar_mode": "summary",
    "errorbar_metric": "SD",
    "errorbar_capsize": 7,
    "errorbar_linewidth": 2.0,
    "errorbar_show_mean": True,
    "errorbar_show_max": False,
    "errorbar_show_min": False,
    "errorbar_show_error": True,
    # Data labels
    "show_data_labels": False,
    "label_font_size": 10,
    "label_content": "y",
    # Legend
    "show_legend": True,
    "legend_font_size": 14,
    "legend_marker_size": 10,
    "legend_loc": "auto",
    "legend_ncol": 1,
    # Ticks / axis styling
    "tick_label_size": 14,
    "tick_label_bold": False,
    "x_tick_rotation": 0.0,
    "tick_length": 4.0,
    "tick_width": 1.5,
    "x_tick_count": 6,
    "y_tick_count": 6,
    "use_custom_x_ticks": False,
    "x_tick_min": 0.0,
    "x_tick_max": 100.0,
    "x_tick_step": 5.0,
    "use_custom_y_ticks": False,
    "y_tick_min": 0.0,
    "y_tick_max": 1.0,
    "y_tick_step": 0.1,
    "auto_x_ticks": True,
    "auto_y_ticks": True,
    "force_origin_zero": True,
    "show_minor_ticks": False,
    "reverse_y_axis": False,
    "axis_label_font_size": 12,
    "title_font_size": 16,
    # Broken axis
    "use_broken_y_axis": False,
    "broken_y_bot_min": 0.0,
    "broken_y_bot_max": 10.0,
    "broken_y_top_min": 90.0,
    "broken_y_top_max": 100.0,
    "use_broken_x_axis": False,
    "broken_x_left_min": 0.0,
    "broken_x_left_max": 10.0,
    "broken_x_right_min": 90.0,
    "broken_x_right_max": 100.0,
    # Export
    "export_mode": "match_preview",
    "export_dpi": DEFAULT_DPI,
    "fig_width": DEFAULT_FIG_WIDTH,
    "fig_height": DEFAULT_FIG_HEIGHT,
    "export_tight_bbox": False,
}

_BOOL_KEYS = {k for k, v in DEFAULT_SETTINGS.items() if isinstance(v, bool)}
_INT_KEYS = {k for k, v in DEFAULT_SETTINGS.items()
             if isinstance(v, int) and not isinstance(v, bool)}
_FLOAT_KEYS = {k for k, v in DEFAULT_SETTINGS.items() if isinstance(v, float)}

SETTING_NAMES = tuple(sorted(DEFAULT_SETTINGS))


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


def _coerce_number(value, caster, key):
    if value is None or value == "":
        raise ValueError(f"setting {key!r} requires a number")
    try:
        return caster(value)
    except (TypeError, ValueError):
        raise ValueError(f"setting {key!r} expects a number, got {value!r}") from None


#: What each chart type implies for the two series toggles.  Selecting a type
#: should draw what its name says without extra flags; this is the rule the GUI
#: used to apply on its own, which left the CLI and the Electron app rendering a
#: connecting line for ``--chart-type scatter``.
CHART_TYPE_SERIES_DEFAULTS = {
    "line": {"show_connecting_line": True, "show_mean": False},
    "scatter": {"show_connecting_line": False, "show_mean": True},
    "line_scatter": {"show_connecting_line": True, "show_mean": True},
}


def make_settings(overrides=None, **kwargs):
    """Return a complete settings dictionary, validated and coerced.

    ``overrides`` may be any mapping.  Unknown keys raise ``ValueError`` so a
    typo in a CLI flag or a JSON spec fails loudly instead of being ignored.
    """
    raw = {}
    if overrides:
        raw.update(dict(overrides))
    if kwargs:
        raw.update(kwargs)

    unknown = sorted(set(raw) - set(DEFAULT_SETTINGS))
    if unknown:
        raise ValueError(
            "unknown setting(s): " + ", ".join(unknown)
            + "\nvalid settings: " + ", ".join(SETTING_NAMES)
        )

    settings = dict(DEFAULT_SETTINGS)
    for key, value in raw.items():
        if value is None:
            continue
        if key in _BOOL_KEYS:
            settings[key] = _coerce_bool(value)
        elif key in _INT_KEYS:
            settings[key] = int(round(float(value)))
        elif key in _FLOAT_KEYS:
            settings[key] = float(value)
        else:
            settings[key] = value

    settings["visual_preset"] = normalize_option_value(
        settings["visual_preset"], VISUAL_PRESET_OPTIONS, "default")
    settings["chart_type"] = normalize_option_value(
        settings["chart_type"], CHART_TYPE_OPTIONS, "line")
    settings["xaxis_mode"] = normalize_option_value(
        settings["xaxis_mode"], XAXIS_MODE_OPTIONS, "categorical")
    settings["errorbar_mode"] = normalize_option_value(
        settings["errorbar_mode"], ERRORBAR_MODE_OPTIONS, "summary")
    settings["errorbar_metric"] = normalize_option_value(
        settings["errorbar_metric"], ERRORBAR_METRIC_OPTIONS, "SD")
    settings["label_content"] = normalize_option_value(
        settings["label_content"], LABEL_CONTENT_OPTIONS, "y")
    settings["export_mode"] = normalize_option_value(
        settings["export_mode"], EXPORT_MODE_OPTIONS, "match_preview")
    settings["bar_style"] = normalize_option_value(
        settings["bar_style"], BAR_STYLE_OPTIONS, "solid")
    if settings["line_style"] not in ("solid", "dashed"):
        settings["line_style"] = "solid"
    if settings["legend_loc"] not in LEGEND_LOC_OPTIONS:
        settings["legend_loc"] = "auto"

    # Chart types imply their series toggles, unless the caller was explicit.
    for key, value in CHART_TYPE_SERIES_DEFAULTS.get(settings["chart_type"], {}).items():
        if key not in raw:
            settings[key] = value

    # Clamp values that would otherwise produce unreadable or broken charts.
    settings["line_width"] = float(np.clip(settings["line_width"], 0.1, 30.0))
    settings["marker_size"] = int(np.clip(settings["marker_size"], 0, 60))
    settings["label_font_size"] = int(np.clip(settings["label_font_size"], 4, 72))
    settings["legend_font_size"] = int(np.clip(settings["legend_font_size"], 4, 72))
    settings["legend_marker_size"] = int(np.clip(settings["legend_marker_size"], 1, 60))
    settings["legend_ncol"] = int(np.clip(settings["legend_ncol"], 1, 20))
    settings["tick_label_size"] = int(np.clip(settings["tick_label_size"], 4, 72))
    settings["axis_label_font_size"] = int(
        np.clip(settings["axis_label_font_size"], 4, 72))
    settings["title_font_size"] = int(np.clip(settings["title_font_size"], 4, 72))
    settings["x_tick_count"] = int(np.clip(settings["x_tick_count"], 2, 100))
    settings["y_tick_count"] = int(np.clip(settings["y_tick_count"], 2, 100))
    settings["point_alpha"] = float(np.clip(settings["point_alpha"], 0.0, 1.0))
    settings["tick_length"] = float(max(settings["tick_length"], 0.0))
    settings["tick_width"] = float(max(settings["tick_width"], 0.0))
    settings["errorbar_capsize"] = int(np.clip(settings["errorbar_capsize"], 0, 100))
    settings["errorbar_linewidth"] = float(
        np.clip(settings["errorbar_linewidth"], 0.0, 30.0))
    settings["bar_edge_width"] = float(np.clip(settings["bar_edge_width"], 0.0, 30.0))
    settings["export_dpi"] = int(np.clip(settings["export_dpi"], 10, 2400))
    settings["fig_width"] = float(np.clip(settings["fig_width"], 0.5, 100.0))
    settings["fig_height"] = float(np.clip(settings["fig_height"], 0.5, 100.0))

    for key in ("line_color", "bar_color", "errorbar_color"):
        settings[key] = normalize_color(settings[key], DEFAULT_SETTINGS[key])
    return settings




# ---------------------------------------------------------------------------
# Headless rendering
# ---------------------------------------------------------------------------

class HeadlessCanvas:
    """Minimal canvas so ChartManager can run without a GUI toolkit."""

    def __init__(self, figure):
        self.figure = figure
        self._backend = FigureCanvasAgg(figure)

    def draw(self):
        self._backend.draw()

    def draw_idle(self):
        self._backend.draw_idle()

    def mpl_connect(self, *args, **kwargs):
        return None

    def mpl_disconnect(self, *args, **kwargs):
        return None

    def get_tk_widget(self):  # pragma: no cover - GUI only
        raise NotImplementedError("headless canvas has no Tk widget")


def new_figure(figsize=None, dpi=None):
    """Create an Agg-backed figure with an attached canvas."""
    fig = Figure(figsize=figsize or (DEFAULT_FIG_WIDTH, DEFAULT_FIG_HEIGHT),
                dpi=dpi or DEFAULT_DPI)
    FigureCanvasAgg(fig)
    return fig


def render_chart(datasets, settings=None, chart_data=None, figsize=None, dpi=None):
    """Render ``datasets`` (or pre-processed ``chart_data``) and return a Figure.

    ``datasets`` uses the same mapping shape as the GUI:
    ``{name: {'sizes': [...], 'data': [[...], ...], 'color': '#rrggbb', ...}}``.
    """
    from .chart_manager import ChartManager  # late import avoids a cycle

    settings = make_settings(settings)
    if figsize is None:
        figsize = (settings["fig_width"], settings["fig_height"])
    if dpi is None:
        dpi = settings["export_dpi"]

    if chart_data is None:
        chart_data = prepare_chart_data(datasets)
    if not chart_data:
        raise ValueError("no valid dataset to plot")

    fig = new_figure(figsize=figsize, dpi=dpi)
    canvas = HeadlessCanvas(fig)
    ax = fig.add_subplot(111)
    manager = ChartManager(ax, canvas, toolbar=None)
    manager.generate_chart(chart_data, settings)
    return fig


def export_figure(fig, path, settings=None, width=None, height=None,
                  dpi=None, tight=None):
    """Save ``fig`` to ``path`` honouring the export settings."""
    settings = make_settings(settings)
    if dpi is None:
        dpi = settings["export_dpi"]
    if tight is None:
        tight = settings["export_tight_bbox"]

    if width is None or height is None:
        if settings["export_mode"] == "match_preview":
            current_w, current_h = (float(v) for v in fig.get_size_inches())
            width = current_w if width is None else width
            height = current_h if height is None else height
        else:
            width = settings["fig_width"] if width is None else width
            height = settings["fig_height"] if height is None else height

    original = fig.get_size_inches()
    save_kwargs = {"dpi": dpi}
    if tight:
        save_kwargs["bbox_inches"] = "tight"
    if str(path).lower().endswith(".svg"):
        save_kwargs["format"] = "svg"
        save_kwargs["metadata"] = {"Date": None}
    try:
        fig.set_size_inches(width, height)
        fig.canvas.draw()
        fig.savefig(path, **save_kwargs)
    finally:
        fig.set_size_inches(original)
    return str(path)


# ---------------------------------------------------------------------------
# Processing (fitting / outliers / smoothing)
# ---------------------------------------------------------------------------

def fit_summary(name, fit_result, degree=None):
    """Structured description of a fit, for reports and machine consumers."""
    summary = {
        "dataset": name,
        "equation": fit_result.get("equation", ""),
        "rSquared": float(fit_result.get("r_squared", float("nan"))),
        "mse": float(fit_result.get("mse", float("nan"))),
    }
    if degree is not None:
        summary["degree"] = int(degree)
    if "slope" in fit_result:
        summary["slope"] = float(fit_result["slope"])
        summary["intercept"] = float(fit_result["intercept"])
    return summary


def fit_label(name, fit_result, degree=None):
    """Legend label for a fitted curve, including the fit quality.

    Showing only "Linear Fit" hides the two numbers that make the fit useful, so
    the equation and R-squared travel with the curve.
    """
    if degree is None:
        equation = str(fit_result.get("equation", "")).strip()
        r_squared = fit_result.get("r_squared")
        inner = equation or "linear fit"
        if r_squared is not None and np.isfinite(r_squared):
            inner = f"{inner}, R\u00b2={float(r_squared):.4f}"
        return f"{name} ({inner})"
    r_squared = fit_result.get("r_squared")
    inner = f"{degree} 次拟合"
    if r_squared is not None and np.isfinite(r_squared):
        inner = f"{inner}, R\u00b2={float(r_squared):.4f}"
    return f"{name} ({inner})"


def apply_processing(chart_data, method="none", degree=2, show_raw=True,
                     show_fit=True, add_jitter=False):
    """Apply a processing method to ``chart_data``.

    Mirrors the GUI "Process" dropdown.  Returns the original mapping when the
    method is ``none`` or produces no output.
    """
    method = normalize_option_value(method, FIT_METHOD_OPTIONS, "none")
    if method == "none" or not chart_data:
        return chart_data

    result_data = {}
    for name, data in chart_data.items():
        sizes = data["sizes"]
        data_list = data["data"]
        color = data["color"]

        x_data = np.asarray(sizes, dtype=float)
        means = np.array(
            [float(np.mean(group)) if len(group) else np.nan for group in data_list],
            dtype=float,
        )
        if x_data.shape != means.shape:
            continue
        finite = np.isfinite(x_data) & np.isfinite(means)
        keep = np.flatnonzero(finite)

        if method == "mean_error":
            if not show_fit:
                continue
            valid_x, valid_data, stds = [], [], []
            for i, x in enumerate(sizes):
                if not finite[i]:
                    continue
                pts = data_list[i]
                valid_x.append(x)
                valid_data.append(pts)
                stds.append(float(np.std(np.asarray(pts, dtype=float)))
                            if len(pts) > 1 else 0.0)
            if valid_x:
                result_data[name + " (Mean \u00b1 SD)"] = {
                    "sizes": valid_x,
                    "data": valid_data,
                    "color": color,
                    "stats": calculate_statistics(valid_data),
                    "is_multiline": True,
                    "y_errors": stds,
                }

        elif method == "linear":
            fit_result = fit_linear_regression(x_data[keep], means[keep])
            if fit_result:
                if show_raw:
                    raw = dict(data)
                    raw["show_as_raw"] = True
                    raw["add_jitter"] = add_jitter
                    result_data[name + " (Raw)"] = raw
                if show_fit:
                    fitted = [[float(v)] for v in fit_result["fitted_values"]]
                    result_data[fit_label(name, fit_result)] = {
                        "sizes": [float(v) for v in x_data[keep]],
                        "data": fitted,
                        "color": color,
                        "stats": calculate_statistics(fitted),
                        "is_fit_curve": True,
                        "fit_info": fit_summary(name, fit_result),
                    }

        elif method == "polynomial":
            fit_result = fit_polynomial(x_data[keep], means[keep], degree)
            if fit_result:
                if show_raw:
                    raw = dict(data)
                    raw["show_as_raw"] = True
                    raw["add_jitter"] = add_jitter
                    result_data[name + " (Raw)"] = raw
                if show_fit:
                    x_finite = x_data[keep]
                    x_smooth = np.linspace(float(np.min(x_finite)),
                                           float(np.max(x_finite)), 200)
                    y_smooth = np.poly1d(fit_result["coefficients"])(x_smooth)
                    smooth = [[float(v)] for v in y_smooth]
                    result_data[fit_label(name, fit_result, degree=degree)] = {
                        "sizes": x_smooth.tolist(),
                        "data": smooth,
                        "color": color,
                        "stats": calculate_statistics(smooth),
                        "is_fit_curve": True,
                        "fit_info": fit_summary(name, fit_result, degree=degree),
                    }

        elif method == "remove_outliers":
            if keep.size == 0:
                continue
            filtered_y, removed_local = remove_outliers_iqr(means[keep], x=x_data[keep])
            if len(filtered_y) > 0:
                kept = np.delete(keep, removed_local)
                filtered = [[float(v)] for v in filtered_y]
                removed_x = [float(x_data[i]) for i in keep[removed_local]]
                result_data[name + f" (无异常值, 剔除 {len(removed_local)} 点)"] = {
                    "sizes": [float(v) for v in x_data[kept]],
                    "data": filtered,
                    "color": color,
                    "stats": calculate_statistics(filtered),
                    "removed_points": removed_x,
                }

        elif method == "smooth":
            if keep.size < 2:
                continue
            window = max(2, min(5, keep.size // 2))
            smoothed_y = smooth_data_moving_average(means, window)
            smoothed = [[float(v)] for v in np.asarray(smoothed_y, dtype=float)]
            result_data[name + f" (移动平均, 窗口 {window})"] = {
                "sizes": [float(v) for v in sizes],
                "data": smoothed,
                "color": color,
                "stats": calculate_statistics(smoothed),
            }

    return result_data if result_data else chart_data


# ---------------------------------------------------------------------------
# Dataset construction helpers
# ---------------------------------------------------------------------------

def default_color(index):
    values = list(AVAILABLE_COLORS.values())
    return values[index % len(values)]


def default_marker(index):
    return AVAILABLE_MARKERS[index % len(AVAILABLE_MARKERS)]


def make_dataset(sizes, data, name=None, color=None, marker=None,
                 y_errors=None, is_multiline=False, index=0, strict=True):
    """Build one dataset entry using the GUI's mapping shape."""
    try:
        sizes = [float(v) for v in sizes]
    except (TypeError, ValueError):
        raise ValueError(f"dataset {name or index!r}: 'sizes' must be numeric") from None

    groups = []
    for group in data:
        if group is None:
            groups.append([])
        elif isinstance(group, (int, float, np.integer, np.floating)):
            groups.append([float(group)])
        else:
            try:
                groups.append([float(v) for v in group])
            except (TypeError, ValueError):
                raise ValueError(
                    f"dataset {name or index!r}: a data group contains a non-numeric value"
                ) from None

    if color is None:
        color = default_color(index)
    dataset = {
        "sizes": sizes,
        "data": groups,
        "color": normalize_color(color, default_color(index)),
    }
    if marker:
        dataset["marker"] = marker
    if y_errors is not None:
        dataset["y_errors"] = [float(v) for v in y_errors]
    if is_multiline:
        dataset["is_multiline"] = True

    is_valid, error_msg = validate_dataset(sizes, groups)
    if not is_valid and strict:
        raise ValueError(f"dataset {name or index!r} is invalid: {error_msg}")
    return dataset


def datasets_from_json(payload):
    """Parse a JSON dataset payload into ``{name: dataset}``.

    Accepted shapes::

        {"datasets": [ {...}, ... ]}
        {"datasets": {"A": {...}, "B": {...}}}
        [ {...}, {...} ]
        {"A": {...}, "B": {...}}

    A dataset entry needs ``sizes`` and ``data``; ``data`` may be a list of
    measurement groups or a flat list of numbers matching ``sizes``.
    """
    source = payload
    if isinstance(payload, dict) and "datasets" in payload:
        payload = payload["datasets"]

    if isinstance(payload, dict):
        entries = []
        for key, value in payload.items():
            if not isinstance(value, dict):
                raise ValueError(f"dataset {key!r} must be an object")
            entry = dict(value)
            entry.setdefault("name", key)
            entries.append(entry)
    elif isinstance(payload, list):
        entries = list(payload)
    else:
        raise ValueError("'datasets' must be an object or a list")

    if not entries:
        raise ValueError("no datasets found in the input")

    datasets = {}
    used = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"dataset #{index + 1} must be an object")
        if "sizes" not in entry or "data" not in entry:
            raise ValueError(f"dataset #{index + 1} needs both 'sizes' and 'data'")
        base_name = str(entry.get("name") or f"Dataset_{index + 1}")
        sizes = entry["sizes"]
        data = entry["data"]
        if not isinstance(sizes, (list, tuple)):
            raise ValueError(f"dataset {base_name!r}: 'sizes' must be a list")
        if not isinstance(data, (list, tuple)):
            raise ValueError(f"dataset {base_name!r}: 'data' must be a list")
        if data and not isinstance(data[0], (list, tuple, type(None))):
            if len(data) != len(sizes):
                raise ValueError(
                    f"dataset {base_name!r}: flat 'data' has {len(data)} values "
                    f"but 'sizes' has {len(sizes)} entries"
                )
            data = [[v] for v in data]

        name = base_name
        counter = 2
        while name in used:
            name = f"{base_name}_{counter}"
            counter += 1
        used.add(name)

        datasets[name] = make_dataset(
            sizes,
            data,
            name=name,
            color=entry.get("color"),
            marker=entry.get("marker"),
            y_errors=entry.get("y_errors"),
            is_multiline=bool(entry.get("is_multiline", False)),
            index=index,
        )

    return datasets


# ---------------------------------------------------------------------------
# Table / multi-line import
# ---------------------------------------------------------------------------

def load_table(path, sheet_name=0):
    """Read a CSV/TSV/Excel table into a DataFrame."""
    return load_table_dataframe(path, sheet_name=sheet_name)


def datasets_from_table(df, orientation="vertical", time_column=None,
                        time_unit="s", base_index=0):
    """Convert a DataFrame into datasets, mirroring the GUI import dialog.

    ``'vertical'`` treats each column as one dataset, ``'horizontal'`` treats
    each row as one dataset.  When ``time_column`` is given, that column
    supplies the X values and is excluded from the datasets.
    """
    import pandas as pd

    if df is None or df.empty:
        raise ValueError("the table is empty")
    if orientation not in ("vertical", "horizontal"):
        raise ValueError("orientation must be 'vertical' or 'horizontal'")

    datasets = {}
    used_names = set()

    def unique_name(candidate):
        name = str(candidate)
        counter = 2
        while name in used_names:
            name = f"{candidate}_{counter}"
            counter += 1
        used_names.add(name)
        return name

    if orientation == "vertical":
        columns = [c for c in df.columns if c != time_column]
        if not columns:
            raise ValueError("no data columns to import")
        tseries = None
        if time_column is not None:
            if time_column not in df.columns:
                raise ValueError(f"time column {time_column!r} is not in the table")
            tseries = pd.to_numeric(df[time_column], errors="coerce")
            if str(time_unit) == "ms":
                tseries = tseries / 1000.0

        for position, column in enumerate(columns):
            yseries = pd.to_numeric(df[column], errors="coerce")
            pairs = []
            for row_number, y in enumerate(yseries.tolist()):
                if y is None or not _is_finite(y):
                    continue
                if tseries is not None:
                    x = tseries.iloc[row_number]
                    if x is None or not _is_finite(x):
                        continue
                else:
                    x = float(row_number) + 1.0
                pairs.append((float(x), float(y)))
            if not pairs:
                continue
            if tseries is not None:
                pairs.sort(key=lambda pair: pair[0])
            name = unique_name(column)
            datasets[name] = make_dataset(
                [p[0] for p in pairs],
                [[p[1]] for p in pairs],
                name=name,
                index=base_index + position,
            )
    else:
        for position in range(len(df)):
            row = df.iloc[position]
            pairs = []
            for column_position, y in enumerate(row.tolist()):
                if y is None or not _is_finite(y):
                    continue
                pairs.append((float(column_position) + 1.0, float(y)))
            if not pairs:
                continue
            label = row.iloc[0] if len(row) else f"Row_{position}"
            name = unique_name(label)
            datasets[name] = make_dataset(
                [p[0] for p in pairs],
                [[p[1]] for p in pairs],
                name=name,
                index=base_index + position,
            )

    if not datasets:
        raise ValueError("no numeric values found in the table")
    return datasets


def _is_finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def datasets_from_multiline(paths, orientation="vertical", merge=False, base_index=0):
    """Import one or more multi-line files (xlsx/xls/csv), mirroring the GUI."""
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    paths = list(paths)
    if not paths:
        raise ValueError("no input files given")

    results = []
    errors = []
    for path in paths:
        try:
            results.append(process_multiline_excel(path, orientation=orientation))
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    if not results:
        raise ValueError("no file could be imported:\n" + "\n".join(errors))

    datasets = {}
    used_names = set()

    def unique_name(candidate):
        name = str(candidate)
        counter = 2
        while name in used_names:
            name = f"{candidate}_{counter}"
            counter += 1
        used_names.add(name)
        return name

    if merge:
        merged = {}
        for result in results:
            raw = result.get("raw_data") or []
            means = result.get("y") or []
            for i, x in enumerate(result["x"]):
                bucket = merged.setdefault(x, [])
                if i < len(raw) and raw[i]:
                    bucket.extend(raw[i])
                elif i < len(means):
                    bucket.append(means[i])
        if merged:
            sorted_x = sorted(merged)
            groups = [merged[x] for x in sorted_x]
            y_errors = [
                float(np.std(np.asarray(g, dtype=float))) if len(g) > 1 else 0.0
                for g in groups
            ]
            name = unique_name("Merged_Dataset")
            datasets[name] = make_dataset(
                sorted_x, groups, name=name, y_errors=y_errors,
                is_multiline=True, index=base_index,
            )
    else:
        for offset, result in enumerate(results):
            raw = result.get("raw_data") or []
            means = result.get("y") or []
            groups = raw if raw else [[v] for v in means]
            y_errors = result.get("y_err") or [0.0] * len(result["x"])
            name = unique_name(result.get("label") or f"Dataset_{offset + 1}")
            datasets[name] = make_dataset(
                result["x"], groups, name=name, y_errors=y_errors,
                is_multiline=True, index=base_index + offset,
            )

    if not datasets:
        raise ValueError("no dataset could be built from the input files")
    return datasets


# ---------------------------------------------------------------------------
# Spec files
# ---------------------------------------------------------------------------

def load_spec(path):
    """Load a JSON render spec, returning ``(datasets, settings_overrides)``.

    The spec may hold ``datasets`` and ``settings`` keys; a bare dataset list or
    mapping is also accepted.  Pass ``"-"`` to read standard input.
    """
    if path in (None, "-"):
        import sys

        text = sys.stdin.read()
        source = "<stdin>"
    else:
        with open(path, "r", encoding="utf-8-sig") as handle:
            text = handle.read()
        source = str(path)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source} is not valid JSON: {exc}") from None

    if not isinstance(payload, dict):
        return datasets_from_json(payload), {}

    if "datasets" in payload:
        datasets = datasets_from_json(payload["datasets"])
    elif "settings" in payload and len(payload) == 1:
        raise ValueError(
            f"{source} has 'settings' but no 'datasets'; add a 'datasets' list "
            "or pass a table with --table"
        )
    else:
        datasets = datasets_from_json(payload)

    settings = payload.get("settings") or {}
    if not isinstance(settings, dict):
        raise ValueError("'settings' must be an object")
    return datasets, settings
