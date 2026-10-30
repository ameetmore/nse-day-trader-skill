---
name: nse-alerts
description: >-
  Price Alerts for NSE. Rings when a price crosses a level, a stop or a
  target from your plan, a stock moves N% from yesterday's close, the NSE
  opening bell (9:15 IST), or the flat-by time (15:10) arrives; knows NSE's
  2026 holidays. Free delayed Yahoo .NS quotes, one ring per rule. Use when
  the user says "alert me", "tell me if it hits", "watch my stop", "remind me
  to close", "is the market open", or while a trade is open after
  /nse-broker.
argument-hint: "[clock|quote|add|check|list|reset]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-alerts

Price Alerts watch while a trade is open, so nobody has to stare at a chart.
An alert is information, never an order.

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                       # is NSE open? next open
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote RELIANCE TCS          # delayed quotes
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan             # stop, target and flat-by from trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol INFY --above 1650
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol HDFCBANK --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                       # rings what hit, once
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
```

Rules live in `trader/alerts.json`; what already rang in
`trader/state/alerts.json`. Quotes: Yahoo's chart endpoint for `SYMBOL.NS`
(free, delayed, unofficial; never for timing an order). Calendar: NSE's 2026
equity holidays; outside 2026 the clock says the list is unknown.

## Steps

1. After an entry fills, run `add --from-plan`.
2. Run `check` every few minutes while the trade is open (a scheduled task
   or a loop). Report only what rang.
3. Stop or target rang: the SL-M or LIMIT order at Kite is what actually gets
   you out. Check `get_orders` / `get_positions`, cancel the exit order that
   is left, and record the fill with `ticket.py fill`.
4. Flat-by rang and the position is open: `/nse-broker` flatten, then
   `/nse-risk`, then the user's yes.

## What it never does

It never places, cancels or modifies an order, and never treats a delayed
quote as a fill.

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
