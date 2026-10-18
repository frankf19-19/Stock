"""🧪 策略實驗室資料(r1130)→ lab/tw.bin、lab/us.bin、lab/meta.json(每週重算)
做法:2014 年起每週最後一個交易日,把每一檔(流動性足夠的)股票當天「符合哪些條件」存成一個 32 位元遮罩,
     再存之後 20/60 個交易日的報酬。前端勾選條件 → 直接在瀏覽器裡篩選、統計,不用等伺服器。
二進位格式(小端序):每列 8 bytes = uint32 條件遮罩 + int16 20日報酬(0.1% 單位)+ int16 60日報酬;
     依週排序,meta.json 記每週有幾列。還沒走完 20/60 天的填 -32768。"""
import os, json, glob, gzip, datetime as dt
import numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
from bottom import load_tw, load_us, win, ld, AR, log

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
os.makedirs("lab", exist_ok=True)

TW_C = [
    ("b20low", "短線超跌", "20 日乖離跌到自己近 3 年最低的 5%", "價格"),
    ("b60low", "中線超跌", "60 日乖離跌到自己近 3 年最低的 5%", "價格"),
    ("ma20up", "站上月線", "收盤在 20 日均線之上", "價格"),
    ("ma60up", "站上季線", "收盤在 60 日均線之上", "價格"),
    ("bull", "均線多頭排列", "5 日線 > 20 日線 > 60 日線", "價格"),
    ("hi52", "接近 52 週新高", "收盤 ≥ 一年最高價的 97%", "價格"),
    ("lo20", "創 20 日新低", "收盤是近 20 天最低", "價格"),
    ("volx2", "爆量", "成交量 ≥ 20 日均量 2 倍", "量"),
    ("rs_top", "強勢股", "近 60 日漲幅在全市場前 20%", "價格"),
    ("rs_bot", "弱勢股", "近 60 日漲幅在全市場後 20%", "價格"),
    ("f3", "外資連 3 天買超", "", "籌碼"),
    ("t3", "投信連 3 天買超", "", "籌碼"),
    ("fs5", "外資連 5 天賣超", "", "籌碼"),
    ("mwash", "融資洗出", "融資從近 20 日高點減少 2 成以上(高點 ≥ 500 張)", "籌碼"),
    ("mup", "融資暴增", "融資 20 天增加 2 成以上(≥ 500 張)", "籌碼"),
    ("big_up", "千張大戶加碼", "千張以上大戶持股比例 4 週增加 0.5 個百分點以上", "籌碼"),
    ("ppl_dn", "股東人數減少", "集保股東人數 4 週減少 3% 以上(籌碼集中)", "籌碼"),
    ("ins_sell", "內部人申報賣出", "近 20 天有董監大股東申報在市場賣股", "籌碼"),
    ("rev_yoy", "月營收年增 ≥ 20%", "最新公布的月營收", "基本面"),
    ("rev_hi", "月營收創 12 個月新高", "", "基本面"),
    ("rev_neg", "月營收年減", "", "基本面"),
    ("pe_low", "本益比偏低", "本益比在自己近 3 年最低的 20%", "基本面"),
    ("pe_high", "本益比偏高", "本益比在自己近 3 年最高的 20%", "基本面"),
    ("dy5", "殖利率 ≥ 5%", "", "基本面"),
    ("btm3", "落底燈亮 3 盞以上", "短線超跌、中線超跌、融資洗出、投信進場 4 盞中亮 3 盞", "落底"),
    ("up_btm", "站回 10 日線、3 天不破底", "止跌燈", "落底"),
    ("mkt_deep", "大盤跌深", "大盤離一年高點跌 8% 以上", "大盤"),
    ("mkt_up", "大盤站上季線", "", "大盤"),
]
US_C = [
    ("b20low", "短線超跌", "20 日乖離跌到自己近 3 年最低的 5%", "價格"),
    ("b60low", "中線超跌", "60 日乖離跌到自己近 3 年最低的 5%", "價格"),
    ("ma20up", "站上月線", "", "價格"),
    ("ma60up", "站上季線", "", "價格"),
    ("bull", "均線多頭排列", "5 日線 > 20 日線 > 60 日線", "價格"),
    ("hi52", "接近 52 週新高", "收盤 ≥ 一年最高價的 97%", "價格"),
    ("lo20", "創 20 日新低", "", "價格"),
    ("volx2", "爆量", "成交量 ≥ 20 日均量 2 倍", "量"),
    ("rs_top", "強勢股", "近 60 日漲幅在 S&P 500 前 20%", "價格"),
    ("rs_bot", "弱勢股", "近 60 日漲幅在 S&P 500 後 20%", "價格"),
    ("dd_deep", "跌幅夠深", "離 120 日高點的跌幅達自己近 3 年最深的 5%", "價格"),
    ("ins_buy", "內部人買進", "近 30 天有主管/董事在市場買進 ≥ 5 萬美元(Form 4)", "籌碼"),
    ("ins_sell", "內部人大賣", "近 30 天有主管/董事賣出 ≥ 100 萬美元(Form 4)", "籌碼"),
    ("si_hi", "空單回補天數高", "空單 ÷ 日均量在 S&P 500 前 20%", "籌碼"),
    ("btm3", "落底燈全亮", "短線超跌、中線超跌、跌幅夠深 3 盞全亮", "落底"),
    ("up_btm", "站回 10 日線、3 天不破底", "止跌燈", "落底"),
    ("mkt_deep", "大盤跌深", "SPY 離一年高點跌 8% 以上", "大盤"),
    ("mkt_up", "大盤站上季線", "SPY 在 60 日線之上", "大盤"),
]


def base_price(c, v):
    ma5, ma10, ma20, ma60 = (c.rolling(n).mean() for n in (5, 10, 20, 60))
    b20, b60 = c / ma20 - 1, c / ma60 - 1
    q20 = b20.rolling(750, min_periods=250).quantile(0.05); q60 = b60.rolling(750, min_periods=250).quantile(0.05)
    p60 = c / c.shift(60) - 1
    rk = p60.rank(axis=1, pct=True)
    newlow = c <= c.rolling(20).min()
    return {
        "b20low": b20 <= q20, "b60low": b60 <= q60, "ma20up": c > ma20, "ma60up": c > ma60, "bull": (ma5 > ma20) & (ma20 > ma60),
        "hi52": c >= 0.97 * c.rolling(250, min_periods=200).max(), "lo20": newlow, "volx2": v >= 2 * v.rolling(20).mean(),
        "rs_top": rk >= 0.8, "rs_bot": rk <= 0.2, "up_btm": (c > ma10) & ~win(newlow, 3),
    }


def monthly_to_daily(series_by_stock, idx, lag_days=10):
    """月資料(m → 值)在次月 lag_days 號之後才算公布 → 對齊到日"""
    out = {}
    for s, (ms, vals) in series_by_stock.items():
        ts = [pd.Timestamp(m + "-01") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=lag_days - 1) for m in ms]
        out[s] = pd.Series(vals, index=ts)
    F = pd.DataFrame(out).sort_index()
    F = F[~F.index.duplicated(keep="last")]
    return F.reindex(F.index.union(idx)).ffill().reindex(idx)


def build_tw():
    W = load_tw()
    c, raw, v, f, t, mb = W["c"], W["raw"], W["v"], W["f"], W["t"], W["mb"]
    stk = [s for s in c.columns if not s.startswith("0")]
    c, raw, v, f, t, mb = (x.reindex(columns=stk) for x in (c, raw, v, f, t, mb))
    idx = c.index
    liq = (v * raw * 1000).rolling(20).mean() >= 2e7
    C = base_price(c, v)
    fp, tp = f.fillna(0), t.fillna(0)
    C["f3"] = (fp > 0) & (fp.shift(1) > 0) & (fp.shift(2) > 0)
    C["t3"] = (tp > 0) & (tp.shift(1) > 0) & (tp.shift(2) > 0)
    C["fs5"] = sum((fp.shift(i) < 0).astype(int) for i in range(5)) == 5
    mmax = mb.rolling(20, min_periods=10).max()
    C["mwash"] = (mb <= 0.8 * mmax) & (mmax >= 500)
    C["mup"] = (mb >= 1.2 * mb.shift(20)) & (mb >= 500)
    # 集保大戶
    T = (ld(f"{AR}/tdcc_hist.json.gz") or {}).get("s") or {}
    b10, ppl = {}, {}
    for s in stk:
        x = T.get(s)
        if not x or not x.get("d"): continue
        ix = pd.to_datetime(x["d"]) + pd.Timedelta(days=1)
        b10[s] = pd.Series(x.get("b10"), index=ix, dtype=float); ppl[s] = pd.Series(x.get("p"), index=ix, dtype=float)
    def align(D):
        F = pd.DataFrame(D).sort_index(); F = F[~F.index.duplicated(keep="last")]
        return F.reindex(F.index.union(idx)).ffill(limit=None).reindex(idx).reindex(columns=stk)
    if b10:
        B10, PPL = align(b10), align(ppl)
        C["big_up"] = (B10 - B10.shift(20)) >= 0.5
        C["ppl_dn"] = PPL <= 0.97 * PPL.shift(20)
    # 月營收
    rv = {}
    for p in glob.glob(f"{AR}/rev/tw/*.json.gz"):
        for s, x in (ld(p) or {}).items():
            if s in stk and x.get("m"): rv[s] = (x["m"], x["r"])
    if rv:
        yoy, hi12 = {}, {}
        for s, (ms, r) in rv.items():
            sr = pd.Series(r, index=ms, dtype=float)
            sr = sr[~sr.index.duplicated(keep="last")].sort_index()
            prev = [sr.get(f"{int(m[:4]) - 1}-{m[5:]}") for m in sr.index]
            y = (sr.values / np.array([p if p else np.nan for p in prev], dtype=float)) - 1
            yoy[s] = (list(sr.index), list(y)); hi12[s] = (list(sr.index), list((sr >= sr.rolling(12, min_periods=12).max()).astype(float)))
        Y, H = monthly_to_daily(yoy, idx).reindex(columns=stk), monthly_to_daily(hi12, idx).reindex(columns=stk)
        C["rev_yoy"] = Y >= 0.2; C["rev_neg"] = Y < 0; C["rev_hi"] = H >= 1
    # 本益比、殖利率
    pe, dy = {}, {}
    for p in sorted(glob.glob(f"{AR}/per/tw/*/*.json.gz")):
        for s, x in (ld(p) or {}).items():
            if s not in stk or not x.get("d"): continue
            pe.setdefault(s, {}).update(zip(x["d"], x.get("pe") or []))
            dy.setdefault(s, {}).update(zip(x["d"], x.get("dy") or []))
    if pe:
        PE = pd.DataFrame({s: pd.Series(d, dtype=float) for s, d in pe.items()}); PE.index = pd.to_datetime(PE.index)
        PE = PE.sort_index().reindex(idx).ffill(limit=5).reindex(columns=stk); PE = PE.where(PE > 0)
        DY = pd.DataFrame({s: pd.Series(d, dtype=float) for s, d in dy.items()}); DY.index = pd.to_datetime(DY.index)
        DY = DY.sort_index().reindex(idx).ffill(limit=5).reindex(columns=stk)
        C["pe_low"] = PE <= PE.rolling(750, min_periods=250).quantile(0.2)
        C["pe_high"] = PE >= PE.rolling(750, min_periods=250).quantile(0.8)
        C["dy5"] = DY >= 5
    # 內部人
    ins = gz_rows("archive/ext/insider_tw.json.gz")
    if ins:
        M = pd.DataFrame(False, index=idx, columns=stk)
        for x in ins:
            if any(k in (x.get("how") or "") for k in ("一般交易", "鉅額", "盤後", "拍賣")) and x["id"] in M.columns and x.get("d"):
                j = idx.searchsorted(pd.Timestamp(x["d"]))
                if j < len(idx): M.iloc[j:j + 20, M.columns.get_loc(x["id"])] = True
        C["ins_sell"] = M
    # 落底燈 3 盞
    lights = (C["b20low"].astype(int) + C["b60low"].astype(int) + win(C["mwash"], 10).astype(int) + win(C["t3"], 5).astype(int))
    C["btm3"] = lights >= 3
    # 大盤
    P = W["c"]["0050"]
    mk_deep = P / P.rolling(250, min_periods=60).max() - 1 <= -0.08
    mk_up = P > P.rolling(60).mean()
    C["mkt_deep"] = pd.DataFrame(np.repeat(mk_deep.values[:, None], len(stk), 1), index=idx, columns=stk)
    C["mkt_up"] = pd.DataFrame(np.repeat(mk_up.values[:, None], len(stk), 1), index=idx, columns=stk)
    return pack("tw", TW_C, C, c, liq, idx, stk)


def gz_rows(p):
    try: return list((json.loads(gzip.open(p).read()).get("rows") or {}).values())
    except Exception: return []


def build_us():
    U = load_us()
    c, v = U["c"], U["v"]
    etf = {"SPY", "QQQ", "SOXX", "SMH", "DIA", "IWM"}
    stk = [s for s in c.columns if s not in etf]
    idx = c.index
    cs, vs = c[stk], v.reindex(columns=stk)
    liq = (vs * cs).rolling(20).mean() >= 2e7
    C = base_price(cs, vs)
    hi = cs.rolling(120, min_periods=60).max(); dd = cs / hi - 1
    C["dd_deep"] = dd <= dd.rolling(750, min_periods=250).quantile(0.05)
    rows = gz_rows("archive/ext/form4_us.json.gz")
    if rows:
        B = pd.DataFrame(False, index=idx, columns=stk); S = B.copy()
        for x in rows:
            if x.get("s") not in B.columns or not x.get("fd") or x.get("role") not in ("CEO", "CFO", "Officer", "Director"): continue
            j = idx.searchsorted(pd.Timestamp(x["fd"]))
            if j >= len(idx): continue
            if x["c"] == "P" and (x.get("v") or 0) >= 5e4: B.iloc[j:j + 21, B.columns.get_loc(x["s"])] = True
            if x["c"] == "S" and (x.get("v") or 0) >= 1e6: S.iloc[j:j + 21, S.columns.get_loc(x["s"])] = True
        C["ins_buy"], C["ins_sell"] = B, S
    try:
        from ext_build import finra_frame
        F = finra_frame(set(stk), idx)
        if F is not None: C["si_hi"] = (F.reindex(columns=stk).rank(axis=1, pct=True) >= 0.8)
    except Exception as e: log(f"  空單略過 {e}")
    C["btm3"] = C["b20low"] & C["b60low"] & C["dd_deep"]
    P = c["SPY"]
    mk_deep = P / P.rolling(250, min_periods=60).max() - 1 <= -0.08; mk_up = P > P.rolling(60).mean()
    C["mkt_deep"] = pd.DataFrame(np.repeat(mk_deep.values[:, None], len(stk), 1), index=idx, columns=stk)
    C["mkt_up"] = pd.DataFrame(np.repeat(mk_up.values[:, None], len(stk), 1), index=idx, columns=stk)
    return pack("us", US_C, C, cs, liq, idx, stk)


def pack(mk, CONDS, C, c, liq, idx, stk):
    r20 = c.shift(-20) / c - 1; r60 = c.shift(-60) / c - 1
    s = pd.Series(idx, index=idx)
    wk = s.groupby([idx.isocalendar().year.values, idx.isocalendar().week.values]).max()
    days = [pd.Timestamp(d) for d in wk.values if pd.Timestamp(d) >= pd.Timestamp("2014-01-01")]
    have = [k for k, *_ in CONDS if k in C]
    buf, counts, latest = [], [], []
    for d in days:
        L = liq.loc[d].fillna(False).values
        if L.sum() == 0: counts.append(0); continue
        mask = np.zeros(len(stk), dtype=np.uint32)
        for b, (k, *_rest) in enumerate(CONDS):
            if k in C:
                x = C[k].loc[d].reindex(stk).fillna(False).values.astype(bool)
                mask |= (x.astype(np.uint32) << np.uint32(b))
        a = r20.loc[d].values; b_ = r60.loc[d].values
        enc = lambda z: np.where(np.isfinite(z), np.clip(np.round(z * 1000), -32767, 32767), -32768).astype(np.int16)
        sel = np.flatnonzero(L)
        rec = np.zeros(len(sel), dtype=[("m", "<u4"), ("a", "<i2"), ("b", "<i2")])
        rec["m"] = mask[sel]; rec["a"] = enc(a[sel]); rec["b"] = enc(b_[sel])
        buf.append(rec.tobytes()); counts.append(int(len(sel)))
        if d == days[-1]: latest = [[stk[i], int(mask[i])] for i in sel]
    open(f"lab/{mk}.bin", "wb").write(b"".join(buf))
    log(f"✓ lab/{mk}.bin:{sum(counts)} 列、{len(days)} 週、條件 {len(have)}/{len(CONDS)}")
    return {"weeks": [d.date().isoformat() for d in days], "counts": counts, "latest": latest, "latest_d": days[-1].date().isoformat(),
            "conds": [{"k": k, "n": n, "w": w, "g": g, "ok": k in C} for k, n, w, g in CONDS]}


if __name__ == "__main__":
    meta = {"u": NOW.strftime("%Y-%m-%d %H:%M"), "fmt": "u32 mask + i16 r20(0.1%) + i16 r60(0.1%)"}
    meta["tw"] = build_tw()
    meta["us"] = build_us()
    json.dump(meta, open("lab/meta.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
