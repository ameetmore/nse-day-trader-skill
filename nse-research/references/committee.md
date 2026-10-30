# The research committee: seats, briefs and the report

The structure follows TradingAgents (Tauric Research, Apache-2.0,
github.com/TauricResearch/TradingAgents): an analyst team, a bull and bear
debate judged by a research manager, a trader's proposal, a three-way risk
debate and a portfolio manager's final rating. The briefs below are written for
this pack: Indian listed stocks, the pack's own tools as the only evidence, and
Claude playing every seat in turn.

## Ground rules for every seat

- **Evidence only from the bundle** (`bundle.md` / `bundle.json` from
  `research.py gather`), plus any filing PDF it links that you open. No number
  from memory. If the bundle says a part is missing, it is missing.
- **Point in time.** With `--as-of`, nothing after that date exists. Do not
  mention later events even if you know them.
- **Quote, do not round into a story.** "RSI 14 47.7" from the snapshot, not
  "momentum is neutral-ish".
- **Each seat argues its brief.** Make the strongest honest case for your side;
  concede what the evidence forces you to concede.
- **Indian context counts:** results dates and SEBI's 45-day filing window,
  promoter holding and pledges, bulk and block deals, F&O ban lists, ASM/GSM
  surveillance and circuit limits, RBI policy, FII/DII flows, the rupee.

## 1. Analyst team (four short reports)

Run them in parallel if subagents are available (one per report, each given
the bundle path), otherwise one after another. Each ends with a 3-5 row table
of its key facts.

- **Technical analyst.** From the technicals and regime: trend (50/200-day),
  momentum (MACD, RSI), volatility (Bollinger, ATR as a % of price), position in
  the 52-week range, volume. Then the market backdrop: NIFTY's trend and India
  VIX. Pick the 4-8 indicators that matter here and say why; skip the rest.
- **Fundamentals analyst.** From the quarters: revenue and net profit growth
  y/y and q/q, margins and their direction, EPS. Name what looks strong and the
  red flags. Banks and NBFCs: say that revenue and operating margin are not
  comparable and point to NII/NIM/asset quality in the filing.
- **News and events analyst.** From the 72 hours of headlines and NSE filings:
  what was announced (results, dividends, bonus, splits, buybacks, QIPs, deals,
  management changes, ratings, regulatory matters), what is scheduled (a board
  meeting date), and the macro tags (RBI, CPI, budget, FII flows).
- **Flows and sentiment analyst.** From the bulk and block deals and the tone
  of the headlines: who bought or sold in size, net by side, whether the same
  client sits on both sides (usually not a view), promoter activity. Rate the
  mood as clearly negative, negative, neutral, positive or clearly positive, with
  a confidence (low/medium/high). Headlines are a thin sample; say so.

## 2. Bull and bear debate (2 rounds by default)

- **Bull researcher:** the strongest evidence-based case for owning the stock:
  growth, quality, positive signals, and a direct answer to the bear's last point.
- **Bear researcher:** the strongest case against: risks, weak or slowing
  numbers, stretched technicals, overhangs (pledges, supply from deals, results
  risk), and a direct answer to the bull's last point.
- Each turn is a reply, not a list: name the other side's point and answer it
  with a number from the bundle.

## 3. Research manager

Judge the debate. Conflict is normal: deciding which side is stronger is the
job, so conflict alone is not a reason to say Hold. Commit to the stronger case,
sized by how clearly it won; say Hold only when the evidence is still balanced
or too thin. Weigh arguments on merit, not on who spoke last. Write:

- **Recommendation:** one of Buy / Overweight / Hold / Underweight / Sell
- **Rationale:** the two or three arguments that decided it
- **Strategic actions:** what the trader should do, sized against a standard
  allocation

## 4. Trader

Turn the plan into a concrete proposal: action (buy / hold / sell / stay out),
the horizon (intraday, a few days, weeks), an entry zone, a stop and why
(the ATR from the snapshot is the natural yardstick), and a size in words.
Prices come from the bundle; the exact stop and size come from `/nse-exit` and
`/nse-budget` if the user wants to act.

## 5. Risk debate (one round each, then a reply round)

- **Aggressive:** argues for the upside the conservative view would miss.
- **Conservative:** argues for protecting capital: gaps, results days, circuits,
  liquidity, the cost of being wrong, the 7-in-10 intraday loss rate.
- **Neutral:** weighs both and the regime (NIFTY trend, India VIX).
Each answers the other two directly.

## 6. Portfolio manager (the final call)

Read the research plan, the trader's proposal, the risk debate and the
journal's lessons. Commit to the stronger case; Hold only if it is genuinely
balanced or thin. Open the report with the rating line.

## The rating scale (use exactly one)

- **Buy:** strong conviction; enter or add
- **Overweight:** favourable; build gradually
- **Hold:** balanced; no action
- **Underweight:** cautious; trim or avoid adding
- **Sell:** strong conviction against; exit or avoid

## The report (save as trader/research/<SYMBOL>-<YYYY-MM-DD>.md)

```markdown
# <SYMBOL> research, <YYYY-MM-DD>

Rating: <Buy | Overweight | Hold | Underweight | Sell>

## Executive summary
The call, the horizon, and how to act on it, in 3-5 sentences.

## Analyst reports
### Technical
### Fundamentals
### News and events
### Flows and sentiment

## Bull case
## Bear case
## Research manager
Recommendation, rationale, strategic actions.

## Trader plan
Action, horizon, entry zone, stop and why, size in words.

## Risk debate
Aggressive, conservative, neutral, and the replies.

## Portfolio manager
The decision and the evidence that decided it.

## What would change the call
The specific facts or price levels that would flip it.

## Sources
The bundle file, the filing links used. Not investment advice.
```

Exactly one line may carry the rating ("Rating: X"). Quote other people's ratings
in prose ("the research manager recommended Overweight") without a "Rating:"
label, or the journal reads two ratings and files the report as REVIEW.
