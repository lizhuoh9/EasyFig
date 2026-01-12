"""
Main entry point for Thrust Analysis Tool
"""
import tkinter as tk
from application import DataAnalysisGUI

def main():
    """Main function to run the application"""
    root = tk.Tk()
    app = DataAnalysisGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()