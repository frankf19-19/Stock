import unittest
import numpy as np
import stock_context_study as S
import stock_execution_audit as A
class StockContextTests(unittest.TestCase):
 def fixture(self):
  ds=np.busday_offset('2020-01-01',np.arange(300)).astype(str).tolist();a=np.tile([100.,102.,98.,100.,1e5],(300,1));e={'a':a,'d':ds,'atrp':np.full(300,.02)};A.prepare(e);return e
 def test_features_causal(self):
  e=self.fixture();f=S.features(e);e['a'][250:,:]*=5;z=S.features(e)
  for k in f:np.testing.assert_array_equal(f[k][:250],z[k][:250])
 def test_volume_prior_twenty_excludes_current(self):
  e=self.fixture();e['a'][250,4]*=2;self.assertEqual(S.features(e)['volume_ratio'][250],2)
 def test_bucket_boundaries(self):
  self.assertEqual(S.classify({'return20':-.1,'volume_ratio':1.5,'ma60_slope':0,'extension20':.1}),{'return20':1,'volume_ratio':1,'ma60_slope':1,'extension20':2})
 def test_missing_feature_not_zero(self):self.assertIsNone(S.classify({'volume_ratio':np.nan})['volume_ratio'])
 def test_effectively_flat_ma_not_down_from_roundoff(self):self.assertEqual(S.classify({'ma60_slope':-1e-16})['ma60_slope'],1)
 def test_weak20_waits_for_next_open(self):
  e=self.fixture();e['a'][271]=[97,101,96,98,1e5];self.assertEqual(S.exit_for(e,251,'break_low','weak20',300),(271,97.,'weak20_next_open'))
 def test_twentieth_day_target_has_priority(self):
  e=self.fixture();e['a'][270,1]=135;self.assertEqual(S.exit_for(e,251,'break_low','weak20',300)[2],'tp')
 def test_weak20_does_not_count_nontraded_bars(self):
  e=self.fixture();e['a'][252:254,4]=0;self.assertEqual(S.exit_for(e,251,'break_low','weak20',300)[0],273)
 def test_intraday_high_not_used_to_raise_protection(self):
  e=self.fixture();e['a'][252]=[100,115,98,100,1e5];self.assertNotEqual(S.exit_for(e,251,'break_low','protect10',260)[2],'sl')
 def test_protection_only_effective_next_day(self):
  e=self.fixture();e['a'][252]=[100,112,95,111,1e5];e['a'][253]=[110,112,99,101,1e5];k,px,why=S.exit_for(e,251,'break_low','protect10',260);self.assertEqual(k,253);self.assertAlmostEqual(px,100*1.003/.997);self.assertEqual(why,'sl')
 def test_protection_gap_not_guaranteed_breakeven(self):
  e=self.fixture();e['a'][252]=[100,112,98,111,1e5];e['a'][253]=[90,110,88,100,1e5];self.assertEqual(S.exit_for(e,251,'break_low','protect10',260),(253,90.,'gap_sl'))
 def test_exact_ten_percent_close_arms_next_day(self):
  e=self.fixture();e['a'][252]=[100,111,98,110,1e5];e['a'][253]=[105,108,99,103,1e5];self.assertEqual(S.exit_for(e,251,'break_low','protect10',260)[0],253)
 def test_summary_json_serializable(self):
  import json
  row={'r':.1,'why':'time_close','entry_day':'2024-01-01','path':{'mae_pct':5,'hit_days':{'10':2}},'new_exits':{p:{'r':.1,'why':'time_close'} for p in S.POLICIES}}
  self.assertEqual(json.loads(json.dumps(S.stats([row])))['exits']['baseline']['positive_years'],1)
 def test_boundary_no_next_open_fabrication(self):
  e=self.fixture();self.assertEqual(S.exit_for(e,251,'break_low','weak20',271)[2],'boundary_mark')
 def test_empty_cohort_no_fake_profit(self):
  x=S.stats([]);self.assertEqual(x['n'],0);self.assertIsNone(x['avg']);self.assertIsNone(x['worst']);self.assertIsNone(x['exits']['weak20']['pf'])
 def test_breakeven_residue_not_tiny_winner_or_loss(self):
  r={'r':.1,'why':'time_close','entry_day':'2024-01-01','path':{'mae_pct':5,'hit_days':{'10':2}},'new_exits':{p:{'r':2e-16,'why':'sl'} for p in S.POLICIES}}
  for v in S.stats([r])['exits'].values():self.assertEqual(v['wins'],0);self.assertIsNone(v['pf']);self.assertEqual(v['positive_years'],0)
if __name__=='__main__':unittest.main()
