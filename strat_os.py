"""r1049:🎯 錯殺低接——實戰追蹤(每天收盤掃描全市場,記下訊號、隔天開盤虛擬買進,照規則出場,累積實戰成績)
規則(2012~2026 回測驗證 ✅;r1143 門檻由 −30% 改 −40%):離 60 日最高點跌 ≥40% 的第一天 → 隔天 9:00 開盤買;停利 +20%、停損 −15%、最多抱 60 個交易日。
   r1143 重測(2016~2026,全市場):門檻 −25% +1.7%/勝率 50% → −30% +3.2%/54% → −35% +4.8%/58% → −40% +6.4%/63%(2,583 次、獲利因子 2.1、11 年全正、前後半段都正)
   → −45%/−50% 平均再高一點但樣本少、有年度轉負,取 −40%。實戰 10/8~10/22 的 −30% 訊號 40 檔平均 −5.6%,也印證 −30% 太早。
   舊版(−30%)數據:
   營收好(近 3 月 YoY 都 >0 或近 3 月有創 13 個月新高):4,933 次、勝率 55%、平均 +3.18%;隨機買進同規則平均 +0.59%。
   營收不好也有效(平均 +2.93%),營收好略佳。注意:歷史資料不含已下市股票,跌深股的回測可能偏樂觀。
另外輸出 rq:每檔的營收品質旗標(給前端判斷「有未來性」)。"""
import json, gzip

DD = -0.40; TP = 0.30; SL = 0.20; HOLD = 90; LIQ = 2e7; RULE_V = 40   # r1178:出場 −15%/+20%/60 → −20%/+30%/90(每筆 +6.4% → +10.4%、勝率 63%);已進場的 open 部位帶自己的 tp/sl 價照原規則走完   # r1143:−30% → −40%;新訊號標 r=40,舊紀錄沒有 r 欄位
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
    # r1143:規則改 −40% 當天,舊門檻(沒有 r 欄位)還沒成交的待買單作廢,不再用 −30% 進場
    old = [q for q in (S.get("pend") or []) if q.get("r") != RULE_V]
    if old:
        S["pend"] = [q for q in S["pend"] if q.get("r") == RULE_V]
        ev.append(f"{last} 🎯 錯殺低接規則改為 −{int(abs(DD)*100)}%:舊門檻待買 {len(old)} 檔作廢(" + "、".join(q["name"] for q in old[:8]) + ")")
    # ① 待買:隔天開盤成交
    keep = []
    for q in S.get("pend") or []:
        if q["sig_d"] >= last: keep.append(q); continue
        d, o = A.bars_of(q["id"])
        if not d or last not in d: keep.append(q) if q.get("tries", 0) < 3 else None; q["tries"] = q.get("tries", 0) + 1; continue
        b = o[d.index(last)]; op = b[0]
        if not op: continue
        S["open"].append({"id": q["id"], "name": q["name"], "sig_d": q["sig_d"], "fill": last, "entry": op, "tp": round(op * (1 + TP), 2), "sl": round(op * (1 - SL), 2), "q": q.get("q"), "n": 0, "r": q.get("r"), "hold": HOLD, "b60": q.get("b60"), "mkt": q.get("mkt")})
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
        # r1157:開盤可知的成交優先；其餘同日雙觸價仍採停損優先。
        if op and op <= p["sl"]: xp, why = op, "sl"
        elif op and op >= p["tp"]: xp, why = op, "tp"
        elif l and l <= p["sl"]: xp, why = p["sl"], "sl"
        elif h and h >= p["tp"]: xp, why = p["tp"], "tp"
        elif p["n"] >= (p.get("hold") or 60): xp, why = c, "time"   # r1178:每筆帶自己的最長持有天數(10/27 前進場的照原 60 天)
        if xp:
            ret = xp * (1 - 0.004425) / (p["entry"] * 1.001425) - 1
            S["closed"].append({**p, "xd": last, "xp": xp, "why": why, "ret": round(ret * 100, 2)})
            ev.append(f"{last} 🎯 錯殺低接{'停利' if why == 'tp' else '停損' if why == 'sl' else '到期'} {p['name']} {xp}({ret*100:+.1f}%)")
        else: still.append(p)
    S["open"] = still
    # ③ 新訊號:今天第一次離 60 日高 ≥40%(r1143)
    try: from trader import has_jump
    except Exception: has_jump = lambda o, n=260: False
    rq = {}; sig = []; br = [0, 0]   # r1182:市場寬度(流動股站上季線比例);<35% 時錯殺 −40% 每筆 +16.8%、其他 −1.2%(plan_bt_study.py brd2)
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
        br[1] += 1; br[0] += c[-1] > sum(c[-60:]) / 60
        dd = c[-1] / max(hh[-60:]) - 1; dd0 = c[-2] / max(hh[-61:-1]) - 1
        if dd <= DD and dd0 > DD and sid not in held:
            qq = rq.get(sid); qual = bool(qq and (qq[0] or qq[1]))
            sig.append({"id": sid, "name": s.get("name"), "sig_d": last, "q": int(qual), "dd": round(dd * 100, 1), "px": c[-1], "r": RULE_V})
    b60 = round(br[0] / br[1], 3) if br[1] >= 200 else None
    for q in sig: q["b60"] = b60; q["mkt"] = int(b60 is not None and b60 < 0.35)   # 只記錄不過濾:實戰照舊全買,另算「大盤一起跌」那批的成績
    S["b60"] = [last, b60]
    for q in sig: S["pend"].append(q)
    if sig: ev.append(f"{last} 🎯 錯殺低接訊號:明天開盤買 " + "、".join(f"{q['name']}(離高點 {q['dd']}%{'・營收好' if q['q'] else ''})" for q in sig[:12]) + (f" 等 {len(sig)} 檔" if len(sig) > 12 else ""))
    S["sig"] = sig; S["rq"] = rq; S["rq_d"] = last
    cl = S["closed"]
    def _st(cl, op):
        return {"closed": len(cl), "win": round(100 * sum(1 for t in cl if t["ret"] > 0) / len(cl), 1) if cl else None,
                "avg": round(sum(t["ret"] for t in cl) / len(cl), 2) if cl else None, "open": len(op)}
    S["stats"] = _st(cl, S["open"])
    S["stats40"] = _st([t for t in cl if t.get("r") == RULE_V], [p for p in S["open"] if p.get("r") == RULE_V])   # r1143:新規則單獨計
    S["statsMkt"] = _st([t for t in cl if t.get("mkt") == 1], [p for p in S["open"] if p.get("mkt") == 1])   # r1182:大盤一起跌(站上季線 <35%)時的訊號
    S["statsNoMkt"] = _st([t for t in cl if t.get("mkt") == 0], [p for p in S["open"] if p.get("mkt") == 0])
    S["stats30"] = _st([t for t in cl if not t.get("r")], [p for p in S["open"] if not p.get("r")])
    S["closed"] = cl  # r1157:錯殺交易永久保存，不截400筆
    S["rules"] = {"dd": DD, "tp": TP, "sl": SL, "hold": HOLD, "v": RULE_V,
                  "bt": {"all": [2301, 10.43, 63], "good": [598, 7.23, 65], "pf": 2.48, "years": "10/11", "range": "2016~2026",
                         "old30": [7305, 3.21, 54], "rand": [48344, 0.59, 47], "halves": [[753, 4.96, 58], [1831, 7.01, 64]],
                         "mkt": {"weak": [1485, 16.8, 76], "other": [816, -1.2, 39], "th": 0.35}}}
    S["done"] = last
    for e in ev: log("os:" + e)
    return S
