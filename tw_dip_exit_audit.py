"""Focused TW dip exits after event-stage screening; fixed ranking and cash constraints."""
import json,os,datetime as dt
from dataclasses import replace
from pathlib import Path
import short_bt_study as SB
from portfolio_research import Policy,simulate
from individual_upgrade_study import events,run,stats
S=SB.load_all();events(S);cal=sorted({d for e in S.values() for d in e['d']});ranks={}
for sid,e in S.items():
    e['idx']={d:i for i,d in enumerate(e['d'])}
    for i in range(250,len(e['d'])):
        d=e['d'][i]
        if d<'2016-01-01' or not e['liq'][i]>=2e4:continue
        if e['a'][i,3]/e['h60'][i]-1<=-.4 and e['a'][i-1,3]/e['h60'][i-1]-1>-.4:
            ranks.setdefault(d,[]).append(dict(sid=sid,sec=e.get('sec') or '',sc=4,r20=0,atrp=.03,c=float(e['a'][i,3]),liq=float(e['liq'][i])))
for r in ranks.values():r.sort(key=lambda c:(-c['liq'],c['sid']))
pol={'baseline':Policy(hold=60,sector_cap=5),'wider_target':Policy(hold=60,tp=.3,sector_cap=5),'trailing15_after20':Policy(hold=60,tp=0,trail=.15,trail_arm=.2,sector_cap=5)}
report={'type':'focused_tw_dip_exit_audit','ranking':'signal-close 20d liquidity descending; 5 slots, at most NAV/5 each entry; no sector cap','limitations':['This five-slot TW dip portfolio is a research scenario; live TW dip tracker has no slot/capital accounting','Candidates selected after earlier two-period event study; final period is reused chronological audit, not unseen holdout'],'results':[],'event_cost1pct':[]}
for period,start,end in [('development','2016-01-01','2021-01-01'),('validation','2021-01-01','2024-01-01'),('final_audit','2024-01-01',None),('full','2016-01-01',None)]:
    for name,p in pol.items():
        r=simulate(S,cal,ranks,p,start,end);row=dict(period=period,variant=name,**r['metrics']);report['results'].append(row);print(json.dumps(row),flush=True)
for name,p in pol.items():
    r=simulate(S,cal,ranks,replace(p,cost=.01));report['results'].append(dict(period='full_cost1pct',variant=name,**r['metrics']))
    for period,start,end in [('first','2016-01-01','2021-01-01'),('second','2021-01-01',None)]:
        rows=run(S,'TW',name,start,end)
        for x in rows:x['r']=(x['r']+1)/(.997/1.003)*(.995/1.005)-1
        row=dict(period=period,variant=name,**stats(rows));report['event_cost1pct'].append(row);print('COST',json.dumps(row),flush=True)
Path('../tw_dip_r1157_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
