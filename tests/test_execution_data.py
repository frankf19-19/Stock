import unittest,tempfile,gzip,json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import stock_execution_data as D

class ExecutionDataTests(unittest.TestCase):
 def fixture(self,root):
  ds=np.busday_offset('2019-01-01',np.arange(321)).astype(str).tolist();a=[[100,102,98,100,1000000] for _ in ds]
  (root/'archive/k/tw/2020').mkdir(parents=True);(root/'k').mkdir();(root/'archive/k/tw/2020/a.json.gz').write_bytes(gzip.compress(json.dumps({'2330':{'d':ds[:320],'o':a[:320]}}).encode()))
  (root/'data.json').write_text(json.dumps({'stocks':[{'id':'2330','market':'TW','name':'test'}]}),encoding='utf-8');(root/'archive/adj_tw.json.gz').write_bytes(gzip.compress(json.dumps({'s':{'2330':[['2019-03-01',.5]]}}).encode()));(root/'adj1y.json').write_text(json.dumps({'s':{'2330':[['2019-03-01',.5]]}}),encoding='utf-8')
  (root/'k/tw23.json').write_text(json.dumps({'2330':{'d':[ds[319],ds[320],'2027-01-01'],'o':[[110,112,108,110,1000000],[111,113,109,111,1000000],[1,2,.5,1,1000000]]}}),encoding='utf-8');return ds
 def test_recent_wins_overlap_and_adds_new_day_without_double_adjustment(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);ds=self.fixture(root)
   with patch.object(D,'ROOT',root):stocks,src,sig=D.load_market('TW',root/'cache')
   e=stocks['2330'];self.assertEqual(e['d'][-1],ds[320]);self.assertEqual(e['a'][-2,3],110);self.assertEqual(e['a'][-1,3],111);self.assertEqual(e['a'][0,3],50);self.assertTrue(any(Path(x['path']).as_posix()=='k/tw23.json' for x in src));self.assertNotIn('2027-01-01',e['d'])
 def test_recent_revision_invalidates_cached_dataset(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);self.fixture(root)
   with patch.object(D,'ROOT',root):
    _,_,first=D.load_market('TW',root/'cache');p=root/'k/tw23.json';j=json.loads(p.read_bytes());j['2330']['o'][-2]=[112,114,110,112,1000000];p.write_text(json.dumps(j),encoding='utf-8');s,_,second=D.load_market('TW',root/'cache')
   self.assertNotEqual(first,second);self.assertEqual(s['2330']['a'][-1,3],112)

if __name__=='__main__':unittest.main()
