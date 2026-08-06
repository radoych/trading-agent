"""Data-quality verification harness.

Runs the checks that decide whether a market-data source can be trusted for
backtesting and signal generation:

  A. Feed coverage   - is Alpaca serving IEX (~2% of tape) or consolidated SIP?
  B. Split handling  - are adjusted bars actually adjusted?
  C. Survivorship    - does the archive retain delisted symbols?
  D. Cross-check     - do vendor bars agree with the broker's bars?

A-C run against Alpaca alone. D additionally needs LSE_API_KEY and the
`lse-data` package; it is skipped cleanly when either is absent.

Usage:  python scripts/verify_data.py
"""

import os
import sys
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

load_dotenv()

# Published consolidated average daily volume, used to infer which feed we are
# actually being served. Order of magnitude is all that matters here.
CONSOLIDATED_ADV = {"AAPL": 50_000_000, "NVDA": 200_000_000, "TSLA": 90_000_000}

# Known splits: (symbol, effective date, ratio)
SPLITS = [("NVDA", "2024-06-10", 10), ("AAPL", "2020-08-31", 4)]

# Symbols that traded and were then delisted. Absent => survivorship bias.
DELISTED = [("SIVB", "2023-01-10", "2023-02-10"),
            ("BBBY", "2023-01-10", "2023-02-10"),
            ("FRC",  "2023-01-10", "2023-02-10")]

SYMBOLS = ["AAPL", "NVDA", "TSLA"]


def client():
    key = os.getenv("PAPER_ALPACA_API_KEY")
    sec = os.getenv("PAPER_ALPACA_SECRET_KEY")
    if not key or not sec:
        sys.exit("PAPER_ALPACA_API_KEY / PAPER_ALPACA_SECRET_KEY not set")
    return StockHistoricalDataClient(key, sec)


def bars(c, symbols, start, end, feed=None, adjustment=None):
    kw = dict(symbol_or_symbols=symbols, timeframe=TimeFrame.Day,
              start=pd.Timestamp(start), end=pd.Timestamp(end))
    if feed:
        kw["feed"] = feed
    if adjustment:
        kw["adjustment"] = adjustment
    return c.get_stock_bars(StockBarsRequest(**kw)).df


def test_a_feed(c):
    print("\n=== A. Which feed is this account served? ===")
    end = datetime.now() - timedelta(days=2)
    start = end - timedelta(days=90)

    for feed in (DataFeed.SIP, DataFeed.IEX):
        try:
            df = bars(c, ["AAPL"], start, end, feed=feed)
            print(f"  {feed.value.upper():4} accessible: {len(df)} bars, "
                  f"median volume {df['volume'].median():,.0f}")
        except Exception as e:
            print(f"  {feed.value.upper():4} REJECTED: {type(e).__name__}: {str(e)[:110]}")

    print("\n  Default feed vs published consolidated ADV:")
    df = bars(c, SYMBOLS, start, end)
    for sym in SYMBOLS:
        try:
            med = df.loc[sym]["volume"].median()
        except KeyError:
            print(f"    {sym}: no data")
            continue
        pct = med / CONSOLIDATED_ADV[sym] * 100
        verdict = "CONSOLIDATED" if pct > 40 else ("PARTIAL" if pct > 10 else "THIN (IEX-like)")
        print(f"    {sym}: median {med:>12,.0f}  = {pct:5.1f}% of consolidated ADV  -> {verdict}")


def test_b_splits(c):
    print("\n=== B. Split adjustment correctness ===")
    for sym, date, ratio in SPLITS:
        d = pd.Timestamp(date)
        start, end = d - timedelta(days=10), d + timedelta(days=10)
        row = []
        for adj in ("raw", "all"):
            try:
                df = bars(c, [sym], start, end, adjustment=adj)
                closes = df.loc[sym]["close"] if sym in df.index.get_level_values(0) else df["close"]
                gaps = (closes / closes.shift(1)).dropna()
                worst = gaps.min()
                row.append((adj, worst, len(closes)))
            except Exception as e:
                row.append((adj, None, f"ERR {type(e).__name__}: {str(e)[:60]}"))

        print(f"\n  {sym} {ratio}:1 split on {date}")
        for adj, worst, n in row:
            if worst is None:
                print(f"    adjustment={adj:4}: {n}")
                continue
            drop = (1 - worst) * 100
            if adj == "raw":
                ok = drop > 50
                note = "split gap present (correct for raw)" if ok else "NO split gap - suspicious"
            else:
                ok = drop < 25
                note = "no split gap (correctly adjusted)" if ok else "SPLIT GAP LEAKED THROUGH"
            print(f"    adjustment={adj:4}: {n} bars, largest 1-day drop {drop:5.1f}%  -> "
                  f"{'PASS' if ok else 'FAIL'} - {note}")


def test_c_survivorship(c):
    print("\n=== C. Survivorship bias (delisted symbols retained?) ===")
    found = 0
    for sym, start, end in DELISTED:
        try:
            df = bars(c, [sym], start, end)
            n = len(df)
            if n:
                found += 1
                print(f"  {sym}: {n} bars -> RETAINED")
            else:
                print(f"  {sym}: 0 bars -> MISSING")
        except Exception as e:
            print(f"  {sym}: MISSING ({type(e).__name__}: {str(e)[:60]})")
    print(f"\n  {found}/{len(DELISTED)} delisted symbols retained.")
    if found < len(DELISTED):
        print("  => Backtests on this source are survivorship-biased. Returns will read high.")


def test_d_crosscheck(c):
    print("\n=== D. Vendor cross-check (LSE vs Alpaca) ===")
    if not os.getenv("LSE_API_KEY"):
        print("  SKIPPED: LSE_API_KEY not set.")
        return
    try:
        from lse import LSE
    except ImportError:
        print("  SKIPPED: `pip install lse-data` required.")
        return

    lse = LSE(api_key=os.getenv("LSE_API_KEY"))
    end = datetime.now() - timedelta(days=2)
    start = end - timedelta(days=60)
    alp = bars(c, SYMBOLS, start, end)

    for sym in SYMBOLS:
        try:
            # candles() returns a list of dicts, not a DataFrame
            v = pd.DataFrame(lse.candles(sym, "1d", start=start.strftime("%Y-%m-%d")))
            if v.empty:
                print(f"  {sym}: LSE returned no candles")
                continue
            v.index = pd.to_datetime(v["timestamp"]).dt.date
            a = alp.loc[sym].reset_index()
            a.index = pd.to_datetime(a["timestamp"]).dt.date
            m = v[["close", "volume"]].join(a[["close", "volume"]], rsuffix="_alp", how="inner")
            if m.empty:
                print(f"  {sym}: no overlapping dates")
                continue
            bps = ((m["close"] / m["close_alp"] - 1).abs() * 1e4).median()
            vr = (m["volume"] / m["volume_alp"]).median()
            worst = ((m["close"] / m["close_alp"] - 1).abs() * 1e4).max()
            print(f"  {sym}: {len(m)} overlapping days | close diff median {bps:6.1f} bps "
                  f"(worst {worst:7.1f}) | volume ratio {vr:5.2f}x")
        except Exception as e:
            print(f"  {sym}: ERROR {type(e).__name__}: {str(e)[:90]}")

    print("\n  volume ratio ~1.0   -> same coverage as Alpaca SIP (independent, consolidated)")
    print("  volume ratio ~0.03  -> LSE is re-serving IEX; trust the rest of the archive less")
    print("  close diff > 20 bps -> do NOT use LSE prices for signals that trigger orders")


def test_e_unique(lse_key_present=True):
    """Probe the endpoints that are the actual remaining reason to use LSE."""
    print("\n=== E. Endpoints Alpaca does not have ===")
    if not os.getenv("LSE_API_KEY"):
        print("  SKIPPED: LSE_API_KEY not set.")
        return
    try:
        from lse import LSE
    except ImportError:
        print("  SKIPPED: `pip install lse-data` required.")
        return
    lse = LSE(api_key=os.getenv("LSE_API_KEY"))

    print("\n  -- history depth (Alpaca starts 2016) --")
    for year in (2003, 2008, 2012, 2016):
        try:
            r = lse.candles("AAPL", "1d", start=f"{year}-01-02", end=f"{year}-03-01")
            print(f"    {year}: {len(r):>3} bars" + ("" if r else "   (empty)"))
        except Exception as e:
            print(f"    {year}: ERROR {type(e).__name__}: {str(e)[:70]}")

    for name, fn in (("economic_calendar", lambda: lse.economic_calendar()),
                     ("fundamentals(AAPL)", lambda: lse.fundamentals("AAPL")),
                     ("financial_reports(AAPL)", lambda: lse.financial_reports("AAPL")),
                     ("insider_trades(AAPL)", lambda: lse.insider_trades("AAPL")),
                     ("dividends(AAPL)", lambda: lse.dividends("AAPL"))):
        print(f"\n  -- {name} --")
        try:
            r = fn()
            n = len(r) if hasattr(r, "__len__") else "?"
            print(f"    returned {n} rows, type {type(r).__name__}")
            if isinstance(r, list) and r:
                keys = list(r[0].keys())
                print(f"    fields: {keys[:14]}")
                import json as _j
                print(f"    sample: {_j.dumps(r[0], default=str)[:230]}")
        except Exception as e:
            print(f"    ERROR {type(e).__name__}: {str(e)[:110]}")


def test_f_news_timestamps():
    """News is only usable for event studies if its timestamps are trustworthy."""
    print("\n=== F. Alpaca news timestamp integrity ===")
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest

    nc = NewsClient(os.getenv("PAPER_ALPACA_API_KEY"), os.getenv("PAPER_ALPACA_SECRET_KEY"))
    arts, page = [], None
    while len(arts) < 400:
        r = nc.get_news(NewsRequest(symbols=",".join(SYMBOLS),
                                    start=pd.Timestamp("2025-01-06", tz="UTC"),
                                    end=pd.Timestamp("2025-02-06", tz="UTC"),
                                    limit=50, page_token=page))
        batch = r.data.get("news", [])
        if not batch:
            break
        arts += batch
        page = r.next_page_token
        if not page:
            break

    if not arts:
        print("  no articles returned")
        return

    ts = pd.Series([a.created_at for a in arts])
    print(f"  {len(arts)} articles, {ts.min()} -> {ts.max()}")
    print(f"  timezone-aware: {ts.dt.tz is not None}")

    # created_at vs updated_at: if they differ, the row was edited after publication
    edited = sum(1 for a in arts if a.updated_at and a.created_at
                 and (a.updated_at - a.created_at).total_seconds() > 60)
    print(f"  edited >60s after creation: {edited}/{len(arts)} "
          f"({edited / len(arts) * 100:.1f}%)")

    # Publication should cluster around US market hours, not be uniform across the day
    et = ts.dt.tz_convert("America/New_York")
    rth = ((et.dt.hour >= 9) & (et.dt.hour < 16)).mean()
    pre = ((et.dt.hour >= 4) & (et.dt.hour < 9)).mean()
    print(f"  published 09:00-16:00 ET: {rth * 100:.0f}%  |  04:00-09:00 ET: {pre * 100:.0f}%"
          f"  |  overnight: {(1 - rth - pre) * 100:.0f}%")
    print("  -> a realistic feed clusters in RTH + pre-market; uniform would mean synthetic stamps")

    dupes = len(arts) - len({a.id for a in arts})
    print(f"  duplicate ids: {dupes}")


def test_g_restatement():
    """Does LSE revise financial_reports rows in place? If so they are NOT as-reported."""
    print("\n=== G. LSE financial_reports: as-reported or restated? ===")
    if not os.getenv("LSE_API_KEY"):
        print("  SKIPPED: LSE_API_KEY not set.")
        return
    try:
        from lse import LSE
    except ImportError:
        print("  SKIPPED: `pip install lse-data` required.")
        return

    rows = LSE(api_key=os.getenv("LSE_API_KEY")).financial_reports("AAPL")
    if not rows:
        print("  no rows returned")
        return

    df = pd.DataFrame(rows)
    for col in ("created_at", "updated_at", "filing_date", "accepted_date", "date"):
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    print(f"  {len(df)} rows | report_types: {sorted(df['report_type'].dropna().unique())}")
    print(f"  fiscal years: {df['fiscal_year'].min()} -> {df['fiscal_year'].max()}")

    if {"created_at", "updated_at"} <= set(df.columns):
        delta = (df["updated_at"] - df["created_at"]).dt.total_seconds()
        revised = (delta > 3600).sum()
        print(f"  rows updated >1h after creation: {revised}/{len(df)}")
        if revised:
            print("  -> WARNING: rows are revised in place. Values may be RESTATED while")
            print("     carrying an original filing_date. Do not treat as point-in-time.")
        else:
            print("  -> rows are not revised in place; consistent with as-reported values.")

    if {"filing_date", "date"} <= set(df.columns):
        lag = (df["filing_date"] - df["date"]).dt.days.dropna()
        if len(lag):
            print(f"  filing lag after period end: median {lag.median():.0f}d, "
                  f"min {lag.min():.0f}d, max {lag.max():.0f}d")
            print("  -> negative or ~0 lag would mean data available before it was filed")


if __name__ == "__main__":
    c = client()
    test_a_feed(c)
    test_b_splits(c)
    test_c_survivorship(c)
    test_d_crosscheck(c)
    test_e_unique()
    test_f_news_timestamps()
    test_g_restatement()
    print()
