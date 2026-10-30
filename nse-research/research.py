#!/usr/bin/env python3
"""Research desk helper for nse-research. Standard library only.

nse-research runs a TradingAgents-style committee with Claude playing every
seat. This script does the deterministic parts: it gathers the evidence from
the pack's own tools into one bundle, and it checks and files the committee's
final report.

    python3 research.py gather RELIANCE                    # -> trader/research/RELIANCE-<today>/bundle.json + bundle.md
    python3 research.py gather RELIANCE --as-of 2026-10-15 # point in time: a past-dated run sees only that day
    python3 research.py check trader/research/RELIANCE-2026-10-30.md
    python3 research.py save RELIANCE trader/research/RELIANCE-2026-10-30.md   # check, then record in the journal

gather runs, for the symbol (each part may fail on its own; the bundle says
which, and the committee must not invent what is missing):
  technicals   nse-technicals snapshot (daily indicators) and the market regime
               (NIFTY 50 trend, India VIX)
  fundamentals nse-analyst quarters (rupees crore, growth, margins, NSE filing)
  news         nse-news headlines and NSE filings (72 hours; with --as-of, the
               72 hours before that day's close)
  flows        nse-deals bulk and block deals in the symbol (latest file only,
               so left out of a past-dated run)
  memory       nse-journal lessons from past calls, this stock first

check reads a finished report and confirms it has every section the committee
must write and exactly one readable rating (Buy, Overweight, Hold, Underweight,
Sell). save does check, files the report as trader/research/<SYMBOL>-<DATE>.md,
and records it with nse-journal for scoring.

--fixtures DIR (tests): reads offline data from DIR/daily, DIR/news,
DIR/analyst and DIR/deals.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.dirname(HERE)
IST = datetime.timedelta(hours=5, minutes=30)
SECTIONS = ("Rating", "Executive summary", "Analyst reports", "Bull case", "Bear case",
            "Research manager", "Trader plan", "Risk debate", "Portfolio manager", "What would change the call")


def tool(folder, script):
    p = os.path.join(PACK, folder, script)
    if not os.path.isfile(p):
        raise SystemExit("research.py: %s is missing; install the whole pack (it needs %s)" % (p, folder))
    return p


def run(folder, script, args):
    """(ok, parsed JSON or text, error text)."""
    try:
        p = subprocess.run([sys.executable, tool(folder, script)] + args, capture_output=True, text=True,
                           encoding="utf-8", timeout=180, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    except subprocess.TimeoutExpired:
        return False, None, "timed out"
    out = p.stdout.strip()
    try:
        data = json.loads(out) if out.startswith(("{", "[")) else out
    except ValueError:
        data = out
    err = p.stderr.strip()
    ok = bool(out) and (p.returncode in (0, 1)) and not (isinstance(data, str) and not data)
    return ok, data, err


def today_ist():
    return (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + IST).date().isoformat()


def nse_symbol(s):
    s = str(s).strip().upper()
    return s[:-3] if s.endswith(".NS") else s


def gather(sym, as_of=None, fixtures=None, journal="trader/journal.json"):
    sym = nse_symbol(sym)
    fx = (lambda sub: ["--offline", os.path.join(fixtures, sub)]) if fixtures else (lambda sub: [])
    asof = ["--as-of", as_of] if as_of else []
    parts, missing = {}, []

    ok, data, err = run("nse-technicals", "indicators.py", ["snapshot", sym, "--json"] + asof + fx("daily"))
    parts["technicals"] = data.get(sym) if ok and isinstance(data, dict) and data.get(sym) else None
    if parts["technicals"] is None:
        missing.append("technicals: %s" % (err or "no data"))
    ok, data, err = run("nse-technicals", "indicators.py", ["regime", "--json"] + asof + fx("daily"))
    parts["regime"] = data if ok and isinstance(data, dict) else None
    if parts["regime"] is None:
        missing.append("market regime: %s" % (err or "no data"))

    ok, data, err = run("nse-analyst", "facts.py", [sym, "--json", "--quarters", "6"] + asof + fx("analyst"))
    comp = (data or {}).get("companies", {}).get(sym) if ok and isinstance(data, dict) else None
    parts["fundamentals"] = comp
    if comp is None:
        missing.append("fundamentals: %s" % (err or "no data"))

    news_args = ["--tickers", sym, "--hours", "72", "--all", "--dry-run", "--json", "--state",
                 os.path.join("trader", "state", "research-news.json")]
    if as_of:
        close = datetime.datetime.fromisoformat(as_of + "T15:30:00") - IST
        news_args += ["--now", close.strftime("%Y-%m-%dT%H:%M:%SZ")]
        if not fixtures:
            news_args.append("--no-moves")      # today's price is not point in time
    ok, data, err = run("nse-news", "news.py", news_args + fx("news"))
    parts["news"] = data if ok and isinstance(data, dict) else None
    if parts["news"] is None:
        missing.append("news: %s" % (err or "no data"))

    if as_of and not fixtures:
        parts["flows"] = None
        missing.append("flows: bulk and block deals are today's file only, left out of a past-dated run")
    else:
        ok, data, err = run("nse-deals", "deals.py", ["--tickers", sym, "--json"] + fx("deals"))
        parts["flows"] = data if ok and isinstance(data, dict) else None
        if parts["flows"] is None:
            missing.append("flows: %s" % (err or "no data"))

    ok, data, err = run("nse-journal", "journal.py", ["--journal", journal, "lessons", sym, "--n", "5"])
    parts["memory"] = data if ok and isinstance(data, str) else "No lessons yet."
    return {"symbol": sym, "as_of": as_of or today_ist(), "point_in_time": bool(as_of),
            "gathered_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "parts": parts, "missing": missing}


def bundle_md(b):
    p = b["parts"]
    out = ["# Evidence bundle: %s, as of %s%s" % (b["symbol"], b["as_of"], " (point in time)" if b["point_in_time"] else ""),
           "", "Every number the committee quotes must come from here. Missing parts are missing: say so, "
           "do not fill them in.", ""]
    t = p.get("technicals")
    out.append("## Technicals (daily, nse-technicals)")
    if t:
        out.append("Close %.2f on %s (the snapshot's own lines):" % (t["close"], t["date"]))
        out += ["- " + r for r in t.get("read", [])]
    else:
        out.append("Not available.")
    r = p.get("regime")
    if r:
        out += ["", "Market regime (NIFTY 50, India VIX): %s. NIFTY %.2f on %s%s." % (
            r["label"], r["nifty"]["close"], r["date"], (", VIX %.2f" % r["vix"]) if r.get("vix") is not None else "")]
    out += ["", "## Fundamentals (nse-analyst, rupees crore)"]
    f = p.get("fundamentals")
    if f and f.get("quarters"):
        for q in f["quarters"][:4]:
            out.append("- %s: revenue %s cr (y/y %s), net profit %s cr (y/y %s), net margin %s, EPS %s" % (
                q["label"], _cr(q["revenue"]), _pc(q["revenue_yoy"]), _cr(q["net_income"]), _pc(q["net_income_yoy"]),
                _pc(q["net_margin"], sign=False), "-" if q["eps_diluted"] is None else "%.2f" % q["eps_diluted"]))
        if f.get("filing"):
            out.append("- Latest NSE results filing: %s" % f["filing"].get("link"))
    else:
        out.append("Not available.")
    out += ["", "## News and filings, last 72 hours (nse-news)"]
    n = p.get("news")
    items = (n or {}).get("items") or []
    for it in items[:15]:
        out.append("- %s%s [%s] %s%s" % ("! " if it.get("important") else "", _ist(it.get("time")),
                                          it.get("source"), it.get("title"),
                                          (" (tags: %s)" % ", ".join(it["tags"])) if it.get("tags") else ""))
    for m in (n or {}).get("moves") or []:
        out.append("- Today's move: %+.2f%% to %.2f" % (m["pct"], m["price"]))
    if not items:
        out.append("No items." if n else "Not available.")
    out += ["", "## Flows: bulk and block deals (nse-deals)"]
    fl = p.get("flows")
    deals = (fl or {}).get("deals") or []
    for d in deals[:10]:
        out.append("- %s %s %s %s shares at %.2f (%s, %s cr)" % (d["date"], d["kind"], d["side"], "{:,}".format(d["qty"]),
                                                                d["price"], d["client"], _cr(d["value"])))
    if not deals:
        out.append("No deals in the file." if fl else "Not available.")
    out += ["", "## Memory (nse-journal)", p.get("memory") or "No lessons yet."]
    if b["missing"]:
        out += ["", "## Missing", ""] + ["- " + m for m in b["missing"]]
    return "\n".join(out) + "\n"


def _ist(iso):
    if not iso:
        return "time unknown"
    try:
        t = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:16]
    return (t.astimezone(datetime.timezone.utc).replace(tzinfo=None) + IST).strftime("%Y-%m-%d %H:%M IST")


def _cr(v):
    return "-" if v is None else "{:,.1f}".format(v / 1e7)


def _pc(v, sign=True):
    return "-" if v is None else (("%+.1f%%" if sign else "%.1f%%") % v)


def check(text):
    """(ok, problems, rating)."""
    sys.path.insert(0, os.path.join(PACK, "nse-journal"))
    import journal  # noqa: E402
    problems = []
    heads = [h.strip().lower() for h in re.findall(r"^#{1,3}\s*(.+?)\s*$", text, re.M)]
    for s in SECTIONS[1:]:
        if not any(h.startswith(s.lower()) for h in heads):
            problems.append("no \"%s\" section" % s)
    rating = journal.parse_rating(text)
    if not rating:
        problems.append("no single readable rating line (\"Rating: Buy\" ... \"Sell\"), or two that disagree")
    if re.search(r"\b(guaranteed|sure shot|cannot lose|risk-free)\b", text, re.I):
        problems.append("promises a result (guaranteed / sure shot / risk-free): remove it")
    return not problems, problems, rating


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("gather", help="collect the evidence bundle for one symbol")
    p.add_argument("symbol")
    p.add_argument("--as-of", help="YYYY-MM-DD: a past-dated, point-in-time run")
    p.add_argument("--fixtures", metavar="DIR", help="offline data root (tests)")
    p.add_argument("--journal", default="trader/journal.json")
    p.add_argument("--out", help="folder (default trader/research/<SYMBOL>-<DATE>)")
    p = sub.add_parser("check", help="check a finished committee report")
    p.add_argument("report")
    p = sub.add_parser("save", help="check, file and record a report in the journal")
    p.add_argument("symbol")
    p.add_argument("report")
    p.add_argument("--date", help="decision date (default: the bundle's as-of, else today IST)")
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--journal", default="trader/journal.json")
    a = ap.parse_args(argv)
    if a.cmd == "gather":
        if a.as_of:
            datetime.date.fromisoformat(a.as_of)
        b = gather(a.symbol, a.as_of, a.fixtures, a.journal)
        folder = a.out or os.path.join("trader", "research", "%s-%s" % (b["symbol"].replace("&", "_"), b["as_of"]))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "bundle.json"), "w", encoding="utf-8") as fh:
            json.dump(b, fh, indent=2, ensure_ascii=False)
        md = bundle_md(b)
        with open(os.path.join(folder, "bundle.md"), "w", encoding="utf-8") as fh:
            fh.write(md)
        print(md)
        present = sum(1 for v in b["parts"].values() if v)
        print("Wrote %s/bundle.json and bundle.md: %d of %d parts present." % (folder, present, len(b["parts"])))
        return 0 if b["parts"].get("technicals") else 1
    if a.cmd in ("check", "save"):
        with open(a.report, encoding="utf-8") as fh:
            text = fh.read()
        ok, problems, rating = check(text)
        if not ok:
            print("Report not ready:")
            for pr in problems:
                print("  - " + pr)
            return 1
        if a.cmd == "check":
            print("Report OK: rating %s, all %d sections present." % (rating, len(SECTIONS)))
            return 0
        sym = nse_symbol(a.symbol)
        date = a.date or _date_from(a.report) or today_ist()
        dest = os.path.join("trader", "research", "%s-%s.md" % (sym.replace("&", "_"), date))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.abspath(dest) != os.path.abspath(a.report):
            shutil.copyfile(a.report, dest)
        ok2, data, err = run("nse-journal", "journal.py", ["--journal", a.journal, "record", "--from", dest,
                                                          "--symbol", sym, "--date", date, "--horizon", str(a.horizon)])
        print("Filed %s (rating %s)." % (dest, rating))
        print(data if isinstance(data, str) else err)
        return 0 if ok2 else 1
    ap.print_help()
    return 1


def _date_from(path):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    return m.group(1) if m else None


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):      # Windows pipes default to cp1252, which has no ₹
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
