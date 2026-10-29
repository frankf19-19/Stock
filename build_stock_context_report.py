"""r1189: verify frozen inputs, copy report and code snapshot, build source manifest."""
import argparse, gzip, hashlib, json
from pathlib import Path

def build(root):
 j=json.loads(gzip.decompress((root/'profiles.json.gz').read_bytes()));spec=json.loads((root/'spec.json').read_bytes());assert j['spec']==spec
 for n,h in spec['source_sha256'].items():assert hashlib.sha256((Path('research/r1188')/n).read_bytes()).hexdigest()==h
 engine=Path('stock_context_study.py').read_bytes().replace(b'\r\n',b'\n');assert hashlib.sha256(engine).hexdigest()==spec['engine_sha256_lf']
 # Main cards need only exact counts and displayed values; retain the complete report separately.
 web={'schema':1,'version':'r1189','research_only':True,'source_sha256':hashlib.sha256((root/'profiles.json.gz').read_bytes()).hexdigest(),'stocks':{}}
 for key,s in j['stocks'].items():
  out={'key':key,'asof':s['asof'],'groups':{}}
  for g,ts in s['groups'].items():
   audit={k:{f:v[f] for f in ('n','avg','worst')} for k,v in ts['audit'].items()};audit['all']['exits']={p:{f:ts['audit']['all']['exits'][p][f] for f in ('avg','delta')} for p in ('weak20','protect10')}
   out['groups'][g]={'development':{'all':{'n':ts['development']['all']['n']}},'validation':{'all':{'n':ts['validation']['all']['n']}},'audit':audit}
  web['stocks'][key]=out
 (root/'web.json.gz').write_bytes(gzip.compress(json.dumps(web,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),mtime=0))
 (root/'engine-used.py').write_bytes(engine);(root/'report.html').write_bytes(Path('stock_context_report.html').read_bytes().replace(b'\r\n',b'\n'))
 files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file() and p.name!='source-checks.json'}
 (root/'source-checks.json').write_bytes(json.dumps({'source':'r1188','files':files},indent=2).encode());print('verified stocks',len(j['stocks']))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);build(p.parse_args().root)
