"""
Line-delimited JSON bridge used by the Electron front end.

The Electron app owns the window and the interface; this module owns the chart
engine.  They talk over the child process's standard streams: one JSON object per
line in, one JSON object per line out.  Nothing else is ever written to stdout,
so the protocol stays parseable even when matplotlib or pandas emit warnings.

Request shape::

    {"id": 1, "cmd": "render", "datasets": [...], "settings": {...}}

Response shape::

    {"id": 1, "ok": true,  "result": {...}}
    {"id": 1, "ok": false, "error": {"kind": "...", "message": "..."}}

Run it with ``python -m easyfig.bridge`` or ``easyfig bridge``.  The protocol is
deliberately small and transport-agnostic; :func:`handle_request` is a plain
function, which is what the unit tests drive directly.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import traceback

from . import __version__
from .chart_builder import (
    BAR_STYLE_OPTIONS,
    CHART_TYPE_OPTIONS,
    CHART_TYPE_SERIES_DEFAULTS,
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
    datasets_from_multiline,
    datasets_from_table,
    export_figure,
    load_table,
    make_settings,
    prepare_chart_data,
    render_chart,
)
from .config import AVAILABLE_COLORS, BASE_COLORS, PALETTE_COLORS, X_AXIS_UNITS, Y_AXIS_UNITS
from .palettes import PALETTE_ORDER, SCIENTIFIC_PALETTES, palette_colors
from .compose import (
    compose_figure_data,
    compose_schema,
    make_compose_settings,
    panels_from_datasets,
    plan_layout,
)

PROTOCOL_VERSION = 1

#: Preview renders are capped so a huge figure cannot stall the interface.
MAX_PREVIEW_PIXELS = 4096


class BridgeError(Exception):
    """An expected failure that should be reported to the caller."""

    def __init__(self, message, kind="error"):
        super().__init__(message)
        self.kind = kind


# ---------------------------------------------------------------------------
# Dataset marshalling
# ---------------------------------------------------------------------------

def datasets_to_list(datasets):
    """Convert ``{name: dataset}`` into an ordered list with explicit names.

    The interface uses an array rather than an object because JavaScript
    reorders integer-like object keys, which would silently reshuffle datasets
    named "1", "2", ...
    """
    result = []
    for name, dataset in datasets.items():
        entry = {"name": name}
        for key in ("sizes", "data", "color", "marker", "y_errors", "is_multiline"):
            if key in dataset and dataset[key] is not None:
                value = dataset[key]
                entry[key] = value.tolist() if hasattr(value, "tolist") else value
        result.append(entry)
    return result


def datasets_from_list(entries):
    """Convert the interface's array form back into the engine's mapping form."""
    if isinstance(entries, dict):
        # Tolerate the mapping form as well, so specs and the CLI keep working.
        return {name: dict(value) for name, value in entries.items()}
    if not isinstance(entries, list):
        raise BridgeError("'datasets' must be a list", kind="bad-request")

    datasets = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise BridgeError(f"dataset #{index + 1} must be an object",
                              kind="bad-request")
        dataset = dict(entry)
        name = str(dataset.pop("name", "") or f"Dataset_{index + 1}")
        if not name:
            raise BridgeError(f"dataset #{index + 1} has an empty name",
                              kind="bad-request")
        if name in datasets:
            raise BridgeError(f"duplicate dataset name {name!r}", kind="bad-request")
        if "sizes" not in dataset or "data" not in dataset:
            raise BridgeError(f"dataset {name!r} needs both 'sizes' and 'data'",
                              kind="bad-request")
        datasets[name] = dataset
    return datasets


def _plain(value):
    """Recursively convert numpy scalars/arrays into JSON-friendly values."""
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _statistics(chart_data):
    """Flatten per-dataset statistics for the interface's statistics panel."""
    stats = []
    for name, data in chart_data.items():
        entry = data.get("stats") or {}
        stats.append({
            "name": name,
            "sizes": _plain(data.get("sizes", [])),
            "color": data.get("color", "#1f77b4"),
            "mean": _plain(entry.get("mean", [])),
            "std": _plain(entry.get("std", [])),
            "max": _plain(entry.get("max", [])),
            "min": _plain(entry.get("min", [])),
            "y_errors": _plain(data.get("y_errors")) if data.get("y_errors") is not None else None,
        })
    return stats


# ---------------------------------------------------------------------------
# Schema for the interface
# ---------------------------------------------------------------------------

def _schema():
    """Everything the interface needs to build its controls."""
    return {
        "protocol": PROTOCOL_VERSION,
        "version": __version__,
        "chartTypes": [
            {"label": label, "value": value} for label, value in CHART_TYPE_OPTIONS
        ],
        "chartTypeSeriesDefaults": {
            key: dict(value) for key, value in CHART_TYPE_SERIES_DEFAULTS.items()
        },
        "xaxisModes": [
            {"label": label, "value": value} for label, value in XAXIS_MODE_OPTIONS
        ],
        "presets": [
            {"label": label, "value": value} for label, value in VISUAL_PRESET_OPTIONS
        ],
        "errorbarModes": [
            {"label": label, "value": value} for label, value in ERRORBAR_MODE_OPTIONS
        ],
        "errorbarMetrics": [
            {"label": label, "value": value} for label, value in ERRORBAR_METRIC_OPTIONS
        ],
        "barStyles": [
            {"label": label, "value": value} for label, value in BAR_STYLE_OPTIONS
        ],
        "labelContents": [
            {"label": label, "value": value} for label, value in LABEL_CONTENT_OPTIONS
        ],
        "exportModes": [
            {"label": label, "value": value} for label, value in EXPORT_MODE_OPTIONS
        ],
        "fitMethods": [
            {"label": label, "value": value} for label, value in FIT_METHOD_OPTIONS
        ],
        "legendLocations": list(LEGEND_LOC_OPTIONS),
        "xUnits": list(X_AXIS_UNITS),
        "yUnits": list(Y_AXIS_UNITS),
        "baseColors": [{"name": name, "hex": value}
                       for name, value in BASE_COLORS.items()],
        "palettes": _palettes(),
        "defaultSettings": dict(DEFAULT_SETTINGS),
        "settingKeys": sorted(DEFAULT_SETTINGS),
        "availableColors": [{"name": name, "hex": value}
                            for name, value in AVAILABLE_COLORS.items()],
        "totalAvailableColors": len(AVAILABLE_COLORS),
        "totalPaletteColors": len(PALETTE_COLORS),
        "compose": compose_schema(),
    }


def _palettes():
    result = []
    for key in PALETTE_ORDER:
        meta = SCIENTIFIC_PALETTES[key]
        result.append({
            "key": key,
            "issue": meta["issue"],
            "journal": meta["journal"],
            "kind": meta["kind"],
            "title": meta.get("title", ""),
            "citation": meta.get("citation", ""),
            "note": meta.get("note", ""),
            "url": meta.get("url", ""),
            "colors": list(meta["colors"]),
            "count": len(meta["colors"]),
        })
    return result


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _cmd_hello(request):
    return _schema()


def _cmd_schema(request):
    return _schema()


def _effective_settings(request):
    overrides = request.get("settings") or {}
    if not isinstance(overrides, dict):
        raise BridgeError("'settings' must be an object", kind="bad-request")
    try:
        return make_settings(overrides)
    except ValueError as exc:
        raise BridgeError(str(exc), kind="bad-settings") from None


def _process(request, settings):
    """Return ``(datasets, chart_data)`` with any processing applied."""
    datasets = datasets_from_list(request.get("datasets") or [])
    if not datasets:
        raise BridgeError("no datasets to render", kind="no-data")

    chart_data = prepare_chart_data(datasets)
    if not chart_data:
        raise BridgeError(
            "no valid dataset: every series needs at least one value per size",
            kind="no-data")

    fit = request.get("fit") or {}
    method = fit.get("method") or "none"
    if method != "none":
        chart_data = apply_processing(
            chart_data,
            method=method,
            degree=int(fit.get("degree", 2) or 2),
            show_raw=bool(fit.get("showRaw", True)),
            show_fit=bool(fit.get("showFit", True)),
            add_jitter=bool(fit.get("addJitter", False)),
        )
    return datasets, chart_data


def _figure_size(request, settings):
    width = request.get("width") or settings["fig_width"]
    height = request.get("height") or settings["fig_height"]
    width = max(float(width), 0.5)
    height = max(float(height), 0.5)
    return width, height


def _cmd_render(request):
    """Render a preview and return it as a base64 PNG."""
    settings = _effective_settings(request)
    datasets, chart_data = _process(request, settings)

    width, height = _figure_size(request, settings)
    dpi = int(request.get("dpi") or 110)
    # Keep the preview within a sane pixel budget.
    longest = max(width, height) * dpi
    if longest > MAX_PREVIEW_PIXELS:
        dpi = max(30, int(dpi * MAX_PREVIEW_PIXELS / longest))

    figure = render_chart(datasets, settings, chart_data=chart_data,
                          figsize=(width, height), dpi=dpi)
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=dpi)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    pixel_width = int(round(width * dpi))
    pixel_height = int(round(height * dpi))

    return {
        "png": encoded,
        "format": "png",
        "dpi": dpi,
        "width": width,
        "height": height,
        "pixelWidth": pixel_width,
        "pixelHeight": pixel_height,
        "datasets": [{"name": name, "color": data.get("color")}
                     for name, data in chart_data.items()],
        "statistics": _statistics(chart_data),
    }


def _cmd_export(request):
    """Render at full quality and write the figure to disk."""
    path = request.get("path")
    if not path:
        raise BridgeError("'path' is required to export", kind="bad-request")
    settings = _effective_settings(request)
    datasets, chart_data = _process(request, settings)

    extension = os.path.splitext(path)[1].lower()
    if extension not in (".png", ".pdf", ".svg", ".jpg", ".jpeg", ".webp",
                         ".tif", ".tiff", ".eps", ".ps"):
        raise BridgeError(
            f"unsupported output extension {extension!r}; "
            "use .png, .pdf, .svg, .eps, .jpg or .tiff", kind="bad-request")

    width, height = _figure_size(request, settings)
    dpi = int(request.get("dpi") or settings["export_dpi"])
    figure = render_chart(datasets, settings, chart_data=chart_data,
                          figsize=(width, height), dpi=dpi)
    try:
        export_figure(figure, path, settings, width=width, height=height, dpi=dpi,
                      tight=request.get("tight"))
    except OSError as exc:
        raise BridgeError(f"cannot write {path}: {exc}", kind="io-error") from None

    size = os.path.getsize(path) if os.path.exists(path) else 0
    return {
        "path": os.path.abspath(path),
        "bytes": size,
        "dpi": dpi,
        "width": width,
        "height": height,
        "pixelWidth": int(round(width * dpi)),
        "pixelHeight": int(round(height * dpi)),
    }


def _cmd_statistics(request):
    """Statistics only, so the panel can refresh without a re-render."""
    settings = _effective_settings(request)
    _datasets, chart_data = _process(request, settings)
    return {"statistics": _statistics(chart_data)}


# ---------------------------------------------------------------------------
# Composition ("拼图"): several charts on one canvas
# ---------------------------------------------------------------------------

def _check_export_extension(path):
    extension = os.path.splitext(path)[1].lower()
    if extension not in (".png", ".pdf", ".svg", ".jpg", ".jpeg", ".webp",
                         ".tif", ".tiff", ".eps", ".ps"):
        raise BridgeError(
            f"unsupported output extension {extension!r}; "
            "use .png, .pdf, .svg, .eps, .jpg or .tiff", kind="bad-request")
    return extension


def _compose_setup(request):
    """Validate a compose request and resolve its layout.

    Returns ``(settings, datasets, panels, compose_options, layout)``.
    """
    settings = _effective_settings(request)
    datasets = datasets_from_list(request.get("datasets") or [])
    if not datasets:
        raise BridgeError("no datasets to compose", kind="no-data")

    panels = request.get("panels")
    if panels is None:
        panels = panels_from_datasets(datasets)
    raw = request.get("compose") or {}
    if not isinstance(raw, dict):
        raise BridgeError("'compose' must be an object", kind="bad-request")
    try:
        options = make_compose_settings(raw)
    except ValueError as exc:
        raise BridgeError(str(exc), kind="bad-settings") from None

    try:
        layout = plan_layout(datasets, panels, options)
    except ValueError as exc:
        raise BridgeError(str(exc), kind="bad-layout") from None
    return settings, datasets, panels, options, layout


def _compose_statistics(datasets, layout):
    """Per-dataset statistics across every panel, for the statistics panel."""
    stats = []
    for panel in layout.get("panels", []):
        subset = {name: datasets[name] for name in panel["datasets"]
                  if name in datasets}
        chart_data = prepare_chart_data(subset)
        if chart_data:
            stats.extend(_statistics(chart_data))
    return stats


def _cmd_compose(request):
    """Render a multi-panel figure and return it as a base64 PNG."""
    settings, datasets, panels, options, layout = _compose_setup(request)

    width = float(request.get("width") or layout["figureWidth"])
    height = float(request.get("height") or layout["figureHeight"])
    dpi = int(request.get("dpi") or 110)
    longest = max(width, height) * dpi
    if longest > MAX_PREVIEW_PIXELS:
        dpi = max(30, int(dpi * MAX_PREVIEW_PIXELS / longest))

    try:
        figure, layout = compose_figure_data(
            datasets, panels, settings=settings, compose=options,
            figsize=(width, height), dpi=dpi, fit=request.get("fit"))
    except ValueError as exc:
        raise BridgeError(str(exc), kind="bad-layout") from None

    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=dpi)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    return {
        "png": encoded,
        "format": "png",
        "dpi": dpi,
        "width": width,
        "height": height,
        "pixelWidth": int(round(width * dpi)),
        "pixelHeight": int(round(height * dpi)),
        "rows": layout["rows"],
        "cols": layout["cols"],
        "panelCount": layout["panelCount"],
        "panels": layout["panels"],
        "labels": layout["labels"],
        "preset": layout["preset"],
        "diagram": layout["diagram"],
        "statistics": _compose_statistics(datasets, layout),
    }


def _cmd_export_compose(request):
    """Render a multi-panel figure at full quality and write it to disk."""
    path = request.get("path")
    if not path:
        raise BridgeError("'path' is required to export", kind="bad-request")
    _check_export_extension(path)

    settings, datasets, panels, options, layout = _compose_setup(request)
    width = float(request.get("width") or layout["figureWidth"])
    height = float(request.get("height") or layout["figureHeight"])
    dpi = int(request.get("dpi") or options["export_dpi"])
    tight = request.get("tight")
    if tight is None:
        tight = bool(options["export_tight_bbox"])

    try:
        figure, layout = compose_figure_data(
            datasets, panels, settings=settings, compose=options,
            figsize=(width, height), dpi=dpi, fit=request.get("fit"))
    except ValueError as exc:
        raise BridgeError(str(exc), kind="bad-layout") from None

    try:
        export_figure(figure, path, settings, width=width, height=height,
                      dpi=dpi, tight=tight)
    except OSError as exc:
        raise BridgeError(f"cannot write {path}: {exc}", kind="io-error") from None

    return {
        "path": os.path.abspath(path),
        "bytes": os.path.getsize(path) if os.path.exists(path) else 0,
        "dpi": dpi,
        "width": width,
        "height": height,
        "pixelWidth": int(round(width * dpi)),
        "pixelHeight": int(round(height * dpi)),
        "rows": layout["rows"],
        "cols": layout["cols"],
        "panelCount": layout["panelCount"],
        "panels": layout["panels"],
        "labels": layout["labels"],
    }


def _cmd_inspect_table(request):
    """Describe a table so the interface can offer a column picker."""
    path = request.get("path")
    if not path:
        raise BridgeError("'path' is required", kind="bad-request")
    try:
        frame = load_table(path, sheet_name=request.get("sheet", 0))
    except (OSError, ValueError, ImportError) as exc:
        raise BridgeError(str(exc), kind="io-error") from None

    preview_rows = int(request.get("previewRows") or 8)
    columns = []
    for column in frame.columns:
        series = frame[column]
        numeric = _numeric_series(series)
        columns.append({
            "name": str(column),
            "numeric": bool(numeric is not None),
            "nonEmpty": int(series.notna().sum()),
        })

    return {
        "path": os.path.abspath(path),
        "rows": int(len(frame)),
        "columns": columns,
        "preview": [
            [None if _is_missing(value) else value for value in row]
            for row in frame.head(preview_rows).itertuples(index=False, name=None)
        ],
    }


def _numeric_series(series):
    import pandas as pd

    try:
        return pd.to_numeric(series, errors="coerce").dropna()
    except (TypeError, ValueError):
        return None


def _is_missing(value):
    try:
        import pandas as pd

        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _cmd_import_table(request):
    """Load a table and turn it into datasets."""
    path = request.get("path")
    if not path:
        raise BridgeError("'path' is required", kind="bad-request")
    try:
        frame = load_table(path, sheet_name=request.get("sheet", 0))
    except (OSError, ValueError, ImportError) as exc:
        raise BridgeError(str(exc), kind="io-error") from None

    columns = request.get("columns")
    if columns:
        unknown = [name for name in columns if name not in frame.columns]
        if unknown:
            raise BridgeError("unknown column(s): " + ", ".join(map(str, unknown)),
                              kind="bad-request")
        frame = frame[list(columns)]

    try:
        datasets = datasets_from_table(
            frame,
            orientation=request.get("orientation", "vertical"),
            time_column=request.get("timeColumn") or None,
            time_unit=request.get("timeUnit", "s") or "s",
        )
    except ValueError as exc:
        raise BridgeError(str(exc), kind="bad-table") from None
    return {"datasets": datasets_to_list(datasets)}


def _cmd_import_multiline(request):
    paths = request.get("paths") or []
    if isinstance(paths, str):
        paths = [paths]
    if not paths:
        raise BridgeError("'paths' is required", kind="bad-request")
    try:
        datasets = datasets_from_multiline(
            list(paths),
            orientation=request.get("orientation", "vertical"),
            merge=bool(request.get("merge", False)),
        )
    except ValueError as exc:
        raise BridgeError(str(exc), kind="bad-table") from None
    return {"datasets": datasets_to_list(datasets)}


def _cmd_palettes(request):
    return {"palettes": _palettes()}


def _cmd_palette_colors(request):
    key = request.get("key")
    if key not in SCIENTIFIC_PALETTES:
        raise BridgeError(f"unknown palette {key!r}", kind="bad-request")
    count = request.get("count")
    return {"colors": palette_colors(key,
                                     count=int(count) if count else None,
                                     reverse=bool(request.get("reverse", False)))}


def _cmd_options(request):
    return {
        "settings": dict(DEFAULT_SETTINGS),
        "settingKeys": sorted(DEFAULT_SETTINGS),
        "visualPresets": [{"label": l, "value": v} for l, v in VISUAL_PRESET_OPTIONS],
        "fitMethods": [{"label": l, "value": v} for l, v in FIT_METHOD_OPTIONS],
    }


def _cmd_normalize_color(request):
    from .palettes import normalize_color

    try:
        return {"color": normalize_color(request.get("color"),
                                         request.get("fallback"))}
    except ValueError as exc:
        raise BridgeError(str(exc), kind="bad-color") from None


def _cmd_shutdown(request):
    return {"bye": True}


COMMANDS = {
    "hello": _cmd_hello,
    "schema": _cmd_schema,
    "render": _cmd_render,
    "export": _cmd_export,
    "compose": _cmd_compose,
    "export_compose": _cmd_export_compose,
    "statistics": _cmd_statistics,
    "inspect_table": _cmd_inspect_table,
    "import_table": _cmd_import_table,
    "import_multiline": _cmd_import_multiline,
    "palettes": _cmd_palettes,
    "palette_colors": _cmd_palette_colors,
    "options": _cmd_options,
    "normalize_color": _cmd_normalize_color,
    "shutdown": _cmd_shutdown,
}

#: Commands are dispatched on this exact allow-list; nothing else is reachable.
SHUTDOWN_COMMANDS = {"shutdown"}


def handle_request(request):
    """Run one request and return its response object (never raises)."""
    request_id = request.get("id") if isinstance(request, dict) else None
    try:
        if not isinstance(request, dict):
            raise BridgeError("request must be a JSON object", kind="bad-request")
        command = request.get("cmd")
        if not command:
            raise BridgeError("'cmd' is required", kind="bad-request")
        handler = COMMANDS.get(command)
        if handler is None:
            raise BridgeError(
                f"unknown command {command!r}; known commands: "
                + ", ".join(sorted(COMMANDS)), kind="unknown-command")
        return {"id": request_id, "ok": True, "result": _plain(handler(request))}
    except BridgeError as exc:
        return {"id": request_id, "ok": False,
                "error": {"kind": exc.kind, "message": str(exc)}}
    except Exception as exc:  # unexpected: keep the interface alive
        return {
            "id": request_id,
            "ok": False,
            "error": {
                "kind": "internal",
                "message": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            },
        }


def handle_line(line):
    """Parse one input line and return the response object."""
    text = (line or "").strip()
    if not text:
        return None
    try:
        request = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"id": None, "ok": False,
                "error": {"kind": "bad-json", "message": f"invalid JSON: {exc}"}}
    return handle_request(request)


def main(argv=None):
    """Serve the protocol on stdin/stdout until EOF or a shutdown command."""
    # The protocol owns stdout exclusively: anything that prints goes to stderr.
    protocol_out = sys.stdout
    sys.stdout = sys.stderr
    for stream in (sys.stdin, sys.stderr, protocol_out):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    def emit(payload):
        protocol_out.write(json.dumps(payload, ensure_ascii=True) + "\n")
        protocol_out.flush()

    for line in sys.stdin:
        response = handle_line(line)
        if response is None:
            continue
        emit(response)
        if response.get("ok") and response.get("result", {}).get("bye"):
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
