"""
Chart generation and management functionality
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, FormatStrFormatter
from matplotlib.ticker import MultipleLocator, FormatStrFormatter


class ChartManager:
    """
    Manages chart generation, styling, and label positioning
    """
    
    def __init__(self, ax, canvas, drag_radius_factor=0.5, toolbar=None):
        """
        Initialize chart manager
        
        Args:
            ax: matplotlib axis
            canvas: matplotlib canvas
            drag_radius_factor: factor for calculating drag radius
            toolbar: NavigationToolbar (用于检测/切换平移缩放状态)
        """
        self.ax = ax
        self.canvas = canvas
        self.drag_radius_factor = drag_radius_factor
        self.toolbar = toolbar
        # 重新启用基础的标签拖动支持（轻量实现）
        self._dragging_text = None
        self._placed_labels = []
        # 移除可拖拽标签相关功能以提高性能
        # self.draggable_labels = []
        # self._placed_labels = []
        # 鼠标滚轮缩放/调整内容大小支持
        self._base_scroll_scale = 1.2
        try:
            # 绑定交互事件（TkAgg 后端）
            self._scroll_cid = self.canvas.mpl_connect('scroll_event', self._on_scroll)
            self._press_cid = self.canvas.mpl_connect('button_press_event', self._on_press)
            self._release_cid = self.canvas.mpl_connect('button_release_event', self._on_release)
            self._motion_cid = self.canvas.mpl_connect('motion_notify_event', self._on_motion)
        except Exception:
            self._scroll_cid = None
            self._press_cid = None
            self._release_cid = None
            self._motion_cid = None
    
    def clear_chart(self):
        """Clear the chart and reset labels"""
        self.ax.clear()
        if self.ax.get_legend() is not None:
            self.ax.get_legend().remove()
        self.canvas.draw()
        # 移除可拖拽标签清理（功能已禁用）
        # self._clear_draggable_labels()
        # self._placed_labels = []
    
    def _clear_draggable_labels(self):
        """Disconnect and clear all draggable labels - 功能已禁用"""
        # 可拖拽标签功能已禁用，此函数不再使用
        pass
    
    def generate_chart(self, chart_data, settings):
        """
        Generate chart with data and apply settings
        
        Args:
            chart_data: Dictionary of processed chart data
            settings: Dictionary containing chart settings
        """
        self.clear_chart()

        # Extract settings
        chart_type = settings.get('chart_type', 'line')
        xaxis_mode = settings.get('xaxis_mode', 'categorical')
        show_mean = settings.get('show_mean', True)
        show_max = settings.get('show_max', False)
        show_min = settings.get('show_min', False)
        show_connecting_line = settings.get('show_connecting_line', False)
        line_color = settings.get('line_color', '#d62728')
        line_style = settings.get('line_style', 'solid')
        line_width = float(settings.get('line_width', 2.0))
        # Marker size UI uses points (pt); scatter requires area in pt^2
        marker_size = float(settings.get('marker_size', 10))
        label_font_size = settings.get('label_font_size', 10)
        show_data_labels = settings.get('show_data_labels', False)
        y_unit = settings.get('y_unit', '')

        # Convert line style
        linestyle_map = {
            'solid': '-',
            'dashed': '--'
        }
        linestyle = linestyle_map.get(line_style, '-')

        # Generate chart based on type (single pass)
        if chart_type == 'pie':
            self._generate_pie_chart(chart_data, settings)
        elif chart_type == 'errorbar':
            self._generate_errorbar_chart(
                chart_data, settings, xaxis_mode, show_connecting_line,
                line_color, linestyle, line_width, marker_size, label_font_size,
                show_data_labels, y_unit
            )
        elif chart_type == 'bar':
            self._generate_bar_chart(
                chart_data, settings, xaxis_mode,
                line_color, line_width, label_font_size, show_data_labels, y_unit
            )
        else:
            # Covers 'line', 'scatter', 'line_scatter' and fallback
            self._generate_line_chart(
                chart_data, settings, xaxis_mode,
                show_mean, show_max, show_min, show_connecting_line,
                line_color, linestyle, line_width, marker_size, label_font_size,
                show_data_labels, y_unit
            )

        # Apply chart styling and render once
        self._apply_chart_styling(settings)
        self.canvas.draw()
    
    def _generate_line_chart(self, chart_data, settings, xaxis_mode,
                           show_mean, show_max, show_min, show_connecting_line,
                           line_color, linestyle, line_width, marker_size, label_font_size,
                           show_data_labels, y_unit):
        """Generate line/scatter chart"""
        # Unit suffix for labels
        unit_suffix = f" {y_unit}" if y_unit and y_unit != '(none)' else ""
        
        # Track data ranges for label positioning
        all_x_values = []
        all_y_values = []
        
        dataset_idx = 0
        
        for name, data in chart_data.items():
            sizes = data['sizes']
            data_list = data['data']
            color = data['color']
            stats = data['stats']
            
            mean_forces = stats['mean']
            std_forces = stats['std']
            max_forces = stats['max']
            min_forces = stats['min']
            
            # Determine x positions
            if xaxis_mode == 'categorical':
                if dataset_idx == 0:
                    x_positions = np.arange(len(sizes))
                    self.ax.set_xticks(x_positions)
                    self.ax.set_xticklabels([str(s) for s in sizes])
                else:
                    x_positions = np.arange(len(sizes))
            else:  # numerical
                x_positions = np.array(sizes)
            
            all_x_values.extend(x_positions)
            all_y_values.extend(mean_forces)
            
            # Check for special display modes
            show_as_raw = data.get('show_as_raw', False)
            is_fit_curve = data.get('is_fit_curve', False)
            add_jitter = data.get('add_jitter', False)
            
            # Handle different display modes
            if is_fit_curve:
                # Display only the smooth fit curve (no scatter points)
                self.ax.plot(x_positions, mean_forces, color=color,
                           linewidth=float(line_width), alpha=0.9, 
                           linestyle=linestyle, zorder=8, label=name)
            
            elif show_as_raw:
                # Display all raw data points as scatter with optional jitter
                point_alpha = float(settings.get('point_alpha', 0.7))
                
                # Flatten all raw data points
                x_flat = []
                y_flat = []
                for i, x_val in enumerate(x_positions):
                    if i < len(data_list) and dataist[i]:
                        y_vals = data_list[i]
                        x_flat.extend([x_val] * len(y_vals))
                        y_flat.extend(y_vals)
                
                if len(x_flat) > 0:
                    x_arr = np.array(x_flat)
                    y_arr = np.array(y_flat)
                    
                    # Apply jitter if requested
                    if add_jitter and len(x_positions) > 1:
                        x_range = max(x_positions) - min(x_positions)
                        jitter_amount = x_range * 0.01  # 1% of range
                        x_jittered = x_arr + np.random.uniform(-jitter_amount, jitter_amount, len(x_arr))
                    else:
                        x_jittered = x_arr
                    
                    # Plot all raw data points
                    self.ax.scatter(x_jittered, y_arr, color=color, 
                                  alpha=point_alpha, s=marker_size**2, 
                                  label=name, zorder=5, edgecolors='none')
            
            else:
                # Standard mode: show mean/max/min with optional connecting lines
                # Use dataset-specific marker or fallback to default circle
                # Marker size UI uses points (pt); scatter requires area in pt^2
                ds_marker = data.get('marker', 'o')
                
                # Plot mean scatter points with custom marker
                if show_mean:
                    self.ax.scatter(x_positions, mean_forces, s=(marker_size ** 2), 
                                  color=color, label=name, alpha=0.8, 
                                  edgecolors=(color if ds_marker == 'x' or ds_marker == '+' else 'black'), # Black edge except for line-only markers
                                  linewidths=1.0, marker=ds_marker, zorder=10)
                
                # Connect lines
                if show_connecting_line:
                    self.ax.plot(x_positions, mean_forces, color=color, # Use dataset color for line
                               linewidth=float(line_width), alpha=0.9, linestyle=linestyle, zorder=5, label=name)
                
                # Draw Error Bars if available (for Multi-Line Chart)
                # Check if this dataset has pre-calculated errors (from multi-line import)
                # AND if the user wants to show them
                show_err = settings.get('show_error_bars_line', True)
                y_errors = data.get('y_errors')
                
                if show_err and y_errors is not None and len(y_errors) > 0:
                     # Draw error bars without markers (markers are drawn by scatter above)
                     self.ax.errorbar(x_positions, mean_forces, yerr=y_errors, 
                                    fmt='none', # No marker here
                                    ecolor=color, # Error bar color same as data color
                                    elinewidth=float(line_width) * 0.8, 
                                    capsize=4, 
                                    zorder=4)
    
                # Plot max/min markers (only if not multiline chart mode, usually)
                if not data.get('is_multiline', False):
                    if show_max:
                        self.ax.scatter(x_positions, max_forces, s=30, 
                                      color=color, marker='^', alpha=0.5)
                    if show_min:
                        self.ax.scatter(x_positions, min_forces, s=30, 
                                      color=color, marker='v', alpha=0.5)
                
                # Add data labels
                if show_data_labels:
                    self._add_data_labels(x_positions, mean_forces, sizes, 
                                        label_font_size, color, unit_suffix,
                                        all_x_values, all_y_values,
                                        settings.get('label_content','y'))
            
            dataset_idx += 1
    
    def _generate_pie_chart(self, chart_data, settings):
        """Generate pie chart from data"""
        # For pie chart, we use the first dataset only
        if not chart_data:
            return
        
        first_dataset = next(iter(chart_data.values()))
        sizes = first_dataset['sizes']
        data_list = first_dataset['data']
        color = first_dataset['color']
        stats = first_dataset['stats']
        
        # Calculate percentages for pie chart
        mean_values = stats['mean']
        total = sum(mean_values)
        
        if total == 0:
            return
        
        percentages = [val / total * 100 for val in mean_values]
        
        # Generate labels with percentages
        labels = [f"{size}\n{percent:.1f}%" for size, percent in zip(sizes, percentages)]
        
        # Generate colors for pie chart
        colors = plt.cm.Set3(np.linspace(0, 1, len(sizes)))
        
        # Create pie chart
        wedges, texts = self.ax.pie(mean_values, labels=labels, colors=colors,
                                   autopct='', startangle=90)
        
        # Equal aspect ratio ensures that pie is drawn as a circle
        self.ax.axis('equal')
        
        # Add title
        chart_title = settings.get('chart_title', 'Pie Chart')
        if chart_title and chart_title != '(none)':
            self.ax.set_title(chart_title, fontsize=14, fontweight='bold')

    def _generate_errorbar_summary_chart(self, chart_data, settings,
                                         show_connecting_line, line_color, linestyle,
                                         line_width, marker_size, label_font_size, y_unit):
        """按数据集汇总绘制误差条图：每个数据集一个点（均值）+误差条（±SD）"""
        if not chart_data:
            return

        unit_suffix = f" {y_unit}" if y_unit and y_unit != '(none)' else ""

        capsize = int(settings.get('errorbar_capsize', 7))
        elw = float(settings.get('errorbar_linewidth', 2.0))
        metric = settings.get('errorbar_metric', 'SD')  # SD 或 SEM
        # 独立的误差线颜色（优先使用用户设置）
        errorbar_color = settings.get('errorbar_color', None)

        names = list(chart_data.keys())
        x_positions = np.arange(len(names))

        means = []
        errors = []
        colors = []
        max_vals = []
        min_vals = []

        for name in names:
            d = chart_data[name]
            # 汇总该数据集的所有数值（跨尺寸/类别）
            all_vals = []
            total_n = 0
            for grp in d['data']:
                if grp:
                    all_vals.extend(grp)
                    total_n += len(grp)
            if len(all_vals) == 0:
                means.append(0.0)
                errors.append(0.0)
                max_vals.append(0.0)
                min_vals.append(0.0)
            else:
                arr = np.array(all_vals)
                means.append(float(np.mean(arr)))
                sd = float(np.std(arr))
                if metric == 'SEM' and total_n > 1:
                    errors.append(sd / float(np.sqrt(total_n)))
                else:
                    errors.append(sd)
                max_vals.append(float(np.max(arr)))
                min_vals.append(float(np.min(arr)))
            colors.append(d.get('color', '#1f77b4'))

        # 设置X轴分类标签
        self.ax.set_xticks(x_positions)
        self.ax.set_xticklabels(names)

        show_mean_point = bool(settings.get('errorbar_show_mean', True))
        show_max_point = bool(settings.get('errorbar_show_max', False))
        show_min_point = bool(settings.get('errorbar_show_min', False))
        show_error_bars = bool(settings.get('errorbar_show_error', True))

        # 绘制每个数据集的误差条（以及中心点）
        for i, (x, m, s, c, name) in enumerate(zip(x_positions, means, errors, colors, names)):
            if show_error_bars and show_mean_point:
                # 同时显示误差条与均值点
                self.ax.errorbar(
                    x, m, yerr=s,
                    fmt='o', color=c,
                    ecolor=(errorbar_color if errorbar_color else c), elinewidth=elw, capsize=capsize, capthick=elw,
                    markersize=marker_size,
                    alpha=1.0, zorder=10, label=name
                )
            elif show_error_bars and not show_mean_point:
                # 仅显示误差条，不显示点
                self.ax.errorbar(
                    x, m, yerr=s,
                    fmt='none', color=c,
                    ecolor=(errorbar_color if errorbar_color else c), elinewidth=elw, capsize=capsize, capthick=elw,
                    alpha=1.0, zorder=10, label=name
                )
            elif show_mean_point and not show_error_bars:
                # 仅显示均值点
                self.ax.scatter(x, m, s=marker_size**2, color=c, zorder=10, label=name)
            else:
                # 两者都不显示，仅保留连接线（若启用）
                pass

            # 可选显示最大/最小值
            try:
                if show_max_point:
                    self.ax.scatter(x, max_vals[i], s=30, color=c, marker='^', alpha=0.7)
                if show_min_point:
                    self.ax.scatter(x, min_vals[i], s=30, color=c, marker='v', alpha=0.7)
            except Exception:
                pass

            if settings.get('show_data_labels', False) and show_mean_point:
                # 仅为每个数据集显示一次均值标签
                offset = (s if (show_error_bars and s > 0) else (max(errors) * 0.05 if (show_error_bars and len(errors) > 0) else 0.0))
                self.ax.text(
                    x, m + offset,
                    f"Mean: {m:.4f}{unit_suffix}",
                    ha='center', va='bottom', fontsize=label_font_size,
                    color=c, weight='bold'
                )

        # 连接各数据集的均值，形成总趋势线
        if show_connecting_line and len(means) > 1:
            self.ax.plot(
                x_positions, means,
                color=line_color, linestyle=linestyle, linewidth=float(line_width),
                alpha=0.85, zorder=5
            )
    
    def _generate_errorbar_chart(self, chart_data, settings, xaxis_mode, show_connecting_line,
                                 line_color, linestyle, line_width, marker_size, label_font_size,
                                 show_data_labels, y_unit):
        """根据模式（summary 或 per_size）绘制误差条图"""
        mode = settings.get('errorbar_mode', 'summary')
        if mode == 'summary':
            return self._generate_errorbar_summary_chart(
                chart_data, settings, show_connecting_line,
                line_color, linestyle, line_width, marker_size, label_font_size, y_unit
            )

        # per_size 模式
        unit_suffix = f" {y_unit}" if y_unit and y_unit != '(none)' else ""
        capsize = int(settings.get('errorbar_capsize', 7))
        elw = float(settings.get('errorbar_linewidth', 2.0))
        metric = settings.get('errorbar_metric', 'SD')
        show_mean_point = bool(settings.get('errorbar_show_mean', True))
        show_max_point = bool(settings.get('errorbar_show_max', False))
        show_min_point = bool(settings.get('errorbar_show_min', False))
        show_error_bars = bool(settings.get('errorbar_show_error', True))
        # 独立误差线颜色
        errorbar_color = settings.get('errorbar_color', None)

        all_x_values = []
        all_y_values = []
        dataset_idx = 0

        for name, data in chart_data.items():
            sizes = data['sizes']
            data_list = data['data']
            color = data['color']
            stats = data['stats']

            mean_forces = stats['mean']
            std_forces = stats['std']
            max_forces = stats.get('max', None)
            min_forces = stats.get('min', None)

            # 计算误差：SD 或 SEM
            if metric == 'SEM':
                counts = [len(g) if g is not None else 0 for g in data_list]
                errors = [ (sd / np.sqrt(n)) if (n and n > 1) else 0.0 for sd, n in zip(std_forces, counts) ]
            else:
                errors = std_forces

            # x 位置
            if xaxis_mode == 'categorical':
                if dataset_idx == 0:
                    x_positions = np.arange(len(sizes))
                    self.ax.set_xticks(x_positions)
                    self.ax.set_xticklabels([str(s) for s in sizes])
                else:
                    x_positions = np.arange(len(sizes))
            else:  # numerical
                x_positions = np.array(sizes)

            # 绘制误差条/均值点，受开关控制
            if show_error_bars and show_mean_point:
                self.ax.errorbar(
                    x_positions, mean_forces,
                    yerr=np.asarray(errors), fmt='o',
                    color=color, ecolor=(errorbar_color if errorbar_color else color), elinewidth=elw, capsize=capsize, capthick=elw,
                    markersize=marker_size,
                    alpha=1.0, zorder=10, label=name
                )
            elif show_error_bars and not show_mean_point:
                self.ax.errorbar(
                    x_positions, mean_forces,
                    yerr=np.asarray(errors), fmt='none',
                    color=color, ecolor=(errorbar_color if errorbar_color else color), elinewidth=elw, capsize=capsize, capthick=elw,
                    alpha=1.0, zorder=10, label=name
                )
            elif show_mean_point and not show_error_bars:
                self.ax.scatter(x_positions, mean_forces, s=marker_size**2, color=color, zorder=10, label=name)
            else:
                pass

            # 可选显示最大/最小值（per_size）
            try:
                if show_max_point and max_forces is not None:
                    self.ax.scatter(x_positions, max_forces, s=30, color=color, marker='^', alpha=0.7)
                if show_min_point and min_forces is not None:
                    self.ax.scatter(x_positions, min_forces, s=30, color=color, marker='v', alpha=0.7)
            except Exception:
                pass

            # 连接均值形成趋势线（可选）
            if show_connecting_line:
                self.ax.plot(x_positions, mean_forces, color=line_color, linestyle=linestyle, linewidth=float(line_width), alpha=0.85)

            # 标签（可选）：与均值点开关联动
            if show_data_labels and show_mean_point:
                self._add_data_labels(x_positions, mean_forces, sizes,
                                      label_font_size, color, unit_suffix,
                                      all_x_values, all_y_values,
                                      settings.get('label_content','y'))

            all_x_values.extend(x_positions)
            all_y_values.extend(mean_forces)

            dataset_idx += 1
    
    def _generate_bar_chart(self, chart_data, settings, xaxis_mode,
                             line_color, line_width, label_font_size, show_data_labels, y_unit):
        """绘制带误差条的柱状图。
        支持两种模式：
        - summary：每个数据集一根柱（总均值）+ 误差（SD/SEM）
        - per_size：每个尺寸/类别一组柱，按数据集并排显示 + 误差
        """
        if not chart_data:
            return

        unit_suffix = f" {y_unit}" if y_unit and y_unit != '(none)' else ""
        mode = settings.get('errorbar_mode', 'summary')
        capsize = int(settings.get('errorbar_capsize', 7))
        elw = float(settings.get('errorbar_linewidth', 2.0))
        metric = settings.get('errorbar_metric', 'SD')
        show_error_bars = bool(settings.get('errorbar_show_error', True))
        bar_color_override = settings.get('bar_color', None)
        errorbar_color_override = settings.get('errorbar_color', None)

        base_bar_width = 0.7
        bar_edge_width = float(settings.get('bar_edge_width', 1.0))

        if mode == 'summary':
            names = list(chart_data.keys())
            x_positions = np.arange(len(names))
            means = []
            errors = []
            colors = []

            for name in names:
                d = chart_data[name]
                all_vals = []
                total_n = 0
                for grp in d['data']:
                    if grp:
                        all_vals.extend(grp)
                        total_n += len(grp)
                if len(all_vals) == 0:
                    means.append(0.0)
                    errors.append(0.0)
                else:
                    arr = np.array(all_vals)
                    m = float(np.mean(arr))
                    sd = float(np.std(arr))
                    e = (sd / float(np.sqrt(total_n))) if (metric == 'SEM' and total_n > 1) else sd
                    means.append(m)
                    errors.append(e)
                colors.append(d.get('color', '#1f77b4'))

            self.ax.set_xticks(x_positions)
            self.ax.set_xticklabels(names)

        for x, m, e, c, name in zip(x_positions, means, errors, colors, names):
            error_kw = {
                'lw': elw,
                'capthick': elw,
                'ecolor': (errorbar_color_override if errorbar_color_override else 'black')
            }
            base_col = (bar_color_override if bar_color_override else c)
            style = str(settings.get('bar_style', 'solid')).lower()
            facecolor = base_col
            edgecolor = None
            hatch = None
            fill_flag = True
            if style == 'white':
                facecolor = 'white'; edgecolor = base_col
            elif style == 'none':
                facecolor = base_col; edgecolor = base_col; fill_flag = False
            elif style == 'mesh':
                facecolor = 'white'; edgecolor = base_col; hatch = 'xx'
            elif style == 'diagonal':
                facecolor = 'white'; edgecolor = base_col; hatch = '//'
            elif style == 'dots':
                facecolor = 'white'; edgecolor = base_col; hatch = '..'
            elif style == 'solid' and bar_edge_width > 0:
                edgecolor = base_col

            bar_kwargs = {
                'width': base_bar_width,
                'color': facecolor,
                'alpha': 0.85,
                'label': name,
                'zorder': 6
            }
            if edgecolor is not None:
                bar_kwargs['edgecolor'] = edgecolor
            if hatch is not None:
                bar_kwargs['hatch'] = hatch
            if not fill_flag:
                bar_kwargs['fill'] = False
            if bar_edge_width is not None:
                bar_kwargs['linewidth'] = bar_edge_width

            if show_error_bars:
                self.ax.bar(x, m, yerr=e, capsize=capsize, error_kw=error_kw, **bar_kwargs)
            else:
                self.ax.bar(x, m, **bar_kwargs)

                if show_data_labels and bool(settings.get('errorbar_show_mean', True)):
                    offset = (e if (show_error_bars and e > 0) else 0.0)
                    self.ax.text(
                        x, m + offset,
                        f"{m:.4f}{unit_suffix}",
                        ha='center', va='bottom', fontsize=label_font_size,
                        color=(bar_color_override if bar_color_override else c), weight='bold'
                    )


        if mode == 'summary':
            return

        # per_size：每个尺寸一组柱，数据集并排
        first = next(iter(chart_data.values()))
        sizes = first['sizes']
        n_sizes = len(sizes)
        dataset_names = list(chart_data.keys())
        n_datasets = len(dataset_names)

        base_positions = np.arange(n_sizes)
        self.ax.set_xticks(base_positions)
        self.ax.set_xticklabels([str(s) for s in sizes])

        width = min(0.85 / max(n_datasets, 1), 0.45)
        offsets = (np.arange(n_datasets) - (n_datasets - 1) / 2.0) * width

        for j, name in enumerate(dataset_names):
            d = chart_data[name]
            color = d.get('color', '#1f77b4')
            means = []
            errors = []
            for i in range(n_sizes):
                grp = d['data'][i] if i < len(d['data']) else []
                if not grp:
                    means.append(0.0)
                    errors.append(0.0)
                else:
                    arr = np.array(grp)
                    m = float(np.mean(arr))
                    sd = float(np.std(arr))
                    e = (sd / float(np.sqrt(len(arr)))) if (metric == 'SEM' and len(arr) > 1) else sd
                    means.append(m)
                    errors.append(e)

            x_pos = base_positions + offsets[j]
            error_kw = {
                'lw': elw,
                'capthick': elw,
                'ecolor': (errorbar_color_override if errorbar_color_override else 'black')
            }
            base_col = (bar_color_override if bar_color_override else color)
            style = str(settings.get('bar_style', 'solid')).lower()
            facecolor = base_col
            edgecolor = None
            hatch = None
            fill_flag = True
            if style == 'white':
                facecolor = 'white'; edgecolor = base_col
            elif style == 'none':
                facecolor = base_col; edgecolor = base_col; fill_flag = False
            elif style == 'mesh':
                facecolor = 'white'; edgecolor = base_col; hatch = 'xx'
            elif style == 'diagonal':
                facecolor = 'white'; edgecolor = base_col; hatch = '//'
            elif style == 'dots':
                facecolor = 'white'; edgecolor = base_col; hatch = '..'
            elif style == 'solid' and bar_edge_width > 0:
                edgecolor = base_col

            bar_kwargs = {
                'width': width,
                'color': facecolor,
                'alpha': 0.85,
                'label': name,
                'zorder': 6
            }
            if edgecolor is not None:
                bar_kwargs['edgecolor'] = edgecolor
            if hatch is not None:
                bar_kwargs['hatch'] = hatch
            if not fill_flag:
                bar_kwargs['fill'] = False
            if bar_edge_width is not None:
                bar_kwargs['linewidth'] = bar_edge_width

            if show_error_bars:
                self.ax.bar(x_pos, means, yerr=errors, capsize=capsize, error_kw=error_kw, **bar_kwargs)
            else:
                self.ax.bar(x_pos, means, **bar_kwargs)

            if show_data_labels and bool(settings.get('errorbar_show_mean', True)):
                for xi, m, e in zip(x_pos, means, errors):
                    offset = (e if (show_error_bars and e > 0) else 0.0)
                    self.ax.text(
                        xi, m + offset,
                        f"{m:.4f}{unit_suffix}",
                        ha='center', va='bottom', fontsize=label_font_size,
                        color=(bar_color_override if bar_color_override else color), weight='bold'
                    )

    def _add_data_labels(self, x_positions, y_values, sizes, font_size, color, 
                        unit_suffix, all_x_values, all_y_values, label_content):
        """Add data labels to chart - 高性能优化版本"""
        # 严格限制数据标签数量，避免性能问题
        MAX_LABELS = 20  # 大幅减少到最多20个标签
        
        if len(x_positions) > MAX_LABELS:
            # 对于大量数据点，只显示部分标签（均匀分布）
            step = len(x_positions) // MAX_LABELS
            display_indices = range(0, len(x_positions), step)
        else:
            display_indices = range(len(x_positions))
        
        # Calculate data ranges for positioning
        x_range = max(all_x_values) - min(all_x_values) if len(all_x_values) > 1 else 1
        y_range = max(all_y_values) - min(all_y_values) if len(all_y_values) > 1 else 1
        
        # Get plot boundaries
        plot_x_min, plot_x_max = self.ax.get_xlim()
        plot_y_min, plot_y_max = self.ax.get_ylim()
        
        # Calculate offsets
        text_offset_x = x_range * 0.02
        text_offset_y = y_range * 0.03
        
        # 极简位置策略 - 只在数据点上方显示
        for i in display_indices:
            if i >= len(x_positions) or i >= len(y_values):
                continue
                
            x_pos = x_positions[i] if i < len(x_positions) else x_positions[-1]
            y_val = y_values[i] if i < len(y_values) else y_values[-1]
            
            label_text = f"({x_pos:.4f}, {y_val:.4f})" if label_content == 'xy' else f"{y_val:.4f}{unit_suffix}"
            
            label_x = x_pos
            try:
                inv = self.ax.yaxis_inverted()
            except Exception:
                inv = False
            label_y = y_val + ((-text_offset_y * 2) if inv else (text_offset_y * 2))
            
            # 检查边界
            if (label_x < plot_x_min or label_x > plot_x_max or
                label_y < plot_y_min or label_y > plot_y_max):
                continue
            
            try:
                # 创建可拖拽标签（轻量实现）
                txt = self.ax.text(label_x, label_y, label_text,
                                   ha='center', va='bottom', 
                                   fontsize=font_size,
                                   color=color, weight='bold')
                # 允许鼠标点击选择该文本用于拖动
                try:
                    txt.set_picker(True)
                except Exception:
                    pass
            except Exception:
                continue  # 忽略创建失败的标签
    
    def _generate_label_positions(self, x, y, offset_x, offset_y):
        """Generate candidate positions for label placement"""
        try:
            inv = self.ax.yaxis_inverted()
        except Exception:
            inv = False
        return [
            {'x': x, 'y': y + ((-offset_y * 2) if inv else (offset_y * 2)), 'ha': 'center', 'va': 'bottom', 'priority': 1},
            # Position 2: Below
            {'x': x, 'y': y - offset_y * 2, 'ha': 'center', 'va': 'top', 'priority': 2},
            # Position 3: Right
            {'x': x + offset_x * 3, 'y': y, 'ha': 'left', 'va': 'center', 'priority': 3},
            # Position 4: Left
            {'x': x - offset_x * 3, 'y': y, 'ha': 'right', 'va': 'center', 'priority': 4},
        ]
    
    def _choose_best_position(self, candidates, x_min, x_max, y_min, y_max, x_range, y_range):
        """Choose the best position from candidates avoiding overlaps"""
        candidates.sort(key=lambda p: p['priority'])
        
        for pos in candidates:
            # Check bounds
            if (pos['x'] < x_min or pos['x'] > x_max or
                pos['y'] < y_min or pos['y'] > y_max):
                continue
            
            # Check overlaps
            if not self._has_overlap(pos, x_range, y_range):
                return pos
        
        # If all positions have issues, return highest priority
        return candidates[0]
    
    def _get_simple_label_position(self, x, y, offset_x, offset_y, x_min, x_max, y_min, y_max):
        """简化的标签位置选择 - 提高性能"""
        # 尝试基础位置：上方
        try:
            inv = self.ax.yaxis_inverted()
        except Exception:
            inv = False
        pos = {
            'x': x,
            'y': y + ((-offset_y * 2) if inv else (offset_y * 2)),
            'ha': 'center',
            'va': 'bottom'
        }
        
        # 检查边界
        if (pos['x'] < x_min or pos['x'] > x_max or
            pos['y'] < y_min or pos['y'] > y_max):
            return None
        
        return pos
    
    def _has_overlap(self, position, x_range, y_range):
        """Check if position overlaps with existing labels"""
        min_x_dist = x_range * 0.05
        min_y_dist = y_range * 0.03
        
        for placed in self._placed_labels:
            x_dist = abs(position['x'] - placed['x'])
            y_dist = abs(position['y'] - placed['y'])
            
            if x_dist < min_x_dist and y_dist < min_y_dist:
                return True
        
        return False
    
    def _apply_chart_styling(self, settings):
        """Apply styling to the chart"""
        # Set labels and title（将单位追加到坐标轴标签）
        xlabel = settings.get('xlabel', 'X Axis')
        x_unit = settings.get('x_unit', '')
        if x_unit and x_unit != '(none)':
            xlabel = f"{xlabel} [{x_unit}]"

        ylabel = settings.get('ylabel', 'Y Axis')
        y_unit = settings.get('y_unit', '')
        if y_unit and y_unit != '(none)':
            ylabel = f"{ylabel} [{y_unit}]"

        axis_fs = int(settings.get('axis_label_font_size', 14))
        title_fs = int(settings.get('title_font_size', 16))
        self.ax.set_xlabel(xlabel, fontsize=axis_fs, weight='bold')
        self.ax.set_ylabel(ylabel, fontsize=axis_fs, weight='bold')
        self.ax.set_title(settings.get('title', 'Chart'), fontsize=title_fs, weight='bold')
        
        # Hide top and right spines
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        
        # Apply tick params (统一刻度字号/长度/线宽)
        tick_label_size = int(settings.get('tick_label_size', 10))
        tick_length = float(settings.get('tick_length', 4.0))
        tick_width = float(settings.get('tick_width', 1.5))
        show_minor_ticks = bool(settings.get('show_minor_ticks', False))
        try:
            # 控制次刻度显隐，默认关闭以减少多余刻度
            if show_minor_ticks:
                self.ax.minorticks_on()
            else:
                self.ax.minorticks_off()
            self.ax.tick_params(axis='both', which='major', labelsize=tick_label_size, length=tick_length, width=tick_width, direction='out')
            self.ax.tick_params(axis='both', which='minor', labelsize=max(tick_label_size-2, 6), length=max(tick_length*0.6, 1.0), width=max(tick_width*0.8, 0.8), direction='out')
            weight = 'bold' if bool(settings.get('tick_label_bold', False)) else 'normal'
            for lbl in self.ax.get_xticklabels():
                try:
                    lbl.set_fontweight(weight)
                except Exception:
                    pass
            for lbl in self.ax.get_yticklabels():
                try:
                    lbl.set_fontweight(weight)
                except Exception:
                    pass
            try:
                for lbl in self.ax.get_xminorticklabels():
                    lbl.set_fontweight(weight)
                for lbl in self.ax.get_yminorticklabels():
                    lbl.set_fontweight(weight)
            except Exception:
                pass
        except Exception:
            pass

        # X 轴刻度数量或自定义范围（仅数值型 X 生效）
        xaxis_mode = settings.get('xaxis_mode', 'categorical')
        x_tick_count = int(settings.get('x_tick_count', 6))
        use_custom_x = bool(settings.get('use_custom_x_ticks', False))
        auto_x = bool(settings.get('auto_x_ticks', False))
        x_step = float(settings.get('x_tick_step', 0.0))
        x_min_set = settings.get('x_tick_min', None)
        x_max_set = settings.get('x_tick_max', None)
        force_origin_zero = bool(settings.get('force_origin_zero', False))
        try:
            if xaxis_mode == 'numeric':
                if use_custom_x and x_step and x_step > 0:
                    cur_xlim = list(self.ax.get_xlim())
                    x_min = float(x_min_set) if x_min_set is not None else cur_xlim[0]
                    x_max = float(x_max_set) if x_max_set is not None else cur_xlim[1]
                    if x_max <= x_min:
                        x_max = x_min + x_step
                    if force_origin_zero:
                        x_min = 0.0
                    self.ax.set_xlim(x_min, x_max)
                    self.ax.xaxis.set_major_locator(MultipleLocator(x_step))
                    # 格式化为整数当步长为整数
                    try:
                        if abs(x_step - int(x_step)) < 1e-9:
                            self.ax.xaxis.set_major_formatter(FormatStrFormatter('%d'))
                    except Exception:
                        pass
                elif auto_x:
                    cur_xlim = list(self.ax.get_xlim())
                    data_min = cur_xlim[0]
                    data_max = cur_xlim[1]
                    if force_origin_zero:
                        data_min = 0.0
                    rng = max(data_max - data_min, 1e-12)
                    target = max(x_tick_count - 1, 1)
                    raw = rng / target
                    mag = 10 ** np.floor(np.log10(raw))
                    norm = raw / mag
                    if norm < 1.5:
                        step = 1 * mag
                    elif norm < 3:
                        step = 2 * mag
                    elif norm < 7:
                        step = 5 * mag
                    else:
                        step = 10 * mag
                    start = (0.0 if force_origin_zero else step * np.floor(data_min / step))
                    end = step * np.ceil(data_max / step)
                    if end <= start:
                        end = start + step
                    self.ax.set_xlim(start, end)
                    self.ax.xaxis.set_major_locator(MultipleLocator(step))
                    try:
                        if abs(step - int(step)) < 1e-9:
                            self.ax.xaxis.set_major_formatter(FormatStrFormatter('%d'))
                    except Exception:
                        pass
                elif x_tick_count and x_tick_count > 1:
                    x_min, x_max = self.ax.get_xlim()
                    if force_origin_zero:
                        x_min = 0.0
                    if x_max == x_min:
                        x_max = x_min + 1.0
                    ticks = list(np.linspace(x_min, x_max, x_tick_count))
                    self.ax.set_xticks(ticks)
        except Exception:
            pass

        # Y 轴刻度数量（均匀分布），用于统一不同图表的刻度数
        y_tick_count = int(settings.get('y_tick_count', 6))
        use_custom_y = bool(settings.get('use_custom_y_ticks', False))
        auto_y = bool(settings.get('auto_y_ticks', False))
        y_step = float(settings.get('y_tick_step', 0.0))
        y_min_set = settings.get('y_tick_min', None)
        y_max_set = settings.get('y_tick_max', None)
        try:
            if use_custom_y and y_step and y_step > 0:
                cur_ylim = list(self.ax.get_ylim())
                y_min = float(y_min_set) if y_min_set is not None else cur_ylim[0]
                y_max = float(y_max_set) if y_max_set is not None else cur_ylim[1]
                if y_max <= y_min:
                    y_max = y_min + y_step
                if force_origin_zero:
                    y_min = 0.0
                self.ax.set_ylim(y_min, y_max)
                self.ax.yaxis.set_major_locator(MultipleLocator(y_step))
                # 根据步长推断小数位，减少不规则小数
                try:
                    s = f"{y_step:.6f}".rstrip('0')
                    decimals = len(s.split('.')[1]) if '.' in s else 0
                    fmt = '%.' + str(decimals) + 'f'
                    if decimals == 0:
                        fmt = '%d'
                    self.ax.yaxis.set_major_formatter(FormatStrFormatter(fmt))
                except Exception:
                    pass
            elif auto_y:
                cur_ylim = list(self.ax.get_ylim())
                data_min = cur_ylim[0]
                data_max = cur_ylim[1]
                if force_origin_zero:
                    data_min = 0.0
                rng = max(data_max - data_min, 1e-12)
                target = max(y_tick_count - 1, 1)
                raw = rng / target
                mag = 10 ** np.floor(np.log10(raw))
                norm = raw / mag
                if norm < 1.5:
                    step = 1 * mag
                elif norm < 3:
                    step = 2 * mag
                elif norm < 7:
                    step = 5 * mag
                else:
                    step = 10 * mag
                start = (0.0 if force_origin_zero else step * np.floor(data_min / step))
                end = step * np.ceil(data_max / step)
                if end <= start:
                    end = start + step
                self.ax.set_ylim(start, end)
                self.ax.yaxis.set_major_locator(MultipleLocator(step))
                try:
                    if abs(step - int(step)) < 1e-9:
                        self.ax.yaxis.set_major_formatter(FormatStrFormatter('%d'))
                    else:
                        s = f"{step:.6f}".rstrip('0')
                        decimals = len(s.split('.')[1]) if '.' in s else 0
                        fmt = '%.' + str(decimals) + 'f'
                        self.ax.yaxis.set_major_formatter(FormatStrFormatter(fmt))
                except Exception:
                    pass
            else:
                if y_tick_count and y_tick_count > 1:
                    y_min, y_max = self.ax.get_ylim()
                    if force_origin_zero:
                        y_min = 0.0
                    # 避免 y_min == y_max 的情况
                    if y_max == y_min:
                        y_max = y_min + 1.0
                    ticks = list(np.linspace(y_min, y_max, y_tick_count))
                    self.ax.set_yticks(ticks)
        except Exception:
            pass

        try:
            reverse_y = bool(settings.get('reverse_y_axis', False))
            self.ax.yaxis.set_inverted(reverse_y)
        except Exception:
            pass

        # Show legend (deduplicate by label) — respect user toggle
        handles, labels = self.ax.get_legend_handles_labels()
        by_label = {}
        for h, l in zip(handles, labels):
            if l not in by_label:
                by_label[l] = h
        show_legend = bool(settings.get('show_legend', True))
        if by_label and show_legend:
            legend_font_size = int(settings.get('legend_font_size', 10))
            legend_marker_size = float(settings.get('legend_marker_size', float(settings.get('marker_size', 10))))
            # 自动避让右上角数据：若右上角存在数据点，则将图例移到绘图区外侧（右侧）
            def _has_points_top_right(ax, frac=0.2):
                try:
                    x_min, x_max = ax.get_xlim(); y_min, y_max = ax.get_ylim()
                    x_cut = x_min + (1 - frac) * (x_max - x_min)
                    y_cut = y_min + (1 - frac) * (y_max - y_min)
                    for coll in ax.collections:
                        try:
                            offs = coll.get_offsets()
                            if offs is None:
                                continue
                            arr = np.asarray(offs)
                            if arr.size == 0:
                                continue
                            if np.any((arr[:,0] >= x_cut) & (arr[:,1] >= y_cut)):
                                return True
                        except Exception:
                            continue
                except Exception:
                    pass
                return False

            place_outside = _has_points_top_right(self.ax, frac=0.2)
            if place_outside:
                try:
                    # 为右侧图例留出空间
                    fig = self.ax.figure
                    fig.subplots_adjust(right=0.83)
                except Exception:
                    pass
                leg = self.ax.legend(
                    list(by_label.values()), list(by_label.keys()),
                    fontsize=legend_font_size,
                    loc='upper left', bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0
                )
            else:
                leg = self.ax.legend(list(by_label.values()), list(by_label.keys()), fontsize=legend_font_size, loc='upper right')
            # 允许拖动图例，用户可手动避让数据重叠
            try:
                leg.set_draggable(True)
            except Exception:
                pass
            # 调整图例句柄的尺寸：散点(PathCollection)用 pt²，线条(Line2D)用 markersize/linewidth
            try:
                for handle in leg.legendHandles:
                    # PathCollection (scatter)
                    if hasattr(handle, 'set_sizes'):
                        handle.set_sizes([legend_marker_size ** 2])
                    # Line2D (errorbar/line legend)
                    if hasattr(handle, 'set_markersize'):
                        handle.set_markersize(legend_marker_size)
                    if hasattr(handle, 'set_linewidth'):
                        # 使用主线宽作为图例线宽保持一致
                        lw = float(settings.get('line_width', 2.0))
                        handle.set_linewidth(lw)
            except Exception:
                pass
        
        # No grid
        self.ax.grid(False)

    # --- 轻量标签拖动交互 ---
    def _on_press(self, event):
        try:
            if event.inaxes != self.ax:
                return
            # 只允许拖动数据坐标中的文本（避免标题/坐标轴标签）
            for txt in getattr(self.ax, 'texts', []):
                try:
                    if txt.get_transform() is self.ax.transData:
                        contains, _ = txt.contains(event)
                        if contains:
                            # 若工具栏处于平移/缩放模式，先自动关闭以释放鼠标
                            try:
                                if self._toolbar_active():
                                    self._deactivate_toolbar_mode()
                            except Exception:
                                pass
                            self._dragging_text = txt
                            return
                except Exception:
                    continue
        except Exception:
            pass

    def _on_motion(self, event):
        try:
            if self._dragging_text is None:
                return
            if event.inaxes != self.ax:
                return
            if event.xdata is None or event.ydata is None:
                return
            self._dragging_text.set_position((event.xdata, event.ydata))
            self.canvas.draw_idle()
        except Exception:
            pass

    def _on_release(self, event):
        try:
            self._dragging_text = None
        except Exception:
            pass

    # --- 工具栏状态辅助 ---
    def _toolbar_active(self):
        tb = getattr(self, 'toolbar', None)
        if tb is None:
            return False
        try:
            mode = getattr(tb, 'mode', None)
            if mode in ('pan', 'zoom', 'PAN', 'ZOOM'):
                return True
        except Exception:
            pass
        try:
            active = getattr(tb, '_active', None)
            return bool(active)
        except Exception:
            return False

    def _deactivate_toolbar_mode(self):
        tb = getattr(self, 'toolbar', None)
        if tb is None:
            return
        try:
            mode = getattr(tb, 'mode', None)
            if mode == 'pan':
                tb.pan()  # 切换关闭
                return
            if mode == 'zoom':
                tb.zoom()  # 切换关闭
                return
        except Exception:
            pass
        # 兼容旧版本，直接清空 _active
        try:
            if getattr(tb, '_active', None):
                tb._active = None
        except Exception:
            pass
        # 释放可能的 widget 锁，避免鼠标被占用
        try:
            wl = getattr(self.canvas, 'widgetlock', None)
            if wl is not None and hasattr(wl, 'release'):
                wl.release(tb)
        except Exception:
            pass

    def _on_scroll(self, event):
        """鼠标滚轮：缩放坐标轴；按住 Ctrl 时同步调整标记/文字大小"""
        try:
            if event.inaxes != self.ax:
                return

            # 判断滚轮方向
            step = getattr(event, 'step', 0)
            if step == 0:
                # 兼容旧版，用 button 标识
                if getattr(event, 'button', None) == 'up':
                    step = 1
                elif getattr(event, 'button', None) == 'down':
                    step = -1
                else:
                    return

            scale = (1 / self._base_scroll_scale) if step > 0 else self._base_scroll_scale

            # 以鼠标所在数据点为中心缩放坐标轴
            cur_xlim = list(self.ax.get_xlim())
            cur_ylim = list(self.ax.get_ylim())
            xdata = event.xdata if event.xdata is not None else (cur_xlim[0] + cur_xlim[1]) / 2
            ydata = event.ydata if event.ydata is not None else (cur_ylim[0] + cur_ylim[1]) / 2

            # 计算新范围
            new_xlim = [xdata - (xdata - cur_xlim[0]) * scale,
                        xdata + (cur_xlim[1] - xdata) * scale]
            new_ylim = [ydata - (ydata - cur_ylim[0]) * scale,
                        ydata + (cur_ylim[1] - ydata) * scale]

            # 适度约束，避免无限缩放或反转
            if new_xlim[1] - new_xlim[0] > 0 and new_ylim[1] - new_ylim[0] > 0:
                self.ax.set_xlim(new_xlim)
                self.ax.set_ylim(new_ylim)

            # Ctrl + 滚轮：同步调整标记/线宽/文本大小
            if getattr(event, 'key', None) in ('control', 'ctrl', 'control+'):  # 兼容不同标识
                size_scale = (1 / self._base_scroll_scale) if step > 0 else self._base_scroll_scale

                # 调整散点大小
                for coll in getattr(self.ax, 'collections', []):
                    try:
                        sizes = coll.get_sizes()
                        if sizes is not None and len(sizes) > 0:
                            new_sizes = np.clip(sizes * size_scale, 10, 800)
                            coll.set_sizes(new_sizes)
                    except Exception:
                        pass

                # 调整线宽
                for line in getattr(self.ax, 'lines', []):
                    try:
                        lw = line.get_linewidth()
                        line.set_linewidth(np.clip(lw * size_scale, 0.5, 6))
                    except Exception:
                        pass

                # 调整文本字号
                for txt in getattr(self.ax, 'texts', []):
                    try:
                        fs = txt.get_fontsize()
                        txt.set_fontsize(np.clip(fs * size_scale, 6, 24))
                    except Exception:
                        pass

            self.canvas.draw_idle()
        except Exception:
            # 安静处理，避免交互异常导致崩溃
            pass
