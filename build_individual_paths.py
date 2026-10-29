"""r1188: web export of immutable individual-path results; does not change metrics."""
import argparse,gzip,json,hashlib
from pathlib import Path

def build(root):
 j=json.loads(gzip.decompress((root/'profiles.json.gz').read_bytes()));parent_raw=Path('research/r1186/execution-audit.json.gz').read_bytes();assert hashlib.sha256(parent_raw).hexdigest()==j['spec']['source_sha256'];parent=json.loads(gzip.decompress(parent_raw))
 for key,s in j['stocks'].items():s['key']=key;s['current_atrp']=parent['stocks'][key]['current_atrp']
 (root/'web.json.gz').write_bytes(gzip.compress(json.dumps(j,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),mtime=0));(root/'report.html').write_bytes(Path('individual_paths_report.html').read_bytes())
 files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file() and p.name!='source-checks.json'};(root/'source-checks.json').write_bytes(json.dumps({'source_research':'r1186','files':files},indent=2).encode());print('stocks',len(j['stocks']))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);build(p.parse_args().root)
