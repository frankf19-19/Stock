"""r1161 research only. Not imported by website, stock selection or live accounting."""
import argparse,collections,datetime as dt,gzip,hashlib,json,math,pickle,subprocess,sys
from pathlib import Path
import numpy as np
import pandas as pd
from portfolio_research import touch_exit,summarize

ROOT=Path(__file__).resolve().parent
BASE={'TW':(.40,.15,.20,60),'US':(.35,.20,.30,90)}
EXIT_NAMES=('baseline','atr4_rr1.5','atr6_rr1.5','short_hold','long_hold')
POLICIES=('baseline','atr4','atr6','own_drawdown_entry','own_drawdown_entry_atr4','rolling_global','rolling_vol_group','rolling_stock_shrink20','atr4_riskcap3pct')
ASOF='2026-10-23'


def save(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False,default=lambda x:x.item() if isinstance(x,np.generic) else (_ for _ in ()).throw(TypeError(type(x).__name__))).encode('utf-8'))


def rolling_mean(a,n):
    out=np.full(len(a),np.nan);v=np.r_[0,np.cumsum(a)];out[n-1:]=(v[n:]-v[:-n])/n;return out


def load_market(market,cache_dir):
    paths=sorted((ROOT/'archive/k'/market.lower()).glob('*/*.json.gz'))
    extra=[ROOT/'data.json']+([ROOT/'archive/adj_tw.json.gz'] if market=='TW' else [])
    action_dir=ROOT/'archive/stock_research/r1161/raw'
    action_paths=[action_dir/n for n in ('TaiwanStockSplitPrice.json','TaiwanStockParValueChange.json','capital_reductions.json')] if market=='TW' else []
    extra += [p for p in action_paths if p.exists()]
    sources=[{'path':str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else 'archive/stock_research/r1161/raw/'+p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths+extra]
    signature=hashlib.sha256(('loader-v2-actions'+json.dumps(sources,sort_keys=True)).encode()).hexdigest()
    cache=Path(cache_dir)/(market.lower()+'_'+signature[:16]+'.pkl.gz');cache.parent.mkdir(parents=True,exist_ok=True)
    if cache.exists():
        with gzip.open(cache,'rb') as f:return pickle.load(f),sources,signature
    universe=json.loads((ROOT/'data.json').read_bytes())['stocks'];metadata={str(s['id']):s for s in universe if s.get('market')==market}
    etfs={str(s['id']) for s in universe if s.get('etf')};merged=collections.defaultdict(dict)
    for path in paths:
        for sid,e in json.loads(gzip.decompress(path.read_bytes())).items():
            if sid in etfs or (market=='TW' and (not sid.isdigit() or len(sid)!=4)):continue
            for d,o in zip(e.get('d',[]),e.get('o',[])):
                if d>ASOF or len(o)<5 or any(v is None or not math.isfinite(v) or v<=0 for v in o[:4]):continue
                if not math.isfinite(o[4]) or o[4]<0:continue
                merged[sid][sys.intern(d)]=o
    adj=json.loads(gzip.decompress((ROOT/'archive/adj_tw.json.gz').read_bytes()))['s'] if market=='TW' else {}
    supplementary={}
    if market=='TW':
        proposed=collections.defaultdict(list)
        for path in action_paths:
            if not path.exists():continue
            payload=json.loads(path.read_bytes())
            if path.name=='capital_reductions.json':
                rows=[r for source in payload['sources'].values() for r in source['payload']['data']]
                before,after='ClosingPriceonTheLastTradingDay','PostReductionReferencePrice'
            else:
                rows=payload['data'];before,after=('before_price','after_price') if 'SplitPrice' in path.name else ('before_close','after_ref_close')
            for r in rows:
                if r.get(before,0)>0 and r.get(after,0)>0 and r['date']<=ASOF:
                    proposed[str(r['stock_id']),r['date']].append(float(r[after])/float(r[before]))
        for (sid,day),ratios in proposed.items():
            if max(ratios)-min(ratios)>1e-6:continue # Conflicts remain flagged as unresolved, never guessed.
            if any(d==day for d,f in adj.get(sid,[])):continue # Never double-adjust an existing reference event.
            supplementary.setdefault(sid,[]).append((day,ratios[0]))
    stocks={}
    for sid,mp in merged.items():
        if len(mp)<300:continue
        ds=sorted(mp);a=np.array([mp[d] for d in ds],float)
        if market=='US':a[:,4]/=1000
        # Liquidity must not use future dividend-adjusted price levels.
        liq=rolling_mean(a[:,3]*a[:,4],20)
        factor=np.ones(len(ds))
        dates_array=np.array(ds)
        for d,f in list(adj.get(sid,[]))+supplementary.get(sid,[]):
            if d>ASOF:continue
            factor[:np.searchsorted(dates_array,d)]*=f
        a[:,:4]*=factor[:,None]
        c=a[:,3];prev=np.r_[c[0],c[:-1]];tr=np.maximum(a[:,1]-a[:,2],np.maximum(abs(a[:,1]-prev),abs(a[:,2]-prev)))
        atr=rolling_mean(tr,20);atrp=atr/c
        hi60=pd.Series(a[:,1]).rolling(60,min_periods=60).max().to_numpy();dd=c/hi60-1
        change=np.r_[0,np.diff(c)];total=rolling_mean(abs(change),63)*63
        er=np.full(len(c),np.nan);er[63:]=np.divide(c[63:]-c[:-63],total[63:],out=np.zeros(len(c)-63),where=total[63:]>0)
        ret=c/prev-1;bad=abs(ret)>.115 if market=='TW' else np.zeros(len(c),bool)
        known_bad=pd.Series(bad.astype(int)).rolling(61,min_periods=1).max().to_numpy().astype(bool)
        thresholds=np.full(len(ds),BASE[market][0]);own_eligible=np.zeros(len(ds),bool)
        years=np.array([int(d[:4]) for d in ds]);ds_arr=np.array(ds)
        for y in sorted(set(years)):
            train=(years<y)&(years>=y-5)&np.isfinite(dd)
            if train.sum()<500:continue
            thresholds[years==y]=np.clip(-np.quantile(dd[train],.01),.25,.50);own_eligible[years==y]=True
        s=metadata.get(sid,{})
        stocks[sid]={'d':ds,'a':a,'idx':{d:i for i,d in enumerate(ds)},'liq':liq,'atr':atr,'atrp':atrp,'dd':dd,'er':er,
          'known_bad':known_bad,'own_threshold':thresholds,'own_eligible':own_eligible,'sec':s.get('sector') or 'unknown','name':s.get('name',sid),
          'anomalies':[{'day':ds[i],'return':round(float(ret[i]),6)} for i in np.flatnonzero(bad)],'current_member':sid in metadata}
    with gzip.open(cache,'wb',compresslevel=1) as f:pickle.dump(stocks,f,protocol=pickle.HIGHEST_PROTOCOL)
    return stocks,sources,signature


def signal_indices(e,threshold,market):
    dd=e['dd'];th=np.broadcast_to(threshold,dd.shape);prev_th=np.r_[th[0],th[:-1]]
    mask=(dd<=-th)&(np.r_[0,dd[:-1]]>-prev_th)&(e['liq']>=2e4)&np.isfinite(e['atrp'])
    mask[:250]=False
    # Same current-known discontinuity guard as the website; no exclusion of future losers.
    if market=='TW':mask &= ~e['known_bad']
    return np.flatnonzero(mask)


def exit_terms(market,name,entry,atr):
    _,sl,tp,hold=BASE[market]
    if name.startswith('atr'):
        mult=4 if name.startswith('atr4') else 6
        sl=float(np.clip(mult*atr/entry,.08 if market=='TW' else .10,.25 if market=='TW' else .30));tp=1.5*sl
    if name=='short_hold':hold//=2
    if name=='long_hold':hold=int(hold*1.5)
    return sl,tp,hold


def event_outcome(e,i,market,name,cost=.006):
    a=e['a'];ei=i+1
    if ei>=len(a) or a[ei,4]<=0:return None
    entry=float(a[ei,0]);sl,tp,hold=exit_terms(market,name,entry,e['atr'][i]);seen=0;last_valid=ei
    for k in range(ei,len(a)):
        o,h,l,c,v=a[k]
        if v<=0:continue
        seen+=1;last_valid=k;px,why=touch_exit(o,h,l,entry*(1-sl),entry*(1+tp))
        if px is None and seen>=hold:px,why=c,'time'
        if px is not None:return {'r':float(px*(1-cost/2)/(entry*(1+cost/2))-1),'exit_day':e['d'][k],'exit_i':k,'why':why,'days':seen,'sl':sl,'tp':tp}
    return {'r':float(a[last_valid,3]*(1-cost/2)/(entry*(1+cost/2))-1),'exit_day':e['d'][-1],'exit_i':len(a)-1,'why':'boundary_mark','days':seen,'sl':sl,'tp':tp}


def build_events(stocks,market):
    events=[];candidates=collections.defaultdict(list);own=collections.defaultdict(list)
    for sid,e in stocks.items():
        for typ,threshold,dest in [('base',BASE[market][0],candidates),('own',e['own_threshold'],own)]:
            for i in signal_indices(e,threshold,market):
                if typ=='own' and not e['own_eligible'][i]:continue
                d=e['d'][i];v=float(e['atrp'][i]);bucket=0 if v<=.02 else 1 if v<=.04 else 2
                event={'sid':sid,'i':int(i),'day':d,'sec':e['sec'],'liq':float(e['liq'][i]),'atrp':v,'bucket':bucket,'er':float(e['er'][i]),'threshold':float(np.broadcast_to(threshold,e['dd'].shape)[i])}
                if typ=='base':
                    outcomes={n:event_outcome(e,i,market,n) for n in EXIT_NAMES}
                    if all(x is not None for x in outcomes.values()):
                        event['outcomes']=outcomes;event['mature_day']=max(x['exit_day'] for x in outcomes.values())
                        event['mature']=all(x['why']!='boundary_mark' for x in outcomes.values());events.append(event)
                if d>='2016-01-01':dest[d].append(event)
    for dest in (candidates,own):
        for rows in dest.values():rows.sort(key=lambda x:(-x['liq'],x['sid']))
    return events,dict(candidates),dict(own)


def clustered_se(rows,diffs,key):
    n=len(rows);mean=float(np.mean(diffs));scores=collections.defaultdict(float)
    for row,diff in zip(rows,diffs):scores[key(row)]+=float(diff)-mean
    g=len(scores)
    return math.sqrt(g/(g-1)*sum(v*v for v in scores.values()))/n if g>=3 and n else float('inf')


def choose_exit(rows,min_n=100,shrink=0,global_gains=None,single_stock=False):
    if len(rows)<min_n:return 'baseline',{'n':len(rows),'reason':'insufficient_events'}
    estimates={};selected='baseline';best=0
    for name in EXIT_NAMES[1:]:
        diffs=np.array([r['outcomes'][name]['r']-r['outcomes']['baseline']['r'] for r in rows])
        avg=float(diffs.mean());prior=(global_gains or {}).get(name,0.)
        weight=len(rows)/(len(rows)+shrink) if shrink else 1.
        estimate=prior+weight*(avg-prior)
        time_se=clustered_se(rows,diffs,lambda r:r['day'][:4] if single_stock else r['day'][:4]+'Q'+str((int(r['day'][5:7])-1)//3+1))
        se=time_se if single_stock else max(time_se,clustered_se(rows,diffs,lambda r:r['sid']))
        eligible=math.isfinite(se) and estimate-3*se>0
        estimates[name]={'paired_mean_gain':avg,'shrunk_gain':estimate,'cluster_se':se if math.isfinite(se) else None,'eligible':eligible}
        if eligible and estimate>best:selected=name;best=estimate
    return selected,{'n':len(rows),'reason':'accepted_gain' if selected!='baseline' else 'uncertainty_fallback','estimates':estimates}


def fit_years(events,years=range(2016,2027)):
    models={};audit=[]
    for y in years:
        cutoff=f'{y}-01-01';earliest=f'{y-5}-01-01'
        rows=[r for r in events if earliest<=r['day']<cutoff and r['mature'] and r['mature_day']<cutoff]
        global_exit,diag=choose_exit(rows)
        global_gains={n:float(np.mean([r['outcomes'][n]['r']-r['outcomes']['baseline']['r'] for r in rows])) if rows else 0 for n in EXIT_NAMES[1:]}
        model={'global':global_exit,'group':{},'stock':{}}
        groups=[]
        for b in range(3):
            subset=[r for r in rows if r['bucket']==b];pick,d=choose_exit(subset,60)
            model['group'][b]=pick if d['reason']=='accepted_gain' else global_exit
            groups.append({'bucket':b,'selected':model['group'][b],**d})
        by_sid=collections.defaultdict(list)
        for r in rows:by_sid[r['sid']].append(r)
        eligible_stocks=0;accepted_stocks=0
        for sid,subset in by_sid.items():
            if len(subset)<20:continue
            eligible_stocks+=1;pick,d=choose_exit(subset,20,50,global_gains,True)
            if d['reason']=='accepted_gain':model['stock'][sid]=pick;accepted_stocks+=1
        models[y]=model
        audit.append({'year':y,'train_earliest':earliest,'cutoff':cutoff,'latest_label':max((r['mature_day'] for r in rows),default=None),
          'global_selected':global_exit,'global_diagnostics':diag,'group_diagnostics':groups,'stocks_with_20_closed_events':eligible_stocks,'individual_changes':accepted_stocks})
    return models,audit


def policy_exit(policy,event,models):
    if policy=='atr4' or policy.endswith('_atr4') or policy=='atr4_riskcap3pct':return 'atr4_rr1.5'
    if policy=='atr6':return 'atr6_rr1.5'
    model=models.get(int(event['day'][:4]),{'global':'baseline','group':{},'stock':{}})
    if policy=='rolling_global':return model['global']
    if policy=='rolling_vol_group':return model['group'].get(event['bucket'],model['global'])
    if policy=='rolling_stock_shrink20':return model['stock'].get(event['sid'],model['global'])
    return 'baseline'


def simulate_adaptive(stocks,calendar,candidates,market,policy,models,start='2016-01-01',end=None,cost=.006,slots=5):
    days=[d for d in calendar if d>=start and (end is None or d<end)];fee=cost/2
    cash=1.;held={};pending=[];curve=[];trades=[];last_nav=1.;cancelled=0;choices=collections.Counter()
    for day in days:
        def sell(sid,p,px,why):
            nonlocal cash
            proceeds=p['units']*px*(1-fee);cash+=proceeds
            trades.append({'sid':sid,'d0':p['entry_day'],'d1':day,'r':proceeds/p['spent']-1,'why':why,'days':p['days'],
              'entry':p['entry'],'exit':float(px),'policy_exit':p['policy_exit'],'bucket':p['bucket'],'signal':p['signal'],'spent':p['spent'],'threshold':p['threshold'],'unresolved_large_gaps':p['gaps']})
        gone=[]
        for sid,p in held.items():
            e=stocks[sid];i=e['idx'].get(day)
            if i is None or e['a'][i,4]<=0:continue
            o=e['a'][i,0]
            if i and abs(o/e['a'][i-1,3]-1)>(.115 if market=='TW' else .5):p['gaps'].append({'day':day,'gap':float(o/e['a'][i-1,3]-1)})
            px,why=touch_exit(o,o,o,p['stop'],p['target'])
            if px is not None:sell(sid,p,px,why);gone.append(sid)
        for sid in gone:del held[sid]
        for order in pending:
            sid=order['sid'];e=stocks[sid];i=e['idx'].get(day)
            # A next-session opening order does not remain executable indefinitely through suspension.
            if i is None or e['a'][i,4]<=0:cancelled+=1;continue
            entry=float(e['a'][i,0]);sl,tp,hold=exit_terms(market,order['policy_exit'],entry,order['atr'])
            spend=min(cash,order['budget'])
            if policy=='atr4_riskcap3pct':spend=min(spend,order['nav']*.03/sl)
            if not(math.isfinite(entry) and entry>0 and spend>1e-12):continue
            cash-=spend;held[sid]={'entry':entry,'entry_day':day,'units':spend/(entry*(1+fee)),'spent':spend,'mark':entry,'days':0,
              'stop':entry*(1-sl),'target':entry*(1+tp),'hold':hold,'policy_exit':order['policy_exit'],'bucket':order['bucket'],'signal':order['day'],'threshold':order['threshold'],'gaps':[]}
        pending=[];gone=[]
        for sid,p in held.items():
            e=stocks[sid];i=e['idx'].get(day)
            if i is None or e['a'][i,4]<=0:continue
            o,h,l,c,v=e['a'][i];p['days']+=1;px,why=touch_exit(o,h,l,p['stop'],p['target'])
            if px is None and p['days']>=p['hold']:px,why=c,'time'
            if px is not None:sell(sid,p,px,why);gone.append(sid)
            else:p['mark']=float(c)
        for sid in gone:del held[sid]
        value=sum(p['units']*p['mark'] for p in held.values());nav=cash+value
        if not math.isfinite(nav) or cash < -1e-9 or len(held)>slots:raise AssertionError('wealth/cash constraint')
        curve.append({'d':day,'nav':float(nav),'cash':float(cash),'exposure':value/nav if nav else 0,'positions':len(held)})
        available=cash
        for event in candidates.get(day,[]):
            if len(held)+len(pending)>=slots:break
            sid=event['sid']
            if sid in held or any(o['sid']==sid for o in pending):continue
            spend=min(available,nav/slots)
            if spend<=1e-12:break
            pick=policy_exit(policy,event,models);choices[pick]+=1
            pending.append({**event,'budget':spend,'nav':nav,'policy_exit':pick,'atr':float(stocks[sid]['atr'][event['i']])});available-=spend
        last_nav=nav
    m=summarize(curve,trades)
    m.update(cancelled_unavailable_open=cancelled,exit_choices=dict(choices),flagged_gap_trades=sum(bool(t['unresolved_large_gaps']) for t in trades),open_flagged_gaps=sum(bool(p['gaps']) for p in held.values()))
    return {'metrics':m,'curve':curve,'trades':trades}


def event_stats(rows):
    if not rows:return {'n':0}
    r=np.array([x['r'] for x in rows]);years=collections.defaultdict(list)
    for x in rows:years[x['day'][:4]].append(x['r'])
    losses=-r[r<0].sum()
    return {'n':len(rows),'mean_pct':float(r.mean()*100),'win_pct':float(np.mean(r>0)*100),'pf':float(r[r>0].sum()/losses) if losses else None,
      'positive_years':sum(np.mean(v)>0 for v in years.values()),'years':len(years),'yearly_mean_pct':{y:float(np.mean(v)*100) for y,v in sorted(years.items())}}


def serial_events(events,policy,models,start='2016-01-01',end=None):
    last={};rows=[]
    for event in sorted(events,key=lambda r:(r['day'],r['sid'])):
        sid=event['sid']
        if event['day']<start or (end is not None and event['day']>=end) or event['i']<last.get(sid,-1):continue
        pick=policy_exit(policy,event,models);outcome=event['outcomes'][pick]
        last[sid]=outcome['exit_i']  # Unfinished positions still block later entries.
        if outcome['why']=='boundary_mark' or (end is not None and outcome['exit_day']>=end):continue
        rows.append({**outcome,'day':event['day'],'sid':sid,'bucket':event['bucket'],'er':event['er'],'sec':event['sec']})
    return rows


def bootstrap_delta(a,b,repetitions=1000):
    if len(a)!=len(b) or not a:return None
    rng=np.random.default_rng(1161);diff=np.array(a)-np.array(b);n=len(diff);block=20;results=[]
    for _ in range(repetitions):
        start=rng.integers(0,n,max(1,math.ceil(n/block)));idx=np.concatenate([(s+np.arange(block))%n for s in start])[:n]
        results.append(diff[idx].mean()*252*100)
    return {'daily_nav_log_return_delta_annualized_pct':float(diff.mean()*252*100),'block_sessions':block,'repetitions':repetitions,
      'p025':float(np.quantile(results,.025)),'p975':float(np.quantile(results,.975)),'limitation':'fixed-rule paired block bootstrap; not a correction for all model searches'}


def main(out,cache_dir,markets=('TW','US')):
    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    report={'version':'r1161','generated':dt.datetime.now(dt.timezone.utc).isoformat(),'source_commit':source_commit,
      'design':json.loads((ROOT/'research/r1161-design.json').read_bytes()),'markets':{}}
    all_runs={}
    for market in markets:
        print('LOAD',market,flush=True);stocks,sources,sha=load_market(market,cache_dir);calendar=sorted({d for e in stocks.values() for d in e['d']})
        print('FEATURED',market,len(stocks),calendar[0],calendar[-1],flush=True)
        events,base,own=build_events(stocks,market);models,audit=fit_years(events)
        print('EVENTS',market,len(events),sum(map(len,base.values())),sum(map(len,own.values())),flush=True)
        baseline_rows=serial_events(events,'baseline',models);by_sid=collections.Counter(x['sid'] for x in baseline_rows)
        active_counts=[by_sid[sid] for sid in stocks]
        quality={'stocks':len(stocks),'price_first':calendar[0],'price_last':calendar[-1],'signature':sha,'sources':sources,
          'serial_completed_trades':len(baseline_rows),'stocks_with_any_completed':sum(x>0 for x in active_counts),
          'stocks_with_20_completed_full_history':sum(x>=20 for x in active_counts),'median_completed_per_stock':float(np.median(active_counts)),
          'count_distribution':dict(collections.Counter('0' if x==0 else '1-4' if x<5 else '5-9' if x<10 else '10-19' if x<20 else '20+' for x in active_counts)),
          'tw_known_discontinuities':sum(len(e['anomalies']) for e in stocks.values()),
          'largest_discontinuities':sorted([dict(sid=sid,**r) for sid,e in stocks.items() for r in e['anomalies']],key=lambda x:abs(x['return']),reverse=True)[:30]}
        section={'data':quality,'annual_models':audit,'results':[],'event_groups':{},'oracle_diagnostic':{},'profile_examples':[]}
        for period,start,end in [('development','2016-01-01','2021-01-01'),('validation','2021-01-01','2024-01-01')]:
            for policy in POLICIES:
                candidates=own if policy.startswith('own_drawdown') else base
                run=simulate_adaptive(stocks,calendar,candidates,market,policy,models,start,end);all_runs[market,period,policy]=run
                row={'period':period,'policy':policy,**run['metrics']};section['results'].append(row);print(json.dumps({'market':market,**row}),flush=True)
        def better(p,base):
            return (p.get('n',0)>=100 and p['avg_pct']>base['avg_pct'] and (p['win_pct']>base['win_pct'] or (p['profit_factor'] or 0)>(base['profit_factor'] or 0))
              and p['positive_years']>=base['positive_years'] and p['cagr_pct']>=base['cagr_pct'] and p['mdd_pct']>=base['mdd_pct'])
        finalists=[p for p in POLICIES if p!='baseline' and all(better(all_runs[market,period,p]['metrics'],all_runs[market,period,'baseline']['metrics']) for period in ['development','validation'])]
        section['frozen_finalists']=finalists
        # Descriptive final comparison is kept for every predeclared model; only frozen finalists can qualify.
        for period,start,end in [('final_audit','2024-01-01',None),('full','2016-01-01',None)]:
            for policy in POLICIES:
                candidates=own if policy.startswith('own_drawdown') else base
                run=simulate_adaptive(stocks,calendar,candidates,market,policy,models,start,end);all_runs[market,period,policy]=run
                section['results'].append({'period':period,'policy':policy,**run['metrics']})
                print(json.dumps({'market':market,'period':period,'policy':policy,**run['metrics']}),flush=True)
        section['eligible']=[p for p in finalists if all(better(all_runs[market,period,p]['metrics'],all_runs[market,period,'baseline']['metrics']) for period in ['final_audit','full'])]
        for policy in POLICIES:
            candidates=own if policy.startswith('own_drawdown') else base
            run=simulate_adaptive(stocks,calendar,candidates,market,policy,models,cost=.01)
            section['results'].append({'period':'full_cost1pct','policy':policy,**run['metrics']})
            full=all_runs[market,'full',policy];save(out.parent/(out.stem+'_'+market+'_'+policy+'_ledger.json'),{'curve':full['curve'],'trades':full['trades']})
            if policy!='baseline':
                a=np.diff(np.log([1.]+[r['nav'] for r in full['curve']]));b=np.diff(np.log([1.]+[r['nav'] for r in all_runs[market,'full','baseline']['curve']]))
                section.setdefault('bootstrap',{})[policy]=bootstrap_delta(a.tolist(),b.tolist(),300)
        for name,groupf in [('volatility',lambda r:['low','middle','high'][r['bucket']]),('direction',lambda r:'up' if r['er']>.2 else 'down' if r['er']<-.2 else 'choppy'),('sector_current_descriptive',lambda r:r['sec'])]:
            gs=collections.defaultdict(list)
            for row in baseline_rows:gs[groupf(row)].append(row)
            section['event_groups'][name]={k:event_stats(v) for k,v in gs.items()}
        # An explicitly invalid hindsight selection shows why per-stock fitting can look deceptively strong.
        by_stock=collections.defaultdict(list)
        for event in events:
            if event['day']>='2016-01-01' and event['mature']:by_stock[event['sid']].append(event)
        oracle=[];plain=[]
        for sid,rs in by_stock.items():
            best=max(EXIT_NAMES,key=lambda n:np.mean([r['outcomes'][n]['r'] for r in rs]))
            oracle.extend([{'day':r['day'],'r':r['outcomes'][best]['r']} for r in rs]);plain.extend([{'day':r['day'],'r':r['outcomes']['baseline']['r']} for r in rs])
        section['oracle_diagnostic']={'invalid_future_aware_do_not_deploy':True,'baseline_common_events':event_stats(plain),'hindsight_best_per_stock':event_stats(oracle)}
        for sid in (['2330','2881','2603','6669','2454','1101'] if market=='TW' else ['NVDA','TSLA','AAPL','KO','JPM','MSFT']):
            if sid not in stocks:continue
            e=stocks[sid];i=len(e['d'])-1;raw_meta=next((s for s in json.loads((ROOT/'data.json').read_bytes())['stocks'] if s['id']==sid and s['market']==market),{})
            rs=[x for x in baseline_rows if x['sid']==sid];atrp=float(e['atrp'][i]);sl=BASE[market][1]
            section['profile_examples'].append({'id':sid,'name':e['name'],'as_of':e['d'][i],'atr20_pct':atrp*100,'fixed_stop_atr_multiple':sl/atrp,
              'own_entry_threshold_pct':float(e['own_threshold'][i])*100,'completed_baseline':event_stats(rs),
              'current_quote_for_context_only':raw_meta.get('price'),'latest_model':models[2026]['stock'].get(sid,models[2026]['global'])})
        section['decision']='research_only_no_live_rule_change' if not section['eligible'] else 'candidate_requires_further_execution_parity_and_risk_review'
        report['markets'][market]=section;save(out,report)
        del stocks
    report['complete']=True;save(out,report)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--cache-dir',type=Path,default=ROOT/'.cache/r1161')
    ap.add_argument('--market',choices=['TW','US','both'],default='both')
    args=ap.parse_args();main(args.output,args.cache_dir,('TW','US') if args.market=='both' else (args.market,))
