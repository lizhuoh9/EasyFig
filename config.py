"""
Configuration constants for Thrust Analysis Tool
"""
WINDOW_TITLE = "EasyFig"
WINDOW_GEOMETRY = "1200x800"

# Default Chart Settings
DEFAULT_CHART_TITLE = "Thrust Analysis"
DEFAULT_XLABEL = "Size (in)"
DEFAULT_YLABEL = "Thrust (kg)"
DEFAULT_LINE_COLOR = "#1f77b4"
DEFAULT_BAR_COLOR = "#1f77b4"
DEFAULT_ERRORBAR_COLOR = "#d62728"

# Plot config
DEFAULT_FIG_WIDTH = 10
DEFAULT_FIG_HEIGHT = 6
DEFAULT_DPI = 100

# Constants
DEFAULT_POINT_ALPHA = 0.25

AVAILABLE_COLORS = {
    'Blue': '#1f77b4',
    'Orange': '#ff7f0e',
    'Green': '#2ca02c',
    'Red': '#d62728',
    'Purple': '#9467bd',
    'Brown': '#8c564b',
    'Pink': '#e377c2',
    'Gray': '#7f7f7f',
    'Olive': '#bcbd22',
    'Cyan': '#17becf',
    'Black': 'black',
    'Bright Red': 'red',
    'Bright Blue': 'blue',
    'Bright Green': 'green',
    'Bright Orange': 'orange',
    'Bright Purple': 'purple'
}

AVAILABLE_MARKERS = [
    'o', 's', '^', 'D', 'v', '<', '>', 'p', '*', 'h', 'H', '+', 'x', 'd', '|', '_'
]

# Common Units
X_AXIS_UNITS = ['(none)', 'in', 'cm', 'mm', 'm', 's', 'ms']
Y_AXIS_UNITS = ['(none)', 'kg', 'g', 'N', 'lb', 'oz', 'Ns']

# Interaction
DEFAULT_DRAG_RADIUS_FACTOR = 0.5
