"""r1188: individual trade paths and paired exits on the frozen r1186 entries. Research only."""
import argparse,collections,gzip,hashlib,json,pickle
from pathlib import Path
import numpy as np
import stock_execution_audit as A
from portfolio_research import touch_exit

POLICIES=('baseline','ma60_exit','fixed_exit','trail15_exit','tighter_stop')
ROOT=Path(__file__).resolve().parent

def exit_same_entry(e,ei,group,policy,cap):
 a=e['a'];entry=float(a[ei,0]);sl,tp,hold,ma=A.terms(group,'baseline' if policy=='tighter_stop' else policy)
 if policy=='tighter_stop':sl=max(.05,sl-.05) if sl else .15
 stop=entry*(1-sl) if sl else None;target=entry*(1+tp) if tp else None;below=0;pending=False;peak=entry;finish=min(cap,ei+hold)
 for k in range(ei,finish):
  o,h,l,c,v=a[k]
  if pending and v>0:return k,float(o),'ma_next_open'
  if v<=0:continue
  px,why=touch_exit(o,h,l,stop,target)
  if px is not None:return k,float(px),why
  if ma:
   below=below+1 if k>ei and c<e['audit_features']['ma60'][k] else 0
   if below>=2:pending=True
  if policy=='trail15_exit':peak=max(peak,c);stop=max(stop or 0,peak*.85)
  if k==finish-1:return k,float(c),'boundary_mark' if k==cap-1 else 'time_close'
 return finish-1,float(a[finish-1,3]),'boundary_mark'

def diagnose(e,row,cap):
 a=e['a'];ds=e['d'];ei=e['idx'][row['entry_day']];xi=e['idx'][row['exit_day']];si=e['idx'][row['signal']];entry=row['entry'];why=row['why']
 # An intraday exit does not tell whether the day's other extreme came before it.
 end=xi+1 if why in ('time_close','boundary_mark') else xi
 held=a[ei:end];lows=np.r_[entry,held[:,2] if len(held) else [],row['exit']];highs=np.r_[entry,held[:,1] if len(held) else [],row['exit']]
 days=np.r_[np.arange(ei,end),xi];hi=np.r_[held[:,1] if len(held) else [],row['exit']]
 hit={}
 for pct in (.05,.10,.20):
  at=np.flatnonzero(hi>=entry*(1+pct));hit[str(int(pct*100))]=int(days[at[0]]-ei+1) if len(at) else None
 klass=lambda v:0 if v<.025 else 1 if v<.04 else 2
 initial=klass(e['atrp'][si]);later=e['atrp'][ei:xi+1];drift=bool(any(klass(v)!=initial for v in later if np.isfinite(v)))
 future=[k for k in range(xi+1,cap) if a[k,4]>0][:20];full=len(future)==20
 stopped=why in ('sl','gap_sl');profit=why in ('tp','gap_tp')
 recovered=bool(np.any(a[future,3]>=entry*1.003/.997)) if stopped and full else None
 after=float((a[future[-1],3]/row['exit']-1)*100) if profit and full else None
 return {'mae_pct':round(float(max(0,1-lows.min()/entry)*100),4),'mfe_pct':round(float(max(0,highs.max()/entry-1)*100),4),'hit_days':hit,'entry_gap_pct':round(float((entry/a[si,3]-1)*100),4),'regime_changed':drift,'signal_regime':initial,'stop_20_observed':bool(stopped and full),'stop_recovered_20':recovered,'target_20_observed':bool(profit and full),'target_after20_pct':round(after,4) if after is not None else None,'post_exit_censored':bool((stopped or profit) and not full)}

def summarize(rows):
 n=len(rows);d=[x['path'] for x in rows];wins=[x['path']['mae_pct'] for x in rows if x['r']>0 and x['why']!='boundary_mark'];quant=lambda xs,q:round(float(np.quantile(xs,q)),3) if len(xs) else None
 stopped=[x for x in rows if x['why'] in ('sl','gap_sl')];follow=[x for x in d if x['stop_20_observed']];tp=[x['target_after20_pct'] for x in d if x['target_20_observed']]
 out={'n':n,'completed':sum(x['why']!='boundary_mark' for x in rows),'open_marks':sum(x['why']=='boundary_mark' for x in rows),'mae_median_pct':quant([x['mae_pct'] for x in d],.5),'mae90_pct':quant([x['mae_pct'] for x in d],.9),'mfe_median_pct':quant([x['mfe_pct'] for x in d],.5),'winning_n':len(wins),'winning_mae90_pct':quant(wins,.9),'gap95_pct':quant([x['entry_gap_pct'] for x in d],.95),'regime_changed_n':sum(x['regime_changed'] for x in d),'stop_n':len(stopped),'stop_observed20_n':len(follow),'stop_recovered20_n':sum(x['stop_recovered_20'] is True for x in follow),'tp_observed20_n':len(tp),'tp_after20_median_pct':quant(tp,.5),'post_exit_censored_n':sum(x['post_exit_censored'] for x in d),'hit':{},'paired':{}}
 for h in ('5','10','20'):
  xs=[x['hit_days'][h] for x in d if x['hit_days'][h] is not None];out['hit'][h]={'n':len(xs),'median_days':quant(xs,.5)}
 for p in POLICIES:
  xs=[x['exits'][p]['r']-x['r'] for x in rows];complete=[v for x,v in zip(rows,xs) if x['why']!='boundary_mark' and x['exits'][p]['why']!='boundary_mark']
  out['paired'][p]={'n':n,'avg_pct':round(float(np.mean([x['exits'][p]['r'] for x in rows])*100),3) if n else None,'mean_delta_pct':round(float(np.mean(xs)*100),3) if n else None,'better_n':sum(v>1e-10 for v in xs),'worse_n':sum(v< -1e-10 for v in xs),'paired_open_n':sum(x['why']=='boundary_mark' or x['exits'][p]['why']=='boundary_mark' for x in rows),'completed_both_n':len(complete),'completed_both_delta_pct':round(float(np.mean(complete)*100),3) if complete else None}
 return out

def main(output):
 if (output/'profiles.json.gz').exists():raise FileExistsError('Use a new directory; frozen research cannot be overwritten')
 output.mkdir(parents=True,exist_ok=True);base=ROOT/'research/r1186';report=json.loads(gzip.decompress((base/'execution-audit.json.gz').read_bytes()));caches={}
 for m,v in report['markets'].items():
  p=ROOT/'.cache/r1186-complete'/report['spec']['asof']/(m.lower()+'_'+v['signature'][:16]+'.pkl.gz')
  if not p.exists():raise FileNotFoundError('Frozen trusted local data cache missing; restore r1186 inputs, do not substitute a newer dataset: '+str(p))
  caches[m]={'path':p,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 spec={'version':'r1188','source_research':'r1186','source_sha256':hashlib.sha256((base/'execution-audit.json.gz').read_bytes()).hexdigest(),'policies':POLICIES,'periods':A.PERIODS,'post_exit_window':20,'touch_threshold_pct':[5,10,20],'method':'Same frozen baseline entry for every alternative exit; independent counterfactual events, NOT a portfolio. No parameter or per-stock winner selection.','limits':['Past periods already examined; diagnostics are not predictive probabilities','Intraday exit-day range excluded; excursions/touch timing are conservative lower bounds','20 valid symbol bars after exit; incomplete followups censored, never classified as failures','Regime at signal fixed; later changes are descriptive, never switch an existing holding automatically','Equal-entry counterfactuals may overlap and are not portfolio returns','Existing survivorship, daily bar, adjusted price and execution limits persist'],'cache_sha256':{m:v['sha256'] for m,v in caches.items()},'engine_sha256':hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest()}
 (output/'spec.json').write_bytes(json.dumps(spec,ensure_ascii=False,indent=2).encode());result={'schema':1,'version':'r1188','research_only':True,'spec':spec,'stocks':{},'market_totals':{}}
 for market,item in caches.items():
  with gzip.open(item['path'],'rb') as f:stocks=pickle.load(f) # Only the self-created trusted local r1186 cache; never downloaded pickles.
  ledger=json.loads(gzip.decompress((base/(market+'-ledger.json.gz')).read_bytes()));details={};totals=collections.Counter()
  for z,(sid,e) in enumerate(stocks.items()):
   key=market+':'+sid;meta=report['stocks'][key];assert e['d'][0]==meta['first'] and e['d'][-1]==meta['asof'] and len(e['d'])==meta['bars'];A.prepare(e)
   digest=hashlib.sha256(('\n'.join(e['d'])).encode()+e['a'].astype('<f8').tobytes()).hexdigest();out={'name':meta['name'],'first':meta['first'],'asof':meta['asof'],'bars':meta['bars'],'bars_sha256':digest,'groups':{}};detail={}
   for group,pols in ledger[sid].items():
    out['groups'][group]={};detail[group]={}
    for period,original in pols['baseline'].items():
     cap=int(np.searchsorted(e['d'],A.PERIODS[period][1]));rows=[]
     for x in original:
      r=dict(x);ei=e['idx'][r['entry_day']];r['path']=diagnose(e,r,cap);r['exits']={}
      for policy in POLICIES:
       k,px,why=exit_same_entry(e,ei,group,policy,cap);rr=float(px*.997/(r['entry']*1.003)-1);r['exits'][policy]={'exit_day':e['d'][k],'exit':px,'why':why,'r':rr}
      b=r['exits']['baseline'];assert b['exit_day']==r['exit_day'] and b['why']==r['why'] and abs(b['r']-r['r'])<1e-10
      rows.append(r)
     out['groups'][group][period]=summarize(rows);detail[group][period]=rows;totals['baseline_events']+=len(rows);totals['regime_changed']+=sum(x['path']['regime_changed'] for x in rows)
   result['stocks'][key]=out;details[sid]=detail
   if z%400==0:print(market,z,'/',len(stocks),flush=True)
  (output/(market+'-paths.json.gz')).write_bytes(gzip.compress(json.dumps(details,separators=(',',':'),allow_nan=False).encode(),mtime=0));result['market_totals'][market]=dict(totals)
  (output/'profiles.json.gz').write_bytes(gzip.compress(json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),mtime=0));print('DONE',market,dict(totals),flush=True)
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args().output)
