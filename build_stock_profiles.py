"""r1161: Explicit research snapshot rebuild. No scheduling or trading-rule writes."""
import argparse,collections,hashlib,json
from pathlib import Path
import stock_adaptive_research as R

def preserve(path,root):
    if not path.exists():return
    raw=path.read_bytes();dest=root/'archive/stock_research/profile_versions'/f'{hashlib.sha256(raw).hexdigest()}.json'
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists() and dest.read_bytes()!=raw:raise ValueError('immutable snapshot conflict')
    if not dest.exists():dest.write_bytes(raw)

def build(root,cache_dir):
    result={'schema':1,'version':'r1161','research_only':True,'evaluation_start':'2016-01-01','cost_round_trip':.006,'strategy':{'TW':'60日高首次回檔40%；隔日開盤；−15%／+20%／60交易日','US':'60日高首次回檔35%；隔日開盤；−20%／+30%／90交易日'},'stocks':{}}
    for market in ['TW','US']:
        stocks,_,_=R.load_market(market,cache_dir);events,_,_=R.build_events(stocks,market)
        counts=collections.Counter(e['sid'] for e in R.serial_events(events,'baseline',{}))
        for sid,e in stocks.items():result['stocks'][market+':'+sid]={'as_of':e['d'][-1],'history_start':e['d'][0],'bars':len(e['d']),'completed':counts[sid]}
    target=root/'strategy_profiles.json';preserve(target,root)
    target.write_bytes(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8'));preserve(target,root)
    return result
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cache-dir',type=Path,default=R.ROOT/'.cache/r1161');args=parser.parse_args()
    print('研究截止日',R.ASOF,'；本程式不推送、不排程、不改買賣規則。')
    print('股票數',len(build(R.ROOT,args.cache_dir)['stocks']))
