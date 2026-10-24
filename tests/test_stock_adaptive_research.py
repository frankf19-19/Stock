import unittest,datetime as dt,json,gzip,tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import stock_adaptive_research as R


class AdaptiveResearchTests(unittest.TestCase):
 def sample(self,rows,dates=None):
  dates=dates or [f'2024-01-{i+2:02d}' for i in range(len(rows))]
  e={'d':dates,'a':np.array(rows,float),'idx':{d:i for i,d in enumerate(dates)},'atr':np.full(len(rows),5.)}
  event={'sid':'A','day':dates[0],'i':0,'threshold':.4,'bucket':1,'liq':1e5}
  return {'A':e},dates,{dates[0]:[event]}
 def test_atr_floors_caps_and_market_baselines(self):
  self.assertEqual(R.exit_terms('TW','baseline',100,3),(.15,.2,60))
  self.assertEqual(R.exit_terms('US','baseline',100,3),(.2,.3,90))
  self.assertAlmostEqual(R.exit_terms('TW','atr4_rr1.5',100,1)[0],.08)
  self.assertAlmostEqual(R.exit_terms('TW','atr4_rr1.5',100,20)[0],.25)
 def test_opening_stop_precedes_later_target(self):
  s,d,c=self.sample([[100,100,100,100,1],[100,100,100,100,1],[70,140,60,120,1]])
  r=R.simulate_adaptive(s,d,c,'TW','baseline',{})
  self.assertEqual(r['trades'][0]['exit'],70);self.assertEqual(r['trades'][0]['why'],'gap_sl')
 def test_same_bar_both_touch_stop_first(self):
  s,d,c=self.sample([[100,100,100,100,1],[100,130,80,110,1]])
  r=R.simulate_adaptive(s,d,c,'TW','baseline',{})
  self.assertEqual(r['trades'][0]['exit'],85)
 def test_no_same_day_buy_and_unfinished_loss_marked(self):
  s,d,c=self.sample([[100,100,100,100,1],[100,101,90,90,1]])
  r=R.simulate_adaptive(s,d,c,'TW','baseline',{})
  self.assertEqual(r['curve'][0]['positions'],0);self.assertEqual(r['metrics']['open_positions'],1)
  self.assertLess(r['metrics']['final_nav'],1);self.assertEqual(r['trades'],[])
 def test_next_market_session_only_no_indefinite_suspension_order(self):
  s,d,c=self.sample([[100,100,100,100,1],[100,100,100,100,1]],['2024-01-02','2024-01-04'])
  r=R.simulate_adaptive(s,['2024-01-02','2024-01-03','2024-01-04'],c,'TW','baseline',{})
  self.assertEqual(r['metrics']['cancelled_unavailable_open'],1);self.assertEqual(r['metrics']['open_positions'],0)
 def test_risk_budget_does_not_borrow_or_exceed_slot_capital(self):
  s,d,c=self.sample([[100,100,100,100,1],[100,100,100,100,1]]);s['A']['atr'][:]=20
  r=R.simulate_adaptive(s,d,c,'TW','atr4_riskcap3pct',{})
  self.assertAlmostEqual(r['curve'][1]['cash'],.88)
  self.assertGreaterEqual(r['metrics']['min_cash'],0)
 def test_future_prices_do_not_change_past_wealth(self):
  s,d,c=self.sample([[100,101,99,100,1]]*4);one=R.simulate_adaptive(s,d,c,'TW','baseline',{})
  s['A']['a'][-1]=[10,12,8,11,1];two=R.simulate_adaptive(s,d,c,'TW','baseline',{})
  self.assertEqual(one['curve'][:-1],two['curve'][:-1])
 def test_model_training_requires_all_labels_to_mature_before_cutoff(self):
  rows=[]
  for i in range(120):
   x={'sid':str(i%10),'day':f'2018-{i%12+1:02d}-01','mature':True,'mature_day':'2020-01-01','bucket':i%3}
   x['outcomes']={n:{'r':1 if n!='baseline' else 0} for n in R.EXIT_NAMES};rows.append(x)
  models,audit=R.fit_years(rows,[2020]);self.assertEqual(audit[0]['global_diagnostics']['n'],0)
  self.assertEqual(models[2020]['global'],'baseline')
 def test_individual_small_sample_falls_back(self):
  name,d=R.choose_exit([{}]*19,20,50,single_stock=True)
  self.assertEqual(name,'baseline');self.assertEqual(d['reason'],'insufficient_events')
 def test_unfinished_serial_trade_blocks_later_winners(self):
  def e(i,exit_i,why,r):
   return {'sid':'A','i':i,'day':f'2024-01-{i+2:02d}','bucket':1,'er':0,'sec':'x','outcomes':{n:{'why':why,'exit_i':exit_i,'exit_day':f'2024-01-{exit_i+2:02d}','r':r} for n in R.EXIT_NAMES}}
  self.assertEqual(R.serial_events([e(0,10,'boundary_mark',-.1),e(2,3,'tp',.2)],'baseline',{}),[])
 def test_raw_liquidity_not_reduced_by_future_dividend_factor(self):
  Path('.cache').mkdir(exist_ok=True)
  with tempfile.TemporaryDirectory(dir='.cache') as tmp:
   root=Path(tmp).resolve();p=root/'archive/k/tw/2020/x.json.gz';p.parent.mkdir(parents=True)
   dates=[(dt.date(2020,1,1)+dt.timedelta(days=i)).isoformat() for i in range(300)]
   p.write_bytes(gzip.compress(json.dumps({'1111':{'d':dates,'o':[[100,101,99,100,300]]*300}}).encode()))
   (root/'data.json').write_text(json.dumps({'stocks':[{'id':'1111','market':'TW'}]}))
   (root/'archive/adj_tw.json.gz').write_bytes(gzip.compress(json.dumps({'s':{'1111':[[dates[290],.5]]}}).encode()))
   with patch.object(R,'ROOT',root):s,_,_=R.load_market('TW',root/'cache')
   self.assertEqual(s['1111']['liq'][260],30000);self.assertEqual(s['1111']['a'][260,3],50)
 def test_no_preselection_using_tomorrows_missing_stock_bar(self):
  n=251;dates=[(dt.date(2020,1,1)+dt.timedelta(days=i)).isoformat() for i in range(n)]
  e={'d':dates,'a':np.array([[100,101,99,100,300]]*n,float),'dd':np.r_[np.zeros(250),-.5],'liq':np.full(n,30000.),'atr':np.full(n,2.),'atrp':np.full(n,.02),'er':np.zeros(n),'known_bad':np.zeros(n,bool),'own_threshold':np.full(n,.4),'own_eligible':np.ones(n,bool),'sec':'test'}
  events,candidates,own=R.build_events({'A':e},'TW')
  self.assertEqual(events,[]);self.assertEqual(len(candidates[dates[-1]]),1)
 def test_no_fill_when_next_day_volume_is_zero(self):
  s,d,c=self.sample([[100,100,100,100,1],[100,130,80,110,0],[100,101,99,100,1]])
  r=R.simulate_adaptive(s,d,c,'TW','baseline',{})
  self.assertEqual(r['metrics']['cancelled_unavailable_open'],1);self.assertEqual(r['trades'],[]);self.assertEqual(r['metrics']['final_nav'],1)
 def test_capital_reduction_continuity_and_no_double_adjustment(self):
  with tempfile.TemporaryDirectory(dir='.cache') as tmp:
   base=Path(tmp).resolve();root=base/'Stock';p=root/'archive/k/tw/2020/x.json.gz';p.parent.mkdir(parents=True)
   dates=[(dt.date(2020,1,1)+dt.timedelta(days=i)).isoformat() for i in range(300)]
   bars=[[8,8,8,8,4000]]*290+[[80,80,80,80,400]]*10
   p.write_bytes(gzip.compress(json.dumps({'1111':{'d':dates,'o':bars}}).encode()))
   (root/'data.json').write_bytes(json.dumps({'stocks':[{'id':'1111','market':'TW'}]}).encode())
   actions=root/'archive/stock_research/r1161/raw';actions.mkdir(parents=True)
   (actions/'capital_reductions.json').write_bytes(json.dumps({'sources':{'1111':{'payload':{'data':[{'stock_id':'1111','date':dates[290],'ClosingPriceonTheLastTradingDay':8,'PostReductionReferencePrice':80}]}}}}).encode())
   for already in [False,True]:
    (root/'archive/adj_tw.json.gz').write_bytes(gzip.compress(json.dumps({'s':{'1111':[[dates[290],10]]} if already else {}}).encode()))
    with patch.object(R,'ROOT',root):stocks,_,_=R.load_market('TW',root/('cache'+str(already)))
    self.assertEqual(stocks['1111']['a'][289,3],80)
    self.assertEqual(stocks['1111']['a'][290,3],80)
    self.assertEqual(stocks['1111']['liq'][260],32000)
if __name__=='__main__':unittest.main()
