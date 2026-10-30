#!/usr/bin/env python3
"""Option-buying planner for nse-fno-plan: NIFTY 50 and SENSEX, intraday. Standard library only.

Turns an index signal into one bought option with its stop, target and size:

    python3 plan.py                                   # trader/entry.json (an index ORB) + trader/fno/chain-<INDEX>.json
    python3 plan.py --index NIFTY --direction up --index-entry 25793 --index-stop 25781 --target-r 2
    python3 plan.py --index SENSEX --direction down --index-entry 84020 --index-stop 84140 --strike atm
    python3 plan.py --strike delta:0.6 --write        # -> trader/orders.json for nse-risk and nse-broker
    python3 plan.py --now "2026-11-02 09:45" --json

The signal: up buys a call (CE), down buys a put (PE). Without flags it reads
trader/entry.json from nse-entry run on the index (^NSEI or ^BSESN), which is a long
(up) opening-range breakout; the index stop defaults to the opening range's midpoint.

The option:
  strike    delta:0.55 (default: the liquid strike whose delta is nearest 0.55, slightly in the
            money: less time decay than out of the money), atm, itm1, otm1, or a number
  expiry    the chain's (nse-fno-chain analyse --write); on the expiry day itself it warns,
            and nse-risk blocks new entries after fno.expiry_no_entries_after (13:00)
  entry     a LIMIT at the ask, up to the 0.05 tick (Zerodha blocks market orders in many
            option contracts, and a market order in a thin option can fill far away)
  stop      the premium at the index stop: Black-Scholes at the stop level with the option's
            own implied volatility, rounded down to the tick (or --stop pct:30). The exit is a
            stop-loss LIMIT order (SL): exchanges no longer take SL-M on index options. Its
            limit sits fno.sl_limit_buffer_pct (2%) under the trigger, at most a quarter of the
            stop distance, and the risk is measured to that limit, the worse fill
  target    the premium at the index target (--target-r R times the index risk, default 2, or
            --index-target), rounded to the tick
  size      whole lots: the most lots whose loss at the stop's limit plus the round-trip costs
            stays within max_loss_per_trade_inr, and within fno.max_lots, fno.max_premium_inr,
            the cash after the buffer, and the exchange's freeze quantity

Costs ("charges", Zerodha options): ₹20 an order, STT 0.15% of the sell premium, exchange
0.03553% (NSE) or 0.0325% (BSE) of premium, SEBI ₹10 a crore, stamp duty 0.003% on the buy,
GST 18% on brokerage + exchange + SEBI.

The premium at the stop is a model: implied volatility moves, and time decay keeps eating the
premium even if the index stands still. The time stop (flat_by, 15:10) closes it either way.
It never places anything. SEBI's study of FY2025-26 found 87.7% of individual F&O traders
lost money; the plan prints the numbers so the odds are visible.
"""

import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "nse-fno-chain"))
import fno_core as F  # noqa: E402

FNO_DEFAULTS = {"max_lots": 2, "max_premium_inr": 30000, "sl_limit_buffer_pct": 2.0,
                "expiry_no_entries_after": "13:00", "min_target_r": 1.5}
CFG_DEFAULTS = {"budget": None, "cash_buffer_pct": 10, "max_loss_per_trade_inr": 2500, "flat_by": "15:10",
                "min_reward_risk": 1.0}


class PlanError(Exception):
    pass


def read_json(path, required=False):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    if required:
        raise PlanError("no %s: %s" % (os.path.basename(path or "file"),
                                       "run nse-fno-chain analyse ... --write first" if "chain" in (path or "") else path))
    return None


def parse_now(text):
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)
    dt = datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return dt - F.IST if dt.tzinfo is None else (dt - dt.utcoffset()).replace(tzinfo=None)


def money(v):
    return ("-" if v < 0 else "") + "₹{:,.2f}".format(abs(v))


def pick_strike(chain, right, rule, spot, step):
    legs = [(s["strike"], s[right]) for s in chain["strikes"] if s.get(right) and s[right].get("ask")]
    liquid = [(k, l) for k, l in legs if not l.get("illiquid")]
    if not liquid:
        raise PlanError("no liquid %s strikes in the chain (all spreads over the limit)" % right)
    atm = chain["atm"]
    sign = 1 if right == "CE" else -1
    rule = str(rule).lower()
    if rule == "atm":
        want = atm
    elif rule == "itm1":
        want = atm - sign * step
    elif rule == "otm1":
        want = atm + sign * step
    elif rule.startswith("delta:"):
        d = float(rule.split(":", 1)[1])
        cand = [(k, l) for k, l in liquid if l.get("delta") is not None]
        if not cand:
            raise PlanError("no deltas in the chain (no implied volatility)")
        return min(cand, key=lambda kl: (abs(abs(kl[1]["delta"]) - d), abs(kl[0] - atm)))
    else:
        want = float(rule)
    hit = [(k, l) for k, l in liquid if k == want]
    if not hit:
        raise PlanError("strike %s %s is not in the chain or is too thin to trade" % (F.strike_text(want), right))
    return hit[0]


def plan(a, now):
    cfg = dict(CFG_DEFAULTS)
    cfg.update(read_json(a.config) or {})
    fno = dict(FNO_DEFAULTS)
    fno.update(cfg.get("fno") or {})
    entry = read_json(a.entry) or {}
    idx = F.index_of(a.index or entry.get("symbol") or "")
    s = F.spec(idx, cfg)
    chain = read_json(a.chain or os.path.join("trader", "fno", "chain-%s.json" % idx), required=True)
    if chain.get("index") != idx:
        raise PlanError("the chain file is for %s, not %s" % (chain.get("index"), idx))
    today = (now + F.IST).date()
    expiry = datetime.date.fromisoformat(chain["expiry"])
    if expiry < today:
        raise PlanError("the chain's expiry %s has passed: run nse-fno-chain again" % expiry)
    direction = (a.direction or ("up" if entry.get("side", "buy") == "buy" else "down")).lower()
    if direction not in ("up", "down"):
        raise PlanError("--direction is up (buy a call) or down (buy a put)")
    right = "CE" if direction == "up" else "PE"
    i_entry = a.index_entry if a.index_entry is not None else entry.get("price")
    if not i_entry:
        raise PlanError("no index entry: run nse-entry on ^NSEI / ^BSESN, or give --index-entry")
    orr = entry.get("opening_range") or {}
    i_stop = a.index_stop if a.index_stop is not None else (
        (orr["high"] + orr["low"]) / 2 if orr.get("high") and orr.get("low") else None)
    if i_stop is None and not a.stop.startswith("pct:"):
        raise PlanError("no index stop: give --index-stop, or --stop pct:X")
    if i_stop is not None and ((direction == "up" and i_stop >= i_entry) or (direction == "down" and i_stop <= i_entry)):
        raise PlanError("the index stop %.2f is on the wrong side of the entry %.2f for a %s trade"
                        % (i_stop, i_entry, direction))
    i_risk = abs(i_entry - i_stop) if i_stop is not None else None
    i_target = a.index_target if a.index_target is not None else (
        i_entry + (1 if direction == "up" else -1) * a.target_r * i_risk if i_risk else None)

    strike, leg = pick_strike(chain, right, a.strike, chain["spot"], s["step"])
    iv = (leg.get("iv") or chain.get("atm_iv") or 12.0) / 100.0
    t = F.years_to_expiry(now, expiry)
    r = chain.get("rate", 0.065)
    premium = F.ceil_tick(leg["ask"])
    # the model price now vs the market: shift every model price by the same gap
    model_now = F.bs_price(right, chain["spot"], strike, t, r, iv)
    gap = premium - model_now
    if a.stop.startswith("pct:"):
        stop = F.floor_tick(premium * (1 - float(a.stop[4:]) / 100.0))
        stop_how = "%s%% under the premium" % a.stop[4:]
    else:
        stop = F.floor_tick(F.bs_price(right, i_stop, strike, t, r, iv) + gap)
        stop_how = "the premium if %s reaches %.2f (Black-Scholes, IV %.1f%%)" % (idx, i_stop, 100 * iv)
    if i_target is not None:
        target = F.round_tick(F.bs_price(right, i_target, strike, t, r, iv) + gap)
        target_how = "the premium if %s reaches %.2f" % (idx, i_target)
    else:
        target = F.round_tick(premium + a.target_r * (premium - stop))
        target_how = "%gR on the premium" % a.target_r
    stop = max(F.TICK, stop)
    if stop >= premium:
        raise PlanError("the premium at the stop (%.2f) is not below the entry (%.2f): widen the index stop" % (stop, premium))
    if target <= premium:
        raise PlanError("the target premium %.2f is not above the entry %.2f" % (target, premium))
    buf = float(fno["sl_limit_buffer_pct"])
    gap_pts = min(stop * buf / 100.0, 0.25 * (premium - stop))   # at most a quarter of the stop distance
    sl_limit = max(F.TICK, F.floor_tick(stop - max(F.TICK, gap_pts)))
    if sl_limit >= stop:
        sl_limit = max(F.TICK, round(stop - F.TICK, 2))
    risk_unit = round(premium - sl_limit, 2)
    reward_unit = round(target - premium, 2)

    lot = int(s["lot"])
    max_loss = float(cfg.get("max_loss_per_trade_inr") or 0)
    budget = float(cfg.get("budget") or 0)
    cash = max(0.0, budget * (1 - float(cfg.get("cash_buffer_pct") or 0) / 100.0)) if budget else None
    limits = []
    n = 0
    if max_loss:
        n = int(max_loss // (risk_unit * lot)) if risk_unit > 0 else 0
        while n > 0 and n * lot * risk_unit + F.option_round_trip(n * lot, premium, sl_limit, s["exchange"]) > max_loss + 0.005:
            n -= 1
        limits.append(("max loss", n, "%s / (%.2f x %d a lot), after costs" % (money(max_loss), risk_unit, lot)))
    limits.append(("max lots", int(fno["max_lots"]), "fno.max_lots"))
    if fno.get("max_premium_inr"):
        limits.append(("premium cap", int(float(fno["max_premium_inr"]) // (premium * lot)),
                       "%s / (%.2f x %d)" % (money(float(fno["max_premium_inr"])), premium, lot)))
    if cash is not None:
        limits.append(("cash", int(cash // (premium * lot)), "%s after the buffer / (%.2f x %d)" % (money(cash), premium, lot)))
    if s.get("freeze"):
        limits.append(("freeze", int(s["freeze"]) // lot, "exchange freeze %d units per order" % int(s["freeze"])))
    lots = max(0, min(x[1] for x in limits))
    bound = next(x[0] for x in limits if x[1] == lots)
    qty = lots * lot
    fees_stop = F.option_round_trip(qty, premium, sl_limit, s["exchange"])
    fees_target = F.option_round_trip(qty, premium, target, s["exchange"])
    net_loss = round(qty * risk_unit + fees_stop, 2)
    net_gain = round(qty * reward_unit - fees_target, 2)
    breakeven = round(net_loss / (net_loss + net_gain), 3) if qty and net_loss + net_gain > 0 else None
    warnings = []
    if expiry == today:
        warnings.append("EXPIRY DAY for this contract: time value can collapse within hours; nse-risk blocks new "
                        "entries after %s." % fno["expiry_no_entries_after"])
    if (premium - stop) / premium > 0.5:
        warnings.append("the stop gives up %.0f%% of the premium: the option may be too far out of the money or "
                        "the index stop too wide." % (100 * (premium - stop) / premium))
    rr = reward_unit / risk_unit if risk_unit else 0
    if rr < float(fno.get("min_target_r") or 0):
        warnings.append("reward:risk on the premium is %.2f, under fno.min_target_r %s." % (rr, fno["min_target_r"]))
    if not F.calendar_known(expiry):
        warnings.append("the holiday list does not cover %d: check the expiry date in Kite." % expiry.year)
    refusal = None
    if lots == 0:
        refusal = ("0 lots: bound by %s (%s). No order." % (bound, next(x[2] for x in limits if x[0] == bound)))
    doc = {
        "created_by": "nse-fno-plan", "instrument": "option", "underlying": idx, "exchange": s["exchange"],
        "symbol": leg["symbol"], "right": right, "strike": strike, "expiry": expiry.isoformat(),
        "direction": direction, "date": today.isoformat(), "lot_size": lot, "lots": lots, "qty": qty,
        "index_entry": round(i_entry, 2), "index_stop": round(i_stop, 2) if i_stop is not None else None,
        "index_target": round(i_target, 2) if i_target is not None else None,
        "entry": premium, "stop": stop, "stop_limit": sl_limit, "target": target, "stop_how": stop_how,
        "target_how": target_how, "iv": round(100 * iv, 2), "delta": leg.get("delta"), "theta": leg.get("theta"),
        "risk_per_share": risk_unit, "reward_per_share": reward_unit, "reward_risk": round(rr, 2),
        "max_loss": round(qty * risk_unit, 2), "charges_at_stop": fees_stop, "charges_at_target": fees_target,
        "net_loss_at_stop": net_loss, "net_gain_at_target": net_gain, "breakeven_win_rate": breakeven,
        "flat_by": cfg.get("flat_by") or "15:10", "limits": [{"name": a_, "lots": b_, "how": c_} for a_, b_, c_ in limits],
        "bound_by": bound, "warnings": warnings, "refusal": refusal,
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return doc


def order_of(p):
    return {"symbol": p["symbol"], "exchange": p["exchange"], "product": "MIS", "side": "buy",
            "qty": str(p["qty"]), "type": "limit", "limit_price": "%.2f" % p["entry"], "time_in_force": "day",
            "order_class": "bracket", "stop_loss_stop_price": "%.2f" % p["stop"],
            "stop_loss_limit_price": "%.2f" % p["stop_limit"], "take_profit_limit_price": "%.2f" % p["target"],
            "why": "%s %s on %s signal: %d lot%s of %d, bound by %s; %s at the stop's limit, with costs"
                   % (p["underlying"], "call" if p["right"] == "CE" else "put",
                      "an up" if p["direction"] == "up" else "a down", p["lots"],
                      "" if p["lots"] == 1 else "s", p["lot_size"], p["bound_by"], money(-p["net_loss_at_stop"])),
            "plan": {k: p[k] for k in ("instrument", "underlying", "right", "strike", "expiry", "lot_size", "lots",
                                       "entry", "stop", "stop_limit", "target", "risk_per_share", "max_loss",
                                       "charges_at_stop", "charges_at_target", "net_loss_at_stop", "flat_by",
                                       "index_entry", "index_stop", "index_target", "delta", "iv", "date")}}


def render(p):
    out = ["%s %s %s %s, expiry %s: buy %s on %s signal (index entry %.2f, stop %s, target %s)" % (
        p["underlying"], F.strike_text(p["strike"]), p["right"], p["symbol"], p["expiry"],
        "a call" if p["right"] == "CE" else "a put", "an up" if p["direction"] == "up" else "a down", p["index_entry"],
        "-" if p["index_stop"] is None else "%.2f" % p["index_stop"],
        "-" if p["index_target"] is None else "%.2f" % p["index_target"])]
    out.append("  Delta %s, IV %.1f%%, theta %s a day per unit." % (
        "-" if p["delta"] is None else "%.2f" % p["delta"], p["iv"], "-" if p["theta"] is None else "%.2f" % p["theta"]))
    out.append("  Entry    %.2f  limit at the ask" % p["entry"])
    out.append("  Stop     %.2f  trigger (%s); SL limit %.2f" % (p["stop"], p["stop_how"], p["stop_limit"]))
    out.append("  Target   %.2f  %s" % (p["target"], p["target_how"]))
    out.append("  Per unit: risk %.2f, reward %.2f, reward:risk %.2f. Flat by %s IST either way."
               % (p["risk_per_share"], p["reward_per_share"], p["reward_risk"], p["flat_by"]))
    out.append("")
    out.append("Lots (the smallest wins):")
    for l in p["limits"]:
        out.append("  %-12s %3d  %s%s" % (l["name"], l["lots"], l["how"], "  <- binds" if l["name"] == p["bound_by"] else ""))
    if p["refusal"]:
        out.append("")
        out.append(p["refusal"])
    else:
        out.append("")
        out.append("Size: %d lot%s = %d units, premium %s. At the stop's limit: -%s with %s costs. At the target: +%s "
                   "after %s costs. Break-even win rate: %.0f%%." % (
                       p["lots"], "" if p["lots"] == 1 else "s", p["qty"], money(p["qty"] * p["entry"]),
                       money(p["net_loss_at_stop"]), money(p["charges_at_stop"]), money(p["net_gain_at_target"]),
                       money(p["charges_at_target"]), 100 * (p["breakeven_win_rate"] or 0)))
        out.append("A model of the premium, not a promise: IV can drop, time decay keeps working, and a fast move can "
                   "jump past the SL limit and leave the stop unfilled.")
    for w in p["warnings"]:
        out.append("note: " + w)
    out.append("Next: nse-risk checks it, nse-broker asks you yes or no. Not investment advice.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--index", help="NIFTY or SENSEX (default: trader/entry.json's symbol)")
    ap.add_argument("--direction", help="up (buy a call) or down (buy a put)")
    ap.add_argument("--index-entry", type=float)
    ap.add_argument("--index-stop", type=float)
    ap.add_argument("--index-target", type=float)
    ap.add_argument("--target-r", type=float, default=2.0)
    ap.add_argument("--strike", default="delta:0.55", help="delta:0.55 (default), atm, itm1, otm1 or a strike")
    ap.add_argument("--stop", default="index", help="index (default: the premium at the index stop) or pct:X")
    ap.add_argument("--chain", help="nse-fno-chain output (default trader/fno/chain-<INDEX>.json)")
    ap.add_argument("--entry", default="trader/entry.json")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--now")
    ap.add_argument("--write", nargs="?", const="trader/orders.json", help="write the order (default trader/orders.json)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        now = parse_now(a.now)
        p = plan(a, now)
    except (PlanError, F.FnoError, ValueError, KeyError) as e:
        print("plan.py: %s" % e, file=sys.stderr)
        return 1
    os.makedirs(os.path.join("trader", "fno"), exist_ok=True)
    with open(os.path.join("trader", "fno", "plan.json"), "w", encoding="utf-8") as fh:
        json.dump(p, fh, indent=2, ensure_ascii=False)
    if a.write and not p["refusal"]:
        d = os.path.dirname(a.write)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.write, "w", encoding="utf-8") as fh:
            json.dump({"created_by": "nse-fno-plan", "created_at": p["created_at"], "status": "proposed",
                       "note": "Proposals only. Nothing is placed until nse-risk passes it and you say yes.",
                       "source": "trader/fno/plan.json (%s)" % p["symbol"], "orders": [order_of(p)]}, fh, indent=2,
                      ensure_ascii=False)
    print(json.dumps(p, indent=2, ensure_ascii=False) if a.json else render(p))
    if a.write and not p["refusal"] and not a.json:
        print("Wrote %s." % a.write)
    return 1 if p["refusal"] else 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):      # Windows pipes default to cp1252
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
