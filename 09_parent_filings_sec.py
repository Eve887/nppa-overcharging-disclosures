"""
STEP 09 – International layer: do foreign parent companies (and Indian companies listed in the
USA) mention India's NPPA in their US SEC filings? Compare that with what the Indian company says.

Example: AstraZeneca PLC's US filing said NPPA alleged overcharging on Tagrisso of about $21m plus
interest, while AstraZeneca Pharma India showed Rs 157.39 crore as a contingent liability.

Uses the free SEC EDGAR full-text search (filings from 2001 onwards).
BEFORE RUNNING: put your own name + email in SEC_USER_AGENT in config.py (SEC requires it).

Input : nothing (search words are below)
Output: data/output/sec_nppa_mentions.xlsx/.csv   one row per filing that mentions NPPA, with
                                                   company, form, date, link, the passage, amounts seen
Run:  python 09_parent_filings_sec.py
      python 09_parent_filings_sec.py --from-year 2018 --max-filings 150

If the search fails (SEC changes its website sometimes), do it by hand:
  https://efts.sec.gov/LATEST/search-index?q=%22National%20Pharmaceutical%20Pricing%20Authority%22
  or the search page  https://www.sec.gov/edgar/search/  and type: "National Pharmaceutical Pricing Authority"
"""
import argparse
import html as htmllib
import re
import time

import pandas as pd
import requests

import config
from utils import save_excel

SEARCHES = ['"National Pharmaceutical Pricing Authority"', '"NPPA" India overcharg']
FORMS = "10-K,20-F,6-K,10-Q,40-F"
AMOUNT = re.compile(r"(?:US\$|\$|₹|Rs\.?|INR)\s?\d[\d,]*(?:\.\d+)?\s*(?:million|billion|m|bn|crores?|lakhs?)?", re.I)


def headers():
    if config.SEC_USER_AGENT.startswith("YourName"):
        raise SystemExit("Put your own name and email in SEC_USER_AGENT in config.py first.")
    return {"User-Agent": config.SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}


def search(q, start, end):
    hits, frm = [], 0
    while True:
        r = requests.get("https://efts.sec.gov/LATEST/search-index",
                         params={"q": q, "forms": FORMS, "dateRange": "custom",
                                 "startdt": start, "enddt": end, "from": frm},
                         headers=headers(), timeout=60)
        r.raise_for_status()
        data = r.json().get("hits", {})
        batch = data.get("hits", [])
        hits += batch
        total = data.get("total", {}).get("value", 0)
        frm += len(batch)
        print(f"   {q}: {frm}/{total}")
        if not batch or frm >= total or frm >= 1000:
            return hits
        time.sleep(0.5)


def filing_url(hit):
    adsh, _, fname = hit["_id"].partition(":")
    cik = str(int(hit["_source"]["ciks"][0]))
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{fname}"


def passages(url):
    r = requests.get(url, headers=headers(), timeout=120)
    r.raise_for_status()
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", r.text)
    text = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", text)))
    out = []
    for m in re.finditer(r"National Pharmaceutical Pricing Authority|\bNPPA\b", text):
        out.append(text[max(0, m.start() - 600): m.end() + 900])
        if len(out) >= 3:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-year", type=int, default=2015)
    ap.add_argument("--max-filings", type=int, default=120, help="How many filings to open and read")
    args = ap.parse_args()
    start, end = f"{args.from_year}-01-01", pd.Timestamp.today().strftime("%Y-%m-%d")

    found = {}
    for q in SEARCHES:
        try:
            for h in search(q, start, end):
                found[h["_id"]] = h
        except Exception as e:
            print(f"Search failed for {q}: {e}\nUse the manual links in the notes at the top of this script.")
    print(f"Filings found: {len(found)}")

    rows = []
    for n, h in enumerate(sorted(found.values(), key=lambda h: h["_source"].get("file_date", ""), reverse=True)):
        s = h["_source"]
        url = filing_url(h)
        names = [re.split(r"\s{2,}\(|\s\(CIK", n)[0].strip() for n in s.get("display_names", [])]
        row = {"company": "; ".join(names), "form": s.get("form", ""),
               "file_date": s.get("file_date", ""), "period_ending": s.get("period_ending", ""), "url": url}
        if n < args.max_filings:
            try:
                ps = passages(url)
                row["passage"] = " ... ".join(ps)
                row["amounts_seen"] = "; ".join(sorted(set(a.strip() for p in ps for a in AMOUNT.findall(p))))[:500]
            except Exception as e:
                row["passage"] = f"could not open: {e}"
            time.sleep(0.3)                  # be polite: SEC allows max 10 requests per second
        rows.append(row)
        print(f"  {row['file_date']}  {row['form']:6} {row['company'][:60]}")

    df = pd.DataFrame(rows)
    df.to_csv(config.OUTPUT / "sec_nppa_mentions.csv", index=False, encoding="utf-8-sig")
    if len(df):
        by_company = (df.groupby("company").agg(filings=("url", "size"), first=("file_date", "min"),
                                                 latest=("file_date", "max")).reset_index()
                      .sort_values("filings", ascending=False))
        save_excel({"Filings": df, "By company": by_company}, config.OUTPUT / "sec_nppa_mentions.xlsx")
    print("\nNEXT: for each parent company, compare its US-filing amount with the Indian company's figure "
          "and NPPA's figure (add a column in your reconciliation notes).")


if __name__ == "__main__":
    main()
