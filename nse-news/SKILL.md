---
name: nse-news
description: >-
  News Monitor for NSE stocks. Tracks breaking headlines (Yahoo Finance) and
  NSE's own filing feeds (corporate announcements, financial results, board
  meetings) for every symbol you watch or hold, shows only what is new since
  the last check, tags results, dividends, bonus and splits, deals, SEBI and
  legal items, and prints how far each stock has moved today. Use when the
  user says "any news on RELIANCE", "why is it moving", "check the news",
  "results today", "announcements", "what's new on my watchlist", or after
  /nse-scanner and before /nse-entry.
argument-hint: "[--tickers SYM ...] [--hours 48] [--all]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-news

The News Monitor answers "why is this moving, and did anything just get
filed?" for the stocks on your watchlist, in your plan and in your portfolio.

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                               # watchlist + plan + portfolio
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE TCS INFY
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers HDFCBANK --all --hours 72
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-nse                      # headlines only
python3 "${CLAUDE_SKILL_DIR}/news.py" --json
```

## Sources

| source | what | requests |
| --- | --- | --- |
| Yahoo Finance RSS | headlines for `SYMBOL.NS` | one per symbol |
| NSE `Online_announcements.xml` | every corporate announcement | one for all symbols |
| NSE `Financial_Results.xml` | results filings | one for all symbols |
| NSE `Board_Meetings.xml` | board meetings (results dates, dividends) | one for all symbols |
| Yahoo chart | today's move vs yesterday's close | one per symbol |

An NSE item is yours when its title, text or attachment name carries your
symbol or your company's name (names come from `trader/universe.txt`). NSE
sometimes answers HTTP 403 to scripts: the tool says so and the headlines
still run. `!` marks the items that move stocks: results, board-meeting
outcomes, dividends, bonus, splits, buybacks, QIPs, deals, resignations,
ratings, SEBI and NCLT matters, pledges.

State: `trader/state/news.json` remembers what was shown (30 days), so a
scheduled run shows only new items. `--all` shows everything in the window.

## Steps

1. Run `news.py` (or `--tickers ...`). Lead with anything marked `!` and any
   stock flagged MOVING (3% or more from yesterday's close).
2. If a results date or a board meeting falls inside today's session, say so
   before any intraday trade: results can gap a stock past any stop.
3. Open the filing (the PDF link) before treating a headline as fact.
4. For a schedule: run it every 15 to 30 minutes in market hours; it prints
   only new items and exits 1 when there is nothing new.

## What it never does

It never trades on a headline, never calls a headline bullish or bearish for
the user, and never treats an RSS summary as the filing itself.

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
