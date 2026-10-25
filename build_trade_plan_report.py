"""Build a standalone, dated research viewer; never changes live trading rules."""
import argparse,datetime as dt,gzip,json,math
from pathlib import Path

ROOT=Path(__file__).resolve().parent
LABELS={'trend20':'月線回檔承接','trend60':'季線回檔承接','break20':'突破20日高','break60':'突破60日高','range20':'盤整低檔承接','reclaim60':'收復季線'}

def price(x,market,up=False):
    if market=='US':return (math.ceil(x*100-1e-8) if up else math.floor(x*100+1e-8))/100
    tick=.01 if x<10 else .05 if x<50 else .1 if x<100 else .5 if x<500 else 1 if x<1000 else 5
    return round((math.ceil(x/tick-1e-8) if up else math.floor(x/tick+1e-8))*tick,2)

def next_day(day,market,holidays):
    d=dt.date.fromisoformat(day)
    for _ in range(20):
        d+=dt.timedelta(days=1)
        if d.weekday()<5 and d.isoformat() not in holidays.get(market.lower(),{}):return d.isoformat()
    return None

def build(source,output):
    report=json.loads(gzip.decompress(source.read_bytes()) if source.suffix=='.gz' else source.read_bytes())
    names={s['market']+':'+s['id']:s.get('name',s['id']) for s in json.loads((ROOT/'data.json').read_bytes())['stocks']}
    holidays=json.loads((ROOT/'holidays.json').read_bytes());rows={}
    for key,s in report['stocks'].items():
        market=key.split(':')[0];plans={}
        for model,p in s['current'].items():
            if model!=s['development_selected'] or not s['validation_supported']:continue
            if p is None:continue
            p=dict(p);p['trigger']=price(p['trigger'],market,True)
            if model.startswith('break') and p['trigger']<=s['current'][model]['trigger']:p['trigger']=price(p['trigger']+(0.01 if market=='US' else 0.0001),market,True)
            for name in ('upper','stop','target'):p[name]=price(p[name],market)
            p['ordered']=0<p['stop']<p['upper']<p['target'] and p['trigger']<=p['upper']
            p['confirm_day']=next_day(p['asof'],market,holidays);p['order_day']=next_day(p['confirm_day'],market,holidays)
            plans[model]=p
        models={m:{period:{k:v[k] for k in ('n','avg_pct','pf')} for period,v in periods.items()} for m,periods in s['models'].items()}
        rows[key]=dict(name=names.get(key,key),**{k:s[k] for k in ('asof','start','bars','development_selected','validation_supported')},models=models,plans=plans)
    data=json.dumps({'stocks':rows,'markets':{k:{'stocks':v['stocks'],'counts':v['counts']} for k,v in report['markets'].items()},'labels':LABELS},ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    template=(ROOT/'trade_plan_report_template.html').read_text(encoding='utf-8')
    output.write_bytes(template.replace('__RESEARCH_DATA__',data).encode('utf-8'))
    return len(rows)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();print(build(a.source,a.output))
