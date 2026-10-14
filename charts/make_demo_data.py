"""
Generate demo measurement data for the CLI examples.

Everything here is synthetic but shaped like the real thing: linear responses
with noise, a saturating response, a signal that needs smoothing, a dataset with
planted gross outliers, a dataset with a large gap for the broken axis, and
multi-file series with repeats for mean +- SD / SEM.

Run it from the repository root::

    python charts/make_demo_data.py

Then see charts/README.md for the commands that turn it into figures.
"""

from __future__ import annotations

import csv
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

SIZES = [1, 2, 3, 4, 5, 6, 7, 8]


def write_rows(path, header, rows):
    # utf-8-sig matches what Excel writes for "CSV UTF-8".
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  {os.path.relpath(path, HERE)}")


def write_multiline(path, label, sizes, repeats, noise, slope, intercept, rng):
    """A multi-line file: header row is X, one row per repeat."""
    rows = []
    for repeat in range(repeats):
        row = [f"r{repeat + 1}"]
        for size in sizes:
            value = slope * size + intercept + rng.normal(0, noise)
            row.append(round(float(value), 3))
        rows.append(row)
    write_rows(path, [label] + sizes, rows)


def main():
    os.makedirs(DATA, exist_ok=True)
    rng = np.random.default_rng(20240607)

    print("writing demo data to charts/data")

    # 1. Linear response, one measurement per size -> linear regression.
    x = np.array(SIZES, dtype=float)
    y = 2.4 * x + 1.1 + rng.normal(0, 0.9, x.size)
    write_rows(os.path.join(DATA, "linear.csv"), ["Size", "Thrust"],
               [[s, round(float(v), 3)] for s, v in zip(x, y)])

    # 2. Saturating response -> polynomial fit.
    xs = np.arange(0, 11, dtype=float)
    ys = 12.0 * (1.0 - np.exp(-0.55 * xs)) + rng.normal(0, 0.35, xs.size)
    write_rows(os.path.join(DATA, "saturating.csv"), ["Time", "Response"],
               [[t, round(float(v), 3)] for t, v in zip(xs, ys)])

    # 3. Linear response with three gross outliers -> outlier removal.
    y_out = 2.4 * x + 1.1 + rng.normal(0, 0.6, x.size)
    y_out[2] += 22.0
    y_out[5] -= 18.0
    y_out[7] += 15.0
    write_rows(os.path.join(DATA, "outliers.csv"), ["Size", "Thrust"],
               [[s, round(float(v), 3)] for s, v in zip(x, y_out)])

    # 4. Noisy signal -> moving-average smoothing.
    t = np.arange(0, 61, dtype=float)
    signal = 10.0 + 3.0 * np.sin(t / 4.5) + rng.normal(0, 1.6, t.size)
    write_rows(os.path.join(DATA, "signal.csv"), ["Time", "Signal"],
               [[tt, round(float(v), 3)] for tt, v in zip(t, signal)])

    # 5. A large gap -> broken axis.
    gap_x = [1, 2, 3, 4, 5, 6]
    gap_y = [12.4, 13.1, 12.8, 210.5, 214.2, 211.9]
    write_rows(os.path.join(DATA, "gap.csv"), ["Position", "Load"],
               [[a, b] for a, b in zip(gap_x, gap_y)])

    # 6. Multi-file series with repeats -> mean +- SD, SEM, per-size error bars.
    write_multiline(os.path.join(DATA, "lot_a.csv"), "Lot A", SIZES, 4, 4.2, 10.2, 1.5, rng)
    write_multiline(os.path.join(DATA, "lot_b.csv"), "Lot B", SIZES, 4, 5.6, 12.4, 0.4, rng)

    # 7. Table form of the same experiment for the table importer.
    write_rows(
        os.path.join(DATA, "lots.csv"),
        ["Size", "Lot A", "Lot B", "Lot C"],
        [[s] + [round(float(slope * s + intercept + rng.normal(0, 1.1)), 3)
                for slope, intercept in ((10.2, 1.5), (12.4, 0.4), (9.1, 2.2))]
         for s in SIZES],
    )

    print("done")


if __name__ == "__main__":
    main()
