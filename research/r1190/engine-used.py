"""r1190: own-stock extreme-decline episodes; equal 60-bar endpoint including cash waits."""
import argparse, collections, gzip, hashlib, json, pickle
from pathlib import Path
import numpy as np
import pandas as pd
from portfolio_research import touch_exit
import stock_execution_audit as A

ROOT=Path(__file__).resolve().parent
METHODS=('immediate','reclaim10','break20')

def features(e):
 a=e['a'];c=pd.Series(a[:,3]);h=pd.Series(a[:,1]);ma10=c.rolling(10).mean();ma20=c.rolling(20).mean();ma60=c.rolling(60).mean()
 b20=c/ma20-1;b60=c/ma60-1;dd=c/c.rolling(120).max()-1
 q=[x.shift(1).rolling(750,min_periods=250).quantile(.05) for x in (b20,b60,dd)]
 extreme=((b20<=q[0]).astype(int)+(b60<=q[1]).astype(int)+(dd<=q[2]).astype(int)>=2)&(dd<=-.10)
 newlow=c<=c.rolling(20).min();up=(c>ma10)&~newlow.rolling(3).max().fillna(1).astype(bool);br=c>h.shift(1).rolling(20).max()
 return {'extreme':extreme.to_numpy(),'reclaim10':up.to_numpy(),'break20':br.to_numpy(),'q':[x.to_numpy() for x in q],'dd':dd.to_numpy()}

def simulate(e,signal,onset,end,market,calendar):
 ds=e['d'];a=e['a'];ei=signal+1
 if ei>=end or calendar.get(ds[ei])!=calendar.get(ds[signal],-2)+1 or a[ei,4]<=0:return {'filled':False,'r':0.,'reason':'missing_next_open'}
 entry=float(a[ei,0]);stop=entry*.8;target=entry*(1.5 if market=='TW' else 1.3);xi=end-1;px=float(a[xi,3]);why='episode_mark'
 for k in range(ei,end):
  if a[k,4]<=0:continue
  value,reason=touch_exit(*a[k,:3],stop,target)
  if value is not None:xi=k;px=float(value);why=reason;break
 anchor=float(np.min(a[max(0,signal-19):signal+1,3]));after=a[signal+1:min(signal+21,end),3];observed=signal+21<=end
 return {'filled':True,'signal':ds[signal],'entry_day':ds[ei],'entry':entry,'exit_day':ds[xi],'exit':px,'why':why,'r':float(px*.997/(entry*1.003)-1),'anchor':anchor,'break20_observed':observed,'broke_anchor20':bool(np.any(after<anchor)) if observed else None,'bars_waited':signal-onset}

def episodes(e,market,f,period,calendar):
 ds=e['d'];a=e['a'];start,end=A.PERIODS[period];lo=int(np.searchsorted(ds,start));cap=int(np.searchsorted(ds,end));out=[];last=-1
 edge=f['extreme']&~np.r_[False,f['extreme'][:-1]]
 for i in np.flatnonzero(edge):
  i=int(i)
  if i<max(lo,370) or i>=cap-1 or i<=last or not(e['liq'][i]>=2e4 and a[i,4]>0) or (market=='TW' and e['known_bad'][i]):continue
  finish=min(i+61,cap);row={'onset':ds[i],'end':ds[finish-1],'complete60':i+61<=cap,'extreme_close':float(a[i,3]),'legs':{}}
  for method in METHODS:
   candidates=[i] if method=='immediate' else [k for k in range(i,min(i+21,finish-1)) if f[method][k] and e['liq'][k]>=2e4 and a[k,4]>0 and not(market=='TW' and e['known_bad'][k])]
   signal=candidates[0] if candidates else None
   row['legs'][method]=simulate(e,signal,i,finish,market,calendar) if signal is not None else {'filled':False,'r':0.,'reason':'no_confirmation20'}
  out.append(row);last=finish-1
 return out

def summarize(rows):
 out={'episodes':len(rows),'complete60':sum(r['complete60'] for r in rows),'methods':{}}
 avg=lambda xs:round(float(np.mean(xs)),3) if xs else None
 for m in METHODS:
  legs=[r['legs'][m] for r in rows];filled=[x for x in legs if x['filled']];complete=[r['legs'][m] for r in rows if r['complete60']];obs=[x for x in filled if x['break20_observed']];years=collections.defaultdict(list)
  for r,x in zip(rows,legs):years[r['onset'][:4]].append(x['r'])
  loss=-sum(x['r'] for x in filled if x['r']<0)
  out['methods'][m]={'filled':len(filled),'cash':len(legs)-len(filled),'avg_all_pct':avg([x['r']*100 for x in legs]),'avg_filled_pct':avg([x['r']*100 for x in filled]),'complete60_avg_pct':avg([x['r']*100 for x in complete]),'winners':sum(x['r']>0 for x in filled),'pf':round(sum(x['r'] for x in filled if x['r']>0)/loss,3) if loss>0 else None,'worst_pct':round(min(x['r'] for x in legs)*100,3) if legs else None,'anchor_observed20':len(obs),'broke_anchor20':sum(x['broke_anchor20'] for x in obs),'wait_median':round(float(np.median([x['bars_waited'] for x in filled])),2) if filled else None,'positive_years':int(sum(np.mean(v)>0 for v in years.values())),'years':len(years)}
 return out

def run(output):
 if output.exists():raise FileExistsError('New immutable study directory required')
 output.mkdir(parents=True);parent=json.loads(gzip.decompress((ROOT/'research/r1186/execution-audit.json.gz').read_bytes()));old=json.loads(gzip.decompress((ROOT/'research/r1188/profiles.json.gz').read_bytes()))
 spec={'version':'r1190','periods':A.PERIODS,'source':'r1186/r1188','source_sha256':hashlib.sha256((ROOT/'research/r1186/execution-audit.json.gz').read_bytes()).hexdigest(),'cache_sha256':old['spec']['cache_sha256'],'engine_sha256_lf':hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),'onset':'First day at least 2 of own b20/b60/dd120 at or below preceding 750 valid observations 5th percentile (min250), and dd120<=-10%. No synthetic split from return jumps.','methods':METHODS,'waiting_bars':20,'common_endpoint_bars':60,'entry':'Next market session open only; unavailable opening remains cash. Same initial cash per episode; no redeployment.','exit':'-20% stop; TW+50% / US+30% target; common 60th stock-bar close marked including fees; not formal 120/90-bar strategy returns.','fee_each_side':.003,'limits':['Previously examined periods; not fresh holdout','Current universe/revised adjusted bars, no full delisted universe or queue/tax reconstruction','Same-stock episode windows do not overlap; stocks can cluster together','Missed confirmations remain zero-return cash; filled-only mean shown separately','Last incomplete episodes retained; full60 comparison separately reported','20-bar anchor failure is descriptive after the signal, not a prediction']}
 (output/'spec.json').write_bytes(json.dumps(spec,ensure_ascii=False,indent=2).encode());result={'schema':1,'version':'r1190','research_only':True,'spec':spec,'stocks':{},'totals':{}};pooled={}
 for market in ('TW','US'):
  sign=parent['markets'][market]['signature'];p=ROOT/'.cache/r1186-complete'/parent['spec']['asof']/(market.lower()+'_'+sign[:16]+'.pkl.gz');assert hashlib.sha256(p.read_bytes()).hexdigest()==spec['cache_sha256'][market]
  with gzip.open(p,'rb') as z:stocks=pickle.load(z) # Only our trusted local cache, checked before loading.
  calendar={d:i for i,d in enumerate(sorted({d for e in stocks.values() for d in e['d']}))};details={};count=0
  for sid,e in stocks.items():
   key=market+':'+sid;meta=old['stocks'][key];sha=hashlib.sha256(('\n'.join(e['d'])).encode()+e['a'].astype('<f8').tobytes()).hexdigest();assert sha==meta['bars_sha256'];f=features(e)
   s={'key':key,'name':meta['name'],'first':meta['first'],'asof':meta['asof'],'bars':meta['bars'],'bars_sha256':sha,'periods':{}};details[sid]={}
   for period in A.PERIODS:
    rows=episodes(e,market,f,period,calendar);s['periods'][period]=summarize(rows);details[sid][period]=rows;count+=len(rows);pooled.setdefault(market,{}).setdefault(period,[]).extend(rows)
   result['stocks'][key]=s
  (output/(market+'-episodes.json.gz')).write_bytes(gzip.compress(json.dumps(details,separators=(',',':'),allow_nan=False).encode(),mtime=0));result['totals'][market]=count;print(market,count,flush=True)
 result['pooled']={m:{t:summarize(rows) for t,rows in ts.items()} for m,ts in pooled.items()}
 (output/'profiles.json.gz').write_bytes(gzip.compress(json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),mtime=0));print('DONE',len(result['stocks']),flush=True)
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);run(p.parse_args().output)
