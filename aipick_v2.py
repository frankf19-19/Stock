#!/usr/bin/env python3
"""AI Pick v2(r935):15 年資料訓練的選股模型 + 過熱環境過濾(台股)
模型與特徵定義和研究引擎(v2/engine.py)完全一致;權重在 aipick_v2_model.json(回測:12 年 +0.98%/檔、最近 52 週 +2.20%,現行 +0.74% / +1.36%)。
用法(由 aipick.py 呼叫):
    V2 = V2Scorer(bars_of, chip_of, data)      # 建一次(會先算全市場 60 日中位報酬與月線寬度)
    V2.ok          → 模型是否可用
    V2.breadth20   → 全市場站上月線家數比例;> 0.70 視為過熱,本週不選
    V2.prob(sid, s, d, o)  → 這檔「未來 10 日贏過大盤」的機率(0~1),None = 資料不足
"""
import json, math, os, gzip, glob, statistics as st

MODEL = "aipick_v2_model.json"


def _ma(x, w, i):
    seg = x[i - w + 1:i + 1]
    return sum(seg) / w if len(seg) == w else None


def _cut(d, o, cutoff):
    """只留日期 < cutoff 的 K(回測週不偷看未來;cutoff=None 不裁)"""
    if not cutoff or not d or d[-1] < cutoff: return d, o
    n = sum(1 for x in d if x < cutoff)
    return d[:n], o[:n]


class V2Scorer:
    def __init__(self, bars_of, chip_of, data, mkt="TW", cutoff=None):
        # r955:參數化市場——美股用 aipick_v2_model_us.json(美股 2012 起重新訓練;無法人/本益比/殖利率,那幾個特徵權重為 0)
        self.ok = False; self.mkt = mkt; self.cutoff = cutoff
        try:
            self.m = json.load(open(MODEL if mkt == "TW" else "aipick_v2_model_us.json", encoding="utf-8"))
        except Exception:
            self.m = None; return
        self.bars_of, self.chip_of = bars_of, chip_of
        self.pe_hist = {}
        for p in (glob.glob("archive/per/tw/*/*.json.gz") if mkt == "TW" else []):                 # 本益比一年歷史(算本益比位置)
            if not any(y in p for y in ("2025", "2026")): continue
            try:
                with gzip.open(p, "rt", encoding="utf-8") as f: j = json.load(f)
                for sid, e in j.items():
                    h = self.pe_hist.setdefault(sid, {})
                    for d, v in zip(e.get("d") or [], e.get("pe") or []):
                        if v is not None: h[d] = v
            except Exception: pass
        r60, above, n = [], 0, 0
        for s in data.get("stocks", []):
            if s.get("market") != mkt or s.get("etf"): continue
            d, o = _cut(*bars_of(s["id"]), cutoff)
            if len(o) < 61: continue
            c = [b[3] for b in o]
            if not c[-1] or not c[-61]: continue
            r60.append(c[-1] / c[-61] - 1)
            m20 = _ma(c, 20, len(c) - 1)
            if m20: n += 1; above += 1 if c[-1] > m20 else 0
        self.mkt_r60 = st.median(r60) if r60 else 0.0
        self.breadth20 = above / n if n else None
        reg = (self.m or {}).get("regime") or {}
        self.overheated = (reg.get("rule") != "none") and self.breadth20 is not None and self.breadth20 > 0.70   # 美股模型 regime=none:回測顯示過熱過濾沒有幫助
        self.ok = True

    def feats(self, sid, s, d, o):
        n = len(o); i = n - 1
        if n < 251: return None
        c = [b[3] for b in o]; h = [b[1] for b in o]; l = [b[2] for b in o]; v = [b[4] or 0 for b in o]
        if not c[i] or not c[i - 60] or not c[i - 250]: return None
        ma5, ma20, ma60 = _ma(c, 5, i), _ma(c, 20, i), _ma(c, 60, i); ma20p = _ma(c, 20, i - 10); ma60p = _ma(c, 60, i - 20)
        if not (ma5 and ma20 and ma60 and ma20p and ma60p): return None
        tr = [max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])) for k in range(i - 13, i + 1)]
        atr = sum(tr) / 14; v5 = _ma(v, 5, i); v20 = _ma(v, 20, i)
        if not v20 or v20 <= 0 or c[i] * v20 < (20000 if self.mkt == "TW" else 2e7): return None
        ch = self.chip_of(sid) or {}
        cd, cf, ct = ch.get("d") or [], ch.get("f") or [], ch.get("t") or []
        last20 = [k for k in range(len(cd)) if cd[k] >= d[i - 19] and cd[k] <= d[i]]
        last5 = [k for k in range(len(cd)) if cd[k] >= d[i - 4] and cd[k] <= d[i]]
        f20 = sum((cf[k] or 0) + (ct[k] or 0) for k in last20); f5 = sum(cf[k] or 0 for k in last5); t5 = sum(ct[k] or 0 for k in last5)
        pe = s.get("pe"); hist = self.pe_hist.get(sid) or {}
        pw = [v2 for dd, v2 in hist.items() if dd >= d[i - 250] and dd <= d[i]]
        pe_pos = (sum(1 for x in pw if x <= pe) / len(pw)) if isinstance(pe, (int, float)) and pe > 0 and len(pw) >= 60 else 0.5
        hi20 = max(h[i - 19:i + 1]); d20 = 19 - max(range(20), key=lambda k: h[i - 19 + k])
        dy = s.get("dv") if isinstance(s.get("dv"), (int, float)) else 0
        row = [float(ma5 > ma20), float(ma20 > ma60), float(c[i] > ma20), ma20 / ma20p - 1,
               c[i] / c[i - 5] - 1, c[i] / c[i - 20] - 1, c[i] / c[i - 60] - 1, c[i] / hi20 - 1,
               math.log(max(v5, 1) / max(v20, 1)), c[i] / ma20 - 1, pe_pos,
               f20 / max(v20 * 20, 1), f5 / max(v5 * 5, 1), t5 / max(v5 * 5, 1),
               atr / c[i], math.log(c[i] * v20 + 1), (c[i] / c[i - 60] - 1) - self.mkt_r60,
               dy / 100, ma60 / ma60p - 1, d20 / 20]
        if any(not math.isfinite(x) for x in row): return None
        return row

    def prob(self, sid, s, d, o):
        if not self.ok: return None
        d, o = _cut(d, o, self.cutoff)
        x = self.feats(sid, s, d, o)
        if x is None: return None
        m = self.m; z = sum((x[k] - m["mu"][k]) / m["sd"][k] * m["w"][k] for k in range(len(x))) + m["b"]
        return 1 / (1 + math.exp(-max(-30, min(30, z))))
