"""r975:🤖 AI 交易員(台股)——取代「每週固定名單」的新規則,由 aipick.py 重班結尾呼叫
依據:2019/06~2026/10 組合層級回測(同模型、扣成本、真實成交規則):
  現行週選股+固定目標 年化 +3.5% / 最大回落 −28%;本規則 年化 +17.0% / 最大回落 −31%、每年約 41 筆
規則:
  進場——任何交易日收盤後,v2 模型勝算 ≥ 0.54(全市場約前 1%)、股價 ≥10、同產業 ≤2 檔、有空位(上限 10 檔)
        → 隔一個交易日「開盤價」買進;開盤漲停鎖死(開=高=低 且 ≥ 昨收+9.5%)或跳空 > 訊號日收盤 +3% → 不追、取消
  出場——停損:個股結構支撐(aipick.stock_levels);不設固定目標;
        漲超過進場價 10% 後啟動移動停利:最高價回落 15% 出場(停利線只上不下);
        以官方日 K 判定:最低價 ≤ 停損/停利線 → 以停損價(跳空開低則以開盤價)出場;跌停鎖死賣不掉 → 順延
  紀錄——每筆都是官方日 K 可驗證的成交;每檔名目 NT$100,000(10 檔 = 100 萬)
"""
import json, os, datetime as dt
FILE = "trader.json"; SLOTS = 10; PMIN = 0.54; MAX_SECTOR = 2; GAP_MAX = 0.03; TRAIL_ON = 1.10; TRAIL_DD = 0.85
NOTIONAL = 100000; FEE_B = 0.001425; FEE_S = 0.001425 + 0.003; START = "2026-10-05"


def _prev_close(o, i):
    return o[i - 1][3] if i > 0 and o[i - 1] and o[i - 1][3] else None


def sector_trend(A, data, last):
    """r979:產業等權指數(同產業成份股每日平均報酬累乘)是否在自己的 20 日線之上——回測:只買「產業在月線上」的訊號,
    年化 +17.0% → +19.4%、最大回落 −31.5% → −27.3%;只週三進場的穩健檢查也從 +15.5% → +21.2%(回落 −36.5% → −27.1%)"""
    rets = {}
    for s in data.get("stocks", []):
        if s.get("market") != "TW" or s.get("etf") or not s.get("sector"): continue
        d, o = A.bars_of(s["id"])
        if len(d) < 41 or d[-1] != last: continue
        c = [b[3] for b in o[-41:]]
        if any(not x for x in c): continue
        r = [max(-0.11, min(0.11, c[i] / c[i - 1] - 1)) for i in range(1, 41)]
        rets.setdefault(s["sector"], []).append(r)
    out = {}
    for sec, L in rets.items():
        if len(L) < 3: continue
        m = [sum(x[i] for x in L) / len(L) for i in range(40)]
        ix = []; v = 1.0
        for x in m: v *= 1 + x; ix.append(v)
        ma20 = sum(ix[-20:]) / 20
        out[sec] = {"up": ix[-1] >= ma20, "gap": round((ix[-1] / ma20 - 1) * 100, 2), "n": len(L)}
    return out


def has_jump(o, n=260):
    """r979:近一年有單日漲跌超過 ±11.5%(台股漲跌幅上限 10%)= 未還原的除權/減資/分割(例:緯穎 9/2 7800→2610)
    → 這檔的均線、報酬等特徵全部失真,模型分數不可信,不進場"""
    for i in range(max(1, len(o) - n), len(o)):
        a, b = o[i - 1][3], o[i][3]
        if a and b and (b / a > 1.115 or b / a < 0.885): return True
    return False


def inst_cost(A, sid):
    """近 60 個交易日「法人淨買超日」的加權均價(參考用,顯示在持股卡)"""
    ch = A.chip_of(sid) or {}; d, o = A.bars_of(sid)
    px = {dd: b[3] for dd, b in zip(d[-60:], o[-60:])}
    num = den = 0.0
    for dd, f, t in zip(ch.get("d") or [], ch.get("f") or [], ch.get("t") or []):
        nb = (f or 0) + (t or 0)
        if dd in px and nb > 0: num += nb * px[dd]; den += nb
    return round(num / den, 2) if den else None


def run(A, data, log=print):
    """A = aipick 模組(bars_of / chip_of / stock_levels / rtick / TODAY / NOW)"""
    # 狀態存在 aipick.json 的 "trader" 欄(update_data 只 commit aipick.json,不會 commit 新檔)
    try: T = (json.load(open(A.OUT, encoding="utf-8")).get("trader")) or {}
    except Exception: T = {}
    T.setdefault("ver", "r975"); T.setdefault("start", START); T.setdefault("pos", []); T.setdefault("pend", [])
    T.setdefault("trades", []); T.setdefault("log", []); T.setdefault("sig_done", "")
    T["rules"] = {"slots": SLOTS, "pmin": PMIN, "gap_max": GAP_MAX, "trail_on": TRAIL_ON, "trail_dd": TRAIL_DD, "max_sector": MAX_SECTOR, "notional": NOTIONAL}
    T["rules"]["sector_filter"] = True
    T["bt"] = {"period": "2019/06~2026/10", "cagr": 19.4, "mdd": -27.3, "trades_y": 36, "win": 27.4, "avg": 5.08,
               "old": {"cagr": 3.5, "mdd": -28.3, "trades_y": 137, "win": 44.4, "avg": 0.33}}
    byid = {s["id"]: s for s in data.get("stocks", [])}
    bd, _ = A.bars_of(A.BENCH_SID); last = bd[-1] if bd else ""
    if not last: return T
    ev = []
    # ⓪ r977:盤中即時成交的「官方日 K 核對」——買進價必須 = 當天官方開盤;出場必須當天最低價真的 ≤ 出場價
    for p in list(T["pos"]):
        if not p.get("rt") or p.get("ok"): continue
        d, o = A.bars_of(p["id"])
        if p["fill"] not in d: continue
        b = o[d.index(p["fill"])]
        if abs(b[0] - p["entry"]) > 1e-6:
            ev.append(f"{p['fill']} ⚠ 核對:{p['name']} 盤中記錄開盤 {p['entry']} ≠ 官方 {b[0]},以官方為準"); p["entry"] = b[0]; p["hi"] = max(p["hi"], b[0])
        p["ok"] = 1
    for t in list(T["trades"]):
        if not t.get("rt") or t.get("ok"): continue
        d, o = A.bars_of(t["id"])
        if t["xd"] not in d: continue
        b = o[d.index(t["xd"])]
        if b[2] <= t["xp"] + 1e-6: t["ok"] = 1; continue
        T["trades"].remove(t)                                              # 官方最低價沒到 → 盤中誤判,撤銷出場
        T["pos"].append({k: t[k] for k in ("id", "name", "sector", "fill", "entry", "sh", "stop0", "p", "sig_d")} |
                        {"stop": t.get("line", t["stop0"]), "hi": t.get("hi", t["entry"]), "seen": d[d.index(t["xd"]) - 1] if d.index(t["xd"]) > 0 else t["fill"], "ok": 1})
        ev.append(f"{t['xd']} ↩ 核對:{t['name']} 官方最低 {b[2]} 未觸及出場價 {t['xp']},撤銷盤中出場")
    # ① 待買單:訊號日之後第一根 K 的開盤
    keep = []
    for q in T["pend"]:
        d, o = A.bars_of(q["id"])
        idx = next((i for i in range(len(d)) if d[i] > q["sig_d"]), None)
        if idx is None: keep.append(q); continue
        b = o[idx]; pc = _prev_close(o, idx); op = b[0]
        if not op or op <= 0: ev.append(f"{d[idx]} ❎ {q['name']} 當天無成交,取消"); continue
        if pc and b[1] == b[2] and op >= pc * 1.095: ev.append(f"{d[idx]} ❎ {q['name']} 開盤漲停鎖死買不到,取消"); continue
        if op > q["sig_px"] * (1 + GAP_MAX): ev.append(f"{d[idx]} ❎ {q['name']} 開盤 {op} 跳空 > +3% 不追,取消"); continue
        if len(T["pos"]) >= SLOTS: ev.append(f"{d[idx]} ❎ {q['name']} 已滿 {SLOTS} 檔,取消"); continue
        lo = max(0, idx - 260); oo = o[lo:idx + 1]; dd = d[lo:idx + 1]
        tr = [max(x[1] - x[2], abs(x[1] - y[3]), abs(x[2] - y[3])) for x, y in zip(oo[1:], oo[:-1])]
        a = sum(tr[-14:]) / max(1, len(tr[-14:]))
        try: _, stp, LV = A.stock_levels(dd, oo, op, a, byid.get(q["id"]))
        except Exception: stp = op * 0.92; LV = {}
        sh = int(NOTIONAL / op)
        T["pos"].append({"id": q["id"], "name": q["name"], "sector": q.get("sector"), "fill": d[idx], "entry": op, "sh": sh,
                         "stop0": round(float(stp), 2), "stop": round(float(stp), 2), "hi": op, "p": q["p"], "sig_d": q["sig_d"], "seen": d[idx],
                         "stp_src": (LV or {}).get("stp_src"), "dn_med": (LV or {}).get("dn_med")})
        ev.append(f"{d[idx]} 🟢 買進 {q['name']} 開盤 {op}(停損 {round(float(stp), 2)})")
    T["pend"] = keep
    # ② 持股:逐根 K 檢查停損 / 移動停利
    still = []
    for p in T["pos"]:
        d, o = A.bars_of(p["id"]); out = None
        for i in range(len(d)):
            if d[i] <= p["seen"]: continue
            b = o[i]; op, h, l = b[0], b[1], b[2]; pc = _prev_close(o, i)
            locked_dn = pc and h == l and op <= pc * 0.905
            line = p["stop"]
            if l <= line and not locked_dn:
                xp = op if op <= line else line
                why = "trail" if line > p["stop0"] else "sl"
                out = (d[i], xp, why); p["seen"] = d[i]; break
            p["hi"] = max(p["hi"], h)
            if p["hi"] >= p["entry"] * TRAIL_ON: p["stop"] = round(max(p["stop"], p["hi"] * TRAIL_DD), 2)
            p["seen"] = d[i]
        if out:
            ret = (out[1] * (1 - FEE_S)) / (p["entry"] * (1 + FEE_B)) - 1
            T["trades"].append({**{k: p[k] for k in ("id", "name", "sector", "fill", "entry", "sh", "stop0", "p", "sig_d")},
                                "xd": out[0], "xp": round(float(out[1]), 2), "why": out[2], "ret": round(ret * 100, 2), "hi": p["hi"]})
            T["trades"][-1]["line"] = p["stop"]
            ev.append(f"{out[0]} {'🔒 移動停利' if out[2] == 'trail' else '🛑 停損'} {p['name']} @{round(float(out[1]), 2)}({ret*100:+.2f}%)")
        else: still.append(p)
    T["pos"] = still
    # ③ 收盤決策(每個交易日一次;最新 K 全市場入庫 ≥90% 才做)
    if last >= START and T["sig_done"] < last:
        tot = hit = 0; lo = (dt.date.fromisoformat(last) - dt.timedelta(days=10)).isoformat()
        for s in data.get("stocks", []):
            if s.get("market") != "TW" or s.get("etf"): continue
            dd, _ = A.bars_of(s["id"])
            if not dd or dd[-1] < lo: continue
            tot += 1; hit += 1 if dd[-1] >= last else 0
        if tot and hit / tot >= 0.9:
            from aipick_v2 import V2Scorer
            V = V2Scorer(A.bars_of, A.chip_of, data, mkt="TW")
            sc = []
            for s in data.get("stocks", []):
                if s.get("market") != "TW" or s.get("etf"): continue
                d, o = A.bars_of(s["id"])
                if not d or d[-1] != last or not o[-1][3] or o[-1][3] < 10: continue
                if has_jump(o): continue
                try: pr = V.prob(s["id"], s, d, o)
                except Exception: pr = None
                if pr is not None: sc.append((pr, s))
            sc.sort(key=lambda x: -x[0])
            ST = sector_trend(A, data, last); T["sectors"] = ST
            held = {p["id"] for p in T["pos"]} | {q["id"] for q in T["pend"]}
            secn = {}
            for p in T["pos"] + T["pend"]: secn[p.get("sector")] = secn.get(p.get("sector"), 0) + 1
            free = SLOTS - len(T["pos"]) - len(T["pend"]); new = []
            for pr, s in sc:
                if free <= 0 or pr < PMIN: break
                if s["id"] in held or secn.get(s.get("sector"), 0) >= MAX_SECTOR: continue
                if not (ST.get(s.get("sector")) or {"up": True})["up"]: continue      # r979:產業在月線下 → 不進場
                d, o = A.bars_of(s["id"])
                q = {"id": s["id"], "name": s.get("name"), "sector": s.get("sector"), "sig_d": last, "sig_px": o[-1][3], "p": round(pr, 4),
                     "sec_gap": (ST.get(s.get("sector")) or {}).get("gap"), "icost": inst_cost(A, s["id"])}
                T["pend"].append(q); new.append(q); held.add(s["id"]); secn[s.get("sector")] = secn.get(s.get("sector"), 0) + 1; free -= 1
            T["top"] = [{"id": s["id"], "name": s.get("name"), "p": round(pr, 4), "sector": s.get("sector"),
                         "sec_up": (ST.get(s.get("sector")) or {"up": True})["up"]} for pr, s in sc[:15]]
            for p in T["pos"]:
                try: p["icost"] = inst_cost(A, p["id"]); p["sec_gap"] = (ST.get(p.get("sector")) or {}).get("gap")
                except Exception: pass
            T["sig_done"] = last; T["n_scored"] = len(sc)
            ev.append(f"{last} 🔍 收盤掃描 {len(sc)} 檔,勝算 ≥{PMIN} 有 {sum(1 for x in sc if x[0] >= PMIN)} 檔;" +
                      ("明天開盤買進:" + "、".join(q["name"] for q in new) if new else "沒有新進場(" + ("已滿" if free <= 0 else "沒有夠強的標的") + ")"))
        else:
            log(f"trader:{last} K 入庫 {hit}/{tot} 未達 90%,本班不做收盤決策")
    for e in ev: T["log"].insert(0, e)
    T["log"] = T["log"][:300]
    tr_ = T["trades"]
    T["stats"] = {"closed": len(tr_), "win": round(100 * sum(1 for t in tr_ if t["ret"] > 0) / len(tr_), 1) if tr_ else None,
                  "avg": round(sum(t["ret"] for t in tr_) / len(tr_), 2) if tr_ else None,
                  "realized": round(sum(t["ret"] / 100 * NOTIONAL for t in tr_))}
    T["updated"] = A.NOW.strftime("%Y-%m-%d %H:%M"); T["last_bar"] = last
    for e in ev: log("trader:" + e)
    return T


def run_intraday(A, data, hhmm, log=print):
    """r977:盤中即時執行(盤中 5 分鐘輕量班呼叫)——
    ① 待買單:09:00 開盤一出來就以「官方開盤價」成交(開盤跳空 > +3% 取消;開盤即漲停且還鎖著 → 先等,收盤日 K 再判)
    ② 持股:真實成交價(MIS z)跌破出場線、且今天官方最低價也 ≤ 出場線 → 當下出場,記下時間
       移動停利線用今天官方最高價即時上調
    所有盤中紀錄晚上都會再用官方日 K 核對(run 的 ⓪)"""
    try: T = (json.load(open(A.OUT, encoding="utf-8")).get("trader")) or {}
    except Exception: return None
    if not T or not ("09:00" <= hhmm <= "13:30"): return T
    today = A.iso(A.TODAY); byid = {s["id"]: s for s in data.get("stocks", [])}
    def live(sid):
        s = byid.get(sid) or {}
        ok = s.get("pz") == 1 and str(s.get("pt") or "")[:10] == today and s.get("dhd") == today and s.get("dhl")
        return (float(s["price"]), s["dhl"]) if ok else (None, None)
    ev = []; keep = []
    for q in T.get("pend") or []:
        if q["sig_d"] >= today: keep.append(q); continue
        px, hl = live(q["id"])
        if not hl: keep.append(q); continue
        op, h, l = hl
        d, o = A.bars_of(q["id"]); pc = o[-1][3] if o and d and d[-1] < today else q["sig_px"]
        if op > q["sig_px"] * (1 + GAP_MAX) and not (h == l and op >= pc * 1.095):
            ev.append(f"{today} {hhmm} ❎ {q['name']} 開盤 {op} 跳空 > +3% 不追,取消"); continue
        if h == l and op >= pc * 1.095: keep.append(q); continue          # 漲停鎖著:收盤後日 K 判定
        if len(T.get("pos") or []) >= SLOTS: ev.append(f"{today} {hhmm} ❎ {q['name']} 已滿 {SLOTS} 檔,取消"); continue
        lo = max(0, len(o) - 260); oo = o[lo:]; dd = d[lo:]
        tr = [max(x[1] - x[2], abs(x[1] - y[3]), abs(x[2] - y[3])) for x, y in zip(oo[1:], oo[:-1])]
        a = sum(tr[-14:]) / max(1, len(tr[-14:]))
        try: _, stp, LV = A.stock_levels(dd, oo, op, a, byid.get(q["id"]))
        except Exception: stp = op * 0.92; LV = {}
        T.setdefault("pos", []).append({"id": q["id"], "name": q["name"], "sector": q.get("sector"), "fill": today, "ft": "09:00", "entry": op,
                                        "sh": int(NOTIONAL / op), "stop0": round(float(stp), 2), "stop": round(float(stp), 2), "hi": op,
                                        "p": q["p"], "sig_d": q["sig_d"], "seen": today, "rt": 1,
                                        "stp_src": (LV or {}).get("stp_src"), "dn_med": (LV or {}).get("dn_med")})
        ev.append(f"{today} 09:00 🟢 買進 {q['name']} 官方開盤 {op}(停損 {round(float(stp), 2)})")
    T["pend"] = keep
    still = []
    for p in T.get("pos") or []:
        px, hl = live(p["id"])
        if px is None or p.get("seen", "") > today or (p["fill"] == today):   # 進場當天不判出場(與回測相同)
            still.append(p); continue
        op, h, l = hl
        hi_now = max(p["hi"], h)                                           # 移動停利線即時計算(不寫回,收盤日 K 再正式更新)
        line = round(max(p["stop"], hi_now * TRAIL_DD), 2) if hi_now >= p["entry"] * TRAIL_ON else p["stop"]
        p["line_rt"] = line
        if px <= line and l <= line:
            xp = op if op <= line else line
            why = "trail" if line > p["stop0"] else "sl"
            ret = (xp * (1 - FEE_S)) / (p["entry"] * (1 + FEE_B)) - 1
            T.setdefault("trades", []).append({**{k: p[k] for k in ("id", "name", "sector", "fill", "entry", "sh", "stop0", "p", "sig_d")},
                                               "xd": today, "xt": hhmm, "xp": round(float(xp), 2), "why": why, "ret": round(ret * 100, 2), "hi": p["hi"], "line": line, "rt": 1})
            ev.append(f"{today} {hhmm} {'🔒 移動停利' if why == 'trail' else '🛑 停損'} {p['name']} @{round(float(xp), 2)}({ret*100:+.2f}%)")
            continue
        still.append(p)
    T["pos"] = still
    for e in ev: T.setdefault("log", []).insert(0, e); log("trader:" + e)
    T["log"] = T.get("log", [])[:300]; T["updated"] = A.NOW.strftime("%Y-%m-%d %H:%M")
    return T
