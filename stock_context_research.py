"""r1166: stock-specific conditional price scenarios; research only, never live signals."""
import argparse,collections,datetime as dt,gzip,hashlib,json,subprocess
from pathlib import Path
import numpy as np
import pandas as pd
import stock_adaptive_research as R
from portfolio_research import touch_exit

FAMILIES=('pullback','range','reclaim')
PERIODS={'first':('2016-01-01','2021-01-01'),'second':('2021-01-01',None)}

def features(e):
 a=e['a'];c=a[:,3];f={}
 for n in (20,60):
  f['ma'+str(n)]=R.rolling_mean(c,n)
  f['hi'+str(n)]=pd.Series(a[:,1]).rolling(n).max().to_numpy()
  f['lo'+str(n)]=pd.Series(a[:,2]).rolling(n).min().to_numpy()
 f['ma60past']=np.r_[np.full(10,np.nan),f['ma60'][:-10]]
 e['context']=f
 return f

def scenario(c,ma20,ma60,ma60past,hi20,hi60,lo20,lo60,atr):
 """All arguments are close-known. A scenario is NOT an executable signal."""
 vals=(c,ma20,ma60,ma60past,hi20,hi60,lo20,lo60,atr)
 if not all(np.isfinite(v) and v>0 for v in vals):return None
 if hi20<lo20 or hi60<lo60:return None
 if c>=ma60 and ma20>=ma60 and ma60-ma60past>.25*atr:
  kind='pullback';stop=lo20-.5*atr;target=hi60;confirm=ma20
  entry=min(ma20,c-.25*atr,(target+1.5*stop)/2.5)
 elif c<ma60-.5*atr or ma60-ma60past<-.25*atr:
  kind='reclaim';line=min([x for x in (ma20,ma60) if x>c] or [ma20])
  confirm=line;entry=line+.25*atr;stop=lo20-.5*atr;target=hi60
 else:
  kind='range';stop=lo60-.5*atr;target=hi20;confirm=lo20
  entry=min(lo20+.25*atr,c-.25*atr,(target+1.5*stop)/2.5)
 risk=entry-stop;reward=target-entry
 valid=stop>0 and risk>=.5*atr and reward>0 and reward/risk>=1.5-1e-9
 return dict(kind=kind,entry=float(entry),stop=float(stop),target=float(target),confirm=float(confirm),
   low=float(entry-.25*atr),rr=float(reward/risk) if risk>0 else None,valid=bool(valid),atr=float(atr),hold=40)

def at(e,i):
 f=e['context'];return scenario(e['a'][i,3],*(f[k][i] for k in ('ma20','ma60','ma60past','hi20','hi60','lo20','lo60')),e['atr'][i])

def confirmed(e,i,p):
 if p['kind']=='reclaim':
  return e['a'][i-1,3]<p['confirm'] and e['a'][i,3]>=p['confirm']
 # A pullback/range order is allowed only after a positive close near its price area.
 return e['a'][i,3]>=e['a'][i-1,3] and e['a'][i,2]<=p['entry']+e['atr'][i]*.5

def run(e,market,start,end,calendar):
 a=e['a'];d=e['d'];out=[];last=-1;cap=len(d) if end is None else int(np.searchsorted(d,end))
 for i in range(250,cap-1):
  if i<=last or d[i]<start or e['liq'][i]<2e4 or (market=='TW' and e['known_bad'][i]):continue
  p=at(e,i-1) # lock levels before the confirmation session
  if not p or not p['valid'] or a[i,2]<=p['stop'] or a[i,3]>=p['target'] or not confirmed(e,i,p):continue
  ei=i+1
  # Orders live for one market session; missing symbol bar cancels, no indefinite suspension wait.
  ci=calendar.index(d[i])
  if ci+1>=len(calendar) or calendar[ci+1]!=d[ei] or a[ei,4]<=0:continue
  o,h,l,c,v=a[ei]
  if o<=p['stop'] or l>p['entry']:continue
  entry=min(o,p['entry']);intraday=o>p['entry']
  for k in range(ei,min(cap,ei+p['hold'])):
   o,h,l,c,v=a[k]
   if v<=0:continue
   # If filled intraday, high may precede the buy. Never book same-day target from that high.
   px,why=touch_exit(entry if k==ei else o,h,l,p['stop'],None if k==ei and intraday else p['target'])
   if px is None and (k==cap-1 or k==ei+p['hold']-1):px,why=c,('boundary_mark' if k==cap-1 else 'time')
   if px is not None:
    out.append(dict(kind=p['kind'],signal=d[i],entry_day=d[ei],exit_day=d[k],entry=float(entry),exit=float(px),stop=p['stop'],target=p['target'],r=float(px*.997/(entry*1.003)-1),why=why));last=k;break
  else:
   # Incomplete suspended holding blocks all subsequent entries and stays marked in results.
   k=cap-1;out.append(dict(kind=p['kind'],signal=d[i],entry_day=d[ei],exit_day=d[k],entry=float(entry),exit=float(a[k,3]),r=float(a[k,3]*.997/(entry*1.003)-1),why='boundary_mark'));last=k
 return out

def stats(rows):
 if not rows:return {'n':0,'avg_pct':None,'win_pct':None,'pf':None,'positive_years':0,'years':0,'boundary_marks':0}
 x=np.array([r['r'] for r in rows]);yr=collections.defaultdict(list)
 for r in rows:yr[r['entry_day'][:4]].append(r['r'])
 loss=-x[x<0].sum()
 return dict(n=len(rows),avg_pct=round(float(x.mean()*100),3),win_pct=round(float((x>0).mean()*100),2),pf=round(float(x[x>0].sum()/loss),3) if loss>0 else None,
  positive_years=sum(np.mean(v)>0 for v in yr.values()),years=len(yr),boundary_marks=sum(r['why']=='boundary_mark' for r in rows))

def main(output,cache):
 report={'version':'r1166','research_only':True,'asof':R.ASOF,'source_commit':subprocess.check_output(['git','rev-parse','HEAD']).decode().strip(),'cost':.006,'engine_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'revision':'v3-cancel-invalidated-confirmation','prior_exploration_preserved':True,
  'predeclared':{'families':FAMILIES,'minimum_reward_risk':1.5,'hold':40,'stop_buffer_atr':.5,'entry_buffer_atr':.25,'periods':PERIODS},'markets':{},'stocks':{},
  'limitations':['Context scenarios are unvalidated reference plans, never live signals or optimal-price claims.','Existing universe survivorship bias; historical periods already studied, not unseen.','Daily-bar fills assumed; no tick/queue or limit-up/down execution simulation.','No current fundamentals used in historical signals.','Same-bar ambiguity is conservative; boundary marks retained.','All scenarios kept, no full-period best-stock selection.']}
 for market in ('TW','US'):
  print('LOAD',market,flush=True);s,sources,sig=R.load_market(market,cache);cal=sorted({d for e in s.values() for d in e['d']});calendar_index={d:i for i,d in enumerate(cal)}
  # O(1) lookup while preserving the calendar interface used in tests.
  class Cal(list):
   def index(self,d):return calendar_index[d]
  calendar=Cal(cal);allrows=collections.defaultdict(list)
  for sid,e in s.items():
   features(e);rows={name:run(e,market,*period,calendar) for name,period in PERIODS.items()}
   per={name:{kind:stats([r for r in rr if r['kind']==kind]) for kind in FAMILIES} for name,rr in rows.items()}
   for name,rr in rows.items():allrows[name].extend(dict(sid=sid,**r) for r in rr)
   report['stocks'][market+':'+sid]={'asof':e['d'][-1],'start':e['d'][0],'bars':len(e['d']),'current':at(e,len(e['d'])-1),'periods':per}
  report['markets'][market]={'stocks':len(s),'sources':sources,'signature':sig,'periods':{name:{kind:stats([r for r in rr if r['kind']==kind]) for kind in FAMILIES} for name,rr in allrows.items()}}
  ledger=output.with_name(output.stem+'-'+market+'-ledger.json.gz');raw=json.dumps(dict(allrows),separators=(',',':')).encode();ledger.write_bytes(gzip.compress(raw,mtime=0));report['markets'][market]['ledger_sha256']=hashlib.sha256(raw).hexdigest()
  print(market,report['markets'][market]['periods'],flush=True)
  del s
 R.save(output,report)
 compact={'schema':1,'version':'r1166','research_only':True,'asof':R.ASOF,'stocks':{sid:{k:v for k,v in e.items() if k!='current'} for sid,e in report['stocks'].items()}}
 R.save(output.with_name('context_profiles.json'),compact)
 print('DONE',len(report['stocks']),flush=True)

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--cache',type=Path,default=R.ROOT/'.cache/r1161');args=ap.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True);main(args.output,args.cache)
