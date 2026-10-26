import gzip,hashlib,json,tempfile,unittest
from pathlib import Path
from build_inline_trade_profiles import build

ROOT=Path(__file__).resolve().parents[1]

class InlineTradeProfileTests(unittest.TestCase):
    def test_compact_view_keeps_all_stock_results_and_never_gives_rejected_plan(self):
        source=ROOT/'research/r1170/conditional-plans.json.gz';raw=source.read_bytes();original=json.loads(gzip.decompress(raw))
        view=json.loads((ROOT/'trade_research_profiles.json').read_bytes())
        self.assertEqual(view['source_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(set(view['stocks']),set(original['stocks']))
        for key,s in original['stocks'].items():
            v=view['stocks'][key];self.assertEqual(v['selected'],s['development_selected']);self.assertEqual(v['supported'],s['validation_supported'])
            if not v['supported']:self.assertIsNone(v['plan'])
            for model,periods in s['models'].items():
                for short,long in [('d','development'),('v','validation'),('a','recent_audit')]:
                    self.assertEqual(v['models'][model][short][:3],[periods[long]['n'],periods[long]['completed'],periods[long]['avg_pct']])

    def test_generator_does_not_overwrite_study_or_calendar_and_matches_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'research/r1170').mkdir(parents=True)
            for file in ['research/r1170/conditional-plans.json.gz','holidays.json']:(root/file).write_bytes((ROOT/file).read_bytes())
            before={file:hashlib.sha256((root/file).read_bytes()).hexdigest() for file in ['research/r1170/conditional-plans.json.gz','holidays.json']}
            actual=build(root);expected=build(root)
            self.assertEqual(actual,expected)
            for file,h in before.items():self.assertEqual(hashlib.sha256((root/file).read_bytes()).hexdigest(),h)

if __name__=='__main__':unittest.main()
