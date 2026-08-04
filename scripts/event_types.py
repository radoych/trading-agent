"""Which categories of news move stocks, and does any of it survive costs?

scripts/latency_decay.py showed undifferentiated headlines carry ~1bp of excess
movement and no directional drift. That averages thousands of routine items
together, so a real effect confined to a small category could be diluted away.
This tests categories separately, in two parts.

Part A - earnings, the category most likely to matter.
    Earnings dates come from LSE financial_reports filing dates rather than from
    the news API: 25 symbols back to 2018 costs ~10 seconds, where scraping the
    equivalent from news costs tens of thousands of paginated requests.
    A filing date is only approximately the announcement date, so within a
    window around it we take the highest-volume session as the announcement.
    Selecting on volume is safe here because the quantity being measured is the
    signed forward return, which plays no part in the selection.

Part B - all categories, via regex over headlines, on a narrower universe.

Both sign events by the event-day abnormal return, observable at the close, and
measure drift from the NEXT session onward so the signing window never overlaps
the measured window. That is what makes the result tradeable rather than
circular.

Usage:  python scripts/event_types.py [--out prefix]
"""

import argparse
import os
import re
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

UNIVERSE = ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOGL", "META", "AMD",
            "INTC", "NFLX", "CRM", "ORCL", "ADBE", "AVGO", "QCOM", "MU",
            "JPM", "BAC", "WMT", "DIS", "BA", "GE", "PFE", "XOM", "COST"]
NEWS_UNIVERSE = ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "AMD", "NFLX"]
BENCH = "SPY"

HORIZONS = [1, 3, 5, 10]        # trading days after the event session
COST_BPS = 5.0
MAX_TAGGED_SYMBOLS = 3

CATEGORIES = [
    ("earnings",  r"\b(q[1-4]|quarter|fy\d*|eps|earnings|revenue|beats?|misses?|"
                  r"tops?)\b"),
    ("guidance",  r"\b(guidance|outlook|forecast|raises?|lowers?|warns?|sees)\b"),
    ("analyst",   r"\b(price target|upgrade[sd]?|downgrade[sd]?|initiate[sd]?|"
                  r"coverage|reiterate[sd]?|analyst|rating)\b"),
    ("legal_reg", r"\b(lawsuit|sues?|sued|settle|settlement|sec|doj|probe|"
                  r"investigat|antitrust|recall|fine[sd]?|subpoena)\b"),
    ("ma",        r"\b(acquir|merger|merge[sd]?|takeover|buyout|stake|divest)\b"),
    ("product",   r"\b(launch|unveil|introduc|releases?|debuts?|partnership|"
                  r"contract)\b"),
    ("exec",      r"\b(ceo|cfo|resign|steps down|appoint|hires?)\b"),
]


def creds():
    k, s = os.getenv("PAPER_ALPACA_API_KEY"), os.getenv("PAPER_ALPACA_SECRET_KEY")
    if not k or not s:
        sys.exit("PAPER_ALPACA_API_KEY / PAPER_ALPACA_SECRET_KEY not set")
    return k, s


def classify(headline):
    h = headline.lower()
    for name, pattern in CATEGORIES:
        if re.search(pattern, h):
            return name
    return "other"


def fetch_daily(symbols, start, end):
    dc = StockHistoricalDataClient(*creds())
    df = dc.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=symbols + [BENCH], timeframe=TimeFrame.Day,
        start=start, end=end, adjustment="all")).df
    closes = df["close"].unstack(level=0).sort_index()
    vols = df["volume"].unstack(level=0).sort_index()
    closes.index = pd.to_datetime(closes.index, utc=True).normalize()
    vols.index = closes.index
    return closes, vols


def build_ar(closes):
    rets = closes.pct_change()
    betas = {}
    for sym in closes.columns:
        if sym == BENCH:
            continue
        r = rets[[sym, BENCH]].dropna()
        if len(r) < 60:
            continue
        cov = np.cov(r[sym], r[BENCH])
        betas[sym] = cov[0, 1] / cov[1, 1]
    ar = pd.DataFrame({s: rets[s] - b * rets[BENCH] for s, b in betas.items()})
    return ar, betas


def drift_table(ar, syms, sess, sign, label, records, cat="-"):
    """Signed cumulative abnormal return over each horizon, from sess onward."""
    cells = []
    for h in HORIZONS:
        vals = np.full(len(syms), np.nan)
        for sym in set(syms):
            m = np.asarray(syms) == sym
            if sym not in ar:
                continue
            cum = np.nancumsum(np.nan_to_num(ar[sym].to_numpy()))
            a, b = np.asarray(sess)[m], np.asarray(sess)[m] + h
            ok = (a >= 0) & (b < len(cum))
            v = np.full(m.sum(), np.nan)
            v[ok] = cum[b[ok]] - cum[a[ok]]
            vals[m] = v
        d = sign * vals
        n = (~np.isnan(d)).sum()
        mean_bps = np.nanmean(d) * 1e4
        se = np.nanstd(d) / np.sqrt(max(n, 1)) * 1e4
        tt = mean_bps / se if se else 0.0
        cells.append(f"{mean_bps:7.1f}(t={tt:4.1f})")
        records.append({"group": label, "category": cat, "n": int(n),
                        "horizon_d": h, "mean_bps": mean_bps, "t_stat": tt,
                        "net_bps": mean_bps - COST_BPS})
    return cells


def part_a(records):
    print("=" * 88, flush=True)
    print("PART A - EARNINGS  (25 symbols, filing dates from LSE, 2018 onward)", flush=True)
    print("=" * 88, flush=True)
    if not os.getenv("LSE_API_KEY"):
        print("  SKIPPED: LSE_API_KEY not set."); return
    try:
        from lse import LSE
    except ImportError:
        print("  SKIPPED: pip install lse-data"); return

    lse = LSE(api_key=os.getenv("LSE_API_KEY"))
    filings = []
    for sym in UNIVERSE:
        try:
            df = pd.DataFrame(lse.financial_reports(sym))
            if df.empty or "report_type" not in df:
                continue
            df = df[df.report_type == "income"]
            for d in pd.to_datetime(df["filing_date"], utc=True, errors="coerce").dropna():
                filings.append({"symbol": sym, "filing": d.normalize()})
        except Exception as e:
            print(f"    {sym}: {type(e).__name__}", flush=True)
    fil = pd.DataFrame(filings)
    print(f"  {len(fil)} income filings across {fil.symbol.nunique()} symbols", flush=True)

    start = fil.filing.min() - pd.Timedelta(days=40)
    end = pd.Timestamp(datetime.now().date(), tz="UTC") - pd.Timedelta(days=2)
    print("  fetching daily bars...", flush=True)
    closes, vols = fetch_daily(UNIVERSE, start.to_pydatetime(), end.to_pydatetime())
    ar, _ = build_ar(closes)
    sessions = closes.index
    print(f"  {len(sessions)} sessions\n", flush=True)

    # Announcement day = highest-volume session in [filing-10, filing+2].
    ev_sym, ev_sess = [], []
    for _, row in fil.iterrows():
        sym = row.symbol
        if sym not in vols:
            continue
        lo = sessions.searchsorted(row.filing - pd.Timedelta(days=10))
        hi = sessions.searchsorted(row.filing + pd.Timedelta(days=2))
        if hi <= lo or hi >= len(sessions) - max(HORIZONS) - 1:
            continue
        window = vols[sym].to_numpy()[lo:hi]
        if np.all(np.isnan(window)):
            continue
        ev_sym.append(sym)
        ev_sess.append(lo + int(np.nanargmax(window)))

    ev_sym, ev_sess = np.array(ev_sym), np.array(ev_sess)
    react = np.array([ar[s].to_numpy()[i] if s in ar else np.nan
                      for s, i in zip(ev_sym, ev_sess)])
    keep = ~np.isnan(react)
    ev_sym, ev_sess, react = ev_sym[keep], ev_sess[keep], react[keep]
    sign = np.sign(react); sign[sign == 0] = 1.0

    base = np.nanmean(np.abs(ar.to_numpy())) * 1e4
    print(f"  {len(ev_sym)} earnings events", flush=True)
    print(f"  mean |AR| on announcement day : {np.nanmean(np.abs(react)) * 1e4:6.1f} bps "
          f"({np.nanmean(np.abs(react)) * 1e4 / base:.1f}x a random session)", flush=True)
    print(f"  baseline |AR| random session  : {base:6.1f} bps\n", flush=True)

    cells = drift_table(ar, ev_sym, ev_sess, sign, "earnings_filing", records)
    hdr = "  drift after announcement:" + "".join(f"   +{h}d" for h in HORIZONS)
    print(hdr, flush=True)
    print("   " + "  ".join(cells) + "\n", flush=True)


def part_b(records):
    print("=" * 88, flush=True)
    print(f"PART B - NEWS CATEGORIES  ({len(NEWS_UNIVERSE)} symbols, 1 year)", flush=True)
    print("=" * 88, flush=True)
    end = pd.Timestamp(datetime.now().date(), tz="UTC") - pd.Timedelta(days=2)
    start = end - pd.Timedelta(days=365)

    nc = NewsClient(*creds())
    rows = []
    for i, sym in enumerate(NEWS_UNIVERSE, 1):
        try:
            r = nc.get_news(NewsRequest(symbols=sym, start=start, end=end))
            for a in r.data.get("news", []):
                if len(a.symbols) > MAX_TAGGED_SYMBOLS or sym not in a.symbols:
                    continue
                rows.append({"symbol": sym, "t": a.created_at,
                             "category": classify(a.headline)})
        except Exception as e:
            print(f"    {sym}: {type(e).__name__}: {str(e)[:50]}", flush=True)
        print(f"    {i}/{len(NEWS_UNIVERSE)} {sym}: {len(rows)} articles", flush=True)

    news = pd.DataFrame(rows)
    if news.empty:
        print("  no news"); return
    news["t"] = pd.to_datetime(news["t"], utc=True)

    closes, _ = fetch_daily(NEWS_UNIVERSE, start.to_pydatetime(), end.to_pydatetime())
    ar, _ = build_ar(closes)
    sessions = closes.index

    eff = news["t"].dt.normalize()
    eff = eff.where(news["t"].dt.hour < 20, eff + pd.Timedelta(days=1))
    news["sess"] = sessions.searchsorted(eff)
    news = news[(news.sess > 0) & (news.sess < len(sessions) - max(HORIZONS) - 1)]
    news = news.drop_duplicates(subset=["symbol", "sess", "category"])

    syms = news["symbol"].to_numpy(); sess = news["sess"].to_numpy()
    react = np.array([ar[s].to_numpy()[i] if s in ar else np.nan
                      for s, i in zip(syms, sess)])
    keep = ~np.isnan(react)
    news, syms, sess, react = news[keep], syms[keep], sess[keep], react[keep]
    base = np.nanmean(np.abs(ar.to_numpy())) * 1e4

    print(f"\n  {len(news)} events | baseline |AR| {base:.1f} bps\n", flush=True)
    hdr = (f"  {'category':10} {'n':>5} {'|AR| day0':>10} {'vs base':>8}  |"
           + "".join(f"    +{h}d drift" for h in HORIZONS))
    print(hdr, flush=True)
    print("  " + "-" * (len(hdr) - 2), flush=True)

    for cat in [c for c, _ in CATEGORIES] + ["other"]:
        m = news["category"].to_numpy() == cat
        if m.sum() < 40:
            continue
        sign = np.sign(react[m]); sign[sign == 0] = 1.0
        mag = np.nanmean(np.abs(react[m])) * 1e4
        cells = drift_table(ar, syms[m], sess[m], sign, "news", records, cat)
        print(f"  {cat:10} {m.sum():5d} {mag:9.1f}b {mag / base:7.2f}x  |"
              + "".join(f"  {c}" for c in cells), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    records = []
    part_a(records)
    part_b(records)

    res = pd.DataFrame(records)
    print("\n" + "=" * 88, flush=True)
    print("VERDICT", flush=True)
    print("=" * 88, flush=True)
    print(f"  Drift signed by the event-day move, measured from the next session.")
    print(f"  |t| > 2 = distinguishable from zero. Round-trip cost {COST_BPS:.0f} bps.\n")
    sig = res[(res.t_stat.abs() > 2) & (res.net_bps > 0)]
    if len(sig):
        print("  Significant AND cost-positive:")
        for _, r in sig.sort_values("net_bps", ascending=False).iterrows():
            print(f"    {r.group}/{r.category:10} +{r.horizon_d:2.0f}d: "
                  f"{r.mean_bps:7.1f} gross, {r.net_bps:7.1f} net, "
                  f"t={r.t_stat:5.1f}, n={r.n}")
    else:
        print("  Nothing is both significant (|t|>2) and positive after costs.")
        print("  Conditioning on event type does not rescue the premise.")

    if args.out:
        res.to_csv(args.out, index=False)
        print(f"\n  wrote {args.out}")


if __name__ == "__main__":
    main()
