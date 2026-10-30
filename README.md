# The NSE Day Trader skill

11 Claude skills for intraday trading on India's NSE and BSE: scan NIFTY charts
for setups, track NSE filings and news, time every entry and exit on NSE's tick
grid, size every trade after Indian trading costs, and replay every outcome
before you risk a rupee.

Free, MIT, no signup, no API key for the analysis. The tools are plain Python
(standard library only) that read free public data: NSE's own lists, RSS feeds
and bulk/block deal files, and Yahoo Finance `.NS` charts.

And no order goes through until you say yes. Nothing in this pack can place an
order on its own. Paper trading is the default.

> Adapted for India from Jake Schincariol's
> [Day Trader skill](https://github.com/Jakeschincariol/day-trader-skill)
> (MIT), which is built for US stocks. Same pipeline and safety gates, rebuilt
> for the NSE clock, rupees, Indian costs, NSE filings and Zerodha Kite.

## Before you start

SEBI's own study found that about **7 in 10 individual intraday traders in the
equity cash segment lost money in FY23**. These skills make the odds and the
costs visible; they do not change them. This is education and tooling, not
investment advice, and nobody involved is a SEBI-registered adviser.

## Install

Paste this into Claude:

```
https://github.com/ameetmore/nse-day-trader-skill

install skill
```

Or as a plugin, in Claude Code:

```
/plugin marketplace add ameetmore/nse-day-trader-skill
/plugin install nse-day-trader-skill@nse-day-trader-skill
```

Or copy the folders:

```bash
git clone https://github.com/ameetmore/nse-day-trader-skill.git
cp -r nse-day-trader-skill/nse-* ~/.claude/skills/
```

Python 3.8 or newer. Nothing to pip install. Then copy
`nse-budget/config.example.json` to `trader/config.json` in your project and
set your budget and limits in rupees.

## The eleven

| command | job | what it does |
| --- | --- | --- |
| `/nse-scanner` | Chart Scanner | Scans NIFTY 50/100/200/500 or every EQ-series stock: daily setups before 9:15, opening-range breakouts after 9:30. |
| `/nse-news` | News Monitor | Yahoo headlines plus NSE's own announcements, results and board-meeting feeds for your stocks; flags results, dividends, bonus, splits, SEBI matters. |
| `/nse-entry` | Entry Timer | Watches a setup bar by bar and calls the first 5-minute close above the 9:15-9:30 range. |
| `/nse-exit` | Exit Planner | Sets the stop and target before you enter, rounded onto NSE's tick grid; flat by 15:10. |
| `/nse-timemachine` | Time Machine | Replays the rest of the session 10,000 times from the stock's own last ~59 sessions, plus every real past day the setup fired. |
| `/nse-budget` | Budget Manager | Sizes the position to your max loss in rupees after brokerage, STT, exchange, SEBI, stamp duty and GST. |
| `/nse-risk` | Risk Manager | PASS or BLOCK: max loss with costs, daily loss, trades a day, entry window, holidays, ticks, no F&O by default. |
| `/nse-broker` | Order Executor | Zerodha Kite tickets (entry, SL-M stop, LIMIT target), your yes word for word, paper by default. |
| `/nse-alerts` | Price Alerts | Rings on the stop, the target, a % move, the opening bell and the 15:10 flat-by. |
| `/nse-analyst` | Earnings Analyst | Quarterly revenue, margins, net profit and EPS in ₹ crore, Indian fiscal quarters, plus the NSE results filing. |
| `/nse-deals` | Deals Tracker | NSE's daily bulk and block deals: who bought and sold big, net by stock, flags your stocks. |

## How it fits together

Everything lands in a `trader/` folder in your project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by 15:10                                           (while it is open)
news / analyst / deals                                                         (on a schedule)
```

## An example trade

The repo's tests run this whole chain offline on **synthetic** data (a made-up
stock, DEMO, built by `tests/make_fixtures.py`), Thursday 29 October 2026:

1. **`/nse-scanner`** at 10:15: DEMO closed above its 9:15-9:30 range (1,402.85
   to 1,408.37).
2. **`/nse-news`**: results and a dividend were filed on NSE at 8:02 and 8:05.
   A results morning can gap, so it says so.
3. **`/nse-entry`**: triggered at 9:40 at ₹1,409.49, the first 5-minute close
   above the range.
4. **`/nse-exit`**: stop at the range midpoint, 1,405.61 rounded down to the
   ₹0.10 tick = **₹1,405.60**; 1R target **₹1,413.40**; flat by 15:10.
5. **`/nse-timemachine`**: 10,000 replays to 15:10 (seed 19) plus the same rule
   on the last 59 real sessions. Its verdict is printed in plain words.
6. **`/nse-budget`** with ₹5,00,000 and ₹2,500 max loss a trade: 266 shares,
   bound by the 75% position cap. Loss at the stop ₹1,034.74 plus about
   ₹179 of costs = **-₹1,213.95**. Gain at the target after costs:
   **+₹859.77**. A 1R trade has to win about 59% of the time just to break
   even. That is the kind of thing this pack is built to show you.
7. **`/nse-risk`**: PASS, with every limit and today's totals.
8. **`/nse-broker`**: the ticket in plain words and the three Kite calls
   (MARKET entry, then SL-M stop and LIMIT target once it fills). You type yes
   for that exact order. In paper mode the fill is recorded locally.
9. **`/nse-alerts`**: rings on the stop, the target and at 15:10.

## What is different from the US version

| | US original | this pack |
| --- | --- | --- |
| Clock | 9:30-16:00 ET, US DST | 9:15-15:30 IST, no DST; NSE 2026 holidays |
| Universe | Nasdaq Trader lists | NSE NIFTY index lists or `EQUITY_L.csv`, EQ series only |
| Prices | cents | NSE tick bands (₹0.01 to ₹5 by price) |
| Costs | zero commission | brokerage, STT, exchange, SEBI, stamp duty, GST |
| Flat by | 15:55 | 15:10, before Zerodha's auto square-off (15:12 / 15:25, ₹50 + GST) |
| Filings | SEC 8-K, XBRL | NSE announcements, results and board-meeting feeds |
| Big-money tracker | Congress trades | NSE bulk and block deals |
| Broker | Alpaca MCP, paper account | Zerodha Kite MCP; Zerodha has no paper account, so paper is local |
| Order shape | bracket order | entry + SL-M + LIMIT (Kite retired bracket orders) |

## Zerodha Kite

Zerodha's official MCP server is
[github.com/zerodha/kite-mcp-server](https://github.com/zerodha/kite-mcp-server).
The hosted endpoint `https://mcp.kite.trade/mcp` needs no API key; you log in
through its `login` tool. The hosted version may leave out order placement.
To place orders through the API you run the server yourself with your own
Kite Connect key, and SEBI's rules require a registered static IP for API
orders from 1 April 2026. Set `place_order`, `modify_order`, `cancel_order`
and the GTT tools to **Needs approval** in Claude. `/nse-broker` walks
through it.

## The tools

```bash
python3 nse-scanner/scan.py universe                                # NIFTY 500 -> trader/universe.txt
python3 nse-scanner/scan.py orb --at 10:15                          # opening-range breakouts so far
python3 nse-news/news.py --tickers RELIANCE TCS --hours 12          # headlines, NSE filings, today's move
python3 nse-entry/entry.py check RELIANCE --setup orb               # waiting / triggered / expired
python3 nse-exit/exit.py plan --stop or-mid --target 2R --write     # -> trader/plan.json
python3 nse-timemachine/timemachine.py run --write                  # 10,000 replays + the history
python3 nse-budget/size.py --write                                  # -> trader/orders.json
python3 nse-risk/check.py                                           # PASS / BLOCK per order
python3 nse-broker/ticket.py show                                   # the Kite tickets, READY or not
python3 nse-alerts/alerts.py add --from-plan                        # stop, target, flat by 15:10
python3 nse-analyst/facts.py RELIANCE                               # quarters, growth, EPS
python3 nse-deals/deals.py --watch                                  # bulk and block deals in your stocks
```

```bash
python3 -m unittest discover -s tests -v      # 52 tests, offline
python3 tests/make_fixtures.py                # rebuild the synthetic fixtures
```

The tests run offline on synthetic fixtures in the exact shape of Yahoo's and
NSE's answers. They check the clock, the tick grid, the cost arithmetic, the
risk rules and every hand-off between skills; they say nothing about whether
any strategy makes money.

## Known limits

- **Data:** Yahoo's `.NS` charts are free and unofficial and can lag. NSE's
  archives sometimes refuse scripts (HTTP 403); every NSE-reading tool then
  says so and accepts a CSV or XML you saved from nseindia.com with `--offline`.
- **Holidays:** 2026 is built in. Add 2027 when NSE publishes its circular.
  Muhurat trading is not modelled.
- **Ticks:** the default bands follow NSE's 2025 circular; NSE reviews each
  stock's band, so near a boundary check the stock's tick or set `tick_size`.
- **Circuits and surveillance:** price bands, upper/lower circuits and ASM/GSM
  lists can stop a stop from filling. The pack warns about this; it does not
  read the lists.
- **Longs only, cash equity only.** No F&O, no shorts unless you change the
  config, and then with your eyes open.

## Safety

- Paper trading by default (`"paper": true`); live is your own decision.
- Only `/nse-broker` can lead to an order, and only after three gates: the
  risk check passed that exact order today, you typed yes for that one order,
  and you clicked Allow once on Claude's own card.
- Kite keys stay in environment variables or the MCP server's config, never in
  the chat.

## License

MIT. Original work © 2026 Jake Schincariol; NSE/BSE adaptation © 2026 ameetmore.
