"""nse-backtest: the option ORB backtest on synthetic Kite-format bars."""

import csv
import datetime
import json
import os
import shutil
import tempfile
import unittest

from _load import FIX, ROOT, load, run

BT = os.path.join(FIX, "backtest")
D = datetime.date


class Expiries(unittest.TestCase):
    def setUp(self):
        self.b = load("nse-backtest", "backtest")

    def test_weekday_history(self):
        w = self.b.weekly_weekday
        self.assertEqual(w("NIFTY", D(2023, 6, 1)), 3)       # Thursday
        self.assertEqual(w("NIFTY", D(2025, 9, 2)), 1)       # Tuesday from September 2025
        self.assertIsNone(w("SENSEX", D(2023, 5, 1)))        # no SENSEX weeklies yet
        self.assertEqual(w("SENSEX", D(2024, 3, 1)), 4)      # Friday
        self.assertEqual(w("SENSEX", D(2025, 3, 4)), 1)      # Tuesday
        self.assertEqual(w("SENSEX", D(2025, 9, 4)), 3)      # Thursday

    def test_holiday_and_switch(self):
        days = [D(2025, 8, 11), D(2025, 8, 12), D(2025, 8, 13), D(2025, 8, 18), D(2025, 8, 28), D(2025, 8, 29),
                D(2025, 9, 1), D(2025, 9, 2)]
        ne = lambda d: self.b.nearest_expiry("NIFTY", d, days, days[-1])
        self.assertEqual(ne(D(2025, 8, 11)), D(2025, 8, 13))   # Thursday 14th not in the data -> Wednesday
        self.assertEqual(ne(D(2025, 8, 29)), D(2025, 9, 2))    # contracts after August expire on Tuesday
        self.assertEqual(ne(D(2025, 8, 28)), D(2025, 8, 28))


class Run(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        rc, out, err = run("nse-backtest", "backtest", ["merge", "--index", "NIFTY",
                                                        os.path.join(BT, "NIFTY-*.json")], self.dir)
        self.assertEqual(rc, 0, err)
        rc, out, err = run("nse-backtest", "backtest", ["vix", os.path.join(BT, "VIX-day.json")], self.dir)
        self.assertEqual(rc, 0, err)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def bt(self, *args):
        rc, out, err = run("nse-backtest", "backtest", ["run", "--index", "NIFTY", "--json"] + list(args), self.dir)
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def trades(self, *args):
        run("nse-backtest", "backtest", ["run", "--index", "NIFTY", "--write"] + list(args), self.dir)
        with open(os.path.join(self.dir, "trader", "backtest", "NIFTY-trades.csv"), encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def test_report_adds_up(self):
        r = self.bt()
        o = r["overall"]
        self.assertEqual(r["days"], 63)
        self.assertEqual(o["trades"] + sum(r["skipped"].values()), r["days"])
        self.assertEqual(sum(y["trades"] for y in r["by_year"].values()), o["trades"])
        self.assertEqual(sum(x["trades"] for x in r["by_direction"].values()), o["trades"])
        self.assertLessEqual(o["max_drawdown"], 0)
        self.assertEqual(self.bt(), r)                                     # deterministic

    def test_trade_rules(self):
        for t in self.trades():
            e, s, sl, tg, x = (float(t[k]) for k in ("entry", "stop", "sl_limit", "target", "exit"))
            self.assertTrue(sl < s < e < tg, t)
            self.assertTrue("09:30" <= t["entry_time"] <= "14:45", t)
            self.assertLessEqual(t["exit_time"], "15:10")
            self.assertEqual(t["right"], "CE" if t["direction"] == "up" else "PE")
            if t["expiry_day"] == "True":
                self.assertLess(t["entry_time"], "13:00")
            if t["exit_why"] == "target":
                self.assertAlmostEqual(x, tg)
            if t["exit_why"] == "stop":
                self.assertGreaterEqual(x, sl - 1e-9)
            for k in ("entry", "stop", "sl_limit", "target"):
                self.assertAlmostEqual(round(float(t[k]) / 0.05), float(t[k]) / 0.05, places=6)

    def test_sides(self):
        up = self.bt("--sides", "up")
        self.assertEqual(up["by_direction"]["down"]["trades"], 0)
        self.assertGreater(up["by_direction"]["up"]["trades"], 0)

    def test_no_look_ahead(self):
        """Changing a day's own VIX, or bars after a trade has closed, must not change that trade."""
        base = {t["date"]: t for t in self.trades()}
        day = "2025-09-03"
        t0 = base[day]
        vix = os.path.join(self.dir, "trader", "backtest", "VIX-1d.csv")
        with open(vix, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        for r in rows:
            if r[0] == day:
                r[5] = "45"                                                   # the same day's VIX: unknown at 9:15
        with open(vix, "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(rows)
        bars = os.path.join(self.dir, "trader", "backtest", "NIFTY-5m.csv")
        with open(bars, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        for r in rows:
            if r[0] == day and r[1] > t0["exit_time"]:
                r[2:6] = ["1", "1", "1", "1"]                                 # wreck everything after the exit
        with open(bars, "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(rows)
        t1 = {t["date"]: t for t in self.trades()}[day]
        for k in ("entry", "stop", "target", "exit", "exit_why", "pnl", "strike"):
            self.assertEqual(t0[k], t1[k], k)

    def test_fetch_plan(self):
        rc, out, err = run("nse-backtest", "backtest", ["fetch-plan", "--index", "SENSEX", "--years", "5",
                                                        "--to", "2026-10-30"], self.dir)
        d = json.loads(out)
        self.assertEqual(d["token"], 265)
        calls = d["calls"]
        self.assertTrue(all(c["interval"] == "5minute" for c in calls))
        spans = [(datetime.date.fromisoformat(c["to_date"][:10]) - datetime.date.fromisoformat(c["from_date"][:10])).days
                 for c in calls]
        self.assertLess(max(spans), 100)
        self.assertEqual(calls[-1]["to_date"][:10], "2026-10-30")


class KiteFetch(unittest.TestCase):
    """fetch against a local stand-in for api.kite.trade: the request shape, paging and merge."""

    def test_fetch_merges_windows(self):
        import http.server
        import threading
        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get("Authorization"), self.headers.get("X-Kite-Version")))
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                d0 = datetime.date.fromisoformat(q["from"][0][:10])
                candles = [["%sT%02d:%02d:00+0530" % (d0, 9 + (15 + 5 * i) // 60, (15 + 5 * i) % 60),
                            100 + i, 101 + i, 99 + i, 100.5 + i, 0] for i in range(75)]
                body = json.dumps({"status": "success", "data": {"candles": candles}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        d = tempfile.mkdtemp()
        try:
            env_extra = {"KITE_API_URL": "http://127.0.0.1:%d" % srv.server_port, "KITE_API_KEY": "k",
                         "KITE_ACCESS_TOKEN": "t"}
            old = {k: os.environ.get(k) for k in env_extra}
            os.environ.update(env_extra)
            try:
                rc, out, err = run("nse-backtest", "backtest", ["fetch", "--index", "NIFTY", "--years", "0.5",
                                                                "--to", "2026-10-30"], d)
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            self.assertEqual(rc, 0, out + err)
            self.assertEqual(len(seen), 3)                                   # 182 days in 90-day windows
            self.assertTrue(seen[0][0].startswith("/instruments/historical/256265/5minute?"))
            self.assertEqual(seen[0][1:], ("token k:t", "3"))
            with open(os.path.join(d, "trader", "backtest", "NIFTY-5m.csv"), encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(len(rows) - 1, 3 * 75)
            self.assertEqual(rows[1][1], "09:15")                            # +0530 read as India time
        finally:
            srv.shutdown()
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
