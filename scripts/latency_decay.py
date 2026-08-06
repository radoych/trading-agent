"""Does a news signal survive the delay before we can act on it?

The agent polls every 10 minutes, then waits for a human to tap Approve. If the
price reaction to a headline is complete within a couple of minutes, no amount
of prompt engineering rescues the design. This measures that directly.

Method
------
For each headline at time T for symbol S:

  1. Abnormal return strips out the market:
         AR[t1,t2] = r_S[t1,t2] - beta_S * r_SPY[t1,t2]
     Without this, "the stock rose after the news" mostly measures the market
     rising, and every result is contaminated by direction of the tape.

  2. Events are signed by the *initial* reaction R0 = AR[T, T+1min], which is
     observable at the time. Averaging raw returns over good and bad news would
     cancel to zero by construction and prove nothing.

  3. Entries start at T+2min so the signing window never overlaps the measured
     window. Overlapping them makes bid-ask bounce in R0 masquerade as mean
     reversion afterwards.

  4. For each entry delay d, we measure signed AR from T+d to T+d+horizon. If
     that is reliably positive, the move continues after the delay and a slow
     system can capture part of it. If it decays to zero by d=10min, it cannot.

Usage:  python scripts/latency_decay.py [--months N] [--out results.csv]
"""

import argparse
import os
import sys
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

SYMBOLS = ["AAPL", "NVDA", "TSLA"]
BENCH = "SPY"

SIGN_WINDOW = 1     # minutes; R0 = AR[T, T+1]
ENTRY_DELAYS = [2, 5, 10, 15, 20, 30, 45, 60]   # minutes after the headline
HORIZONS = [15, 60, 240]                         # minutes held after entry

# Benzinga tags many tickers on macro stories; those are not stock-specific news.
MAX_TAGGED_SYMBOLS = 3
# Collapse re-reports of the same story for the same symbol.
DEDUPE_MINUTES = 30
COST_BPS = 5.0      # assumed round-trip cost, for the net column


def creds():
    k, s = os.getenv("PAPER_ALPACA_API_KEY"), os.getenv("PAPER_ALPACA_SECRET_KEY")
    if not k or not s:
        sys.exit("PAPER_ALPACA_API_KEY / PAPER_ALPACA_SECRET_KEY not set")
    return k, s


def fetch_news(start, end):
    nc = NewsClient(*creds())
    # Omitting `limit` lets the SDK auto-paginate; passing it caps the result.
    r = nc.get_news(NewsRequest(symbols=",".join(SYMBOLS), start=start, end=end))
    rows = []
    for a in r.data.get("news", []):
        tagged = [s for s in a.symbols if s in SYMBOLS]
        if len(a.symbols) > MAX_TAGGED_SYMBOLS or not tagged:
            continue
        for sym in tagged:
            rows.append({"symbol": sym, "t": a.created_at,
                         "headline": a.headline, "id": a.id})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["t"], utc=True)
    return df.sort_values("t").reset_index(drop=True)


def fetch_minutes(start, end):
    dc = StockHistoricalDataClient(*creds())
    out = {}
    for sym in SYMBOLS + [BENCH]:
        frames = []
        cur = start
        while cur < end:  # chunk to keep responses manageable
            nxt = min(cur + timedelta(days=60), end)
            df = dc.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=[sym], timeframe=TimeFrame.Minute,
                start=cur, end=nxt)).df
            if len(df):
                frames.append(df.loc[sym]["close"])
            cur = nxt
        if frames:
            s = pd.concat(frames)
            s = s[~s.index.duplicated()].sort_index()
            s.index = pd.to_datetime(s.index, utc=True)
            out[sym] = s
        print(f"  {sym}: {len(out.get(sym, [])):,} minute bars")
    return out


def compute_betas(start, end):
    """Beta from daily returns over the sample. One number per symbol."""
    dc = StockHistoricalDataClient(*creds())
    df = dc.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=SYMBOLS + [BENCH], timeframe=TimeFrame.Day,
        start=start, end=end)).df
    closes = df["close"].unstack(level=0)
    rets = closes.pct_change().dropna()
    betas = {}
    for sym in SYMBOLS:
        cov = np.cov(rets[sym], rets[BENCH])
        betas[sym] = cov[0, 1] / cov[1, 1]
    return betas


def price_at(series, times, tolerance="5min"):
    """First bar at or after each time (you cannot trade before it prints)."""
    idx = pd.DatetimeIndex(times)
    return series.reindex(idx, method="bfill",
                          tolerance=pd.Timedelta(tolerance)).to_numpy(dtype=float)


def abnormal(px, bench, betas, symbols, t1, t2):
    """AR[t1,t2] per event, market-adjusted."""
    ar = np.full(len(symbols), np.nan)
    for sym in SYMBOLS:
        m = symbols == sym
        if not m.any():
            continue
        p1, p2 = price_at(px[sym], t1[m]), price_at(px[sym], t2[m])
        b1, b2 = price_at(bench, t1[m]), price_at(bench, t2[m])
        ar[m] = (p2 / p1 - 1) - betas[sym] * (b2 / b1 - 1)
    return ar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    end = pd.Timestamp(datetime.now().date(), tz="UTC") - pd.Timedelta(days=2)
    start = end - pd.Timedelta(days=30 * args.months)
    print(f"Window: {start.date()} -> {end.date()}  ({args.months} months)\n")

    print("Fetching news...")
    news = fetch_news(start, end)
    if news.empty:
        sys.exit("no news returned")
    print(f"  {len(news)} stock-specific mentions "
          f"(<={MAX_TAGGED_SYMBOLS} tickers tagged)")

    # Collapse repeats of the same story per symbol
    news["gap"] = news.groupby("symbol")["t"].diff().dt.total_seconds().div(60)
    news = news[news["gap"].isna() | (news["gap"] > DEDUPE_MINUTES)]
    print(f"  {len(news)} after {DEDUPE_MINUTES}min dedupe")

    print("\nFetching minute bars...")
    px = fetch_minutes(start.to_pydatetime(), end.to_pydatetime())
    if BENCH not in px:
        sys.exit("no benchmark bars")
    bench = px[BENCH]

    print("\nEstimating betas from daily returns...")
    betas = compute_betas(start.to_pydatetime(), end.to_pydatetime())
    print("  " + "  ".join(f"{k}={v:.2f}" for k, v in betas.items()))

    t = news["t"].to_numpy()
    syms = news["symbol"].to_numpy()

    # Keep only events with bars around them (i.e. during the session)
    r0 = abnormal(px, bench, betas, syms, t, t + pd.Timedelta(minutes=SIGN_WINDOW))
    tail = abnormal(px, bench, betas, syms, t,
                    t + pd.Timedelta(minutes=max(ENTRY_DELAYS) + max(HORIZONS)))
    ok = ~np.isnan(r0) & ~np.isnan(tail)
    print(f"\n  {ok.sum()} of {len(news)} events fall inside a trading session "
          f"with full follow-through coverage")
    if ok.sum() < 50:
        sys.exit("too few usable events")

    t, syms, r0 = t[ok], syms[ok], r0[ok]
    sign = np.sign(r0)
    sign[sign == 0] = 1.0

    pre = abnormal(px, bench, betas, syms, t - pd.Timedelta(minutes=30), t)

    print("\n" + "=" * 74)
    print("IMMEDIATE REACTION (is there any information in the news at all?)")
    print("=" * 74)
    print(f"  events                        : {len(t)}")
    print(f"  mean |AR| in first {SIGN_WINDOW}min      : "
          f"{np.nanmean(np.abs(r0)) * 1e4:7.1f} bps")
    print(f"  median |AR| in first {SIGN_WINDOW}min    : "
          f"{np.nanmedian(np.abs(r0)) * 1e4:7.1f} bps")
    print(f"  mean |AR| 30min BEFORE news   : {np.nanmean(np.abs(pre)) * 1e4:7.1f} bps")
    print("  -> if the pre-news move is comparable, the headline is already priced in")

    print("\n" + "=" * 74)
    print("LATENCY DECAY - signed abnormal return by entry delay, in bps")
    print("=" * 74)
    hdr = "  delay |" + "".join(f"  +{h}min hold" for h in HORIZONS) + "   |  n"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    records = []
    for d in ENTRY_DELAYS:
        entry = t + pd.Timedelta(minutes=d)
        cells = []
        n_last = 0
        for h in HORIZONS:
            ar = abnormal(px, bench, betas, syms, entry,
                          entry + pd.Timedelta(minutes=h))
            signed = sign * ar
            good = ~np.isnan(signed)
            n_last = good.sum()
            mean_bps = np.nanmean(signed) * 1e4
            se = np.nanstd(signed) / np.sqrt(max(good.sum(), 1)) * 1e4
            tstat = mean_bps / se if se else 0.0
            cells.append(f"{mean_bps:7.1f} (t={tstat:5.1f})")
            records.append({"delay_min": d, "horizon_min": h, "n": int(n_last),
                            "mean_bps": mean_bps, "t_stat": tstat,
                            "net_of_costs_bps": mean_bps - COST_BPS})
        print(f"  {d:5d} |" + "".join(f"  {c}" for c in cells) + f"   | {n_last}")

    print("\n  Signed by the first-minute reaction; entries start at +2min so the")
    print("  signing window never overlaps the measured window.")
    print(f"  |t| > 2 means distinguishable from zero. Assumed round-trip cost "
          f"{COST_BPS:.0f} bps.")

    res = pd.DataFrame(records)
    print("\n" + "=" * 74)
    print("VERDICT")
    print("=" * 74)
    realistic = res[(res.delay_min >= 10) & (res.horizon_min >= 60)]
    best = realistic.loc[realistic.mean_bps.idxmax()] if len(realistic) else None
    if best is not None:
        print(f"  Best realistic entry (>=10min delay): {best.mean_bps:.1f} bps gross, "
              f"{best.net_of_costs_bps:.1f} bps net, t={best.t_stat:.1f}")
        if best.net_of_costs_bps <= 0 or abs(best.t_stat) < 2:
            print("  -> No usable edge survives a realistic delay.")
            print("     The news-reaction premise does not support this design.")
        else:
            print("  -> An edge survives. Worth building the full pipeline.")

    if args.out:
        res.to_csv(args.out, index=False)
        print(f"\n  wrote {args.out}")


if __name__ == "__main__":
    main()
