"""Shared index-option facts and maths for nse-fno-chain and nse-fno-plan. Standard library only.

Contract facts (check them when the exchanges revise them; every one can be overridden in
trader/config.json under "fno"):
  NIFTY 50   NSE (Kite exchange NFO), lot 65 (contracts expiring from January 2026), strike step 50,
             weekly options expire on Tuesday, the monthly is the last Tuesday of the month,
             quantity freeze 3,510 (from 5 October 2026)
  SENSEX     BSE (Kite exchange BFO), lot 20, strike step 100, weekly options expire on
             Thursday, the monthly is the last Thursday; quantity freeze: set it in the config
  A holiday moves an expiry to the previous trading day. Options trade in ticks of 0.05.

Kite trading symbols: weekly NIFTY<YY><M><DD><STRIKE><CE|PE> with M = 1-9, O, N, D (for
example NIFTY26N0925800CE for 9 November 2026), and the monthly contract
NIFTY<YY><MON><STRIKE><CE|PE> (NIFTY26NOV25800CE). Kite's search_instruments is the
authority: when you have its list, pass it and the symbols come from there.
"""

import datetime
import math

INDICES = {
    "NIFTY": {"name": "NIFTY 50", "exchange": "NFO", "spot_exchange": "NSE", "kite_spot": "NSE:NIFTY 50",
              "yahoo": "^NSEI", "lot": 65, "step": 50, "weekday": 1, "freeze": 3510},
    "SENSEX": {"name": "SENSEX", "exchange": "BFO", "spot_exchange": "BSE", "kite_spot": "BSE:SENSEX",
               "yahoo": "^BSESN", "lot": 20, "step": 100, "weekday": 3, "freeze": None},
}
ALIASES = {"NIFTY": "NIFTY", "NIFTY50": "NIFTY", "NIFTY 50": "NIFTY", "^NSEI": "NIFTY", "NSEI": "NIFTY",
           "SENSEX": "SENSEX", "^BSESN": "SENSEX", "BSESN": "SENSEX"}
TICK = 0.05

# NSE equity and derivatives trading holidays 2026 (BSE follows the same list for 2026).
HOLIDAYS = {
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03", "2026-04-14",
    "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10",
    "2026-11-24", "2026-12-25",
}
CALENDAR_YEARS = (2026,)
IST = datetime.timedelta(hours=5, minutes=30)
WEEK_CODE = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "O", 11: "N", 12: "D"}
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


class FnoError(Exception):
    pass


def index_of(name):
    key = ALIASES.get(str(name or "").strip().upper())
    if not key:
        raise FnoError("this pack trades NIFTY 50 and SENSEX options only, not %r" % name)
    return key


def spec(idx, cfg=None):
    """The index's facts, with any override from config["fno"][INDEX] (lot, step, freeze)."""
    s = dict(INDICES[idx])
    over = ((cfg or {}).get("fno") or {}).get(idx) or {}
    for k in ("lot", "step", "freeze"):
        if over.get(k) is not None:
            s[k] = over[k]
    return s


# ---------------------------------------------------------------- calendar

def trading_day(d):
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def prev_trading_day(d):
    while not trading_day(d):
        d -= datetime.timedelta(days=1)
    return d


def _last_weekday(year, month, weekday):
    nxt = datetime.date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - datetime.timedelta(days=1)
    while d.weekday() != weekday:
        d -= datetime.timedelta(days=1)
    return d


def is_monthly(idx, expiry):
    """True when this expiry is the month's last scheduled expiry (after any holiday shift)."""
    wd = INDICES[idx]["weekday"]
    last = prev_trading_day(_last_weekday(expiry.year, expiry.month, wd))
    return expiry == last


def expiries(idx, start, n=4):
    """The next n weekly expiries on or after `start` (a date), holiday-shifted."""
    wd = INDICES[idx]["weekday"]
    out = []
    d = start - datetime.timedelta(days=7)
    while len(out) < n:
        d += datetime.timedelta(days=1)
        if d.weekday() != wd:
            continue
        e = prev_trading_day(d)
        if e >= start and e not in out:
            out.append(e)
    return out


def calendar_known(d):
    return d.year in CALENDAR_YEARS


# ---------------------------------------------------------------- symbols

def strike_text(strike):
    return ("%d" % strike) if float(strike) == int(strike) else ("%g" % strike)


def tradingsymbol(idx, expiry, strike, right):
    """Kite's symbol for an index option (right = 'CE' or 'PE')."""
    yy = expiry.year % 100
    if is_monthly(idx, expiry):
        return "%s%02d%s%s%s" % (idx, yy, MONTHS[expiry.month - 1], strike_text(strike), right)
    return "%s%02d%s%02d%s%s" % (idx, yy, WEEK_CODE[expiry.month], expiry.day, strike_text(strike), right)


def atm(spot, step):
    return int(round(spot / step) * step)


# ---------------------------------------------------------------- Black-Scholes

def _ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_price(right, s, k, t, r, sigma, q=0.0):
    if t <= 0 or sigma <= 0:
        return max(0.0, (s - k) if right == "CE" else (k - s))
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if right == "CE":
        return s * math.exp(-q * t) * _ncdf(d1) - k * math.exp(-r * t) * _ncdf(d2)
    return k * math.exp(-r * t) * _ncdf(-d2) - s * math.exp(-q * t) * _ncdf(-d1)


def greeks(right, s, k, t, r, sigma, q=0.0):
    """delta, gamma, theta (rupees per calendar day), vega (rupees per 1 IV point)."""
    if t <= 0 or sigma <= 0:
        itm = (s > k) if right == "CE" else (s < k)
        return {"delta": (1.0 if itm else 0.0) * (1 if right == "CE" else -1), "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    st = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / st
    d2 = d1 - st
    disc_q, disc_r = math.exp(-q * t), math.exp(-r * t)
    if right == "CE":
        delta = disc_q * _ncdf(d1)
        theta = (-s * disc_q * _npdf(d1) * sigma / (2 * math.sqrt(t)) - r * k * disc_r * _ncdf(d2)
                 + q * s * disc_q * _ncdf(d1))
    else:
        delta = disc_q * (_ncdf(d1) - 1)
        theta = (-s * disc_q * _npdf(d1) * sigma / (2 * math.sqrt(t)) + r * k * disc_r * _ncdf(-d2)
                 - q * s * disc_q * _ncdf(-d1))
    gamma = disc_q * _npdf(d1) / (s * st)
    vega = s * disc_q * _npdf(d1) * math.sqrt(t) / 100.0
    return {"delta": delta, "gamma": gamma, "theta": theta / 365.0, "vega": vega}


def implied_vol(right, price, s, k, t, r, q=0.0):
    """Bisection on volatility. None when the price is below intrinsic value or there is no time."""
    if price is None or price <= 0 or t <= 0:
        return None
    intrinsic = max(0.0, (s - k) if right == "CE" else (k - s)) * math.exp(-r * t)
    if price < intrinsic - 1e-6:
        return None
    lo, hi = 1e-4, 5.0
    if bs_price(right, s, k, t, r, hi, q) < price:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if bs_price(right, s, k, t, r, mid, q) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-6:
            break
    return (lo + hi) / 2


def years_to_expiry(now_utc, expiry):
    """Calendar time from now to 15:30 IST on the expiry day, in years (at least one minute)."""
    end = datetime.datetime.combine(expiry, datetime.time(15, 30)) - IST
    secs = (end - now_utc).total_seconds()
    return max(secs, 60.0) / (365.0 * 86400.0)


# ---------------------------------------------------------------- costs

OPTION_CHARGES = {  # Zerodha, equity options, zerodha.com/charges read 2026-10-30
    "brokerage_per_order": 20.0,
    "stt_sell_pct": 0.15,                          # of the premium on the sell side (from 1 April 2026)
    "exchange_pct": {"NFO": 0.03553, "BFO": 0.0325},   # of the premium, both sides
    "sebi_per_crore": 10.0,
    "stamp_buy_pct": 0.003,
    "gst_pct": 18.0,
}


def option_round_trip(qty, buy, sell, exchange, table=None):
    """Rupees to buy qty at `buy` and sell at `sell`: one buy order and one sell order.
    Squared off before expiry, so no STT on exercise."""
    t = dict(OPTION_CHARGES)
    t.update(table or {})
    if qty <= 0:
        return 0.0
    bv, sv = qty * float(buy), qty * float(sell)
    ex = t["exchange_pct"].get(exchange, 0.03553) if isinstance(t["exchange_pct"], dict) else t["exchange_pct"]
    brokerage = 2 * float(t["brokerage_per_order"])
    stt = round(sv * t["stt_sell_pct"] / 100.0)
    exch = (bv + sv) * ex / 100.0
    sebi = (bv + sv) * t["sebi_per_crore"] / 1e7
    stamp = round(bv * t["stamp_buy_pct"] / 100.0)
    gst = (brokerage + exch + sebi) * t["gst_pct"] / 100.0
    return round(brokerage + stt + exch + sebi + stamp + gst, 2)


def floor_tick(x, tick=TICK):
    return round(math.floor(round(x / tick, 6)) * tick, 2)


def ceil_tick(x, tick=TICK):
    return round(math.ceil(round(x / tick, 6)) * tick, 2)


def round_tick(x, tick=TICK):
    return round(math.floor(x / tick + 0.5) * tick, 2)
