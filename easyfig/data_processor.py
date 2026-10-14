"""
Data processing utilities for parsing and analyzing input data
"""
import os
import re

import numpy as np

# Table formats accepted by :func:`load_table_dataframe`.
TABLE_EXTENSIONS = ('.csv', '.tsv', '.txt', '.xlsx', '.xlsm', '.xls')

# Above this size an .xlsx workbook is streamed row by row instead of being
# materialised by pandas, which keeps peak memory close to a single row.
LARGE_TABLE_BYTES = 10 * 1024 * 1024


def load_table_dataframe(path, sheet_name=0):
    """Read a CSV/TSV/Excel file into a pandas DataFrame.

    ``.xlsx``/``.xlsm`` files larger than :data:`LARGE_TABLE_BYTES` are streamed
    with openpyxl.  ``pandas.read_excel`` has no ``chunksize`` argument, so
    streaming is the only way to bound memory for big workbooks.
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError(
            "pandas is required to read tables. Install: pip install pandas openpyxl"
        ) from None

    if not os.path.isfile(path):
        raise FileNotFoundError(f"table not found: {path}")

    ext = os.path.splitext(path)[1].lower()
    # ``utf-8-sig`` strips a byte-order mark, which Excel's "CSV UTF-8" always
    # writes; without it the mark glues itself to the first column name.
    if ext == '.csv':
        return pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig')
    if ext == '.txt':
        return pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig')
    if ext == '.tsv':
        return pd.read_csv(path, sep='\t', encoding='utf-8-sig')
    if ext == '.xls':
        return pd.read_excel(path, sheet_name=sheet_name)
    if ext in ('.xlsx', '.xlsm'):
        if os.path.getsize(path) > LARGE_TABLE_BYTES:
            return _stream_xlsx(path, sheet_name=sheet_name)
        return pd.read_excel(path, sheet_name=sheet_name)
    raise ValueError(f"Unsupported table format: {ext or path}")


def _dedupe_column_names(names):
    """Reproduce pandas' duplicate-header renaming ('A', 'A.1', 'A.2')."""
    seen = {}
    result = []
    for name in names:
        if name in seen:
            seen[name] += 1
            result.append(f"{name}.{seen[name]}")
        else:
            seen[name] = 0
            result.append(name)
    return result


def _stream_xlsx(path, sheet_name=0):
    """Stream a large workbook sheet into a DataFrame using openpyxl read-only mode."""
    try:
        import pandas as pd
        from openpyxl import load_workbook
    except ImportError:
        raise ImportError(
            "openpyxl is required for large .xlsx files. Install: pip install openpyxl"
        ) from None

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if isinstance(sheet_name, int):
            sheet = workbook.worksheets[sheet_name]
        else:
            sheet = workbook[sheet_name]

        rows = sheet.iter_rows(values_only=True)
        try:
            header = next(rows)
        except StopIteration:
            return pd.DataFrame()

        columns = _dedupe_column_names([
            value if value is not None and str(value).strip() != ''
            else f"Unnamed: {position}"
            for position, value in enumerate(header)
        ])

        records = [list(row) for row in rows]
        return pd.DataFrame(records, columns=columns)
    finally:
        workbook.close()


def _extract_numeric_axis_value(value):
    """Extract a numeric axis value from headers such as 1, 1.5, 1mm, or 24V."""
    if value is None:
        return None

    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)

    text = str(value).strip()
    if not text or text.lower().startswith("unnamed"):
        return None

    try:
        return float(text)
    except ValueError:
        match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _safe_std(values):
    """Return a finite population standard deviation for plotting."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size <= 1:
        return 0.0
    std = float(np.std(arr, ddof=0))
    return std if np.isfinite(std) else 0.0


def parse_data_input(text):
    """
    Parse input text to extract data values
    
    Args:
        text: Input text containing data
        
    Returns:
        list: List of float values extracted from text
    """
    data = []
    
    # Split by common delimiters
    parts = re.split(r'[,;\s\n]+', text.strip())
    
    for part in parts:
        part = part.strip()
        if part:
            try:
                # Try to convert to float
                value = float(part)
                data.append(value)
            except ValueError:
                # Skip non-numeric values
                continue
    
    return data


def calculate_statistics(data_list, max_points=10000):
    """
    Calculate statistical measures for a list of data points.
    If the total points exceed max_points, it switches to efficient sampling.
    
    Args:
        data_list: List of data values for each size/category
        max_points: Threshold for switching to sampling logic
        
    Returns:
        dict: Dictionary containing mean, std, max, min arrays
    """
    if not data_list:
        return None
    
    total_points = sum(len(data) for data in data_list)
    use_sampling = total_points > max_points
    
    mean_values = []
    std_values = []
    max_values = []
    min_values = []
    
    # At least one sample per group, otherwise np.mean() of an empty selection
    # would return NaN and emit a RuntimeWarning.
    points_per_group = max(1, max_points // len(data_list)) if use_sampling else None
    
    for data in data_list:
        if len(data) > 0:
            if use_sampling and len(data) > points_per_group:
                # Efficient sampling for large datasets
                indices = np.random.choice(len(data), points_per_group, replace=False)
                arr = np.array(data, dtype=float)[indices]
            else:
                arr = np.array(data, dtype=float)
                
            mean_values.append(np.mean(arr))
            std_values.append(_safe_std(arr))
            max_values.append(np.max(arr))
            min_values.append(np.min(arr))
        else:
            mean_values.append(0)
            std_values.append(0)
            max_values.append(0)
            min_values.append(0)
    
    return {
        'mean': np.array(mean_values),
        'std': np.array(std_values),
        'max': np.array(max_values),
        'min': np.array(min_values)
    }


def validate_dataset(sizes, data_list):
    """
    Validate that dataset has correct structure
    
    Args:
        sizes: List of size values (x-axis)
        data_list: List of data arrays for each size
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not sizes:
        return False, "No sizes specified"
    
    if not data_list:
        return False, "No data provided"
    
    if len(sizes) != len(data_list):
        return False, f"Number of sizes ({len(sizes)}) doesn't match number of data groups ({len(data_list)})"
    
    # Check if all data groups have values
    for i, data in enumerate(data_list):
        if len(data) == 0:
            return False, f"No data for size {sizes[i]}"
    
    return True, ""


def prepare_chart_data(datasets):
    """
    Prepare and organize data for chart generation
    
    Args:
        datasets: Dictionary of datasets {name: {'sizes': [], 'data': [], 'color': ''}}
        
    Returns:
        dict: Processed chart data
    """
    chart_data = {}
    
    for name, dataset in datasets.items():
        sizes = dataset['sizes']
        data_list = dataset['data']
        color = dataset['color']
        
        # Validate dataset
        is_valid, error_msg = validate_dataset(sizes, data_list)
        if not is_valid:
            continue
        
        # Check if this is multiline data with pre-computed errors
        if dataset.get('is_multiline') and 'y_errors' in dataset:
            # Use actual mean if multiple values are present, or pre-computed means
            y_means = np.array([np.mean(d) if d and len(d) > 0 else 0 for d in data_list])
            y_errors = np.array([
                float(err) if err is not None and np.isfinite(err) else 0.0
                for err in dataset['y_errors']
            ])
            # Keep max/min truthful instead of aliasing them to the mean, so the
            # Max/Min display toggles show real extrema for imported data.
            y_max = np.array([np.max(d) if d and len(d) > 0 else 0 for d in data_list])
            y_min = np.array([np.min(d) if d and len(d) > 0 else 0 for d in data_list])
            stats = {
                'mean': y_means,
                'std': y_errors,
                'max': y_max,
                'min': y_min
            }
        else:
            # Calculate statistics normally
            stats = calculate_statistics(data_list)
        
        if stats:
            chart_data[name] = {
                'sizes': sizes,
                'data': data_list,
                'color': color,
                'stats': stats,
                'is_multiline': dataset.get('is_multiline', False),
                'marker': dataset.get('marker', 'o'),
                'y_errors': dataset.get('y_errors', None)
            }
    
    return chart_data


def fit_linear_regression(x_data, y_data):
    """
    Perform linear regression on data points
    
    Args:
        x_data: List of x values
        y_data: List of y values
        
    Returns:
        dict: Dictionary containing slope, intercept, and fitted values
    """
    if len(x_data) != len(y_data) or len(x_data) < 2:
        return None
    
    x = np.array(x_data)
    y = np.array(y_data)
    
    # Calculate linear regression coefficients
    A = np.vstack([x, np.ones(len(x))]).T
    slope, intercept = np.linalg.lstsq(A, y, rcond=None)[0]
    
    # Calculate fitted values
    fitted_y = slope * x + intercept
    
    # Calculate R-squared and MSE
    ss_res = np.sum((y - fitted_y) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    mse = ss_res / len(y) if len(y) > 0 else 0
    
    return {
        'slope': slope,
        'intercept': intercept,
        'fitted_values': fitted_y,
        'r_squared': r_squared,
        'mse': mse,
        'equation': f"y = {slope:.4f}x + {intercept:.4f}",
        'r_squared_text': f"R² = {r_squared:.4f}",
        'mse_text': f"MSE = {mse:.4e}"
    }


def fit_polynomial(x_data, y_data, degree=2):
    """
    Perform polynomial regression on data points
    
    Args:
        x_data: List of x values
        y_data: List of y values
        degree: Degree of polynomial (default: 2)
        
    Returns:
        dict: Dictionary containing coefficients and fitted values
    """
    if len(x_data) != len(y_data) or len(x_data) <= degree:
        return None
    
    x = np.array(x_data)
    y = np.array(y_data)
    
    # Fit polynomial
    coefficients = np.polyfit(x, y, degree)
    polynomial = np.poly1d(coefficients)
    
    # Calculate fitted values
    fitted_y = polynomial(x)
    
    # Calculate R-squared and MSE
    ss_res = np.sum((y - fitted_y) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    mse = ss_res / len(y) if len(y) > 0 else 0
    
    # Generate equation string.  Terms carry their own sign, otherwise a
    # negative coefficient reads as "+ -0.7465x^2".
    equation_parts = []
    for i, coef in enumerate(coefficients):
        power = degree - i
        magnitude = abs(float(coef))
        if power == 0:
            body = f"{magnitude:.4f}"
        elif power == 1:
            body = f"{magnitude:.4f}x"
        else:
            body = f"{magnitude:.4f}x^{power}"
        if i == 0:
            equation_parts.append(("-" if coef < 0 else "") + body)
        else:
            equation_parts.append((" - " if coef < 0 else " + ") + body)

    equation = "y = " + "".join(equation_parts)
    
    return {
        'coefficients': coefficients,
        'fitted_values': fitted_y,
        'r_squared': r_squared,
        'mse': mse,
        'equation': equation,
        'r_squared_text': f"R² = {r_squared:.4f}",
        'mse_text': f"MSE = {mse:.4e}",
        'degree': degree
    }


def _robust_line(x, y, max_pairs=20000):
    """Theil-Sen slope/intercept, resistant to a few gross outliers.

    Detrending has to be robust, otherwise the outliers being hunted drag the
    fitted line and spread the residuals until they hide inside the fence again
    (the classic masking problem).  Theil-Sen takes the median of every pairwise
    slope, so a minority of wild points cannot move it.

    Falls back to least squares when the pairwise count would be excessive.
    """
    n = x.size
    if n < 2:
        return None
    if n * (n - 1) // 2 > max_pairs:
        try:
            slope, intercept = np.polyfit(x, y, 1)
            return float(slope), float(intercept)
        except (np.linalg.LinAlgError, ValueError):
            return None

    chunks = []
    for i in range(n - 1):
        dx = x[i + 1:] - x[i]
        dy = y[i + 1:] - y[i]
        usable = dx != 0
        if np.any(usable):
            chunks.append(dy[usable] / dx[usable])
    if not chunks:
        return None
    slope = float(np.median(np.concatenate(chunks)))
    intercept = float(np.median(y - slope * x))
    return slope, intercept


def remove_outliers_iqr(data, multiplier=1.5, x=None):
    """
    Remove outliers with a Tukey (interquartile range) fence.

    The fence is applied to the **residuals about a robust line** when ``x`` is
    supplied.  Two things decide whether this actually works:

    * the raw values must not be tested directly - on a trending series the
      extremes inflate the quartiles until the fence covers them, so gross
      errors survive untouched;
    * the detrending must be robust - a least-squares line is dragged by the
      very outliers being looked for, which spreads the residuals back inside
      the fence.

    For the demo data (a rising line plus three planted gross errors) the raw
    fence is ``[-17.4, 43.3]`` and removes nothing, while the residual fence is
    ``[-9.3, 8.5]`` and removes all three.

    Args:
        data: List of data values
        multiplier: IQR multiplier (default: 1.5)
        x: Optional matching x values; enables the detrended test

    Returns:
        tuple: (filtered_data, removed_indices)
    """
    values = np.asarray(data, dtype=float)
    if values.size < 4:
        return list(values), []

    signal = values
    if x is not None:
        xs = np.asarray(x, dtype=float)
        if xs.shape == values.shape:
            finite = np.isfinite(values) & np.isfinite(xs)
            if finite.sum() >= 2 and np.ptp(xs[finite]) > 0:
                line = _robust_line(xs[finite], values[finite])
                if line is not None:
                    slope, intercept = line
                    signal = values - (slope * xs + intercept)

    finite_signal = signal[np.isfinite(signal)]
    if finite_signal.size < 4:
        return list(values), []

    q1, q3 = (float(v) for v in np.percentile(finite_signal, [25, 75]))
    iqr = q3 - q1
    if iqr > 0:
        lower_bound = q1 - multiplier * iqr
        upper_bound = q3 + multiplier * iqr
    else:
        # A degenerate spread - a flat baseline with one spike makes the
        # quartiles identical - needs a different fence.
        median = float(np.median(finite_signal))
        mad = float(np.median(np.abs(finite_signal - median)))
        if mad > 0:
            lower_bound = median - 3.5 * mad / 0.6745
            upper_bound = median + 3.5 * mad / 0.6745
        else:
            # Every deviation is zero: anything off the median is an outlier.
            lower_bound = upper_bound = median

    filtered_data = []
    removed_indices = []
    for index, raw in enumerate(values):
        value = signal[index]
        if np.isfinite(value) and lower_bound <= value <= upper_bound:
            filtered_data.append(float(raw))
        else:
            removed_indices.append(index)

    return filtered_data, removed_indices


def smooth_data_moving_average(data, window_size=3):
    """
    Apply moving average smoothing to data
    
    Args:
        data: List of data values
        window_size: Size of moving average window (default: 3)
        
    Returns:
        list: Smoothed data
    """
    if len(data) < window_size:
        return data
    
    smoothed = []
    for i in range(len(data)):
        start = max(0, i - window_size // 2)
        end = min(len(data), i + window_size // 2 + 1)
        window = data[start:end]
        smoothed.append(np.mean(window))
    
    return smoothed


def process_multiline_excel(file_path, orientation='vertical'):
    """
    Process an Excel or CSV file for a multi-line chart.

    File format:
    - Cell (0,0): Series Label (e.g., "0.4"), or the filename when empty
    - Row 0 (rest): X-axis values (numeric headers), vertical orientation
    - Col 0 (rest): X-axis values, horizontal orientation
    - Data: repeated measurements for each X value

    Args:
        file_path: Path to the .xlsx/.xlsm/.xls/.csv/.tsv/.txt file
        orientation: 'vertical' (X values across the header row) or
                     'horizontal' (X values down the first column)

    Returns:
        dict: Contains 'x' (X values), 'y' (column means),
              'y_err' (column std), 'raw_data' (measurement groups) and
              'label' (from cell 0,0 or the filename)
    """
    if orientation not in ('vertical', 'horizontal'):
        raise ValueError(f"Unsupported orientation: {orientation}")

    try:
        import pandas as pd
    except ImportError:
        raise ImportError(
            "pandas is required. Install: pip install pandas openpyxl"
        ) from None

    try:
        df = load_table_dataframe(file_path)
    except (FileNotFoundError, ValueError, ImportError):
        raise
    except Exception as e:
        raise ValueError(f"Failed to read table file: {str(e)}") from None

    if df.empty:
        raise ValueError("Table file is empty")

    # 1. Identify Series Label from the first column header (Cell 0,0)
    first_col_header = df.columns[0]
    label = str(first_col_header)
    if label.startswith('Unnamed'): 
        # Fallback to filename if header is empty
        basename = os.path.basename(str(file_path))
        label = os.path.splitext(basename)[0]

    x_values = []
    raw_data_list = []
    y_means = []
    y_stds = []

    if orientation == 'vertical':
        potential_x_cols = df.columns[1:]
        valid_data_cols = []

        for col in potential_x_cols:
            val = _extract_numeric_axis_value(col)
            if val is None:
                continue
            x_values.append(val)
            valid_data_cols.append(col)

        if not x_values:
            raise ValueError(
                f"No numeric X-axis values found in header row of {file_path}. "
                "Expected format: First row contains X values like 1, 1.5, 2, or 1mm."
            )

        for col in valid_data_cols:
            series = df[col]
            if isinstance(series, pd.DataFrame):
                # A duplicated header yields several columns; keep the first.
                series = series.iloc[:, 0]
            col_data = pd.to_numeric(series, errors='coerce').dropna()

            if len(col_data) == 0:
                y_means.append(0.0)
                y_stds.append(0.0)
                raw_data_list.append([])
            else:
                y_means.append(float(col_data.mean()))
                y_stds.append(_safe_std(col_data.to_numpy()))
                raw_data_list.append([float(v) for v in col_data.tolist()])
    else:
        value_columns = list(df.columns[1:])
        if not value_columns:
            raise ValueError(
                f"No data columns found in {file_path}. Expected repeated measurements after the first column."
            )

        for _, row in df.iterrows():
            x_val = _extract_numeric_axis_value(row.iloc[0])
            if x_val is None:
                continue

            row_data = pd.to_numeric(row.iloc[1:], errors='coerce').dropna()
            x_values.append(x_val)
            if len(row_data) == 0:
                y_means.append(0.0)
                y_stds.append(0.0)
                raw_data_list.append([])
            else:
                y_means.append(float(row_data.mean()))
                y_stds.append(_safe_std(row_data.to_numpy()))
                raw_data_list.append([float(v) for v in row_data.tolist()])

        if not x_values:
            raise ValueError(
                f"No numeric X-axis values found in the first column of {file_path}. "
                "Expected format: First column contains X values like 1, 1.5, 2, or 1mm."
            )
    
    return {
        'x': x_values,
        'y': y_means,
        'y_err': y_stds,
        'raw_data': raw_data_list,
        'label': label
    }


def process_multiple_multiline_excel(file_paths, orientation='vertical'):
    """
    Process multiple Excel files for multi-line chart.
    
    Args:
        file_paths: List of Excel file paths
        
    Returns:
        list: List of dicts from process_multiline_excel for each file
    """
    results = []
    errors = []
    
    for file_path in file_paths:
        try:
            result = process_multiline_excel(file_path, orientation=orientation)
            results.append(result)
        except Exception as e:
            errors.append(f"{file_path}: {str(e)}")
    
    return results, errors
