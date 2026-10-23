"""美股(S&P 500 現成分股)個股買賣計畫規則回測:跌深低接門檻/出場、52 週新高突破+季線停損、停損確認。"""
import sys, os, glob, gzip, json, collections, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan_bt_study as PB
R = os.path.dirname(os.path.abspath(__file__))
def load_us():
    K = collections.defaultdict(lambda: ([], []))
    for y in sorted(os.listdir(f'{R}/archive/k/us')):
        for f in glob.glob(f'{R}/archive/k/us/{y}/*.json.gz'):
            j = json.load(gzip.open(f, 'rt'))
            for sid, e in j.items():
                if e.get('d') and e.get('o'): K[sid][0].extend(e['d']); K[sid][1].extend(e['o'])
    out = {}
    for sid, (d, o) in K.items():
        idx = sorted(range(len(d)), key=lambda i: d[i]); dd, oo = [], []
        for i in idx:
            x, y = d[i], o[i]
            if dd and dd[-1] == x: oo[-1] = y; continue
            if not y or len(y) < 5 or not y[3] or not y[0]: continue
            dd.append(x); oo.append(y)
        if len(dd) < 300: continue
        a = np.array(oo, dtype=float); a[:, 4] = a[:, 4] / 1000.0   # r1156:volume千股×股價=千美元；不能多乘一次股價
        out[sid] = dict(d=dd, a=a, f=np.zeros(len(dd)), t=np.zeros(len(dd)), sec='', rev={})
    return out
S = load_us(); PB.prep(S); print('US stocks', len(S), flush=True)
sim, stats, mk_exit = PB.simulate, PB.stats, PB.mk_exit
ev250 = lambda e, i: e['a'][i][3] > e['P']['h250'][i] and e['a'][i-1][3] <= e['P']['h250'][i-1]
def dipk(k): return lambda e, i: e['a'][i][3] / e['P']['h60'][i] - 1 <= -k and e['a'][i-1][3] / e['P']['h60'][i-1] - 1 > -k
x = mk_exit(sl=0.15, tp=0.20, hold=60)
rng = np.random.default_rng(1)
stats(sim(S, None, x, sample_any=True, rng=rng), '隨機買 | −15%/+20%/60日')
for k in (0.20, 0.25, 0.30, 0.35, 0.40):
    stats(sim(S, dipk(k), x), f'跌深 −{int(k*100)}% 第一天 | −15%/+20%/60日')
for k in (0.25, 0.35):
    stats(sim(S, dipk(k), x, start='2016-01-01', end='2021-01-01'), f'跌深 −{int(k*100)}% | 2016~2020')
    stats(sim(S, dipk(k), x, start='2021-01-01'), f'跌深 −{int(k*100)}% | 2021~2026')
    stats(sim(S, dipk(k), mk_exit(sl=0.15, tp=0.30, hold=60)), f'跌深 −{int(k*100)}% | −15%/+30%/60日')
    stats(sim(S, dipk(k), mk_exit(sl=0.20, tp=0.30, hold=90)), f'跌深 −{int(k*100)}% | −20%/+30%/90日')
    stats(sim(S, dipk(k), mk_exit(sl=0.10, tp=0.20, hold=60)), f'跌深 −{int(k*100)}% | −10%/+20%/60日')
    stats(sim(S, dipk(k), mk_exit(stop_ma='ma60', tp=None, hold=120)), f'跌深 −{int(k*100)}% | 季線/不停利/120日')
print('--- 突破 ---')
stats(sim(S, None, mk_exit(stop_ma='ma60', tp=0.25, hold=60), sample_any=True, rng=rng), '隨機買 | 季線/+25%/60日')
stats(sim(S, None, mk_exit(stop_ma='ma60', tp=None, hold=120), sample_any=True, rng=rng), '隨機買 | 季線/不停利/120日')
for nm, xx in [('季線/+25%/60日', mk_exit(stop_ma='ma60', tp=0.25, hold=60)), ('季線/不停利/120日', mk_exit(stop_ma='ma60', tp=None, hold=120)), ('季線/不停利/250日', mk_exit(stop_ma='ma60', tp=None, hold=250)), ('−15%/+25%/60日', mk_exit(sl=0.15, tp=0.25, hold=60)), ('月線/不停利/120日', mk_exit(stop_ma='ma20', tp=None, hold=120))]:
    stats(sim(S, ev250, xx), f'站上 250 日高 | {nm}')
def mk_x(confirm=1, hold=120):
    def f(e, ei):
        a = e['a']; O, H, L, C, V = a.T; n = len(C); P = e['P']; below = 0
        for k in range(ei, min(n, ei + hold)):
            below = below + 1 if (C[k] < P['ma60'][k] and k > ei) else 0
            if below >= confirm:
                xi = k + 1 if k + 1 < n else k; return xi, (O[k+1] if k + 1 < n else C[k]), 'ma'
            if k == ei + hold - 1: return k, C[k], 'time'
        return None, None, None
    return f
stats(sim(S, ev250, mk_x(2)), '站上 250 日高 | 連 2 天跌破季線/120日')
stats(sim(S, ev250, mk_x(3)), '站上 250 日高 | 連 3 天跌破季線/120日')
for a_, b_ in (('2016-01-01', '2021-01-01'), ('2021-01-01', None)):
    stats(sim(S, ev250, mk_exit(stop_ma='ma60', tp=None, hold=120), start=a_, end=b_), f'站上 250 日高 | 季線/不停利 | {a_[:4]}~')
    stats(sim(S, None, mk_exit(stop_ma='ma60', tp=None, hold=120), start=a_, end=b_, sample_any=True, rng=rng), f'隨機 | 季線/不停利 | {a_[:4]}~')
ev60 = lambda e, i: e['a'][i][3] > e['P']['h60'][i] and e['a'][i-1][3] <= e['P']['h60'][i-1]
near = lambda e, i: e['a'][i][3] / e['P']['hi250'][i] - 1 >= -0.10
stats(sim(S, lambda e, i: ev60(e, i) and near(e, i), mk_exit(stop_ma='ma60', tp=None, hold=120)), '站上 60 日高+近高 | 季線/不停利')
stats(sim(S, lambda e, i: ev60(e, i) and not near(e, i), mk_exit(stop_ma='ma60', tp=None, hold=120)), '站上 60 日高+非近高 | 季線/不停利')
# 年度分布
tr = sim(S, ev250, mk_exit(stop_ma='ma60', tp=None, hold=120)); yy = collections.defaultdict(list)
for t in tr: yy[t[1][:4]].append(t[2])
print('突破逐年:', ' '.join(f'{y}:{np.mean(v)*100:+.1f}%' for y, v in sorted(yy.items())))
tr = sim(S, None, mk_exit(stop_ma='ma60', tp=None, hold=120), sample_any=True, rng=rng); yy = collections.defaultdict(list)
for t in tr: yy[t[1][:4]].append(t[2])
print('隨機逐年:', ' '.join(f'{y}:{np.mean(v)*100:+.1f}%' for y, v in sorted(yy.items())))
