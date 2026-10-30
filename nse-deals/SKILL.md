---
name: nse-deals
description: >-
  Bulk and Block Deals Tracker for NSE (the Indian answer to tracking
  big-money trades). Reads NSE's daily bulk-deal and block-deal files: who
  bought or sold big blocks of which stock, how many shares, at what price,
  worth how many crore, and net by stock; flags deals in your watchlist, plan
  or portfolio; filters by symbol, client name, side or size; shows only new
  deals on a schedule. Use when the user says "bulk deals", "block deals",
  "who bought", "what are the big funds doing", "FII buying", "promoter
  selling", "did anyone buy RELIANCE in bulk".
argument-hint: "[--tickers SYM ...] [--watch] [--client NAME] [--min-value CRORE]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-deals

The Deals Tracker reads the trades that are big enough to be reported by
name: bulk deals (one client's trades in a stock above 0.5% of its listed
shares in a day) and block deals (large negotiated trades in NSE's separate
block-deal windows).

```bash
python3 "${CLAUDE_SKILL_DIR}/deals.py"                              # today's bulk + block deals, biggest first
python3 "${CLAUDE_SKILL_DIR}/deals.py" --watch                      # only your watchlist, plan and portfolio
python3 "${CLAUDE_SKILL_DIR}/deals.py" --tickers RELIANCE ADANIENT
python3 "${CLAUDE_SKILL_DIR}/deals.py" --client "mutual fund" --side buy
python3 "${CLAUDE_SKILL_DIR}/deals.py" --min-value 25               # ₹25 crore and up
python3 "${CLAUDE_SKILL_DIR}/deals.py" --new                        # for a schedule: only unseen deals
python3 "${CLAUDE_SKILL_DIR}/deals.py" --json
```

## Sources

`https://nsearchives.nseindia.com/content/equities/bulk.csv` and
`block.csv`, the latest trading day, published after the session. Columns are
matched by name. NSE sometimes refuses scripts (HTTP 403): then ask the user to
download the CSVs from nseindia.com (Market data > Bulk & block deals) and run
`deals.py --offline FOLDER`.

## Reading it honestly

- Every buy had a seller. A fund buying is news; it is not a signal.
- The same client on both sides of a stock on the same day is usually an
  intermediary or arbitrage, not a view.
- Promoter or promoter-group selling, and pledges, are worth a look in
  `/nse-news`; a block deal between two named funds at the same price is often
  just a transfer.
- Deals are reported after the fact: by the time you read them the price has
  already moved.

## Steps

1. Run `deals.py` (or `--watch`). Lead with deals in the user's own stocks,
   then the biggest by value.
2. Summarise net buying or selling by stock in a sentence.
3. For a daily habit, schedule `deals.py --new --watch` after 18:00 IST.

## What it never does

It never suggests copying a trade, never infers why a fund traded, and never
names a deal it did not read in NSE's file.

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
