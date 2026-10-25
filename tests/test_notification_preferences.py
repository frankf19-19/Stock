import unittest
from unittest.mock import patch
import sys,types
def blocked(*a,**k):raise AssertionError('Real network is forbidden in notification tests')
with patch.dict(sys.modules,{'requests':types.SimpleNamespace(get=blocked,post=blocked)}):
 import notify as N

class NoticeTests(unittest.TestCase):
 def test_empty_and_markers_only_mean_no_notifications(self):
  events=[('fill|x|2330',1,'x'),('fz|x|2330',3,'x'),('sl|x|2330',2,'x')]
  self.assertEqual(N.filter_notice_events(events,[]),[])
  self.assertEqual(N.filter_notice_events(events,['btm_v1','ins_v1']),[])
  self.assertEqual(N.filter_notice_events(events,None),events)
 def test_legacy_category_and_rotated_fill_selection(self):
  e=[('rotbuy|x|2330',1,'x'),('fz|x|2330',3,'x'),('sl|x|2330',2,'x')]
  self.assertEqual(N.filter_notice_events(e,['fill','btm_v1','ins_v1']),e[:1])
  self.assertEqual(N.filter_notice_events(e,['fav','btm_v1','ins_v1']),e[1:2])
 def fixture(self,cost=None,px=120,fav=True,model=True):
  stock={'id':'2330','name':'台積電','market':'TW','al':{'bull':True,'z0':115,'z1':125}}
  aip={'weeks':[{'picks':[{'id':'2330','legs':[{'entry':100}]}]}]} if model else {}
  ud={'fav_ids':['2330'] if fav else [],'port1':[{'id':'2330','cost':cost}] if cost is not None else []}
  with patch.object(N,'plan_price_events',return_value={}),patch.object(N,'lead_signal',return_value=[]),patch.object(N,'_acc',return_value={}),patch.object(N,'fav_levels',return_value={}):
   return N.collect_fav_events({'stocks':[stock]},aip,{'2330':px},ud)
 def test_model_cost_never_becomes_user_cost(self):
  r=self.fixture();self.assertFalse(any(e[0].startswith(('ftp|','fsl|')) for e in r))
 def test_holdings_do_not_need_to_be_favorites_for_risk_notice(self):
  r=self.fixture(cost=100,px=90,fav=False);self.assertEqual(len(r),1);self.assertTrue(r[0][0].startswith('fsl|'));self.assertIn('93.0',r[0][2]);self.assertIn('持股成本',r[0][2])
 def test_invalid_user_cost_does_not_crash_other_observations(self):
  for cost in ('bad',float('nan'),float('inf'),-1):
   r=self.fixture(cost=cost);self.assertTrue(any(e[0].startswith('fz|') for e in r));self.assertFalse(any(e[0].startswith('ftp|') for e in r))
 def test_observation_copy_has_prices_and_no_buy_command(self):
  r=self.fixture();text=next(x[2] for x in r if x[0].startswith('fz|'));self.assertIn('最新可用價 120',text);self.assertIn('下一步',text);self.assertIn('不是買進確認',text)
 def test_risk_has_priority_and_bypasses_soft_daily_cap(self):
  stop=('fsl|x|2330',3,'stop');fill=('fill|x|2454',1,'fill');obs=('fz|x|2330',3,'obs')
  self.assertEqual(sorted([fill,obs,stop],key=N.notice_priority)[0],stop);self.assertTrue(N.notice_important(stop));self.assertFalse(N.notice_important(obs))
 def test_single_notification_names_stock_and_links_correct_page(self):
  r=N.notice_summary([('fz|x|2330',3,'<b>台積電</b>(2330)\n最新可用價 120')],{'stocks':[{'id':'2330','name':'台積電'}]})
  self.assertTrue(r['title'].startswith('台積電（2330）'));self.assertTrue(r['url'].endswith('#stock/2330'));self.assertNotIn('<b>',r['body']);self.assertEqual(r['tag'],'kyansuo-fz-2330-'+N.TODAY)
 def test_different_events_do_not_overwrite_whole_day_with_one_tag(self):
  d={'stocks':[{'id':'2330','name':'台積電'}]};a=N.notice_summary([('sl|x|2330',2,'a')],d);b=N.notice_summary([('fill|x|2330',1,'b')],d);self.assertNotEqual(a['tag'],b['tag']);self.assertEqual(a,N.notice_summary([('sl|x|2330',2,'a')],d))
 def test_multiple_risks_link_to_holdings(self):
  r=N.notice_summary([('ftp|x|2330',3,'a'),('fsl|x|2454',3,'b')],{'stocks':[]});self.assertTrue(r['url'].endswith('#port'))
if __name__=='__main__':unittest.main()
