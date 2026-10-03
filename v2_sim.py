#!/usr/bin/env python3
"""AI Pick v2:走查式訓練 + 「跟實戰同規則」回測
模型 A:用全部歷史(≥2 年)訓練;模型 B:只用最近 25 週(= 現行做法)。同一套回測,看差在哪。
實戰規則:週五收盤選 5 檔(+5 候補)→ 下週掛單(≤買價;第 2 天收盤仍沒成交且 ≤ 追價上限就追)→
         出場:到目標 / 停損(個股結構價位,aipick.stock_levels)/ 移動停利(漲 8% 後高點回落 6%)/
         訊號轉弱(週五重排名掉出前 30% 且收盤 < 月線 → 下週一開盤出場)→ 出場後 14 天內由候補同日接替
"""
import json, sys, math, os, datetime as dt
import numpy as np
WORK = os.environ.get("V2WORK", "v2work")
from aipick import stock_levels, rtick

MKT = os.environ.get("MKT", "TW"); SUB = "tw" if MKT == "TW" else "us"
os.environ["AIPICK_MKT"] = MKT
X = np.load(f"{WORK}/{SUB}_X.npy"); Y = np.load(f"{WORK}/{SUB}_Y.npy"); META = json.load(open(f"{WORK}/{SUB}_meta.json")); CAL = json.load(open(f"{WORK}/{SUB}_cal.json"))
IDS = np.array([m[0] for m in META]); DAY = np.array([m[1] for m in META])
BARS = {}
def bars(sid):
    if sid not in BARS: BARS[sid] = np.load(f"{WORK}/{SUB}_bars/{sid}.npy")
    return BARS[sid]


def fit_logit(Xtr, ytr, l2=1.0, iters=300):
    mu = Xtr.mean(0); sd = Xtr.std(0) + 1e-6; Z = (Xtr - mu) / sd
    w = np.zeros(Z.shape[1]); b = 0.0; lr = 0.1; n = len(ytr)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = Z.T @ (p - ytr) / n + l2 * w / n; gb = (p - ytr).mean()
        w -= lr * g; b -= lr * gb
    return w, b, mu, sd


def predict(m, Xq):
    w, b, mu, sd = m; return 1 / (1 + np.exp(-(((Xq - mu) / sd) @ w + b)))


def levels_for(sid, i, buy):
    B = bars(sid); lo = max(0, i - 260)
    o = [[float(B[0, k]), float(B[1, k]), float(B[2, k]), float(B[3, k]), float(B[4, k])] for k in range(lo, i + 1) if not np.isnan(B[3, k])]
    d = [CAL[k] for k in range(lo, i + 1) if not np.isnan(B[3, k])]
    tr = [max(x[1] - x[2], abs(x[1] - y[3]), abs(x[2] - y[3])) for x, y in zip(o[1:], o[:-1])]
    a = sum(tr[-14:]) / max(1, len(tr[-14:]))
    try:
        tgt, stp, lvl = stock_levels(d, o, buy, a, None)
    except Exception:
        tgt, stp = buy * 1.10, buy * 0.92
    return float(tgt), float(stp)


def run_leg(sid, start_i, entry, tgt, stp, weak_k=None, same_day=False):
    """從 start_i(成交日)跑到出場。weak_k:訊號轉弱後要出場的那根 K(開盤價出場)。回傳 (exit_i, exit_px, why, hold)"""
    B = bars(sid); hi = entry; n = B.shape[1]; first = True
    for k in range(start_i, n):
        o, h, l, c = B[0, k], B[1, k], B[2, k], B[3, k]
        if np.isnan(c): continue
        if weak_k is not None and k >= weak_k and not first: return k, float(o), "weak", k - start_i
        if not (first and same_day):
            if hi >= entry * 1.08 and not first:
                tsp = hi * 0.94
                if tsp > stp and l <= tsp: return k, float(o if o <= tsp else tsp), "trail", k - start_i
            if l <= stp: return k, float(o if o <= stp else stp), "sl", k - start_i
            if h >= tgt: return k, float(o if o >= tgt else tgt), "tp", k - start_i
        hi = max(hi, h if not np.isnan(h) else hi); first = False
    return None, None, None, n - start_i


def weak_day(sid, start_i, TOP30, fris):
    """成交後第一個「週五掉出前 30% 且收盤 < 月線」→ 回傳下一根 K 的 idx"""
    B = bars(sid)
    for f in fris:
        if f <= start_i or f not in TOP30: continue
        if sid in TOP30[f]: continue
        c = B[3, f]
        if np.isnan(c): continue
        ma = np.nanmean(B[3, f - 19:f + 1])
        if c < ma:
            k = f + 1
            while k < B.shape[1] and np.isnan(B[3, k]): k += 1
            return k if k < B.shape[1] else None
    return None


def simulate(model_fn, years, label, top=5, bench=5):
    fris = sorted(set(DAY.tolist()))
    # 先算每個週五的排名(同一個模型)→ TOP30 供訊號轉弱用
    RANK = {}; TOP30 = {}
    for fi in fris:
        if int(CAL[fi][:4]) < min(years): continue
        m = model_fn(fi)
        if m is None: continue
        mask = DAY == fi
        if mask.sum() < 50: continue
        p = predict(m, X[mask]); ids = IDS[mask]; order = np.argsort(-p)
        RANK[fi] = [ids[j] for j in order]; TOP30[fi] = set(RANK[fi][:max(10, len(ids) * 3 // 10)])
    res = []; held = {}
    MR60 = np.load(f"{WORK}/{SUB}_mkt_r60.npy"); REG = os.environ.get("REGIME", ""); BREADTH = np.load(f"{WORK}/{SUB}_breadth.npy") if os.path.exists(f"{WORK}/{SUB}_breadth.npy") else None          # 大盤環境過濾(研究用)
    for fi in fris:
        y = int(CAL[fi][:4])
        if y not in years or fi not in RANK: continue
        if REG and BREADTH is not None:
            BR = BREADTH; b20, b60, u20, r60 = float(BR[0, fi]), float(BR[1, fi]), float(BR[2, fi]), float(MR60[fi])
            try:
                if eval(REG): continue                                             # 條件成立 → 這週不選股(研究用)
            except Exception: pass
        held = {s: e for s, e in held.items() if e is None or e > fi}      # 已出場的釋放
        ranked = RANK[fi]
        picks = [s for s in ranked if s not in held][:top + bench]
        main, benchl = picks[:top], picks[top:]
        week_start = fi + 1
        for sid in main:
            B = bars(sid); close = float(B[3, fi])
            if np.isnan(close) or close < (10 if MKT == "TW" else 5): continue
            buy = rtick(close * 0.995, "near"); buy_hi = rtick(close * 1.015, "near")
            fill_i = None; entry = None
            for k in range(week_start, min(week_start + 5, B.shape[1])):
                o, l, c = B[0, k], B[2, k], B[3, k]
                if np.isnan(c): continue
                if l <= buy: fill_i, entry = k, (float(min(o, buy)) if o <= buy else float(buy)); break
                if k == week_start + 1 and c <= buy_hi: fill_i, entry = k, float(c); break
            if fill_i is None: res.append({"y": y, "sid": sid, "fri": CAL[fi], "nofill": 1}); continue
            tgt, stp = levels_for(sid, fi, entry)
            sx = float(os.environ.get("STOPX", "1") or 1)
            if sx != 1: stp = entry - sx * (entry - stp)                      # 研究:停損距離乘數
            chain = []; cur = (sid, fill_i, entry, tgt, stp); bench_q = list(benchl); same = False; rot_used = 0
            while True:
                s2, st, en, tg, sp = cur
                xi, xp, why, hold = run_leg(s2, st, en, tg, sp, weak_day(s2, st, TOP30, fris), same_day=same)
                if xi is None:
                    Bq = bars(s2); v = Bq[3, ~np.isnan(Bq[3])]; chain.append({"sid": s2, "entry": en, "exit": float(v[-1]), "why": "open", "hold": hold}); held[s2] = None; break
                chain.append({"sid": s2, "entry": en, "exit": xp, "why": why, "hold": hold, "xd": CAL[xi]}); held[s2] = xi
                # 研究:停損後 3 天內收盤站回停損價之上 → 視為洗盤,同檔重新進場一次(REENTRY=1)
                if os.environ.get("REENTRY") and why == "sl" and not chain[-1].get("re"):
                    Bq = bars(s2); back = None
                    for k2 in range(xi + 1, min(xi + 4, Bq.shape[1])):
                        if not np.isnan(Bq[3, k2]) and Bq[3, k2] > sp * 1.01: back = k2; break
                    if back is not None:
                        en2 = float(Bq[3, back]); tg2, sp2 = levels_for(s2, back, en2)
                        cur = (s2, back, en2, tg2, sp2); same = True; chain[-1]["re"] = 1; held[s2] = None
                        continue
                if xi - fill_i <= 14 and bench_q and why in ("tp", "sl", "trail"):
                    nxt = bench_q.pop(0); Bn = bars(nxt); cn = Bn[3, xi]
                    if np.isnan(cn) or cn <= 0: break
                    en2 = float(cn); tg2, sp2 = levels_for(nxt, xi, en2); cur = (nxt, xi, en2, tg2, sp2); same = True; rot_used += 1
                    continue
                break
            tot = 1.0
            for L in chain: tot *= L["exit"] / L["entry"]
            res.append({"y": y, "sid": sid, "fri": CAL[fi], "ret": (tot - 1) * 100, "legs": chain, "rot": rot_used})
    return res


def report(res, label):
    out = {}
    for y in sorted({r["y"] for r in res}):
        rs = [r for r in res if r["y"] == y and "ret" in r]; nf = sum(1 for r in res if r["y"] == y and r.get("nofill"))
        if not rs: continue
        rets = [r["ret"] for r in rs]; legs = [L for r in rs for L in r["legs"] if L["why"] != "open"]
        lr = [(L["exit"] / L["entry"] - 1) * 100 for L in legs]
        why = {}
        for L in legs: why[L["why"]] = why.get(L["why"], 0) + 1
        out[y] = {"n": len(rs), "nofill": nf, "win": round(100 * sum(1 for x in rets if x > 0) / len(rets), 1), "avg": round(float(np.mean(rets)), 2),
                  "med": round(float(np.median(rets)), 2), "leg_n": len(legs), "leg_avg": round(float(np.mean(lr)), 2) if lr else None,
                  "hold": round(float(np.mean([L["hold"] for L in legs])), 1) if legs else None, "why": why}
    allr = [r["ret"] for r in res if "ret" in r]
    out["ALL"] = {"n": len(allr), "win": round(100 * sum(1 for x in allr if x > 0) / len(allr), 1), "avg": round(float(np.mean(allr)), 2), "med": round(float(np.median(allr)), 2)}
    print(f"\n=== {label} ===")
    for y, v in out.items(): print(y, v)
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "A"
    years = [int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else range(2015, 2027))]
    cache = {}
    ybin = (Y > 0).astype(float)
    def model_A(fi):     # 全部歷史(距今 ≥ 10 日,避免看到未來)
        yr = CAL[fi][:4]
        if yr in cache: return cache[yr]
        first = next(k for k in sorted(set(DAY.tolist())) if CAL[k][:4] == yr)
        m = (DAY < first - 10)
        if m.sum() < 20000: return None
        cache[yr] = fit_logit(X[m], ybin[m]); return cache[yr]
    def model_B(fi):     # 最近 25 週(現行做法)
        key = fi // 5
        if key in cache: return cache[key]
        fr = sorted(k for k in set(DAY.tolist()) if k < fi - 10)[-25:]
        if len(fr) < 25: return None
        m = np.isin(DAY, fr); cache[key] = fit_logit(X[m], ybin[m]); return cache[key]
    fn = model_A if mode == "A" else model_B
    res = simulate(fn, years, mode)
    rep = report(res, "模型 " + mode + ("(15 年歷史訓練)" if mode == "A" else "(最近 25 週訓練=現行)"))
    json.dump({"rep": rep, "res": res}, open(f"{WORK}/{SUB}_res_{mode}_{years[0]}_{years[-1]}.json", "w"), ensure_ascii=False)
