"""r1049:🎯 錯殺低接——實戰追蹤(每天收盤掃描全市場,記下訊號、隔天開盤虛擬買進,照規則出場,累積實戰成績)
規則(2012~2026 回測驗證 ✅):離 60 日最高點跌 ≥30% 的第一天 → 隔天 9:00 開盤買;停利 +20%、停損 −15%、最多抱 60 個交易日。
   營收好(近 3 月 YoY 都 >0 或近 3 月有創 13 個月新高):4,933 次、勝率 55%、平均 +3.18%;隨機買進同規則平均 +0.59%。
   營收不好也有效(平均 +2.93%),營收好略佳。注意:歷史資料不含已下市股票,跌深股的回測可能偏樂觀。
另外輸出 rq:每檔的營收品質旗標(給前端判斷「有未來性」)。"""
import json, gzip

DD = -0.30; TP = 0.20; SL = 0.15; HOLD = 60; LIQ = 2e7
_REV = {}


def rev_q(sid, day):
    """回傳 [營收連 3 月成長(0/1), 近 3 月創 13 個月新高(0/1), 最新 YoY%] ——只用 day 當天已公布的月份(M 月營收 M+1 月 11 日起)"""
    k = sid[:2]
    if k not in _REV:
        try: _REV[k] = json.load(gzip.open(f"archive/rev/tw/{k}.json.gz", "rt"))
        except Exception: _REV[k] = {}
    e = _REV[k].get(sid) or {}; R = dict(zip(e.get("m") or [], e.get("r") or []))
    if not R: return None
    y, m = int(day[:4]), int(day[5:7]); m -= 1 if int(day[8:10]) >= 11 else 2
    while m <= 0: m += 12; y -= 1
    ms = sorted(x for x in R if x <= f"{y}-{m:02d}")
    if len(ms) < 15: return None
    def ym(s, back):
        yy, mm = int(s[:4]), int(s[5:7]) - back
        while mm <= 0: mm += 12; yy -= 1
        return f"{yy}-{mm:02d}"
    last = ms[-1]; yoy = []
    for i in range(3):
        a, b = R.get(ym(last, i)), R.get(ym(last, i + 12))
        yoy.append((a / b - 1) if a and b and b > 0 else None)
    pos3 = int(all(v is not None and v > 0 for v in yoy))
    r13 = 0
    for i in range(3):
        cur = R.get(ym(last, i)); prev = [R.get(ym(last, i + j)) for j in range(1, 13)]
        prev = [p for p in prev if p]
        if cur and len(prev) >= 10 and cur >= max(prev): r13 = 1
    return [pos3, r13, round(yoy[0] * 100, 1) if yoy[0] is not None else None]


def run(A, data, T, last, log=print):
    S = T.setdefault("os", {"open": [], "pend": [], "closed": [], "start": last})
    if S.get("done") == last: return S
    ev = []
    # ① 待買:隔天開盤成交
    keep = []
    for q in S.get("pend") or []:
        if q["sig_d"] >= last: keep.append(q); continue
        d, o = A.bars_of(q["id"])
        if not d or last not in d: keep.append(q) if q.get("tries", 0) < 3 else None; q["tries"] = q.get("tries", 0) + 1; continue
        b = o[d.index(last)]; op = b[0]
        if not op: continue
        S["open"].append({"id": q["id"], "name": q["name"], "sig_d": q["sig_d"], "fill": last, "entry": op, "tp": round(op * (1 + TP), 2), "sl": round(op * (1 - SL), 2), "q": q.get("q"), "n": 0})
    S["pend"] = keep
    # ② 出場(含今天剛買的,用今天日 K)
    still = []
    for p in S["open"]:
        d, o = A.bars_of(p["id"])
        if not d or last not in d: still.append(p); continue
        b = o[d.index(last)]; op, h, l, c = b[0], b[1], b[2], b[3]
        if p.get("seen") == last: still.append(p); continue
        p["seen"] = last; p["n"] = p.get("n", 0) + 1; p["px"] = c
        xp = why = None
        if l and l <= p["sl"]: xp, why = (min(op, p["sl"]) if p["fill"] != last else p["sl"]), "sl"
        elif h and h >= p["tp"]: xp, why = (max(op, p["tp"]) if p["fill"] != last else p["tp"]), "tp"
        elif p["n"] >= HOLD: xp, why = c, "time"
        if xp:
            ret = xp * (1 - 0.004425) / (p["entry"] * 1.001425) - 1
            S["closed"].append({**p, "xd": last, "xp": xp, "why": why, "ret": round(ret * 100, 2)})
            ev.append(f"{last} 🎯 錯殺低接{'停利' if why == 'tp' else '停損' if why == 'sl' else '到期'} {p['name']} {xp}({ret*100:+.1f}%)")
        else: still.append(p)
    S["open"] = still
    # ③ 新訊號:今天第一次離 60 日高 ≥30%
    try: from trader import has_jump
    except Exception: has_jump = lambda o, n=260: False
    rq = {}; sig = []
    held = {p["id"] for p in S["open"]} | {q["id"] for q in S["pend"]}
    for s in data.get("stocks", []):
        sid = str(s.get("id", ""))
        if s.get("market") != "TW" or s.get("etf") or not sid.isdigit() or len(sid) != 4: continue
        try:
            r = rev_q(sid, last)
            if r: rq[sid] = r
        except Exception: pass
        d, o = A.bars_of(sid)
        if not d or d[-1] != last or len(o) < 62: continue
        if has_jump(o, 61): continue
        c = [b[3] for b in o]; hh = [b[1] for b in o]; v = [b[4] or 0 for b in o]
        liq = sum(c[-k] * v[-k] for k in range(1, 21)) / 20 * 1000
        if liq < LIQ: continue
        dd = c[-1] / max(hh[-60:]) - 1; dd0 = c[-2] / max(hh[-61:-1]) - 1
        if dd <= DD and dd0 > DD and sid not in held:
            qq = rq.get(sid); qual = bool(qq and (qq[0] or qq[1]))
            sig.append({"id": sid, "name": s.get("name"), "sig_d": last, "q": int(qual), "dd": round(dd * 100, 1), "px": c[-1]})
    for q in sig: S["pend"].append(q)
    if sig: ev.append(f"{last} 🎯 錯殺低接訊號:明天開盤買 " + "、".join(f"{q['name']}(離高點 {q['dd']}%{'・營收好' if q['q'] else ''})" for q in sig[:12]) + (f" 等 {len(sig)} 檔" if len(sig) > 12 else ""))
    S["sig"] = sig; S["rq"] = rq; S["rq_d"] = last
    cl = S["closed"]
    S["stats"] = {"closed": len(cl), "win": round(100 * sum(1 for t in cl if t["ret"] > 0) / len(cl), 1) if cl else None,
                  "avg": round(sum(t["ret"] for t in cl) / len(cl), 2) if cl else None, "open": len(S["open"])}
    S["closed"] = cl[-400:]
    S["rules"] = {"dd": DD, "tp": TP, "sl": SL, "hold": HOLD,
                  "bt": {"good": [4933, 3.18, 55], "all": [8569, 3.10, 54], "bad": [4376, 2.93, 53], "rand": [48344, 0.59, 47], "years": "12/15", "range": "2012~2026"}}
    S["done"] = last
    for e in ev: log("os:" + e)
    return S
