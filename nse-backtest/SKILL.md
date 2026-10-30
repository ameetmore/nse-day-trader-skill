---
name: nse-backtest
description: >-
  Backtest for the pack's NIFTY 50 / SENSEX option-buying opening-range
  breakout over years of real 5-minute index bars from Zerodha Kite: the same
  signal, stop, target, strike choice, expiry-day cutoff and 15:10 exit as
  nse-entry, nse-fno-plan and nse-risk, with option premiums modelled by
  Black-Scholes from the prior day's India VIX, slippage and Zerodha F&O
  costs; reports win rate, average R, net rupees, max drawdown and losing
  streaks by year, direction and expiry day, next to the same signal traded
  on the index itself. Use when the user says "backtest", "test the strategy
  on 5 years", "how would it have done", "historical performance", "win rate
  of the ORB".
argument-hint: "[fetch|fetch-vix|run] --index NIFTY|SENSEX [--years 5]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-backtest

The backtest replays the pack's option-buying rules on every trading day of
the period and reports what they would have done, with the modelling stated
up front so nobody mistakes an estimate for a record.

```bash
# once a day: Kite access (needs a Kite Connect app with historical data;
# KITE_API_KEY and KITE_API_SECRET set as environment variables)
python3 "${CLAUDE_SKILL_DIR}/backtest.py" kite-login               # open the URL, log in
python3 "${CLAUDE_SKILL_DIR}/backtest.py" kite-token REQUEST_TOKEN # from the address you land on

python3 "${CLAUDE_SKILL_DIR}/backtest.py" fetch --index NIFTY --years 5    # ~21 windows, merged
python3 "${CLAUDE_SKILL_DIR}/backtest.py" fetch --index SENSEX --years 5   # weeklies only from May 2023
python3 "${CLAUDE_SKILL_DIR}/backtest.py" fetch-vix                        # India VIX daily, free
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --index NIFTY --write
python3 "${CLAUDE_SKILL_DIR}/backtest.py" run --index NIFTY --sides up --target-r 1.5 --from 2024-01-01
```

On Windows: `set KITE_API_KEY=...` and `set KITE_API_SECRET=...` in the same
Command Prompt, then `py nse-backtest\backtest.py ...`. Keys stay in the
environment; the day's access token is saved in `trader/backtest/.kite_token`
(git-ignored). Never paste keys into the chat.

For a few months only, Claude's Kite connector can fetch the bars instead:
`fetch-plan` lists the `get_historical_data` calls and `merge` joins the saved
answers. Five years is about 90,000 candles per index, too much for a chat, so
use `fetch` for that.

## The rules it replays

- Opening range 9:15-9:30; the first 5-minute close above it buys a call,
  below it buys a put (`--sides`); one trade a day; no entry after 14:45, and
  none after 13:00 in a contract that expires that day.
- Index stop at the range midpoint, target `--target-r` (2) times the risk.
- Nearest weekly expiry on that date. NIFTY expired on Thursday until 31 August
  2025 and on Tuesday after. SENSEX weeklies started in May 2023, expiring
  Friday, then Tuesday from January 2025, then Thursday from September 2025.
  A day missing from the data moves the expiry to the trading day before.
- Strike nearest delta 0.55; entry, stop trigger, SL limit and target exactly
  as nse-fno-plan computes them; stop checked before target inside a bar; a
  gap through the stop fills at the gapped price; out at 15:10.

## Read the results honestly

- **Option premiums are modelled.** No free source keeps expired option
  prices, so each premium is Black-Scholes on the real index bar with the prior
  day's India VIX as the volatility, held flat for the day. Real weekly options
  have skew and moving IV. Try `--iv-scale 0.9` and `1.2` to see how much the
  answer depends on it.
- **The index columns are not modelled:** the same signal, stop and target
  traded on the index in points. If the idea fails there, the options will not
  rescue it.
- **Costs at today's rates** (STT 0.15% on option sales since April 2026,
  higher than before), **rupees at today's lot size**, slippage 0.5% each way.
- **One set of fixed rules, no fitting.** Change the rules after seeing the
  results and the next backtest is fitted to the past. Check every year
  separately, not only the total.
- Past results do not predict future ones, and SEBI found 87.7% of individual
  F&O traders lost money in FY2025-26.

## Steps

1. Check the user has a Kite Connect app with historical data; if not, say the
   5-year intraday test needs it (or a 5-minute CSV they already have:
   `merge --index NIFTY file.csv`).
2. `fetch` for each index, `fetch-vix`, then `run --write`.
3. Report the totals, the by-year table, calls versus puts, expiry days, the
   index-points baseline, and the modelling caveats in plain words.
4. Offer the sensitivity runs: `--iv-scale`, `--target-r`, `--sides`.

## What it never does

It never trades, never fits its rules to the data, and never presents a
modelled premium as a recorded price.

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
