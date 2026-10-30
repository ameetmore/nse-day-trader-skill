#!/usr/bin/env python3
"""Option chain for nse-fno-chain: NIFTY 50 and SENSEX index options. Standard library only.

    python3 chain.py expiries NIFTY                    # the next weekly expiries, holiday-shifted
    python3 chain.py symbols NIFTY --spot 25812        # the Kite instruments to quote, ATM +- 10 strikes
    python3 chain.py symbols SENSEX --spot 84210 --expiry 2026-11-05 --width 8
    python3 chain.py analyse NIFTY --quotes trader/fno/quotes-NIFTY.json --spot 25812
    python3 chain.py analyse NIFTY --quotes FILE --spot 25812 --now "2026-11-03 10:20" --json

This tool never connects to the broker. Claude gets the prices with Zerodha's Kite MCP
server: `symbols` prints the instrument list, Claude passes it to Kite's get_quotes (and the
spot from "NSE:NIFTY 50" or "BSE:SENSEX"), saves Kite's answer to a file, and `analyse`
reads that file. Kite's search_instruments output can be saved and given with
--instruments: then symbols, lot size and expiry come from Kite itself.

analyse prints, for the expiry:
  per strike   call and put: last price, bid/ask spread %, open interest, volume, implied
               volatility (Black-Scholes from the mid price), delta, theta (rupees a day)
  ATM          the strike nearest the spot; the ATM straddle (call + put) and the move it
               implies by expiry (about 0.8 x the straddle is the one-standard-deviation move)
  PCR          put open interest / call open interest, over the strikes quoted
  max pain     the expiry price at which option buyers, in total, would be paid the least
  OI walls     the strikes with the most call OI (often read as resistance) and put OI (support)
  liquidity    a strike whose spread is over --max-spread-pct (default 2%) is flagged

Readings, not signals: open interest says where positions are, not which way they face, and
max pain is not a forecast. Writes trader/fno/chain-<INDEX>.json for nse-fno-plan.
"""

import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fno_core as F  # noqa: E402

RATE = 0.065    # risk-free rate for Black-Scholes (about the 91-day T-bill)


def parse_now(text):
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)
    t = text.strip().replace("Z", "+00:00")
    dt = datetime.datetime.fromisoformat(t)
    if dt.tzinfo is None:
        return dt - F.IST
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def today_ist(now_utc):
    return (now_utc + F.IST).date()


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_config(path):
    if path and os.path.isfile(path):
        return load_json(path)
    return {}


# ---------------------------------------------------------------- Kite data

def quotes_map(doc):
    """Kite get_quotes answer -> {"EXCH:SYMBOL": quote}. Accepts {"data": {...}} or the map itself,
    or a list of quotes that carry "instrument"/"tradingsymbol"."""
    if isinstance(doc, dict) and isinstance(doc.get("data"), dict):
        doc = doc["data"]
    if isinstance(doc, list):
        out = {}
        for q in doc:
            key = q.get("instrument") or ("%s:%s" % (q.get("exchange", ""), q.get("tradingsymbol", "")))
            out[key] = q
        return out
    if not isinstance(doc, dict):
        raise F.FnoError("the quotes file is not a Kite get_quotes answer")
    return doc


def instruments_list(doc):
    if isinstance(doc, dict) and isinstance(doc.get("data"), list):
        doc = doc["data"]
    return doc if isinstance(doc, list) else []


SYM_RX = re.compile(r"^(NIFTY|SENSEX)(\d{2})(?:([1-9OND])(\d{2})|(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC))"
                    r"(\d+(?:\.\d+)?)(CE|PE)$")


def parse_symbol(sym, idx=None):
    """'NIFTY26N0925800CE' -> (index, expiry date or (year, month) for a monthly, strike, right)."""
    m = SYM_RX.match(sym.split(":")[-1])
    if not m:
        return None
    ix, yy, mcode, dd, mon, strike, right = m.groups()
    year = 2000 + int(yy)
    if mcode:
        month = {"O": 10, "N": 11, "D": 12}.get(mcode) or int(mcode)
        exp = datetime.date(year, month, int(dd))
    else:
        month = F.MONTHS.index(mon) + 1
        exp = F.prev_trading_day(F._last_weekday(year, month, F.INDICES[ix]["weekday"]))
    return ix, exp, float(strike), right


def build_chain(idx, quotes, spot, now_utc, expiry=None, instruments=None, max_spread=2.0, r=RATE):
    rows = {}
    meta = {}
    if instruments:
        for ins in instruments:
            meta[ins.get("tradingsymbol")] = ins
    for key, q in quotes.items():
        sym = key.split(":")[-1]
        info = None
        if sym in meta and meta[sym].get("strike") is not None:
            ins = meta[sym]
            try:
                exp = datetime.date.fromisoformat(str(ins.get("expiry"))[:10])
            except ValueError:
                continue
            info = (idx, exp, float(ins["strike"]), ins.get("instrument_type"))
        else:
            info = parse_symbol(sym)
        if not info or info[0] != idx or info[3] not in ("CE", "PE"):
            continue
        _, exp, strike, right = info
        if expiry and exp != expiry:
            continue
        rows.setdefault(exp, {}).setdefault(strike, {})[right] = _leg(sym, q, right, spot, strike, exp, now_utc, r,
                                                                       max_spread)
    if not rows:
        raise F.FnoError("no %s option quotes%s in the file" % (idx, (" for %s" % expiry) if expiry else ""))
    exp = expiry or min(rows)
    return exp, rows[exp]


def _leg(sym, q, right, spot, strike, exp, now_utc, r, max_spread):
    ltp = q.get("last_price")
    depth = q.get("depth") or {}
    bid = next((x.get("price") for x in (depth.get("buy") or []) if x.get("price")), None)
    ask = next((x.get("price") for x in (depth.get("sell") or []) if x.get("price")), None)
    mid = (bid + ask) / 2 if bid and ask else ltp
    spread = (100.0 * (ask - bid) / mid) if bid and ask and mid else None
    t = F.years_to_expiry(now_utc, exp)
    iv = F.implied_vol(right, mid, spot, strike, t, r) if mid else None
    if iv is not None and iv < 0.01:
        iv = None          # a price at intrinsic value says nothing about volatility
    g = F.greeks(right, spot, strike, t, r, iv) if iv else None
    return {"symbol": sym, "ltp": ltp, "bid": bid, "ask": ask, "mid": mid,
            "spread_pct": round(spread, 2) if spread is not None else None,
            "illiquid": spread is None or spread > max_spread,
            "oi": int(q.get("oi") or 0), "volume": int(q.get("volume") or 0),
            "iv": round(100 * iv, 2) if iv else None,
            "delta": round(g["delta"], 3) if g else None, "theta": round(g["theta"], 2) if g else None,
            "gamma": round(g["gamma"], 6) if g else None, "vega": round(g["vega"], 2) if g else None}


def analyse(idx, chain, spot, exp, now_utc, step):
    strikes = sorted(chain)
    a = F.atm(spot, step)
    if a not in chain:
        a = min(strikes, key=lambda k: abs(k - spot))
    ce_oi = {k: (chain[k].get("CE") or {}).get("oi", 0) for k in strikes}
    pe_oi = {k: (chain[k].get("PE") or {}).get("oi", 0) for k in strikes}
    tce, tpe = sum(ce_oi.values()), sum(pe_oi.values())
    pain = None
    if tce or tpe:
        pain = min(strikes, key=lambda x: sum(ce_oi[k] * max(0, x - k) + pe_oi[k] * max(0, k - x) for k in strikes))
    straddle = None
    c, p = chain[a].get("CE") or {}, chain[a].get("PE") or {}
    if c.get("mid") and p.get("mid"):
        straddle = round(c["mid"] + p["mid"], 2)
    ivs = [x.get("iv") for k in (a,) for x in (c, p) if x.get("iv")]
    t_days = F.years_to_expiry(now_utc, exp) * 365
    return {"index": idx, "expiry": exp.isoformat(), "monthly": F.is_monthly(idx, exp), "spot": spot, "atm": a,
            "days_to_expiry": round(t_days, 2), "expiry_today": exp == today_ist(now_utc),
            "straddle": straddle, "implied_move": round(0.8 * straddle, 1) if straddle else None,
            "implied_move_pct": round(80.0 * straddle / spot, 2) if straddle else None,
            "atm_iv": round(sum(ivs) / len(ivs), 2) if ivs else None,
            "pcr": round(tpe / tce, 2) if tce else None, "max_pain": pain,
            "call_wall": max(strikes, key=lambda k: ce_oi[k]) if tce else None,
            "put_wall": max(strikes, key=lambda k: pe_oi[k]) if tpe else None,
            "strikes": [{"strike": k, "CE": chain[k].get("CE"), "PE": chain[k].get("PE")} for k in strikes],
            "as_of": (now_utc + F.IST).strftime("%Y-%m-%d %H:%M IST")}


def render(res):
    out = ["%s options, expiry %s (%s%s), %.2f days left, spot %.2f, as of %s" % (
        res["index"], res["expiry"], "monthly" if res["monthly"] else "weekly",
        ", TODAY" if res["expiry_today"] else "", res["days_to_expiry"], res["spot"], res["as_of"])]
    hdr = "%8s %8s %6s %10s %6s %6s | %-7s | %6s %6s %10s %6s %8s" % (
        "CE ltp", "IV%", "delta", "OI", "sprd%", "theta", "strike", "theta", "sprd%", "OI", "delta", "PE ltp")
    out.append(hdr)
    for row in res["strikes"]:
        c, p = row["CE"] or {}, row["PE"] or {}
        f = lambda v, fmt: "-" if v is None else fmt % v
        mark = "*" if row["strike"] == res["atm"] else " "
        out.append("%8s %8s %6s %10s %6s %6s |%s%-7s| %6s %6s %10s %6s %8s" % (
            f(c.get("ltp"), "%.2f"), f(c.get("iv"), "%.1f"), f(c.get("delta"), "%.2f"),
            "-" if c.get("oi") is None else "{:,}".format(c["oi"]),
            f(c.get("spread_pct"), "%.1f") + ("!" if c.get("illiquid") else ""),
            f(c.get("theta"), "%.1f"), mark, F.strike_text(row["strike"]), f(p.get("theta"), "%.1f"),
            f(p.get("spread_pct"), "%.1f") + ("!" if p.get("illiquid") else ""),
            "-" if p.get("oi") is None else "{:,}".format(p["oi"]), f(p.get("delta"), "%.2f"), f(p.get("ltp"), "%.2f")))
    out.append("")
    if res["straddle"]:
        out.append("ATM %s straddle %.2f: the market prices about +-%.0f points (%.2f%%) by expiry; ATM IV %s%%."
                   % (F.strike_text(res["atm"]), res["straddle"], res["implied_move"], res["implied_move_pct"],
                      res["atm_iv"] if res["atm_iv"] is not None else "-"))
    if res["pcr"] is not None:
        out.append("PCR (OI) %.2f. Max pain %s. Most call OI at %s, most put OI at %s (over the strikes quoted)."
                   % (res["pcr"], F.strike_text(res["max_pain"]), F.strike_text(res["call_wall"]),
                      F.strike_text(res["put_wall"])))
    if res["expiry_today"]:
        out.append("EXPIRY DAY: option premiums can lose most of their time value within hours; a bought option "
                   "that is not in the money by 15:30 expires worthless.")
    out.append("! = spread wider than the limit (thin). Readings, not signals. Not investment advice.")
    return "\n".join(out)


# ---------------------------------------------------------------- commands

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("expiries", help="the next weekly expiries")
    p.add_argument("index")
    p.add_argument("--n", type=int, default=4)
    p.add_argument("--now")
    p = sub.add_parser("symbols", help="the Kite instruments to quote around the money")
    p.add_argument("index")
    p.add_argument("--spot", type=float, required=True)
    p.add_argument("--expiry", help="YYYY-MM-DD (default: the nearest expiry)")
    p.add_argument("--width", type=int, default=10, help="strikes each side of ATM (10)")
    p.add_argument("--now")
    p.add_argument("--config", default="trader/config.json")
    p = sub.add_parser("analyse", help="analyse a saved Kite get_quotes answer")
    p.add_argument("index")
    p.add_argument("--quotes", required=True, help="Kite get_quotes JSON saved to a file")
    p.add_argument("--spot", type=float, required=True, help="the index level now (Kite NSE:NIFTY 50 / BSE:SENSEX)")
    p.add_argument("--expiry", help="YYYY-MM-DD (default: the nearest in the file)")
    p.add_argument("--instruments", help="Kite search_instruments JSON (authoritative symbols and expiries)")
    p.add_argument("--max-spread-pct", type=float, default=2.0)
    p.add_argument("--rate", type=float, default=RATE)
    p.add_argument("--now")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--write", nargs="?", const="", help="save to trader/fno/chain-<INDEX>.json (or PATH)")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        idx = F.index_of(a.index)
        now = parse_now(a.now)
        today = today_ist(now)
        if a.cmd == "expiries":
            es = F.expiries(idx, today, a.n)
            for e in es:
                print("%s %s %s%s" % (idx, e.isoformat(), e.strftime("%a"),
                                      "  (monthly)" if F.is_monthly(idx, e) else ""))
            if not F.calendar_known(es[-1]):
                print("note: the holiday list covers %s only; check the exchange's calendar." % ", ".join(
                    str(y) for y in F.CALENDAR_YEARS))
            return 0
        s = F.spec(idx, read_config(a.config))
        exp = datetime.date.fromisoformat(a.expiry) if a.expiry else None
        if a.cmd == "symbols":
            exp = exp or F.expiries(idx, today, 1)[0]
            mid = F.atm(a.spot, s["step"])
            keys = ["%s:%s" % (s["exchange"], F.tradingsymbol(idx, exp, mid + i * s["step"], r))
                    for i in range(-a.width, a.width + 1) for r in ("CE", "PE")]
            print(json.dumps({"index": idx, "expiry": exp.isoformat(), "spot_instrument": s["kite_spot"],
                              "instruments": keys}, indent=2))
            print("Pass these to Kite get_quotes (with %s for the spot), save the answer as JSON, then run "
                  "analyse. Kite's search_instruments is the authority if a symbol is not found." % s["kite_spot"],
                  file=sys.stderr)
            return 0
        quotes = quotes_map(load_json(a.quotes))
        ins = instruments_list(load_json(a.instruments)) if a.instruments else None
        exp, chain = build_chain(idx, quotes, a.spot, now, exp, ins, a.max_spread_pct, a.rate)
        res = analyse(idx, chain, a.spot, exp, now, s["step"])
        res.update({"lot": s["lot"], "exchange": s["exchange"], "freeze": s["freeze"], "rate": a.rate})
        if a.write is not None:
            path = a.write or os.path.join("trader", "fno", "chain-%s.json" % idx)
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(res, fh, indent=2)
        print(json.dumps(res, indent=2) if a.json else render(res))
        return 0
    except (F.FnoError, ValueError, OSError) as e:
        print("chain.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):      # Windows pipes default to cp1252
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
