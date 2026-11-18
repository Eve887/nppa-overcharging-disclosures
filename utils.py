"""
utils.py  –  small helper functions shared by all step scripts.
"""
import re
from datetime import datetime

import pandas as pd


def to_number(text):
    """'1,234.50' -> 1234.5 ;  '-', '', 'Nil' -> 0.0 ;  anything unreadable -> None"""
    if text is None:
        return None
    t = str(text).strip().replace(",", "").replace("₹", "").replace("Rs.", "").strip()
    if t in ("", "-", "--", "nil", "Nil", "NIL", "NA", "N.A.", "0"):
        return 0.0
    try:
        return float(t)
    except ValueError:
        return None


NUMBER_TOKEN = re.compile(r"^-?\(?\d[\d,]*\.?\d*\)?$|^-$")


def number_tokens(cell):
    """All number-like pieces inside one table cell (a merged cell can hold several)."""
    return [x for x in str(cell or "").split() if NUMBER_TOKEN.match(x)]


def save_excel(sheets, path):
    """
    Save one or more tables to an Excel file.
    sheets = {"Sheet name": dataframe, ...}
    Plain typed values only: no formulas, no merged cells, nothing locked.
    """
    from openpyxl.styles import Alignment, Font, PatternFill
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for row in ws.iter_rows():
                for c in row:
                    c.font = Font(name="Arial", size=10)
                    c.alignment = Alignment(vertical="top", wrap_text=False)
            for c in ws[1]:
                c.font = Font(name="Arial", size=10, bold=True)
                c.fill = PatternFill("solid", fgColor="DDEBF7")
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
            ws.freeze_panes = "A2"
    print(f"Saved Excel: {path}")


def stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M")
