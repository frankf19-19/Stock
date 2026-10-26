"""r1181:美股跌深低接(第一天離 60 日高 −35%,−20%/+30%/90 日)的「本股條件」研究。
只用價格/量/產業(美股沒有可回測的歷史估值與籌碼);兩期(2016~2020 / 2021~2026)差距都 ≥0.8% 才採用;
另外用股票隨機分兩半做交叉驗證(一半挑條件、另一半驗證總分)。"""
import sys, os, json, zlib, collections as CC, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan_bt_study as PB
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'us_plan_bt_study.py')).read().split("S = load_us()")[0]
exec(src)
S = load_us(); PB.prep(S)
D = json.load(open('/home/claude/repo2/data.json'))
SEC = {s['id']: s.get('sector') or '' for s in D['stocks'] if s.get('market') == 'US'}
# 產業 20 日強弱、SPY 200 日線
alld = CC.defaultdict(list); mk = CC.defaultdict(list)
for sid, e in S.items():
    C = e['a'][:, 3]
    for i in range(20, len(C)):
        r = C[i] / C[i-20] - 1; alld[(SEC.get(sid, ''), e['d'][i])].append(r); mk[e['d'][i]].append(r)
SR = {k: np.mean(v) for k, v in alld.items() if len(v) >= 5}; MK = {d: np.mean(v) for d, v in mk.items()}
spy = S.get('SPY')
def bull(d):
    if spy is None: return None
    try: i = spy['d'].index(d)
    except ValueError: return None
    return spy['a'][i][3] > spy['P']['ma240'][i] if spy['P']['ma240'][i] else None
def dip35(e, i): return e['a'][i][3] / e['P']['h60'][i] - 1 <= -0.35 and e['a'][i-1][3] / e['P']['h60'][i-1] - 1 > -0.35
xf = PB.mk_exit(sl=0.20, tp=0.30, hold=90)
T = []
for pn, a_, b_ in (('A', '2016-01-01', '2021-01-01'), ('B', '2021-01-01', None)):
    for t in PB.simulate(S, dip35, xf, start=a_, end=b_):
        sid = t[0]; e = S[sid]; i = e['d'].index(t[1]) - 1; a = e['a']; C = a[:, 3]; V = a[:, 4]; P = e['P']
        sec = SEC.get(sid, ''); sr = SR.get((sec, e['d'][i])); mr = MK.get(e['d'][i]); atrp = P['atr'][i] / C[i]
        F = {'前20日跌>25%(急跌)': C[i] / C[i-20] - 1 < -0.25, '前20日跌<15%(慢跌)': C[i] / C[i-20] - 1 > -0.15,
             '當天量>2倍': V[i] > 2 * V[i-20:i].mean(), '當天量縮': V[i] < V[i-20:i].mean(), '當天跌>5%': C[i] / C[i-1] - 1 < -0.05,
             '仍在年線上': bool(P['ma240'][i]) and C[i] > P['ma240'][i], '月線>季線': P['ma20'][i] > P['ma60'][i],
             '離60日高>−45%(跌更深)': C[i] / P['h60'][i] - 1 <= -0.45, '波動>4%/日': atrp > 0.04, '波動<2.5%/日': atrp < 0.025,
             '產業弱於大盤5%': sr is not None and mr is not None and sr - mr < -0.05, '產業強過大盤': sr is not None and mr is not None and sr - mr > 0.0,
             '大盤(SPY)在年線上': bull(e['d'][i]) is True}
        T.append((zlib.crc32(sid.encode()) % 2, pn, t[2], F))
m_ = lambda L: np.mean(L) * 100 if L else float('nan')
print(f'美股跌深 −35%:{len(T)} 筆;A {m_([r for h,p,r,F in T if p=="A"]):+.2f}%  B {m_([r for h,p,r,F in T if p=="B"]):+.2f}%')
def deltas(rows):
    out = {}
    for fn in rows[0][3]:
        res = []
        for pn in ('A', 'B'):
            y = [r for h, p, r, F in rows if p == pn and F[fn]]; nn = [r for h, p, r, F in rows if p == pn and not F[fn]]
            res.append((m_(y) - m_(nn), len(y), len(nn), m_(y), m_(nn)))
        out[fn] = res
    return out
for fn, ((da, ya, na, ma, mna), (db, yb, nb, mb, mnb)) in deltas(T).items():
    ok = min(ya, na, yb, nb) >= 30
    flag = '  ✅加分' if ok and da > 0.8 and db > 0.8 else ('  ❌扣分' if ok and da < -0.8 and db < -0.8 else '')
    print(f'  {fn:22} 符合 A {ma:+6.2f}%({ya}) B {mb:+6.2f}%({yb}) | 不符合 A {mna:+6.2f}% B {mnb:+6.2f}% | 差 A {da:+5.2f} B {db:+5.2f}{flag}')
for tr in (0, 1):
    rows = [x for x in T if x[0] == tr]; sel = {}
    for fn, ((da, ya, na, *_), (db, yb, nb, *_)) in deltas(rows).items():
        if min(ya, na, yb, nb) < 20: continue
        if da > 0.8 and db > 0.8: sel[fn] = 1
        elif da < -0.8 and db < -0.8: sel[fn] = -1
    print(f'\n用第 {tr} 半挑出:' + '、'.join(f"{k}{'+' if v>0 else '−'}" for k, v in sel.items()))
    for pn in ('A', 'B'):
        B_ = CC.defaultdict(list)
        for h, p, r, F in T:
            if h == tr or p != pn: continue
            B_[max(-3, min(3, sum(v for k, v in sel.items() if F[k])))].append(r)
        print(f'  另一半 期 {pn}:' + '  '.join(f"{k:+d}:{m_(B_[k]):+.1f}%({len(B_[k])})" for k in sorted(B_)))
