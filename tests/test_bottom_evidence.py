import unittest, tempfile, json, gzip, datetime as dt
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import bottom as B
import stock_bottom_study as S

class BottomEvidenceTests(unittest.TestCase):
 def fixture(self,n=500):
  ds=np.busday_offset('2024-01-01',np.arange(n)).astype(str).tolist();return {'a':np.tile([100.,102.,98.,100.,1e5],(n,1)),'d':ds,'liq':np.full(n,1e5),'known_bad':np.zeros(n,bool)}
 def test_real_crash_not_rewritten_as_split(self):
  c=pd.DataFrame({'s':[100.,70.,71.]});other=c.copy();before=c.copy();bad=B.fix_split(c,[other]);pd.testing.assert_frame_equal(c,before);pd.testing.assert_frame_equal(other,before);self.assertTrue(bad.iloc[1,0])
 def test_explicit_split_applied_once_and_conflicts_not_guessed(self):
  a=B.explicit_adjustments({'2330':[['2020-01-01',.5]]},{'2330':[['2020-01-01',.4]]},[('2330','2020-01-01',.3),('0050','2025-06-18',.25),('bad','2020-01-01',.5),('bad','2020-01-01',.6)])
  self.assertEqual(a['2330'],[('2020-01-01',.4)]);self.assertEqual(a['0050'],[('2025-06-18',.25)]);self.assertNotIn('bad',a)
 def test_bad_latest_close_not_replaced_by_older_price(self):
  self.assertIsNone(B.thresholds([100.]*61+[None]));self.assertIsNone(B.thresholds([100.]*61+[0]));self.assertEqual(B.thresholds([None]*10+[100.]*62)['last'],100)
 def test_zero_volume_days_included_in_liquidity_average(self):self.assertFalse(B.liquid_value([100.]*20,[2e5]+[0.]*19,1));self.assertFalse(B.liquid_value([100.]*20,[None]+[2e5]*19,1));self.assertTrue(B.liquid_value([100.]*20,[2e5]*20,1))
 def test_margin_suspension_zero_is_not_washout(self):self.assertFalse(B.margin_washout([1000.]*19+[0.]));self.assertTrue(B.margin_washout([1000.]*19+[790.]));self.assertFalse(B.margin_washout([100.]*19+[79.]))
 def test_partial_and_future_tw_bars_excluded(self):
  with tempfile.TemporaryDirectory(dir='.cache') as folder:
   p=Path(folder)/'k.json';p.write_text(json.dumps({'2330':{'d':['2026-10-29','2026-10-30','2026-11-02'],'o':[[100,101,99,100,1]]*3}}))
   before=B.k_closes(str(p),now=dt.datetime.fromisoformat('2026-10-30T04:00:00+00:00'));after=B.k_closes(str(p),now=dt.datetime.fromisoformat('2026-10-30T06:00:00+00:00'));self.assertEqual(before['2330'][0],['2026-10-29']);self.assertEqual(after['2330'][0],['2026-10-29','2026-10-30'])
 def test_us_close_handles_summer_and_winter(self):
  with tempfile.TemporaryDirectory(dir='.cache') as folder:
   p=Path(folder)/'k.json'
   for day,pre,post in [('2026-07-01','19:59','20:01'),('2026-12-01','20:59','21:01')]:
    p.write_text(json.dumps({'AAPL':{'d':[day],'o':[[100,101,99,100,1]]}}));self.assertEqual(B.k_closes(str(p),market='US',now=dt.datetime.fromisoformat(day+'T'+pre+':00+00:00')),{});self.assertEqual(B.k_closes(str(p),market='US',now=dt.datetime.fromisoformat(day+'T'+post+':00+00:00'))['AAPL'][0],[day])
 def test_index_partial_close_is_not_a_confirmed_daily_bar(self):
  now=dt.datetime.fromisoformat('2026-10-30T04:00:00+00:00');ts=int(dt.datetime.fromisoformat('2026-10-30T00:00:00+00:00').timestamp())
  with patch.object(B,'jl',return_value={'series':{'^TWII':{'d':{'t':[ts],'c':[20000]}}}}):self.assertEqual(B.yext_daily('^TWII',now=now),[])
 def test_stats_versions_preserve_original_bytes(self):
  with tempfile.TemporaryDirectory(dir='.cache') as folder,patch.object(B,'AR',folder):
   p=Path(folder)/'stats.json';p.write_bytes(b'{"old":1}');B.preserve_stats(p);p.write_bytes(b'{"new":2}');B.preserve_stats(p);files=list((Path(folder)/'hist/bottom/stats_versions').glob('*.gz'));self.assertEqual({gzip.decompress(x.read_bytes()) for x in files},{b'{"old":1}',b'{"new":2}'})
 def test_own_quantiles_never_read_future_prices(self):
  e=self.fixture();e['a'][:,3]=np.linspace(100,120,500);f=S.features(e);e['a'][450:,:4]*=.1;z=S.features(e)
  for a,b in zip(f['q'],z['q']):np.testing.assert_array_equal(a[:450],b[:450])
  np.testing.assert_array_equal(f['extreme'][:450],z['extreme'][:450])
 def test_waiting_cash_not_removed_from_average(self):
  filled={'filled':True,'r':.2,'break20_observed':True,'broke_anchor20':False,'bars_waited':3};cash={'filled':False,'r':0}
  rows=[{'onset':'2024-01-01','complete60':True,'legs':{m:filled for m in S.METHODS}},{'onset':'2024-06-01','complete60':True,'legs':{m:cash for m in S.METHODS}}]
  x=S.summarize(rows)['methods']['break20'];self.assertEqual(x['avg_all_pct'],10);self.assertEqual(x['avg_filled_pct'],20);self.assertEqual(x['cash'],1)
 def test_missing_next_market_open_stays_cash(self):
  e=self.fixture();calendar={d:i for i,d in enumerate(e['d'])};calendar[e['d'][401]]=calendar[e['d'][400]]+2;self.assertFalse(S.simulate(e,400,400,461,'TW',calendar)['filled'])
 def test_stop_gap_uses_open_not_stop_price(self):
  e=self.fixture();e['a'][402]=[60,110,50,100,1e5];calendar={d:i for i,d in enumerate(e['d'])};x=S.simulate(e,400,400,461,'TW',calendar);self.assertEqual(x['exit'],60);self.assertEqual(x['why'],'gap_sl')
 def test_same_endpoint_does_not_extend_later_entry(self):
  e=self.fixture();calendar={d:i for i,d in enumerate(e['d'])};a=S.simulate(e,400,400,461,'TW',calendar);b=S.simulate(e,420,400,461,'TW',calendar);self.assertEqual(a['exit_day'],b['exit_day']);self.assertEqual(b['bars_waited'],20)
 def test_incomplete_anchor_window_not_counted_as_safe(self):
  e=self.fixture();calendar={d:i for i,d in enumerate(e['d'])};x=S.simulate(e,450,440,461,'TW',calendar);self.assertFalse(x['break20_observed']);self.assertIsNone(x['broke_anchor20'])
 def test_no_event_is_not_zero_risk(self):self.assertIsNone(S.summarize([])['methods']['immediate']['avg_all_pct'])
 def test_waiting_entry_excludes_invalid_signal_and_windows_do_not_overlap(self):
  e=self.fixture();e['d']=np.busday_offset('2024-01-01',np.arange(500)).astype(str).tolist();f={'extreme':np.zeros(500,bool),'reclaim10':np.zeros(500,bool),'break20':np.zeros(500,bool)};f['extreme'][400]=True;f['extreme'][420]=True;f['reclaim10'][405]=True;e['known_bad'][405]=True;cal={d:i for i,d in enumerate(e['d'])};rows=S.episodes(e,'TW',f,'audit',cal);self.assertEqual(len(rows),1);self.assertFalse(rows[0]['legs']['reclaim10']['filled'])

if __name__=='__main__':unittest.main()
