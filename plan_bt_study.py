"""個股「買賣計畫」通用規則回測:全市場 2016~2026,事件=收盤站上 N 日高(隔天開盤買),出場=停損/停利/最長持有。
看每筆報酬、勝率、獲利因子、持有天數,對照「任意一天買、同樣出場規則」。"""
import sys, os, pickle, collections, json, numpy as np, time
sys.path.insert(0, os.path.dirname(__file__))
from short_bt_study import load_all, roll_max

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
        f5 = np.full(n, 0.0); f5[4:] = np.convolve(e['f'], np.ones(5), 'valid'); t5 = np.full(n, 0.0); t5[4:] = np.convolve(e['t'], np.ones(5), 'valid')
        vs = np.concatenate([[0], np.cumsum(V)]); vol5 = np.full(n, 1.0); vol5[4:] = np.maximum(vs[5:] - vs[:-5], 1); v20p = np.full(n, np.nan); v20p[20:] = (vs[20:-1] - vs[:-21]) / 20
        lo60 = np.full(n, np.nan)
        for i in range(59, n): lo60[i] = L[i-59:i+1].min()
        e['P'] = dict(f5=f5/vol5, t5=t5/vol5, v20p=v20p, lo60=lo60, ma20=ma(20), ma60=ma(60), ma240=ma(240), h20=hprev(20), h60=hprev(60), h120=hprev(120), h250=hprev(250), liq=liq, atr=atr,
                      hi250=roll_max(H, 250))

def ry_at(e, i):
    d = e['d'][i]; y, mo = int(d[:4]), int(d[5:7]); back = 1 if int(d[8:10]) >= 12 else 2
    mm = mo - back; yy = y
    if mm <= 0: mm += 12; yy -= 1
    return (e.get('rev') or {}).get(f'{yy}-{mm:02d}')

def simulate(S, ev, exit_rule, start='2016-01-01', sample_any=False, rng=None, max_gap=None, end=None):
    """ev(e,i)->bool 事件;exit_rule(e,i_entry)->(exit_i, exit_px, why)"""
    trades = []
    for sid, e in S.items():
        d = e['d']; a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']
        i0 = next((k for k, x in enumerate(d) if x >= start), None)
        if i0 is None: continue
        n = n if end is None else min(n, next((k for k, x in enumerate(d) if x >= end), n))
        last_exit = -1
        for i in range(max(i0, 250), n - 2):
            if i <= last_exit: continue
            if not (P['liq'][i] >= 2e4): continue
            if sample_any:
                if rng.random() > 0.01: continue
            elif not ev(e, i): continue
            ei = i + 1; px = O[ei]
            if not px: continue
            if max_gap is not None and px / C[i] - 1 > max_gap: continue
            xi, xp, why = exit_rule(e, ei)
            if xi is None: continue
            if end is not None and d[xi] >= end: continue  # r1156:分段驗證不讀到區間後的出場
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
    if which == 'b5':
        ev250 = EV['站上 250 日高']; base = EX['季線停損/不停利/120日']; tp25 = EX['季線停損/+25%/60日']
        def mk_x(buf=0.0, confirm=1, hard=None, tstop=None, half=None, hold=120):
            def f(e, ei):
                a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']; px = O[ei]; below = 0; sold_half = False; got = 0.0
                for k in range(ei, min(n, ei + hold)):
                    if hard and L[k] <= px * (1 - hard):
                        xp = min(O[k], px * (1 - hard)); return k, (got + xp * 0.5 if sold_half else xp), 'sl'
                    if half and not sold_half and H[k] >= px * (1 + half):
                        sold_half = True; got = max(O[k], px * (1 + half)) * 0.5
                    if tstop and k - ei + 1 == tstop and max(H[ei:k+1]) < px * 1.05: return k, (got + C[k] * 0.5 if sold_half else C[k]), 'time'
                    below = below + 1 if (C[k] < P['ma60'][k] * (1 - buf) and k > ei) else 0
                    if below >= confirm:
                        xi = k + 1 if k + 1 < n else k; xp = O[k+1] if k + 1 < n else C[k]
                        return xi, (got + xp * 0.5 if sold_half else xp), 'ma'
                    if k == ei + hold - 1: return k, (got + C[k] * 0.5 if sold_half else C[k]), 'time'
                return None, None, None
            return f
        stats(simulate(S, ev250, base), '基準:季線停損/不停利/120日')
        stats(simulate(S, ev250, mk_x()), '同上(自寫版,應相同)')
        stats(simulate(S, ev250, mk_x(buf=0.02)), '跌破季線 2% 以上才賣')
        stats(simulate(S, ev250, mk_x(buf=0.03)), '跌破季線 3% 以上才賣')
        stats(simulate(S, ev250, mk_x(confirm=2)), '連 2 天收盤跌破季線才賣')
        stats(simulate(S, ev250, mk_x(confirm=3)), '連 3 天收盤跌破季線才賣')
        stats(simulate(S, ev250, mk_x(hard=0.15)), '季線 + 硬停損 −15%(先到先賣)')
        stats(simulate(S, ev250, mk_x(hard=0.20)), '季線 + 硬停損 −20%')
        stats(simulate(S, ev250, mk_x(hard=0.10)), '季線 + 硬停損 −10%')
        stats(simulate(S, ev250, mk_x(tstop=20)), '季線 + 20 天內沒漲 5% 就出')
        stats(simulate(S, ev250, mk_x(tstop=10)), '季線 + 10 天內沒漲 5% 就出')
        stats(simulate(S, ev250, mk_x(half=0.30)), '季線 + 漲 30% 先賣一半(現行寫法)')
        stats(simulate(S, ev250, mk_x(half=0.20)), '季線 + 漲 20% 先賣一半')
        stats(simulate(S, ev250, mk_x(half=0.50)), '季線 + 漲 50% 先賣一半')
        stats(simulate(S, ev250, mk_x(hold=250)), '季線/不停利/250日')
        stats(simulate(S, ev250, mk_x(hold=60)), '季線/不停利/60日')
        # 加碼:+10% 且收盤在月線上 → 再買一單位(報酬以總投入計)
        def mk_add(th=0.10, hold=120, ma='ma20'):
            def f(e, ei):
                a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']; px = O[ei]; units = [px]; added = False
                for k in range(ei, min(n, ei + hold)):
                    if not added and k > ei and C[k] >= px * (1 + th) and C[k] > P[ma][k] and k + 1 < n and O[k+1]:
                        units.append(O[k+1]); added = True
                    if C[k] < P['ma60'][k] and k > ei:
                        xi = k + 1 if k + 1 < n else k; xp = O[k+1] if k + 1 < n else C[k]
                        # 回傳等效出場價:使 xp_eff/px = 平均每單位報酬
                        return xi, px * np.mean([xp / u for u in units]), ('ma+' if added else 'ma')
                    if k == ei + hold - 1: return k, px * np.mean([C[k] / u for u in units]), 'time'
                return None, None, None
            return f
        for th in (0.05, 0.10, 0.20):
            stats(simulate(S, ev250, mk_add(th)), f'加碼:漲 {int(th*100)}% 且月線上再買一單位(報酬按總投入)')
        # 進場細分
        def days_since_prev_high(e, i):
            H = e['a'][:, 1]; h = e['P']['h250'][i]
            j = i - 1
            while j > i - 250 and H[j] < h: j -= 1
            return i - j
        F = {'首次突破(前高在 ≥60 天前)': lambda e, i: ev250(e, i) and days_since_prev_high(e, i) >= 60,
             '首次突破(前高在 ≥120 天前)': lambda e, i: ev250(e, i) and days_since_prev_high(e, i) >= 120,
             '續創(前高在 20 天內)': lambda e, i: ev250(e, i) and days_since_prev_high(e, i) <= 20,
             '收在當天高點 1% 內': lambda e, i: ev250(e, i) and e['a'][i][3] >= e['a'][i][1] * 0.99,
             '留上影線(收盤低於高點 3%+)': lambda e, i: ev250(e, i) and e['a'][i][3] < e['a'][i][1] * 0.97,
             '突破幅度 <2%(剛過)': lambda e, i: ev250(e, i) and e['a'][i][3] / e['P']['h250'][i] - 1 < 0.02,
             '突破幅度 ≥5%(大過)': lambda e, i: ev250(e, i) and e['a'][i][3] / e['P']['h250'][i] - 1 >= 0.05,
             '站上季線且月線>季線': lambda e, i: ev250(e, i) and e['P']['ma20'][i] > e['P']['ma60'][i],
             '離季線 <10%': lambda e, i: ev250(e, i) and e['a'][i][3] / e['P']['ma60'][i] - 1 < 0.10,
             '離季線 ≥20%(已漲多)': lambda e, i: ev250(e, i) and e['a'][i][3] / e['P']['ma60'][i] - 1 >= 0.20}
        m = S.get('0050')
        if m is not None:
            mdx = {d: k for k, d in enumerate(m['d'])}; mc = m['a'][:, 3]; cs = np.concatenate([[0], np.cumsum(mc)]); m200 = np.full(len(mc), np.nan); m200[199:] = (cs[200:] - cs[:-200]) / 200
            def bull(e, i):
                k = mdx.get(e['d'][i]); return k is not None and not np.isnan(m200[k]) and mc[k] > m200[k]
            F['0050 在 200 日線上(多頭)'] = lambda e, i: ev250(e, i) and bull(e, i)
            F['0050 在 200 日線下(空頭)'] = lambda e, i: ev250(e, i) and not bull(e, i)
        for nm, ef in F.items():
            stats(simulate(S, ef, base), f'{nm} | 季線/不停利'); stats(simulate(S, ef, tp25), f'{nm} | 季線/+25%')
        # 再買回:上一筆 60 天內被季線停損出場,這次再突破
        tr = simulate(S, ev250, base); last = {}; re_, fresh = [], []
        for t in sorted(tr, key=lambda t: (t[0], t[1])):
            sid = t[0]; prev = last.get(sid)
            if prev and prev[1] == 'ma':
                from datetime import date
                dd = (date.fromisoformat(t[1]) - date.fromisoformat(prev[0])).days
                (re_ if dd <= 90 else fresh).append(t)
            else: fresh.append(t)
            last[sid] = (t[1], t[4])
        stats(re_, '再買回(上次被季線洗出 90 天內又突破)'); stats(fresh, '其他')
    if which == 'filt9b':
        # r1180:①驗證 r1179「本股條件」合計分數兩期是否單調;②新因素:融資、本益比/殖利率/淨值比、大戶持股/股東人數、產業強弱
        import collections as CC, glob as GL, gzip as GZ
        CAP = json.load(open('/home/claude/repo2/cap.json'))['c']
        RR = '/home/claude/repo2/archive'
        def load_yearly(sub, keys):
            out = CC.defaultdict(lambda: {k: {} for k in keys})
            for f in GL.glob(f'{RR}/{sub}/tw/*/*.json.gz'):
                j = json.load(GZ.open(f, 'rt'))
                for sid, e in j.items():
                    if sid not in S: continue
                    for k in keys:
                        vs = e.get(k) or []
                        for d, v in zip(e.get('d') or [], vs): out[sid][k][d] = v
            return out
        MG = load_yearly('margin', ['mb']); PE = load_yearly('per', ['pe', 'pb', 'dy'])
        TD = json.load(GZ.open(f'{RR}/tdcc_hist.json.gz', 'rt'))['s']
        print('aux loaded', len(MG), len(PE), len(TD), flush=True)
        # 產業 20 日報酬(等權),每日
        secmap = CC.defaultdict(list)
        for sid, e in S.items(): secmap[e.get('sec') or ''].append(sid)
        SR = CC.defaultdict(dict)   # sec -> date -> mean r20
        MK = {}
        alld = CC.defaultdict(list)
        for sid, e in S.items():
            C = e['a'][:, 3]; sec = e.get('sec') or ''
            for i in range(20, len(C)):
                if not (e['P']['liq'][i] >= 2e4): continue
                alld[(sec, e['d'][i])].append(C[i] / C[i-20] - 1)
        mk = CC.defaultdict(list)
        for (sec, d), L in alld.items():
            if len(L) >= 5: SR[sec][d] = float(np.mean(L))
            mk[d] += L
        MK = {d: float(np.mean(L)) for d, L in mk.items()}
        print('sector strength ready', flush=True)
        def vol_of(e, i): a = e['P']['atr'][i] / e['a'][i][3]; return '低' if a < 0.025 else '中' if a < 0.04 else '高'
        def size_of(e, i, sid):
            c = CAP.get(sid); m = c * 1e8 / 10 * e['a'][i][3] if c else None
            return None if m is None else ('大' if m >= 5e10 else '中' if m >= 1e10 else '小')
        def gx(ma='ma60', conf=2, hold=120, tp=None, sl=None):
            def f(e, ei):
                a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']; px = O[ei]; below = 0
                for k in range(ei, min(n, ei + hold)):
                    if sl and L[k] <= px * (1 - sl): return k, min(O[k], px * (1 - sl)), 'sl'
                    if tp and H[k] >= px * (1 + tp): return k, max(O[k], px * (1 + tp)), 'tp'
                    if ma:
                        below = below + 1 if (C[k] < P[ma][k] and k > ei) else 0
                        if below >= conf: xi = k + 1 if k + 1 < n else k; return xi, (O[k+1] if k + 1 < n else C[k]), 'ma'
                    if k == ei + hold - 1: return k, C[k], 'time'
                return None, None, None
            return f
        def dipk_conf(k):
            def f(e, i):
                H = e['a'][:, 1]; C = e['a'][:, 3]; P = e['P']
                if not (C[i] / P['h60'][i] - 1 <= -k): return False
                if not (C[i] > H[i-1] and C[i-1] <= H[i-2]): return False
                return any(C[j] / P['h60'][j] - 1 <= -k and C[j-1] / P['h60'][j-1] - 1 > -k for j in range(i-10, i))
            return f
        ev250 = EV['站上 250 日高']
        G = {'low': (ev250, gx(ma=None, sl=0.15, tp=0.30, hold=90), lambda v, z: v == '低'),
             'mid': (ev250, gx(), lambda v, z: v == '中'),
             'dip': (dipk_conf(0.25), gx(ma=None, sl=0.20, tp=0.30, hold=90), lambda v, z: v == '高')}
        GN = {'low': '突破・低波動', 'mid': '突破・中波動', 'dip': '跌25%止跌・高波動'}
        def ry_back(e, i, b):
            d = e['d'][i]; y, mo = int(d[:4]), int(d[5:7]); back = (1 if int(d[8:10]) >= 12 else 2) + b
            mm = mo - back; yy = y
            while mm <= 0: mm += 12; yy -= 1
            return (e.get('rev') or {}).get(f'{yy}-{mm:02d}')
        def base_feats(e, i):
            a = e['a']; C = a[:, 3]; V = a[:, 4]; P = e['P']
            r3 = [ry_back(e, i, b) for b in range(3)]
            f20 = e['f'][max(0, i-19):i+1].sum() / max(1, V[max(0, i-19):i+1].sum()); t20 = e['t'][max(0, i-19):i+1].sum() / max(1, V[max(0, i-19):i+1].sum())
            return dict(ry=r3[0], r3=None if any(x is None for x in r3) else all(x > 0 for x in r3), acc=None if r3[0] is None or r3[1] is None else r3[0] > r3[1],
                        f20=f20, t20=t20, c20=C[i] / C[i-20] - 1, dayRet=C[i] / C[i-1] - 1, volR=V[i] / max(1, V[i-20:i].mean()),
                        aboveYear=bool(P['ma240'][i]) and C[i] > P['ma240'][i], ma20gt60=P['ma20'][i] > P['ma60'][i])
        def score(g, x):   # 與前端 stockCondHTML 同一套
            p = m = 0; both = x['f20'] < -0.02 and x['t20'] <= 0
            if g == 'low':
                p += (x['ry'] is not None and x['ry'] > 0.20) + (x['volR'] < 1); m += both + (x['c20'] > 0.20) + (x['dayRet'] > 0.05)
            elif g == 'mid':
                p += (x['f20'] > 0.02) + (x['t20'] > 0.01) + (x['c20'] > 0.20); m += both + (x['volR'] < 1) + (x['dayRet'] > 0.05) + x['ma20gt60']
            else:
                p += (x['f20'] > 0.02) + (x['t20'] > 0.01) + (x['c20'] < -0.10) + (x['dayRet'] > 0.05) + (x['acc'] is True)
                m += x['aboveYear'] + x['ma20gt60'] + (x['r3'] is True)
            return int(p) - int(m)
        def nearest_before(dmap, d, look=40):
            # dmap: date->value,取 d 當天或之前最近一筆
            if d in dmap: return dmap[d]
            return None
        def new_feats(sid, e, i):
            d = e['d'][i]; out = {}
            mb = MG.get(sid, {}).get('mb', {}); d20 = e['d'][i-20]
            if d in mb and d20 in mb and mb[d20] and mb[d20] > 0:
                ch = mb[d] / mb[d20] - 1; out['融資20日增>15%'] = ch > 0.15; out['融資20日減>15%'] = ch < -0.15
            pe = PE.get(sid) or {}
            if pe and d in pe['pe']:
                v = pe['pe'][d]
                if v and v > 0: out['本益比<12'] = v < 12; out['本益比>40'] = v > 40
            if pe and d in pe['dy'] and pe['dy'][d] is not None: out['殖利率>5%'] = pe['dy'][d] > 5
            if pe and d in pe['pb'] and pe['pb'][d]: out['淨值比<1.2'] = pe['pb'][d] < 1.2; out['淨值比>5'] = pe['pb'][d] > 5
            td = TD.get(sid)
            if td:
                ds = td['d']; import bisect
                j = bisect.bisect_right(ds, d) - 1
                if j >= 4:
                    b4 = td.get('b4') or []; pp = td.get('p') or []
                    if len(b4) > j and b4[j] is not None and b4[j-4] is not None:
                        out['大戶(400張)4週增≥1點'] = b4[j] - b4[j-4] >= 1.0; out['大戶4週減≥1點'] = b4[j] - b4[j-4] <= -1.0
                    if len(pp) > j and pp[j] and pp[j-4]:
                        out['股東人數4週減≥3%'] = pp[j] / pp[j-4] - 1 <= -0.03; out['股東人數4週增≥3%'] = pp[j] / pp[j-4] - 1 >= 0.03
            sec = e.get('sec') or ''
            sr = SR.get(sec, {}).get(d); mr = MK.get(d)
            if sr is not None and mr is not None:
                out['產業20日強過大盤5%'] = sr - mr > 0.05; out['產業20日弱於大盤5%'] = sr - mr < -0.05
            return out
        m_ = lambda L: np.mean(L) * 100 if L else float('nan')
        for g, (ev, xf, okt) in G.items():
            SC = {'A': CC.defaultdict(list), 'B': CC.defaultdict(list)}
            NF = CC.defaultdict(lambda: {'A': ([], []), 'B': ([], [])})
            base = {'A': [], 'B': []}
            for pn, a_, b_ in (('A', '2016-01-01', '2021-01-01'), ('B', '2021-01-01', None)):
                for t in simulate(S, ev, xf, start=a_, end=b_):
                    e = S[t[0]]; i = e['d'].index(t[1]) - 1
                    v, z = vol_of(e, i), size_of(e, i, t[0])
                    if z is None or not okt(v, z): continue
                    base[pn].append(t[2])
                    sc = max(-2, min(2, score(g, base_feats(e, i))))
                    SC[pn][sc].append(t[2])
                    for fn, fv in new_feats(t[0], e, i).items(): NF[fn][pn][0 if fv else 1].append(t[2])
            print(f'\n######## {GN[g]}:全部 A {m_(base["A"]):+.2f}%({len(base["A"])}) B {m_(base["B"]):+.2f}%({len(base["B"])}) ########', flush=True)
            print('  ① 本股條件合計分數(≤−2 … ≥+2):')
            for sc in (-2, -1, 0, 1, 2):
                a, b = SC['A'].get(sc, []), SC['B'].get(sc, [])
                print(f'     {sc:+d}: A {m_(a):+6.2f}%({len(a):4d},勝{(np.array(a)>0).mean()*100 if a else 0:3.0f}%) | B {m_(b):+6.2f}%({len(b):4d},勝{(np.array(b)>0).mean()*100 if b else 0:3.0f}%)')
            print('  ② 新因素:')
            for fn, d in sorted(NF.items()):
                (ay, an), (by, bn) = d['A'], d['B']
                if min(len(ay), len(an), len(by), len(bn)) < 30: continue
                da, db = m_(ay) - m_(an), m_(by) - m_(bn)
                flag = '  ✅加分' if da > 0.8 and db > 0.8 else ('  ❌扣分' if da < -0.8 and db < -0.8 else '')
                print(f'     {fn:18} 符合 A {m_(ay):+6.2f}%({len(ay):4d}) B {m_(by):+6.2f}%({len(by):4d}) | 不符合 A {m_(an):+6.2f}% B {m_(bn):+6.2f}% | 差 A {da:+5.2f} B {db:+5.2f}{flag}', flush=True)
    if which == 'filt9':
        # r1179:同一買法、同一類型裡,個股條件(營收、法人、漲幅、量能、位置)能不能再分出好壞?兩期都要成立
        import collections as CC
        CAP = json.load(open('/home/claude/repo2/cap.json'))['c']
        def vol_of(e, i): a = e['P']['atr'][i] / e['a'][i][3]; return '低' if a < 0.025 else '中' if a < 0.04 else '高'
        def size_of(e, i, sid):
            c = CAP.get(sid); m = c * 1e8 / 10 * e['a'][i][3] if c else None
            return None if m is None else ('大' if m >= 5e10 else '中' if m >= 1e10 else '小')
        def gx(ma='ma60', conf=2, hold=120, tp=None, sl=None):
            def f(e, ei):
                a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']; px = O[ei]; below = 0
                for k in range(ei, min(n, ei + hold)):
                    if sl and L[k] <= px * (1 - sl): return k, min(O[k], px * (1 - sl)), 'sl'
                    if tp and H[k] >= px * (1 + tp): return k, max(O[k], px * (1 + tp)), 'tp'
                    if ma:
                        below = below + 1 if (C[k] < P[ma][k] and k > ei) else 0
                        if below >= conf: xi = k + 1 if k + 1 < n else k; return xi, (O[k+1] if k + 1 < n else C[k]), 'ma'
                    if k == ei + hold - 1: return k, C[k], 'time'
                return None, None, None
            return f
        def dipk_conf(k):
            def f(e, i):
                H = e['a'][:, 1]; C = e['a'][:, 3]; P = e['P']
                if not (C[i] / P['h60'][i] - 1 <= -k): return False
                if not (C[i] > H[i-1] and C[i-1] <= H[i-2]): return False
                return any(C[j] / P['h60'][j] - 1 <= -k and C[j-1] / P['h60'][j-1] - 1 > -k for j in range(i-10, i))
            return f
        ev250 = EV['站上 250 日高']
        # 每一組:進場、出場、哪些類型
        G = {
          '突破・低波動(固定−15/+30/90)': (ev250, gx(ma=None, sl=0.15, tp=0.30, hold=90), lambda v, z: v == '低'),
          '突破・中波動(季線連2天)': (ev250, gx(), lambda v, z: v == '中'),
          '突破・高波動中大型(季線連2天)': (ev250, gx(), lambda v, z: v == '高' and z in ('大', '中')),
          '跌25%止跌・高波動(−20/+30/90)': (dipk_conf(0.25), gx(ma=None, sl=0.20, tp=0.30, hold=90), lambda v, z: v == '高'),
        }
        def feats(e, i):
            a = e['a']; C = a[:, 3]; V = a[:, 4]; P = e['P']
            ry = ry_at(e, i)
            # 近 3 個月營收 YoY 都 >0
            def ry_back(b):
                d = e['d'][i]; y, mo = int(d[:4]), int(d[5:7]); back = (1 if int(d[8:10]) >= 12 else 2) + b
                mm = mo - back; yy = y
                while mm <= 0: mm += 12; yy -= 1
                return (e.get('rev') or {}).get(f'{yy}-{mm:02d}')
            r3 = [ry_back(b) for b in range(3)]
            f20 = e['f'][max(0, i-19):i+1].sum() / max(1, V[max(0, i-19):i+1].sum()); t20 = e['t'][max(0, i-19):i+1].sum() / max(1, V[max(0, i-19):i+1].sum())
            return {
              '月營收YoY>0': None if ry is None else ry > 0,
              '月營收YoY>20%': None if ry is None else ry > 0.20,
              '近3月營收YoY都>0': None if any(x is None for x in r3) else all(x > 0 for x in r3),
              '營收加速(本月YoY>前月)': None if r3[0] is None or r3[1] is None else r3[0] > r3[1],
              '外資20日買超': f20 > 0.02, '投信20日買超': t20 > 0.01, '外資投信都賣': f20 < -0.02 and t20 <= 0,
              '前20日已漲>20%': C[i] / C[i-20] - 1 > 0.20, '前20日跌>10%': C[i] / C[i-20] - 1 < -0.10,
              '當天量>2倍均量': V[i] > 2 * V[i-20:i].mean(), '當天量<均量': V[i] < V[i-20:i].mean(),
              '站在年線上': bool(P['ma240'][i]) and C[i] > P['ma240'][i],
              '月線>季線(多頭)': P['ma20'][i] > P['ma60'][i],
              '當天收長紅(>5%)': C[i] / C[i-1] - 1 > 0.05,
            }
        for gn, (ev, xf, okt) in G.items():
            rows = CC.defaultdict(lambda: {'A': ([], []), 'B': ([], [])})
            base = {'A': [], 'B': []}
            for pn, a_, b_ in (('A', '2016-01-01', '2021-01-01'), ('B', '2021-01-01', None)):
                for t in simulate(S, ev, xf, start=a_, end=b_):
                    e = S[t[0]]; i = e['d'].index(t[1]) - 1
                    v, z = vol_of(e, i), size_of(e, i, t[0])
                    if z is None or not okt(v, z): continue
                    base[pn].append(t[2])
                    for fn, fv in feats(e, i).items():
                        if fv is None: continue
                        rows[fn][pn][0 if fv else 1].append(t[2])
            m = lambda L: np.mean(L) * 100 if L else float('nan')
            print(f'\n######## {gn}:全部 A {m(base["A"]):+.2f}%({len(base["A"])}) | B {m(base["B"]):+.2f}%({len(base["B"])}) ########', flush=True)
            for fn, d in rows.items():
                (ay, an), (by, bn) = d['A'], d['B']
                if min(len(ay), len(an), len(by), len(bn)) < 30: continue
                da, db = m(ay) - m(an), m(by) - m(bn)
                flag = '  ✅加分' if da > 0.8 and db > 0.8 else ('  ❌扣分' if da < -0.8 and db < -0.8 else '')
                print(f'  {fn:18} 符合 A {m(ay):+6.2f}%({len(ay):4d}) B {m(by):+6.2f}%({len(by):4d}) | 不符合 A {m(an):+6.2f}% B {m(bn):+6.2f}% | 差 A {da:+5.2f} B {db:+5.2f}{flag}', flush=True)
    if which == 'exit9':
        # r1178:依市值×波動 9 類重驗「賣出」規則;進場:突破(52週新高)、跌 25% 止跌
        import collections as CC
        CAP = json.load(open('/home/claude/repo2/cap.json'))['c']
        def typ(e, i, sid):
            a = e['P']['atr'][i] / e['a'][i][3]; c = CAP.get(sid)
            if not c: return None
            m = c * 1e8 / 10 * e['a'][i][3]
            return ('低波動' if a < 0.025 else '中波動' if a < 0.04 else '高波動') + '・' + ('大型' if m >= 5e10 else '中型' if m >= 1e10 else '小型')
        def gx(ma='ma60', conf=2, hold=120, tp=None, half=None, sl=None):
            def f(e, ei):
                a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']; px = O[ei]; below = 0; got = 0.0; hs = False
                for k in range(ei, min(n, ei + hold)):
                    if sl and L[k] <= px * (1 - sl):
                        xp = min(O[k], px * (1 - sl)); return k, (got + xp * 0.5 if hs else xp), 'sl'
                    if tp and H[k] >= px * (1 + tp):
                        xp = max(O[k], px * (1 + tp)); return k, (got + xp * 0.5 if hs else xp), 'tp'
                    if half and not hs and H[k] >= px * (1 + half): hs = True; got = max(O[k], px * (1 + half)) * 0.5
                    if ma:
                        below = below + 1 if (C[k] < P[ma][k] and k > ei) else 0
                        if below >= conf:
                            xi = k + 1 if k + 1 < n else k; xp = O[k+1] if k + 1 < n else C[k]; return xi, (got + xp * 0.5 if hs else xp), 'ma'
                    if k == ei + hold - 1: return k, (got + C[k] * 0.5 if hs else C[k]), 'time'
                return None, None, None
            return f
        def dipk_conf(k):
            def f(e, i):
                H = e['a'][:, 1]; C = e['a'][:, 3]; P = e['P']
                if not (C[i] / P['h60'][i] - 1 <= -k): return False
                if not (C[i] > H[i-1] and C[i-1] <= H[i-2]): return False
                return any(C[j] / P['h60'][j] - 1 <= -k and C[j-1] / P['h60'][j-1] - 1 > -k for j in range(i-10, i))
            return f
        E = {
          '突破': (EV['站上 250 日高'], {
            '季線連2天(現行)': gx(), '季線連3天': gx(conf=3), '月線連2天': gx(ma='ma20'), '季線連2天+30%先賣半': gx(half=0.30),
            '季線連2天+50%先賣半': gx(half=0.50), '固定+25%/季線': gx(tp=0.25), '季線連2天/250日': gx(hold=250), '−15%/+30%/90日': gx(ma=None, sl=0.15, tp=0.30, hold=90)}),
          '跌25%止跌': (dipk_conf(0.25), {
            '−15%/+20%/60日(現行)': gx(ma=None, sl=0.15, tp=0.20, hold=60), '−15%/+25%/60日': gx(ma=None, sl=0.15, tp=0.25, hold=60),
            '−15%/+30%/90日': gx(ma=None, sl=0.15, tp=0.30, hold=90), '−20%/+30%/90日': gx(ma=None, sl=0.20, tp=0.30, hold=90),
            '−10%/+20%/60日': gx(ma=None, sl=0.10, tp=0.20, hold=60), '−15%/+20%/40日': gx(ma=None, sl=0.15, tp=0.20, hold=40),
            '−15%/月線連2天/90日': gx(ma='ma20', sl=0.15, hold=90), '−15%/+15%先賣半,季線連2天': gx(ma='ma60', sl=0.15, half=0.15, hold=120)})}
        TY = [v + '・' + z for v in ('低波動', '中波動', '高波動') for z in ('大型', '中型', '小型')]
        for en, (ev, XS) in E.items():
            print(f'\n######## 進場:{en} ########', flush=True)
            R = {}
            for xn, xf in XS.items():
                for pn, a_, b_ in (('A', '2016-01-01', '2021-01-01'), ('B', '2021-01-01', None)):
                    tr = simulate(S, ev, xf, start=a_, end=b_); g = CC.defaultdict(list)
                    for t in tr:
                        e = S[t[0]]; i = e['d'].index(t[1]) - 1; ty = typ(e, i, t[0])
                        if ty: g[ty].append(t[2]); g['全部'].append(t[2])
                    R[(xn, pn)] = g
            for ty in TY + ['全部']:
                rows = []
                for xn in XS:
                    a, b = R[(xn, 'A')].get(ty, []), R[(xn, 'B')].get(ty, [])
                    if len(a) < 30 or len(b) < 30: continue
                    pf = lambda L: (np.array(L)[np.array(L) > 0].sum() / max(1e-9, -np.array(L)[np.array(L) < 0].sum()))
                    rows.append(f'   {xn:22} A {np.mean(a)*100:+6.2f}% PF{pf(a):4.2f} 勝{(np.array(a)>0).mean()*100:3.0f}%({len(a)}) | B {np.mean(b)*100:+6.2f}% PF{pf(b):4.2f} 勝{(np.array(b)>0).mean()*100:3.0f}%({len(b)})')
                if rows: print(f'[{ty}]'); print('\n'.join(rows), flush=True)
    if which == 'mcap':
        # r1177:「大型/中小型」改用市值(實收資本額/10 元面額 = 股數,× 當天收盤)而不是成交值;波動 × 市值 3×3 類
        import collections as CC
        CAP = json.load(open('/home/claude/repo2/cap.json' if os.path.exists('/home/claude/repo2/cap.json') else 'cap.json'))['c']
        def mc(e, sid, i): c = CAP.get(sid); return (c * 1e8 / 10) * e['a'][i][3] if c else None   # 元
        def typ(e, i, sid):
            a = e['P']['atr'][i] / e['a'][i][3]; m = mc(e, sid, i)
            if m is None: return None
            v = '低波動' if a < 0.025 else ('中波動' if a < 0.04 else '高波動')
            z = '大型' if m >= 5e10 else ('中型' if m >= 1e10 else '小型')   # ≥500 億 / 100~500 億 / <100 億
            return v + '・' + z
        def mk_x2(hold=120):
            def f(e, ei):
                a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']; below = 0
                for k in range(ei, min(n, ei + hold)):
                    below = below + 1 if (C[k] < P['ma60'][k] and k > ei) else 0
                    if below >= 2:
                        xi = k + 1 if k + 1 < n else k; return xi, (O[k+1] if k + 1 < n else C[k]), 'ma'
                    if k == ei + hold - 1: return k, C[k], 'time'
                return None, None, None
            return f
        def dipk(k): return lambda e, i: e['a'][i][3] / e['P']['h60'][i] - 1 <= -k and e['a'][i-1][3] / e['P']['h60'][i-1] - 1 > -k
        def dipk_conf(k):
            def f(e, i):
                H = e['a'][:, 1]; C = e['a'][:, 3]; P = e['P']
                if not (C[i] / P['h60'][i] - 1 <= -k): return False
                if not (C[i] > H[i-1] and C[i-1] <= H[i-2]): return False
                return any(C[j] / P['h60'][j] - 1 <= -k and C[j-1] / P['h60'][j-1] - 1 > -k for j in range(i-10, i))
            return f
        x1520 = mk_exit(sl=0.15, tp=0.20, hold=60)
        METH = {'突破(52週新高)': (EV['站上 250 日高'], mk_x2()), '錯殺−40%首日': (dipk(0.40), x1520), '跌−25%止跌': (dipk_conf(0.25), x1520), '跌−30%止跌': (dipk_conf(0.30), x1520), '隨機買(−15/+20)': (None, x1520)}
        rng = np.random.default_rng(11)
        res = {}
        for nm, (ev, xf) in METH.items():
            for pn, a_, b_ in (('A', '2016-01-01', '2021-01-01'), ('B', '2021-01-01', None)):
                tr = simulate(S, ev, xf, start=a_, end=b_, sample_any=ev is None, rng=rng)
                g = CC.defaultdict(list)
                for t in tr:
                    e = S[t[0]]; i = e['d'].index(t[1]) - 1; ty = typ(e, i, t[0])
                    if ty: g[ty].append(t[2])
                res[(nm, pn)] = g
            print('done', nm, flush=True)
        TY = [v + '・' + z for v in ('低波動', '中波動', '高波動') for z in ('大型', '中型', '小型')]
        st = lambda L: f"{np.mean(L)*100:+6.2f}%({len(L):4d},勝{(np.array(L)>0).mean()*100:3.0f}%)" if len(L) >= 20 else f"   —   ({len(L):4d})"
        for ty in TY:
            print(f'\n[{ty}]')
            for nm in METH: print(f'  {nm:14} A {st(res[(nm,"A")].get(ty,[]))} | B {st(res[(nm,"B")].get(ty,[]))}')
        # 目前各類股票檔數
        cnt = CC.Counter()
        for sid, e in S.items():
            if e['d'][-1] < '2026-10' or not (e['P']['liq'][-1] >= 2e4): continue
            t = typ(e, len(e['d']) - 1, sid); cnt[t] += 1
        print('\n目前各類檔數:', dict(cnt))
    if which == 'dipt':
        # 依類型找「比較容易等到」的跌深買點:各類型測多個門檻,出場 −15%/+20%/60 日;對照同類型隨機日買同出場
        import collections as CC
        def typ(e, i):
            a = e['P']['atr'][i] / e['a'][i][3]; lq = e['P']['liq'][i]
            v = 0 if a < 0.025 else (1 if a < 0.04 else 2)
            return ('低波動', '中波動', '高波動')[v] + ('・大型' if lq >= 1e5 else '・中小型')
        def dipk(k): return lambda e, i: e['a'][i][3] / e['P']['h60'][i] - 1 <= -k and e['a'][i-1][3] / e['P']['h60'][i-1] - 1 > -k
        def dipk_conf(k):   # 跌到門檻後,第一天收盤站上前一天高點(止跌確認),且仍在門檻下 5% 內
            def f(e, i):
                H = e['a'][:, 1]; C = e['a'][:, 3]; P = e['P']
                if not (C[i] / P['h60'][i] - 1 <= -k): return False
                if not (C[i] > H[i-1] and C[i-1] <= H[i-2]): return False
                # 近 10 天內曾首次跌破門檻
                return any(C[j] / P['h60'][j] - 1 <= -k and C[j-1] / P['h60'][j-1] - 1 > -k for j in range(i-10, i))
            return f
        X = {'−15/+20/60': mk_exit(sl=0.15, tp=0.20, hold=60), '−10/+15/40': mk_exit(sl=0.10, tp=0.15, hold=40)}
        per = (('A', '2016-01-01', '2021-01-01'), ('B', '2021-01-01', None))
        rng = np.random.default_rng(7)
        def run(ev, xf, rand=False):
            out = {}
            for pn, a_, b_ in per:
                tr = simulate(S, ev, xf, start=a_, end=b_, sample_any=rand, rng=rng)
                g = CC.defaultdict(list)
                for t in tr:
                    e = S[t[0]]; i = e['d'].index(t[1]) - 1; g[typ(e, i)].append(t[2])
                out[pn] = g
            return out
        types = ['低波動・大型', '中波動・大型', '高波動・大型', '低波動・中小型', '中波動・中小型', '高波動・中小型']
        nyears = {'A': 5, 'B': 5.8}
        nst = CC.Counter()
        for sid, e in S.items():
            for i in range(250, len(e['d']), 20):
                if e['d'][i] >= '2016-01-01' and e['P']['liq'][i] >= 2e4: nst[typ(e, i)] += 1
        for xn, xf in X.items():
            base = run(None, xf, rand=True)
            print(f'\n===== 出場 {xn} =====')
            for ty in types:
                ba, bb = base['A'].get(ty, []), base['B'].get(ty, [])
                print(f'{ty}: 隨機買 A {np.mean(ba)*100:+.2f}% B {np.mean(bb)*100:+.2f}%')
            for k in (0.15, 0.20, 0.25, 0.30, 0.35, 0.40):
                for cn, ev in ((f'首次跌 −{int(k*100)}%', dipk(k)), (f'跌 −{int(k*100)}% 後止跌確認', dipk_conf(k))):
                    r = run(ev, xf)
                    for ty in types:
                        a, b = r['A'].get(ty, []), r['B'].get(ty, [])
                        if len(a) + len(b) < 60: continue
                        ba, bb = base['A'].get(ty, []), base['B'].get(ty, [])
                        stock_months = nst[ty] / (len(a) + len(b) + 1e-9)   # 每檔平均多少「月」出現一次(粗估)
                        print(f'  {cn:14} {ty:8} A {np.mean(a)*100:+6.2f}%({len(a):4d},勝{(np.array(a)>0).mean()*100:3.0f}%) 贏隨機{(np.mean(a)-np.mean(ba))*100:+5.2f} | B {np.mean(b)*100:+6.2f}%({len(b):4d},勝{(np.array(b)>0).mean()*100:3.0f}%) 贏隨機{(np.mean(b)-np.mean(bb))*100:+5.2f} | 約每檔 {stock_months*20/250:.1f} 年一次', flush=True)
    if which == 'type':
        # 依「股票類型」挑買法:類型 = 波動(20 日 ATR/價 三等分) × 規模(20 日均成交值 ≥1 億 / 以下)
        # 2016~2020 決定每個類型用哪個買法,2021~2026 驗證;對照「全部用同一個買法」
        def mk_x2(hold=120):
            def f(e, ei):
                a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']; below = 0
                for k in range(ei, min(n, ei + hold)):
                    below = below + 1 if (C[k] < P['ma60'][k] and k > ei) else 0
                    if below >= 2:
                        xi = k + 1 if k + 1 < n else k; return xi, (O[k+1] if k + 1 < n else C[k]), 'ma'
                    if k == ei + hold - 1: return k, C[k], 'time'
                return None, None, None
            return f
        def near(e, i, lim=0.10): return e['a'][i][3] / e['P']['hi250'][i] - 1 >= -lim
        up = lambda e, i: e['P']['ma20'][i] > e['P']['ma60'][i] and e['a'][i][3] > e['P']['ma60'][i]
        METH = {
            '52週新高突破': (EV['站上 250 日高'], mk_x2()),
            '近高突破60日高': (lambda e, i: EV['站上 60 日高'](e, i) and near(e, i), mk_x2()),
            '錯殺低接−40%': (lambda e, i: e['a'][i][3] / e['P']['h60'][i] - 1 <= -0.40 and e['a'][i-1][3] / e['P']['h60'][i-1] - 1 > -0.40, mk_exit(sl=0.15, tp=0.20, hold=60)),
            '錯殺低接−30%': (lambda e, i: e['a'][i][3] / e['P']['h60'][i] - 1 <= -0.30 and e['a'][i-1][3] / e['P']['h60'][i-1] - 1 > -0.30, mk_exit(sl=0.15, tp=0.20, hold=60)),
            '多頭回檔到月線': (lambda e, i: up(e, i) and near(e, i, 0.15) and e['a'][i][2] <= e['P']['ma20'][i] and e['a'][i-1][2] > e['P']['ma20'][i-1] and e['a'][i][3] >= e['P']['ma20'][i] * 0.98, mk_x2()),
            '多頭回檔到季線': (lambda e, i: e['P']['ma20'][i] > e['P']['ma60'][i] and e['a'][i][2] <= e['P']['ma60'][i] and e['a'][i-1][2] > e['P']['ma60'][i-1] and e['a'][i][3] >= e['P']['ma60'][i] * 0.98, mk_exit(sl=0.10, tp=0.20, hold=60)),
        }
        def typ(e, i):
            a = e['P']['atr'][i] / e['a'][i][3]; lq = e['P']['liq'][i]
            v = 0 if a < 0.025 else (1 if a < 0.04 else 2)
            return ('低波動', '中波動', '高波動')[v] + ('・大型' if lq >= 1e5 else '・中小型')
        import collections as CC
        R = {}
        for nm, (ev, xf) in METH.items():
            for per, (a_, b_) in (('A', ('2016-01-01', '2021-01-01')), ('B', ('2021-01-01', None))):
                tr = simulate(S, ev, xf, start=a_, end=b_)
                g = CC.defaultdict(list)
                for t in tr:
                    e = S[t[0]]; i = e['d'].index(t[1]) - 1
                    g[typ(e, i)].append(t[2])
                    g['全部'].append(t[2])
                R[(nm, per)] = g
            print('done', nm, flush=True)
        types = ['低波動・大型', '中波動・大型', '高波動・大型', '低波動・中小型', '中波動・中小型', '高波動・中小型', '全部']
        st = lambda L: (np.mean(L) * 100, len(L), (np.array(L) > 0).mean() * 100) if len(L) else (np.nan, 0, np.nan)
        print('\n類型 | 買法 | 2016~2020 每筆/筆數/勝率 | 2021~2026 每筆/筆數/勝率')
        for ty in types:
            for nm in METH:
                a = st(R[(nm, 'A')].get(ty, [])); b = st(R[(nm, 'B')].get(ty, []))
                print(f'{ty:8} {nm:10} A {a[0]:+6.2f}% {a[1]:5d} {a[2]:4.0f}% | B {b[0]:+6.2f}% {b[1]:5d} {b[2]:4.0f}%')
            print()
        # 依 A 期挑每個類型最好的買法(≥100 筆),看 B 期;對照全部用 A 期整體最好的單一買法
        best_all = max(METH, key=lambda m: st(R[(m, 'A')]['全部'])[0] if st(R[(m, 'A')]['全部'])[1] >= 300 else -99)
        tail_B = []; one_B = []
        for ty in types[:-1]:
            cand = [(st(R[(m, 'A')].get(ty, []))[0], m) for m in METH if st(R[(m, 'A')].get(ty, []))[1] >= 100]
            if not cand: continue
            bm = max(cand)[1]
            tb = R[(bm, 'B')].get(ty, []); ob = R[(best_all, 'B')].get(ty, [])
            tail_B += tb; one_B += ob
            print(f'{ty}: A 期挑 {bm} → B {st(tb)[0]:+.2f}%({st(tb)[1]} 筆) | 全部用 {best_all} → B {st(ob)[0]:+.2f}%({st(ob)[1]} 筆)')
        print(f'合計 依類型挑 B 期 {st(tail_B)[0]:+.2f}%({len(tail_B)} 筆) | 全部用 {best_all} {st(one_B)[0]:+.2f}%({len(one_B)} 筆)')
    if which == 'b6':
        ev250 = EV['站上 250 日高']
        def mk_x(buf=0.0, confirm=1, hold=120):
            def f(e, ei):
                a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']; px = O[ei]; below = 0
                for k in range(ei, min(n, ei + hold)):
                    below = below + 1 if (C[k] < P['ma60'][k] * (1 - buf) and k > ei) else 0
                    if below >= confirm:
                        xi = k + 1 if k + 1 < n else k; xp = O[k+1] if k + 1 < n else C[k]; return xi, xp, 'ma'
                    if k == ei + hold - 1: return k, C[k], 'time'
                return None, None, None
            return f
        for nm, x in [('當天跌破就賣', mk_x()), ('連 2 天', mk_x(confirm=2)), ('連 3 天', mk_x(confirm=3)), ('跌破 3%', mk_x(buf=0.03))]:
            tr = simulate(S, ev250, x); r = np.array([t[2] for t in tr]); lo = r[r < 0]
            print(f'{nm:12} 平均 {r.mean()*100:+.2f}%  輸的平均 {lo.mean()*100:+.2f}%  最差 5% {np.percentile(r,5)*100:+.1f}%  最差 1% {np.percentile(r,1)*100:+.1f}%  <−20% 佔 {(r<-0.2).mean()*100:.1f}%  贏的平均 {r[r>0].mean()*100:+.2f}%')
            for a_, b_ in (('2016-01-01', '2021-01-01'), ('2021-01-01', None)):
                t2 = simulate(S, ev250, x, start=a_, end=b_); r2 = np.array([t[2] for t in t2]); print(f'      {a_[:4]}~ 平均 {r2.mean()*100:+.2f}% PF {r2[r2>0].sum()/-r2[r2<0].sum():.2f} 筆 {len(r2)}')
    if which == 'b3':
        ev250 = EV['站上 250 日高']; xo = EX['季線停損/+25%/60日']; xn = EX['季線停損/不停利/120日']
        F3 = {'250日高': ev250,
              '250日高+量>1.5倍': lambda e, i: ev250(e, i) and e['a'][i][4] > 1.5 * e['P']['v20p'][i],
              '250日高+量>2倍': lambda e, i: ev250(e, i) and e['a'][i][4] > 2.0 * e['P']['v20p'][i],
              '250日高+量<1.2倍(無量)': lambda e, i: ev250(e, i) and e['a'][i][4] < 1.2 * e['P']['v20p'][i],
              '250日高+投信5日買超': lambda e, i: ev250(e, i) and e['P']['t5'][i] >= 0.03,
              '250日高+外資5日買超': lambda e, i: ev250(e, i) and e['P']['f5'][i] >= 0.05,
              '250日高+法人都沒買': lambda e, i: ev250(e, i) and e['P']['t5'][i] < 0.03 and e['P']['f5'][i] < 0.05,
              '250日高+月營收YoY>0': lambda e, i: ev250(e, i) and (ry_at(e, i) or -1) > 0,
              '250日高+月營收YoY>20%': lambda e, i: ev250(e, i) and (ry_at(e, i) or -1) > 0.20,
              '250日高+月營收YoY<0': lambda e, i: ev250(e, i) and ry_at(e, i) is not None and ry_at(e, i) <= 0,
              '250日高+當天漲幅<5%': lambda e, i: ev250(e, i) and e['a'][i][3] / e['a'][i-1][3] - 1 < 0.05,
              '250日高+當天漲幅≥5%': lambda e, i: ev250(e, i) and e['a'][i][3] / e['a'][i-1][3] - 1 >= 0.05,
              '250日高+成交值前段(≥1億)': lambda e, i: ev250(e, i) and e['P']['liq'][i] >= 1e5,
              '250日高+小型(<1億)': lambda e, i: ev250(e, i) and e['P']['liq'][i] < 1e5}
        for en, ef in F3.items():
            stats(simulate(S, ef, xo), f'{en} | 季線/+25%'); stats(simulate(S, ef, xn), f'{en} | 季線/不停利')
        stats(simulate(S, ev250, xo, max_gap=0.03), '250日高 | 季線/+25% | 開盤跳空>3%不買')
        stats(simulate(S, ev250, xn, max_gap=0.03), '250日高 | 季線/不停利 | 開盤跳空>3%不買')
        # 錯殺低接
        dip = lambda e, i: e['a'][i][3] / e['P']['h60'][i] - 1 <= -0.30 and e['a'][i-1][3] / e['P']['h60'][i-1] - 1 > -0.30
        for xn2, xf in {'−15%/+20%/60日(現行)': mk_exit(sl=0.15, tp=0.20, hold=60), '−15%/+25%/60日': mk_exit(sl=0.15, tp=0.25, hold=60), '−10%/+20%/60日': mk_exit(sl=0.10, tp=0.20, hold=60),
                        '−15%/+20%/40日': mk_exit(sl=0.15, tp=0.20, hold=40), '−15%/+20%/90日': mk_exit(sl=0.15, tp=0.20, hold=90), '−20%/+30%/90日': mk_exit(sl=0.20, tp=0.30, hold=90),
                        '月線停損/+20%/60日': mk_exit(stop_ma='ma20', tp=0.20, hold=60)}.items():
            stats(simulate(S, dip, xf), f'錯殺(60日高−30%第一天) | {xn2}')
        stats(simulate(S, lambda e, i: dip(e, i) and (ry_at(e, i) or -1) > 0, mk_exit(sl=0.15, tp=0.20, hold=60)), '錯殺+營收YoY>0 | −15%/+20%/60日')
        stats(simulate(S, lambda e, i: dip(e, i) and ry_at(e, i) is not None and ry_at(e, i) <= 0, mk_exit(sl=0.15, tp=0.20, hold=60)), '錯殺+營收YoY≤0 | −15%/+20%/60日')
        stats(simulate(S, lambda e, i: dip(e, i) and e['P']['ma240'][i] and e['a'][i][3] > e['P']['ma240'][i], mk_exit(sl=0.15, tp=0.20, hold=60)), '錯殺+仍在年線上 | −15%/+20%/60日')
        stats(simulate(S, lambda e, i: e['a'][i][3] / e['P']['h60'][i] - 1 <= -0.40 and e['a'][i-1][3] / e['P']['h60'][i-1] - 1 > -0.40, mk_exit(sl=0.15, tp=0.20, hold=60)), '錯殺改 −40% 第一天 | −15%/+20%/60日')
        stats(simulate(S, lambda e, i: e['a'][i][3] / e['P']['h60'][i] - 1 <= -0.20 and e['a'][i-1][3] / e['P']['h60'][i-1] - 1 > -0.20, mk_exit(sl=0.15, tp=0.20, hold=60)), '錯殺改 −20% 第一天 | −15%/+20%/60日')
    if which == 'b4':
        def dipk(k): return lambda e, i: e['a'][i][3] / e['P']['h60'][i] - 1 <= -k and e['a'][i-1][3] / e['P']['h60'][i-1] - 1 > -k
        x = mk_exit(sl=0.15, tp=0.20, hold=60)
        for k in (0.25, 0.30, 0.35, 0.40, 0.45, 0.50):
            stats(simulate(S, dipk(k), x), f'錯殺 −{int(k*100)}% 第一天 | −15%/+20%/60日')
        for k in (0.35, 0.40):
            stats(simulate(S, dipk(k), x, start='2016-01-01', end='2021-01-01'), f'錯殺 −{int(k*100)}% | 2016~2020')
            stats(simulate(S, dipk(k), x, start='2021-01-01'), f'錯殺 −{int(k*100)}% | 2021~2026')
            stats(simulate(S, dipk(k), mk_exit(sl=0.15, tp=0.20, hold=40)), f'錯殺 −{int(k*100)}% | −15%/+20%/40日')
            stats(simulate(S, dipk(k), mk_exit(sl=0.15, tp=0.30, hold=60)), f'錯殺 −{int(k*100)}% | −15%/+30%/60日')
            stats(simulate(S, dipk(k), mk_exit(sl=0.20, tp=0.30, hold=90)), f'錯殺 −{int(k*100)}% | −20%/+30%/90日')
            stats(simulate(S, lambda e, i, f=dipk(k): f(e, i) and (ry_at(e, i) or -1) > 0, x), f'錯殺 −{int(k*100)}% +營收YoY>0 | −15%/+20%/60日')
            stats(simulate(S, lambda e, i, f=dipk(k): f(e, i) and e['P']['liq'][i] >= 3e4, x), f'錯殺 −{int(k*100)}% +日成交值≥3000萬 | −15%/+20%/60日')
            stats(simulate(S, lambda e, i, f=dipk(k): f(e, i) and e['P']['liq'][i] < 3e4, x), f'錯殺 −{int(k*100)}% +日成交值<3000萬 | −15%/+20%/60日')
            stats(simulate(S, dipk(k), x, max_gap=0.0), f'錯殺 −{int(k*100)}% | 開高不買')
        # 年度分布 −40%
        tr = simulate(S, dipk(0.40), x)
        import collections as C3
        yy = C3.defaultdict(list)
        for t in tr: yy[t[1][:4]].append(t[2])
        for y in sorted(yy): print(f'   {y}: 筆 {len(yy[y]):4d} 平均 {np.mean(yy[y])*100:+.1f}% 勝率 {np.mean(np.array(yy[y])>0)*100:.0f}%')
    if which == 'own2':
        import collections as C2
        for k in (0.30, 0.40):
            dp = lambda e, i, k=k: e['a'][i][3] / e['P']['h60'][i] - 1 <= -k and e['a'][i-1][3] / e['P']['h60'][i-1] - 1 > -k
            x = mk_exit(sl=0.15, tp=0.20, hold=60)
            tr_a = simulate(S, dp, x, start='2013-01-01', end='2020-01-01'); tr_b = simulate(S, dp, x, start='2020-01-01')
            pa = C2.defaultdict(list)
            for t in tr_a: pa[t[0]].append(t[2])
            good = {sid for sid, v in pa.items() if len(v) >= 3 and np.mean(v) > 0.03}; bad = {sid for sid, v in pa.items() if len(v) >= 3 and np.mean(v) <= 0}
            stats([t for t in tr_b if t[0] in good], f'錯殺−{int(k*100)}% 前期(2013~19)自己有效 → 2020~26')
            stats([t for t in tr_b if t[0] in bad], f'錯殺−{int(k*100)}% 前期自己無效 → 2020~26')
            stats([t for t in tr_b if t[0] not in good and t[0] not in bad], f'錯殺−{int(k*100)}% 前期樣本少 → 2020~26')
    if which == 'own':
        # 每檔自己的歷史能不能預測:2012~2018 的「站上 250 日高」勝率/平均 → 2019~2026
        ev250 = EV['站上 250 日高']; xo = EX['季線停損/+25%/60日']
        tr_a = simulate(S, ev250, xo, start='2013-01-01', end='2019-01-01'); tr_b = simulate(S, ev250, xo, start='2019-01-01')
        import collections as C2
        pa = C2.defaultdict(list)
        for t in tr_a: pa[t[0]].append(t[2])
        good = {sid for sid, v in pa.items() if len(v) >= 5 and np.mean(v) > 0.02}; bad = {sid for sid, v in pa.items() if len(v) >= 5 and np.mean(v) <= 0}
        stats([t for t in tr_b if t[0] in good], '前期(2013~18)自己突破有效的股票 → 2019~26')
        stats([t for t in tr_b if t[0] in bad], '前期自己突破無效的股票 → 2019~26')
        stats([t for t in tr_b if t[0] not in good and t[0] not in bad], '前期樣本少/中性 → 2019~26')
        stats(tr_b, '全部 2019~26')
    if which == 'exit':
        EX2 = dict(EX); EX2.update({'季線停損/+20%/60日': mk_exit(stop_ma='ma60', tp=0.20, hold=60), '季線停損/+30%/60日': mk_exit(stop_ma='ma60', tp=0.30, hold=60),
            '季線停損/+25%/120日': mk_exit(stop_ma='ma60', tp=0.25, hold=120), '−10%/+20%/60日': mk_exit(sl=0.10, tp=0.20, hold=60), '−20%/+30%/90日': mk_exit(sl=0.20, tp=0.30, hold=90),
            '月線停損/+25%/60日': mk_exit(stop_ma='ma20', tp=0.25, hold=60), '2ATR/+20%/60日': mk_exit(atr_sl=2, tp=0.20, hold=60), '季線停損/不停利/250日': mk_exit(stop_ma='ma60', tp=None, hold=250)})
        for en in ('站上 250 日高', '站上 60 日高+離52週高≤10%'):
            ef = EV[en]
            for xn, xf in EX2.items(): stats(simulate(S, ef, xf), f'{en} | {xn}')
