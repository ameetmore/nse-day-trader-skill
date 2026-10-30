#!/usr/bin/env python3
"""Earnings reader for nse-analyst. Standard library only.

Pulls a listed Indian company's reported quarterly numbers and lays out what
changed: revenue, operating and net margins, net profit, diluted EPS, and
growth against the previous quarter and the same quarter a year earlier.
It also finds the company's latest results filing on NSE.

    python3 facts.py RELIANCE
    python3 facts.py TCS INFY --quarters 8
    python3 facts.py HDFCBANK --json
    python3 facts.py RELIANCE TCS INFY --metrics trader/metrics.json

Sources:
  - Quarterly figures: Yahoo Finance's fundamentals time series (free,
    unofficial, can be late or incomplete for smaller companies):
    https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/<SYMBOL>.NS
    ?type=quarterlyTotalRevenue,quarterlyOperatingIncome,quarterlyNetIncome,...
  - The filing: NSE's Financial Results RSS feed (the newest item that names
    the symbol or the company), the document the numbers come from:
    https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml

Indian companies report quarterly under Ind AS, usually standalone AND
consolidated; Yahoo's series are normally the consolidated ones. Banks and
NBFCs report revenue and operating profit differently: their margins can be
blank or not comparable with an industrial company's. When a number matters,
read it in the NSE filing. Amounts print in ₹ crore (1 crore = 10 million).

--metrics FILE merges one row per symbol into a JSON file (TTM revenue, net
profit and EPS, margins, growth). Offline: --offline DIR reads
timeseries-<SYMBOL>.json and nse-results.xml from DIR.

Numbers only: this tool never says whether a stock is a buy.
"""

import argparse
import datetime as _dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

TS_URL = ("https://%s.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/%s"
          "?symbol=%s&type=%s&period1=%d&period2=%d&merge=false&padTimeSeries=true")
RESULTS_PATH = "/content/RSS/Financial_Results.xml"
NSE_HOSTS = ("https://nsearchives.nseindia.com", "https://archives.nseindia.com")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
CRORE = 1e7
SERIES = {  # our key -> Yahoo's quarterly type
    "revenue": "quarterlyTotalRevenue",
    "operating_income": "quarterlyOperatingIncome",
    "net_income": "quarterlyNetIncome",
    "net_income_common": "quarterlyNetIncomeCommonStockholders",
    "eps_diluted": "quarterlyDilutedEPS",
    "eps_basic": "quarterlyBasicEPS",
}


class FactsError(Exception):
    pass


def yahoo_symbol(sym):
    s = str(sym).strip().upper()
    if s.startswith("^") or s.endswith((".NS", ".BO")):
        return s
    return s + ".NS"


def nse_symbol(sym):
    s = str(sym).strip().upper()
    return s[:-3] if s.endswith((".NS", ".BO")) else s


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.3):
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def get(self, url, name, referer=None):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise FactsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        headers = {"User-Agent": UA, "Accept": "*/*"}
        if referer:
            headers["Referer"] = referer
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise FactsError("HTTP %s for %s" % (exc.code, url.split("?")[0]))
        except urllib.error.URLError as exc:
            raise FactsError("could not reach %s: %s" % (url.split("/")[2], exc.reason))


def fetch_series(fetcher, sym, now=None):
    now = now or _dt.datetime.now(_dt.timezone.utc)
    p2 = int(now.timestamp())
    p1 = p2 - 4 * 366 * 86400
    ysym = urllib.parse.quote(yahoo_symbol(sym), safe=".^-")
    types = ",".join(SERIES.values())
    last = None
    for host in ("query2", "query1"):
        try:
            return fetcher.get(TS_URL % (host, ysym, ysym, types, p1, p2), "timeseries-%s.json" % nse_symbol(sym))
        except FactsError as exc:
            last = exc
            if fetcher.offline:
                break
    raise last


# ---------------------------------------------------------------- parsing

def parse_series(data, sym):
    """Yahoo timeseries JSON -> {quarter end date: {key: value}} and the currency."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        results = doc["timeseries"]["result"]
    except (ValueError, KeyError, TypeError):
        raise FactsError("Yahoo's figures for %s are not in the shape this tool knows" % sym)
    back = {v: k for k, v in SERIES.items()}
    quarters, currency = {}, None
    for r in results or []:
        types = (r.get("meta") or {}).get("type") or []
        for t in types:
            key = back.get(t)
            if not key:
                continue
            for pt in r.get(t) or []:
                if not pt:
                    continue
                d = pt.get("asOfDate")
                raw = (pt.get("reportedValue") or {}).get("raw")
                if not d or raw is None:
                    continue
                quarters.setdefault(d, {})[key] = float(raw)
                currency = currency or pt.get("currencyCode")
    if not quarters:
        raise FactsError("Yahoo has no quarterly figures for %s (a small or new listing, or a wrong symbol)"
                         % sym)
    return quarters, currency or "INR"


def build_quarters(quarters, n):
    """Newest first: one row per quarter with margins and growth."""
    dates = sorted(quarters)
    rows = []
    for i, d in enumerate(dates):
        q = dict(quarters[d])
        if q.get("net_income") is None and q.get("net_income_common") is not None:
            q["net_income"] = q["net_income_common"]
        if q.get("eps_diluted") is None and q.get("eps_basic") is not None:
            q["eps_diluted"] = q["eps_basic"]
        rev = q.get("revenue")
        row = {"quarter_end": d, "label": quarter_label(d), "revenue": rev,
               "operating_income": q.get("operating_income"), "net_income": q.get("net_income"),
               "eps_diluted": q.get("eps_diluted")}
        row["operating_margin"] = _pct(q.get("operating_income"), rev)
        row["net_margin"] = _pct(q.get("net_income"), rev)
        prev = quarters[dates[i - 1]] if i >= 1 else None
        yago = year_ago(quarters, d)
        for k in ("revenue", "net_income", "eps_diluted"):
            row["%s_qoq" % k] = _growth(q.get(k), (prev or {}).get(k))
            row["%s_yoy" % k] = _growth(q.get(k), (yago or {}).get(k))
        rows.append(row)
    return rows[::-1][:n]


def year_ago(quarters, d):
    day = _dt.date.fromisoformat(d)
    for k in sorted(quarters):
        kd = _dt.date.fromisoformat(k)
        if 350 <= (day - kd).days <= 380:
            return quarters[k]
    return None


def quarter_label(d):
    """2026-09-30 -> 'Q2 FY27 (Sep 2026)': India's fiscal year runs April to March."""
    day = _dt.date.fromisoformat(d)
    fy = day.year + 1 if day.month >= 4 else day.year
    q = {6: 1, 7: 1, 5: 1, 9: 2, 8: 2, 10: 2, 12: 3, 11: 3, 1: 3, 3: 4, 2: 4, 4: 4}[day.month]
    return "Q%d FY%02d (%s)" % (q, fy % 100, day.strftime("%b %Y"))


def _pct(a, b):
    if a is None or not b:
        return None
    return round(100.0 * a / b, 1)


def _growth(a, b):
    """Percent change; None when either side is missing or the base is zero or negative
    (growth from a loss is not a meaningful percentage)."""
    if a is None or b is None or b <= 0:
        return None
    return round(100.0 * (a / b - 1), 1)


def ttm(rows, key):
    vals = [r.get(key) for r in rows[:4]]
    if len(vals) < 4 or any(v is None for v in vals):
        return None
    return sum(vals)


def parse_results_rss(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FactsError("NSE results feed is not valid XML: %s" % exc)
    out = []
    for it in root.iter("item"):
        get = lambda n: " ".join(((it.find(n).text if it.find(n) is not None else "") or "").split())
        out.append({"title": get("title"), "description": get("description"), "link": get("link"),
                    "date": get("pubDate")})
    return out


def latest_filing(items, sym, name=None):
    base = nse_symbol(sym)
    pats = [re.compile(r"/%s_" % re.escape(base)), re.compile(r"\b%s\b" % re.escape(base))]
    if name:
        pats.append(re.compile(re.escape(" ".join(name.split())).replace(r"\ ", r"[\s-]+"), re.I))
    for it in items:   # the feed is newest first
        hay = "%s %s %s" % (it["title"], it["description"], it["link"])
        if any(p.search(hay) for p in pats):
            return it
    return None


# ---------------------------------------------------------------- output

def crore(v):
    if v is None:
        return "-"
    c = v / CRORE
    return "{:,.0f}".format(c) if abs(c) >= 100 else "{:,.1f}".format(c)


def pct(v):
    return "-" if v is None else "%+.1f%%" % v


def summary_line(sym, rows):
    if not rows:
        return "%s: no quarters." % sym
    cur = rows[0]
    parts = ["%s %s: revenue ₹%s cr" % (sym, cur["label"], crore(cur["revenue"]))]
    if cur.get("revenue_yoy") is not None:
        parts[-1] += " (%s y/y)" % pct(cur["revenue_yoy"])
    if cur.get("net_income") is not None:
        p = "net profit ₹%s cr" % crore(cur["net_income"])
        if cur.get("net_income_yoy") is not None:
            p += " (%s y/y)" % pct(cur["net_income_yoy"])
        parts.append(p)
    if cur.get("net_margin") is not None:
        parts.append("net margin %.1f%%" % cur["net_margin"])
    if cur.get("eps_diluted") is not None:
        parts.append("diluted EPS ₹%.2f" % cur["eps_diluted"])
    return ", ".join(parts) + "."


def table(sym, rows, currency):
    out = ["%s quarterly, ₹ crore except EPS (%s; source: Yahoo Finance fundamentals, check the NSE filing)."
           % (sym, currency)]
    out.append("%-22s %10s %8s %8s %10s %8s %7s %9s" % ("quarter", "revenue", "q/q", "y/y", "net profit",
                                                       "y/y", "margin", "EPS"))
    for r in rows:
        out.append("%-22s %10s %8s %8s %10s %8s %7s %9s" % (
            r["label"], crore(r["revenue"]), pct(r["revenue_qoq"]), pct(r["revenue_yoy"]),
            crore(r["net_income"]), pct(r["net_income_yoy"]),
            "-" if r["net_margin"] is None else "%.1f%%" % r["net_margin"],
            "-" if r["eps_diluted"] is None else "%.2f" % r["eps_diluted"]))
    return out


def merge_metrics(path, rows_by_sym):
    doc = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    for sym, rows in rows_by_sym.items():
        cur = rows[0] if rows else {}
        doc[sym] = {"quarter": cur.get("label"), "quarter_end": cur.get("quarter_end"),
                    "ttm_revenue_cr": None if ttm(rows, "revenue") is None else round(ttm(rows, "revenue") / CRORE, 1),
                    "ttm_net_profit_cr": None if ttm(rows, "net_income") is None else round(ttm(rows, "net_income") / CRORE, 1),
                    "ttm_eps": None if ttm(rows, "eps_diluted") is None else round(ttm(rows, "eps_diluted"), 2),
                    "net_margin": cur.get("net_margin"), "operating_margin": cur.get("operating_margin"),
                    "revenue_yoy": cur.get("revenue_yoy"), "net_profit_yoy": cur.get("net_income_yoy")}
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def load_names(path="trader/universe.txt"):
    out = {}
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                if "|" in ln:
                    s, n = ln.rstrip("\n").split("|", 1)
                    out[s.strip().upper()] = n.strip()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tickers", nargs="*", help="NSE symbols, e.g. RELIANCE TCS")
    ap.add_argument("--quarters", type=int, default=6)
    ap.add_argument("--no-filings", action="store_true", help="skip the NSE results-filing lookup")
    ap.add_argument("--metrics", metavar="FILE", help="merge a row per symbol into this JSON")
    ap.add_argument("--universe", default="trader/universe.txt", help="SYMBOL|Name lines, for company names")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.tickers:
        ap.error("give at least one NSE symbol, e.g. facts.py RELIANCE")
    fetcher = Fetcher(offline=a.offline)
    names = load_names(a.universe)
    filings, notes, out, rows_by = [], [], {}, {}
    if not a.no_filings:
        for host in NSE_HOSTS:
            try:
                filings = parse_results_rss(fetcher.get(host + RESULTS_PATH, "nse-results.xml",
                                                        referer="https://www.nseindia.com/"))
                break
            except FactsError as exc:
                notes.append("NSE results feed: %s" % exc)
                if a.offline:
                    break
        if filings:
            notes = [n for n in notes if not n.startswith("NSE results feed")]
    rc = 0
    for t in a.tickers:
        sym = nse_symbol(t)
        try:
            quarters, currency = parse_series(fetch_series(fetcher, sym), sym)
        except FactsError as exc:
            print("facts.py: %s: %s" % (sym, exc), file=sys.stderr)
            rc = 1
            continue
        rows = build_quarters(quarters, a.quarters)
        rows_by[sym] = rows
        filing = latest_filing(filings, sym, names.get(sym)) if filings else None
        out[sym] = {"symbol": sym, "currency": currency, "quarters": rows, "filing": filing,
                    "ttm": {"revenue": ttm(rows, "revenue"), "net_income": ttm(rows, "net_income"),
                            "eps_diluted": ttm(rows, "eps_diluted")}}
        if not a.json:
            print(summary_line(sym, rows))
            for line in table(sym, rows, currency):
                print(line)
            if filing:
                print("Latest NSE results filing: %s (%s) %s" % (filing["description"] or filing["title"],
                                                                 filing["date"], filing["link"]))
            elif not a.no_filings and filings:
                print("No results filing for %s in NSE's current feed (it holds the most recent filings only)."
                      % sym)
            print("")
    if a.metrics and rows_by:
        merge_metrics(a.metrics, rows_by)
    if a.json:
        print(json.dumps({"companies": out, "notes": notes}, indent=2, ensure_ascii=False))
    else:
        for n in notes:
            print("note: %s" % n)
        print("Numbers only, not advice. Yahoo's figures can lag or differ from the filing: the NSE filing "
              "is the source.")
    return rc


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
