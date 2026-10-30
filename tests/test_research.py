"""nse-technicals, nse-journal and nse-research, offline."""

import json
import math
import os
import shutil
import tempfile
import unittest

from _load import FIX, ROOT, load, run

DAILY = os.path.join(FIX, "daily")


def slurp(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def bars_from(xs):
    return [{"date": "2026-01-%02d" % (i + 1), "o": x, "h": x + 1, "l": x - 1, "c": x, "v": 100} for i, x in enumerate(xs)]


class Indicators(unittest.TestCase):
    def setUp(self):
        self.ta = load("nse-technicals", "indicators")

    def test_known_values(self):
        ta = self.ta
        self.assertEqual(ta.sma([1, 2, 3, 4], 2), 3.5)
        self.assertIsNone(ta.sma([1, 2], 3))
        self.assertEqual(ta.rsi(list(range(1, 30))), 100.0)              # only gains
        self.assertAlmostEqual(ta.rsi(list(range(30, 1, -1))), 0.0)      # only losses
        flat = [10.0] * 40
        m, s, h = ta.macd(flat)
        self.assertAlmostEqual(m, 0.0)
        self.assertAlmostEqual(h, 0.0)
        mid, up, lo = ta.bollinger([1.0, 3.0] * 10)
        self.assertAlmostEqual(mid, 2.0)
        self.assertAlmostEqual(up - mid, 2.0)                             # sd 1, k 2
        self.assertAlmostEqual(ta.atr(bars_from([10.0] * 20)), 2.0)       # high - low = 2 every day
        b = bars_from([10.0] * 25)
        b[-1]["v"] = 1900                                                 # one heavy day at the same price
        self.assertAlmostEqual(ta.vwma(b), 10.0)

    def test_ema_seed_and_recursion(self):
        xs = [float(x) for x in range(1, 41)]
        e = self.ta.ema_series(xs, 10)
        k = 2 / 11.0
        manual = sum(xs[:10]) / 10
        for x in xs[10:]:
            manual = x * k + manual * (1 - k)
        self.assertAlmostEqual(e[-1], manual)

    def test_point_in_time(self):
        rc, out, err = run("nse-technicals", "indicators", ["snapshot", "DEMO", "--offline", DAILY,
                                                            "--as-of", "2026-10-15", "--json"], ROOT)
        self.assertEqual(rc, 0, err)
        d = json.loads(out)["DEMO"]
        self.assertEqual(d["date"], "2026-10-15")
        self.assertTrue(all(c[0] <= "2026-10-15" for c in d["recent_closes"]))

    def test_unfinished_session_is_dropped(self):
        import datetime
        bars = bars_from([10.0] * 3)
        bars[-1]["date"] = "2026-10-29"
        kept = self.ta.cut(bars, now_utc=datetime.datetime(2026, 10, 29, 6, 0))     # 11:30 IST
        self.assertEqual(len(kept), 2)
        kept = self.ta.cut(bars, now_utc=datetime.datetime(2026, 10, 29, 10, 30))   # 16:00 IST
        self.assertEqual(len(kept), 3)

    def test_regime(self):
        rc, out, err = run("nse-technicals", "indicators", ["regime", "--offline", DAILY, "--as-of", "2026-10-29",
                                                            "--json"], ROOT)
        self.assertEqual(rc, 0, err)
        r = json.loads(out)
        self.assertRegex(r["label"], r"^(uptrend|downtrend|mixed), (low|normal|high) volatility$")
        self.assertTrue(9 <= r["vix"] <= 30)


class Journal(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "trader", "research"))
        self.j = load("nse-journal", "journal")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def jr(self, *args):
        return run("nse-journal", "journal", list(args), self.dir)

    def test_parse_rating(self):
        p = self.j.parse_rating
        self.assertEqual(p("# X\n\nRating: Overweight\n## Research manager\nRecommendation: Buy"), "Overweight")
        self.assertEqual(p("- **Rating**: sell"), "Sell")
        self.assertEqual(p("**Rating Scale** (use exactly one):\nRating: Hold"), "Hold")
        self.assertIsNone(p("Rating: Buy\nFinal rating: Sell"))          # two calls that disagree
        self.assertIsNone(p("Operating margin: Sell-side estimates"))
        self.assertIsNone(p("We like it a lot."))
        self.assertEqual(p("Rating：Buy"), "Buy")                   # fullwidth colon, NFKC

    def test_window_counts_trading_days_after_the_decision(self):
        series = {"2026-10-15": 100, "2026-10-16": 101, "2026-10-19": 102, "2026-10-21": 103, "2026-10-22": 104,
                  "2026-10-23": 105, "2026-10-26": 106}
        self.assertEqual(self.j.window(series, "2026-10-15", 5, "2026-10-30"), ("2026-10-16", 101, "2026-10-26", 106))
        self.assertIsNone(self.j.window(series, "2026-10-15", 6, "2026-10-30"))
        self.assertIsNone(self.j.window(series, "2026-10-15", 5, "2026-10-26"))  # today's bar is not done

    def test_hits(self):
        h = self.j.hit
        self.assertTrue(h("Buy", 0.5))
        self.assertFalse(h("Overweight", -0.1))
        self.assertTrue(h("Sell", -3))
        self.assertTrue(h("Hold", 1.5))
        self.assertFalse(h("Hold", -2.5))

    def test_record_settle_reflect_score(self):
        with open(os.path.join(self.dir, "trader", "research", "DEMO-2026-10-15.md"), "w", encoding="utf-8") as fh:
            fh.write("# DEMO research, 2026-10-15\n\nRating: Overweight\n")
        self.assertEqual(self.jr("record", "--from", "trader/research/DEMO-2026-10-15.md")[0], 0)
        rc, out, _ = self.jr("settle", "--offline", DAILY, "--today", "2026-10-30")
        self.assertEqual(rc, 0, out)
        doc = json.loads(slurp(os.path.join(self.dir, "trader", "journal.json")))
        e = doc["entries"][0]
        self.assertEqual((e["from"], e["to"]), ("2026-10-16", "2026-10-26"))     # 10-20 is Dussehra
        self.assertAlmostEqual(e["alpha_pct"], round(e["return_pct"] - e["nifty_pct"], 2), places=2)
        ta = load("nse-technicals", "indicators")
        bars, _ = ta.parse_bars(slurp(os.path.join(DAILY, "DEMO-1y-1d.json")), "DEMO")
        c = {b["date"]: b["c"] for b in bars}
        self.assertAlmostEqual(e["return_pct"], round(100 * (c["2026-10-26"] / c["2026-10-16"] - 1), 2))
        rc, out, err = self.jr("reflect", "--id", e["id"], "--lesson", "short")
        self.assertEqual(rc, 2)
        self.assertEqual(self.jr("reflect", "--id", e["id"], "--lesson",
                                 "The call lagged NIFTY by %.2f%% over five days. Check the regime first." % abs(e["alpha_pct"]))[0], 0)
        rc, out, _ = self.jr("lessons", "DEMO")
        self.assertIn("Check the regime first", out)
        self.jr("trade", "--symbol", "DEMO", "--date", "2026-10-29", "--pnl", "-1213.95", "--r", "-1")
        rc, out, _ = self.jr("score", "--json")
        s = json.loads(out)
        self.assertEqual(s["ratings"]["Overweight"]["n"], 1)
        self.assertEqual(s["trades"]["n"], 1)
        self.assertEqual(s["trades"]["net"], -1213.95)

    def test_unreadable_rating_is_review(self):
        with open(os.path.join(self.dir, "r-DEMO-2026-10-15.md"), "w", encoding="utf-8") as fh:
            fh.write("Rating: Buy\nFinal rating: Sell\n")
        rc, out, _ = self.jr("record", "--from", "r-DEMO-2026-10-15.md", "--symbol", "DEMO")
        self.assertEqual(rc, 1)
        self.assertIn("REVIEW", out)
        rc, out, _ = self.jr("settle", "--offline", DAILY, "--today", "2026-10-30")
        self.assertIn("Nothing to settle", out)

    def test_pending_inside_window(self):
        self.jr("record", "--symbol", "DEMO", "--date", "2026-10-27", "--rating", "Buy")
        rc, out, _ = self.jr("settle", "--offline", DAILY, "--today", "2026-10-30")
        self.assertEqual(rc, 1)
        self.assertIn("still inside", out)


REPORT = """# DEMO research, 2026-10-29

Rating: Overweight

## Executive summary
Results beat; the trend is intact above the 200-day.

## Analyst reports
### Technical
RSI 14 47.7.
### Fundamentals
Revenue +8.9% y/y.
### News and events
Results and a dividend filed.
### Flows and sentiment
A bulk buy of 2,50,000 shares.

## Bull case
Growth.
## Bear case
Below the 50-day.
## Research manager
Recommendation: Overweight. The results outweigh the soft momentum.
## Trader plan
Build over a week, stop under the 200-day.
## Risk debate
Aggressive, conservative, neutral.
## Portfolio manager
Overweight.
## What would change the call
A close under 1,268.
## Sources
bundle.md. Not investment advice.
"""


class Research(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_gather_point_in_time(self):
        rc, out, err = run("nse-research", "research", ["gather", "DEMO", "--as-of", "2026-10-29", "--fixtures", FIX],
                           self.dir)
        self.assertEqual(rc, 0, err)
        with open(os.path.join(self.dir, "trader", "research", "DEMO-2026-10-29", "bundle.json"), encoding="utf-8") as fh:
            b = json.load(fh)
        p = b["parts"]
        self.assertEqual(p["technicals"]["date"], "2026-10-29")
        self.assertTrue(p["regime"]["label"])
        labels = [q["label"] for q in p["fundamentals"]["quarters"]]
        self.assertNotIn("Q2 FY27 (Sep 2026)", labels)         # its results deadline is after 2026-10-29
        self.assertEqual(labels[0], "Q1 FY27 (Jun 2026)")
        self.assertTrue(any("Outcome of Board Meeting" in i["title"] for i in p["news"]["items"]))
        self.assertEqual({d["symbol"] for d in p["flows"]["deals"]}, {"DEMO"})
        self.assertIn("6 of 6 parts", out)
        self.assertIn("## Technicals", slurp(os.path.join(self.dir, "trader", "research", "DEMO-2026-10-29", "bundle.md")))

    def test_news_window_ends_at_the_as_of_close(self):
        rc, out, err = run("nse-research", "research", ["gather", "DEMO", "--as-of", "2026-10-27", "--fixtures", FIX],
                           self.dir)
        with open(os.path.join(self.dir, "trader", "research", "DEMO-2026-10-27", "bundle.json"), encoding="utf-8") as fh:
            items = json.load(fh)["parts"]["news"]["items"]
        self.assertFalse(any(i["time"] and i["time"] > "2026-10-27T10:00" for i in items))

    def test_check_and_save(self):
        path = os.path.join(self.dir, "draft.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(REPORT)
        rc, out, _ = run("nse-research", "research", ["check", path], self.dir)
        self.assertEqual(rc, 0, out)
        rc, out, _ = run("nse-research", "research", ["save", "DEMO", path, "--date", "2026-10-29"], self.dir)
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "trader", "research", "DEMO-2026-10-29.md")))
        doc = json.loads(slurp(os.path.join(self.dir, "trader", "journal.json")))
        self.assertEqual(doc["entries"][0]["rating"], "Overweight")

    def test_check_catches_problems(self):
        path = os.path.join(self.dir, "bad.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(REPORT.replace("## Bear case\nBelow the 50-day.\n", "").replace(
                "Rating: Overweight", "Rating: Buy\nFinal rating: Sell") + "\nA sure shot.\n")
        rc, out, _ = run("nse-research", "research", ["check", path], self.dir)
        self.assertEqual(rc, 1)
        self.assertIn("Bear case", out)
        self.assertIn("rating", out)
        self.assertIn("promises", out)

    def test_committee_reference_ships(self):
        with open(os.path.join(ROOT, "nse-research", "references", "committee.md"), encoding="utf-8") as fh:
            text = fh.read()
        for seat in ("Technical analyst", "Bull researcher", "Bear researcher", "Research manager", "Aggressive",
                     "Conservative", "Neutral", "Portfolio manager", "TradingAgents"):
            self.assertIn(seat, text)


if __name__ == "__main__":
    unittest.main()
