"""r1170: preregistered comparison of six conditional trade plans. Research only.

Never imported by live selection, accounting, or notifications. All levels are
locked before confirmation; no full-period best-stock selection is published.
"""
import argparse, collections, gzip, hashlib, json, subprocess
from pathlib import Path
import numpy as np
import pandas as pd
import stock_adaptive_research as R
from portfolio_research import touch_exit

MODELS=('trend20','trend60','break20','break60','range20','reclaim60')
PERIODS={'development':('2016-01-01','2021-01-01'),
         'validation':('2021-01-01','2024-01-01'),
         'recent_audit':('2024-01-01',None)}

def features(e):
    a=e['a']; c=pd.Series(a[:,3]); f={}
    for n in (20,60,120):
        f['ma'+str(n)]=c.rolling(n).mean().to_numpy()
    for n in (20,60):
        f['hi'+str(n)]=pd.Series(a[:,1]).rolling(n).max().to_numpy()
        f['lo'+str(n)]=pd.Series(a[:,2]).rolling(n).min().to_numpy()
    f['ma60past']=np.r_[np.full(10,np.nan),f['ma60'][:-10]]
    e['trade_features']=f

def plan(e,i,model):
    f=e['trade_features']; atr=float(e['atr'][i]); c=float(e['a'][i,3])
    v={k:float(x[i]) for k,x in f.items()}
    if not all(np.isfinite(x) and x>0 for x in [atr,c,*v.values()]):return None
    if model.startswith('trend'):
        if not(v['ma20']>=v['ma60']>=v['ma120']):return None
        trigger=v['ma'+model[5:]]; stop=v['lo20']-.5*atr
        upper=trigger+.25*atr; target=v['hi60']; hold=40; confirm='bounce'
    elif model.startswith('break'):
        trigger=v['hi'+model[5:]]; upper=trigger+.5*atr
        stop=trigger-2*atr; target=upper+2*(upper-stop)
        hold=40 if model=='break20' else 60; confirm='cross'
    elif model=='range20':
        if abs(v['ma60']-v['ma60past'])>.5*atr:return None
        trigger=v['lo20']+.5*atr; upper=trigger+.25*atr
        stop=v['lo20']-.5*atr; target=v['hi20']; hold=20; confirm='bounce'
    else:
        trigger=v['ma60']; upper=trigger+.25*atr
        stop=v['lo20']-.5*atr; target=v['hi60']; hold=40; confirm='cross'
        if c>=trigger:return None
    risk=upper-stop
    if not(0<stop<upper<target and risk>=.5*atr and (target-upper)/risk>=1.5):return None
    return dict(model=model,trigger=trigger,upper=upper,stop=stop,target=target,
                hold=hold,confirm=confirm,asof=e['d'][i])

def run(e,market,model,start,end,calendar):
    a=e['a'];ds=e['d'];cap=len(ds) if end is None else int(np.searchsorted(ds,end))
    out=[];last=-1
    for i in range(250,cap-1):
        if i<=last or ds[i]<start or e['liq'][i-1]<2e4:continue
        if market=='TW' and e['known_bad'][i]:continue
        p=plan(e,i-1,model)
        if not p or a[i,4]<=0 or a[i,2]<=p['stop'] or a[i,3]>=p['target']:continue
        if p['confirm']=='cross':
            confirmed=a[i-1,3]<=p['trigger'] and a[i,3]>p['trigger']
        else:
            confirmed=a[i,2]<=p['upper'] and a[i,3]>=p['trigger'] and a[i,3]>=a[i-1,3]
        if not confirmed:continue
        ei=i+1;ci=calendar.get(ds[i])
        # A one-session order expires on the next market session, not next symbol bar.
        if ci is None or calendar.get(ds[ei])!=ci+1 or a[ei,4]<=0:continue
        o,h,l,c,v=a[ei]
        if o<=p['stop'] or l>p['upper']:continue
        entry=min(o,p['upper']);intraday=o>p['upper'];finish=min(cap,ei+p['hold'])
        for k in range(ei,finish):
            o,h,l,c,v=a[k]
            if v<=0:continue
            px,why=touch_exit(o,h,l,p['stop'],None if k==ei and intraday else p['target'])
            if px is None and k==finish-1:px,why=c,'boundary_mark' if k==cap-1 else 'time'
            if px is not None:break
        else:
            k=finish-1;px=a[k,3];why='boundary_mark'
        out.append(dict(signal=ds[i],entry_day=ds[ei],exit_day=ds[k],entry=float(entry),
                        exit=float(px),stop=p['stop'],target=p['target'],days=k-ei+1,
                        r=float(px*.997/(entry*1.003)-1),why=why))
        last=k
    return out

def stats(rows):
    if not rows:return dict(n=0,completed=0,boundary_marks=0,avg_pct=None,win_pct=None,pf=None)
    r=np.array([x['r'] for x in rows]);loss=-r[r<0].sum();ys=collections.defaultdict(list)
    for x in rows:ys[x['entry_day'][:4]].append(x['r'])
    return dict(n=len(rows),completed=sum(x['why']!='boundary_mark' for x in rows),
                boundary_marks=sum(x['why']=='boundary_mark' for x in rows),
                avg_pct=round(float(r.mean()*100),3),win_pct=round(float((r>0).mean()*100),2),
                pf=round(float(r[r>0].sum()/loss),3) if loss>0 else None,
                median_days=round(float(np.median([x['days'] for x in rows])),1),
                worst_pct=round(float(r.min()*100),3),positive_years=sum(np.mean(v)>0 for v in ys.values()),years=len(ys))

def supported(s,min_n):
    return s.get('completed',0)>=min_n and (s.get('avg_pct') or 0)>0 and (s.get('pf') or 0)>=1.1 and s.get('positive_years',0)*2>=s.get('years',1)

def main(output,cache,markets):
    spec={'models':MODELS,'periods':PERIODS,'roundtrip_cost':.006,
          'selection':'development only; >=10 completed, positive mean, PF>=1.1, >=half positive years; highest mean among eligible; ties fixed model order',
          'qualification':'selected model must independently pass validation with >=6 completed; recent_audit is descriptive and cannot choose or replace the model',
          'orders':'prior-close levels, confirmation close, next market session one-day limit ceiling, gap below stop cancels',
          'limitations':['Research-only conditional templates, not validated live trading recommendations.',
                         'Existing universe survivorship bias; historical periods previously examined, not unseen.',
                         'Daily-bar conservative assumptions; no queue/limit lock/slippage simulation.',
                         'Adjusted research prices; not a guarantee of historical legal ticks or future execution.',
                         'Event averages are not portfolio CAGR or drawdown; boundary losses retained.',
                         'No current financial statements backfilled into historical signals.']}
    output.parent.mkdir(parents=True,exist_ok=True)
    spec_path=output.with_name('predeclared-spec.json')
    if not spec_path.exists():R.save(spec_path,spec)
    else:assert json.loads(spec_path.read_bytes())==json.loads(json.dumps(spec))
    report={'version':'r1170','research_only':True,'source_commit':subprocess.check_output(['git','rev-parse','HEAD']).decode().strip(),
            'engine_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'spec':spec,'markets':{},'stocks':{}}
    for market in markets:
        print('LOAD',market,flush=True); stocks,sources,signature=R.load_market(market,cache)
        cal={d:i for i,d in enumerate(sorted({d for e in stocks.values() for d in e['d']}))}
        pooled={p:{m:[] for m in MODELS} for p in PERIODS};ledgers={};counts=collections.Counter()
        for sid,e in stocks.items():
            features(e);by={m:{p:run(e,market,m,*bounds,cal) for p,bounds in PERIODS.items()} for m in MODELS}
            ss={m:{p:stats(rows) for p,rows in periods.items()} for m,periods in by.items()}
            eligible=[m for m in MODELS if supported(ss[m]['development'],10)]
            selected=max(eligible,key=lambda m:ss[m]['development']['avg_pct']) if eligible else None
            qualified=bool(selected and supported(ss[selected]['validation'],6))
            counts['selected' if selected else 'insufficient_development']+=1
            counts['validation_pass' if qualified else 'validation_not_pass']+=1
            report['stocks'][market+':'+sid]={'asof':e['d'][-1],'start':e['d'][0],'bars':len(e['d']),
                'models':ss,'development_selected':selected,'validation_supported':qualified,
                'current':{m:plan(e,len(e['d'])-1,m) for m in MODELS}}
            ledgers[sid]=by
            for m,periods in by.items():
                for p,rows in periods.items():pooled[p][m].extend(rows)
        raw=json.dumps(ledgers,separators=(',',':'),allow_nan=False).encode();lp=output.with_name(output.stem+'-'+market+'-ledger.json.gz');lp.write_bytes(gzip.compress(raw,mtime=0))
        report['markets'][market]={'stocks':len(stocks),'signature':signature,'sources':sources,'counts':dict(counts),
                                  'ledger_sha256':hashlib.sha256(raw).hexdigest(),'pooled':{p:{m:stats(r) for m,r in ms.items()} for p,ms in pooled.items()}}
        R.save(output,report);print(market,len(stocks),dict(counts),flush=True)
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--cache',type=Path,default=R.ROOT/'.cache/r1161');ap.add_argument('--markets',nargs='+',default=['TW','US']);a=ap.parse_args();main(a.output,a.cache,a.markets)
