"""底部爆量長紅研究(Frank 11/07:「已經跌很久的、底部出大量往上拉,是很重要的訊號嗎?」)
事件:跌很久(收盤離 120 日高 ≥ X%、季線下彎、收盤在季線下) + 收盤離 60 日低 ≤ 10%(在底部)
      + 當天量 ≥ K 倍 20 日均量 + 收紅 ≥ R%(往上拉)
進場:隔天開盤;看 5/20/60 日後報酬(扣 0.6% 成本)。
對照:同樣「跌很久、在底部」但當天沒有爆量長紅的日子(隔天開盤買、同樣持有)→ 爆量長紅有沒有多出來的才算訊號。
分 2016~2020 / 2021~2026 兩段、分大盤寬度(<35% / 其他)看穩不穩。"""
import sys, os, collections, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import short_bt_study as SB

S = SB.load_all(); SB.features(S)
# 市場寬度(流動股站上季線比例)
BRc = collections.defaultdict(lambda: [0, 0])
for sid, e in S.items():
    C = e['a'][:, 3]; F = e['F']
    for i in range(60, len(C)):
        if F['liq'][i] >= 2e4: BRc[e['d'][i]][1] += 1; BRc[e['d'][i]][0] += C[i] > F['ma60'][i]
BR = {d: v[0] / v[1] for d, v in BRc.items() if v[1] >= 50}

H_ = (5, 20, 60)
def fwd(e, i, h):
    a = e['a']; n = len(a)
    if i + 1 + h >= n: return None
    px = a[i + 1][0]
    if not px: return None
    return a[i + h][3] / px - 1 - 0.006

def stat(L):
    if not L: return '—'
    L = np.array(L); return f"{len(L):>6} 次 平均 {L.mean()*100:+6.2f}% 中位 {np.median(L)*100:+6.2f}% 勝率 {np.mean(L>0)*100:4.0f}%"

VARIANTS = {
    '基本:離高 ≥30%、量 ≥3 倍、收紅 ≥4%': dict(dd=0.30, vk=3.0, up=0.04),
    '跌更深:離高 ≥40%': dict(dd=0.40, vk=3.0, up=0.04),
    '量更大:量 ≥5 倍': dict(dd=0.30, vk=5.0, up=0.04),
    '漲停級:收紅 ≥9%': dict(dd=0.30, vk=3.0, up=0.09),
    '量 ≥2 倍、收紅 ≥3%(寬鬆)': dict(dd=0.30, vk=2.0, up=0.03),
    '量 ≥3 倍、收紅 ≥4%、收在最高附近': dict(dd=0.30, vk=3.0, up=0.04, top=1),
    '量 ≥3 倍、收紅 ≥4%、跌超過 6 個月': dict(dd=0.30, vk=3.0, up=0.04, long=1),
}

def scan(v):
    ev = {h: [] for h in H_}; base = {h: [] for h in H_}; rows = []
    for sid, e in S.items():
        a = e['a']; O, Hh, L, C, V = a.T; F = e['F']; d = e['d']; n = len(C)
        hi120 = SB.roll_max(Hh, 120); lo60 = -SB.roll_max(-L, 60)
        ma120 = np.full(n, np.nan); cc = np.concatenate([[0], np.cumsum(C)]); ma120[119:] = (cc[120:] - cc[:-120]) / 120
        last = -999
        for i in range(250, n - 61):
            if d[i] < '2016-01-01': continue
            if not (F['liq'][i] >= 2e4): continue
            if not (C[i] <= hi120[i] * (1 - v['dd'])): continue
            if not (C[i] < F['ma60'][i] and F['ma60'][i] < F['ma60'][i - 20]): continue   # 季線下彎、價在季線下
            if not (C[i] <= lo60[i] * 1.10): continue                                    # 在底部
            if v.get('long') and not (ma120[i] < ma120[i - 60] and C[i] < ma120[i]): continue
            vr = V[i] / max(F['v20p'][i], 1); up = C[i] / C[i - 1] - 1
            hit = vr >= v['vk'] and up >= v['up'] and (not v.get('top') or (Hh[i] - C[i]) <= 0.25 * (Hh[i] - L[i] + 1e-9))
            p = 0 if hit else 1
            if hit and i - last < 20: continue
            for h in H_:
                r = fwd(e, i, h)
                if r is None: continue
                (ev if hit else base)[h].append(r)
            if hit:
                last = i; r20 = fwd(e, i, 20); r60 = fwd(e, i, 60)
                rows.append((d[i], sid, r20, r60, BR.get(d[i])))
    return ev, base, rows

for nm, v in VARIANTS.items():
    ev, base, rows = scan(v)
    print(f"\n######## {nm} ########")
    for h in H_: print(f"  {h:>2} 日  訊號 {stat(ev[h])}\n        對照 {stat(base[h])}")
    A = [r for r in rows if r[0] < '2021-01-01']; B = [r for r in rows if r[0] >= '2021-01-01']
    for lab, X in (('2016~2020', A), ('2021~2026', B)):
        print(f"  {lab}: 20 日 {stat([x[2] for x in X if x[2] is not None])} | 60 日 {stat([x[3] for x in X if x[3] is not None])}")
    W = [r for r in rows if r[4] is not None and r[4] < 0.35]; O_ = [r for r in rows if r[4] is not None and r[4] >= 0.35]
    print(f"  大盤一起跌(<35%): 60 日 {stat([x[3] for x in W if x[3] is not None])}")
    print(f"  大盤沒跌夠(≥35%): 60 日 {stat([x[3] for x in O_ if x[3] is not None])}")
    sys.stdout.flush()
