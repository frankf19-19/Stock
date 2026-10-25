import unittest,datetime as dt
from unittest.mock import patch
import numpy as np
import stock_context_research as C
class ContextTests(unittest.TestCase):
 def test_three_regimes(self):
  self.assertEqual(C.scenario(110,108,100,99,115,120,103,90,2)['kind'],'pullback')
  self.assertEqual(C.scenario(95,98,100,101,105,115,92,85,2)['kind'],'reclaim')
  self.assertEqual(C.scenario(100,100,100,100,110,115,95,94,2)['kind'],'range')
 def test_invalid_prices_and_reward(self):
  self.assertIsNone(C.scenario(0,1,1,1,1,1,1,1,1))
  self.assertFalse(C.scenario(95,105,110,111,106,107,90,85,2)['valid'])
 def test_boundaries_are_not_dropped(self):
  r=C.stats([dict(r=-.1,entry_day='2020-01-02',why='boundary_mark')]);self.assertEqual(r['boundary_marks'],1);self.assertEqual(r['avg_pct'],-10)
 def test_features_have_no_future_dependency(self):
  a=np.array([[100+i*.1,102+i*.1,98+i*.1,100+i*.1,1e6] for i in range(300)])
  def e(x):return {'a':x,'atr':np.full(len(x),4.)}
  one=e(a.copy());C.features(one);before=C.at(one,270)
  two=e(a.copy());two['a'][280:,:4]*=10;C.features(two);self.assertEqual(before,C.at(two,270))
 def test_close_confirmation_cannot_use_tomorrows_price(self):
  e={'a':np.array([[95,98,92,95,1],[99,101,98,100,1]],float)}
  self.assertTrue(C.confirmed(e,1,dict(kind='reclaim',confirm=98)))
  self.assertFalse(C.confirmed(e,1,dict(kind='reclaim',confirm=105)))
 def run_fixture(self,nextbar,calendar_gap=False,lastclose=100):
  dates=[(dt.date(2020,1,1)+dt.timedelta(days=i)).isoformat() for i in range(253)]
  a=np.array([[100,101,99,100,1000]]*253,float);a[251]=nextbar;a[252]=[lastclose,max(lastclose,100),min(lastclose,99),lastclose,1000]
  e={'a':a,'d':dates,'liq':np.full(253,1e5),'known_bad':np.zeros(253,bool)}
  p=dict(kind='range',entry=100,stop=90,target=120,valid=True,hold=40,confirm=100)
  cal=dates.copy()
  if calendar_gap:cal.insert(251,dates[250]+'x')
  with patch.object(C,'at',side_effect=lambda e,i:p if i==249 else None),patch.object(C,'confirmed',return_value=True):
   return C.run(e,'TW','2020-01-01',None,cal)
 def test_intraday_buy_does_not_take_profit_from_earlier_high(self):
  r=self.run_fixture([110,130,95,105,1000]);self.assertEqual(len(r),1);self.assertEqual(r[0]['why'],'boundary_mark');self.assertEqual(r[0]['exit'],100)
 def test_intraday_buy_stop_is_conservative(self):
  r=self.run_fixture([110,130,80,105,1000]);self.assertEqual(r[0]['why'],'sl');self.assertEqual(r[0]['exit'],90)
 def test_open_below_stop_cancels_buy(self):self.assertEqual(self.run_fixture([80,130,70,110,1000]),[])
 def test_missing_next_market_session_cancels(self):self.assertEqual(self.run_fixture([100,110,95,105,1000],True),[])
 def test_boundary_loser_retained(self):
  r=self.run_fixture([100,110,95,100,1000],lastclose=95);self.assertEqual(r[0]['why'],'boundary_mark');self.assertLess(r[0]['r'],0)
if __name__=='__main__':unittest.main()
