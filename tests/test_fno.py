"""NIFTY 50 and SENSEX index options: calendar, symbols, pricing, chain, planner, risk and broker."""

import datetime
import json
import math
import os
import shutil
import tempfile
import unittest

from _load import FIX, ROOT, load, run

FNO = os.path.join(FIX, "fno")
F = load("nse-fno-chain", "fno_core")
D = datetime.date


class Calendar(unittest.TestCase):
    def test_weekly_expiries_and_holiday_shift(self):
        self.assertEqual(F.expiries("NIFTY", D(2026, 10, 30), 4),
                         [D(2026, 11, 3), D(2026, 11, 9), D(2026, 11, 17), D(2026, 11, 23)])   # 10th and 24th are holidays
        self.assertEqual(F.expiries("SENSEX", D(2026, 10, 30), 4),
                         [D(2026, 11, 5), D(2026, 11, 12), D(2026, 11, 19), D(2026, 11, 26)])
        self.assertEqual(F.expiries("NIFTY", D(2026, 11, 3), 1), [D(2026, 11, 3)])                # expiry day itself

    def test_monthly(self):
        self.assertTrue(F.is_monthly("NIFTY", D(2026, 11, 23)))          # last Tuesday (24th) is a holiday
        self.assertFalse(F.is_monthly("NIFTY", D(2026, 11, 17)))
        self.assertTrue(F.is_monthly("SENSEX", D(2026, 11, 26)))
        self.assertTrue(F.is_monthly("NIFTY", D(2026, 12, 29)))

    def test_symbols_round_trip(self):
        chain = load("nse-fno-chain", "chain")
        cases = [("NIFTY", D(2026, 11, 3), 25800, "CE", "NIFTY26N0325800CE"),
                 ("NIFTY", D(2026, 11, 23), 25800, "PE", "NIFTY26NOV25800PE"),
                 ("SENSEX", D(2026, 11, 5), 84200, "PE", "SENSEX26N0584200PE"),
                 ("NIFTY", D(2026, 10, 6), 24900, "CE", "NIFTY26O0624900CE"),
                 ("NIFTY", D(2026, 1, 6), 26000, "CE", "NIFTY2610626000CE")]
        for idx, exp, k, r, want in cases:
            self.assertEqual(F.tradingsymbol(idx, exp, k, r), want)
            self.assertEqual(chain.parse_symbol(want), (idx, exp, float(k), r), want)

    def test_only_nifty_and_sensex(self):
        self.assertEqual(F.index_of("^NSEI"), "NIFTY")
        self.assertEqual(F.index_of("sensex"), "SENSEX")
        with self.assertRaises(F.FnoError):
            F.index_of("BANKNIFTY")


class Pricing(unittest.TestCase):
    def test_put_call_parity_and_iv(self):
        s, k, t, r, v = 25800.0, 25850.0, 3 / 365.0, 0.065, 0.13
        c, p = F.bs_price("CE", s, k, t, r, v), F.bs_price("PE", s, k, t, r, v)
        self.assertAlmostEqual(c - p, s - k * math.exp(-r * t), places=6)
        self.assertAlmostEqual(F.implied_vol("CE", c, s, k, t, r), v, places=4)
        self.assertAlmostEqual(F.implied_vol("PE", p, s, k, t, r), v, places=4)
        self.assertIsNone(F.implied_vol("CE", 1.0, s, 25000, t, r))           # below intrinsic

    def test_greeks(self):
        g = F.greeks("CE", 25800, 25800, 2 / 365.0, 0.065, 0.12)
        gp = F.greeks("PE", 25800, 25800, 2 / 365.0, 0.065, 0.12)
        self.assertTrue(0.45 < g["delta"] < 0.6)
        self.assertAlmostEqual(g["delta"] - gp["delta"], 1.0, places=6)
        self.assertLess(g["theta"], 0)
        self.assertGreater(g["vega"], 0)

    def test_costs(self):
        # 130 units bought at 117.10 and sold at 108.60 on NFO
        bv, sv = 130 * 117.10, 130 * 108.60
        exch = (bv + sv) * 0.03553 / 100
        sebi = (bv + sv) * 10 / 1e7
        want = 40 + round(sv * 0.0015) + exch + sebi + round(bv * 0.00003) + 0.18 * (40 + exch + sebi)
        self.assertAlmostEqual(F.option_round_trip(130, 117.10, 108.60, "NFO"), round(want, 2), places=2)
        self.assertLess(F.option_round_trip(20, 300, 280, "BFO"), F.option_round_trip(20, 300, 280, "NFO"))

    def test_ticks(self):
        self.assertEqual(F.floor_tick(110.33), 110.30)
        self.assertEqual(F.ceil_tick(117.06), 117.10)
        self.assertEqual(F.round_tick(131.37), 131.35)
        self.assertEqual(F.ceil_tick(117.10), 117.10)


class ChainAndPlan(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "trader"))
        with open(os.path.join(ROOT, "nse-budget", "config.example.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        cfg["allow_options"] = True
        self.cfg = cfg
        self.save_cfg()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def save_cfg(self):
        with open(os.path.join(self.dir, "trader", "config.json"), "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh)

    def r(self, folder, name, *args):
        return run(folder, name, list(args), self.dir)

    def chain(self, idx="NIFTY", spot="25792.89", now="2026-11-02 09:45"):
        return self.r("nse-fno-chain", "chain", "analyse", idx, "--quotes", os.path.join(FNO, "quotes-%s.json" % idx),
                      "--spot", spot, "--now", now, "--write", "--json")

    def test_chain_analysis(self):
        rc, out, err = self.chain()
        self.assertEqual(rc, 0, err)
        c = json.loads(out)
        self.assertEqual((c["expiry"], c["atm"], c["lot"], c["exchange"]), ("2026-11-03", 25800, 65, "NFO"))
        self.assertFalse(c["monthly"])
        self.assertTrue(0.5 < c["pcr"] < 2)
        self.assertIn(c["max_pain"], [s["strike"] for s in c["strikes"]])
        self.assertGreater(c["call_wall"], c["atm"])
        self.assertLess(c["put_wall"], c["atm"])
        atm = [s for s in c["strikes"] if s["strike"] == 25800][0]
        self.assertTrue(10 < atm["CE"]["iv"] < 20)
        self.assertAlmostEqual(c["straddle"], atm["CE"]["mid"] + atm["PE"]["mid"], places=2)

    def test_symbols_command(self):
        rc, out, _ = self.r("nse-fno-chain", "chain", "symbols", "SENSEX", "--spot", "84150", "--width", "1",
                            "--now", "2026-11-02 09:45")
        d = json.loads(out)
        self.assertEqual(d["instruments"][:2], ["BFO:SENSEX26N0584100CE", "BFO:SENSEX26N0584100PE"])
        self.assertEqual(d["spot_instrument"], "BSE:SENSEX")

    def plan(self, *extra):
        self.chain()
        return self.r("nse-fno-plan", "plan", "--index", "NIFTY", "--direction", "up", "--index-entry", "25792.89",
                      "--index-stop", "25781.14", "--now", "2026-11-02 09:45", "--json", *extra)

    def test_plan_sizes_to_max_loss_after_costs(self):
        self.cfg["fno"]["max_lots"] = 50
        self.cfg["fno"]["max_premium_inr"] = 10 ** 6
        self.cfg["max_loss_per_trade_inr"] = 3000
        self.save_cfg()
        rc, out, err = self.plan()
        self.assertEqual(rc, 0, err)
        p = json.loads(out)
        self.assertEqual(p["right"], "CE")
        self.assertEqual(p["qty"], p["lots"] * 65)
        self.assertEqual(p["bound_by"], "max loss")
        self.assertLessEqual(p["net_loss_at_stop"], 3000)
        more = (p["lots"] + 1) * 65
        self.assertGreater(more * p["risk_per_share"] + F.option_round_trip(more, p["entry"], p["stop_limit"], "NFO"), 3000)
        for k in ("entry", "stop", "stop_limit", "target"):
            self.assertAlmostEqual(round(p[k] / 0.05), p[k] / 0.05, places=6, msg=k)
        self.assertLess(p["stop_limit"], p["stop"])
        self.assertLess(p["stop"], p["entry"])
        self.assertGreater(p["target"], p["entry"])
        self.assertLessEqual(p["stop"] - p["stop_limit"], 0.25 * (p["entry"] - p["stop"]) + 0.05)
        self.assertTrue(0 < p["breakeven_win_rate"] < 1)

    def test_put_on_a_down_signal(self):
        self.chain("SENSEX", "84100", "2026-11-02 10:30")
        rc, out, err = self.r("nse-fno-plan", "plan", "--index", "SENSEX", "--direction", "down", "--index-entry",
                              "84100", "--index-stop", "84190", "--now", "2026-11-02 10:30", "--json")
        self.assertEqual(rc, 0, err)
        p = json.loads(out)
        self.assertEqual((p["right"], p["exchange"], p["lot_size"]), ("PE", "BFO", 20))
        self.assertLess(p["delta"], 0)

    def test_wrong_side_stop_is_refused(self):
        self.chain()
        rc, out, err = self.r("nse-fno-plan", "plan", "--index", "NIFTY", "--direction", "up", "--index-entry",
                              "25792", "--index-stop", "25800", "--now", "2026-11-02 09:45")
        self.assertEqual(rc, 1)
        self.assertIn("wrong side", err)

    def test_zero_lots_is_a_refusal(self):
        self.cfg["max_loss_per_trade_inr"] = 100
        self.save_cfg()
        rc, out, err = self.plan("--write")
        self.assertEqual(rc, 1)
        self.assertIn("0 lots", out)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "trader", "orders.json")))

    def test_full_chain_to_broker(self):
        rc, out, err = run("nse-entry", "entry", ["check", "^NSEI", "--offline", FNO, "--now", "2026-11-02 09:45",
                                                  "--write"], self.dir)
        self.assertEqual(rc, 0, out + err)
        self.chain()
        rc, out, err = self.r("nse-fno-plan", "plan", "--now", "2026-11-02 09:45", "--write")
        self.assertEqual(rc, 0, out + err)
        rc, out, err = self.r("nse-risk", "check", "--now", "2026-11-02 09:46")
        self.assertEqual(rc, 0, out)
        self.assertIn("units", out)
        rc, out, err = self.r("nse-broker", "ticket", "show", "--now", "2026-11-02 09:46", "--index", "1", "--json")
        t = json.loads(out)
        legs = [c["input"] for c in t["kite_calls"]]
        self.assertEqual([l["exchange"] for l in legs], ["NFO"] * 3)
        self.assertEqual([l["order_type"] for l in legs], ["LIMIT", "SL", "LIMIT"])
        self.assertLess(legs[1]["price"], legs[1]["trigger_price"])
        self.assertTrue(t["ready"])


class OptionRisk(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "trader"))
        with open(os.path.join(ROOT, "nse-budget", "config.example.json"), encoding="utf-8") as fh:
            self.cfg = json.load(fh)
        self.cfg["allow_options"] = True

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def order(self, **over):
        o = {"symbol": "NIFTY26N0325750CE", "exchange": "NFO", "product": "MIS", "side": "buy", "qty": "130",
             "type": "limit", "limit_price": "117.10", "time_in_force": "day", "order_class": "bracket",
             "stop_loss_stop_price": "110.30", "stop_loss_limit_price": "108.60", "take_profit_limit_price": "131.35",
             "plan": {"entry": 117.10, "stop": 110.30, "target": 131.35, "lot_size": 65, "expiry": "2026-11-03",
                      "charges_at_stop": 79.0}}
        o.update(over)
        return o

    def check(self, orders, now="2026-11-02 09:46"):
        with open(os.path.join(self.dir, "trader", "config.json"), "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh)
        with open(os.path.join(self.dir, "trader", "orders.json"), "w", encoding="utf-8") as fh:
            json.dump({"orders": orders}, fh)
        return run("nse-risk", "check", ["--now", now, "--no-write"], self.dir)

    def test_passes(self):
        rc, out, _ = self.check([self.order()])
        self.assertEqual(rc, 0, out)
        self.assertIn("1,184", out.replace("1,185", "1,184"))         # 130 x (117.10 - 108.60) + 79

    def test_options_off_by_default(self):
        self.cfg["allow_options"] = False
        rc, out, _ = self.check([self.order()])
        self.assertEqual(rc, 1)
        self.assertIn("F&O is off", out)

    def test_blocks(self):
        cases = [
            (dict(symbol="NIFTY26NOVFUT"), "index options only"),
            (dict(symbol="BANKNIFTY26NOV52000CE"), "index options only"),
            (dict(qty="100"), "lots"),
            (dict(exchange="BFO"), "trade on NFO"),
            (dict(limit_price="117.12"), "tick"),
            (dict(qty="195"), "fno.max_lots"),
            (dict(side="sell", order_class=None, stop_loss_stop_price=None, stop_loss_limit_price=None,
                  take_profit_limit_price=None), "writing"),
            (dict(product="CNC"), "MIS"),
        ]
        for over, why in cases:
            rc, out, _ = self.check([self.order(**over)])
            self.assertEqual(rc, 1, "%s should block" % over)
            self.assertIn(why, out, over)

    def test_freeze(self):
        self.cfg["fno"]["max_lots"] = 100
        self.cfg["fno"]["max_premium_inr"] = 10 ** 8
        self.cfg["max_order_inr"] = 10 ** 8
        self.cfg["max_loss_per_trade_inr"] = 10 ** 8
        self.cfg["max_daily_loss_inr"] = 10 ** 8
        self.cfg["max_position_pct"] = 1000
        self.cfg["budget"] = 10 ** 8
        rc, out, _ = self.check([self.order(qty=str(65 * 55), limit_price="1.00", stop_loss_stop_price="0.90",
                                            stop_loss_limit_price="0.85", take_profit_limit_price="1.50")])
        self.assertIn("freeze", out)

    def test_expiry_day_cutoff(self):
        rc, out, _ = self.check([self.order()], now="2026-11-03 13:05")
        self.assertEqual(rc, 1)
        self.assertIn("expires today", out)
        rc, out, _ = self.check([self.order()], now="2026-11-03 10:00")
        self.assertEqual(rc, 0, out)
        self.assertIn("expiry day", out)


if __name__ == "__main__":
    unittest.main()
