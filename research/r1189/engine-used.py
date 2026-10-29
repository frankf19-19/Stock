"""r1189: own-stock signal-time contexts and two prespecified exit diagnostics. No live policy."""
import argparse, collections, gzip, hashlib, json, pickle
from pathlib import Path
import numpy as np
import pandas as pd
import stock_execution_audit as A
from portfolio_research import touch_exit

ROOT=Path(__file__).resolve().parent
POLICIES=('baseline','weak20','protect10')
AXES={'return20':[-.10,.10],'volume_ratio':[1.5],'ma60_slope':[0.0],'extension20':[0.0,.10]}

def features(e):
 a=e['a'];c=pd.Series(a[:,3]);v=pd.Series(a[:,4]);m20=c.rolling(20).mean();m60=c.rolling(60).mean()
 return {'return20':(c/c.shift(20)-1).to_numpy(),'volume_ratio':(v/v.shift(1).rolling(20).mean().replace(0,np.nan)).to_numpy(),'ma60_slope':(m60/m60.shift(20)-1).to_numpy(),'extension20':(c/m20-1).to_numpy()}

def classify(x):
 return {k:int(np.searchsorted(AXES[k],v+1e-12,side='right')) if v is not None and np.isfinite(v) else None for k,v in x.items()}

def exit_for(e,ei,g,policy,cap):
 a=e['a'];entry=float(a[ei,0]);sl,tp,hold,ma=A.terms(g,'baseline');stop=entry*(1-sl) if sl else None;target=entry*(1+tp) if tp else None
 below=0;pending=None;valid=0;finish=min(cap,ei+hold)
 for k in range(ei,finish):
  o,h,l,c,v=a[k]
  if v<=0:continue
  if pending:return k,float(o),pending
  valid+=1;px,why=touch_exit(o,h,l,stop,target)
  if px is not None:return k,float(px),why
  if ma:
   below=below+1 if k>ei and c<e['audit_features']['ma60'][k] else 0
   if below>=2:pending='ma_next_open'
  if policy=='weak20' and valid==20 and c<=entry:pending=pending or 'weak20_next_open'
  # This close is known only after today's touches; new stop is effective next session.
  if policy=='protect10' and c>=entry*1.10-entry*1e-12:stop=max(stop or 0,entry*1.003/.997)
  if k==finish-1:return k,float(c),'boundary_mark' if k==cap-1 else 'time_close'
 return finish-1,float(a[finish-1,3]),'boundary_mark'

def stats(rows):
 n=len(rows);avg=lambda z:round(float(np.mean(z)),3) if z else None
 out={'n':n,'open':sum(r['why']=='boundary_mark' for r in rows),'avg':avg([r['r']*100 for r in rows]),'worst':round(min(r['r'] for r in rows)*100,3) if rows else None,'mae':avg([r['path']['mae_pct'] for r in rows]),'hit10':sum(r['path']['hit_days']['10'] is not None for r in rows),'exits':{}}
 for p in POLICIES:
  # A cost-adjusted protective exit can leave machine-precision residue, not a win/loss.
  ret=[0.0 if abs(r['new_exits'][p]['r'])<1e-12 else r['new_exits'][p]['r'] for r in rows];loss=-sum(v for v in ret if v<0);years=collections.defaultdict(list)
  for r,v in zip(rows,ret):years[r['entry_day'][:4]].append(v)
  pair=[r for r in rows if r['why']!='boundary_mark' and r['new_exits'][p]['why']!='boundary_mark']
  out['exits'][p]={'avg':avg([v*100 for v in ret]),'delta':avg([(v-r['r'])*100 for v,r in zip(ret,rows)]),'wins':sum(v>0 for v in ret),'pf':round(sum(v for v in ret if v>0)/loss,3) if loss>0 else None,'positive_years':int(sum(np.mean(v)>0 for v in years.values())),'years':len(years),'open':sum(r['new_exits'][p]['why']=='boundary_mark' for r in rows),'paired_completed':len(pair),'completed_delta':avg([(r['new_exits'][p]['r']-r['r'])*100 for r in pair])}
 return out

def cohorts(rows):
 out={'all':stats(rows)}
 for axis,cuts in AXES.items():
  for i in range(len(cuts)+1):
   chosen=[r for r in rows if r['context']['bins'][axis]==i]
   if chosen:out[axis+':'+str(i)]=stats(chosen)
 return out

def run(output):
 if output.exists():raise FileExistsError('New research directory required; never overwrite completed studies')
 output.mkdir(parents=True);base=ROOT/'research/r1188';old=json.loads(gzip.decompress((base/'profiles.json.gz').read_bytes()));parent=json.loads(gzip.decompress((ROOT/'research/r1186/execution-audit.json.gz').read_bytes()))
 spec={'version':'r1189','source':'r1188','axes':AXES,'bucket_epsilon':1e-12,'policies':POLICIES,'periods':A.PERIODS,'fee_each_side':.003,'engine_sha256_lf':hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),'source_sha256':{n:hashlib.sha256((base/n).read_bytes()).hexdigest() for n in ['profiles.json.gz','TW-paths.json.gz','US-paths.json.gz']},'cache_sha256':old['spec']['cache_sha256'],'limits':['Descriptive own-stock cohorts; no model selection, no new orders or probability forecast','Signal-time features only; current closing conditions must be rechecked on an actual signal day','Cohorts overlap across axes; neither independent samples nor a portfolio','Existing survivorship, revised adjusted bars and intraday execution limitations remain','No financial dates imputed; historical publication timestamps incomplete','All historical periods already researched; not an untouched holdout']}
 (output/'spec.json').write_bytes(json.dumps(spec,ensure_ascii=False,indent=2).encode());result={'schema':1,'version':'r1189','research_only':True,'spec':spec,'stocks':{},'totals':{}};pool={}
 for market in ('TW','US'):
  sign=parent['markets'][market]['signature'];cp=ROOT/'.cache/r1186-complete'/parent['spec']['asof']/(market.lower()+'_'+sign[:16]+'.pkl.gz');assert hashlib.sha256(cp.read_bytes()).hexdigest()==spec['cache_sha256'][market]
  with gzip.open(cp,'rb') as f:stocks=pickle.load(f) # Only self-created trusted local cache, SHA verified before deserializing.
  ledger=json.loads(gzip.decompress((base/(market+'-paths.json.gz')).read_bytes()));details={};count=0
  for sid,e in stocks.items():
   key=market+':'+sid;meta=old['stocks'][key];assert len(e['d'])==meta['bars'] and e['d'][-1]==meta['asof'];A.prepare(e);f=features(e)
   sha=hashlib.sha256(('\n'.join(e['d'])).encode()+e['a'].astype('<f8').tobytes()).hexdigest();assert sha==meta['bars_sha256']
   latest={k:float(v[-1]) if np.isfinite(v[-1]) else None for k,v in f.items()};s={'key':key,'name':meta['name'],'first':meta['first'],'asof':meta['asof'],'bars':meta['bars'],'bars_sha256':sha,'current_atrp':float(e['atrp'][-1]),'latest':{'values':latest,'bins':classify(latest)},'groups':{}};detail={}
   for g,periods in ledger[sid].items():
    s['groups'][g]={};detail[g]={}
    for t,rows in periods.items():
     processed=[];cap=int(np.searchsorted(e['d'],A.PERIODS[t][1]))
     for original in rows:
      r={k:v for k,v in original.items() if k!='exits'};si=e['idx'][r['signal']];vals={k:float(v[si]) if np.isfinite(v[si]) else None for k,v in f.items()};r['context']={'values':vals,'bins':classify(vals)};ei=e['idx'][r['entry_day']];r['new_exits']={}
      for policy in POLICIES:
       xi,px,why=exit_for(e,ei,g,policy,cap);r['new_exits'][policy]={'exit_day':e['d'][xi],'exit':px,'why':why,'r':px*.997/(r['entry']*1.003)-1}
      b=r['new_exits']['baseline'];assert b['exit_day']==r['exit_day'] and b['why']==r['why'] and abs(b['r']-r['r'])<1e-10
      processed.append(r)
     s['groups'][g][t]=cohorts(processed);detail[g][t]=processed;count+=len(processed);pool.setdefault(market+':'+g,{}).setdefault(t,[]).extend(processed)
   result['stocks'][key]=s;details[sid]=detail
  (output/(market+'-contexts.json.gz')).write_bytes(gzip.compress(json.dumps(details,separators=(',',':'),allow_nan=False).encode(),mtime=0));result['totals'][market]=count;print(market,count,flush=True)
 result['pooled']={g:{t:cohorts(v) for t,v in ts.items()} for g,ts in pool.items()}
 (output/'profiles.json.gz').write_bytes(gzip.compress(json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),mtime=0));print('DONE',len(result['stocks']),flush=True)
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);run(p.parse_args().output)
