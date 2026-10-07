"""r1024:📈 量價組——只用價格與成交量的選股模型(38 項量價特徵,HistGradientBoosting,純 Python 推論)
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
import numpy as np, pandas as pd

FEATS = ['r5','r20','r60','r120','r250','r250x20','dh20','dh60','dh250','dl60','b5','b20','b60','b120','b240','s20','s60','m20_60','m60_240',
         'atr','vol20','vol60','vr5','vr20','lval','lim60','lim250','rsi','kd','gap','body20','upday20','nh20','dsh','skew60','maxr20','minr20','cv']
TOPK = 20; REB = 1; SELL_RANK = 100; STOP_ATR = 3.0; TP = 0.25; NOTIONAL = 100000; LIQ = 2e7
FEE_B = 0.001425; FEE_S = 0.001425 + 0.003
_M = {}

def model():
    if "m" not in _M:
        try: _M["m"] = json.load(open("aipick_pv_model.json", encoding="utf-8"))
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

def feats_df(o):
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
    F['liq'] = val.rolling(20).median(); F['atr_abs'] = tr.rolling(14).mean()
    return F

def feats_last(o):
    if not o or len(o) < 262: return None, None
    F = feats_df(o[-300:]); row = F.iloc[-1]
    x = [float(row[f]) if row[f] == row[f] else float('nan') for f in FEATS]
    if sum(1 for v in x if v != v) > 3: return None, None
    return x, row

def _bar(A, sid, day):
    d, o = A.bars_of(sid)
    if not d: return None, None
    try: i = d.index(day)
    except ValueError: return None, None
    return o[i], o[i-1] if i > 0 else None

def run(A, data, T, last, log=print):
    """收盤班呼叫:① 以今天日K成交上一輪訊號的進出(開盤價)② 盤中停損/停利(用今天最高最低)③ 每 5 個交易日重排前 20 名"""
    S = T.setdefault("pv", {"pos": [], "pend": [], "trades": [], "log": [], "nav": [], "picks": [], "last_rb": None, "start": last})
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
                ev.append(f"{last} 🔄 量價組換股賣出 {p['name']} 開盤 {op}({ret*100:+.1f}%)")
        else:
            if pb and pb[3] and op >= pb[3]*1.095: ev.append(f"{last} ❎ 量價組 {q['name']} 漲停開出買不到,放棄"); continue
            if any(x["id"] == q["id"] for x in S["pos"]): continue
            stp = round(op - STOP_ATR*q["atr"], 2); tp = round(op*(1+TP), 2)
            S["pos"].append({"id": q["id"], "name": q["name"], "fill": last, "entry": op, "sh": int(NOTIONAL/op), "stop": stp, "tp": tp, "rank": q.get("rank"), "sig_d": q["sig_d"]})
            ev.append(f"{last} 🟢 買進 量價組 {q['name']} 開盤 {op}(停損 {stp}、停利 {tp})")
    S["pend"] = keep
    # ② 停損/停利(含今天剛買的)
    for p in (list(S["pos"]) if fresh else []):
        b, _ = _bar(A, p["id"], last)
        if not b: continue
        o_, h_, l_ = b[0], b[1], b[2]; xp = why = None
        if l_ and l_ <= p["stop"]: xp, why = min(o_, p["stop"]), "sl"
        elif h_ and h_ >= p["tp"]: xp, why = max(o_, p["tp"]), "tp"
        if xp:
            ret = (xp*(1-FEE_S))/(p["entry"]*(1+FEE_B))-1
            S["trades"].append({**p, "xd": last, "xp": xp, "why": why, "ret": round(ret*100, 2)}); S["pos"].remove(p)
            ev.append(f"{last} {'🛑 停損' if why=='sl' else '🎯 停利'} 量價組 {p['name']} {xp}({ret*100:+.1f}%)")
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
            x, row = feats_last(o)
            if x is None or not (row["liq"] >= LIQ): continue
            z = score(x)
            if z is not None: sc.append((z, s, float(row["atr_abs"])))
        sc.sort(key=lambda t: -t[0])
        if len(sc) >= 100:                                  # r1029:每檔量價排名 + ATR(個股頁/卡片算停損用)
            S["rank_all"] = {s["id"]: [i+1, round(at, 4)] for i, (z, s, at) in enumerate(sc)}; S["rank_d"] = last; S["n_scored"] = len(sc)
        if len(sc) >= 100 and due and fresh:
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
                S["pend"].append({"id": s["id"], "name": s.get("name"), "act": "buy", "sig_d": last, "atr": at, "rank": i+1}); slots -= 1
            nb = [q["name"] for q in S["pend"] if q["act"] == "buy" and q["sig_d"] == last]; ns = [q["name"] for q in S["pend"] if q["act"] == "sell" and q["sig_d"] == last]
            if nb or ns: ev.append(f"{last} 📈 量價組收盤重排:明天開盤買進 {'、'.join(nb) or '無'};明天開盤換股賣出 {'、'.join(ns) or '無'}")
            S["last_rb"] = last
    # 淨值
    real = sum(t["ret"]/100*NOTIONAL for t in S["trades"]); unreal = 0.0
    for p in S["pos"]:
        d, o = A.bars_of(p["id"]); c = o[-1][3] if o else None
        if c: unreal += (c - p["entry"])*p["sh"]; p["px"] = c
    e8d, e8o = A.bars_of("0050"); e8 = e8o[-1][3] if e8o and e8d and e8d[-1] == last else None
    S["nav"] = [x for x in S["nav"] if x[0] != last][-400:] + [[last, round(real+unreal), len(S["pos"]), e8]]
    tr_ = S["trades"]
    S["stats"] = {"closed": len(tr_), "win": round(100*sum(1 for t in tr_ if t["ret"] > 0)/len(tr_), 1) if tr_ else None,
                  "avg": round(sum(t["ret"] for t in tr_)/len(tr_), 2) if tr_ else None, "realized": round(real)}
    S["rules"] = {"topk": TOPK, "reb": REB, "sell_rank": SELL_RANK, "stop_atr": STOP_ATR, "tp": TP, "liq": LIQ}
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
                ev.append(f"{today} 09:00 🔄 量價組換股賣出 {p['name']} 官方開盤 {op}({ret*100:+.1f}%)")
            continue
        d, o = A.bars_of(q["id"]); pc = o[-1][3] if o and d and d[-1] < today else None
        if pc and h == l and op >= pc*1.095: ev.append(f"{today} 09:00 ❎ 量價組 {q['name']} 漲停鎖死買不到,放棄"); continue
        if any(x["id"] == q["id"] for x in S["pos"]) or len(S["pos"]) >= TOPK: continue
        stp = round(op - STOP_ATR*q["atr"], 2); tp = round(op*(1+TP), 2)
        S["pos"].append({"id": q["id"], "name": q["name"], "fill": today, "ft": "09:00", "entry": op, "sh": int(NOTIONAL/op), "stop": stp, "tp": tp, "rank": q.get("rank"), "sig_d": q["sig_d"]})
        ev.append(f"{today} 09:00 🟢 買進 量價組 {q['name']} 官方開盤 {op}(停損 {stp}、停利 {tp})")
    S["pend"] = keep
    for p in list(S["pos"]):
        px, hl = live(p["id"])
        if px is None or not hl: continue
        op, h, l = hl; xp = why = None
        if l <= p["stop"]: xp, why = min(op, p["stop"]), "sl"
        elif h >= p["tp"]: xp, why = max(op, p["tp"]), "tp"
        if xp:
            ret = (xp*(1-FEE_S))/(p["entry"]*(1+FEE_B))-1
            S["trades"].append({**p, "xd": today, "xt": hhmm, "xp": xp, "why": why, "ret": round(ret*100, 2)}); S["pos"].remove(p)
            ev.append(f"{today} {hhmm} {'🛑 停損' if why=='sl' else '🎯 停利'} 量價組 {p['name']} {xp}({ret*100:+.1f}%)")
        else: p["px"] = px
    for e in ev: S["log"].insert(0, e); T.setdefault("log", []).insert(0, e); log("pv:" + e)

BT = {"range": "2016-01~2026-09", "cagr": 30.7, "mdd": -41.7, "b0050": 25.4, "bmdd0050": -32.6, "mkt": 16.2,
      "years": {"2016": [20.8, 26.3], "2017": [28.0, 18.5], "2018": [9.7, -8.6], "2019": [29.9, 34.1], "2020": [32.0, 42.7], "2021": [58.4, 14.5],
                "2022": [2.1, -18.9], "2023": [48.4, 21.8], "2024": [42.8, 57.5], "2025": [21.4, 40.2], "2026": [36.5, 60.7]},
      "variants": [["每週換股(原設計)", 27.4, -35.3], ["每天換股、掉出前 20 就賣", -1.2, -64.5], ["每天、掉出前 40 才賣", 23.3, -43.1],
                   ["每天、掉出前 60 才賣", 29.5, -43.6], ["每天、掉出前 100 才賣(採用)", 30.7, -41.7],
                   ["(每週版)不設停損停利", 30.4, -37.7], ["(每週版)停損 −8%", 21.5, -35.0], ["(每週版)停利 +15%", 27.2, -37.5], ["(每週版)收盤破月線停損", 2.1, -38.4]]}
