#!/usr/bin/env python3
"""News monitor for nse-news. Standard library only.

Watches headlines and NSE corporate filings for the stocks you watch or hold
and prints only what is new since the last check, newest first, with how far
each stock has moved today and a flag on anything that touches your symbols.

    python3 news.py                                  # watchlist + plan + portfolio symbols
    python3 news.py --tickers RELIANCE TCS INFY
    python3 news.py --tickers RELIANCE --all --hours 72  # the last 3 days, seen or not
    python3 news.py --no-nse                         # headlines only
    python3 news.py --no-moves                       # skip the price line per symbol

Your symbols, when --tickers is not given: every hit in trader/watchlist.json
(nse-scanner), the symbol in trader/plan.json (nse-exit) and the positions in
trader/portfolio.json. Company names come from trader/universe.txt
(SYMBOL|Name, written by nse-scanner universe) and the watchlist.

Sources:
  - Yahoo Finance headline RSS, one request per symbol (.NS added):
    https://feeds.finance.yahoo.com/rss/2.0/headline?s=<SYMBOL>.NS&region=IN&lang=en-IN
  - NSE's own RSS feeds, one request each for ALL your symbols:
      corporate announcements  .../content/RSS/Online_announcements.xml
      financial results        .../content/RSS/Financial_Results.xml
      board meetings           .../content/RSS/Board_Meetings.xml
    on https://nsearchives.nseindia.com. An item is yours when its title,
    text or attachment name carries your symbol or your company's name.
    NSE sometimes refuses scripts (HTTP 403); the tool then says so and the
    headlines still run.
  - The move: Yahoo Finance's chart endpoint (unofficial, can lag), the last
    price against yesterday's close:
    https://query2.finance.yahoo.com/v8/finance/chart/<SYMBOL>.NS?range=1d&interval=5m

Times print in India time (IST). State: trader/state/news.json remembers what
you have seen (30 days), so an item shows once. Offline: --offline DIR reads
yahoo-<SYMBOL>.xml, chart-<SYMBOL>.json and nse-announcements.xml,
nse-results.xml, nse-board.xml from DIR. The tests use it.

Headlines are leads, not facts: open the filing or the story before acting,
and treat nothing here as advice.
"""

import argparse
import datetime as _dt
import email.utils
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=IN&lang=en-IN"
CHART = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
NSE_HOSTS = ("https://nsearchives.nseindia.com", "https://archives.nseindia.com")
NSE_FEEDS = (  # (offline file, path, kind)
    ("nse-announcements.xml", "/content/RSS/Online_announcements.xml", "announcement"),
    ("nse-results.xml", "/content/RSS/Financial_Results.xml", "results"),
    ("nse-board.xml", "/content/RSS/Board_Meetings.xml", "board meeting"),
)
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
KEEP_DAYS = 30
MOVE_PCT = 3.0  # a stock this far from yesterday's close is flagged as moving
IST = _dt.timedelta(hours=5, minutes=30)

IMPORTANT = re.compile(
    r"financial results|\bresults\b|outcome of board meeting|board meeting|dividend|bonus|split|"
    r"buy-?back|rights issue|\bQIP\b|preferential|acqui|amalgamation|merger|scheme of arrangement|"
    r"resignation|cessation|credit rating|insolvency|\bNCLT\b|default|fraud|SEBI order|penalty|"
    r"pledge|encumbrance|open offer|delist", re.I)
KEYWORDS = [
    ("earnings", r"\bearnings\b|\bresults\b|\bEPS\b|\bguidance\b|\bQ[1-4]\b|\bprofit\b|\brevenue\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|target price|price target|\boutperform\b|\bunderperform\b"),
    ("legal", r"\bSEBI\b|\bNCLT\b|\bcourt\b|\bprobe\b|\binvestigation\b|\bpenalty\b|\bCCI\b|\bED\b raid|\btax demand"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bamalgamation\b|\bstake\b|\btakeover\b|\bopen offer\b"),
    ("capital", r"\bdividend\b|\bbuy-?back\b|\bbonus\b|\bstock split\b|\bsplit\b|\bQIP\b|\brights issue\b|"
                r"\bpreferential\b|\bblock deal\b|\bbulk deal\b"),
    ("people", r"\bCEO\b|\bCFO\b|\bMD\b|\bresign|\bcessation\b|\bappoint"),
    ("risk", r"\bdefault\b|\binsolvency\b|\bpledge\b|\bencumbrance\b|\bfraud\b|\bdowngrade\b|\bdelist"),
    ("circuit", r"\bupper circuit\b|\blower circuit\b|\bcircuit\b|\bsurveillance\b|\bASM\b|\bGSM\b"),
    ("macro", r"\bRBI\b|\brepo rate\b|\bMPC\b|\bCPI\b|\binflation\b|\bGDP\b|\bFII\b|\bFPI\b|\bbudget\b|\brupee\b"),
]


class NewsError(Exception):
    pass


# ---------------------------------------------------------------- time

def to_ist(utc):
    """Aware or naive UTC -> naive India wall-clock time (UTC+5:30, no daylight saving)."""
    if utc.tzinfo is not None:
        utc = utc.astimezone(_dt.timezone.utc)
    return utc.replace(tzinfo=None) + IST


# ---------------------------------------------------------------- inputs

def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def load_names(path="trader/universe.txt"):
    out = {}
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                if "|" in ln:
                    sym, name = ln.rstrip("\n").split("|", 1)
                    out[sym.strip().upper()] = name.strip() or None
    return out


def watch_from_files(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json",
                     plan="trader/plan.json"):
    """{symbol: name or None}: the scanner's hits, the planned trade and your holdings."""
    out = {}
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []):
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out[sym.upper()] = h.get("name")
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.setdefault(pl["symbol"].upper(), pl.get("name"))
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []):
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            out[sym.upper()] = p.get("name") or out.get(sym.upper())
    return out


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.15):
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def get(self, url, name, referer=None):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise NewsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        headers = {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip", "Accept": "*/*"}
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            raise NewsError("HTTP %s for %s" % (exc.code, url))
        except urllib.error.URLError as exc:
            raise NewsError("could not reach %s: %s" % (url, exc.reason))


def yahoo_symbol(sym):
    """NSE symbol -> Yahoo symbol: RELIANCE -> RELIANCE.NS. SYM.BO (a BSE listing),
    SYM.NS and index symbols like ^NSEI are kept as they are."""
    s = str(sym).strip().upper()
    if s.startswith("^") or s.endswith((".NS", ".BO")):
        return s
    return s + ".NS"


def _yq(sym):
    return urllib.parse.quote(yahoo_symbol(sym), safe=".^-")


# ---------------------------------------------------------------- parsing

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _text(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_time(value):
    """RFC 822 (RSS), ISO 8601, or NSE's '29-Oct-2026 18:23:01' (IST) -> aware UTC, or None."""
    value = (value or "").strip()
    if not value:
        return None
    d = None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            d = None
    if d is None:
        for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
            try:
                d = (_dt.datetime.strptime(value, fmt) - IST).replace(tzinfo=_dt.timezone.utc)
                break
            except ValueError:
                continue
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def parse_rss(data, ticker):
    """Yahoo headline RSS -> items."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("RSS for %s is not valid XML: %s" % (ticker, exc))
    out = []
    for it in root.iter("item"):
        title = _text(it, "title")
        link = _text(it, "link")
        guid = _text(it, "guid") or link
        out.append({"id": "rss:" + guid, "source": "Yahoo Finance", "kind": "headline",
                    "ticker": ticker, "title": title, "summary": _text(it, "description"),
                    "link": link, "time": parse_time(_text(it, "pubDate")), "important": False})
    return out


def parse_nse_rss(data, kind):
    """One of NSE's RSS feeds -> items, not yet tied to a symbol (ticker "")."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("NSE %s feed is not valid XML: %s" % (kind, exc))
    out = []
    for it in root.iter("item"):
        title = " ".join(_text(it, "title").split())
        desc = " ".join(re.sub(r"<[^>]+>", " ", _text(it, "description")).split())
        link = _text(it, "link")
        when = parse_time(_text(it, "pubDate"))
        key = link or "%s|%s|%s" % (kind, title, desc[:80])
        hay = "%s %s" % (title, desc)
        out.append({"id": "nse:" + key, "source": "NSE", "kind": kind, "ticker": "", "company": title,
                    "title": ("%s: %s" % (title, desc)) if desc and desc.lower() != title.lower() else title,
                    "summary": desc, "link": link, "time": when,
                    "important": kind != "announcement" or bool(IMPORTANT.search(hay))})
    return out


def parse_chart(data, ticker):
    """Yahoo chart JSON -> {"ticker", "price", "prev_close", "pct", "time"} or raise."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NewsError("chart for %s is not usable" % ticker)
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not price or not prev:
        raise NewsError("chart for %s has no price" % ticker)
    when = meta.get("regularMarketTime")
    return {"ticker": ticker, "price": round(float(price), 2), "prev_close": round(float(prev), 2),
            "pct": round((float(price) / float(prev) - 1) * 100, 2),
            "time": _dt.datetime.fromtimestamp(when, _dt.timezone.utc) if when else None}


def collect_moves(fetcher, watch, errors=None):
    errors = [] if errors is None else errors
    out = []
    for t in sorted(watch):
        name = "chart-%s.json" % t
        try:
            try:
                data = fetcher.get(CHART % ("query2", _yq(t)), name)
            except NewsError as exc:
                if fetcher.offline or not re.search(r"HTTP (429|5\d\d)", str(exc)):
                    raise
                data = fetcher.get(CHART % ("query1", _yq(t)), name)
            out.append(parse_chart(data, t))
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("price for %s: %s" % (t, exc))
    return out


def norm_company(name):
    """'Reliance Industries Ltd.' and 'RELIANCE INDUSTRIES LIMITED' -> 'reliance industries'."""
    t = (name or "").lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\b(limited|ltd|the)\b", " ", t)
    return " ".join(t.split())


def mention_patterns(watch):
    """Headline mentions of your other symbols: the symbol as written (case-sensitive, so
    RELIANCE is not 'Reliance MF') or the full company name."""
    pats = {}
    for t, name in watch.items():
        base = t[:-3] if t.endswith((".NS", ".BO")) else t
        alts = [r"\bNSE\s*:\s*%s\b" % re.escape(base), r"\(%s\)" % re.escape(base)]
        if len(base) >= 3:
            alts.append(r"(?<![\w&-])%s(?![\w&-])" % re.escape(base))
        rx = [re.compile("|".join(alts))]
        if name and norm_company(name):
            words = norm_company(name).split()
            rx.append(re.compile(r"\b%s\b" % r"[\W_]+".join(re.escape(w) for w in words), re.I))
        pats[t] = rx
    return pats


def nse_touches(item, watch):
    """An NSE filing is yours only when its company is exactly yours (NSE titles are the
    company's name), or its attachment starts with your symbol: .../RELIANCE_29102026...pdf.
    'Reliance Chemotex Industries' or a 'Reliance MF' NAV is not RELIANCE."""
    company = norm_company(item.get("company"))
    out = set()
    for t, name in watch.items():
        base = t[:-3] if t.endswith((".NS", ".BO")) else t
        if name and company and norm_company(name) == company:
            out.add(t)
        elif re.search(r"/%s_\d{8}" % re.escape(base), item.get("link") or ""):
            out.add(t)
    return out


def tag(items, watch):
    """Which of your symbols each item touches, and why it matters."""
    pats = mention_patterns(watch)
    for it in items:
        hay = "%s %s %s" % (it["title"], it.get("summary") or "", it.get("link") or "")
        if it["source"] == "NSE":
            touches = nse_touches(it, watch)
        else:
            touches = {it["ticker"]} if it["ticker"] in watch else set()
            text = "%s %s" % (it["title"], it.get("summary") or "")
            for t, rxs in pats.items():
                if any(r.search(text) for r in rxs):
                    touches.add(t)
        it["touches"] = sorted(touches)
        it["tags"] = [label for label, rx in KEYWORDS if re.search(rx, hay, re.I)]
        if it["kind"] == "results" and "earnings" not in it["tags"]:
            it["tags"].insert(0, "earnings")
    return items


def dedupe(items):
    """One item per story: same id, or same link, or same title the same day."""
    seen, out = {}, []
    for it in items:
        keys = [it["id"], it["link"],
                "%s|%s" % (re.sub(r"\W+", " ", it["title"].lower()).strip(),
                           it["time"].date() if it["time"] else "")]
        hit = next((seen[k] for k in keys if k and k in seen), None)
        if hit is not None:
            for t in it.get("touches", []):
                if t not in hit["touches"]:
                    hit["touches"].append(t)
            hit["touches"].sort()
            continue
        for k in keys:
            if k:
                seen[k] = it
        out.append(it)
    return out


def fingerprint(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- the check

def collect(fetcher, watch, nse=True, errors=None):
    errors = [] if errors is None else errors
    items = []
    for t in sorted(watch):
        try:
            items += parse_rss(fetcher.get(YAHOO % _yq(t), "yahoo-%s.xml" % t), t)
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("headlines for %s: %s" % (t, exc))
    if nse:
        for fname, path, kind in NSE_FEEDS:
            data, last = None, None
            for host in NSE_HOSTS:
                try:
                    data = fetcher.get(host + path, fname, referer="https://www.nseindia.com/")
                    break
                except NewsError as exc:
                    last = exc
                    if fetcher.offline:
                        break
            if data is None:
                if not (fetcher.offline and last and "no file" in str(last)):
                    errors.append("NSE %s feed: %s" % (kind, last))
                continue
            try:
                items += parse_nse_rss(data, kind)
            except NewsError as exc:
                errors.append(str(exc))
    return items


def mine(items, watch):
    """Headlines are per symbol already; NSE items count only when they touch one of yours."""
    return [it for it in items if it["source"] != "NSE" or it.get("touches")]


def select(items, state, now, hours=48, show_all=False):
    """Items within the window; only unseen ones unless show_all."""
    seen = state.setdefault("seen", {})
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)  # a pinned --now: nothing from after it
    out = []
    for it in items:
        if it["time"] is not None and (it["time"] < cutoff or it["time"] > ahead):
            continue
        fp = fingerprint(it)
        it["new"] = fp not in seen
        if it["new"] or show_all:
            out.append(it)
    out.sort(key=lambda i: (i["time"] or now), reverse=True)
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    stamp = now.isoformat()
    for it in items:
        seen.setdefault(fingerprint(it), stamp)
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = stamp


def render_moves(moves, move_pct=MOVE_PCT):
    out = []
    for m in moves:
        flag = "MOVING" if abs(m["pct"]) >= move_pct else ""
        when = (" at %s IST" % to_ist(m["time"]).strftime("%H:%M")) if m.get("time") else ""
        out.append("%-12s %s %+.2f%% vs yesterday's close %s%s  %s" % (
            m["ticker"], "{:,.2f}".format(m["price"]), m["pct"], "{:,.2f}".format(m["prev_close"]),
            when, flag))
    return out


def render(items, errors, now, moves=None, move_pct=MOVE_PCT):
    out = render_moves(moves or [], move_pct)
    if out:
        out.append("")
    if not items:
        out.append("Nothing new.")
    for it in items:
        when = to_ist(it["time"]).strftime("%Y-%m-%d %H:%M IST") if it["time"] else "time unknown"
        mark = "!" if it.get("important") else " "
        who = ",".join(it["touches"]) or it["ticker"]
        src = it["source"] if it["source"] != "NSE" else "NSE %s" % it["kind"]
        out.append("%s %s  %-12s %-18s %s" % (mark, when, who, src, it["title"]))
        extra = []
        if it["tags"]:
            extra.append("tags: " + ", ".join(it["tags"]))
        extra.append(it["link"])
        out.append("      " + "  ".join(x for x in extra if x))
    for e in errors:
        out.append("note: %s" % e)
    out.append("Checked %s. Headlines are leads, not facts; open the filing or the story before acting. "
               "Not financial advice." % to_ist(now).strftime("%Y-%m-%d %H:%M IST"))
    return "\n".join(out) + "\n"


def _json_ready(items):
    out = []
    for it in items:
        d = dict(it)
        d["time"] = it["time"].isoformat() if it["time"] else None
        out.append(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="NSE symbols; default: watchlist + plan + portfolio")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--universe", default="trader/universe.txt", help="SYMBOL|Name lines, for company names")
    ap.add_argument("--state", default="trader/state/news.json")
    ap.add_argument("--hours", type=float, default=48, help="ignore items older than this")
    ap.add_argument("--all", action="store_true", help="show seen items too")
    ap.add_argument("--no-nse", action="store_true", help="headlines only, skip NSE's filing feeds")
    ap.add_argument("--no-moves", action="store_true", help="skip the price line per symbol")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT, help="flag a move this big (percent)")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time, for reproducible runs (no offset = UTC)")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    known = watch_from_files(args.portfolio, args.watchlist, args.plan)
    if args.tickers:
        watch = {t.upper(): known.get(t.upper()) for t in args.tickers}
    else:
        watch = known
    if not watch:
        print("news: no symbols. Pass --tickers, or run /nse-scanner first (it writes "
              "trader/watchlist.json).", file=sys.stderr)
        return 2
    names = load_names(args.universe)
    for t in watch:
        watch[t] = watch[t] or names.get(t)
    now = parse_time(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    state = load_json(args.state) or {}
    errors = []
    fetcher = Fetcher(offline=args.offline)
    items = collect(fetcher, watch, nse=not args.no_nse, errors=errors)
    items = mine(dedupe(tag(items, watch)), watch)
    shown = select(items, state, now, hours=args.hours, show_all=args.all)
    moves = [] if args.no_moves else collect_moves(fetcher, watch, errors)
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        print(json.dumps({"checked": now.isoformat(), "moves": mv, "items": _json_ready(shown),
                          "notes": errors}, indent=2))
    else:
        sys.stdout.write(render(shown, errors, now, moves, args.move_pct))
    if not args.dry_run:
        remember(items, state, now)
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):      # Windows pipes default to cp1252, which has no ₹
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
