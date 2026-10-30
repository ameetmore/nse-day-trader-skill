---
name: nse-technicals
description: >-
  Technical Analyst for NSE stocks. Computes the standard daily indicators
  from free Yahoo .NS bars and prints them as the verified source of numbers:
  SMA 50/200, EMA 10, MACD with signal and histogram, RSI 14, Bollinger
  bands, ATR 14, VWMA 20, the 52-week range and volume; plus the market
  regime from NIFTY 50's trend and India VIX. Point in time with --as-of, so
  past-dated analysis sees no later bar. Use when the user says "technicals
  for RELIANCE", "RSI", "MACD", "moving averages", "is it overbought",
  "support and resistance", "what's the market trend", "India VIX", or inside
  /nse-research.
argument-hint: "[snapshot SYM ...|regime] [--as-of YYYY-MM-DD]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-technicals

The Technical Analyst gives every later claim about price, trend and momentum
one source of truth: numbers computed here, from bars, as of a date. Any
level, RSI or moving average quoted in a report should come from this output.

```bash
python3 "${CLAUDE_SKILL_DIR}/indicators.py" snapshot RELIANCE               # as of the last completed session
python3 "${CLAUDE_SKILL_DIR}/indicators.py" snapshot TCS INFY --json
python3 "${CLAUDE_SKILL_DIR}/indicators.py" snapshot RELIANCE --as-of 2026-10-15  # point in time
python3 "${CLAUDE_SKILL_DIR}/indicators.py" regime                          # NIFTY 50 trend + India VIX
python3 "${CLAUDE_SKILL_DIR}/indicators.py" snapshot RELIANCE --write       # -> trader/research/RELIANCE-technicals.json
```

## The indicators (daily bars)

| indicator | what it says | caution |
| --- | --- | --- |
| SMA 50 / SMA 200 | medium- and long-term trend; 50 over 200 is the "golden cross" side | lags; slow to turn |
| EMA 10 | short-term momentum | noisy in a range |
| MACD 12/26/9, signal, histogram | momentum and its change | false crosses in sideways markets |
| RSI 14 (Wilder) | above 70 stretched, under 30 washed out | can stay extreme in a strong trend |
| Bollinger 20, 2 sd | where price sits against its recent spread | price can ride a band |
| ATR 14 (Wilder) | a typical day's range, in rupees and % | backward-looking |
| VWMA 20 | the average price, weighted by volume | skewed by one huge day |
| 52-week high/low | where the close sits in the year's range | |

Choose the 4 to 8 that matter for the question and say why; do not recite all
of them. The `regime` line labels NIFTY uptrend / downtrend / mixed and India
VIX low (under 13) / normal / high (20 and up).

## Point in time

`--as-of DATE` drops every bar after that date: a past-dated analysis cannot
peek at what happened next. Without it, a session still trading (before 15:30
IST) is left out, because an unfinished bar is not a close.

## Steps

1. Run `snapshot SYMBOL` (and `regime` for the backdrop).
2. Report the few readings that matter, quoting the numbers as printed.
3. If another source disagrees with these numbers, say there is a
   discrepancy; do not average them into a new number.

## What it never does

It never forecasts a price, never draws support or resistance that the numbers
do not show, and never calls a stock a buy.

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
