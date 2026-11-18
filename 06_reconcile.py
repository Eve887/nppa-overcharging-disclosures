"""
STEP 06 – The main result: NPPA's figure vs the company's figure, the gap, a disclosure
score, and how big the exposure is compared with the company's profit and net worth.

Input : data/output/company_panel.csv        (step 03)
        data/input/company_disclosures.csv   (YOU fill this from the annual reports / step 05)
        data/input/financials.csv            (YOU fill: revenue, net profit, net worth)
Output: data/output/reconciliation.xlsx  and  reconciliation.csv
Run:  python 06_reconcile.py

Words used:
  gap                 = NPPA outstanding  minus  the company's own figure (Rs crore)
  provision           = money the company has already booked as an expense for this risk
  contingent liability= a possible payment the company only mentions in the notes (no expense booked)
  disclosure score    = 0 to 5 points:
                        +1 names NPPA or DPCO, +1 gives an amount, +1 splits principal and interest,
                        +1 explains the gap (0.5 if partly), +1 auditor key audit matter on it
"""
import pandas as pd

import config
from utils import save_excel

panel = pd.read_csv(config.OUTPUT / "company_panel.csv", encoding="utf-8-sig")
disc = pd.read_csv(config.INPUT / "company_disclosures.csv", encoding="utf-8-sig", dtype=str).fillna("")
fin = pd.read_csv(config.INPUT / "financials.csv", encoding="utf-8-sig", dtype=str).fillna("")


def num(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def nppa_list_for(fy):
    """FY2025-26 -> NPPA list at 31 Mar 2026. CY2025 -> the latest list on or before 31 Dec 2025."""
    if fy.startswith("CY"):
        target = f"{fy[2:]}-12-31"
    elif fy.startswith("FY") and "-" in fy:
        target = f"{int(fy[2:6]) + 1}-03-31"
    else:
        target = config.TARGET_LIST_DATE
    dates = sorted(d for d in panel["list_date"].dropna().unique() if d <= target)
    return dates[-1] if dates else ""


yes = lambda v: str(v).strip().lower() in ("yes", "y", "true", "1")
rows = []
for d in disc.itertuples():
    list_date = nppa_list_for(d.fy)
    p = panel[(panel["nse_symbol"] == d.nse_symbol) & (panel["list_date"] == list_date)]
    nppa_out = round(p["outstanding_crore"].sum(), 2) if len(p) else None
    nppa_lit = round(p["outstanding_litigation_crore"].sum(), 2) if len(p) else None
    company = num(d.company_figure_crore)
    gap = round(nppa_out - company, 2) if (nppa_out is not None and company is not None) else None

    explains = str(d.explains_gap).strip().lower()
    score = (1 if (yes(d.names_nppa) or yes(d.names_dpco)) else 0) + (1 if company is not None else 0) \
        + (1 if yes(d.gives_principal_interest_split) else 0) \
        + (1 if explains in ("yes", "not needed") else 0.5 if explains == "partly" else 0) \
        + (1 if yes(d.auditor_kam) else 0)

    if company is None and nppa_out and nppa_out > config.BIG_GAP_CRORE and d.checked_by_hand != "yes" and not d.names_nppa:
        verdict = "NOT CHECKED YET"
    elif company is None and nppa_out and nppa_out > config.BIG_GAP_CRORE:
        verdict = "BIG EXPOSURE, NO COMPANY FIGURE"
    elif gap is not None and abs(gap) > config.BIG_GAP_CRORE and explains not in ("yes", "not needed"):
        # gap = NPPA outstanding minus company figure. Negative -> the company's own figure is
        # BIGGER than NPPA's, which is a different situation from the company understating it.
        verdict = "COMPANY SHOWS MORE THAN NPPA" if gap < 0 else "BIG UNEXPLAINED GAP"
    elif gap is not None and abs(gap) > config.BIG_GAP_CRORE:
        verdict = "Big gap, explained by company"
    elif gap is not None:
        verdict = "Matches (gap small)"
    else:
        verdict = "Missing data"
    if verdict not in ("NOT CHECKED YET", "Missing data") and not yes(d.checked_by_hand):
        verdict += " (provisional - confirm by hand)"

    f = fin[(fin["nse_symbol"] == d.nse_symbol) & (fin["fy"] == d.fy)]
    profit = num(f["net_profit_crore"].iloc[0]) if len(f) else None
    networth = num(f["net_worth_crore"].iloc[0]) if len(f) else None
    revenue = num(f["revenue_crore"].iloc[0]) if len(f) else None
    prov = num(d.provision_crore)
    rows.append({
        "NSE symbol": d.nse_symbol, "Year": d.fy, "NPPA list date used": list_date,
        "NPPA outstanding (Rs cr)": nppa_out, "NPPA: of which under litigation (Rs cr)": nppa_lit,
        "Company figure (Rs cr)": company, "What company figure covers": d.figure_covers,
        "Gap NPPA minus company (Rs cr)": gap,
        "Gap as % of NPPA figure": round(100 * gap / nppa_out, 1) if (gap is not None and nppa_out) else None,
        "Provision booked (Rs cr)": prov, "Deposits (Rs cr)": num(d.deposits_crore),
        "Provision as % of NPPA outstanding": round(100 * prov / nppa_out, 1) if (prov is not None and nppa_out) else None,
        "Names NPPA": d.names_nppa, "Names DPCO": d.names_dpco,
        "Splits principal / interest": d.gives_principal_interest_split,
        "Explains gap": d.explains_gap, "Company's stated reason": d.stated_reason,
        "Auditor key audit matter": d.auditor_kam, "Disclosure score (0-5)": score,
        "Verdict": verdict,
        "NPPA outstanding as % of net profit": round(100 * nppa_out / profit, 1) if (nppa_out and profit) else None,
        "NPPA outstanding as % of net worth": round(100 * nppa_out / networth, 1) if (nppa_out and networth) else None,
        "NPPA outstanding as % of revenue": round(100 * nppa_out / revenue, 2) if (nppa_out and revenue) else None,
        "Checked by hand": d.checked_by_hand, "Note reference": d.note_reference,
        "Source": d.source_url, "Notes": d.notes,
    })

rec = pd.DataFrame(rows).sort_values("NPPA outstanding (Rs cr)", ascending=False, na_position="last")
rec.to_csv(config.OUTPUT / "reconciliation.csv", index=False, encoding="utf-8-sig")
legend = pd.DataFrame({"Item": ["gap", "provision", "contingent liability", "disclosure score", "verdict rule",
                                "verdict direction", "NPPA list date", "units"],
                       "Meaning": ["NPPA outstanding minus the company's own figure",
                                   "money already booked as an expense for this risk",
                                   "possible payment only mentioned in the notes; no expense booked",
                                   "+1 names NPPA/DPCO, +1 gives amount, +1 splits principal/interest, +1 explains gap (0.5 partly), +1 auditor KAM",
                                   f"'BIG' means more than Rs {config.BIG_GAP_CRORE} crore (change BIG_GAP_CRORE in config.py)",
                                   "An unexplained big gap is split by direction: gap negative (company's own "
                                   "figure is BIGGER than NPPA's) -> 'COMPANY SHOWS MORE THAN NPPA'; gap "
                                   "positive (NPPA's figure is bigger, i.e. the company understates it) -> "
                                   "'BIG UNEXPLAINED GAP'",
                                   "FY2025-26 uses the 31 Mar 2026 list; CY2025 uses the latest list on/before 31 Dec 2025",
                                   "Rs crore (1 crore = 100 lakh = 10 million)"]})
save_excel({"Reconciliation": rec, "Legend": legend}, config.OUTPUT / "reconciliation.xlsx")

checked = rec[~rec["Verdict"].isin(["NOT CHECKED YET", "Missing data"])]
matches = checked["Verdict"].str.startswith(("Matches", "Big gap, explained by company")).sum()
shows_more = checked["Verdict"].str.startswith("COMPANY SHOWS MORE THAN NPPA").sum()
shows_less = checked["Verdict"].str.startswith(("BIG UNEXPLAINED GAP", "BIG EXPOSURE, NO COMPANY FIGURE")).sum()
big = shows_more + shows_less      # kept for anyone who still wants the old combined count
print(rec[["NSE symbol", "NPPA outstanding (Rs cr)", "Company figure (Rs cr)",
           "Gap NPPA minus company (Rs cr)", "Disclosure score (0-5)", "Verdict"]].to_string(index=False))
print(f"\nCompanies checked: {len(checked)}")
print(f"  (a) matches / explained:                              {matches}")
print(f"  (b) company shows more than NPPA:                     {shows_more}")
print(f"  (c) company shows less than NPPA or no figure, unexplained: {shows_less}")
print("Decision rule from the roadmap:  3+ of 10 -> strong headline;  1-2 -> 'disclosure quality ranking';"
      "  0 -> finding is 'disclosure is fine'.")
