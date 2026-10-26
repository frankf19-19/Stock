#!/usr/bin/env python3
"""r1180:產業強弱 → sector_str.json(前端「🔎 本股條件」用)
每個產業 = 同產業流動股(20 日均成交值 ≥2,000 萬)近 20 個交易日報酬的平均;大盤 = 全部流動股平均。
回測(plan_bt_study.py filt9b):高波動跌 25% 止跌時,產業 20 日弱於大盤 5% 以上 → 每筆少 −2.4% / −6.6%(兩期)。"""
import json, glob, datetime as dt, collections

def main():
    D = json.load(open("data.json", encoding="utf-8"))
    sec = {s["id"]: s.get("sector") or "" for s in D["stocks"] if s.get("market") == "TW" and not s.get("etf")}
    rets = collections.defaultdict(list); allr = []; asof = None
    for p in glob.glob("k/tw*.json"):
        try: j = json.load(open(p, encoding="utf-8"))
        except Exception: continue
        for sid, e in j.items():
            if sid not in sec or not isinstance(e, dict): continue
            o = e.get("o") or []; d = e.get("d") or []
            if len(o) < 21 or len(d) != len(o): continue
            try:
                c, c20 = float(o[-1][3]), float(o[-21][3])
                liq = sum(float(x[3]) * float(x[4] or 0) for x in o[-20:]) / 20
            except Exception: continue
            if c <= 0 or c20 <= 0 or liq < 2e4: continue
            r = c / c20 - 1
            rets[sec[sid]].append(r); allr.append(r); asof = max(asof or d[-1], d[-1])
    if len(allr) < 200:
        print(f"sector_strength:流動股只有 {len(allr)} 檔,疑似資料異常,不覆寫"); return
    mk = sum(allr) / len(allr)
    out = {"u": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), "asof": asof, "mkt": round(mk, 4),
           "s": {k: {"r20": round(sum(v) / len(v), 4), "n": len(v)} for k, v in rets.items() if k and len(v) >= 5}}
    json.dump(out, open("sector_str.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    weak = sorted(((v["r20"] - mk, k) for k, v in out["s"].items()))[:3]
    print(f"sector_strength:{len(out['s'])} 個產業、大盤 20 日 {mk*100:+.1f}%;最弱 " + "、".join(f"{k} {x*100:+.1f}%" for x, k in weak))

if __name__ == "__main__":
    main()
