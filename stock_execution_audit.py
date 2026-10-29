"""r1186 execution audit. Research only; no strategy or live account imports this file."""
import argparse,collections,gzip,hashlib,json,subprocess
from pathlib import Path
import numpy as np
import pandas as pd
import stock_adaptive_research as R
import stock_execution_data as D
from portfolio_research import touch_exit

POLICIES=('baseline','only_52week','limit_close','gap3_cancel','ma60_exit','fixed_exit','trail15_exit')
GROUPS=('break_low','break_mid','break_high','dip25_high_weak','dip40_weak','us_dip35')
PERIODS={'development':('2016-01-01','2021-01-01'),'validation':('2021-01-01','2024-01-01'),'audit':('2024-01-01','2026-10-29')}

def prepare(e):
 a=e['a'];c=pd.Series(a[:,3]);h=pd.Series(a[:,1]);f={'ma60':c.rolling(60).mean().to_numpy()}
 for w in (60,120,250):f['h'+str(w)]=h.rolling(w).max().shift(1).to_numpy()
 f['hi250']=h.rolling(250).max().to_numpy();f['vol']=np.where(e['atrp']<.025,0,np.where(e['atrp']<.04,1,2))
 e['audit_features']=f

def breadth(stocks):
 out=collections.defaultdict(lambda:[0,0])
 for e in stocks.values():
  f=e['audit_features'];a=e['a']
  for i in np.flatnonzero(np.isfinite(f['ma60'])&(e['liq']>=2e4)):
   v=out[e['d'][i]];v[0]+=int(a[i,3]>f['ma60'][i]);v[1]+=1
 return {d:x[0]/x[1] for d,x in out.items() if x[1]>=200}

def signal_sets(e,market,br):
 a=e['a'];f=e['audit_features'];n=len(a);C=a[:,3];H=a[:,1];prev=np.r_[np.nan,C[:-1]]
 valid=(e['liq']>=2e4)&(a[:,4]>0);valid[:251]=False
 if market=='TW':valid &= ~e['known_bad']
 first={}
 for w in (60,120,250):
  v=f['h'+str(w)];first[w]=(C>v)&(prev<=np.r_[np.nan,v[:-1]])&(C>=f['hi250']*.9)
 if market=='US':return {'us_dip35':np.flatnonzero(valid&(e['dd']<=-.35)&(np.r_[0,e['dd'][:-1]]>-.35))},first[250]
 union=first[60]|first[120]|first[250]
 out={g:np.flatnonzero(valid&union&(f['vol']==v)) for v,g in enumerate(GROUPS[:3])}
 hp=f['h60'];dd=C/hp-1;cross=(dd<=-.25)&(np.r_[0,dd[:-1]]>-.25)
 recent=np.zeros(n,bool)
 for j in np.flatnonzero(cross):recent[j+1:min(n,j+11)]=True
 conf=(C>np.r_[np.nan,H[:-1]])&(prev<=np.r_[np.nan,np.nan,H[:-2]])&(dd<=-.25)&recent
 weak=np.array([br.get(d,1)<.35 for d in e['d']])
 out['dip25_high_weak']=np.flatnonzero(valid&conf&weak&(f['vol']==2))
 out['dip40_weak']=np.flatnonzero(valid&weak&(e['dd']<=-.4)&(np.r_[0,e['dd'][:-1]]>-.4))
 return out,first[250]

def terms(group,policy):
 fixed=group in ('break_low','dip25_high_weak','dip40_weak','us_dip35')
 sl,tp,hold=(.15,.30,90) if group=='break_low' else (.20,.30,90) if group=='us_dip35' else (.20,.50,120) if group.startswith('dip') else (None,None,120)
 if policy=='ma60_exit':fixed=False;sl=tp=None;hold=120
 if policy=='fixed_exit' and group.startswith('break'):fixed=True;sl,tp,hold=.15,.30,90
 if policy=='trail15_exit':fixed=True;tp=None;hold=120
 return sl,tp,hold,not fixed

def simulate(e,indices,first250,cal,group,policy,start,end,cost=.006):
 """Single stock / method has one cash unit; no overlapping positions, no future trade is dropped."""
 a=e['a'];ds=e['d'];f=e['audit_features'];lo=int(np.searchsorted(ds,start));cap=int(np.searchsorted(ds,end));nav=np.ones(max(0,cap-lo));rows=[];counts=collections.Counter();last=-1;cash=1.;fee=cost/2
 sl,tp,hold,ma=terms(group,policy)
 for i in indices:
  i=int(i)
  if i<lo or i>=cap-1 or i<=last:continue
  counts['signals']+=1
  if policy=='only_52week' and group.startswith('break') and not first250[i]:counts['not_52week']+=1;continue
  ei=i+1
  if cal.get(ds[ei])!=cal.get(ds[i],-999)+1 or a[ei,4]<=0:counts['missing_next_session']+=1;continue
  entry=float(a[ei,0]);intraday=False
  if policy=='gap3_cancel' and entry>a[i,3]*1.03:counts['gap_cancelled']+=1;continue
  if policy=='limit_close':
   limit=float(a[i,3])
   if a[ei,2]>limit:counts['not_filled']+=1;continue
   intraday=entry>limit;entry=min(entry,limit)
  stop=entry*(1-sl) if sl else None;target=entry*(1+tp) if tp else None
  units=cash/(entry*(1+fee));below=0;pending=False;peak=entry;finish=min(cap,ei+hold);why=None;px=None
  for k in range(ei,finish):
   o,h,l,c,v=a[k]
   if pending and v>0:px,why=o,'ma_next_open';break
   if v<=0:continue
   # Entry-day high may precede a limit fill: cannot claim that high as profit or trailing peak.
   px,why=touch_exit(o,h,l,stop,None if intraday and k==ei else target)
   if px is not None:break
   if ma:
    below=below+1 if k>ei and c<f['ma60'][k] else 0
    if below>=2:pending=True
   if policy=='trail15_exit':
    peak=max(peak,c);stop=max(stop or 0,peak*.85) # known close only; effective next session
   if k==finish-1:px,why=c,('boundary_mark' if k==cap-1 else 'time_close');break
  else:k=finish-1;px=a[k,3];why='boundary_mark'
  cash=units*px*(1-fee);nav[ei-lo:k-lo+1]=units*a[ei:k+1,3];nav[k-lo:]=cash
  r=float(px*(1-fee)/(entry*(1+fee))-1)
  rows.append({'signal':ds[i],'entry_day':ds[ei],'exit_day':ds[k],'entry':entry,'exit':float(px),'r':r,'days':k-ei+1,'why':why,'entry_i':ei,'exit_i':k})
  counts['filled']+=1;last=k
 return rows,nav,dict(counts)

def metrics(rows,nav,days):
 r=np.array([x['r'] for x in rows]);loss=-r[r<0].sum();years=collections.defaultdict(list)
 for x in rows:years[x['entry_day'][:4]].append(x['r'])
 marks=sum(x['why']=='boundary_mark' for x in rows)
 return {'n':len(rows),'completed':len(rows)-marks,'open_marks':marks,'avg_pct':round(float(r.mean()*100),3) if len(r) else None,'win_pct':round(float((r>0).mean()*100),2) if len(r) else None,'pf':round(float(r[r>0].sum()/loss),3) if loss>0 else None,'worst_trade_pct':round(float(r.min()*100),3) if len(r) else None,'positive_years':sum(np.mean(x)>0 for x in years.values()),'years_with_trades':len(years),'median_days':float(np.median([x['days'] for x in rows])) if rows else None,'capital_return_pct':round(float((nav[-1]-1)*100),3) if len(nav) else 0,'cagr_pct':round(float((nav[-1]**(365.25/max(days,1))-1)*100),3) if len(nav) and nav[-1]>0 else None,'mdd_pct':round(float(np.min(nav/np.maximum.accumulate(np.r_[1,nav])[1:])-1)*100,3) if len(nav) else 0}

def main(output,asof,markets):
 output.mkdir(parents=True,exist_ok=True)
 if any((output/n).exists() for n in ('execution-audit.json','execution-audit.json.gz')):raise FileExistsError('Use a new output directory; completed research snapshots are immutable')
 spec={'version':'r1186','asof':asof,'data':'Permanent archive plus recent website K, recent dates take priority; factors merged by event date, no double adjustment.','policies':POLICIES,'groups':GROUPS,'periods':PERIODS,'fee_each_side':.003,'stress_fee_each_side':.005,'selection':'No per-stock best-method selection; all fixed variants reported; historical periods already examined, not a fresh holdout.','execution':'Signals on completed close, next market session only, conservative stop-first range but open observed first. End holdings marked with exit cost, not dropped. Limit same-day high never assumed after entry.','capital':'Each stock/method starts with one independent cash unit, one position maximum; aggregate is equal initial capital across current universe with no reallocation. It is not a five-position executable portfolio.','limits':['Survivorship/current-universe and revised-data biases remain','Adjusted OHLC, no intraday queue, limit lock, historical tick matching or true tax model','No current financial facts backfilled, no market-cap group based on current shares','Historical MA breadth reconstructed from liquid stocks, not known historical full membership','Calendar derived from market bars; no guarantee missing market sessions are detected','No automatic rule promotion or prediction of exact execution price']}
 R.save(output/'predeclared-spec.json',spec)
 report={'spec':spec,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'engine_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'loader_sha256':hashlib.sha256(Path(D.__file__).read_bytes()).hexdigest(),'stocks':{},'markets':{}}
 D.ASOF=asof
 for market in markets:
  print('LOAD',market,flush=True);stocks,sources,signature=D.load_market(market,R.ROOT/'.cache/r1186-complete'/asof);[prepare(e) for e in stocks.values()];br=breadth(stocks) if market=='TW' else {};calendar=sorted({d for e in stocks.values() for d in e['d']});cal={d:i for i,d in enumerate(calendar)}
  active=('us_dip35',) if market=='US' else GROUPS[:-1];pool={};ledger={};pooledcurves={};counter={};stress={}
  for z,(sid,e) in enumerate(stocks.items()):
   signals,first=signal_sets(e,market,br);st={};ld={}
   for group in active:
    st[group]={};ld[group]={}
    for policy in POLICIES:
     if group=='us_dip35' and policy=='only_52week':continue
     st[group][policy]={};ld[group][policy]={}
     for period,(start,end) in PERIODS.items():
      rows,nav,ct=simulate(e,signals[group],first,cal,group,policy,start,end);key=(group,policy,period);pool.setdefault(key,[]).extend(rows)
      ds=[d for d in calendar if start<=d<end];ed=e['d'];k0=int(np.searchsorted(ed,start));bar_dates=np.array(ed[k0:k0+len(nav)]);ix=np.searchsorted(bar_dates,np.array(ds),side='right');vals=np.r_[1.,nav][ix]
      pooledcurves[key]=pooledcurves.get(key,0)+vals;counter.setdefault(key,collections.Counter()).update(ct)
      days=(np.datetime64(min(end,asof))-np.datetime64(start)).astype(int)+1
      st[group][policy][period]=metrics(rows,nav,days);ld[group][policy][period]=rows
      rr=[dict(x,r=float(x['exit']*.995/(x['entry']*1.005)-1)) for x in rows];stress.setdefault(key,[]).extend(rr)
   report['stocks'][market+':'+sid]={'name':e['name'],'first':e['d'][0],'asof':e['d'][-1],'bars':len(e['d']),'current_atrp':round(float(e['atrp'][-1]),6),'groups':st};ledger[sid]=ld
   if z%100==0:print(market,z,'/',len(stocks),flush=True)
  agg={}
  for key,rows in pool.items():
   g,p,t=key;start,end=PERIODS[t];days=(np.datetime64(min(end,asof))-np.datetime64(start)).astype(int)+1;nav=pooledcurves[key]/len(stocks)
   agg.setdefault(g,{}).setdefault(p,{})[t]={'metrics':metrics(rows,nav,days),'stress_1pct':metrics(stress[key],[],days),'execution_counts':dict(counter[key])}
  report['markets'][market]={'stocks':len(stocks),'signature':signature,'sources':sources,'calendar_first':calendar[0],'calendar_last':calendar[-1],'breadth_dates':len(br),'aggregate':agg}
  R.save(output/'execution-audit.json',report)
  (output/(market+'-ledger.json.gz')).write_bytes(gzip.compress(json.dumps(ledger,separators=(',',':'),allow_nan=False).encode(),mtime=0));R.save(output/'execution-audit.json',report);print('DONE',market,len(stocks),flush=True)
 return report

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--asof',default='2026-10-28');ap.add_argument('--markets',nargs='+',default=['TW','US']);args=ap.parse_args();main(args.output,args.asof,args.markets)
