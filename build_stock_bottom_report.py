"""r1190: immutable study web export with canonical LF manifest."""
import argparse,gzip,json,hashlib
from pathlib import Path
def build(root):
 j=json.loads(gzip.decompress((root/'profiles.json.gz').read_bytes()));spec=json.loads((root/'spec.json').read_bytes());assert j['spec']==spec
 engine=Path('stock_bottom_study.py').read_bytes().replace(b'\r\n',b'\n');assert hashlib.sha256(engine).hexdigest()==spec['engine_sha256_lf']
 assert hashlib.sha256(Path('research/r1186/execution-audit.json.gz').read_bytes()).hexdigest()==spec['source_sha256']
 web={'schema':1,'version':'r1190','research_only':True,'source_sha256':hashlib.sha256((root/'profiles.json.gz').read_bytes()).hexdigest(),'stocks':{}}
 for k,s in j['stocks'].items():
  ps=s['periods'];a=ps['audit'];web['stocks'][k]={'key':k,'asof':s['asof'],'periods':{'development':{'episodes':ps['development']['episodes']},'validation':{'episodes':ps['validation']['episodes']},'audit':{'episodes':a['episodes'],'complete60':a['complete60'],'methods':{m:{f:v[f] for f in ('filled','avg_all_pct','anchor_observed20','broke_anchor20')} for m,v in a['methods'].items()}}}}
 (root/'web.json.gz').write_bytes(gzip.compress(json.dumps(web,separators=(',',':'),allow_nan=False).encode(),mtime=0));(root/'engine-used.py').write_bytes(engine);(root/'report.html').write_bytes(Path('stock_bottom_report.html').read_bytes().replace(b'\r\n',b'\n'))
 files={}
 for p in root.iterdir():
  if not p.is_file() or p.name=='source-checks.json':continue
  b=p.read_bytes();b=b.replace(b'\r\n',b'\n') if p.suffix in ('.json','.md','.py','.html') else b;p.write_bytes(b);files[p.name]=hashlib.sha256(b).hexdigest()
 (root/'source-checks.json').write_bytes(json.dumps({'source':'r1186/r1188','files':files},indent=2).encode());print('verified stocks',len(j['stocks']))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);build(p.parse_args().root)
