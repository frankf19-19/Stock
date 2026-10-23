"""台股短期清單(近 52 週高 × 強勢訊號)回測器:重現 aip3.tw_short_candidates,測各種改法。
用 archive/k/tw(2012~2026 日 K)、archive/inst/tw(法人)、archive/adj_tw(還原因子)。
每週最後交易日收盤選 5 檔(同產業最多 2),下個交易日開盤買,最多 15 日,tp +20% / sl −15%(盤中觸及以該價出場;跳空以開盤)。"""
import json, gzip, os, sys, glob, math, collections, pickle, time
import numpy as np
R = '/home/claude/repo2'
CACHE = '/tmp/claude-0/-home-claude/ff72e86a-413d-5175-a594-8b5d63886f08/scratchpad/short_bt_cache.pkl'

def load_all():
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, 'rb'))
    K = collections.defaultdict(lambda: ([], []))
    for y in sorted(os.listdir(f'{R}/archive/k/tw')):
        for f in glob.glob(f'{R}/archive/k/tw/{y}/*.json.gz'):
            j = json.load(gzip.open(f, 'rt'))
            for sid, e in j.items():
                if not (e.get('d') and e.get('o')): continue
                K[sid][0].extend(e['d']); K[sid][1].extend(e['o'])
    I = collections.defaultdict(lambda: ([], [], []))
    for y in sorted(os.listdir(f'{R}/archive/inst/tw')):
        for f in glob.glob(f'{R}/archive/inst/tw/{y}/*.json.gz'):
            j = json.load(gzip.open(f, 'rt'))
            for sid, e in j.items():
                if not e.get('d'): continue
                I[sid][0].extend(e['d']); I[sid][1].extend(e.get('f') or [0]*len(e['d'])); I[sid][2].extend(e.get('t') or [0]*len(e['d']))
    adj = (json.load(gzip.open(f'{R}/archive/adj_tw.json.gz', 'rt')).get('s') or {})
    D = json.load(open(f'{R}/data.json'))
    sec = {s['id']: s.get('sector') or '' for s in D['stocks'] if s.get('market') == 'TW'}
    etf = {s['id'] for s in D['stocks'] if s.get('etf')}
    out = {}
    for sid, (d, o) in K.items():
        if sid in etf or not sid.isdigit() or len(sid) != 4: continue
        idx = sorted(range(len(d)), key=lambda i: d[i]); d = [d[i] for i in idx]; o = [o[i] for i in idx]
        # dedupe dates
        dd, oo = [], []
        for x, y in zip(d, o):
            if dd and dd[-1] == x: oo[-1] = y; continue
            if not y or len(y) < 5 or not y[3]: continue
            dd.append(x); oo.append(y)
        if len(dd) < 300: continue
        a = np.array(oo, dtype=float)  # o,h,l,c,v
        # adjust
        fa = np.ones(len(dd))
        for ex, f in sorted(adj.get(sid) or []):
            m = np.array([x < ex for x in dd]); fa[m] *= f
        a[:, :4] *= fa[:, None]
        di, fi, ti = I.get(sid, ([], [], []))
        mp = {x: (fi[k], ti[k]) for k, x in enumerate(di)}
        f_ = np.array([mp.get(x, (0, 0))[0] for x in dd], dtype=float); t_ = np.array([mp.get(x, (0, 0))[1] for x in dd], dtype=float)
        out[sid] = dict(d=dd, a=a, f=f_, t=t_, sec=sec.get(sid, ''))
    pickle.dump(out, open(CACHE, 'wb'))
    return out

def rsi14(C):
    n = len(C); r = np.full(n, 50.0); ag = al = None
    for j in range(1, n):
        d1 = C[j] - C[j-1]; gg = max(d1, 0); ll = max(-d1, 0)
        if ag is None: ag, al = gg, ll
        else: ag += (gg - ag) / 14; al += (ll - al) / 14
        r[j] = 100 - 100 / (1 + ag / al) if al else 100
    return r

def kd_k(C, H, L):
    n = len(C); K = np.full(n, 50.0); kv = 50.0
    for j in range(8, n):
        lo9 = L[j-8:j+1].min(); hi9 = H[j-8:j+1].max(); rsv = (C[j]-lo9)/(hi9-lo9)*100 if hi9 > lo9 else 50
        kv += (rsv - kv) / 3; K[j] = kv
    return K

def roll_max(x, w):
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        out[i] = x[max(0, i-w+1):i+1].max()
    return out

def features(S):
    """每檔預算指標(每日)"""
    for sid, e in S.items():
        a = e['a']; O, H, L, C, V = a.T; n = len(C)
        cs = np.concatenate([[0], np.cumsum(C*V)]); vs = np.concatenate([[0], np.cumsum(V)])
        liq = np.full(n, np.nan); liq[19:] = (cs[20:] - cs[:-20]) / 20
        hi250 = roll_max(H, 250); phi = np.full(n, np.nan); phi[1:] = roll_max(H, 250)[:-1]
        h20p = np.full(n, np.nan); h20p[20:] = roll_max(H, 20)[19:-1]
        h55p = np.full(n, np.nan); h55p[55:] = roll_max(H, 55)[54:-1]
        v5 = np.full(n, np.nan); v5[4:] = (vs[5:] - vs[:-5]) / 5
        v20b = np.full(n, np.nan); v20b[24:] = (vs[21:-4] - vs[1:-24]) / 20 if n > 25 else np.nan
        v20p = np.full(n, np.nan); v20p[20:] = (vs[20:-1] - vs[:-21]) / 20
        ma20 = np.full(n, np.nan); ma20[19:] = (np.concatenate([[0], np.cumsum(C)])[20:] - np.concatenate([[0], np.cumsum(C)])[:-20]) / 20
        ma60 = np.full(n, np.nan); ma60[59:] = (np.concatenate([[0], np.cumsum(C)])[60:] - np.concatenate([[0], np.cumsum(C)])[:-60]) / 60
        rs = rsi14(C); kk = kd_k(C, H, L)
        kd3 = np.zeros(n, bool); kd3[2:] = (kk[2:] >= 80) & (kk[1:-1] >= 80) & (kk[:-2] >= 80)
        sign = np.sign(np.diff(C, prepend=C[0])); obv = np.cumsum(sign * V); obvHi = obv >= roll_max(obv, 60)
        t5 = np.full(n, 0.0); t5[4:] = np.convolve(e['t'], np.ones(5), 'valid'); f5 = np.full(n, 0.0); f5[4:] = np.convolve(e['f'], np.ones(5), 'valid')
        vol5 = np.full(n, 1.0); vol5[4:] = np.maximum(vs[5:] - vs[:-5], 1)
        e['F'] = dict(liq=liq, hi250=hi250, phi=phi, h20p=h20p, h55p=h55p, v5=v5, v20b=v20b, v20p=v20p, ma20=ma20, ma60=ma60, rsi=rs, kd3=kd3,
                      obvHi=obvHi, tb=t5/vol5, fb=f5/vol5)

def score_day(e, i, min_i=130):
    if i < min_i: return None
    a = e['a']; O, H, L, C, V = a.T; F = e['F']
    liq = F['liq'][i]
    if not (liq >= 2e4): return None
    dh = C[i] / F['hi250'][i] - 1
    if dh < -0.10: return None
    new52 = (C[i] > F['phi'][i]) and i >= 200
    brk20 = C[i] > F['h20p'][i] and F['v5'][i] > F['v20b'][i]
    brk55 = C[i] > F['h55p'][i]
    big = (V[i] / max(F['v20p'][i], 1) >= 2) and (C[i] / C[i-1] - 1 >= 0.03)
    bull = C[i] > F['ma20'][i] > F['ma60'][i]
    tb, fb = F['tb'][i], F['fb'][i]
    sc = new52*2 + brk20 + brk55 + (F['rsi'][i] >= 70) + F['kd3'][i] + big + F['obvHi'][i] + (tb >= 0.03)*2 + (fb >= 0.05) + bull
    if sc < 4: return None
    return dict(sc=int(sc), tb=tb, r5=C[i]/C[i-5]-1, dh=dh, new52=new52, bull=bull, liq=liq)

def run(S, cal, mkt_ok, variant):
    """cal: 全部交易日(升冪) ; mkt_ok[d]: 大盤濾網是否允許進場 ; variant: dict 參數"""
    K = variant.get('K', 5); hold_max = variant.get('hold', 15); tp = variant.get('tp', 0.20); sl = variant.get('sl', 0.15)
    sec_cap = variant.get('sec_cap', 2); filt = variant.get('filt', 'none'); min_sc = variant.get('min_sc', 4)
    pos_scale = variant.get('bear_scale', 1.0)
    # week-last days
    import datetime as dt
    wl = set()
    for k, d in enumerate(cal):
        nxt = cal[k+1] if k+1 < len(cal) else None
        if nxt is None or dt.date.fromisoformat(nxt).isocalendar()[1] != dt.date.fromisoformat(d).isocalendar()[1]: wl.add(d)
    # index maps
    idx = {sid: {d: k for k, d in enumerate(e['d'])} for sid, e in S.items()}
    trades = []; open_pos = []  # (sid, entry_i, entry_px, sec, size)
    daily = collections.defaultdict(float)  # date -> pnl weighted
    for di, d in enumerate(cal):
        # manage positions
        still = []
        for p in open_pos:
            sid = p['sid']; e = S[sid]; k = idx[sid].get(d)
            if k is None: still.append(p); continue
            O, H, L, C, V = e['a'][k]
            n = k - p['ei'] + 1
            ex = None
            p['hi'] = max(p.get('hi', p['px']), H)
            trail = variant.get('trail'); be = variant.get('be')
            sl_eff = p['px'] * (1 - sl) if sl else None
            if be and p['hi'] >= p['px'] * (1 + be): sl_eff = max(sl_eff or 0, p['px'] * 1.002)
            if trail and p['hi'] >= p['px'] * (1 + variant.get('trail_arm', 0.08)): sl_eff = max(sl_eff or 0, p['hi'] * (1 - trail))
            if sl_eff and L <= sl_eff: ex = min(O, sl_eff); why = 'sl'
            elif tp and H >= p['px'] * (1 + tp): ex = max(O, p['px'] * (1 + tp)); why = 'tp'
            elif n >= hold_max: ex = C; why = 'time'
            if ex:
                r = ex / p['px'] - 1 - 0.006   # 來回成本 0.6%
                trades.append(dict(sid=sid, d0=e['d'][p['ei']], d1=d, r=r, why=why, size=p['size'], year=d[:4]))
                daily[d] += r * p['size']
            else: still.append(p)
        open_pos = still
        # weekly selection
        if d in wl or (variant.get('daily') and len(open_pos) < K):
            held = {p['sid'] for p in open_pos}; secs = collections.Counter(p['sec'] for p in open_pos)
            cands = []
            for sid, e in S.items():
                if sid in held: continue
                k = idx[sid].get(d)
                if k is None: continue
                s = score_day(e, k)
                if not s or s['sc'] < min_sc: continue
                if filt == 'new52' and not s['new52']: continue
                if filt == 'bull' and not s['bull']: continue
                if filt == 'tb' and not (s['tb'] >= 0.03): continue
                s['sid'] = sid; cands.append(s)
            cands.sort(key=lambda x: (-x['sc'], -x['tb'], x['r5']))
            room = K - len(open_pos)
            scale = 1.0 if mkt_ok.get(d, True) else pos_scale
            if scale <= 0: room = 0
            for c in cands:
                if room <= 0: break
                sec = S[c['sid']]['sec']
                if secs[sec] >= sec_cap: continue
                # buy next trading day open
                e = S[c['sid']]; k = idx[c['sid']][d]
                if k + 1 >= len(e['d']): continue
                open_pos.append(dict(sid=c['sid'], ei=k+1, px=e['a'][k+1][0], sec=sec, size=scale / K)); secs[sec] += 1; room -= 1
    # equity: per-trade pnl, position size = scale/K of equity (approx: daily compounding on realized)
    eq = 1.0; curve = []; peak = 1.0; mdd = 0.0; yr = collections.defaultdict(float)
    for d in cal:
        eq *= (1 + daily.get(d, 0.0)); curve.append(eq); peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
    for t in trades: yr[t['year']] += t['r'] * t['size']
    yrs = (len(cal) / 245)
    cagr = eq ** (1 / yrs) - 1
    wins = sum(1 for t in trades if t['r'] > 0)
    return dict(cagr=cagr, mdd=mdd, n=len(trades), win=wins / max(1, len(trades)), avg=float(np.mean([t['r'] for t in trades])) if trades else 0,
                worst=min(yr.values()) if yr else 0, yrs={k: round(v*100, 1) for k, v in sorted(yr.items())}, pos_years=sum(1 for v in yr.values() if v > 0), ny=len(yr))

if __name__ == '__main__':
    t0 = time.time()
    S = load_all(); print('stocks', len(S), f'{time.time()-t0:.0f}s')
    features(S); print('features', f'{time.time()-t0:.0f}s')
    cal = sorted(set(d for e in S.values() for d in e['d']))
    cal = [d for d in cal if d >= '2016-01-01']
    # market filter: 0050 vs MA200
    e50 = S.get('0050')
    mkt = {}
    if e50 is None:
        import gzip as gz
        o50 = collections.defaultdict(list); d50 = []
        for y in sorted(os.listdir(f'{R}/archive/k/tw')):
            f = f'{R}/archive/k/tw/{y}/005.json.gz'
            if os.path.exists(f):
                j = json.load(gz.open(f, 'rt')); e = j.get('0050')
                if e: d50 += e['d']; o50['o'] += e['o']
        C = np.array([x[3] for x in o50['o']], float); ma = np.full(len(C), np.nan)
        cs = np.concatenate([[0], np.cumsum(C)]); ma[199:] = (cs[200:] - cs[:-200]) / 200
        for k, d in enumerate(d50): mkt[d] = bool(C[k] >= ma[k]) if not np.isnan(ma[k]) else True
    variants = {
        'baseline(tp20/sl15,15d)': dict(),
        '空頭不進場(0050<MA200)': dict(bear_scale=0.0),
        '空頭半部位': dict(bear_scale=0.5),
        '只要創52週新高': dict(filt='new52'),
        '只要均線多頭': dict(filt='bull'),
        '只要投信5日買超': dict(filt='tb'),
        '門檻 sc≥5': dict(min_sc=5),
        '門檻 sc≥6': dict(min_sc=6),
        '持 10 日': dict(hold=10),
        '持 20 日': dict(hold=20),
        'tp15/sl10': dict(tp=0.15, sl=0.10),
        'tp25/sl15': dict(tp=0.25, sl=0.15),
        '不停利 sl15': dict(tp=0, sl=0.15),
        '同產業上限 1': dict(sec_cap=1),
        '8 檔': dict(K=8),
        '空位每天補(不等週末)': dict(daily=1),
        '每天補+sc≥6': dict(daily=1, min_sc=6),
        '漲8%後停損移到成本': dict(be=0.08),
        '漲8%後移動停損8%': dict(trail=0.08),
        '漲10%後移動停損6%': dict(trail=0.06, trail_arm=0.10),
        '不停利+漲10%移動停損8%': dict(tp=0, trail=0.08, trail_arm=0.10),
        '持20日+漲8%移動停損8%': dict(hold=20, trail=0.08),
    }
    sel = sys.argv[1:] or list(variants)
    for name in sel:
        v = variants[name]; r = run(S, cal, mkt, v)
        print(f"{name:28} 年化 {r['cagr']*100:+6.1f}%  回落 {r['mdd']*100:6.1f}%  筆數 {r['n']:5}  勝率 {r['win']*100:4.0f}%  平均 {r['avg']*100:+5.2f}%  最差年 {r['worst']*100:+6.1f}%  正年 {r['pos_years']}/{r['ny']}  {time.time()-t0:.0f}s", flush=True)
        if name.startswith('baseline'): print('   逐年', r['yrs'])
