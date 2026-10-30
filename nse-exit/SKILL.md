---
name: nse-exit
description: >-
  Exit Planner for NSE intraday trades. Sets the stop and the target BEFORE
  you enter: stop at the opening-range midpoint or low, a price, a percent or
  an ATR multiple; target as an R multiple (1R, 2R) or a price; both rounded
  onto NSE's tick grid so Kite accepts them; flat by 15:10 IST either way,
  before the broker's auto square-off. Writes trader/plan.json for
  /nse-timemachine and /nse-budget. Long side only. Use when the user says
  "where's my stop", "set a target", "plan the exit", "stop loss", "risk
  reward", or after /nse-entry triggers.
argument-hint: "[--stop or-mid|or-low|price:X|pct:X|atr:K] [--target 2R|price:X]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-exit

The Exit Planner writes down where you get out before you get in: the stop
(you were wrong), the target (you were right) and the time (the day is over).

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                                  # from trader/entry.json: or-mid stop, 2R
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-mid --target 1R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol RELIANCE --entry 1412.40 --or-high 1408.40 --or-low 1396.10
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:1.5 --target 2R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

## The rules

- **Stops** round DOWN onto the tick grid (away from the entry); **targets**
  round half up onto it. NSE ticks by price: ₹0.01 up to ₹250, ₹0.05 to
  ₹1,000, ₹0.10 to ₹5,000, ₹0.50 to ₹10,000, ₹1 to ₹20,000, ₹5 above (NSE
  circular effective 15 April 2025). NSE reviews each stock's band, so near a
  boundary check the stock's tick or set `"tick_size"` in the config.
- **Refused:** a stop at or above the entry, a target at or below it, a risk
  under 0.05% of the price (inside the spread), a short.
- **flat_by** 15:10 IST (config). Zerodha squares off open MIS positions
  itself at 15:12 for stocks in the closing auction and 15:25 for the rest,
  and charges ₹50 + GST an order for it: being out by 15:10 avoids both.
- `min_reward_risk` only warns here; `/nse-risk` enforces it. Remember the
  costs: on a 1R target, brokerage, STT and the rest make a coin-flip trade
  lose money. `/nse-budget` shows the numbers.

## Example (synthetic DEMO fixture)

```
Exit plan: DEMO long, Thu 2026-10-29, opening-range breakout on 5-minute bars
  Entry         ₹1,409.49 at 9:40 AM (bar 4)
  Stop          ₹1,405.60  opening-range midpoint: (₹1,408.37 + ₹1,402.85) / 2 = ₹1405.61, rounded down to the ₹0.1 tick
  Target        ₹1,413.40  1R (one times the risk)
  Risk a share  ₹3.89 (0.28% of the entry)
  Flat by       15:10 IST, win or lose: no overnight hold
```

## Steps

1. Run `exit.py plan --write` after the entry triggers (it reads
   `trader/entry.json`), or give `--symbol --entry` yourself.
2. Read the plan back in plain words: stop, target, risk a share, flat by.
3. Hand off to `/nse-timemachine`, then `/nse-budget`.

## What it never does

It never places a stop at the broker (nse-broker does, after the entry
fills), never moves a stop further away, and never plans a short.

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
