"""🎯 落底燈號(r1126)→ bottom.json(+ bottom_stats.json 每週重算一次)

問題:「跌了這麼多,落底了沒?」——用歷史真的驗證過的訊號回答,大盤(台股、美股三大指數)與每一檔個股都有。

一、燈號(每顆燈都用 2014 年起的真實資料回測過)
  大盤(台股加權):中線超跌(60日乖離≤-10%)、短線急跌(20日乖離≤-6%)、外資賣到極端(近20日累計賣超在近3年最極端10%)、
                  全面殺盤(站上月線的股票≤15%,近10天內)  ＋ 止跌:廣度急升、站回10日線且3天不破底
  大盤(美股 S&P500/那斯達克/費半):20日乖離、60日乖離 ≤ 自己歷史最低5%、全面殺盤、新低家數≥20%  ＋ 同樣兩顆止跌
  個股(台股):20日乖離 ≤ 自己近3年最低5%、60日乖離同、融資20日內減少2成、投信連3天買超  ＋ 止跌:站回10日線且3天不破底
  個股(美股):20日乖離、60日乖離、離120日高點跌幅 ≤ 自己近3年最低5%  ＋ 止跌
二、驗證(bottom_stats.json,每週重算;資料:archive/ 2012 起每檔 K 線、法人、融資,美股 SPY/QQQ/SOXX 與 S&P 500 成分股)
  大盤:在「離一年高點跌 ≥8%」的日子裡比較「亮燈 vs 沒亮」之後 20/60 天漲跌與最多再跌幅度;
       一顆燈要「亮的時候比沒亮好」(3 個月上漲機率高 3 個百分點以上,或之後再跌幅度少 1 個百分點以上)才算通過,沒通過的燈網站不顯示。
  個股:所有流動性足夠(20日均成交值≥2000萬台幣/2000萬美元)的股票日,依「亮了幾盞」分組統計。
三、盤中即時:價格類的燈都換算成「門檻價」(例:跌到 X 元以下會亮),前端用即時價直接判斷;法人/融資類用前一個交易日資料。
"""
import json, os, glob, gzip, sys, time, datetime as dt, hashlib
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
OUT, STATS = "bottom.json", "bottom_stats.json"
AR = "archive"
ETF_US = {"SPY", "QQQ", "SOXX", "SMH", "DIA", "IWM"}
SEMIS = ['NVDA', 'AMD', 'AVGO', 'QCOM', 'TXN', 'INTC', 'MU', 'AMAT', 'LRCX', 'KLAC', 'ADI', 'MCHP', 'NXPI', 'ON', 'MPWR',
         'MRVL', 'TER', 'SWKS', 'QRVO', 'TSM', 'ARM', 'SMCI', 'ENPH', 'FSLR']
MKT_US = {"SPX": ("SPY", "^GSPC", "S&P 500"), "NDX": ("QQQ", "^IXIC", "那斯達克"), "SOX": ("SOXX", "^SOX", "費城半導體")}


def log(*a): print(*a, flush=True)
def ld(p):
    with gzip.open(p) as f:return json.loads(f.read())
def jl(p, d=None):
    try:
        with open(p,encoding='utf-8') as f:return json.load(f)
    except Exception: return d
def r1(x, n=1):
    try:
        x = float(x)
        return None if not np.isfinite(x) else round(x, n)
    except Exception: return None
def win(s, n): return s.astype(float).rolling(n, min_periods=1).max().astype(bool)


# ══════════════════════════ 歷史資料(archive) ══════════════════════════
def fix_split(c, others):
    """r1190: never infer corporate-action factors from a return. Preserve observed crashes.

    Explicit archived action factors were already applied. Unresolved discontinuities are
    excluded from TW stock validation via a trailing validity mask, not erased from prices.
    """
    return (c.pct_change(fill_method=None).abs() > .115)

def explicit_adjustments(archived=None,recent=None,supplemental=None):
    """r1190: merge dated public action records; never derive factors from observed returns."""
    if archived is None:archived=(ld(f'{AR}/adj_tw.json.gz') or {}).get('s',{})
    if recent is None:recent=(jl('adj1y.json',{}) or {}).get('s',{})
    adj={sid:dict(rows) for sid,rows in archived.items()}
    for sid,rows in recent.items():adj.setdefault(sid,{}).update(dict(rows))
    proposals={}
    if supplemental is None:
        supplemental=[]
        folder=f'{AR}/stock_research/r1161/raw'
        for name,before,after in [('TaiwanStockSplitPrice.json','before_price','after_price'),('TaiwanStockParValueChange.json','before_close','after_ref_close'),('capital_reductions.json','ClosingPriceonTheLastTradingDay','PostReductionReferencePrice')]:
            payload=jl(f'{folder}/{name}',{}) or {}
            rows=[r for x in payload.get('sources',{}).values() for r in x['payload']['data']] if name=='capital_reductions.json' else payload.get('data',[])
            for r in rows:
                if isinstance(r.get(before),(int,float)) and isinstance(r.get(after),(int,float)) and r[before]>0 and r[after]>0:
                    supplemental.append((str(r['stock_id']),r['date'],r[after]/r[before]))
    for sid,day,factor in supplemental:
        if np.isfinite(factor) and factor>0 and day<=NOW.date().isoformat():proposals.setdefault((sid,day),[]).append(factor)
    for (sid,day),values in proposals.items():
        if max(values)-min(values)>1e-6 or day in adj.get(sid,{}):continue
        adj.setdefault(sid,{})[day]=values[0]
    return {sid:sorted((d,f) for d,f in rows.items() if d<=NOW.date().isoformat() and np.isfinite(f) and f>0) for sid,rows in adj.items()}


def load_tw(years=None):
    K, I, M = {}, {}, {}
    ys = sorted(os.listdir(f"{AR}/k/tw"))
    if years: ys = ys[-years:]
    for y in ys:
        for p in glob.glob(f"{AR}/k/tw/{y}/*.json.gz"):
            for s, v in ld(p).items():
                if "o" in v: K.setdefault(s, []).append(v)
        for p in glob.glob(f"{AR}/inst/tw/{y}/*.json.gz"):
            for s, v in ld(p).items():
                if "f" in v: I.setdefault(s, []).append(v)
        for p in glob.glob(f"{AR}/margin/tw/{y}/*.json.gz"):
            for s, v in ld(p).items():
                if "mb" in v: M.setdefault(s, []).append(v)
    adj = explicit_adjustments()
    def ser(parts, key, sub=None):
        d, x = [], []
        for v in parts:
            d += v["d"]; x += (v[key] if sub is None else [r[sub] for r in v[key]])
        s = pd.Series(x, index=pd.to_datetime(d), dtype="float64")
        return s[~s.index.duplicated(keep="last")].sort_index()
    C, H, L, V, F, T, MB = {}, {}, {}, {}, {}, {}, {}
    for s, parts in K.items():
        raw = ser(parts, "o", 3)
        C[s] = raw; V[s] = ser(parts, "o", 4)
        if s in I: F[s] = ser(I[s], "f"); T[s] = ser(I[s], "t")
        if s in M: MB[s] = ser(M[s], "mb")
    raw = pd.DataFrame(C)
    n = raw.notna().sum(axis=1); raw = raw[n >= n.rolling(20, min_periods=1).max() * 0.8]
    ix = raw.index
    c = raw.copy()
    for s in c.columns:                              # 除權息還原
        for ed, fac in adj.get(s, []) or []:
            c.loc[c.index < pd.Timestamp(ed), s] *= fac
    jumps = fix_split(c, []).rolling(61,min_periods=1).max().fillna(0).astype(bool)
    W = {"c": c, "raw": raw, "v": pd.DataFrame(V).reindex(ix), "f": pd.DataFrame(F).reindex(ix),
         "t": pd.DataFrame(T).reindex(ix), "mb": pd.DataFrame(MB).reindex(ix), "jumps": jumps}
    return W


def load_us():
    K = {}
    for y in sorted(os.listdir(f"{AR}/k/us")):
        for p in glob.glob(f"{AR}/k/us/{y}/*.json.gz"):
            for s, v in ld(p).items():
                if "o" in v: K.setdefault(s, []).append(v)
    C, V = {}, {}
    for s, parts in K.items():
        d, o = [], []
        for v in parts: d += v["d"]; o += v["o"]
        df = pd.DataFrame(o, index=pd.to_datetime(d)).sort_index()
        df = df[~df.index.duplicated(keep="last")]
        C[s] = df[3]; V[s] = df[4]
    return {"c": pd.DataFrame(C), "v": pd.DataFrame(V)}


# ══════════════════════════ 驗證工具 ══════════════════════════
def fwd_frame(P):
    D = pd.DataFrame({"P": P})
    for k in (20, 60): D[f"r{k}"] = P.shift(-k) / P - 1
    D["mdd"] = pd.concat([P.shift(-i) for i in range(1, 61)], axis=1).min(axis=1) / P - 1
    return D


def grp(D, m):
    m = m & D["r60"].notna()
    if m.sum() == 0: return {"n": 0}
    x = D[m]
    return {"n": int(m.sum()), "w20": r1((x.r20 > 0).mean() * 100, 0), "m20": r1(x.r20.median() * 100),
            "w60": r1((x.r60 > 0).mean() * 100, 0), "m60": r1(x.r60.median() * 100), "dd": r1(x.mdd.median() * 100)}


def episodes(m, gap=20):
    idx = np.flatnonzero(m.values); n, last = 0, -999
    for i in idx:
        if i - last > gap: n += 1
        last = i
    return n


def judge(on, off, ep):
    """通過:亮的時候比沒亮好——3個月上漲機率高 ≥3 個百分點,或之後再跌少 ≥1 個百分點(且上漲機率沒差超過 8)"""
    if on.get("n", 0) < 30 or ep < 4: return False
    a = (on["w60"] or 0) - (off["w60"] or 0)
    b = (on["dd"] or -99) - (off["dd"] or -99)
    return bool(a >= 3 or (b >= 1.0 and a >= -8))


def market_validate(D, L, kinds, names):
    C = D["dd"] <= -0.08
    out = []
    for k, s in L.items():
        s = s.fillna(False)
        on, off = grp(D, C & s), grp(D, C & ~s)
        ep = episodes(C & s & D["r60"].notna())
        out.append({"k": k, "name": names[k], "kind": kinds[k], "ep": ep, "on": on, "off": off, "pass": judge(on, off, ep)})
    lowk = [o["k"] for o in out if o["kind"] == "low" and o["pass"]]
    cnt = sum(L[k].fillna(False).astype(int) for k in lowk) if lowk else pd.Series(0, index=D.index)
    cs = []
    for n in range(0, 4):
        m = C & ((cnt == n) if n < 3 else (cnt >= 3))
        g = grp(D, m)
        if g.get("n", 0) >= 20: g["k"] = n; cs.append(g)
    return {"lights": out, "cnt": cs, "base": grp(D, C), "all": grp(D, pd.Series(True, index=D.index))}


# ══════════════════════════ 每週:驗證 + 門檻 ══════════════════════════
def tw_market_series(W):
    c, raw, f = W["c"], W["raw"], W["f"]
    stk = [s for s in c.columns if not s.startswith("0")]
    P = c["0050"]
    F = (f.reindex(columns=stk).fillna(0) * raw[stk] * 1000).sum(axis=1) / 1e8
    cs = c[stk]
    ab20 = (cs > cs.rolling(20).mean()).sum(axis=1) / cs.notna().sum(axis=1) * 100
    return P, F, ab20


def tw_market_lights(P, F, ab20, F20q):
    ma10, ma20, ma60 = P.rolling(10).mean(), P.rolling(20).mean(), P.rolling(60).mean()
    newlow = P <= P.rolling(20).min()
    F20 = F.rolling(20).sum()
    return {
        "b60": P / ma60 - 1 <= -0.10,
        "b20": P / ma20 - 1 <= -0.06,
        "fx": F20 <= F20q,
        "br": win(ab20 <= 15, 10),
        "thr": win((ab20 >= 50) & win(ab20 <= 20, 15), 5),
        "up": (P > ma10) & ~win(newlow, 3),
    }


NAMES_TW = {"b60": "中線超跌:加權 60 日乖離 ≤ -10%", "b20": "短線急跌:加權 20 日乖離 ≤ -6%",
            "fx": "外資賣到極端:近 20 日累計賣超達近 3 年最極端 10%", "br": "全面殺盤:站上月線的股票 ≤ 15%(近 10 天內)",
            "thr": "止跌:廣度急升(站上月線家數 ≤20% → 15 天內回到 ≥50%)", "up": "止跌:站回 10 日線、3 天不破底"}
NAMES_US = {"b20": "短線急跌:20 日乖離 ≤ 自己歷史最低 5%", "b60": "中線超跌:60 日乖離 ≤ 自己歷史最低 5%",
            "br": "全面殺盤:站上月線的股票 ≤ 15%(近 10 天內)", "nl": "恐慌拋售:創 60 日新低的股票 ≥ 20%(近 10 天內)",
            "thr": "止跌:廣度急升(站上月線家數 ≤20% → 15 天內回到 ≥50%)", "up": "止跌:站回 10 日線、3 天不破底"}
KINDS = {"b60": "low", "b20": "low", "fx": "low", "br": "low", "nl": "low", "thr": "stop", "up": "stop"}


def us_market_lights(P, ab20, lo60, q20, q60):
    ma10, ma20, ma60 = P.rolling(10).mean(), P.rolling(20).mean(), P.rolling(60).mean()
    newlow = P <= P.rolling(20).min()
    return {"b20": P / ma20 - 1 <= q20, "b60": P / ma60 - 1 <= q60, "br": win(ab20 <= 15, 10), "nl": win(lo60 >= 20, 10),
            "thr": win((ab20 >= 50) & win(ab20 <= 20, 15), 5), "up": (P > ma10) & ~win(newlow, 3)}


def stock_validate(c, L, lowk, liq, dd, start="2014-01-01"):
    fwd = {k: c.shift(-k) / c - 1 for k in (20, 60)}
    a = c.values; out = np.full(a.shape, np.nan)
    for i in range(a.shape[0] - 1):
        with np.errstate(all="ignore"): out[i] = np.nanmin(a[i + 1:i + 61], axis=0) / a[i] - 1
    mdd = pd.DataFrame(out, index=c.index, columns=c.columns)
    valid = (liq & fwd[60].notna()).values & (c.index >= pd.Timestamp(start))[:, None]
    def g(M):
        M = M & valid
        n = int(M.sum())
        if n < 200: return {"n": n}
        r, r2, d = fwd[60].values[M], fwd[20].values[M], mdd.values[M]
        return {"n": n, "w20": r1(np.mean(r2 > 0) * 100, 0), "m20": r1(np.nanmedian(r2) * 100), "w60": r1(np.mean(r > 0) * 100, 0),
                "m60": r1(np.nanmedian(r) * 100), "dd": r1(np.nanmedian(d) * 100)}
    deep = (dd <= -0.2).values
    lights = []
    for k in lowk + ["up"]:
        s = L[k].fillna(False).values
        lights.append({"k": k, "on": g(deep & s), "off": g(deep & ~s)})
    cnt = sum(L[k].fillna(False).astype(int) for k in lowk).values
    allv = np.ones_like(valid)
    cs = [dict(g(cnt == n), k=n) for n in range(len(lowk) + 1)]
    csd = [dict(g(deep & (cnt == n)), k=n) for n in range(len(lowk) + 1)]
    up = L["up"].fillna(False).values
    stop = {"on": g((cnt >= 2) & up), "off": g((cnt >= 2) & ~up)}
    return {"lights": lights, "cnt": cs, "cnt_deep": csd, "stop": stop, "all": g(allv.astype(bool)), "deep": g(deep)}


def run_stats():
    t0 = time.time()
    log("📚 讀台股 archive(2012 起)…")
    W = load_tw()
    log(f"  {W['c'].shape} {time.time()-t0:.0f}s")
    # ── 台股大盤 ──
    P, F, ab20 = tw_market_series(W)
    F20 = F.rolling(20).sum()
    F20q_s = F20.rolling(750, min_periods=250).quantile(0.10)
    L = tw_market_lights(P, F, ab20, F20q_s)
    D = fwd_frame(P); D["dd"] = P / P.rolling(250, min_periods=60).max() - 1
    D = D[D.index >= "2014-01-01"]; L = {k: v.reindex(D.index) for k, v in L.items()}
    mk = {"TW": market_validate(D, L, KINDS, NAMES_TW)}
    mk["TW"]["thr"] = {"F20q": r1(F20q_s.iloc[-1], 0)}
    mk["TW"]["name"] = "台股加權"
    log(f"  台股大盤驗證完成 {time.time()-t0:.0f}s:" + ",".join(f"{o['k']}{'✓' if o['pass'] else '✗'}" for o in mk["TW"]["lights"]))
    # ── 台股個股 ──
    c, raw, v, f, t, mb = W["c"], W["raw"], W["v"], W["f"], W["t"], W["mb"]
    stk = [s for s in c.columns if not s.startswith("0")]
    cs, rs = c[stk], raw[stk]
    liq = ((v.reindex(columns=stk) * rs * 1000).rolling(20).mean() >= 2e7) & ~W['jumps'][stk]
    b20 = cs / cs.rolling(20).mean() - 1; b60 = cs / cs.rolling(60).mean() - 1
    q20 = b20.rolling(750, min_periods=250).quantile(0.05); q60 = b60.rolling(750, min_periods=250).quantile(0.05)
    mbs = mb.reindex(columns=stk); mbmax = mbs.rolling(20, min_periods=10).max()
    ts = t.reindex(columns=stk).fillna(0)
    newlow = cs <= cs.rolling(20).min()
    LS = {"20": b20 <= q20, "60": b60 <= q60, "mf": win((mbs > 0) & (mbs <= 0.8 * mbmax) & (mbmax >= 500), 10),
          "tr": win((ts > 0) & (ts.shift(1) > 0) & (ts.shift(2) > 0), 5), "up": (cs > cs.rolling(10).mean()) & ~win(newlow, 3)}
    dd = cs / cs.rolling(120, min_periods=60).max() - 1
    sk = {"TW": stock_validate(cs, LS, ["20", "60", "mf", "tr"], liq, dd)}
    log(f"  台股個股驗證完成 {time.time()-t0:.0f}s")
    # 每檔門檻(全部代號含 ETF,用最近 750 天)
    ca = c
    b20a = ca / ca.rolling(20).mean() - 1; b60a = ca / ca.rolling(60).mean() - 1
    tail = lambda x: x.iloc[-750:]
    thr_tw = {}
    for s in ca.columns:
        a, b = tail(b20a[s]).dropna(), tail(b60a[s]).dropna()
        if len(a) >= 250 and len(b) >= 250:
            thr_tw[s] = [round(float(a.quantile(0.05)), 4), round(float(b.quantile(0.05)), 4)]
    del W, c, raw, v, f, t, mb, cs, rs, liq, b20, b60, q20, q60, mbs, mbmax, ts, LS, dd, ca, b20a, b60a
    # ── 美股 ──
    log("📚 讀美股 archive…")
    U = load_us(); c, v = U["c"], U["v"]
    stk = [s for s in c.columns if s not in ETF_US]
    cs = c[stk]
    ab20 = (cs > cs.rolling(20).mean()).sum(axis=1) / cs.notna().sum(axis=1) * 100
    lo60 = (cs <= cs.rolling(60).min()).sum(axis=1) / cs.notna().sum(axis=1) * 100
    sm = c[[s for s in SEMIS if s in c.columns]]
    ab20s = (sm > sm.rolling(20).mean()).sum(axis=1) / sm.notna().sum(axis=1) * 100
    lo60s = (sm <= sm.rolling(60).min()).sum(axis=1) / sm.notna().sum(axis=1) * 100
    for key, (etf, _sym, name) in MKT_US.items():
        P = c[etf].dropna()
        b20s, b60s = P / P.rolling(20).mean() - 1, P / P.rolling(60).mean() - 1
        q20s, q60s = b20s.expanding(min_periods=500).quantile(0.05), b60s.expanding(min_periods=500).quantile(0.05)
        A, N = (ab20s, lo60s) if key == "SOX" else (ab20, lo60)
        L = us_market_lights(P, A.reindex(P.index), N.reindex(P.index), q20s, q60s)
        D = fwd_frame(P); D["dd"] = P / P.rolling(250, min_periods=60).max() - 1
        D = D[D.index >= "2014-01-01"]; L = {k: v.reindex(D.index) for k, v in L.items()}
        mk[key] = market_validate(D, L, KINDS, NAMES_US)
        mk[key]["thr"] = {"q20": round(float(q20s.iloc[-1]), 4), "q60": round(float(q60s.iloc[-1]), 4)}
        mk[key]["name"] = name
        log(f"  {name} 驗證:" + ",".join(f"{o['k']}{'✓' if o['pass'] else '✗'}" for o in mk[key]["lights"]))
    liq = (v[stk] * cs).rolling(20).mean() >= 2e7
    b20 = cs / cs.rolling(20).mean() - 1; b60 = cs / cs.rolling(60).mean() - 1
    dd = cs / cs.rolling(120, min_periods=60).max() - 1
    q20 = b20.rolling(750, min_periods=250).quantile(0.05); q60 = b60.rolling(750, min_periods=250).quantile(0.05)
    qdd = dd.rolling(750, min_periods=250).quantile(0.05)
    newlow = cs <= cs.rolling(20).min()
    LS = {"20": b20 <= q20, "60": b60 <= q60, "dd": dd <= qdd, "up": (cs > cs.rolling(10).mean()) & ~win(newlow, 3)}
    sk["US"] = stock_validate(cs, LS, ["20", "60", "dd"], liq, dd)
    thr_us = {}
    for s in c.columns:
        x = c[s].dropna()
        if len(x) < 400: continue
        a = (x / x.rolling(20).mean() - 1).iloc[-750:].dropna(); b = (x / x.rolling(60).mean() - 1).iloc[-750:].dropna()
        d = (x / x.rolling(120, min_periods=60).max() - 1).iloc[-750:].dropna()
        thr_us[s] = [round(float(a.quantile(0.05)), 4), round(float(b.quantile(0.05)), 4), round(float(d.quantile(0.05)), 4)]
    log(f"  美股完成 {time.time()-t0:.0f}s")
    S = {"v": 1, "quality_version": "r1190", "u": NOW.strftime("%Y-%m-%d %H:%M"), "period": f"2014~{NOW.year}", "mkt": mk, "stk": sk,
         "thr_tw": thr_tw, "thr_us": thr_us}
    preserve_stats(STATS)
    json.dump(S, open(STATS, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"✓ {STATS}:台股門檻 {len(thr_tw)} 檔、美股 {len(thr_us)} 檔,{time.time()-t0:.0f}s")
    return S


# ══════════════════════════ 每天:目前狀態 ══════════════════════════
def thresholds(closes):
    """最近收盤序列(舊→新)→ 盤中即時判斷用的總和/低點。今天的價格 P 有兩種代入法:
       同一天(P 取代最後一根收盤):S9/S19/S59 = 前 9/19/59 根總和、lo19 = 前 19 根最低、nl2 = 前 2 天有沒有創 20 日新低
       隔天(P 是新的一根):N9/N19/N59 = 最近 9/19/59 根總和、nlo19 = 最近 19 根最低、nl2n = 最近 2 天(含最後一根)有沒有創新低
       20日乖離 = P / ((S19+P)/20) - 1;站回 10 日線 ⇔ P > S9/9;今天破底 ⇔ P ≤ lo19"""
    # r1190: dropping a bad final bar would mislabel an older close with the newest date.
    if len(closes)<62 or any(v is None or not np.isfinite(v) or v<=0 for v in closes[-62:]): return None
    x = [float(v) for v in closes[-62:]]
    if len(x) < 62: return None
    def isnl(i):   # 第 i 根(負索引)是否 ≤ 它前 19 根的最低 → 創 20 日新低
        j = len(x) + i
        return x[j] <= min(x[j - 19:j])
    return {"last": x[-1], "S9": sum(x[-10:-1]), "S19": sum(x[-20:-1]), "S59": sum(x[-60:-1]), "lo19": min(x[-20:-1]),
            "nl2": int(isnl(-2) or isnl(-3)), "N9": sum(x[-9:]), "N19": sum(x[-19:]), "N59": sum(x[-59:]), "nlo19": min(x[-19:]),
            "nl2n": int(isnl(-1) or isnl(-2))}


def px_thr(t, q, n):
    """乖離 ≤ q 的門檻價:P ≤ (1+q)·S(n-1) / (n-(1+q))"""
    S = t["S19"] if n == 20 else t["S59"]
    return (1 + q) * S / (n - (1 + q))


def k_closes(path_glob, adj=None, market='TW', now=None):
    """k/*.json → {sid: (dates, closes, vols)};adj = 台股除權息還原(只處理視窗內的事件)"""
    out = {}
    for p in glob.glob(path_glob):
        for s, v in (jl(p, {}) or {}).items():
            if not isinstance(v, dict) or "o" not in v: continue
            d = v["d"]; c = [r[3] for r in v["o"]]; vol = [r[4] for r in v["o"]]
            local=(now or NOW).astimezone(ZoneInfo('America/New_York' if market=='US' else 'Asia/Taipei'))
            today=local.date().isoformat();cut=16*60 if market=='US' else 13*60+30
            keep=[i for i,day in enumerate(d) if day<today or (day==today and local.hour*60+local.minute>=cut)]
            d=[d[i] for i in keep];c=[c[i] for i in keep];vol=[vol[i] for i in keep]
            if not d:continue
            if adj and s in adj:
                c = c[:]
                for ed, fac in adj[s]:
                    for i, dd in enumerate(d):
                        if dd < ed and c[i] is not None: c[i] = c[i] * fac
            out[s] = (d, c, vol)
    return out


def yext_daily(sym, now=None):
    try:
        d = (jl("yext.json", {}).get("series", {}).get(sym) or {}).get("d") or {}
        rows=[(dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat(), float(c)) for t, c in zip(d.get("t") or [], d.get("c") or []) if c is not None]
        market='TW' if sym=='^TWII' else 'US';local=(now or NOW).astimezone(ZoneInfo('Asia/Taipei' if market=='TW' else 'America/New_York'));today=local.date().isoformat();cut=13*60+30 if market=='TW' else 16*60
        return [(day,c) for day,c in rows if day<today or (day==today and local.hour*60+local.minute>=cut)]
    except Exception: return []


def breadth(series_map, codes, days=30):
    """{sid:(d,c)} → 最近 days 天:站上月線% 與 60日新低%"""
    rows = {}
    for s in codes:
        if s not in series_map: continue
        d, c, _ = series_map[s]
        rows[s] = pd.Series(c, index=pd.to_datetime(d), dtype="float64")
    if not rows: return None, None
    C = pd.DataFrame(rows).sort_index()
    C = C[C.notna().sum(axis=1) >= len(rows) * 0.6]
    ab = (C > C.rolling(20).mean()).sum(axis=1) / C.notna().sum(axis=1) * 100
    lo = (C <= C.rolling(60).min()).sum(axis=1) / C.notna().sum(axis=1) * 100
    return ab.iloc[-days:], lo.iloc[-days:]


def mkt_state(closes, dates, extra, q20, q60, stats):
    t = thresholds(closes)
    if not t: return None
    P = t["last"]
    st = {"d": dates[-1], "last": r1(P, 2), "S9": t["S9"], "S19": t["S19"], "S59": t["S59"], "lo19": t["lo19"], "nl2": t["nl2"],
          "N9": t["N9"], "N19": t["N19"], "N59": t["N59"], "nlo19": t["nlo19"], "nl2n": t["nl2n"],
          "q20": q20, "q60": q60, "p20": r1(px_thr(t, q20, 20), 2), "p60": r1(px_thr(t, q60, 60), 2), "pma10": r1(t["S9"] / 9, 2),
          "b20": r1((P / ((t["S19"] + P) / 20) - 1) * 100, 2), "b60": r1((P / ((t["S59"] + P) / 60) - 1) * 100, 2)}
    st.update(extra)
    st["pass"] = [o["k"] for o in stats.get("lights", []) if o.get("pass")]
    return st


def _pack(t):
    """個股陣列前 11 欄(前端 btmStk 依序讀):last,S9,S19,S59,lo19,nl2,N9,N19,N59,nlo19,nl2n"""
    rd = lambda v: round(v, 2) if abs(v) >= 1 else round(v, 4)
    return [rd(t["last"]), rd(t["S9"]), rd(t["S19"]), rd(t["S59"]), rd(t["lo19"]), t["nl2"], rd(t["N9"]), rd(t["N19"]), rd(t["N59"]), rd(t["nlo19"]), t["nl2n"]]

def preserve_stats(path):
    """r1190: preserve every replaced validation version, including the legacy first one."""
    if not os.path.exists(path):return
    with open(path,'rb') as f:raw=f.read()
    folder=f'{AR}/hist/bottom/stats_versions';os.makedirs(folder,exist_ok=True)
    target=f'{folder}/{hashlib.sha256(raw).hexdigest()}.json.gz'
    if not os.path.exists(target):
        with open(target,'wb') as f:f.write(gzip.compress(raw,mtime=0))

def liquid_value(closes,volumes,multiplier):
    if len(closes)<20 or len(volumes)<20:return False
    rows=list(zip(closes[-20:],volumes[-20:]))
    if any(c is None or v is None or not np.isfinite(c) or not np.isfinite(v) or c<=0 or v<0 for c,v in rows):return False
    return sum(c*v*multiplier for c,v in rows)/20>=2e7

def margin_washout(xs):
    for i in range(max(0,len(xs)-10),len(xs)):
        w=[v for v in xs[max(0,i-19):i+1] if v is not None and np.isfinite(v) and v>=0]
        if len(w)>=10 and max(w)>=500 and xs[i] is not None and np.isfinite(xs[i]) and 0<xs[i]<=.8*max(w):return True
    return False


def run_daily(S, persist=True):
    adj = explicit_adjustments()
    cut = (NOW - dt.timedelta(days=150)).date().isoformat()
    adj_recent = {s: [e for e in v if e[0] >= cut] for s, v in adj.items()}
    adj_recent = {s: v for s, v in adj_recent.items() if v}
    tw = k_closes("k/tw*.json", adj_recent)
    us = k_closes("k/us_*.json",market='US')
    log(f"  K 線:台股 {len(tw)}、美股 {len(us)}")
    out = {"v": 1, "quality_version":S.get('quality_version'), "u": NOW.strftime("%Y-%m-%d %H:%M"), "period": S.get("period"), "stats_u": S.get("u"), "mkt": {}, "stk": {}, "stock_dates":{}}
    # 法人/融資(c/ 分片:f/t 390 天、mf 20 天)
    chips = {}
    for p in glob.glob("c/tw*.json"):
        for s, v in (jl(p, {}) or {}).items():
            if isinstance(v, dict) and v.get("d"): chips[s] = v
    # 封存的融資(補 c/ 只有 20 天的不足)
    mb_ar = {}
    yr = str(NOW.year)
    for y in sorted({str(NOW.year - 1), yr}):
        for p in glob.glob(f"{AR}/margin/tw/{y}/*.json.gz"):
            for s, v in ld(p).items():
                if "mb" in v:
                    a = mb_ar.setdefault(s, {})
                    for d, x in zip(v["d"], v["mb"]): a[d] = x
    # ── 台股大盤 ──
    st_tw = S["mkt"]["TW"]
    tw_idx = yext_daily("^TWII")
    stk_tw = [s for s in tw if not s.startswith("0")]
    ab, lo = breadth(tw, stk_tw)
    # 外資近20日賣超(億)= Σ 外資張數 × 收盤 × 1000
    F = {}
    for s in stk_tw:
        ch = chips.get(s); d, c, _ = tw[s]
        if not ch: continue
        px = dict(zip(d, c))
        for dd, fv in zip(ch["d"][-25:], ch["f"][-25:]):
            p = px.get(dd)
            if p and fv is not None: F[dd] = F.get(dd, 0) + fv * p * 1000 / 1e8
    Fs = pd.Series(F).sort_index()
    F20 = float(Fs.iloc[-20:].sum()) if len(Fs) >= 20 else None
    F20q = st_tw.get("thr", {}).get("F20q")
    if tw_idx and ab is not None:
        dts, cls = [x[0] for x in tw_idx], [x[1] for x in tw_idx]
        thr_series = (ab >= 50) & win(ab <= 20, 15)
        extra = {"ab20": r1(ab.iloc[-1]), "ab20min10": r1(ab.iloc[-10:].min()), "F20": r1(F20, 0), "F20q": F20q,
                 "Fd": [[k, r1(v, 0)] for k, v in Fs.iloc[-10:].items()],   # r1129:近 10 日外資現貨買賣超(億),盤勢解讀用
                 "on": {"fx": bool(F20 is not None and F20q is not None and F20 <= F20q), "br": bool(ab.iloc[-10:].min() <= 15),
                        "thr": bool(thr_series.iloc[-5:].any())}}
        out["mkt"]["TW"] = mkt_state(cls, dts, extra, -0.06, -0.10, st_tw)
        out["mkt"]["TW"]["name"] = "台股加權"
    # ── 美股三大 ──
    stk_us = [s for s in us if s not in ETF_US]
    ab_u, lo_u = breadth(us, stk_us)
    ab_s, lo_s = breadth(us, [s for s in SEMIS if s in us])
    for key, (_etf, sym, name) in MKT_US.items():
        st = S["mkt"].get(key) or {}
        dly = yext_daily(sym)
        A, N = (ab_s, lo_s) if key == "SOX" else (ab_u, lo_u)
        if not dly or A is None: continue
        thr_series = (A >= 50) & win(A <= 20, 15)
        extra = {"ab20": r1(A.iloc[-1]), "ab20min10": r1(A.iloc[-10:].min()), "lo60": r1(N.iloc[-1]), "lo60max10": r1(N.iloc[-10:].max()),
                 "on": {"br": bool(A.iloc[-10:].min() <= 15), "nl": bool(N.iloc[-10:].max() >= 20), "thr": bool(thr_series.iloc[-5:].any())}}
        q = st.get("thr", {})
        m = mkt_state([x[1] for x in dly], [x[0] for x in dly], extra, q.get("q20", -0.05), q.get("q60", -0.08), st)
        if m: m["name"] = name; out["mkt"][key] = m
    # ── 個股 ──
    thr_tw, thr_us = S.get("thr_tw", {}), S.get("thr_us", {})
    n_tw = n_us = 0
    for s, (d, c, vol) in tw.items():
        t = thresholds(c); q = thr_tw.get(s)
        if not t or not q: continue
        liquid=liquid_value(c,vol,1000)
        # 融資洗出:最近10天內任一天 融資 ≤ 前20日高點 × 0.8(且高點 ≥ 500 張)
        mf = 0
        ser = dict(mb_ar.get(s, {}))
        ch = chips.get(s)
        if ch and ch.get("cd") and ch.get("mf"):
            for dd, x in zip(ch["cd"], ch["mf"]):
                if x is not None: ser[dd] = x
        if ser:
            ks = sorted(ser)[-40:]; xs = [ser[k] for k in ks]
            mf=int(margin_washout(xs))
        tr = 0
        if ch and ch.get("t"):
            tt = ch["t"]
            for i in range(len(tt) - 5, len(tt)):
                if i >= 2 and all((tt[j] or 0) > 0 for j in (i, i - 1, i - 2)): tr = 1
        out["stk"][s] = _pack(t) + [q[0], q[1], mf, tr, int(liquid)]
        out['stock_dates'][s]=d[-1]
        n_tw += 1
    for s, (d, c, vol) in us.items():
        t = thresholds(c); q = thr_us.get(s)
        if not t or not q: continue
        hi120 = max(x for x in c[-120:] if x is not None)
        liquid=liquid_value(c,vol,1)
        out["stk"][s] = _pack(t) + [q[0], q[1], r1(hi120, 2), q[2], int(liquid)]
        out['stock_dates'][s]=d[-1]
        n_us += 1
    out["asof"] = {"tw": max((v[0][-1] for v in tw.values()), default=None), "us": max((v[0][-1] for v in us.values()), default=None)}
    # 給前端的驗證摘要(不含每檔門檻)
    out["stats"] = {"mkt": S["mkt"], "stk": S["stk"]}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    if persist:
        try:   # 永久紀錄:每天大盤燈號狀態(只增不刪)
            os.makedirs(f"{AR}/hist/bottom", exist_ok=True)
            fp = f"{AR}/hist/bottom/{NOW.year}.json.gz"
            rec = json.loads(gzip.open(fp).read()) if os.path.exists(fp) else {}
            for k, m in out["mkt"].items():
                if not m: continue
                P = m["last"]
                on = dict(m.get("on") or {})
                on["b20"] = bool(P <= m["p20"]); on["b60"] = bool(P <= m["p60"]); on["up"] = bool(P > m["pma10"] and not m["nl2"] and P > m["lo19"])
                rec.setdefault(m["d"], {})[k] = {"last": P, "b20": m["b20"], "b60": m["b60"], "on": [x for x, v in on.items() if v and x in m["pass"]]}
            gzip.open(fp, "wt", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
        except Exception as e:
            log(f"  永久紀錄略過:{e}")
    log(f"✓ {OUT}:台股 {n_tw} 檔、美股 {n_us} 檔;大盤 " + "、".join(f"{k} {v.get('b20')}%/{v.get('b60')}%" for k, v in out["mkt"].items()))


def main():
    S = jl(STATS)
    need = (S is None or S.get('quality_version')!='r1190' or os.environ.get("BOTTOM_STATS") == "1")
    if S and not need:
        try:
            age = (NOW - dt.datetime.strptime(S["u"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)).days
            need = age >= 7
        except Exception: need = True
    if need:
        if not os.path.isdir(f"{AR}/k/tw"):
            log("✗ 沒有 archive/,無法重算驗證");
            if S is None: return
        else:
            S = run_stats()
    run_daily(S)


if __name__ == "__main__":
    main()
