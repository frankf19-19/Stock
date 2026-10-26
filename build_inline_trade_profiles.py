"""r1171: lossless study inputs stay immutable; derive a compact primary-card view."""
import gzip,hashlib,json
from pathlib import Path
from build_trade_plan_report import price,next_day

def build(root):
    source=root/'research/r1170/conditional-plans.json.gz';raw=source.read_bytes();j=json.loads(gzip.decompress(raw))
    holiday_raw=(root/'holidays.json').read_bytes();holidays=json.loads(holiday_raw)
    out={'schema':1,'version':'r1170','research_only':True,'source_sha256':hashlib.sha256(raw).hexdigest(),
         'calendar_sha256':hashlib.sha256(holiday_raw).hexdigest(),'stocks':{}}
    for key,s in j['stocks'].items():
        market=key.split(':')[0];selected=s['development_selected'];p=s['current'].get(selected) if selected and s['validation_supported'] else None
        if p:
            p=dict(p);original=p['trigger'];p['trigger']=price(original,market,True)
            if selected.startswith('break') and p['trigger']<=original:p['trigger']=price(p['trigger']+(0.01 if market=='US' else 0.0001),market,True)
            for k in ('upper','stop','target'):p[k]=price(p[k],market)
            p['ordered']=0<p['stop']<p['upper']<p['target'] and p['trigger']<=p['upper']
            p['confirm_day']=next_day(p['asof'],market,holidays);p['order_day']=next_day(p['confirm_day'],market,holidays)
        models={m:{short:[v[k] for k in ('n','completed','avg_pct','pf','positive_years','years')] if v['n'] else [0,0,None,None,0,0]
                   for short,long in [('d','development'),('v','validation'),('a','recent_audit')] for v in [periods[long]]}
                for m,periods in s['models'].items()}
        out['stocks'][key]={'selected':selected,'supported':s['validation_supported'],'asof':s['asof'],
                            'start':s['start'],'bars':s['bars'],'models':models,'plan':p}
    path=root/'trade_research_profiles.json';path.write_bytes(json.dumps(out,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())
    return out

if __name__=='__main__':print(len(build(Path(__file__).resolve().parent)['stocks']))
