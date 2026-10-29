import unittest,tempfile,json,gzip
from pathlib import Path
from unittest.mock import patch
import build_execution_audit_report as B

class ExecutionReportTests(unittest.TestCase):
 def test_compact_fields_and_source_fingerprint_are_preserved(self):
  metrics={k:i for i,k in enumerate(B.FIELDS)};j={'spec':{'asof':'2026-10-28'},'source_commit':'abc','engine_sha256':'def','markets':{'TW':{'sources':[{'sha256':'xyz'}],'signature':'sig','stocks':1,'aggregate':{}}},'stocks':{'TW:2330':{'name':'台積電','first':'2012-01-02','asof':'2026-10-28','bars':3000,'current_atrp':.02,'groups':{'break_low':{'baseline':{'audit':metrics}}}}}}
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'execution-audit.json').write_text(json.dumps(j),encoding='utf-8');B.build(root);v=json.loads(gzip.decompress((root/'profiles.json.gz').read_bytes()));self.assertEqual(v['stocks']['TW:2330']['groups']['break_low']['baseline']['audit'],list(range(len(B.FIELDS))));self.assertNotIn('sources',v['markets']['TW']);self.assertEqual(json.loads((root/'sources.json').read_bytes())['markets']['TW']['sources'][0]['sha256'],'xyz')
 def test_viewer_has_stock_link_periods_and_conservative_disclosure(self):
  h=Path('execution_audit_report.html').read_text(encoding='utf-8-sig');self.assertIn('DecompressionStream',h);self.assertIn('獲利因子',h);self.assertIn('期末未出場',h);self.assertIn('不是你的預期獲利',h);self.assertIn('history.replaceState',h)

if __name__=='__main__':unittest.main()
