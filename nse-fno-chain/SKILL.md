---
name: nse-fno-chain
description: >-
  Option Chain for NIFTY 50 and SENSEX index options. Knows the contracts
  (NIFTY lot 65, weekly expiry Tuesday; SENSEX lot 20, expiry Thursday;
  holidays move an expiry to the day before; monthly = the last one of the
  month), builds the Kite instrument list around the money, and analyses a
  saved Kite get_quotes answer: per-strike price, spread, open interest,
  implied volatility and Greeks, the ATM straddle and the move it implies,
  PCR, max pain and the OI walls. Use when the user says "NIFTY option
  chain", "SENSEX options", "which strike", "PCR", "max pain", "open
  interest", "IV", "next expiry", or before /nse-fno-plan.
argument-hint: "[expiries|symbols|analyse] NIFTY|SENSEX"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-fno-chain

> **Read this first.** SEBI's study of FY2025-26 found **87.7% of individual F&O traders lost
> money**, an average net loss of about ₹1.17 lakh each. Bought options lose value every
> minute the index does not move, and most expire worthless. This pack buys NIFTY 50 and
> SENSEX options intraday only, with a stop, a size cap and your yes on every order. It does
> not write (sell) options and does not trade futures.

The Option Chain turns Kite's raw quotes into the few numbers an option buyer
needs: which strikes are liquid, what the market expects the index to move,
and what each option's delta and daily time decay are.

```bash
python3 "${CLAUDE_SKILL_DIR}/chain.py" expiries NIFTY                    # next weekly expiries, holiday-shifted
python3 "${CLAUDE_SKILL_DIR}/chain.py" expiries SENSEX
python3 "${CLAUDE_SKILL_DIR}/chain.py" symbols NIFTY --spot 25812        # Kite instruments, ATM +- 10 strikes
python3 "${CLAUDE_SKILL_DIR}/chain.py" analyse NIFTY --quotes trader/fno/quotes-NIFTY.json --spot 25812 --write
python3 "${CLAUDE_SKILL_DIR}/chain.py" analyse SENSEX --quotes FILE --spot 84210 --expiry 2026-11-05 --json
```

## Getting the data from Kite (Claude does this)

1. Spot: Kite `get_ltp` (or `get_quotes`) for `NSE:NIFTY 50` or `BSE:SENSEX`.
2. `chain.py symbols INDEX --spot SPOT` prints the instrument list for the
   nearest expiry (`--expiry` for another).
3. Kite `get_quotes` with that list. Save the answer exactly as returned to
   `trader/fno/quotes-INDEX.json`.
4. `chain.py analyse INDEX --quotes trader/fno/quotes-INDEX.json --spot SPOT --write`.

If Kite says an instrument does not exist, run Kite `search_instruments` for
the index, save it, and pass it with `--instruments FILE`: Kite's own list of
symbols, strikes, expiries and lot sizes then wins over the built-in rules.

## The contracts (built in; override under "fno" in trader/config.json)

| | NIFTY 50 | SENSEX |
| --- | --- | --- |
| Exchange (Kite) | NFO | BFO |
| Lot | 65 | 20 |
| Strike step | 50 | 100 |
| Weekly expiry | Tuesday | Thursday |
| Monthly | last Tuesday | last Thursday |
| Freeze (units per order) | 3,510 (from 5 Oct 2026) | set it in the config |

A holiday moves the expiry to the trading day before (10 November 2026 moves
NIFTY's expiry to Monday 9 November). Kite symbols: weekly
`NIFTY26N0325800CE` (year, month code 1-9/O/N/D, day, strike), monthly
`NIFTY26NOV25800CE`. Exchanges revise lots and freeze limits; check them when a
circular comes out.

## Reading the chain honestly

- **Implied move:** about 0.8 x the ATM straddle is one standard deviation to
  expiry. An option buyer needs a move bigger than that, and soon.
- **Theta:** printed in rupees a day per unit. On expiry day it accelerates.
- **PCR, max pain, OI walls:** where positions sit, not which way they face.
  None of them is a forecast.
- **Spread:** a strike flagged `!` is too thin; the planner will not pick it.

## What it never does

It never places an order, never calls a direction, and never treats a model
Greek as a promise.

## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a
  rules check, not a recommendation. SEBI's own 2024 study found about 7 in 10 individual intraday
  traders in the equity cash segment lost money in FY23; say so when the user is new to this.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode records
  simulated fills in `trader/` and sends nothing to Kite. Going live is the user's own decision, in
  their own config.
- Nothing in this pack places an order except nse-broker, and only when all three hold: nse-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and
  the user clicked Allow once on Claude's own card because Kite's `place_order` tool is set to
  "Needs approval". Never set an order tool to "Always allow".
- No F&O, margin (MIS leverage), short selling or delivery holding unless the config allows it and
  the user confirms.
- Kite API keys live in environment variables or the MCP server's own config, never in the chat.
  SEBI's rules require a registered static IP for API order placement (from 1 April 2026).
