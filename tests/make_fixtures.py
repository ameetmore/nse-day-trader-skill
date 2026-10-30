#!/usr/bin/env python3
"""Build the offline test fixtures. SYNTHETIC data, seeded, in the exact shape of
Yahoo's v8 chart and v7 spark answers for NSE symbols (.NS, Asia/Kolkata,
9:15 to 15:30 IST). The prices are made up: they test the arithmetic and the
clock, not any real stock. Run from the repo root:

    python3 tests/make_fixtures.py

The plan day is Thursday 2026-10-29. DEMO breaks out of its 15-minute opening
range on the 9:40 bar (closes 9:45); FLAT never does; the other names give the
scanner something to sort.
"""

import datetime
import gzip
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures")
IST = datetime.timedelta(hours=5, minutes=30)
PLAN_DAY = datetime.date(2026, 10, 29)
HOLIDAYS = {"2026-09-14", "2026-10-02", "2026-10-20"}
BARS = 75


def trading_days(end, n):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5 and d.isoformat() not in HOLIDAYS:
            out.append(d)
        d -= datetime.timedelta(days=1)
    return out[::-1]


def ts(day, slot):
    local = datetime.datetime.combine(day, datetime.time(9, 15)) + datetime.timedelta(minutes=5 * slot)
    return int((local - IST - datetime.datetime(1970, 1, 1)).total_seconds())


def session(rng, day, start, drift=0.0, vol=0.0025, shape=None):
    """75 five-minute bars. `shape` overrides closes for given slots."""
    bars, prev = [], start
    for i in range(BARS):
        o = prev * (1 + rng.gauss(0, vol / 4))
        c = o * (1 + rng.gauss(drift, vol))
        if shape and i in shape:
            c = shape[i]
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        v = int(rng.uniform(20000, 90000) * (3 if i < 3 else 1))
        bars.append((ts(day, i), round(o, 2), round(h, 2), round(lo, 2), round(c, 2), v))
        prev = c
    return bars


def meta(sym, bars, prev_close, rng_label, gran="5m", name=None):
    last = bars[-1]
    return {"currency": "INR", "symbol": sym, "exchangeName": "NSI", "fullExchangeName": "NSE",
            "instrumentType": "EQUITY", "gmtoffset": 19800, "timezone": "IST",
            "exchangeTimezoneName": "Asia/Kolkata", "regularMarketPrice": last[4],
            "regularMarketTime": last[0] + 300, "regularMarketVolume": sum(b[5] for b in bars),
            "regularMarketDayHigh": max(b[2] for b in bars), "regularMarketDayLow": min(b[3] for b in bars),
            "previousClose": prev_close, "chartPreviousClose": prev_close, "longName": name or sym,
            "shortName": name or sym, "priceHint": 2, "dataGranularity": gran, "range": rng_label}


def chart(sym, bars, prev_close, rng_label, gran="5m", name=None):
    return {"chart": {"result": [{
        "meta": meta(sym, bars, prev_close, rng_label, gran, name),
        "timestamp": [b[0] for b in bars],
        "indicators": {"quote": [{"open": [b[1] for b in bars], "high": [b[2] for b in bars],
                                  "low": [b[3] for b in bars], "close": [b[4] for b in bars],
                                  "volume": [b[5] for b in bars]}]}}], "error": None}}


def demo_day(rng, start):
    """The plan day for DEMO: a tight first 15 minutes, then a close above the range."""
    shape = {0: start * 1.002, 1: start * 0.999, 2: start * 1.001, 3: start * 1.002, 4: start * 1.003,
             5: start * 1.009}
    return session(rng, PLAN_DAY, start, drift=0.0002, vol=0.0012, shape=shape)


def write(name, doc, gz=False):
    path = os.path.join(OUT, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(doc, separators=(",", ":"))
    if gz:
        with gzip.GzipFile(path, "wb", mtime=0) as fh:
            fh.write(data.encode("utf-8"))
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data)


def main():
    rng = random.Random(2026)
    days = trading_days(PLAN_DAY, 60)
    names = {"DEMO": ("Demo Industries Ltd", 1240.0), "FLAT": ("Flatline Textiles Ltd", 410.0),
             "ALPHA": ("Alpha Power Ltd", 285.0), "BETA": ("Beta Pharma Ltd", 2150.0),
             "M&M": ("Mahindra-like Motors (synthetic)", 3100.0)}
    history = {}
    for sym, (name, p0) in names.items():
        allbars, p = [], p0
        for d in days[:-1]:
            s = session(rng, d, p, drift=rng.choice([0.0, 0.0001, -0.0001]))
            allbars += s
            p = s[-1][4]
        history[sym] = (allbars, p)

    # DEMO: 59 past sessions + the plan day, as the 60d time-machine chart
    past, last_close = history["DEMO"]
    today = demo_day(rng, last_close)
    write("charts/DEMO-60d-5m.json.gz", chart("DEMO.NS", past + today, past[-76][4], "60d",
                                               name=names["DEMO"][0]), gz=True)
    # DEMO plan day only, cut at 10:15 (bars up to the 10:10 bar)
    cut = [b for b in today if b[0] + 300 <= ts(PLAN_DAY, 12)]
    write("charts/DEMO.json", chart("DEMO.NS", cut, last_close, "1d", name=names["DEMO"][0]))
    write("charts/DEMO-full.json", chart("DEMO.NS", today, last_close, "1d", name=names["DEMO"][0]))
    # FLAT: never leaves its range
    fpast, fclose = history["FLAT"]
    flat_today = session(random.Random(7), PLAN_DAY, fclose, vol=0.0003,
                         shape={i: fclose * (1.0 + (0.0004 if i % 2 else -0.0004)) for i in range(BARS)})
    write("charts/FLAT.json", chart("FLAT.NS", flat_today, fclose, "1d", name=names["FLAT"][0]))

    # scanner: spark of today's 5m closes for every name, and 3mo of daily closes
    spark5, spark1d = [], []
    for sym, (name, _) in names.items():
        past, close = history[sym]
        day = today if sym == "DEMO" else (flat_today if sym == "FLAT" else
                                           session(rng, PLAN_DAY, close, drift=0.0003))
        ysym = sym + ".NS"
        spark5.append({"symbol": ysym, "response": [chart(ysym, day, close, "1d", name=name)["chart"]["result"][0]]})
        write("scanner/charts/%s.json" % sym, chart(ysym, day, close, "1d", name=name))
        dailies = []
        for k, d in enumerate(days[:-1]):
            b = past[k * BARS:(k + 1) * BARS]
            dailies.append((ts(d, 0), b[0][1], max(x[2] for x in b), min(x[3] for x in b), b[-1][4],
                            sum(x[5] for x in b) * 10))
        r = chart(ysym, dailies, dailies[-2][4], "3mo", gran="1d", name=name)["chart"]["result"][0]
        r["meta"]["regularMarketVolume"] = 900000
        spark1d.append({"symbol": ysym, "response": [r]})
    write("scanner/spark-5m-2026-10-29.json", {"spark": {"result": spark5, "error": None}})
    write("scanner/spark-3mo-2026-10-28.json", {"spark": {"result": spark1d, "error": None}})

    # daily bars, about a year, for nse-technicals and nse-journal: DEMO, NIFTY 50, India VIX
    drng = random.Random(99)
    ddays = trading_days(PLAN_DAY, 250)
    for sym, p0, drift, vol, name in (("DEMO.NS", 1000.0, 0.0012, 0.015, "Demo Industries Ltd"),
                                      ("^NSEI", 24000.0, 0.0004, 0.008, "NIFTY 50"),
                                      ("^INDIAVIX", 13.0, 0.0, 0.04, "India VIX")):
        rows, p = [], p0
        for d in ddays:
            o = p * (1 + drng.gauss(0, vol / 3))
            c = o * (1 + drng.gauss(drift, vol))
            if sym == "^INDIAVIX":
                c = max(9.0, min(30.0, c))
            h = max(o, c) * (1 + abs(drng.gauss(0, vol / 2)))
            lo = min(o, c) * (1 - abs(drng.gauss(0, vol / 2)))
            v = 0 if sym.startswith("^") else int(drng.uniform(4e5, 1.6e6))
            rows.append((ts(d, 0), round(o, 2), round(h, 2), round(lo, 2), round(c, 2), v))
            p = c
        if sym == "DEMO.NS":   # end the year where the intraday DEMO fixture closes, so they agree
            f = today[-1][4] / rows[-1][4]
            rows = [(r[0], round(r[1] * f, 2), round(r[2] * f, 2), round(r[3] * f, 2), round(r[4] * f, 2), r[5])
                    for r in rows]
        fname = {"DEMO.NS": "DEMO", "^NSEI": "NSEI", "^INDIAVIX": "INDIAVIX"}[sym]
        write("daily/%s-1y-1d.json" % fname, chart(sym, rows, rows[-2][4], "1y", gran="1d", name=name))

    # index options: NIFTY 50 and SENSEX intraday spot, and a Kite get_quotes answer for each chain
    import importlib.util
    spec_ = importlib.util.spec_from_file_location("fno_core", os.path.join(os.path.dirname(HERE), "nse-fno-chain",
                                                                           "fno_core.py"))
    F = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(F)
    orng = random.Random(7)
    plan_day = datetime.date(2026, 11, 2)                      # Monday; NIFTY expires Tue 3 Nov, SENSEX Thu 5 Nov
    for idx, ysym, base, expiry in (("NIFTY", "^NSEI", 25780.0, datetime.date(2026, 11, 3)),
                                    ("SENSEX", "^BSESN", 84150.0, datetime.date(2026, 11, 5))):
        # spot: a 15-minute range, then a close above it on the 9:35 bar
        bars, prev = [], base
        for i in range(BARS):
            o = prev
            c = base * (1 + (0.0004, -0.0003, 0.0002, 0.0002, 0.0005, 0.0016)[i]) if i < 6 else \
                o * (1 + orng.gauss(0.00005, 0.0006))
            h, lo = max(o, c) * (1 + abs(orng.gauss(0, 0.0002))), min(o, c) * (1 - abs(orng.gauss(0, 0.0002)))
            bars.append((ts(plan_day, i), round(o, 2), round(h, 2), round(lo, 2), round(c, 2), 0))
            prev = c
        cut = [b for b in bars if b[0] + 300 <= ts(plan_day, 6)]           # data to 09:45
        write("fno/%s.json" % ysym, chart(ysym, cut, base * 0.998, "1d", name=F.INDICES[idx]["name"]))
        # the chain at 09:45 on the plan day, priced by Black-Scholes on a volatility smile
        sp = cut[-1][4]
        now = datetime.datetime.combine(plan_day, datetime.time(9, 45)) - IST
        t = F.years_to_expiry(now, expiry)
        step = F.INDICES[idx]["step"]
        mid = F.atm(sp, step)
        quotes = {}
        for k in range(-12, 13):
            strike = mid + k * step
            for right in ("CE", "PE"):
                iv = 0.12 + 0.000004 * ((strike - sp) / step * 10) ** 2 / 10 + (0.01 if right == "PE" and strike < sp else 0)
                px = F.bs_price(right, sp, strike, t, 0.065, iv)
                px = max(0.05, round(px * 20) / 20)
                sprd = max(0.05, round(px * (0.004 if abs(k) <= 6 else 0.03) * 20) / 20)
                oi = int(1e6 * (1.6 if (right == "CE" and k == 4) or (right == "PE" and k == -4) else 1.0)
                         * max(0.15, 1 - abs(k) / 14.0) * orng.uniform(0.85, 1.15))
                sym = F.tradingsymbol(idx, expiry, strike, right)
                quotes["%s:%s" % (F.INDICES[idx]["exchange"], sym)] = {
                    "instrument_token": 1000000 + len(quotes), "last_price": px, "volume": int(oi * 3.1), "oi": oi,
                    "ohlc": {"open": px, "high": px * 1.2, "low": px * 0.8, "close": px},
                    "depth": {"buy": [{"price": round(max(0.05, px - sprd / 2) * 20) / 20, "quantity": 1300, "orders": 9}],
                              "sell": [{"price": round((px + sprd / 2) * 20) / 20, "quantity": 1200, "orders": 7}]}}
        write("fno/quotes-%s.json" % idx, {"data": quotes})

    # backtest: Kite-format 5-minute NIFTY bars, 1 Aug to 31 Oct 2025 in two chunk files (Thursday
    # expiries until the end of August, Tuesday after; Thursday 14 Aug 2025 is left out of the
    # data so the expiry must move to Wednesday), and India VIX day candles
    brng = random.Random(5)
    bdays, d = [], datetime.date(2025, 8, 1)
    while d <= datetime.date(2025, 10, 31):
        if d.weekday() < 5 and d.isoformat() not in ("2025-08-14", "2025-08-15", "2025-10-02"):
            bdays.append(d)
        d += datetime.timedelta(days=1)
    chunks, vixc, lvl, vx = {1: [], 2: []}, [], 24500.0, 12.5
    for d in bdays:
        trend = brng.choice((-1, 0, 0, 1)) * 0.00025
        for i in range(BARS):
            o = lvl
            c = o * (1 + brng.gauss(trend, 0.0011))
            h, lo = max(o, c) * (1 + abs(brng.gauss(0, 0.0004))), min(o, c) * (1 - abs(brng.gauss(0, 0.0004)))
            t = datetime.datetime.combine(d, datetime.time(9, 15)) + datetime.timedelta(minutes=5 * i)
            chunks[1 if d.month < 9 else 2].append({"date": t.strftime("%Y-%m-%dT%H:%M:%S+0530"), "open": round(o, 2),
                                                    "high": round(h, 2), "low": round(lo, 2), "close": round(c, 2),
                                                    "volume": 0})
            lvl = c
        vx = max(9.5, min(22.0, vx * (1 + brng.gauss(0, 0.05))))
        vixc.append({"date": "%sT00:00:00+0530" % d, "open": round(vx, 2), "high": round(vx * 1.03, 2),
                     "low": round(vx * 0.97, 2), "close": round(vx, 2), "volume": 0})
    write("backtest/NIFTY-2025-08-01.json", {"data": chunks[1]})
    write("backtest/NIFTY-2025-09-01.json", {"data": chunks[2]})
    write("backtest/VIX-day.json", {"data": vixc})

    # quotes for alerts
    for sym in ("DEMO", "FLAT"):
        c = json.load(open(os.path.join(OUT, "charts", "%s.json" % sym), encoding="utf-8"))
        write("quotes/yahoo-%s.json" % sym, c)
    print("wrote fixtures under", OUT)


if __name__ == "__main__":
    main()
