"""r1186 research snapshot loader: permanent history plus recent website K bars. No live import."""
import collections,gzip,hashlib,json,math,pickle,sys
from pathlib import Path
import numpy as np
import pandas as pd
from stock_adaptive_research import ROOT,rolling_mean,BASE
ASOF='2026-10-28'
def load_market(market,cache_dir):
    paths=sorted((ROOT/'archive/k'/market.lower()).glob('*/*.json.gz'))+sorted((ROOT/'k').glob(market.lower()+'*.json'))
    extra=[ROOT/'data.json']+([ROOT/'archive/adj_tw.json.gz',ROOT/'adj1y.json'] if market=='TW' else [])
    action_dir=ROOT/'archive/stock_research/r1161/raw'
    action_paths=[action_dir/n for n in ('TaiwanStockSplitPrice.json','TaiwanStockParValueChange.json','capital_reductions.json')] if market=='TW' else []
    extra += [p for p in action_paths if p.exists()]
    sources=[{'path':str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else 'archive/stock_research/r1161/raw/'+p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths+extra]
    signature=hashlib.sha256(('loader-v3-recent-priority'+ASOF+hashlib.sha256(Path(__file__).read_bytes()).hexdigest()+json.dumps(sources,sort_keys=True)).encode()).hexdigest()
    cache=Path(cache_dir)/(market.lower()+'_'+signature[:16]+'.pkl.gz');cache.parent.mkdir(parents=True,exist_ok=True)
    if cache.exists():
        with gzip.open(cache,'rb') as f:return pickle.load(f),sources,signature
    universe=json.loads((ROOT/'data.json').read_bytes())['stocks'];metadata={str(s['id']):s for s in universe if s.get('market')==market}
    etfs={str(s['id']) for s in universe if s.get('etf')};merged=collections.defaultdict(dict)
    for path in paths:
        for sid,e in json.loads(gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes()).items():
            if sid in etfs or (market=='TW' and (not sid.isdigit() or len(sid)!=4)):continue
            for d,o in zip(e.get('d',[]),e.get('o',[])):
                if d>ASOF or len(o)<5 or any(v is None or not math.isfinite(v) or v<=0 for v in o[:4]):continue
                if not math.isfinite(o[4]) or o[4]<0:continue
                merged[sid][sys.intern(d)]=o
    adj=json.loads(gzip.decompress((ROOT/'archive/adj_tw.json.gz').read_bytes()))['s'] if market=='TW' else {}
    if market=='TW':
        recent=json.loads((ROOT/'adj1y.json').read_bytes()).get('s',{})
        for sid,rows in recent.items():adj[sid]=sorted(dict(adj.get(sid,[])+rows).items())
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
