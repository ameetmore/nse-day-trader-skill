---
name: nse-scanner
description: >-
  Chart Scanner for NSE. Scans hundreds or thousands of Indian stock charts
  for setups: before the open, daily setups (20-day breakouts, bull flags, a
  reclaimed 20-day average, oversold bounces); after 9:30 IST, opening-range
  breakouts on 5-minute bars. Builds its universe from NSE's own lists (NIFTY
  50/100/200/500, or every EQ-series stock) and reads free Yahoo .NS charts.
  Writes trader/watchlist.json for the other skills. Use when the user says
  "scan the market", "what's breaking out", "find setups", "scan NIFTY 500",
  "opening range breakouts", "what to watch today", or at the start of a
  trading day, before /nse-news and /nse-entry.
argument-hint: "[universe|daily|orb] [--index nifty500|all] [--symbols A,B]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-scanner

The Chart Scanner turns a list of NSE stocks into a short list of charts worth
a closer look. A hit is a chart that matched a rule, not a stock to buy.

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                       # NIFTY 500 from NSE -> trader/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe --index all           # every EQ-series stock (~2,000)
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                          # before 9:15: daily setups -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols RELIANCE,TCS,INFY
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                            # after 9:35: opening-range breakouts so far
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:15 --or-minutes 15 # replay the clock at 10:15 IST
```

Other flags: `--limit N`, `--watchlist FILE`, `--min-price` (₹50), `--min-volume`
(500,000 shares for `daily`), `--max-confirm` (200 charts in stage 2), `--json`,
`--no-write`, `--offline PATH` (saved Yahoo JSON), `--now "2026-10-29 10:15"`
(IST).

## Symbols and data

- Symbols are NSE trading symbols: `RELIANCE`, `M&M`, `BAJAJ-AUTO`. Yahoo gets
  them with `.NS` added. Give `SYM.BO` for a BSE-only listing.
- `universe` downloads NSE's CSV (`ind_nifty500list.csv`, or `EQUITY_L.csv`
  for `--index all`) and keeps the EQ series only: BE/BZ trade-to-trade and
  SME series cannot be traded intraday. If NSE refuses the download (it
  sometimes blocks scripts), ask the user to save the CSV from nseindia.com
  and run `universe --offline FOLDER`.
- Bars are Yahoo's free, unofficial 5-minute and daily charts. They can lag.
  Session: 9:15 to 15:30 IST, NSE's 2026 holiday list built in.

## The setups

- **daily** (closes only): `breakout_20d`, `bull_flag`, `reclaim_ma20`,
  `oversold` (RSI 14 under 30) and `oversold_bounce`. Today's bar is left out
  until the close.
- **orb**: the opening range is the first 15 minutes (9:15 to 9:30). A hit is
  the first completed 5-minute bar to CLOSE above the range high, at that
  bar's close time. A chart counts only when every bar from 9:15 to the
  cutoff is there (a missing bar is a halt, a circuit or no trades).

## Steps

1. If `trader/universe.txt` is missing, run `universe` first (NIFTY 500 is a
   sensible default: liquid and quick to scan).
2. Before the open run `daily`; after 9:35 run `orb`. Both write
   `trader/watchlist.json`.
3. Show the top hits in a short table: symbol, setup, price, how far over.
   Point out anything stuck near its upper circuit or on an ASM/GSM
   surveillance list if the user mentions it: those can halt or demand 100%
   margin.
4. Hand off: `/nse-news SYMBOL` for why it moves, `/nse-research SYMBOL` for a
   full committee view if there is time, then `/nse-entry SYMBOL`.

## Example (offline fixtures, synthetic prices)

```
Opening-range breakout scan, Thu 2026-10-29 10:15 AM IST: 15-minute range (9:15 to 9:30 AM), 5-minute bars, Yahoo.
2 of 5 charts closed above their opening-range high by 10:15 AM:
   9:40 AM  BETA    ₹1,659.68  range 1,640.33 to 1,654.62  +0.31% over
   9:40 AM  DEMO    ₹1,409.49  range 1,402.85 to 1,408.37  +0.08% over
```

## What it never does

It never ranks a stock as a buy, never places an order, and never calls a
breakout on a bar that has not closed.

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
