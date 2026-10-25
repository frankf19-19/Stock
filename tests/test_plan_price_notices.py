import unittest,sys,types,json,hashlib
from unittest.mock import patch
from pathlib import Path
with patch.dict(sys.modules,{'requests':types.SimpleNamespace()}):
 import notify as N

class PlanNoticeTests(unittest.TestCase):
 def row(self,price=2422):
  return {'TW:2330':{'price':price,'events':[{'kind':'fp_entry','planKey':'fp_entry|TW|2330|2026-10-22|abc','title':'到個股評估區','text':'評估上限2425；目前先不買'}]}}
 def test_background_selects_exact_shared_event_and_keeps_waiting(self):
  with patch.object(N,'plan_price_events',return_value=self.row()):r=N.collect_plan_price_events({'id':'2330','market':'TW','name':'台積電'},2422,['fp_entry'])
  self.assertEqual(len(r),1);self.assertIn('目前先不買',r[0][2]);self.assertIn('2425',r[0][2]);self.assertTrue(r[0][0].startswith('fp_entry|'))
 def test_no_selection_or_quote_mismatch_means_no_approximate_fallback(self):
  with patch.object(N,'plan_price_events',return_value=self.row()):
   self.assertEqual(N.collect_plan_price_events({'id':'2330','market':'TW'},2422,[]),[])
   self.assertEqual(N.collect_plan_price_events({'id':'2330','market':'TW'},2410,['fp_entry']),[])
 def test_background_failure_returns_empty_and_does_not_send_or_guess(self):
  with patch.object(N,'_PLAN_NOTICE_CACHE',None),patch.object(N.shutil,'which',return_value=None):self.assertEqual(N.plan_price_events(),{})
 def test_new_plan_kinds_filter_and_critical_defense_priority(self):
  event=('fp_stop|TW|2330|2026-10-22|abc',3,'x');self.assertEqual(N.filter_notice_events([event],['fp_stop','btm_v1','ins_v1']),[event]);self.assertEqual(N.filter_notice_events([event],[]),[]);self.assertTrue(N.notice_important(event));self.assertEqual(N.cat_of(event[0]),'fav')
 def test_browser_and_background_use_same_event_tag_and_stock_link(self):
  key='fp_stop|TW|2330|2026-10-22|abc';r=N.notice_summary([(key,3,'台積電(2330)跌破2365')],{'stocks':[{'id':'2330','name':'台積電'}]});self.assertEqual(r['tag'],'kyansuo-plan-'+key.replace('|','-'));self.assertTrue(r['url'].endswith('#stock/2330'))
 def test_us_favorites_collect_plan_notices_without_using_tw_technical_rules(self):
  data={'stocks':[{'id':'AAPL','market':'US','name':'Apple'}]};row={'US:AAPL':{'price':100,'events':[{'kind':'fp_entry','planKey':'fp_entry|US|AAPL|2026-10-22|x','title':'評估區','text':'先不買'}]}}
  with patch.object(N,'plan_price_events',return_value=row):r=N.collect_fav_events(data,{}, {'AAPL':100},{'fav_ids':['AAPL'],'cats':['fp_entry']})
  self.assertEqual(len(r),1);self.assertTrue(r[0][0].startswith('fp_entry|US|'))
 def test_python_to_node_bridge_runs_read_only_with_same_source_hash(self):
  with patch.object(N,'_PLAN_NOTICE_CACHE',None):
   r=N.plan_price_events();self.assertGreater(len(r),100);p=r['TW:2330']['current'];self.assertGreater(p['entry'],p['stop']);self.assertGreater(p['target'],p['entry'])
 def test_workflows_explicitly_provide_node_before_notifications(self):
  root=Path(__file__).resolve().parent.parent
  for name in ('update_quotes.yml','update_data.yml'):
   source=(root/'.github/workflows'/name).read_text(encoding='utf-8');self.assertLess(source.index('actions/setup-node@v4'),source.index('python notify.py'))
if __name__=='__main__':unittest.main()
