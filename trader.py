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


def run(A, data, log=print):
    """A = aipick 模組(bars_of / chip_of / stock_levels / rtick / TODAY / NOW)"""
    try: T = json.load(open(FILE, encoding="utf-8"))
    except Exception: T = {}
    T.setdefault("ver", "r975"); T.setdefault("start", START); T.setdefault("pos", []); T.setdefault("pend", [])
    T.setdefault("trades", []); T.setdefault("log", []); T.setdefault("sig_done", "")
    T["rules"] = {"slots": SLOTS, "pmin": PMIN, "gap_max": GAP_MAX, "trail_on": TRAIL_ON, "trail_dd": TRAIL_DD, "max_sector": MAX_SECTOR, "notional": NOTIONAL}
    T["bt"] = {"period": "2019/06~2026/10", "cagr": 17.0, "mdd": -31.5, "trades_y": 41, "win": 28.8, "avg": 3.95,
               "old": {"cagr": 3.5, "mdd": -28.3, "trades_y": 137, "win": 44.4, "avg": 0.33}}
    byid = {s["id"]: s for s in data.get("stocks", [])}
    bd, _ = A.bars_of(A.BENCH_SID); last = bd[-1] if bd else ""
    if not last: return T
    ev = []
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
        try: _, stp, _ = A.stock_levels(dd, oo, op, a, byid.get(q["id"]))
        except Exception: stp = op * 0.92
        sh = int(NOTIONAL / op)
        T["pos"].append({"id": q["id"], "name": q["name"], "sector": q.get("sector"), "fill": d[idx], "entry": op, "sh": sh,
                         "stop0": round(float(stp), 2), "stop": round(float(stp), 2), "hi": op, "p": q["p"], "sig_d": q["sig_d"], "seen": d[idx]})
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
                try: pr = V.prob(s["id"], s, d, o)
                except Exception: pr = None
                if pr is not None: sc.append((pr, s))
            sc.sort(key=lambda x: -x[0])
            held = {p["id"] for p in T["pos"]} | {q["id"] for q in T["pend"]}
            secn = {}
            for p in T["pos"] + T["pend"]: secn[p.get("sector")] = secn.get(p.get("sector"), 0) + 1
            free = SLOTS - len(T["pos"]) - len(T["pend"]); new = []
            for pr, s in sc:
                if free <= 0 or pr < PMIN: break
                if s["id"] in held or secn.get(s.get("sector"), 0) >= MAX_SECTOR: continue
                d, o = A.bars_of(s["id"])
                q = {"id": s["id"], "name": s.get("name"), "sector": s.get("sector"), "sig_d": last, "sig_px": o[-1][3], "p": round(pr, 4)}
                T["pend"].append(q); new.append(q); held.add(s["id"]); secn[s.get("sector")] = secn.get(s.get("sector"), 0) + 1; free -= 1
            T["top"] = [{"id": s["id"], "name": s.get("name"), "p": round(pr, 4)} for pr, s in sc[:15]]
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
    json.dump(T, open(FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for e in ev: log("trader:" + e)
    return T
