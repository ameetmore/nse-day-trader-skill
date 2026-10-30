---
name: nse-broker
description: >-
  Order Executor for Zerodha Kite. Shows each approved order as a plain
  ticket (entry, SL-M stop-loss, LIMIT target, max loss with costs) plus the
  exact Kite MCP place_order calls, records your explicit yes word for word,
  and only then lets Claude call Kite (whose place_order tool is set to Needs
  approval, so Claude's Allow once card asks again). Paper by default:
  Zerodha has no paper account, so paper fills are recorded locally. Builds
  the flatten ticket by 15:10 IST, records fills, and covers setting up
  Zerodha's Kite MCP server. Use when the user says "place the order", "buy
  it", "execute", "send it to Zerodha", "close my position", "flatten",
  "connect Kite", or after /nse-risk passes.
argument-hint: "[order number]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-broker

The Order Executor is the only skill in this pack that can lead to a real
order, so it is the strictest. An order reaches the market only after three
gates, every time, for every order:

1. **nse-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.
3. **The user clicked Allow once** on Claude's own permission card, because
   Kite's `place_order` tool is set to "Needs approval".

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                      # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --broker-id ORDER_ID
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --filled-qty 266 --filled-price 1409.60
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol DEMO --side sell --qty 266 --price 1413.40
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol DEMO --qty 266
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to a broker. It renders tickets, checks that a reply
is a real yes for that order, builds the flatten ticket, and keeps the log in
`trader/state/broker.json`.

## Kite has no bracket order

Zerodha retired bracket orders, so one planned trade is three Kite orders:

1. **entry:** `place_order` BUY, `product` MIS, MARKET (or LIMIT).
2. **after the entry fills** (check `get_order_history` / `get_orders` for
   COMPLETE): the **stop-loss**, SELL `SL-M` with `trigger_price` = the stop.
3. **after the entry fills:** the **target**, SELL `LIMIT` at the target.

When one exit fills, **cancel the other** (`cancel_order`), or it can open a
new position the wrong way.

**Index options (NFO / BFO)** from `/nse-fno-plan`: the entry is a LIMIT at the
ask, and the stop is an **SL** (stop-limit, `trigger_price` and `price`), never
SL-M: exchanges do not accept SL-M on index options, and BSE dropped it
altogether. The ticket shows the exact calls. If Kite's RMS rejects the second exit order for
margin, keep the SL-M stop at the broker and let `/nse-alerts` ring at the
target instead. `ticket.py show` prints all three calls with exact arguments.

## Setting up Zerodha's Kite MCP server

Zerodha's official server is github.com/zerodha/kite-mcp-server (MIT).

- **Hosted:** add `https://mcp.kite.trade/mcp` as a custom connector (or, in
  Claude Desktop, `npx mcp-remote https://mcp.kite.trade/mcp`), then call its
  `login` tool and sign in to Kite in the browser. No API key needed. The
  hosted server may leave out order-placing tools for safety; if
  `place_order` is not among the tools, it cannot place orders.
- **Self-hosted (for order placement):** a Kite Connect developer app
  (`KITE_API_KEY`, `KITE_API_SECRET` as environment variables, never in the
  chat), run the server locally, and register your static IP in the
  developer console: SEBI's rules require it for API orders from 1 April 2026.
- In Claude, set `place_order`, `modify_order`, `cancel_order` and the GTT
  tools to **Needs approval**. Never "Always allow".

## Paper and live

`"paper": true` (default): `show` says what would be sent, `approve` records
the yes, and `result --status placed --filled-qty N --filled-price P` records
a simulated fill in `trader/portfolio.json`. Nothing goes to Kite. Live
(`"paper": false`) is the user's own decision in their own config; say
"LIVE, real money" on every ticket.

## Steps

1. Run `ticket.py show`. Present ONE ready ticket in plain words: what, how
   many, stop, target, max loss with costs.
2. Ask for a yes for that one order. Record it with `approve --reply "<their
   exact words>"`. A vague reply ("ok", "sure", "do them all") is refused:
   ask again.
3. Live only: call Kite `place_order` with exactly the entry's arguments; the
   Allow once card is the third gate. Record the outcome with `result`.
4. After the fill, place the SL-M stop (and the target), with the same care.
5. By 15:10, if anything is still open: `ticket.py flatten`, then
   `/nse-risk`, then a yes. Cancel the open exit orders before the flatten
   sell. Zerodha's own auto square-off (15:12 or 15:25) costs ₹50 + GST.
6. When the trade is closed, record it: `/nse-journal` (`journal.py trade
   --pnl NET --r R`), net of costs, and write its one-paragraph lesson.

## What it never does

It never places an order without all three gates, never batches yeses, never
retries a denied order, never changes an order after its risk check, and
never asks for or handles Kite credentials in the chat.

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
