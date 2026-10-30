---
name: nse-budget
description: >-
  Budget Manager for NSE intraday trades. Sizes a position from
  trader/plan.json to your budget and your max loss per trade in rupees,
  AFTER Indian trading costs (brokerage, STT, exchange and SEBI fees, stamp
  duty, GST; Zerodha intraday rates by default), whole shares only, with an
  optional MIS margin multiplier. Writes one proposed order (entry, SL-M
  stop, LIMIT target) to trader/orders.json. Also splits a budget across
  stocks by weight for delivery (CNC). Use when the user says "how many
  shares", "size it", "position size", "my budget is", "max loss", "what will
  it cost", or after /nse-exit or /nse-timemachine and before /nse-risk.
argument-hint: "[--budget 500000] [--limit PRICE] [--write]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-budget

The Budget Manager answers "how many shares?" so that, if the stop fills, the
loss plus the costs stays inside your limit.

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                        # trader/plan.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write                # -> trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --budget 200000 --write
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 1410.00 --write # a limit entry
python3 "${CLAUDE_SKILL_DIR}/size.py" --weights RELIANCE=30,HDFCBANK=25,TCS=20,INFY=15,ITC=10 \
    --budget 500000 --prices trader/prices.json             # delivery split (CNC), whole shares
```

Start from `config.example.json` here: copy it to `trader/config.json` and
change the numbers. The keys are in rupees: `budget`, `max_loss_per_trade_inr`,
`max_daily_loss_inr`, `max_order_inr`, `min_order_inr`.

## How many shares

The smallest of: **max loss** (the most shares whose loss at the stop plus the
round-trip costs fits `max_loss_per_trade_inr`), **position cap**
(`max_position_pct` of the budget), **max order** (`max_order_inr`) and
**cash** (budget minus the cash buffer). With `"allow_margin": true` and
`"product": "MIS"`, cash is multiplied by `mis_leverage` (your broker's
intraday leverage for that stock, often up to 5x under SEBI's margin rules).
The position cap is a percent of the budget, so with margin raise
`max_position_pct` above 100 too (500 = 5x) or the cap still binds. Margin
makes the position bigger, not the loss limit: the max-loss rule still binds.

## Costs

`"charges": "zerodha"` (default): brokerage 0.03% or ₹20 per executed order,
whichever is lower; STT 0.025% on the sell; NSE transaction charges 0.00307%;
SEBI ₹10 a crore; stamp duty 0.003% on the buy; GST 18% on brokerage +
transaction + SEBI (zerodha.com/charges, read 2026-10-30). Use `"none"`, or an
object with your broker's rates. It is an estimate; the contract note is the
real number.

## Example (synthetic DEMO plan, ₹5,00,000 budget)

```
Size: 266 shares of DEMO = ₹374,924.34 at 1409.49. Max loss at the stop: 266 x 3.89 = ₹1,034.74.
Costs (zerodha intraday estimate ...): about ₹179.21 at the stop, ₹180.29 at the target.
Net at the stop: -₹1,213.95. Net at the target: +₹859.77.
```

That 1R plan risks ₹1,214 to make ₹860 after costs: it needs to win about
59% of the time to break even. Say this kind of thing plainly.

## Steps

1. Make sure `trader/config.json` has a budget and a max loss in rupees.
2. Run `size.py`, read the limits table, say which one binds, the size, the
   max loss with costs and the net at the target.
3. With the user's go-ahead, `size.py --write`, then `/nse-risk`.

## What it never does

It never places an order, never rounds up past a limit, never sizes a short,
and never hides money it could not invest.

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
