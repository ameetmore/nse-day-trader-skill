#!/usr/bin/env python3
"""Technical snapshot for nse-technicals. Standard library only.

Computes the standard indicators on DAILY bars, as of a date, and prints them
as the one verified source of numbers for any later claim about price levels,
trends or momentum. Also reads the market's regime: NIFTY 50's trend and the
India VIX.

    python3 indicators.py snapshot RELIANCE                  # as of the last completed session
    python3 indicators.py snapshot RELIANCE --as-of 2026-10-15   # point in time: nothing after that day
    python3 indicators.py snapshot TCS INFY --json
    python3 indicators.py regime                             # NIFTY 50 trend + India VIX
    python3 indicators.py snapshot DEMO --offline tests/fixtures/daily --as-of 2026-10-29

Indicators (daily closes unless noted; the usual default windows):
  sma50, sma200      simple moving averages: medium- and long-term trend
  ema10              exponential average: short-term momentum
  macd, macd_signal, macd_hist    EMA12 - EMA26, its 9-day EMA, and the gap
  rsi14              Wilder's RSI: above 70 stretched, under 30 washed out
  boll_mid, boll_upper, boll_lower   20-day SMA +- 2 standard deviations
  atr14              Wilder's average true range (high, low, close): a day's
                     typical move, for stops and sizing
  vwma20             20-day volume-weighted average (stocks only)
  52-week high and low, and where the close sits between them
  average volume (20 days), last volume as a multiple of it

Point in time: --as-of DATE drops every bar after that date, so a snapshot
for a past day sees only what was known then (TradingAgents' look-ahead
rule). Without --as-of, a session still in progress (before 15:30 IST) is
dropped: an unfinished bar is not a close.

Data: Yahoo's free daily chart for SYMBOL.NS (range 2y), unofficial, can lag.
Offline: --offline DIR reads <SYMBOL>-1y-1d.json (NSEI and INDIAVIX for the
regime). Writes nothing unless --write (trader/research/<SYMBOL>-technicals.json).

Numbers, not advice. An indicator describes the past; it does not forecast.
"""

import argparse
import datetime
import gzip
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; nse-day-trader-skill/1.0; +https://github.com/ameetmore/nse-day-trader-skill)"
HOSTS = ("query2", "query1")
IST = datetime.timedelta(hours=5, minutes=30)
CLOSE = datetime.time(15, 30)
NIFTY, VIX = "^NSEI", "^INDIAVIX"
OFFLINE_NAMES = {NIFTY: "NSEI", VIX: "INDIAVIX"}


class TAError(Exception):
    pass


# ---------------------------------------------------------------- data

def yahoo_symbol(sym):
    s = str(sym).strip().upper()
    if s.startswith("^") or s.endswith((".NS", ".BO")):
        return s
    return s + ".NS"


def nse_symbol(sym):
    s = str(sym).strip().upper()
    return s[:-3] if s.endswith(".NS") else s


def _read(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def fetch_daily(sym, offline=None, rng="2y"):
    if offline:
        base = OFFLINE_NAMES.get(yahoo_symbol(sym), nse_symbol(sym))
        for name in (base + "-1y-1d.json", base + "-1y-1d.json.gz", base + ".json"):
            p = os.path.join(offline, name)
            if os.path.isfile(p):
                return _read(p)
        raise TAError("offline: no daily file for %s in %s" % (sym, offline))
    path = "/v8/finance/chart/%s?range=%s&interval=1d" % (urllib.parse.quote(yahoo_symbol(sym), safe=".^-"), rng)
    last = "no answer"
    for host in HOSTS:
        req = urllib.request.Request("https://%s.finance.yahoo.com%s" % (host, path),
                                     headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
            if e.code == 404:
                try:
                    return e.read().decode("utf-8", "replace")
                except Exception:
                    pass
            if e.code == 429:
                time.sleep(3)
        except (urllib.error.URLError, OSError) as e:
            last = str(getattr(e, "reason", e))
    raise TAError("Yahoo answered %s for %s" % (last, sym))


def parse_bars(text, sym):
    """Yahoo v8 daily chart -> [{"date", "o", "h", "l", "c", "v"}], oldest first, nulls dropped."""
    try:
        doc = json.loads(text)
        res = doc["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise TAError("Yahoo returned something unexpected for %s" % sym)
    if not res:
        err = (doc.get("chart") or {}).get("error") or {}
        raise TAError("no data for %s: %s" % (sym, err.get("description", "unknown symbol")))
    r = res[0]
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    out = {}
    for i, t in enumerate(r.get("timestamp") or []):
        def col(k):
            arr = q.get(k) or []
            return arr[i] if i < len(arr) else None
        c = col("close")
        if t is None or c is None:
            continue
        local = datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=int(t)) + IST
        o, h, lo = col("open"), col("high"), col("low")
        out[local.date().isoformat()] = {"date": local.date().isoformat(), "o": float(o if o is not None else c),
                                         "h": float(h if h is not None else c), "l": float(lo if lo is not None else c),
                                         "c": float(c), "v": int(col("volume") or 0)}
    return [out[d] for d in sorted(out)], r.get("meta") or {}


def cut(bars, as_of=None, now_utc=None):
    """Point in time: keep bars up to as_of; without it, drop a session still trading."""
    if as_of:
        return [b for b in bars if b["date"] <= as_of]
    now = (now_utc or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)) + IST
    if bars and bars[-1]["date"] == now.date().isoformat() and now.time() < CLOSE:
        return bars[:-1]
    return bars


# ---------------------------------------------------------------- indicators

def sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def ema_series(xs, n):
    """EMA seeded with the first n-period SMA (the usual convention)."""
    if len(xs) < n:
        return []
    k = 2.0 / (n + 1)
    out = [sum(xs[:n]) / n]
    for x in xs[n:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def rsi(xs, n=14):
    if len(xs) < n + 1:
        return None
    gains = [max(0.0, xs[i] - xs[i - 1]) for i in range(1, len(xs))]
    losses = [max(0.0, xs[i - 1] - xs[i]) for i in range(1, len(xs))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1 + ag / al)


def atr(bars, n=14):
    if len(bars) < n + 1:
        return None
    trs = [max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"])) for p, b in zip(bars, bars[1:])]
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def macd(xs):
    e12, e26 = ema_series(xs, 12), ema_series(xs, 26)
    if not e26:
        return None, None, None
    line = [a - b for a, b in zip(e12[-len(e26):], e26)]
    sig = ema_series(line, 9)
    if not sig:
        return line[-1], None, None
    return line[-1], sig[-1], line[-1] - sig[-1]


def bollinger(xs, n=20, k=2.0):
    if len(xs) < n:
        return None, None, None
    w = xs[-n:]
    m = sum(w) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
    return m, m + k * sd, m - k * sd


def vwma(bars, n=20):
    w = bars[-n:]
    vol = sum(b["v"] for b in w)
    if len(w) < n or vol <= 0:
        return None
    return sum(b["c"] * b["v"] for b in w) / vol


def compute(bars):
    if len(bars) < 30:
        raise TAError("only %d daily bars: need at least 30" % len(bars))
    closes = [b["c"] for b in bars]
    last = bars[-1]
    m, s, h = macd(closes)
    bm, bu, bl = bollinger(closes)
    yr = bars[-250:]
    hi52, lo52 = max(b["h"] for b in yr), min(b["l"] for b in yr)
    vols = [b["v"] for b in bars[-21:-1]]
    avgv = sum(vols) / len(vols) if vols and any(vols) else None
    ind = {
        "close": last["c"], "date": last["date"], "bars": len(bars),
        "change_1d_pct": 100.0 * (last["c"] / bars[-2]["c"] - 1),
        "change_20d_pct": 100.0 * (last["c"] / bars[-21]["c"] - 1) if len(bars) > 21 else None,
        "sma50": sma(closes, 50), "sma200": sma(closes, 200), "ema10": (ema_series(closes, 10) or [None])[-1],
        "macd": m, "macd_signal": s, "macd_hist": h, "rsi14": rsi(closes),
        "boll_mid": bm, "boll_upper": bu, "boll_lower": bl, "atr14": atr(bars),
        "vwma20": vwma(bars), "high_52w": hi52, "low_52w": lo52,
        "pos_52w_pct": 100.0 * (last["c"] - lo52) / (hi52 - lo52) if hi52 > lo52 else None,
        "avg_volume_20d": avgv, "volume_x": (last["v"] / avgv) if avgv else None,
        "recent_closes": [[b["date"], b["c"]] for b in bars[-10:]],
    }
    if ind["atr14"]:
        ind["atr_pct"] = 100.0 * ind["atr14"] / last["c"]
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in ind.items()}


def read_lines(ind):
    """Plain facts from the numbers: no forecasts, only what the indicator says now."""
    out = []
    c = ind["close"]
    if ind.get("sma50") and ind.get("sma200"):
        out.append("trend: close %s the 50-day (%.2f) and %s the 200-day (%.2f); 50-day %s 200-day"
                   % ("above" if c > ind["sma50"] else "below", ind["sma50"],
                      "above" if c > ind["sma200"] else "below", ind["sma200"],
                      "above" if ind["sma50"] > ind["sma200"] else "below"))
    elif ind.get("sma50"):
        out.append("trend: close %s the 50-day (%.2f); fewer than 200 bars for the 200-day"
                   % ("above" if c > ind["sma50"] else "below", ind["sma50"]))
    if ind.get("macd_hist") is not None:
        out.append("momentum: MACD %.2f %s its signal %.2f (histogram %+.2f)"
                   % (ind["macd"], "above" if ind["macd_hist"] > 0 else "below", ind["macd_signal"], ind["macd_hist"]))
    if ind.get("rsi14") is not None:
        r = ind["rsi14"]
        out.append("RSI 14 %.1f%s" % (r, " (above 70: stretched)" if r > 70 else " (under 30: washed out)" if r < 30 else ""))
    if ind.get("boll_upper"):
        where = ("above the upper band" if c > ind["boll_upper"] else "below the lower band" if c < ind["boll_lower"]
                 else "inside the bands")
        out.append("Bollinger: %s (%.2f to %.2f)" % (where, ind["boll_lower"], ind["boll_upper"]))
    if ind.get("atr14"):
        out.append("ATR 14 %.2f (%.2f%% of the close): a typical day's range" % (ind["atr14"], ind["atr_pct"]))
    if ind.get("pos_52w_pct") is not None:
        out.append("52 weeks: %.2f to %.2f; the close sits %.0f%% of the way up" % (ind["low_52w"], ind["high_52w"],
                                                                                  ind["pos_52w_pct"]))
    if ind.get("volume_x"):
        out.append("volume: %.1fx the 20-day average" % ind["volume_x"])
    return out


def regime(nifty, vix):
    """Market backdrop from NIFTY 50 and India VIX: facts plus one plain label."""
    n = compute(nifty)
    v = vix[-1]["c"] if vix else None
    v20 = sma([b["c"] for b in vix], 20) if vix and len(vix) >= 20 else None
    up = n["close"] > (n.get("sma50") or n["close"]) and (n.get("sma200") is None or n["close"] > n["sma200"])
    down = n["close"] < (n.get("sma50") or n["close"]) and (n.get("sma200") is not None and n["close"] < n["sma200"])
    label = "uptrend" if up else "downtrend" if down else "mixed"
    if v is not None:
        label += ", %s volatility" % ("high" if v >= 20 else "low" if v < 13 else "normal")
    return {"label": label, "nifty": n, "vix": round(v, 2) if v is not None else None,
            "vix_sma20": round(v20, 2) if v20 else None, "date": n["date"]}


# ---------------------------------------------------------------- CLI

def fmt(v, nd=2):
    return "-" if v is None else ("{:,.%df}" % nd).format(v)


def print_snapshot(sym, ind):
    print("%s daily, as of the %s close (%d bars, Yahoo; verified numbers for this run):" % (sym, ind["date"], ind["bars"]))
    rows = [("close", ind["close"]), ("1-day %", ind["change_1d_pct"]), ("20-day %", ind["change_20d_pct"]),
            ("SMA 50", ind["sma50"]), ("SMA 200", ind["sma200"]), ("EMA 10", ind["ema10"]),
            ("MACD", ind["macd"]), ("MACD signal", ind["macd_signal"]), ("MACD hist", ind["macd_hist"]),
            ("RSI 14", ind["rsi14"]), ("Bollinger up", ind["boll_upper"]), ("Bollinger mid", ind["boll_mid"]),
            ("Bollinger low", ind["boll_lower"]), ("ATR 14", ind["atr14"]), ("VWMA 20", ind["vwma20"]),
            ("52w high", ind["high_52w"]), ("52w low", ind["low_52w"])]
    for k, v in rows:
        print("  %-14s %12s" % (k, fmt(v)))
    for line in read_lines(ind):
        print("  - " + line)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("snapshot", help="indicators for one or more symbols")
    p.add_argument("symbols", nargs="+")
    p2 = sub.add_parser("regime", help="NIFTY 50 trend and India VIX")
    for q in (p, p2):
        q.add_argument("--as-of", help="YYYY-MM-DD: use no bar after this day (point in time)")
        q.add_argument("--offline", metavar="DIR")
        q.add_argument("--json", action="store_true")
        q.add_argument("--write", action="store_true", help="save under trader/research/")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        if a.cmd == "regime":
            nifty = cut(parse_bars(fetch_daily(NIFTY, a.offline), NIFTY)[0], a.as_of)
            try:
                vix = cut(parse_bars(fetch_daily(VIX, a.offline), VIX)[0], a.as_of)
            except TAError:
                vix = []
            r = regime(nifty, vix)
            if a.write:
                _save("trader/research/market-regime.json", r)
            if a.json:
                print(json.dumps(r, indent=2))
            else:
                print("Market regime as of %s: %s." % (r["date"], r["label"]))
                print_snapshot("NIFTY 50", r["nifty"])
                if r["vix"] is not None:
                    print("  India VIX %.2f (20-day average %s)" % (r["vix"], fmt(r["vix_sma20"])))
            return 0
        out, rc = {}, 0
        for s in a.symbols:
            sym = nse_symbol(s)
            try:
                bars, meta = parse_bars(fetch_daily(sym, a.offline), sym)
                out[sym] = compute(cut(bars, a.as_of))
                out[sym]["as_of"] = a.as_of
                out[sym]["read"] = read_lines(out[sym])
            except TAError as e:
                print("indicators.py: %s: %s" % (sym, e), file=sys.stderr)
                rc = 1
                continue
            if a.write:
                _save("trader/research/%s-technicals.json" % sym.replace("&", "_"), out[sym])
            if not a.json:
                print_snapshot(sym, out[sym])
        if a.json:
            print(json.dumps(out, indent=2))
        elif out:
            print("Numbers, not advice: indicators describe the past.")
        return rc
    except TAError as e:
        print("indicators.py: %s" % e, file=sys.stderr)
        return 1


def _save(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):      # Windows pipes default to cp1252, which has no ₹
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
