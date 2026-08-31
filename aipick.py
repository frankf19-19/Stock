#!/usr/bin/env python3
"""K研所 · 🤖 AI Pick 週選模型 v1(r702)
每週五收盤後(或週末/週一第一班)由量化模型選出「下週看漲」的台股 5 檔,
給出本週建議買價/追價上限/目標/停損,寫入 aipick.json 後**凍結不再改動**;
之後每一班都用 k/ 分片的實際 K 線回頭核對:有沒有成交、下週收在哪、有沒有到目標/停損,
累積成準確率與漲跌幅統計,前端 AI Pick 區塊直接讀。

輸入:data.json、k/tw*.json      輸出:aipick.json(自我累積,不可被覆蓋重建)
規則:
  ・買進週 = 建議買進的那一週(週一日期);評估週 = 買進週的下一週
  ・成交判定:買進週任一日 開盤≤買價 → 以開盤成交;最低≤買價 → 以買價成交;
              否則最低≤追價上限 → 以追價上限成交;全週都沒碰到 → 未成交(不計入勝率)
  ・結算:評估週最後一根 K 收盤 vs 成交價;>0 命中(win)、<0 失誤(loss)、=0 平(flat)
  ・出場(r736):成交後逐日檢查,先碰到目標 → 以目標價賣出;先碰到停損 → 以停損價賣出;
              兩者同日觸及採保守假設(停損先);都沒碰到 → 評估週最後一根 K 收盤賣出(到期出場)
  ・每檔都記錄「買進日/買進價 → 賣出日/賣出價/賣出原因/持有天數/實現損益」,統計以實際出場為準
"""
import json, os, sys, datetime as dt

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
TODAY = NOW.date()
OUT = "aipick.json"
MODEL = "v2"
XVER = 2                      # r736:出場結算版本(舊檔會自動重跑一次補上買賣時間/實現損益)
N_PICK = 5
MAX_PER_SECTOR = 2
KEEP_WEEKS = 80


# ───────────────────────── 工具 ─────────────────────────
def monday(d):
    return d - dt.timedelta(days=d.weekday())


def iso(d):
    return d.isoformat()


def tick(px):
    """台股升降單位"""
    if px < 10: return 0.01
    if px < 50: return 0.05
    if px < 100: return 0.1
    if px < 500: return 0.5
    if px < 1000: return 1.0
    return 5.0


def rtick(px, mode="near"):
    t = tick(px)
    q = px / t
    if mode == "down": q = int(q)
    elif mode == "up": q = int(q) + (0 if abs(q - int(q)) < 1e-9 else 1)
    else: q = round(q)
    v = q * t
    return round(v, 2)


def avg(a):
    return sum(a) / len(a) if a else 0.0


def atr(o, p=14):
    """o=[[開,高,低,收,量]...] 取最後 p 期 TR 簡單平均"""
    if len(o) < p + 1: return None
    s = 0.0
    for i in range(len(o) - p, len(o)):
        h, l, pc = o[i][1], o[i][2], o[i - 1][3]
        s += max(h - l, abs(h - pc), abs(l - pc))
    return s / p


def shard_key(sid):
    t = str(sid)
    return t[:3] if t[:2] == "00" else t[:2]


_SH = {}
def shard(sid):
    k = shard_key(sid)
    if k not in _SH:
        p = f"k/tw{k}.json"
        try:
            with open(p, encoding="utf-8") as f: _SH[k] = json.load(f)
        except Exception:
            _SH[k] = {}
    return _SH[k]


def bars_of(sid):
    e = shard(sid).get(sid)
    if not e or not isinstance(e.get("d"), list) or not isinstance(e.get("o"), list): return [], []
    d, o = e["d"], e["o"]
    n = min(len(d), len(o))
    return d[:n], o[:n]


def load_json(p, default):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception:
        return default


# ───────────────────────── 選股模型 ─────────────────────────
_SC_MEMO = {}
def score_one(s, d, o, cutoff):
    """回傳 (score, why[], meta) 或 None。cutoff:只用日期 < cutoff 的 K(同檔同週記憶化)"""
    mk = (s.get("id"), cutoff)
    if mk in _SC_MEMO: return _SC_MEMO[mk]
    r = _score_one(s, d, o, cutoff)
    _SC_MEMO[mk] = r
    return r


def _score_one(s, d, o, cutoff):
    idx = [i for i, x in enumerate(d) if x < cutoff]
    if len(idx) < 65: return None
    o = [o[i] for i in idx]
    d = [d[i] for i in idx]
    if any(len(x) < 5 for x in o[-65:]): return None
    c = [x[3] for x in o]; h = [x[1] for x in o]; l = [x[2] for x in o]; v = [x[4] or 0 for x in o]
    last = c[-1]
    if not (last >= 10): return None
    ma5, ma10, ma20, ma60 = avg(c[-5:]), avg(c[-10:]), avg(c[-20:]), avg(c[-60:])
    ma20p = avg(c[-25:-5])
    r5 = last / c[-6] - 1; r20 = last / c[-21] - 1; r60 = last / c[-61] - 1
    bias20 = last / ma20 - 1
    v5, v20 = avg(v[-5:]), avg(v[-20:])
    if v20 <= 0: return None
    vr = v5 / v20
    liq = avg([c[i] * v[i] for i in range(len(c) - 20, len(c))]) * 1000   # 元/日
    if liq < 3e7: return None                                            # 日均成交值 < 3,000 萬:流動性不足
    h20 = max(h[-21:-1]); near = last / h20
    a = atr(o, 14)
    if not a or a <= 0: return None
    # 追高/乖離過大剔除
    if r5 > 0.15 or bias20 > 0.15: return None
    # 連續跌破季線且季線下彎:不做
    if last < ma60 and ma20 < ma60 and ma20 < ma20p: return None

    sc = 0.0; why = []
    # 趨勢結構
    if ma5 > ma20: sc += 10
    if ma20 > ma60: sc += 10; why.append("月線在季線上")
    if last > ma20: sc += 5
    if ma20 > ma20p: sc += 4; why.append("月線翻揚")
    # 動能
    sc += max(-10, min(25, r20 * 100)) * 0.8 + max(-20, min(50, r60 * 100)) * 0.3
    if r20 > 0.05: why.append(f"20日 {r20*100:+.1f}%")
    # 突破位置
    if near >= 0.98: sc += 10; why.append("貼近20日高" if last <= h20 else "創20日新高")
    if last > h20: sc += 5
    # 量能
    if 1.1 <= vr <= 2.5: sc += 8; why.append(f"量增 {vr:.1f}x")
    elif vr > 2.5: sc += 3; why.append(f"爆量 {vr:.1f}x")
    elif vr < 0.7: sc -= 5
    # 乖離健康度
    if 0 <= bias20 <= 0.06: sc += 6
    elif bias20 <= 0.10: sc += 2
    elif bias20 > 0.10: sc -= 6
    elif bias20 < -0.03: sc -= 4
    # 基本面 / 籌碼
    f = ((s.get("f") or {}).get("score") or 50); cs = ((s.get("c") or {}).get("score") or 50)
    sc += (f - 50) / 50 * 12; sc += (cs - 50) / 50 * 10
    if f >= 70: why.append(f"基本面 {f} 分")
    raw = ((s.get("c") or {}).get("raw") or {})
    f5 = raw.get("f5")
    if isinstance(f5, (int, float)) and f5 > 0 and f5 / max(v20 * 5, 1) > 0.05:
        sc += 6; why.append(f"外資5日 +{int(f5):,} 張")
    if s.get("t3"): sc += 4; why.append("三率三升")
    if s.get("thesis"): sc += 3
    # 回測不破(拉回站穩 10 日線且月線向上)
    kind = "trend"
    if r5 <= 0 and last >= ma10 and ma20 > ma20p:
        sc += 4; kind = "pullback"; why.append("拉回站穩10日線")
    if last > h20 and vr >= 1.1: kind = "break"
    # 買價:貼近 5 日線 → 直接以收盤買;否則等回測到 5 日線附近(不低於收盤-0.5ATR)
    bias5 = last / ma5 - 1
    if bias5 <= 0.015: buy = last
    else: buy = max(ma5, last - 0.5 * a)
    buy = rtick(buy, "down")
    buy_hi = rtick(buy * 1.015, "up")
    tgt = rtick(min(buy * 1.12, max(buy * 1.04, buy + 2.0 * a)), "near")
    stp = rtick(max(buy * 0.92, buy - 2.0 * a), "near")
    meta = {"ref_close": round(last, 2), "ref_day": d[-1], "atr": round(a, 2), "buy": buy, "buy_hi": buy_hi,
            "target": tgt, "stop": stp, "kind": kind, "r20": round(r20 * 100, 1), "bias20": round(bias20 * 100, 1),
            "vr": round(vr, 2)}
    # 🧠 學習用特徵向量(連續值;順序 = FEATS)
    import math
    fx = [1.0 if ma5 > ma20 else 0.0, 1.0 if ma20 > ma60 else 0.0, 1.0 if last > ma20 else 0.0,
          max(-0.1, min(0.1, ma20 / ma20p - 1)), max(-0.2, min(0.2, r5)), max(-0.3, min(0.5, r20)),
          max(-0.5, min(1.0, r60)), max(-0.3, min(0.05, last / h20 - 1)), math.log(max(vr, 0.2)),
          max(-0.15, min(0.15, bias20)), (f - 50) / 50, (cs - 50) / 50,
          max(-0.3, min(0.3, (f5 / max(v20 * 5, 1)) if isinstance(f5, (int, float)) else 0.0)),
          1.0 if s.get("t3") else 0.0, min(0.15, a / last), math.log10(max(liq, 1e6))]
    meta["fx"] = [round(x, 4) for x in fx]
    return sc, why[:5], meta

FEATS = ["5日線>月線", "月線>季線", "收盤>月線", "月線斜率", "5日漲幅", "20日漲幅", "60日漲幅", "距20日高",
         "量能比(log)", "月線乖離", "基本面分", "籌碼分", "外資5日買超比", "三率三升", "波動率(ATR%)", "成交值(log)"]
NF = len(FEATS)

# ───────────────────────── 🧠 學習(walk-forward 邏輯斯迴歸) ─────────────────────────
def fwd_label(d, o, cutoff, horizon_end):
    """cutoff 前最後收盤 → horizon_end(含)前最後收盤 的報酬;未走完回傳 None"""
    i0 = None
    for i in range(len(d) - 1, -1, -1):
        if d[i] < cutoff: i0 = i; break
    if i0 is None: return None
    i1 = None
    for i in range(len(d) - 1, i0, -1):
        if d[i] <= horizon_end: i1 = i; break
    if i1 is None or d[i1] < horizon_end[:8] + "01": return None
    # 至少要有 horizon 週的 K(週四以後)才算走完
    if d[i1] < (dt.date.fromisoformat(horizon_end) - dt.timedelta(days=1)).isoformat() and TODAY <= dt.date.fromisoformat(horizon_end) + dt.timedelta(days=3):
        return None
    c0, c1 = o[i0][3], o[i1][3]
    if not (c0 > 0 and c1 > 0): return None
    return c1 / c0 - 1


_FEAT_CACHE = {}
def week_samples(data, cutoff_week):
    """某個買進週(cutoff=週一)的全市場樣本:[(id, fx, ret2w)];ret 未走完者 ret=None"""
    key = iso(cutoff_week)
    if key in _FEAT_CACHE: return _FEAT_CACHE[key]
    out = []
    h_end = iso(cutoff_week + dt.timedelta(days=11))
    for s in data.get("stocks", []):
        if s.get("market") != "TW" or s.get("etf"): continue
        d, o = bars_of(s["id"])
        if not d: continue
        r = score_one(s, d, o, key)
        if not r: continue
        sc, why, meta = r
        out.append({"id": s["id"], "fx": meta["fx"], "sc": sc, "ret": fwd_label(d, o, key, h_end)})
    _FEAT_CACHE[key] = out
    return out


def fit_model(samples):
    """samples: list of {fx, ret(不為 None)};以「贏過同週中位數」為標籤,L2 邏輯斯迴歸。回傳 learn dict 或 None"""
    try:
        import numpy as np
    except Exception:
        return None
    X = np.array([x["fx"] for x in samples], dtype=float); y = np.array([x["y"] for x in samples], dtype=float)
    if len(X) < 300: return None
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    w = np.zeros(NF); b = 0.0; lam = 1.0 / len(X) * 20; lr = 0.5
    for _ in range(400):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = Z.T @ (p - y) / len(X) + lam * w; gb = float((p - y).mean())
        w -= lr * g; b -= lr * gb
    p = 1 / (1 + np.exp(-(Z @ w + b)))
    acc = float(((p > 0.5) == (y > 0.5)).mean())
    # 單因子 IC(Spearman 近似:用 rank 相關)
    ic = []
    R = np.array([x["ret"] for x in samples], dtype=float)
    for j in range(NF):
        a = X[:, j]
        if a.std() < 1e-9: ic.append(0.0); continue
        ra = a.argsort().argsort(); rr = R.argsort().argsort()
        ic.append(float(np.corrcoef(ra, rr)[0, 1]))
    return {"n": int(len(X)), "w": [round(float(v), 4) for v in w], "b": round(b, 4),
            "mu": [round(float(v), 5) for v in mu], "sd": [round(float(v), 5) for v in sd],
            "acc": round(acc * 100, 1), "ic": [round(v, 3) for v in ic]}


LABEL_Q = float(os.environ.get("AIPICK_LABEL_Q", "0.6"))
ALPHA_MAX = float(os.environ.get("AIPICK_ALPHA_MAX", "0.45"))   # 會被自動調參覆蓋(learn.alpha_max)
ALPHA_GRID = [0.3, 0.45, 0.6]
def learn_alpha(n, amax=None):
    """樣本越多越信模型:<300 不用、3000 以上到 alpha_max(自動調參決定)"""
    amax = ALPHA_MAX if amax is None else amax
    if n < 300: return 0.0
    return round(min(amax, 0.2 + (amax - 0.2) * (n - 300) / 2700), 2)


def build_learn(data, buy_week, weeks_hint=40, amax=None):
    """用 buy_week 之前「已走完」的所有週訓練(walk-forward,無未來資料)"""
    samples = []
    for k in range(1, weeks_hint + 1):
        wk = buy_week - dt.timedelta(days=7 * k)
        if wk + dt.timedelta(days=11) >= buy_week: continue   # 評估週要在 buy_week 之前走完
        ws = [x for x in week_samples(data, wk) if x["ret"] is not None]
        if len(ws) < 50: continue
        srt = sorted(x["ret"] for x in ws)
        thr = srt[int(len(srt) * LABEL_Q)]            # 標籤:當週報酬排名前 (1−LABEL_Q) 的才算「好」(市場中性)
        for x in ws:
            samples.append({"fx": x["fx"], "ret": x["ret"], "y": 1.0 if x["ret"] > thr else 0.0})
    m = fit_model(samples)
    if not m: return {"n": len(samples), "alpha": 0.0, "ver": "v1", "note": "樣本不足(<300),沿用規則模型"}
    m["alpha"] = learn_alpha(m["n"], amax); m["alpha_max"] = ALPHA_MAX if amax is None else amax
    m["ver"] = "v2"; m["trained_for"] = iso(buy_week)
    return m


def simulate_bt(data, n_bt, amax):
    """用某個 alpha_max 走一遍回測(walk-forward);回傳週清單(已結算)"""
    out = []
    for k in range(n_bt, 0, -1):
        bwk = monday(TODAY) - dt.timedelta(days=7 * k)
        if bwk + dt.timedelta(days=13) > TODAY: continue
        L = build_learn(data, bwk, amax=amax)
        w = gen_week(data, bwk, L)
        if w["picks"]:
            w["bt"] = True; evaluate(w); out.append(w)
    return out


def tune_alpha(data, n_bt):
    """🧠 自動調參:對 ALPHA_GRID 各跑一遍回測,以「勝率 + 平均報酬」綜合分挑最好的 alpha_max;回傳 (amax, weeks, report)"""
    best = None; rep = []
    for a in ALPHA_GRID:
        ws = simulate_bt(data, n_bt, a)
        st = stats_of(ws)
        if not st["weeks"]: continue
        metric = ((st["win_rate"] or 50) - 50) / 5 + (st["avg_ret"] or 0)   # 勝率每 +5 個百分點 ≈ 平均報酬 +1%
        rep.append({"alpha_max": a, "win_rate": st["win_rate"], "avg_ret": st["avg_ret"], "metric": round(metric, 2)})
        if best is None or metric > best[0]: best = (metric, a, ws)
    if not best: return ALPHA_MAX, [], rep
    return best[1], best[2], rep


def model_logit(learn, fx):
    if not learn or not learn.get("w"): return 0.0
    z = learn["b"]
    for j in range(NF):
        z += learn["w"][j] * (fx[j] - learn["mu"][j]) / learn["sd"][j]
    return z


def review_week(w):
    """檢討:輸家 vs 贏家在哪些特徵差最多(用 pick 上的 fx)"""
    try:
        win = [p for p in w["picks"] if p.get("result") == "win" and p.get("fx")]
        los = [p for p in w["picks"] if p.get("result") == "loss" and p.get("fx")]
        if not los: return f"{aipmd(w['buy_week'])} 週 5 檔全數命中或未成交,無需修正"
        if not win:
            m = [avg([p["fx"][j] for p in los]) for j in range(NF)]
            hi = sorted(range(NF), key=lambda j: -abs(m[j]))[:2]
            return f"{aipmd(w['buy_week'])} 週全數失誤——共同點:" + "、".join(f"{FEATS[j]} {m[j]:+.2f}" for j in hi) + ";模型已把該週樣本納入重訓"
        diff = []
        for j in range(NF):
            a = avg([p["fx"][j] for p in win]); c = avg([p["fx"][j] for p in los])
            diff.append((j, a - c))
        diff.sort(key=lambda x: -abs(x[1]))
        top = diff[:2]
        return f"{aipmd(w['buy_week'])} 週命中 {len(win)}/失誤 {len(los)}——贏家與輸家差最多的是:" + "、".join(
            f"{FEATS[j]}(贏家{'高' if v > 0 else '低'} {abs(v):.2f})" for j, v in top) + ";已納入重訓"
    except Exception as e:
        return f"檢討失敗:{e}"


def aipmd(s):
    m = str(s)[5:].split("-"); return f"{int(m[0])}/{int(m[1])}"


def gen_week(data, buy_week, learn=None):
    cutoff = iso(buy_week)
    cands = []
    for s in data.get("stocks", []):
        if s.get("market") != "TW" or s.get("etf") or s.get("disp"): continue
        if not (isinstance(s.get("price"), (int, float)) and s["price"] > 0): continue
        d, o = bars_of(s["id"])
        if not d: continue
        r = score_one(s, d, o, cutoff)
        if not r: continue
        sc, why, meta = r
        cands.append((sc, s, why, meta))
    # 🧠 混合:規則分 z 值 ×(1−α)+ 學習模型 logit z 值 × α
    alpha = float((learn or {}).get("alpha") or 0.0)
    if alpha > 0 and len(cands) > 5:
        base = [c[0] for c in cands]; lg = [model_logit(learn, c[3]["fx"]) for c in cands]
        def z(a):
            m = avg(a); sd = (avg([(x - m) ** 2 for x in a]) ** 0.5) or 1.0
            return [(x - m) / sd for x in a]
        zb, zl = z(base), z(lg)
        cands = [((1 - alpha) * zb[i] * 10 + alpha * zl[i] * 10 + 50, c[1], c[2], dict(c[3], ml=round(lg[i], 3), rule=round(c[0], 1)))
                 for i, c in enumerate(cands)]
    cands.sort(key=lambda x: -x[0])
    picks, per = [], {}
    for sc, s, why, meta in cands:
        sec = s.get("sector") or "其他"
        if per.get(sec, 0) >= MAX_PER_SECTOR: continue
        per[sec] = per.get(sec, 0) + 1
        picks.append({"id": s["id"], "name": s.get("name") or s["id"], "sector": sec,
                      "score": round(sc, 1), "why": why, **meta,
                      "fill": None, "entry": None, "hi": None, "lo": None, "last": None, "last_day": None,
                      "ret": None, "ret_c": None, "hit_tp": False, "hit_sl": False, "result": "pending",
                      "xd": None, "xp": None, "xw": None, "hold": None})
        if len(picks) >= N_PICK: break
    ref_day = max((p["ref_day"] for p in picks), default=cutoff)
    return {"buy_week": cutoff, "eval_week": iso(buy_week + dt.timedelta(days=7)),
            "made": NOW.strftime("%Y-%m-%d %H:%M"), "ref_day": ref_day,
            "model": (learn or {}).get("ver") or "v1", "alpha": alpha, "learn_n": int((learn or {}).get("n") or 0),
            "status": "open", "picks": picks, "n_cand": len(cands)}


# ───────────────────────── 追蹤結算 ─────────────────────────
def exit_scan(p, held, entry):
    """成交後逐日找「實際出場」:先到目標→目標價賣、先到停損→停損價賣,同日兩者皆觸及採保守(停損先)。
    回傳 (出場日, 出場價, 原因 tp/sl, 持有天數);都沒碰到回傳 (None, None, None, 已持有天數)。"""
    tg, sp = p["target"], p["stop"]
    for i, (day, b) in enumerate(held):
        op, hh, ll = b[0], b[1], b[2]
        hit_sl = ll <= sp
        hit_tp = hh >= tg
        if hit_sl:                                          # 保守:同日都碰到,先算停損
            if i == 0: px = sp if entry > sp else entry     # 成交日:進場價已含跳空,不能再用開盤價
            else: px = op if op <= sp else sp
            return day, px, "sl", i + 1
        if hit_tp:
            if i == 0: px = tg if entry < tg else entry
            else: px = op if op >= tg else tg
            return day, px, "tp", i + 1
    return None, None, None, len(held)


def evaluate(week):
    bw = dt.date.fromisoformat(week["buy_week"]); ew = bw + dt.timedelta(days=7)
    bw_end = iso(bw + dt.timedelta(days=4)); ew_end = iso(ew + dt.timedelta(days=4))
    buy_week_over = TODAY > bw + dt.timedelta(days=6)
    eval_over = TODAY > ew + dt.timedelta(days=6)     # 評估週之後的週一起一定結算
    all_done = True
    for p in week["picks"]:
        d, o = bars_of(p["id"])
        bb = [(d[i], o[i]) for i in range(len(d)) if week["buy_week"] <= d[i] <= bw_end and len(o[i]) >= 4]
        eb = [(d[i], o[i]) for i in range(len(d)) if week["eval_week"] <= d[i] <= ew_end and len(o[i]) >= 4]
        # 成交判定(僅買進週)
        fill, entry = p.get("fill"), p.get("entry")
        if not fill:
            for day, b in bb:
                op, hi, lo = b[0], b[1], b[2]
                if op <= p["buy"]: fill, entry = day, op; break
                if lo <= p["buy"]: fill, entry = day, p["buy"]; break
            if not fill:
                for day, b in bb:
                    if b[2] <= p["buy_hi"]: fill, entry = day, min(max(b[0], p["buy"]), p["buy_hi"]); break
        p["fill"], p["entry"] = fill, (round(entry, 2) if entry else None)
        if fill:
            held = [(day, b) for day, b in (bb + eb) if day >= fill]
            hi = max((b[1] for _, b in held), default=None)
            lo = min((b[2] for _, b in held), default=None)
            lastc = held[-1][1][3] if held else None
            p["hi"], p["lo"], p["last"], p["last_day"] = hi, lo, lastc, (held[-1][0] if held else None)
            p["hit_tp"] = bool(hi is not None and hi >= p["target"])
            p["hit_sl"] = bool(lo is not None and lo <= p["stop"])
            p["ret_c"] = round((lastc / entry - 1) * 100, 2) if (lastc and entry) else None
            xd, xp, xw, nheld = exit_scan(p, held, entry)
            done = bool(eb and (eb[-1][0] >= ew_end or eval_over))
            if xd:                                                    # 到目標/觸停損:當天就賣出
                p["xd"], p["xp"], p["xw"], p["hold"] = xd, round(xp, 2), xw, nheld
                p["ret"] = round((xp / entry - 1) * 100, 2)
                p["result"] = "win" if p["ret"] > 0 else ("loss" if p["ret"] < 0 else "flat")
            elif done:                                                # 到期:評估週最後收盤賣出
                p["xd"], p["xp"], p["xw"], p["hold"] = p["last_day"], lastc, "exp", len(held)
                p["ret"] = p["ret_c"]
                r = p["ret"] or 0
                p["result"] = "win" if r > 0 else ("loss" if r < 0 else "flat")
            else:                                                     # 持有中:ret 先用現有收盤浮動
                p["xd"] = p["xp"] = p["xw"] = None
                p["hold"] = len(held)
                p["ret"] = p["ret_c"]
                p["result"] = "pending"; all_done = False
        else:
            p["xd"] = p["xp"] = p["xw"] = p["hold"] = None
            if buy_week_over and (bb or TODAY > bw + dt.timedelta(days=9)):
                p["result"] = "nofill"
            else:
                p["result"] = "pending"; all_done = False
    week["xv"] = XVER
    if all_done and week["picks"]:
        week["status"] = "done"
    elif TODAY >= ew:
        week["status"] = "tracking"
    else:
        week["status"] = "open"


def stats_of(weeks):
    done = [w for w in weeks if w.get("status") == "done"]
    picks = [p for w in done for p in w["picks"]]
    filled = [p for p in picks if p.get("result") in ("win", "loss", "flat")]
    wins = [p for p in filled if p["result"] == "win"]; losses = [p for p in filled if p["result"] == "loss"]
    rets = [p["ret"] for p in filled if isinstance(p.get("ret"), (int, float))]
    wr = [p["ret"] for p in wins]; lr = [p["ret"] for p in losses]
    st = {"weeks": len(done), "n": len(picks), "filled": len(filled), "nofill": len([p for p in picks if p.get("result") == "nofill"]),
          "wins": len(wins), "losses": len(losses), "flat": len([p for p in filled if p["result"] == "flat"]),
          "win_rate": round(len(wins) / (len(wins) + len(losses)) * 100, 1) if (wins or losses) else None,
          "avg_ret": round(avg(rets), 2) if rets else None,
          "avg_win": round(avg(wr), 2) if wr else None, "avg_loss": round(avg(lr), 2) if lr else None,
          "best": max(rets) if rets else None, "worst": min(rets) if rets else None,
          "tp_rate": round(len([p for p in filled if p.get("hit_tp")]) / len(filled) * 100, 1) if filled else None,
          "sl_rate": round(len([p for p in filled if p.get("hit_sl")]) / len(filled) * 100, 1) if filled else None,
          "sum_ret": round(sum(rets), 2) if rets else None}
    hold = [p["hold"] for p in filled if isinstance(p.get("hold"), int)]
    retc = [p["ret_c"] for p in filled if isinstance(p.get("ret_c"), (int, float))]
    st["avg_hold"] = round(avg(hold), 1) if hold else None
    st["avg_ret_c"] = round(avg(retc), 2) if retc else None
    for k in ("tp", "sl", "exp"):
        st["x_" + k] = len([p for p in filled if p.get("xw") == k])
    xr = {k: [p["ret"] for p in filled if p.get("xw") == k and isinstance(p.get("ret"), (int, float))] for k in ("tp", "sl", "exp")}
    st["x_ret"] = {k: (round(avg(v), 2) if v else None) for k, v in xr.items()}
    # 每週小結(勝/檔/平均)
    st["by_week"] = []
    eq = 100.0; curve = []
    for w in done:
        fw = [p for p in w["picks"] if p.get("result") in ("win", "loss", "flat")]
        r = [p["ret"] for p in fw if isinstance(p.get("ret"), (int, float))]
        a = avg(r) if r else 0.0
        eq *= (1 + a / 100); curve.append(round(eq, 2))
        st["by_week"].append({"buy_week": w["buy_week"], "n": len(w["picks"]), "filled": len(fw),
                              "wins": len([p for p in fw if p["result"] == "win"]), "avg": round(a, 2) if r else None})
    st["equity"] = curve
    return st


# ───────────────────────── 主流程 ─────────────────────────
def main():
    data = load_json("data.json", {})
    if not data.get("stocks"):
        print("aipick:data.json 不可用,略過"); return
    J = load_json(OUT, {"model": MODEL, "weeks": [], "stats": {}})
    weeks = J.get("weeks") or []
    weeks = [w for w in weeks if isinstance(w, dict) and w.get("buy_week")]

    # 這一班應該存在的「買進週」
    wd = TODAY.weekday(); hm = NOW.hour * 60 + NOW.minute
    if (wd == 4 and hm >= 14 * 60 + 30) or wd >= 5:
        buy_week = monday(TODAY) + dt.timedelta(days=7)
    else:
        buy_week = monday(TODAY)
    force = os.environ.get("AIPICK_FORCE") == "1"
    learn_prev = J.get("learn") or {}
    rebuild_bt = os.environ.get("AIPICK_REBUILD_BT") == "1" or (weeks and not learn_prev)   # v1 檔升級 v2:回測重跑(含學習)
    if rebuild_bt:
        weeks = [w for w in weeks if not w.get("bt")]
    amax = learn_prev.get("alpha_max") or ALPHA_MAX
    tune_rep = learn_prev.get("tune") or []
    live_done = len([w for w in weeks if w.get("status") == "done" and not w.get("bt")])
    retune = rebuild_bt or (live_done and live_done % 4 == 0 and learn_prev.get("tuned_at_live") != live_done)   # 每累積 4 週實戰重調一次
    if not [w for w in weeks if w.get("bt")] or retune:   # 首次建檔/升級/定期重調:逐週回測(walk-forward,每週先用更早的週訓練再選股)+ 自動調參
        n_bt = int(os.environ.get("AIPICK_BACKFILL", "26") or 0)
        weeks = [w for w in weeks if not w.get("bt")]
        amax, bt_weeks, tune_rep = tune_alpha(data, n_bt)
        weeks += bt_weeks
        print(f"aipick:回測建檔 {len(bt_weeks)} 週(walk-forward 含學習)・自動調參 alpha_max={amax} {tune_rep}")
        learn_prev = dict(learn_prev, tuned_at_live=live_done, force_train=True); tuned_now = True
    else:
        tuned_now = False
    have = next((w for w in weeks if w["buy_week"] == iso(buy_week)), None)
    if force and have:
        weeks = [w for w in weeks if w is not have]; have = None; print("aipick:AIPICK_FORCE 重算本週")
    if not have:
        ok = True
        if wd == 4 and buy_week > monday(TODAY):   # 週五盤後:必須等到週五 K 入庫(以台積電為準)才選,否則留給下一班
            d, _ = bars_of("2330")
            if not d or d[-1] < iso(TODAY):
                ok = False; print(f"aipick:週五 K 尚未入庫(最新 {d[-1] if d else '無'}),本班不選股")
        if ok:
            L = build_learn(data, buy_week, amax=amax)
            w = gen_week(data, buy_week, L)
            if w["picks"]:
                weeks.append(w)
                print(f"aipick:選出 {w['buy_week']} 買進週 {len(w['picks'])} 檔(候選 {w['n_cand']}):" +
                      "、".join(f"{p['name']}@{p['buy']}" for p in w["picks"]))
            else:
                print("aipick:無符合標的,本週不選")
    # 逐週結算(已 done 的不再動,結果永久凍結)
    for w in weeks:
        if w.get("status") != "done" or w.get("xv") != XVER:      # r736:舊檔(只有收盤結算)重跑一次,補買賣時間與實現損益
            try: evaluate(w)
            except Exception as e: print("aipick:evaluate 失敗", w.get("buy_week"), e)
    weeks.sort(key=lambda w: w["buy_week"])
    weeks = weeks[-KEEP_WEEKS:]
    # 🧠 學習狀態:每班用「到今天已走完」的全部週重訓(下一次選股就用這組);記錄變化與檢討
    wk_key = iso(monday(TODAY))
    if learn_prev.get("wk") == wk_key and learn_prev.get("w") and not learn_prev.get("force_train"):
        learn = {k: v for k, v in learn_prev.items() if k not in ("force_train",)}   # 本週已訓練過:沿用(每班不重跑,省時)
    else:
        learn = build_learn(data, monday(TODAY) + dt.timedelta(days=14), amax=amax)   # 訓練集 = 評估週已走完的所有週
        learn["wk"] = wk_key
    learn["updated"] = NOW.strftime("%Y-%m-%d %H:%M"); learn["feats"] = FEATS
    learn["alpha_max"] = amax; learn["tune"] = tune_rep; learn["tuned_at_live"] = learn_prev.get("tuned_at_live", 0)
    log = list(learn_prev.get("log") or [])
    reviewed = set(learn_prev.get("reviewed") or [])
    for w in weeks:
        if w.get("status") == "done" and not w.get("bt") and w["buy_week"] not in reviewed:
            log.insert(0, {"t": NOW.strftime("%m-%d"), "k": "review", "msg": review_week(w)}); reviewed.add(w["buy_week"])
    if tune_rep and tuned_now:
        log.insert(0, {"t": NOW.strftime("%m-%d"), "k": "tune", "msg": "自動調參:" + " / ".join(f"α{r['alpha_max']}→勝率 {r['win_rate']}%・均 {r['avg_ret']:+}%" for r in tune_rep) + f";採用 α_max={amax}"})
    if learn.get("n") and learn.get("n") != learn_prev.get("n"):
        msg = f"重訓完成:樣本 {learn['n']:,}(上次 {learn_prev.get('n') or 0:,})・訓練集準確 {learn.get('acc')}%・模型權重 α={learn.get('alpha')}"
        if learn_prev.get("w") and learn.get("w"):
            dw = sorted(range(NF), key=lambda j: -abs(learn["w"][j] - learn_prev["w"][j]))[:2]
            msg += ";權重變化最大:" + "、".join(f"{FEATS[j]} {learn_prev['w'][j]:+.2f}→{learn['w'][j]:+.2f}" for j in dw)
        log.insert(0, {"t": NOW.strftime("%m-%d"), "k": "train", "msg": msg})
    learn["log"] = log[:40]; learn["reviewed"] = sorted(reviewed)[-80:]
    out = {"model": MODEL, "updated": NOW.strftime("%Y-%m-%d %H:%M"), "weeks": weeks, "learn": learn,
           "stats": stats_of([w for w in weeks if not w.get("bt")]),        # 實戰(凍結後追蹤)
           "stats_bt": stats_of([w for w in weeks if w.get("bt")])}         # 回測(首次建檔 walk-forward)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    st, sb = out["stats"], out["stats_bt"]
    print(f"aipick:完成 實戰 {st['weeks']} 週 勝率 {st['win_rate']}% 平均 {st['avg_ret']}% | 回測 {sb['weeks']} 週 勝率 {sb['win_rate']}% 平均 {sb['avg_ret']}%")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("aipick:例外", e); sys.exit(0)   # 絕不讓主流程失敗
