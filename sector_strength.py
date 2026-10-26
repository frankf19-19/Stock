#!/usr/bin/env python3
"""r1180:產業強弱 → sector_str.json(前端「🔎 本股條件」用)
每個產業 = 同產業流動股(20 日均成交值 ≥2,000 萬)近 20 個交易日報酬的平均;大盤 = 全部流動股平均。
回測(plan_bt_study.py filt9b):高波動跌 25% 止跌時,產業 20 日弱於大盤 5% 以上 → 每筆少 −2.4% / −6.6%(兩期)。
r1182:另算「市場寬度」a60 = 流動股收盤站上自己季線(60 日均)的比例(plan_bt_study.py brd2:跌深類買法只在 <35% 時有效)。"""
import json, glob, datetime as dt, collections

def main():
    D = json.load(open("data.json", encoding="utf-8"))
    sec = {s["id"]: s.get("sector") or "" for s in D["stocks"] if s.get("market") == "TW" and not s.get("etf")}
    rets = collections.defaultdict(list); allr = []; asof = None
    bd = collections.defaultdict(lambda: [0, 0])   # date -> [站上季線, 流動股數]
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
            try:
                C = [float(x[3]) for x in o]; V = [float(x[4] or 0) for x in o]
                for k in range(max(60, len(o) - 130), len(o)):
                    if sum(C[j] * V[j] for j in range(k - 19, k + 1)) / 20 < 2e4: continue
                    bd[d[k]][1] += 1; bd[d[k]][0] += C[k] > sum(C[k - 59:k + 1]) / 60
            except Exception: pass
            if c <= 0 or c20 <= 0 or liq < 2e4: continue
            r = c / c20 - 1
            rets[sec[sid]].append(r); allr.append(r); asof = max(asof or d[-1], d[-1])
    if len(allr) < 200:
        print(f"sector_strength:流動股只有 {len(allr)} 檔,疑似資料異常,不覆寫"); return
    mk = sum(allr) / len(allr)
    out = {"u": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), "asof": asof, "mkt": round(mk, 4),
           "a60h": [[k, round(v[0] / v[1], 3)] for k, v in sorted(bd.items()) if v[1] >= 200][-60:],
           "s": {k: {"r20": round(sum(v) / len(v), 4), "n": len(v)} for k, v in rets.items() if k and len(v) >= 5}}
    if out["a60h"] and out["a60h"][-1][0] == asof: out["a60"] = out["a60h"][-1][1]
    json.dump(out, open("sector_str.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    weak = sorted(((v["r20"] - mk, k) for k, v in out["s"].items()))[:3]
    print(f"sector_strength:{len(out['s'])} 個產業、大盤 20 日 {mk*100:+.1f}%、站上季線 {out.get('a60', 0)*100:.0f}%;最弱 " + "、".join(f"{k} {x*100:+.1f}%" for x, k in weak))

if __name__ == "__main__":
    main()
