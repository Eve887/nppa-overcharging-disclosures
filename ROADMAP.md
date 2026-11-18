# NPPA Overcharging Demands vs Company Disclosures — Full Roadmap

This file explains how to run the whole project on a Windows laptop, in PowerShell.
Every step is one Python script. Run them in number order. Each script tells you what it did and what to check next.

---

## 0. What the project answers

**Question:** NPPA (National Pharmaceutical Pricing Authority) publishes how much money it says each drug company owes for
*overcharging*, which means selling a medicine above the government's ceiling price. Do listed companies show the same
amount to investors in their annual reports? If not, how big is the difference, and do they explain it?

**The three layers this project covers:**

| Layer | What it is in this project |
|---|---|
| Regulatory | NPPA, DPCO 1979 / 1987 / 1995 / 2013 (Drugs Prices Control Orders), ceiling prices, demand notices, court cases |
| Finance | Ind AS 37 accounting: **provision** (money already booked as an expense) vs **contingent liability** (only mentioned in the notes); materiality (size compared with profit); share-price reaction |
| Data science | Crawling, OCR, PDF-table parsing, name matching (fuzzy matching), reconciliation, event study, charts |

**What the pilot (7 Nov 2026) already found:** Cipla explains its large gap in detail. AstraZeneca matches NPPA almost exactly.
Sun Pharma's notes don't name NPPA or DPCO at all (only a "DPEA" line), which leaves ~₹426 crore unexplained.
Zydus's report showed nothing in an automated search. Pfizer, Wockhardt, Lupin, Sanofi India and Ipca are not checked yet.

---

## 1. Folder layout

```
NPPA_Project\
│  ROADMAP.md                     <- this file
│  config.py                      <- ALL folder paths and settings (edit once)
│  utils.py                       <- small shared helpers (no need to touch)
│  requirements.txt               <- list of Python libraries
│  00_check_setup.py ... 10_build_report.py   <- the steps
│
└─ data\
   ├─ input\        <- CSV files YOU edit (open in Excel, save as CSV)
   │     company_aliases.csv       name patterns -> listed company (pre-filled, ~45 rows)
   │     annual_reports.csv        annual report links (5 filled, 5 for you to find)
   │     company_disclosures.csv   what each company says (5 pre-filled from the pilot)
   │     financials.csv            revenue, profit, net worth (you fill)
   │     events.csv                dates of NPPA announcements for the event study (1 pre-filled)
   ├─ annual_reports\   <- downloaded annual report PDFs
   └─ output\           <- everything the scripts create (Excel, CSV, charts, final report)
```

**Saving CSV files from Excel:** File → Save As → choose **"CSV UTF-8 (Comma delimited)"**. Plain "CSV" can break the ₹ sign.

---

## 2. One-time setup (≈30 minutes)

**2.1 Copy this folder** to `G:\SANSK\NPPA_Project\`

**2.2 Open PowerShell and go to the folder:**
```powershell
cd G:\SANSK\NPPA_Project
```

**2.3 Install the Python libraries:**
```powershell
python -m pip install -r requirements.txt
```

**2.4 Install Tesseract OCR.** You only need it for scanned PDFs in step 01. Open PowerShell **as Administrator**:
```powershell
winget install -e --id UB-Mannheim.TesseractOCR
Invoke-WebRequest -Uri "https://github.com/tesseract-ocr/tessdata/raw/main/hin.traineddata" -OutFile "C:\Program Files\Tesseract-OCR\tessdata\hin.traineddata"
```
Close that window and open a normal PowerShell again.

**2.5 Check paths in `config.py`.** Open it in Notepad or VS Code:
- `CRAWLER_DOWNLOADS`: the folder where your crawler saved the NPPA files
- `SEC_USER_AGENT`: change it to **your name and your email** (SEC rule, needed for step 09)

**2.6 Run the check:**
```powershell
python 00_check_setup.py
```
Everything should say **OK**, and it should find your overcharging PDFs. Fix anything marked MISSING before going on.

---

## 3. The steps

> **Tip:** every script can be stopped with **Ctrl + C** and run again. Steps 01 and 04 skip work that's already done.
> If a script shows an error, read the **last line** first. It usually names the problem (a missing file, a wrong path).

### STEP 01 — Turn all crawled PDFs into searchable Markdown (optional but useful)
```powershell
# Pass 1: fast, text pages only (minutes)
python 01_pdf_to_markdown.py --input "G:\SANSK\NPPA_Crawler\downloads\phase_10" --output "G:\SANSK\NPPA_Crawler\markdown" --gentle --no-ocr
# Pass 2: scanned pages with OCR, slow, only while charging (hours, can be spread over days)
python 01_pdf_to_markdown.py --input "G:\SANSK\NPPA_Crawler\downloads\phase_10" --output "G:\SANSK\NPPA_Crawler\markdown" --gentle --only-when-charging
```
- **Result:** `markdown\INDEX.md` lists every document, sorted into groups (overcharging lists, Authority minutes, gazette orders...).
- **Why it helps:** you can search all ~2,300 NPPA documents at once. In VS Code, use "Search in folder" (Ctrl + Shift + F) and type a company name, e.g. `Ranbaxy`.
- The main pipeline (steps 02 onwards) does **not** depend on this step.

### STEP 02 — Parse every NPPA overcharging list into one table
```powershell
python 02_parse_overcharging_lists.py
```
- **What it does:** finds every company-wise list (file names with "overcharg", "stmt-" or "detailed", **plus** every PDF that step 01
  sorted into `01_overcharging_lists`), finds the tables, splits cells that hold 2 or more companies, fixes rows NPPA printed twice
  ("KiviKivi LabsLabs"), reads each table's unit (lakh or crore) from its own header, and converts everything to crore.
- **Dates:** the "data up to" date printed inside the PDF (e.g. "till 28.02.2017", "UPTO DECEMBER 2018") is used first; the file name is the backup.
- **What you have:** company-wise lists from **Feb 2017 to March 2026** (about 30 lists). Year-wise summaries are skipped on purpose,
  but keep them: they hold NPPA's own totals (e.g. "amount still under litigation") for checking.
- **Results in `data\output\`:**
  - `overcharging_cases_all_lists.csv`: one row per case per list date
  - `overcharging_list_summary.csv`: totals per list. **CHECK THIS FIRST**
  - `overcharging_rows_to_review.csv`: rows the script wasn't sure about
- **How to check (important):**
  1. In `overcharging_list_summary.csv`, compare `outstanding_total_crore_parsed` with `nppa_printed_total_crore`.
     A difference under ~3% is fine. A big difference means some rows weren't read.
  2. For the March 2026 list, the total should be about **₹8,200–8,550 crore**. The Parliamentary committee reported ₹8,526 crore unrecovered as of Sept 2025.
  3. Files marked "SCANNED" have no text. Run step 01 on them, then copy the numbers by hand if needed.
  4. Files marked "no company table found" are usually year-wise summaries. That's fine; they are not company lists.
  5. Open `overcharging_rows_to_review.csv`, sorted by `outstanding_crore` (biggest first). Check the top 20 against the PDF, using the `page` column.
- **Tested:** on a copy of the March 2026 table (1,149 rows, ₹8,259 crore; the J.B. Chemicals row matched NPPA exactly), and on a test PDF with NPPA's layout (all values correct, total matched).
  Real PDFs from other years may use a different layout. If a year fails, look at the error, check that list's header names, and add words to `HEADER_RULES` at the top of the script.

### STEP 03 — Match NPPA's company names to listed companies
```powershell
python 03_map_companies.py
```
- **Results:** `company_panel.xlsx` / `.csv` (one row per company per list date), `cases_with_companies.csv`, `unmatched_names_to_check.csv`.
- **Your job:** open `unmatched_names_to_check.csv` (biggest amounts first). If a name belongs to a listed company, add a row to
  `data\input\company_aliases.csv` and run step 03 again. Repeat until the big names are matched.
- **Decisions you must make yourself, and write down in the report:**
  - Joint lines like "Okasa / Cipla": counted for Cipla. Cipla says joint Okasa demands are excluded.
  - Ranbaxy → Sun Pharma (merged 2015). Wyeth → Pfizer. Cadila Healthcare → Zydus. But **Cadila Pharmaceuticals is a different company**.
  - Legacy names (Hoechst, Boots, Cyanamid) are marked `legacy`. Decide whether to add them to Sanofi, Abbott or Pfizer.
- **Expected:** the top listed companies should be Cipla, Sun, AstraZeneca, Dr. Reddy's, Pfizer, Zydus, Wockhardt, Lupin, Sanofi, Ipca.

### STEP 04 — Download annual reports
1. Open `data\input\annual_reports.csv`. Five links are filled. For **Pfizer, Wockhardt, Lupin, Sanofi India, Ipca**, find the FY2025-26 annual report:
   - **NSE:** nseindia.com → search the company → Corporate Information → Annual Reports
   - **BSE:** bseindia.com → company → Annual Reports
   - or the company website → Investors
   Right-click the PDF → Copy link address → paste it in the `url` column. **Sanofi's year ends 31 December**, so use CY2025.
2. Run:
```powershell
python 04_download_annual_reports.py
```
- If a download fails, download the PDF in your browser and save it as `data\annual_reports\SYMBOL_FY.pdf`,
  e.g. `PFIZER_FY2025-26.pdf`.

### STEP 05 — Find the NPPA/DPCO pages in each annual report
```powershell
python 05_find_disclosures.py
```
- **Results:** `data\output\disclosures\SYMBOL_FY.md` (only the matching passages, with page numbers) and `disclosure_search_summary.xlsx`.
- **Your job, which is the heart of the project:** for each company, read the passages **and** the full contingent-liabilities note
  (usually titled "Contingent liabilities and commitments"). Then fill one row in `data\input\company_disclosures.csv`:

| Column | What to write |
|---|---|
| company_figure_crore | The amount the company gives for NPPA/DPCO matters, in ₹ crore (1 crore = 10 million = 100 lakh) |
| figure_covers | In your words: what that number includes |
| contingent_liability_crore / provision_crore / deposits_crore | Split, if the company gives it |
| names_nppa, names_dpco | yes / no |
| gives_principal_interest_split | yes / no |
| explains_gap | yes / partly / no / not needed (if the gap is tiny) |
| stated_reason | The company's reason, in your words |
| auditor_kam | yes if the auditor's report has a "Key Audit Matter" on it |
| note_reference | e.g. "Note 38(A), page 212" |
| checked_by_hand | **yes** only after YOU read the note |

- **Must-do checks from the pilot:**
  - **Sun Pharma:** read Note 38 fully. Is NPPA money hidden inside "Claims not acknowledged as debts"? This decides the headline.
  - **Zydus:** the automated search found nothing. Read the contingent liabilities note.
  - **Dr. Reddy's:** the pilot used the US Form 20-F. Also read the Indian annual report.
- **Unit conversions:** ₹ million ÷ 10 = ₹ crore. ₹ lakh ÷ 100 = ₹ crore. Example: Rs 1,573.9 million = ₹157.39 crore.

### STEP 06 — Reconciliation (the main result)
Also fill `data\input\financials.csv` (revenue, net profit, net worth from each standalone statement). Then:
```powershell
python 06_reconcile.py
```
- **Result:** `reconciliation.xlsx`, with the gap, disclosure score (0–5), verdict and materiality for each company.
- **Decision rule (from the pilot):**
  - **3 or more** of 10 with a big unexplained gap or no figure → strong headline. Go ahead with the full project.
  - **1–2** → still a good project, framed as a "ranking of disclosure quality".
  - **0** → the finding is "companies disclose well". That's true but weak, so consider moving to your next project.
- The verdict says "provisional" until you set `checked_by_hand` = yes.

### STEP 07 — Trends 2019 → 2026 and charts
```powershell
python 07_trends_and_charts.py
```
- **Results:** `trends.xlsx` and `data\output\charts\*.png`. Use the charts in your report and slides.
- **Look for:** which companies' amounts grew or fell, how much is new vs old, and the share under litigation.

### STEP 08 — Share-price reaction (event study)
1. Collect events in `data\input\events.csv`: search NSE/BSE **Corporate Announcements** for "NPPA", "DPCO" and "overcharg".
   Companies must report such notices under SEBI Regulation 30. Note the exact date. **If filed after 3:30 pm, use the next trading day.**
2. Run:
```powershell
python 08_event_study.py
```
- Prices come from Yahoo Finance (`SYMBOL.NS`) via the `yfinance` library. If downloading fails, make a CSV with columns
  `date, CIPLA.NS, ^NSEI ...` and run `python 08_event_study.py --prices-csv yourfile.csv`.
- **How to read it:** CAR = cumulative abnormal return, meaning how much the stock moved beyond what the market explains.
  |t| > 2 (p < 0.05) suggests a real reaction. **With fewer than ~10 events, call them case studies, not proof.**

### STEP 09 — International layer: foreign parents' US filings
Check that `SEC_USER_AGENT` in config.py has your name and email. Then:
```powershell
python 09_parent_filings_sec.py
```
- **Result:** `sec_nppa_mentions.xlsx`, listing every US SEC filing that mentions NPPA, with the passage and amounts.
- **Compare three numbers for each foreign-owned company** (AstraZeneca, Pfizer, Sanofi, Abbott, Novartis, GSK): the parent's US filing, the Indian company's annual report, and NPPA's list.
  Example from the pilot: AstraZeneca PLC said about **$21 million plus interest** for Tagrisso, the Indian company said **₹157.39 crore**, and NPPA said **₹157.4 crore**.
- If the script's search fails, search by hand at https://www.sec.gov/edgar/search/ for `"National Pharmaceutical Pricing Authority"`.

### STEP 10 — Build the final report
```powershell
python 10_build_report.py
```
- **Result:** `data\output\FINAL_REPORT.md`, with tables and charts filled in automatically and **[bracketed] parts for you to write**.
- Open it in VS Code (Ctrl + Shift + V shows the preview) or Typora, or paste it into Word or Google Docs.

---

## 4. Suggested timetable (fits your 1–2 week target)

| Day | Work | Steps |
|---|---|---|
| 1 | Setup; parse all lists; check totals | 00, 02 |
| 2 | Company matching; fix aliases | 03 |
| 3 | Find and download annual reports; run the search | 04, 05 |
| 4–5 | **Read notes by hand** for the 10 companies; fill disclosures + financials | 05 → 06 |
| 6 | Reconciliation; decide go / reframe / stop | 06 |
| 7 | Trends and charts | 07 |
| 8 | Collect events; event study | 08 |
| 9 | SEC parent filings; international comparison | 09 |
| 10 | Write the report | 10 |
| Background | OCR of all PDFs, only while charging | 01 |

**Optional extensions**, if the result is strong: expand from 10 to 25–30 listed companies (add rows to the input CSVs, then run steps 04–06 again),
and compare FY2024-25 vs FY2025-26 for the same companies.

---

## 5. Common problems and fixes

| Problem | Fix |
|---|---|
| `python` is not recognized | Reinstall Python with "Add to PATH" ticked, or use `py` instead of `python` |
| `ModuleNotFoundError: No module named 'x'` | `python -m pip install x` |
| `FileNotFoundError ... company_panel.csv` | You skipped a step. Run the steps in order (02 → 03 → ...) |
| `PermissionError` while saving | Close the Excel/CSV file that is open, then run again |
| Step 02 total far from NPPA's total | Check `overcharging_rows_to_review.csv` and that list's header names. Add words to `HEADER_RULES` |
| Step 04 "NOT a PDF" | The link was a web page. Open it in the browser and copy the direct PDF link |
| Step 05 "pages have no text" | That report is scanned. Run step 01 on it (OCR), then read the Markdown |
| Step 08 price download fails | Check your internet, or use `--prices-csv` with prices saved from NSE |
| Step 09 403 error | Put your real name and email in `SEC_USER_AGENT` |
| Garbled ₹ / Hindi in CSV | Open the CSV in Excel via Data → From Text/CSV → UTF-8, and save as "CSV UTF-8" |

---

## 6. Rules to keep the work trustworthy

1. **Never trust an automated "not found".** Read the note yourself before writing "the company does not disclose".
2. **Keep a source for every number**: file name + page, filled in `note_reference` and `source_url`.
3. **Write down every judgement call**: joint cases, legacy names, which NPPA list date matches which financial year.
4. **Say what you could not check**: scanned pages, rows flagged for review, small event sample.
5. This is research, not legal or investment advice. Say so in the report.

---

## 7. Key facts and sources to cite

- NPPA "Status of Overcharging Cases upto March 2026":
  https://nppa.gov.in/storage/uploads/pdf/b-status-of-overcharging-cases-upto-march-2026-a14044926da64a8d44a8e9ca865f78d1.pdf
- Parliamentary Standing Committee report (6 Aug 2026), summarised by PRS Legislative Research: ₹8,526 crore (85%) unrecovered
  as of 30 Sept 2025, ~70% under litigation, some cases over 20 years old; recommends a dedicated legal cell in NPPA.
- Cipla FY2025-26 annual report, Notes 9 and 40A: ₹2,011 crore (principal ₹863 crore + interest ₹1,148 crore), deposits ₹175.08 crore + ₹27.07 crore.
- AstraZeneca Pharma India FY2025-26 annual report, Note 32(b): regulatory demand ₹1,573.9 million as a contingent liability.
- AstraZeneca Symbicort demand notice ₹148.66 crore, received 29 July 2026 (Regulation 30 disclosure).
- Dr. Reddy's Form 20-F FY2026, Note 31 (NPPA: Norfloxacin; cardiovascular/anti-diabetic formulations).
- SEC EDGAR full-text search: https://www.sec.gov/edgar/search/
