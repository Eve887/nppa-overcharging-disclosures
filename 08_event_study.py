"""
STEP 08 – Event study: does the share price react when a company announces an NPPA demand?

Idea in simple words:
  1. "Normal" behaviour: over ~1 year BEFORE the event (trading days -250 to -31), measure how
     the stock usually moves with the market (Nifty 50) -> a straight-line fit (the "market model").
  2. Around the event (e.g. day -1 to day +1), compare the actual return with what the
     market model expected. The difference = "abnormal return" (AR).
  3. Add ARs over the window = "cumulative abnormal return" (CAR).
  4. t-statistic: is the CAR large compared with the stock's normal day-to-day noise?
     Roughly, |t| > 2 means "unlikely to be just noise" (p-value < 0.05).

Input : data/input/events.csv   (one row per announcement: NSE symbol + date)
        Find announcements on NSE/BSE "Corporate Announcements" (search: NPPA, DPCO, overcharg).
        If the filing came AFTER 3:30 pm, use the NEXT trading day as event_date.
Output: data/output/event_study_results.xlsx/.csv  and  data/output/charts/event_<SYMBOL>_<date>.png
Run:  python 08_event_study.py
      python 08_event_study.py --prices-csv my_prices.csv   (offline: columns date,<SYMBOL>.NS,^NSEI)

Caution: with only a few events the result is a case study, not strong statistics. Say so in the report.
"""
import argparse
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import config
from utils import save_excel

EST_START, EST_END = -250, -31
WINDOWS = [(-1, 1), (0, 1), (0, 5), (-5, 10)]


def load_prices(tickers, start, end, prices_csv=None):
    if prices_csv:
        px = pd.read_csv(prices_csv, parse_dates=["date"]).set_index("date")
        return px[[t for t in tickers if t in px.columns]]
    import yfinance as yf
    data = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)["Close"]
    if isinstance(data, pd.Series):
        data = data.to_frame(tickers[0])
    return data


def p_value(t):
    return math.erfc(abs(t) / math.sqrt(2))     # two-sided, normal approximation


def study(stock, bench, event_date):
    rets = pd.concat([stock.pct_change(), bench.pct_change()], axis=1, keys=["r", "m"]).dropna()
    after = rets.index[rets.index >= pd.Timestamp(event_date)]
    if len(after) == 0:
        return None, "event date after last price"
    t0 = rets.index.get_loc(after[0])
    rel = pd.Series(range(len(rets)), index=rets.index) - t0
    est = rets[(rel >= EST_START) & (rel <= EST_END)]
    if len(est) < 120:
        return None, f"only {len(est)} days of history before the event (need 120+)"
    beta = est["r"].cov(est["m"]) / est["m"].var()
    alpha = est["r"].mean() - beta * est["m"].mean()
    resid_sd = (est["r"] - alpha - beta * est["m"]).std(ddof=2)
    ar = rets["r"] - (alpha + beta * rets["m"])
    out = {"alpha": alpha, "beta": round(beta, 3), "daily_noise_sd_%": round(100 * resid_sd, 3),
           "AR_day0_%": round(100 * ar.iloc[t0], 2)}
    for a, b in WINDOWS:
        w = ar[(rel >= a) & (rel <= b)]
        if len(w) < (b - a + 1):
            continue
        car = w.sum()
        t = car / (resid_sd * math.sqrt(len(w)))
        out[f"CAR[{a},{b}]_%"] = round(100 * car, 2)
        out[f"t[{a},{b}]"] = round(t, 2)
        out[f"p[{a},{b}]"] = round(p_value(t), 3)
    path = ar[(rel >= -10) & (rel <= 20)].cumsum() * 100
    path.index = rel[(rel >= -10) & (rel <= 20)].values
    return (out, path), "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices-csv", help="Use prices from this CSV instead of downloading")
    args = ap.parse_args()

    ev = pd.read_csv(config.INPUT / "events.csv", encoding="utf-8-sig", dtype=str).fillna("")
    results = []
    for e in ev.itertuples():
        d = pd.Timestamp(e.event_date)
        tick = f"{e.nse_symbol}.NS"
        start, end = (d - pd.Timedelta(days=430)).strftime("%Y-%m-%d"), (d + pd.Timedelta(days=45)).strftime("%Y-%m-%d")
        for bench_name, bench_tick in [("Nifty 50", config.MARKET_INDEX), ("Nifty Pharma", config.SECTOR_INDEX)]:
            try:
                px = load_prices([tick, bench_tick], start, end, args.prices_csv)
                res, status = study(px[tick].dropna(), px[bench_tick].dropna(), d)
            except Exception as ex:
                res, status = None, f"price download failed: {type(ex).__name__}: {ex}"
            row = {"nse_symbol": e.nse_symbol, "event_date": e.event_date, "event_type": e.event_type,
                   "amount_crore": e.amount_crore, "benchmark": bench_name, "status": status}
            if res:
                stats, path = res
                row.update(stats)
                fig, ax = plt.subplots(figsize=(6, 3))
                ax.axvline(0, color="#999", lw=0.8); ax.axhline(0, color="#999", lw=0.8)
                ax.plot(path.index, path.values, marker=".", color="#2F6DB5")
                ax.set_title(f"{e.nse_symbol} {e.event_date}: cumulative abnormal return vs {bench_name} (%)",
                             loc="left", fontsize=8)
                ax.set_xlabel("trading days from event")
                fig.tight_layout()
                fig.savefig(config.CHARTS / f"event_{e.nse_symbol}_{e.event_date}_{bench_name.replace(' ', '')}.png")
                plt.close(fig)
            results.append(row)
            print(f"  {e.nse_symbol:12} {e.event_date}  vs {bench_name:12}  {status}  "
                  f"CAR[-1,1]={row.get('CAR[-1,1]_%', '')}%  t={row.get('t[-1,1]', '')}")

    res = pd.DataFrame(results)
    res.to_csv(config.OUTPUT / "event_study_results.csv", index=False, encoding="utf-8-sig")
    ok = res[(res["status"] == "ok") & (res["benchmark"] == "Nifty 50")] if len(res) else res
    summary = []
    if len(ok) >= 2:
        for a, b in WINDOWS:
            col = f"CAR[{a},{b}]_%"
            if col in ok:
                x = ok[col].dropna()
                t = x.mean() / (x.std(ddof=1) / math.sqrt(len(x))) if len(x) > 1 and x.std(ddof=1) > 0 else float("nan")
                summary.append({"window": f"[{a},{b}]", "events": len(x), "average_CAR_%": round(x.mean(), 2),
                                "share_negative_%": round(100 * (x < 0).mean(), 1), "t_across_events": round(t, 2)})
    save_excel({"Per event": res, "Average across events": pd.DataFrame(summary)},
               config.OUTPUT / "event_study_results.xlsx")
    if len(ok) < 10:
        print(f"\nNOTE: only {len(ok)} usable event(s). Treat this as case studies, not proof.")


if __name__ == "__main__":
    main()
