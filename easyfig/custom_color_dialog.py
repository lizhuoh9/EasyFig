"""
Custom English-only colour picker with a built-in scientific palette library.

The dialog offers three ways to choose a colour:

1. **Presets** - the quick-pick swatches from :data:`config.BASE_COLORS`.
2. **Scientific palettes** - the ten published journal palettes in
   :mod:`easyfig.palettes`.  Pick a palette from the dropdown and click any
   swatch; the swatch label is the 1-based position inside the palette, so
   ``P42 Nature 3`` is the same colour as ``palette_colors("akun42_nature")[2]``.
3. **Custom value** - any ``#rgb``/``#rrggbb`` value or matplotlib colour name.

:func:`askcolor` is a drop-in replacement for ``tkinter.colorchooser.askcolor``.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .config import BASE_COLORS
from .palettes import (
    PALETTE_ORDER,
    SCIENTIFIC_PALETTES,
    normalize_color,
    palette_colors,
    palette_series_label,
    text_color_for,
)

# Geometry of the dialog.  The height is driven by the content so the palette
# panel never leaves a gap; only the width is fixed, which also bounds the
# wraplength used for the palette description.
DIALOG_WIDTH = 470
MIN_DIALOG_HEIGHT = 440
SWATCH_COLUMNS = 6
COMBO_WIDTH = 46


class _Tooltip:
    """Minimal hover tooltip.

    The previous implementation only altered the button relief, which gave no
    way to tell two similar swatches apart.
    """

    def __init__(self, widget, text, delay=350):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id = None
        self._window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        try:
            self._after_id = self.widget.after(self.delay, self._show)
        except Exception:
            self._after_id = None

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._window is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
            window = tk.Toplevel(self.widget)
            window.wm_overrideredirect(True)
            window.wm_geometry(f"+{x}+{y}")
            tk.Label(window, text=self.text, background="#ffffe0",
                     relief=tk.SOLID, borderwidth=1, padx=4, pady=1).pack()
            self._window = window
        except Exception:
            self._window = None

    def _hide(self, _event=None):
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None


class EnglishColorDialog:
    """Colour picker with presets, journal palettes and a free-form entry."""

    def __init__(self, parent, initial_color="#FF0000", title="Choose Color",
                 on_change=None):
        self.on_change = on_change
        try:
            self.selected_color = normalize_color(initial_color, "#ff0000")
        except ValueError:
            self.selected_color = "#ff0000"
        if self.selected_color is None:
            self.selected_color = "#ff0000"

        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)

        self.result = None
        self._palette_swatches = []
        self._create_widgets()

        # Let Tk size the dialog to its content, then place it over the parent.
        self.dialog.update_idletasks()
        self.dialog.minsize(DIALOG_WIDTH, MIN_DIALOG_HEIGHT)
        try:
            width = max(self.dialog.winfo_reqwidth(), DIALOG_WIDTH)
            height = max(self.dialog.winfo_reqheight(), MIN_DIALOG_HEIGHT)
            x = parent.winfo_x() + (parent.winfo_width() - width) // 2
            y = parent.winfo_y() + (parent.winfo_height() - height) // 3
            self.dialog.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass

    # -- construction -------------------------------------------------------

    def _create_widgets(self):
        self._create_preset_section()
        self._create_palette_section()
        self._create_preview_section()
        self._create_custom_section()
        self._create_button_row()

    def _create_preset_section(self):
        frame = ttk.LabelFrame(self.dialog, text="Color Presets", padding="8")
        frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        for index, (name, color) in enumerate(BASE_COLORS.items()):
            button = tk.Button(
                frame, bg=color, activebackground=color, width=3, height=1,
                relief=tk.RAISED, borderwidth=1,
                command=lambda c=color, n=name: self.select_preset(c, n),
            )
            button.grid(row=index // SWATCH_COLUMNS, column=index % SWATCH_COLUMNS,
                        padx=2, pady=2, sticky="nsew")
            _Tooltip(button, f"{name}  {color}")

    def _create_palette_section(self):
        frame = ttk.LabelFrame(self.dialog, text="Scientific Palettes (10)",
                               padding="8")
        frame.pack(fill=tk.X, padx=10, pady=5)

        chooser = ttk.Frame(frame)
        chooser.pack(fill=tk.X)
        ttk.Label(chooser, text="Palette:").pack(side=tk.LEFT)
        self.palette_var = tk.StringVar()
        self.palette_combo = ttk.Combobox(
            chooser, textvariable=self.palette_var, state="readonly",
            width=COMBO_WIDTH,
            values=[self._palette_choice_label(name) for name in PALETTE_ORDER],
        )
        self.palette_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        self.palette_combo.bind("<<ComboboxSelected>>", self._on_palette_change)
        self.palette_combo.current(0)

        self.palette_info = ttk.Label(frame, text="", wraplength=DIALOG_WIDTH - 50,
                                      justify=tk.LEFT, foreground="#555555")
        self.palette_info.pack(fill=tk.X, pady=(6, 4))

        self.swatch_frame = ttk.Frame(frame)
        self.swatch_frame.pack(fill=tk.X)

        ttk.Label(frame,
                  text="Tip: the number on each swatch is its 1-based position "
                       "in the palette.").pack(fill=tk.X, pady=(6, 0))

        self._render_palette_swatches()

    @staticmethod
    def _palette_choice_label(name):
        meta = SCIENTIFIC_PALETTES[name]
        return (f"{palette_series_label(name)} · {len(meta['colors'])} colors"
                f" · {meta['kind'].split('/')[0].strip()}")

    def _current_palette_key(self):
        index = self.palette_combo.current()
        if index < 0 or index >= len(PALETTE_ORDER):
            return PALETTE_ORDER[0]
        return PALETTE_ORDER[index]

    def _on_palette_change(self, _event=None):
        self._render_palette_swatches()

    def _render_palette_swatches(self):
        for child in self.swatch_frame.winfo_children():
            child.destroy()
        self._palette_swatches = []

        key = self._current_palette_key()
        meta = SCIENTIFIC_PALETTES[key]
        url = meta.get("url", "")
        self.palette_info.configure(text=" · ".join(part for part in (
            f"第{meta['issue']}期", meta["journal"], meta["kind"],
            meta.get("note", ""),
        ) if part))

        for index, color in enumerate(palette_colors(key)):
            name = f"{palette_series_label(key)} {index + 1}"
            button = tk.Button(
                self.swatch_frame, bg=color, activebackground=color,
                fg=text_color_for(color), width=3, height=1, borderwidth=1,
                relief=tk.RAISED, text=str(index + 1),
                command=lambda c=color, n=name: self.select_preset(c, n),
            )
            button.grid(row=index // SWATCH_COLUMNS, column=index % SWATCH_COLUMNS,
                        padx=2, pady=2, sticky="nsew")
            _Tooltip(button, f"{name}  {color}" + (f"\n{url}" if url else ""))
            self._palette_swatches.append(button)

    def _create_preview_section(self):
        frame = ttk.Frame(self.dialog)
        frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(frame, text="Selected Color:").pack(side=tk.LEFT)
        self.preview_canvas = tk.Canvas(frame, width=80, height=30,
                                        bg=self.selected_color,
                                        highlightthickness=2,
                                        highlightbackground="black")
        self.preview_canvas.pack(side=tk.LEFT, padx=8)
        self.color_label = ttk.Label(frame, text=self.selected_color)
        self.color_label.pack(side=tk.LEFT)

    def _create_custom_section(self):
        frame = ttk.LabelFrame(self.dialog, text="Custom Color (hex or name)",
                               padding="8")
        frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(frame, text="Value:").pack(side=tk.LEFT)
        self.hex_entry = ttk.Entry(frame, width=16)
        self.hex_entry.pack(side=tk.LEFT, padx=6)
        self.hex_entry.insert(0, self.selected_color)
        self.hex_entry.bind("<Return>", lambda _event: self.apply_custom())
        ttk.Button(frame, text="Apply", command=self.apply_custom).pack(side=tk.LEFT,
                                                                       padx=4)
        ttk.Label(frame, text="e.g. #4E74B3 or red").pack(side=tk.LEFT, padx=6)

    def _create_button_row(self):
        frame = ttk.Frame(self.dialog)
        frame.pack(fill=tk.X, padx=10, pady=(5, 10))
        ttk.Button(frame, text="OK", command=self.ok, width=10).pack(side=tk.RIGHT,
                                                                    padx=5)
        ttk.Button(frame, text="Cancel", command=self.cancel,
                   width=10).pack(side=tk.RIGHT)

    # -- behaviour ----------------------------------------------------------

    def _set_selected(self, color, label_text=None):
        self.selected_color = color
        self.preview_canvas.configure(bg=color)
        self.color_label.configure(text=label_text or color)
        self.hex_entry.delete(0, tk.END)
        self.hex_entry.insert(0, color)
        if self.on_change:
            try:
                self.on_change(self.selected_color)
            except Exception:
                pass

    def select_preset(self, color, name):
        """Select one of the preset or palette swatches."""
        self._set_selected(color, f"{name} ({color})")

    def apply_custom(self):
        """Validate and apply the value typed into the entry."""
        raw = self.hex_entry.get().strip()
        try:
            color = normalize_color(raw)
        except ValueError as exc:
            self.color_label.configure(text=str(exc))
            return
        if color is None:
            self.color_label.configure(text="Enter a colour value")
            return
        self._set_selected(color, color)

    def ok(self):
        self.result = ((0, 0, 0), self.selected_color)  # match colorchooser's shape
        self.dialog.destroy()

    def cancel(self):
        self.result = None
        self.dialog.destroy()

    def show(self):
        self.dialog.wait_window()
        return self.result


def askcolor(color=None, title="Choose Color", parent=None, on_change=None):
    """Drop-in replacement for ``tkinter.colorchooser.askcolor``.

    Returns ``((r, g, b), '#rrggbb')`` or ``None`` when cancelled.  The tuple is
    kept for compatibility; only the hex string is meaningful.
    """
    if parent is None:
        raise ValueError("askcolor() needs a parent widget")
    dialog = EnglishColorDialog(parent, color, title, on_change)
    return dialog.show()
