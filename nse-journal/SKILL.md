---
name: nse-journal
description: >-
  Decision Journal: the pack's memory. Records every research rating (Buy to
  Sell) and every finished day trade; once a rating's window has traded,
  settles it against its own price and NIFTY 50 (return, alpha, hit or miss);
  keeps a short lesson for each, which /nse-research reads back before the
  next call on that stock; and keeps a scorecard of hit rate and alpha by
  rating and of day-trade results. A report with no readable rating is filed
  as REVIEW, never scored. Use when the user says "how have my calls done",
  "score my trades", "journal this trade", "what did we learn", "track
  record", or after /nse-research and after a trade closes.
argument-hint: "[record|trade|settle|reflect|lessons|score|show]"
---

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

# nse-journal

The Journal is how the pack learns from itself: every call is written down
before the outcome is known, scored when it is, and turned into a lesson.

```bash
python3 "${CLAUDE_SKILL_DIR}/journal.py" record --from trader/research/RELIANCE-2026-10-30.md --horizon 5
python3 "${CLAUDE_SKILL_DIR}/journal.py" record --symbol TCS --date 2026-10-30 --rating Overweight
python3 "${CLAUDE_SKILL_DIR}/journal.py" trade --symbol DEMO --date 2026-10-29 --pnl 859.77 --r 0.71 --note "orb, 1R"
python3 "${CLAUDE_SKILL_DIR}/journal.py" settle                       # score every finished window
python3 "${CLAUDE_SKILL_DIR}/journal.py" reflect --id TCS-2026-10-30-1 --lesson "..."
python3 "${CLAUDE_SKILL_DIR}/journal.py" lessons RELIANCE
python3 "${CLAUDE_SKILL_DIR}/journal.py" score
python3 "${CLAUDE_SKILL_DIR}/journal.py" show --n 20
```

Everything lives in `trader/journal.json`.

## How a rating is scored

- The window starts at the first close AFTER the decision date and runs the
  horizon (5 trading days by default) on NSE's calendar.
- Return = end close / start close - 1. Alpha = return minus NIFTY 50's
  return over the same dates.
- Hit: Buy or Overweight with alpha above 0; Sell or Underweight below 0; Hold
  within 2% of NIFTY.
- A report whose rating line is missing, or which has two rating lines that
  disagree, is REVIEW: recorded, never scored.

## Writing a lesson (after `settle`)

2 to 4 plain sentences: what the alpha says about the call (quote it); which
part of the thesis the window supports or undercuts; one concrete thing to do
differently next time. If 5 days is too short to judge a thesis written for
weeks, say so plainly, or later runs will treat a short window as proof.

## Day trades

After a trade is closed (the fills from `/nse-broker`, net of costs), record
it with `trade --pnl NET --r R`. `score` shows the count, the win rate, the
net rupees and the average R. Fewer than 20 entries tells you almost nothing
about skill; the scorecard says so.

## Steps

1. After `/nse-research` saves a report, it is recorded automatically.
2. Run `settle` on a schedule (daily after 16:00 IST is enough); for each
   settled call, write its lesson with `reflect`.
3. Before a new call on a stock, `/nse-research` reads `lessons SYMBOL`.
4. Use `score` for an honest track record.

## What it never does

It never edits a past decision, never scores a REVIEW entry, and never turns a
small sample into a rule.

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
