---
name: nse-timemachine
description: >-
  Time Machine for NSE intraday trades. Before you risk a rupee, replays the
  rest of the session 10,000 times from the stock's own 5-minute bars at the
  same time of day over its last ~59 full sessions, plus re-runs the same
  rule on each of those real sessions, and says how often the target came
  first, the stop came first, or neither by flat-by (15:10 IST). Reproducible
  with a seed. Use when the user says "what are the odds", "backtest this",
  "replay it", "simulate the trade", "time machine", or after /nse-exit and
  before /nse-budget.
argument-hint: "[--replays 10000] [--seed 19] [--until 15:10]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-timemachine

The Time Machine asks one honest question before money is at risk: on days
like the last sixty, how often does this exact plan hit its target before its
stop?

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run                     # trader/plan.json, 10,000 replays, seed 19
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --write             # -> trader/timemachine.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until 15:30       # hold to the close instead of flat-by
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol RELIANCE --date 2026-10-29 \
    --entry 1412.40 --stop 1405.60 --target 1426.00 --entry-time "9:40 AM"
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart --from trader/timemachine.json
```

## How it works

1. One Yahoo request: 60 days of 5-minute bars for `SYMBOL.NS`. Only FULL
   sessions before the plan's day count: 75 bars, 9:15 to 15:30 IST.
2. Each replay starts at the entry and walks the rest of the day. Every bar is
   drawn whole from the same time slot (plus or minus 2 bars) of a random past
   session and scaled to the current price. The stop is checked before the
   target inside a bar (the conservative call).
3. It ends at the plan's `flat_by` (15:10 by default), so "neither" means you
   would have closed it yourself.
4. The history line re-runs the same rule (same opening range, same stop
   rule, same R target) on each real past session.
5. The verdict compares how often the target came first with what the R
   multiple needs to break even. It does not include costs: `/nse-budget`
   shows them, and on small R targets they matter.

## Steps

1. Run `timemachine.py run --write` after `/nse-exit`.
2. Report the three numbers (target first, stop first, neither), the history
   line and the verdict in plain words. If it is close to a coin flip, say so.
3. Hand off to `/nse-budget`.

## What it never does

It never predicts a price, never uses data from the plan's own day, and never
calls a trade good. Results, news, circuits and halts can do what the last
sixty sessions never did.

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
