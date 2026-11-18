"""
STEP 00 – Check that everything is installed and the folders exist.
Run:  python 00_check_setup.py
"""
import importlib
import shutil
import sys
from pathlib import Path

import config

print(f"Python version: {sys.version.split()[0]}  (3.10 or newer is best)")

missing = []
for package, import_name in [("pymupdf", "pymupdf"), ("pytesseract", "pytesseract"), ("pillow", "PIL"),
                             ("psutil", "psutil"), ("pandas", "pandas"), ("openpyxl", "openpyxl"),
                             ("rapidfuzz", "rapidfuzz"), ("requests", "requests"),
                             ("yfinance", "yfinance"), ("matplotlib", "matplotlib")]:
    try:
        importlib.import_module(import_name)
        print(f"  OK       {package}")
    except ImportError:
        print(f"  MISSING  {package}")
        missing.append(package)
if missing:
    print("\nInstall the missing ones with:\n  python -m pip install " + " ".join(missing))

tess = shutil.which("tesseract") or (r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                                     if Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists() else None)
print(f"\nTesseract OCR program: {tess or 'NOT FOUND (only needed for scanned pages in step 01)'}")

print("\nFolders:")
for label, folder in [("Crawler downloads", config.CRAWLER_DOWNLOADS), ("Markdown output", config.MARKDOWN_OUTPUT),
                      ("Input CSVs", config.INPUT), ("Outputs", config.OUTPUT),
                      ("Annual reports", config.ANNUAL_REPORTS)]:
    print(f"  {'OK     ' if folder.exists() else 'MISSING'} {label}: {folder}")

over = list(config.CRAWLER_DOWNLOADS.rglob("*overcharg*.pdf")) if config.CRAWLER_DOWNLOADS.exists() else []
print(f"\nOvercharging PDFs found in crawler downloads: {len(over)}")
if config.SEC_USER_AGENT.startswith("YourName"):
    print("\nREMINDER: put your own name + email in SEC_USER_AGENT in config.py before step 09.")
print("\nDone.")
