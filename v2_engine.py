#!/usr/bin/env python3
"""AI Pick v2 引擎(r934 研究版):15 年資料 → 每週特徵 → 訓練/回測
資料:archive/k/tw/<年>/<分片>.json.gz(日K)、archive/inst/tw(三大法人)、archive/per/tw(本益比等)
"""
import json, gzip, glob, os, math, datetime as dt
import numpy as np

ROOT = "archive"
WORK = os.environ.get("V2WORK", "v2work")
MKT = os.environ.get("MKT", "TW")
SUB = "tw" if MKT == "TW" else "us"
LIQ = 20000 if MKT == "TW" else 20_000_000      # 20 日均成交值門檻:台股 NT$2,000 萬(張×元/1000);美股 US$2,000 萬
FEATS = ["5日線>月線", "月線>季線", "收盤>月線", "月線斜率", "5日漲幅", "20日漲幅", "60日漲幅", "距20日高",
         "量能比(log)", "月線乖離", "本益比位置", "法人20日淨買比", "外資5日買超比", "投信5日買超比",
         "波動率(ATR%)", "成交值(log)", "相對強弱60", "殖利率", "季線斜率", "20日新高距今"]


def gz(p):
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f: return json.load(f)
    except Exception: return {}


def shards():
    return sorted({os.path.basename(p).split(".")[0] for p in glob.glob(f"{ROOT}/k/{SUB}/*/*.json.gz")})


def calendar(start="2012-01-01"):
    ds = set()
    for p in glob.glob(f"{ROOT}/k/{SUB}/*/*.json.gz"):
        for e in gz(p).values(): ds.update(e.get("d") or [])
    return [d for d in sorted(ds) if d >= start]


def load_shard(sh, cal, pos):
    """只載一個分片 → {id: arrays(float32)}"""
    raw = {}
    for kind in ("k", "inst", "per"):
        for p in sorted(glob.glob(f"{ROOT}/{kind}/{SUB}/*/{sh}.json.gz")):
            for sid, e in gz(p).items():
                r = raw.setdefault(sid, {})
                for k, v in e.items(): r.setdefault(kind + "." + k, []).extend(v)
    n = len(cal); S = {}
    for sid, r in raw.items():
        kd = r.get("k.d") or []; ko = r.get("k.o") or []
        if len(kd) < 250: continue
        idx = np.array([pos.get(d, -1) for d in kd]); ok = idx >= 0
        if ok.sum() < 250: continue
        arr = {k: np.full(n, np.nan, dtype=np.float32) for k in ("o", "h", "l", "c", "v", "f", "t", "pe", "dy")}
        oo = np.array([x if x and len(x) >= 5 else [np.nan] * 5 for x in ko], dtype=np.float32)
        for j, k in enumerate(("o", "h", "l", "c", "v")): arr[k][idx[ok]] = oo[ok, j]
        for key, col in (("inst.f", "f"), ("inst.t", "t"), ("per.pe", "pe"), ("per.dy", "dy")):
            dd = r.get(key.split(".")[0] + ".d") or []; vv = r.get(key) or []
            if dd and vv and len(dd) == len(vv):
                ii = np.array([pos.get(d, -1) for d in dd]); m = ii >= 0
                arr[col][ii[m]] = np.array([x if x is not None else np.nan for x in vv], dtype=np.float32)[m]
        S[sid] = arr
    return S


def market_medians(cal, pos):
    """第一段:全市場每日「前瞻 10 日報酬」與「過去 60 日報酬」的中位數(串流累積)"""
    n = len(cal); F, R = [], []
    for sh in shards():
        for sid, a in load_shard(sh, cal, pos).items():
            c = a["c"]; f = np.full(n, np.nan, dtype=np.float32); f[:-10] = c[10:] / c[:-10] - 1
            r = np.full(n, np.nan, dtype=np.float32); r[60:] = c[60:] / c[:-60] - 1
            F.append(f); R.append(r)
    F = np.array(F); R = np.array(R)
    return np.nanmedian(F, axis=0), np.nanmedian(R, axis=0)


def _ma(x, w):
    c = np.cumsum(np.nan_to_num(x)); out = np.full_like(x, np.nan)
    out[w - 1:] = (c[w - 1:] - np.concatenate(([0], c[:-w]))) / w
    return out


def features(S, cal, mkt_fwd, mkt_r60):
    """對每檔算每天的特徵矩陣(只在 Friday 取樣);回傳 X(行), meta(id, day_idx), fwd(10 日超額報酬)"""
    n = len(cal); days = np.array([dt.date.fromisoformat(d).weekday() for d in cal])
    fri = np.where(days == 4)[0]
    fri = fri[(fri >= 250) & (fri < n - 11)]
    X, meta, Y = [], [], []
    for sid, a in S.items():
        c, o, h, l, v = a["c"], a["o"], a["h"], a["l"], a["v"]
        if np.isnan(c[fri]).all(): continue
        ma5, ma20, ma60 = _ma(c, 5), _ma(c, 20), _ma(c, 60)
        tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1)))); atr = _ma(tr, 14)
        v5, v20 = _ma(v, 5), _ma(v, 20)
        fnet, tnet = np.nan_to_num(a["f"]), np.nan_to_num(a["t"])
        f20 = _ma(fnet + tnet, 20) * 20; f5 = _ma(fnet, 5) * 5; t5 = _ma(tnet, 5) * 5
        hi20 = np.array([np.nanmax(h[max(0, i - 19):i + 1]) if i >= 19 else np.nan for i in range(n)])
        pe = a["pe"]; dy = a["dy"]
        for i in fri:
            if np.isnan(c[i]) or np.isnan(ma60[i]) or v20[i] <= 0 or c[i] <= 0: continue
            if np.isnan(c[i - 60]) or np.isnan(c[i - 250]): continue
            if c[i] * v20[i] < LIQ: continue                       # 20 日均成交值 < 2,000 萬(張×元/1000 → 2 萬) 不選
            pw = pe[max(0, i - 250):i + 1]; pw = pw[~np.isnan(pw)]
            pe_pos = (np.sum(pw <= pe[i]) / len(pw)) if len(pw) >= 60 and not np.isnan(pe[i]) and pe[i] > 0 else 0.5
            d20 = int(i - np.nanargmax(h[i - 19:i + 1]))
            row = [float(ma5[i] > ma20[i]), float(ma20[i] > ma60[i]), float(c[i] > ma20[i]), ma20[i] / ma20[i - 10] - 1,
                   c[i] / c[i - 5] - 1, c[i] / c[i - 20] - 1, c[i] / c[i - 60] - 1, c[i] / hi20[i] - 1,
                   math.log(max(v5[i], 1) / max(v20[i], 1)), c[i] / ma20[i] - 1, pe_pos,
                   f20[i] / max(v20[i] * 20, 1), f5[i] / max(v5[i] * 5, 1), t5[i] / max(v5[i] * 5, 1),
                   atr[i] / c[i], math.log(c[i] * v20[i] + 1), (c[i] / c[i - 60] - 1) - (mkt_r60[i] if not np.isnan(mkt_r60[i]) else 0),
                   (dy[i] if not np.isnan(dy[i]) else 0) / 100, ma60[i] / ma60[i - 20] - 1, d20 / 20]
            if any(not np.isfinite(x) for x in row): continue
            if np.isnan(c[i + 10]) or np.isnan(mkt_fwd[i]): continue
            X.append(row); meta.append((sid, int(i))); Y.append(float(c[i + 10] / c[i] - 1 - mkt_fwd[i]))
    return np.array(X, dtype=float), meta, np.array(Y, dtype=float)


if __name__ == "__main__":
    import time
    os.makedirs(WORK, exist_ok=True)
    t0 = time.time(); cal = calendar(); pos = {d: i for i, d in enumerate(cal)}; print("交易日", len(cal), round(time.time() - t0), "s")
    t0 = time.time(); mkt_fwd, mkt_r60 = market_medians(cal, pos); print("市場中位數完成", round(time.time() - t0), "s")
    np.save(f"{WORK}/{SUB}_mkt_fwd.npy", mkt_fwd); np.save(f"{WORK}/{SUB}_mkt_r60.npy", mkt_r60); json.dump(cal, open(f"{WORK}/{SUB}_cal.json", "w"))
    Xs, metas, Ys = [], [], []; t0 = time.time(); nst = 0
    os.makedirs(f"{WORK}/{SUB}_bars", exist_ok=True)
    for sh in shards():
        S = load_shard(sh, cal, pos); nst += len(S)
        for sid, a in S.items(): np.save(f"{WORK}/{SUB}_bars/{sid}.npy", np.stack([a["o"], a["h"], a["l"], a["c"], a["v"]]))
        X, meta, Y = features(S, cal, mkt_fwd, mkt_r60)
        if len(X): Xs.append(X); metas.extend(meta); Ys.append(Y)
    X = np.concatenate(Xs); Y = np.concatenate(Ys)
    print("特徵", X.shape, "檔數", nst, round(time.time() - t0), "s", "超額報酬中位", round(float(np.nanmedian(Y)) * 100, 3), "%")
    np.save(f"{WORK}/{SUB}_X.npy", X.astype(np.float32)); np.save(f"{WORK}/{SUB}_Y.npy", Y.astype(np.float32)); json.dump(metas, open(f"{WORK}/{SUB}_meta.json", "w"))
