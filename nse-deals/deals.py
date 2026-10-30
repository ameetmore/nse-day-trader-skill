#!/usr/bin/env python3
"""Bulk and block deals for nse-deals: who bought and sold big blocks of which
stock today. Standard library only.

    python3 deals.py                                 # today's NSE bulk + block deals, biggest first
    python3 deals.py --tickers RELIANCE ADANIENT     # only these symbols
    python3 deals.py --watch                         # only your watchlist, plan and portfolio
    python3 deals.py --client "goldman"              # one buyer or seller, by name
    python3 deals.py --min-value 25                  # deals of at least ₹25 crore
    python3 deals.py --new                           # only deals not shown before (for a schedule)
    python3 deals.py --offline tests/fixtures/deals --json

What they are. NSE publishes both files after the session:
  bulk deals   one client's trades in a stock that add up to more than 0.5% of
               its listed shares in a day (on the normal market).
  block deals  big negotiated trades done in the exchange's separate
               block-deal windows.
A name on the list is a fact about yesterday's or today's trade, not a forecast:
a fund may be selling for reasons that have nothing to do with the stock, and
the other side of every buy is a sell.

Sources (NSE archives, CSV, the latest trading day; some days NSE refuses
scripts with HTTP 403, and the tool then says so):
  https://nsearchives.nseindia.com/content/equities/bulk.csv
  https://nsearchives.nseindia.com/content/equities/block.csv
Columns, matched by name so small header changes do not break it: Date,
Symbol, Security Name, Client Name, Buy/Sell, Quantity Traded,
Trade Price / Wght. Avg. Price, Remarks.

Your symbols for --watch: the hits in trader/watchlist.json, the symbol in
trader/plan.json and the positions in trader/portfolio.json. State:
trader/state/deals.json remembers what --new has shown (60 days).
Exit code 0 when something is shown, 1 when nothing matched.
"""

import argparse
import csv
import datetime as _dt
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

HOSTS = ("https://nsearchives.nseindia.com", "https://archives.nseindia.com")
FILES = (("bulk", "/content/equities/bulk.csv", "bulk.csv"),
         ("block", "/content/equities/block.csv", "block.csv"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
CRORE = 1e7
KEEP_DAYS = 60


class DealsError(Exception):
    pass


def _norm(h):
    return re.sub(r"[^a-z]", "", (h or "").lower())


COLS = {  # our key -> words that identify the column
    "date": ("date",),
    "symbol": ("symbol",),
    "name": ("securityname", "companyname", "scripname"),
    "client": ("clientname", "client"),
    "side": ("buysell", "dealtype", "transactiontype"),
    "qty": ("quantitytraded", "quantity", "qty"),
    "price": ("tradepricewghtavgprice", "tradeprice", "price", "wghtavgprice"),
    "remarks": ("remarks",),
}


def parse_csv(text, kind):
    """NSE bulk.csv / block.csv text -> deals. Raises DealsError on an unknown shape."""
    text = text.replace("\r", "").lstrip("﻿")
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        return []
    hdr = [_norm(h) for h in rows[0]]
    idx = {}
    for key, words in COLS.items():
        for w in words:
            hit = next((i for i, h in enumerate(hdr) if h == w), None)
            if hit is None:
                hit = next((i for i, h in enumerate(hdr) if h.startswith(w)), None)
            if hit is not None:
                idx[key] = hit
                break
    missing = [k for k in ("symbol", "client", "side", "qty", "price") if k not in idx]
    if missing:
        if len(rows) == 1 or "nodata" in _norm(text[:200]) or "norecord" in _norm(text[:200]):
            return []
        raise DealsError("%s.csv has no %s column (header: %s)" % (kind, ", ".join(missing), ",".join(rows[0])[:120]))
    out = []
    for r in rows[1:]:
        cell = lambda k: r[idx[k]].strip() if k in idx and idx[k] < len(r) else ""
        try:
            qty = int(float(cell("qty").replace(",", "")))
            price = float(cell("price").replace(",", ""))
        except ValueError:
            continue
        side = cell("side").upper()
        side = "BUY" if side.startswith("B") else "SELL" if side.startswith("S") else side
        out.append({"kind": kind, "date": iso_date(cell("date")), "symbol": cell("symbol").upper(),
                    "name": cell("name"), "client": " ".join(cell("client").split()), "side": side,
                    "qty": qty, "price": price, "value": round(qty * price, 2), "remarks": cell("remarks")})
    return out


def iso_date(text):
    t = (text or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d %b %Y"):
        try:
            return _dt.datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    return t


def fetch(kind, path, fname, offline=None):
    if offline:
        p = os.path.join(offline, fname)
        if not os.path.isfile(p):
            raise DealsError("offline: no %s" % p)
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    last = "no answer"
    for host in HOSTS:
        req = urllib.request.Request(host + path, headers={"User-Agent": UA, "Accept": "*/*",
                                                           "Referer": "https://www.nseindia.com/"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
        except (urllib.error.URLError, OSError) as e:
            last = str(getattr(e, "reason", e))
    raise DealsError("NSE %s deals: %s. Open nseindia.com > Market data > Bulk & block deals in a browser, "
                     "save the CSV and pass --offline FOLDER" % (kind, last))


def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def watch_symbols(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json", plan="trader/plan.json"):
    out = set()
    for h in (load_json(watchlist) or {}).get("hits", []):
        if h.get("symbol") or h.get("ticker"):
            out.add(str(h.get("symbol") or h.get("ticker")).upper())
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.add(str(pl["symbol"]).upper())
    for p in (load_json(portfolio) or {}).get("positions", []):
        if p.get("ticker") or p.get("symbol"):
            out.add(str(p.get("ticker") or p.get("symbol")).upper())
    return {s[:-3] if s.endswith(".NS") else s for s in out}


def fingerprint(d):
    blob = "|".join(str(d[k]) for k in ("kind", "date", "symbol", "client", "side", "qty", "price"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def by_symbol(deals):
    """{symbol: {"buy": value, "sell": value, "clients": {client: net qty}}}."""
    out = {}
    for d in deals:
        s = out.setdefault(d["symbol"], {"name": d["name"], "buy": 0.0, "sell": 0.0, "clients": {}})
        s["buy" if d["side"] == "BUY" else "sell"] += d["value"]
        s["clients"][d["client"]] = s["clients"].get(d["client"], 0) + (d["qty"] if d["side"] == "BUY" else -d["qty"])
    return out


def cr(v):
    c = v / CRORE
    return "₹{:,.1f} cr".format(c) if c >= 1 else "₹{:,.2f} cr".format(c)


def render(deals, notes, mine, show):
    out = []
    if not deals:
        out.append("No bulk or block deals match.")
    else:
        dates = sorted({d["date"] for d in deals})
        out.append("NSE bulk and block deals, %s: %d deal%s in %d stock%s, biggest first."
                   % (", ".join(dates), len(deals), "" if len(deals) == 1 else "s",
                      len({d["symbol"] for d in deals}), "" if len({d["symbol"] for d in deals}) == 1 else "s"))
        for d in deals[:show]:
            flag = "*" if d["symbol"] in mine else " "
            out.append("%s %-5s %-12s %-4s %12s @ %10s = %13s  %s" % (
                flag, d["kind"], d["symbol"], d["side"], "{:,}".format(d["qty"]), "{:,.2f}".format(d["price"]),
                cr(d["value"]), d["client"][:60]))
        if len(deals) > show:
            out.append("  ... %d more (--show N, or --json for all)." % (len(deals) - show))
        agg = by_symbol(deals)
        net = sorted(agg.items(), key=lambda kv: -abs(kv[1]["buy"] - kv[1]["sell"]))[:5]
        out.append("")
        out.append("Net by stock (bought minus sold in these deals, not the whole market):")
        for sym, a in net:
            out.append("  %-12s bought %s, sold %s, net %s%s" % (
                sym, cr(a["buy"]), cr(a["sell"]), "+" if a["buy"] >= a["sell"] else "-",
                cr(abs(a["buy"] - a["sell"]))))
        if any(d["symbol"] in mine for d in deals):
            out.append("* = on your watchlist, plan or portfolio.")
    for n in notes:
        out.append("note: %s" % n)
    out.append("A deal is a fact about a trade, not a signal: every buyer had a seller. Not financial advice.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="only these NSE symbols")
    ap.add_argument("--watch", action="store_true", help="only your watchlist, plan and portfolio symbols")
    ap.add_argument("--client", help="only deals whose client name contains this (case-insensitive)")
    ap.add_argument("--side", choices=["buy", "sell"])
    ap.add_argument("--kind", choices=["bulk", "block"], help="only one of the two files")
    ap.add_argument("--min-value", type=float, default=0, help="minimum deal value in ₹ crore")
    ap.add_argument("--new", action="store_true", help="only deals not shown before (state file)")
    ap.add_argument("--state", default="trader/state/deals.json")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--offline", metavar="DIR", help="read bulk.csv and block.csv from DIR")
    ap.add_argument("--show", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    deals, notes = [], []
    for kind, path, fname in FILES:
        if a.kind and kind != a.kind:
            continue
        try:
            deals += parse_csv(fetch(kind, path, fname, a.offline), kind)
        except DealsError as e:
            notes.append(str(e))
    mine = watch_symbols(a.portfolio, a.watchlist, a.plan)
    if a.tickers:
        want = {t.upper()[:-3] if t.upper().endswith(".NS") else t.upper() for t in a.tickers}
        deals = [d for d in deals if d["symbol"] in want]
    if a.watch:
        if not mine:
            notes.append("--watch: no symbols in trader/watchlist.json, plan.json or portfolio.json")
        deals = [d for d in deals if d["symbol"] in mine]
    if a.client:
        c = a.client.lower()
        deals = [d for d in deals if c in d["client"].lower()]
    if a.side:
        deals = [d for d in deals if d["side"] == a.side.upper()]
    if a.min_value:
        deals = [d for d in deals if d["value"] >= a.min_value * CRORE - 0.5]
    state = load_json(a.state) or {}
    seen = state.setdefault("seen", {})
    if a.new:
        deals = [d for d in deals if fingerprint(d) not in seen]
    deals.sort(key=lambda d: (-d["value"], d["symbol"]))
    if a.json:
        print(json.dumps({"deals": deals, "by_symbol": by_symbol(deals), "notes": notes,
                          "mine": sorted(mine)}, indent=2, ensure_ascii=False))
    else:
        print(render(deals, notes, mine, a.show))
    if a.new and deals:
        today = _dt.date.today().isoformat()
        for d in deals:
            seen.setdefault(fingerprint(d), d["date"] or today)
        cutoff = (_dt.date.today() - _dt.timedelta(days=KEEP_DAYS)).isoformat()
        state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
        folder = os.path.dirname(a.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(a.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    if notes and not deals and len(notes) == len([f for f in FILES if not a.kind or f[0] == a.kind]):
        return 1
    return 0 if deals else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):      # Windows pipes default to cp1252, which has no ₹
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
