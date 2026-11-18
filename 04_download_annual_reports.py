"""
STEP 04 – Download the companies' annual reports.

Input : data/input/annual_reports.csv   (one row per company + year, with the PDF link)
Output: data/annual_reports/<SYMBOL>_<FY>.pdf  (or .htm for SEC filings)
        data/output/annual_report_downloads.csv  (what worked, what failed)
Run:  python 04_download_annual_reports.py

Where to find a link if the 'url' column is empty:
  - NSE: nseindia.com -> search the company -> "Corporate Information"/"Annual Reports"
  - BSE: bseindia.com -> company page -> "Annual Reports"
  - The company's own website -> Investors -> Annual Reports
Right-click the PDF link -> "Copy link address" -> paste into the 'url' column.

You can also skip downloading: just save the PDF yourself into data/annual_reports/
with the name  SYMBOL_FY.pdf   e.g.  PFIZER_FY2025-26.pdf   Step 05 will find it.
Files that already exist are not downloaded again.
"""
import time

import pandas as pd
import requests
import urllib3

import config

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "application/pdf,text/html,*/*"}

lst = pd.read_csv(config.INPUT / "annual_reports.csv", encoding="utf-8-sig").fillna("")
log = []
for r in lst.itertuples():
    if not r.url:
        print(f"  NO LINK  {r.nse_symbol} {r.fy}  -> add the link in annual_reports.csv (or save the PDF yourself)")
        log.append({"nse_symbol": r.nse_symbol, "fy": r.fy, "status": "no link"})
        continue
    ext = ".htm" if r.url.lower().split("?")[0].endswith((".htm", ".html")) else ".pdf"
    target = config.ANNUAL_REPORTS / f"{r.nse_symbol}_{r.fy}{ext}"
    if target.exists() and target.stat().st_size > 10_000:
        print(f"  HAVE     {target.name}")
        log.append({"nse_symbol": r.nse_symbol, "fy": r.fy, "status": "already downloaded", "file": target.name})
        continue
    headers = dict(HEADERS)
    if "sec.gov" in r.url:                                   # SEC wants a real contact in the User-Agent
        headers["User-Agent"] = config.SEC_USER_AGENT
    status = ""
    for attempt in range(3):
        try:
            try:
                resp = requests.get(r.url, headers=headers, timeout=120, stream=True)
            except requests.exceptions.SSLError:            # some Indian sites have broken certificates
                urllib3.disable_warnings()
                resp = requests.get(r.url, headers=headers, timeout=120, stream=True, verify=False)
            resp.raise_for_status()
            with open(target, "wb") as f:
                for chunk in resp.iter_content(256 * 1024):
                    f.write(chunk)
            size_mb = target.stat().st_size / 1e6
            first = open(target, "rb").read(5)
            if ext == ".pdf" and first != b"%PDF-":
                status = "downloaded but NOT a PDF (probably a web page) - get the direct PDF link"
            else:
                status = f"ok ({size_mb:.1f} MB)"
            break
        except Exception as e:
            status = f"failed: {type(e).__name__}: {e}"
            time.sleep(5)
    print(f"  {status[:10]:10} {target.name}")
    log.append({"nse_symbol": r.nse_symbol, "fy": r.fy, "status": status, "file": target.name, "url": r.url})

pd.DataFrame(log).to_csv(config.OUTPUT / "annual_report_downloads.csv", index=False, encoding="utf-8-sig")
print("\nSaved data/output/annual_report_downloads.csv")
