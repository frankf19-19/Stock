"""大盤週乖離・入場時機 → bias.json
=================================
問題:「大盤現在的週乖離,放在它自己十年的歷史裡算低檔嗎?低檔進場歷史上怎麼樣?」
對象:加權指數、櫃買、S&P 500、Nasdaq、道瓊、費城半導體(Yahoo chart 週線,10 年;GitHub IP 可通,美股 K 備援同源)。

乖離 = (週收 − N 週均線)/ N 週均線。看三條:10 週(季)、20 週(半年)、52 週(年);主指標用 20 週。
低檔/高檔不是固定 %——每個指數波動不同,用「它自己十年的乖離分佈」定:
  ≤ 10 分位 = 低檔(歷史上很少這麼便宜),≤ 25 偏低,25~75 中性,≥ 75 偏高,≥ 90 高檔。
回測:每次「從上方進入低檔區」的那一週,之後 4/8/13/26 週的漲幅——勝率與中位數,直接回答「低檔進場好不好」。
狀態機:zone 變化時記 zone_since;notify 用它推「進入低檔」一次。
"""
import json, os, datetime as dt, statistics as st
import requests

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
OUT = "bias.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
INDICES = [("^TWII", "加權指數", "TW"), ("^TWOII", "櫃買指數", "TW"), ("^GSPC", "S&P 500", "US"),
           ("^IXIC", "那斯達克", "US"), ("^DJI", "道瓊", "US"), ("^SOX", "費城半導體", "US")]
MAS = [10, 20, 52]
MAIN = 20
FWD = [4, 8, 13, 26]


def log(*a): print(*a, flush=True)


def fetch_weekly(sym):
    """[(週日期 ISO, 收盤)] 升冪;Yahoo 週線 10 年。"""
    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                         params={"range": "10y", "interval": "1wk", "includeAdjustedClose": "false"}, headers=UA, timeout=40)
        j = r.json()
        r0 = j["chart"]["result"][0]
        ts = r0.get("timestamp") or []
        cl = r0["indicators"]["quote"][0]["close"]
        out = []
        for t, c in zip(ts, cl):
            if c is None: continue
            out.append((dt.datetime.fromtimestamp(t, TZ).date().isoformat(), float(c)))
        return out if len(out) >= 60 else None
    except Exception as e:
        log(f"  {sym} 抓取失敗:{e}"); return None


def pct_rank(xs, v):
    """v 在 xs 裡的百分位(0~100)。"""
    if not xs: return None
    n = sum(1 for x in xs if x <= v)
    return round(100.0 * n / len(xs), 1)


def zone_of(p):
    if p is None: return None
    if p <= 10: return "低檔"
    if p <= 25: return "偏低"
    if p >= 90: return "高檔"
    if p >= 75: return "偏高"
    return "中性"


def analyze(sym, name, mkt, wk, prev):
    C = [c for _, c in wk]; D = [d for d, _ in wk]; n = len(C)
    res = {"sym": sym, "name": name, "mkt": mkt, "last": round(C[-1], 2), "as_of": D[-1], "weeks": n, "ma": {}}
    bias_hist = {}
    for m in MAS:
        if n < m + 10: continue
        b = [None] * n
        s = sum(C[:m])
        for i in range(m - 1, n):
            if i >= m: s += C[i] - C[i - m]
            ma = s / m
            b[i] = (C[i] / ma - 1) * 100
        hist = [x for x in b if x is not None]
        cur = b[-1]
        bias_hist[m] = b
        res["ma"][str(m)] = {"ma": round(C[-1] / (1 + cur / 100), 2), "bias": round(cur, 2), "pct": pct_rank(hist, cur),
                             "p10": round(sorted(hist)[int(len(hist) * 0.10)], 2), "p25": round(sorted(hist)[int(len(hist) * 0.25)], 2),
                             "p75": round(sorted(hist)[int(len(hist) * 0.75)], 2), "p90": round(sorted(hist)[int(len(hist) * 0.90)], 2),
                             "min": round(min(hist), 2), "max": round(max(hist), 2)}
    if str(MAIN) not in res["ma"]: return None
    main = res["ma"][str(MAIN)]
    res["zone"] = zone_of(main["pct"])
    # zone 起始:跟上次比
    pz = (prev or {}).get("zone"); ps = (prev or {}).get("zone_since")
    res["zone_since"] = ps if (pz == res["zone"] and ps) else D[-1]
    res["prev_zone"] = pz
    # ── 回測:從上方進入「低檔」(≤ p10)那一週,之後 k 週報酬 ──
    b = bias_hist[MAIN]; thr = main["p10"]
    eps = []
    for i in range(MAIN, n):
        if b[i] is None or b[i - 1] is None: continue
        if b[i] <= thr and b[i - 1] > thr:
            e = {"d": D[i], "bias": round(b[i], 2), "px": round(C[i], 2), "fwd": {}}
            for k in FWD:
                if i + k < n: e["fwd"][str(k)] = round((C[i + k] / C[i] - 1) * 100, 2)
            eps.append(e)
    bt = {}
    for k in FWD:
        xs = [e["fwd"][str(k)] for e in eps if str(k) in e["fwd"]]
        if len(xs) >= 3:
            bt[str(k)] = {"n": len(xs), "win": round(100 * sum(1 for x in xs if x > 0) / len(xs)), "med": round(st.median(xs), 2),
                          "avg": round(sum(xs) / len(xs), 2), "worst": round(min(xs), 2)}
    res["low_eps"] = eps[-8:]
    res["low_bt"] = bt
    # 對照:任意週之後 k 週的基準
    base = {}
    for k in FWD:
        xs = [(C[i + k] / C[i] - 1) * 100 for i in range(0, n - k)]
        if xs: base[str(k)] = {"win": round(100 * sum(1 for x in xs if x > 0) / len(xs)), "med": round(st.median(xs), 2)}
    res["base"] = base
    # 近 52 週的主乖離序列(前端畫小圖)
    res["spark"] = [round(x, 1) if x is not None else None for x in b[-52:]]
    res["spark_d"] = D[-52:]
    return res


def main():
    prev = {}
    try: prev = {x["sym"]: x for x in json.load(open(OUT, encoding="utf-8")).get("idx", [])}
    except Exception: pass
    out = []
    for sym, name, mkt in INDICES:
        wk = fetch_weekly(sym)
        if not wk:
            if sym in prev: out.append(prev[sym]); log(f"  {name}:抓不到,沿用前值")
            continue
        r = analyze(sym, name, mkt, wk, prev.get(sym))
        if r:
            out.append(r)
            m = r["ma"][str(MAIN)]
            log(f"  {name}:{r['last']}・20週乖離 {m['bias']:+.2f}%(十年分位 {m['pct']})→ {r['zone']}"
                + (f",自 {r['zone_since']}" if r["zone_since"] != r["as_of"] else "(本週進入)"))
    res = {"u": NOW.strftime("%Y-%m-%d %H:%M"), "main_ma": MAIN, "idx": out}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"✅ {OUT}:{len(out)} 個指數")


if __name__ == "__main__":
    main()
