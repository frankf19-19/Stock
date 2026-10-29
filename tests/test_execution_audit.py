import unittest,json,tempfile
from pathlib import Path
import numpy as np
import stock_execution_audit as A

class ExecutionAuditTests(unittest.TestCase):
 def fixture(self,n=270):
  ds=np.busday_offset('2020-01-01',np.arange(n)).astype(str).tolist();a=np.tile([100.,102.,98.,100.,1e5],(n,1));e={'d':ds,'a':a,'liq':np.full(n,1e6),'atrp':np.full(n,.02),'dd':np.zeros(n),'known_bad':np.zeros(n,bool)};A.prepare(e);return e,{d:i for i,d in enumerate(ds)}
 def run_one(self,edit=None,policy='baseline',group='break_low',last=269,cost=.006):
  e,cal=self.fixture()
  if edit:edit(e,cal)
  return A.simulate(e,np.array([250]),np.ones(270,bool),cal,group,policy,e['d'][250],e['d'][last] if last<269 else '2022-01-01',cost)
 def test_open_gap_target_precedes_later_low(self):
  r,_,_=self.run_one(lambda e,c:e['a'].__setitem__(252,[140,145,70,100,1e5]));self.assertEqual(r[0]['exit'],140);self.assertEqual(r[0]['why'],'gap_tp')
 def test_ambiguous_intraday_stop_first(self):
  r,_,_=self.run_one(lambda e,c:e['a'].__setitem__(252,[100,140,70,100,1e5]));self.assertEqual(r[0]['exit'],85)
 def test_limit_fill_cannot_sell_at_earlier_high(self):
  r,_,_=self.run_one(lambda e,c:e['a'].__setitem__(251,[140,145,99,100,1e5]),'limit_close');self.assertNotEqual(r[0]['why'],'gap_tp');self.assertEqual(r[0]['entry'],100)
 def test_limit_not_filled_and_gap_cancel_count_missed_signal(self):
  for p in ['limit_close','gap3_cancel']:
   r,_,ct=self.run_one(lambda e,c:e['a'].__setitem__(251,[110,115,105,110,1e5]),p);self.assertEqual(r,[]);self.assertEqual(ct['signals'],1)
 def test_boundary_loss_is_kept_with_cost_and_nav(self):
  r,nav,_=self.run_one(lambda e,c:e['a'].__setitem__(269,[95,96,94,95,1e5]));self.assertEqual(r[0]['why'],'boundary_mark');self.assertLess(r[0]['r'],0);self.assertAlmostEqual(nav[-1],95*.997/(100*1.003))
 def test_missing_next_session_does_not_delay_entry(self):
  r,_,ct=self.run_one(lambda e,c:c.__setitem__(e['d'][251],c[e['d'][251]]+1));self.assertEqual(r,[]);self.assertEqual(ct['missing_next_session'],1)
 def test_period_end_never_uses_future_exit(self):
  r,_,_=self.run_one(lambda e,c:e['a'].__setitem__(260,[100,150,99,140,1e5]),last=259);self.assertLess(r[0]['exit_day'],'2021');self.assertEqual(r[0]['why'],'boundary_mark');self.assertLess(r[0]['r'],0)
 def test_ma_exit_at_following_open_not_second_close(self):
  def change(e,c):
   e['a'][252]=[99,100,97,98,1e5];e['a'][253]=[98,99,96,97,1e5];e['a'][254]=[92,94,91,93,1e5];A.prepare(e)
  r,_,_=self.run_one(change,group='break_mid');self.assertEqual(r[0]['exit'],92);self.assertEqual(r[0]['why'],'ma_next_open')
 def test_one_stock_no_overlapping_capital(self):
  e,cal=self.fixture();r,nav,_=A.simulate(e,np.array([250,251,252]),np.ones(270,bool),cal,'break_low','baseline',e['d'][250],'2022-01-01');self.assertEqual(len(r),1);self.assertAlmostEqual(nav[-1],1+r[0]['r'])
 def test_cost_stress_reduces_same_trade_net(self):
  a=self.run_one(cost=.006)[0][0]['r'];b=self.run_one(cost=.01)[0][0]['r'];self.assertLess(b,a)
 def test_future_price_does_not_change_prior_signals(self):
  e,cal=self.fixture();e['a'][251]=[100,105,99,104,1e5];A.prepare(e);v,_=A.signal_sets(e,'TW',{});e['a'][269]=[1,2,.5,1,1e5];A.prepare(e);w,_=A.signal_sets(e,'TW',{});self.assertEqual([i for i in v['break_low'] if i<269],[i for i in w['break_low'] if i<269])
 def test_ledger_has_portable_json_types(self):
  rows,_,_=self.run_one();self.assertTrue(json.dumps(rows,allow_nan=False))
 def test_completed_research_cannot_be_overwritten(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'execution-audit.json.gz').write_bytes(b'preserve')
   with self.assertRaises(FileExistsError):A.main(p,'2026-10-28',[])
   self.assertEqual((p/'execution-audit.json.gz').read_bytes(),b'preserve')
 def test_no_market_breadth_does_not_create_weak_market_signal(self):
  e,_=self.fixture();e['dd'][251]=-.45;out,_=A.signal_sets(e,'TW',{});self.assertEqual(len(out['dip40_weak']),0)

if __name__=='__main__':unittest.main()
