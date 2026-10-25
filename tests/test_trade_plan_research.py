import unittest
import numpy as np
from unittest.mock import patch
import stock_trade_plan_research as R
import build_trade_plan_report as V

class TradePlanResearchTests(unittest.TestCase):
    def fixture(self):
        ds=np.busday_offset('2020-01-01',np.arange(260)).astype(str).tolist()
        a=np.tile([100.,102.,98.,100.,100000.],(260,1))
        e={'d':ds,'a':a,'liq':np.full(260,1e6),'atr':np.full(260,2.),'known_bad':np.zeros(260,bool)}
        R.features(e)
        return e,{d:i for i,d in enumerate(ds)}

    def run_one(self,mutate=None,calendar=None):
        e,cal=self.fixture();e['a'][250]=[100,106,99,105,100000]
        if mutate:mutate(e)
        p={'trigger':102,'upper':104,'stop':95,'target':122,'hold':3,'confirm':'cross','asof':e['d'][249]}
        with patch.object(R,'plan',side_effect=lambda e,i,m:p if i==249 else None):
            return R.run(e,'TW','break20',e['d'][250],None,calendar or cal)

    def test_next_day_only_and_limit_ceiling(self):
        rows=self.run_one(lambda e:e['a'].__setitem__(251,[106,108,103,105,100000]))
        self.assertEqual(rows[0]['entry'],104)
        self.assertEqual(rows[0]['days'],3)
        self.assertEqual(rows[0]['why'],'time')

    def test_gap_below_stop_cancels_order(self):
        self.assertEqual(self.run_one(lambda e:e['a'].__setitem__(251,[94,110,93,108,100000])),[])

    def test_confirmation_cannot_have_already_broken_stop(self):
        self.assertEqual(self.run_one(lambda e:e['a'].__setitem__(250,[100,106,94,105,100000])),[])

    def test_missing_market_session_does_not_wait_for_suspension(self):
        e,cal=self.fixture();cal[e['d'][251]]+=1
        self.assertEqual(self.run_one(calendar=cal),[])

    def test_intraday_fill_does_not_claim_earlier_high_as_profit(self):
        rows=self.run_one(lambda e:e['a'].__setitem__(251,[125,130,103,105,100000]))
        self.assertEqual(rows[0]['entry'],104)
        self.assertNotEqual(rows[0]['why'],'tp')

    def test_same_bar_stop_before_target_and_cost_included(self):
        rows=self.run_one(lambda e:e['a'].__setitem__(251,[100,125,94,110,100000]))
        self.assertEqual(rows[0]['exit'],95)
        self.assertEqual(rows[0]['why'],'sl')
        self.assertAlmostEqual(rows[0]['r'],95*.997/(100*1.003)-1)

    def test_boundary_mark_retains_unrealized_loss(self):
        e,cal=self.fixture();e['a'][258]=[100,106,99,105,100000];e['a'][259]=[100,102,96,97,100000]
        p={'trigger':102,'upper':104,'stop':95,'target':122,'hold':40,'confirm':'cross'}
        with patch.object(R,'plan',side_effect=lambda e,i,m:p if i==257 else None):
            rows=R.run(e,'TW','break20',e['d'][258],None,cal)
        self.assertEqual(rows[0]['why'],'boundary_mark');self.assertLess(rows[0]['r'],0)
        self.assertEqual(R.stats(rows)['completed'],0)

    def test_future_bar_does_not_change_prior_plan(self):
        e,_=self.fixture();p=R.plan(e,250,'break20');e['a'][259]=[1,2,.1,1,1]
        R.features(e);self.assertEqual(R.plan(e,250,'break20'),p)

    def test_sparse_or_negative_results_never_qualify(self):
        self.assertFalse(R.supported({'completed':5,'avg_pct':20,'pf':2,'positive_years':5,'years':5},10))
        self.assertFalse(R.supported({'completed':20,'avg_pct':-1,'pf':.9,'positive_years':1,'years':5},10))

    def test_calendar_skips_weekend_typhoon_and_announced_holiday(self):
        h={'tw':{'2026-10-23':'closed','2026-10-26':'closed'}}
        self.assertEqual(V.next_day('2026-10-22','TW',h),'2026-10-27')
        self.assertEqual(V.next_day('2026-10-27','TW',h),'2026-10-28')

    def test_price_display_respects_tw_tick_boundaries_and_us_cents(self):
        self.assertEqual(V.price(2419.04,'TW',True),2420)
        self.assertEqual(V.price(2428.60,'TW'),2425)
        self.assertEqual(V.price(49.999,'TW'),49.95)
        self.assertEqual(V.price(999.99,'TW',True),1000)
        self.assertEqual(V.price(123.456,'US'),123.45)

if __name__=='__main__':unittest.main()
