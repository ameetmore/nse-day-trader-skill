---
name: nse-research
description: >-
  Research Committee for NSE stocks, adapted from TradingAgents' multi-agent
  design with Claude in every seat: four analysts (technical, fundamentals,
  news and events, flows and sentiment), a bull versus bear debate, a
  research manager's verdict, a trader's plan, an aggressive / conservative /
  neutral risk debate and a portfolio manager's final 5-tier rating (Buy,
  Overweight, Hold, Underweight, Sell), all grounded in an evidence bundle
  from the pack's own tools and the journal's past lessons; then filed and
  scored by /nse-journal. Point in time with --as-of. Use when the user says
  "research RELIANCE", "should I buy", "analyse TCS", "bull and bear case",
  "full analysis", "investment committee", "deep dive", or to vet a scanner
  pick before trading it.
argument-hint: "[SYMBOL] [--as-of YYYY-MM-DD] [--rounds 2]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-research

The Research Committee turns one stock into one committed, written call. It
follows TradingAgents' structure (Tauric Research): analysts report, a bull
and a bear argue, a manager judges, a trader plans, three risk views argue,
and a portfolio manager decides. Here Claude plays every seat, from evidence
the pack's own tools gather, with no extra model or API key. Read
`references/committee.md` for each seat's brief and the report template
before starting.

```bash
python3 "${CLAUDE_SKILL_DIR}/research.py" gather RELIANCE                   # evidence -> trader/research/RELIANCE-<date>/
python3 "${CLAUDE_SKILL_DIR}/research.py" gather RELIANCE --as-of 2026-10-15  # a past-dated, point-in-time run
python3 "${CLAUDE_SKILL_DIR}/research.py" check trader/research/RELIANCE-2026-10-30.md
python3 "${CLAUDE_SKILL_DIR}/research.py" save RELIANCE trader/research/RELIANCE-2026-10-30.md
```

`gather` calls `nse-technicals` (indicators and the NIFTY / India VIX regime),
`nse-analyst` (quarters), `nse-news` (72 hours of headlines and NSE filings),
`nse-deals` (bulk and block deals) and `nse-journal` (past lessons) and writes
`bundle.md` and `bundle.json`. The whole pack must be installed side by side.

## Steps

1. **Gather.** Run `research.py gather SYMBOL`. Tell the user in one line
   which parts came back and which are missing.
2. **Analysts.** Write the four short reports from the bundle (in parallel
   with subagents if available, each given the bundle's path). Quote numbers
   exactly as the bundle prints them.
3. **Debate.** Bull, then bear, replying to each other, for 2 rounds (or what
   the user asked for). Each turn answers the other side's last point with a
   number.
4. **Research manager.** Judge the debate: commit to the stronger side; Hold
   only if it is genuinely balanced or the evidence is thin.
5. **Trader.** Action, horizon, entry zone, stop (ATR is the yardstick), size
   in words.
6. **Risk debate.** Aggressive, conservative, neutral, one round plus replies.
   Bring in the regime and the journal's lessons.
7. **Portfolio manager.** The final 5-tier rating and why; what would change it.
8. **Write and save.** Write the report from the template in
   `references/committee.md` to `trader/research/<SYMBOL>-<DATE>.md`, run
   `research.py save SYMBOL <file>` (it checks every section and the single
   rating line, then records it in the journal). Fix anything `check` reports.
9. **Answer.** Give the user the rating, the 3-5 sentence summary and the
   strongest point on each side. Offer the next step: for an intraday idea,
   `/nse-entry` and the rest of the trade pipeline; for a longer view, nothing
   more is needed now: the journal will score it.

## Discipline

- **Every number from the bundle.** Nothing from memory, nothing invented for
  a missing part.
- **Point in time:** with `--as-of`, write as if it is that day's close.
- **Commit.** Conflict between seats is the job, not a reason for Hold.
- **One rating line** in the report ("Rating: X"); mention other seats'
  recommendations in prose.
- **Long horizons are not the pack's specialty.** Say what horizon the call is
  for; the journal scores 5 trading days by default (`--horizon` to change).
- **Backtesting the committee:** run it with `--as-of` on several past dates,
  save each, and let `journal.py settle` and `score` grade them. That is
  TradingAgents' backtest, done by hand and honestly small.

## What it never does

It never places or proposes an order by itself (orders only go through
`/nse-budget`, `/nse-risk` and `/nse-broker` with the user's yes), never calls
its rating advice, and never hides a missing input.

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
