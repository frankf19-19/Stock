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
  ・換股(r738):5 檔改為「5 個倉位」,倉位出場後只要評估週還沒結束就從候補名單遞補下一檔,
              誰先出場誰先挑;隔一個交易日以開盤價進場,目標/停損依實際進場價等比例重錨;
              次數不設限,直到候補用完或評估週結束。倉位報酬 = 各段複利相乘
  ・每段都記錄「買進日/買進價 → 賣出日/賣出價/賣出原因/持有天數/實現損益」,統計以實際出場為準
"""
import json, os, sys, datetime as dt

# r890:市場參數化——AIPICK_MKT=US 時跑美股(S&P 500),其餘一律台股,台股行為完全不變
MKT = (os.environ.get("AIPICK_MKT") or "TW").upper()
US = MKT == "US"
if US:
    try:
        from zoneinfo import ZoneInfo
        TZ = ZoneInfo("America/New_York")
    except Exception:
        TZ = dt.timezone(dt.timedelta(hours=-4))
else:
    TZ = dt.timezone(dt.timedelta(hours=8))
BENCH_SID = "SPY" if US else "2330"
NOW = dt.datetime.now(TZ)
TODAY = NOW.date()
OUT = "aipick_us.json" if US else "aipick.json"
MODEL = "v2"
XVER = 4                      # r921:無期限模式;r738:結算版本(換股輪動;版本一變舊檔自動重跑)
N_PICK = 5
BENCH_N = 15                  # r738:候補名單長度——倉位出場後依序遞補,前端盤中可立刻提示換股
MAX_PER_SECTOR = 2
KEEP_WEEKS = 80


# ───────────────────────── 工具 ─────────────────────────
def monday(d):
    return d - dt.timedelta(days=d.weekday())


def iso(d):
    return d.isoformat()


def tick(px):
    """台股升降單位(美股一律 0.01)"""
    if US: return 0.01
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
    k = (str(sid)[0].lower() if US else shard_key(sid))
    if k not in _SH:
        p = f"k/us_{k}.json" if US else f"k/tw{k}.json"
        try:
            with open(p, encoding="utf-8") as f: _SH[k] = json.load(f)
        except Exception:
            _SH[k] = {}
    return _SH[k]


SETTLE_CUTOFF_H = 17 if US else 14        # 台北 14:00 前不採用當日 K 棒(13:30 收盤 + 緩衝)

def bars_of(sid):
    """r749:結算只用「已完成」的日 K。
    盤中的當日棒還在變動,拿它算成交與停損會把盤中瞬間凍進紀錄——
    2026-08-31 欣興跌停鎖死,當日棒塌成 o=h=l=c=999,結算就寫出「999 買進、同日 999 觸停損、0%」
    這種既不存在又美化績效的交易。規則:日期 < 今天才算;今天的棒要過 14:00 且不是退化棒才採用。"""
    e = shard(sid).get(sid)
    if not e or not isinstance(e.get("d"), list) or not isinstance(e.get("o"), list): return [], []
    d, o = e["d"], e["o"]
    n = min(len(d), len(o))
    d, o = d[:n], o[:n]
    if n and d[-1] == TODAY.isoformat():
        b = o[-1]
        degenerate = len(b) >= 4 and b[0] == b[1] == b[2] == b[3]
        if NOW.hour < SETTLE_CUTOFF_H or degenerate:
            return d[:-1], o[:-1]
    return d, o


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
    if not (last >= (5 if US else 10)): return None
    ma5, ma10, ma20, ma60 = avg(c[-5:]), avg(c[-10:]), avg(c[-20:]), avg(c[-60:])
    ma20p = avg(c[-25:-5])
    r5 = last / c[-6] - 1; r20 = last / c[-21] - 1; r60 = last / c[-61] - 1
    bias20 = last / ma20 - 1
    v5, v20 = avg(v[-5:]), avg(v[-20:])
    if v20 <= 0: return None
    vr = v5 / v20
    liq = avg([c[i] * v[i] for i in range(len(c) - 20, len(c))]) * (1 if US else 1000)   # 元/日(美股:美元,量為股數)
    if liq < (2e7 if US else 3e7): return None                           # 台股 3,000 萬元/日;美股 2,000 萬美元/日
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
    tgt, stp, lvl = stock_levels(d, o, buy, a, s)                      # r922:依個股壓力/支撐/波段習性定目標與停損(不再制式 +12%/-8%)
    meta = {"ref_close": round(last, 2), "ref_day": d[-1], "atr": round(a, 2), "buy": buy, "buy_hi": buy_hi,
            "target": tgt, "stop": stp, "kind": kind, "r20": round(r20 * 100, 1), "bias20": round(bias20 * 100, 1),
            "vr": round(vr, 2), "lvl": lvl}
    if lvl.get("rr") is not None and lvl["rr"] < 1.5: sc -= 8        # 賺賠比不到 1.5 的,分數扣一些(結構不利)
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
        if s.get("market") != MKT or s.get("etf"): continue
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
            "mu": [round(float(v), 5) for v in mu], "sd": [round(max(float(v), 1e-5), 5) for v in sd],   # r890:常數特徵(美股無籌碼/基本面)避免除以 0
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
        L = build_learn(data, bwk, amax=amax); L["_bt"] = True
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
        z += learn["w"][j] * (fx[j] - learn["mu"][j]) / (learn["sd"][j] or 1.0)
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


def _vol_weights(picks):
    """r936:依波動率給建議權重——波動小的配多一點(1/ATR%),總和 100%"""
    try:
        w = {p["id"]: 1.0 / max(0.005, (p.get("atr") or 0) / p["buy"]) for p in picks if p.get("buy")}
        tot = sum(w.values()) or 1
        return {k: round(100 * v / tot) for k, v in w.items()}
    except Exception:
        return {}


def chip_of(sid):
    """c/ 分片裡這檔的法人日資料(d/f/t/g)"""
    if "_CSH" not in globals(): globals()["_CSH"] = {}
    if MKT != "TW": return {}
    key = "tw" + (sid[:3] if sid[:2] == "00" else sid[:2])
    if key not in _CSH:
        try: _CSH[key] = load_json(f"c/{key}.json", {})
        except Exception: _CSH[key] = {}
    return _CSH[key].get(sid) or {}


def gen_week(data, buy_week, learn=None, reviews=None, exclude=None):
    """reviews:{sid: ai2}——由獨立步驟 aipick_review.py 產生;有就用在第三關排序(r943)
    exclude:r956 目前已持有(或掛單中)的股票——不再重複入選,由下一順位遞補"""
    exclude = set(exclude or [])
    cutoff = iso(buy_week)
    cands = []
    # r935:台股改用 v2(15 年訓練模型 + 過熱過濾);美股維持原模型(尚未用同套引擎驗證);回測週不用
    V2 = None
    # r955:美股也上 v2(規則篩選 + 美股重訓模型排序;回測驗證見 aipick_v2_model_us.json 的 backtest)
    _bt = bool((learn or {}).get("_bt"))
    if os.environ.get("AIPICK_V2", "1") == "1" and (not _bt or os.environ.get("AIPICK_V2_BT") == "1"):
        try:
            from aipick_v2 import V2Scorer
            V2 = V2Scorer(bars_of, chip_of, data, mkt=MKT, cutoff=cutoff)
            if not V2.ok: V2 = None
        except Exception as e:
            print("aipick:v2 載入失敗,改用原模型", e); V2 = None
    for s in data.get("stocks", []):
        if s.get("market") != MKT or s.get("etf") or s.get("disp"): continue
        if not (isinstance(s.get("price"), (int, float)) and s["price"] > 0): continue
        d, o = bars_of(s["id"])
        if not d: continue
        r = score_one(s, d, o, cutoff)
        if not r: continue
        sc, why, meta = r
        if V2:
            pv = V2.prob(s["id"], s, d, o)
            if pv is None: continue
            meta["v2p"] = round(pv, 4); meta["rule"] = round(sc, 1)
            sc = pv * 100                                             # v2:用「未來 10 日贏過大盤機率」排名
            why = [f"{'15' if MKT == 'TW' else '14'} 年模型:贏大盤機率 {pv * 100:.0f}%"] + list(why)[:3]
        cands.append((sc, s, why, meta))
    # 🧠 混合:規則分 z 值 ×(1−α)+ 學習模型 logit z 值 × α
    alpha = float((learn or {}).get("alpha") or 0.0)
    if V2: alpha = 0.0                                                   # v2 已經是模型分,不再混舊的學習權重
    if alpha > 0 and len(cands) > 5:
        base = [c[0] for c in cands]; lg = [model_logit(learn, c[3]["fx"]) for c in cands]
        def z(a):
            m = avg(a); sd = (avg([(x - m) ** 2 for x in a]) ** 0.5) or 1.0
            return [(x - m) / sd for x in a]
        zb, zl = z(base), z(lg)
        cands = [((1 - alpha) * zb[i] * 10 + alpha * zl[i] * 10 + 50, c[1], c[2], dict(c[3], ml=round(lg[i], 3), rule=round(c[0], 1)))
                 for i, c in enumerate(cands)]
    cands.sort(key=lambda x: -x[0])
    # r941:三關選股(台股 v2)——① 15 年模型取前 30 ② 加籌碼/分點綜合分重排取前 10 ③ AI 逐檔複核(產業/籌碼/時機),「保留」的往後排 → 前 5 + 候補 5
    #       同時記下「純量化」的前 5(alt_quant),大腦追蹤兩種選法的實際成績
    alt_quant = [c[1]["id"] for c in cands[:5]]
    if V2 and MKT == "TW" and len(cands) >= 10 and not V2.overheated:   # 三關的籌碼/分點/AI 複核只有台股資料
        try:
            top = cands[:30]
            def z(a):
                m = avg(a); sd = (avg([(x - m) ** 2 for x in a]) ** 0.5) or 1.0
                return [(x - m) / sd for x in a]
            zp = z([c[0] for c in top])
            ch = []
            for c in top:
                sid = c[1]["id"]; cs = ((c[1].get("c") or {}).get("score") or 50)
                bk = load_json(f"bk/tw{sid[:3] if sid[:2] == '00' else sid[:2]}.json", {}).get(sid) or {}
                SL = bk.get("s") or []; m5 = sum((x.get("m15") or 0) for x in SL[-5:] if isinstance(x, dict))
                _d, _o = bars_of(sid); v20 = (sum((b[4] or 0) for b in _o[-20:]) / 20) if len(_o) >= 20 else 1
                kbb = 1 if any((x[6] or "") >= iso(buy_week - dt.timedelta(days=10)) for x in ((bk.get("kb") or {}).get("b") or [])[:5]) else 0
                ch.append((cs - 50) / 15 + max(-2, min(2, m5 / v20 * 20)) + 0.5 * kbb)      # 籌碼分 + 分點主力 5 日淨買比 + 關鍵分點最近進場
            zc = z(ch)
            comp = [(zp[i] * 1.0 + 0.35 * zc[i], top[i]) for i in range(len(top))]
            comp.sort(key=lambda x: -x[0])
            short = [c for _, c in comp[:10]]
            # ③ AI 複核:不在這裡呼叫 AI(會超時),改用 aipick_review.py 事先做好的結果(reviews);沒有就只用前兩關
            rev = dict(reviews or {})
            shortlist = [c[1]["id"] for c in short]
            final = []
            for k, (cv, c) in enumerate(comp[:10]):
                j = rev.get(c[1]["id"]); pen = 0.0
                if j: pen = (0.6 if j.get("verdict") == "保留" else 0) + (0.2 if j.get("chip_verdict") == "偏空" else -0.1 if j.get("chip_verdict") == "偏多" else 0)
                meta = dict(c[3], comp=round(cv, 3), chip_z=round(zc[k] if k < len(zc) else 0, 2), ai2=j)
                final.append((cv - pen, c[1], c[2], meta))
            final.sort(key=lambda x: -x[0])
            cands = final + [c for c in cands if c[1]["id"] not in {f[1]["id"] for f in final}]
            globals()["_SHORTLIST"] = shortlist
            print(f"aipick:三關選股 → 量化前5 {alt_quant} / 綜合前5 {[c[1]['id'] for c in cands[:5]]} / AI 複核 {len(rev)} 檔(保留 {sum(1 for j in rev.values() if j.get('verdict') == '保留')})")
        except Exception as e:
            print("aipick:三關選股例外,改用純量化", e)
    picks, per = [], {}
    if V2 and V2.overheated:                                             # 過熱:全市場站上月線家數 > 70% → 本週不選股
        print(f"aipick:v2 過熱過濾——站上月線家數 {V2.breadth20 * 100:.0f}% > 70%,本週不選股")
        return {"buy_week": cutoff, "gen": NOW.strftime("%Y-%m-%d %H:%M"), "status": "skip", "picks": [], "bench": [], "n_cand": len(cands),
                "skip": f"市場過熱:全市場 {V2.breadth20 * 100:.0f}% 的股票站上月線(> 70%),這種週追高容易回檔,AI 選擇空手一週", "breadth20": round(V2.breadth20, 3), "v2": True}
    for sc, s, why, meta in cands:
        if s["id"] in exclude: continue                                    # r956:已持有/掛單中 → 不重複入選(只擋入選,不動排名與 cand_top)
        sec = s.get("sector") or "其他"
        if per.get(sec, 0) >= MAX_PER_SECTOR: continue
        per[sec] = per.get(sec, 0) + 1
        picks.append({"id": s["id"], "name": s.get("name") or s["id"], "sector": sec,
                      "score": round(sc, 1), "why": why, **meta,
                      "fill": None, "entry": None, "hi": None, "lo": None, "last": None, "last_day": None,
                      "ret": None, "ret_c": None, "hit_tp": False, "hit_sl": False, "result": "pending",
                      "xd": None, "xp": None, "xw": None, "hold": None})
        if len(picks) >= N_PICK: break
    # 🔄 r738:候補名單(名次接在正選之後)——倉位出場後依序遞補,產業上限在遞補當下才檢查
    pid = {p["id"] for p in picks}
    bench = []
    for sc, s, why, meta in cands:
        if s["id"] in pid or s["id"] in exclude: continue
        bench.append({"id": s["id"], "name": s.get("name") or s["id"], "sector": s.get("sector") or "其他",
                      "score": round(sc, 1), "why": why[:3], "kind": meta["kind"],
                      "buy": meta["buy"], "target": meta["target"], "stop": meta["stop"],
                      "ref_close": meta["ref_close"], "atr": meta["atr"]})
        if len(bench) >= BENCH_N: break
    ref_day = max((p["ref_day"] for p in picks), default=cutoff)
    return {"buy_week": cutoff, "eval_week": iso(buy_week + dt.timedelta(days=7)),
            "made": NOW.strftime("%Y-%m-%d %H:%M"), "ref_day": ref_day,
            "model": (learn or {}).get("ver") or "v1", "alpha": alpha, "learn_n": int((learn or {}).get("n") or 0),
            "status": "open", "picks": picks, "bench": bench, "n_cand": len(cands),
            "cand_top": [c[1]["id"] for c in cands[:max(10, len(cands) * 3 // 10)]],      # r935:前 30%(訊號轉弱判斷用;r921 漏掉了)
            "weights": _vol_weights(picks),                                                 # r936:建議權重(1/波動率)
            "alt_quant": alt_quant,                                                         # r941:純量化前 5(對照組)
            "shortlist": globals().get("_SHORTLIST") or [c[1]["id"] for c in cands[:10]],  # r943:前 10(給獨立複核步驟用)
            "reviews": dict(reviews or {}),
            "v2": bool(V2), "breadth20": round(V2.breadth20, 3) if V2 and V2.breadth20 is not None else None,
            "held_excl": sorted(exclude)}


# ───────────────────────── r956:跨週持股去重 ─────────────────────────
#   無期限模式下舊週倉位會一直留著,新名單/換股又選到同一檔 → 同一檔被持有 2~3 個倉位、資金過度集中。
#   規則:①新一週選股排除「目前持有中」與「掛單等成交」的股票;②換股時,別的倉位當天正持有的股票不換進。
#   只影響 EXCL_FROM 之後的決策——已發生的歷史紀錄不回頭改寫。
EXCL_FROM = "2026-10-05"
_WEEKS = []

def _held_elsewhere(sid, day, week):
    for w in _WEEKS:
        if w is week or w.get("bt"): continue
        for p in w.get("picks") or []:
            for L in p.get("legs") or []:
                if L.get("id") == sid and L.get("fill") and L["fill"] <= day and (not L.get("xd") or L["xd"] > day):
                    return True
    return False

def held_now(weeks):
    """目前持有中(最後一段未出場)+ 掛單等成交(未成交、未取消)的股票"""
    out = set()
    for w in weeks:
        if w.get("bt") or w.get("status") in ("done", "skip"): continue
        for p in w.get("picks") or []:
            legs = p.get("legs") or []
            if legs:
                if not legs[-1].get("xd"): out.add(legs[-1]["id"])
            elif p.get("result") not in ("nofill",) and not p.get("_nofill"):
                out.add(p["id"])
    return out


# ───────────────────────── 追蹤結算 ─────────────────────────
def exit_scan(p, held, entry):
    """成交後逐日找「實際出場」:先到目標→目標價賣、先到停損→停損價賣,同日兩者皆觸及採保守(停損先)。
    回傳 (出場日, 出場價, 原因 tp/sl, 持有天數);都沒碰到回傳 (None, None, None, 已持有天數)。"""
    tg, sp = p["target"], p["stop"]
    hi = entry; weak = p.get("weak_from")                   # r921:移動停利(漲 8% 後停損上移到高點 94%)/ 訊號轉弱出場
    for i, (day, b) in enumerate(held):
        op, hh, ll = b[0], b[1], b[2]
        if weak and day > weak:
            return day, op, "weak", i + 1
        if p.get("trail") and i > 0 and hi >= entry * 1.08:
            tsp = round(hi * 0.94, 2)
            if tsp > sp and ll <= tsp:
                return day, (op if op <= tsp else tsp), "trail", i + 1
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
        hi = max(hi, hh)
    return None, None, None, len(held)


def _pivots(o, win=4):
    """簡單波段轉折:win 根內最高/最低 → 壓力/支撐候選與波段幅度"""
    H = [b[1] for b in o]; L = [b[2] for b in o]; n = len(o)
    ph, pl = [], []
    for i in range(win, n - win):
        if H[i] >= max(H[i - win:i]) and H[i] >= max(H[i + 1:i + 1 + win]): ph.append((i, H[i]))
        if L[i] <= min(L[i - win:i]) and L[i] <= min(L[i + 1:i + 1 + win]): pl.append((i, L[i]))
    return ph, pl


def _vol_profile(o, bins=40):
    """量能密集區(近 120 日成交量集中的價位帶):上方是壓力、下方是支撐"""
    oo = [b for b in o[-120:] if len(b) >= 5 and b[4]]
    if len(oo) < 30: return []
    lo, hi = min(b[2] for b in oo), max(b[1] for b in oo)
    if hi <= lo: return []
    w = (hi - lo) / bins; acc = [0.0] * bins
    for b in oo:
        i0, i1 = int((b[2] - lo) / w), min(bins - 1, int((b[1] - lo) / w))
        for i in range(max(0, i0), i1 + 1): acc[i] += b[4] / (i1 - i0 + 1)
    tot = sum(acc) or 1
    top = sorted(range(bins), key=lambda i: -acc[i])[:3]
    return [(lo + (i + 0.5) * w, acc[i] / tot) for i in top if acc[i] / tot >= 0.06]


def _gaps(o):
    """未回補的跳空缺口:上方缺口 = 壓力(缺口下緣);下方缺口 = 支撐(缺口上緣)"""
    out = []; oo = o[-120:]
    for i in range(1, len(oo)):
        pv, cu = oo[i - 1], oo[i]
        if cu[2] > pv[1]:                                    # 向上跳空
            top, bot = cu[2], pv[1]
            if not any(x[2] <= bot for x in oo[i + 1:]): out.append(("down", top))   # 之後沒跌回 → 缺口上緣是支撐
        elif cu[1] < pv[2]:                                  # 向下跳空
            top, bot = pv[2], cu[1]
            if not any(x[1] >= top for x in oo[i + 1:]): out.append(("up", bot))     # 之後沒漲回 → 缺口下緣是壓力
    return out


def stock_levels(d, o, buy, a, s=None):
    """r922:每檔依自己的結構定目標/停損(回傳 目標, 停損, 說明)
    目標:買價上方「有意義的壓力」——20/60/250 日高點、近期波段高點;太近(<4%)就看下一道;
          上限參考這檔自己的波段習性(近一年上漲段中位數),大波動股允許更大目標、牛皮股目標較小
    停損:買價下方最近的支撐——20 日低、月線、季線、近期波段低點——再留 0.5 ATR 緩衝;
          但不會緊到 1.5 ATR 內(雜訊),也不會寬過 3 ATR / 15%
    賺賠比:目標距離至少是停損距離的 1.5 倍,不夠就把目標推到下一道壓力"""
    n = len(o); C = [b[3] for b in o]; H = [b[1] for b in o]; L = [b[2] for b in o]
    o250 = o[-250:]; ph, pl = _pivots(o250)
    ups, dns = [], []
    pts = sorted([(i, h, "h") for i, h in ph] + [(i, l, "l") for i, l in pl])
    for k in range(1, len(pts)):
        (i0, p0, t0), (i1, p1, t1) = pts[k - 1], pts[k]
        if t0 == "l" and t1 == "h" and p0 > 0: ups.append(p1 / p0 - 1)
        if t0 == "h" and t1 == "l" and p0 > 0: dns.append(1 - p1 / p0)
    up_med = sorted(ups)[len(ups) // 2] if len(ups) >= 4 else 0.10
    dn_med = sorted(dns)[len(dns) // 2] if len(dns) >= 4 else 0.08
    ma20 = sum(C[-20:]) / 20; ma60 = sum(C[-60:]) / 60 if n >= 60 else None
    # ── 壓力候選(買價上方)
    res = []
    for lab, v in (("20 日高", max(H[-20:])), ("60 日高", max(H[-60:]) if n >= 60 else None), ("年高", max(H[-250:]))):
        if v and v > buy * 1.005: res.append((v, lab))
    for i, h in ph[-6:]:
        if h > buy * 1.005: res.append((h, f"波段高 {d[-len(o250) + i][5:]}"))
    vp = _vol_profile(o); gp = _gaps(o)                                  # r923:量能密集區、未補缺口
    for v, share in vp:
        if v > buy * 1.005: res.append((v, f"量能密集區({share * 100:.0f}% 成交)"))
    for kind, v in gp:
        if kind == "up" and v > buy * 1.005: res.append((v, "上方缺口"))
    res.sort()
    tmax = buy * (1 + min(0.35, max(0.06, 1.2 * up_med)))     # 這檔的「合理一段行情」
    fsc = ((s or {}).get("f") or {}).get("score") if s else None   # r923:基本面強 → 目標可以放遠;弱 → 收斂
    csc = ((s or {}).get("c") or {}).get("score") if s else None   #       籌碼強 → 停損可用較遠支撐;弱 → 緊一點
    if isinstance(fsc, (int, float)) and fsc != 50: tmax *= 1.15 if fsc >= 70 else 0.88 if fsc <= 40 else 1.0
    pe, eps = (s or {}).get("pe"), (s or {}).get("eps")               # 估值天花板:本益比已 > 35 倍的,目標不超過 eps×(本益比+8)
    if isinstance(pe, (int, float)) and isinstance(eps, (int, float)) and pe > 35 and eps > 0:
        tmax = min(tmax, max(buy * 1.05, eps * (pe + 8)))
    tgt = None; tsrc = ""
    for v, lab in res:
        if v >= buy * 1.04 and v <= tmax: tgt, tsrc = v, lab; break
    if tgt is None:
        far = [r for r in res if r[0] > tmax]
        tgt, tsrc = (min(tmax, far[0][0]), "波段習性上限") if far else (max(buy * 1.06, buy + 2.0 * a), "2 倍 ATR")
    # ── 支撐候選(買價下方)
    sup = []
    for lab, v in (("20 日低", min(L[-20:])), ("月線", ma20), ("季線", ma60)):
        if v and v < buy * 0.995: sup.append((v, lab))
    for i, l in pl[-6:]:
        if l < buy * 0.995: sup.append((l, f"波段低 {d[-len(o250) + i][5:]}"))
    for v, share in vp:
        if v < buy * 0.995: sup.append((v, f"量能密集區({share * 100:.0f}% 成交)"))
    for kind, v in gp:
        if kind == "down" and v < buy * 0.995: sup.append((v, "下方缺口"))
    sup.sort(reverse=True)
    smin, smax = buy - 1.5 * a, max(buy - 2.5 * a, buy * 0.90)
    if isinstance(csc, (int, float)) and csc <= 40: smax = max(buy - 2.0 * a, buy * 0.92)   # 籌碼弱:停損不給太寬
    stp = None; ssrc = ""
    for v, lab in sup:
        v2 = v - 0.5 * a
        if smax <= v2 <= smin: stp, ssrc = v2, lab + " 下方"; break
    if stp is None:
        near = [x for x in sup if x[0] - 0.5 * a > smin]
        stp, ssrc = (smin, "1.5 倍 ATR") if near else (max(smax, buy - 2.0 * a), "2 倍 ATR")
    # ── 賺賠比至少 1.5
    risk = buy - stp
    if risk > 0 and (tgt - buy) < 1.5 * risk:
        nxt = [r for r in res if r[0] >= buy + 1.5 * risk and r[0] <= buy * 1.35]
        if nxt: tgt, tsrc = nxt[0][0], nxt[0][1] + "(補足賺賠比)"
        else: tgt, tsrc = buy + 1.5 * risk, "1.5 倍風險"
    tgt = rtick(tgt, "near"); stp = rtick(stp, "near")
    rr = round((tgt - buy) / (buy - stp), 2) if buy > stp else None
    lvl = {"tgt_src": tsrc, "stp_src": ssrc, "rr": rr, "up_med": round(up_med * 100, 1), "dn_med": round(dn_med * 100, 1),
           "why": f"目標 {tgt}({tsrc},+{(tgt / buy - 1) * 100:.1f}%)/ 停損 {stp}({ssrc},{(stp / buy - 1) * 100:.1f}%)/ 賺賠比 {rr}"}
    return tgt, stp, lvl


def _leg(src, sid, name, sector, fill, entry, tgt, stp, score=None, kind=None):
    return {"id": sid, "name": name, "sector": sector, "src": src, "score": score, "kind": kind,
            "fill": fill, "entry": round(entry, 2), "target": tgt, "stop": stp,
            "xd": None, "xp": None, "xw": None, "hold": None, "ret": None, "ret_c": None,
            "last": None, "last_day": None}


def _apply_weak(p, leg):
    wk = p.get("weak")
    if wk and wk.get("id") == leg["id"] and not leg.get("xd"): leg["weak_from"] = wk["from"]
    return leg


def _run_leg(leg, ew_end, eval_over):
    """把一段部位從成交日跑到出場或視窗結束。回傳 True = 已出場。"""
    if ew_end == FAR: leg["trail"] = 1                      # r921:無期限模式 → 開移動停利
    d, o = bars_of(leg["id"])
    held = [(d[i], o[i]) for i in range(len(d)) if leg["fill"] <= d[i] <= ew_end and len(o[i]) >= 4]
    if not held: return False
    lastc, lastd = held[-1][1][3], held[-1][0]
    leg["last"], leg["last_day"] = lastc, lastd
    leg["ret_c"] = round((lastc / leg["entry"] - 1) * 100, 2) if leg["entry"] else None
    leg["hi"] = max(b[1] for _, b in held); leg["lo"] = min(b[2] for _, b in held)
    scan = held[1:] if leg.get("same_day") else held          # r918:盤中即時換股的那檔,進場當天不用整根日K判斷出場
    xd, xp, xw, n = exit_scan(leg, scan, leg["entry"]) if scan else (None, None, None, 0)
    if xd and leg.get("same_day"): n += 1
    if xd:
        leg.update(xd=xd, xp=round(xp, 2), xw=xw, hold=n, ret=round((xp / leg["entry"] - 1) * 100, 2))
        return True
    if ew_end != FAR and (lastd >= ew_end or eval_over):  # 到期(只有回測週;實戰無期限,r921)
        leg.update(xd=lastd, xp=lastc, xw="exp", hold=len(held), ret=leg["ret_c"])
        return True
    leg["hold"] = len(held)
    leg["ret"] = leg["ret_c"]
    return False


def _has_day_after(day, ew_end):
    """day 之後、視窗內還有沒有交易日(以台積電日曆為準)。"""
    d, _ = bars_of(BENCH_SID)
    return any(day < x <= ew_end for x in d)


# ═══ r786:成交/出場的「幾點幾分」——像交易員的對帳單 ═══
# 日 K 只能判定「這一天成交」;幾點成交要看 1 分 K。富果 1 分 K 走站上的 Worker 代理(共用 key),
# 每筆成交/出場只查一次、結果存進 leg(ft/xt),之後不再查。到期出場固定 13:30。
WORKER = "https://muddy-cake-cb69.frankccc199.workers.dev"
_MIN_CACHE = {}
def _minutes(sid, date):
    """回傳當日 1 分 K [(HH:MM, o, h, l, c), ...] 升冪;抓不到回 []。"""
    key = (sid, date)
    if key in _MIN_CACHE: return _MIN_CACHE[key]
    out = []
    try:
        import requests, time as _t
        if date == iso(TODAY):
            api = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{sid}?timeframe=1"
        else:
            api = f"https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{sid}?timeframe=1&fields=open,high,low,close&sort=asc"
        r = requests.get(f"{WORKER}/fgl", params={"u": api}, timeout=20,
                         headers={"Referer": "https://frankf19-19.github.io/Stock/", "Origin": "https://frankf19-19.github.io"})   # r808
        _t.sleep(1.1)
        if r.ok:
            for x in (r.json().get("data") or []):
                ds = str(x.get("date") or "")
                if not ds.startswith(date): continue
                hm = ds[11:16]
                try: out.append((hm, float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"])))
                except Exception: pass
            out.sort()
    except Exception:
        out = []
    _MIN_CACHE[key] = out
    return out


# ═══ r787:盤中「當下記」——交易員的對帳單不是收盤後回頭補的 ═══
# 盤中 5 分鐘迴圈每輪拿 data.json 的即時價:第一次碰到買價/追價區/目標/停損,就把「日期・時間・價格」記進
# p["iv"](intraday)。收盤後日 K 結算出同一天的成交/出場時,直接沿用這個時間;沒記到的(網站沒跑那輪)
# 才退回查富果 1 分 K。這樣時間是「當下」的,結算價仍以日 K 為準(凍結不動)。
def intraday_watch(weeks, prices, hhmm):
    n = 0
    today = iso(TODAY)
    for w in weeks:
        if w.get("bt") or w.get("status") == "done": continue
        bw = w["buy_week"]; bw_end = iso(dt.date.fromisoformat(bw) + dt.timedelta(days=4))
        for p in w.get("picks") or []:
            iv = p.setdefault("iv", {})
            legs = p.get("legs") or []
            cur = legs[-1] if legs else None
            if cur and cur.get("xd"): continue                          # 已收工
            sid = cur["id"] if cur else p["id"]
            px = prices.get(sid)
            if not px: continue
            if not cur:                                                 # 等買進:限價/追價第一次碰到
                if (w.get("mode") == "open" and (today < bw or iv.get("fill") or p.get("result") == "nofill")) or (w.get("mode") != "open" and (not (bw <= today <= bw_end) or iv.get("fill"))): continue
                if px <= p["buy"]:
                    iv["fill"] = {"d": today, "t": hhmm, "px": p["buy"], "how": "limit"}; n += 1
                elif px <= p.get("buy_hi", p["buy"]):
                    iv["fill"] = {"d": today, "t": hhmm, "px": px, "how": "chase"}; n += 1
            else:                                                       # 持有中:目標/停損第一次碰到
                if iv.get("exit") and iv["exit"].get("leg") == len(legs) - 1: continue
                if px >= cur["target"]:
                    iv["exit"] = {"d": today, "t": hhmm, "px": cur["target"], "w": "tp", "leg": len(legs) - 1, "id": sid}; n += 1
                elif px <= cur["stop"]:
                    iv["exit"] = {"d": today, "t": hhmm, "px": cur["stop"], "w": "sl", "leg": len(legs) - 1, "id": sid}; n += 1
    return n


def apply_intraday_times(weeks):
    """結算出的 leg 若跟盤中記錄同一天,時間直接沿用(不必查富果)。"""
    n = 0
    for w in weeks:
        if w.get("bt"): continue
        for p in w.get("picks") or []:
            iv = p.get("iv") or {}
            legs = p.get("legs") or []
            f = iv.get("fill")
            if f and legs and legs[0].get("fill") == f["d"] and not legs[0].get("ft"):
                legs[0]["ft"] = f["t"]; n += 1
            x = iv.get("exit")
            if x and legs:
                li = x.get("leg", len(legs) - 1)
                if li < len(legs) and legs[li].get("xd") == x["d"] and legs[li].get("xw") == x.get("w") and not legs[li].get("xt"):
                    legs[li]["xt"] = x["t"]; n += 1
    return n


def stamp_times(weeks, budget=12):
    """補上 ft(成交時間)/ xt(出場時間)。每班最多 budget 次查詢,沒補到的下一班再補。"""
    n = 0
    for w in weeks:
        if w.get("bt"): continue
        for p in w.get("picks") or []:
            for L in p.get("legs") or []:
                if L.get("fill") and not L.get("ft"):
                    if n >= budget: return n
                    ms = _minutes(L["id"], L["fill"]); n += 1
                    if ms:
                        if L.get("src") == "bench":
                            L["ft"] = ms[0][0]                                   # 換股是隔日開盤市價進場
                        elif ms[0][1] <= L["entry"] + 1e-9:
                            L["ft"] = ms[0][0]                                   # 跳空開在買價下 → 開盤成交
                        else:
                            hit = next((m for m in ms if m[3] <= L["entry"] + 1e-9), None)
                            L["ft"] = hit[0] if hit else ms[-1][0]
                if L.get("xd") and not L.get("xt"):
                    if L.get("xw") == "exp":
                        L["xt"] = "13:30"; continue
                    if n >= budget: return n
                    ms = _minutes(L["id"], L["xd"]); n += 1
                    if ms:
                        lvl = L["target"] if L["xw"] == "tp" else L["stop"]
                        same_day = (L["xd"] == L["fill"])
                        pool = ms
                        if same_day and L.get("ft"):
                            pool = [m for m in ms if m[0] >= L["ft"]] or ms     # 成交之後才可能出場
                        if L["xw"] == "tp": hit = next((m for m in pool if m[2] >= lvl - 1e-9), None)
                        else: hit = next((m for m in pool if m[3] <= lvl + 1e-9), None)
                        if pool and pool[0][1] and ((L["xw"] == "tp" and pool[0][1] >= lvl) or (L["xw"] == "sl" and pool[0][1] <= lvl)):
                            L["xt"] = pool[0][0]                                # 跳空開在目標/停損外 → 開盤出場
                        else:
                            L["xt"] = hit[0] if hit else pool[-1][0]
    return n


def _open_at(sid, after_day, ew_end):
    """出場日之後的第一個交易日(以該股自己的 K 為準);回傳 (日期, 開盤價) 或 None。"""
    d, o = bars_of(sid)
    for i in range(len(d)):
        if d[i] > after_day and d[i] <= ew_end and len(o[i]) >= 4 and o[i][0] and o[i][0] > 0:
            return d[i], o[i][0]
    return None


def _fill_px(b, p):
    """單日的成交價;沒成交回 None。
    r750:原本拆成「限價」與「追價」兩個迴圈,追價那圈用 max(開盤, 買價),
    會把「整天都在買價之下」的跳空日硬拉到買價成交(2026-08-31 欣興跌停鎖死 999 卻算成 1145 進場)。
    改成單一判定,三種情形互斥:"""
    if b[0] <= p["buy"]: return b[0]                                  # 跳空開在買價之下 → 以開盤價成交
    if b[2] <= p["buy"]: return p["buy"]                              # 盤中回到買價 → 限價成交
    if b[2] <= p["buy_hi"]: return min(b[0], p["buy_hi"])             # 只進到追價區 → 追價上限內成交
    return None


FAR = "2099-12-31"
def evaluate(week):
    bw = dt.date.fromisoformat(week["buy_week"]); ew = bw + dt.timedelta(days=7)
    bw_end = iso(bw + dt.timedelta(days=4)); ew_end = iso(ew + dt.timedelta(days=4))
    buy_week_over = TODAY > bw + dt.timedelta(days=6)
    eval_over = TODAY > ew + dt.timedelta(days=6)     # 評估週之後的週一起一定結算
    # r921:實戰(非回測)改成「無期限」——沒有到期賣出、買進也不限一週;
    #      出場只由訊號決定:到目標 / 觸停損 / 移動停利 / 訊號轉弱(排名掉出前 30% 且跌破月線)
    if not week.get("bt"):
        week["mode"] = "open"
        bw_end, ew_end = FAR, FAR
        buy_week_over = False; eval_over = False
        nw = week.get("_next_ids")                     # 下一週名單出來後,沒進名單的舊掛單取消(排名已掉)
        if nw is not None and TODAY > bw + dt.timedelta(days=6):
            for p in week["picks"]:
                if not (p.get("legs") or []) and not (p.get("iv") or {}).get("fill") and p["id"] not in nw: p["_cancel"] = 1
    bench = list(week.get("bench") or [])
    picks = week["picks"]

    # ── 第一段:買進週限價成交 ──
    for p in picks:
        d, o = bars_of(p["id"])
        bb = [(d[i], o[i]) for i in range(len(d)) if week["buy_week"] <= d[i] <= bw_end and len(o[i]) >= 4]
        fill = entry = None
        for day, b in bb:
            e = _fill_px(b, p)
            if e is None: continue
            if e <= p["stop"]: continue      # r750:進場價已在停損之下 → 訊號失效,這天不成交,繼續往後找
            fill, entry = day, e; break
        if fill:
            p["legs"] = [_leg("pick", p["id"], p["name"], p.get("sector"), fill, entry,
                              p["target"], p["stop"], p.get("score"), p.get("kind"))]
            _run_leg(_apply_weak(p, p["legs"][0]), ew_end, eval_over)
        else:
            p["legs"] = []
        p["_nofill"] = bool(not fill and (p.pop("_cancel", 0) or (buy_week_over and (bb or TODAY > bw + dt.timedelta(days=9)))))

    # ── 🔄 換股輪動:誰先出場誰先挑候補,次數不設限 ──
    used = {p["id"] for p in picks}
    bi = 0
    while bench:
        pick_slot = None
        for si, p in enumerate(picks):
            lg = p["legs"][-1] if p["legs"] else None
            if not lg or not lg["xd"] or lg["xw"] == "exp" or lg.get("_rot"): continue
            key = (lg["xd"], si)
            if pick_slot is None or key < pick_slot[0]: pick_slot = (key, p, lg)
        if not pick_slot: break
        _, p, lg = pick_slot
        lg["_rot"] = 1                                    # 這一段已試過換股,不論成不成功都不再回頭
        nxt = None
        rot = (p.get("iv") or {}).get("rot")              # r918:即時換股(盤中出場當下就接替,不等隔日開盤)
        if rot and rot.get("d") == lg["xd"] and rot["id"] not in used and rot.get("px") \
                and not (lg["xd"] >= EXCL_FROM and _held_elsewhere(rot["id"], lg["xd"], week)):
            en = float(rot["px"])
            leg = _leg("bench", rot["id"], rot.get("name"), rot.get("sector"), rot["d"], en,
                       rtick(en * float(rot.get("rr") or 1.0), "near"), rtick(en * float(rot.get("rs") or 1.0), "near"), rot.get("score"), rot.get("kind"))
            leg["same_day"] = 1; leg["ft"] = rot.get("t")
            p["legs"].append(leg); used.add(rot["id"])
            _run_leg(_apply_weak(p, leg), ew_end, eval_over)
            continue
        while bi < len(bench):
            b = bench[bi]; bi += 1
            if b["id"] in used: continue
            if lg["xd"] >= EXCL_FROM and _held_elsewhere(b["id"], lg["xd"], week): continue   # r956:別的倉位正持有 → 不重複換進
            openn = sum(1 for q in picks for L in q["legs"]                 # 同時持有的同產業檔數上限
                        if L.get("sector") == b.get("sector") and L["fill"] <= lg["xd"] and (not L["xd"] or L["xd"] > lg["xd"]))
            if openn >= MAX_PER_SECTOR: continue
            nxt = b; break
        if not nxt: break
        if week.get("mode") == "open" and lg["xd"] > iso(bw + dt.timedelta(days=13)): continue   # r921:出場太晚就不換股,交給新一週名單
        nd = _open_at(nxt["id"], lg["xd"], ew_end)
        if not nd: continue                               # 沒有下一個交易日了(視窗已到尾)
        day, en = nd
        if not _has_day_after(day, ew_end):               # r786:評估週最後一個交易日不再換股進場——買了當天收盤就得賣,不是交易員會做的事
            continue
        rr = (nxt["target"] / nxt["buy"]) if nxt["buy"] else 1.0           # 目標/停損依實際進場價等比例重錨,維持原本風報比
        rs = (nxt["stop"] / nxt["buy"]) if nxt["buy"] else 1.0
        leg = _leg("bench", nxt["id"], nxt["name"], nxt.get("sector"), day, en,
                   rtick(en * rr, "near"), rtick(en * rs, "near"), nxt.get("score"), nxt.get("kind"))
        p["legs"].append(leg); used.add(nxt["id"])
        _run_leg(_apply_weak(p, leg), ew_end, eval_over)

    # ── 倉位彙總:報酬 = 各段複利相乘 ──
    all_done = True
    for p in picks:
        legs = p["legs"]
        for L in legs: L.pop("_rot", None)
        p["rot"] = max(0, len(legs) - 1)
        if not legs:
            p.update(fill=None, entry=None, hi=None, lo=None, last=None, last_day=None,
                     ret=None, ret_c=None, hit_tp=False, hit_sl=False, xd=None, xp=None, xw=None, hold=None)
            p["result"] = "nofill" if p.pop("_nofill", False) else "pending"
            if p["result"] == "pending": all_done = False
            continue
        p.pop("_nofill", None)
        f, z = legs[0], legs[-1]
        p["fill"], p["entry"] = f["fill"], f["entry"]
        p["xd"], p["xp"], p["xw"] = z["xd"], z["xp"], z["xw"]
        p["last"], p["last_day"] = z["last"], z["last_day"]
        p["hi"], p["lo"] = f.get("hi"), f.get("lo")
        p["hold"] = sum(L["hold"] or 0 for L in legs)
        eqm = 1.0
        for L in legs: eqm *= 1 + (L["ret"] or 0) / 100.0
        p["ret"] = round((eqm - 1) * 100, 2)
        p["ret_c"] = p["ret"]
        p["hit_tp"] = any(L["xw"] == "tp" for L in legs)
        p["hit_sl"] = any(L["xw"] == "sl" for L in legs)
        if z["xd"]:
            p["result"] = "win" if p["ret"] > 0 else ("loss" if p["ret"] < 0 else "flat")
        else:
            p["result"] = "pending"; all_done = False

    week["xv"] = XVER
    week["rot"] = sum(p.get("rot") or 0 for p in picks)
    if week.get("skip"):
        week["status"] = "skip"                                  # r935:過熱空手週,狀態固定
    elif all_done and picks:
        week["status"] = "done"
    elif TODAY >= ew:
        week["status"] = "tracking"
    else:
        week["status"] = "open"


def week_benchmark(data, w):
    """同一持有視窗(買進週第一個交易日收盤 → 評估週最後交易日收盤)全台股報酬的中位數。
    站內沒有指數序列;用「隨便挑一檔的典型結果」當對照,比大盤更直接回答模型有沒有選股能力。"""
    bw = w["buy_week"]; bw_end = iso(dt.date.fromisoformat(bw) + dt.timedelta(days=4))
    ew_end = iso(dt.date.fromisoformat(w["eval_week"]) + dt.timedelta(days=4))
    rets = []
    for s in data.get("stocks", []):
        if s.get("market") != MKT or s.get("etf"): continue
        d, o = bars_of(s["id"])
        if len(d) < 30: continue
        i0 = next((i for i, x in enumerate(d) if x >= bw), None)
        if i0 is None or d[i0] > bw_end: continue
        i1 = None
        for i in range(len(d) - 1, i0, -1):
            if d[i] <= ew_end: i1 = i; break
        if i1 is None: continue
        c0, c1 = (o[i0][3] if len(o[i0]) >= 4 else None), (o[i1][3] if len(o[i1]) >= 4 else None)
        if c0 and c1: rets.append((c1 / c0 - 1) * 100)
    if len(rets) < 50: return None
    rets.sort()
    return round(rets[len(rets) // 2], 2)


# ───────────────────────── 🤖 入選/出場理由(Gemini,純敘述,不影響選股與結算)─────────────────────────
_G = {"n": 0}
GEMINI_KEY = os.environ.get("GEMINI_KEY", "").strip()
GEMINI_MODEL = "gemini-2.5-flash"
AI_BUDGET = 12                 # 每班最多幾次呼叫(免費層節流;沒用完留給下一班)

def _ai_ok(txt):
    """r774:理由必須是完整句子——被截斷的(「欣興(3037)被」)不能存,否則永遠不會重生。"""
    t = (txt or "").strip()
    return len(t) >= 20 and t[-1] in "。!?.)」)"

def _gemini(prompt, max_tokens=400):
    if not GEMINI_KEY or _G["n"] >= AI_BUDGET: return ""
    import time as _t, requests
    if _G["n"] > 0: _t.sleep(6)
    _G["n"] += 1
    # r774:2.5 Flash 預設會「思考」,thinking token 算在 maxOutputTokens 裡——220 被想掉大半,
    #      剩幾個 token 只夠寫出股票名就斷。關掉思考(這種摘要不需要),配額拉到 400,並檢查 finishReason。
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.4,
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    # r956:額度用完(429)或模型下架(404)就換模型——8/31 起出場理由全數空白、10/05 名單入選理由 0/5,原因是只打單一模型
    for attempt, mdl in enumerate([GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-2.0-flash"]):
        try:
            if mdl.startswith("gemini-2.0"): body["generationConfig"].pop("thinkingConfig", None)   # 2.0 不認 thinkingConfig
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={GEMINI_KEY}",
                              json=body, timeout=60)
            if r.status_code in (429, 500, 503, 404): print(f"  gemini 理由 {mdl} {r.status_code},換模型"); _t.sleep(6); continue
            if not r.ok:
                print(f"  gemini 理由 {mdl} 錯誤 {r.status_code}:{r.text[:160]}")
                if "thinking" in str(r.text): body["generationConfig"].pop("thinkingConfig", None)
                continue
            cand = (r.json().get("candidates") or [{}])[0]
            ps = (cand.get("content") or {}).get("parts") or []
            txt = "".join(p.get("text", "") for p in ps).strip().replace("\n", " ")
            if cand.get("finishReason") == "MAX_TOKENS" and attempt == 0:  # 還是不夠 → 加倍再試一次
                body["generationConfig"]["maxOutputTokens"] = max_tokens * 2; continue
            return txt[:300] if _ai_ok(txt) else ""
        except Exception:
            _t.sleep(10)
    return ""

_RULES = "用繁體中文寫,語氣像交易員筆記,只能引用我給的數字,不要加任何我沒給的資訊,不要說「建議買進」這類話,不要用驚嘆號。"

AI2_BUDGET = 24
_G2 = {"n": 0}

def _gemini_raw(prompt, max_tokens=900, search=False, json_schema=None):
    """r939:深度複核用——可開 Google 搜尋(研究)或結構化 JSON(分析),兩者不能同時"""
    if not GEMINI_KEY or _G2["n"] >= AI2_BUDGET: return ""
    import time as _t, requests
    if _G2["n"] > 0: _t.sleep(4)
    _G2["n"] += 1
    gc = {"maxOutputTokens": max_tokens, "temperature": 0.4}
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gc}
    if search: body["tools"] = [{"google_search": {}}]
    if json_schema: gc["responseMimeType"] = "application/json"; gc["responseSchema"] = json_schema; gc["thinkingConfig"] = {"thinkingBudget": 2048}
    # r946:429(額度用完)就換模型——flash → flash-lite → 2.0-flash 各自有獨立額度
    for attempt, mdl in enumerate([GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-2.0-flash", GEMINI_MODEL]):
        try:
            if json_schema and mdl == "gemini-2.0-flash": body["generationConfig"].pop("thinkingConfig", None)
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={GEMINI_KEY}", json=body, timeout=90)
            if r.status_code in (429, 500, 503, 404): print(f"  gemini {mdl} {r.status_code},換模型/重試"); _t.sleep(6 if attempt < 4 else 30); continue
            if not r.ok: print(f"  gemini 錯誤 {r.status_code}:{r.text[:300]}"); return ""
            j = r.json(); cand = (j.get("candidates") or [{}])[0]
            txt = "".join(p.get("text", "") for p in ((cand.get("content") or {}).get("parts") or []) if not p.get("thought")).strip()
            if not txt: print(f"  gemini 空回應:{str(j)[:300]}")
            return txt
        except Exception as e:
            print(f"  gemini 例外:{e}"); _t.sleep(10)
    return ""

def chip_digest(sid, s):
    """r940:把這檔的籌碼資料整理成白話(法人、大戶、融資、分點主力、關鍵分點),給 AI 複核用"""
    L = []
    try:
        kv = ((s.get("c") or {}).get("kv") or {})
        if kv: L.append("法人:" + "、".join(f"{k} {v}" for k, v in kv.items()))
        c = chip_of(sid) or {}
        bp, bd = c.get("bp") or [], c.get("bd") or []
        if len(bp) >= 5: L.append(f"400 張以上大戶持股:{bp[-1]}%(4 週前 {bp[-5]}%,變化 {bp[-1] - bp[-5]:+.2f} 個百分點)")
        mf = [x for x in (c.get("mf") or []) if x is not None]
        if len(mf) >= 20: L.append(f"融資餘額:{mf[-1]:,} 張(20 日前 {mf[-20]:,},{(mf[-1] / mf[-20] - 1) * 100:+.1f}%)")
        f = c.get("f") or []; t = c.get("t") or []
        if len(f) >= 3:
            st = 0
            for x in reversed(f):
                if (x or 0) > 0: st += 1
                else: break
            if st >= 2: L.append(f"外資已連買 {st} 天")
            st = 0
            for x in reversed(t):
                if (x or 0) > 0: st += 1
                else: break
            if st >= 2: L.append(f"投信已連買 {st} 天")
        key = "tw" + (sid[:3] if sid[:2] == "00" else sid[:2])
        bk = load_json(f"bk/{key}.json", {}).get(sid) or {}
        SL = bk.get("s") or []; DL = bk.get("d") or []
        S = SL[-1] if isinstance(SL, list) and SL and isinstance(SL[-1], dict) else {}
        if S:
            m5 = sum((x.get("m15") or 0) for x in SL[-5:] if isinstance(x, dict))
            L.append(f"分點({DL[-1] if DL else ''}):主力 15 大分點今日淨買 {S.get('m15', 0):+,} 張、近 5 日累計 {m5:+,} 張、買方家數 {S.get('nb')} / 賣方 {S.get('ns')}、集中度 {S.get('conc')}%")
            if S.get("b"): L.append("今日買超前 5 分點:" + "、".join(f"{x[0]} +{x[1]:,} 張@{x[2]}" for x in S["b"][:5]))
            if S.get("s"): L.append("今日賣超前 5 分點:" + "、".join(f"{x[0]} {x[1]:,} 張@{x[2]}" for x in S["s"][:5]))
            if S.get("dt"): L.append("短沖分點(當沖為主,不算主力):" + "、".join(S["dt"][:4]))
        kb = bk.get("kb") or {}
        if kb.get("b"):
            L.append("這檔的關鍵分點(歷史上進場後勝率高,看它們有沒有再進場):" + "、".join(f"{x[0]}(進場後 20 日平均 {x[4]:+.1f}%、勝率 {x[5]}%,最近進場 {x[6]})" for x in kb["b"][:3]))
        if kb.get("s"):
            L.append("歷史上出場訊號準的分點:" + "、".join(f"{x[0]}(最近出場 {x[6]})" for x in kb["s"][:3]))
    except Exception as e:
        L.append(f"(籌碼整理例外 {e})")
    return "\n".join(L) if L else "(無籌碼資料)"


AI2_SCHEMA = {"type": "OBJECT", "properties": {
    "verdict": {"type": "STRING"}, "thesis": {"type": "STRING"}, "industry": {"type": "STRING"}, "outlook": {"type": "STRING"},
    "chips": {"type": "STRING"}, "chip_verdict": {"type": "STRING"},
    "catalysts": {"type": "ARRAY", "items": {"type": "STRING"}}, "risks": {"type": "ARRAY", "items": {"type": "STRING"}},
    "timing": {"type": "STRING"}, "watch": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["verdict", "thesis", "industry", "outlook", "timing", "chips", "chip_verdict"]}

def s_of(sid):
    try:
        return next((x for x in (_DATA_CACHE.get("stocks") or []) if x.get("id") == sid), {})
    except Exception:
        return {}
_DATA_CACHE = {}

def ai_review_pick(p, w):
    """r939:AI 複核——模型選出來後,AI 上網研究這家公司與產業,給「同意 / 保留」與理由(不改變選股,先記錄;大腦追蹤哪種結果好)"""
    name, sid, sec = p["name"], p["id"], p.get("sector") or "—"
    research = _gemini_raw(f"用 Google 搜尋「{name} {sid}」最近 3 個月的資訊,整理成研究筆記(繁體中文,400 字內):主要產品/客戶/競爭對手;最新重要新聞與法說會重點(附日期);所屬產業趨勢與景氣位置;市場主要爭議。只寫查得到的事實。", 1200, search=True)
    prompt = (f"你是資深股票研究員。量化模型選出 {name}({sid},{sec})為本週候選,買價 {p['buy']}、目標 {p['target']}(+{(p['target']/p['buy']-1)*100:.1f}%)、停損 {p['stop']}({(p['stop']/p['buy']-1)*100:.1f}%)。\n"
              f"量化理由:{'、'.join(p.get('why') or [])}。\n研究筆記:{research or '(無)'}\n【籌碼數據】\n{chip_digest(sid, s_of(sid))}\n"
              "請以產業與公司基本面角度複核,給出:verdict(只能是「同意」或「保留」:同意=基本面/產業也支持此時進場;保留=有明顯疑慮,例如產業轉弱、重大利空、估值透支),"
              "thesis(100 字內核心看法),industry(產業位置 60 字內),outlook(未來 6~12 個月展望 80 字內),catalysts(2~3 點),risks(2~3 點),"
              "chips(籌碼解讀 120 字內:誰在買、誰在賣、法人與分點主力方向是否一致、大戶與融資的變化代表什麼、關鍵分點的動向),chip_verdict(只能是「偏多」「中性」「偏空」),"
              "timing(對買進時機的看法:現在、拉回再買、或等事件後;以及什麼情況應提早賣出,80 字內),watch(接下來 2~3 個要追蹤的事)。價位只能引用上面給的數字。")
    t = _gemini_raw(prompt, 1600, json_schema=AI2_SCHEMA)
    try:
        j = json.loads(t)
        if j.get("verdict") not in ("同意", "保留"): j["verdict"] = "同意" if "同意" in str(j.get("verdict")) else "保留"
        j["at"] = NOW.strftime("%Y-%m-%d %H:%M"); return j
    except Exception as e:
        print(f"  複核 JSON 解析失敗:{e} / 回應開頭:{(t or '')[:200]}")
        return None

def ai_reason_pick(p, w):
    """入選理由:2 句,只用評分明細裡的數字。"""
    why = "、".join(p.get("why") or [])
    prompt = (f"{_RULES}\n這檔台股被量化模型選進下週名單。用兩句話說明為什麼是它,第一句講結構或動能,第二句講風險報酬設定。\n"
              f"股票:{p['name']}({p['id']}),產業:{p.get('sector') or '—'}。模型分 {p.get('score')}(型態 {p.get('kind')})。\n"
              f"命中的條件:{why or '無'}。近20日漲幅 {p.get('r20')}%,乖離月線 {p.get('bias20')}%,量比 {p.get('vr')}x。\n"
              f"建議買價 {p['buy']}、目標 {p['target']}(+{(p['target']/p['buy']-1)*100:.1f}%)、停損 {p['stop']}({(p['stop']/p['buy']-1)*100:.1f}%),持有到 {w['eval_week']} 那週結束。")
    return _gemini(prompt)

def ai_reason_exit(L, p):
    """出場理由:1 句,說明為什麼在那個價位/那一天出場。"""
    why = {"tp": "碰到目標價", "sl": "跌破停損價", "exp": "評估週到期收盤"}.get(L.get("xw"), "出場")
    prompt = (f"{_RULES}\n用一句話說明這筆交易的出場。\n"
              f"{L['name']}({L['id']}):{L['fill']} 以 {L['entry']} 買進,{L['xd']} 以 {L['xp']} 賣出,原因是{why},"
              f"持有 {L.get('hold')} 個交易日,實現損益 {L.get('ret'):+}%。目標價 {L['target']}、停損價 {L['stop']}。"
              + ("這是換股遞補的部位。" if L.get("src") == "bench" else ""))
    return _gemini(prompt, 120)


def stats_of(weeks):
    done = [w for w in weeks if w.get("status") == "done" or w.get("mode") == "open"]   # r921:無期限模式 → 以已平倉的個股計,不等整週結束
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
    # r956:含持有中倉位的成績(無期限模式下多數倉位還沒結案,只看已結案會被「先停損先結案」拉低)
    live = [p for w in done if not w.get("bt") for p in w["picks"] if (p.get("legs") or []) and isinstance(p.get("ret"), (int, float))]
    if live:
        mr = sorted(p["ret"] for p in live)
        st["mtm"] = {"n": len(live), "open": len([p for p in live if p.get("result") == "pending"]),
                     "win_rate": round(len([x for x in mr if x > 0]) / len(mr) * 100, 1),
                     "avg_ret": round(avg(mr), 2), "median": round(mr[len(mr) // 2], 2),
                     "best": round(mr[-1], 2), "worst": round(mr[0], 2)}
    hold = [p["hold"] for p in filled if isinstance(p.get("hold"), int)]
    retc = [p["ret_c"] for p in filled if isinstance(p.get("ret_c"), (int, float))]
    st["avg_hold"] = round(avg(hold), 1) if hold else None
    st["avg_ret_c"] = round(avg(retc), 2) if retc else None
    legs = [L for p in filled for L in (p.get("legs") or [])]
    for k in ("tp", "sl", "exp"):
        st["x_" + k] = len([L for L in legs if L.get("xw") == k])
    xr = {k: [L["ret"] for L in legs if L.get("xw") == k and isinstance(L.get("ret"), (int, float))] for k in ("tp", "sl", "exp")}
    st["x_ret"] = {k: (round(avg(v), 2) if v else None) for k, v in xr.items()}
    st["legs"] = len(legs)
    st["rot"] = sum(p.get("rot") or 0 for p in filled)
    st["rot_rate"] = round(len([p for p in filled if (p.get("rot") or 0) > 0]) / len(filled) * 100, 1) if filled else None
    lr = [L["ret"] for L in legs if isinstance(L.get("ret"), (int, float))]
    st["avg_leg_ret"] = round(avg(lr), 2) if lr else None
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
    # ── r771:風險調整後績效(學 ProPicks 的戰績列:年化 / Sharpe / Sortino / 最大回撤)──
    wk = [(b["avg"] or 0.0) for b in st["by_week"]]
    n = len(wk)
    if n >= 4:
        m = avg(wk); sd = (avg([(x - m) ** 2 for x in wk]) * n / (n - 1)) ** 0.5
        dn = [min(0.0, x) for x in wk]; dsd = (avg([x * x for x in dn]) * n / (n - 1)) ** 0.5
        st["wk_std"] = round(sd, 2)
        st["sharpe"] = round(m / sd * (52 ** 0.5), 2) if sd > 0 else None      # 週報酬年化(52 週),無風險利率視為 0
        st["sortino"] = round(m / dsd * (52 ** 0.5), 2) if dsd > 0 else None
        st["ann_ret"] = round(((curve[-1] / 100.0) ** (52.0 / n) - 1) * 100, 2) if curve else None
    else:
        st["wk_std"] = st["sharpe"] = st["sortino"] = st["ann_ret"] = None
    peak, mdd, mdd_i = 100.0, 0.0, None
    for i, v in enumerate(curve):
        peak = max(peak, v)
        dd = (v / peak - 1) * 100
        if dd < mdd: mdd, mdd_i = dd, i
    st["mdd"] = round(mdd, 2)
    st["mdd_week"] = st["by_week"][mdd_i]["buy_week"] if mdd_i is not None else None
    # 對照線:同一持有視窗「全台股報酬中位數」——回答「模型選的 5 檔,有沒有比隨便一檔好」
    bq, bcurve, bms = 100.0, [], []
    for w in done:
        b = w.get("bm")
        if isinstance(b, (int, float)): bms.append(b)
        bq *= (1 + (b or 0.0) / 100); bcurve.append(round(bq, 2))
    st["bm_equity"] = bcurve
    st["bm_avg"] = round(avg(bms), 2) if bms else None
    st["bm_n"] = len(bms)
    st["alpha"] = round((st["avg_ret"] or 0) - st["bm_avg"], 2) if (bms and st["avg_ret"] is not None) else None
    return st


# ───────────────────────── 主流程 ─────────────────────────
def main():
    data = load_json("data.json", {}); _DATA_CACHE.update(data)
    if not data.get("stocks"):
        print("aipick:data.json 不可用,略過"); return
    J = load_json(OUT, {"model": MODEL, "weeks": [], "stats": {}})
    weeks = J.get("weeks") or []
    weeks = [w for w in weeks if isinstance(w, dict) and w.get("buy_week")]

    # 這一班應該存在的「買進週」
    wd = TODAY.weekday(); hm = NOW.hour * 60 + NOW.minute
    if (wd == 4 and hm >= ((16 * 60 + 30) if US else (14 * 60 + 30))) or wd >= 5:
        buy_week = monday(TODAY) + dt.timedelta(days=7)
    else:
        buy_week = monday(TODAY)
    force = os.environ.get("AIPICK_FORCE") == "1"
    # 🪶 r740:盤中輕量班(intraday-quotes 自迴圈每 5 分鐘呼叫一次)——只做結算與換股輪動,
    #    不重訓、不選股、不回測。理由:重訓/選股要掃全市場,在 5 分鐘的輪迴裡會被 timeout 砍掉,
    #    砍到一半又每輪重試,既拖垮報價又可能把 learn 寫成降級版本。選股交給 update_data 的重班。
    LIGHT = os.environ.get("AIPICK_LIGHT") == "1"
    learn_prev = J.get("learn") or {}
    rebuild_bt = (not LIGHT) and (os.environ.get("AIPICK_REBUILD_BT") == "1" or (weeks and not learn_prev))   # v1 檔升級 v2:回測重跑(含學習)
    if rebuild_bt:
        weeks = [w for w in weeks if not w.get("bt")]
    amax = learn_prev.get("alpha_max") or ALPHA_MAX
    tune_rep = learn_prev.get("tune") or []
    live_done = len([w for w in weeks if w.get("status") == "done" and not w.get("bt")])
    retune = rebuild_bt or ((not LIGHT) and live_done and live_done % 4 == 0 and learn_prev.get("tuned_at_live") != live_done)   # 每累積 4 週實戰重調一次
    if (not LIGHT) and (not [w for w in weeks if w.get("bt")] or retune):   # 首次建檔/升級/定期重調:逐週回測(walk-forward,每週先用更早的週訓練再選股)+ 自動調參
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
    if not have and LIGHT:
        print("aipick:輕量班不選股,等 update_data 重班產生本週名單")
    if not have and not LIGHT:
        ok = True
        if buy_week > monday(TODAY):
            # r954:下週名單必須等「上一個交易日的 K」全市場入庫才選。
            #  舊版只在週五檢查、且只看指標股(台積電/SPY)——週末的班完全不檢查:
            #  10/03 美股名單在美東週六 00:10 產生時,全市場 10/02 K 還沒入庫(16:54 台北才進來),
            #  5 檔裡 4 檔用 10/01 收盤當基準;台股 8/31 週也發生過(用 8/27 選)。
            #  規則:①指標股要有最近一個平日的 K;②全市場 ≥90% 的活躍股票要跟指標股同一天;
            #        ③過了寬限時間(平日後一天 18:00,當地時間)仍不齊 → 視為假日/部分缺漏,照現有資料選並記錄。
            d, _ = bars_of(BENCH_SID); bl = d[-1] if d else ""
            last_wd = TODAY - dt.timedelta(days=max(0, wd - 4))
            grace = NOW >= dt.datetime.combine(last_wd + dt.timedelta(days=1), dt.time(18, 0), tzinfo=NOW.tzinfo)
            if not bl or (bl < iso(last_wd) and not grace):
                ok = False; print(f"aipick:{iso(last_wd)} K 尚未入庫(指標股最新 {bl or '無'}),本班不選股")
            else:
                lo = iso(dt.date.fromisoformat(bl) - dt.timedelta(days=10)); tot = hit = 0
                for s0 in data.get("stocks", []):
                    if s0.get("market") != MKT or s0.get("etf"): continue
                    dd, _ = bars_of(s0["id"])
                    if not dd or dd[-1] < lo: continue
                    tot += 1; hit += 1 if dd[-1] >= bl else 0
                cov = hit / tot if tot else 0
                hard = NOW >= dt.datetime.combine(last_wd + dt.timedelta(days=2), dt.time(12, 0), tzinfo=NOW.tzinfo)
                if cov < 0.90 and not hard:
                    ok = False; print(f"aipick:{bl} K 只有 {hit}/{tot}({cov:.0%})入庫,未達 90%,本班不選股")
                else:
                    print(f"aipick:K 入庫 {bl} 覆蓋 {hit}/{tot}({cov:.0%})" + (",已過寬限,照現有資料選" if cov < 0.90 else ""))
        if ok:
            L = build_learn(data, buy_week, amax=amax)
            w = gen_week(data, buy_week, L, exclude=held_now(weeks))
            if w.get("status") == "skip":
                weeks.append(w); print("aipick:本週空手(" + w.get("skip", "") + ")")
            elif w["picks"]:
                weeks.append(w)
                print(f"aipick:選出 {w['buy_week']} 買進週 {len(w['picks'])} 檔(候選 {w['n_cand']}):" +
                      "、".join(f"{p['name']}@{p['buy']}" for p in w["picks"]))
            else:
                print("aipick:無符合標的,本週不選")
    # 🔁 r767:補產缺漏的候補名單——未成交的正選要能手動換股,前端得先有候補可挑。
    #    只補未結案的週(done 的結果永久凍結不動);score_one 以該週 cutoff 計分,
    #    所以補出來的排名與當初選股當下一致,不會用今天的資料回頭污染歷史。
    if not LIGHT:
        for w in weeks:
            if w.get("bt") or w.get("status") == "done" or w.get("bench"): continue
            try:
                bw = dt.date.fromisoformat(w["buy_week"])
                w2 = gen_week(data, bw, build_learn(data, bw, amax=amax), exclude=w.get("held_excl"))
                used = {p["id"] for p in w.get("picks") or []}
                used |= {L["id"] for p in (w.get("picks") or []) for L in (p.get("legs") or [])}
                w["bench"] = [b for b in (w2.get("bench") or []) if b["id"] not in used][:BENCH_N]
                print(f"aipick:補產候補 {w['buy_week']} 共 {len(w['bench'])} 檔")
            except Exception as e:
                print("aipick:補產候補失敗", w.get("buy_week"), e)
    # 逐週結算(已 done 的不再動,結果永久凍結)
    # r943:複核已完成、買進週還沒開始 → 依複核結果重排一次(保留的往後、候補遞補),只做一次
    try:
        for i, w in enumerate(weeks):
            if w.get("bt") or w.get("rev_applied") or not w.get("reviews") or w.get("status") == "skip": continue
            bwd = dt.date.fromisoformat(w["buy_week"])
            if bwd < TODAY or (bwd == TODAY and NOW.hour >= 9): continue        # 開盤後就不再動名單
            if not all(sid in w["reviews"] for sid in (w.get("shortlist") or [])[:10]): continue
            L2 = build_learn(data, dt.date.fromisoformat(w["buy_week"]), amax=amax)
            w2 = gen_week(data, dt.date.fromisoformat(w["buy_week"]), L2, reviews=w["reviews"], exclude=w.get("held_excl"))
            if w2.get("picks"):
                old = [p["id"] for p in w["picks"]]; new = [p["id"] for p in w2["picks"]]
                for p in w2["picks"]:
                    if p["id"] in w["reviews"]: p["ai2"] = w["reviews"][p["id"]]
                    for q in w["picks"]:
                        if q["id"] == p["id"] and q.get("ai"): p["ai"] = q["ai"]
                w2["reviews"] = w["reviews"]; w2["rev_applied"] = 1; w2["pre_review"] = old
                weeks[i] = w2
                print(f"aipick:複核後重排 {w['buy_week']}:{old} → {new}" + ("(有調整)" if old != new else "(不變)"))
    except Exception as e:
        print("aipick:複核後重排例外", e)
    # r921:無期限模式的兩個訊號——① 下一週名單(舊掛單是否取消)② 訊號轉弱(排名掉出前 30% 且跌破月線 → 下一根 K 開盤出場)
    try:
        lw = sorted([w for w in weeks if not w.get("bt")], key=lambda w: w["buy_week"])
        for i, w in enumerate(lw):
            w["_next_ids"] = {p["id"] for p in lw[i + 1]["picks"]} if i + 1 < len(lw) else None
        latest = lw[-1] if lw else None
        top = set(latest.get("cand_top") or []) if latest else set()
        if top:
            for w in lw:
                if w is latest: continue
                for p in w["picks"]:
                    cur = (p.get("legs") or [None])[-1]
                    if not cur or cur.get("xd") or p.get("weak"): continue
                    if cur["id"] in top: continue
                    d, o = bars_of(cur["id"])
                    if len(d) >= 20 and o[-1][3] < sum(x[3] for x in o[-20:]) / 20:
                        p["weak"] = {"id": cur["id"], "from": d[-1]}
                        print(f"aipick:訊號轉弱 {cur['id']} {cur.get('name')}(排名掉出前 30% 且跌破月線)→ 下一根 K 開盤出場")
    except Exception as e:
        print("aipick:訊號轉弱判斷例外", e)
    globals()["_WEEKS"][:] = weeks                                  # r956:換股去重要看到其他週的持股
    for w in weeks:
        if w.get("status") != "done" or w.get("xv") != XVER:      # r736:舊檔(只有收盤結算)重跑一次,補買賣時間與實現損益
            try: evaluate(w)
            except Exception as e: print("aipick:evaluate 失敗", w.get("buy_week"), e)
    weeks.sort(key=lambda w: w["buy_week"])
    weeks = weeks[-KEEP_WEEKS:]
    # r787:盤中當下記(只在交易時段;時間用報價快照的時間)
    try:
        if (not US) and TODAY.weekday() < 5 and 9 * 60 <= hm <= 13 * 60 + 35:
            prices = {s["id"]: float(s["price"]) for s in data.get("stocks") or [] if s.get("price")}
            ni = intraday_watch(weeks, prices, data.get("intraday") or NOW.strftime("%H:%M"))
            if ni: print(f"aipick:盤中記錄 {ni} 筆觸發(買價/目標/停損)")
    except Exception as e:
        print(f"aipick:盤中記錄失敗 {e}")
    try:
        na = 0 if US else apply_intraday_times(weeks)       # r890:美股不做分K時間戳(台股 MIS 專用)
        if na: print(f"aipick:沿用盤中記錄的時間 {na} 筆")
        nt = 0 if US else stamp_times(weeks, budget=6 if LIGHT else 20)
        if nt: print(f"aipick:補成交/出場時間 {nt} 次查詢(富果 1 分 K)")
    except Exception as e:
        print(f"aipick:補時間失敗 {e}")
    if not LIGHT:
        # 對照線:每個已結算的週補一次「全台股同視窗中位數」(算過就不再算,結果跟著週凍結)
        nb = 0
        for w in weeks:
            if w.get("status") == "done" and "bm" not in w:
                try: w["bm"] = week_benchmark(data, w); nb += 1
                except Exception: w["bm"] = None
        if nb: print(f"aipick:補算對照基準 {nb} 週")
        # 🤖 入選/出場理由:純敘述,不影響選股與結算;沒金鑰或預算用完就跳過,下一班再補
        if GEMINI_KEY:
            na = nx = 0
            for w in weeks:
                if w.get("bt"): continue
                for p in w.get("picks") or []:
                    if not _ai_ok(p.get("ai")) and _G["n"] < AI_BUDGET and w.get("status") != "done":
                        t = ai_reason_pick(p, w)
                        if t: p["ai"] = t; na += 1
                    pass   # r943:複核改由 aipick_review.py 獨立步驟處理
                    for L in p.get("legs") or []:
                        if L.get("xd") and not _ai_ok(L.get("ai_x")) and _G["n"] < AI_BUDGET:
                            t = ai_reason_exit(L, p)
                            if t: L["ai_x"] = t; nx += 1
            print(f"aipick:Gemini 理由 入選 {na} 則、出場 {nx} 則(本班呼叫 {_G['n']}/{AI_BUDGET})")
        else:
            print("aipick:未設 GEMINI_KEY,跳過入選/出場理由")
    # 🧠 學習狀態:每班用「到今天已走完」的全部週重訓(下一次選股就用這組);記錄變化與檢討
    wk_key = iso(monday(TODAY))
    if LIGHT or (learn_prev.get("wk") == wk_key and learn_prev.get("w") and not learn_prev.get("force_train")):
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
    for w in weeks: w.pop("_next_ids", None)                          # r921:暫存欄位(set)不寫入
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
