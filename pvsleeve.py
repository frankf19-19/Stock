"""r1024:📈 量價籌碼組——只用價格與成交量的選股模型(38 項量價特徵,HistGradientBoosting,純 Python 推論)
回測(2016~2026 滾動驗證,每年只用過去資料訓練):每週換前 20 名、含成本,年化 +28.8%、最大回落 −30.6%
(同期 0050 +25.4%/−32.6%;全市場等權 +16.2%)。
規則(皆經同一回測驗證):
  買入價  = 訊號隔天開盤價(漲停開出買不到就放棄;跳空濾網回測無益,不用)
  停損價  = 進場價 − 3×ATR(14)  → 盤中觸及即出場(回測:年化 −1.9%,最大回落 −37.7% → −30.6%)
  停利價  = 進場價 × 1.25        → 盤中觸及即出場(回測:中性略正)
  換股    = r1025 每天收盤重排:新進前 20 名 → 隔天開盤買(有空位才買);持股掉出前 100 名 → 隔天開盤賣
            (回測:每天但掉出前 20 就賣 −1.2%;前 40 +23.3%;前 100 +30.7%,交易次數最少)
  盤中    = 09:00 用官方開盤價成交;停損/停利用即時成交價+官方最高最低確認,碰到就出場
狀態存 aipick.json → trader.pv"""
import json, math
# r1031:盤中班(update_quotes)沒裝 pandas → pandas/numpy 改在需要算特徵時才載入,盤中成交/停利不受影響

FEATS = ['r5','r20','r60','r120','r250','r250x20','dh20','dh60','dh250','dl60','b5','b20','b60','b120','b240','s20','s60','m20_60','m60_240',
         'atr','vol20','vol60','vr5','vr20','lval','lim60','lim250','rsi','kd','gap','body20','upday20','nh20','dsh','skew60','maxr20','minr20','cv',
         'x_f5','x_t5','x_f20','x_t20','x_mb']   # r1030:籌碼(外資/投信 5、20 日買超佔均量、融資 20 日變化)
TOPK = 20; REB = 1; SELL_RANK = 200; STOP_ATR = None; TP = 0.25; MODEL_VER = 'pvc1'; NOTIONAL = 100000; LIQ = 2e7
IVC = 0.03; WMIN = 0.67; WMAX = 1.5   # r1048:依波動分配金額(每檔 = 平均金額 × 0.67~1.5 倍;波動大的少買)——回測年化 43.7%→39.1%、最大回落 −31.2%→−24.3%
FEE_B = 0.001425; FEE_S = 0.001425 + 0.003
_M = {}

def model():
    if "m" not in _M:
        try: _M["m"] = json.load(open("aipick_pvc_model.json", encoding="utf-8"))
        except Exception: _M["m"] = None
    return _M["m"]

def score(x):
    M = model()
    if not M or x is None: return None
    z = M["base"]
    for t in M["trees"]:
        i = 0
        while not t[i][4]:
            f, th, l, r, _, _, mg = t[i]; v = x[f]
            i = l if (mg if v != v else v <= th) else r
        z += t[i][5]
    return z

def feats_df(o, ch=None):
    import numpy as np, pandas as pd
    """o = [[開,高,低,收,量(張)],...](由舊到新);回傳與訓練完全相同定義的特徵表"""
    df = pd.DataFrame([b[:5] for b in o], columns=['O','H','L','C','V'], dtype=float)
    C,O,H,L,V = df.C,df.O,df.H,df.L,df.V
    ma = lambda x,n: x.rolling(n, min_periods=n).mean()
    val = C*V*1000; r = C.pct_change()
    m5,m10,m20,m60,m120,m240 = [ma(C,n) for n in (5,10,20,60,120,240)]
    tr = pd.concat([H-L,(H-C.shift()).abs(),(L-C.shift()).abs()],axis=1).max(axis=1)
    up = r.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); dn = (-r).clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
    lo9,hi9 = L.rolling(9).min(),H.rolling(9).max(); rsv = (C-lo9)/(hi9-lo9).replace(0,np.nan)
    F = pd.DataFrame({
     'r5':C/C.shift(5)-1,'r20':C/C.shift(20)-1,'r60':C/C.shift(60)-1,'r120':C/C.shift(120)-1,'r250':C/C.shift(250)-1,
     'r250x20':C.shift(20)/C.shift(250)-1,
     'dh20':C/H.rolling(20).max()-1,'dh60':C/H.rolling(60).max()-1,'dh250':C/H.rolling(250).max()-1,'dl60':C/L.rolling(60).min()-1,
     'b5':C/m5-1,'b20':C/m20-1,'b60':C/m60-1,'b120':C/m120-1,'b240':C/m240-1,
     's20':m20/m20.shift(5)-1,'s60':m60/m60.shift(10)-1,'m20_60':m20/m60-1,'m60_240':m60/m240-1,
     'atr':tr.rolling(14).mean()/C,'vol20':r.rolling(20).std(),'vol60':r.rolling(60).std(),
     'vr5':V.rolling(5).mean()/V.rolling(60).mean(),'vr20':V.rolling(20).mean()/V.rolling(120).mean(),
     'lval':np.log1p(val.rolling(20).mean()),'lim60':(r>=0.095).rolling(60).sum(),'lim250':(r>=0.095).rolling(250).sum(),
     'rsi':up/(up+dn),'kd':rsv.ewm(alpha=1/3,adjust=False).mean(),
     'gap':O/C.shift()-1,'body20':((C-O)/C.shift()).rolling(20).mean(),'upday20':(r>0).rolling(20).mean(),
     'nh20':(C>=C.rolling(20).max()).rolling(20).sum(),'dsh':(H.rolling(20).max().diff()!=0).rolling(20).sum(),
     'skew60':r.rolling(60).skew(),'maxr20':r.rolling(20).max(),'minr20':r.rolling(20).min(),
     'cv':(val/val.rolling(20).mean())})
    vv = V.rolling(20).mean().replace(0, np.nan)
    if ch is not None:
        f = pd.Series(ch.get('f'), dtype=float).fillna(0); t = pd.Series(ch.get('t'), dtype=float).fillna(0)
        F['x_f5'] = f.rolling(5).sum()/vv; F['x_t5'] = t.rolling(5).sum()/vv; F['x_f20'] = f.rolling(20).sum()/vv; F['x_t20'] = t.rolling(20).sum()/vv
        mb = pd.Series(ch.get('mb'), dtype=float).ffill(); F['x_mb'] = mb/mb.shift(20)-1
    else:
        for c in ('x_f5','x_t5','x_f20','x_t20','x_mb'): F[c] = np.nan
    F['liq'] = val.rolling(20).median(); F['atr_abs'] = tr.rolling(14).mean()
    return F

def chip_aligned(A, sid, d):
    """把法人(c/ 分片 d/f/t)與融資(cd/mf)對齊到日K日期;沒有的日子法人記 0、融資沿用前值"""
    ch = A.chip_of(sid) or {}
    fm = dict(zip(ch.get("d") or [], ch.get("f") or [])); tm = dict(zip(ch.get("d") or [], ch.get("t") or []))
    mm = dict(zip(ch.get("cd") or [], ch.get("mf") or []))
    if not fm: return None
    return {"f": [fm.get(x, 0) or 0 for x in d], "t": [tm.get(x, 0) or 0 for x in d], "mb": [mm.get(x) for x in d]}

def feats_last(o, ch=None):
    if not o or len(o) < 262: return None, None
    if ch is not None: ch = {k: v[-300:] for k, v in ch.items()}
    F = feats_df(o[-300:], ch); row = F.iloc[-1]
    x = [float(row[f]) if row[f] == row[f] else float('nan') for f in FEATS]
    if sum(1 for v in x if v != v) > 4: return None, None
    return x, row

def _bar(A, sid, day):
    d, o = A.bars_of(sid)
    if not d: return None, None
    try: i = d.index(day)
    except ValueError: return None, None
    return o[i], o[i-1] if i > 0 else None

def _tk(v):
    t = 0.01 if v < 10 else 0.05 if v < 50 else 0.1 if v < 100 else 0.5 if v < 500 else 1 if v < 1000 else 5
    return round(round(v / t) * t, 2)

def pxmap(A, S, sc, last):
    """假設今天收盤改成某個價,重算這檔分數(其他股票不變):
       sell = 收盤跌到這價會掉出前 SELL_RANK 名(→ 隔天開盤賣)
       buy  = 收盤到這價會進入前 TOPK 名(→ 隔天開盤買);buy_lo = 現在已在前 TOPK 時,跌到這價以下就不在了"""
    import bisect
    try: prio = set(json.load(open("bk/_prio_users.json", encoding="utf-8")))
    except Exception: prio = set()
    ids = prio | {p["id"] for p in S.get("pos") or []} | {q["id"] for q in S.get("pend") or []} | {x["id"] for x in S.get("picks") or []}
    neg = sorted([-z for z, _, _ in sc]); own = {s["id"]: z for z, s, _ in sc}
    def rank(z, sid):
        r = bisect.bisect_left(neg, -z) + 1
        return r - (1 if own.get(sid, -9e9) > z else 0)
    out = {}
    for sid in ids:
        if sid not in own: continue
        d, o = A.bars_of(sid)
        if not d or d[-1] != last: continue
        ch = chip_aligned(A, sid, d); b = o[-1]; px = b[3]
        def at(p):
            o2 = o[:-1] + [[b[0], max(b[1], p), min(b[2], p), p] + list(b[4:])]
            x, _ = feats_last(o2, ch); z = score(x) if x else None
            return rank(z, sid) if z is not None else None
        r = {"px": px}; r0 = rank(own[sid], sid)
        for k in range(1, 31):
            p = _tk(px * (1 - 0.01 * k)); rk = at(p)
            if rk and rk > SELL_RANK: r["sell"] = p; break
        if r0 <= TOPK:
            for k in range(1, 21):
                p = _tk(px * (1 - 0.01 * k)); rk = at(p)
                if rk and rk > TOPK: r["buy_lo"] = p; break
        else:
            for k in range(1, 16):
                hit = None
                for p in (_tk(px * (1 + 0.01 * k)), _tk(px * (1 - 0.01 * k))):
                    rk = at(p)
                    if rk and rk <= TOPK: hit = p; break
                if hit: r["buy"] = hit; break
        out[sid] = r
    return out

def _wr(px, atr):
    try: return round(min(WMAX, max(WMIN, IVC * float(px) / float(atr))), 3) if atr and px else 1.0
    except Exception: return 1.0


def _size(S, q, op):
    """r1048:這檔買多少——原始倍數 wr(依波動)÷ 目前持股平均倍數,總投入不超過 TOPK × NOTIONAL"""
    wr = q.get("wr") or _wr(op, q.get("atr"))
    ws = [p.get("wr", 1.0) for p in S.get("pos") or []] + [wr]
    w = min(2.5, max(0.4, wr / (sum(ws) / len(ws))))
    used = sum(p.get("w", 1.0) for p in S.get("pos") or [])
    w = round(max(0.0, min(w, TOPK - used)), 3)
    return wr, w


def run(A, data, T, last, log=print):
    """收盤班呼叫:① 以今天日K成交上一輪訊號的進出(開盤價)② 盤中停損/停利(用今天最高最低)③ 每 5 個交易日重排前 20 名"""
    S = T.setdefault("pv", {"pos": [], "pend": [], "trades": [], "log": [], "nav": [], "picks": [], "last_rb": None, "start": last})
    if S.get("ver") != MODEL_VER:                          # r1030:換成量價籌碼模型 → 舊名單作廢、尚未成交的待辦取消,以新模型重排
        S["pend"] = []; S["picks"] = []; S["last_rb"] = None; S["rank_d"] = None; S["ver"] = MODEL_VER
        for p in S["pos"]: p["stop"] = None
    if S.get("done") == last and S.get("rank_d") == last: return S
    fresh = S.get("done") != last
    ev = []; byid = {s["id"]: s for s in data.get("stocks", [])}
    # ① 開盤成交(訊號日 < 今天)
    keep = []
    for q in S["pend"]:
        if q["sig_d"] >= last or not fresh: keep.append(q); continue
        b, pb = _bar(A, q["id"], last)
        if not b or not b[0]: keep.append(q) if q.get("tries", 0) < 2 else None; q["tries"] = q.get("tries", 0) + 1; continue
        op = b[0]
        if q["act"] == "sell":
            p = next((x for x in S["pos"] if x["id"] == q["id"]), None)
            if p:
                ret = (op*(1-FEE_S))/(p["entry"]*(1+FEE_B))-1
                S["trades"].append({**p, "xd": last, "xp": op, "why": "rot", "ret": round(ret*100, 2)}); S["pos"].remove(p)
                ev.append(f"{last} 🔄 量價籌碼組換股賣出 {p['name']} 開盤 {op}({ret*100:+.1f}%)")
        else:
            if pb and pb[3] and op >= pb[3]*1.095: ev.append(f"{last} ❎ 量價籌碼組 {q['name']} 漲停開出買不到,放棄"); continue
            if any(x["id"] == q["id"] for x in S["pos"]): continue
            stp = round(op - STOP_ATR*q["atr"], 2) if STOP_ATR else None; tp = round(op*(1+TP), 2)
            wr, w = _size(S, q, op)
            if w < 0.1: ev.append(f"{last} ❎ 量價籌碼組 {q['name']} 資金已用完,放棄"); continue
            S["pos"].append({"id": q["id"], "name": q["name"], "fill": last, "entry": op, "sh": int(NOTIONAL*w/op), "amt": round(NOTIONAL*w), "w": w, "wr": wr, "stop": stp, "tp": tp, "rank": q.get("rank"), "sig_d": q["sig_d"]})
            ev.append(f"{last} 🟢 買進 量價籌碼組 {q['name']} 開盤 {op}(金額 {w:.2f} 倍、停利 {tp}{('、停損 ' + str(stp)) if stp else ''})")
    S["pend"] = keep
    # ② 停損/停利(含今天剛買的)
    for p in (list(S["pos"]) if fresh else []):
        b, _ = _bar(A, p["id"], last)
        if not b: continue
        o_, h_, l_ = b[0], b[1], b[2]; xp = why = None
        if l_ and p.get("stop") and l_ <= p["stop"]: xp, why = min(o_, p["stop"]), "sl"
        elif h_ and h_ >= p["tp"]: xp, why = max(o_, p["tp"]), "tp"
        if xp:
            ret = (xp*(1-FEE_S))/(p["entry"]*(1+FEE_B))-1
            S["trades"].append({**p, "xd": last, "xp": xp, "why": why, "ret": round(ret*100, 2)}); S["pos"].remove(p)
            ev.append(f"{last} {'🛑 停損' if why=='sl' else '🎯 停利'} 量價籌碼組 {p['name']} {xp}({ret*100:+.1f}%)")
    # ③ 重排(每 5 個交易日)
    d0, _ = A.bars_of("2330"); cal = [x for x in d0 if x <= last]
    due = (not S.get("last_rb")) or (S["last_rb"] in cal and len(cal) - 1 - cal.index(S["last_rb"]) >= REB) or (S["last_rb"] not in cal)
    if (due or S.get("rank_d") != last) and model():
        sc = []
        for s in data.get("stocks", []):
            if s.get("market") != "TW" or s.get("etf") or not str(s.get("id", "")).isdigit() or len(str(s["id"])) != 4: continue
            d, o = A.bars_of(s["id"])
            if not d or d[-1] != last: continue
            try:
                from trader import has_jump
                if has_jump(o): continue
            except Exception: pass
            x, row = feats_last(o, chip_aligned(A, s["id"], d))
            if x is None or not (row["liq"] >= LIQ): continue
            z = score(x)
            if z is not None: sc.append((z, s, float(row["atr_abs"])))
        sc.sort(key=lambda t: -t[0])
        if len(sc) >= 100:                                  # r1029:每檔量價排名 + ATR(個股頁/卡片算停損用)
            S["rank_all"] = {s["id"]: [i+1, round(at, 4)] for i, (z, s, at) in enumerate(sc)}; S["rank_d"] = last; S["n_scored"] = len(sc)
            try: S["pxmap"] = pxmap(A, S, sc, last)          # r1031:排名門檻換算成價格
            except Exception as e: log(f"pv:價位換算例外 {e}")
        if len(sc) >= 100 and due and (fresh or not S.get("last_rb")):
            top = sc[:TOPK]; ids = {s["id"] for _, s, _ in top}
            S["picks"] = [{"id": s["id"], "name": s.get("name"), "sector": s.get("sector"), "z": round(z, 4), "rank": i+1, "px": (A.bars_of(s["id"])[1] or [[0,0,0,0]])[-1][3]} for i, (z, s, _) in enumerate(top)]
            S["picks_d"] = last; S["n_scored"] = len(sc)
            held = {p["id"] for p in S["pos"]}; RK = {s["id"]: i+1 for i, (z, s, _) in enumerate(sc)}
            S["pend"] = [q for q in S["pend"] if q["sig_d"] >= last]
            for p in S["pos"]:
                p["rank"] = RK.get(p["id"])
                if RK.get(p["id"], 10**6) > SELL_RANK: S["pend"].append({"id": p["id"], "name": p["name"], "act": "sell", "sig_d": last, "rank": RK.get(p["id"])})
            slots = TOPK - len(S["pos"]) + sum(1 for q in S["pend"] if q["act"] == "sell" and q["sig_d"] == last)
            for i, (z, s, at) in enumerate(top):
                if slots <= 0: break
                if s["id"] in held: continue
                _px = (A.bars_of(s["id"])[1] or [[0, 0, 0, 0]])[-1][3]
                S["pend"].append({"id": s["id"], "name": s.get("name"), "act": "buy", "sig_d": last, "atr": at, "rank": i+1, "wr": _wr(_px, at)}); slots -= 1
            nb = [q["name"] for q in S["pend"] if q["act"] == "buy" and q["sig_d"] == last]; ns = [q["name"] for q in S["pend"] if q["act"] == "sell" and q["sig_d"] == last]
            if nb or ns: ev.append(f"{last} 📈 量價籌碼組收盤重排:明天開盤買進 {'、'.join(nb) or '無'};明天開盤換股賣出 {'、'.join(ns) or '無'}")
            S["last_rb"] = last
    # 淨值
    real = sum(t["ret"]/100*(t.get("amt") or NOTIONAL) for t in S["trades"]); unreal = 0.0
    for p in S["pos"]:
        d, o = A.bars_of(p["id"]); c = o[-1][3] if o else None
        if c: unreal += (c - p["entry"])*p["sh"]; p["px"] = c
    e8d, e8o = A.bars_of("0050"); e8 = e8o[-1][3] if e8o and e8d and e8d[-1] == last else None
    S["nav"] = [x for x in S["nav"] if x[0] != last][-400:] + [[last, round(real+unreal), len(S["pos"]), e8]]
    tr_ = S["trades"]
    S["stats"] = {"closed": len(tr_), "win": round(100*sum(1 for t in tr_ if t["ret"] > 0)/len(tr_), 1) if tr_ else None,
                  "avg": round(sum(t["ret"] for t in tr_)/len(tr_), 2) if tr_ else None, "realized": round(real)}
    S["rules"] = {"topk": TOPK, "reb": REB, "sell_rank": SELL_RANK, "stop_atr": STOP_ATR, "tp": TP, "liq": LIQ, "size": "ivol", "wmin": WMIN, "wmax": WMAX, "notional": NOTIONAL}
    S["bt"] = BT
    for e in ev: S["log"].insert(0, e)
    S["log"] = S["log"][:200]; S["done"] = last; S["updated"] = A.NOW.strftime("%Y-%m-%d %H:%M")
    for e in ev: T.setdefault("log", []).insert(0, e); log("pv:" + e)   # 也寫進主交易紀錄 → 手機推播
    return S

def intraday(A, data, T, today, hhmm, live, log=print):
    """盤中(5 分鐘一班):09:00 官方開盤價成交待辦;持股即時檢查停損/停利(即時成交價 + 官方最高/最低確認)"""
    S = T.get("pv")
    if not S: return
    ev = []; keep = []
    for q in S.get("pend") or []:
        if q["sig_d"] >= today: keep.append(q); continue
        px, hl = live(q["id"])
        if not hl: keep.append(q); continue
        op, h, l = hl
        if q["act"] == "sell":
            p = next((x for x in S["pos"] if x["id"] == q["id"]), None)
            if p:
                ret = (op*(1-FEE_S))/(p["entry"]*(1+FEE_B))-1
                S["trades"].append({**p, "xd": today, "xt": "09:00", "xp": op, "why": "rot", "ret": round(ret*100, 2)}); S["pos"].remove(p)
                ev.append(f"{today} 09:00 🔄 量價籌碼組換股賣出 {p['name']} 官方開盤 {op}({ret*100:+.1f}%)")
            continue
        d, o = A.bars_of(q["id"]); pc = o[-1][3] if o and d and d[-1] < today else None
        if pc and h == l and op >= pc*1.095: ev.append(f"{today} 09:00 ❎ 量價籌碼組 {q['name']} 漲停鎖死買不到,放棄"); continue
        if any(x["id"] == q["id"] for x in S["pos"]) or len(S["pos"]) >= TOPK: continue
        stp = round(op - STOP_ATR*q["atr"], 2) if STOP_ATR else None; tp = round(op*(1+TP), 2)
        wr, w = _size(S, q, op)
        if w < 0.1: ev.append(f"{today} 09:00 ❎ 量價籌碼組 {q['name']} 資金已用完,放棄"); continue
        S["pos"].append({"id": q["id"], "name": q["name"], "fill": today, "ft": "09:00", "entry": op, "sh": int(NOTIONAL*w/op), "amt": round(NOTIONAL*w), "w": w, "wr": wr, "stop": stp, "tp": tp, "rank": q.get("rank"), "sig_d": q["sig_d"]})
        ev.append(f"{today} 09:00 🟢 買進 量價籌碼組 {q['name']} 官方開盤 {op}(金額 {w:.2f} 倍、停利 {tp}{('、停損 ' + str(stp)) if stp else ''})")
    S["pend"] = keep
    for p in list(S["pos"]):
        px, hl = live(p["id"])
        if px is None or not hl: continue
        op, h, l = hl; xp = why = None
        if p.get("stop") and l <= p["stop"]: xp, why = min(op, p["stop"]), "sl"
        elif h >= p["tp"]: xp, why = max(op, p["tp"]), "tp"
        if xp:
            ret = (xp*(1-FEE_S))/(p["entry"]*(1+FEE_B))-1
            S["trades"].append({**p, "xd": today, "xt": hhmm, "xp": xp, "why": why, "ret": round(ret*100, 2)}); S["pos"].remove(p)
            ev.append(f"{today} {hhmm} {'🛑 停損' if why=='sl' else '🎯 停利'} 量價籌碼組 {p['name']} {xp}({ret*100:+.1f}%)")
        else: p["px"] = px
    for e in ev: S["log"].insert(0, e); T.setdefault("log", []).insert(0, e); log("pv:" + e)

BT = {"range": "2016-01~2026-09", "cagr": 39.1, "mdd": -24.3, "b0050": 25.4, "bmdd0050": -32.6, "mkt": 16.2, "sharpe": 1.95,
      "years": {"2016": [35.5, 26.3], "2017": [34.2, 18.5], "2018": [15.9, -8.6], "2019": [21.5, 34.1], "2020": [58.0, 42.7], "2021": [52.6, 14.5],
                "2022": [26.0, -18.9], "2023": [44.9, 21.8], "2024": [31.3, 57.5], "2025": [32.9, 40.2], "2026": [61.4, 60.7]},
      "variants": [["純量價(不含籌碼)、每天、前100賣、停損3ATR", 30.7, -41.7], ["量價+籌碼、每週換股", 30.5, -33.5], ["量價+籌碼、每天、前100賣、不設停損停利", 39.6, -35.8],
                   ["前200賣、停利25%、每檔一樣多(10/9 前)", 43.7, -31.2], ["同上、依波動分配 0.67~1.5 倍(採用)", 39.1, -24.3], ["同上、依波動分配 0.5~2 倍", 36.3, -20.8],
                   ["同上+停損4ATR", 39.0, -36.5], ["前300賣、停利25%", 38.9, -32.0]],
      "research": [["主力比較:量價籌碼組", 43.7, -31.2, "✅ 最好"], ["主力比較:樹模型組(同期重建)", 24.6, -27.1, "較弱"], ["量價 70% + 樹 30% 混合", 37.9, -29.6, "沒有比較好"],
                   ["進場:費半昨晚漲 ≥1.5% 當天不買", 44.1, -32.2, "差異在誤差內,不改"], ["進場:改掛昨收 +2% 限價", 44.5, -31.2, "前後兩段不一致,不改"], ["進場:開盤跳空 >3% 不買", 43.7, -31.3, "沒差,不改"],
                   ["新資料:加月營收重訓", 43.5, -34.6, "前後兩段不一致,不改"], ["新資料:加營收+本益比/殖利率", 39.8, -34.7, "變差"], ["風控:同產業最多 4 檔", 42.8, -31.4, "沒幫助"],
                   ["風控:0050 跌破年線只持 10 檔", 38.3, -29.1, "最差一年變 −4%,不用"], ["風控:依波動分配金額 0.67~1.5 倍", 39.1, -24.3, "✅ 採用"]]}
