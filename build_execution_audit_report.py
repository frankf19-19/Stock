"""Build the r1186 reproducible, compact research viewer. No new live signals."""
import argparse,gzip,json,hashlib
from pathlib import Path
import stock_execution_audit as A

FIELDS=['n','completed','open_marks','avg_pct','win_pct','pf','worst_trade_pct','median_days','capital_return_pct','cagr_pct','mdd_pct']
def build(root):
 raw_path=root/'execution-audit.json';j=json.loads(raw_path.read_bytes() if raw_path.exists() else gzip.decompress((root/'execution-audit.json.gz').read_bytes()));small={'schema':1,'version':'r1186','spec':j['spec'],'fields':FIELDS,'source_commit':j['source_commit'],'engine_sha256':j['engine_sha256'],'markets':{},'stocks':{}}
 for market,m in j['markets'].items():small['markets'][market]={k:v for k,v in m.items() if k!='sources'}
 for key,s in j['stocks'].items():
  small['stocks'][key]={k:s[k] for k in ['name','first','asof','bars','current_atrp']};small['stocks'][key]['groups']={g:{p:{t:[v.get(k) for k in FIELDS] for t,v in periods.items()} for p,periods in ps.items()} for g,ps in s['groups'].items()}
 raw=json.dumps(small,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode();(root/'profiles.json.gz').write_bytes(gzip.compress(raw,mtime=0))
 sources={'engine_path':'engine-used.py','loader_path':'loader-used.py','loader_sha256':j.get('loader_sha256'),'source_commit':j['source_commit'],'engine_sha256':j['engine_sha256'],'profiles_uncompressed_sha256':hashlib.sha256(raw).hexdigest(),'markets':{m:{k:v for k,v in z.items() if k in ('sources','signature','stocks','calendar_first','calendar_last')} for m,z in j['markets'].items()}}
 (root/'sources.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2),encoding='utf-8');(root/'report.html').write_bytes(Path('execution_audit_report.html').read_bytes());print('viewer stocks',len(small['stocks']),'gzip bytes',(root/'profiles.json.gz').stat().st_size)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);build(p.parse_args().root)
