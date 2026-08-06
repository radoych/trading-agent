"""Backtest the ETF proposal engine, so the risk posture is chosen from numbers.

Strategy skeleton, rebalanced monthly:

  1. Trend gate    - an ETF is only eligible if it closes above its 200-day SMA.
                     This is the single most reliable drawdown reducer available
                     and it is what keeps the book out of sustained bear markets.
  2. Rank          - by momentum (see per-variant scoring below).
  3. Hold top N    - anything unfilled goes to SHY as a cash proxy.

Variants:
  core         - 6 uncorrelated assets, 3 slots, plain 12m+6m momentum, equal
                 weighted. THIS IS THE ONE THAT WORKS. Beats SPY on Sharpe
                 (1.00 vs 0.87) and Calmar (0.72 vs 0.44) with roughly half the
                 drawdown, and holds up in both halves of the sample.
  preservation - wide universe, 3 slots, also requires positive 12m absolute
                 momentum, inverse-volatility weighted.
  growth       - wide universe, 5 slots, trend gate only, equal weighted.

Both wide-universe variants LOSE to buy-and-hold. They are retained because the
comparison is the point: 27 correlated sector ETFs plus a volatility penalty
produced more trading, lower returns and deeper drawdowns than 6 assets and a
simpler score. Reported numbers reflect a search over roughly seven
configurations, so expect live results below the backtest.

No lookahead: signals use data up to and including the rebalance close, and
positions earn from the NEXT session onward. Costs are charged on turnover.

Usage:  python scripts/backtest_etf.py [--start 2017-01-01] [--out prefix]
"""

import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

CASH = "SHY"

# The wide universe was the first attempt. It underperforms buy-and-hold: too
# many correlated sector ETFs crowd out genuine diversifiers, and the volatility
# penalty in the score kept picking bonds during equity rallies. Kept so the
# comparison stays reproducible.
WIDE_UNIVERSE = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLV", "XLF", "XLE", "XLI",
                 "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC", "TLT", "IEF", "AGG",
                 "LQD", "GLD", "SLV", "EFA", "EEM", "USMV", "SCHD", "VYM", "DBC"]

# Six genuinely different return drivers: US large cap, US tech, developed
# international, emerging, long duration treasuries, gold. Holding the top 3 by
# momentum, gated on the 200-day trend, beat every other configuration tried and
# held up in both halves of the sample.
CORE_UNIVERSE = ["SPY", "QQQ", "EFA", "EEM", "TLT", "GLD"]

RISK_UNIVERSE = WIDE_UNIVERSE
UNIVERSE = sorted(set(WIDE_UNIVERSE + CORE_UNIVERSE + [CASH]))

TREND_DAYS = 200
MOM_LONG, MOM_SHORT, VOL_DAYS = 252, 126, 63
COST_BPS = 5.0          # one-way, charged on turnover
TRADING_DAYS = 252


def load_prices(start, end):
    k, s = os.getenv("PAPER_ALPACA_API_KEY"), os.getenv("PAPER_ALPACA_SECRET_KEY")
    if not k or not s:
        sys.exit("PAPER_ALPACA_API_KEY / PAPER_ALPACA_SECRET_KEY not set")
    dc = StockHistoricalDataClient(k, s)
    df = dc.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=UNIVERSE, timeframe=TimeFrame.Day,
        start=start, end=end, adjustment="all")).df
    closes = df["close"].unstack(level=0).sort_index()
    closes.index = pd.to_datetime(closes.index).tz_localize(None).normalize()
    return closes


def zscore(s):
    sd = s.std()
    return (s - s.mean()) / sd if sd and np.isfinite(sd) else s * 0.0


def build_weights(closes, variant, first_date):
    """Target weights on each monthly rebalance date."""
    if variant == "core":
        pool, n_slots = CORE_UNIVERSE, 3
    else:
        pool, n_slots = RISK_UNIVERSE, (3 if variant == "preservation" else 5)
    rets = closes.pct_change()
    sma = closes.rolling(TREND_DAYS).mean()
    vol = rets.rolling(VOL_DAYS).std() * np.sqrt(TRADING_DAYS)
    mom_l = closes / closes.shift(MOM_LONG) - 1
    mom_s = closes / closes.shift(MOM_SHORT) - 1

    # Last trading day of each month
    rebal = closes.index.to_series().groupby(
        [closes.index.year, closes.index.month]).last()
    rebal = [d for d in rebal if d >= first_date]

    rows = {}
    for d in rebal:
        elig = []
        for sym in pool:
            p, m = closes.at[d, sym], sma.at[d, sym]
            if not np.isfinite(p) or not np.isfinite(m) or p <= m:
                continue
            if not np.isfinite(mom_l.at[d, sym]) or not np.isfinite(vol.at[d, sym]):
                continue
            if variant == "preservation" and mom_l.at[d, sym] <= 0:
                continue
            elig.append(sym)

        w = pd.Series(0.0, index=UNIVERSE)
        if elig:
            if variant == "core":
                # Plain momentum. The volatility penalty actively hurt here: it
                # tilted into bonds during equity rallies.
                score = mom_l.loc[d, elig] + mom_s.loc[d, elig]
            else:
                score = (0.5 * zscore(mom_l.loc[d, elig])
                         + 0.5 * zscore(mom_s.loc[d, elig])
                         - 0.5 * zscore(vol.loc[d, elig]))
            picks = score.sort_values(ascending=False).head(n_slots).index.tolist()
            if variant == "preservation":
                inv = 1.0 / vol.loc[d, picks]
                w[picks] = (inv / inv.sum()) * (len(picks) / n_slots)
            else:
                w[picks] = 1.0 / n_slots
        w[CASH] = max(0.0, 1.0 - w.sum())
        rows[d] = w
    return pd.DataFrame(rows).T


def run(closes, weights):
    """Daily equity curve. Weights set at close of d apply from d+1."""
    rets = closes.pct_change().fillna(0.0)
    daily_w = weights.reindex(closes.index).shift(1).ffill().fillna(0.0)
    gross = (daily_w * rets[daily_w.columns]).sum(axis=1)

    turn = weights.diff().abs().sum(axis=1)
    if len(weights):
        turn.iloc[0] = weights.iloc[0].abs().sum()
    cost = pd.Series(0.0, index=closes.index)
    # Cost lands on the session the trade executes, i.e. the day after signal.
    for d, t in turn.items():
        nxt = closes.index[closes.index.searchsorted(d) + 1:][:1]
        if len(nxt):
            cost.at[nxt[0]] = t * COST_BPS / 1e4

    net = gross - cost
    return (1 + net).cumprod(), net, turn


def stats(curve, net, turn, weights=None):
    curve = curve.dropna()
    if curve.empty:
        return {}
    yrs = (curve.index[-1] - curve.index[0]).days / 365.25
    cagr = curve.iloc[-1] ** (1 / yrs) - 1
    dd = curve / curve.cummax() - 1
    vol = net.std() * np.sqrt(TRADING_DAYS)
    out = {
        "CAGR": cagr, "Total": curve.iloc[-1] - 1, "MaxDD": dd.min(),
        "Vol": vol, "Sharpe": (net.mean() * TRADING_DAYS) / vol if vol else 0.0,
        "Calmar": cagr / abs(dd.min()) if dd.min() else 0.0,
        "WorstYr": net.groupby(net.index.year).apply(lambda s: (1 + s).prod() - 1).min(),
        "Trades": int(round(turn.sum() * 2.5)) if turn is not None else 0,
    }
    if weights is not None:
        out["InMkt"] = 1 - weights[CASH].mean()
    return out


def drawdown_in(curve, lo, hi):
    seg = curve.loc[lo:hi]
    if seg.empty:
        return 0.0
    return (seg / seg.cummax() - 1).min()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2017-01-01")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    print("Loading ETF prices (dividend adjusted)...", flush=True)
    closes = load_prices(pd.Timestamp("2015-06-01"), pd.Timestamp("2026-07-24"))
    print(f"  {len(closes)} sessions, {closes.shape[1]} ETFs\n", flush=True)

    first = pd.Timestamp(args.start)
    results, curves = {}, {}

    for variant in ("core", "preservation", "growth"):
        w = build_weights(closes, variant, first)
        curve, net, turn = run(closes.loc[first:], w)
        curves[variant] = curve
        results[variant] = stats(curve, net, turn, w)

    # Benchmarks
    for bench, label in ((["SPY"], "SPY hold"), (None, "60/40")):
        sub = closes.loc[first:]
        if bench:
            r = sub["SPY"].pct_change().fillna(0.0)
        else:
            r = (0.6 * sub["SPY"].pct_change() + 0.4 * sub["AGG"].pct_change()).fillna(0.0)
        c = (1 + r).cumprod()
        curves[label] = c
        results[label] = stats(c, r, pd.Series([0.0]))

    print("=" * 92)
    print(f"ETF STRATEGY BACKTEST  {first.date()} -> {closes.index[-1].date()}"
          f"   (costs {COST_BPS:.0f}bps/side)")
    print("=" * 92)
    hdr = (f"  {'strategy':14}{'CAGR':>8}{'Total':>9}{'MaxDD':>8}{'Vol':>7}"
           f"{'Sharpe':>8}{'Calmar':>8}{'WorstYr':>9}{'InMkt':>7}{'Trades':>8}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for name in ("core", "preservation", "growth", "SPY hold", "60/40"):
        s = results[name]
        print(f"  {name:14}{s['CAGR']:7.1%}{s['Total']:9.1%}{s['MaxDD']:8.1%}"
              f"{s['Vol']:7.1%}{s['Sharpe']:8.2f}{s['Calmar']:8.2f}"
              f"{s['WorstYr']:9.1%}"
              f"{s.get('InMkt', 1.0):7.0%}{s.get('Trades', 0):8d}")

    print("\n  Drawdown through the two stress periods:")
    print(f"  {'strategy':14}{'2020 COVID':>13}{'2022 bear':>12}")
    for name in ("core", "preservation", "growth", "SPY hold", "60/40"):
        c = curves[name]
        print(f"  {name:14}{drawdown_in(c, '2020-02-01', '2020-05-01'):12.1%}"
              f"{drawdown_in(c, '2022-01-01', '2022-11-01'):12.1%}")

    print("\n  Calendar year returns:")
    yrs = sorted({d.year for d in curves['growth'].index})
    print(f"  {'strategy':14}" + "".join(f"{y:>8}" for y in yrs))
    for name in ("core", "preservation", "growth", "SPY hold"):
        c = curves[name]
        cells = []
        for y in yrs:
            seg = c[c.index.year == y]
            cells.append(f"{(seg.iloc[-1] / seg.iloc[0] - 1):7.1%}" if len(seg) > 1 else "      -")
        print(f"  {name:14}" + "".join(cells))

    if args.out:
        pd.DataFrame(curves).to_csv(f"{args.out}_curves.csv")
        pd.DataFrame(results).T.to_csv(f"{args.out}_stats.csv")
        print(f"\n  wrote {args.out}_curves.csv / _stats.csv")


if __name__ == "__main__":
    main()
