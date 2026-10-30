import unittest,tempfile,datetime,json,gzip
from pathlib import Path
import build_margin_pressure as M
class MarginPressure(unittest.TestCase):
 def setUp(self):
  self.ds=[(datetime.date(2025,1,1)+datetime.timedelta(days=i)).isoformat() for i in range(80)];self.b={d:1000-i*5 for i,d in enumerate(self.ds)};self.p=dict.fromkeys(self.ds,100.)
 def test_deltas_and_real_peak_count(self):
  r=M.calculate(self.b,self.p,self.ds,self.ds[-1]);self.assertEqual(r['windows']['5']['delta'],-25);self.assertEqual(r['windows']['20']['delta'],-100);self.assertEqual(r['peak60']['date'],self.ds[-60]);self.assertEqual(r['peak60']['removed'],295);self.assertTrue(r['peak60']['complete'])
 def test_missing_middle_is_not_filled_zero_or_compressed_day(self):
  del self.b[self.ds[-3]];r=M.calculate(self.b,self.p,self.ds,self.ds[-1]);self.assertFalse(r['windows']['5']['complete']);self.assertEqual(r['windows']['5']['delta'],-25);self.assertEqual(r['windows']['5']['observed'],5);self.assertFalse(r['peak60']['complete'])
 def test_missing_baseline_is_unknown_not_zero(self):
  del self.b[self.ds[-6]];r=M.calculate(self.b,self.p,self.ds,self.ds[-1]);self.assertIsNone(r['windows']['5'])
 def test_zero_after_gap_does_not_claim_total_washout(self):
  del self.b[self.ds[-2]];self.b[self.ds[-1]]=0;r=M.calculate(self.b,self.p,self.ds,self.ds[-1]);self.assertIsNone(r['peak60']['removed_pct']);self.assertEqual(r['scenarios'],[]);self.assertIsNone(r['windows']['5']['pct'])
 def test_scenario_formula_not_a_cohort_estimate(self):
  r=M.calculate(self.b,self.p,self.ds,self.ds[-1]);self.assertEqual(len(r['scenarios']),3);x=r['scenarios'][0];self.assertAlmostEqual(x['line'],78);self.assertAlmostEqual(x['maintenance_pct'],100/.6);self.assertAlmostEqual(x['to_line_pct'],-22);self.assertTrue(x['label'].startswith('假設'))
 def test_no_price_or_discontinuous_price_blocks_scenario(self):
  self.p[self.ds[-1]]=None;r=M.calculate(self.b,self.p,self.ds,self.ds[-1]);self.assertEqual(r['scenarios'],[]);self.p[self.ds[-1]]=50;r=M.calculate(self.b,self.p,self.ds,self.ds[-1]);self.assertEqual(r['scenarios'],[])
 def test_no_future_observations_enter_asof_math(self):
  day=self.ds[-10];before=M.calculate(self.b,self.p,self.ds,day);self.b[self.ds[-1]]=1e9;self.p[self.ds[-1]]=1e9;self.assertEqual(before,M.calculate(self.b,self.p,self.ds,day))
 def test_snapshots_immutable_and_active_revision_explicit(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);a={'updated':'2026-10-30','s':{'2330':{'f':100}},'hist':{}};M.preserve_snapshot(a,root);M.preserve_snapshot(a,root);first=list((root/'archive/hist/margin').glob('*/*.gz'));self.assertEqual(len(first),1);old=first[0].read_bytes();a['s']['2330']['f']=90;M.preserve_snapshot(a,root);self.assertEqual(len(list((root/'archive/hist/margin').glob('*/*.gz'))),2);self.assertEqual(first[0].read_bytes(),old);active=M.read(root/'archive/hist/margin/active.json');self.assertEqual(M.read(root/'archive/hist/margin/2026-10-30'/(active['2026-10-30']+'.json.gz'))['s']['2330']['f'],90)
if __name__=='__main__':unittest.main()
