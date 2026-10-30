---
name: nse-risk
description: >-
  Risk Manager for NSE trades. Checks every proposed order in
  trader/orders.json against your rules before it can reach the broker: whole
  shares, NSE/BSE cash equity only (no F&O unless allowed), MIS or CNC,
  prices on NSE's tick grid, a stop on every entry, max loss per trade
  including costs, reward:risk, daily loss limit, trades per day, the
  9:30-14:45 entry window and NSE holidays, position size and cash. PASS or
  BLOCK with the reasons, recorded by fingerprint so /nse-broker only offers
  an order that passed. Use when the user says "check the order", "is this
  within my limits", "risk check", or after /nse-budget and before
  /nse-broker.
argument-hint: "[--orders trader/orders.json] [--json]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-risk

The Risk Manager is the gate between a plan and the broker. It does not judge
the trade; it checks the order against the rules you wrote down when you were
calm.

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                           # trader/ files -> trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-10-29 09:45"  # pin the clock (IST)
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write
```

## What blocks an order

- **format:** no whole-share qty (no fractional or rupee-amount orders in
  India), an exchange other than NSE/BSE, a product other than MIS/CNC, a
  limit order without a price, a bracket missing a leg.
- **tick:** a limit, stop or target off NSE's tick grid (the exchange rejects
  it).
- **asset:** futures and options unless `"allow_options": true`. Even then,
  only NIFTY 50 options on NFO and SENSEX options on BFO (no futures, no stock
  or other index options); anything else must be an NSE/BSE equity symbol.
- **index options (with `allow_options`):** whole lots (NIFTY 65, SENSEX 20),
  within the freeze quantity, prices on the 0.05 tick, product MIS or NRML,
  buy to open only (selling an option you do not hold is writing it: blocked),
  `fno.max_lots`, `fno.max_premium_inr`, and no new entry in a contract on its
  expiry day after `fno.expiry_no_entries_after` (13:00). The loss is measured
  to the SL order's limit price, the worse fill.
- **short:** selling more than you hold, unless `"allow_short": true`.
- **entries also:** blocked list, size limits, position cap, cash buffer
  (or margin when `allow_margin` is false), duplicates, orders per day, no
  stop, max loss per trade (qty x risk + the costs nse-budget estimated),
  reward:risk, daily loss limit, trades per day, and the window: before
  `no_entries_before` (09:30), after `no_entries_after` (14:45), weekends,
  NSE holidays, outside 9:15 to 15:30.

An exit (a sell that only reduces what you hold) is always allowed through
apart from format, asset and short checks: getting out must always be
possible.

## Steps

1. Run `check.py` after `/nse-budget --write`.
2. Report PASS or BLOCK per order with the reasons in plain words.
3. A BLOCK is final for that order: fix the order or the rules, then check
   again. Never edit `trader/state/risk.json` by hand.
4. PASS: hand off to `/nse-broker`.

## What it never does

It never places, edits or "fixes" an order, and never passes an order it did
not check today.

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
