import unittest
import numpy as np
import stock_individual_paths as P
import stock_execution_audit as A

class IndividualPathTests(unittest.TestCase):
 def fixture(self):
  ds=np.busday_offset('2020-01-01',np.arange(300)).astype(str).tolist();a=np.tile([100.,102.,98.,100.,1e5],(300,1));e={'d':ds,'idx':{d:i for i,d in enumerate(ds)},'a':a,'atrp':np.full(300,.02)};A.prepare(e);return e
 def row(self,e,why='sl',exit_i=254,px=85):return {'signal':e['d'][250],'entry_day':e['d'][251],'exit_day':e['d'][exit_i],'entry':100,'exit':px,'why':why,'r':px*.997/(100*1.003)-1}
 def test_intraday_exit_does_not_borrow_exit_day_extremes(self):
  e=self.fixture();e['a'][254]=[100,180,20,100,1e5];d=P.diagnose(e,self.row(e),300);self.assertEqual(d['mae_pct'],15);self.assertEqual(d['mfe_pct'],2);self.assertIsNone(d['hit_days']['10'])
 def test_close_exit_includes_that_days_range(self):
  e=self.fixture();e['a'][254]=[100,140,75,110,1e5];d=P.diagnose(e,self.row(e,'time_close',px=110),300);self.assertEqual(d['mae_pct'],25);self.assertEqual(d['mfe_pct'],40);self.assertEqual(d['hit_days']['10'],4)
 def test_post_stop_recovery_uses_cost_adjusted_original_cost(self):
  e=self.fixture();e['a'][255:275,3]=100;d=P.diagnose(e,self.row(e),300);self.assertFalse(d['stop_recovered_20']);e['a'][260,3]=101;self.assertTrue(P.diagnose(e,self.row(e),300)['stop_recovered_20'])
 def test_incomplete_followup_not_counted_as_failed_recovery(self):
  e=self.fixture();d=P.diagnose(e,self.row(e,exit_i=295),300);self.assertFalse(d['stop_20_observed']);self.assertIsNone(d['stop_recovered_20']);self.assertTrue(d['post_exit_censored'])
 def test_followup_never_looks_across_period_end(self):
  e=self.fixture();e['a'][280,3]=150;d=P.diagnose(e,self.row(e),270);self.assertIsNone(d['stop_recovered_20'])
 def test_target_continuation_is_descriptive_close_to_close(self):
  e=self.fixture();e['a'][274,3]=143;d=P.diagnose(e,self.row(e,'tp',px=130),300);self.assertAlmostEqual(d['target_after20_pct'],10)
 def test_regime_drift_is_measured_from_signal_not_today(self):
  e=self.fixture();e['atrp'][252]=.05;self.assertTrue(P.diagnose(e,self.row(e),300)['regime_changed']);e['atrp'][299]=.5;self.assertTrue(P.diagnose(e,self.row(e),300)['regime_changed'])
 def test_same_entry_stop_gap_is_open_not_stop_level(self):
  e=self.fixture();e['a'][252]=[70,90,60,80,1e5];k,px,why=P.exit_same_entry(e,251,'break_low','baseline',300);self.assertEqual((k,px,why),(252,70,'gap_sl'))
 def test_tighter_stop_and_baseline_share_entry(self):
  e=self.fixture();e['a'][252]=[100,103,88,101,1e5];self.assertEqual(P.exit_same_entry(e,251,'break_low','tighter_stop',300)[1],90);self.assertNotEqual(P.exit_same_entry(e,251,'break_low','baseline',300)[2],'sl')
 def test_boundary_counterfactual_retains_loss(self):
  e=self.fixture();e['a'][259,3]=95;k,px,why=P.exit_same_entry(e,251,'break_mid','baseline',260);self.assertEqual(why,'boundary_mark');self.assertEqual(px,95)
 def test_no_events_is_not_fake_zero_risk(self):
  s=P.summarize([]);self.assertEqual(s['n'],0);self.assertIsNone(s['mae90_pct']);self.assertIsNone(s['paired']['baseline']['avg_pct']);self.assertEqual(s['hit']['10']['n'],0)
 def test_exit_day_high_is_not_used_as_hit_timing(self):
  e=self.fixture();e['a'][254,1]=180;d=P.diagnose(e,self.row(e,'tp',px=130),300);self.assertEqual(d['hit_days']['10'],4);self.assertEqual(d['hit_days']['20'],4)

if __name__=='__main__':unittest.main()
