"""
STEP 03 – Match NPPA's company names to listed companies, and build a company-by-date table.

NPPA writes the same company many ways ("Cipla Ltd", "Cipla Labs", "Cipla Ltd / Okasa").
This step uses YOUR list of name patterns (data/input/company_aliases.csv) to give each
case a "listed company" and NSE symbol.

Input : data/output/overcharging_cases_all_lists.csv   (from step 02)
        data/input/company_aliases.csv                  (you can edit / add rows)
Output: data/output/cases_with_companies.csv            every case + matched company
        data/output/company_panel.csv                   one row per company per list date
        data/output/unmatched_names_to_check.csv        names not matched, biggest amounts first,
                                                        with a suggested match (fuzzy matching)
        data/output/company_panel.xlsx                  same panel in Excel (plain values)
Run:  python 03_map_companies.py

To fix a wrong or missing match: add/edit a row in company_aliases.csv, then run again.
'pattern' is a "regular expression" = a search pattern. Simple words work fine, e.g.  lupin
"\b" means "word edge":  \beris\b  matches "Eris" but not "Steris".
"""
import re

import pandas as pd
from rapidfuzz import fuzz, process

import config
from utils import save_excel

cases = pd.read_csv(config.OUTPUT / "overcharging_cases_all_lists.csv", encoding="utf-8-sig")

# ---------- lists with no date: let the user type the date in once ----------
# Some PDFs have no readable date in the file name or on page 1. Their rows come with an
# empty list_date. You can give the date by hand in data/input/list_dates_manual.csv
# (columns: source_file, list_date as YYYY-MM-DD). Rows still without a date are left
# out of the company panel (but kept in cases_with_companies.csv).
cases["list_date"] = cases["list_date"].fillna("").astype(str).str.strip()
manual_path = config.INPUT / "list_dates_manual.csv"
if manual_path.exists():
    manual = pd.read_csv(manual_path, encoding="utf-8-sig", dtype=str).fillna("")
    fix = {r.source_file: r.list_date.strip() for r in manual.itertuples() if r.list_date.strip()}
    mask = cases["list_date"].eq("") & cases["source_file"].isin(fix)
    cases.loc[mask, "list_date"] = cases.loc[mask, "source_file"].map(fix)
    if mask.any():
        print(f"Dates typed in by hand were used for {cases.loc[mask, 'source_file'].nunique()} file(s).")
no_date = sorted(cases.loc[cases["list_date"] == "", "source_file"].dropna().unique())
if no_date:
    print(f"\nWARNING: {len(no_date)} file(s) have NO DATE, so they are left out of the company panel:")
    for f in no_date:
        print(f"   - {f}")
    known = pd.read_csv(manual_path, encoding="utf-8-sig", dtype=str).fillna("") if manual_path.exists() else pd.DataFrame(columns=["source_file", "list_date"])
    add = [f for f in no_date if f not in set(known["source_file"])]
    if add:
        known = pd.concat([known, pd.DataFrame({"source_file": add, "list_date": [""] * len(add)})], ignore_index=True)
        known.to_csv(manual_path, index=False, encoding="utf-8-sig")
    print(f"   -> Open {manual_path}, type each file's date as YYYY-MM-DD (e.g. 2019-03-31),")
    print("      save as CSV UTF-8, and run this step again. Find the date by opening the PDF")
    print("      (or its Markdown file) and looking for 'upto ...' / 'as on ...'.\n")
aliases = pd.read_csv(config.INPUT / "company_aliases.csv", encoding="utf-8-sig").fillna("")
rules = [(re.compile(a.pattern, re.I), a) for a in aliases.itertuples()]


def match(name):
    name = str(name)
    for rx, a in rules:
        if rx.search(name):
            return a.listed_company, a.nse_symbol, a.listed
    return "", "", ""


cases[["listed_company", "nse_symbol", "listed"]] = cases["company_raw"].apply(lambda n: pd.Series(match(n)))
cases["under_litigation"] = cases["status"].fillna("").str.contains("litig", case=False)
cases.to_csv(config.OUTPUT / "cases_with_companies.csv", index=False, encoding="utf-8-sig")

# ---------- company panel: one row per company per NPPA list date ----------
m = cases[(cases["listed_company"] != "") & (cases["list_date"] != "")].copy()
m["outstanding_litigation_crore"] = m["outstanding_crore"].where(m["under_litigation"], 0)
panel = (m.groupby(["listed_company", "nse_symbol", "listed", "list_date"], dropna=False)
          .agg(cases=("outstanding_crore", "size"),
               principal_crore=("principal_crore", "sum"),
               interest_crore=("interest_crore", "sum"),
               total_demand_crore=("total_crore", "sum"),
               recovered_crore=("recovered_crore", "sum"),
               outstanding_crore=("outstanding_crore", "sum"),
               outstanding_litigation_crore=("outstanding_litigation_crore", "sum"),
               rows_needing_review=("needs_review", lambda s: int((s.fillna("") != "").sum())))
          .reset_index().round(2))
panel["share_under_litigation_pct"] = (100 * panel["outstanding_litigation_crore"] /
                                       panel["outstanding_crore"].where(panel["outstanding_crore"] != 0)).round(1)
panel = panel.sort_values(["list_date", "outstanding_crore"], ascending=[True, False])
panel.to_csv(config.OUTPUT / "company_panel.csv", index=False, encoding="utf-8-sig")

# ---------- names not matched: suggest the closest known company ----------
known = sorted(set(aliases["listed_company"]))
un = (cases[cases["listed_company"] == ""].groupby("company_raw")
      .agg(outstanding_crore=("outstanding_crore", "sum"), lines=("outstanding_crore", "size"),
           list_dates=("list_date", lambda s: ", ".join(sorted(set(map(str, s))))))
      .reset_index().sort_values("outstanding_crore", ascending=False).round(2))


def suggest(name):
    best = process.extractOne(str(name), known, scorer=fuzz.token_set_ratio)
    return pd.Series([best[0], round(best[1])] if best else ["", 0])


un[["suggested_company", "similarity_0_to_100"]] = un["company_raw"].apply(suggest)
un.to_csv(config.OUTPUT / "unmatched_names_to_check.csv", index=False, encoding="utf-8-sig")

latest = panel[panel["list_date"] == panel["list_date"].max()] if len(panel) else panel
save_excel({"Panel (all dates)": panel, "Latest list": latest,
            "Unmatched names": un.head(500)}, config.OUTPUT / "company_panel.xlsx")

share = 100 * m["outstanding_crore"].sum() / max(cases["outstanding_crore"].sum(), 1e-9)
print(f"Cases matched to a company: {len(m)} of {len(cases)}  ({share:.1f}% of all outstanding money)")
print("Top 15 listed companies in the latest list (Rs crore):")
print(latest[latest["listed"] == "yes"].head(15)[["listed_company", "outstanding_crore", "cases",
                                                   "share_under_litigation_pct"]].to_string(index=False))
print("\nNEXT: open unmatched_names_to_check.csv. If a big name belongs to a listed company,")
print("      add a pattern to company_aliases.csv and run this step again.")
