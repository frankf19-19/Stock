"""個股「買賣計畫」通用規則回測:全市場 2016~2026,事件=收盤站上 N 日高(隔天開盤買),出場=停損/停利/最長持有。
看每筆報酬、勝率、獲利因子、持有天數,對照「任意一天買、同樣出場規則」。"""
import sys, os, pickle, collections, numpy as np, time
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
