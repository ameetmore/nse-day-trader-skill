"""Scanner, news, analyst and deals, offline; plus repo hygiene."""

import glob
import json
import os
import re
import shutil
import tempfile
import unittest

from _load import FIX, ROOT, load, run

SKILLS = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "nse-*")))


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class Scanner(Tmp):
    EQUITY = ("SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
              "RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10\n"
              "M&M,Mahindra & Mahindra Limited,EQ,08-NOV-1995,5,1,INE101A01026,5\n"
              "BAJAJ-AUTO,Bajaj Auto Limited,EQ,26-MAY-2008,10,1,INE917I01010,10\n"
              "SOMEBE,Some Trade To Trade Ltd,BE,01-JAN-2020,10,1,INE000X01010,10\n"
              "SMEONE,Some SME Ltd,SM,01-JAN-2022,10,1,INE000Y01010,10\n")

    def test_universe_keeps_eq_only(self):
        scan = load("nse-scanner", "scan")
        kept, counts = scan.build_universe(self.EQUITY)
        self.assertEqual([k for k, _ in kept], ["BAJAJ-AUTO", "M&M", "RELIANCE"])
        self.assertEqual(counts["rows"], 5)

    def test_universe_from_an_index_list_offline(self):
        with open(os.path.join(self.dir, "ind_nifty50list.csv"), "w", encoding="utf-8") as fh:
            fh.write("Company Name,Industry,Symbol,Series,ISIN Code\n"
                     "Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018\n"
                     "Tata Consultancy Services Ltd.,Information Technology,TCS,EQ,INE467B01029\n")
        rc, out, err = run("nse-scanner", "scan", ["universe", "--index", "nifty50", "--offline", self.dir,
                                                   "--out", os.path.join(self.dir, "u.txt")], self.dir)
        self.assertEqual(rc, 0, err)
        with open(os.path.join(self.dir, "u.txt"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().splitlines(), ["RELIANCE|Reliance Industries Ltd.",
                                                      "TCS|Tata Consultancy Services Ltd."])

    def test_yahoo_symbols(self):
        scan = load("nse-scanner", "scan")
        self.assertEqual(scan.to_yahoo("reliance"), "RELIANCE.NS")
        self.assertEqual(scan.to_yahoo("SOMECO.BO"), "SOMECO.BO")
        self.assertEqual(scan.to_yahoo("^NSEI"), "^NSEI")
        self.assertIn("M%26M.NS", scan.chart_path("M&M", "1d", "5m"))
        self.assertEqual(scan.from_yahoo("M&M.NS"), "M&M")

    def test_orb_scan(self):
        rc, out, err = run("nse-scanner", "scan", ["orb", "--offline", os.path.join(FIX, "scanner", "spark-5m-2026-10-29.json"),
                                                   "--now", "2026-10-29 10:15", "--min-price", "0", "--json",
                                                   "--no-write"], self.dir)
        self.assertEqual(rc, 0, err)
        doc = json.loads(out)
        hits = {h["symbol"] for h in doc["hits"]}
        self.assertIn("DEMO", hits)
        self.assertNotIn("FLAT", hits)

    def test_orb_before_the_range_is_done(self):
        rc, out, err = run("nse-scanner", "scan", ["orb", "--offline", os.path.join(FIX, "scanner", "spark-5m-2026-10-29.json"),
                                                   "--now", "2026-10-29 09:25", "--min-price", "0", "--no-write"], self.dir)
        self.assertEqual(rc, 1)
        self.assertIn("9:15", out + err)

    def test_daily_scan_runs(self):
        rc, out, err = run("nse-scanner", "scan", ["daily", "--offline", os.path.join(FIX, "scanner", "spark-3mo-2026-10-28.json"),
                                                   "--now", "2026-10-29 08:30", "--min-price", "0", "--min-volume", "0",
                                                   "--json", "--no-write"], self.dir)
        doc = json.loads(out)
        self.assertEqual(doc["scanned"], 5, err)


class News(Tmp):
    def news(self, *extra):
        return run("nse-news", "news", ["--offline", os.path.join(FIX, "news"), "--now", "2026-10-29T04:30:00Z",
                                        "--dry-run", "--json"] + list(extra), self.dir)

    def test_only_my_symbols_from_nse(self):
        rc, out, err = self.news("--tickers", "DEMO", "FLAT")
        self.assertEqual(rc, 0, err)
        items = json.loads(out)["items"]
        titles = " ".join(i["title"] for i in items)
        self.assertIn("Demo Industries Limited", titles)
        self.assertNotIn("Somebody Else", titles)
        self.assertNotIn("Old story", titles)            # older than 48 hours

    def test_results_are_important(self):
        rc, out, _ = self.news("--tickers", "DEMO")
        items = json.loads(out)["items"]
        res = [i for i in items if i["kind"] == "results"]
        self.assertTrue(res and res[0]["important"])
        self.assertIn("earnings", res[0]["tags"])
        outcome = [i for i in items if "Outcome of Board Meeting" in i["title"]][0]
        self.assertTrue(outcome["important"])
        self.assertIn("capital", outcome["tags"])        # the dividend

    def test_nse_dates_are_ist(self):
        news = load("nse-news", "news")
        t = news.parse_time("29-Oct-2026 08:05:00")
        self.assertEqual((t.hour, t.minute), (2, 35))      # 08:05 IST = 02:35 UTC

    def test_seen_items_show_once(self):
        args = ["--offline", os.path.join(FIX, "news"), "--now", "2026-10-29T04:30:00Z", "--tickers", "DEMO",
                "--state", os.path.join(self.dir, "s.json")]
        rc1, _, _ = run("nse-news", "news", args, self.dir)
        rc2, out2, _ = run("nse-news", "news", args, self.dir)
        self.assertEqual((rc1, rc2), (0, 1))
        self.assertIn("Nothing new", out2)


class Analyst(Tmp):
    def test_quarters_and_growth(self):
        rc, out, err = run("nse-analyst", "facts", ["DEMO", "--offline", os.path.join(FIX, "analyst"), "--json"], self.dir)
        self.assertEqual(rc, 0, err)
        c = json.loads(out)["companies"]["DEMO"]
        q = c["quarters"][0]
        self.assertEqual(q["label"], "Q2 FY27 (Sep 2026)")
        self.assertEqual(q["revenue_yoy"], 15.3)         # 2260 vs 1960
        self.assertEqual(q["net_income_yoy"], 18.2)      # 234 vs 198
        self.assertIn("DEMO_29102026080200", c["filing"]["link"])

    def test_fiscal_quarter_labels(self):
        f = load("nse-analyst", "facts")
        self.assertEqual(f.quarter_label("2026-06-30"), "Q1 FY27 (Jun 2026)")
        self.assertEqual(f.quarter_label("2026-12-31"), "Q3 FY27 (Dec 2026)")
        self.assertEqual(f.quarter_label("2027-03-31"), "Q4 FY27 (Mar 2027)")
        self.assertIsNone(f._growth(10, -5))


class Deals(Tmp):
    def deals(self, *extra):
        return run("nse-deals", "deals", ["--offline", os.path.join(FIX, "deals"), "--json"] + list(extra), self.dir)

    def test_indian_number_format(self):
        rc, out, err = self.deals()
        self.assertEqual(rc, 0, err)
        d = json.loads(out)["deals"]
        demo = [x for x in d if x["symbol"] == "DEMO" and x["side"] == "BUY"][0]
        self.assertEqual(demo["qty"], 250000)            # "2,50,000"
        self.assertAlmostEqual(demo["value"], 352562500.0)
        self.assertEqual(d[0]["kind"], "block")          # biggest first

    def test_filters(self):
        _, out, _ = self.deals("--tickers", "ALPHA")
        self.assertEqual({x["symbol"] for x in json.loads(out)["deals"]}, {"ALPHA"})
        _, out, _ = self.deals("--client", "mutual fund")
        self.assertEqual(len(json.loads(out)["deals"]), 1)
        _, out, _ = self.deals("--min-value", "30")
        self.assertEqual({x["symbol"] for x in json.loads(out)["deals"]}, {"BETA", "DEMO"})
        rc, out, _ = self.deals("--tickers", "NOPE")
        self.assertEqual(rc, 1)

    def test_header_variants(self):
        d = load("nse-deals", "deals")
        rows = d.parse_csv("﻿Date ,Symbol ,Security Name ,Client Name ,Buy / Sell ,Quantity Traded ,"
                           "Trade Price / Wght. Avg. Price ,Remarks\n"
                           "29-OCT-2026,ABC,Abc Ltd,X FUND,S,1000,10.5,-\n", "bulk")
        self.assertEqual((rows[0]["side"], rows[0]["qty"], rows[0]["date"]), ("SELL", 1000, "2026-10-29"))
        self.assertEqual(d.parse_csv("Date,Symbol\nNO RECORDS\n", "block"), [])

    def test_new_only_shows_once(self):
        st = os.path.join(self.dir, "deals.json")
        rc1, _, _ = run("nse-deals", "deals", ["--offline", os.path.join(FIX, "deals"), "--new", "--state", st], self.dir)
        rc2, out, _ = run("nse-deals", "deals", ["--offline", os.path.join(FIX, "deals"), "--new", "--state", st], self.dir)
        self.assertEqual((rc1, rc2), (0, 1))


class Repo(unittest.TestCase):
    def test_fourteen_skills_with_matching_names(self):
        self.assertEqual(len(SKILLS), 14)
        for s in SKILLS:
            with open(os.path.join(ROOT, s, "SKILL.md"), encoding="utf-8") as fh:
                text = fh.read()
            m = re.match(r"---\nname: (\S+)\ndescription: >-\n(.*?)\n---\n", text, re.S)
            self.assertTrue(m, s)
            self.assertEqual(m.group(1), s)
            self.assertLess(len(" ".join(m.group(2).split())), 1024, s)

    def test_scripts_named_in_skills_exist(self):
        for s in SKILLS:
            with open(os.path.join(ROOT, s, "SKILL.md"), encoding="utf-8") as fh:
                text = fh.read()
            for script in set(re.findall(r'CLAUDE_SKILL_DIR\}/([\w.-]+\.py)', text)):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, s, script)), "%s: %s" % (s, script))

    def test_no_us_leftovers(self):
        bad = re.compile(r"\b(TSLA|Alpaca|alpaca|EDGAR|Pelosi|NYSE|nasdaqtrader|place_stock_order)\b")
        for path in [p for p in glob.glob(os.path.join(ROOT, "nse-*", "*")) if os.path.isfile(p)]:
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    self.assertIsNone(bad.search(line), "%s:%d: %s" % (path, n, line.strip()))

    def test_plugin_manifest(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            p = json.load(fh)
        self.assertEqual(p["name"], "nse-day-trader-skill")
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as fh:
            m = json.load(fh)
        self.assertEqual(m["plugins"][0]["name"], "nse-day-trader-skill")

    def test_config_example_is_in_rupees(self):
        with open(os.path.join(ROOT, "nse-budget", "config.example.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.assertFalse([k for k in cfg if k.endswith("_usd")])
        self.assertEqual(cfg["broker"], "kite")
        self.assertTrue(cfg["paper"])


if __name__ == "__main__":
    unittest.main()
