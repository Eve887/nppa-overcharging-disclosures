"""
STEP 10 – Put everything together into one report you can read, edit and share.

Input : the outputs of steps 03, 06, 07, 08, 09 (whatever exists)
Output: data/output/FINAL_REPORT.md   (Markdown: open in VS Code / Obsidian / Typora, or paste into Word / Google Docs)
Run:  python 10_build_report.py

The numbers and tables are filled in automatically. The parts in [square brackets] are for
YOU to write in your own words (findings, interpretation) – that is what makes it your project.
"""
import pandas as pd

import config
from utils import stamp

O = config.OUTPUT


def read(name):
    p = O / name
    return pd.read_csv(p, encoding="utf-8-sig") if p.exists() else None


def table(df, cols, n=15):
    if df is None or not len(df):
        return "_(not available yet – run the earlier steps)_\n"
    d = df[[c for c in cols if c in df.columns]].head(n).fillna("")
    head = "| " + " | ".join(d.columns) + " |\n|" + "---|" * len(d.columns) + "\n"
    return head + "".join("| " + " | ".join(str(v) for v in r) + " |\n" for r in d.itertuples(index=False))


def chart(name, caption):
    p = config.CHARTS / name
    return f"\n![{caption}](charts/{name})\n\n*{caption}*\n" if p.exists() else ""


panel, rec, ev, sec = read("company_panel.csv"), read("reconciliation.csv"), read("event_study_results.csv"), read("sec_nppa_mentions.csv")
summ = read("overcharging_list_summary.csv")

latest = panel[panel["list_date"] == panel["list_date"].max()] if panel is not None else None
n_checked = big = 0
if rec is not None:
    chk = rec[rec["Verdict"] != "NOT CHECKED YET"]
    n_checked = len(chk)
    big = chk["Verdict"].astype(str).str.startswith(("BIG UNEXPLAINED", "BIG EXPOSURE")).sum()

md = f"""# NPPA overcharging demands vs company disclosures
### Does what India's drug-price regulator says companies owe match what the companies tell investors?

_Report generated {stamp()}. Numbers come from the project's scripts; text in [brackets] is for you to write._

---

## 1. Summary (write this last)
- **Question:** NPPA publishes, company by company, the money it says drug makers owe for overcharging above
  government ceiling prices. Do listed companies disclose the same exposure in their annual reports?
- **Data:** {len(summ) if summ is not None else '?'} NPPA status lists (2019–2026), {n_checked} company annual reports checked by reconciliation.
- **Main finding:** {big} of {n_checked} companies checked show a big unexplained gap or give no figure. [Explain in 2–3 sentences.]
- **Why it matters for investors:** [Materiality: how large is the exposure vs profit / net worth?]
- **International angle:** [What foreign parents say in US SEC filings vs the Indian subsidiary.]

## 2. Background (regulatory layer)
[Explain in your words: NPPA, DPCO 1979 / 1987 / 1995 / 2013, ceiling prices, how overcharging demands with
interest are raised, why most money is stuck in court (~70% under litigation per the Parliamentary
Standing Committee report of Aug 2026), and the committee's recommendation for a legal cell.]

## 3. NPPA's side: what the regulator says
{chart('01_nppa_total_outstanding_trend.png', 'Total outstanding across all NPPA lists')}
{chart('02_top10_outstanding.png', 'Top 10 listed companies, latest NPPA list')}
**Latest list – top listed companies (Rs crore)**

{table(latest[latest['listed'] == 'yes'] if latest is not None else None, ['listed_company', 'nse_symbol', 'outstanding_crore', 'outstanding_litigation_crore', 'share_under_litigation_pct', 'cases'])}
{chart('03_company_trends.png', 'Company outstanding over time')}
[What changed between 2019 and 2026? Which companies grew / fell? New cases vs old ones?]

## 4. The companies' side and the reconciliation (finance layer)
{chart('04_nppa_vs_company.png', 'NPPA figure vs company figure')}
{table(rec, ['NSE symbol', 'NPPA outstanding (Rs cr)', 'Company figure (Rs cr)', 'Gap NPPA minus company (Rs cr)', 'Provision booked (Rs cr)', 'Disclosure score (0-5)', 'Verdict'])}
{chart('05_disclosure_scores.png', 'Disclosure quality score')}
{chart('06_materiality_vs_profit.png', 'Exposure vs net profit')}
**Company by company** [one short paragraph each: what the company says, the gap, its stated reason, how it is
accounted for (provision vs contingent liability under Ind AS 37), auditor key audit matter or not].

## 5. Market reaction (event study)
{table(ev[ev['benchmark'] == 'Nifty 50'] if ev is not None and 'benchmark' in ev else ev, ['nse_symbol', 'event_date', 'event_type', 'amount_crore', 'CAR[-1,1]_%', 't[-1,1]', 'p[-1,1]', 'status'])}
[Interpretation. With few events, describe them as case studies.]

## 6. International comparison
{table(sec, ['company', 'form', 'file_date', 'amounts_seen', 'url'], 20)}
[Compare: parent's US filing amount vs Indian subsidiary's figure vs NPPA's figure. Also compare how other
regulators publish such data, e.g. whether any regulator publishes company-wise unpaid amounts like NPPA.]

## 7. Method (data science layer)
1. Crawled nppa.gov.in (≈2,500 files), de-duplicated by SHA-256, converted PDFs to text/Markdown with OCR for scans.
2. Parsed every "Status of Overcharging Cases" PDF into one table (split merged cells, lakh → crore).
3. Matched ~1,000 raw company names to listed companies with pattern rules + fuzzy-match suggestions.
4. Searched annual reports for NPPA/DPCO passages; filled the reconciliation by reading the notes.
5. Computed gaps, disclosure scores, materiality ratios; market-model event study (Nifty 50 / Nifty Pharma).
6. Searched SEC EDGAR full text for parent-company disclosures.

## 8. Limitations
- PDF table parsing is imperfect: rows flagged for review were checked by hand [say how many].
- "Not found" in an annual report search ≠ not disclosed; every such case was read by hand [confirm].
- NPPA lists and annual reports may use different dates, interest calculations and duplicate notices.
- Few market events → event study is illustrative, not statistical proof.
- This is research, not legal or investment advice.

## 9. Sources
- NPPA – Status of Overcharging Cases (lists on nppa.gov.in)
- Company annual reports (see data/input/annual_reports.csv)
- PRS Legislative Research – summary of the Standing Committee report on NPPA (Aug 2026)
- SEC EDGAR full-text search
"""
(O / "FINAL_REPORT.md").write_text(md, encoding="utf-8")
print(f"Saved {O / 'FINAL_REPORT.md'}")
