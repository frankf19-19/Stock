"""60 分 K 型態掃描:長長尖尖(空間震倉)/ 扁扁寬寬(時間換籌碼)→ hourly_scan.json
====================================================================================
兩型是同一個結構(整理 → 突破 → 主升),差在洗盤方式:
  長長尖尖:整理區間裡出現「長下影線」——快速下殺又拉回,用空間嚇出散戶
  扁扁寬寬:長時間小 K 棒在窄區間來回——用時間磨掉散戶耐心
兩型可同時成立(扁平整理裡出現長下影線),是最強組合,單獨標。

兩段式(全市場 1,900 檔不可能每檔打 Fugle):
  第一段・日 K 預篩(零成本):近 15 日高低幅 ≤ 10%、現價在區間內且離區間底 ≤ 3%、20 日均量 ≥ 500 張。
  第二段・對候選抓 60 分 K(Fugle 走 Cloudflare Worker /fgl 代理,共用站上的 key;近 30 日一次回傳)。
    間隔 1.1 秒 → 每分鐘 ≤ 55 次,符合免費方案速率;300 檔約 6 分鐘。

判定(每檔的門檻都相對於它自己的小時 ATR):
  整理段 = 從最後一根往回走,rolling 高低幅 ≤ RANGE_MAX 的最長連續段(≥ MIN_BARS 根)
  扁扁寬寬:段長 ≥ FLAT_BARS,實體中位數 ≤ 0.5%,全幅中位數 ≤ 1.2%,整理均量 ≤ 整理前 20 根均量 × 0.7
  長長尖尖:段內任一根:下影線 ≥ 2×實體 且 ≥ 1.2×ATR,收盤在該根上半,最低 ≤ 段低 × 1.01,量 ≥ 段均量 × 1.5
  狀態:洗盤中(仍在段內)/ 已突破(收 > 段高 × 1.005 且量 ≥ 段均量 × 2)/ 回測成功(突破後 ≥3 根低點守住段高)/ 失敗(跌破影線低點)
輸出:hourly_scan.json {"u","d","cand":候選數,"scanned":實際抓到數,"items":[{...}]}
"""
import json, os, sys, time, datetime as dt, statistics as st
import requests

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
OUT = "hourly_scan.json"
WORKER = "https://muddy-cake-cb69.frankccc199.workers.dev"
FUGLE = "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{sid}?timeframe=60&fields=open,high,low,close,volume&sort=asc"
SLEEP = 1.1                  # 每分鐘 ≤ 55 次
MAX_CAND = 400               # 候選上限(超過就依量排序取前 400)
# 第一段
D_RANGE_MAX, D_NEAR_LOW, D_MIN_LOTS = 0.10, 0.03, 500
# 第二段
RANGE_MAX, MIN_BARS, FLAT_BARS = 0.08, 15, 25
FLAT_BODY, FLAT_RNG, FLAT_VOL = 0.005, 0.012, 0.7
SH_BODY_X, SH_ATR_X, SH_VOL_X = 2.0, 1.2, 1.5
BRK_X, BRK_VOL_X, RETEST_BARS = 1.005, 2.0, 3


def log(*a): print(*a, flush=True)


def shard_key(sid):
    t = str(sid); return t[:3] if t[:2] == "00" else t[:2]

_SH = {}
def bars_of(sid):
    k = shard_key(sid)
    if k not in _SH:
        try: _SH[k] = json.load(open(f"k/tw{k}.json", encoding="utf-8"))
        except Exception: _SH[k] = {}
    e = _SH[k].get(sid) or {}
    d, o = e.get("d") or [], e.get("o") or []
    n = min(len(d), len(o)); return d[:n], o[:n]


def stage1(stocks):
    """日 K 預篩 → [(sid, name, 區間幅, 距底%, 20日均量張)]"""
    out = []
    for s in stocks:
        if s.get("market") != "TW" or s.get("etf"): continue
        d, o = bars_of(s["id"])
        if len(o) < 40: continue
        w = o[-15:]
        try:
            hi = max(b[1] for b in w); lo = min(b[2] for b in w); c = o[-1][3]
            vol20 = sum((b[4] or 0) for b in o[-20:]) / 20          # k 分片的量已是「張」
        except Exception:
            continue
        if not (lo > 0 and c > 0): continue
        rng = hi / lo - 1
        if rng > D_RANGE_MAX or vol20 < D_MIN_LOTS: continue
        if not (lo <= c <= hi * 1.02): continue
        near = c / lo - 1
        if near > D_NEAR_LOW and c < hi * 0.995: continue          # 在區間中段、又沒接近突破 → 先不看
        out.append((s["id"], s.get("name") or s["id"], round(rng * 100, 2), round(near * 100, 2), int(vol20)))
    out.sort(key=lambda x: -x[4])
    return out[:MAX_CAND]


def fetch_h60(sid):
    try:
        r = requests.get(f"{WORKER}/fgl", params={"u": FUGLE.format(sid=sid)}, timeout=20)
        if not r.ok: return None
        j = r.json()
        rows = j.get("data") if isinstance(j, dict) else None
        if not rows: return None
        bars = []
        for x in rows:
            try: bars.append([str(x.get("date")), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), float(x.get("volume") or 0)])
            except Exception: pass
        bars.sort(key=lambda b: b[0])
        return bars if len(bars) >= MIN_BARS else None
    except Exception:
        return None


def classify(bars):
    """bars = [[date,o,h,l,c,v],...] 升冪。回傳 dict 或 None(沒有整理段)。"""
    n = len(bars)
    C = [b[4] for b in bars]
    # 小時 ATR(20)
    tr = [max(bars[i][2] - bars[i][3], abs(bars[i][2] - C[i - 1]), abs(bars[i][3] - C[i - 1])) for i in range(1, n)]
    atr = sum(tr[-20:]) / min(20, len(tr)) if tr else 0
    # 整理段:從最後一根往回走,只要包含後 rolling 高低幅 ≤ RANGE_MAX 就繼續;遇到突破棒(最後幾根)先跳過再找
    def run_from(end):
        hi = lo = None; start = end
        for i in range(end, -1, -1):
            h, l = bars[i][2], bars[i][3]
            nh = h if hi is None else max(hi, h); nl = l if lo is None else min(lo, l)
            if nl > 0 and nh / nl - 1 > RANGE_MAX: break
            hi, lo, start = nh, nl, i
        return start, end, hi, lo
    # 8% 是上限不是整理本身的寬度:1.2% 的扁平段後面接一根 +3% 的突破棒,rolling 高低幅仍 ≤ 8%,
    # 突破棒會被「吸進」整理段。所以先試把最後 0~4 根當突破棒排除,只要排除後的下一根真的是
    # 「收 > 段高×1.005 且量 ≥ 段均量×2」就採用那個切法;都不是才用最長的那個。
    best = None; fallback = None
    for skip in range(0, 5):
        end = n - 1 - skip
        if end < MIN_BARS: break
        s0, e0, hi, lo = run_from(end)
        if not hi or e0 - s0 + 1 < MIN_BARS: continue
        if fallback is None: fallback = (s0, e0, hi, lo, skip)
        if skip > 0:
            vseg0 = sum(b[5] for b in bars[s0:e0 + 1]) / (e0 - s0 + 1)
            b0 = bars[e0 + 1]
            if b0[4] > hi * BRK_X and b0[5] >= vseg0 * BRK_VOL_X:
                best = (s0, e0, hi, lo, skip); break
    best = best or fallback
    if not best: return None
    s0, e0, hi, lo, skip = best
    seg = bars[s0:e0 + 1]; L = len(seg)
    med = lambda a: st.median(a) if a else 0
    body = med([abs(b[4] - b[1]) / b[4] for b in seg if b[4]])
    rngm = med([(b[2] - b[3]) / b[4] for b in seg if b[4]])
    vseg = sum(b[5] for b in seg) / L
    pre = bars[max(0, s0 - 20):s0]
    vpre = sum(b[5] for b in pre) / len(pre) if pre else vseg
    vratio = vseg / vpre if vpre else 1.0
    flat = L >= FLAT_BARS and body <= FLAT_BODY and rngm <= FLAT_RNG and vratio <= FLAT_VOL
    # 長下影線
    shadow = None
    for i in range(s0, e0 + 1):
        o, h, l, c, v = bars[i][1:6]
        bd = abs(c - o); low_sh = min(o, c) - l
        if atr <= 0 or l <= 0: continue
        if low_sh >= SH_BODY_X * max(bd, 1e-9) and low_sh >= SH_ATR_X * atr and c >= l + (h - l) * 0.5 \
           and l <= lo * 1.01 and v >= vseg * SH_VOL_X:
            cand = {"at": bars[i][0], "depth": round(low_sh / c * 100, 2), "low": l, "vol_x": round(v / vseg, 2) if vseg else None}
            if not shadow or cand["depth"] > shadow["depth"]: shadow = cand
    types = ([ "flat"] if flat else []) + (["shadow"] if shadow else [])
    if not types: return None
    # 狀態
    last = bars[-1]; state = "洗盤中"; brk = None
    after = bars[e0 + 1:]
    if after:
        b0 = after[0]
        if b0[4] > hi * BRK_X and b0[5] >= vseg * BRK_VOL_X: brk = b0[0]
        if brk:
            state = "已突破"
            if len(after) >= RETEST_BARS + 1 and all(x[3] >= hi for x in after[1:1 + RETEST_BARS]): state = "回測成功"
            if last[4] < hi: state = "突破失敗"
    if shadow and last[4] < shadow["low"] * 0.99: state = "洗盤失敗"
    return {"type": types, "state": state, "bars": L, "range_pct": round((hi / lo - 1) * 100, 2), "hi": hi, "lo": lo,
            "body_med": round(body * 100, 2), "rng_med": round(rngm * 100, 2), "vol_ratio": round(vratio, 2),
            "shadow": shadow, "brk_at": brk, "last": last[4], "last_at": last[0], "atr_pct": round(atr / last[4] * 100, 2) if last[4] else None}


def main():
    try: data = json.load(open("data.json", encoding="utf-8"))
    except Exception: log("沒有 data.json"); return
    stocks = data.get("stocks") or []
    cand = stage1(stocks)
    log(f"第一段:日 K 預篩 {len(cand)} 檔候選(區間 ≤{D_RANGE_MAX*100:.0f}%、近底 ≤{D_NEAR_LOW*100:.0f}%、均量 ≥{D_MIN_LOTS} 張)")
    prev = {}
    try: prev = {x["id"]: x for x in json.load(open(OUT, encoding="utf-8")).get("items", [])}
    except Exception: pass
    items, scanned, fails = [], 0, 0
    t0 = time.time()
    for sid, name, d_rng, d_near, vol in cand:
        bars = fetch_h60(sid); time.sleep(SLEEP)
        if not bars: fails += 1; continue
        scanned += 1
        r = classify(bars)
        if not r: continue
        r.update({"id": sid, "name": name, "d_range": d_rng, "d_near_low": d_near, "vol20": vol,
                  "first_seen": (prev.get(sid) or {}).get("first_seen") or NOW.strftime("%Y-%m-%d %H:%M")})
        items.append(r)
        if time.time() - t0 > 20 * 60: log("  超過 20 分鐘,本輪先寫出"); break
    order = {"回測成功": 0, "已突破": 1, "洗盤中": 2, "突破失敗": 3, "洗盤失敗": 4}
    items.sort(key=lambda x: (order.get(x["state"], 9), -len(x["type"]), -x["bars"]))
    res = {"u": NOW.strftime("%Y-%m-%d %H:%M"), "d": NOW.strftime("%Y-%m-%d"), "cand": len(cand), "scanned": scanned, "fails": fails,
           "params": {"range_max": RANGE_MAX, "flat_bars": FLAT_BARS, "shadow_atr_x": SH_ATR_X, "brk_vol_x": BRK_VOL_X}, "items": items}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    both = sum(1 for x in items if len(x["type"]) == 2)
    log(f"✅ {OUT}:掃 {scanned}/{len(cand)} 檔(失敗 {fails}),命中 {len(items)} 檔——"
        f"扁扁寬寬 {sum(1 for x in items if 'flat' in x['type'])}、長長尖尖 {sum(1 for x in items if 'shadow' in x['type'])}、兩型同時 {both};"
        f"已突破/回測成功 {sum(1 for x in items if x['state'] in ('已突破','回測成功'))}")


if __name__ == "__main__":
    main()
