"""個股「買賣計畫」通用規則回測:全市場 2016~2026,事件=收盤站上 N 日高(隔天開盤買),出場=停損/停利/最長持有。
看每筆報酬、勝率、獲利因子、持有天數,對照「任意一天買、同樣出場規則」。"""
import sys, os, pickle, collections, numpy as np, time
sys.path.insert(0, os.path.dirname(__file__))
from short_bt import load_all, roll_max

def prep(S):
    for sid, e in S.items():
        a = e['a']; O, H, L, C, V = a.T; n = len(C)
        cs = np.concatenate([[0], np.cumsum(C)])
        def ma(w):
            m = np.full(n, np.nan); m[w-1:] = (cs[w:] - cs[:-w]) / w; return m
        def hprev(w):
            h = np.full(n, np.nan); h[w:] = roll_max(H, w)[w-1:-1]; return h
        cv = np.concatenate([[0], np.cumsum(C*V)]); liq = np.full(n, np.nan); liq[19:] = (cv[20:] - cv[:-20]) / 20
        tr = np.maximum(H - L, np.maximum(abs(H - np.roll(C, 1)), abs(L - np.roll(C, 1)))); tr[0] = H[0]-L[0]
        ctr = np.concatenate([[0], np.cumsum(tr)]); atr = np.full(n, np.nan); atr[19:] = (ctr[20:] - ctr[:-20]) / 20
        e['P'] = dict(ma20=ma(20), ma60=ma(60), ma240=ma(240), h20=hprev(20), h60=hprev(60), h120=hprev(120), h250=hprev(250), liq=liq, atr=atr,
                      hi250=roll_max(H, 250))

def simulate(S, ev, exit_rule, start='2016-01-01', sample_any=False, rng=None):
    """ev(e,i)->bool 事件;exit_rule(e,i_entry)->(exit_i, exit_px, why)"""
    trades = []
    for sid, e in S.items():
        d = e['d']; a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']
        i0 = next((k for k, x in enumerate(d) if x >= start), None)
        if i0 is None: continue
        last_exit = -1
        for i in range(max(i0, 250), n - 2):
            if i <= last_exit: continue
            if not (P['liq'][i] >= 2e4): continue
            if sample_any:
                if rng.random() > 0.01: continue
            elif not ev(e, i): continue
            ei = i + 1; px = O[ei]
            if not px: continue
            xi, xp, why = exit_rule(e, ei)
            if xi is None: continue
            r = xp / px - 1 - 0.006
            trades.append((sid, d[ei], r, xi - ei + 1, why))
            last_exit = xi
    return trades

def mk_exit(sl=None, tp=None, hold=60, stop_ma=None, atr_sl=None):
    def f(e, ei):
        a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']; px = O[ei]
        slp = px * (1 - sl) if sl else None
        if atr_sl: slp = px - atr_sl * P['atr'][ei-1]
        tpp = px * (1 + tp) if tp else None
        for k in range(ei, min(n, ei + hold)):
            if slp and L[k] <= slp: return k, min(O[k], slp), 'sl'
            if tpp and H[k] >= tpp: return k, max(O[k], tpp), 'tp'
            if stop_ma and C[k] < P[stop_ma][k] and k > ei: return k + 1 if k + 1 < n else k, O[k+1] if k + 1 < n else C[k], 'ma'
            if k == ei + hold - 1: return k, C[k], 'time'
        return None, None, None
    return f

def stats(tr, name):
    if not tr: print(f'{name:40} 無交易'); return
    r = np.array([t[2] for t in tr]); hd = np.mean([t[3] for t in tr])
    pf = r[r > 0].sum() / max(1e-9, -r[r < 0].sum())
    yrs = collections.defaultdict(list)
    for t in tr: yrs[t[1][:4]].append(t[2])
    ypos = sum(1 for v in yrs.values() if np.mean(v) > 0)
    print(f'{name:40} 筆 {len(tr):6}  平均 {r.mean()*100:+5.2f}%  中位 {np.median(r)*100:+5.2f}%  勝率 {(r>0).mean()*100:4.0f}%  獲利因子 {pf:4.2f}  持有 {hd:4.1f} 天  正年 {ypos}/{len(yrs)}', flush=True)

if __name__ == '__main__':
    t0 = time.time(); S = load_all(); prep(S); print('ready', f'{time.time()-t0:.0f}s')
    rng = np.random.default_rng(1)
    def near(e, i, lim=0.10): return e['a'][i][3] / e['P']['hi250'][i] - 1 >= -lim
    EV = {
        '站上 60 日高': lambda e, i: e['a'][i][3] > e['P']['h60'][i] and e['a'][i-1][3] <= e['P']['h60'][i-1],
        '站上 120 日高': lambda e, i: e['a'][i][3] > e['P']['h120'][i] and e['a'][i-1][3] <= e['P']['h120'][i-1],
        '站上 250 日高': lambda e, i: e['a'][i][3] > e['P']['h250'][i] and e['a'][i-1][3] <= e['P']['h250'][i-1],
        '站上 60 日高+量>20日均1.5倍': lambda e, i: e['a'][i][3] > e['P']['h60'][i] and e['a'][i-1][3] <= e['P']['h60'][i-1] and e['a'][i][4] > 1.5 * np.mean(e['a'][i-20:i, 4]),
        '站上 60 日高+多頭排列': lambda e, i: e['a'][i][3] > e['P']['h60'][i] and e['a'][i-1][3] <= e['P']['h60'][i-1] and e['P']['ma20'][i] > e['P']['ma60'][i],
        '站上 60 日高+離52週高≤10%': lambda e, i: e['a'][i][3] > e['P']['h60'][i] and e['a'][i-1][3] <= e['P']['h60'][i-1] and near(e, i),
        '站回季線(前一日在季線下)': lambda e, i: e['a'][i][3] > e['P']['ma60'][i] and e['a'][i-1][3] <= e['P']['ma60'][i-1],
        '站回月線+季線上': lambda e, i: e['a'][i][3] > e['P']['ma20'][i] and e['a'][i-1][3] <= e['P']['ma20'][i-1] and e['a'][i][3] > e['P']['ma60'][i],
        '回測季線不破(收盤距季線<2%且在上)': lambda e, i: 0 <= e['a'][i][3] / e['P']['ma60'][i] - 1 < 0.02 and e['P']['ma20'][i] > e['P']['ma60'][i],
    }
    EX = {
        '季線停損/+25%/60日': mk_exit(stop_ma='ma60', tp=0.25, hold=60),
        '−10%/+25%/60日': mk_exit(sl=0.10, tp=0.25, hold=60),
        '−15%/+25%/60日': mk_exit(sl=0.15, tp=0.25, hold=60),
        '−15%/+20%/40日': mk_exit(sl=0.15, tp=0.20, hold=40),
        '3ATR/+25%/60日': mk_exit(atr_sl=3, tp=0.25, hold=60),
        '季線停損/不停利/120日': mk_exit(stop_ma='ma60', tp=None, hold=120),
        '月線停損/+15%/30日': mk_exit(stop_ma='ma20', tp=0.15, hold=30),
    }
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if which in ('all', 'any'):
        for xn, xf in EX.items():
            stats(simulate(S, None, xf, sample_any=True, rng=rng), f'任意日買 | {xn}')
    if which in ('all', 'ev'):
        for en, ef in EV.items():
            for xn in ('季線停損/+25%/60日', '−15%/+25%/60日'):
                stats(simulate(S, ef, EX[xn]), f'{en} | {xn}')
    if which == 'pos':
        far = lambda e, i: e['a'][i][3] / e['P']['hi250'][i] - 1 < -0.20
        mid = lambda e, i: -0.20 <= e['a'][i][3] / e['P']['hi250'][i] - 1 < -0.10
        EV3 = {'60日高・低位置(離高>20%)': lambda e, i: EV['站上 60 日高'](e, i) and far(e, i), '60日高・中間(10~20%)': lambda e, i: EV['站上 60 日高'](e, i) and mid(e, i),
               '120日高・低位置': lambda e, i: EV['站上 120 日高'](e, i) and far(e, i), '120日高・中間': lambda e, i: EV['站上 120 日高'](e, i) and mid(e, i),
               '120日高・近高(≤10%)': lambda e, i: EV['站上 120 日高'](e, i) and near(e, i)}
        for en, ef in EV3.items():
            for xn in ('季線停損/+25%/60日', '季線停損/不停利/120日'): stats(simulate(S, ef, EX[xn]), f'{en} | {xn}')
    if which == 'exit':
        EX2 = dict(EX); EX2.update({'季線停損/+20%/60日': mk_exit(stop_ma='ma60', tp=0.20, hold=60), '季線停損/+30%/60日': mk_exit(stop_ma='ma60', tp=0.30, hold=60),
            '季線停損/+25%/120日': mk_exit(stop_ma='ma60', tp=0.25, hold=120), '−10%/+20%/60日': mk_exit(sl=0.10, tp=0.20, hold=60), '−20%/+30%/90日': mk_exit(sl=0.20, tp=0.30, hold=90),
            '月線停損/+25%/60日': mk_exit(stop_ma='ma20', tp=0.25, hold=60), '2ATR/+20%/60日': mk_exit(atr_sl=2, tp=0.20, hold=60), '季線停損/不停利/250日': mk_exit(stop_ma='ma60', tp=None, hold=250)})
        for en in ('站上 250 日高', '站上 60 日高+離52週高≤10%'):
            ef = EV[en]
            for xn, xf in EX2.items(): stats(simulate(S, ef, xf), f'{en} | {xn}')
