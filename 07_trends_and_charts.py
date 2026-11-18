"""
STEP 07 – Trends over time (2019 -> 2026) and charts.

Input : data/output/company_panel.csv          (step 03)
        data/output/cases_with_companies.csv   (step 03)
        data/output/reconciliation.csv         (step 06, optional)
Output: data/output/trends.xlsx                 company outstanding at every NPPA list date + change
        data/output/charts/*.png                charts for your report / slides
Run:  python 07_trends_and_charts.py
"""
import matplotlib
matplotlib.use("Agg")              # draw charts to files (no window needed)
import matplotlib.pyplot as plt
import pandas as pd

import config
from utils import save_excel

plt.rcParams.update({"font.family": "Arial", "font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 150})
BLUE, ORANGE, GREY, RED = "#2F6DB5", "#E08A2E", "#9AA3AD", "#C0392B"

panel = pd.read_csv(config.OUTPUT / "company_panel.csv", encoding="utf-8-sig")
cases = pd.read_csv(config.OUTPUT / "cases_with_companies.csv", encoding="utf-8-sig")
listed = panel[panel["listed"] == "yes"]

# ---------- 1. Table: each company's outstanding at each list date ----------
wide = listed.pivot_table(index="listed_company", columns="list_date", values="outstanding_crore", aggfunc="sum").round(2)
dates = sorted(wide.columns)
if len(dates) >= 2:
    wide["Change first->latest (Rs cr)"] = (wide[dates[-1]] - wide[dates[0]]).round(2)
    wide["Change %"] = (100 * wide["Change first->latest (Rs cr)"] / wide[dates[0]]).round(1)
wide = wide.sort_values(dates[-1], ascending=False)
totals = (cases.groupby("list_date")
          .agg(all_cases=("outstanding_crore", "size"), outstanding_crore=("outstanding_crore", "sum"),
               recovered_crore=("recovered_crore", "sum"))
          .reset_index().round(2))
save_excel({"Company by list date": wide.reset_index(), "NPPA totals by date": totals},
           config.OUTPUT / "trends.xlsx")

# ---------- 2. Chart: NPPA total outstanding over time ----------
if len(totals) >= 2:
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.plot(pd.to_datetime(totals["list_date"]), totals["outstanding_crore"], marker="o", color=BLUE)
    ax.set_title("NPPA overcharging: total outstanding (Rs crore)", loc="left")
    ax.grid(axis="y", alpha=0.3)
    jump_date = pd.Timestamp("2021-03-31")
    if totals["list_date"].min() <= "2021-03-31" <= totals["list_date"].max():
        ax.axvline(jump_date, color=GREY, linestyle="--", linewidth=1)
        ax.annotate("From 2021 NPPA includes old DPCO 1979 cases\nand recalculated interest",
                    xy=(jump_date, ax.get_ylim()[1]), xytext=(6, -4), textcoords="offset points",
                    fontsize=7, color=GREY, va="top")
    fig.tight_layout(); fig.savefig(config.CHARTS / "01_nppa_total_outstanding_trend.png"); plt.close(fig)

# ---------- 3. Chart: top 10 listed companies, latest list ----------
latest = listed[listed["list_date"] == listed["list_date"].max()].nlargest(10, "outstanding_crore").iloc[::-1]
fig, ax = plt.subplots(figsize=(7, 4))
ax.barh(latest["listed_company"], latest["outstanding_litigation_crore"], color=BLUE, label="Under litigation")
ax.barh(latest["listed_company"], latest["outstanding_crore"] - latest["outstanding_litigation_crore"],
        left=latest["outstanding_litigation_crore"], color=GREY, label="Other status")
ax.set_title(f"Top 10 listed companies by NPPA outstanding (Rs crore)\nlist of {listed['list_date'].max()}",
             loc="left", fontsize=9)
ax.legend(frameon=False, loc="lower right")
fig.tight_layout(); fig.savefig(config.CHARTS / "02_top10_outstanding.png"); plt.close(fig)

# ---------- 4. Chart: top 10 companies over time ----------
if len(dates) >= 2:
    top = wide.head(8).index
    fig, ax = plt.subplots(figsize=(7, 4))
    for name in top:
        y = wide.loc[name, dates].astype(float)
        # A log scale cannot show zero or negative (e.g. a company with more recovered than
        # demanded nets to <=0 in some lists). Leaving those as a break in the line is more
        # honest than letting matplotlib silently plunge them to the bottom of the chart.
        y = y.where(y > 0)
        ax.plot(pd.to_datetime(dates), y.values, marker="o", label=name[:28])
    ax.set_yscale("log")
    ax.set_title("Outstanding per company over time (Rs crore, log scale)", loc="left")
    ax.legend(frameon=False, fontsize=7, ncol=2)
    fig.tight_layout(); fig.savefig(config.CHARTS / "03_company_trends.png"); plt.close(fig)

# ---------- 5. Charts from the reconciliation ----------
rec_path = config.OUTPUT / "reconciliation.csv"
if rec_path.exists():
    rec = pd.read_csv(rec_path, encoding="utf-8-sig")
    r = rec.dropna(subset=["Company figure (Rs cr)"]).iloc[::-1]
    if len(r):
        fig, ax = plt.subplots(figsize=(7, 0.5 * len(r) + 1.5))
        y = range(len(r))
        ax.barh([i + 0.2 for i in y], r["NPPA outstanding (Rs cr)"], height=0.4, color=BLUE, label="NPPA says")
        ax.barh([i - 0.2 for i in y], r["Company figure (Rs cr)"], height=0.4, color=ORANGE, label="Company says")
        ax.set_yticks(list(y)); ax.set_yticklabels(r["NSE symbol"])
        ax.set_title("NPPA figure vs company's own figure (Rs crore)", loc="left")
        ax.legend(frameon=False, loc="lower right")
        fig.text(0.01, 0.005, "Note: Lupin and Ipca give no company figure, so they are not on this chart.",
                  fontsize=7, color=GREY)
        fig.tight_layout(rect=(0, 0.03, 1, 1))
        fig.savefig(config.CHARTS / "04_nppa_vs_company.png"); plt.close(fig)
    s = rec.dropna(subset=["Disclosure score (0-5)"])
    s = s[s["Verdict"] != "NOT CHECKED YET"].sort_values("Disclosure score (0-5)")
    if len(s):
        fig, ax = plt.subplots(figsize=(7, 0.45 * len(s) + 1.5))
        colors = [RED if v < 2 else ORANGE if v < 4 else BLUE for v in s["Disclosure score (0-5)"]]
        ax.barh(s["NSE symbol"], s["Disclosure score (0-5)"], color=colors)
        ax.set_xlim(0, 5.6)
        for i, v in enumerate(s["Disclosure score (0-5)"]):
            ax.text(v + 0.1, i, f"{v:g}", va="center", fontsize=8)
        ax.set_title("Disclosure quality score (0 = silent, 5 = full)", loc="left")
        fig.tight_layout(); fig.savefig(config.CHARTS / "05_disclosure_scores.png"); plt.close(fig)
    m = rec.dropna(subset=["NPPA outstanding as % of net profit"])
    if len(m):
        fig, ax = plt.subplots(figsize=(7, 0.45 * len(m) + 1.5))
        m = m.sort_values("NPPA outstanding as % of net profit")
        ax.barh(m["NSE symbol"], m["NPPA outstanding as % of net profit"], color=BLUE)
        ax.set_title("NPPA outstanding as % of the company's yearly net profit", loc="left")
        fig.tight_layout(); fig.savefig(config.CHARTS / "06_materiality_vs_profit.png"); plt.close(fig)

print(f"Saved trends.xlsx and charts in {config.CHARTS}")
