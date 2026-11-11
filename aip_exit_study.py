import sys, os, collections, time, datetime as dt
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); os.chdir(os.path.dirname(os.path.abspath(__file__)))
import short_bt_study as SB
from aip_dip_study import prep_dip, breadth, dip_sig
def run(S, cal, BR, v):
    K = v.get('K', 5); idx = {sid: {d: k for k, d in enumerate(e['d'])} for sid, e in S.items()}
    wl = set()
    for k, d in enumerate(cal):
        nxt = cal[k+1] if k+1 < len(cal) else None
        if nxt is None or dt.date.fromisoformat(nxt).isocalendar()[1] != dt.date.fromisoformat(d).isocalendar()[1]: wl.add(d)
    trades = []; open_pos = []; daily = collections.defaultdict(float); CI = {d: k for k, d in enumerate(cal)}
    dip = v.get('dip'); th = v.get('th', 0.35); cap = (dip or {}).get('cap', K)
    for d in cal:
        still = []
        for p in open_pos:
            e = S[p['sid']]; k = idx[p['sid']].get(d)
            if k is None: still.append(p); continue
            O, H, L, C, V = e['a'][k]; n = k - p['ei'] + 1; ex = None
            ex = None
            if p['kind'] == 'mom':
                # 市場急殺 → 隔天開盤全出 / 收緊停損
                if p.get('mx'): ex = O; why = 'mkt'
                sl_ = p['sl']
                if v.get('be') and p.get('hi', 0) >= p['px'] * (1 + v['be']): sl_ = min(sl_, v.get('be_sl', 0.0))
                if p.get('tight'): sl_ = min(sl_, v['tight_sl'])
            else: sl_ = p['sl']
            if ex: pass
            elif L <= p['px'] * (1 - sl_): ex = min(O, p['px'] * (1 - sl_)); why = 'sl'
            elif p['tp'] and H >= p['px'] * (1 + p['tp']): ex = max(O, p['px'] * (1 + p['tp'])); why = 'tp'
            elif n >= p['hold']: ex = C; why = 'time'
            elif p['kind'] == 'mom' and v.get('fail') and n == v['fail'][0] and C <= p['px'] * (1 + v['fail'][1]): ex = C; why = 'fail'
            p['hi'] = max(p.get('hi', 0), H)
            if ex:
                r = ex / p['px'] - 1 - 0.006
                trades.append(dict(r=r, size=p['size'], year=d[:4], kind=p['kind']))
                daily[d] += r * p['size']
            else: still.append(p)
        open_pos = still
        held = {p['sid'] for p in open_pos}
        if v.get('mkt') and d in CI and CI[d] >= v['mkt'][0] and BR.get(d) is not None and BR.get(cal[CI[d]-v['mkt'][0]]) is not None and BR[cal[CI[d]-v['mkt'][0]]] - BR[d] > v['mkt'][1]:
            for p in open_pos:
                if p['kind'] == 'mom':
                    if v.get('tight_sl') is not None: p['tight'] = 1
                    else: p['mx'] = 1
        if v.get('bvol') is not None and len(open_pos) < K and BR.get(d, 1) < th and sum(p['kind'] == 'bvol' for p in open_pos) < v['bvol'].get('cap', K):
            bv = v['bvol']; c = []
            for sid, e in S.items():
                if sid in held: continue
                k = idx[sid].get(d)
                if k is None or k < 250 or k + 1 >= len(e['d']): continue
                F = e['F']; a_ = e['a']; Cc = a_[k][3]
                if not (F['liq'][k] >= 2e4) or not a_[k-1][3]: continue
                up = Cc / a_[k-1][3] - 1
                if up < 0.03: continue
                vr = a_[k][4] / max(F['v20p'][k], 1)
                if vr < 2: continue
                if not (Cc < F['ma60'][k] < F['ma60'][k-20]): continue
                if not (Cc <= F['hi120'][k] * 0.7 and Cc <= F['lo60'][k] * 1.10): continue
                c.append((-vr, sid, k))
            c.sort()
            for _, sid, k in c:
                if len(open_pos) >= K or sum(p['kind'] == 'bvol' for p in open_pos) >= bv.get('cap', K): break
                e = S[sid]; px0 = e['a'][k+1][0]
                if not px0: continue
                open_pos.append(dict(sid=sid, ei=k+1, px=px0, sec=e['sec'], size=1.0 / K, tp=bv.get('tp', 0.5), sl=bv.get('sl', 0.2), hold=bv.get('hold', 60), kind='bvol')); held.add(sid)
        # 跌深補位(每天):大盤一起跌、有空位
        if dip is not None and len(open_pos) < K and BR.get(d, 1) < th and sum(p['kind'] == 'dip' for p in open_pos) < cap:
            c = []
            for sid, e in S.items():
                if sid in held: continue
                k = idx[sid].get(d)
                if k is None or k + 1 >= len(e['d']): continue
                s = dip_sig(e, k)
                if s and (dip.get('kinds') is None or s[0] in dip['kinds']): c.append((s[0] != 'k40', e['F']['atr'][k] / e['a'][k][3], sid, k))
            c.sort()
            for _, _, sid, k in c:
                if len(open_pos) >= K or sum(p['kind'] == 'dip' for p in open_pos) >= cap: break
                e = S[sid]; px0 = e['a'][k+1][0]
                if not px0: continue
                open_pos.append(dict(sid=sid, ei=k+1, px=px0, sec=e['sec'], size=1.0 / K, tp=dip.get('tp', 0.5), sl=dip.get('sl', 0.2), hold=dip.get('hold', 120), kind='dip')); held.add(sid)
        # 短期清單(每週)
        drop_ok = True
        if v.get('drop'):
            k0 = cal.index(d) if False else None
        if v.get('drop') and d in CI and CI[d] >= v.get('lb',5) and BR.get(d) is not None and BR.get(cal[CI[d]-v.get('lb',5)]) is not None and BR[cal[CI[d]-v.get('lb',5)]] - BR[d] > v['drop']: drop_ok = False
        if v.get('hot') and BR.get(d, 0) > v['hot']: drop_ok = False
        if d in wl and drop_ok and not v.get('no_mom') and not (v.get('mom_off_weak') and BR.get(d, 1) < th):
            secs = collections.Counter(p['sec'] for p in open_pos); cands = []
            for sid, e in S.items():
                if sid in held: continue
                k = idx[sid].get(d)
                if k is None: continue
                s = SB.score_day(e, k)
                if not s: continue
                s['sid'] = sid; cands.append(s)
            cands.sort(key=lambda x: (-x['sc'], x['atrp']))
            for c in cands:
                if len(open_pos) >= K: break
                sec = S[c['sid']]['sec']
                if secs[sec] >= 2: continue
                e = S[c['sid']]; k = idx[c['sid']][d]
                if k + 1 >= len(e['d']): continue
                open_pos.append(dict(sid=c['sid'], ei=k+1, px=e['a'][k+1][0], sec=sec, size=1.0 / K, tp=v.get('tp', 0.20), sl=v.get('sl', 0.15), hold=v.get('hold', 15), kind='mom')); secs[sec] += 1
    eq = 1.0; peak = 1.0; mdd = 0.0; yr = collections.defaultdict(float)
    for d in cal:
        eq *= (1 + daily.get(d, 0.0)); peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
    for t in trades: yr[t['year']] += t['r'] * t['size']
    cagr = eq ** (245 / len(cal)) - 1
    kinds = collections.defaultdict(list)
    for t in trades: kinds[t['kind']].append(t['r'])
    return dict(daily=daily, cagr=cagr, mdd=mdd, worst=min(yr.values()), pos=sum(1 for x in yr.values() if x > 0), ny=len(yr), yrs={k: round(x*100, 1) for k, x in sorted(yr.items())},
                kinds={k: (len(x), round(float(np.mean(x))*100, 2), round(float(np.mean([r > 0 for r in x]))*100)) for k, x in kinds.items()})


S = SB.load_all(); SB.features(S); prep_dip(S)
for sid, e in S.items():
    a = e['a']; e['F']['hi120'] = SB.roll_max(a[:, 1], 120); e['F']['lo60'] = -SB.roll_max(-a[:, 2], 60)
cal = [d for d in sorted(set(d for e in S.values() for d in e['d'])) if d >= '2016-01-01']; BR = breadth(S)
BASE = dict(drop=0.25)
V = {'採用版(短期清單+急殺週不買)': {},
     '急殺(5日掉>25點)→短期部位隔天全出': dict(mkt=(5, 0.25)),
     '急殺(5日掉>15點)→短期部位隔天全出': dict(mkt=(5, 0.15)),
     '急殺(3日掉>15點)→短期部位隔天全出': dict(mkt=(3, 0.15)),
     '急殺(5日掉>15點)→停損收緊到 −7%': dict(mkt=(5, 0.15), tight_sl=0.07),
     '急殺(5日掉>25點)→停損收緊到 −7%': dict(mkt=(5, 0.25), tight_sl=0.07),
     '賺 10% 後停損移到成本': dict(be=0.10),
     '賺 8% 後停損移到成本': dict(be=0.08),
     '賺 12% 後停損移到 +3%': dict(be=0.12, be_sl=-0.03),
     '3 天後還賠 5% 就走': dict(fail=(3, -0.05)),
     '5 天後還賠 5% 就走': dict(fail=(5, -0.05)),
     '5 天後沒賺就走': dict(fail=(5, 0.0)),
     '+底部爆量補位(60日,−20/+50)': dict(bvol={}),
     '+底部爆量補位 最多 2 格': dict(bvol=dict(cap=2)),
     '+底部爆量補位(40日,−15/+30)': dict(bvol=dict(hold=40, sl=0.15, tp=0.3)),
     '+底部爆量 最多2格(90日,−20/+50)': dict(bvol=dict(cap=2, hold=90)),
}
def half(r, a, b): return round(sum(x for y, x in r['yrs'].items() if a <= y <= b), 1)
for nm in V:
    v = dict(BASE); v.update(V[nm]); r = run(S, cal, BR, v)
    print(f"{nm:30} 年化 {r['cagr']*100:+6.1f}% 回落 {r['mdd']*100:6.1f}% 最差年 {r['worst']*100:+6.1f}% 正年 {r['pos']}/{r['ny']} 前半 {half(r,'2016','2020')} 後半 {half(r,'2021','2026')} {r['kinds']}", flush=True)
    print('   逐年', r['yrs'], flush=True)
