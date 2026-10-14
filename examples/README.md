# Examples

Ten figures rendered from synthetic data with the `easyfig` command line
interface. Everything here is shaped like real measurements: linear responses
with noise, a saturating response, a signal that needs smoothing, three planted
gross outliers, a dataset with a large gap for a broken axis, and repeated
series for mean ± SD / SEM.

## Regenerate

```powershell
python examples/make_demo_data.py          # writes examples/output/data/*.csv
```

Then run the commands below. They write into `examples/output/`, which is
generated and therefore ignored by git — clone, run, and you have the figures
back. `easyfig` is the installed console script; `python -m easyfig` works the
same way from an uninstalled checkout.

| # | Figure | What it shows |
| --- | --- | --- |
| 01 | `01-linear-fit.png` | Raw points plus a least-squares line; the legend carries the equation and R² |
| 02 | `02-polynomial-fit.png` | A saturating response fitted with a cubic; equation signs are correct |
| 03 | `03-outliers-before.png` | Scatter with three planted gross errors |
| 04 | `04-outliers-after.png` | The same data after robust IQR removal (`剔除 3 点`) |
| 05 | `05-smooth-before.png` | A noisy periodic signal |
| 06 | `06-smooth-after.png` | The same signal after moving-average smoothing |
| 07 | `07-errorbar-mean-sd.png` | Two multi-line files → mean ± SD per size |
| 08 | `08-bar-sem.png` | Summary bar chart with standard error |
| 09 | `09-broken-axis.png` | A broken Y axis for data spanning 12–214; the connecting line breaks at the break instead of being clipped into a stub |
| 10 | `10-sci-preset.png` | The SCI preset: grayscale, distinct line styles, inward minor ticks |

## Commands

### 01 – linear fit

```powershell
easyfig plot --table examples/output/data/linear.csv --time-column Size `
  --chart-type line_scatter --xaxis-mode numeric --palette akun42_nature `
  --fit linear --show-raw --show-fit `
  --title "线性拟合：推力—尺寸" --xlabel Size --x-unit in --ylabel Thrust --y-unit kg `
  --legend-loc "upper left" -o examples/output/01-linear-fit.png --json-out
```

`--json-out` reports the fit, not just the input:

```json
"fits": [{"dataset": "Thrust", "equation": "y = 2.4955x + 0.7768",
          "rSquared": 0.9395, "mse": 2.1038, "slope": 2.4955, "intercept": 0.7768}]
```

### 02 – polynomial fit

```powershell
easyfig plot --table examples/output/data/saturating.csv --time-column Time `
  --chart-type line_scatter --xaxis-mode numeric --palette akun36_nature `
  --fit polynomial --degree 3 --show-raw --show-fit `
  --title "响应饱和曲线：3 次多项式拟合" --xlabel Time --x-unit s --ylabel Response `
  --legend-loc "lower right" -o examples/output/02-polynomial-fit.png --json-out
```

### 03 / 04 – outlier removal

```powershell
easyfig plot --table examples/output/data/outliers.csv --time-column Size `
  --chart-type scatter --xaxis-mode numeric --palette akun33_science `
  --marker-size 12 --title "异常值处理前（含 3 个粗大误差）" `
  --xlabel Size --x-unit in --ylabel Thrust --y-unit kg `
  --legend-loc "upper left" -o examples/output/03-outliers-before.png

easyfig plot --table examples/output/data/outliers.csv --time-column Size `
  --chart-type line_scatter --xaxis-mode numeric --palette akun33_science `
  --fit remove_outliers --line-color "#C1282D" `
  --title "异常值处理后（稳健 IQR 剔除 3 点）" `
  --xlabel Size --x-unit in --ylabel Thrust --y-unit kg `
  --legend-loc "upper left" -o examples/output/04-outliers-after.png
```

The removals are reported in the series name (`剔除 3 点`).

### 05 / 06 – smoothing

```powershell
easyfig plot --table examples/output/data/signal.csv --time-column Time `
  --chart-type line_scatter --xaxis-mode numeric --palette akun40_tibet `
  --line-width 1.0 --marker-size 4 --show-mean --show-connecting-line `
  --title "平滑前：原始噪声信号" --xlabel Time --x-unit s --ylabel Signal `
  --legend-loc "upper right" -o examples/output/05-smooth-before.png

easyfig plot --table examples/output/data/signal.csv --time-column Time `
  --chart-type line --xaxis-mode numeric --palette akun40_tibet `
  --fit smooth --line-width 2.4 --title "平滑后：移动平均" `
  --xlabel Time --x-unit s --ylabel Signal `
  --legend-loc "upper right" -o examples/output/06-smooth-after.png
```

### 07 / 08 – repeated measurements

Two multi-line files (header row = X, one row per repeat):

```powershell
easyfig plot --multiline examples/output/data/lot_a.csv examples/output/data/lot_b.csv `
  --chart-type errorbar --errorbar-mode per_size --errorbar-metric SD `
  --xaxis-mode numeric --palette akun42_nature `
  --title "均值 ± 标准差（4 次重复）" --xlabel Size --x-unit in `
  --ylabel Thrust --y-unit kg --legend-loc "upper left" `
  -o examples/output/07-errorbar-mean-sd.png

easyfig plot --multiline examples/output/data/lot_a.csv examples/output/data/lot_b.csv `
  --chart-type bar --errorbar-mode summary --errorbar-metric SEM `
  --xaxis-mode categorical --palette akun35_science --show-data-labels `
  --ylabel Thrust --y-unit kg --title "批次汇总：均值 ± 标准误" `
  --legend-loc "upper left" -o examples/output/08-bar-sem.png
```

### 09 – broken axis

```powershell
easyfig plot --table examples/output/data/gap.csv --time-column Position `
  --chart-type line_scatter --xaxis-mode numeric --palette akun38_latlf_m `
  --broken-y --broken-y-low-min 0 --broken-y-low-max 30 `
  --broken-y-high-min 200 --broken-y-high-max 230 `
  --title "断轴：跨量级的载荷数据" --xlabel Position --ylabel Load `
  --legend-loc "upper left" -o examples/output/09-broken-axis.png
```

### 10 – SCI preset

```powershell
easyfig plot --table examples/output/data/lots.csv --time-column Size `
  --chart-type line_scatter --xaxis-mode numeric --palette akun39_echarts `
  --preset sci --title "SCI 期刊风格：批次对比" --xlabel Size --x-unit in `
  --ylabel Thrust --y-unit kg --legend-loc "upper left" -o examples/output/10-sci-preset.png
```

## Notes

* A broken axis follows the [Matplotlib broken-axis example](https://matplotlib.org/stable/gallery/subplots_axes_and_figures/broken_axis.html)
  and [`brokenaxes`](https://github.com/bendichter/brokenaxes): a small gap
  between panels, 45-degree strokes on every edge facing a join, inner spines
  hidden, inner ticks moved outboard and unlabelled, one shared tick interval,
  and no tick labelled on the join itself. A connecting line is **broken at the
  panel edge** rather than drawn through it — drawn straight through it would be
  clipped into a stub that reads as a measurement. This applies to an X break
  too, where the stub would be horizontal.
* `--chart-type scatter` / `line_scatter` set the series toggles themselves
  (`--show-mean`, `--show-connecting-line`), so passing them explicitly is only
  needed to override the default for a type.
* Charts can also be exported as `.pdf`, `.svg`, `.jpg` or `.tiff` by changing
  the output extension, and `--dpi`, `--width`, `--height`, `--tight` control
  the output size.
* The same data can be opened in the Electron app
  (`npm start` → 导入表格…), which uses the identical engine.
