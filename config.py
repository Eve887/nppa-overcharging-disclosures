"""
config.py  –  ONE place for all folder paths and settings.
Change the paths here once; every step script reads them from this file.
"""
from pathlib import Path

# Folder where this project lives (the folder containing this config.py)
PROJECT = Path(__file__).resolve().parent

# ---- Your crawler's files (change if your folders are different) ----
CRAWLER_DOWNLOADS = Path(r"G:\SANSK\NPPA_Crawler\downloads\phase_10")   # all downloaded NPPA files
MARKDOWN_OUTPUT   = Path(r"G:\SANSK\NPPA_Crawler\markdown")             # where step 01 writes Markdown

# ---- Project data folders (created automatically) ----
DATA           = PROJECT / "data"
INPUT          = DATA / "input"            # CSV files YOU fill in / edit
OUTPUT         = DATA / "output"           # everything the scripts produce
ANNUAL_REPORTS = DATA / "annual_reports"   # company annual report PDFs
CHARTS         = OUTPUT / "charts"

for folder in (DATA, INPUT, OUTPUT, ANNUAL_REPORTS, CHARTS):
    folder.mkdir(parents=True, exist_ok=True)

# ---- Settings ----
# The financial year you are reconciling, and the NPPA list date that matches its year-end.
TARGET_FY = "FY2025-26"
TARGET_LIST_DATE = "2026-03-31"     # NPPA "Status of overcharging cases upto March 2026"

# A gap bigger than this (Rs crore) with no explanation counts as a "big unexplained gap".
BIG_GAP_CRORE = 25

# SEC (USA) asks every automated user to identify themselves.
# Put YOUR OWN name and email here before running step 09.
SEC_USER_AGENT = "Your Name your.email@example.com"

# Benchmarks for the share-price event study (step 08), Yahoo Finance codes.
MARKET_INDEX = "^NSEI"          # Nifty 50
SECTOR_INDEX = "^CNXPHARMA"     # Nifty Pharma
