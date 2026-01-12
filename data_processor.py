"""
Data processing utilities for parsing and analyzing input data
"""
import re
import numpy as np


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
    
    points_per_group = max_points // len(data_list) if use_sampling else None
    
    for data in data_list:
        if len(data) > 0:
            if use_sampling and len(data) > points_per_group:
                # Efficient sampling for large datasets
                indices = np.random.choice(len(data), points_per_group, replace=False)
                arr = np.array(data)[indices]
            else:
                arr = np.array(data)
                
            mean_values.append(np.mean(arr))
            std_values.append(np.std(arr))
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
            # Use pre-computed statistics for multiline data
            y_means = np.array([d[0] for d in data_list])
            y_errors = np.array(dataset['y_errors'])
            stats = {
                'mean': y_means,
                'std': y_errors,
                'max': y_means,
                'min': y_means
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
    
    # Calculate R-squared
    ss_res = np.sum((y - fitted_y) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    
    return {
        'slope': slope,
        'intercept': intercept,
        'fitted_values': fitted_y,
        'r_squared': r_squared,
        'equation': f"y = {slope:.4f}x + {intercept:.4f}",
        'r_squared_text': f"R² = {r_squared:.4f}"
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
    
    # Calculate R-squared
    ss_res = np.sum((y - fitted_y) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    
    # Generate equation string
    equation_parts = []
    for i, coef in enumerate(coefficients):
        power = degree - i
        if power == 0:
            equation_parts.append(f"{coef:.4f}")
        elif power == 1:
            equation_parts.append(f"{coef:.4f}x")
        else:
            equation_parts.append(f"{coef:.4f}x^{power}")
    
    equation = "y = " + " + ".join(equation_parts)
    
    return {
        'coefficients': coefficients,
        'fitted_values': fitted_y,
        'r_squared': r_squared,
        'equation': equation,
        'r_squared_text': f"R² = {r_squared:.4f}",
        'degree': degree
    }


def remove_outliers_iqr(data, multiplier=1.5):
    """
    Remove outliers from data using Interquartile Range (IQR) method
    
    Args:
        data: List of data values
        multiplier: IQR multiplier (default: 1.5)
        
    Returns:
        tuple: (filtered_data, removed_indices)
    """
    if len(data) < 4:
        return data, []
    
    q1 = np.percentile(data, 25)
    q3 = np.percentile(data, 75)
    iqr = q3 - q1
    
    lower_bound = q1 - multiplier * iqr
    upper_bound = q3 + multiplier * iqr
    
    filtered_data = []
    removed_indices = []
    
    for i, value in enumerate(data):
        if lower_bound <= value <= upper_bound:
            filtered_data.append(value)
        else:
            removed_indices.append(i)
    
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


def process_multiline_excel(file_path):
    """
    Process Excel file for multi-line chart.
    
    Excel format based on user requirement:
    - Cell (0,0): Series Label (e.g., "0.4")
    - Row 0 (rest): X-axis values (Numeric headers)
    - Col 0 (rest): Data indices (Ignored)
    - Data: Repeated measurements
    
    Args:
        file_path: Path to the Excel file
        
    Returns:
        dict: Contains 'x' (X values), 'y' (column means), 
              'y_err' (column std), 'label' (from cell 0,0 or filename)
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required. Install: pip install pandas openpyxl")
    
    import os
    
    # Read Excel file
    # We read without header first to inspect the first row manually, or read with header=0
    # Reading with header=0 is standard interpretation of the user's format description
    try:
        df = pd.read_excel(file_path, header=0)
    except Exception as e:
        raise ValueError(f"Failed to read Excel file: {str(e)}")
        
    if df.empty:
        raise ValueError("Excel file is empty")
        
    # 1. Identify Series Label from the first column header (Cell 0,0)
    # The dataframe columns include the first cell as the name of the first column
    first_col_header = df.columns[0]
    
    # Use the header as label if it looks like a value (e.g. 0.4), otherwise use filename
    label = str(first_col_header)
    if label.startswith('Unnamed'): 
        # Fallback to filename if header is empty
        basename = os.path.basename(file_path)
        label = os.path.splitext(basename)[0]
    
    # 2. Identify X Values from the remaining column headers
    # We skip the first column (which is the index column)
    potential_x_cols = df.columns[1:]
    
    x_values = []
    valid_data_cols = []
    
    for col in potential_x_cols:
        try:
            # Try to parse column header as float for X-axis value
            val = float(col)
            x_values.append(val)
            valid_data_cols.append(col)
        except (ValueError, TypeError):
            # Skip columns that aren't numeric x-values
            continue
            
    if not x_values:
        raise ValueError(f"No numeric X-axis values found in header row of {file_path}. Expected format: First row contains X values like 1, 1.5, 2...")
    
    # 3. Calculate Stats for each valid column AND collect raw data
    y_means = []
    y_stds = []
    raw_data_list = []
    
    for col in valid_data_cols:
        # Convert column to numeric, coercing errors to NaN, then drop NaNs
        col_data = pd.to_numeric(df[col], errors='coerce').dropna()
        
        if len(col_data) == 0:
            y_means.append(0.0)
            y_stds.append(0.0)
            raw_data_list.append([])
        else:
            y_means.append(float(col_data.mean()))
            y_stds.append(float(col_data.std()))
            # Convert Series to list
            raw_data_list.append(col_data.tolist())
    
    return {
        'x': x_values,
        'y': y_means,
        'y_err': y_stds,
        'raw_data': raw_data_list,
        'label': label
    }


def process_multiple_multiline_excel(file_paths):
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
            result = process_multiline_excel(file_path)
            results.append(result)
        except Exception as e:
            errors.append(f"{file_path}: {str(e)}")
    
    return results, errors

