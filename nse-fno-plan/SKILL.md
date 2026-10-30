---
name: nse-fno-plan
description: >-
  Option-Buying Planner for NIFTY 50 and SENSEX, intraday. Turns an index
  signal (an opening-range breakout from /nse-entry on ^NSEI or ^BSESN, or
  your levels) into one bought call or put: picks a liquid strike near delta
  0.55, prices the stop and the target from the index levels with
  Black-Scholes, uses an SL stop-limit exit, and sizes whole lots so the loss
  at the stop plus F&O costs stays within your max loss, max lots and premium
  cap; shows the break-even win rate; writes trader/orders.json for /nse-risk
  and /nse-broker. Use when the user says "buy NIFTY call", "SENSEX put",
  "option trade", "how many lots", "option stop loss", or after
  /nse-fno-chain.
argument-hint: "[--index NIFTY|SENSEX] [--direction up|down] [--strike delta:0.55|atm|itm1|otm1]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-fno-plan

> **Read this first.** SEBI's study of FY2025-26 found **87.7% of individual F&O traders lost
> money**, an average net loss of about ₹1.17 lakh each. Bought options lose value every
> minute the index does not move, and most expire worthless. This pack buys NIFTY 50 and
> SENSEX options intraday only, with a stop, a size cap and your yes on every order. It does
> not write (sell) options and does not trade futures.

The planner decides four things before anything is bought: which option, where
it is wrong (the stop), where it is right (the target), and how many lots, so
that being wrong costs no more than you set.

```bash
python3 "${CLAUDE_SKILL_DIR}/plan.py"                          # trader/entry.json + trader/fno/chain-<INDEX>.json
python3 "${CLAUDE_SKILL_DIR}/plan.py" --write                  # -> trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/plan.py" --index NIFTY --direction up --index-entry 25793 --index-stop 25770 --target-r 2
python3 "${CLAUDE_SKILL_DIR}/plan.py" --index SENSEX --direction down --index-entry 84100 --index-stop 84190
python3 "${CLAUDE_SKILL_DIR}/plan.py" --strike atm --stop pct:30
```

## The full intraday flow

1. `/nse-news` and the regime (`nse-technicals regime`): results, RBI, US
   cues, India VIX.
2. Signal on the index: `entry.py check ^NSEI --write` (or `^BSESN`), the
   first 5-minute close above the 9:15-9:30 range. For a put, give
   `--direction down` and your levels.
3. Chain: `/nse-fno-chain` (Kite quotes, then `analyse --write`).
4. Plan: `plan.py --write`. Read back the strike, entry, stop, target, lots,
   loss at the stop with costs, and the break-even win rate.
5. `/nse-risk` (needs `"allow_options": true`), then `/nse-broker` and the
   user's yes.
6. While open: alerts on the INDEX levels (Yahoo has no option quotes):
   `alerts.py add --symbol ^NSEI --below <index stop>` and `--above <index target>`,
   plus the 15:10 flat-by.

## The rules it applies

- **Strike:** default the liquid strike with |delta| nearest 0.55 (slightly
  in the money: less decay per rupee than far out of the money options).
- **Entry:** a LIMIT at the ask, up to the 0.05 tick. Zerodha blocks market
  orders in many option contracts.
- **Stop:** the premium if the index reaches your index stop (Black-Scholes at
  the option's own IV), rounded down to the tick. The exit is an SL
  (stop-limit) order because SL-M is not accepted on index options; its limit
  sits 2% under the trigger, never more than a quarter of the stop distance,
  and the risk is measured to that limit.
- **Target:** the premium if the index reaches your target (default 2x the
  index risk).
- **Lots:** the smallest of max loss after costs, `fno.max_lots` (2),
  `fno.max_premium_inr` (₹30,000), cash after the buffer, and the freeze limit.
- **Expiry day:** it warns; `/nse-risk` blocks new entries in an expiring
  contract after `fno.expiry_no_entries_after` (13:00).
- **Costs (Zerodha options):** ₹20 an order, STT 0.15% of the sell premium
  (from 1 April 2026), exchange 0.03553% NSE / 0.0325% BSE of premium, SEBI
  ₹10 a crore, stamp duty 0.003% on the buy, GST 18%.

## Saying it straight

Always show the user the loss at the stop with costs, the gain at the target,
and the break-even win rate the plan needs. A premium stop is a model:
implied volatility can drop, time decay keeps working, and a fast move can jump
past an SL limit so the stop does not fill. Kite may reject a second exit
order (the target) for margin while the stop is pending: then keep the stop at
Kite and let an index alert ring at the target.

## What it never does

It never sells (writes) options, never trades futures, never holds overnight,
never places an order, and never picks a strike the chain marks as thin.

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
