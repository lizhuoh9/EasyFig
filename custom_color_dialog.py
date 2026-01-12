"""
Custom English-only color picker dialog
"""
import tkinter as tk
from tkinter import ttk


class EnglishColorDialog:
    """Custom color picker with English interface only"""
    
    def __init__(self, parent, initial_color="#FF0000", title="Choose Color", on_change=None):
        self.result = None
        self.initial_color = initial_color
        self.on_change = on_change
        
        # Create dialog
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.geometry("400x320")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Make dialog modal
        self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)
        
        # Color presets
        self.colors = {
            'Red': '#FF0000', 'Orange': '#FF7F00', 'Yellow': '#FFFF00',
            'Green': '#00FF00', 'Cyan': '#00FFFF', 'Blue': '#0000FF',
            'Purple': '#7F00FF', 'Magenta': '#FF00FF', 'Pink': '#FF1493',
            'Brown': '#8B4513', 'Gray': '#808080', 'Black': '#000000',
            'White': '#FFFFFF', 'Dark Red': '#8B0000', 'Dark Green': '#006400',
            'Dark Blue': '#00008B', 'Navy': '#000080', 'Maroon': '#800000',
            'Olive': '#808000', 'Teal': '#008080', 'Lime': '#00FF00',
            'Aqua': '#00FFFF', 'Fuchsia': '#FF00FF', 'Silver': '#C0C0C0'
        }
        
        self.selected_color = initial_color
        self.create_widgets()
        
        # Center dialog
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.dialog.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.dialog.winfo_height()) // 2
        self.dialog.geometry(f"+{x}+{y}")
        
    def create_widgets(self):
        """Create dialog widgets"""
        # Color presets
        preset_frame = ttk.LabelFrame(self.dialog, text="Color Presets", padding="10")
        preset_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create grid of color buttons
        colors_list = list(self.colors.items())
        cols = 6
        
        for i, (name, color) in enumerate(colors_list):
            row = i // cols
            col = i % cols
            
            btn = tk.Button(preset_frame, bg=color, width=3, height=1,
                          command=lambda c=color, n=name: self.select_preset(c, n))
            btn.grid(row=row, column=col, padx=2, pady=2)
            
            # Tooltip
            self.create_tooltip(btn, name)
        
        # Preview and info
        info_frame = ttk.Frame(self.dialog)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(info_frame, text="Selected Color:").pack(side=tk.LEFT, padx=5)
        
        self.preview_canvas = tk.Canvas(info_frame, width=80, height=30,
                                        bg=self.selected_color,
                                        highlightthickness=2,
                                        highlightbackground='black')
        self.preview_canvas.pack(side=tk.LEFT, padx=5)
        
        self.color_label = ttk.Label(info_frame, text=self.selected_color)
        self.color_label.pack(side=tk.LEFT, padx=5)
        
        # Custom color entry
        custom_frame = ttk.LabelFrame(self.dialog, text="Custom Color (Hex)", padding="10")
        custom_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(custom_frame, text="Hex Code:").pack(side=tk.LEFT, padx=5)
        
        self.hex_entry = ttk.Entry(custom_frame, width=15)
        self.hex_entry.pack(side=tk.LEFT, padx=5)
        self.hex_entry.insert(0, self.selected_color)
        
        ttk.Button(custom_frame, text="Apply", 
                  command=self.apply_custom).pack(side=tk.LEFT, padx=5)
        
        # Buttons
        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(btn_frame, text="OK", command=self.ok, width=10).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.cancel, width=10).pack(side=tk.RIGHT)
    
    def create_tooltip(self, widget, text):
        """Create simple tooltip"""
        def on_enter(event):
            widget.config(relief=tk.RAISED)
        
        def on_leave(event):
            widget.config(relief=tk.FLAT)
        
        widget.bind('<Enter>', on_enter)
        widget.bind('<Leave>', on_leave)
    
    def select_preset(self, color, name):
        """Select a preset color"""
        self.selected_color = color
        self.preview_canvas.config(bg=color)
        self.color_label.config(text=f"{name} ({color})")
        self.hex_entry.delete(0, tk.END)
        self.hex_entry.insert(0, color)
        try:
            if self.on_change:
                self.on_change(self.selected_color)
        except Exception:
            pass
    
    def apply_custom(self):
        """Apply custom hex color"""
        hex_code = self.hex_entry.get().strip()
        
        # Validate hex code
        if not hex_code.startswith('#'):
            hex_code = '#' + hex_code
        
        if len(hex_code) == 7:
            try:
                # Test if valid hex
                int(hex_code[1:], 16)
                self.selected_color = hex_code.upper()
                self.preview_canvas.config(bg=self.selected_color)
                self.color_label.config(text=self.selected_color)
                try:
                    if self.on_change:
                        self.on_change(self.selected_color)
                except Exception:
                    pass
            except ValueError:
                self.color_label.config(text="Invalid hex code!")
        else:
            self.color_label.config(text="Invalid format!")
    
    def ok(self):
        """OK button clicked"""
        self.result = ((0, 0, 0), self.selected_color)  # Match colorchooser return format
        self.dialog.destroy()
    
    def cancel(self):
        """Cancel button clicked"""
        self.result = None
        self.dialog.destroy()
    
    def show(self):
        """Show dialog and return result"""
        self.dialog.wait_window()
        return self.result


def askcolor(color=None, title="Choose Color", parent=None, on_change=None):
    """
    Drop-in replacement for tkinter.colorchooser.askcolor
    Returns: ((r, g, b), '#RRGGBB') or None if cancelled
    """
    if color is None:
        color = "#FF0000"
    
    dialog = EnglishColorDialog(parent, color, title, on_change)
    return dialog.show()
