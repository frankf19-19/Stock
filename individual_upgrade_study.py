"""r1157 個股跌深進出場比較：研究檔，不修改上線規則。"""
import argparse,collections,datetime as dt,json
from pathlib import Path
import numpy as np
import short_bt_study as SB
from portfolio_research import touch_exit
from strategy_research import load_us

def stats(rows):
    if not rows:return {'n':0}
    r=np.array([x['r'] for x in rows]);years=collections.defaultdict(list)
    for x in rows:years[x['entry_day'][:4]].append(x['r'])
    return dict(n=len(rows),avg_pct=round(float(r.mean())*100,3),win_pct=round(float((r>0).mean())*100,2),profit_factor=round(float(r[r>0].sum()/max(1e-9,-r[r<0].sum())),3),
      positive_years=int(sum(np.mean(v)>0 for v in years.values())),years=len(years),worst5_pct=round(float(np.percentile(r,5))*100,3),
      yearly_avg_pct={k:round(float(np.mean(v))*100,3) for k,v in sorted(years.items())},boundary_marks=sum(x['why']=='boundary_mark' for x in rows))

def events(S):
    for e in S.values():
        a=e['a'];e['h60']=SB.roll_max(a[:,1],60);cv=np.r_[0,np.cumsum(a[:,3]*a[:,4])];e['liq']=np.full(len(a),np.nan);e['liq'][19:]=(cv[20:]-cv[:-20])/20

def run(S,market,variant,start,end):
    th,sl,tp,hold=(.4,.15,.2,60) if market=='TW' else (.35,.2,.3,90)
    if variant=='shorter_hold':hold//=2
    if variant=='wider_target':tp+=.1
    if variant=='tighter_stop':sl-=.05
    if variant=='trailing15_after20':tp=0
    out=[]
    for sid,e in S.items():
        a=e['a'];ds=e['d'];n=len(ds);last=-1
        limit=n if end is None else next((i for i,d in enumerate(ds) if d>=end),n)
        for i in range(250,limit-1):
            if i<=last or ds[i]<start or e['liq'][i]<2e4:continue
            if not(a[i,3]/e['h60'][i]-1<=-th and a[i-1,3]/e['h60'][i-1]-1>-th):continue
            signal=i
            if variant=='wait_up5':
                j=next((j for j in range(i+1,min(i+6,limit-1)) if a[j,3]>a[j-1,3]),None)
                if j is None:last=min(i+5,limit-1);continue
                i=j
            ei=i+1;entry=a[ei,0]
            if not(np.isfinite(entry) and entry>0):continue
            stop=entry*(1-sl);target=entry*(1+tp) if tp else None;peak=entry
            for k in range(ei,min(limit,ei+hold)):
                o,h,l,c,v=a[k];px,why=touch_exit(o,h,l,stop,target)
                if px is None and k==ei+hold-1:px,why=c,'time'
                if px is None and k==limit-1:px,why=c,'boundary_mark'
                if px is not None:
                    out.append(dict(sid=sid,signal_day=ds[signal],entry_day=ds[ei],exit_day=ds[k],r=float(px*.997/(entry*1.003)-1),why=why));last=k;break
                peak=max(peak,h)
                if variant=='trailing15_after20' and peak>=entry*1.2:stop=max(stop,peak*.85)
    return out

def main(out):
    root=Path(__file__).resolve().parent;report={'generated':dt.datetime.now(dt.timezone.utc).isoformat(),'type':'individual_event_comparison','cost_roundtrip':.006,
      'limitations':['事件平均不是資金組合年化，不能跟五檔組合績效混用','目前股票庫有倖存者偏差','分段最後持倉按最後收盤扣估計賣出費用評價，標boundary_mark，不冒充實際出場','歷史期間已被研究，並非真正未見資料','只有通過前後段與風險門檻才可提議改版'],'results':[]}
    variants=['baseline','wait_up5','shorter_hold','wider_target','tighter_stop','trailing15_after20']
    for market in ['TW','US']:
        print('loading',market,flush=True);S=SB.load_all() if market=='TW' else load_us(root);events(S)
        for period,start,end in [('first','2016-01-01','2021-01-01'),('second','2021-01-01',None)]:
            for v in variants:
                rows=run(S,market,v,start,end);r=dict(market=market,period=period,variant=v,**stats(rows));report['results'].append(r);print(json.dumps(r),flush=True)
        del S
    report['decision']='research_only_no_automatic_rule_change';out.parent.mkdir(exist_ok=True,parents=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);main(ap.parse_args().output)

