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

def fetch_weekly_finmind(sid, start="2014-01-01"):
    """r884:Yahoo 的 00631L 週線有分割/錯值(2015-01 出現 19→0.87),改抓 FinMind 日線自己併成週線(取每週最後一個交易日收盤)。"""
    try:
        tok = os.environ.get("FINMIND_TOKEN", "")
        r = requests.get("https://api.finmindtrade.com/api/v4/data",
                         params={"dataset": "TaiwanStockPrice", "data_id": sid, "start_date": start, "token": tok}, timeout=60)
        rows = (r.json() or {}).get("data") or []
        if len(rows) < 200: log(f"  FinMind {sid} 只有 {len(rows)} 筆"); return None
        # 分割還原:00631L 2024 年有 1:? 分割;用「前後日跳動 >40%」偵測並把之前的價格按比例折算
        rows.sort(key=lambda x: x["date"])
        px = [(x["date"], float(x["close"])) for x in rows if x.get("close")]
        adj = []
        factor = 1.0
        # 由後往前:遇到跳空(前一日/當日 比例 >1.4 或 <0.7)就把更早的價格乘上比例
        out = [None] * len(px)
        for i in range(len(px) - 1, -1, -1):
            d, c = px[i]
            if i < len(px) - 1:
                nxt = px[i + 1][1]
                ratio = nxt / c if c else 1
                if ratio < 0.7 or ratio > 1.4:
                    factor *= ratio
            out[i] = (d, c * factor)
        # 併週線:ISO 週,取該週最後一筆
        wk = {}
        for d, c in out:
            y, w, _ = dt.date.fromisoformat(d).isocalendar()
            wk[(y, w)] = (d, c)
        res = [wk[k] for k in sorted(wk)]
        return res if len(res) >= 60 else None
    except Exception as e:
        log(f"  FinMind {sid} 失敗:{e}"); return None


def _wk_map(wk): return {d: c for d, c in wk}

def analyze_lev(sym, name, wk, base_wk, base_res):
    """r886:槓桿 ETF 專屬(依 2014~2026 真實回測重寫):
       ①自身週乖離(沿用 analyze)②加權跌進「偏低檔(分位≤25)」vs「極低檔(≤10)」→正2 8/13/26 週
       ③正2 自身低檔(反指標)④年線上下 ⑤波動情境 ⑥「現在同類情境」⑦年度報酬與最大回檔 ⑧綜合判定"""
    r = analyze(sym, name, "TW", wk, None)
    if not r: return None
    C = [c for _, c in wk]; D = [d for d, _ in wk]; n = len(C)
    BC = [c for _, c in base_wk]; BD = [d for d, _ in base_wk]; bn = len(BC)
    def isow(d):
        y, w, _ = dt.date.fromisoformat(d).isocalendar(); return y * 100 + w
    lw = {isow(d): i for i, d in enumerate(D)}
    near = lambda d: lw.get(isow(d))
    def fwd_at(d, k):
        i = near(d)
        if i is None or i + k >= n: return None
        return (C[i + k] / C[i] - 1) * 100
    def stat(xs):
        xs = [x for x in xs if x is not None]
        return {"n": len(xs), "win": round(100 * sum(1 for x in xs if x > 0) / len(xs)), "med": round(st.median(xs), 1),
                "avg": round(sum(xs) / len(xs), 1), "worst": round(min(xs), 1), "best": round(max(xs), 1)} if len(xs) >= 3 else None
    # 加權 20 週乖離、分位
    b = [None] * bn; s_ = 0.0
    for i in range(bn):
        s_ += BC[i]
        if i >= 20: s_ -= BC[i - 20]
        if i >= 19: b[i] = (BC[i] / (s_ / 20) - 1) * 100
    hist = [x for x in b if x is not None]; srt = sorted(hist)
    p10 = srt[int(len(hist) * .10)]; p25 = srt[int(len(hist) * .25)]; p90 = srt[int(len(hist) * .90)]
    def episodes(thr):
        eps = []
        for i in range(20, bn):
            if b[i] is None or b[i - 1] is None: continue
            if b[i] <= thr and b[i - 1] > thr:
                e = {"d": BD[i], "bias": round(b[i], 1), "fwd": {}}
                for k in FWD:
                    v = fwd_at(BD[i], k)
                    if v is not None: e["fwd"][str(k)] = round(v, 1)
                eps.append(e)
        return eps
    e10, e25 = episodes(p10), episodes(p25)
    bt = lambda eps: {str(k): stat([e["fwd"].get(str(k)) for e in eps]) for k in FWD}
    r["twii_low10"] = {"n": len(e10), "bt": bt(e10), "eps": e10[-4:]}
    r["twii_low25"] = {"n": len(e25), "bt": bt(e25), "eps": e25[-4:]}
    # 任意時點基準(正2)
    r["base"] = {str(k): stat([(C[i + k] / C[i] - 1) * 100 for i in range(0, n - k)]) for k in FWD}
    # 年線上下
    above = {str(k): [] for k in (8, 13, 26)}; below = {str(k): [] for k in (8, 13, 26)}
    for j in range(52, bn):
        i = near(BD[j])
        if i is None: continue
        ma = sum(BC[j - 51:j + 1]) / 52
        tg = above if BC[j] >= ma else below
        for k in (8, 13, 26):
            if i + k < n: tg[str(k)].append((C[i + k] / C[i] - 1) * 100)
    r["ma52"] = {"above": {k: stat(v) for k, v in above.items()}, "below": {k: stat(v) for k, v in below.items()}}
    ma52_now = sum(BC[bn - 52:]) / 52
    r["twii_above_ma52"] = BC[-1] >= ma52_now; r["twii_ma52"] = round(ma52_now, 0)
    # 波動情境
    rets = [(BC[i] / BC[i - 1] - 1) * 100 for i in range(1, bn)]
    vols = [st.pstdev(rets[i - 20:i]) for i in range(20, len(rets) + 1)]
    vp_now = pct_rank(vols, vols[-1]) if vols else None
    r["vol_pct"] = vp_now
    hi90, chop, calm = [], [], []
    for t, v in enumerate(vols):
        j = t + 20
        if j >= bn or b[j] is None: continue
        f = fwd_at(BD[j], 8)
        if f is None: continue
        vp = pct_rank(vols, v)
        if vp >= 90: hi90.append(f)
        if vp >= 75 and abs(b[j]) <= 3: chop.append(f)
        if vp <= 50: calm.append(f)
    r["vol_bt"] = {"hi90_8": stat(hi90), "chop_8": stat(chop), "calm_8": stat(calm)}
    # 現在同類情境:加權分位 ±12、波動分位同側(≥75 或 <75)、年線同側 → 正2 之後
    tp = pct_rank(hist, b[-1]); r["twii_pct"] = tp; r["twii_bias"] = round(b[-1], 2)
    like = {str(k): [] for k in (8, 13, 26)}; like_d = []
    for j in range(52, bn):
        t = j - 20
        if t < 0 or t >= len(vols) or b[j] is None: continue
        bp = pct_rank(hist, b[j]); vp = pct_rank(vols, vols[t])
        ma = sum(BC[j - 51:j + 1]) / 52
        if abs(bp - tp) <= 12 and ((vp >= 75) == (vp_now >= 75)) and ((BC[j] >= ma) == r["twii_above_ma52"]):
            like_d.append(BD[j])
            for k in (8, 13, 26):
                f = fwd_at(BD[j], k)
                if f is not None: like[str(k)].append(f)
    recent = sum(1 for d in like_d if (dt.date.fromisoformat(BD[-1]) - dt.date.fromisoformat(d)).days <= 70)
    r["like_now"] = {"n": len(like_d), "recent10w": recent, "bt": {k: stat(v) for k, v in like.items()}}
    # 正2 自身低檔(反指標)
    lb = [None] * n; s2 = 0.0
    for i in range(n):
        s2 += C[i]
        if i >= 20: s2 -= C[i - 20]
        if i >= 19: lb[i] = (C[i] / (s2 / 20) - 1) * 100
    lh = [x for x in lb if x is not None]; lp10 = sorted(lh)[int(len(lh) * .10)]
    own = []
    for i in range(20, n):
        if lb[i] is not None and lb[i - 1] is not None and lb[i] <= lp10 and lb[i - 1] > lp10:
            own.append({str(k): ((C[i + k] / C[i] - 1) * 100 if i + k < n else None) for k in FWD})
    r["own_low"] = {"n": len(own), "bt": {str(k): stat([o[str(k)] for o in own]) for k in FWD}}
    sp = r["ma"]["20"]["pct"]
    # 年度報酬 + 最大回檔
    yr, ty = {}, {}
    for i, d in enumerate(D): yr.setdefault(d[:4], {"s": C[i]})["e"] = C[i]
    for i, d in enumerate(BD): ty.setdefault(d[:4], {"s": BC[i]})["e"] = BC[i]
    r["yearly"] = [{"y": y, "lev": round((v["e"] / v["s"] - 1) * 100), "twii": (round((ty[y]["e"] / ty[y]["s"] - 1) * 100) if y in ty else None)} for y, v in sorted(yr.items())]
    peak = 0; mdd = 0; dds = []
    for i in range(n):
        peak = max(peak, C[i]); dd = (C[i] / peak - 1) * 100; mdd = min(mdd, dd)
        if i % 26 == 25: dds.append(round(mdd)); mdd = 0
    r["dd_half"] = dds[-12:]
    r["total"] = {"lev": round((C[-1] / C[0] - 1) * 100), "twii": round((BC[-1] / BC[max(0, near(BD[0]) or 0)] - 1) * 100) if bn else None, "from": D[0]}
    # ⑧ 綜合判定(依回測):加權分位 ≤25 且 >10:+2(甜蜜點);≤10:+1(短線無優勢,只適合半年以上);
    #    加權 ≥90:−1;正2 自身 ≤10:−1(反指標);正2 自身 ≥90:−1;波動分位 ≥90:+1(急跌後反彈段);年線不計分(12 年多頭下年線下反而更好,但不敢當規則)
    score = 0; why = []
    if tp is not None:
        if 10 < tp <= 25: score += 2; why.append(f"加權乖離分位 {tp}(偏低檔=甜蜜點,26 週歷史勝率 77%)")
        elif tp <= 10: score += 1; why.append(f"加權乖離分位 {tp}(極低檔:短線無優勢、最差 −25%,只適合抱半年以上)")
        elif tp >= 90: score -= 1; why.append(f"加權乖離分位 {tp}(過熱)")
        else: why.append(f"加權乖離分位 {tp}(不便宜,持有不加碼)")
    if sp is not None:
        if sp <= 10: score -= 1; why.append(f"正2 自身乖離分位 {sp}(自身低檔是反指標:8 週勝率 45%)")
        elif sp >= 90: score -= 1; why.append(f"正2 自身乖離分位 {sp}(過熱)")
    if vp_now is not None and vp_now >= 90: score += 1; why.append(f"波動分位 {vp_now}(高波動段歷史 8 週 75% 勝、中位 +14.5%)")
    why.append("加權在年線" + ("上" if r["twii_above_ma52"] else "下") + "(不計分:12 年皆為多頭,年線下反而 V 轉;若遇長空頭則相反)")
    verdict = "加碼區・分批" if score >= 2 else "可小量" if score == 1 else "持有不加碼" if score == 0 else "減碼/不追"
    r["score"] = score; r["verdict"] = verdict; r["why"] = why
    r["p10"] = round(p10, 1); r["p25"] = round(p25, 1); r["p90"] = round(p90, 1)
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
        wk = fetch_weekly_finmind(sym.replace(".TW", ""))     # r884:正2 走 FinMind(Yahoo 這檔資料壞)
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
