"""r1209:AI Pick 短期清單 + 「大盤一起跌時的錯殺」互補回測。
短期清單 = r1141 採用版(每週最後交易日選、綜合分 ≥4、同分低波動優先、5 檔、同產業 ≤2、+20%/−15%/15 日)。
加上:空位(任何一天)且全市場站上季線比例 <TH 時,用跌深訊號補位(錯殺 −40% 第一天、跌 25% 後止跌・高波動),
跌深部位用自己的出場(預設 −20%/+50%/120 日)。比較年化、最大回落、最差年、正年。
用法:STOCK_BT_CACHE=<pkl> python3 aip_dip_study.py"""
import sys, os, collections, time, datetime as dt
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import short_bt_study as SB

def prep_dip(S):
    for sid, e in S.items():
        a = e['a']; H = a[:, 1]; C = a[:, 3]; n = len(C)
        h60 = np.full(n, np.nan); h60[60:] = SB.roll_max(H, 60)[59:-1]
        e['F']['h60'] = h60

def breadth(S):
    b = collections.defaultdict(lambda: [0, 0])
    for sid, e in S.items():
        C = e['a'][:, 3]; F = e['F']
        for i in range(60, len(C)):
            if F['liq'][i] >= 2e4: b[e['d'][i]][1] += 1; b[e['d'][i]][0] += C[i] > F['ma60'][i]
    return {d: v[0] / v[1] for d, v in b.items() if v[1] >= 50}

def dip_sig(e, i):
    a = e['a']; H = a[:, 1]; C = a[:, 3]; F = e['F']
    if i < 80 or not (F['liq'][i] >= 2e4): return None
    h = F['h60']
    if np.isnan(h[i]) or np.isnan(h[i-1]): return None
    dd, dd0 = C[i] / h[i] - 1, C[i-1] / h[i-1] - 1
    if dd <= -0.40 and dd0 > -0.40: return ('k40', dd)
    atrp = F['atr'][i] / C[i]
    if atrp >= 0.04 and dd <= -0.25 and C[i] > H[i-1] and C[i-1] <= H[i-2]:
        if any(C[j] / h[j] - 1 <= -0.25 and C[j-1] / h[j-1] - 1 > -0.25 for j in range(i-10, i)): return ('d25', dd)
    return None

def run(S, cal, BR, v):
    K = v.get('K', 5); idx = {sid: {d: k for k, d in enumerate(e['d'])} for sid, e in S.items()}
    wl = set()
    for k, d in enumerate(cal):
        nxt = cal[k+1] if k+1 < len(cal) else None
        if nxt is None or dt.date.fromisoformat(nxt).isocalendar()[1] != dt.date.fromisoformat(d).isocalendar()[1]: wl.add(d)
    trades = []; open_pos = []; daily = collections.defaultdict(float)
    dip = v.get('dip'); th = v.get('th', 0.35); cap = (dip or {}).get('cap', K)
    for d in cal:
        still = []
        for p in open_pos:
            e = S[p['sid']]; k = idx[p['sid']].get(d)
            if k is None: still.append(p); continue
            O, H, L, C, V = e['a'][k]; n = k - p['ei'] + 1; ex = None
            if L <= p['px'] * (1 - p['sl']): ex = min(O, p['px'] * (1 - p['sl'])); why = 'sl'
            elif p['tp'] and H >= p['px'] * (1 + p['tp']): ex = max(O, p['px'] * (1 + p['tp'])); why = 'tp'
            elif n >= p['hold']: ex = C; why = 'time'
            if ex:
                r = ex / p['px'] - 1 - 0.006
                trades.append(dict(r=r, size=p['size'], year=d[:4], kind=p['kind']))
                daily[d] += r * p['size']
            else: still.append(p)
        open_pos = still
        held = {p['sid'] for p in open_pos}
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
        if d in wl and not (v.get('mom_off_weak') and BR.get(d, 1) < th):
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
                open_pos.append(dict(sid=c['sid'], ei=k+1, px=e['a'][k+1][0], sec=sec, size=1.0 / K, tp=0.20, sl=0.15, hold=15, kind='mom')); secs[sec] += 1
    eq = 1.0; peak = 1.0; mdd = 0.0; yr = collections.defaultdict(float)
    for d in cal:
        eq *= (1 + daily.get(d, 0.0)); peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
    for t in trades: yr[t['year']] += t['r'] * t['size']
    cagr = eq ** (245 / len(cal)) - 1
    kinds = collections.defaultdict(list)
    for t in trades: kinds[t['kind']].append(t['r'])
    return dict(cagr=cagr, mdd=mdd, worst=min(yr.values()), pos=sum(1 for x in yr.values() if x > 0), ny=len(yr), yrs={k: round(x*100, 1) for k, x in sorted(yr.items())},
                kinds={k: (len(x), round(float(np.mean(x))*100, 2), round(float(np.mean([r > 0 for r in x]))*100)) for k, x in kinds.items()})

if __name__ == '__main__':
    t0 = time.time(); S = SB.load_all(); SB.features(S); prep_dip(S)
    cal = [d for d in sorted(set(d for e in S.values() for d in e['d'])) if d >= '2016-01-01']
    BR = breadth(S); print('ready', f'{time.time()-t0:.0f}s', flush=True)
    V = {'採用版(只有短期清單)': {},
         '+錯殺補位(<35%,−20/+50/120)': dict(dip={}),
         '+錯殺補位(<35%,−20/+30/90)': dict(dip=dict(tp=0.3, hold=90)),
         '+錯殺補位(只用 −40%)': dict(dip=dict(kinds=['k40'])),
         '+錯殺補位(門檻 <30%)': dict(dip={}, th=0.30),
         '+錯殺補位(門檻 <45%)': dict(dip={}, th=0.45),
         '+錯殺補位,大盤弱時短期清單暫停': dict(dip={}, mom_off_weak=1),
         '+錯殺最多 2 格(−20/+50/120)': dict(dip=dict(cap=2)),
         '+錯殺最多 2 格(−20/+30/90)': dict(dip=dict(cap=2, tp=0.3, hold=90)),
         '+錯殺最多 1 格(−20/+50/120)': dict(dip=dict(cap=1))}
    for nm in (sys.argv[1:] or V):
        r = run(S, cal, BR, V[nm])
        print(f"{nm:34} 年化 {r['cagr']*100:+6.1f}%  回落 {r['mdd']*100:6.1f}%  最差年 {r['worst']*100:+6.1f}%  正年 {r['pos']}/{r['ny']}  {r['kinds']}", flush=True)
        print('   逐年', r['yrs'], flush=True)
