"""r1156：可重現的跌深門檻事件研究。只產生研究檔，不改選股或交易規則。"""
import argparse,collections,datetime as dt,gzip,json
from pathlib import Path
import numpy as np
import short_bt_study as SB
import plan_bt_study as PB

def metrics(tr):
    if not tr:return {'n':0}
    r=np.array([x[2] for x in tr]);yrs=collections.defaultdict(list)
    for x in tr:yrs[x[1][:4]].append(x[2])
    return {'n':len(tr),'avg_pct':round(float(r.mean()*100),3),'median_pct':round(float(np.median(r)*100),3),'win_pct':round(float((r>0).mean()*100),2),'profit_factor':round(float(r[r>0].sum()/max(1e-9,-r[r<0].sum())),3),'positive_years':int(sum(np.mean(v)>0 for v in yrs.values())),'years':len(yrs),'yearly_avg_pct':{k:round(float(np.mean(v)*100),3) for k,v in sorted(yrs.items())}}

def load_us(root):
    merged=collections.defaultdict(dict)
    for path in sorted((root/'archive/k/us').glob('*/*.json.gz')):
        for sid,e in json.loads(gzip.decompress(path.read_bytes())).items():
            for d,o in zip(e.get('d',[]),e.get('o',[])):
                if len(o)>=5 and all(x is not None and np.isfinite(x) and x>0 for x in o[:4]):merged[sid][d]=o
    out={}
    for sid,rows in merged.items():
        if len(rows)<300:continue
        ds=sorted(rows);a=np.array([rows[d] for d in ds],float);a[:,4]/=1000
        out[sid]={'d':ds,'a':a,'f':np.zeros(len(ds)),'t':np.zeros(len(ds)),'rev':{}}
    return out

def research(root,out):
    report={'generated':dt.datetime.now(dt.timezone.utc).isoformat(),'type':'event-study','cost_roundtrip':.006,'limitations':['事件平均不是組合年化或最大回落','目前股票庫有倖存者／下市股缺漏風險','日K無法識別同日先停損或先停利；採停損優先','跨分段結束尚未出場者不納入該段完整交易','本次比較不自動改動任何上線門檻'],'results':[]}
    for market in ['TW','US']:
        print('loading',market,flush=True);S=SB.load_all() if market=='TW' else load_us(root);PB.prep(S)
        for e in S.values():e['hi60inc']=SB.roll_max(e['a'][:,1],60)
        print('ready',market,len(S),flush=True)
        base=.40 if market=='TW' else .35
        for th in [base-.05,base,base+.05]:
            def event(e,i):
                h=e['hi60inc'];c=e['a'][:,3]
                return c[i]/h[i]-1<=-th and c[i-1]/h[i-1]-1>-th
            ex=PB.mk_exit(sl=.15 if market=='TW' else .20,tp=.20 if market=='TW' else .30,hold=60 if market=='TW' else 90)
            for name,start,end in [('full','2016-01-01',None),('first','2016-01-01','2021-01-01'),('second','2021-01-01',None)]:
                tr=PB.simulate(S,event,ex,start=start,end=end)
                row={'market':market,'threshold':round(th,2),'baseline':abs(th-base)<1e-9,'period':name,**metrics(tr)}
                report['results'].append(row);print(json.dumps(row,ensure_ascii=True),flush=True)
        del S
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();research(Path(__file__).resolve().parent,a.output)
