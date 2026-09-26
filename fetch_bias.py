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
    res["low_eps_all"] = eps                                # r883:給正2對齊用(不輸出到前端卡片)
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


# ═══ r883:台股正2(00631L)進場時機 ═══
LEV = [("00631L.TW", "元大台灣50正2", "^TWII")]

def _wk_map(wk): return {d: c for d, c in wk}

def analyze_lev(sym, name, wk, base_wk, base_res):
    """槓桿 ETF 專屬:①自身週乖離(沿用 analyze)②加權低檔進場→正2 8/13/26 週結果 ③年線上下 ④波動衰耗
    ⑤綜合判定。回傳 dict(附在 bias.json 的 lev)。"""
    r = analyze(sym, name, "TW", wk, None)
    if not r: return None
    C = [c for _, c in wk]; D = [d for d, _ in wk]; n = len(C)
    BC = [c for _, c in base_wk]; BD = [d for d, _ in base_wk]; bn = len(BC)
    idx_of = {d: i for i, d in enumerate(D)}
    def fwd_at(d, k):
        i = idx_of.get(d)
        if i is None:
            # 找最接近(同週)的日期
            cand = [j for j, dd in enumerate(D) if abs((dt.date.fromisoformat(dd) - dt.date.fromisoformat(d)).days) <= 4]
            if not cand: return None
            i = cand[0]
        if i + k >= n: return None
        return (C[i + k] / C[i] - 1) * 100
    # ② 加權進入低檔區 → 正2 的後續
    eps = []
    for e in (base_res or {}).get("low_eps_all", []):
        row = {"d": e["d"], "twii_bias": e["bias"], "fwd": {}}
        for k in FWD:
            v = fwd_at(e["d"], k)
            if v is not None: row["fwd"][str(k)] = round(v, 2)
        if row["fwd"]: eps.append(row)
    bt = {}
    for k in FWD:
        xs = [e["fwd"][str(k)] for e in eps if str(k) in e["fwd"]]
        if len(xs) >= 3:
            bt[str(k)] = {"n": len(xs), "win": round(100 * sum(1 for x in xs if x > 0) / len(xs)), "med": round(st.median(xs), 2),
                          "avg": round(sum(xs) / len(xs), 2), "worst": round(min(xs), 2), "best": round(max(xs), 2)}
    r["twii_low_eps"] = eps[-6:]; r["twii_low_bt"] = bt
    # ③ 加權在 52 週均之上 vs 之下,正2 的 8/13 週表現(槓桿要順勢抱)
    bmap = _wk_map(base_wk)
    above = {"8": [], "13": []}; below = {"8": [], "13": []}
    for i in range(52, n):
        d = D[i]
        j = [jj for jj, dd in enumerate(BD) if dd == d]
        if not j or j[0] < 52: continue
        j = j[0]
        ma52 = sum(BC[j - 51:j + 1]) / 52
        tgt = above if BC[j] >= ma52 else below
        for k in (8, 13):
            if i + k < n: tgt[str(k)].append((C[i + k] / C[i] - 1) * 100)
    def stat(xs): return {"n": len(xs), "win": round(100 * sum(1 for x in xs if x > 0) / len(xs)), "med": round(st.median(xs), 2)} if len(xs) >= 5 else None
    r["ma52"] = {"above": {k: stat(v) for k, v in above.items()}, "below": {k: stat(v) for k, v in below.items()}}
    jb = bn - 1; ma52_now = sum(BC[jb - 51:jb + 1]) / 52
    r["twii_above_ma52"] = BC[-1] >= ma52_now; r["twii_ma52"] = round(ma52_now, 2)
    # ④ 波動衰耗:加權 20 週實現波動(週報酬標準差)十年分位;高波動+盤整 = 正2 磨損
    rets = [(BC[i] / BC[i - 1] - 1) * 100 for i in range(1, bn)]
    vols = [st.pstdev(rets[i - 20:i]) for i in range(20, len(rets) + 1)]
    r["vol_pct"] = pct_rank(vols, vols[-1]) if vols else None; r["vol_now"] = round(vols[-1], 2) if vols else None
    # 高波動(≥75 分位)且加權 20 週乖離在 ±3% 內(盤整)時,正2 之後 8 週的中位
    bb = base_res["ma"]["20"] if base_res else None
    chop = []
    if vols:
        # 對齊:vols[t] 對應 BD[t+20]
        for t, v in enumerate(vols):
            j = t + 20
            if j >= bn or j + 8 >= bn: continue
            # 加權 20 週乖離
            ma20 = sum(BC[j - 19:j + 1]) / 20; bias = (BC[j] / ma20 - 1) * 100
            if pct_rank(vols, v) >= 75 and abs(bias) <= 3:
                d = BD[j]; f = fwd_at(d, 8)
                if f is not None: chop.append(f)
    r["chop_bt"] = stat(chop)
    # ⑤ 綜合判定(分數):加權分位 ≤10:+3、≤25:+2;正2 自身分位 ≤25:+1;加權在年線上:+1;波動 ≥75:−1;正2 分位 ≥90:−2、加權 ≥90:−1
    tp = (base_res or {}).get("ma", {}).get("20", {}).get("pct")
    sp = r["ma"]["20"]["pct"]
    score = 0; why = []
    if tp is not None:
        if tp <= 10: score += 3; why.append(f"加權乖離十年分位 {tp}(極低)")
        elif tp <= 25: score += 2; why.append(f"加權乖離分位 {tp}(偏低)")
        elif tp >= 90: score -= 1; why.append(f"加權乖離分位 {tp}(過熱)")
    if sp is not None:
        if sp <= 25: score += 1; why.append(f"正2 自身乖離分位 {sp}(便宜)")
        elif sp >= 90: score -= 2; why.append(f"正2 自身乖離分位 {sp}(過熱)")
    if r["twii_above_ma52"]: score += 1; why.append("加權在年線之上(順勢)")
    else: why.append("加權在年線之下(逆勢,槓桿磨損風險)")
    if r["vol_pct"] is not None and r["vol_pct"] >= 75: score -= 1; why.append(f"波動分位 {r['vol_pct']}(高,盤整衰耗)")
    verdict = "積極分批" if score >= 3 else "分批進場" if score >= 2 else "小量試單" if score >= 1 else "觀望" if score >= 0 else "減碼/不追"
    r["score"] = score; r["verdict"] = verdict; r["why"] = why
    r["base_sym"] = base_res["sym"] if base_res else None
    return r


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
    # r883:正2
    lev_out = []
    base_by = {x["sym"]: x for x in out}
    wk_cache = {}
    for sym, name, base in LEV:
        wk = fetch_weekly(sym)
        if not wk: log(f"  {name}:抓不到"); continue
        bwk = wk_cache.get(base) or fetch_weekly(base)
        if not bwk: continue
        wk_cache[base] = bwk
        try:
            r = analyze_lev(sym, name, wk, bwk, base_by.get(base))
            if r:
                r.pop("low_eps_all", None); lev_out.append(r)
                log(f"  {name}:{r['last']}・判定 {r['verdict']}(分數 {r['score']})・{';'.join(r['why'])}")
        except Exception as e:
            log(f"  {name} 分析失敗:{e}")
    for x in out: x.pop("low_eps_all", None)
    res = {"u": NOW.strftime("%Y-%m-%d %H:%M"), "main_ma": MAIN, "idx": out, "lev": lev_out}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"✅ {OUT}:{len(out)} 個指數")


if __name__ == "__main__":
    main()
