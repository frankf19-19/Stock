"""r1157 research-only daily cash/units engine. Never imported by live trading jobs."""
from dataclasses import dataclass
from datetime import date
import collections, math
import numpy as np

@dataclass(frozen=True)
class Policy:
    slots: int = 5
    sector_cap: int = 2
    hold: int = 15
    sl: float = .15
    tp: float = .20
    min_score: int = 4
    max_r20: float | None = None
    max_gap: float | None = None
    trail: float | None = None
    trail_arm: float = .10
    break_even: float | None = None
    risk_scale: bool = False
    cost: float = .006

def touch_exit(o, h, l, stop, target):
    # Opening auction is observed before the intraday range; ambiguous range: stop first.
    if stop is not None and o <= stop: return o, 'gap_sl'
    if target is not None and o >= target: return o, 'gap_tp'
    if stop is not None and l <= stop: return stop, 'sl'
    if target is not None and h >= target: return target, 'tp'
    return None, None

def summarize(curve, trades, initial=1.):
    if not curve: return {}
    nav=np.array([x['nav'] for x in curve]);peaks=np.maximum.accumulate(np.r_[initial,nav])[1:]
    years=collections.defaultdict(list)
    for x in curve: years[x['d'][:4]].append(x['nav'])
    prior=initial; yr={}
    for y,vals in sorted(years.items()): yr[y]=(vals[-1]/prior-1)*100;prior=vals[-1]
    span=max(1,(date.fromisoformat(curve[-1]['d'])-date.fromisoformat(curve[0]['d'])).days+1)/365.25
    returns=np.array([t['r'] for t in trades]);gain=returns[returns>0].sum();loss=-returns[returns<0].sum()
    daily=np.diff(np.log(np.r_[initial,nav]));down=daily[daily<0]
    return dict(n=len(trades),cagr_pct=round(((nav[-1]/initial)**(1/span)-1)*100,3),mdd_pct=round(float(np.min(nav/peaks-1))*100,3),
        avg_pct=round(float(returns.mean())*100,3) if len(returns) else None,win_pct=round(float((returns>0).mean())*100,2) if len(returns) else None,
        profit_factor=round(float(gain/loss),3) if loss else None,positive_years=sum(v>0 for v in yr.values()),years=len(yr),
        yearly_pct={y:round(v,3) for y,v in yr.items()},final_nav=round(float(nav[-1]),6),
        exposure_pct=round(float(np.mean([x['exposure'] for x in curve]))*100,2),open_positions=curve[-1]['positions'],
        worst_year_pct=round(min(yr.values()),3),min_cash=round(min(x['cash'] for x in curve),12))

def simulate(stocks, calendar, candidates, policy=Policy(), start='2016-01-01', end=None, initial=1.):
    """candidates: dated, close-known ranks; no future-bar eligibility check.
    Orders wait for that symbol's next available bar (suspensions retained).
    End boundary marks open holdings, never drops unfinished losers. No forced sale.
    """
    days=[d for d in calendar if d>=start and (end is None or d<end)]
    cash=initial; held={};pending=[];trades=[];curve=[];last_nav=initial
    fee=policy.cost/2
    for day in days:
        # Existing stops/targets triggered at open release cash before new orders.
        def sell(sid,p,px,why):
            nonlocal cash
            proceeds=p['units']*px*(1-fee);cash+=proceeds
            trades.append(dict(sid=sid,d0=p['entry_day'],d1=day,r=proceeds/p['spent']-1,why=why,days=p['days'],entry=p['entry'],exit=float(px)))
        opening_exits=[]
        for sid,p in held.items():
            e=stocks[sid];i=e['idx'].get(day)
            if i is None:continue
            o=e['a'][i,0];px,why=touch_exit(o,o,o,p['stop'],p['target'])
            if px is not None:sell(sid,p,px,why);opening_exits.append(sid)
        for sid in opening_exits:del held[sid]
        # Each reservation fixed at previous close; no replacing rejected gap orders with future-aware picks.
        waiting=[]
        for order in pending:
            sid=order['sid'];e=stocks[sid];i=e['idx'].get(day)
            if i is None:waiting.append(order);continue
            o=e['a'][i,0]
            if not math.isfinite(o) or o<=0:waiting.append(order);continue
            if policy.max_gap is not None and o/order['close']-1>policy.max_gap:continue
            spend=min(cash,order['budget'])
            if spend<=1e-12:continue
            cash-=spend;entry=float(o)
            held[sid]=dict(entry=entry,entry_day=day,spent=spend,units=spend/(entry*(1+fee)),days=0,
                stop=entry*(1-policy.sl) if policy.sl else None,target=entry*(1+policy.tp) if policy.tp else None,
                peak=entry,mark=entry,sec=order['sec'])
        pending=waiting
        intraday_exits=[]
        for sid,p in held.items():
            e=stocks[sid];i=e['idx'].get(day)
            if i is None:continue
            o,h,l,c,v=e['a'][i];p['days']+=1
            px,why=touch_exit(o,h,l,p['stop'],p['target'])
            if px is None and p['days']>=policy.hold:px,why=c,'time'
            if px is not None:sell(sid,p,px,why);intraday_exits.append(sid);continue
            p['mark']=float(c)
            # Today's HIGH may arm tomorrow's stop only; cannot retroactively stop on today's LOW.
            p['peak']=max(p['peak'],float(h))
            if policy.trail and p['peak']>=p['entry']*(1+policy.trail_arm):p['stop']=max(p['stop'] or 0,p['peak']*(1-policy.trail))
            if policy.break_even and p['peak']>=p['entry']*(1+policy.break_even):p['stop']=max(p['stop'] or 0,p['entry']*(1+fee)/(1-fee))
        for sid in intraday_exits:del held[sid]
        value=sum(p['units']*p['mark'] for p in held.values());nav=cash+value
        if cash < -1e-10 or len(held)+len(pending)>policy.slots:raise AssertionError('cash/slot constraint')
        curve.append(dict(d=day,nav=float(nav),cash=float(cash),exposure=value/nav if nav else 0,positions=len(held)))
        # Selection occurs strictly after this session closes.
        if day in candidates:
            occupied=set(held)|{p['sid'] for p in pending};secs=collections.Counter(p['sec'] for p in held.values());secs.update(p['sec'] for p in pending)
            reserved=sum(p['budget'] for p in pending);available=max(0,cash-reserved)
            for c in candidates[day]:
                if len(held)+len(pending)>=policy.slots:break
                if c['sid'] in occupied or c['sc']<policy.min_score or secs[c['sec']]>=policy.sector_cap:continue
                if policy.max_r20 is not None and c['r20']>policy.max_r20:continue
                scale=min(1.,.03/max(c['atrp'],.0001)) if policy.risk_scale else 1.
                budget=min(available,nav/policy.slots*scale)
                if budget<=1e-12:break
                pending.append(dict(sid=c['sid'],budget=budget,close=c['c'],sec=c['sec']))
                available-=budget;secs[c['sec']]+=1;occupied.add(c['sid'])
        last_nav=nav
    return dict(metrics=summarize(curve,trades,initial),curve=curve,trades=trades)
