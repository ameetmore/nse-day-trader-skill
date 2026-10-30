---
name: nse-entry
description: >-
  Entry Timer for NSE. Watches a setup bar by bar on free Yahoo 1-minute or
  5-minute .NS bars and tells you the moment to get in: the first completed
  bar that CLOSES above the 15-minute opening range (9:15 to 9:30 IST) or
  above a level you give, with an optional volume check. Says waiting and how
  far, triggered with the time and price, expired (no entries after 14:45 by
  default), or not open yet, and writes trader/entry.json for /nse-exit. Long
  side only; never places an order. Use when the user says "tell me when to
  get in", "watch RELIANCE", "has it broken out", "entry signal", "check my
  watchlist", or after /nse-scanner and /nse-news.
argument-hint: "[SYMBOL] [--setup orb|level] [--interval 5m|1m]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-entry

The Entry Timer turns a setup into one moment: the bar that confirms it. A
price that pokes above the high in the middle of a bar is not an entry. A bar
that CLOSES above it is. It never buys anything.

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE                  # 15-minute opening range, 5-minute bars
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --write          # also save trader/entry.json
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TCS --setup level --level 3120.50
python3 "${CLAUDE_SKILL_DIR}/entry.py" check INFY --interval 1m --min-volume-x 1.5
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch RELIANCE --until 14:45    # one line per closed bar
python3 "${CLAUDE_SKILL_DIR}/entry.py" watchlist                       # every hit in trader/watchlist.json
```

Other flags: `--or-minutes N` (15), `--json`, `--offline FILE` (saved Yahoo
chart JSON or a folder of `<SYMBOL>.json`), `--now "2026-10-29 09:45"` (IST).

## The rule

- **Opening range (orb):** the high and low of 9:15 to 9:30 (the 9:15, 9:20
  and 9:25 five-minute bars). The 9:15 bar follows NSE's 9:00-9:08 pre-open
  auction, so it often carries a big share of the morning's volume.
- **Trigger:** the first completed bar after the range that CLOSES above the
  level. A close exactly at the level is not above it.
- **Time:** that bar's close time (the 9:35 bar closes at 9:40 AM). Price: its
  close, to the paisa.
- **Window:** no entries before 09:30 or after 14:45 (`no_entries_before`,
  `no_entries_after` in `trader/config.json`), leaving time to be flat by
  15:10, before the broker's own auto square-off.
- Weekends and NSE holidays: closed. Muhurat trading is not modelled.

## Steps

1. Check `/nse-news` for the symbol first: a results day can gap past stops.
2. Run `entry.py check SYMBOL` and say the status in one line.
3. To wait for it, run `entry.py watch SYMBOL --until 14:45` in the
   background, or `check --write` on a schedule every 5 minutes.
4. When it triggers, say the time and the price and that nothing was placed.
   If the trigger is more than a bar old, say that a late entry is a
   different trade.
5. Hand off to `/nse-exit` to set the stop and target BEFORE anything is
   bought. A stock locked at its upper circuit can trigger here and still be
   impossible to buy: say so if the user mentions a circuit.

## What it never does

It never places an order, sizes a position or sets the stop, never moves the
level after the fact, and never runs `/nse-broker` from a background watch:
nobody is there to say yes.

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
