---
name: nse-analyst
description: >-
  Earnings Analyst for Indian listed companies. Lays out what changed quarter
  by quarter (Indian fiscal quarters, Q1 = April-June): revenue, operating
  and net margins, net profit, diluted EPS, growth q/q and y/y, in rupees
  crore, from Yahoo's fundamentals series, and finds the latest results
  filing in NSE's Financial Results feed. Use when the user says "how were
  RELIANCE's results", "earnings", "quarterly numbers", "did profit grow",
  "Q2 results", or before trading a stock around its results.
argument-hint: "[SYMBOL ...] [--quarters 6]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-analyst

The Earnings Analyst reads the numbers, not the headlines.

```bash
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE
python3 "${CLAUDE_SKILL_DIR}/facts.py" TCS INFY --quarters 8
python3 "${CLAUDE_SKILL_DIR}/facts.py" HDFCBANK --json
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE TCS INFY --metrics trader/metrics.json
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE --as-of 2026-10-15   # only quarters due by then
```

`--as-of` keeps a quarter only once SEBI's results deadline has passed (45
days after the quarter, 60 for March), so a past-dated analysis never sees
later results; a company that filed early is still left out until then.

## Sources and caveats

- Quarterly figures: Yahoo Finance's fundamentals time series for
  `SYMBOL.NS` (free, unofficial). Usually the consolidated numbers. They can
  arrive days after the filing, or be missing for smaller companies.
- The filing: NSE's `Financial_Results.xml` RSS, newest first. That PDF is
  the source; when a number matters, open it (Claude can read the PDF).
- Indian companies file standalone AND consolidated results; say which one a
  number is. Banks and NBFCs have no comparable "revenue" or operating
  margin; read their NII, NIM and asset quality from the filing instead.
- Amounts in ₹ crore (1 crore = 10 million). Growth from a loss is left blank.

## Steps

1. Run `facts.py SYMBOL`. Lead with the latest quarter: revenue and net
   profit growth y/y, margin, EPS.
2. Point to the NSE filing link. If the latest quarter on Yahoo is older
   than a filing in the NSE feed, say Yahoo has not caught up.
3. Before an intraday trade, check `/nse-news` for a results date or board
   meeting today: results days gap.

## What it never does

It never calls a stock cheap, expensive, a buy or a sell.

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
