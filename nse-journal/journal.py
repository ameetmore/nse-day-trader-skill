#!/usr/bin/env python3
"""Decision journal for nse-journal: the pack's memory. Standard library only.

Every call the pack makes (an nse-research rating, or a day trade) goes into
an append-only journal. Once its window has traded, the call is SETTLED: scored
against its own price and against NIFTY 50 over the same days. Then a short
lesson is written for it, and nse-research reads the lessons back before the
next call on that stock. The idea is TradingAgents' memory log, made
deterministic: the numbers are computed here; only the lesson is words.

    python3 journal.py record --from trader/research/RELIANCE-2026-10-15.md   # rating read from the report
    python3 journal.py record --symbol TCS --date 2026-10-15 --rating Overweight --horizon 10
    python3 journal.py trade --symbol DEMO --date 2026-10-29 --pnl 859.77 --r 0.71 --note "orb, 1R target"
    python3 journal.py settle                         # score every call whose window is over
    python3 journal.py reflect --id TCS-2026-10-15-1 --lesson "..."
    python3 journal.py lessons RELIANCE               # what past calls taught, this stock first
    python3 journal.py score                          # the scorecard: hit rate and alpha by rating
    python3 journal.py show --n 20

Ratings: the five-tier scale Buy, Overweight, Hold, Underweight, Sell. A report
whose own rating line cannot be read (missing, or two rating lines that
disagree) is recorded as REVIEW and never scored: a decision nobody can read
is not a Hold.

Settling a rating: the window starts at the first close AFTER the decision
date (the decision was made with that day's information) and runs --horizon
trading days (default 5). Return = end close / start close - 1; alpha =
return - NIFTY 50's return over the same dates. A hit: Buy or Overweight with
alpha > 0; Sell or Underweight with alpha < 0; Hold with |alpha| under the hold
band (2%). Day trades are scored on their own result (net rupees and R).

Data: Yahoo daily closes for SYMBOL.NS and ^NSEI. Offline: --offline DIR reads
<SYMBOL>-1y-1d.json and NSEI-1y-1d.json. Journal: trader/journal.json.
"""

import argparse
import datetime
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

RATINGS = ("Buy", "Overweight", "Hold", "Underweight", "Sell")
REVIEW = "REVIEW"
BULL, BEAR = {"Buy", "Overweight"}, {"Sell", "Underweight"}
HOLD_BAND = 2.0
BENCH = "^NSEI"
IST = datetime.timedelta(hours=5, minutes=30)
UA = "Mozilla/5.0 (compatible; nse-day-trader-skill/1.0; +https://github.com/ameetmore/nse-day-trader-skill)"

_OWN = r"(?:(?:final|our|overall|recommended|portfolio manager'?s?)\s+)*"
RATING_LINE = re.compile(r"^\s*(?:[-*+]\s+)?[\s*_#]*" + _OWN + r"rating\b[^:\n]*?[:\-–—]"
                         r"[\s*_]*(buy|overweight|hold|underweight|sell)\b", re.I)
SCALE_LINE = re.compile(r"rating\s*(scale|options|legend)", re.I)


class JournalError(Exception):
    pass


def parse_rating(text):
    """The report's own rating, or None. Its rating lines must agree; a scale legend is ignored."""
    if not text:
        return None
    norm = unicodedata.normalize("NFKC", text)
    found = []
    for line in norm.splitlines():
        if SCALE_LINE.search(line):
            continue
        m = RATING_LINE.match(line)
        if m:
            found.append(m.group(1).capitalize())
    if not found or len(set(found)) > 1:
        return None
    return found[0]


# ---------------------------------------------------------------- storage

def load(path):
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    else:
        doc = {}
    doc.setdefault("entries", [])
    return doc


def save(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def new_id(doc, sym, date):
    n = 1 + sum(1 for e in doc["entries"] if e["symbol"] == sym and e["date"] == date)
    return "%s-%s-%d" % (sym, date, n)


def nse_symbol(s):
    s = str(s).strip().upper()
    return s[:-3] if s.endswith(".NS") else s


def check_date(d, what="--date"):
    try:
        return datetime.date.fromisoformat(d).isoformat()
    except (TypeError, ValueError):
        raise JournalError("%s wants YYYY-MM-DD, got %r" % (what, d))


# ---------------------------------------------------------------- prices

def yahoo_symbol(sym):
    s = str(sym).strip().upper()
    if s.startswith("^") or s.endswith((".NS", ".BO")):
        return s
    return s + ".NS"


def closes(sym, offline=None):
    """{date: close} from Yahoo's daily chart (dates in IST)."""
    if offline:
        name = {"^NSEI": "NSEI", "^INDIAVIX": "INDIAVIX"}.get(yahoo_symbol(sym), nse_symbol(sym))
        p = os.path.join(offline, name + "-1y-1d.json")
        if not os.path.isfile(p):
            raise JournalError("offline: no %s" % p)
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
    else:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=2y&interval=1d" % (
            urllib.parse.quote(yahoo_symbol(sym), safe=".^-"))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                text = r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as e:
            raise JournalError("prices for %s: %s" % (sym, getattr(e, "reason", e)))
    try:
        r = json.loads(text)["chart"]["result"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        raise JournalError("no price data for %s" % sym)
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    out = {}
    for t, c in zip(r.get("timestamp") or [], q.get("close") or []):
        if t is None or c is None or c <= 0:
            continue
        d = (datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=int(t)) + IST).date().isoformat()
        out[d] = float(c)
    return out


def window(series, date, horizon, today):
    """(start date, start close, end date, end close) or None if the window has not finished.
    Only completed sessions count: today's bar is used only after it is in the past."""
    days = [d for d in sorted(series) if d > date and d < today]
    if len(days) < horizon + 1:
        return None
    s, e = days[0], days[horizon]
    return s, series[s], e, series[e]


def hit(rating, alpha, band=HOLD_BAND):
    if rating in BULL:
        return alpha > 0
    if rating in BEAR:
        return alpha < 0
    return abs(alpha) < band


# ---------------------------------------------------------------- commands

def cmd_record(a, doc):
    text = None
    if a.source_file:
        with open(a.source_file, encoding="utf-8") as fh:
            text = fh.read()
    sym = nse_symbol(a.symbol or _guess_symbol(a.source_file))
    date = check_date(a.date or _guess_date(a.source_file))
    if a.rating:
        rating = next((r for r in RATINGS if r.lower() == a.rating.strip().lower()), None)
        if not rating:
            raise JournalError("--rating is one of %s" % ", ".join(RATINGS))
    else:
        rating = parse_rating(text)
    e = {"id": new_id(doc, sym, date), "kind": "rating", "symbol": sym, "date": date,
         "rating": rating or REVIEW, "horizon": a.horizon, "status": "review" if not rating else "pending",
         "report": a.source_file, "summary": _summary(text) if text else (a.note or ""),
         "recorded_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    doc["entries"].append(e)
    if not rating:
        print("Recorded %s as REVIEW: no single readable rating line (\"Rating: Buy\" ... \"Sell\") in the "
              "report. It will not be scored. Fix the report and record it again." % e["id"])
    else:
        print("Recorded %s: %s %s on %s, scored over %d trading days from the next close."
              % (e["id"], sym, rating, date, a.horizon))
    return 0 if rating else 1


def cmd_trade(a, doc):
    sym, date = nse_symbol(a.symbol), check_date(a.date)
    e = {"id": new_id(doc, sym, date), "kind": "trade", "symbol": sym, "date": date, "status": "settled",
         "pnl": round(float(a.pnl), 2), "r": None if a.r is None else round(float(a.r), 2),
         "summary": a.note or "", "lesson": None,
         "recorded_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    doc["entries"].append(e)
    print("Recorded trade %s: %s net %s%s. Write its lesson: journal.py reflect --id %s --lesson \"...\""
          % (e["id"], sym, _rs(e["pnl"]), "" if e["r"] is None else ", %+.2fR" % e["r"], e["id"]))
    return 0


def cmd_settle(a, doc):
    today = (a.today and check_date(a.today, "--today")) or (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + IST).date().isoformat()
    pending = [e for e in doc["entries"] if e["kind"] == "rating" and e["status"] == "pending"]
    if not pending:
        print("Nothing to settle.")
        return 1
    cache, done, waiting, notes = {}, [], 0, []

    def series(sym):
        if sym not in cache:
            cache[sym] = closes(sym, a.offline)
        return cache[sym]
    for e in pending:
        try:
            w = window(series(e["symbol"]), e["date"], e["horizon"], today)
            b = window(series(BENCH), e["date"], e["horizon"], today)
        except JournalError as exc:
            notes.append("%s: %s" % (e["id"], exc))
            continue
        if not w or not b:
            waiting += 1
            continue
        if (w[0], w[2]) != (b[0], b[2]):
            notes.append("%s: the stock and NIFTY windows do not line up (%s..%s vs %s..%s); a halt or missing "
                         "bar. Left pending." % (e["id"], w[0], w[2], b[0], b[2]))
            continue
        ret = 100.0 * (w[3] / w[1] - 1)
        bret = 100.0 * (b[3] / b[1] - 1)
        e.update({"status": "settled", "from": w[0], "to": w[2], "start_close": w[1], "end_close": w[3],
                  "return_pct": round(ret, 2), "nifty_pct": round(bret, 2), "alpha_pct": round(ret - bret, 2),
                  "hit": hit(e["rating"], ret - bret), "lesson": e.get("lesson")})
        done.append(e)
    for e in done:
        print("Settled %s: %s %s, %s to %s: %+.2f%% vs NIFTY %+.2f%% = alpha %+.2f%% (%s)."
              % (e["id"], e["symbol"], e["rating"], e["from"], e["to"], e["return_pct"], e["nifty_pct"],
                 e["alpha_pct"], "hit" if e["hit"] else "miss"))
    if waiting:
        print("%d still inside their window." % waiting)
    for n in notes:
        print("note: " + n)
    if done:
        print("Next: write a 2-4 sentence lesson for each (journal.py reflect --id ID --lesson \"...\"): what the "
              "result says about the call, which part of the thesis it supports or undercuts, one thing to do "
              "differently. Say so if %d days is too short to judge the thesis." % done[0]["horizon"])
    return 0 if done else 1


def cmd_reflect(a, doc):
    e = next((x for x in doc["entries"] if x["id"] == a.id), None)
    if not e:
        raise JournalError("no entry %s (journal.py show lists them)" % a.id)
    if e["status"] != "settled":
        raise JournalError("%s is %s: only a settled call gets a lesson, so the lesson knows the outcome"
                           % (a.id, e["status"]))
    lesson = " ".join((a.lesson or "").split())
    if not 20 <= len(lesson) <= 900:
        raise JournalError("a lesson is 2-4 plain sentences (20 to 900 characters)")
    e["lesson"] = lesson
    print("Saved the lesson for %s." % a.id)
    return 0


def lessons_for(doc, sym=None, n=5):
    done = [e for e in doc["entries"] if e.get("lesson")]
    done.sort(key=lambda e: e["date"], reverse=True)
    mine = [e for e in done if sym and e["symbol"] == sym][:n]
    others = [e for e in done if e not in mine][:max(0, n - len(mine))]
    return mine, others


def cmd_lessons(a, doc):
    sym = nse_symbol(a.symbol) if a.symbol else None
    mine, others = lessons_for(doc, sym, a.n)
    if not mine and not others:
        print("No lessons yet: settle some calls and reflect on them first.")
        return 1
    if mine:
        print("Past lessons on %s:" % sym)
        for e in mine:
            print("- %s" % _line(e))
    if others:
        print("Recent lessons on other stocks:")
        for e in others:
            print("- %s" % _line(e))
    print("Lessons are from small samples: weigh them, do not obey them.")
    return 0


def scorecard(doc, band=HOLD_BAND):
    rows = {}
    for e in doc["entries"]:
        if e["kind"] == "rating" and e["status"] == "settled":
            r = rows.setdefault(e["rating"], {"n": 0, "hits": 0, "alpha": 0.0, "ret": 0.0})
            r["n"] += 1
            r["hits"] += 1 if hit(e["rating"], e["alpha_pct"], band) else 0
            r["alpha"] += e["alpha_pct"]
            r["ret"] += e["return_pct"]
    trades = [e for e in doc["entries"] if e["kind"] == "trade"]
    t = None
    if trades:
        rs = [e["r"] for e in trades if e.get("r") is not None]
        t = {"n": len(trades), "wins": sum(1 for e in trades if e["pnl"] > 0),
             "net": round(sum(e["pnl"] for e in trades), 2), "avg_r": round(sum(rs) / len(rs), 2) if rs else None}
    return rows, t, sum(1 for e in doc["entries"] if e["status"] == "review")


def cmd_score(a, doc):
    rows, t, review = scorecard(doc)
    if a.json:
        print(json.dumps({"ratings": rows, "trades": t, "review": review}, indent=2))
        return 0
    if not rows and not t:
        print("Nothing settled yet.")
        return 1
    if rows:
        print("Ratings, settled (hit: Buy/Overweight beat NIFTY, Sell/Underweight lagged it, Hold within %g%%):"
              % HOLD_BAND)
        print("  %-12s %4s %8s %12s %12s" % ("rating", "n", "hit rate", "avg return", "avg alpha"))
        for r in RATINGS:
            if r in rows:
                x = rows[r]
                print("  %-12s %4d %7.0f%% %+11.2f%% %+11.2f%%" % (r, x["n"], 100.0 * x["hits"] / x["n"],
                                                                 x["ret"] / x["n"], x["alpha"] / x["n"]))
        total = sum(x["n"] for x in rows.values())
        if total < 20:
            print("  %d settled calls: too few to tell skill from luck." % total)
    if t:
        print("Day trades: %d, %d winners (%.0f%%), net %s%s." % (
            t["n"], t["wins"], 100.0 * t["wins"] / t["n"], _rs(t["net"]),
            "" if t["avg_r"] is None else ", average %+.2fR" % t["avg_r"]))
    if review:
        print("%d entr%s in REVIEW (no readable rating), not scored." % (review, "y" if review == 1 else "ies"))
    return 0


def cmd_show(a, doc):
    es = doc["entries"][-a.n:]
    if not es:
        print("The journal is empty.")
        return 1
    for e in es:
        print(_line(e, full=True))
    return 0


# ---------------------------------------------------------------- helpers

def _rs(v):
    return ("-" if v < 0 else "+") + "₹{:,.2f}".format(abs(v))


def _line(e, full=False):
    if e["kind"] == "trade":
        head = "%s %s day trade, net %s%s" % (e["date"], e["symbol"], _rs(e["pnl"]),
                                             "" if e.get("r") is None else " (%+.2fR)" % e["r"])
    elif e["status"] == "settled":
        head = "%s %s %s: %+.2f%% vs NIFTY %+.2f%% over %d days (%s)" % (
            e["date"], e["symbol"], e["rating"], e["return_pct"], e["nifty_pct"], e["horizon"],
            "hit" if e["hit"] else "miss")
    else:
        head = "%s %s %s (%s)" % (e["date"], e["symbol"], e["rating"], e["status"])
    if full:
        head = "%-24s %s" % (e["id"], head)
    if e.get("lesson"):
        head += ". Lesson: " + e["lesson"]
    return head


def _summary(text):
    t = re.sub(r"[#*_>`]", "", text or "")
    t = " ".join(t.split())
    return t[:400]


def _guess_symbol(path):
    m = re.search(r"([A-Z0-9&\-]+)-\d{4}-\d{2}-\d{2}", os.path.basename(path or ""))
    if not m:
        raise JournalError("give --symbol (could not read it from the file name)")
    return m.group(1)


def _guess_date(path):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path or ""))
    if not m:
        raise JournalError("give --date (could not read it from the file name)")
    return m.group(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--journal", default="trader/journal.json")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("record", help="record a rating (from a report, or given)")
    p.add_argument("--from", dest="source_file", help="a research report (markdown); its rating line is read")
    p.add_argument("--symbol")
    p.add_argument("--date", help="the decision date, YYYY-MM-DD (default: from the file name)")
    p.add_argument("--rating", help="Buy, Overweight, Hold, Underweight or Sell")
    p.add_argument("--horizon", type=int, default=5, help="trading days to score over (5)")
    p.add_argument("--note")
    p = sub.add_parser("trade", help="record a finished day trade")
    p.add_argument("--symbol", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--pnl", required=True, type=float, help="net rupees after costs")
    p.add_argument("--r", type=float, help="the result in R (risk units)")
    p.add_argument("--note")
    p = sub.add_parser("settle", help="score every call whose window is over")
    p.add_argument("--offline", metavar="DIR")
    p.add_argument("--today", help="YYYY-MM-DD (default: today in IST)")
    p = sub.add_parser("reflect", help="save the lesson for a settled call")
    p.add_argument("--id", required=True)
    p.add_argument("--lesson", required=True)
    p = sub.add_parser("lessons", help="past lessons, this stock first")
    p.add_argument("symbol", nargs="?")
    p.add_argument("--n", type=int, default=5)
    p = sub.add_parser("score", help="hit rate and alpha by rating, and day-trade results")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("show", help="the latest entries")
    p.add_argument("--n", type=int, default=20)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        doc = load(a.journal)
        if a.cmd == "record" and a.horizon < 1:
            raise JournalError("--horizon must be at least 1")
        rc = {"record": cmd_record, "trade": cmd_trade, "settle": cmd_settle, "reflect": cmd_reflect,
              "lessons": cmd_lessons, "score": cmd_score, "show": cmd_show}[a.cmd](a, doc)
        if a.cmd in ("record", "trade", "settle", "reflect"):
            save(a.journal, doc)
        return rc
    except JournalError as e:
        print("journal.py: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
