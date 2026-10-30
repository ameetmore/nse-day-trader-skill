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

    # quotes for alerts
    for sym in ("DEMO", "FLAT"):
        c = json.load(open(os.path.join(OUT, "charts", "%s.json" % sym), encoding="utf-8"))
        write("quotes/yahoo-%s.json" % sym, c)
    print("wrote fixtures under", OUT)


if __name__ == "__main__":
    main()
