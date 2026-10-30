"""The whole pack, offline, on the synthetic DEMO trade: scanner -> entry -> exit ->
time machine -> budget -> risk -> broker -> alerts. Fixtures: tests/make_fixtures.py."""

import datetime
import json
import os
import shutil
import tempfile
import unittest

from _load import FIX, ROOT, load, run

NOW = "2026-10-29 09:45"
CHARTS = os.path.join(FIX, "charts")


def config(**over):
    with open(os.path.join(ROOT, "nse-budget", "config.example.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg.update(over)
    return cfg


class Chain(unittest.TestCase):
    """One temp folder, the skills run in order, each reading what the last wrote."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.dir, "trader"))
        with open(os.path.join(cls.dir, "trader", "config.json"), "w", encoding="utf-8") as fh:
            json.dump(config(), fh)
        cls.out = {}
        steps = [
            ("entry", ("nse-entry", "entry", ["check", "DEMO", "--setup", "orb", "--offline", CHARTS,
                                              "--now", NOW, "--write"])),
            ("exit", ("nse-exit", "exit", ["plan", "--stop", "or-mid", "--target", "1R", "--write",
                                           "--now", NOW])),
            ("tm", ("nse-timemachine", "timemachine", ["run", "--offline",
                                                       os.path.join(CHARTS, "DEMO-60d-5m.json.gz"),
                                                       "--now", NOW, "--write"])),
            ("budget", ("nse-budget", "size", ["--now", NOW, "--write"])),
            ("risk", ("nse-risk", "check", ["--now", NOW])),
            ("show", ("nse-broker", "ticket", ["show", "--now", NOW])),
        ]
        for key, (folder, name, args) in steps:
            cls.out[key] = run(folder, name, args, cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def doc(self, name):
        with open(os.path.join(self.dir, "trader", name), encoding="utf-8") as fh:
            return json.load(fh)

    def test_every_step_succeeds(self):
        for key, (rc, out, err) in self.out.items():
            self.assertEqual(rc, 0, "%s failed: %s %s" % (key, out[-400:], err[-400:]))

    def test_entry_triggers_on_the_935_bar(self):
        e = self.doc("entry.json")
        self.assertEqual(e["symbol"], "DEMO")
        self.assertEqual(e["status"], "triggered")
        self.assertAlmostEqual(e["price"], 1409.49)
        self.assertIn("9:40", self.out["entry"][1])

    def test_exit_plan_on_tick_grid(self):
        p = self.doc("plan.json")
        self.assertEqual(p["stop"], 1405.60)        # (1408.37 + 1402.85) / 2 = 1405.61, down to the 0.10 tick
        self.assertEqual(p["target"], 1413.40)      # 1409.49 + 3.89, half up to the 0.10 tick
        self.assertEqual(p["tick_size"], 0.10)
        self.assertEqual(p["flat_by"], "15:10")
        self.assertEqual(p["exchange"], "NSE")

    def test_time_machine_adds_up_and_ends_at_flat_by(self):
        t = self.doc("timemachine.json")
        mc = t["monte_carlo"] if "monte_carlo" in t else t["mc"] if "mc" in t else t
        tot = mc["p_target"] + mc["p_stop"] + mc["p_neither"]
        self.assertAlmostEqual(tot, 1.0, places=3)
        self.assertEqual(mc.get("until"), "15:10")
        self.assertIn("seed 19", self.out["tm"][1])

    def test_time_machine_is_reproducible(self):
        a = run("nse-timemachine", "timemachine", ["run", "--offline", os.path.join(CHARTS, "DEMO-60d-5m.json.gz"),
                                                   "--now", NOW, "--json", "--replays", "2000"], self.dir)
        b = run("nse-timemachine", "timemachine", ["run", "--offline", os.path.join(CHARTS, "DEMO-60d-5m.json.gz"),
                                                   "--now", NOW, "--json", "--replays", "2000"], self.dir)
        self.assertEqual(a[0], 0, a[2])
        self.assertEqual(a[1], b[1])

    def test_budget_sizes_and_costs(self):
        o = self.doc("orders.json")["orders"][0]
        self.assertEqual(o["qty"], "266")             # bound by the 75% position cap on a 5 lakh budget
        self.assertEqual(o["exchange"], "NSE")
        self.assertEqual(o["product"], "MIS")
        self.assertEqual(o["stop_loss_stop_price"], "1405.60")
        self.assertEqual(o["take_profit_limit_price"], "1413.40")
        self.assertAlmostEqual(o["plan"]["charges_at_stop"], 179.21)
        self.assertAlmostEqual(o["plan"]["net_loss_at_stop"], 1213.95)

    def test_risk_passes_and_broker_is_ready(self):
        self.assertIn("PASS  #1 buy DEMO 266 shares", self.out["risk"][1])
        show = self.out["show"][1]
        self.assertIn("READY", show)
        self.assertIn('"order_type": "SL-M"', show)
        self.assertIn('"trigger_price": 1405.6', show)
        self.assertIn("PAPER", show)


class Pieces(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "trader"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, doc):
        with open(os.path.join(self.dir, "trader", name), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

    def plan(self, **over):
        p = {"symbol": "DEMO", "side": "buy", "date": "2026-10-29", "setup": "orb", "entry": 1409.49,
             "stop": 1405.60, "target": 1413.40, "entry_time": "9:40 AM", "flat_by": "15:10"}
        p.update(over)
        return p

    # ---------------------------------------------------------------- entry

    def test_flat_never_breaks_out_and_expires(self):
        rc, out, _ = run("nse-entry", "entry", ["check", "FLAT", "--offline", CHARTS,
                                                "--now", "2026-10-29 15:00"], self.dir)
        self.assertEqual(rc, 1)
        self.assertIn("EXPIRED", out)
        self.assertIn("14:45", out)

    def test_before_the_open_is_not_open(self):
        rc, out, _ = run("nse-entry", "entry", ["check", "DEMO", "--offline", CHARTS,
                                                "--now", "2026-10-29 09:05"], self.dir)
        self.assertIn("9:15", out)

    def test_holiday_is_closed(self):
        rc, out, _ = run("nse-entry", "entry", ["check", "DEMO", "--offline", CHARTS,
                                                "--now", "2026-10-20 10:00"], self.dir)
        self.assertIn("Dussehra", out)

    # ---------------------------------------------------------------- exit

    def test_exit_refuses_a_stop_above_the_entry(self):
        rc, out, err = run("nse-exit", "exit", ["plan", "--symbol", "DEMO", "--entry", "1409.49",
                                                "--setup", "level", "--stop", "price:1415",
                                                "--now", NOW], self.dir)
        self.assertEqual(rc, 1)
        self.assertIn("at or above the entry", out + err)

    # ---------------------------------------------------------------- budget

    def test_max_loss_binds_after_costs(self):
        self.write("config.json", config(max_loss_per_trade_inr=500))
        self.write("plan.json", self.plan())
        rc, out, _ = run("nse-budget", "size", ["--now", NOW, "--json"], self.dir)
        self.assertEqual(rc, 0, out)
        s = json.loads(out)
        sizing = s.get("sizing", s)
        self.assertEqual(sizing["bound_by"], "max loss")
        self.assertLessEqual(sizing["net_loss_at_stop"], 500.0)
        n = sizing["qty"] + 1                            # one more share would break the limit
        size = load("nse-budget", "size")
        t = size.charges_table({"charges": "zerodha"})
        self.assertGreater(n * 3.89 + size.round_trip_charges(n, 1409.49, 1405.60, t), 500.0)

    def test_no_charges_and_margin(self):
        self.write("config.json", config(charges="none", allow_margin=True, mis_leverage=5,
                                         max_position_pct=500, max_order_inr=10000000,
                                         max_loss_per_trade_inr=100000))
        self.write("plan.json", self.plan())
        rc, out, _ = run("nse-budget", "size", ["--now", NOW, "--json"], self.dir)
        sizing = json.loads(out).get("sizing", json.loads(out))
        self.assertEqual(sizing["charges_at_stop"], 0.0)
        self.assertEqual(sizing["leverage"], 5.0)
        self.assertEqual(sizing["qty"], 1596)            # 4.5 lakh cash x 5 / 1409.49

    def test_zero_shares_is_a_refusal(self):
        self.write("config.json", config(max_loss_per_trade_inr=3))
        self.write("plan.json", self.plan())
        rc, out, _ = run("nse-budget", "size", ["--now", NOW, "--write"], self.dir)
        self.assertNotEqual(rc, 0)
        self.assertIn("No order", out)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "trader", "orders.json")))

    # ---------------------------------------------------------------- risk

    def order(self, **over):
        o = {"symbol": "DEMO", "exchange": "NSE", "product": "MIS", "side": "buy", "qty": "10",
             "type": "market", "time_in_force": "day", "order_class": "bracket",
             "take_profit_limit_price": "1413.40", "stop_loss_stop_price": "1405.60",
             "plan": {"entry": 1409.49, "stop": 1405.60, "target": 1413.40}}
        o.update(over)
        return o

    def risk(self, orders, now=NOW, **cfg):
        self.write("config.json", config(**cfg))
        self.write("orders.json", {"orders": orders})
        return run("nse-risk", "check", ["--now", now, "--no-write"], self.dir)

    def test_risk_passes_a_clean_order(self):
        rc, out, _ = self.risk([self.order()])
        self.assertEqual(rc, 0, out)

    def test_risk_blocks_off_tick_prices(self):
        rc, out, _ = self.risk([self.order(stop_loss_stop_price="1405.63")])
        self.assertEqual(rc, 1)
        self.assertIn("tick", out)

    def test_risk_blocks_rupee_amount_orders(self):
        o = self.order()
        del o["qty"]
        o["notional"] = "10000"
        rc, out, _ = self.risk([o])
        self.assertEqual(rc, 1)
        self.assertIn("whole-share", out)

    def test_risk_blocks_fno_unless_allowed(self):
        rc, out, _ = self.risk([self.order(symbol="NIFTY26NOV24000CE")])
        self.assertEqual(rc, 1)
        self.assertIn("futures or options", out)

    def test_risk_blocks_after_the_window_and_on_holidays(self):
        rc, out, _ = self.risk([self.order()], now="2026-10-29 14:50")
        self.assertEqual(rc, 1)
        self.assertIn("window", out)
        rc, out, _ = self.risk([self.order()], now="2026-11-10 10:00")
        self.assertEqual(rc, 1)

    def test_risk_counts_costs_in_the_max_loss(self):
        o = self.order(qty="100")
        o["plan"]["charges_at_stop"] = 120.0
        rc, out, _ = self.risk([o], max_loss_per_trade_inr=450)   # 100 x 3.89 = 389, + 120 = 509
        self.assertEqual(rc, 1)
        self.assertIn("costs", out)

    def test_risk_accepts_nse_symbols(self):
        for sym in ("M&M", "BAJAJ-AUTO", "RELIANCE.BO"):
            rc, out, _ = self.risk([self.order(symbol=sym)])
            self.assertNotIn("does not look like", out, sym)

    # ---------------------------------------------------------------- broker

    def test_fingerprints_agree_between_risk_and_broker(self):
        check = load("nse-risk", "check")
        ticket = load("nse-broker", "ticket")
        o = self.order()
        self.assertEqual(check.fingerprint(o), ticket.fingerprint(o))
        self.assertEqual(check.ORDER_FIELDS, ticket.ORDER_FIELDS)

    def test_kite_calls_for_a_bracket(self):
        ticket = load("nse-broker", "ticket")
        calls = ticket.kite_calls(self.order(type="limit", limit_price="1409.50"))
        self.assertEqual([c["step"] for c in calls], ["entry", "stop-loss", "target"])
        e, s, t = (c["input"] for c in calls)
        self.assertEqual((e["order_type"], e["price"], e["product"], e["exchange"]), ("LIMIT", 1409.5, "MIS", "NSE"))
        self.assertEqual((s["transaction_type"], s["order_type"], s["trigger_price"]), ("SELL", "SL-M", 1405.6))
        self.assertEqual((t["order_type"], t["price"]), ("LIMIT", 1413.4))
        self.assertLessEqual(len(e["tag"]), 20)
        self.assertTrue(e["tag"].isalnum())

    def test_bse_symbol_goes_to_bse(self):
        ticket = load("nse-broker", "ticket")
        e = ticket.kite_calls(self.order(symbol="SOMECO.BO"))[0]["input"]
        self.assertEqual((e["exchange"], e["tradingsymbol"]), ("BSE", "SOMECO"))

    def test_a_vague_yes_is_refused(self):
        self.risk([self.order()])
        run("nse-risk", "check", ["--now", NOW], self.dir)
        rc, out, _ = run("nse-broker", "ticket", ["approve", "--index", "1", "--reply", "ok do them all",
                                                  "--now", NOW], self.dir)
        self.assertEqual(rc, 1)
        rc, out, _ = run("nse-broker", "ticket", ["approve", "--index", "1", "--reply", "yes",
                                                  "--now", NOW], self.dir)
        self.assertEqual(rc, 0, out)
        self.assertIn("PAPER", out)

    # ---------------------------------------------------------------- alerts

    def test_clock(self):
        rc, out, _ = run("nse-alerts", "alerts", ["clock", "--now", "2026-10-29 09:16"], self.dir)
        self.assertIn("OPEN", out)
        rc, out, _ = run("nse-alerts", "alerts", ["clock", "--now", "2026-11-10 10:00"], self.dir)
        self.assertIn("Diwali", out)
        self.assertIn("2026-11-11 09:15", out)
        rc, out, _ = run("nse-alerts", "alerts", ["clock", "--now", "2026-10-29 15:31"], self.dir)
        self.assertIn("after the close", out)

    def test_flat_by_alert_rings_once(self):
        self.write("plan.json", self.plan())
        run("nse-alerts", "alerts", ["add", "--from-plan"], self.dir)
        q = os.path.join(FIX, "quotes")
        rc, out, _ = run("nse-alerts", "alerts", ["check", "--offline", q, "--now", "2026-10-29 15:11"], self.dir)
        self.assertIn("Flat by close", out)
        rc, out2, _ = run("nse-alerts", "alerts", ["check", "--offline", q, "--now", "2026-10-29 15:12"], self.dir)
        self.assertNotIn("Flat by close", out2)


class Clock(unittest.TestCase):
    def test_every_tool_agrees_on_ist(self):
        utc = datetime.datetime(2026, 10, 29, 3, 45)          # 09:15 IST
        for folder, name in (("nse-scanner", "scan"), ("nse-entry", "entry"), ("nse-exit", "exit"),
                             ("nse-timemachine", "timemachine"), ("nse-budget", "size"),
                             ("nse-risk", "check"), ("nse-broker", "ticket"), ("nse-alerts", "alerts")):
            m = load(folder, name)
            self.assertEqual(m.to_ist(utc), datetime.datetime(2026, 10, 29, 9, 15), folder)
            if hasattr(m, "ist_to_utc"):
                self.assertEqual(m.ist_to_utc(datetime.datetime(2026, 10, 29, 9, 15)), utc, folder)
            hol = getattr(m, "NSE_HOLIDAYS", None)
            if hol is not None:
                self.assertIn("2026-11-10", hol, folder)
                self.assertEqual(len(hol), 16, folder)

    def test_parse_now_is_ist(self):
        m = load("nse-risk", "check")
        self.assertEqual(m.parse_now("2026-10-29 09:15"), datetime.datetime(2026, 10, 29, 3, 45))
        self.assertEqual(m.parse_now("2026-10-29T03:45:00Z"), datetime.datetime(2026, 10, 29, 3, 45))


class Ticks(unittest.TestCase):
    def test_bands(self):
        ex = load("nse-exit", "exit")
        D = ex.Decimal
        for price, tick in ((99, "0.01"), (250, "0.01"), (250.05, "0.05"), (1000, "0.05"), (1409.49, "0.10"),
                            (5000.5, "0.50"), (12000, "1.00"), (30000, "5.00")):
            self.assertEqual(ex.tick_for(D(str(price))), D(tick), price)
        self.assertEqual(ex.tick_for(D("1409.49"), "0.05"), D("0.05"))
        self.assertEqual(ex.floor_tick(D("1405.61"), D("0.10")), D("1405.60"))
        self.assertEqual(ex.round_tick(D("1413.38"), D("0.10")), D("1413.40"))
        risk = load("nse-risk", "check")
        self.assertTrue(risk.on_tick(1405.60, 0.10))
        self.assertFalse(risk.on_tick(1405.63, 0.10))
        self.assertTrue(risk.on_tick(212.37, 0.01))


class Costs(unittest.TestCase):
    def test_zerodha_round_trip(self):
        size = load("nse-budget", "size")
        t = size.charges_table({})
        # 266 x 1409.49 buy, sell at 1405.60: brokerage 20 + 20, STT 93, NSE 22.99, SEBI 0.75,
        # stamp 11, GST 18% of (40 + 22.99 + 0.75)
        self.assertAlmostEqual(size.round_trip_charges(266, 1409.49, 1405.60, t), 179.21, places=2)
        # a small order: brokerage is 0.03%, under the 20 rupee cap
        small = size.round_trip_charges(10, 500, 505, t)
        self.assertLess(small, 10)
        self.assertEqual(size.round_trip_charges(10, 500, 505, size.charges_table({"charges": "none"})), 0.0)
        custom = size.charges_table({"charges": {"brokerage_cap": 0, "brokerage_pct": 0}})
        self.assertLess(size.round_trip_charges(266, 1409.49, 1405.60, custom), 179.21 - 40)


if __name__ == "__main__":
    unittest.main()
