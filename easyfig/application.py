"""
Main application - ALL ISSUES FIXED
"""
# FORCE ENGLISH LOCALE BEFORE ANY IMPORTS
import os
import sys
import locale

# Set English locale globally
os.environ['LANG'] = 'C'
os.environ['LC_ALL'] = 'C'
os.environ['LANGUAGE'] = 'en_US:en'
try:
    locale.setlocale(locale.LC_ALL, 'C')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except:
        pass

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.backend_bases import NavigationToolbar2
import numpy as np

from .config import *  # noqa: F401,F403  (constants + colour tables used below)
from .config import AVAILABLE_COLORS, PALETTE_ORDER
from .data_processor import (
    load_table_dataframe,
    parse_data_input,
    prepare_chart_data,
    process_multiline_excel,
    validate_dataset,
)
from .chart_manager import ChartManager
from .custom_color_dialog import askcolor  # Use custom English colour picker
from .palettes import palette_colors, palette_label, palette_series_label
# Option tables and the canonical settings live in chart_builder so the GUI and
# the command line interface always agree on names and defaults.
from .chart_builder import (
    BAR_STYLE_OPTIONS,
    DEFAULT_SETTINGS,
    ERRORBAR_METRIC_OPTIONS,
    ERRORBAR_MODE_OPTIONS,
    EXPORT_MODE_OPTIONS,
    FIT_METHOD_OPTIONS,
    LABEL_CONTENT_OPTIONS,
    LEGEND_LOC_OPTIONS,
    VISUAL_PRESET_OPTIONS,
    apply_processing,
    export_figure,
    get_option_label,
    get_option_labels,
    make_settings,
    normalize_option_value,
)

CM_TO_IN = 1 / 2.54
IN_TO_CM = 2.54


class DataAnalysisGUI:
    
    def __init__(self, root):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_GEOMETRY)
        
        self.datasets = {}
        
        self.chart_title = DEFAULT_CHART_TITLE
        self.xlabel = DEFAULT_XLABEL
        self.ylabel = DEFAULT_YLABEL
        self.x_unit = ""
        self.y_unit = ""
        self.line_color = DEFAULT_LINE_COLOR
        # Global colors for bar charts and error bars
        self.bar_color = DEFAULT_BAR_COLOR
        self.errorbar_color = DEFAULT_ERRORBAR_COLOR
        
        self.available_colors = AVAILABLE_COLORS
        
        self.create_widgets()
        
    def create_widgets(self):
        main_container = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        left_panel = ttk.Frame(main_container)
        main_container.add(left_panel, weight=1)
        
        right_panel = ttk.Frame(main_container)
        main_container.add(right_panel, weight=2)

        left_scrollbar = ttk.Scrollbar(left_panel, orient=tk.VERTICAL)
        left_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        left_canvas = tk.Canvas(left_panel, highlightthickness=0)
        left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left_scrollbar.configure(command=left_canvas.yview)

        left_controls = ttk.Frame(left_canvas)
        left_window = left_canvas.create_window((0, 0), window=left_controls, anchor="nw")

        def _update_left_scrollregion(event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))

        def _resize_left_controls(event):
            left_canvas.itemconfigure(left_window, width=event.width)

        def _on_left_mousewheel(event):
            left_canvas.yview_scroll(int(-event.delta / 120), "units")

        def _bind_left_mousewheel(event=None):
            left_canvas.bind_all("<MouseWheel>", _on_left_mousewheel)

        def _unbind_left_mousewheel(event=None):
            left_canvas.unbind_all("<MouseWheel>")

        left_controls.bind("<Configure>", _update_left_scrollregion)
        left_canvas.bind("<Configure>", _resize_left_controls)
        left_canvas.bind("<Enter>", _bind_left_mousewheel)
        left_canvas.bind("<Leave>", _unbind_left_mousewheel)
        
        # 优先显示“Step 1 • Datasets”，保持从上到下的顺序
        self._create_dataset_management(left_controls)
        self._create_chart_settings(left_controls)
        
        self._create_chart_display(right_panel)
        self._create_stats_panel(right_panel)
        
        self.status_bar = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def _create_chart_settings(self, parent):
        chart_frame = ttk.LabelFrame(parent, text="Step 2 • Plot Method", padding="10")
        chart_frame.pack(fill=tk.X, padx=5, pady=5)
        chart_frame.columnconfigure(1, weight=1)
        
        # Use a dictionary to track current row for grid layout
        layout_state = {'row': 0}
        
        self._create_axis_labels_section(chart_frame, layout_state)
        self._create_plot_method_section(chart_frame, layout_state)
        self._create_line_style_section(chart_frame, layout_state)
        self._create_stats_display_section(chart_frame, layout_state)
        self._create_error_bar_section(chart_frame, layout_state)
        self._create_marker_section(chart_frame, layout_state)
        self._create_axis_ticks_section(chart_frame, layout_state)
        self._create_export_section(chart_frame, layout_state)
        
        # Initial UI state update
        self._on_plot_method_change()
        
    def _create_axis_labels_section(self, parent, state):
        row = state['row']
        ttk.Label(parent, text="Chart Title:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.title_entry = ttk.Entry(parent, width=35)
        self.title_entry.insert(0, getattr(self, 'chart_title', ''))
        self.title_entry.grid(row=row, column=1, columnspan=2, sticky=tk.EW, pady=2, padx=(5, 0))
        row += 1
        
        ttk.Label(parent, text="X-Axis:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.xlabel_entry = ttk.Entry(parent, width=20)
        self.xlabel_entry.insert(0, getattr(self, 'xlabel', ''))
        self.xlabel_entry.grid(row=row, column=1, sticky=tk.W, pady=2, padx=(5, 0))
        self.x_unit_combo = ttk.Combobox(parent, width=8, values=X_AXIS_UNITS)
        self.x_unit_combo.set('(none)')
        self.x_unit_combo.grid(row=row, column=2, sticky=tk.W, pady=2, padx=(5, 0))
        row += 1
        
        ttk.Label(parent, text="Y-Axis:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.ylabel_entry = ttk.Entry(parent, width=20)
        self.ylabel_entry.insert(0, getattr(self, 'ylabel', ''))
        self.ylabel_entry.grid(row=row, column=1, sticky=tk.W, pady=2, padx=(5, 0))
        self.y_unit_combo = ttk.Combobox(parent, width=8, values=Y_AXIS_UNITS)
        self.y_unit_combo.set('(none)')
        self.y_unit_combo.grid(row=row, column=2, sticky=tk.W, pady=2, padx=(5, 0))
        row += 1
        
        ttk.Separator(parent, orient='horizontal').grid(row=row, column=0, columnspan=3, sticky=tk.EW, pady=8)
        state['row'] = row + 1

    def _create_plot_method_section(self, parent, state):
        row = state['row']
        plot_method_frame = ttk.LabelFrame(parent, text="Chart Type • Processing", padding="5")
        plot_method_frame.grid(row=row, column=0, columnspan=3, sticky=tk.EW, pady=5)
        
        # X-Axis Mode
        ttk.Label(plot_method_frame, text="X-Axis:").pack(side=tk.LEFT, padx=5)
        self.xaxis_mode = tk.StringVar(value="categorical")
        mode_frame = ttk.Frame(plot_method_frame)
        mode_frame.pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="Numeric", variable=self.xaxis_mode, 
                       value="numeric", command=self._on_plot_method_change).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="Categorical", variable=self.xaxis_mode, 
                       value="categorical", command=self._on_plot_method_change).pack(side=tk.LEFT, padx=5)
        
        # Display Mode
        ttk.Label(plot_method_frame, text="Display:").pack(side=tk.LEFT, padx=(15, 5))
        self.chart_type_var = tk.StringVar(value="line")
        chart_type_frame = ttk.Frame(plot_method_frame)
        chart_type_frame.pack(side=tk.LEFT, padx=5)
        for text, val in [("Line", "line"), ("Scatter", "scatter"), ("Line/Scatter", "line_scatter"), 
                          ("Pie", "pie"), ("Error Bar", "errorbar"), ("Bar", "bar")]:
            ttk.Radiobutton(chart_type_frame, text=text, variable=self.chart_type_var, 
                           value=val, command=self._on_plot_method_change).pack(side=tk.LEFT, padx=2)
        
        # Fitting frame (optional processing)
        self.fitting_frame = ttk.Frame(plot_method_frame)
        self.fitting_frame.pack(side=tk.LEFT, padx=(15, 5))
        ttk.Label(self.fitting_frame, text="Process:").pack(side=tk.LEFT, padx=5)
        self.fit_method_var = tk.StringVar(value=get_option_label("none", FIT_METHOD_OPTIONS, "None"))
        ttk.Combobox(self.fitting_frame, textvariable=self.fit_method_var, 
                    values=get_option_labels(FIT_METHOD_OPTIONS), 
                    width=16, state="readonly").pack(side=tk.LEFT, padx=5)
        
        self.poly_degree_var = tk.IntVar(value=2)
        self.poly_degree_spin = ttk.Spinbox(self.fitting_frame, from_=1, to=10, increment=1, 
                                            textvariable=self.poly_degree_var, width=5, state="disabled")
        self.poly_degree_spin.pack(side=tk.LEFT, padx=5)
        self.fit_method_var.trace('w', self._on_fit_method_change)
        
        # Fitting display options
        self.show_raw_data_var = tk.BooleanVar(value=True)
        self.show_fit_curve_var = tk.BooleanVar(value=True)
        self.add_jitter_var = tk.BooleanVar(value=False)
        
        fit_display_frame = ttk.Frame(self.fitting_frame)
        fit_display_frame.pack(side=tk.LEFT, padx=(10, 5))
        ttk.Checkbutton(fit_display_frame, text="Raw data", 
                       variable=self.show_raw_data_var,
                       command=self._on_plot_method_change).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(fit_display_frame, text="Fit curve", 
                       variable=self.show_fit_curve_var).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(fit_display_frame, text="Jitter", 
                       variable=self.add_jitter_var).pack(side=tk.LEFT, padx=2)
        
        state['row'] = row + 1

    def _create_line_style_section(self, parent, state):
        row = state['row']
        self.line_frame = ttk.LabelFrame(parent, text="Step 3 • Style", padding="5")
        self.line_frame.grid(row=row, column=0, columnspan=3, sticky=tk.EW, pady=5)
        
        preset_row = ttk.Frame(self.line_frame)
        preset_row.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(preset_row, text="Visual Preset:").pack(side=tk.LEFT, padx=5)
        self.visual_preset_var = tk.StringVar(value=get_option_label("default", VISUAL_PRESET_OPTIONS, "Default"))
        preset_combo = ttk.Combobox(
            preset_row,
            textvariable=self.visual_preset_var,
            values=get_option_labels(VISUAL_PRESET_OPTIONS),
            width=10,
            state="readonly"
        )
        preset_combo.pack(side=tk.LEFT, padx=5)
        preset_combo.bind("<<ComboboxSelected>>", self._on_visual_preset_selected)
        ttk.Label(
            preset_row,
            text="SCI only changes presentation."
        ).pack(side=tk.LEFT, padx=(10, 5))

        # Simplified layout for line style
        style_top = ttk.Frame(self.line_frame)
        style_top.pack(fill=tk.X)
        
        ttk.Label(style_top, text="Color:").pack(side=tk.LEFT, padx=5)
        self.line_color_canvas = tk.Canvas(style_top, width=30, height=20, bg=getattr(self, 'line_color', 'red'), highlightthickness=1)
        self.line_color_canvas.pack(side=tk.LEFT, padx=5)
        ttk.Button(style_top, text="Line Color...", command=self.change_line_color, width=12).pack(side=tk.LEFT)
        
        ttk.Label(style_top, text="Width:").pack(side=tk.LEFT, padx=(15, 5))
        self.line_width_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(style_top, from_=0.5, to=10.0, increment=0.5, textvariable=self.line_width_var, width=5).pack(side=tk.LEFT)
        
        style_bottom = ttk.Frame(self.line_frame)
        style_bottom.pack(fill=tk.X, pady=2)
        
        self.line_style_var = tk.StringVar(value="solid")
        ttk.Label(style_bottom, text="Style:").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(style_bottom, text="Solid", variable=self.line_style_var, value="solid").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(style_bottom, text="Dashed", variable=self.line_style_var, value="dashed").pack(side=tk.LEFT, padx=5)
        
        self.show_connecting_line_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(style_bottom, text="Show line", variable=self.show_connecting_line_var).pack(side=tk.LEFT, padx=10)
        
        self.show_error_bars_line_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(style_bottom, text="Error bars", variable=self.show_error_bars_line_var).pack(side=tk.LEFT, padx=10)
        
        state['row'] = row + 1

    def _create_stats_display_section(self, parent, state):
        row = state['row']
        self.stats_display_frame = ttk.LabelFrame(parent, text="Step 4 • Statistics", padding="5")
        self.stats_display_frame.grid(row=row, column=0, columnspan=3, sticky=tk.EW, pady=5)
        
        self.show_max_var = tk.BooleanVar(value=False)
        self.show_mean_var = tk.BooleanVar(value=True)
        self.show_min_var = tk.BooleanVar(value=False)
        
        for text, var in [("Mean values", self.show_mean_var), ("Maximum", self.show_max_var), ("Minimum", self.show_min_var)]:
            ttk.Checkbutton(self.stats_display_frame, text=text, variable=var).pack(side=tk.LEFT, padx=10)
        
        state['row'] = row + 1

    def _create_error_bar_section(self, parent, state):
        # We reuse the same row as statistics for toggling
        row = state['row'] - 1
        self.error_bar_options_frame = ttk.LabelFrame(parent, text="Step 4 • Error Bar Options", padding="5")
        self.error_bar_options_frame.grid(row=row, column=0, columnspan=3, sticky=tk.EW, pady=5)
        
        # Mode and Metric Row
        mode_row = ttk.Frame(self.error_bar_options_frame)
        mode_row.pack(fill=tk.X, pady=2)
        ttk.Label(mode_row, text="Mode:").pack(side=tk.LEFT, padx=5)
        self.errorbar_mode_var = tk.StringVar(value=get_option_label("summary", ERRORBAR_MODE_OPTIONS, "Summary"))
        ttk.Combobox(
            mode_row,
            textvariable=self.errorbar_mode_var,
            values=get_option_labels(ERRORBAR_MODE_OPTIONS),
            width=10,
            state="readonly"
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(mode_row, text="Metric:").pack(side=tk.LEFT, padx=(15, 5))
        self.errorbar_metric_var = tk.StringVar(value="SD")
        ttk.Combobox(mode_row, textvariable=self.errorbar_metric_var, values=get_option_labels(ERRORBAR_METRIC_OPTIONS), width=6, state="readonly").pack(side=tk.LEFT, padx=5)
        
        # Settings Row
        settings_row = ttk.Frame(self.error_bar_options_frame)
        settings_row.pack(fill=tk.X, pady=2)
        ttk.Label(settings_row, text="Capsize:").pack(side=tk.LEFT, padx=5)
        self.errorbar_capsize_var = tk.IntVar(value=int(DEFAULT_SETTINGS['errorbar_capsize']))
        ttk.Spinbox(settings_row, from_=0, to=20, textvariable=self.errorbar_capsize_var, width=5).pack(side=tk.LEFT, padx=5)

        ttk.Label(settings_row, text="Line Width:").pack(side=tk.LEFT, padx=(15, 5))
        self.errorbar_linewidth_var = tk.DoubleVar(value=float(DEFAULT_SETTINGS['errorbar_linewidth']))
        ttk.Spinbox(settings_row, from_=0.5, to=5.0, increment=0.1, textvariable=self.errorbar_linewidth_var, width=5).pack(side=tk.LEFT, padx=5)

        # Bar style Row (bar charts only)
        self.bar_style_row = ttk.Frame(self.error_bar_options_frame)
        self.bar_style_row.pack(fill=tk.X, pady=2)
        ttk.Label(self.bar_style_row, text="Bar Style:").pack(side=tk.LEFT, padx=5)
        self.bar_style_var = tk.StringVar(value=get_option_label("solid", BAR_STYLE_OPTIONS, "Solid"))
        ttk.Combobox(self.bar_style_row, textvariable=self.bar_style_var, values=get_option_labels(BAR_STYLE_OPTIONS), width=10, state="readonly").pack(side=tk.LEFT, padx=5)

        ttk.Label(self.bar_style_row, text="Edge Width:").pack(side=tk.LEFT, padx=(15, 5))
        self.bar_edge_width_var = tk.DoubleVar(value=float(DEFAULT_SETTINGS['bar_edge_width']))
        ttk.Spinbox(self.bar_style_row, from_=0.0, to=8.0, increment=0.5, textvariable=self.bar_edge_width_var, width=5).pack(side=tk.LEFT, padx=5)

        # Error bar colour Row
        self.errorbar_color_row = ttk.Frame(self.error_bar_options_frame)
        self.errorbar_color_row.pack(fill=tk.X, pady=2)
        ttk.Label(self.errorbar_color_row, text="Error Color:").pack(side=tk.LEFT, padx=5)
        self.errorbar_color_canvas = tk.Canvas(self.errorbar_color_row, width=20, height=15, bg=getattr(self, 'errorbar_color', 'black'), highlightthickness=1)
        self.errorbar_color_canvas.pack(side=tk.LEFT, padx=5)
        ttk.Button(self.errorbar_color_row, text="Error Color...", command=self.change_errorbar_color, width=12).pack(side=tk.LEFT)

        # Bar colour Row (bar charts only)
        self.bar_color_row = ttk.Frame(self.error_bar_options_frame)
        self.bar_color_row.pack(fill=tk.X, pady=2)
        ttk.Label(self.bar_color_row, text="Bar Color:").pack(side=tk.LEFT, padx=5)
        self.bar_color_canvas = tk.Canvas(self.bar_color_row, width=20, height=15, bg=getattr(self, 'bar_color', 'blue'), highlightthickness=1)
        self.bar_color_canvas.pack(side=tk.LEFT, padx=5)
        ttk.Button(self.bar_color_row, text="Bar Color...", command=self.change_bar_color, width=10).pack(side=tk.LEFT)

        # Toggles
        toggle_row = ttk.Frame(self.error_bar_options_frame)
        toggle_row.pack(fill=tk.X, pady=2)
        self.errorbar_show_mean_var = tk.BooleanVar(value=True)
        self.errorbar_show_max_var = tk.BooleanVar(value=False)
        self.errorbar_show_min_var = tk.BooleanVar(value=False)
        self.errorbar_show_error_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toggle_row, text="Mean", variable=self.errorbar_show_mean_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(toggle_row, text="Max", variable=self.errorbar_show_max_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(toggle_row, text="Min", variable=self.errorbar_show_min_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(toggle_row, text="Error Bars", variable=self.errorbar_show_error_var).pack(side=tk.LEFT, padx=5)

        self.error_bar_options_frame.grid_remove() # Default hidden

    def _set_error_bar_rows(self, show_bar_rows, show_color_rows=True):
        """Show/hide the optional rows inside the error bar options frame.

        ``show_bar_rows``   - bar style and bar colour (bar charts only)
        ``show_color_rows`` - the error bar colour row
        """
        rows = (
            (self.bar_style_row, show_bar_rows),
            (self.bar_color_row, show_bar_rows),
            (self.errorbar_color_row, show_color_rows),
        )
        for widget, visible in rows:
            try:
                if visible:
                    if not widget.winfo_manager():
                        widget.pack(fill=tk.X, pady=2)
                else:
                    widget.pack_forget()
            except Exception:
                pass
    def _create_marker_section(self, parent, state):
        row = state['row']
        marker_frame = ttk.LabelFrame(parent, text="Step 5 • Markers & Labels", padding="5")
        marker_frame.grid(row=row, column=0, columnspan=3, sticky=tk.EW, pady=5)
        
        # Marker Row
        m_row = ttk.Frame(marker_frame)
        m_row.pack(fill=tk.X, pady=2)
        ttk.Label(m_row, text="Marker Size:").pack(side=tk.LEFT, padx=5)
        self.marker_size_var = tk.IntVar(value=10)
        ttk.Spinbox(m_row, from_=0, to=30, textvariable=self.marker_size_var, width=5).pack(side=tk.LEFT, padx=5)
        
        # Data Labels Row
        l_row = ttk.Frame(marker_frame)
        l_row.pack(fill=tk.X, pady=2)
        self.show_data_labels_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(l_row, text="Show labels", variable=self.show_data_labels_var).pack(side=tk.LEFT, padx=5)
        ttk.Label(l_row, text="Size:").pack(side=tk.LEFT, padx=5)
        self.font_size_var = tk.IntVar(value=10)
        ttk.Spinbox(l_row, from_=6, to=20, textvariable=self.font_size_var, width=5).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(l_row, text="Label Text:").pack(side=tk.LEFT, padx=(15, 5))
        self.label_content_var = tk.StringVar(value=get_option_label("y", LABEL_CONTENT_OPTIONS, "Y Only"))
        ttk.Combobox(
            l_row,
            textvariable=self.label_content_var,
            values=get_option_labels(LABEL_CONTENT_OPTIONS),
            state="readonly",
            width=8
        ).pack(side=tk.LEFT, padx=5)
        
        # Legend Row 1
        leg_row1 = ttk.Frame(marker_frame)
        leg_row1.pack(fill=tk.X, pady=2)
        self.show_legend_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(leg_row1, text="Legend", variable=self.show_legend_var).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(leg_row1, text="Position:").pack(side=tk.LEFT, padx=(5, 2))
        self.legend_loc_var = tk.StringVar(value="auto")
        ttk.Combobox(leg_row1, textvariable=self.legend_loc_var,
                     values=LEGEND_LOC_OPTIONS, state="readonly", width=11).pack(side=tk.LEFT, padx=2)

        ttk.Label(leg_row1, text="Columns:").pack(side=tk.LEFT, padx=(5, 2))
        self.legend_ncol_var = tk.IntVar(value=1)
        ttk.Spinbox(leg_row1, from_=1, to=10, textvariable=self.legend_ncol_var, width=3).pack(side=tk.LEFT, padx=2)
        
        # Legend Row 2
        leg_row2 = ttk.Frame(marker_frame)
        leg_row2.pack(fill=tk.X, pady=2)
        ttk.Label(leg_row2, text="Font:").pack(side=tk.LEFT, padx=5)
        self.legend_font_size_var = tk.IntVar(value=14)
        ttk.Spinbox(leg_row2, from_=6, to=32, textvariable=self.legend_font_size_var, width=5).pack(side=tk.LEFT, padx=5)
        ttk.Label(leg_row2, text="Marker:").pack(side=tk.LEFT, padx=(10, 5))
        self.legend_marker_size_var = tk.IntVar(value=10)
        ttk.Spinbox(leg_row2, from_=4, to=24, textvariable=self.legend_marker_size_var, width=5).pack(side=tk.LEFT, padx=5)
        
        # Point Transparency (Alpha)
        self.point_alpha_var = tk.DoubleVar(value=0.7)
        self.alpha_frame = ttk.Frame(marker_frame)
        self.alpha_frame.pack(fill=tk.X, pady=2)
        ttk.Label(self.alpha_frame, text="Point Alpha (0-1):").pack(side=tk.LEFT, padx=5)
        ttk.Spinbox(self.alpha_frame, from_=0.0, to=1.0, increment=0.1, textvariable=self.point_alpha_var, width=5).pack(side=tk.LEFT, padx=5)
        
        state['row'] = row + 1
        
    def _create_axis_ticks_section(self, parent, state):
        row = state['row']
        axis_frame = ttk.LabelFrame(parent, text="Step 6 • Axis & Ticks", padding="5")
        axis_frame.grid(row=row, column=0, columnspan=3, sticky=tk.EW, pady=5)
        
        # Tick counts
        t_row1 = ttk.Frame(axis_frame)
        t_row1.pack(fill=tk.X, pady=2)
        ttk.Label(t_row1, text="X Ticks:").pack(side=tk.LEFT, padx=5)
        self.x_tick_count_var = tk.IntVar(value=6)
        ttk.Spinbox(t_row1, from_=2, to=20, textvariable=self.x_tick_count_var, width=5).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(t_row1, text="Y Ticks:").pack(side=tk.LEFT, padx=(15, 5))
        self.y_tick_count_var = tk.IntVar(value=6)
        ttk.Spinbox(t_row1, from_=2, to=20, textvariable=self.y_tick_count_var, width=5).pack(side=tk.LEFT, padx=5)
        
        # Font sizes
        t_row2 = ttk.Frame(axis_frame)
        t_row2.pack(fill=tk.X, pady=2)
        ttk.Label(t_row2, text="Tick Font:").pack(side=tk.LEFT, padx=5)
        self.tick_label_size_var = tk.IntVar(value=14)
        ttk.Spinbox(t_row2, from_=6, to=32, textvariable=self.tick_label_size_var, width=5).pack(side=tk.LEFT, padx=5)
        
        self.tick_label_bold_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(t_row2, text="Bold", variable=self.tick_label_bold_var).pack(side=tk.LEFT, padx=5)

        ttk.Label(t_row2, text="Angle:").pack(side=tk.LEFT, padx=(5, 2))
        self.x_tick_rotation_var = tk.IntVar(value=0)
        ttk.Spinbox(t_row2, from_=-90, to=90, increment=15, textvariable=self.x_tick_rotation_var, width=4).pack(side=tk.LEFT, padx=2)
        
        ttk.Label(t_row2, text="Axis Font:").pack(side=tk.LEFT, padx=(15, 5))
        self.axis_label_font_size_var = tk.IntVar(value=12)
        ttk.Spinbox(t_row2, from_=8, to=24, textvariable=self.axis_label_font_size_var, width=5).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(t_row2, text="Title Font:").pack(side=tk.LEFT, padx=(15, 5))
        self.title_font_size_var = tk.IntVar(value=16)
        ttk.Spinbox(t_row2, from_=10, to=32, textvariable=self.title_font_size_var, width=5).pack(side=tk.LEFT, padx=5)
        
        # Tick style
        t_row3 = ttk.Frame(axis_frame)
        t_row3.pack(fill=tk.X, pady=2)
        ttk.Label(t_row3, text="Tick Length:").pack(side=tk.LEFT, padx=5)
        self.tick_length_var = tk.DoubleVar(value=4.0)
        ttk.Spinbox(t_row3, from_=0.5, to=12.0, increment=0.5, textvariable=self.tick_length_var, width=5).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(t_row3, text="Width:").pack(side=tk.LEFT, padx=(15, 5))
        self.tick_width_var = tk.DoubleVar(value=1.5)
        ttk.Spinbox(t_row3, from_=0.5, to=4.0, increment=0.1, textvariable=self.tick_width_var, width=5).pack(side=tk.LEFT, padx=5)
        
        # Toggles
        # Toggles
        t_row4 = ttk.Frame(axis_frame)
        t_row4.pack(fill=tk.X, pady=2)
        self.show_minor_ticks_var = tk.BooleanVar(value=False)
        self.reverse_y_axis_var = tk.BooleanVar(value=False)
        self.auto_x_ticks_var = tk.BooleanVar(value=True)
        self.auto_y_ticks_var = tk.BooleanVar(value=True)
        self.force_origin_zero_var = tk.BooleanVar(value=True) # Consistent naming
        
        ttk.Checkbutton(t_row4, text="Minor ticks", variable=self.show_minor_ticks_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(t_row4, text="Reverse Y", variable=self.reverse_y_axis_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(t_row4, text="Auto X", variable=self.auto_x_ticks_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(t_row4, text="Auto Y", variable=self.auto_y_ticks_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(t_row4, text="Zero Start", variable=self.force_origin_zero_var).pack(side=tk.LEFT, padx=5)
        
        # Custom X ticks
        self.use_custom_x_ticks_var = tk.BooleanVar(value=False)
        self.x_tick_min_var = tk.DoubleVar(value=0.0)
        self.x_tick_max_var = tk.DoubleVar(value=100.0)
        self.x_tick_step_var = tk.DoubleVar(value=5.0)
        
        # Custom Y ticks
        self.use_custom_y_ticks_var = tk.BooleanVar(value=False)
        self.y_tick_min_var = tk.DoubleVar(value=0.0)
        self.y_tick_max_var = tk.DoubleVar(value=1.0)
        self.y_tick_step_var = tk.DoubleVar(value=0.1)
        
        state['row'] = row + 1

        # Custom X ticks row
        cx_row = ttk.Frame(axis_frame)
        cx_row.pack(fill=tk.X, pady=2)
        ttk.Checkbutton(cx_row, text="Use custom X ticks", variable=self.use_custom_x_ticks_var).pack(side=tk.LEFT, padx=5)
        ttk.Label(cx_row, text="Start:").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(cx_row, textvariable=self.x_tick_min_var, width=5, increment=0.1).pack(side=tk.LEFT, padx=2)
        ttk.Label(cx_row, text="End:").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(cx_row, textvariable=self.x_tick_max_var, width=5, increment=0.1).pack(side=tk.LEFT, padx=2)
        ttk.Label(cx_row, text="Step:").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(cx_row, textvariable=self.x_tick_step_var, width=5, increment=0.1).pack(side=tk.LEFT, padx=2)
        
        # Custom Y ticks row
        cy_row = ttk.Frame(axis_frame)
        cy_row.pack(fill=tk.X, pady=2)
        ttk.Checkbutton(cy_row, text="Use custom Y ticks", variable=self.use_custom_y_ticks_var).pack(side=tk.LEFT, padx=5)
        ttk.Label(cy_row, text="Start:").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(cy_row, textvariable=self.y_tick_min_var, width=5, increment=0.1).pack(side=tk.LEFT, padx=2)
        ttk.Label(cy_row, text="End:").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(cy_row, textvariable=self.y_tick_max_var, width=5, increment=0.1).pack(side=tk.LEFT, padx=2)
        ttk.Label(cy_row, text="Step:").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(cy_row, textvariable=self.y_tick_step_var, width=5, increment=0.1).pack(side=tk.LEFT, padx=2)

        # Broken Y-Axis
        self.use_broken_y_axis_var = tk.BooleanVar(value=False)
        self.broken_y_bot_min_var = tk.DoubleVar(value=0.0)
        self.broken_y_bot_max_var = tk.DoubleVar(value=10.0)
        self.broken_y_top_min_var = tk.DoubleVar(value=90.0)
        self.broken_y_top_max_var = tk.DoubleVar(value=100.0)

        broken_y_row1 = ttk.Frame(axis_frame)
        broken_y_row1.pack(fill=tk.X, pady=2)
        ttk.Checkbutton(broken_y_row1, text="Use Broken Y-Axis", variable=self.use_broken_y_axis_var).pack(side=tk.LEFT, padx=5)

        broken_y_row2 = ttk.Frame(axis_frame)
        broken_y_row2.pack(fill=tk.X, pady=1)
        ttk.Label(broken_y_row2, text="Bot Range:").pack(side=tk.LEFT, padx=(25, 2))
        ttk.Spinbox(broken_y_row2, textvariable=self.broken_y_bot_min_var, width=5, increment=1.0).pack(side=tk.LEFT, padx=2)
        ttk.Label(broken_y_row2, text="to").pack(side=tk.LEFT, padx=2)
        ttk.Spinbox(broken_y_row2, textvariable=self.broken_y_bot_max_var, width=5, increment=1.0).pack(side=tk.LEFT, padx=2)

        ttk.Label(broken_y_row2, text="Top Range:").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(broken_y_row2, textvariable=self.broken_y_top_min_var, width=5, increment=1.0).pack(side=tk.LEFT, padx=2)
        ttk.Label(broken_y_row2, text="to").pack(side=tk.LEFT, padx=2)
        ttk.Spinbox(broken_y_row2, textvariable=self.broken_y_top_max_var, width=5, increment=1.0).pack(side=tk.LEFT, padx=2)

        # Broken X-Axis
        self.use_broken_x_axis_var = tk.BooleanVar(value=False)
        self.broken_x_left_min_var = tk.DoubleVar(value=0.0)
        self.broken_x_left_max_var = tk.DoubleVar(value=10.0)
        self.broken_x_right_min_var = tk.DoubleVar(value=90.0)
        self.broken_x_right_max_var = tk.DoubleVar(value=100.0)

        broken_x_row1 = ttk.Frame(axis_frame)
        broken_x_row1.pack(fill=tk.X, pady=2)
        ttk.Checkbutton(broken_x_row1, text="Use Broken X-Axis", variable=self.use_broken_x_axis_var).pack(side=tk.LEFT, padx=5)

        broken_x_row2 = ttk.Frame(axis_frame)
        broken_x_row2.pack(fill=tk.X, pady=1)
        ttk.Label(broken_x_row2, text="Left Range:").pack(side=tk.LEFT, padx=(25, 2))
        ttk.Spinbox(broken_x_row2, textvariable=self.broken_x_left_min_var, width=5, increment=1.0).pack(side=tk.LEFT, padx=2)
        ttk.Label(broken_x_row2, text="to").pack(side=tk.LEFT, padx=2)
        ttk.Spinbox(broken_x_row2, textvariable=self.broken_x_left_max_var, width=5, increment=1.0).pack(side=tk.LEFT, padx=2)

        ttk.Label(broken_x_row2, text="Right Range:").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(broken_x_row2, textvariable=self.broken_x_right_min_var, width=5, increment=1.0).pack(side=tk.LEFT, padx=2)
        ttk.Label(broken_x_row2, text="to").pack(side=tk.LEFT, padx=2)
        ttk.Spinbox(broken_x_row2, textvariable=self.broken_x_right_max_var, width=5, increment=1.0).pack(side=tk.LEFT, padx=2)



    def _create_export_section(self, parent, state):
        row = state['row']
        export_frame = ttk.LabelFrame(parent, text="Step 7 • Export Settings", padding="5")
        export_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=5)
        
        e_row = ttk.Frame(export_frame)
        e_row.pack(fill=tk.X, pady=2)
        ttk.Label(e_row, text="DPI:").pack(side=tk.LEFT, padx=5)
        self.fig_dpi_var = tk.IntVar(value=300)
        ttk.Spinbox(e_row, from_=72, to=1200, increment=50, textvariable=self.fig_dpi_var, width=6).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(e_row, text="Size (in):").pack(side=tk.LEFT, padx=(15, 2))
        self.fig_width_var = tk.DoubleVar(value=DEFAULT_FIG_WIDTH)
        self.fig_height_var = tk.DoubleVar(value=DEFAULT_FIG_HEIGHT)
        ttk.Spinbox(e_row, from_=1.0, to=20.0, increment=0.5, textvariable=self.fig_width_var, width=4).pack(side=tk.LEFT, padx=2)
        ttk.Label(e_row, text="x").pack(side=tk.LEFT)
        ttk.Spinbox(e_row, from_=1.0, to=20.0, increment=0.5, textvariable=self.fig_height_var, width=4).pack(side=tk.LEFT, padx=2)
        
        export_mode_row = ttk.Frame(export_frame)
        export_mode_row.pack(fill=tk.X, pady=2)
        ttk.Label(export_mode_row, text="Export Mode:").pack(side=tk.LEFT, padx=5)
        self.export_mode_var = tk.StringVar(value=get_option_label("match_preview", EXPORT_MODE_OPTIONS, "Match Preview"))
        ttk.Combobox(
            export_mode_row,
            textvariable=self.export_mode_var,
            values=get_option_labels(EXPORT_MODE_OPTIONS),
            width=16,
            state="readonly"
        ).pack(side=tk.LEFT, padx=5)
        self.export_tight_bbox_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(export_mode_row, text="Auto crop margins", variable=self.export_tight_bbox_var).pack(side=tk.LEFT, padx=(10, 5))
        
        preview_hint_row = ttk.Frame(export_frame)
        preview_hint_row.pack(fill=tk.X, pady=2)
        ttk.Button(preview_hint_row, text="Use Preview Size", command=self._sync_export_size_to_preview).pack(side=tk.LEFT, padx=5)
        ttk.Label(preview_hint_row, text="Match preview keeps export close to the preview layout.").pack(side=tk.LEFT, padx=(10, 5))
        
        # Action Buttons row next to it
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=row, column=2, sticky=tk.NSEW, pady=5, padx=5)
        ttk.Button(btn_frame, text="Generate Preview", command=self.generate_chart, style='Action.TButton').pack(fill=tk.X, expand=True, pady=2)
        ttk.Button(btn_frame, text="Export Figure", command=self.export_plot).pack(fill=tk.X, expand=True, pady=2)
        ttk.Button(btn_frame, text="Clear Figure", command=self.clear_plot).pack(fill=tk.X, expand=True, pady=2)
        
        state['row'] = row + 1

    def _sync_export_size_to_preview(self):
        width, height = self.fig.get_size_inches()
        self.fig_width_var.set(round(float(width), 2))
        self.fig_height_var.set(round(float(height), 2))
        self.status_bar.config(text=f"Export size synced to preview: {width:.2f} x {height:.2f} in")

    def _on_visual_preset_selected(self, event=None):
        preset = normalize_option_value(self.visual_preset_var.get(), VISUAL_PRESET_OPTIONS, "default")
        self.visual_preset_var.set(get_option_label(preset, VISUAL_PRESET_OPTIONS, "Default"))
        if preset == "sci":
            self._apply_sci_visual_defaults()
            self.status_bar.config(text="Visual preset: SCI")
        else:
            self._apply_default_visual_defaults()
            self.status_bar.config(text="Visual preset: Default")

    def _apply_default_visual_defaults(self):
        self.line_width_var.set(2.0)
        self.marker_size_var.set(10)
        self.font_size_var.set(10)
        self.legend_font_size_var.set(14)
        self.legend_marker_size_var.set(10)
        self.tick_label_size_var.set(14)
        self.axis_label_font_size_var.set(12)
        self.title_font_size_var.set(16)
        self.tick_length_var.set(4.0)
        self.tick_width_var.set(1.5)
        self.show_minor_ticks_var.set(False)
        self.tick_label_bold_var.set(False)
        self.point_alpha_var.set(0.7)
        self.errorbar_capsize_var.set(7)
        self.errorbar_linewidth_var.set(2.0)
        self.bar_edge_width_var.set(1.0)
        self.show_data_labels_var.set(True)
        self.show_legend_var.set(True)
        self.legend_loc_var.set("auto")
        self.legend_ncol_var.set(1)
        self.line_style_var.set("solid")
        # SCI switches the bar style to 'white'; restore it, otherwise the two
        # presets are no longer symmetric.
        self.bar_style_var.set("solid")

    def _apply_sci_visual_defaults(self):
        self.line_width_var.set(1.4)
        self.marker_size_var.set(7)
        self.font_size_var.set(8)
        self.legend_font_size_var.set(8)
        self.legend_marker_size_var.set(7)
        self.tick_label_size_var.set(9)
        self.axis_label_font_size_var.set(10)
        self.title_font_size_var.set(11)
        self.tick_length_var.set(5.0)
        self.tick_width_var.set(1.0)
        self.show_minor_ticks_var.set(True)
        self.tick_label_bold_var.set(False)
        self.point_alpha_var.set(0.45)
        self.errorbar_capsize_var.set(3)
        self.errorbar_linewidth_var.set(1.2)
        self.bar_edge_width_var.set(1.0)
        self.show_data_labels_var.set(False)
        self.show_legend_var.set(True)
        self.legend_loc_var.set("best")
        self.legend_ncol_var.set(1)
        self.line_style_var.set("solid")
        self.bar_style_var.set("white")

    def _on_fit_method_change(self, *args):
        """Enable/disable polynomial degree spinner based on fit method"""
        method = normalize_option_value(self.fit_method_var.get(), FIT_METHOD_OPTIONS, "none")
        method_label = get_option_label(method, FIT_METHOD_OPTIONS, "None")
        if self.fit_method_var.get() != method_label:
            self.fit_method_var.set(method_label)
            return
        # Find the degree spinner in the fitting frame children
        for widget in self.fitting_frame.winfo_children():
            if isinstance(widget, ttk.Spinbox):
                if method == "polynomial":
                    widget.config(state="normal")
                else:
                    widget.config(state="disabled")
                break

    def _create_dataset_management(self, parent):
        dataset_frame = ttk.LabelFrame(parent, text="Step 1 • Datasets", padding="10")
        dataset_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        list_frame = ttk.Frame(dataset_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.dataset_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, height=8)
        self.dataset_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.dataset_listbox.yview)
        
        btn_frame = ttk.Frame(dataset_frame)
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(btn_frame, text="Add", command=self.add_dataset, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Edit", command=self.edit_dataset, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Set Color", command=self.change_dataset_color, width=10).pack(side=tk.LEFT, padx=2)
        
        btn_frame2 = ttk.Frame(dataset_frame)
        btn_frame2.pack(fill=tk.X, pady=(2, 0))
        
        ttk.Button(btn_frame2, text="Remove", command=self.remove_dataset, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame2, text="Clear All", command=self.clear_datasets, width=8).pack(side=tk.LEFT, padx=2)
        
        import_frame = ttk.Frame(dataset_frame)
        import_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(import_frame, text="Import Table Excel", 
                  command=self.import_from_excel).pack(fill=tk.X, padx=2)
        
        ttk.Button(import_frame, text="Import Multi-Line Excel", 
                  command=self.import_multiline_excel).pack(fill=tk.X, padx=2, pady=(2, 0))

        # Scientific palette quick-apply: recolour every dataset in one click.
        palette_frame = ttk.LabelFrame(dataset_frame, text="Scientific Palette",
                                       padding="5")
        palette_frame.pack(fill=tk.X, pady=(6, 0))
        self.palette_choice_var = tk.StringVar()
        self.palette_choice_combo = ttk.Combobox(
            palette_frame, textvariable=self.palette_choice_var, state="readonly",
            values=[palette_label(name) for name in PALETTE_ORDER], width=30)
        self.palette_choice_combo.current(0)
        self.palette_choice_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(palette_frame, text="Apply to All",
                   command=self.apply_palette_to_datasets).pack(side=tk.LEFT, padx=2)

    def _selected_palette_key(self):
        """Key of the palette chosen in the Datasets panel."""
        index = self.palette_choice_combo.current()
        if index < 0 or index >= len(PALETTE_ORDER):
            return PALETTE_ORDER[0]
        return PALETTE_ORDER[index]

    def apply_palette_to_datasets(self):
        """Assign the selected palette's colours to all datasets, in order."""
        if not self.datasets:
            messagebox.showwarning("Warning", "No datasets")
            return
        key = self._selected_palette_key()
        colors = palette_colors(key, count=len(self.datasets))
        for position, dataset in enumerate(self.datasets.values()):
            dataset['color'] = colors[position]
        self._refresh_dataset_listbox_colors()
        label = palette_series_label(key)
        self.status_bar.config(
            text=f"Palette {label} applied to {len(self.datasets)} dataset(s)")
        if self.chart_manager is not None:
            try:
                self.generate_chart()
            except Exception:
                pass

    def _refresh_dataset_listbox_colors(self):
        """Repaint the dataset list from the dataset colours."""
        for position, name in enumerate(self.datasets):
            try:
                self.dataset_listbox.itemconfig(
                    position, bg=self.datasets[name].get('color') or '#ffffff')
            except Exception:
                pass

    def _create_chart_display(self, parent):
        chart_frame = ttk.LabelFrame(parent, text="Preview", padding="5")
        chart_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create matplotlib figure
        self.fig = Figure(figsize=(10, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        
        # Create canvas
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Add custom navigation toolbar
        class CustomToolbar(NavigationToolbar2Tk):
            toolitems = [t for t in NavigationToolbar2Tk.toolitems 
                        if t[0] not in ['Subplots', 'Save']]
        
        self.toolbar = CustomToolbar(self.canvas, chart_frame)
        self.toolbar.update()

        toolbar_frame = ttk.Frame(chart_frame)
        toolbar_frame.pack(fill=tk.X, pady=(5, 0))
        
        # Add Adjust Margins button to toolbar
        ttk.Button(toolbar_frame, text="Adjust Preview Margins",
                  command=self.open_margin_dialog).pack(side=tk.LEFT, padx=5)
        
        # Initialize chart manager（传入工具栏以处理平移/缩放与标签拖拽的交互）
        self.chart_manager = ChartManager(self.ax, self.canvas, DEFAULT_DRAG_RADIUS_FACTOR, toolbar=self.toolbar)
    
    def _create_stats_panel(self, parent):
        stats_frame = ttk.LabelFrame(parent, text="Statistics", padding="5")
        stats_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.stats_text = scrolledtext.ScrolledText(stats_frame, height=10, wrap=tk.WORD)
        self.stats_text.pack(fill=tk.BOTH, expand=True)
    
    def _on_plot_method_change(self):
        """Show only the option groups that apply to the current chart type."""
        chart_type = self.chart_type_var.get()
        mode = self.xaxis_mode.get()

        def hide_error_bar_rows():
            self._set_error_bar_rows(False, show_color_rows=False)

        # Pie charts have no axes, ticks, error bars or line styling.
        if chart_type == "pie":
            self.xaxis_mode.set("categorical")
            self.line_frame.grid_remove()
            self.stats_display_frame.grid_remove()
            self.error_bar_options_frame.grid_remove()
            hide_error_bar_rows()
            try:
                self.alpha_frame.pack_forget()
            except Exception:
                pass
            return

        # Bar and error bar charts share the same option group.
        if chart_type in ("errorbar", "bar"):
            self.line_frame.grid_remove()
            self.stats_display_frame.grid_remove()
            self.error_bar_options_frame.grid()
            self._set_error_bar_rows(show_bar_rows=(chart_type == "bar"),
                                     show_color_rows=True)
            try:
                self.alpha_frame.pack_forget()
            except Exception:
                pass
            return

        # Line / scatter / line+scatter: pick sensible defaults once per type.
        if chart_type == "line":
            self.show_connecting_line_var.set(True)
            self.show_mean_var.set(False)
        elif chart_type == "scatter":
            self.show_connecting_line_var.set(False)
            self.show_mean_var.set(True)
        elif chart_type == "line_scatter":
            self.show_connecting_line_var.set(True)
            self.show_mean_var.set(True)

        self.line_frame.grid()
        self.stats_display_frame.grid()
        self.error_bar_options_frame.grid_remove()
        hide_error_bar_rows()

        # Point transparency only affects raw scatter points; it used to be
        # hidden permanently because nothing ever packed it back.
        try:
            if self.show_raw_data_var.get():
                if not self.alpha_frame.winfo_manager():
                    self.alpha_frame.pack(fill=tk.X, pady=2)
            else:
                self.alpha_frame.pack_forget()
        except Exception:
            pass
    
    def open_margin_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Adjust Chart Margins")
        dialog.geometry("450x350")
        dialog.transient(self.root)
        dialog.grab_set()
        
        unit_frame = ttk.Frame(dialog)
        unit_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(unit_frame, text="Unit:").pack(side=tk.LEFT, padx=5)
        
        unit_var = tk.StringVar(value="cm")
        ttk.Radiobutton(unit_frame, text="Centimeters (cm)", variable=unit_var, 
                       value="cm", command=lambda: update_unit()).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(unit_frame, text="Inches (in)", variable=unit_var, 
                       value="in", command=lambda: update_unit()).pack(side=tk.LEFT, padx=10)
        
        margin_frame = ttk.LabelFrame(dialog, text="Margins", padding="10")
        margin_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        fig_width, fig_height = self.fig.get_size_inches()
        left, bottom, right, top = self.fig.subplotpars.left, self.fig.subplotpars.bottom, \
                                   self.fig.subplotpars.right, self.fig.subplotpars.top
        
        left_in = left * fig_width
        bottom_in = bottom * fig_height
        right_in = (1 - right) * fig_width
        top_in = (1 - top) * fig_height
        
        margins = {}
        margin_vars = {}
        
        for idx, (name, default_val) in enumerate([("Left", left_in), ("Bottom", bottom_in), 
                                                     ("Right", right_in), ("Top", top_in)]):
            row_frame = ttk.Frame(margin_frame)
            row_frame.pack(fill=tk.X, pady=5)
            
            ttk.Label(row_frame, text=f"{name}:", width=8).pack(side=tk.LEFT, padx=5)
            
            var = tk.DoubleVar(value=round(default_val * IN_TO_CM, 2))
            margin_vars[name.lower()] = var
            
            scale = ttk.Scale(row_frame, from_=0, to=10, variable=var, orient=tk.HORIZONTAL)
            scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            margins[name.lower()] = scale
            
            entry = ttk.Entry(row_frame, textvariable=var, width=8)
            entry.pack(side=tk.LEFT, padx=5)
            
            unit_label = ttk.Label(row_frame, text="cm", width=3)
            unit_label.pack(side=tk.LEFT)
            margins[name.lower() + '_unit'] = unit_label
        
        def update_unit():
            unit = unit_var.get()
            for name in ['left', 'bottom', 'right', 'top']:
                current = margin_vars[name].get()
                if unit == "in":
                    margin_vars[name].set(round(current * CM_TO_IN, 3))
                    margins[name].config(to=4)
                    margins[name + '_unit'].config(text="in")
                else:
                    margin_vars[name].set(round(current * IN_TO_CM, 2))
                    margins[name].config(to=10)
                    margins[name + '_unit'].config(text="cm")
        
        def apply_margins():
            unit = unit_var.get()
            left_val = margin_vars['left'].get()
            bottom_val = margin_vars['bottom'].get()
            right_val = margin_vars['right'].get()
            top_val = margin_vars['top'].get()
            
            if unit == "cm":
                left_val *= CM_TO_IN
                bottom_val *= CM_TO_IN
                right_val *= CM_TO_IN
                top_val *= CM_TO_IN
            
            fig_width, fig_height = self.fig.get_size_inches()
            
            left_frac = left_val / fig_width
            bottom_frac = bottom_val / fig_height
            right_frac = 1 - (right_val / fig_width)
            top_frac = 1 - (top_val / fig_height)
            
            if left_frac >= right_frac or bottom_frac >= top_frac:
                messagebox.showerror("Error", "Margins too large!")
                return
            
            self.fig.subplots_adjust(left=left_frac, bottom=bottom_frac, 
                                    right=right_frac, top=top_frac,
                                    wspace=0, hspace=0)
            self.canvas.draw()
            self.status_bar.config(text="Margins updated")
        
        def reset_margins():
            unit = unit_var.get()
            if unit == "cm":
                margin_vars['left'].set(1.25)
                margin_vars['bottom'].set(1.0)
                margin_vars['right'].set(0.5)
                margin_vars['top'].set(0.5)
            else:
                margin_vars['left'].set(0.5)
                margin_vars['bottom'].set(0.4)
                margin_vars['right'].set(0.2)
                margin_vars['top'].set(0.2)
            apply_margins()
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(btn_frame, text="Apply", command=apply_margins).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Reset", command=reset_margins).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)
    
    def change_line_color(self):
        """Change line color"""
        result = askcolor(
            color=self.line_color,
            title="Choose Line Color",
            parent=self.root
        )
        
        if result and result[1]:
            self.line_color = result[1]
            self.line_color_canvas.config(bg=self.line_color)
    
    def change_bar_color(self):
        """Change global bar color"""
        def _apply(color):
            self.bar_color = color
            try:
                self.bar_color_canvas.config(bg=self.bar_color)
            except Exception:
                pass
            try:
                self.status_bar.config(text=f"Bar color: {self.bar_color}")
            except Exception:
                pass
            try:
                if getattr(self, 'chart_manager', None) is not None and self.datasets:
                    self.generate_chart()
            except Exception:
                pass
        result = askcolor(color=self.bar_color, title="Choose Bar Color", parent=self.root, on_change=_apply)
        if result and result[1]:
            _apply(result[1])
    
    def change_errorbar_color(self):
        """Change error bar color"""
        def _apply(color):
            self.errorbar_color = color
            try:
                self.errorbar_color_canvas.config(bg=self.errorbar_color)
            except Exception:
                pass
            try:
                self.status_bar.config(text=f"Error bar color: {self.errorbar_color}")
            except Exception:
                pass
            try:
                if getattr(self, 'chart_manager', None) is not None and self.datasets:
                    self.generate_chart()
            except Exception:
                pass
        result = askcolor(color=self.errorbar_color, title="Choose Error Bar Color", parent=self.root, on_change=_apply)
        if result and result[1]:
            _apply(result[1])
    
    def change_dataset_color(self):
        """Change dataset color"""
        selection = self.dataset_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Select a dataset")
            return
        
        name = self.dataset_listbox.get(selection[0])
        current_color = self.datasets[name]['color']
        
        result = askcolor(
            color=current_color,
            title="Choose Color",
            parent=self.root
        )
        
        if result and result[1]:
            self.datasets[name]['color'] = result[1]
            self.dataset_listbox.itemconfig(selection[0], bg=result[1])
            self.status_bar.config(text=f"Dataset color updated: {name}")
    
    def _build_color_chooser(self, dialog, initial_name=None, initial_hex=None):
        """Build the colour row shared by the Add/Edit dataset dialogs.

        Offers both the named dropdown (which now includes every colour of the
        ten scientific palettes) and the full palette-aware picker.  Returns a
        zero-argument callable yielding the currently selected colour.
        """
        frame = ttk.Frame(dialog)
        frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(frame, text="Color:").pack(side=tk.LEFT)

        keys = list(self.available_colors)
        fallback = self.available_colors[keys[0]]
        state = {'custom': None}

        selected = initial_name if initial_name in self.available_colors else None
        if selected is None and initial_hex:
            for name, value in self.available_colors.items():
                if value == initial_hex:
                    selected = name
                    break
            else:
                # A colour that is not in the named list (e.g. a custom hex or a
                # value from a JSON spec) is kept as-is.
                state['custom'] = initial_hex

        color_var = tk.StringVar()
        combo = ttk.Combobox(frame, textvariable=color_var, values=keys,
                             width=20, state='readonly')
        combo.set(selected or keys[0])
        combo.pack(side=tk.LEFT, padx=5)

        def get_color():
            if state['custom']:
                return state['custom']
            return self.available_colors.get(color_var.get() or combo.get(), fallback)

        swatch = tk.Canvas(frame, width=30, height=20, highlightthickness=1,
                           bg=get_color())
        swatch.pack(side=tk.LEFT, padx=5)

        def refresh():
            try:
                swatch.config(bg=get_color())
            except Exception:
                pass

        def on_combo_selected(_event=None):
            state['custom'] = None
            refresh()

        def apply_custom(color):
            state['custom'] = color
            refresh()

        def pick():
            result = askcolor(color=get_color(), title="Choose Dataset Color",
                              parent=dialog, on_change=apply_custom)
            if result and result[1]:
                apply_custom(result[1])

        combo.bind('<<ComboboxSelected>>', on_combo_selected)
        ttk.Button(frame, text="Pick...", command=pick, width=8).pack(side=tk.LEFT,
                                                                     padx=2)
        ttk.Label(frame, text="(includes the 10 journal palettes)").pack(side=tk.LEFT,
                                                                        padx=4)
        return get_color

    def add_dataset(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Dataset")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        
        name_frame = ttk.Frame(dialog)
        name_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(name_frame, text="Dataset Name:").pack(side=tk.LEFT)
        name_entry = ttk.Entry(name_frame, width=30)
        name_entry.pack(side=tk.LEFT, padx=5)
        name_entry.insert(0, f"Dataset_{len(self.datasets)+1}")
        
        get_dataset_color = self._build_color_chooser(
            dialog,
            initial_name=list(self.available_colors)[
                len(self.datasets) % len(self.available_colors)],
        )

        ttk.Label(dialog, text="X Values:").pack(padx=10, pady=(10, 0))
        sizes_text = scrolledtext.ScrolledText(dialog, height=3, wrap=tk.WORD)
        sizes_text.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(dialog, text="Y Values (each line = one X):").pack(padx=10, pady=(10, 0))
        data_text = scrolledtext.ScrolledText(dialog, height=15, wrap=tk.WORD)
        data_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        def save_dataset():
            name = name_entry.get().strip()
            if not name:
                messagebox.showwarning("Warning", "Enter name")
                return
            # 保证名称唯一：若重复则自动加序号后缀
            if name in self.datasets:
                base = name
                counter = 2
                while f"{base}_{counter}" in self.datasets:
                    counter += 1
                name = f"{base}_{counter}"
            
            sizes_raw = sizes_text.get(1.0, tk.END).strip()
            sizes = parse_data_input(sizes_raw)
            
            if not sizes:
                messagebox.showwarning("Warning", "Enter X values")
                return
            
            data_raw = data_text.get(1.0, tk.END).strip()
            lines = data_raw.split('\n')
            
            data_list = []
            for line in lines:
                if line.strip():
                    data = parse_data_input(line)
                    data_list.append(data)
            
            if not data_list:
                messagebox.showwarning("Warning", "Enter Y values")
                return
            
            is_valid, error_msg = validate_dataset(sizes, data_list)
            if not is_valid:
                messagebox.showerror("Error", error_msg)
                return
            
            color = get_dataset_color()
            
            self.datasets[name] = {
                'sizes': sizes,
                'data': data_list,
                'color': color
            }
            
            self.dataset_listbox.insert(tk.END, name)
            self.dataset_listbox.itemconfig(tk.END, bg=color)
            
            self.status_bar.config(text=f"Added '{name}'")
            dialog.destroy()
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(btn_frame, text="Save", command=save_dataset).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
    
    def edit_dataset(self):
        selection = self.dataset_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Select dataset")
            return
        
        old_name = self.dataset_listbox.get(selection[0])
        dataset = self.datasets[old_name]
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit: {old_name}")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        
        name_frame = ttk.Frame(dialog)
        name_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(name_frame, text="Name:").pack(side=tk.LEFT)
        name_entry = ttk.Entry(name_frame, width=30)
        name_entry.pack(side=tk.LEFT, padx=5)
        name_entry.insert(0, old_name)
        
        get_dataset_color = self._build_color_chooser(
            dialog, initial_hex=dataset['color'])
        
        ttk.Label(dialog, text="X Values:").pack(padx=10, pady=(10, 0))
        sizes_text = scrolledtext.ScrolledText(dialog, height=3, wrap=tk.WORD)
        sizes_text.pack(fill=tk.X, padx=10, pady=5)
        sizes_text.insert(1.0, ' '.join(map(str, dataset['sizes'])))
        
        ttk.Label(dialog, text="Y Values:").pack(padx=10, pady=(10, 0))
        data_text = scrolledtext.ScrolledText(dialog, height=15, wrap=tk.WORD)
        data_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        for data in dataset['data']:
            data_text.insert(tk.END, ' '.join(map(str, data)) + '\n')
        
        def save_changes():
            new_name = name_entry.get().strip()
            if not new_name:
                messagebox.showwarning("Warning", "Enter name")
                return
            # 保证重命名后唯一：若重复则自动加序号
            if new_name != old_name and new_name in self.datasets:
                base = new_name
                counter = 2
                while f"{base}_{counter}" in self.datasets:
                    counter += 1
                new_name = f"{base}_{counter}"
            
            sizes_raw = sizes_text.get(1.0, tk.END).strip()
            sizes = parse_data_input(sizes_raw)
            
            if not sizes:
                messagebox.showwarning("Warning", "Enter X values")
                return
            
            data_raw = data_text.get(1.0, tk.END).strip()
            lines = data_raw.split('\n')
            
            data_list = []
            for line in lines:
                if line.strip():
                    data = parse_data_input(line)
                    data_list.append(data)
            
            if not data_list:
                messagebox.showwarning("Warning", "Enter Y values")
                return
            
            is_valid, error_msg = validate_dataset(sizes, data_list)
            if not is_valid:
                messagebox.showerror("Error", error_msg)
                return
            
            color = get_dataset_color()
            
            del self.datasets[old_name]
            
            self.datasets[new_name] = {
                'sizes': sizes,
                'data': data_list,
                'color': color
            }
            
            self.dataset_listbox.delete(selection[0])
            self.dataset_listbox.insert(selection[0], new_name)
            self.dataset_listbox.itemconfig(selection[0], bg=color)
            
            self.status_bar.config(text=f"Updated")
            dialog.destroy()
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(btn_frame, text="Save", command=save_changes).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
    
    def remove_dataset(self):
        selection = self.dataset_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Select dataset")
            return
        
        name = self.dataset_listbox.get(selection[0])
        if messagebox.askyesno("Confirm", f"Remove '{name}'?"):
            del self.datasets[name]
            self.dataset_listbox.delete(selection[0])
            self.status_bar.config(text=f"Removed")
    
    def clear_datasets(self):
        if messagebox.askyesno("Confirm", "Clear all?"):
            self.datasets.clear()
            self.dataset_listbox.delete(0, tk.END)
            self.status_bar.config(text="Cleared")
    
    def import_from_excel(self):
        try:
            import pandas as pd  # noqa: F401  (presence check for a clear error)
        except ImportError:
            messagebox.showerror("Error", "Need pandas.\nInstall: pip install pandas openpyxl")
            return
        
        file_path = filedialog.askopenfilename(
            title="Select Excel",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
        )
        
        if not file_path:
            return
        
        try:
            # 检查文件大小
            file_size = os.path.getsize(file_path)
            MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB限制
            
            if file_size > MAX_FILE_SIZE:
                result = messagebox.askyesno(
                    "Large file warning",
                    f"The file is {file_size / (1024*1024):.1f} MB, above the recommended "
                    f"{MAX_FILE_SIZE / (1024*1024):.1f} MB.\n"
                    "Importing it may make the application slow or unresponsive.\n"
                    "Continue anyway?"
                )
                if not result:
                    return
            
            # pandas.read_excel has no chunksize argument; load_table_dataframe
            # streams large workbooks with openpyxl instead so memory stays bounded.
            df = load_table_dataframe(file_path)
            
            # 检查数据量
            total_cells = df.shape[0] * df.shape[1]
            MAX_CELLS = 100000  # 10万个单元格限制
            
            if total_cells > MAX_CELLS:
                result = messagebox.askyesno(
                    "Large data warning",
                    f"The file contains {total_cells:,} cells, above the recommended "
                    f"{MAX_CELLS:,}.\n"
                    "Processing this much data may make the application slow.\n"
                    "Continue anyway?"
                )
                if not result:
                    return
            
            self._show_excel_import_dialog(df, file_path)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed:\n{str(e)}")
    
    def import_multiline_excel(self):
        """Import multiple Excel files for multi-line chart.
        Each file becomes one line. Headers are X values, column means are Y values."""
        file_paths = filedialog.askopenfilenames(
            title="Select Excel Files for Multi-Line Chart",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
        )
        
        if not file_paths:
            return

        orientation = self._choose_multiline_import_orientation()
        if orientation is None:
            return
            
        merge_multiline = False
        if len(file_paths) > 1:
            merge_multiline = messagebox.askyesno(
                "Merge Data?",
                "You have selected multiple files.\n\n"
                "Do you want to merge points with the same X coordinates across these files into a single dataset? "
                "This allows you to plot them as combined error bars or fit a single curve."
            )
        
        # Use available markers cyclically
        available_markers = AVAILABLE_MARKERS
        imported_count = 0
        errors = []
        
        # Capture current dataset count for correct cycling
        initial_dataset_count = len(self.datasets)
        
        if merge_multiline:
            merged_data_by_x = {}
            for file_path in file_paths:
                try:
                    result = process_multiline_excel(file_path, orientation=orientation)
                    x_vals = result['x']
                    raw_data = result.get('raw_data', [])
                    y_means = result.get('y', [])
                    for i, x in enumerate(x_vals):
                        if x not in merged_data_by_x:
                            merged_data_by_x[x] = []
                        if i < len(raw_data) and len(raw_data[i]) > 0:
                            merged_data_by_x[x].extend(raw_data[i])
                        elif i < len(y_means):
                            merged_data_by_x[x].append(y_means[i])
                except Exception as e:
                    errors.append(f"{file_path}: {str(e)}")
            
            if merged_data_by_x:
                sorted_x = sorted(merged_data_by_x.keys())
                merged_raw_data = [merged_data_by_x[x] for x in sorted_x]
                
                y_means = [np.mean(pts) if pts else 0.0 for pts in merged_raw_data]
                y_errors = [np.std(pts) if len(pts)>1 else 0.0 for pts in merged_raw_data]
                
                name = "Merged_Dataset"
                if name in self.datasets:
                    counter = 2
                    while f"{name}_{counter}" in self.datasets:
                        counter += 1
                    name = f"{name}_{counter}"
                
                cycle_idx = initial_dataset_count
                color_values = list(self.available_colors.values())
                color = color_values[cycle_idx % len(color_values)]
                marker = available_markers[cycle_idx % len(available_markers)]
                
                self.datasets[name] = {
                    'sizes': sorted_x,
                    'data': merged_raw_data,
                    'color': color,
                    'marker': marker,
                    'y_errors': y_errors,
                    'is_multiline': True
                }
                
                self.dataset_listbox.insert(tk.END, name)
                self.dataset_listbox.itemconfig(tk.END, bg=color)
                imported_count = len(file_paths) - len(errors)
        else:
            for idx, file_path in enumerate(file_paths):
                try:
                    # Process the Excel file
                    result = process_multiline_excel(file_path, orientation=orientation)
                    
                    # Create dataset name from label
                    name = result['label']
                    # Ensure unique name
                    if name in self.datasets:
                        counter = 2
                        while f"{name}_{counter}" in self.datasets:
                            counter += 1
                        name = f"{name}_{counter}"
                    
                    # Get X values and Y values (means)
                    x_values = result['x']
                    y_means = result['y']
                    y_errors = result['y_err']
                    
                    # Format data_list: Prefer raw data if available, otherwise use means
                    if 'raw_data' in result and result['raw_data']:
                        data_list = result['raw_data']
                    else:
                        data_list = [[y] for y in y_means]
                    
                    # Assign color and marker
                    # Cycle through colors and markers based on existing dataset count + index
                    cycle_idx = initial_dataset_count + idx
                    color_values = list(self.available_colors.values())
                    color = color_values[cycle_idx % len(color_values)]
                    marker = available_markers[cycle_idx % len(available_markers)]
                    
                    # Store dataset with extra info for error bars and marker
                    self.datasets[name] = {
                        'sizes': x_values,
                        'data': data_list,
                        'color': color,
                        'marker': marker,  # Store marker shape
                        'y_errors': y_errors,  # Store std for error bars
                        'is_multiline': True   # Flag to identify multiline data
                    }
                    
                    # Add to listbox
                    self.dataset_listbox.insert(tk.END, name)
                    self.dataset_listbox.itemconfig(tk.END, bg=color)
                    imported_count += 1
                    
                except Exception as e:
                    errors.append(f"{file_path}: {str(e)}")
        
        # Show result
        if imported_count > 0:
            self.status_bar.config(text=f"Imported {imported_count} file(s) for multi-line chart")
            
            # Automatically set chart settings for Multi-Line Errorbar Chart
            self.xaxis_mode.set("numeric")
            self.chart_type_var.set("line")
            self.show_connecting_line_var.set(True)
            self.show_mean_var.set(True) # Ensure means are shown (since these are means)
            self.show_data_labels_var.set(True) # User requested labels initially

        
        if errors:
            error_msg = "\n".join(errors[:5])  # Show first 5 errors
            if len(errors) > 5:
                error_msg += f"\n... and {len(errors) - 5} more errors"
            messagebox.showwarning("Import Warnings", f"Some files failed to import:\n{error_msg}")

    def _choose_multiline_import_orientation(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Multi-Line Import")
        dialog.geometry("420x220")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        ttk.Label(
            dialog,
            text="Choose how the Excel data should be interpreted for multi-line import.",
            wraplength=380,
            justify=tk.LEFT
        ).pack(fill=tk.X, padx=15, pady=(15, 10))

        orientation_var = tk.StringVar(value="vertical")

        options_frame = ttk.LabelFrame(dialog, text="Data Orientation", padding="10")
        options_frame.pack(fill=tk.X, padx=15, pady=5)

        ttk.Radiobutton(
            options_frame,
            text="Vertical: first row is X, columns contain repeated measurements",
            variable=orientation_var,
            value="vertical"
        ).pack(anchor=tk.W, pady=2)
        ttk.Radiobutton(
            options_frame,
            text="Horizontal: first column is X, rows contain repeated measurements",
            variable=orientation_var,
            value="horizontal"
        ).pack(anchor=tk.W, pady=2)

        ttk.Label(
            dialog,
            text="Example: headers like 1, 1.5, 2, 1mm are accepted.",
            wraplength=380,
            justify=tk.LEFT
        ).pack(fill=tk.X, padx=15, pady=(5, 10))

        result = {'value': None}

        def confirm():
            result['value'] = orientation_var.get()
            dialog.destroy()

        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=15, pady=(0, 15))
        ttk.Button(button_frame, text="Import", command=confirm).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)

        dialog.wait_window()
        return result['value']
    
    @staticmethod
    def _numeric_series(df, column):
        """Return ``df[column]`` as a numeric Series, tolerating duplicate headers."""
        import pandas as pd

        series = df[column]
        if isinstance(series, pd.DataFrame):
            # A duplicated header selects several columns; keep the first.
            series = series.iloc[:, 0]
        return pd.to_numeric(series, errors='coerce')

    def _show_excel_import_dialog(self, df, file_path):
        dialog = tk.Toplevel(self.root)
        dialog.title("Import from Excel")
        dialog.geometry("550x500")
        dialog.transient(self.root)
        dialog.grab_set()
        import pandas as pd
        
        orient_frame = ttk.LabelFrame(dialog, text="Data Orientation", padding="10")
        orient_frame.pack(fill=tk.X, padx=10, pady=10)
        
        orient_var = tk.StringVar(value="vertical")
        ttk.Radiobutton(orient_frame, text="Vertical (columns = datasets)", 
                       variable=orient_var, value="vertical",
                       command=lambda: update_preview()).pack(anchor=tk.W)
        ttk.Radiobutton(orient_frame, text="Horizontal (rows = datasets)", 
                       variable=orient_var, value="horizontal",
                       command=lambda: update_preview()).pack(anchor=tk.W)

        ts_frame = ttk.LabelFrame(dialog, text="Time Series Options", padding="10")
        ts_frame.pack(fill=tk.X, padx=10, pady=5)
        time_series_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ts_frame, text="Use one column as X (time)",
                        variable=time_series_var).pack(anchor=tk.W)
        ts_row1 = ttk.Frame(ts_frame)
        ts_row1.pack(fill=tk.X, pady=2)
        ttk.Label(ts_row1, text="Time column:").pack(side=tk.LEFT, padx=5)
        time_col_var = tk.StringVar()
        time_col_combo = ttk.Combobox(ts_row1, textvariable=time_col_var, state="readonly", width=24)
        time_col_combo.pack(side=tk.LEFT, padx=5)
        ts_row2 = ttk.Frame(ts_frame)
        ts_row2.pack(fill=tk.X, pady=2)
        ttk.Label(ts_row2, text="Time unit:").pack(side=tk.LEFT, padx=5)
        time_unit_var = tk.StringVar(value="s")
        ttk.Combobox(ts_row2, textvariable=time_unit_var, values=["s", "ms"], state="readonly", width=8).pack(side=tk.LEFT, padx=5)
        ttk.Label(ts_row2, text="Tick step (s):").pack(side=tk.LEFT, padx=10)
        tick_step_var = tk.DoubleVar(value=0.5)
        ttk.Spinbox(ts_row2, from_=0.000001, to=1e6, increment=0.5, textvariable=tick_step_var, width=10).pack(side=tk.LEFT, padx=5)
        
        select_frame = ttk.LabelFrame(dialog, text="Select Data", padding="10")
        select_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        canvas = tk.Canvas(select_frame)
        scrollbar = ttk.Scrollbar(select_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        selection_vars = {}
        
        def update_preview():
            for widget in scrollable_frame.winfo_children():
                widget.destroy()
            
            selection_vars.clear()
            orient = orient_var.get()
            
            if orient == "vertical":
                for col in df.columns:
                    var = tk.BooleanVar(value=True)
                    selection_vars[col] = var
                    ttk.Checkbutton(scrollable_frame, 
                                   text=f"{col} ({len(df[col].dropna())} values)",
                                   variable=var).pack(anchor=tk.W, padx=5, pady=2)
            else:
                for idx in df.index:
                    row_name = str(df.iloc[idx, 0]) if len(df.columns) > 0 else f"Row {idx}"
                    var = tk.BooleanVar(value=True)
                    selection_vars[idx] = var
                    ttk.Checkbutton(scrollable_frame,
                                   text=f"{row_name} ({df.iloc[idx].count()} values)",
                                   variable=var).pack(anchor=tk.W, padx=5, pady=2)
            try:
                time_col_combo['values'] = list(df.columns)
                if df.columns.size > 0:
                    time_col_combo.set(df.columns[0])
            except Exception:
                pass
        
        update_preview()
        
        def import_selected():
            orient = orient_var.get()
            selected = [k for k, v in selection_vars.items() if v.get()]
            
            if not selected:
                messagebox.showwarning("Warning", "Select at least one")
                return
            
            color_keys = list(self.available_colors.keys())
            
            if orient == "vertical":
                if time_series_var.get():
                    tcol = time_col_var.get()
                    if not tcol or tcol not in df.columns:
                        messagebox.showwarning("Warning", "Select a valid time column")
                        return
                    tseries = self._numeric_series(df, tcol)
                    unit = time_unit_var.get()
                    if unit == 'ms':
                        tseries = tseries / 1000.0
                    tlist = tseries.tolist()
                    for idx, col in enumerate(selected):
                        # The selected time column is X, not its own dataset.
                        if col == tcol:
                            continue
                        yseries = self._numeric_series(df, col)
                        pairs = [
                            (float(x), float(y))
                            for x, y in zip(tlist, yseries.tolist())
                            if x is not None and y is not None
                            and np.isfinite(x) and np.isfinite(y)
                        ]
                        if not pairs:
                            continue
                        pairs.sort(key=lambda p: p[0])
                        xs = [p[0] for p in pairs]
                        ys = [p[1] for p in pairs]
                        dataset_name = str(col)
                        counter = 1
                        while dataset_name in self.datasets:
                            dataset_name = f"{col}_{counter}"
                            counter += 1
                        color = self.available_colors[color_keys[idx % len(color_keys)]]
                        self.datasets[dataset_name] = {
                            'sizes': xs,
                            'data': [[val] for val in ys],
                            'color': color
                        }
                        self.dataset_listbox.insert(tk.END, dataset_name)
                        self.dataset_listbox.itemconfig(tk.END, bg=color)
                    try:
                        xmin = float(np.nanmin(tseries))
                        xmax = float(np.nanmax(tseries))
                        if np.isfinite(xmin) and np.isfinite(xmax):
                            self.xaxis_mode.set("numeric")
                            self.x_unit_combo.set("s")
                            self.use_custom_x_ticks_var.set(True)
                            self.x_tick_min_var.set(xmin)
                            self.x_tick_max_var.set(xmax)
                            self.x_tick_step_var.set(float(tick_step_var.get()))
                            self.chart_type_var.set("line")
                            self.show_connecting_line_var.set(True)
                    except Exception:
                        pass
                else:
                    for idx, col in enumerate(selected):
                        yseries = self._numeric_series(df, col)
                        # Use the real row position as X so dropping blank cells
                        # no longer shifts every remaining point.
                        pairs = [
                            (float(row_number) + 1.0, float(y))
                            for row_number, y in enumerate(yseries.tolist())
                            if y is not None and np.isfinite(y)
                        ]
                        if not pairs:
                            continue
                        dataset_name = str(col)
                        counter = 1
                        while dataset_name in self.datasets:
                            dataset_name = f"{col}_{counter}"
                            counter += 1
                        color = self.available_colors[color_keys[idx % len(color_keys)]]
                        self.datasets[dataset_name] = {
                            'sizes': [p[0] for p in pairs],
                            'data': [[p[1]] for p in pairs],
                            'color': color
                        }
                        self.dataset_listbox.insert(tk.END, dataset_name)
                        self.dataset_listbox.itemconfig(tk.END, bg=color)
            else:
                for idx, row_idx in enumerate(selected):
                    row = df.iloc[row_idx]
                    if len(row) == 0:
                        continue
                    # Column 0 holds the series name; the rest are measurements.
                    label = row.iloc[0] if len(row) > 1 else f"Row_{row_idx}"
                    pairs = []
                    for column_position, value in enumerate(row.tolist()):
                        if column_position == 0 and len(row) > 1:
                            continue
                        try:
                            numeric = float(value)
                        except (TypeError, ValueError):
                            continue
                        if np.isfinite(numeric):
                            pairs.append((float(column_position), numeric))
                    if not pairs:
                        continue
                    dataset_name = str(label)
                    base_name = dataset_name
                    counter = 1
                    while dataset_name in self.datasets:
                        dataset_name = f"{base_name}_{counter}"
                        counter += 1
                    color = self.available_colors[color_keys[idx % len(color_keys)]]
                    self.datasets[dataset_name] = {
                        'sizes': [p[0] for p in pairs],
                        'data': [[p[1]] for p in pairs],
                        'color': color
                    }
                    self.dataset_listbox.insert(tk.END, dataset_name)
                    self.dataset_listbox.itemconfig(tk.END, bg=color)
            
            messagebox.showinfo("Success", f"Imported {len(selected)}")
            self.status_bar.config(text=f"Imported {len(selected)}")
            dialog.destroy()
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(btn_frame, text="Import", command=import_selected).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
    
    def generate_chart(self):
        if not self.datasets:
            messagebox.showwarning("Warning", "No datasets")
            return
        
        # 显示进度条
        progress_window = tk.Toplevel(self.root)
        progress_window.title("Processing...")
        progress_window.geometry("300x100")
        progress_window.transient(self.root)
        progress_window.resizable(False, False)
        progress_window.grab_set()
        progress_window.protocol("WM_DELETE_WINDOW", lambda: None)
        
        progress_label = ttk.Label(progress_window, text="Preparing data...")
        progress_label.pack(pady=10)
        
        progress_bar = ttk.Progressbar(progress_window, mode='indeterminate')
        progress_bar.pack(fill=tk.X, padx=20, pady=10)
        progress_bar.start()
        
        def process_chart():
            try:
                self.chart_title = self.title_entry.get()
                self.xlabel = self.xlabel_entry.get()
                self.ylabel = self.ylabel_entry.get()
                self.x_unit = self.x_unit_combo.get()
                self.y_unit = self.y_unit_combo.get()
                
                progress_label.config(text="Calculating statistics...")
                progress_window.update_idletasks()
                chart_data = prepare_chart_data(self.datasets)
                try:
                    total_ds = len(self.datasets)
                    valid_ds = len(chart_data)
                    if valid_ds < total_ds:
                        invalid = []
                        for nm, ds in self.datasets.items():
                            ok, _msg = validate_dataset(ds['sizes'], ds['data'])
                            if not ok:
                                invalid.append(nm)
                        if invalid:
                            self.status_bar.config(
                                text=f"Valid datasets: {valid_ds}/{total_ds}; "
                                     f"skipped: {', '.join(invalid[:10])}")
                        else:
                            self.status_bar.config(text=f"Valid datasets: {valid_ds}/{total_ds}")
                    else:
                        self.status_bar.config(text=f"Valid datasets: {valid_ds}/{total_ds}")
                except Exception:
                    pass
                
                if not chart_data:
                    progress_bar.stop()
                    progress_window.destroy()
                    messagebox.showwarning("Warning", "No valid data")
                    return
                
                # Apply fitting if selected
                fit_method = normalize_option_value(self.fit_method_var.get(), FIT_METHOD_OPTIONS, "none")
                if fit_method != "none":
                    progress_label.config(text="Applying processing...")
                    progress_window.update_idletasks()
                    chart_data = self._apply_fitting(chart_data, fit_method)
                
                progress_label.config(text="Rendering chart...")
                progress_window.update_idletasks()
                settings = make_settings(self._collect_settings())
                
                if self.chart_manager is None:
                    progress_bar.stop()
                    progress_window.destroy()
                    messagebox.showerror("Error", "Chart manager not initialized")
                    return
                    
                self.chart_manager.generate_chart(chart_data, settings)
                # Keep the GUI's axis reference in sync: the chart manager
                # rebuilds the axes on every render.
                self.ax = self.chart_manager.ax
                self._update_statistics(chart_data)
                
                progress_bar.stop()
                progress_window.destroy()
                self.status_bar.config(text="Preview updated")
                
            except Exception as e:
                progress_bar.stop()
                progress_window.destroy()
                messagebox.showerror("Error", f"Failed:\n{str(e)}")
                import traceback
                traceback.print_exc()
        
        # 在新线程中处理，避免UI卡死
        progress_window.update_idletasks()
        self.root.after(10, process_chart)

    def _collect_settings(self):
        """Read every chart setting from the widgets into a plain dictionary.

        The result is completed and validated by ``chart_builder.make_settings``,
        which the CLI also uses, so both front ends render identically.
        """
        settings = {
            # Read the widgets directly so exporting after an edit always uses
            # what is on screen, not the values from the last preview.
            'title': self.title_entry.get(),
            'xlabel': self.xlabel_entry.get(),
            'ylabel': self.ylabel_entry.get(),
            'x_unit': self.x_unit_combo.get(),
            'y_unit': self.y_unit_combo.get(),
            'chart_type': self.chart_type_var.get(),
            'xaxis_mode': self.xaxis_mode.get(),
            'visual_preset': normalize_option_value(
                self.visual_preset_var.get(), VISUAL_PRESET_OPTIONS, "default"),
            'errorbar_mode': normalize_option_value(
                self.errorbar_mode_var.get(), ERRORBAR_MODE_OPTIONS, "summary"),
            'errorbar_metric': self.errorbar_metric_var.get(),
            'errorbar_capsize': self.errorbar_capsize_var.get(),
            'errorbar_linewidth': self.errorbar_linewidth_var.get(),
            'errorbar_show_mean': self.errorbar_show_mean_var.get(),
            'errorbar_show_max': self.errorbar_show_max_var.get(),
            'errorbar_show_min': self.errorbar_show_min_var.get(),
            'errorbar_show_error': self.errorbar_show_error_var.get(),
            'show_max': self.show_max_var.get(),
            'show_min': self.show_min_var.get(),
            'show_mean': self.show_mean_var.get(),
            'show_connecting_line': self.show_connecting_line_var.get(),
            'show_error_bars_line': self.show_error_bars_line_var.get(),
            'line_color': self.line_color,
            'bar_color': self.bar_color,
            'bar_style': normalize_option_value(
                self.bar_style_var.get(), BAR_STYLE_OPTIONS, "solid"),
            'bar_edge_width': self.bar_edge_width_var.get(),
            'point_alpha': self.point_alpha_var.get(),
            'errorbar_color': self.errorbar_color,
            'line_style': self.line_style_var.get(),
            'line_width': self.line_width_var.get(),
            'marker_size': self.marker_size_var.get(),
            'x_tick_count': self.x_tick_count_var.get(),
            'y_tick_count': self.y_tick_count_var.get(),
            'tick_label_size': self.tick_label_size_var.get(),
            'tick_label_bold': self.tick_label_bold_var.get(),
            'x_tick_rotation': self.x_tick_rotation_var.get(),
            'tick_length': self.tick_length_var.get(),
            'tick_width': self.tick_width_var.get(),
            'use_custom_x_ticks': self.use_custom_x_ticks_var.get(),
            'x_tick_min': self.x_tick_min_var.get(),
            'x_tick_max': self.x_tick_max_var.get(),
            'x_tick_step': self.x_tick_step_var.get(),
            'use_custom_y_ticks': self.use_custom_y_ticks_var.get(),
            'y_tick_min': self.y_tick_min_var.get(),
            'y_tick_max': self.y_tick_max_var.get(),
            'y_tick_step': self.y_tick_step_var.get(),
            'auto_x_ticks': self.auto_x_ticks_var.get(),
            'auto_y_ticks': self.auto_y_ticks_var.get(),
            'force_origin_zero': self.force_origin_zero_var.get(),
            'show_minor_ticks': self.show_minor_ticks_var.get(),
            'legend_font_size': self.legend_font_size_var.get(),
            'legend_marker_size': self.legend_marker_size_var.get(),
            'show_legend': self.show_legend_var.get(),
            'legend_loc': self.legend_loc_var.get(),
            'legend_ncol': self.legend_ncol_var.get(),
            'axis_label_font_size': self.axis_label_font_size_var.get(),
            'title_font_size': self.title_font_size_var.get(),
            'label_font_size': self.font_size_var.get(),
            'show_data_labels': self.show_data_labels_var.get(),
            'reverse_y_axis': self.reverse_y_axis_var.get(),
            'use_broken_y_axis': self.use_broken_y_axis_var.get(),
            'broken_y_bot_min': self.broken_y_bot_min_var.get(),
            'broken_y_bot_max': self.broken_y_bot_max_var.get(),
            'broken_y_top_min': self.broken_y_top_min_var.get(),
            'broken_y_top_max': self.broken_y_top_max_var.get(),
            'use_broken_x_axis': self.use_broken_x_axis_var.get(),
            'broken_x_left_min': self.broken_x_left_min_var.get(),
            'broken_x_left_max': self.broken_x_left_max_var.get(),
            'broken_x_right_min': self.broken_x_right_min_var.get(),
            'broken_x_right_max': self.broken_x_right_max_var.get(),
            'label_content': normalize_option_value(
                self.label_content_var.get(), LABEL_CONTENT_OPTIONS, "y"),
            'export_mode': normalize_option_value(
                self.export_mode_var.get() if hasattr(self, 'export_mode_var') else None,
                EXPORT_MODE_OPTIONS, "match_preview"),
            'export_dpi': self.fig_dpi_var.get(),
            'fig_width': self.fig_width_var.get(),
            'fig_height': self.fig_height_var.get(),
            'export_tight_bbox': self.export_tight_bbox_var.get(),
        }
        return settings
    
    def _update_statistics(self, chart_data):
        """更新统计信息，优化大数据量处理"""
        self.stats_text.delete(1.0, tk.END)
        
        y_unit = self.y_unit if self.y_unit and self.y_unit != '(none)' else ""
        unit_suffix = f" {y_unit}" if y_unit else ""
        
        # 限制显示的统计信息数量，避免UI卡死
        MAX_DISPLAY_DATASETS = 50
        MAX_DISPLAY_POINTS = 100
        
        dataset_names = list(chart_data.keys())
        
        if len(dataset_names) > MAX_DISPLAY_DATASETS:
            self.stats_text.insert(tk.END, f"Too many datasets; showing the first {MAX_DISPLAY_DATASETS}\n")
            self.stats_text.insert(tk.END, f"{len(dataset_names)} datasets in total\n")
            self.stats_text.insert(tk.END, "=" * 60 + "\n")
            dataset_names = dataset_names[:MAX_DISPLAY_DATASETS]
        
        for name in dataset_names:
            data = chart_data[name]
            sizes = data['sizes']
            stats = data['stats']
            
            self.stats_text.insert(tk.END, f"\n{name}:\n")
            self.stats_text.insert(tk.END, "-" * 60 + "\n")
            
            # 如果数据点过多，只显示部分数据
            if len(sizes) > MAX_DISPLAY_POINTS:
                self.stats_text.insert(tk.END, f"Too many points; showing the first {MAX_DISPLAY_POINTS}\n")
                display_indices = range(min(MAX_DISPLAY_POINTS, len(sizes)))
            else:
                display_indices = range(len(sizes))
            
            for i in display_indices:
                line = (f"X={sizes[i]}: "
                       f"Mean={stats['mean'][i]:.4f}{unit_suffix}, "
                       f"SD={stats['std'][i]:.4f}{unit_suffix}, "
                       f"Max={stats['max'][i]:.4f}{unit_suffix}, "
                       f"Min={stats['min'][i]:.4f}{unit_suffix}\n")
                self.stats_text.insert(tk.END, line)
            
            if len(sizes) > MAX_DISPLAY_POINTS:
                self.stats_text.insert(tk.END, f"... {len(sizes) - MAX_DISPLAY_POINTS} more points\n")
            
            self.stats_text.insert(tk.END, "\n")
    
    def clear_plot(self):
        if self.chart_manager:
            self.chart_manager.clear_chart()
        self.stats_text.delete(1.0, tk.END)
        self.status_bar.config(text="Preview cleared")
    
    def export_plot(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("PDF files", "*.pdf"), 
                      ("SVG files", "*.svg"), ("All files", "*.*")]
        )
        
        if file_path:
            try:
                settings = make_settings(self._collect_settings())
                export_mode = settings['export_mode']
                if export_mode == "match_preview":
                    width, height = [float(v) for v in self.fig.get_size_inches()]
                else:
                    width = settings['fig_width']
                    height = settings['fig_height']
                dpi = settings['export_dpi']
                tight_bbox = settings['export_tight_bbox']

                # Same export path as the CLI, so both produce identical files.
                export_figure(self.fig, file_path, settings,
                              width=width, height=height,
                              dpi=dpi, tight=tight_bbox)
                self.canvas.draw()
                
                file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                
                # Calculate actual pixel dimensions
                pixel_width = int(width * dpi)
                pixel_height = int(height * dpi)
                
                mode_label = get_option_label(export_mode, EXPORT_MODE_OPTIONS, "Match Preview")
                self.status_bar.config(text=f"Saved ({mode_label}): {pixel_width}x{pixel_height}px")
                messagebox.showinfo("Success", 
                    f"Saved!\n\n"
                    f"File: {os.path.basename(file_path)}\n"
                    f"Mode: {mode_label}\n"
                    f"Size: {width}x{height} inches ({pixel_width}x{pixel_height} px)\n"
                    f"DPI: {dpi}\n"
                    f"Auto crop: {'On' if tight_bbox else 'Off'}\n"
                    f"File: {file_size_mb:.2f} MB")
            except Exception as e:
                messagebox.showerror("Error", f"Failed:\n{str(e)}")

    def _apply_fitting(self, chart_data, fit_method):
        """Apply the selected processing method; shared with the CLI."""
        try:
            return apply_processing(
                chart_data,
                method=fit_method,
                degree=int(self.poly_degree_var.get()),
                show_raw=bool(self.show_raw_data_var.get()),
                show_fit=bool(self.show_fit_curve_var.get()),
                add_jitter=bool(self.add_jitter_var.get()),
            )
        except Exception as e:
            messagebox.showwarning("Fitting Warning", f"Could not apply fitting: {str(e)}")
            return chart_data

