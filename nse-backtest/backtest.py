#!/usr/bin/env python3
"""Backtest for nse-backtest: the pack's NIFTY 50 / SENSEX option-buying opening-range
breakout, over years of real 5-minute index bars. Standard library only.

    python3 backtest.py kite-login                                # 1. open the printed URL, log in to Kite
    python3 backtest.py kite-token REQUEST_TOKEN                  # 2. turn the redirect's request_token into today's access token
    python3 backtest.py fetch --index NIFTY --years 5             # 3. download 5 years of 5-minute bars from Kite, merged
    python3 backtest.py fetch-vix                                 # 4. India VIX daily closes (free, Yahoo; or --kite)
    python3 backtest.py fetch-plan --index NIFTY --years 5        # or: the Kite calls, for Claude's Kite connector (small ranges)
    python3 backtest.py merge --index NIFTY trader/backtest/raw/NIFTY-*.json
    python3 backtest.py vix trader/backtest/raw/VIX-day.json
    python3 backtest.py run --index NIFTY                         # -> report; --write saves trader/backtest/
    python3 backtest.py run --index SENSEX --sides up --target-r 1.5 --from 2023-05-15

THE DATA
  Direct from Kite (fetch): needs a Kite Connect app with historical-data access. Set
  KITE_API_KEY and KITE_API_SECRET as environment variables (never in a file you share), run
  kite-login, log in, copy request_token from the address you land on, run kite-token. The
  access token lasts the trading day and is kept in trader/backtest/.kite_token (trader/ is
  git-ignored). fetch then downloads the 5-minute candles in 90-day windows, about 3 requests a
  second, and merges them.
  Through Claude's Kite connector (fetch-plan): fine for a few months; 5 years is about 90,000
  candles per index, too much to pass through a chat, so use fetch for that.
  Index bars: Kite's get_historical_data, interval 5minute, for the index's instrument token
  (NIFTY 50 256265 on NSE, SENSEX 265 on BSE; confirm with Kite search_instruments). Kite
  serves 5-minute candles in windows of up to 100 days, so 5 years is about 19 calls per index;
  fetch-plan lists them. Save each answer as JSON under trader/backtest/raw/, then merge.
  Volatility: India VIX daily closes (Kite token 264969, interval day, or Yahoo ^INDIAVIX).
  Merge also reads Yahoo chart JSON and CSV (date,time,open,high,low,close or datetime,...).

THE RULES (the same as nse-entry, nse-fno-plan and nse-risk)
  1. Opening range: the 9:15, 9:20 and 9:25 bars. A day without all three is skipped.
  2. Signal: the first 5-minute bar after the range to CLOSE above its high (buy a call) or
     below its low (buy a put); --sides up / down / both. One trade a day. No entry after 14:45,
     and none after 13:00 in a contract that expires that day (nse-risk's cutoff).
  3. Index stop: the range midpoint. Index target: --target-r (2) times the index risk.
  4. Option: the nearest weekly expiry ON THAT DATE (NIFTY: Thursday until 31 Aug 2025, Tuesday
     after; SENSEX weeklies from 15 May 2023: Friday, Tuesday from 1 Jan 2025, Thursday from
     1 Sep 2025; a non-trading day moves it to the trading day before, read from the data), the
     strike whose delta is nearest --strike-delta (0.55), entry, stop trigger, SL limit and target
     premiums exactly as nse-fno-plan sets them.
  5. Then bar by bar: the stop is checked before the target inside a bar (the conservative call);
     a bar that gaps through the stop fills at the gapped premium; out at 15:10 either way.

WHAT IS MODELLED, NOT MEASURED (read this before trusting a number)
  Historical prices of expired options are not freely available, so every option premium is
  Black-Scholes on the real index bar, with that day's implied volatility taken as the PREVIOUS
  day's India VIX close (x --iv-scale) held flat through the day, and the real time to expiry.
  Real premiums carry a skew, a different weekly IV, and IV that moves intraday, so treat the
  option results as an estimate. The index-points result (the same signal, stop and target on the
  index itself) uses only real bars and is the cleaner test of the signal.
  Fills: --slippage-pct (0.5%) of the premium against you on entry and on every exit. Costs:
  today's Zerodha option charges (STT 0.15% of the sell premium from April 2026, which is higher
  than it was in earlier years, so older years are charged more than they really were). Rupees
  use TODAY's lot size (NIFTY 65, SENSEX 20) x --lots throughout, so years compare like for like.

Output: trades, win rate, average R, profit factor, net rupees, max drawdown, the longest losing
streak, and the same by year, by direction and for expiry days; --write saves
trader/backtest/<INDEX>-report.json and <INDEX>-trades.csv. Past results do not predict future ones.
"""

import argparse
import bisect
import hashlib
import csv
import datetime
import glob
import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "nse-fno-chain"))
import fno_core as F  # noqa: E402

TOKENS = {"NIFTY": 256265, "SENSEX": 265, "VIX": 264969}
SPOT_KEYS = {"NIFTY": "NSE:NIFTY 50", "SENSEX": "BSE:SENSEX", "VIX": "NSE:INDIA VIX"}
OPEN_MIN, LAST_ENTRY, FLAT = 9 * 60 + 15, 14 * 60 + 45, 15 * 60 + 10
EXPIRY_CUTOFF = 13 * 60
RATE = 0.065
OUT = os.path.join("trader", "backtest")


class BTError(Exception):
    pass


# ---------------------------------------------------------------- expiry history

def weekly_weekday(idx, d):
    """The weekday (0=Mon) a weekly contract expiring on or near date d expired on, or None."""
    if idx == "NIFTY":
        return 3 if d < datetime.date(2025, 9, 1) else 1
    if d < datetime.date(2023, 5, 15):
        return None                                  # no SENSEX weeklies before May 2023
    if d < datetime.date(2025, 1, 1):
        return 4
    if d < datetime.date(2025, 9, 1):
        return 1
    return 3


def nearest_expiry(idx, d, trading_days, last_day):
    """The nearest weekly expiry on or after d. A scheduled day that is not a trading day in the
    data moves to the trading day before it (beyond the data, the built-in 2026 holidays)."""
    for k in range(0, 12):
        sched = d + datetime.timedelta(days=k)
        wd = weekly_weekday(idx, sched)
        if wd is None:
            return None
        if sched.weekday() != wd:
            continue
        e = sched
        if e <= last_day:
            i = bisect.bisect_right(trading_days, e) - 1
            e = trading_days[i] if i >= 0 else e
        else:
            e = F.prev_trading_day(e)
        if e >= d:
            return e
    return None


# ---------------------------------------------------------------- data in

def _rows_from_doc(doc):
    """Kite historical JSON (list of {date, open, ...} or {"candles": [[ts, o, h, l, c, v]]}),
    or a Yahoo v8 chart -> [(datetime IST naive, o, h, l, c)]."""
    if isinstance(doc, dict) and "data" in doc and not isinstance(doc.get("chart"), dict):
        doc = doc["data"]
    out = []
    if isinstance(doc, dict) and isinstance(doc.get("candles"), list):
        doc = [{"date": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4]} for c in doc["candles"]]
    if isinstance(doc, list):
        for r in doc:
            t = _parse_dt(r.get("date") or r.get("datetime") or r.get("timestamp"))
            if t is None or r.get("close") is None:
                continue
            out.append((t, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
        return out
    if isinstance(doc, dict) and isinstance(doc.get("chart"), dict):
        res = (doc["chart"].get("result") or [None])[0] or {}
        q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        for i, ts in enumerate(res.get("timestamp") or []):
            vals = [(q.get(k) or [None] * (i + 1))[i] if i < len(q.get(k) or []) else None
                    for k in ("open", "high", "low", "close")]
            if ts is None or None in vals:
                continue
            t = datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=int(ts)) + F.IST
            out.append((t,) + tuple(float(v) for v in vals))
        return out
    raise BTError("not a Kite historical or Yahoo chart answer")


def _parse_dt(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=int(v)) + F.IST
    s = str(v).strip().replace("Z", "+00:00")
    if len(s) > 5 and s[-5] in "+-" and s[-4:].isdigit():
        s = s[:-2] + ":" + s[-2:]                     # Kite's +0530 -> +05:30 (older Pythons need the colon)
    try:
        t = datetime.datetime.fromisoformat(s)
    except ValueError:
        try:
            t = datetime.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if t.tzinfo is not None:
        t = (t - t.utcoffset()).replace(tzinfo=None) + F.IST
    return t


def _rows_from_csv(text):
    rd = csv.reader(io.StringIO(text))
    hdr = [h.strip().lower() for h in next(rd)]
    ix = {k: hdr.index(k) for k in hdr}
    out = []
    for r in rd:
        if not r:
            continue
        if "datetime" in ix:
            t = _parse_dt(r[ix["datetime"]])
        else:
            t = _parse_dt("%s %s" % (r[ix["date"]], r[ix["time"]] if "time" in ix else "00:00:00"))
        if t is None:
            continue
        out.append((t, float(r[ix["open"]]), float(r[ix["high"]]), float(r[ix["low"]]), float(r[ix["close"]])))
    return out


def read_rows(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if text.lstrip().startswith(("{", "[")):
        return _rows_from_doc(json.loads(text))
    return _rows_from_csv(text)


def write_csv(path, rows, daily=False):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "time", "open", "high", "low", "close"])
        for t, o, h, l, c in rows:
            w.writerow([t.date().isoformat(), "00:00" if daily else t.strftime("%H:%M"), o, h, l, c])


def load_bars(path):
    """{date: [(minute_of_day, o, h, l, c)]} of 5-minute bars inside 9:15-15:30."""
    days = {}
    for t, o, h, l, c in read_rows(path):
        m = t.hour * 60 + t.minute
        if m < OPEN_MIN or m >= 15 * 60 + 30 or (m - OPEN_MIN) % 5:
            continue
        days.setdefault(t.date(), {})[m] = (m, o, h, l, c)
    return {d: [v[k] for k in sorted(v)] for d, v in days.items()}


def load_vix(path):
    return {t.date(): c for t, o, h, l, c in read_rows(path)}


# ---------------------------------------------------------------- one day

def years_left(day, minute, expiry):
    now = datetime.datetime.combine(day, datetime.time(minute // 60, minute % 60))
    end = datetime.datetime.combine(expiry, datetime.time(15, 30))
    return max((end - now).total_seconds(), 60.0) / (365.0 * 86400.0)


def pick_strike(right, spot, t, vol, step, want):
    a = F.atm(spot, step)
    best = None
    for i in range(-10, 11):
        k = a + i * step
        d = abs(F.greeks(right, spot, k, t, RATE, vol)["delta"])
        score = (abs(d - want), abs(k - a))
        if best is None or score < best[0]:
            best = (score, k)
    return best[1]


def simulate_day(idx, day, bars, expiry, vol, a):
    """One day under the rules. Returns a trade dict, or (None, reason)."""
    s = F.spec(idx)
    by = {b[0]: b for b in bars}
    rng = [by.get(OPEN_MIN + 5 * i) for i in range(3)]
    if None in rng:
        return None, "incomplete opening range"
    orh, orl = max(b[2] for b in rng), min(b[3] for b in rng)
    mid = (orh + orl) / 2
    sig = None
    for b in bars:
        m = b[0]
        close_min = m + 5
        if m < OPEN_MIN + 15:
            continue
        if close_min > LAST_ENTRY:
            break
        if a.sides in ("both", "up") and b[4] > orh:
            sig = ("up", b)
            break
        if a.sides in ("both", "down") and b[4] < orl:
            sig = ("down", b)
            break
    if not sig:
        return None, "no breakout by 14:45"
    direction, bar = sig
    entry_min = bar[0] + 5
    if expiry == day and entry_min >= EXPIRY_CUTOFF:
        return None, "expiry-day cutoff (13:00)"
    right = "CE" if direction == "up" else "PE"
    ie, istop = bar[4], mid
    risk = abs(ie - istop)
    if risk <= 0:
        return None, "zero index risk"
    itarget = ie + (1 if direction == "up" else -1) * a.target_r * risk
    t0 = years_left(day, entry_min, expiry)
    k = pick_strike(right, ie, t0, vol, s["step"], a.strike_delta)
    price = lambda spot, t: F.bs_price(right, spot, k, t, RATE, vol)
    slip = a.slippage_pct / 100.0
    entry = F.ceil_tick(price(ie, t0) * (1 + slip))
    stop = max(F.TICK, F.floor_tick(price(istop, t0)))
    target = F.round_tick(price(itarget, t0))
    if stop >= entry or target <= entry:
        return None, "premium stop/target not around the entry"
    gap_pts = min(stop * 0.02, 0.25 * (entry - stop))
    sl_limit = max(F.TICK, F.floor_tick(stop - max(F.TICK, gap_pts)))
    exit_px, why, exit_min = None, None, None
    # index-only baseline: the same levels on the index
    i_exit, i_why = None, None
    for b in bars:
        m, o, h, l, c = b
        if m < entry_min:
            continue
        t = years_left(day, m + 5, expiry)
        adverse, fav = (l, h) if direction == "up" else (h, l)
        if i_exit is None:
            if (direction == "up" and l <= istop) or (direction == "down" and h >= istop):
                i_exit, i_why = (o if (direction == "up" and o < istop) or (direction == "down" and o > istop) else istop), "stop"
            elif (direction == "up" and h >= itarget) or (direction == "down" and l <= itarget):
                i_exit, i_why = itarget, "target"
        if exit_px is None:
            p_open, p_adv, p_fav = price(o, t), price(adverse, t), price(fav, t)
            if p_open <= stop:
                exit_px, why = p_open * (1 - slip), "stop (gap)"
            elif p_adv <= stop:
                exit_px, why = max(sl_limit, stop * (1 - slip)), "stop"
            elif p_fav >= target:
                exit_px, why = target, "target"
            if exit_px is not None:
                exit_min = m + 5
        if m + 5 >= FLAT:
            if exit_px is None:
                exit_px, why, exit_min = price(c, t) * (1 - slip), "time 15:10", m + 5
            if i_exit is None:
                i_exit, i_why = c, "time 15:10"
            break
        if exit_px is not None and i_exit is not None:
            break
    if exit_px is None:            # data ended early that day
        last = bars[-1]
        exit_px, why, exit_min = price(last[4], years_left(day, last[0] + 5, expiry)) * (1 - slip), "last bar", last[0] + 5
        if i_exit is None:
            i_exit, i_why = last[4], "last bar"
    exit_px = max(0.0, exit_px)
    qty = s["lot"] * a.lots
    costs = F.option_round_trip(qty, entry, max(exit_px, F.TICK), s["exchange"])
    per_unit = exit_px - entry
    risk_unit = entry - sl_limit
    pts = (i_exit - ie) if direction == "up" else (ie - i_exit)
    return {
        "date": day.isoformat(), "year": day.year, "weekday": day.strftime("%a"), "direction": direction,
        "entry_time": "%02d:%02d" % divmod(entry_min, 60), "exit_time": "%02d:%02d" % divmod(exit_min, 60),
        "expiry": expiry.isoformat(), "expiry_day": expiry == day, "days_to_expiry": (expiry - day).days,
        "vix": round(vol * 100 / a.iv_scale, 2), "index_entry": round(ie, 2), "index_stop": round(istop, 2),
        "index_target": round(itarget, 2), "strike": k, "right": right, "entry": entry, "stop": stop,
        "sl_limit": sl_limit, "target": target, "exit": round(exit_px, 2), "exit_why": why,
        "r": round(per_unit / risk_unit, 3) if risk_unit > 0 else 0.0,
        "pnl": round(per_unit * qty - costs, 2), "costs": costs, "qty": qty,
        "index_points": round(pts, 2), "index_r": round(pts / risk, 3), "index_exit_why": i_why,
    }, None


# ---------------------------------------------------------------- stats

def stats(trades):
    n = len(trades)
    if not n:
        return {"trades": 0}
    pnl = [t["pnl"] for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    eq, peak, dd, streak, worst = 0.0, 0.0, 0.0, 0, 0
    for p in pnl:
        eq += p
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
        streak = streak + 1 if p <= 0 else 0
        worst = max(worst, streak)
    ir = [t["index_r"] for t in trades]
    return {"trades": n, "win_rate": round(len(wins) / n, 4), "avg_r": round(sum(t["r"] for t in trades) / n, 3),
            "net": round(sum(pnl), 2), "avg_pnl": round(sum(pnl) / n, 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "max_drawdown": round(dd, 2), "longest_losing_streak": worst,
            "costs": round(sum(t["costs"] for t in trades), 2),
            "index_win_rate": round(sum(1 for x in ir if x > 0) / n, 4), "index_avg_r": round(sum(ir) / n, 3),
            "exits": {k: sum(1 for t in trades if t["exit_why"] == k) for k in sorted({t["exit_why"] for t in trades})}}


def run(a):
    idx = F.index_of(a.index)
    bars_path = a.bars or os.path.join(OUT, "%s-5m.csv" % idx)
    vix_path = a.vix or os.path.join(OUT, "VIX-1d.csv")
    for p, what in ((bars_path, "5-minute bars (merge first)"), (vix_path, "India VIX daily (vix first)")):
        if not os.path.isfile(p):
            raise BTError("no %s at %s" % (what, p))
    days = load_bars(bars_path)
    vix = load_vix(vix_path)
    vdays = sorted(vix)
    tdays = sorted(days)
    if not tdays:
        raise BTError("no 5-minute bars between 9:15 and 15:30 in %s" % bars_path)
    lo = datetime.date.fromisoformat(a.date_from) if a.date_from else tdays[0]
    hi = datetime.date.fromisoformat(a.date_to) if a.date_to else tdays[-1]
    trades, skipped = [], {}
    for d in tdays:
        if not lo <= d <= hi:
            continue
        i = bisect.bisect_left(vdays, d) - 1             # the PREVIOUS day's VIX: known at the open
        if i < 0:
            skipped["no prior India VIX"] = skipped.get("no prior India VIX", 0) + 1
            continue
        vol = vix[vdays[i]] / 100.0 * a.iv_scale
        exp = nearest_expiry(idx, d, tdays, tdays[-1])
        if exp is None:
            skipped["no weekly contract then"] = skipped.get("no weekly contract then", 0) + 1
            continue
        t, why = simulate_day(idx, d, days[d], exp, vol, a)
        if t:
            trades.append(t)
        else:
            skipped[why] = skipped.get(why, 0) + 1
    by_year = {y: stats([t for t in trades if t["year"] == y]) for y in sorted({t["year"] for t in trades})}
    by_dir = {k: stats([t for t in trades if t["direction"] == k]) for k in ("up", "down")}
    exp_day = {"expiry day": stats([t for t in trades if t["expiry_day"]]),
               "other days": stats([t for t in trades if not t["expiry_day"]])}
    s = F.spec(idx)
    return {"index": idx, "from": lo.isoformat(), "to": hi.isoformat(), "days": sum(1 for d in tdays if lo <= d <= hi),
            "rules": {"sides": a.sides, "target_r": a.target_r, "strike_delta": a.strike_delta, "lots": a.lots,
                      "lot_size_today": s["lot"], "slippage_pct": a.slippage_pct, "iv_scale": a.iv_scale,
                      "entry_window": "9:30-14:45", "flat_by": "15:10", "expiry_cutoff": "13:00"},
            "overall": stats(trades), "by_year": by_year, "by_direction": by_dir, "expiry": exp_day,
            "skipped": skipped, "trades": trades}


def render(r):
    o = r["overall"]
    out = ["%s option ORB backtest, %s to %s: %d trading days, %d trades (lots: %d x %d today's lot)."
           % (r["index"], r["from"], r["to"], r["days"], o.get("trades", 0), r["rules"]["lots"],
              r["rules"]["lot_size_today"])]
    if not o.get("trades"):
        out.append("No trades.")
        return "\n".join(out)
    out.append("Rules: %s, target %gx index risk, strike delta %.2f, slippage %.1f%%, IV = prior-day India VIX x %g."
               % (r["rules"]["sides"], r["rules"]["target_r"], r["rules"]["strike_delta"], r["rules"]["slippage_pct"],
                  r["rules"]["iv_scale"]))
    out.append("")
    hdr = "%-12s %6s %6s %7s %13s %11s %12s %6s | %6s %7s" % (
        "", "trades", "win%", "avg R", "net ₹", "avg ₹", "max DD ₹", "PF", "idx w%", "idx R")
    out.append(hdr)

    def line(name, x):
        if not x.get("trades"):
            return "%-12s %6d" % (name, 0)
        return "%-12s %6d %5.1f%% %+7.3f %13s %11s %12s %6s | %5.1f%% %+7.3f" % (
            name, x["trades"], 100 * x["win_rate"], x["avg_r"], "{:,.0f}".format(x["net"]),
            "{:,.0f}".format(x["avg_pnl"]), "{:,.0f}".format(x["max_drawdown"]),
            "-" if x["profit_factor"] is None else "%.2f" % x["profit_factor"],
            100 * x["index_win_rate"], x["index_avg_r"])
    out.append(line("ALL", o))
    for y, x in r["by_year"].items():
        out.append(line(str(y), x))
    for k, x in r["by_direction"].items():
        out.append(line("calls" if k == "up" else "puts", x))
    for k, x in r["expiry"].items():
        out.append(line(k, x))
    out.append("")
    out.append("Exits: %s. Costs paid: ₹%s. Longest losing streak: %d trades."
               % (", ".join("%s %d" % kv for kv in o["exits"].items()), "{:,.0f}".format(o["costs"]),
                  o["longest_losing_streak"]))
    if r["skipped"]:
        out.append("Days without a trade: %s." % ", ".join("%s %d" % kv for kv in sorted(r["skipped"].items(),
                                                                                      key=lambda kv: -kv[1])))
    out.append("idx = the same signal, stop and target traded on the index in points: real bars only, no model.")
    out.append("Option premiums are Black-Scholes estimates from India VIX (no historical option prices); costs at "
               "today's rates; rupees at today's lot size. Past results do not predict future ones. Not advice.")
    return "\n".join(out)


# ---------------------------------------------------------------- Kite Connect (direct)

KITE_API = os.environ.get("KITE_API_URL", "https://api.kite.trade")    # override only for tests
TOKEN_FILE = os.path.join(OUT, ".kite_token")


def _env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        raise BTError("set the %s environment variable first (Windows: set %s=...; macOS/Linux: export %s=...)"
                      % (name, name, name))
    return v


def kite_get(path, api_key, token):
    req = urllib.request.Request(KITE_API + path, headers={"X-Kite-Version": "3",
                                                           "Authorization": "token %s:%s" % (api_key, token)})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code == 429 and attempt < 3:
                time.sleep(2 + 2 * attempt)
                continue
            if e.code == 403:
                raise BTError("Kite refused the request (403): the access token has expired (they last one trading "
                              "day) or the app has no historical-data access. Run kite-login again. %s" % body)
            raise BTError("Kite answered HTTP %d: %s" % (e.code, body))
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(2)
                continue
            raise BTError("could not reach Kite: %s" % e.reason)
    raise BTError("Kite kept rate-limiting the requests")


def cmd_kite_login(a):
    key = _env("KITE_API_KEY")
    print("Open this in your browser, log in to Kite, and copy request_token=... from the address you land on:")
    print("  https://kite.zerodha.com/connect/login?v=3&api_key=%s" % urllib.parse.quote(key))
    print("Then: backtest.py kite-token REQUEST_TOKEN")
    return 0


def cmd_kite_token(a):
    key, secret = _env("KITE_API_KEY"), _env("KITE_API_SECRET")
    checksum = hashlib.sha256((key + a.request_token + secret).encode("utf-8")).hexdigest()
    body = urllib.parse.urlencode({"api_key": key, "request_token": a.request_token, "checksum": checksum}).encode()
    req = urllib.request.Request(KITE_API + "/session/token", data=body, headers={"X-Kite-Version": "3"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            doc = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise BTError("Kite did not accept the request token (HTTP %d): it is single-use and expires in minutes; "
                      "run kite-login again. %s" % (e.code, e.read().decode("utf-8", "replace")[:200]))
    tok = (doc.get("data") or {}).get("access_token")
    if not tok:
        raise BTError("no access token in Kite's answer")
    os.makedirs(OUT, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
        fh.write(tok)
    print("Saved today's access token to %s (it expires the next morning; keep this folder private)." % TOKEN_FILE)
    return 0


def _token():
    if os.environ.get("KITE_ACCESS_TOKEN"):
        return os.environ["KITE_ACCESS_TOKEN"].strip()
    if os.path.isfile(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    raise BTError("no Kite access token: run kite-login, then kite-token (or set KITE_ACCESS_TOKEN)")


def cmd_fetch(a):
    idx = F.index_of(a.index)
    key, tok = _env("KITE_API_KEY"), _token()
    to = datetime.date.fromisoformat(a.to) if a.to else (datetime.datetime.now(datetime.timezone.utc) + F.IST).date()
    start = to - datetime.timedelta(days=int(365.25 * a.years))
    raw = os.path.join(OUT, "raw")
    os.makedirs(raw, exist_ok=True)
    d, files, n = start, [], 0
    while d <= to:
        e = min(to, d + datetime.timedelta(days=89))
        path = os.path.join(raw, "%s-%s.json" % (idx, d.isoformat()))
        if not (os.path.isfile(path) and e < to):            # completed windows are kept; the latest is refreshed
            q = urllib.parse.urlencode({"from": "%s 09:15:00" % d, "to": "%s 15:30:00" % e})
            doc = kite_get("/instruments/historical/%d/5minute?%s" % (TOKENS[idx], q), key, tok)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            n += 1
            print("  %s to %s: %d candles" % (d, e, len(((doc.get("data") or {}).get("candles")) or [])))
            time.sleep(0.4)
        files.append(path)
        d = e + datetime.timedelta(days=1)
    print("Downloaded %d window%s from Kite." % (n, "" if n == 1 else "s"))
    return cmd_merge(argparse.Namespace(index=idx, files=files, out=None))


def cmd_fetch_vix(a):
    raw = os.path.join(OUT, "raw")
    os.makedirs(raw, exist_ok=True)
    path = os.path.join(raw, "VIX-day.json")
    if a.kite:
        key, tok = _env("KITE_API_KEY"), _token()
        to = (datetime.datetime.now(datetime.timezone.utc) + F.IST).date()
        start = to - datetime.timedelta(days=int(365.25 * a.years))
        q = urllib.parse.urlencode({"from": "%s 00:00:00" % start, "to": "%s 23:59:59" % to})
        doc = kite_get("/instruments/historical/%d/day?%s" % (TOKENS["VIX"], q), key, tok)
    else:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/%5EINDIAVIX?range=10y&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; nse-day-trader-skill/1.0)"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                doc = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError) as e:
            raise BTError("could not download India VIX from Yahoo (%s); try --kite" % getattr(e, "reason", e))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return cmd_vix(argparse.Namespace(files=[path], out=None))


# ---------------------------------------------------------------- commands

def cmd_fetch_plan(a):
    idx = "VIX" if a.index.upper() in ("VIX", "INDIAVIX", "INDIA VIX") else F.index_of(a.index)
    to = datetime.date.fromisoformat(a.to) if a.to else (datetime.datetime.now(datetime.timezone.utc) + F.IST).date()
    start = to - datetime.timedelta(days=int(365.25 * a.years))
    calls = []
    if idx == "VIX":
        calls.append({"instrument_token": TOKENS["VIX"], "from_date": "%s 00:00:00" % start,
                      "to_date": "%s 23:59:59" % to, "interval": "day", "save_as": "trader/backtest/raw/VIX-day.json"})
    else:
        d = start
        while d <= to:
            e = min(to, d + datetime.timedelta(days=a.chunk_days - 1))
            calls.append({"instrument_token": TOKENS[idx], "from_date": "%s 09:15:00" % d,
                          "to_date": "%s 15:30:00" % e, "interval": "5minute",
                          "save_as": "trader/backtest/raw/%s-%s.json" % (idx, d.isoformat())})
            d = e + datetime.timedelta(days=1)
    print(json.dumps({"index": idx, "instrument": SPOT_KEYS[idx], "token": TOKENS[idx],
                      "note": "confirm the token with Kite search_instruments (%s) before fetching" % SPOT_KEYS[idx],
                      "calls": calls}, indent=2))
    print("%d Kite get_historical_data calls. Save each answer exactly as returned to its save_as path, then: "
          "backtest.py %s" % (len(calls), "vix trader/backtest/raw/VIX-day.json" if idx == "VIX"
                              else "merge --index %s trader/backtest/raw/%s-*.json" % (idx, idx)), file=sys.stderr)
    return 0


def cmd_merge(a):
    idx = F.index_of(a.index)
    rows = {}
    files = []
    for pat in a.files:
        files += sorted(glob.glob(pat)) or [pat]
    for f in files:
        for r in read_rows(f):
            rows[r[0]] = r
    if not rows:
        raise BTError("no bars in %s" % ", ".join(files))
    out = a.out or os.path.join(OUT, "%s-5m.csv" % idx)
    data = [rows[k] for k in sorted(rows)]
    write_csv(out, data)
    days = sorted({r[0].date() for r in data})
    print("Merged %d files: %s bars on %d days, %s to %s -> %s"
          % (len(files), "{:,}".format(len(data)), len(days), days[0], days[-1], out))
    gaps = [(x, y) for x, y in zip(days, days[1:]) if (y - x).days > 6]
    if gaps:
        print("note: gaps over 6 days: %s" % ", ".join("%s..%s" % g for g in gaps[:5]))
    return 0


def cmd_vix(a):
    rows = []
    for pat in a.files:
        for f in sorted(glob.glob(pat)) or [pat]:
            rows += read_rows(f)
    if not rows:
        raise BTError("no India VIX rows")
    by = {r[0].date(): r for r in rows}
    out = a.out or os.path.join(OUT, "VIX-1d.csv")
    write_csv(out, [by[k] for k in sorted(by)], daily=True)
    print("India VIX: %d days, %s to %s -> %s" % (len(by), min(by), max(by), out))
    return 0


def cmd_run(a):
    r = run(a)
    if a.write is not None:
        os.makedirs(OUT, exist_ok=True)
        base = os.path.join(OUT, "%s" % r["index"])
        with open(base + "-report.json", "w", encoding="utf-8") as fh:
            json.dump({k: v for k, v in r.items() if k != "trades"}, fh, indent=2, ensure_ascii=False)
        with open(base + "-trades.csv", "w", encoding="utf-8", newline="") as fh:
            if r["trades"]:
                w = csv.DictWriter(fh, fieldnames=list(r["trades"][0].keys()))
                w.writeheader()
                w.writerows(r["trades"])
    print(json.dumps({k: v for k, v in r.items() if k != "trades"}, indent=2) if a.json else render(r))
    if a.write is not None and not a.json:
        print("Wrote %s-report.json and %s-trades.csv." % (base, base))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("kite-login", help="print the Kite login URL (needs KITE_API_KEY)")
    p = sub.add_parser("kite-token", help="exchange the request_token for today's access token")
    p.add_argument("request_token")
    p = sub.add_parser("fetch", help="download 5-minute index bars from Kite and merge them")
    p.add_argument("--index", required=True)
    p.add_argument("--years", type=float, default=5)
    p.add_argument("--to", help="YYYY-MM-DD (default today)")
    p = sub.add_parser("fetch-vix", help="download India VIX daily closes (Yahoo; --kite for Kite)")
    p.add_argument("--kite", action="store_true")
    p.add_argument("--years", type=float, default=6)
    p = sub.add_parser("fetch-plan", help="list the Kite historical calls for an index or India VIX")
    p.add_argument("--index", required=True, help="NIFTY, SENSEX or VIX")
    p.add_argument("--years", type=float, default=5)
    p.add_argument("--to", help="YYYY-MM-DD (default today)")
    p.add_argument("--chunk-days", type=int, default=90, help="days per 5-minute call (Kite allows up to 100)")
    p = sub.add_parser("merge", help="merge saved 5-minute answers into one CSV")
    p.add_argument("--index", required=True)
    p.add_argument("files", nargs="+")
    p.add_argument("--out")
    p = sub.add_parser("vix", help="save India VIX daily closes as CSV")
    p.add_argument("files", nargs="+")
    p.add_argument("--out")
    p = sub.add_parser("run", help="run the backtest")
    p.add_argument("--index", required=True)
    p.add_argument("--bars", help="5-minute CSV (default trader/backtest/<INDEX>-5m.csv)")
    p.add_argument("--vix", help="India VIX daily CSV (default trader/backtest/VIX-1d.csv)")
    p.add_argument("--from", dest="date_from")
    p.add_argument("--to", dest="date_to")
    p.add_argument("--sides", choices=("both", "up", "down"), default="both")
    p.add_argument("--target-r", type=float, default=2.0)
    p.add_argument("--strike-delta", type=float, default=0.55)
    p.add_argument("--lots", type=int, default=1)
    p.add_argument("--slippage-pct", type=float, default=0.5)
    p.add_argument("--iv-scale", type=float, default=1.0, help="weekly IV / India VIX (1.0)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", nargs="?", const="")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"fetch-plan": cmd_fetch_plan, "merge": cmd_merge, "vix": cmd_vix, "run": cmd_run,
                "kite-login": cmd_kite_login, "kite-token": cmd_kite_token, "fetch": cmd_fetch,
                "fetch-vix": cmd_fetch_vix}[a.cmd](a)
    except (BTError, F.FnoError, ValueError, OSError) as e:
        print("backtest.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):      # Windows pipes default to cp1252
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
