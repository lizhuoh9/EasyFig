#!/usr/bin/env python3
"""
EasyFig command line interface.

Render the same charts the GUI produces, without opening a window, so EasyFig
can be driven from a shell, a Makefile, a CI job or another program.

Examples
--------
Render a table with one dataset per column:

    python -m easyfig plot --table results.csv --chart-type bar -o bar.png

Multi-line import (one file per series, merged into one dataset):

    python -m easyfig plot --multiline a.xlsx b.xlsx --merge -o merged.png \\
        --title "Thrust" --xlabel "Size" --x-unit in --y-unit kg

Full control from a JSON spec, machine readable result on stdout:

    python -m easyfig spec spec.json --json-out

Compose several charts into one multi-panel figure (a/b/c markers, one font):

    python -m easyfig compose --spec figure.json -o figure.png
    python -m easyfig compose --table results.csv --layout big-left-2 \\
        --panels "1;2,3;4,5,6,7" -o figure.png
    python -m easyfig compose --table results.csv --layout big-top-3 --print-layout
    python -m easyfig layouts             # every preset, drawn as ASCII

Read a spec from a pipe:

    cat spec.json | python -m easyfig spec - -o out.svg

List every supported setting and its default:

    python -m easyfig options

Once installed, the ``easyfig`` console script is shorter and does the same
thing, so the examples read ``easyfig plot ...`` in the documentation.

Exit codes: 0 success, 1 processing error, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import matplotlib

# Select a non-interactive backend before pyplot is imported anywhere.
matplotlib.use("Agg")

from . import chart_builder  # noqa: E402
from .chart_builder import (  # noqa: E402
    BAR_STYLE_OPTIONS,
    CHART_TYPE_OPTIONS,
    DEFAULT_SETTINGS,
    ERRORBAR_METRIC_OPTIONS,
    ERRORBAR_MODE_OPTIONS,
    EXPORT_MODE_OPTIONS,
    FIT_METHOD_OPTIONS,
    LABEL_CONTENT_OPTIONS,
    LEGEND_LOC_OPTIONS,
    VISUAL_PRESET_OPTIONS,
    XAXIS_MODE_OPTIONS,
    apply_processing,
    datasets_from_json,
    datasets_from_multiline,
    datasets_from_table,
    export_figure,
    get_option_labels,
    get_option_values,
    load_spec,
    load_table,
    make_settings,
    render_chart,
)
from .palettes import PALETTE_ORDER, SCIENTIFIC_PALETTES  # noqa: E402
from .palettes import palette_colors as palette_colors_for  # noqa: E402
from .palettes import palette_label, palette_names  # noqa: E402
from . import compose as compose_engine  # noqa: E402
from .compose import (  # noqa: E402
    COMPOSE_DEFAULT_SETTINGS,
    LAYOUT_PRESETS,
    PRESET_ORDER,
    compose_figure_data,
    compose_spec_schema,
    list_presets,
    load_compose_spec,
    make_compose_settings,
    panels_from_datasets,
    parse_panel_groups,
    plan_layout,
)

__version__ = "1.3.0"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


class CliError(Exception):
    """An expected, user-facing failure."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stderr(message):
    print(message, file=sys.stderr)


def _make_output_robust():
    """Never crash because a console codepage cannot render a character.

    Palette metadata contains Chinese text.  On a console whose codepage cannot
    represent it, ``print`` would raise ``UnicodeEncodeError`` and the command
    would fail; downgrade that to a replacement character instead.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except Exception:
            pass


def _choice(values):
    return sorted(set(values))


def _parse_sheet(value):
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _parse_set_pairs(pairs):
    """Turn repeated ``KEY=VALUE`` flags into a settings mapping."""
    overrides = {}
    for item in pairs or []:
        if "=" not in item:
            raise CliError(f"--set expects KEY=VALUE, got {item!r}")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise CliError(f"--set expects KEY=VALUE, got {item!r}")
        overrides[key] = value.strip()
    return overrides


def _namespace_overrides(args):
    """Collect every explicitly supplied chart option into a settings mapping."""
    overrides = {}
    for key in DEFAULT_SETTINGS:
        value = getattr(args, key, None)
        if value is not None:
            overrides[key] = value
    overrides.update(_parse_set_pairs(getattr(args, "set", None)))
    return overrides


def _build_settings(args, spec_settings=None):
    overrides = dict(spec_settings or {})
    overrides.update(_namespace_overrides(args))
    try:
        return make_settings(overrides)
    except ValueError as exc:
        raise CliError(str(exc)) from None


def _input_sources(args):
    return [
        name for name, value in (
            ("--table", getattr(args, "table", None)),
            ("--multiline", getattr(args, "multiline", None)),
            ("--json", getattr(args, "json", None)),
            ("--spec", getattr(args, "spec", None)),
        ) if value
    ]


def _load_datasets(args):
    """Load datasets from whichever input source the user selected."""
    sources = _input_sources(args)
    if not sources:
        raise CliError(
            "no input given: use --table, --multiline, --json or --spec "
            "(or pass a positional input file)"
        )
    if len(sources) > 1:
        raise CliError("choose only one input source, got: " + ", ".join(sources))

    if getattr(args, "spec", None):
        return load_spec(args.spec)

    if getattr(args, "json", None):
        path = args.json
        try:
            if path == "-":
                payload = json.loads(sys.stdin.read())
            else:
                with open(path, "r", encoding="utf-8-sig") as handle:
                    payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise CliError(f"{path} is not valid JSON: {exc}") from None
        except OSError as exc:
            raise CliError(f"cannot read {path}: {exc}") from None
        return datasets_from_json(payload), {}

    if getattr(args, "multiline", None):
        datasets = datasets_from_multiline(
            args.multiline,
            orientation=args.orientation,
            merge=bool(args.merge),
        )
        return datasets, {}

    # --table
    sheet = _parse_sheet(getattr(args, "sheet", None))
    try:
        frame = load_table(args.table, sheet_name=sheet)
    except (OSError, ValueError, ImportError) as exc:
        raise CliError(str(exc)) from None
    datasets = datasets_from_table(
        frame,
        orientation=args.orientation,
        time_column=getattr(args, "time_column", None),
        time_unit=getattr(args, "time_unit", "s") or "s",
    )
    return datasets, {}


def _render(args, datasets, settings):
    """Apply processing, render and optionally export. Returns (fig, info)."""
    chart_data = None
    method = args.fit or "none"
    if method != "none":
        from .data_processor import prepare_chart_data

        chart_data = prepare_chart_data(datasets)
        if not chart_data:
            raise CliError("no valid dataset to plot")
        chart_data = apply_processing(
            chart_data,
            method=method,
            degree=args.degree,
            show_raw=settings.get("_show_raw", True),
            show_fit=settings.get("_show_fit", True),
            add_jitter=settings.get("_add_jitter", False),
        )

    render_settings = {k: v for k, v in settings.items() if not k.startswith("_")}
    dpi = args.dpi if args.dpi is not None else render_settings["export_dpi"]
    figsize = None
    if args.width is not None and args.height is not None:
        figsize = (args.width, args.height)

    try:
        fig = render_chart(datasets, render_settings, chart_data=chart_data,
                           figsize=figsize, dpi=dpi)
    except ValueError as exc:
        raise CliError(str(exc)) from None

    # ``chart_data`` is what was actually drawn; without processing it is the
    # prepared view of the input datasets.
    plotted = chart_data
    if plotted is None:
        from .data_processor import prepare_chart_data as _prepare

        plotted = _prepare(datasets)
    return fig, render_settings, plotted


def _export(fig, args, render_settings):
    out = args.out
    extension = os.path.splitext(out)[1].lower()
    if extension not in (".png", ".pdf", ".svg", ".jpg", ".jpeg", ".webp",
                         ".tif", ".tiff", ".eps", ".ps"):
        raise CliError(
            f"unsupported output extension {extension!r}; "
            "use .png, .pdf, .svg, .eps, .jpg or .tiff"
        )
    dpi = args.dpi if args.dpi is not None else render_settings["export_dpi"]
    try:
        export_figure(
            fig, out, render_settings,
            width=args.width,
            height=args.height,
            dpi=dpi,
            tight=args.tight if args.tight is not None else None,
        )
    except OSError as exc:
        raise CliError(f"cannot write {out}: {exc}") from None
    return out


def apply_palette(datasets, palette_name, reverse=False):
    """Recolour ``datasets`` in order from a built-in scientific palette.

    Colours are taken with :func:`palettes.palette_colors`, so a palette with
    fewer colours than datasets wraps around and one with more is sub-sampled.
    """
    if palette_name not in PALETTE_ORDER:
        raise CliError(
            f"unknown palette {palette_name!r}; available: "
            + ", ".join(PALETTE_ORDER)
        )
    colors = palette_colors_for(palette_name, count=len(datasets), reverse=reverse)
    for dataset, color in zip(datasets.values(), colors):
        dataset['color'] = color
    return datasets


def _result_payload(args, plotted, settings, out_path, fig):
    """Describe what was actually drawn, not just what was loaded.

    With ``--fit`` the input datasets are replaced by the fitted curves and raw
    point clouds, and a pipeline needs to see that.
    """
    width, height = (float(v) for v in fig.get_size_inches())
    dpi = args.dpi if args.dpi is not None else settings["export_dpi"]
    payload = {
        "ok": True,
        "output": out_path,
        "datasets": list(plotted.keys()),
        "dataset_count": len(plotted),
        "colors": [data.get("color") for data in plotted.values()],
        "chart_type": settings["chart_type"],
        "width_in": round(width, 4),
        "height_in": round(height, 4),
        "dpi": int(dpi),
        "pixel_width": int(round(width * dpi)),
        "pixel_height": int(round(height * dpi)),
    }
    fits = [data["fit_info"] for data in plotted.values() if data.get("fit_info")]
    if fits:
        payload["fits"] = fits
    if getattr(args, "palette", None):
        payload["palette"] = args.palette
    if out_path and os.path.exists(out_path):
        payload["bytes"] = os.path.getsize(out_path)
    return payload


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _add_input_arguments(parser):
    parser.add_argument("input", nargs="?", default=None,
                        help="input file; inferred from the extension "
                             "(table or multi-line data)")
    parser.add_argument("--table", metavar="PATH",
                        help="CSV/TSV/Excel table: columns (or rows) are datasets")
    parser.add_argument("--multiline", nargs="+", metavar="PATH",
                        help="one or more multi-line Excel/CSV files, one series each")
    parser.add_argument("--json", metavar="PATH",
                        help="dataset JSON file ('-' reads stdin)")
    parser.add_argument("--spec", metavar="PATH",
                        help="spec JSON file ('-' reads stdin); for `compose` it "
                             "also carries the layout and the panels")
    parser.add_argument("--orientation", choices=["vertical", "horizontal"],
                        default="vertical",
                        help="table/multi-line orientation (default: vertical)")
    parser.add_argument("--sheet", metavar="NAME|INDEX", default=None,
                        help="worksheet name or index for Excel input")
    parser.add_argument("--time-column", metavar="COLUMN", default=None,
                        help="use this column as X values instead of row numbers")
    parser.add_argument("--time-unit", choices=["s", "ms"], default="s",
                        help="unit of --time-column (default: s)")
    parser.add_argument("--merge", action="store_true",
                        help="merge equal X values across multi-line files")


def _add_output_arguments(parser):
    parser.add_argument("-o", "--out", metavar="PATH", default=None,
                        help="output figure path; the extension chooses the format")
    parser.add_argument("--dpi", type=int, default=None, help="output resolution")
    parser.add_argument("--width", type=float, default=None, help="figure width in inches")
    parser.add_argument("--height", type=float, default=None, help="figure height in inches")
    parser.add_argument("--tight", action=argparse.BooleanOptionalAction,
                        default=None, help="crop surrounding whitespace")
    parser.add_argument("--json-out", action="store_true",
                        help="print a JSON result object on stdout")
    parser.add_argument("--print-settings", action="store_true",
                        help="print the resolved settings as JSON and exit")


def _add_chart_arguments(parser):
    group = parser.add_argument_group("chart settings")

    def add(name, flags, **kwargs):
        kwargs.setdefault("default", None)
        group.add_argument(*flags, dest=name, **kwargs)

    add("chart_type", ["--chart-type"], choices=_choice(get_option_values(CHART_TYPE_OPTIONS)),
        help="chart type")
    add("xaxis_mode", ["--xaxis-mode"], choices=_choice(get_option_values(XAXIS_MODE_OPTIONS)),
        help="treat X values as categories or numbers")
    add("visual_preset", ["--preset"], choices=_choice(get_option_values(VISUAL_PRESET_OPTIONS)),
        help="visual preset")
    add("title", ["--title"])
    add("xlabel", ["--xlabel"])
    add("ylabel", ["--ylabel"])
    add("x_unit", ["--x-unit"])
    add("y_unit", ["--y-unit"])

    add("show_mean", ["--show-mean"], action=argparse.BooleanOptionalAction)
    add("show_max", ["--show-max"], action=argparse.BooleanOptionalAction)
    add("show_min", ["--show-min"], action=argparse.BooleanOptionalAction)
    add("show_connecting_line", ["--show-connecting-line", "--connecting-line"],
        action=argparse.BooleanOptionalAction)
    add("show_error_bars_line", ["--show-line-error-bars", "--line-error-bars"],
        action=argparse.BooleanOptionalAction)
    add("show_data_labels", ["--show-data-labels", "--data-labels"],
        action=argparse.BooleanOptionalAction)
    add("label_content", ["--label-content"],
        choices=_choice(get_option_values(LABEL_CONTENT_OPTIONS)))
    add("show_legend", ["--show-legend", "--legend"],
        action=argparse.BooleanOptionalAction)
    add("legend_loc", ["--legend-loc"], choices=_choice(LEGEND_LOC_OPTIONS))
    add("legend_ncol", ["--legend-cols"], type=int)
    add("legend_font_size", ["--legend-font-size"], type=float)
    add("legend_marker_size", ["--legend-marker-size"], type=float)

    add("line_color", ["--line-color"], metavar="COLOR")
    add("bar_color", ["--bar-color"], metavar="COLOR")
    add("errorbar_color", ["--errorbar-color"], metavar="COLOR")
    group.add_argument("--palette", metavar="NAME", default=None,
                       help="colour the datasets from a built-in scientific "
                            "palette; run `easyfig palettes` to list them")
    group.add_argument("--palette-reverse", action="store_true",
                       help="use the palette back-to-front (sequential ramps)")
    add("line_style", ["--line-style"], choices=["solid", "dashed"])
    add("line_width", ["--line-width"], type=float)
    add("marker_size", ["--marker-size"], type=float)
    add("point_alpha", ["--point-alpha"], type=float)
    add("bar_style", ["--bar-style"], choices=_choice(get_option_values(BAR_STYLE_OPTIONS)))
    add("bar_edge_width", ["--bar-edge-width"], type=float)

    add("errorbar_mode", ["--errorbar-mode"],
        choices=_choice(get_option_values(ERRORBAR_MODE_OPTIONS)))
    add("errorbar_metric", ["--errorbar-metric"],
        choices=_choice(get_option_values(ERRORBAR_METRIC_OPTIONS)))
    add("errorbar_capsize", ["--errorbar-capsize"], type=float)
    add("errorbar_linewidth", ["--errorbar-linewidth"], type=float)
    add("errorbar_show_mean", ["--errorbar-mean"], action=argparse.BooleanOptionalAction)
    add("errorbar_show_error", ["--errorbar-bars"], action=argparse.BooleanOptionalAction)
    add("errorbar_show_max", ["--errorbar-max"], action=argparse.BooleanOptionalAction)
    add("errorbar_show_min", ["--errorbar-min"], action=argparse.BooleanOptionalAction)

    add("tick_label_size", ["--tick-label-size"], type=float)
    add("tick_label_bold", ["--tick-label-bold"], action=argparse.BooleanOptionalAction)
    add("x_tick_rotation", ["--x-tick-rotation"], type=float)
    add("tick_length", ["--tick-length"], type=float)
    add("tick_width", ["--tick-width"], type=float)
    add("x_tick_count", ["--x-tick-count"], type=int)
    add("y_tick_count", ["--y-tick-count"], type=int)
    add("auto_x_ticks", ["--auto-x-ticks"], action=argparse.BooleanOptionalAction)
    add("auto_y_ticks", ["--auto-y-ticks"], action=argparse.BooleanOptionalAction)
    add("force_origin_zero", ["--zero-start"], action=argparse.BooleanOptionalAction)
    add("show_minor_ticks", ["--minor-ticks"], action=argparse.BooleanOptionalAction)
    add("reverse_y_axis", ["--reverse-y"], action=argparse.BooleanOptionalAction)
    add("axis_label_font_size", ["--axis-font-size"], type=float)
    add("title_font_size", ["--title-font-size"], type=float)
    add("label_font_size", ["--label-font-size"], type=float)

    add("use_custom_x_ticks", ["--custom-x-ticks"], action=argparse.BooleanOptionalAction)
    add("x_tick_min", ["--x-tick-min"], type=float)
    add("x_tick_max", ["--x-tick-max"], type=float)
    add("x_tick_step", ["--x-tick-step"], type=float)
    add("use_custom_y_ticks", ["--custom-y-ticks"], action=argparse.BooleanOptionalAction)
    add("y_tick_min", ["--y-tick-min"], type=float)
    add("y_tick_max", ["--y-tick-max"], type=float)
    add("y_tick_step", ["--y-tick-step"], type=float)

    add("use_broken_y_axis", ["--broken-y"], action=argparse.BooleanOptionalAction)
    add("broken_y_bot_min", ["--broken-y-low-min"], type=float)
    add("broken_y_bot_max", ["--broken-y-low-max"], type=float)
    add("broken_y_top_min", ["--broken-y-high-min"], type=float)
    add("broken_y_top_max", ["--broken-y-high-max"], type=float)
    add("use_broken_x_axis", ["--broken-x"], action=argparse.BooleanOptionalAction)
    add("broken_x_left_min", ["--broken-x-low-min"], type=float)
    add("broken_x_left_max", ["--broken-x-low-max"], type=float)
    add("broken_x_right_min", ["--broken-x-high-min"], type=float)
    add("broken_x_right_max", ["--broken-x-high-max"], type=float)

    group.add_argument("--fit", choices=_choice(get_option_values(FIT_METHOD_OPTIONS)),
                       default=None, help="processing method applied before plotting")
    group.add_argument("--degree", type=int, default=2,
                       help="polynomial degree for --fit polynomial (default: 2)")
    group.add_argument("--show-raw", action=argparse.BooleanOptionalAction, default=None,
                       help="with --fit, also draw the raw points")
    group.add_argument("--show-fit", action=argparse.BooleanOptionalAction, default=None,
                       help="with --fit, also draw the fitted curve")
    group.add_argument("--jitter", action=argparse.BooleanOptionalAction, default=None,
                       help="with --fit linear/polynomial, jitter the raw points")
    group.add_argument("--set", action="append", metavar="KEY=VALUE",
                       help="set any setting directly (repeatable); "
                            "see the 'options' subcommand")


def _add_compose_arguments(parser):
    """Layout and typography flags for multi-panel composition."""
    group = parser.add_argument_group("composition")

    group.add_argument("--layout", dest="layout_preset", metavar="PRESET",
                       default=None,
                       help="layout preset (run `easyfig layouts` to see them all "
                            "with a diagram), e.g. big-left-2 / big-top-3 / 2x2")
    group.add_argument("--rows", dest="grid_rows", type=int, default=None,
                       help="grid rows (manual layout)")
    group.add_argument("--cols", dest="grid_cols", type=int, default=None,
                       help="grid columns (manual layout)")
    group.add_argument("--row-heights", dest="row_heights", metavar="R,R,...",
                       default=None,
                       help="height ratio per row, e.g. 1.4,1 makes the first row bigger")
    group.add_argument("--col-widths", dest="col_widths", metavar="R,R,...",
                       default=None,
                       help="width ratio per column, e.g. 2,1 makes the first column wider")
    group.add_argument("--gap-x", dest="gap_x", type=float, default=None,
                       help="minimum gap between columns")
    group.add_argument("--gap-y", dest="gap_y", type=float, default=None,
                       help="minimum gap between rows")
    group.add_argument("--panels", metavar="GROUPS", default=None,
                       help="panel grouping: groups split on ';', datasets on ','; "
                            "use names or 1-based indices, '*' for everything left, "
                            "e.g. --panels '1;2,3;*'")

    group.add_argument("--label-style", dest="label_style", default=None,
                       choices=_choice(v for _, v in compose_engine.LABEL_STYLE_OPTIONS),
                       help="panel marker style")
    group.add_argument("--label-position", dest="label_position", default=None,
                       choices=_choice(v for _, v in compose_engine.LABEL_POSITION_OPTIONS),
                       help="where the panel marker sits")
    group.add_argument("--label-size", dest="label_font_size", type=int, default=None,
                       help="panel marker font size")
    group.add_argument("--no-labels", dest="label_show", action="store_false",
                       default=None, help="hide the a/b/c panel markers")
    group.add_argument("--suptitle", dest="suptitle", default=None,
                       help="title for the whole composed figure")
    group.add_argument("--no-panel-titles", dest="show_panel_titles",
                       action="store_false", default=None,
                       help="do not title each panel with its dataset name(s)")

    group.add_argument("--font-family", dest="font_family", default=None,
                       help="font family for every panel, e.g. 'Times New Roman' "
                            "or Arial; CJK glyphs fall back automatically")
    group.add_argument("--unify-font-sizes", dest="unify_font_sizes",
                       action=argparse.BooleanOptionalAction, default=None,
                       help="make every panel use these font sizes (default: on)")
    group.add_argument("--panel-width", dest="panel_width", type=float, default=None,
                       help="inches per panel column when sizing automatically")
    group.add_argument("--panel-height", dest="panel_height", type=float, default=None,
                       help="inches per panel row when sizing automatically")
    group.add_argument("--auto-size", dest="auto_size",
                       action=argparse.BooleanOptionalAction, default=None,
                       help="size the canvas from the grid (default: on); turn it "
                            "off to use --width/--height")

    group.add_argument("--print-layout", dest="print_layout", action="store_true",
                       help="print the resolved grid, placement and an ASCII "
                            "diagram, then exit without rendering")
    group.add_argument("--schema", dest="schema", action="store_true",
                       help="print the compose spec schema (for writing spec files) "
                            "and exit")


#: Chart flags that also feed the unified typography of a composed figure.
_COMPOSE_FONT_FLAGS = {
    "title_font_size": "title_font_size",
    "axis_label_font_size": "axis_label_font_size",
    "tick_label_size": "tick_label_size",
    "legend_font_size": "legend_font_size",
    "label_font_size": "data_label_font_size",
    "tick_label_bold": "tick_label_bold",
}


def _compose_overrides(args, spec_compose=None):
    """Collect compose settings from the flags, the spec and the chart flags."""
    overrides = dict(spec_compose or {})
    for key in COMPOSE_DEFAULT_SETTINGS:
        value = getattr(args, key, None)
        if value is not None:
            overrides[key] = value
    for source, target in _COMPOSE_FONT_FLAGS.items():
        value = getattr(args, source, None)
        if value is not None:
            overrides.setdefault(target, value)

    # Spelling out a grid means the user wants that grid, not the automatic one.
    if not overrides.get("layout_preset") and not overrides.get("layout_mode"):
        if (overrides.get("grid_rows") is not None
                or overrides.get("grid_cols") is not None
                or overrides.get("row_heights") or overrides.get("col_widths")):
            overrides["layout_mode"] = "manual"
    return overrides


def _help_epilog():
    """The Examples section of the module docstring, for ``--help``."""
    text = __doc__.split("Examples", 1)[-1]
    text = text.split("Exit codes")[0]
    lines = [line for line in text.splitlines() if line.strip("-").strip()]
    return "\n".join(lines).strip()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="easyfig",
        description="Render EasyFig charts from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_epilog(),
    )
    parser.add_argument("--version", action="version",
                        version=f"EasyFig {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    plot = subparsers.add_parser(
        "plot", help="render a chart from a table, multi-line files or JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_input_arguments(plot)
    _add_output_arguments(plot)
    _add_chart_arguments(plot)

    spec = subparsers.add_parser(
        "spec", help="render a chart from a JSON spec file",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    spec.add_argument("spec", metavar="PATH",
                      help="spec JSON file ('-' reads stdin)")
    _add_output_arguments(spec)
    _add_chart_arguments(spec)

    options = subparsers.add_parser(
        "options", help="list supported settings and their defaults")
    options.add_argument("--json", action="store_true",
                         help="print the settings as JSON")

    compose = subparsers.add_parser(
        "compose", help="compose several charts into one multi-panel figure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Compose a multi-panel figure: several charts on one canvas, each "
            "with an a/b/c marker, sharing one font and one set of font sizes.\n\n"
            "The layout is not limited to a uniform grid.  A panel can span "
            "rows/columns, and rows/columns can have different sizes, so one "
            "chart can be deliberately larger than the others."
        ))
    _add_input_arguments(compose)
    _add_output_arguments(compose)
    _add_compose_arguments(compose)
    _add_chart_arguments(compose)

    layouts = subparsers.add_parser(
        "layouts", help="list the layout presets with an ASCII diagram")
    layouts.add_argument("preset", nargs="?", default=None,
                         help="show one preset in detail")
    layouts.add_argument("--json", action="store_true",
                         help="print the presets as JSON")
    layouts.add_argument("--schema", action="store_true",
                         help="print the compose spec schema instead")

    palettes = subparsers.add_parser(
        "palettes", help="list the ten built-in scientific palettes")
    palettes.add_argument("--json", action="store_true",
                          help="print the palettes as JSON")

    gui = subparsers.add_parser("gui", help="launch the graphical interface")
    gui.add_argument("files", nargs="*", help="accepted for compatibility")

    subparsers.add_parser(
        "bridge",
        help="serve the JSON bridge on stdin/stdout (used by the Electron app)")

    return parser


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _apply_fit_switches(args, settings):
    """Fold the --fit display switches into the settings mapping."""
    settings = dict(settings)
    settings["_show_raw"] = True if args.show_raw is None else bool(args.show_raw)
    settings["_show_fit"] = True if args.show_fit is None else bool(args.show_fit)
    settings["_add_jitter"] = False if args.jitter is None else bool(args.jitter)
    return settings


def _infer_input(args):
    """Let a lone positional argument behave like --table/--multiline."""
    if not args.input:
        return args
    extension = os.path.splitext(args.input)[1].lower()
    if extension in (".json",):
        args.json = args.json or args.input
    elif extension in (".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".txt"):
        args.table = args.table or args.input
    else:
        raise CliError(
            f"cannot infer the input type of {args.input!r}; "
            "use --table, --multiline or --json"
        )
    return args


def _run_render(args):
    if not args.out and not args.print_settings:
        raise CliError("nothing to do: pass -o/--out PATH or --print-settings")

    datasets = None
    extra_settings = {}
    if _input_sources(args):
        datasets, extra_settings = _load_datasets(args)
    elif not args.print_settings:
        raise CliError(
            "no input given: use --table, --multiline, --json or --spec "
            "(or pass a positional input file)"
        )

    settings = _build_settings(args, extra_settings)
    settings = _apply_fit_switches(args, settings)

    if args.print_settings:
        printable = {k: v for k, v in settings.items() if not k.startswith("_")}
        print(json.dumps(printable, indent=2, sort_keys=True, default=str))
        if not args.out:
            return EXIT_OK

    if datasets is None:
        raise CliError("no input given; nothing to render")

    if getattr(args, "palette", None):
        apply_palette(datasets, args.palette,
                      reverse=bool(getattr(args, "palette_reverse", False)))

    fig, render_settings, plotted = _render(args, datasets, settings)
    out_path = _export(fig, args, render_settings)

    if args.json_out:
        print(json.dumps(_result_payload(args, plotted, render_settings, out_path, fig),
                         sort_keys=True))
    else:
        _stderr(f"Wrote {out_path}")
    return EXIT_OK


def command_plot(args):
    return _run_render(_infer_input(args))


def command_spec(args):
    return _run_render(args)


def _as_ascii_json(payload):
    """json.dumps tuned for pipes: pure ASCII, so any codepage survives."""
    return json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=False,
                      default=str)


def command_compose(args):
    """Compose several charts into one multi-panel figure."""
    if args.schema:
        print(_as_ascii_json(compose_spec_schema()))
        return EXIT_OK

    spec_settings = {}
    compose_from_spec = {}
    panels = None
    if getattr(args, "spec", None):
        try:
            loaded = load_compose_spec(args.spec)
        except ValueError as exc:
            raise CliError(str(exc)) from None
        datasets = loaded["datasets"]
        spec_settings = loaded["settings"]
        compose_from_spec = loaded["compose"]
        panels = loaded["panels"]
    else:
        datasets, spec_settings = _load_datasets(args)

    if not datasets:
        raise CliError("no datasets to compose")

    settings = _build_settings(args, spec_settings)
    settings = _apply_fit_switches(args, settings)
    render_settings = {k: v for k, v in settings.items() if not k.startswith("_")}

    overrides = _compose_overrides(args, compose_from_spec)
    # --title on a composed figure names the whole figure; panel titles come
    # from the panels themselves (or their dataset names).
    if args.title and not overrides.get("suptitle"):
        overrides["suptitle"] = args.title

    try:
        compose_settings = make_compose_settings(overrides)
    except ValueError as exc:
        raise CliError(str(exc)) from None

    if panels is None and getattr(args, "panels", None):
        try:
            panels = parse_panel_groups(args.panels, list(datasets))
        except ValueError as exc:
            raise CliError(str(exc)) from None
    if panels is None:
        panels = panels_from_datasets(datasets)

    if args.print_settings:
        print(_as_ascii_json({"settings": render_settings,
                              "compose": compose_settings}))
        if not args.out and not args.print_layout:
            return EXIT_OK

    if args.print_layout:
        try:
            info = plan_layout(datasets, panels, compose_settings)
        except ValueError as exc:
            raise CliError(str(exc)) from None
        print(info["diagram"])
        print()
        print(f"网格 {info['rows']} × {info['cols']}，{info['panelCount']} 个面板，"
              f"画布 {info['figureWidth']:.2f} × {info['figureHeight']:.2f} in")
        for panel in info["panels"]:
            span = f"{panel['rowspan']}×{panel['colspan']}"
            print(f"  {panel['label']:<3} 第{panel['row'] + 1}行 第{panel['col'] + 1}列  "
                  f"跨{span:<4} {' / '.join(panel['datasets'])}")
        if args.json_out:
            print(_as_ascii_json(info))
        if not args.out:
            return EXIT_OK

    if not args.out:
        raise CliError("nothing to do: pass -o/--out PATH, --print-layout "
                       "or --print-settings")

    fit = None
    if args.fit and args.fit != "none":
        fit = {
            "method": args.fit,
            "degree": args.degree,
            "showRaw": settings.get("_show_raw", True),
            "showFit": settings.get("_show_fit", True),
            "addJitter": settings.get("_add_jitter", False),
        }

    if getattr(args, "palette", None):
        apply_palette(datasets, args.palette,
                      reverse=bool(getattr(args, "palette_reverse", False)))

    figsize = None
    if args.width is not None and args.height is not None:
        figsize = (args.width, args.height)
    dpi = args.dpi if args.dpi is not None else compose_settings["export_dpi"]

    try:
        fig, info = compose_figure_data(
            datasets, panels, settings=render_settings, compose=compose_settings,
            figsize=figsize, dpi=dpi, fit=fit)
    except ValueError as exc:
        raise CliError(str(exc)) from None

    out = args.out
    extension = os.path.splitext(out)[1].lower()
    if extension not in (".png", ".pdf", ".svg", ".jpg", ".jpeg", ".webp",
                         ".tif", ".tiff", ".eps", ".ps"):
        raise CliError(
            f"unsupported output extension {extension!r}; "
            "use .png, .pdf, .svg, .eps, .jpg or .tiff")

    width, height = (float(v) for v in fig.get_size_inches())
    tight = args.tight if args.tight is not None \
        else compose_settings["export_tight_bbox"]
    try:
        export_figure(fig, out, render_settings, width=width, height=height,
                      dpi=dpi, tight=tight)
    except OSError as exc:
        raise CliError(f"cannot write {out}: {exc}") from None

    if args.json_out:
        payload = {
            "ok": True,
            "output": out,
            "rows": info["rows"],
            "cols": info["cols"],
            "panel_count": info["panelCount"],
            "panels": info["panels"],
            "labels": info["labels"],
            "layout_preset": compose_settings["layout_preset"],
            "font_family": compose_settings["font_family"],
            "width_in": round(width, 4),
            "height_in": round(height, 4),
            "dpi": int(dpi),
            "pixel_width": int(round(width * dpi)),
            "pixel_height": int(round(height * dpi)),
        }
        if os.path.exists(out):
            payload["bytes"] = os.path.getsize(out)
        print(json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str))
    else:
        _stderr(f"Wrote {out}  ({info['rows']}×{info['cols']}, "
                f"{info['panelCount']} panels)")
    return EXIT_OK


def command_layouts(args):
    """List the layout presets with a picture of each arrangement."""
    if args.schema:
        print(_as_ascii_json(compose_spec_schema()))
        return EXIT_OK

    presets = list_presets()
    if args.json:
        print(_as_ascii_json(presets))
        return EXIT_OK

    keys = [preset["key"] for preset in presets]
    if args.preset:
        if args.preset not in keys:
            raise CliError(f"unknown layout preset {args.preset!r}; available: "
                           + ", ".join(keys))
        for preset in presets:
            if preset["key"] != args.preset:
                continue
            print(f"{preset['key']}  {preset['label']}")
            if preset["rows"]:
                print(f"  网格 {preset['rows']}×{preset['cols']} · "
                      f"{preset['panels']} 个面板")
            for line in preset["diagram"].splitlines():
                print("  " + line)
            print()
            print("  spec 里的写法:")
            print("    " + json.dumps({"layout": preset["layout"]},
                                      ensure_ascii=False))
            print("  命令行:")
            print(f"    easyfig compose --table data.csv --layout {preset['key']} "
                  "-o figure.png")
        return EXIT_OK

    print("布局预设：用 --layout KEY 指定，或写进 spec 的 layout.preset")
    print("标注 a/b/c… 的方框就是面板；· 表示空位。")
    for preset in presets:
        print()
        print(f"{preset['key']:<14}{preset['label']}")
        if preset["rows"]:
            print(f"  网格 {preset['rows']}×{preset['cols']} · "
                  f"{preset['panels']} 个面板")
        for line in preset["diagram"].splitlines():
            print("  " + line)
    print()
    print("单个预设详情： easyfig layouts <preset>")
    print("spec 完整格式： easyfig compose --schema")
    print("示例： easyfig compose --table data.csv --layout big-top-3 -o figure.png")
    return EXIT_OK


def command_options(args):
    if args.json:
        print(json.dumps(DEFAULT_SETTINGS, indent=2, sort_keys=True))
        return EXIT_OK

    tables = [
        ("Chart types", CHART_TYPE_OPTIONS),
        ("X axis mode", XAXIS_MODE_OPTIONS),
        ("Visual preset", VISUAL_PRESET_OPTIONS),
        ("Error bar mode", ERRORBAR_MODE_OPTIONS),
        ("Error bar metric", ERRORBAR_METRIC_OPTIONS),
        ("Bar style", BAR_STYLE_OPTIONS),
        ("Label content", LABEL_CONTENT_OPTIONS),
        ("Export mode", EXPORT_MODE_OPTIONS),
        ("Processing", FIT_METHOD_OPTIONS),
    ]
    for title, options in tables:
        print(f"{title}:")
        for label, value in options:
            print(f"  {value:<16} {label}")
        print()

    print("Legend positions:")
    print("  " + ", ".join(LEGEND_LOC_OPTIONS))
    print()
    print("Settings (defaults):")
    for key in sorted(DEFAULT_SETTINGS):
        print(f"  {key:<24} {DEFAULT_SETTINGS[key]!r}")
    print()
    print("Any setting can be set with --set KEY=VALUE.")
    return EXIT_OK


def command_palettes(args):
    """List the built-in scientific palettes."""
    if args.json:
        payload = {
            name: {
                "issue": meta["issue"],
                "journal": meta["journal"],
                "kind": meta["kind"],
                "colors": list(meta["colors"]),
                "citation": meta["citation"],
                "url": meta.get("url", ""),
                "note": meta.get("note", ""),
            }
            for name, meta in ((key, SCIENTIFIC_PALETTES[key]) for key in PALETTE_ORDER)
        }
        # ensure_ascii keeps the JSON pure ASCII so it survives any console or
        # pipe encoding; consumers still decode the original CJK text.
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    for name in PALETTE_ORDER:
        meta = SCIENTIFIC_PALETTES[name]
        print(f"{name}")
        print(f"  issue    : {meta['issue']}   journal: {meta['journal']}")
        print(f"  kind     : {meta['kind']}")
        print(f"  colors   : {' '.join(meta['colors'])}")
        if meta.get("note"):
            print(f"  note     : {meta['note']}")
        print(f"  source   : {meta.get('url', '')}")
        print()
    print("Use a palette with: easyfig plot --table t.csv --palette akun42_nature -o out.png")
    return EXIT_OK


def command_bridge(args):
    """Serve the JSON bridge used by the Electron front end."""
    from .bridge import main as bridge_main

    return bridge_main()


def command_gui(args):
    try:
        import tkinter as tk
    except ImportError as exc:  # pragma: no cover
        raise CliError(f"tkinter is not available: {exc}") from None
    from .application import DataAnalysisGUI

    root = tk.Tk()
    DataAnalysisGUI(root)
    root.mainloop()
    return EXIT_OK


COMMANDS = {
    "plot": command_plot,
    "spec": command_spec,
    "compose": command_compose,
    "layouts": command_layouts,
    "options": command_options,
    "palettes": command_palettes,
    "bridge": command_bridge,
    "gui": command_gui,
}


def main(argv=None):
    _make_output_robust()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return EXIT_USAGE

    handler = COMMANDS[args.command]
    try:
        return handler(args)
    except CliError as exc:
        _stderr(f"error: {exc}")
        return EXIT_USAGE if args.command == "options" else EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover
        _stderr("interrupted")
        return EXIT_ERROR
    except Exception as exc:  # pragma: no cover - unexpected failure
        if os.environ.get("EASYFIG_DEBUG"):
            raise
        _stderr(f"error: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
