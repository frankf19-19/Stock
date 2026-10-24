"""🧪 外部資料:回測驗證 + 每日現況(r1130)
  python ext_build.py stats  → ext_stats.json(每週重算;用 archive/ext 的歷史 + 指數長歷史 + archive 個股 K 線)
  python ext_build.py        → ext.json(每天;現況 + 驗證摘要給前端)
驗證原則(跟落底燈號同一套,沒過的照實標示):
  ・美國金融壓力(FRED)、景氣燈號:看指數之後 3/6/12 個月的表現,比較「訊號成立 vs 不成立」。
  ・選擇權支撐壓力:最大賣權未平倉(支撐)/最大買權未平倉(壓力)在結算前守住的比例,
      和「同樣距離、同樣天數」的歷史基準比——守住的比例要明顯比基準高才算有效。
  ・內部人申報賣出(台股)/內部人買進(美股 Form 4):事件後 20/60 天的表現,
      和「之前 60 天漲跌差不多的股票」比(避免『內部人都在大漲後賣』造成的假象)。
  ・空單(FINRA):超跌股裡,空單天數高 vs 低之後 60 天的表現。"""
import os, sys, re, json, gzip, time, math, datetime as dt
from finra_calendar import load_calendar, available_date
import numpy as np, pandas as pd, requests, warnings
warnings.filterwarnings("ignore")

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
E = "archive/ext"
UA = {"User-Agent": "Mozilla/5.0 (K-research personal dashboard)"}


def log(*a): print(*a, flush=True)
def gz(p, d=None):
    try: return json.loads(gzip.open(p).read())
    except Exception: return d
def jl(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d
def r1(x, n=1):
    try:
        x = float(x); return None if not math.isfinite(x) else round(x, n)
    except Exception: return None


# ══════════════════ 指數長歷史(Yahoo 日線 max;存一份永久) ══════════════════
def idx_daily(sym):
    os.makedirs(f"{E}/idx", exist_ok=True)
    fp = f"{E}/idx/{sym.replace('^', '')}.json.gz"
    A = gz(fp, {}) or {}
    if A.get("_v") != 2: A = {"_v": 2}                     # 舊版快取(range=max 會回傳季線,不是日線)整個重抓
    try:
        new = {}
        for p0, p1 in ((0, 1262304000), (1262304000, int(time.time()) + 86400)):   # 分兩段要日線,避免 Yahoo 自動降成月/季線
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"period1": p0, "period2": p1, "interval": "1d"}, headers=UA, timeout=60)
            r0 = r.json()["chart"]["result"][0]
            if (r0.get("meta") or {}).get("dataGranularity") not in (None, "1d"): log(f"  {sym} 粒度 {r0['meta'].get('dataGranularity')},略過這段"); continue
            for t, c in zip(r0.get("timestamp") or [], r0["indicators"]["quote"][0]["close"]):
                if c: new[dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()] = round(float(c), 2)
            time.sleep(1)
        if len(new) > 2000: A.update(new); json_gz(fp, A)
        log(f"  {sym}:日線 {len(A) - 1} 天({min(k for k in A if k != '_v')}~)")
    except Exception as e: log(f"  {sym} 抓取失敗 {e}(用舊資料)")
    A.pop("_v", None)
    s = pd.Series(A, dtype=float); s.index = pd.to_datetime(s.index)
    return s.sort_index()


def json_gz(p, o):
    with gzip.open(p + ".tmp", "wt", encoding="utf-8") as f: json.dump(o, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(p + ".tmp", p)


def fwd(P, hs=(20, 60, 120, 250)):
    D = pd.DataFrame({"P": P})
    for h in hs: D[f"r{h}"] = P.shift(-h) / P - 1
    D["mdd120"] = pd.concat([P.shift(-i) for i in range(1, 121)], axis=1).min(axis=1) / P - 1
    return D


def grp(D, m, h=("r60", "r120", "r250")):
    m = m.fillna(False) & D[h[0]].notna()
    if m.sum() == 0: return {"n": 0}
    x = D[m]; o = {"n": int(m.sum())}
    for c in h:
        y = x[c].dropna()
        if len(y): o["w" + c[1:]] = r1((y > 0).mean() * 100, 0); o["m" + c[1:]] = r1(y.median() * 100)
    o["dd"] = r1(x["mdd120"].median() * 100)
    return o


def episodes(m, gap=20):
    idx = np.flatnonzero(m.fillna(False).values); n, last = 0, -999
    for i in idx:
        if i - last > gap: n += 1
        last = i
    return n


# ══════════════════ A. 美國金融壓力(FRED) ══════════════════
def fred_frame():
    A = gz(f"{E}/fred.json.gz", {}) or {}
    S = {}
    for k, v in (A.get("s") or {}).items():
        s = pd.Series(v, dtype=float); s.index = pd.to_datetime(s.index); S[k] = s.sort_index()
    return S


def fred_signals(S, idx):
    f = lambda k: S[k].reindex(idx, method="ffill") if k in S else pd.Series(np.nan, index=idx)
    baa, nfci, stl, vix, cur = f("BAA10Y"), f("NFCI"), f("STLFSI4"), f("VIXCLS"), f("T10Y3M")
    q90 = baa.rolling(756, min_periods=250).quantile(0.9)
    q80 = baa.rolling(756, min_periods=250).quantile(0.8)
    mx20 = baa.rolling(20, min_periods=5).max()
    sq90 = stl.rolling(756, min_periods=250).quantile(0.9)
    return {
        "credit_hi": baa >= q90,                                     # 公司債利差在近 3 年最高的 10%
        "credit_ease": (mx20 >= q80) & (baa <= mx20 - 0.15),         # 利差從高點回落 0.15 以上(壓力開始解除)
        "nfci_tight": nfci > 0,                                      # 金融情勢偏緊
        "stl_hi": stl >= sq90,                                       # 金融壓力指數在近 3 年最高的 10%
        "vix_hi": vix >= 30,                                         # VIX ≥ 30
        "curve_inv": cur < 0,                                        # 殖利率曲線倒掛(10 年 < 3 個月)
    }, {"baa": baa, "q90": q90, "mx20": mx20, "nfci": nfci, "stl": stl, "vix": vix, "cur": cur}


FRED_KIND = {"credit_hi": "low", "credit_ease": "stop", "nfci_tight": "low", "stl_hi": "low", "vix_hi": "low", "curve_inv": "risk"}
FRED_NAME = {"credit_hi": "公司債利差飆高(近 3 年最高 10%)", "credit_ease": "利差從高點回落(壓力解除)", "nfci_tight": "金融情勢偏緊(NFCI > 0)",
             "stl_hi": "金融壓力指數飆高(近 3 年最高 10%)", "vix_hi": "VIX ≥ 30(恐慌)", "curve_inv": "殖利率曲線倒掛(衰退警訊)"}


def judge_low(on, off, ep):
    if on.get("n", 0) < 60 or ep < 4: return False
    a = (on.get("w120") or 0) - (off.get("w120") or 0); b = (on.get("dd") or -99) - (off.get("dd") or -99)
    return bool(a >= 3 or (b >= 1 and a >= -8))


def stats_fred(spx):
    S = fred_frame()
    D = fwd(spx); D = D[D.index >= "1990-01-01"]
    L, _ = fred_signals(S, D.index)
    D["dd"] = D.P / D.P.rolling(250, min_periods=60).max() - 1
    C = D["dd"] <= -0.08
    out = {}
    for k, s in L.items():
        if FRED_KIND[k] == "risk":   # 風險訊號:全部日子比
            on, off = grp(D, s), grp(D, ~s)
            ep = episodes(s & D.r250.notna(), 60)
            ok = on.get("n", 0) >= 250 and ep >= 3 and ((off.get("w250") or 0) - (on.get("w250") or 0) >= 5 or (on.get("dd") or 0) - (off.get("dd") or 0) <= -2)
        else:
            on, off = grp(D, C & s), grp(D, C & ~s)
            ep = episodes(C & s & D.r120.notna())
            ok = judge_low(on, off, ep)
        flip = False
        if not ok and FRED_KIND[k] != "risk" and on.get("n", 0) >= 60 and ep >= 4:   # 成立時反而更差 → 當「危險訊號」
            flip = bool((off.get("w120") or 0) - (on.get("w120") or 0) >= 5 or (on.get("dd") or 0) - (off.get("dd") or 0) <= -2)
        out[k] = {"name": FRED_NAME[k], "kind": FRED_KIND[k], "pass": ok or flip, "flip": flip, "ep": ep, "on": on, "off": off}
        log(f"  FRED {k:12s} {'✓' if ok else '✗'} ep{ep} on {on} | off {off}")
    return {"lights": out, "period": f"{D.index[0].year}~{D.index[-1].year}", "base": grp(D, C), "all": grp(D, pd.Series(True, index=D.index))}


# ══════════════════ B. 景氣對策信號 ══════════════════
COLOR = {"B": "藍燈", "YB": "黃藍燈", "G": "綠燈", "YR": "黃紅燈", "R": "紅燈"}


def biz_series(idx):
    A = gz(f"{E}/biz.json.gz", {}) or {}
    rows = []
    for m, v in sorted((A.get("m") or {}).items()):
        if not v.get("monitoring"): continue
        y, mo = map(int, m.split("-"))
        pub = (dt.date(y, mo, 1) + dt.timedelta(days=62)).replace(day=1) - dt.timedelta(days=4)   # 次月底左右公布
        rows.append((pd.Timestamp(pub), v["monitoring"], v.get("monitoring_color"), v.get("leading_notrend")))
    if not rows: return None
    F = pd.DataFrame(rows, columns=["pub", "score", "color", "lead"]).set_index("pub")
    F["lead_up3"] = (F.lead.diff() > 0).rolling(3).sum() == 3
    F["lead_turn"] = F.lead_up3 & ~F.lead_up3.shift(1).fillna(False)
    return F.reindex(idx, method="ffill")


def stats_biz(twii):
    D = fwd(twii); D = D[D.index >= "1998-01-01"]
    F = biz_series(D.index)
    if F is None: return {}
    L = {"blue": F.score <= 16, "blue_y": F.score <= 22, "red": F.score >= 38, "red_y": F.score >= 32,
         "lead_turn": pd.Series(F.lead_up3.values, index=D.index)}
    NM = {"blue": "藍燈(≤16 分,景氣低迷)", "blue_y": "藍燈或黃藍燈(≤22 分)", "red": "紅燈(≥38 分,景氣過熱)",
          "red_y": "紅燈或黃紅燈(≥32 分)", "lead_turn": "領先指標連 3 個月上升"}
    out = {}
    for k, s in L.items():
        s = s.fillna(False).astype(bool)
        on, off = grp(D, s), grp(D, ~s); ep = episodes(s & D.r250.notna(), 60)
        if k.startswith("red"):
            ok = on.get("n", 0) >= 120 and ep >= 3 and ((off.get("w250") or 0) - (on.get("w250") or 0) >= 5 or (off.get("m250") or 0) - (on.get("m250") or 0) >= 3)
        else:
            ok = on.get("n", 0) >= 120 and ep >= 3 and ((on.get("w250") or 0) - (off.get("w250") or 0) >= 5 or (on.get("m250") or 0) - (off.get("m250") or 0) >= 3)
        d6 = (on.get("w120") or 0) - (off.get("w120") or 0)
        out[k] = {"name": NM[k], "kind": "risk" if k.startswith("red") else "buy", "pass": ok, "ep": ep, "on": on, "off": off,
                  "p6": bool(on.get("n", 0) >= 120 and ep >= 3 and (d6 <= -5 if k.startswith("red") else d6 >= 5))}
        log(f"  景氣 {k:10s} {'✓' if ok else '✗'} ep{ep} on {on} | off {off}")
    return {"lights": out, "period": f"{D.index[0].year}~{D.index[-1].year}", "all": grp(D, pd.Series(True, index=D.index))}


# ══════════════════ C. 選擇權支撐壓力 ══════════════════
def opt_days():
    out = {}
    d = f"{E}/opt"
    if not os.path.isdir(d): return out
    for fn in sorted(os.listdir(d)):
        out.update(gz(f"{d}/{fn}", {}) or {})
    return out


def opt_expiry(O):
    last = {}
    for d in sorted(O):
        for c, e in O[d].items():
            last[c] = e.get("x", "").replace("/", "-") or d
            if len(last[c]) == 8 and last[c].isdigit(): last[c] = f"{last[c][:4]}-{last[c][4:6]}-{last[c][6:]}"
    return last


def walls(e, spot):
    ks = e["k"]
    pu = [x for x in ks if x[0] <= spot and x[2] > 0]; ca = [x for x in ks if x[0] >= spot and x[1] > 0]
    pw = max(pu, key=lambda x: x[2]) if pu else None; cw = max(ca, key=lambda x: x[1]) if ca else None
    tp = sum(x[2] for x in ks); tc = sum(x[1] for x in ks)
    return pw, cw, (tp / tc if tc else None)


def stats_opt(twii):
    O = opt_days()
    if not O: return {}
    X = opt_expiry(O)
    P = twii; idx = P.index
    pos = {d: i for i, d in enumerate(idx)}
    rows = []
    for d in sorted(O):
        t = pd.Timestamp(d)
        if t not in pos or t.weekday() != 2: continue        # 每週三取樣一次(減少重疊)
        spot = P.loc[t]
        for kind in ("m", "w"):
            cons = sorted(c for c in O[d] if (re.fullmatch(r"\d{6}", c) is not None) == (kind == "m"))
            cons = [c for c in cons if X.get(c) and X[c] > d]
            if kind == "w":   # 跟每日顯示同一規則:接下來 3 個週選裡挑未平倉最多的
                tot = lambda c: sum(x[1] + x[2] for x in O[d][c]["k"])
                cons = sorted(sorted(cons, key=lambda c: X[c])[:3], key=lambda c: -tot(c))
                if cons and tot(cons[0]) < 3000: cons = []
            for c in cons:
                x = X.get(c)
                if not x or x <= d: continue
                te = pd.Timestamp(x)
                if te not in pos: te = idx[idx.searchsorted(te) - 1] if idx.searchsorted(te) > 0 else None
                if te is None or te <= t: continue
                n = pos[te] - pos[t]
                if n < 2 or n > 30: continue
                pw, cw, pcr = walls(O[d][c], spot)
                seg = P.iloc[pos[t] + 1: pos[te] + 1]
                rows.append({"d": d, "k": kind, "n": n, "spot": spot, "pw": pw[0] if pw else None, "cw": cw[0] if cw else None,
                             "end": P.loc[te], "lo": seg.min(), "hi": seg.max()})
                break
    R = pd.DataFrame(rows)
    if R.empty: return {}
    # 基準:同樣天數、同樣距離,歷史上「期間最低沒跌破 / 最高沒漲破」的機率
    cache = {}
    def path_minmax(n):
        if n in cache: return cache[n]
        mins = pd.concat([P.shift(-i) for i in range(1, n + 1)], axis=1).min(axis=1) / P - 1
        maxs = pd.concat([P.shift(-i) for i in range(1, n + 1)], axis=1).max(axis=1) / P - 1
        cache[n] = (mins.dropna().values, maxs.dropna().values); return cache[n]
    out = {}
    for kind in ("m", "w"):
        S = R[R.k == kind]
        for side, col, lab in (("put", "pw", "支撐(最大賣權未平倉)"), ("call", "cw", "壓力(最大買權未平倉)")):
            s = S[S[col].notna()]
            if len(s) < 40: continue
            held, exp = [], []
            for _, x in s.iterrows():
                mins, maxs = path_minmax(int(x.n))
                dist = x[col] / x.spot - 1
                if side == "put":
                    held.append(x.lo >= x[col]); exp.append((mins >= dist).mean())
                else:
                    held.append(x.hi <= x[col]); exp.append((maxs <= dist).mean())
            h, e = float(np.mean(held)) * 100, float(np.mean(exp)) * 100
            ok = len(s) >= 60 and h - e >= 5
            out[f"{kind}_{side}"] = {"name": ("月選" if kind == "m" else "週選") + lab, "n": int(len(s)), "held": r1(h, 0), "exp": r1(e, 0),
                                     "dist": r1(float(((s[col] / s.spot - 1) * 100).median())), "pass": bool(ok)}
            log(f"  選擇權 {kind}_{side}:n={len(s)} 守住 {h:.0f}% vs 基準 {e:.0f}% {'✓' if ok else '✗'}")
    return {"lights": out, "period": f"{R.d.min()[:4]}~{R.d.max()[:4]}"}


# ══════════════════ D/E/F. 個股事件(內部人、Form 4、空單) ══════════════════
def event_study(c, events, liq=None, label=""):
    """events: list of (Timestamp, sid);c: 還原收盤 DataFrame。比「事件」vs「之前 60 天漲跌同一級距的所有股票日」"""
    r20 = c.shift(-20) / c - 1; r60 = c.shift(-60) / c - 1; p60 = c / c.shift(60) - 1
    ix = {d: i for i, d in enumerate(c.index)}
    ev = []
    for t, s in events:
        if s not in c.columns: continue
        j = c.index.searchsorted(t)
        if j + 1 >= len(c.index): continue
        d = c.index[min(j + 1, len(c.index) - 1)]             # 公告隔天收盤進場
        a, b, p = r20.at[d, s], r60.at[d, s], p60.at[d, s]
        if np.isnan(b) or np.isnan(p): continue
        ev.append((d, s, a, b, p))
    if len(ev) < 30: return {"n": len(ev)}
    E_ = pd.DataFrame(ev, columns=["d", "s", "r20", "r60", "p60"])
    # 基準:同期間所有(流動性足夠)股票日,依之前 60 天漲跌分 5 級
    m = r60.stack(); pp = p60.stack()
    if liq is not None: m = m[liq.stack().reindex(m.index).fillna(False)]
    B = pd.DataFrame({"r60": m, "p60": pp.reindex(m.index), "r20": r20.stack().reindex(m.index)}).dropna()
    B = B[B.index.get_level_values(0) >= E_.d.min()]
    qs = np.quantile(B.p60, [0.2, 0.4, 0.6, 0.8])
    B["q"] = np.searchsorted(qs, B.p60); E_["q"] = np.searchsorted(qs, E_.p60)
    w = E_.q.value_counts(normalize=True)
    bm = sum(w.get(q, 0) * (B[B.q == q].r60 > 0).mean() for q in range(5)) * 100
    bmed = sum(w.get(q, 0) * B[B.q == q].r60.median() for q in range(5)) * 100
    bm20 = sum(w.get(q, 0) * (B[B.q == q].r20 > 0).mean() for q in range(5)) * 100
    o = {"n": int(len(E_)), "stocks": int(E_.s.nunique()), "w20": r1((E_.r20 > 0).mean() * 100, 0), "m20": r1(E_.r20.median() * 100),
         "w60": r1((E_.r60 > 0).mean() * 100, 0), "m60": r1(E_.r60.median() * 100),
         "bw20": r1(bm20, 0), "bw60": r1(bm, 0), "bm60": r1(bmed), "allw60": r1((B.r60 > 0).mean() * 100, 0)}
    log(f"  {label}: {o}")
    return o


def insider_events():
    A = gz(f"{E}/insider_tw.json.gz", {}) or {}
    rows = list((A.get("rows") or {}).values())
    return rows


MKT_SALE = ("一般交易", "鉅額", "盤後", "拍賣")


def is_mkt_sale(how): return any(k in (how or "") for k in MKT_SALE)


def stats_insider_tw():
    from bottom import load_tw
    rows = insider_events()
    if len(rows) < 100: return {}
    W = load_tw()
    c, raw, v = W["c"], W["raw"], W["v"]
    liq = (v * raw * 1000).rolling(20).mean() >= 2e7
    adv = v.rolling(20).mean()
    ev_all, ev_big, ev_clu, ev_gift = [], [], [], []
    by = {}
    for x in rows:
        if not x.get("d") or not x.get("sh"): continue
        t = pd.Timestamp(x["d"]); s = x["id"]
        if is_mkt_sale(x.get("how")):
            ev_all.append((t, s)); by.setdefault(s, []).append((t, x.get("who")))
            try:
                j = adv.index.searchsorted(t); a = adv[s].iloc[max(0, j - 1)] if s in adv.columns else np.nan
                px = raw[s].iloc[max(0, j - 1)] if s in raw.columns else np.nan
                if (a and x["sh"] / 1000 >= 3 * a) or (px and x["sh"] * px >= 1e8): ev_big.append((t, s))
            except Exception: pass
        elif "贈與" in (x.get("how") or "") or "信託" in (x.get("how") or ""):
            ev_gift.append((t, s))
    for s, L in by.items():
        L.sort()
        for i, (t, who) in enumerate(L):
            others = {w for (t2, w) in L if abs((t2 - t).days) <= 20 and w != who}
            if others: ev_clu.append((t, s))
    out = {"all": event_study(c, ev_all, liq, "內部人市場賣出(全部)"), "big": event_study(c, ev_big, liq, "大額(≥3 天均量或 ≥1 億)"),
           "clu": event_study(c, list(dict.fromkeys(ev_clu)), liq, "20 天內 2 位以上內部人申報賣"),
           "gift": event_study(c, ev_gift, liq, "贈與/信託給家人")}
    for k, o in out.items():
        if o.get("n", 0) >= 100:
            if k == "gift":   # 贈與/信託:看是不是「之後比同級股票好」
                o["pass"] = bool((o["w60"] - o["bw60"]) >= 3 or (o["m60"] - o["bm60"]) >= 1); o["good"] = True
            else:
                o["pass"] = bool((o["bw60"] - o["w60"]) >= 3 or (o["bm60"] - o["m60"]) >= 1)   # 「警訊」有效 = 之後比同級股票差
    out["period"] = f"{min(x['d'] for x in rows)[:4]}~{NOW.year}"
    return out


def stats_form4():
    from bottom import load_us
    A = gz(f"{E}/form4_us.json.gz", {}) or {}
    rows = list((A.get("rows") or {}).values())
    if len(rows) < 100: return {}
    U = load_us(); c = U["c"]
    liq = (U["v"] * c).rolling(20).mean() >= 2e7
    buy = [x for x in rows if x["c"] == "P" and x.get("fd") and (x.get("v") or 0) >= 50000 and x.get("role") in ("CEO", "CFO", "Officer", "Director")]
    sell = [x for x in rows if x["c"] == "S" and x.get("fd") and (x.get("v") or 0) >= 1e6 and x.get("role") in ("CEO", "CFO", "Officer", "Director")]
    by = {}
    for x in buy: by.setdefault(x["s"], []).append((pd.Timestamp(x["fd"]), x["who"]))
    clu = []
    for s, L in by.items():
        for t, w in L:
            if {w2 for t2, w2 in L if abs((t2 - t).days) <= 30 and w2 != w}: clu.append((t, s))
    out = {"buy": event_study(c, [(pd.Timestamp(x["fd"]), x["s"]) for x in buy], liq, "Form4 主管買進 ≥5 萬美元"),
           "buy_clu": event_study(c, list(dict.fromkeys(clu)), liq, "Form4 30 天內 2 位以上主管買進"),
           "sell_big": event_study(c, [(pd.Timestamp(x["fd"]), x["s"]) for x in sell], liq, "Form4 主管賣出 ≥100 萬美元")}
    for k, o in out.items():
        if o.get("n", 0) >= 100:
            if k.startswith("buy"): o["pass"] = bool((o["w60"] - o["bw60"]) >= 3 or (o["m60"] - o["bm60"]) >= 1)
            else: o["pass"] = bool((o["bw60"] - o["w60"]) >= 3 or (o["bm60"] - o["m60"]) >= 1)
    out["period"] = f"{min(x['fd'] for x in rows)[:4]}~{NOW.year}"
    return out


def finra_frame(cols, idx):
    A = gz(f"{E}/finra_si.json.gz", {}) or {}
    dtc = {}
    calendar = load_calendar()
    for s, d in (A.get("s") or {}).items():
        if s not in cols: continue
        # r1158: unknown publication dates are excluded, not shifted by a guessed offset.
        ser = {pd.Timestamp(available_date(k, calendar)): v[2] for k, v in d.items()
               if available_date(k, calendar) and v and len(v)>2 and v[2] is not None and v[2] < 900}
        if ser: dtc[s] = pd.Series(ser).sort_index()
    if not dtc: return None
    F = pd.DataFrame(dtc).sort_index()
    return F.reindex(idx, method="ffill", limit=25)


def stats_finra():
    from bottom import load_us
    U = load_us(); c = U["c"]
    F = finra_frame(set(c.columns), c.index)
    if F is None or F.dropna(how="all").empty: return {"timing_policy": "official_publication_next_session_v1", "n": 0}
    b20 = c / c.rolling(20).mean() - 1
    q20 = b20.rolling(750, min_periods=250).quantile(0.05)
    over = b20 <= q20
    hi = F.rank(axis=1, pct=True) >= 0.8
    r60 = c.shift(-60) / c - 1
    def g(M):
        x = r60.where(M).stack().dropna()
        return {"n": int(len(x)), "w60": r1((x > 0).mean() * 100, 0), "m60": r1(x.median() * 100)} if len(x) else {"n": 0}
    on, off = g(over & hi), g(over & ~hi & F.notna())
    ok = on.get("n", 0) >= 200 and ((on.get("w60") or 0) - (off.get("w60") or 0) >= 3 or (on.get("m60") or 0) - (off.get("m60") or 0) >= 1)
    log(f"  空單:超跌+空單天數前 20% {on} vs 其他超跌 {off} {'✓' if ok else '✗'}")
    al_hi, al_lo = g(hi), g(~hi & F.notna())
    return {"timing_policy": "official_publication_next_session_v1", "unknown_publication_excluded": True, "over_hi": {"name": "超跌而且空單回補天數高(前 20%)", "on": on, "off": off, "pass": bool(ok)},
            "all_hi": {"name": "空單回補天數高(前 20%,不分漲跌)", "on": al_hi, "off": al_lo,
                       "pass": bool(al_hi.get("n", 0) >= 500 and ((al_lo.get("w60") or 0) - (al_hi.get("w60") or 0) >= 3))},
            "period": f"{F.dropna(how='all').index[0].year}~{F.index[-1].year}"}


def run_stats():
    t0 = time.time()
    spx, twii = idx_daily("^GSPC"), idx_daily("^TWII")
    S = {"u": NOW.strftime("%Y-%m-%d %H:%M")}
    for k, f in (("fred", lambda: stats_fred(spx)), ("biz", lambda: stats_biz(twii)), ("opt", lambda: stats_opt(twii)),
                 ("insider_tw", stats_insider_tw), ("form4", stats_form4), ("finra", stats_finra)):
        try: S[k] = f()
        except Exception as e:
            import traceback; traceback.print_exc(); S[k] = {"err": str(e)[:200]}
        log(f"── {k} 完成 {time.time() - t0:.0f}s")
    json.dump(S, open("ext_stats.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return S


# ══════════════════ 每日現況 ══════════════════
def daily(S):
    out = {"v": 1, "u": NOW.strftime("%Y-%m-%d %H:%M"), "stats_u": S.get("u")}
    # FRED
    try:
        F = fred_frame()
        idx = pd.date_range("2020-01-01", NOW.date(), freq="B")
        L, V = fred_signals(F, idx)
        last = lambda s: (s.dropna().index[-1].date().isoformat(), r1(s.dropna().iloc[-1], 2)) if s.dropna().size else (None, None)
        cur = {}
        for k in ("BAA10Y", "T10Y3M", "NFCI", "STLFSI4", "VIXCLS", "BAMLH0A0HYM2", "DGS10"):
            if k in F and F[k].size:
                s = F[k].dropna(); cur[k] = {"d": s.index[-1].date().isoformat(), "v": r1(s.iloc[-1], 3),
                                              "c20": r1(s.iloc[-1] - s.iloc[-21], 3) if len(s) > 21 else None,
                                              "h": [[d.date().isoformat(), r1(x, 3)] for d, x in s.iloc[-260:].items()][::5]}
        out["fred"] = {"cur": cur, "on": {k: bool(v.iloc[-1]) for k, v in L.items()}, "q90": r1(V["q90"].dropna().iloc[-1], 2) if V["q90"].dropna().size else None,
                       "mx20": r1(V["mx20"].dropna().iloc[-1], 2) if V["mx20"].dropna().size else None, "stats": S.get("fred")}
    except Exception as e: log(f"  FRED 現況失敗 {e}")
    # 景氣
    try:
        A = gz(f"{E}/biz.json.gz", {}) or {}
        ms = sorted(k for k, v in (A.get("m") or {}).items() if v.get("monitoring"))
        h = [[m, A["m"][m]["monitoring"], A["m"][m]["monitoring_color"], A["m"][m].get("leading_notrend")] for m in ms[-60:]]
        lead = [x[3] for x in h[-4:]]
        out["biz"] = {"last": h[-1] if h else None, "h": h, "lead_up3": bool(len(lead) == 4 and all(b > a for a, b in zip(lead, lead[1:]))), "stats": S.get("biz")}
    except Exception as e: log(f"  景氣現況失敗 {e}")
    # 選擇權
    try:
        O = opt_days()
        if O:
            d = max(O); day = O[d]
            spot = None
            try:
                y = json.load(open("yext.json"))["series"]["^TWII"]["d"]; spot = float(y["c"][-1])
            except Exception: pass
            res = {"d": d, "spot": spot, "c": {}}
            X = opt_expiry(O)
            for kind in ("m", "w"):   # 先月選(週選要跟月選比厚薄)
                dd = d.replace("-", "")
                cons = [c for c in day if (re.fullmatch(r"\d{6}", c) is not None) == (kind == "m")]
                cons = sorted((c for c in cons if (day[c].get("x") or "99999999") > dd), key=lambda c: (day[c].get("x") or "99999999", c))
                if not cons or not spot: continue
                if kind == "w":   # 週選:接下來 3 個到期裡,挑未平倉最多的(週五新制週選常常很薄)
                    tot = lambda c: sum(x[1] + x[2] for x in day[c]["k"])
                    cons = sorted(cons[:3], key=lambda c: -tot(c))
                    mon = res["c"].get("m")
                    mtot = sum(x[1] + x[2] for x in (day.get(mon["con"]) or {}).get("k", [])) if mon else 0
                    if tot(cons[0]) < 3000 or (mtot and tot(cons[0]) < 0.25 * mtot): continue   # 太薄 → 這週看月選就好
                cn = cons[0]; e = day[cn]
                pw, cw, pcr = walls(e, spot)
                ks = e["k"]
                tp = sorted([x for x in ks if x[2] > 0], key=lambda x: -x[2])[:5]; tc = sorted([x for x in ks if x[1] > 0], key=lambda x: -x[1])[:5]
                res["c"][kind] = {"con": cn, "x": e.get("x") or "", "pw": pw[0] if pw else None, "pwoi": pw[2] if pw else None,
                                  "cw": cw[0] if cw else None, "cwoi": cw[1] if cw else None, "pcr": r1(pcr * 100 if pcr else None, 0),
                                  "tp": [[x[0], x[2]] for x in tp], "tc": [[x[0], x[1]] for x in tc],
                                  "k": [x for x in ks if abs(x[0] / spot - 1) <= 0.08]}
            res["stats"] = S.get("opt")
            out["opt"] = res
    except Exception as e: log(f"  選擇權現況失敗 {e}")
    # 內部人(台股):近 120 天申報
    try:
        cut = (NOW - dt.timedelta(days=120)).date().isoformat()
        rec = {}
        for x in insider_events():
            if (x.get("d") or "") < cut: continue
            rec.setdefault(x["id"], []).append({k: x.get(k) for k in ("d", "role", "who", "how", "sh", "hold", "after", "p0", "p1", "to")})
        for v in rec.values(): v.sort(key=lambda z: z["d"], reverse=True)
        out["insider_tw"] = {"recent": rec, "stats": S.get("insider_tw")}
    except Exception as e: log(f"  內部人現況失敗 {e}")
    # Form 4:近 120 天
    try:
        A = gz(f"{E}/form4_us.json.gz", {}) or {}
        cut = (NOW - dt.timedelta(days=120)).date().isoformat()
        rec = {}
        for x in (A.get("rows") or {}).values():
            if (x.get("fd") or "") < cut: continue
            rec.setdefault(x["s"], []).append({k: x.get(k) for k in ("fd", "td", "c", "sh", "px", "v", "who", "role")})
        for v in rec.values(): v.sort(key=lambda z: z["fd"], reverse=True)
        out["form4"] = {"recent": rec, "stats": S.get("form4")}
    except Exception as e: log(f"  Form4 現況失敗 {e}")
    # FINRA:每檔最近 6 期
    try:
        A = gz(f"{E}/finra_si.json.gz", {}) or {}
        cur = {}
        calendar = load_calendar()
        today = NOW.date().isoformat()
        for s, d in (A.get("s") or {}).items():
            ks = sorted(k for k in d if calendar.get(k) and calendar[k] <= today)[-6:]
            if ks: cur[s] = [[k] + d[k] for k in ks]
        stats = S.get("finra") or {}
        if stats.get("timing_policy") != "official_publication_next_session_v1":
            stats = {"pending_revalidation": True, "legacy_stats": stats, "timing_policy": "legacy_unverified"}
        out["finra"] = {"cur": cur, "publication_dates": calendar, "stats": stats,
                        "unknown_publication_excluded": True}
    except Exception as e: log(f"  空單現況失敗 {e}")
    json.dump(out, open("ext.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"✓ ext.json:{', '.join(k for k in out if k not in ('v', 'u', 'stats_u'))}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        S = run_stats()
    else:
        S = jl("ext_stats.json", {}) or {}
    daily(S)
