"""
EasyFig test suite.

Run with either::

    python -m unittest discover -s tests -v
    python tests/test_easyfig.py

The suite is deliberately dependency-light: it only needs the standard library
plus the runtime dependencies EasyFig already requires (numpy, matplotlib,
pandas, openpyxl).  Charts are rendered with the Agg backend, so no display is
needed.
"""

from __future__ import annotations

import base64
import contextlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import warnings

import matplotlib

matplotlib.use("Agg")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import easyfig  # noqa: E402
import main as main_module  # noqa: E402
from easyfig import chart_builder, data_processor, palettes  # noqa: E402
from easyfig import cli as cli_module  # noqa: E402
from easyfig import compose as compose_engine  # noqa: E402
from easyfig import gui as gui_module  # noqa: E402
from easyfig.compose import (  # noqa: E402
    COMPOSE_DEFAULT_SETTINGS,
    PRESET_ORDER,
)
from easyfig.chart_builder import HeadlessCanvas, make_settings, render_chart  # noqa: E402
from easyfig.chart_manager import ChartManager  # noqa: E402
from easyfig.config import (  # noqa: E402
    AVAILABLE_COLORS,
    BASE_COLORS,
    PALETTE_COLORS,
)
from easyfig.data_processor import (  # noqa: E402
    calculate_statistics,
    load_table_dataframe,
    parse_data_input,
    prepare_chart_data,
    process_multiline_excel,
    remove_outliers_iqr,
    smooth_data_moving_average,
    validate_dataset,
    fit_linear_regression,
    fit_polynomial,
)


def sample_datasets():
    return {
        "A": {"sizes": [1, 2, 3, 4],
              "data": [[1.0, 1.1], [2.0, 2.2], [3.0], [4.0, 3.8]],
              "color": "#1f77b4"},
        "B": {"sizes": [1, 2, 3, 4],
              "data": [[2.0], [2.5], [3.5], [4.5]],
              "color": "#ff7f0e", "marker": "s",
              "is_multiline": True, "y_errors": [0.1, 0.1, 0.0, 0.2]},
    }


ALL_CHART_TYPES = ["line", "scatter", "line_scatter", "pie", "errorbar", "bar"]


class TempDirMixin:
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="easyfig-test-")
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def path(self, name):
        return os.path.join(self.tmp, name)


# ---------------------------------------------------------------------------
# data_processor
# ---------------------------------------------------------------------------

class TestParsing(unittest.TestCase):
    def test_parse_data_input_delimiters(self):
        self.assertEqual(parse_data_input("1, 2;3\n4\t5"), [1.0, 2.0, 3.0, 4.0, 5.0])

    def test_parse_data_input_skips_text(self):
        self.assertEqual(parse_data_input("1 abc 2"), [1.0, 2.0])

    def test_parse_data_input_empty(self):
        self.assertEqual(parse_data_input("   "), [])

    def test_validate_dataset_mismatch(self):
        ok, message = validate_dataset([1, 2], [[1.0]])
        self.assertFalse(ok)
        self.assertIn("doesn't match", message)

    def test_validate_dataset_empty_group(self):
        ok, message = validate_dataset([1, 2], [[1.0], []])
        self.assertFalse(ok)
        self.assertIn("No data for size 2", message)

    def test_validate_dataset_ok(self):
        self.assertEqual(validate_dataset([1], [[1.0]]), (True, ""))


class TestStatistics(unittest.TestCase):
    def test_basic(self):
        stats = calculate_statistics([[1.0, 3.0], [2.0]])
        self.assertAlmostEqual(stats["mean"][0], 2.0)
        self.assertAlmostEqual(stats["std"][0], 1.0)
        self.assertAlmostEqual(stats["max"][0], 3.0)
        self.assertAlmostEqual(stats["min"][0], 1.0)
        self.assertAlmostEqual(stats["mean"][1], 2.0)

    def test_empty_group_becomes_zero(self):
        stats = calculate_statistics([[]])
        self.assertEqual(list(stats["mean"]), [0])

    def test_sampling_never_yields_nan(self):
        """Regression: max_points < group count used to make points_per_group 0."""
        groups = [[float(i)] for i in range(50)]
        stats = calculate_statistics(groups, max_points=10)
        self.assertTrue(np.isfinite(stats["mean"]).all())
        self.assertTrue(np.isfinite(stats["std"]).all())

    def test_no_data_returns_none(self):
        self.assertIsNone(calculate_statistics([]))

    def test_prepare_chart_data_keeps_true_max_min_for_multiline(self):
        datasets = {"M": {"sizes": [1, 2], "data": [[1.0, 5.0], [2.0, 9.0]],
                          "color": "red", "is_multiline": True,
                          "y_errors": [1.0, 2.0]}}
        chart_data = prepare_chart_data(datasets)
        stats = chart_data["M"]["stats"]
        self.assertAlmostEqual(float(stats["max"][0]), 5.0)
        self.assertAlmostEqual(float(stats["min"][1]), 2.0)
        self.assertAlmostEqual(float(stats["std"][1]), 2.0)


class TestFitting(unittest.TestCase):
    def test_linear_regression_perfect_line(self):
        result = fit_linear_regression([1, 2, 3], [2, 4, 6])
        self.assertAlmostEqual(result["slope"], 2.0)
        self.assertAlmostEqual(result["intercept"], 0.0)
        self.assertAlmostEqual(result["r_squared"], 1.0)

    def test_linear_regression_rejects_short_input(self):
        self.assertIsNone(fit_linear_regression([1], [2]))

    def test_linear_regression_constant_y(self):
        result = fit_linear_regression([1, 2, 3], [5, 5, 5])
        self.assertEqual(result["r_squared"], 0)

    def test_polynomial_degree_guard(self):
        self.assertIsNone(fit_polynomial([1, 2], [1, 2], degree=2))

    def test_polynomial_equation_text(self):
        result = fit_polynomial([1, 2, 3, 4], [1, 4, 9, 16], degree=2)
        self.assertIn("x^2", result["equation"])

    def test_polynomial_equation_uses_real_signs(self):
        """Regression: negative coefficients rendered as "+ -0.7465x^2"."""
        # y = -x^2 + 3x + 1, so the leading and middle terms are signed.
        x = [1, 2, 3, 4, 5, 6]
        y = [-xx * xx + 3 * xx + 1 for xx in x]
        result = fit_polynomial(x, y, degree=2)
        equation = result["equation"]
        self.assertNotIn("+ -", equation)
        self.assertNotIn("- -", equation)
        self.assertTrue(equation.startswith("y = -1.0000x^2"), equation)
        self.assertIn(" + 3.0000x", equation)
        self.assertIn(" + 1.0000", equation)

    def test_polynomial_equation_matches_the_fitted_curve(self):
        x = np.linspace(-3, 3, 25)
        y = 2 * x ** 3 - 5 * x ** 2 + 0.5 * x - 7
        result = fit_polynomial(x, y, degree=3)
        self.assertTrue(result["equation"].startswith("y = 2.0000x^3 - 5.0000x^2 + 0.5000x - 7.0000"),
                        result["equation"])

    def test_remove_outliers(self):
        data = [1.0, 1.1, 1.2, 1.3, 50.0]
        filtered, removed = remove_outliers_iqr(data)
        self.assertNotIn(50.0, filtered)
        self.assertEqual(removed, [4])

    def test_remove_outliers_detrends_a_trending_series(self):
        """Regression: on a rising series the raw fence covered every point.

        The demo data is a rising line with three planted gross errors; testing
        raw values against the quartiles removed nothing at all.
        """
        x = list(range(1, 9))
        y = [3.808, 5.918, 29.599, 10.167, 12.765, -2.835, 17.556, 36.535]

        # Without x, the fence cannot tell the trend from the outliers.
        _raw_filtered, raw_removed = remove_outliers_iqr(y)
        self.assertEqual(raw_removed, [])

        # With x, the residuals expose exactly the three planted outliers.
        filtered, removed = remove_outliers_iqr(y, x=x)
        self.assertEqual(removed, [2, 5, 7])
        self.assertEqual(len(filtered), 5)

    def test_remove_outliers_flat_baseline_with_a_spike(self):
        """A zero-IQR spread falls back to a MAD fence."""
        data = [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 90.0]
        _filtered, removed = remove_outliers_iqr(data, x=list(range(len(data))))
        self.assertEqual(removed, [6])

    def test_remove_outliers_ignores_non_finite(self):
        data = [1.0, 1.1, 1.2, float("nan"), 1.3, 50.0]
        filtered, removed = remove_outliers_iqr(data)
        self.assertIn(3, removed)
        self.assertNotIn(50.0, filtered)

    def test_remove_outliers_small_input_untouched(self):
        data = [1.0, 2.0]
        filtered, removed = remove_outliers_iqr(data)
        self.assertEqual(filtered, data)
        self.assertEqual(removed, [])

    def test_smooth_moving_average_short_input(self):
        data = [1.0, 2.0]
        self.assertEqual(smooth_data_moving_average(data, 5), data)

    def test_smooth_moving_average_reduces_spike(self):
        data = [1.0, 1.0, 9.0, 1.0, 1.0]
        smoothed = smooth_data_moving_average(data, 3)
        self.assertLess(smoothed[2], 9.0)


class TestTableLoading(TempDirMixin, unittest.TestCase):
    def _frame(self):
        return pd.DataFrame({"Size": [1, 2, 3], "A": [1.0, 2.0, 3.0], "B": [2.0, 3.0, 4.0]})

    def test_load_csv(self):
        path = self.path("t.csv")
        self._frame().to_csv(path, index=False)
        frame = load_table_dataframe(path)
        self.assertEqual(list(frame.columns), ["Size", "A", "B"])
        self.assertEqual(len(frame), 3)

    def test_load_tsv(self):
        path = self.path("t.tsv")
        self._frame().to_csv(path, index=False, sep="\t")
        self.assertEqual(len(load_table_dataframe(path)), 3)

    def test_load_xlsx(self):
        path = self.path("t.xlsx")
        self._frame().to_excel(path, index=False)
        frame = load_table_dataframe(path)
        self.assertEqual(list(frame.columns), ["Size", "A", "B"])

    def test_load_xlsx_second_sheet(self):
        path = self.path("multi.xlsx")
        with pd.ExcelWriter(path) as writer:
            self._frame().to_excel(writer, index=False, sheet_name="first")
            pd.DataFrame({"Z": [9, 8]}).to_excel(writer, index=False, sheet_name="second")
        self.assertEqual(list(load_table_dataframe(path, sheet_name="second").columns), ["Z"])
        self.assertEqual(list(load_table_dataframe(path, sheet_name=1).columns), ["Z"])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_table_dataframe(self.path("nope.csv"))

    def test_unsupported_extension(self):
        path = self.path("t.docx")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x")
        with self.assertRaises(ValueError):
            load_table_dataframe(path)

    def test_utf8_bom_is_stripped_from_column_names(self):
        """Excel's "CSV UTF-8" writes a BOM; it must not glue onto a header."""
        path = self.path("bom.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write("Lot A,1,2\nr1,10.0,20.0\nr2,10.1,20.1\n")
        frame = load_table_dataframe(path)
        self.assertEqual(list(frame.columns), ["Lot A", "1", "2"])
        self.assertNotIn("\ufeff", "".join(str(column) for column in frame.columns))

    def test_utf8_bom_is_stripped_from_tsv(self):
        path = self.path("bom.tsv")
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write("Size\tA\n1\t10.0\n2\t20.0\n")
        frame = load_table_dataframe(path)
        self.assertEqual(list(frame.columns), ["Size", "A"])

    def test_streaming_reader_matches_pandas(self):
        """The openpyxl streaming path must agree with pandas on names and values."""
        path = self.path("big.xlsx")
        frame = pd.DataFrame({
            "label": ["x", "y", "z"],
            "1": [1.0, 2.0, 3.0],
            "": [4.0, 5.0, 6.0],
            "dup": [7.0, 8.0, 9.0],
        })
        frame.to_excel(path, index=False)
        expected = pd.read_excel(path)
        streamed = data_processor._stream_xlsx(path)
        self.assertEqual(list(streamed.columns), list(expected.columns))
        for column in expected.columns:
            if column == "label":
                self.assertEqual(streamed[column].tolist(), expected[column].tolist())
            else:
                self.assertTrue(np.allclose(streamed[column].to_numpy(dtype=float),
                                            expected[column].to_numpy(dtype=float)))


class TestMultilineImport(TempDirMixin, unittest.TestCase):
    def _vertical_workbook(self, name="v.xlsx"):
        path = self.path(name)
        frame = pd.DataFrame({
            "label": ["r1", "r2", "r3"],
            1: [1.0, 1.2, 0.8],
            2: [2.0, 2.2, 1.8],
            3: [3.0, 3.0, 3.0],
        })
        frame.to_excel(path, index=False)
        return path

    def test_vertical_xlsx(self):
        result = process_multiline_excel(self._vertical_workbook(), "vertical")
        self.assertEqual(result["x"], [1.0, 2.0, 3.0])
        self.assertAlmostEqual(result["y"][0], 1.0)
        self.assertEqual(result["label"], "label")
        self.assertEqual(len(result["raw_data"][1]), 3)

    def test_vertical_csv(self):
        """CSV support: process_multiline_excel used to require Excel."""
        path = self.path("v.csv")
        pd.DataFrame({
            "label": ["r1", "r2"],
            1: [1.0, 1.2],
            2: [2.0, 2.2],
        }).to_csv(path, index=False)
        result = process_multiline_excel(path, "vertical")
        self.assertEqual(result["x"], [1.0, 2.0])
        self.assertEqual(result["label"], "label")

    def test_vertical_uses_filename_when_header_blank(self):
        path = self.path("blank.xlsx")
        frame = pd.DataFrame({None: ["r1", "r2"], 1: [1.0, 2.0], 2: [3.0, 4.0]})
        frame.to_excel(path, index=False)
        result = process_multiline_excel(path, "vertical")
        self.assertEqual(result["label"], "blank")

    def test_csv_bom_does_not_pollute_the_series_label(self):
        """A BOM on a CSV header must not leak into the dataset name."""
        path = self.path("bom_line.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write("样品 A,1,2,3\nr1,1.0,2.0,3.0\nr2,1.1,2.1,3.1\n")
        result = process_multiline_excel(path, "vertical")
        self.assertEqual(result["label"], "样品 A")
        self.assertNotIn("\ufeff", result["label"])

    def test_horizontal(self):
        path = self.path("h.xlsx")
        pd.DataFrame({
            "x": [1.0, 2.0, 3.0],
            "r1": [10.0, 20.0, 30.0],
            "r2": [11.0, 21.0, 31.0],
        }).to_excel(path, index=False)
        result = process_multiline_excel(path, "horizontal")
        self.assertEqual(result["x"], [1.0, 2.0, 3.0])
        self.assertAlmostEqual(result["y"][0], 10.5)

    def test_bad_orientation(self):
        with self.assertRaises(ValueError):
            process_multiline_excel(self._vertical_workbook(), "diagonal")

    def test_no_numeric_headers(self):
        path = self.path("bad.xlsx")
        pd.DataFrame({"label": ["a"], "foo": [1.0]}).to_excel(path, index=False)
        with self.assertRaises(ValueError):
            process_multiline_excel(path, "vertical")

    def test_header_unit_suffix_accepted(self):
        path = self.path("units.xlsx")
        pd.DataFrame({"label": ["a", "b"], "1mm": [1.0, 2.0], "2mm": [3.0, 4.0]}).to_excel(
            path, index=False)
        result = process_multiline_excel(path, "vertical")
        self.assertEqual(result["x"], [1.0, 2.0])


# ---------------------------------------------------------------------------
# chart_builder
# ---------------------------------------------------------------------------

class TestSettings(unittest.TestCase):
    def test_defaults_are_complete(self):
        settings = make_settings()
        self.assertEqual(settings, chart_builder.DEFAULT_SETTINGS)

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            make_settings({"no_such_setting": 1})
        self.assertIn("unknown setting", str(ctx.exception))

    def test_bool_coercion(self):
        self.assertTrue(make_settings({"show_legend": "yes"})["show_legend"])
        self.assertFalse(make_settings({"show_legend": "0"})["show_legend"])
        with self.assertRaises(ValueError):
            make_settings({"show_legend": "maybe"})

    def test_number_coercion(self):
        self.assertEqual(make_settings({"line_width": "3.5"})["line_width"], 3.5)
        self.assertEqual(make_settings({"x_tick_count": "8"})["x_tick_count"], 8)
        with self.assertRaises(ValueError):
            make_settings({"line_width": "wide"})

    def test_clamping(self):
        self.assertEqual(make_settings({"line_width": -5})["line_width"], 0.1)
        self.assertEqual(make_settings({"point_alpha": 5})["point_alpha"], 1.0)
        self.assertEqual(make_settings({"export_dpi": 1})["export_dpi"], 10)

    def test_enum_normalisation_by_label_or_value(self):
        self.assertEqual(make_settings({"chart_type": "Bar"})["chart_type"], "bar")
        self.assertEqual(make_settings({"chart_type": "bar"})["chart_type"], "bar")
        self.assertEqual(make_settings({"chart_type": "nonsense"})["chart_type"], "line")
        self.assertEqual(make_settings({"legend_loc": "nope"})["legend_loc"], "auto")

    def test_colour_normalisation(self):
        self.assertEqual(make_settings({"line_color": "f00"})["line_color"], "#ff0000")
        self.assertEqual(make_settings({"line_color": "#ABC"})["line_color"], "#aabbcc")
        self.assertEqual(make_settings({"line_color": "red"})["line_color"], "red")
        with self.assertRaises(ValueError):
            make_settings({"line_color": "chartreuse-ish"})

    def test_chart_type_implies_series_toggles(self):
        """Regression: --chart-type scatter used to draw a connecting line."""
        scatter = make_settings({"chart_type": "scatter"})
        self.assertTrue(scatter["show_mean"])
        self.assertFalse(scatter["show_connecting_line"])

        line = make_settings({"chart_type": "line"})
        self.assertFalse(line["show_mean"])
        self.assertTrue(line["show_connecting_line"])

        both = make_settings({"chart_type": "line_scatter"})
        self.assertTrue(both["show_mean"])
        self.assertTrue(both["show_connecting_line"])

        # Types with no opinion keep the plain defaults.
        bar = make_settings({"chart_type": "bar"})
        self.assertEqual(bar["show_mean"], chart_builder.DEFAULT_SETTINGS["show_mean"])
        self.assertEqual(bar["show_connecting_line"],
                         chart_builder.DEFAULT_SETTINGS["show_connecting_line"])

    def test_explicit_series_toggles_beat_the_chart_type(self):
        settings = make_settings({"chart_type": "scatter", "show_connecting_line": True})
        self.assertTrue(settings["show_connecting_line"])
        settings = make_settings({"chart_type": "line", "show_mean": True})
        self.assertTrue(settings["show_mean"])

    def test_bare_defaults_are_unchanged(self):
        self.assertEqual(make_settings(), chart_builder.DEFAULT_SETTINGS)

    def test_chart_type_series_defaults_table_is_exposed(self):
        self.assertEqual(set(chart_builder.CHART_TYPE_SERIES_DEFAULTS),
                         {"line", "scatter", "line_scatter"})
        for chart_type, defaults in chart_builder.CHART_TYPE_SERIES_DEFAULTS.items():
            with self.subTest(chart_type=chart_type):
                settings = make_settings({"chart_type": chart_type})
                for key, value in defaults.items():
                    self.assertEqual(settings[key], value)


class TestDatasetBuilders(TempDirMixin, unittest.TestCase):
    def test_from_json_list(self):
        datasets = chart_builder.datasets_from_json([
            {"name": "A", "sizes": [1, 2], "data": [[1.0], [2.0]]},
            {"name": "B", "sizes": [1, 2], "data": [3.0, 4.0]},
        ])
        self.assertEqual(list(datasets), ["A", "B"])
        self.assertEqual(datasets["B"]["data"], [[3.0], [4.0]])

    def test_from_json_mapping_and_duplicate_names(self):
        datasets = chart_builder.datasets_from_json({
            "A": {"sizes": [1], "data": [[1.0]]},
            "B": {"name": "A", "sizes": [1], "data": [[2.0]]},
        })
        self.assertEqual(list(datasets), ["A", "A_2"])

    def test_from_json_flat_length_mismatch(self):
        with self.assertRaises(ValueError):
            chart_builder.datasets_from_json([
                {"name": "A", "sizes": [1, 2, 3], "data": [1.0, 2.0]},
            ])

    def test_from_json_missing_keys(self):
        with self.assertRaises(ValueError):
            chart_builder.datasets_from_json([{"name": "A", "sizes": [1]}])

    def test_from_json_empty(self):
        with self.assertRaises(ValueError):
            chart_builder.datasets_from_json([])

    def test_from_json_colour_override(self):
        datasets = chart_builder.datasets_from_json([
            {"name": "A", "sizes": [1], "data": [[1.0]], "color": "blue",
             "marker": "s", "y_errors": [0.5], "is_multiline": True},
        ])
        dataset = datasets["A"]
        self.assertEqual(dataset["color"], "blue")
        self.assertEqual(dataset["marker"], "s")
        self.assertEqual(dataset["y_errors"], [0.5])
        self.assertTrue(dataset["is_multiline"])

    def test_from_table_vertical_and_time_column(self):
        frame = pd.DataFrame({"t": [0.0, 1.0, 2.0], "a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
        datasets = chart_builder.datasets_from_table(frame, time_column="t")
        self.assertEqual(list(datasets), ["a", "b"])
        self.assertEqual(datasets["a"]["sizes"], [0.0, 1.0, 2.0])

    def test_from_table_vertical_row_numbers(self):
        """Regression: X used to be 1..n even when blank cells were dropped."""
        frame = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
        datasets = chart_builder.datasets_from_table(frame)
        self.assertEqual(datasets["a"]["sizes"], [1.0, 3.0])

    def test_from_table_time_unit_ms(self):
        frame = pd.DataFrame({"t": [0.0, 500.0], "a": [1.0, 2.0]})
        datasets = chart_builder.datasets_from_table(frame, time_column="t", time_unit="ms")
        self.assertEqual(datasets["a"]["sizes"], [0.0, 0.5])

    def test_from_table_horizontal(self):
        frame = pd.DataFrame({"name": ["s1", "s2"], "1": [1.0, 5.0], "2": [2.0, 6.0]})
        datasets = chart_builder.datasets_from_table(frame, orientation="horizontal")
        self.assertEqual(list(datasets), ["s1", "s2"])

    def test_from_table_missing_time_column(self):
        frame = pd.DataFrame({"a": [1.0]})
        with self.assertRaises(ValueError):
            chart_builder.datasets_from_table(frame, time_column="t")

    def test_from_table_non_numeric_only(self):
        frame = pd.DataFrame({"a": ["x", "y"]})
        with self.assertRaises(ValueError):
            chart_builder.datasets_from_table(frame)

    def test_from_multiline_merge_and_separate(self):
        first = self.path("a.xlsx")
        second = self.path("b.xlsx")
        pd.DataFrame({"l": ["a"] * 2, 1: [1.0, 1.2], 2: [2.0, 2.2]}).to_excel(first, index=False)
        pd.DataFrame({"l": ["b"] * 2, 1: [3.0, 3.2], 2: [4.0, 4.2]}).to_excel(second, index=False)

        separate = chart_builder.datasets_from_multiline([first, second])
        self.assertEqual(len(separate), 2)

        merged = chart_builder.datasets_from_multiline([first, second], merge=True)
        self.assertEqual(list(merged), ["Merged_Dataset"])
        self.assertEqual(merged["Merged_Dataset"]["sizes"], [1.0, 2.0])
        # Two repeats per file per X value -> four measurements in each group.
        groups = merged["Merged_Dataset"]["data"]
        self.assertEqual([len(g) for g in groups], [4, 4])
        self.assertEqual(sorted(groups[0]), [1.0, 1.2, 3.0, 3.2])

    def test_from_multiline_all_bad(self):
        with self.assertRaises(ValueError):
            chart_builder.datasets_from_multiline([self.path("nope.xlsx")])

    def test_load_spec_roundtrip(self):
        path = self.path("spec.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({
                "datasets": [{"name": "A", "sizes": [1], "data": [[1.0]]}],
                "settings": {"chart_type": "bar"},
            }, handle)
        datasets, settings = chart_builder.load_spec(path)
        self.assertEqual(list(datasets), ["A"])
        self.assertEqual(settings, {"chart_type": "bar"})

    def test_load_spec_settings_only_is_rejected(self):
        path = self.path("s.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"settings": {"chart_type": "bar"}}, handle)
        with self.assertRaises(ValueError):
            chart_builder.load_spec(path)

    def test_load_spec_bad_json(self):
        path = self.path("bad.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(ValueError):
            chart_builder.load_spec(path)


class TestProcessing(unittest.TestCase):
    def setUp(self):
        self.chart_data = prepare_chart_data(sample_datasets())

    def test_none_returns_input(self):
        self.assertIs(chart_builder.apply_processing(self.chart_data, "none"), self.chart_data)

    def test_linear(self):
        result = chart_builder.apply_processing(self.chart_data, "linear")
        self.assertTrue(any("(Raw)" in key for key in result))
        fits = {key: value for key, value in result.items() if value.get("is_fit_curve")}
        self.assertEqual(len(fits), len(self.chart_data))
        label, fit = next(iter(fits.items()))
        # The legend must carry the equation and the fit quality, not just
        # "Linear Fit" - otherwise the fit is unreadable.
        self.assertIn("y =", label)
        self.assertIn("R\u00b2", label)
        self.assertIn("fit_info", fit)
        self.assertAlmostEqual(fit["fit_info"]["rSquared"], fit["fit_info"]["rSquared"])
        self.assertIn("slope", fit["fit_info"])
        self.assertIn("intercept", fit["fit_info"])

    def test_fit_label_includes_r_squared(self):
        from easyfig.chart_builder import fit_label

        fit_result = {"equation": "y = 2.0000x + 1.0000", "r_squared": 0.98765}
        self.assertEqual(fit_label("A", fit_result), "A (y = 2.0000x + 1.0000, R\u00b2=0.9877)")
        self.assertEqual(fit_label("A", fit_result, degree=2), "A (2 次拟合, R\u00b2=0.9877)")
        # A degenerate fit (no R-squared) must still produce a usable label.
        self.assertEqual(fit_label("A", {"equation": "", "r_squared": float("nan")}),
                         "A (linear fit)")

    def test_polynomial(self):
        result = chart_builder.apply_processing(self.chart_data, "polynomial", degree=2)
        self.assertTrue(any("2 次拟合" in key for key in result))
        fits = [value for value in result.values() if value.get("is_fit_curve")]
        self.assertEqual(fits[0]["fit_info"]["degree"], 2)

    def test_mean_error_sets_y_errors(self):
        result = chart_builder.apply_processing(self.chart_data, "mean_error")
        self.assertTrue(any("Mean ± SD" in k for k in result))
        for key, value in result.items():
            self.assertEqual(len(value["sizes"]), len(value["y_errors"]))

    def test_remove_outliers(self):
        result = chart_builder.apply_processing(self.chart_data, "remove_outliers")
        self.assertTrue(any("无异常值" in key for key in result))

    def test_remove_outliers_reports_which_points_were_dropped(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        y = [10.0, 11.0, 10.5, 90.0, 10.2, 11.5]
        chart_data = prepare_chart_data(
            {"S": {"sizes": x, "data": [[v] for v in y], "color": "red"}})
        result = chart_builder.apply_processing(chart_data, "remove_outliers")
        label, cleaned = next(iter(result.items()))
        self.assertEqual(cleaned["removed_points"], [4.0])
        self.assertNotIn(4.0, cleaned["sizes"])
        self.assertIn("剔除 1 点", label)

    def test_smooth(self):
        result = chart_builder.apply_processing(self.chart_data, "smooth")
        self.assertTrue(any("移动平均" in key for key in result))
        for value in result.values():
            self.assertTrue(np.isfinite(value["stats"]["mean"]).all())

    def test_unknown_method_is_ignored(self):
        self.assertIs(chart_builder.apply_processing(self.chart_data, "wat"), self.chart_data)

    def test_show_fit_off_linear_yields_nothing(self):
        result = chart_builder.apply_processing(
            self.chart_data, "linear", show_raw=False, show_fit=False)
        self.assertIs(result, self.chart_data)

    def test_single_point_dataset_does_not_crash(self):
        chart_data = prepare_chart_data(
            {"only": {"sizes": [1], "data": [[1.0]], "color": "red"}})
        for method in ["linear", "polynomial", "mean_error", "remove_outliers", "smooth"]:
            chart_builder.apply_processing(chart_data, method)


# ---------------------------------------------------------------------------
# chart_manager
# ---------------------------------------------------------------------------

def render(datasets=None, settings=None, figsize=(4, 3), dpi=60):
    return render_chart(datasets if datasets is not None else sample_datasets(),
                        settings or {}, figsize=figsize, dpi=dpi)


class TestChartRendering(unittest.TestCase):
    def test_every_chart_type_renders(self):
        for chart_type in ALL_CHART_TYPES:
            with self.subTest(chart_type=chart_type):
                fig = render(settings={"chart_type": chart_type})
                self.assertTrue(fig.axes)

    def test_full_combination_sweep(self):
        """Regression sweep across chart type / axis mode / preset / error bar mode."""
        failures = []
        for chart_type in ALL_CHART_TYPES:
            for xaxis_mode in ["categorical", "numeric"]:
                for preset in ["default", "sci"]:
                    for eb_mode in ["summary", "per_size"]:
                        for legend_loc in ["auto", "outside right", "best"]:
                            settings = {
                                "chart_type": chart_type,
                                "xaxis_mode": xaxis_mode,
                                "visual_preset": preset,
                                "errorbar_mode": eb_mode,
                                "legend_loc": legend_loc,
                                "show_data_labels": True,
                                "show_connecting_line": True,
                                "show_mean": True,
                                "show_max": True,
                                "show_min": True,
                                "show_error_bars_line": True,
                            }
                            try:
                                render(settings=settings)
                            except Exception as exc:  # pragma: no cover - failure path
                                failures.append((chart_type, xaxis_mode, preset,
                                                 eb_mode, legend_loc, repr(exc)))
        self.assertEqual(failures, [], f"{len(failures)} combinations failed")

    def test_pie_chart_regression(self):
        """Regression: pie used to raise 'too many values to unpack'."""
        fig = render(settings={"chart_type": "pie", "title": "Shares"})
        self.assertEqual(len(fig.axes[0].patches), 4)
        self.assertEqual(fig.axes[0].get_xlabel(), "")

    def test_pie_all_zero_and_negative(self):
        zero = {"Z": {"sizes": [1, 2], "data": [[0.0], [0.0]], "color": "red"}}
        self.assertTrue(render(zero, {"chart_type": "pie"}).axes)
        negative = {"N": {"sizes": [1, 2], "data": [[-1.0], [3.0]], "color": "red"}}
        self.assertEqual(len(render(negative, {"chart_type": "pie"}).axes[0].patches), 2)

    def test_pie_uses_single_dataset(self):
        fig = render(settings={"chart_type": "pie"})
        # 4 wedges from dataset A only, not 8 from both datasets.
        self.assertEqual(len(fig.axes[0].patches), 4)

    def test_bar_data_labels_with_error_bars(self):
        """Regression: bar labels were only drawn when error bars were off."""
        fig = render(settings={"chart_type": "bar", "show_data_labels": True,
                               "errorbar_show_error": True,
                               "errorbar_show_mean": True})
        labels = [t.get_text() for t in fig.axes[0].texts]
        self.assertEqual(len(labels), 2)
        self.assertTrue(all(label.strip() for label in labels))

    def test_bar_data_labels_without_error_bars(self):
        fig = render(settings={"chart_type": "bar", "show_data_labels": True,
                               "errorbar_show_error": False,
                               "errorbar_show_mean": True})
        self.assertEqual(len([t for t in fig.axes[0].texts]), 2)

    def test_bar_labels_suppressed_when_mean_hidden(self):
        fig = render(settings={"chart_type": "bar", "show_data_labels": True,
                               "errorbar_show_mean": False})
        self.assertEqual(list(fig.axes[0].texts), [])

    def test_legend_handle_sizing_uses_current_api(self):
        """Regression: legendHandles was removed in matplotlib 3.9."""
        fig = render(settings={"chart_type": "scatter", "xaxis_mode": "numeric",
                               "show_mean": True, "legend_marker_size": 18})
        legend = fig.axes[0].get_legend()
        self.assertIsNotNone(legend)
        handles = getattr(legend, "legend_handles", None)
        if handles is None:
            handles = getattr(legend, "legendHandles", None)
        self.assertTrue(handles)
        sizes = [h.get_sizes()[0] for h in handles if hasattr(h, "get_sizes")]
        self.assertTrue(sizes)
        self.assertAlmostEqual(sizes[0], 18 ** 2)

    def test_legend_can_be_hidden(self):
        fig = render(settings={"show_legend": False})
        self.assertIsNone(fig.axes[0].get_legend())

    def test_errorbar_metric_sem(self):
        fig = render(settings={"chart_type": "errorbar", "errorbar_mode": "per_size",
                               "errorbar_metric": "SEM"})
        self.assertTrue(fig.axes)

    def test_empty_data_raises(self):
        with self.assertRaises(ValueError):
            render_chart({}, {})

    def test_show_as_raw_with_jitter(self):
        chart_data = prepare_chart_data(sample_datasets())
        chart_data["A"]["show_as_raw"] = True
        chart_data["A"]["add_jitter"] = True
        fig = render_chart(sample_datasets(), {}, chart_data=chart_data, figsize=(4, 3), dpi=60)
        self.assertTrue(fig.axes)

    def test_reverse_y_axis(self):
        fig = render(settings={"reverse_y_axis": True})
        self.assertTrue(fig.axes[0].yaxis_inverted())

    def test_summary_bar_keeps_categorical_labels(self):
        """Regression: numeric X mode overwrote the dataset-name labels."""
        fig = render(settings={"chart_type": "bar", "xaxis_mode": "numeric",
                               "errorbar_mode": "summary"})
        labels = [t.get_text() for t in fig.axes[0].get_xticklabels() if t.get_text()]
        self.assertEqual(labels, ["A", "B"])

    def test_summary_errorbar_keeps_categorical_labels(self):
        fig = render(settings={"chart_type": "errorbar", "xaxis_mode": "numeric",
                               "errorbar_mode": "summary"})
        labels = [t.get_text() for t in fig.axes[0].get_xticklabels() if t.get_text()]
        self.assertEqual(labels, ["A", "B"])

    def test_per_size_bar_still_honours_numeric_x(self):
        fig = render(settings={"chart_type": "bar", "xaxis_mode": "numeric",
                               "errorbar_mode": "per_size"})
        labels = [t.get_text() for t in fig.axes[0].get_xticklabels() if t.get_text()]
        self.assertTrue(labels)
        for label in labels:
            self.assertRegex(label.replace("-", ""), r"^\d+(\.\d+)?$")

    def test_x_axis_is_numeric_helper(self):
        numeric = ChartManager._x_axis_is_numeric
        self.assertTrue(numeric({"xaxis_mode": "numeric", "chart_type": "line"}))
        self.assertTrue(numeric({"xaxis_mode": "numeric", "chart_type": "bar",
                                 "errorbar_mode": "per_size"}))
        self.assertFalse(numeric({"xaxis_mode": "numeric", "chart_type": "bar",
                                  "errorbar_mode": "summary"}))
        self.assertFalse(numeric({"xaxis_mode": "categorical", "chart_type": "line"}))

    def test_minor_ticks_toggle(self):
        fig = render(settings={"show_minor_ticks": True})
        self.assertNotEqual(fig.axes[0].xaxis.get_minor_ticks(), [])


class TestBrokenAxis(unittest.TestCase):
    def _broken_y(self):
        return {"xaxis_mode": "numeric", "chart_type": "line",
                "show_connecting_line": True,
                "use_broken_y_axis": True,
                "broken_y_bot_min": 0, "broken_y_bot_max": 3,
                "broken_y_top_min": 100, "broken_y_top_max": 120}

    def test_y_break_creates_two_panels_with_configured_ranges(self):
        fig = render(settings=self._broken_y())
        self.assertEqual(len(fig.axes), 2)
        bounds = sorted(tuple(round(v, 3) for v in ax.get_ylim()) for ax in fig.axes)
        self.assertEqual(bounds, [(0.0, 3.0), (100.0, 120.0)])

    def test_x_break_creates_two_panels(self):
        fig = render(settings={"xaxis_mode": "numeric", "chart_type": "line",
                               "show_connecting_line": True, "use_broken_x_axis": True,
                               "broken_x_left_min": 0, "broken_x_left_max": 1.5,
                               "broken_x_right_min": 3, "broken_x_right_max": 4})
        self.assertEqual(len(fig.axes), 2)
        bounds = sorted(tuple(round(v, 3) for v in ax.get_xlim()) for ax in fig.axes)
        self.assertEqual(bounds, [(0.0, 1.5), (3.0, 4.0)])

    def test_both_axes_broken_creates_four_panels(self):
        settings = dict(self._broken_y())
        settings.update({"use_broken_x_axis": True,
                         "broken_x_left_min": 0, "broken_x_left_max": 1.5,
                         "broken_x_right_min": 3, "broken_x_right_max": 4})
        self.assertEqual(len(render(settings=settings).axes), 4)

    def test_invalid_range_falls_back_to_one_panel(self):
        fig = render(settings={"chart_type": "line", "use_broken_y_axis": True,
                               "broken_y_bot_min": 5, "broken_y_bot_max": 5,
                               "broken_y_top_min": 1, "broken_y_top_max": 2})
        self.assertEqual(len(fig.axes), 1)

    def test_reversed_range_is_normalised(self):
        fig = render(settings={"chart_type": "line", "use_broken_y_axis": True,
                               "broken_y_bot_min": 3, "broken_y_bot_max": 0,
                               "broken_y_top_min": 120, "broken_y_top_max": 100})
        bounds = sorted(tuple(round(v, 3) for v in ax.get_ylim()) for ax in fig.axes)
        self.assertEqual(bounds, [(0.0, 3.0), (100.0, 120.0)])

    def test_shared_labels_drawn_once(self):
        """One x label, one y label and one title for the whole figure."""
        fig = render(settings=self._broken_y())
        shared = [text for text in fig.texts if text.get_text()]
        self.assertEqual(len(shared), 3)
        # None of them belongs to an individual panel.
        for ax in fig.axes:
            self.assertEqual(ax.get_title(), "")
            self.assertEqual(ax.get_xlabel(), "")
            self.assertEqual(ax.get_ylabel(), "")

    def test_title_is_centred_on_a_multi_column_layout(self):
        """Regression: the title sat over the top-right panel, not the figure.

        On a 2x2 broken layout it was centred at x=717 of a 1000px figure.
        """
        fig = render_chart(self._gap_datasets(), {
            "chart_type": "line_scatter", "xaxis_mode": "numeric",
            "show_mean": True, "show_connecting_line": True,
            "title": "Four panels",
            "use_broken_x_axis": True, "use_broken_y_axis": True,
            "broken_x_left_min": 0, "broken_x_left_max": 3,
            "broken_x_right_min": 7, "broken_x_right_max": 10,
            "broken_y_bot_min": 0, "broken_y_bot_max": 20,
            "broken_y_top_min": 25, "broken_y_top_max": 40,
        }, figsize=(10, 6), dpi=100)

        self.assertEqual(len(fig.axes), 4)
        self.assertIsNotNone(fig._suptitle)
        self.assertEqual(fig._suptitle.get_text(), "Four panels")
        self.assertAlmostEqual(fig._suptitle.get_position()[0], 0.5, places=6)

    def test_every_chart_type_with_broken_axis(self):
        for chart_type in ALL_CHART_TYPES:
            with self.subTest(chart_type=chart_type):
                settings = dict(self._broken_y())
                settings["chart_type"] = chart_type
                # A pie has no cartesian axes, so its break is ignored.
                expected = 1 if chart_type == "pie" else 2
                self.assertEqual(len(render(settings=settings).axes), expected)

    def test_pie_ignores_broken_axis(self):
        settings = dict(self._broken_y())
        settings["chart_type"] = "pie"
        fig = render(settings=settings)
        self.assertEqual(len(fig.axes), 1)
        self.assertEqual(len(fig.axes[0].patches), 4)

    def test_resolve_broken_range_rejects_non_numeric(self):
        self.assertIsNone(ChartManager._resolve_broken_range("a", "b", "c", "d"))
        self.assertIsNone(ChartManager._resolve_broken_range(None, None, None, None))
        self.assertIsNone(ChartManager._resolve_broken_range(0, 1, 5, 5))
        self.assertEqual(ChartManager._resolve_broken_range(1, 0, 2, 3), [(0.0, 1.0), (2.0, 3.0)])

    # -- the conventions the references use --------------------------------

    @staticmethod
    def _panel_with_ylim(fig, wanted):
        for ax in fig.axes:
            if tuple(round(float(v), 6) for v in ax.get_ylim()) == tuple(wanted):
                return ax
        raise AssertionError(f"no panel with ylim {wanted}")

    def test_join_tick_is_dropped_and_the_window_is_kept(self):
        """Regression: the join tick widened (200,230) into (190,240).

        ``MultipleLocator`` reports one step beyond the window on each side, and
        ``Axis.set_ticks`` performs a documented mandatory view expansion so every
        tick it is handed becomes visible.
        """
        fig = render(settings=self._broken_y())
        top = self._panel_with_ylim(fig, (100.0, 120.0))
        bottom = self._panel_with_ylim(fig, (0.0, 3.0))

        self.assertEqual(tuple(round(v, 6) for v in top.get_ylim()), (100.0, 120.0))
        self.assertEqual(tuple(round(v, 6) for v in bottom.get_ylim()), (0.0, 3.0))

        top_ticks = [float(v) for v in top.get_yticks()]
        bottom_ticks = [float(v) for v in bottom.get_yticks()]
        # The join of the upper panel is its bottom limit, and of the lower panel
        # its top limit; neither may be labelled.
        self.assertNotIn(100.0, top_ticks)
        self.assertNotIn(3.0, bottom_ticks)
        # Nothing leaks in from outside the window.
        self.assertTrue(all(100.0 - 1e-9 <= t <= 120.0 + 1e-9 for t in top_ticks))
        self.assertTrue(all(0.0 - 1e-9 <= t <= 3.0 + 1e-9 for t in bottom_ticks))
        self.assertTrue(top_ticks and bottom_ticks)

    def test_standardisation_is_skipped_when_it_would_starve_a_panel(self):
        """A narrow panel must keep a usable axis, not a single tick."""
        fig = render(settings=self._broken_y())  # (0, 3) next to (100, 120)
        bottom = self._panel_with_ylim(fig, (0.0, 3.0))
        self.assertGreaterEqual(len(bottom.get_yticks()), 2)

    def test_panels_share_one_tick_interval(self):
        """brokenaxes.standardize_ticks: a differing step reads as broken."""
        fig = render_chart(self._gap_datasets(), {
            "chart_type": "line_scatter", "xaxis_mode": "numeric",
            "show_mean": True, "show_connecting_line": True,
            "use_broken_y_axis": True,
            "broken_y_bot_min": 0, "broken_y_bot_max": 30,
            "broken_y_top_min": 200, "broken_y_top_max": 240,
        }, figsize=(4, 3), dpi=60)

        steps = []
        for ax in fig.axes:
            ticks = np.unique(np.asarray(ax.get_yticks(), dtype=float))
            if ticks.size >= 2:
                steps.append(round(float(np.min(np.diff(ticks))), 6))
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0], steps[1], f"tick steps differ: {steps}")

    def test_break_marks_are_figure_level_45_degree_strokes(self):
        fig = render_chart(self._gap_datasets(), {
            "chart_type": "line_scatter", "xaxis_mode": "numeric",
            "show_mean": True, "show_connecting_line": True,
            "use_broken_y_axis": True,
            "broken_y_bot_min": 0, "broken_y_bot_max": 30,
            "broken_y_top_min": 200, "broken_y_top_max": 230,
        }, figsize=(10, 6), dpi=60)

        strokes = list(fig.artists)
        # Two panels, both ends of the join edge, on both panels.
        self.assertEqual(len(strokes), 4)

        width_in, height_in = (float(v) for v in fig.get_size_inches())
        for stroke in strokes:
            xs = np.asarray(stroke.get_xdata(), dtype=float)
            ys = np.asarray(stroke.get_ydata(), dtype=float)
            # 45 degrees on screen, so the slope measured in inches is 1.
            dx_in = (xs[1] - xs[0]) * width_in
            dy_in = (ys[1] - ys[0]) * height_in
            self.assertAlmostEqual(abs(dy_in / dx_in), 1.0, places=6,
                                   msg=f"stroke is not 45 degrees: {dx_in} x {dy_in}")
            self.assertIs(stroke.get_transform(), fig.transFigure)

    def test_inner_spines_hidden_and_outer_kept(self):
        fig = render(settings=self._broken_y())
        top = self._panel_with_ylim(fig, (100.0, 120.0))
        bottom = self._panel_with_ylim(fig, (0.0, 3.0))

        self.assertTrue(top.spines["top"].get_visible())
        self.assertFalse(top.spines["bottom"].get_visible())
        self.assertFalse(bottom.spines["top"].get_visible())
        self.assertTrue(bottom.spines["bottom"].get_visible())
        for ax in (top, bottom):
            self.assertTrue(ax.spines["left"].get_visible())
            self.assertTrue(ax.spines["right"].get_visible())

    def test_inner_ticks_are_moved_outboard(self):
        """Stray tick marks must not hang in the gap between the panels."""
        fig = render(settings=self._broken_y())
        top = self._panel_with_ylim(fig, (100.0, 120.0))
        bottom = self._panel_with_ylim(fig, (0.0, 3.0))

        top_ticks = top.xaxis.get_major_ticks()
        bottom_ticks = bottom.xaxis.get_major_ticks()

        # Upper panel: x ticks moved to its top edge, labels suppressed, so
        # nothing hangs in the gap.  (get_ticks_position() reports 'unknown' for
        # shared axes, so assert the visible ticks instead.)
        self.assertTrue(all(not tick.tick1line.get_visible() for tick in top_ticks))
        self.assertTrue(all(tick.tick2line.get_visible() for tick in top_ticks))
        self.assertTrue(all(not tick.label1.get_visible() for tick in top_ticks))

        # Lower panel keeps the labelled bottom row.
        self.assertTrue(all(tick.tick1line.get_visible() for tick in bottom_ticks))
        self.assertTrue(all(tick.label1.get_visible() for tick in bottom_ticks))

        # One column, so the y ticks stay on the left and keep their labels.
        for ax in (top, bottom):
            ticks = ax.yaxis.get_major_ticks()
            self.assertTrue(all(tick.tick1line.get_visible() for tick in ticks))
            self.assertTrue(all(tick.label1.get_visible() for tick in ticks))

    def test_broken_panels_are_separated_by_a_small_gap(self):
        """The gallery uses hspace=0.05 so the two boxes read as two boxes."""
        fig = render(settings=self._broken_y())
        top = self._panel_with_ylim(fig, (100.0, 120.0))
        bottom = self._panel_with_ylim(fig, (0.0, 3.0))
        top_box, bottom_box = top.get_position(), bottom.get_position()
        gap = top_box.y0 - bottom_box.y1
        self.assertGreater(gap, 0.0)
        self.assertLess(gap, 0.1)

    def test_chart_type_series_rule_applies_to_broken_panels(self):
        """A broken panel is still a normal chart; the rule must not be skipped."""
        settings = dict(self._broken_y())
        # Drop the explicit toggle so the chart-type rule is what decides.
        settings.pop("show_connecting_line", None)
        settings["chart_type"] = "scatter"
        fig = render(settings=settings)
        for ax in fig.axes:
            data_lines = [line for line in ax.lines
                          if line.get_transform() is ax.transData]
            self.assertEqual(data_lines, [], "scatter must not draw a line")

    def _gap_datasets(self):
        return {"Load": {"sizes": [1, 2, 3, 4, 5, 6],
                         "data": [[12.4], [13.1], [12.8], [210.5], [214.2], [211.9]],
                         "color": "#8E0028"}}

    def test_broken_axis_does_not_draw_a_line_across_the_break(self):
        """Regression: the clipped segment reappeared as a vertical stub.

        A line drawn straight through the break is cut at the panel edge and
        looks like a measurement; the polyline must be broken instead.
        """
        fig = render_chart(self._gap_datasets(), {
            "chart_type": "line_scatter", "xaxis_mode": "numeric",
            "show_mean": True, "show_connecting_line": True,
            "use_broken_y_axis": True,
            "broken_y_bot_min": 0, "broken_y_bot_max": 30,
            "broken_y_top_min": 200, "broken_y_top_max": 230,
        }, figsize=(4, 3), dpi=60)

        self.assertEqual(len(fig.axes), 2)
        for ax in fig.axes:
            low, high = sorted(ax.get_ylim())
            data_lines = [line for line in ax.lines
                          if line.get_transform() is ax.transData]
            self.assertTrue(data_lines, "expected a polyline in every panel")
            for line in data_lines:
                values = np.asarray(line.get_ydata(), dtype=float)
                finite = values[np.isfinite(values)]
                self.assertGreater(finite.size, 0)
                # Every drawn vertex stays inside its own panel window.
                self.assertGreaterEqual(float(finite.min()), low - 1e-6)
                self.assertLessEqual(float(finite.max()), high + 1e-6)
                # And the series is genuinely split, not just clipped.
                self.assertGreater(int(np.isnan(values).sum()), 0)

    def test_broken_axis_panels_each_hold_their_own_points(self):
        fig = render_chart(self._gap_datasets(), {
            "chart_type": "line_scatter", "xaxis_mode": "numeric",
            "show_mean": True, "show_connecting_line": True,
            "use_broken_y_axis": True,
            "broken_y_bot_min": 0, "broken_y_bot_max": 30,
            "broken_y_top_min": 200, "broken_y_top_max": 230,
        }, figsize=(4, 3), dpi=60)

        def plotted(ax):
            lines = [line for line in ax.lines if line.get_transform() is ax.transData]
            values = np.concatenate([np.asarray(line.get_ydata(), dtype=float)
                                     for line in lines])
            return values[np.isfinite(values)]

        low_panel, high_panel = sorted(fig.axes, key=lambda ax: ax.get_ylim()[0])
        self.assertTrue(np.all(plotted(low_panel) < 30))
        self.assertTrue(np.all(plotted(high_panel) > 200))

    def test_single_panel_still_clips_instead_of_breaking(self):
        """The window mask must not leak into ordinary charts."""
        datasets = {"S": {"sizes": [1, 2, 3, 4, 5],
                          "data": [[1.0], [2.0], [3.0], [4.0], [50.0]],
                          "color": "red"}}
        fig = render_chart(datasets, {
            "chart_type": "line", "xaxis_mode": "numeric",
            "show_connecting_line": True,
            "use_custom_y_ticks": True,
            "y_tick_min": 0, "y_tick_max": 10, "y_tick_step": 2,
        }, figsize=(4, 3), dpi=60)

        self.assertEqual(len(fig.axes), 1)
        ax = fig.axes[0]
        lines = [line for line in ax.lines if line.get_transform() is ax.transData]
        values = np.concatenate([np.asarray(line.get_ydata(), dtype=float)
                                 for line in lines])
        self.assertFalse(np.isnan(values).any(),
                         "a single panel must clip, not break, the polyline")
        self.assertIn(50.0, values.tolist())

    def _gap_in_x_datasets(self):
        return {"S": {"sizes": [1, 1.5, 2, 8, 8.5, 9],
                      "data": [[10.0], [12.0], [11.0], [30.0], [32.0], [31.0]],
                      "color": "#1f77b4"}}

    def _plotted(self, ax):
        lines = [line for line in ax.lines if line.get_transform() is ax.transData]
        xs = np.concatenate([np.asarray(line.get_xdata(), dtype=float)
                             for line in lines])
        ys = np.concatenate([np.asarray(line.get_ydata(), dtype=float)
                             for line in lines])
        keep = np.isfinite(ys)
        return xs[keep], ys[keep], ys

    def test_broken_x_keeps_each_panels_points(self):
        """Regression: the window was captured too early and emptied panel 0.

        For an X-only break the y axis still autoscales, so a window read before
        the data is drawn is the matplotlib default (0, 1) and masks everything.
        """
        fig = render_chart(self._gap_in_x_datasets(), {
            "chart_type": "line_scatter", "xaxis_mode": "numeric",
            "show_mean": True, "show_connecting_line": True,
            "use_broken_x_axis": True,
            "broken_x_left_min": 0, "broken_x_left_max": 3,
            "broken_x_right_min": 7, "broken_x_right_max": 10,
        }, figsize=(4, 3), dpi=60)

        self.assertEqual(len(fig.axes), 2)
        counts = []
        for ax in fig.axes:
            xs, ys, raw = self._plotted(ax)
            counts.append(ys.size)
            self.assertGreater(ys.size, 0, "every panel must keep its own points")
            low, high = sorted(ax.get_xlim())
            # No vertex sits outside its own panel window.
            self.assertTrue(bool(((xs >= low) & (xs <= high)).all()))
            # And the series is genuinely split.
            self.assertGreater(int(np.isnan(raw).sum()), 0)
        self.assertEqual(counts, [3, 3])

    def test_broken_x_does_not_draw_a_line_across_the_break(self):
        fig = render_chart(self._gap_in_x_datasets(), {
            "chart_type": "line_scatter", "xaxis_mode": "numeric",
            "show_mean": True, "show_connecting_line": True,
            "use_broken_x_axis": True,
            "broken_x_left_min": 0, "broken_x_left_max": 3,
            "broken_x_right_min": 7, "broken_x_right_max": 10,
        }, figsize=(4, 3), dpi=60)

        for ax in fig.axes:
            xs, _ys, _raw = self._plotted(ax)
            low, high = sorted(ax.get_xlim())
            self.assertTrue(bool(((xs >= low - 1e-6) & (xs <= high + 1e-6)).all()))

    def test_both_axes_broken_partition_the_data(self):
        """The four quadrants together hold every point, each exactly once."""
        fig = render_chart(self._gap_in_x_datasets(), {
            "chart_type": "line_scatter", "xaxis_mode": "numeric",
            "show_mean": True, "show_connecting_line": True,
            "use_broken_x_axis": True, "use_broken_y_axis": True,
            "broken_x_left_min": 0, "broken_x_left_max": 3,
            "broken_x_right_min": 7, "broken_x_right_max": 10,
            "broken_y_bot_min": 0, "broken_y_bot_max": 20,
            "broken_y_top_min": 25, "broken_y_top_max": 40,
        }, figsize=(4, 3), dpi=60)

        self.assertEqual(len(fig.axes), 4)
        total = 0
        for ax in fig.axes:
            xs, ys, _raw = self._plotted(ax)
            total += ys.size
            for x, y in zip(xs, ys):
                x_low, x_high = sorted(ax.get_xlim())
                y_low, y_high = sorted(ax.get_ylim())
                self.assertTrue(x_low - 1e-6 <= x <= x_high + 1e-6, (x, ax.get_xlim()))
                self.assertTrue(y_low - 1e-6 <= y <= y_high + 1e-6, (y, ax.get_ylim()))
        # 6 points across the four panels; the (low x, high y) and (high x, low y)
        # quadrants are legitimately empty.
        self.assertEqual(total, 6)


class TestExports(TempDirMixin, unittest.TestCase):
    def test_png_export(self):
        fig = render()
        out = self.path("fig.png")
        chart_builder.export_figure(fig, out, make_settings({"export_dpi": 80}))
        self.assertTrue(os.path.getsize(out) > 0)

    def test_pdf_and_svg_export(self):
        for extension in (".pdf", ".svg"):
            with self.subTest(extension=extension):
                fig = render()
                out = self.path("fig" + extension)
                chart_builder.export_figure(fig, out, make_settings({}))
                self.assertTrue(os.path.getsize(out) > 0)

    def test_custom_size_export_changes_pixel_dimensions(self):
        fig = render()
        settings = make_settings({"export_mode": "custom_size",
                                  "fig_width": 4, "fig_height": 2,
                                  "export_dpi": 50})
        out = self.path("sized.png")
        chart_builder.export_figure(fig, out, settings)
        from PIL import Image  # noqa: PLC0415  (optional dependency)
        with Image.open(out) as image:
            self.assertEqual(image.size, (200, 100))

    def test_export_restores_figure_size(self):
        fig = render(figsize=(5, 4))
        before = tuple(fig.get_size_inches())
        chart_builder.export_figure(fig, self.path("x.png"),
                                    make_settings({"export_mode": "custom_size",
                                                   "fig_width": 2, "fig_height": 2}))
        self.assertEqual(tuple(fig.get_size_inches()), before)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCli(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from easyfig import cli

        self.cli = cli

    def run_cli(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.cli.main(argv)
        return code, stdout.getvalue()

    def _table_csv(self, name="table.csv"):
        path = self.path(name)
        pd.DataFrame({
            "Size": [1, 2, 3, 4],
            "A": [10.0, 20.0, 30.0, 40.0],
            "B": [9.0, 19.0, 31.0, 39.0],
        }).to_csv(path, index=False)
        return path

    def _spec_json(self, name="spec.json"):
        path = self.path(name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({
                "datasets": [{"name": "A", "sizes": [1, 2, 3],
                              "data": [[1.0], [2.0], [3.0]]}],
                "settings": {"chart_type": "bar", "title": "Spec chart"},
            }, handle)
        return path

    def test_plot_from_table(self):
        out = self.path("a.png")
        code, _ = self.run_cli(["plot", "--table", self._table_csv(),
                                "--time-column", "Size", "-o", out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.getsize(out) > 0)

    def test_positional_input_inference(self):
        out = self.path("p.png")
        code, _ = self.run_cli(["plot", self._table_csv(), "-o", out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out))

    def test_json_out_reports_dataset_names(self):
        out = self.path("j.png")
        code, stdout = self.run_cli([
            "plot", "--table", self._table_csv(), "--time-column", "Size",
            "-o", out, "--json-out"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["datasets"], ["A", "B"])
        self.assertEqual(payload["output"], out)

    def test_spec_command(self):
        out = self.path("s.png")
        code, _ = self.run_cli(["spec", self._spec_json(), "-o", out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out))

    def test_print_settings(self):
        code, stdout = self.run_cli(["plot", "--chart-type", "pie",
                                     "--x-tick-count", "9", "--print-settings"])
        self.assertEqual(code, 0)
        settings = json.loads(stdout)
        self.assertEqual(settings["chart_type"], "pie")
        self.assertEqual(settings["x_tick_count"], 9)

    def test_set_escape_hatch(self):
        out = self.path("set.png")
        code, _ = self.run_cli(["plot", "--table", self._table_csv(),
                                "--set", "chart_type=pie", "--set", "legend_loc=best",
                                "-o", out])
        self.assertEqual(code, 0)

    def test_multiline_merge(self):
        first = self.path("l1.xlsx")
        second = self.path("l2.xlsx")
        pd.DataFrame({"l": ["a", "a"], 1: [1.0, 1.1], 2: [2.0, 2.1]}).to_excel(first, index=False)
        pd.DataFrame({"l": ["b", "b"], 1: [3.0, 3.1], 2: [4.0, 4.1]}).to_excel(second, index=False)
        out = self.path("m.png")
        code, stdout = self.run_cli(["plot", "--multiline", first, second, "--merge",
                                     "-o", out, "--json-out"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["datasets"], ["Merged_Dataset"])

    def test_fit_option(self):
        out = self.path("fit.png")
        code, _ = self.run_cli(["plot", "--table", self._table_csv(),
                                "--time-column", "Size", "--fit", "linear",
                                "--show-raw", "--show-fit", "-o", out])
        self.assertEqual(code, 0)

    def test_polynomial_fit(self):
        out = self.path("poly.png")
        code, _ = self.run_cli(["plot", "--table", self._table_csv(),
                                "--time-column", "Size", "--fit", "polynomial",
                                "--degree", "3", "-o", out])
        self.assertEqual(code, 0)

    def test_options_command_json(self):
        code, stdout = self.run_cli(["options", "--json"])
        self.assertEqual(code, 0)
        self.assertIn("chart_type", json.loads(stdout))

    def test_options_command_text(self):
        code, stdout = self.run_cli(["options"])
        self.assertEqual(code, 0)
        self.assertIn("Chart types", stdout)

    def test_missing_input_is_an_error(self):
        code, _ = self.run_cli(["plot", "-o", self.path("x.png")])
        self.assertEqual(code, 1)

    def test_no_output_and_no_print_is_an_error(self):
        code, _ = self.run_cli(["plot", "--table", self._table_csv()])
        self.assertEqual(code, 1)

    def test_unknown_setting_is_rejected(self):
        code, _ = self.run_cli(["plot", "--table", self._table_csv(),
                                "--set", "nope=1", "-o", self.path("x.png")])
        self.assertEqual(code, 1)

    def test_bad_colour_is_rejected(self):
        code, _ = self.run_cli(["plot", "--table", self._table_csv(),
                                "--set", "line_color=zzz",
                                "-o", self.path("x.png")])
        self.assertEqual(code, 1)

    def test_missing_table_is_an_error(self):
        code, _ = self.run_cli(["plot", "--table", self.path("nope.csv"),
                                "-o", self.path("x.png")])
        self.assertEqual(code, 1)

    def test_bad_output_extension(self):
        code, _ = self.run_cli(["plot", "--table", self._table_csv(),
                                "-o", self.path("x.xyz")])
        self.assertEqual(code, 1)

    def test_bad_json_payload(self):
        path = self.path("bad.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{oops")
        code, _ = self.run_cli(["plot", "--json", path, "-o", self.path("x.png")])
        self.assertEqual(code, 1)

    def test_no_subcommand_returns_usage(self):
        code, _ = self.run_cli([])
        self.assertEqual(code, 2)

    def test_broken_axis_via_cli(self):
        out = self.path("broken.png")
        code, _ = self.run_cli([
            "plot", "--table", self._table_csv(), "--time-column", "Size",
            "--chart-type", "line", "--xaxis-mode", "numeric",
            "--broken-x", "--broken-x-low-min", "1", "--broken-x-low-max", "2",
            "--broken-x-high-min", "4", "--broken-x-high-max", "5",
            "-o", out])
        self.assertEqual(code, 0)

    def test_gui_subcommand_is_registered(self):
        parser = self.cli.build_parser()
        args = parser.parse_args(["gui"])
        self.assertEqual(args.command, "gui")

    def test_palettes_command_text(self):
        code, stdout = self.run_cli(["palettes"])
        self.assertEqual(code, 0)
        self.assertIn("akun42_nature", stdout)
        self.assertIn("#4E74B3", stdout)

    def test_palettes_command_json(self):
        code, stdout = self.run_cli(["palettes", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(len(payload), 10)
        self.assertEqual(payload["akun42_nature"]["colors"][0], "#4E74B3")
        self.assertEqual(payload["akun42_nature"]["issue"], 42)

    def test_palette_flag_recolours_datasets(self):
        out = self.path("pal.png")
        code, stdout = self.run_cli([
            "plot", "--table", self._table_csv(), "--time-column", "Size",
            "--palette", "akun42_nature", "-o", out, "--json-out"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["palette"], "akun42_nature")
        self.assertEqual(payload["datasets"], ["A", "B"])
        self.assertEqual(payload["colors"], ["#4E74B3", "#FB9780"])

    def test_palette_reverse_flag(self):
        out = self.path("palr.png")
        code, stdout = self.run_cli([
            "plot", "--table", self._table_csv(), "--time-column", "Size",
            "--palette", "akun42_nature", "--palette-reverse",
            "-o", out, "--json-out"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["colors"], ["#944D55", "#FDBCA8"])

    def test_unknown_palette_is_rejected(self):
        code, _ = self.run_cli(["plot", "--table", self._table_csv(),
                                "--palette", "not-a-palette",
                                "-o", self.path("x.png")])
        self.assertEqual(code, 1)

    def test_apply_palette_wraps_and_subsamples(self):
        from easyfig.cli import apply_palette

        many = {f"D{i}": {"sizes": [1], "data": [[1.0]], "color": "#000000"}
                for i in range(11)}
        apply_palette(many, "akun42_nature")
        colors = [dataset["color"] for dataset in many.values()]
        self.assertEqual(len(colors), 11)
        self.assertEqual(colors[8], colors[0])  # wrapped around

        few = {f"D{i}": {"sizes": [1], "data": [[1.0]], "color": "#000000"}
               for i in range(2)}
        apply_palette(few, "akun42_nature")
        self.assertEqual([d["color"] for d in few.values()], ["#4E74B3", "#FB9780"])

    def test_palette_works_with_a_json_spec(self):
        out = self.path("spec_pal.png")
        code, stdout = self.run_cli(["spec", self._spec_json(), "--palette",
                                     "akun39_echarts", "-o", out, "--json-out"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["colors"], ["#546FC6"])


class TestMainDispatcher(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        import main

        self.main = main

    def test_cli_subcommand_is_forwarded(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.main.main(["options", "--json"])
        self.assertEqual(code, 0)
        self.assertIn("chart_type", stdout.getvalue())

    def test_plot_is_forwarded(self):
        path = self.path("t.csv")
        pd.DataFrame({"Size": [1, 2], "A": [1.0, 2.0]}).to_csv(path, index=False)
        out = self.path("o.png")
        with contextlib.redirect_stdout(io.StringIO()):
            code = self.main.main(["plot", "--table", path, "--time-column", "Size",
                                   "-o", out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out))


# ---------------------------------------------------------------------------
# Scientific palettes and colour helpers
# ---------------------------------------------------------------------------

#: Pinned copy of the ten palettes, independent of ``palettes.py``, so that an
#: accidental edit to the colour values fails the suite.
EXPECTED_PALETTES = {
    "akun42_nature": (42, "#4E74B3 #96D1DF #FEE0D5 #FDBCA8 #FB9780 #EB6E68 #C85A5D #944D55"),
    "akun41_nature": (41, "#485098 #4660AD #5A96CC #68B4CE #80CDBB #A5C582 #D6CF67 #F3DE67 #F9EF7C"),
    "akun40_tibet": (40, "#00B8AA #374649 #FD625E #F2C811 #5F6B6D #8AD4EB #FE9666 #A66999"),
    "akun39_echarts": (39, "#546FC6 #91CB74 #FAC859 #EE6666 #73C0DE #3BA372 #FC8452 #9A60B4"),
    "akun38_latlf_m": (38, "#8E0028 #BD3C33 #E4945A #F9C676 #FBECAB #FFFFFF #D1E2EF #7FA9CD #527CB4 #3F60A3 #30327D"),
    "akun37_nature": (37, "#334454 #185D7A #0178A2 #0892AE #13AFBE #53C3C4 #99D7CC #CCE7E2 #FAFCFB"),
    "akun36_nature": (36, "#2A1773 #1E3096 #10528E #226C87 #348286 #479A88 #5AB37D #82CD66 #C5DD6D #F8EE97"),
    "akun35_science": (35, "#C1282D #D75728 #ED8622 #F6B66B #FCE7CE #C9DFEF #5CA0CF #0D67A6 #174263 #211D1F"),
    "akun33_science": (33, "#F37252 #F7935A #FCB461 #FED297 #FFF0DC #E3F5F6 #ABE0E4 #7FC6D3 #779FC6 #6F78B9"),
    "akun32_nature": (32, "#224767 #6FAEE0 #A1CAED #D1E6F8 #FEFDFE #E4CCE4 #CA95C3 #A85EA2 #8E338A"),
}


class TestPaletteLibrary(unittest.TestCase):
    def test_ten_palettes_in_recommended_order(self):
        self.assertEqual(len(palettes.PALETTE_ORDER), 10)
        self.assertEqual(palettes.palette_names(), palettes.PALETTE_ORDER)
        self.assertEqual(list(EXPECTED_PALETTES), palettes.PALETTE_ORDER)

    def test_palette_colors_match_the_published_values(self):
        for key, (issue, spec) in EXPECTED_PALETTES.items():
            with self.subTest(palette=key):
                meta = palettes.SCIENTIFIC_PALETTES[key]
                self.assertEqual(meta["issue"], issue)
                self.assertEqual(meta["colors"], spec.split())

    def test_every_palette_has_unique_colors(self):
        for key in palettes.PALETTE_ORDER:
            colors = palettes.SCIENTIFIC_PALETTES[key]["colors"]
            with self.subTest(palette=key):
                self.assertEqual(len(colors), len(set(colors)))

    def test_metadata_carries_provenance(self):
        for key in palettes.PALETTE_ORDER:
            meta = palettes.SCIENTIFIC_PALETTES[key]
            for field in ("issue", "journal", "kind", "citation", "url", "title"):
                with self.subTest(palette=key, field=field):
                    self.assertTrue(meta.get(field), f"{key}:{field} is empty")

    def test_colors_can_be_subsampled_wrapped_and_reversed(self):
        key = "akun42_nature"
        full = palettes.SCIENTIFIC_PALETTES[key]["colors"]
        self.assertEqual(palettes.palette_colors(key), full)
        self.assertEqual(palettes.palette_colors(key, 0), [])
        three = palettes.palette_colors(key, 3)
        self.assertEqual(len(three), 3)
        self.assertEqual(three[0], full[0])
        self.assertEqual(palettes.palette_colors(key, 8), full)
        self.assertEqual(palettes.palette_colors(key, 10), full + full[:2])
        self.assertEqual(palettes.palette_colors(key, reverse=True), full[::-1])

    def test_palettes_with_at_least(self):
        self.assertEqual(palettes.palettes_with_at_least(11), ["akun38_latlf_m"])
        self.assertEqual(len(palettes.palettes_with_at_least(8)), 10)
        self.assertEqual(palettes.palettes_with_at_least(12), [])

    def test_all_palette_colors_is_deduplicated_and_complete(self):
        colors = palettes.all_palette_colors()
        self.assertEqual(len(colors), 92)
        self.assertEqual(len({color.lower() for color in colors}), 92)

    def test_palette_color_items_are_named_positions(self):
        items = palettes.palette_color_items()
        self.assertEqual(len(items), 92)
        mapping = dict(items)
        self.assertEqual(mapping["P42 Nature 1"], "#4E74B3")
        self.assertEqual(mapping["P42 Nature 8"], "#944D55")
        self.assertEqual(mapping["P40 未标注 1"], "#00B8AA")
        self.assertEqual(mapping["P38 Nature Climate Change 11"], "#30327D")

    def test_labels(self):
        self.assertEqual(palettes.palette_series_label("akun42_nature"), "P42 Nature")
        self.assertEqual(palettes.palette_series_label("akun40_tibet"), "P40 未标注")
        self.assertEqual(palettes.palette_series_label("akun38_latlf_m"),
                         "P38 Nature Climate Change")
        self.assertIn("第42期", palettes.describe_palette("akun42_nature"))
        self.assertIn("colors", palettes.palette_label("akun42_nature"))

    def test_unknown_palette_raises(self):
        with self.assertRaises(KeyError):
            palettes.palette_colors("nope")
        with self.assertRaises(KeyError):
            palettes.describe_palette("nope")

    def test_module_stays_dependency_free(self):
        """The picker imports palettes without numpy/matplotlib/tkinter/pandas."""
        with open(palettes.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for banned in ("import numpy", "import matplotlib", "import tkinter",
                       "import pandas"):
            self.assertNotIn(banned, source)


class TestColorHelpers(unittest.TestCase):
    def test_normalize_accepts_hex_forms(self):
        for raw, expected in (
            ("#4E74B3", "#4e74b3"), ("4E74B3", "#4e74b3"),
            ("#ABC", "#aabbcc"), ("abc", "#aabbcc"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(palettes.normalize_color(raw), expected)

    def test_normalize_passes_named_colors_through(self):
        self.assertEqual(palettes.normalize_color("red"), "red")
        self.assertEqual(palettes.normalize_color("Black"), "Black")

    def test_normalize_fallback_and_errors(self):
        self.assertEqual(palettes.normalize_color(None, "#123456"), "#123456")
        self.assertEqual(palettes.normalize_color("   ", "#123456"), "#123456")
        with self.assertRaises(ValueError):
            palettes.normalize_color("not-a-colour")
        with self.assertRaises(ValueError):
            palettes.normalize_color(7)

    def test_is_hex_color(self):
        for good in ("#fff", "fff", "#ffffff", "ABCDEF"):
            self.assertTrue(palettes.is_hex_color(good), good)
        for bad in ("#ffff", "ggg", "", None, "#ffffff00"):
            self.assertFalse(palettes.is_hex_color(bad), bad)

    def test_text_color_for_contrast(self):
        self.assertEqual(palettes.text_color_for("#ffffff"), "#000000")
        self.assertEqual(palettes.text_color_for("#000000"), "#ffffff")
        self.assertEqual(palettes.text_color_for("black"), "#ffffff")

    def test_every_palette_color_is_valid_and_round_trips(self):
        for color in palettes.all_palette_colors():
            with self.subTest(color=color):
                self.assertTrue(palettes.is_hex_color(color))
                self.assertEqual(palettes.normalize_color(color), color.lower())

    def test_chart_builder_uses_the_shared_helper(self):
        self.assertIs(chart_builder.normalize_color, palettes.normalize_color)


class TestConfigPaletteIntegration(unittest.TestCase):
    def test_base_picks_come_first_and_are_unchanged(self):
        """Extending AVAILABLE_COLORS must not renumber existing assignments."""
        keys = list(AVAILABLE_COLORS)
        self.assertEqual(keys[:len(BASE_COLORS)], list(BASE_COLORS))
        self.assertEqual(list(BASE_COLORS.values())[:3],
                         ["#1f77b4", "#ff7f0e", "#2ca02c"])

    def test_every_palette_color_is_available_by_name(self):
        for name, color in palettes.palette_color_items():
            with self.subTest(name=name):
                self.assertEqual(AVAILABLE_COLORS.get(name), color)

    def test_counts(self):
        self.assertEqual(len(PALETTE_COLORS), 92)
        self.assertEqual(len(AVAILABLE_COLORS), len(BASE_COLORS) + 92)

    def test_available_palette_colors_are_tk_safe(self):
        for color in PALETTE_COLORS.values():
            self.assertTrue(palettes.is_hex_color(color), color)

    def test_config_reexports_the_palette_api(self):
        from easyfig import config

        self.assertIs(config.SCIENTIFIC_PALETTES, palettes.SCIENTIFIC_PALETTES)
        self.assertEqual(config.PALETTE_ORDER, palettes.PALETTE_ORDER)


class TestFonts(unittest.TestCase):
    """Chinese labels must not render as tofu boxes."""

    def test_cjk_font_is_configured(self):
        from easyfig import fonts

        families = fonts.configure_matplotlib_fonts()
        self.assertTrue(families, "no CJK-capable font was found on this machine")

        import matplotlib

        self.assertEqual(matplotlib.rcParams["font.sans-serif"][0], families[0])
        # U+2212 is missing from several CJK families.
        self.assertFalse(matplotlib.rcParams["axes.unicode_minus"])

    def test_serif_stack_keeps_serif_first_and_adds_cjk(self):
        from easyfig import fonts

        stack = fonts.serif_stack()
        self.assertEqual(stack[0], "DejaVu Serif")
        for family in fonts.installed_cjk_fonts():
            self.assertIn(family, stack)

    def test_configuration_is_idempotent(self):
        from easyfig import fonts

        first = fonts.configure_matplotlib_fonts()
        second = fonts.configure_matplotlib_fonts()
        self.assertEqual(first, second)

        import matplotlib

        families = list(matplotlib.rcParams["font.sans-serif"])
        fonts.configure_matplotlib_fonts()
        self.assertEqual(list(matplotlib.rcParams["font.sans-serif"]), families)

    def test_chinese_labels_render_without_missing_glyphs(self):
        """Regression: DejaVu Sans turned every Chinese label into a box."""
        datasets = {
            "示例 A": {"sizes": [1, 2, 3], "data": [[1.0], [2.0], [3.0]],
                       "color": "#4E74B3"},
        }
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fig = render_chart(datasets, {
                "title": "推力分析",
                "xlabel": "尺寸",
                "ylabel": "推力",
                "y_unit": "千克",
                "xaxis_mode": "numeric",
            }, figsize=(4, 3), dpi=60)
            fig.canvas.draw()

        missing = [str(item.message) for item in caught
                   if "missing from font" in str(item.message)]
        self.assertEqual(missing, [], f"missing glyphs: {missing}")

    def test_chinese_renders_with_the_sci_preset(self):
        datasets = {"示例": {"sizes": [1, 2], "data": [[1.0], [2.0]],
                            "color": "#4E74B3"}}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fig = render_chart(datasets, {"visual_preset": "sci", "title": "中文标题"},
                               figsize=(4, 3), dpi=60)
            fig.canvas.draw()
        missing = [str(item.message) for item in caught
                   if "missing from font" in str(item.message)]
        self.assertEqual(missing, [], f"missing glyphs: {missing}")


class TestBridge(unittest.TestCase):
    """The line-delimited JSON protocol the Electron front end speaks."""

    def setUp(self):
        from easyfig import bridge

        self.bridge = bridge

    def call(self, cmd, **payload):
        response = self.bridge.handle_request({"id": 1, "cmd": cmd, **payload})
        self.assertTrue(response["ok"], response.get("error"))
        return response["result"]

    def fails(self, cmd, **payload):
        response = self.bridge.handle_request({"id": 1, "cmd": cmd, **payload})
        self.assertFalse(response["ok"])
        return response["error"]

    @staticmethod
    def wire_datasets():
        return [
            {"name": "A", "sizes": [1, 2, 3],
             "data": [[1.0, 1.1], [2.0, 2.2], [3.0]], "color": "#4E74B3"},
            {"name": "B", "sizes": [1, 2, 3],
             "data": [[2.0], [2.5], [3.5]], "color": "#FB9780"},
        ]

    # -- schema ------------------------------------------------------------

    def test_hello_returns_the_interface_schema(self):
        schema = self.call("hello")
        self.assertEqual(schema["protocol"], self.bridge.PROTOCOL_VERSION)
        self.assertEqual(schema["version"], easyfig.__version__)
        self.assertEqual(len(schema["chartTypes"]), 6)
        self.assertEqual(len(schema["palettes"]), 10)
        self.assertEqual(len(schema["baseColors"]), len(BASE_COLORS))
        self.assertEqual(schema["totalPaletteColors"], 92)
        self.assertEqual(schema["totalAvailableColors"], len(AVAILABLE_COLORS))

    def test_schema_defaults_match_the_shared_settings(self):
        schema = self.call("schema")
        self.assertEqual(schema["defaultSettings"], dict(chart_builder.DEFAULT_SETTINGS))
        self.assertEqual(set(schema["settingKeys"]),
                         set(chart_builder.DEFAULT_SETTINGS))

    def test_schema_palettes_carry_provenance(self):
        for palette in self.call("hello")["palettes"]:
            for field in ("key", "issue", "journal", "kind", "colors", "citation", "url"):
                self.assertIn(field, palette, palette.get("key"))
            self.assertEqual(palette["count"], len(palette["colors"]))

    def test_schema_exposes_the_chart_type_series_rule(self):
        """The interface applies the same rule, so it must be discoverable."""
        schema = self.call("hello")
        self.assertEqual(schema["chartTypeSeriesDefaults"],
                         {key: dict(value) for key, value
                          in chart_builder.CHART_TYPE_SERIES_DEFAULTS.items()})

    def test_scatter_render_has_points_and_no_line(self):
        """Regression: scatter used to render a connecting line only."""
        scatter = self.call("render", datasets=self.wire_datasets(),
                            settings={"chart_type": "scatter", "xaxis_mode": "numeric"},
                            dpi=40)
        self.assertTrue(scatter["png"])
        # The engine reports the drawn series; the styling is asserted by the
        # chart-builder unit tests.

    # -- dataset marshalling ----------------------------------------------

    def test_dataset_round_trip_preserves_order_and_names(self):
        """Integer-like names would be reordered by a JS object; arrays avoid it."""
        entries = [{"name": str(index), "sizes": [1], "data": [[1.0]]}
                   for index in (3, 1, 2, 10)]
        mapping = self.bridge.datasets_from_list(entries)
        self.assertEqual(list(mapping), ["3", "1", "2", "10"])
        restored = self.bridge.datasets_to_list(mapping)
        self.assertEqual([entry["name"] for entry in restored], ["3", "1", "2", "10"])

    def test_datasets_from_list_accepts_the_mapping_form(self):
        mapping = self.bridge.datasets_from_list({"A": {"sizes": [1], "data": [[1.0]]}})
        self.assertEqual(list(mapping), ["A"])

    def test_duplicate_names_are_rejected(self):
        error = self.fails("render", datasets=[
            {"name": "A", "sizes": [1], "data": [[1.0]]},
            {"name": "A", "sizes": [1], "data": [[2.0]]},
        ])
        self.assertEqual(error["kind"], "bad-request")
        self.assertIn("duplicate", error["message"])

    def test_missing_sizes_is_rejected(self):
        error = self.fails("render", datasets=[{"name": "A", "data": [[1.0]]}])
        self.assertEqual(error["kind"], "bad-request")

    # -- render ------------------------------------------------------------

    def test_render_returns_a_decodable_png(self):
        result = self.call("render", datasets=self.wire_datasets(),
                           settings={"chart_type": "line", "xaxis_mode": "numeric"},
                           dpi=60)
        raw = base64.b64decode(result["png"])
        self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
        self.assertGreater(len(raw), 1000)
        self.assertEqual(result["format"], "png")
        self.assertGreater(result["pixelWidth"], 0)
        self.assertGreater(result["pixelHeight"], 0)
        self.assertEqual([entry["name"] for entry in result["datasets"]], ["A", "B"])

    def test_render_returns_statistics(self):
        result = self.call("render", datasets=self.wire_datasets(), dpi=50)
        stats = result["statistics"]
        self.assertEqual(len(stats), 2)
        self.assertEqual(stats[0]["name"], "A")
        self.assertAlmostEqual(stats[0]["mean"][0], 1.05)
        self.assertEqual(len(stats[0]["mean"]), 3)

    def test_render_for_every_chart_type(self):
        for chart_type in ALL_CHART_TYPES:
            with self.subTest(chart_type=chart_type):
                result = self.call("render", datasets=self.wire_datasets(),
                                   settings={"chart_type": chart_type}, dpi=40)
                self.assertTrue(result["png"])

    def test_render_with_processing(self):
        result = self.call("render", datasets=self.wire_datasets(),
                           settings={"xaxis_mode": "numeric"},
                           fit={"method": "linear", "showRaw": True, "showFit": True},
                           dpi=40)
        names = [entry["name"] for entry in result["datasets"]]
        self.assertTrue(any("R\u00b2" in name for name in names))
        self.assertTrue(any("(Raw)" in name for name in names))

    def test_render_rejects_unknown_settings(self):
        error = self.fails("render", datasets=self.wire_datasets(),
                           settings={"not_a_setting": 1})
        self.assertEqual(error["kind"], "bad-settings")
        self.assertIn("unknown setting", error["message"])

    def test_render_without_datasets(self):
        error = self.fails("render", datasets=[])
        self.assertEqual(error["kind"], "no-data")

    def test_render_caps_the_preview_size(self):
        result = self.call("render", datasets=self.wire_datasets(),
                           settings={"fig_width": 40, "fig_height": 40}, dpi=300)
        self.assertLessEqual(max(result["pixelWidth"], result["pixelHeight"]),
                             self.bridge.MAX_PREVIEW_PIXELS)

    # -- export ------------------------------------------------------------

    def test_export_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for extension in (".png", ".pdf", ".svg"):
                with self.subTest(extension=extension):
                    target = os.path.join(tmp, "figure" + extension)
                    result = self.call("export", datasets=self.wire_datasets(),
                                       settings={"export_dpi": 60}, path=target)
                    self.assertTrue(os.path.getsize(target) > 0)
                    self.assertEqual(result["path"], os.path.abspath(target))
                    self.assertGreater(result["bytes"], 0)

    def test_export_needs_a_path(self):
        error = self.fails("export", datasets=self.wire_datasets())
        self.assertEqual(error["kind"], "bad-request")

    def test_export_rejects_unknown_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            error = self.fails("export", datasets=self.wire_datasets(),
                               path=os.path.join(tmp, "figure.xyz"))
            self.assertEqual(error["kind"], "bad-request")
            self.assertIn("extension", error["message"])

    # -- tables ------------------------------------------------------------

    def _table(self, directory, name="table.csv"):
        path = os.path.join(directory, name)
        pd.DataFrame({
            "Size": [1, 2, 3],
            "LotA": [10.0, 20.0, 30.0],
            "LotB": [11.0, 21.0, 31.0],
        }).to_csv(path, index=False)
        return path

    def test_inspect_table_describes_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.call("inspect_table", path=self._table(tmp))
            self.assertEqual(result["rows"], 3)
            self.assertEqual([column["name"] for column in result["columns"]],
                             ["Size", "LotA", "LotB"])
            self.assertTrue(all(column["numeric"] for column in result["columns"]))
            self.assertEqual(len(result["preview"]), 3)

    def test_import_table_with_time_column_and_column_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.call("import_table", path=self._table(tmp),
                               orientation="vertical", timeColumn="Size",
                               columns=["Size", "LotA"])
            datasets = result["datasets"]
            self.assertEqual([entry["name"] for entry in datasets], ["LotA"])
            self.assertEqual(datasets[0]["sizes"], [1.0, 2.0, 3.0])

    def test_import_table_rejects_unknown_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            error = self.fails("import_table", path=self._table(tmp),
                               columns=["Nope"])
            self.assertEqual(error["kind"], "bad-request")

    def test_import_table_missing_file(self):
        error = self.fails("import_table", path="does/not/exist.csv")
        self.assertEqual(error["kind"], "io-error")

    def test_import_multiline_and_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, "a.xlsx")
            second = os.path.join(tmp, "b.xlsx")
            pd.DataFrame({"l": ["a", "a"], 1: [1.0, 1.2], 2: [2.0, 2.2]}).to_excel(
                first, index=False)
            pd.DataFrame({"l": ["b", "b"], 3: [3.0, 3.2], 4: [4.0, 4.2]}).to_excel(
                second, index=False)

            separate = self.call("import_multiline", paths=[first, second],
                                 orientation="vertical")
            self.assertEqual(len(separate["datasets"]), 2)

            merged = self.call("import_multiline", paths=[first, second],
                               orientation="vertical", merge=True)
            self.assertEqual([entry["name"] for entry in merged["datasets"]],
                             ["Merged_Dataset"])

    def test_import_multiline_needs_paths(self):
        error = self.fails("import_multiline", paths=[])
        self.assertEqual(error["kind"], "bad-request")

    # -- palettes and colours ---------------------------------------------

    def test_palettes_command(self):
        payload = self.call("palettes")["palettes"]
        self.assertEqual(len(payload), 10)
        self.assertEqual(payload[0]["key"], "akun42_nature")

    def test_palette_colors_command(self):
        result = self.call("palette_colors", key="akun42_nature", count=3)
        self.assertEqual(len(result["colors"]), 3)
        reversed_colors = self.call("palette_colors", key="akun42_nature",
                                    reverse=True)["colors"]
        self.assertEqual(reversed_colors[0], "#944D55")

    def test_palette_colors_unknown_key(self):
        error = self.fails("palette_colors", key="nope")
        self.assertEqual(error["kind"], "bad-request")

    def test_normalize_color(self):
        self.assertEqual(self.call("normalize_color", color="4E74B3")["color"], "#4e74b3")
        self.assertEqual(self.call("normalize_color", color="#ABC")["color"], "#aabbcc")
        error = self.fails("normalize_color", color="not-a-colour")
        self.assertEqual(error["kind"], "bad-color")

    def test_options_command(self):
        result = self.call("options")
        self.assertEqual(result["settings"], dict(chart_builder.DEFAULT_SETTINGS))
        self.assertEqual(len(result["fitMethods"]), 6)

    # -- protocol ----------------------------------------------------------

    def test_unknown_command_is_reported(self):
        error = self.fails("definitely-not-a-command")
        self.assertEqual(error["kind"], "unknown-command")
        self.assertIn("known commands", error["message"])

    def test_missing_command_is_reported(self):
        response = self.bridge.handle_request({"id": 7})
        self.assertFalse(response["ok"])
        self.assertEqual(response["id"], 7)
        self.assertEqual(response["error"]["kind"], "bad-request")

    def test_non_object_request_is_reported(self):
        response = self.bridge.handle_request(["not", "an", "object"])
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["kind"], "bad-request")

    def test_handle_line_parses_json(self):
        response = self.bridge.handle_line('{"id": 3, "cmd": "hello"}')
        self.assertTrue(response["ok"])
        self.assertEqual(response["id"], 3)

    def test_handle_line_reports_bad_json(self):
        response = self.bridge.handle_line("{oops")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["kind"], "bad-json")

    def test_handle_line_ignores_blank_lines(self):
        self.assertIsNone(self.bridge.handle_line("   "))
        self.assertIsNone(self.bridge.handle_line(""))

    def test_ids_are_echoed(self):
        for request_id in (0, 1, 42, "abc"):
            response = self.bridge.handle_request({"id": request_id, "cmd": "hello"})
            self.assertEqual(response["id"], request_id)

    def test_internal_errors_do_not_escape(self):
        """A handler that raises must still produce a protocol response."""
        original = self.bridge.COMMANDS["hello"]

        def explode(_request):
            raise RuntimeError("boom")

        self.bridge.COMMANDS["hello"] = explode
        try:
            response = self.bridge.handle_request({"id": 1, "cmd": "hello"})
        finally:
            self.bridge.COMMANDS["hello"] = original
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["kind"], "internal")
        self.assertIn("boom", response["error"]["message"])

    def test_stdout_carries_only_protocol_lines(self):
        """Warnings and other prints must not corrupt the protocol stream."""
        lines = [
            json.dumps({"id": 1, "cmd": "hello"}),
            json.dumps({"id": 2, "cmd": "render", "datasets": self.wire_datasets(),
                        "dpi": 40}),
            json.dumps({"id": 3, "cmd": "shutdown"}),
        ]
        old_stdin, old_stdout = sys.stdin, sys.stdout
        captured = io.StringIO()
        try:
            sys.stdin = io.StringIO("\n".join(lines) + "\n")
            sys.stdout = captured
            self.bridge.main()
        finally:
            sys.stdin, sys.stdout = old_stdin, old_stdout

        payloads = [line for line in captured.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(payloads), 3)
        for line in payloads:
            json.loads(line)  # raises if anything non-protocol leaked in
        self.assertTrue(json.loads(payloads[2])["result"]["bye"])

    def test_shutdown_ends_the_loop(self):
        """Lines after shutdown are not processed."""
        old_stdin, old_stdout = sys.stdin, sys.stdout
        captured = io.StringIO()
        try:
            sys.stdin = io.StringIO("\n".join([
                json.dumps({"id": 1, "cmd": "shutdown"}),
                json.dumps({"id": 2, "cmd": "hello"}),
            ]) + "\n")
            sys.stdout = captured
            self.bridge.main()
        finally:
            sys.stdin, sys.stdout = old_stdin, old_stdout
        self.assertEqual(len(captured.getvalue().strip().splitlines()), 1)

    def test_module_entry_point(self):
        """`python -m easyfig.bridge` must serve the protocol end to end."""
        script = "from easyfig import bridge; import sys; sys.exit(bridge.main())"
        try:
            process = subprocess.run(
                [sys.executable, "-c", script],
                input=json.dumps({"id": 1, "cmd": "hello"}) + "\n",
                capture_output=True, text=True, cwd=ROOT, timeout=180,
                env={**os.environ, "PYTHONPATH": ROOT},
            )
        except OSError as exc:  # pragma: no cover - confined sandboxes
            self.skipTest(f"cannot spawn a subprocess here: {exc}")
        self.assertEqual(process.returncode, 0, process.stderr)
        first = json.loads(process.stdout.strip().splitlines()[0])
        self.assertTrue(first["ok"])
        self.assertEqual(len(first["result"]["palettes"]), 10)


class TestElectronPackaging(unittest.TestCase):
    """The Electron app must stay in step with the Python package."""

    def _manifest(self):
        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_manifest_version_matches_python(self):
        self.assertEqual(self._manifest()["version"], easyfig.__version__)

    def test_entry_points_exist(self):
        manifest = self._manifest()
        self.assertEqual(manifest["main"], "electron/main.js")
        for relative in ("electron/main.js", "electron/preload.js",
                         "electron/python-bridge.js", "electron/renderer/index.html",
                         "electron/renderer/app.js",
                         "electron/renderer/styles/apple.css"):
            with self.subTest(file=relative):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, relative)), relative)

    def test_renderer_is_referenced_by_the_main_process(self):
        with open(os.path.join(ROOT, "electron", "main.js"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("renderer", source)
        self.assertIn("index.html", source)
        self.assertIn("preload.js", source)

    def test_preload_exposes_a_narrow_api(self):
        with open(os.path.join(ROOT, "electron", "preload.js"), encoding="utf-8") as handle:
            source = handle.read()
        for name in ("info", "request", "openTable", "openMultiline", "saveFigure",
                     "setTheme", "openExternal", "signalRendered"):
            self.assertIn(f"{name}:", source, name)
        # No raw IPC or Node surface may be handed to the renderer.
        self.assertNotIn("nodeIntegration: true", source)
        self.assertNotIn("require(", source.replace("require('electron')", ""))

    def test_python_bridge_spawns_the_bridge_module(self):
        with open(os.path.join(ROOT, "electron", "python-bridge.js"),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("easyfig.bridge", source)
        self.assertIn("EASYFIG_PYTHON", source)
        self.assertIn(".conda-env", source)

    def test_renderer_loads_only_local_assets(self):
        """The CSP forbids remote code, so no CDN links may creep in."""
        with open(os.path.join(ROOT, "electron", "renderer", "index.html"),
                  encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn("Content-Security-Policy", html)
        self.assertIn("default-src 'none'", html)
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
        self.assertNotIn("<script>", html)  # no inline scripts

    def test_renderer_has_no_inline_event_handlers(self):
        with open(os.path.join(ROOT, "electron", "renderer", "index.html"),
                  encoding="utf-8") as handle:
            html = handle.read()
        for attribute in ("onclick=", "onchange=", "onload="):
            self.assertNotIn(attribute, html, attribute)

    def test_every_control_setting_exists_in_the_engine(self):
        """Any data-setting in the markup must be a real engine setting."""
        with open(os.path.join(ROOT, "electron", "renderer", "index.html"),
                  encoding="utf-8") as handle:
            html = handle.read()
        known = set(chart_builder.DEFAULT_SETTINGS)
        used = set(re.findall(r'data-setting="([^"]+)"', html))
        self.assertTrue(used)
        self.assertEqual(used - known, set(),
                         f"unknown settings referenced by the interface: {used - known}")

    def test_every_colour_setting_exists_in_the_engine(self):
        with open(os.path.join(ROOT, "electron", "renderer", "index.html"),
                  encoding="utf-8") as handle:
            html = handle.read()
        known = set(chart_builder.DEFAULT_SETTINGS)
        used = set(re.findall(r'data-color-setting="([^"]+)"', html))
        self.assertTrue(used)
        self.assertEqual(used - known, set())


class TestElectronSidecar(unittest.TestCase):
    """Drive the real Node sidecar against the real Python bridge."""

    NODE_SCRIPT = r"""
const path = require('node:path');
const { PythonBridge, resolvePython } = require(path.join(process.cwd(), 'electron', 'python-bridge'));

(async () => {
  const python = process.env.EASYFIG_TEST_PYTHON || resolvePython();
  if (!python) { console.error('no python interpreter'); process.exit(2); }
  const engine = new PythonBridge({ python });
  try {
    const schema = await engine.hello();
    const rendered = await engine.request('render', {
      datasets: [{ name: 'A', sizes: [1, 2, 3], data: [[1], [2], [3]], color: '#4E74B3' }],
      settings: { chart_type: 'line', xaxis_mode: 'numeric' },
      dpi: 40,
    });
    const failure = await engine.request('definitely-not-a-command').then(
      () => null,
      (error) => error.kind || 'error',
    );
    console.log(JSON.stringify({
      version: schema.version,
      palettes: schema.palettes.length,
      chartTypes: schema.chartTypes.length,
      pngBytes: Math.round(rendered.png.length * 0.75),
      stats: rendered.statistics.length,
      failureKind: failure,
    }));
  } finally {
    engine.dispose();
  }
  process.exit(0);
})().catch((error) => { console.error(error.message); process.exit(1); });
"""

    @staticmethod
    def _node():
        for name in ("node", "node.exe"):
            try:
                probe = subprocess.run([name, "--version"], capture_output=True,
                                       text=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                continue
            if probe.returncode == 0:
                return name
        return None

    def test_node_sidecar_talks_to_the_python_bridge(self):
        node = self._node()
        if node is None:
            self.skipTest("node is not available")
        python = sys.executable

        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "sidecar-check.js")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write(self.NODE_SCRIPT)
            try:
                process = subprocess.run(
                    [node, script],
                    cwd=ROOT, capture_output=True, text=True, timeout=300,
                    env={**os.environ,
                         "EASYFIG_TEST_PYTHON": python,
                         "EASYFIG_PYTHON": python},
                )
            except OSError as exc:  # pragma: no cover - confined sandboxes
                self.skipTest(f"cannot spawn node here: {exc}")

        self.assertEqual(process.returncode, 0,
                         f"stdout={process.stdout}\nstderr={process.stderr}")
        payload = json.loads(process.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["version"], easyfig.__version__)
        self.assertEqual(payload["palettes"], 10)
        self.assertEqual(payload["chartTypes"], 6)
        self.assertGreater(payload["pngBytes"], 500)
        self.assertEqual(payload["stats"], 1)
        self.assertEqual(payload["failureKind"], "unknown-command")


class TestHeadlessCanvas(unittest.TestCase):
    def test_canvas_draw_is_safe(self):
        fig = render()
        canvas = HeadlessCanvas(fig)
        canvas.draw()
        canvas.draw_idle()
        self.assertIsNone(canvas.mpl_connect("button_press_event", lambda event: None))

    def test_no_tk_widget(self):
        with self.assertRaises(NotImplementedError):
            HeadlessCanvas(render()).get_tk_widget()


def _tk_available():
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


@unittest.skipUnless(_tk_available(), "no Tk display available")
class TestGuiWiring(unittest.TestCase):
    """The GUI must stay in lockstep with the settings the CLI understands."""

    def setUp(self):
        import tkinter as tk

        from easyfig import application

        self.tk = tk
        self.application = application
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = application.DataAnalysisGUI(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.root.destroy()

    def test_collect_settings_covers_every_default(self):
        """Guards against a setting being added to one front end only."""
        collected = self.app._collect_settings()
        self.assertEqual(set(collected), set(chart_builder.DEFAULT_SETTINGS))

    def test_collected_settings_pass_validation(self):
        settings = make_settings(self.app._collect_settings())
        self.assertEqual(settings["chart_type"], "line")
        self.assertEqual(settings["xaxis_mode"], "categorical")

    def test_preset_switch_is_symmetric(self):
        self.app.visual_preset_var.set("SCI")
        self.app._on_visual_preset_selected()
        self.assertEqual(self.app.bar_style_var.get(), "white")
        self.app.visual_preset_var.set("Default")
        self.app._on_visual_preset_selected()
        self.assertEqual(self.app.bar_style_var.get(), "solid")

    def test_every_chart_type_toggles_option_groups(self):
        for chart_type in ALL_CHART_TYPES:
            for mode in ("categorical", "numeric"):
                with self.subTest(chart_type=chart_type, mode=mode):
                    self.app.chart_type_var.set(chart_type)
                    self.app.xaxis_mode.set(mode)
                    self.app._on_plot_method_change()
                    self.root.update_idletasks()

    def test_pie_forces_categorical_mode(self):
        self.app.xaxis_mode.set("numeric")
        self.app.chart_type_var.set("pie")
        self.app._on_plot_method_change()
        self.assertEqual(self.app.xaxis_mode.get(), "categorical")

    def test_error_bar_rows_exist(self):
        """Regression: these were referenced but never created."""
        for attr in ("bar_style_row", "bar_color_row", "errorbar_color_row"):
            self.assertTrue(hasattr(self.app, attr), f"missing {attr}")

    def test_bar_rows_hidden_for_errorbar_charts(self):
        self.app.chart_type_var.set("bar")
        self.app._on_plot_method_change()
        self.assertTrue(self.app.bar_style_row.winfo_manager())
        self.app.chart_type_var.set("errorbar")
        self.app._on_plot_method_change()
        self.assertFalse(self.app.bar_style_row.winfo_manager())
        self.assertTrue(self.app.errorbar_color_row.winfo_manager())

    def test_alpha_frame_returns_for_raw_scatter(self):
        """Regression: the alpha control used to be hidden permanently."""
        self.app.chart_type_var.set("bar")
        self.app._on_plot_method_change()
        self.assertFalse(self.app.alpha_frame.winfo_manager())
        self.app.chart_type_var.set("scatter")
        self.app.show_raw_data_var.set(True)
        self.app._on_plot_method_change()
        self.assertTrue(self.app.alpha_frame.winfo_manager())

    def test_polynomial_degree_spinner_toggles(self):
        self.app.fit_method_var.set("Polynomial Fit")
        self.root.update_idletasks()
        self.assertEqual(str(self.app.poly_degree_spin.cget("state")), "normal")
        self.app.fit_method_var.set("None")
        self.root.update_idletasks()
        self.assertEqual(str(self.app.poly_degree_spin.cget("state")), "disabled")

    def test_generate_chart_renders_every_type(self):
        self.app.datasets["A"] = {"sizes": [1, 2, 3],
                                  "data": [[1.0, 1.1], [2.0], [3.0]],
                                  "color": "#1f77b4"}
        self.app.dataset_listbox.insert("end", "A")
        errors = []
        self.application.messagebox.showerror = lambda title, message, **kw: errors.append(
            (title, message))
        self.application.messagebox.showwarning = lambda title, message, **kw: None
        for chart_type in ALL_CHART_TYPES:
            self.app.chart_type_var.set(chart_type)
            self.app.xaxis_mode.set("categorical")
            self.app._on_plot_method_change()
            self.app.generate_chart()
            for _ in range(40):
                self.root.update()
        self.assertEqual(errors, [])

    # -- palette integration ------------------------------------------------

    def test_palette_dropdown_lists_all_ten(self):
        values = self.app.palette_choice_combo.cget("values")
        self.assertEqual(len(values), 10)
        self.assertEqual(self.app.palette_choice_combo.current(), 0)

    def test_apply_palette_to_datasets(self):
        for name, color in (("A", "#111111"), ("B", "#222222"), ("C", "#333333")):
            self.app.datasets[name] = {"sizes": [1], "data": [[1.0]], "color": color}
            self.app.dataset_listbox.insert("end", name)
        self.application.messagebox.showerror = lambda *a, **k: None
        self.app.palette_choice_combo.current(0)  # akun42_nature
        self.app.apply_palette_to_datasets()
        self.assertEqual(
            [dataset["color"] for dataset in self.app.datasets.values()],
            ["#4E74B3", "#FEE0D5", "#EB6E68"],
        )
        # the listbox swatches follow the datasets
        for position, name in enumerate(self.app.datasets):
            self.assertEqual(
                self.app.dataset_listbox.itemcget(position, "bg"),
                self.app.datasets[name]["color"],
            )

    def test_apply_palette_without_datasets_warns(self):
        warnings = []
        self.application.messagebox.showwarning = lambda title, message, **kw: warnings.append(
            (title, message))
        self.app.apply_palette_to_datasets()
        self.assertEqual(len(warnings), 1)

    def test_palette_selection_survives_a_preset_switch(self):
        self.app.palette_choice_combo.current(4)  # akun38_latlf_m
        self.assertEqual(self.app._selected_palette_key(), "akun38_latlf_m")

    def test_every_palette_colour_is_selectable_in_the_dataset_chooser(self):
        """The chooser dropdown is backed by AVAILABLE_COLORS."""
        captured = {}
        dialog = self.tk.Toplevel(self.root)
        try:
            getter = self.app._build_color_chooser(dialog)
            captured["color"] = getter()
        finally:
            dialog.destroy()
        self.assertIn(captured["color"], AVAILABLE_COLORS.values())

    def test_color_chooser_keeps_a_custom_hex(self):
        dialog = self.tk.Toplevel(self.root)
        try:
            getter = self.app._build_color_chooser(dialog, initial_hex="#123456")
            self.assertEqual(getter(), "#123456")
        finally:
            dialog.destroy()


@unittest.skipUnless(_tk_available(), "no Tk display available")
class TestColorDialog(unittest.TestCase):
    """The picker is where the ten palettes are meant to be usable."""

    def setUp(self):
        import tkinter as tk

        from easyfig.custom_color_dialog import EnglishColorDialog

        self.tk = tk
        self.dialog_class = EnglishColorDialog
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.update_idletasks()

    def tearDown(self):
        self.root.destroy()

    def open_dialog(self, initial="#4E74B3", **kwargs):
        dialog = self.dialog_class(self.root, initial, "Pick a colour", **kwargs)
        self.root.update_idletasks()
        self.addCleanup(self._close, dialog)
        return dialog

    @staticmethod
    def _close(dialog):
        try:
            dialog.dialog.destroy()
        except Exception:
            pass

    def test_palette_dropdown_lists_all_ten(self):
        dialog = self.open_dialog()
        self.assertEqual(len(dialog.palette_combo.cget("values")), 10)
        self.assertEqual(dialog.palette_combo.current(), 0)

    def test_swatch_count_matches_each_palette(self):
        dialog = self.open_dialog()
        for index, key in enumerate(palettes.PALETTE_ORDER):
            with self.subTest(palette=key):
                dialog.palette_combo.current(index)
                dialog._render_palette_swatches()
                self.root.update_idletasks()
                expected = len(palettes.SCIENTIFIC_PALETTES[key]["colors"])
                self.assertEqual(len(dialog._palette_swatches), expected)
                self.assertEqual(len(dialog.swatch_frame.winfo_children()), expected)

    def test_swatch_labels_are_palette_positions(self):
        dialog = self.open_dialog()
        labels = [button.cget("text") for button in dialog._palette_swatches]
        self.assertEqual(labels, [str(index) for index in range(1, 9)])

    def test_clicking_a_swatch_selects_that_colour(self):
        dialog = self.open_dialog()
        seen = []
        dialog.on_change = seen.append

        dialog._palette_swatches[0].invoke()
        self.assertEqual(dialog.selected_color, "#4E74B3")
        self.assertEqual(seen, ["#4E74B3"])
        self.assertEqual(dialog.preview_canvas.cget("bg"), "#4E74B3")
        self.assertEqual(dialog.hex_entry.get(), "#4E74B3")
        self.assertIn("P42 Nature 1", dialog.color_label.cget("text"))

        dialog.palette_combo.current(5)  # akun37_nature
        dialog._render_palette_swatches()
        dialog._palette_swatches[1].invoke()
        self.assertEqual(dialog.selected_color, "#185D7A")
        self.assertIn("P37 Nature 2", dialog.color_label.cget("text"))

    def test_swatch_foreground_contrasts_with_its_colour(self):
        dialog = self.open_dialog()
        dialog.palette_combo.current(4)  # akun38_latlf_m, includes #FFFFFF
        dialog._render_palette_swatches()
        for button in dialog._palette_swatches:
            expected = palettes.text_color_for(button.cget("bg"))
            self.assertEqual(button.cget("fg"), expected)

    def test_preset_section_keeps_the_base_picks(self):
        dialog = self.open_dialog()
        presets = dialog.dialog.winfo_children()[0]
        self.assertEqual(len(presets.winfo_children()), len(BASE_COLORS))

        buttons = [child for child in presets.winfo_children()]
        buttons[0].invoke()
        self.assertEqual(dialog.selected_color, list(BASE_COLORS.values())[0])

    def test_custom_entry_accepts_short_hex_and_names(self):
        dialog = self.open_dialog()
        for raw, expected in (("#ABC", "#aabbcc"), ("4e74b3", "#4e74b3"),
                              ("red", "red")):
            with self.subTest(raw=raw):
                dialog.hex_entry.delete(0, "end")
                dialog.hex_entry.insert(0, raw)
                dialog.apply_custom()
                self.assertEqual(dialog.selected_color, expected)

    def test_custom_entry_rejects_junk(self):
        dialog = self.open_dialog()
        dialog.hex_entry.delete(0, "end")
        dialog.hex_entry.insert(0, "zzz")
        dialog.apply_custom()
        self.assertEqual(dialog.selected_color, "#4e74b3")
        self.assertIn("invalid colour", dialog.color_label.cget("text"))

    def test_invalid_initial_colour_falls_back(self):
        dialog = self.open_dialog(initial="chartreuse-ish")
        self.assertEqual(dialog.selected_color, "#ff0000")

    def test_ok_and_cancel_result_shape(self):
        dialog = self.open_dialog()
        dialog.selected_color = "#123456"
        dialog.ok()
        self.assertEqual(dialog.result, ((0, 0, 0), "#123456"))

        dialog = self.open_dialog()
        dialog.cancel()
        self.assertIsNone(dialog.result)

    def test_every_palette_colour_can_be_selected(self):
        """Clicking every swatch of every palette yields the published colour."""
        dialog = self.open_dialog()
        for index, key in enumerate(palettes.PALETTE_ORDER):
            dialog.palette_combo.current(index)
            dialog._render_palette_swatches()
            for position, button in enumerate(dialog._palette_swatches):
                button.invoke()
                expected = palettes.SCIENTIFIC_PALETTES[key]["colors"][position]
                self.assertEqual(dialog.selected_color, expected, (key, position))


class TestPackaging(unittest.TestCase):
    def _pyproject(self):
        import tomllib

        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as handle:
            return tomllib.load(handle)

    def test_console_script_is_declared(self):
        data = self._pyproject()
        self.assertEqual(data["project"]["name"], "easyfig")
        self.assertEqual(data["project"]["scripts"]["easyfig"], "easyfig.cli:main")
        self.assertEqual(data["project"]["gui-scripts"]["easyfig-gui"],
                         "easyfig.gui:main")

    def test_declared_package_exists(self):
        data = self._pyproject()
        for package in data["tool"]["setuptools"]["packages"]:
            module = importlib.import_module(package)
            self.assertTrue(hasattr(module, "__path__"), package)

    def test_entry_point_targets_are_callable(self):
        self.assertTrue(callable(cli_module.main))
        self.assertTrue(callable(gui_module.main))

    def test_versions_agree(self):
        data = self._pyproject()
        self.assertEqual(data["project"]["version"], easyfig.__version__)
        self.assertEqual(cli_module.__version__, easyfig.__version__)

    def test_dependencies_cover_the_imports(self):
        declared = " ".join(self._pyproject()["project"]["dependencies"]).lower()
        for requirement in ("numpy", "matplotlib", "pandas", "openpyxl"):
            self.assertIn(requirement, declared)

    def test_python_module_entry_point_reports_usage(self):
        """`python -m easyfig` with no subcommand prints help and exits 2."""
        import runpy

        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stdout(io.StringIO()):
                runpy.run_module("easyfig", run_name="__main__", alter_sys=True)
        self.assertEqual(ctx.exception.code, 2)

    def test_root_launchers_still_work(self):
        """`python main.py <subcommand>` must forward to the CLI."""
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main_module.main(["palettes", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(stdout.getvalue())), 10)

    def test_dispatcher_only_forwards_real_subcommands(self):
        from easyfig.cli import build_parser

        parser = build_parser()
        for command in main_module.CLI_SUBCOMMANDS:
            extra = ["-"] if command == "spec" else []
            with self.subTest(command=command):
                args = parser.parse_args([command] + extra)
                self.assertEqual(args.command, command)


# ---------------------------------------------------------------------------
# compose (multi-panel figures)
# ---------------------------------------------------------------------------

def compose_datasets(count):
    """``{"A": {...}}`` style data with one series per name."""
    names = [chr(ord("A") + index) for index in range(count)]
    return {
        name: {"sizes": [1, 2, 3],
               "data": [[1.0 + index, 1.2 + index],
                        [2.0 + index, 2.1 + index],
                        [3.0 + index, 2.9 + index]],
               "color": "#4E74B3"}
        for index, name in enumerate(names)
    }


class TestComposeLayout(unittest.TestCase):
    """Grid resolution, placement, markers and diagrams."""

    def setUp(self):
        from easyfig import compose

        self.compose = compose

    def test_auto_grid_prefers_compact_landscape_shapes(self):
        expected = {
            1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (2, 2), 5: (2, 3),
            6: (2, 3), 7: (2, 4), 8: (2, 4), 9: (3, 3), 10: (2, 5),
            11: (3, 4), 12: (3, 4),
        }
        for count, shape in expected.items():
            with self.subTest(count=count):
                self.assertEqual(self.compose.auto_grid(count), shape)

    def test_auto_grid_never_leaves_a_hole_it_could_avoid(self):
        for count in range(1, 13):
            rows, cols = self.compose.auto_grid(count)
            with self.subTest(count=count):
                self.assertGreaterEqual(rows * cols, count)
                self.assertGreaterEqual(cols / rows, self.compose.MIN_AUTO_ASPECT)
                self.assertLessEqual(cols / rows, self.compose.MAX_AUTO_ASPECT)

    def test_panel_labels_continue_after_z(self):
        self.assertEqual(self.compose.panel_label(0), "a")
        self.assertEqual(self.compose.panel_label(25), "z")
        self.assertEqual(self.compose.panel_label(26), "aa")
        self.assertEqual(self.compose.panel_label(27), "ab")

    def test_panel_label_styles(self):
        self.assertEqual(self.compose.panel_label(1, "abc"), "b")
        self.assertEqual(self.compose.panel_label(1, "paren"), "(b)")
        self.assertEqual(self.compose.panel_label(1, "ABC"), "B")
        self.assertEqual(self.compose.panel_label(1, "dot"), "b.")

    def test_place_panels_flows_in_reading_order(self):
        specs = [{"rowspan": 1, "colspan": 1, "row": None, "col": None}
                 for _ in range(4)]
        placements = self.compose.place_panels(2, 2, specs)
        self.assertEqual(placements, [(0, 0, 1, 1), (0, 1, 1, 1),
                                      (1, 0, 1, 1), (1, 1, 1, 1)])

    def test_place_panels_respects_explicit_positions_first(self):
        specs = [
            {"rowspan": 1, "colspan": 1, "row": None, "col": None},
            {"rowspan": 1, "colspan": 1, "row": None, "col": None},
            {"rowspan": 2, "colspan": 1, "row": 0, "col": 1},
        ]
        placements = self.compose.place_panels(2, 2, specs)
        self.assertEqual(placements[2], (0, 1, 2, 1))
        self.assertEqual(placements[0], (0, 0, 1, 1))
        self.assertEqual(placements[1], (1, 0, 1, 1))

    def test_place_panels_reports_a_grid_that_is_too_small(self):
        specs = [{"rowspan": 1, "colspan": 1, "row": None, "col": None}
                 for _ in range(5)]
        with self.assertRaises(ValueError) as caught:
            self.compose.place_panels(2, 2, specs)
        self.assertIn("放不下", str(caught.exception))

    def test_diagram_merges_spanned_cells(self):
        specs = [
            {"rowspan": 2, "colspan": 1, "row": None, "col": None},
            {"rowspan": 1, "colspan": 1, "row": None, "col": None},
            {"rowspan": 1, "colspan": 1, "row": None, "col": None},
        ]
        placements = self.compose.place_panels(2, 2, specs)
        lines = self.compose.layout_diagram(2, 2, placements,
                                            ["a", "b", "c"]).splitlines()
        # The left panel spans both rows, so no separator crosses it.
        self.assertEqual(lines[0][0], "┌")
        self.assertEqual(lines[0][-1], "┐")
        self.assertTrue(lines[0].startswith("┌───────"), lines[0])
        self.assertIn("a", "\n".join(lines))
        self.assertIn("b", "\n".join(lines))

    def test_diagram_marks_empty_slots(self):
        placements = self.compose.place_panels(2, 2, [
            {"rowspan": 1, "colspan": 1, "row": None, "col": None}])
        diagram = self.compose.layout_diagram(2, 2, placements, ["a"])
        self.assertIn("·", diagram)

    def test_every_preset_renders_its_own_diagram(self):
        for key in self.compose.PRESET_ORDER:
            preset = self.compose.describe_preset(key)
            with self.subTest(preset=key):
                self.assertTrue(preset["diagram"].strip())
                self.assertEqual(len(preset["spans"]), preset["panels"])
                self.assertGreaterEqual(preset["panels"], 1)
                self.assertIn("label", preset)

    def test_presets_grow_rows_for_extra_panels(self):
        """A preset designed for 3 panels must still work with 7."""
        datasets = compose_datasets(7)
        panels = [{"datasets": [name]} for name in datasets]
        layout = self.compose.plan_layout(datasets, panels,
                                          {"layout_preset": "big-left-2"})
        self.assertEqual(layout["panelCount"], 7)
        self.assertGreaterEqual(layout["rows"], 2)
        self.assertEqual(layout["panels"][0]["rowspan"], 2)
        self.assertEqual({panel["label"] for panel in layout["panels"]},
                         set("abcdefg"))

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            self.compose.make_compose_settings({"layout_preset": "nope"})
        self.assertIn("unknown layout preset", str(caught.exception))

    def test_unknown_compose_setting_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            self.compose.make_compose_settings({"colour": "red"})
        self.assertIn("unknown compose setting", str(caught.exception))

    def test_compose_settings_do_not_share_list_defaults(self):
        """Mutable defaults must be copied, not aliased between calls."""
        first = self.compose.make_compose_settings()
        first["row_heights"].append(9.0)
        second = self.compose.make_compose_settings()
        self.assertEqual(second["row_heights"], [])

    def test_ratio_lists_are_validated(self):
        with self.assertRaises(ValueError):
            self.compose.make_compose_settings({"col_widths": [1.0, 0.0]})
        self.assertEqual(self.compose.make_compose_settings(
            {"col_widths": "2, 1"})["col_widths"], [2.0, 1.0])


class TestComposePanels(unittest.TestCase):
    """Panel validation and the resolved per-panel settings."""

    def setUp(self):
        from easyfig import compose

        self.compose = compose

    def test_normalize_panels_rejects_an_unknown_dataset(self):
        with self.assertRaises(ValueError) as caught:
            self.compose.normalize_panels([{"datasets": ["ghost"]}], ["A"])
        self.assertIn("不存在的数据集", str(caught.exception))

    def test_normalize_panels_rejects_an_empty_group(self):
        with self.assertRaises(ValueError):
            self.compose.normalize_panels([{"datasets": []}], ["A"])

    def test_normalize_panels_rejects_an_unknown_panel_key(self):
        with self.assertRaises(ValueError) as caught:
            self.compose.normalize_panels(
                [{"datasets": ["A"], "spann": 2}], ["A"])
        self.assertIn("未知键", str(caught.exception))

    def test_normalize_panels_rejects_a_bad_span(self):
        with self.assertRaises(ValueError):
            self.compose.normalize_panels(
                [{"datasets": ["A"], "colspan": 0}], ["A"])

    def test_normalize_panels_rejects_half_a_position(self):
        with self.assertRaises(ValueError):
            self.compose.normalize_panels(
                [{"datasets": ["A"], "row": 1}], ["A"])

    def test_panel_settings_never_break_inside_a_cell(self):
        options = self.compose.make_compose_settings()
        spec = {"names": ["A"], "settings": {"use_broken_y_axis": True,
                                             "legend_loc": "outside right"}}
        settings = self.compose._panel_settings(
            chart_builder.make_settings({}), options, spec)
        self.assertFalse(settings["use_broken_y_axis"])
        self.assertFalse(settings["use_broken_x_axis"])
        self.assertEqual(settings["legend_loc"], "upper right")

    def test_panel_title_defaults_to_the_dataset_name(self):
        options = self.compose.make_compose_settings()
        settings = self.compose._panel_settings(
            chart_builder.make_settings({}), options,
            {"names": ["A", "B"], "settings": {}})
        self.assertEqual(settings["title"], "A / B")

    def test_panel_title_can_be_switched_off_or_overridden(self):
        options = self.compose.make_compose_settings({"show_panel_titles": False})
        settings = self.compose._panel_settings(
            chart_builder.make_settings({}), options,
            {"names": ["A"], "settings": {}})
        self.assertEqual(settings["title"], "")

        options = self.compose.make_compose_settings()
        settings = self.compose._panel_settings(
            chart_builder.make_settings({}), options,
            {"names": ["A"], "settings": {"title": "自定义"}})
        self.assertEqual(settings["title"], "自定义")

    def test_unified_font_sizes_override_the_panel(self):
        options = self.compose.make_compose_settings({"tick_label_size": 7})
        settings = self.compose._panel_settings(
            chart_builder.make_settings({"tick_label_size": 22}), options,
            {"names": ["A"], "settings": {}})
        self.assertEqual(settings["tick_label_size"], 7)

    def test_panel_sizes_are_left_alone_when_unification_is_off(self):
        options = self.compose.make_compose_settings({"unify_font_sizes": False})
        settings = self.compose._panel_settings(
            chart_builder.make_settings({"tick_label_size": 22}), options,
            {"names": ["A"], "settings": {}})
        self.assertEqual(settings["tick_label_size"], 22)

    def test_a_panel_chart_type_brings_its_series_rule_along(self):
        """A scatter panel must not draw a connecting line."""
        options = self.compose.make_compose_settings()
        settings = self.compose._panel_settings(
            chart_builder.make_settings({"chart_type": "line"}), options,
            {"names": ["A"], "settings": {"chart_type": "scatter"}})
        self.assertFalse(settings["show_connecting_line"])


class TestComposeRendering(TempDirMixin, unittest.TestCase):
    """Real figures: panel count, markers, fonts and export."""

    def setUp(self):
        super().setUp()
        from easyfig import compose

        self.compose = compose
        self.datasets = compose_datasets(7)

    def panels_for(self, count, **extra):
        panels = [{"datasets": [chr(ord("A") + index)]} for index in range(count)]
        if extra:
            panels[0].update(extra)
        return panels

    def test_seven_panels_land_on_a_two_by_four_grid(self):
        layout = self.compose.plan_layout(self.datasets, self.panels_for(7))
        self.assertEqual((layout["rows"], layout["cols"]), (2, 4))
        self.assertEqual(len(layout["panels"]), 7)
        self.assertEqual([panel["label"] for panel in layout["panels"]],
                         list("abcdefg"))

    def test_a_figure_has_one_axes_per_panel(self):
        fig = self.compose.compose_figure(self.datasets, self.panels_for(7))
        self.assertEqual(len(fig.axes), 7)

    def test_panel_markers_are_drawn(self):
        fig = self.compose.compose_figure(
            self.datasets, self.panels_for(3),
            compose={"layout_preset": "1x3", "label_style": "paren"})
        texts = [text.get_text() for ax in fig.axes for text in ax.texts]
        self.assertEqual(sorted(texts), ["(a)", "(b)", "(c)"])

    def test_markers_can_be_switched_off(self):
        fig = self.compose.compose_figure(
            self.datasets, self.panels_for(3),
            compose={"layout_preset": "1x3", "label_show": False})
        texts = [text.get_text() for ax in fig.axes for text in ax.texts]
        self.assertEqual(texts, [])

    def test_several_datasets_can_share_one_panel(self):
        panels = [{"datasets": ["A", "B", "C"]}, {"datasets": ["D"]},
                  {"datasets": ["E"]}, {"datasets": ["F"]}, {"datasets": ["G"]}]
        fig, layout = self.compose.compose_figure_data(self.datasets, panels,
                                                       compose={"layout_mode": "auto"})
        self.assertEqual(len(fig.axes), 5)
        self.assertEqual(layout["panels"][0]["datasets"], ["A", "B", "C"])

    def test_a_panel_can_span_rows_and_columns(self):
        panels = [
            {"datasets": ["A"], "colspan": 2, "rowspan": 2},
            {"datasets": ["B"]}, {"datasets": ["C"]},
        ]
        layout = self.compose.plan_layout(
            self.datasets, panels,
            {"layout_mode": "manual", "grid_rows": 2, "grid_cols": 3})
        self.assertEqual(layout["panels"][0]["rowspan"], 2)
        self.assertEqual(layout["panels"][0]["colspan"], 2)

    def test_unified_font_family_reaches_every_text(self):
        fig = self.compose.compose_figure(
            self.datasets, self.panels_for(3),
            compose={"layout_preset": "1x3",
                     "font_family": "Times New Roman"})
        families = set()
        for ax in fig.axes:
            families.add(ax.title.get_fontfamily()[0])
            families.add(ax.xaxis.label.get_fontfamily()[0])
            for label in ax.get_xticklabels() + ax.get_yticklabels():
                families.add(label.get_fontfamily()[0])
        self.assertEqual(families, {"Times New Roman"})

    def test_font_family_is_left_to_the_renderer_by_default(self):
        fig = self.compose.compose_figure(self.datasets, self.panels_for(2))
        self.assertEqual(self.compose.unify_fonts(fig, {"font_family": ""}), 0)

    def test_margins_leave_room_for_the_markers(self):
        """A short canvas must not clip the panel titles or the a/b markers."""
        options = self.compose.make_compose_settings()
        margins = self.compose.effective_margins(options, (6.0, 2.8))
        self.assertGreaterEqual(1.0 - margins["margin_top"], 0.10)
        self.assertGreaterEqual(margins["margin_left"], 0.06)
        self.assertGreater(margins["margin_bottom"], 0.05)

    def test_gaps_grow_with_the_font_sizes(self):
        small = self.compose.make_compose_settings()
        large = self.compose.make_compose_settings({
            "tick_label_size": 18, "axis_label_font_size": 20,
            "title_font_size": 22})
        _, small_y = self.compose.effective_gaps(small, (6.0, 2.8), 1, 2)
        _, large_y = self.compose.effective_gaps(large, (6.0, 2.8), 1, 2)
        self.assertGreater(large_y, small_y)

    def test_the_whole_figure_title_gets_its_own_room(self):
        reserve, y = self.compose.suptitle_placement(
            self.compose.make_compose_settings({"suptitle": "组合图"}), (6.0, 2.8))
        self.assertGreater(reserve, 0.0)
        self.assertIsNotNone(y)

        reserve, y = self.compose.suptitle_placement(
            self.compose.make_compose_settings(), (6.0, 2.8))
        self.assertEqual(reserve, 0.0)
        self.assertIsNone(y)

    def test_fit_processing_applies_to_every_panel(self):
        fig = self.compose.compose_figure(
            self.datasets, self.panels_for(2),
            compose={"layout_preset": "1x2"},
            fit={"method": "linear", "degree": 2, "showRaw": True,
                 "showFit": True, "addJitter": False})
        self.assertEqual(len(fig.axes), 2)

    def test_compose_export_writes_a_file(self):
        from easyfig.chart_builder import export_figure

        fig, layout = self.compose.compose_figure_data(
            self.datasets, self.panels_for(4),
            compose={"layout_preset": "big-top-3"})
        out = self.path("figure.png")
        export_figure(fig, out, width=layout["figureWidth"],
                      height=layout["figureHeight"], dpi=80, tight=True)
        self.assertTrue(os.path.getsize(out) > 0)

    def test_a_panel_with_unplottable_data_is_reported(self):
        datasets = dict(self.datasets)
        datasets["broken"] = {"sizes": [1, 2], "data": [[], [1.0]],
                              "color": "#000000"}
        with self.assertRaises(ValueError) as caught:
            self.compose.compose_figure(datasets, [{"datasets": ["broken"]}])
        self.assertIn("没有可绘制的数据", str(caught.exception))


class TestComposeSpec(TempDirMixin, unittest.TestCase):
    """Spec files, panel grouping strings and the schema dump."""

    def setUp(self):
        super().setUp()
        from easyfig import compose

        self.compose = compose

    def write_spec(self, payload, name="figure.json"):
        path = self.path(name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        return path

    def test_example_spec_from_the_schema_is_valid(self):
        schema = self.compose.compose_spec_schema()
        path = self.write_spec(schema["example"])
        loaded = self.compose.load_compose_spec(path)
        self.assertEqual(sorted(loaded["datasets"]), ["Sample A", "Sample B",
                                                      "Sample C"])
        self.assertEqual(loaded["compose"]["layout_preset"], "big-left-2")
        fig, layout = self.compose.compose_figure_data(
            loaded["datasets"], loaded["panels"], settings=loaded["settings"],
            compose=loaded["compose"])
        self.assertEqual(layout["panelCount"], 3)
        self.assertEqual(len(fig.axes), 3)

    def test_layout_keys_translate_to_compose_settings(self):
        overrides = self.compose.layout_to_compose(
            {"rows": 2, "cols": 3, "col_widths": [2, 1, 1], "gap_y": 0.4,
             "margins": [0.1, 0.9, 0.2, 0.9]})
        self.assertEqual(overrides["grid_rows"], 2)
        self.assertEqual(overrides["grid_cols"], 3)
        self.assertEqual(overrides["col_widths"], [2, 1, 1])
        self.assertEqual(overrides["gap_y"], 0.4)
        self.assertEqual(overrides["margin_left"], 0.1)
        self.assertEqual(overrides["margin_top"], 0.9)
        self.assertEqual(overrides["layout_mode"], "manual")

    def test_unknown_layout_key_is_rejected(self):
        with self.assertRaises(ValueError):
            self.compose.layout_to_compose({"column": 2})

    def test_margins_need_four_values(self):
        with self.assertRaises(ValueError):
            self.compose.layout_to_compose({"margins": [0.1, 0.9]})

    def test_unknown_spec_key_is_rejected(self):
        path = self.write_spec({"datasets": [{"name": "A", "sizes": [1],
                                              "data": [[1.0]]}],
                                "layouts": {}})
        with self.assertRaises(ValueError) as caught:
            self.compose.load_compose_spec(path)
        self.assertIn("unknown spec key", str(caught.exception))

    def test_a_spec_without_datasets_is_rejected(self):
        path = self.write_spec({"panels": []})
        with self.assertRaises(ValueError):
            self.compose.load_compose_spec(path)

    def test_panels_default_to_one_per_dataset(self):
        path = self.write_spec({"datasets": [
            {"name": "A", "sizes": [1, 2], "data": [[1.0], [2.0]]},
            {"name": "B", "sizes": [1, 2], "data": [[3.0], [4.0]]},
        ]})
        loaded = self.compose.load_compose_spec(path)
        self.assertEqual(loaded["panels"],
                         [{"datasets": ["A"]}, {"datasets": ["B"]}])

    def test_broken_json_is_reported_with_its_path(self):
        path = self.path("bad.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(ValueError) as caught:
            self.compose.load_compose_spec(path)
        self.assertIn("not valid JSON", str(caught.exception))

    def test_panel_groups_parse_names_indices_and_star(self):
        names = ["A", "B", "C", "D"]
        self.assertEqual(self.compose.parse_panel_groups("1;2;C", names),
                         [{"datasets": ["A"]}, {"datasets": ["B"]},
                          {"datasets": ["C"]}])
        # Inside a group "*" means "and every dataset no group has taken yet".
        self.assertEqual(self.compose.parse_panel_groups("A,B;C,*", names),
                         [{"datasets": ["A", "B"]}, {"datasets": ["C", "D"]}])
        # A group that is only "*" takes everything left.
        self.assertEqual(self.compose.parse_panel_groups("A;*", names),
                         [{"datasets": ["A"]},
                          {"datasets": ["B", "C", "D"]}])

    def test_panel_groups_report_an_unknown_name(self):
        with self.assertRaises(ValueError) as caught:
            self.compose.parse_panel_groups("A;ghost", ["A"])
        self.assertIn("未知数据集", str(caught.exception))

    def test_panel_groups_report_an_out_of_range_index(self):
        with self.assertRaises(ValueError):
            self.compose.parse_panel_groups("9", ["A"])

    def test_schema_lists_every_preset_and_option(self):
        schema = self.compose.compose_spec_schema()
        self.assertEqual([preset["key"] for preset in schema["presets"]],
                         list(PRESET_ORDER))
        self.assertEqual(schema["layoutPresetKeys"], list(PRESET_ORDER))
        self.assertEqual(schema["labelStyles"], ["abc", "paren", "ABC", "dot"])
        self.assertIn("compose", schema["keys"])
        self.assertIn("panels", schema["keys"])

    def test_interface_schema_exposes_the_compose_controls(self):
        schema = self.compose.compose_schema()
        self.assertEqual(schema["composeDefaults"],
                         dict(COMPOSE_DEFAULT_SETTINGS))
        self.assertEqual(set(schema["composeSettingKeys"]),
                         set(COMPOSE_DEFAULT_SETTINGS))
        self.assertEqual(len(schema["layoutPresets"]), len(PRESET_ORDER))
        self.assertTrue(all("installed" in entry
                            for entry in schema["fontFamilies"]))


class TestComposeCli(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from easyfig import cli

        self.cli = cli

    def run_cli(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.cli.main(argv)
        return code, stdout.getvalue()

    def _table_csv(self, name="table.csv"):
        path = self.path(name)
        pd.DataFrame({
            "Size": [1, 2, 3, 4, 5],
            "A": [1.0, 1.4, 1.8, 2.2, 2.6],
            "B": [2.1, 2.5, 2.9, 3.3, 3.7],
            "C": [3.3, 3.6, 3.9, 4.2, 4.5],
        }).to_csv(path, index=False)
        return path

    def test_layouts_lists_every_preset_with_a_diagram(self):
        code, output = self.run_cli(["layouts"])
        self.assertEqual(code, 0)
        for key in PRESET_ORDER:
            self.assertIn(key, output)
        self.assertIn("┌", output)

    def test_layouts_json_is_machine_readable(self):
        code, output = self.run_cli(["layouts", "--json"])
        self.assertEqual(code, 0)
        presets = json.loads(output)
        self.assertEqual([preset["key"] for preset in presets],
                         list(PRESET_ORDER))
        self.assertTrue(all(preset["diagram"] for preset in presets))

    def test_layouts_details_one_preset(self):
        code, output = self.run_cli(["layouts", "big-left-2"])
        self.assertEqual(code, 0)
        self.assertIn("big-left-2", output)
        self.assertIn("左大", output)
        self.assertIn('"preset": "big-left-2"', output)

    def test_layouts_rejects_an_unknown_preset(self):
        code, _ = self.run_cli(["layouts", "nope"])
        self.assertEqual(code, 1)

    def test_compose_schema_is_printed(self):
        code, output = self.run_cli(["compose", "--schema"])
        self.assertEqual(code, 0)
        schema = json.loads(output)
        self.assertIn("example", schema)
        self.assertIn("presets", schema)

    def test_compose_print_layout_does_not_write_a_file(self):
        code, output = self.run_cli([
            "compose", "--table", self._table_csv(), "--time-column", "Size",
            "--layout", "big-left-2", "--print-layout"])
        self.assertEqual(code, 0)
        self.assertIn("网格", output)
        self.assertIn("第1行 第1列", output)
        self.assertIn("┌", output)

    def test_compose_renders_a_multi_panel_figure(self):
        out = self.path("figure.png")
        code, _ = self.run_cli([
            "compose", "--table", self._table_csv(), "--time-column", "Size",
            "--layout", "1x3", "--font-family", "Times New Roman",
            "-o", out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.getsize(out) > 0)

    def test_compose_json_out_describes_the_layout(self):
        out = self.path("figure.png")
        code, output = self.run_cli([
            "compose", "--table", self._table_csv(), "--time-column", "Size",
            "--layout", "1x3", "--panels", "A;B;C", "--json-out", "-o", out])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["rows"], 1)
        self.assertEqual(payload["cols"], 3)
        self.assertEqual(payload["panel_count"], 3)
        self.assertEqual(payload["labels"], ["a", "b", "c"])

    def test_compose_accepts_a_spec_file(self):
        spec = self.path("figure.json")
        with open(spec, "w", encoding="utf-8") as handle:
            json.dump(compose_engine.compose_spec_schema()["example"], handle,
                      ensure_ascii=False)
        out = self.path("from-spec.png")
        code, _ = self.run_cli(["compose", "--spec", spec, "-o", out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.getsize(out) > 0)

    def test_compose_reports_a_grid_that_is_too_small(self):
        code, _ = self.run_cli([
            "compose", "--table", self._table_csv(), "--time-column", "Size",
            "--rows", "1", "--cols", "1",
            "-o", self.path("nope.png")])
        self.assertEqual(code, 1)

    def test_compose_reports_a_bad_preset(self):
        code, _ = self.run_cli([
            "compose", "--table", self._table_csv(), "--layout", "wat",
            "-o", self.path("nope.png")])
        self.assertEqual(code, 1)

    def test_compose_needs_something_to_do(self):
        code, _ = self.run_cli([
            "compose", "--table", self._table_csv(), "--time-column", "Size"])
        self.assertEqual(code, 1)


class TestComposeBridge(unittest.TestCase):
    """The compose commands the Electron interface calls."""

    def setUp(self):
        from easyfig import bridge

        self.bridge = bridge

    def call(self, cmd, **payload):
        response = self.bridge.handle_request({"id": 1, "cmd": cmd, **payload})
        self.assertTrue(response["ok"], response.get("error"))
        return response["result"]

    def fails(self, cmd, **payload):
        response = self.bridge.handle_request({"id": 1, "cmd": cmd, **payload})
        self.assertFalse(response["ok"])
        return response["error"]

    @staticmethod
    def wire_datasets(count=7):
        return [
            {"name": chr(ord("A") + index), "sizes": [1, 2, 3],
             "data": [[1.0 + index], [2.0 + index], [3.0 + index]],
             "color": "#4E74B3"}
            for index in range(count)
        ]

    def test_schema_carries_the_compose_controls(self):
        schema = self.call("hello")
        self.assertIn("compose", schema)
        self.assertEqual(schema["compose"]["composeDefaults"],
                         dict(COMPOSE_DEFAULT_SETTINGS))
        self.assertEqual(len(schema["compose"]["layoutPresets"]),
                         len(PRESET_ORDER))

    def test_compose_returns_a_png_and_the_layout(self):
        result = self.call("compose", datasets=self.wire_datasets(7),
                           compose={"layout_mode": "auto"}, dpi=80)
        self.assertTrue(result["png"])
        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["cols"], 4)
        self.assertEqual(result["panelCount"], 7)
        self.assertEqual([panel["label"] for panel in result["panels"]],
                         list("abcdefg"))
        self.assertIn("┌", result["diagram"])
        self.assertTrue(result["statistics"])

    def test_compose_defaults_to_one_panel_per_dataset(self):
        result = self.call("compose", datasets=self.wire_datasets(3), dpi=80)
        self.assertEqual(result["panelCount"], 3)

    def test_compose_honours_panel_grouping(self):
        result = self.call("compose", datasets=self.wire_datasets(3),
                           panels=[{"datasets": ["A", "B"]},
                                   {"datasets": ["C"]}], dpi=80)
        self.assertEqual(result["panelCount"], 2)
        self.assertEqual(result["panels"][0]["datasets"], ["A", "B"])

    def test_compose_reports_an_empty_panel_list(self):
        error = self.fails("compose", datasets=self.wire_datasets(2), panels=[])
        self.assertEqual(error["kind"], "bad-layout")

    def test_compose_reports_a_grid_that_is_too_small(self):
        error = self.fails("compose", datasets=self.wire_datasets(4),
                           compose={"layout_mode": "manual", "grid_rows": 1,
                                    "grid_cols": 1})
        self.assertEqual(error["kind"], "bad-layout")
        self.assertIn("放不下", error["message"])

    def test_compose_reports_unknown_settings(self):
        error = self.fails("compose", datasets=self.wire_datasets(2),
                           compose={"nope": 1})
        self.assertEqual(error["kind"], "bad-settings")

    def test_compose_reports_an_unknown_dataset(self):
        error = self.fails("compose", datasets=self.wire_datasets(2),
                           panels=[{"datasets": ["ghost"]}])
        self.assertEqual(error["kind"], "bad-layout")

    def test_compose_needs_data(self):
        error = self.fails("compose", datasets=[], compose={})
        self.assertEqual(error["kind"], "no-data")

    def test_export_compose_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "figure.png")
            result = self.call("export_compose", path=out,
                               datasets=self.wire_datasets(4),
                               compose={"layout_preset": "big-top-3"},
                               dpi=80)
            self.assertTrue(os.path.getsize(out) > 0)
            self.assertEqual(result["panelCount"], 4)
            self.assertEqual(result["bytes"], os.path.getsize(out))

    def test_export_compose_rejects_an_unknown_extension(self):
        error = self.fails("export_compose", path="figure.bmp",
                           datasets=self.wire_datasets(2))
        self.assertEqual(error["kind"], "bad-request")

    def test_export_compose_requires_a_path(self):
        error = self.fails("export_compose", datasets=self.wire_datasets(2))
        self.assertEqual(error["kind"], "bad-request")

    def test_compose_preview_is_capped_in_pixels(self):
        """A big grid must not stall the interface with a huge preview."""
        result = self.call("compose", datasets=self.wire_datasets(7),
                           compose={"panel_width": 12.0, "panel_height": 12.0},
                           dpi=300)
        self.assertLessEqual(max(result["pixelWidth"], result["pixelHeight"]),
                             self.bridge.MAX_PREVIEW_PIXELS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
