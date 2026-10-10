"""r1070:🧺 最愛個股的「近期吃貨分點」(全部券商每日買賣,bkall/<股票>/<年>.tsv.gz,2021-07 起)
=====================================================================================
每檔(最愛/持股優先名單 bk/_prio_users.json,且全券商資料 ≥ 500 個交易日):
  1) 現在誰在吃貨——三種節奏任一符合:
       近 5 天淨買 ≥ 5 天成交量 2%、近 10 天 ≥ 2%、近 20 天 ≥ 1%;
       買的天數 ≥ 一半、賣的天數 ≤ 兩成、最近一天也有買;排除隔日沖券商。
  2) 每家在「這檔」過去同樣節奏吃貨(同一家冷卻 W 天才算下一次)之後 20 天比大盤(全市場同日平均、
     進場=隔天開盤)的實際紀錄:次數、平均、上漲比例;近兩年「≥3 次、平均 ≥+3%、勝率 ≥60%」標 ★。
  3) 這檔的逐年驗證(2023 起每年):用前兩年挑 ★ 分點與最好的節奏 → 當年它們再吃貨 vs 同檔其他分點吃貨;
     再隨機挑同樣家數 200 次當對照 → p 值(隨機也能贏這麼多的機率)。
研究結果(2026-10-11,23 檔最愛,2023~2026 四個驗證年):★ 分點再吃貨 +3.2%(724 次)vs 其他分點 +2.0%、
  這幾檔任意一天 +3.4%;勝過其他分點的「檔×年」35/74 ≈ 一半 → 整體 ❌;p<0.05 只有 4 檔(運氣預期 1.2 檔)。
輸出 bk/_acc.json
用法:python bk_acc.py(bkall.py 收尾時呼叫;也可單獨跑)"""
import os, json, gzip, glob, datetime as dt
import numpy as np

ALL = "bkall"
OUT = "bk/_acc.json"
NOW_STY = [(20, 1.0), (10, 2.0), (5, 2.0)]            # 長的優先(較持續)
STY = [(W, th) for W in (5, 10, 20, 40) for th in (1, 2, 4, 8)]
MINN, MINAVG, MINWIN = 3, 0.03, 0.6
H = 20
NPERM = 200


def log(*a): print(*a, flush=True)


# ── 價格(還原)與全市場同日平均 20 天報酬 ──
def load_prices(since="2021"):
    adj = {}
    try: adj = json.load(gzip.open("archive/adj_tw.json.gz", "rt", encoding="utf-8")).get("s") or {}
    except Exception: pass
    raw = {}
    for p in sorted(glob.glob("archive/k/tw/*/*.json.gz")):
        if os.path.basename(os.path.dirname(p)) < since: continue
        try:
            for sid, e in (json.load(gzip.open(p, "rt", encoding="utf-8")) or {}).items():
                dd = raw.setdefault(sid, {})
                for d, o in zip(e.get("d") or [], e.get("o") or []):
                    if o and len(o) >= 5 and o[3]: dd[d] = (float(o[0] or o[3]), float(o[3]), float(o[4] or 0))
        except Exception: pass
    cal = sorted(raw.get("0050") or max(raw.values(), key=len))
    ci = {d: i for i, d in enumerate(cal)}
    sids = [s for s in raw if len(raw[s]) >= 60]
    O = np.full((len(cal), len(sids)), np.nan); C = O.copy(); V = O.copy()
    for j, s in enumerate(sids):
        exs = sorted(adj.get(s) or [])
        for d, (o, c, v) in raw[s].items():
            i = ci.get(d)
            if i is None: continue
            f = 1.0
            for ex, fx in exs:
                if d < ex: f *= fx
            O[i, j], C[i, j], V[i, j] = o * f, c * f, v
    ent = np.vstack([O[1:], np.full((1, len(sids)), np.nan)])
    ex = np.vstack([C[H:], np.full((H, len(sids)), np.nan)])
    r = ex / ent - 1
    tv = C * V * 1000
    k = 20; cs = np.nancumsum(np.vstack([np.zeros((1, len(sids))), np.nan_to_num(tv)]), axis=0)
    liq = np.full(tv.shape, False); liq[k - 1:] = (cs[k:] - cs[:-k]) / k > 2e7
    rr = np.where(liq & np.isfinite(r) & (np.abs(r) < 1.5), r, np.nan)
    with np.errstate(all="ignore"): mx = np.nanmean(rr, axis=1)
    return cal, ci, {s: j for j, s in enumerate(sids)}, O, C, r, mx


def load_stock(sid):
    seen = {}
    for p in sorted(glob.glob(os.path.join(ALL, sid, "*.tsv.gz"))):
        try:
            for ln in gzip.open(p, "rt", encoding="utf-8"):
                t = ln.rstrip("\n").split("\t")
                if len(t) == 6: seen[(t[0], t[1])] = t
        except Exception: pass
    if not seen: return None
    days = sorted({k[0] for k in seen}); brs = sorted({k[1] for k in seen})
    di = {d: i for i, d in enumerate(days)}; bi = {b: j for j, b in enumerate(brs)}
    BUY = np.zeros((len(days), len(brs)), np.float32); SEL = BUY.copy(); BPX = BUY.copy()
    for (d, b), t in seen.items():
        i, j = di[d], bi[b]
        try:
            BUY[i, j] = float(t[2] or 0); SEL[i, j] = float(t[3] or 0); BPX[i, j] = float(t[4] or 0)
        except Exception: pass
    return {"d": days, "B": brs, "BUY": BUY, "SEL": SEL, "BPX": BPX, "vol": BUY.sum(axis=1).astype(float)}


def roll(a, W):
    c = np.cumsum(np.vstack([np.zeros((1, a.shape[1])), a]), axis=0)
    return np.vstack([np.full((W - 1, a.shape[1]), np.nan), c[W:] - c[:-W]])


def qualify(o, W, th):
    N = (o["BUY"] - o["SEL"]).astype(np.float64)
    NW = roll(N, W)
    vc = np.cumsum(np.concatenate([[0.0], o["vol"]]))
    VW = np.concatenate([np.full(W - 1, np.nan), vc[W:] - vc[:-W]])[:, None]
    with np.errstate(all="ignore"): sh = NW / np.maximum(VW, 1) * 100
    bd = roll((N > 0).astype(np.float64), W); sd = roll((N < 0).astype(np.float64), W)
    q = (sh >= th) & (bd >= max(2, 0.5 * W)) & (sd <= 0.2 * W) & (N > 0)
    return q, sh, NW, bd, sd


def events(o, W, th, cache):
    k = (W, th)
    if k in cache: return cache[k]
    q = qualify(o, W, th)[0]
    ev = []
    for j in range(q.shape[1]):
        last = -10 ** 9
        for i in np.flatnonzero(q[:, j]):
            if i - last >= W and (i == 0 or not q[i - 1, j]): ev.append((i, j)); last = i
    I = np.array([e[0] for e in ev], int); J = np.array([e[1] for e in ev], int)
    X = o["x"][I] if len(I) else np.array([])
    Y = np.array([o["d"][i][:4] for i in I]) if len(I) else np.array([])
    D = np.array([o["d"][i] for i in I]) if len(I) else np.array([])
    cache[k] = (I, J, X, Y, D)
    return cache[k]


def pick(I, J, X, D, lo, hi):
    """lo<=日期<hi 且有 20 天後報酬 → 每家統計,回 ★ 名單"""
    m = (D >= lo) & (D < hi) & np.isfinite(X)
    st = {}
    for j, x in zip(J[m], X[m]): st.setdefault(int(j), []).append(x)
    sel = [j for j, xs in st.items() if len(xs) >= MINN and np.mean(xs) >= MINAVG and np.mean(np.array(xs) > 0) >= MINWIN]
    return sel, st, m


def validate(o, cache, rng):
    years = []; sel_all = []; oth_all = []; perm_rows = []
    for Y in ("2023", "2024", "2025", "2026"):
        lo, hi = f"{int(Y) - 2}-01-01", f"{Y}-01-01"; te_hi = f"{int(Y) + 1}-01-01"
        best = None
        for W, th in STY:
            I, J, X, Yr, D = events(o, W, th, cache)
            if not len(I): continue
            sel, st, m = pick(I, J, X, D, lo, hi)
            if not sel: continue
            xs = [x for j in sel for x in st[j]]
            if len(xs) < 8: continue
            if best is None or np.mean(xs) > best[0]: best = (np.mean(xs), W, th, sel, st)
        if not best: continue
        _, W, th, sel, st = best
        I, J, X, Yr, D = events(o, W, th, cache)
        tm = (D >= hi) & (D < te_hi) & np.isfinite(X)
        if not tm.any(): continue
        ss = np.isin(J, sel) & tm; cc = (~np.isin(J, sel)) & tm
        if not ss.any(): continue
        base = np.nanmean(o["x"][np.array([d[:4] == Y for d in o["d"]])])
        years.append({"Y": Y, "W": W, "th": th, "k": len(sel), "n": int(ss.sum()), "avg": round(float(X[ss].mean()) * 100, 2),
                      "cn": int(cc.sum()), "cavg": round(float(X[cc].mean()) * 100, 2) if cc.any() else None, "base": round(float(base) * 100, 2)})
        sel_all += list(X[ss]); oth_all += list(X[cc])
        cand = [j for j, xs in st.items() if len(xs) >= MINN]
        perm_rows.append((J, X, tm, cand, len(sel)))
    if not years: return None
    obs = np.mean(sel_all) - (np.mean(oth_all) if oth_all else 0)
    null = []
    for _ in range(NPERM):
        a = []; b = []
        for J, X, tm, cand, k in perm_rows:
            s = rng.choice(cand, min(k, len(cand)), replace=False)
            ss = np.isin(J, s) & tm
            a += list(X[ss]); b += list(X[tm & ~np.isin(J, s)])
        if a and b: null.append(np.mean(a) - np.mean(b))
    p = float(np.mean(np.array(null) >= obs)) if null else None
    win = sum(1 for y in years if y["cavg"] is not None and y["avg"] > y["cavg"])
    n = len(sel_all)
    verdict = "樣本少" if n < 15 else ("有效" if (p is not None and p < 0.05 and obs > 0 and win * 2 >= len(years)) else "無效")
    return {"years": years, "n": n, "avg": round(float(np.mean(sel_all)) * 100, 2), "oth": round(float(np.mean(oth_all)) * 100, 2) if oth_all else None,
            "base": round(float(np.nanmean([y["base"] for y in years])), 2), "diff": round(float(obs) * 100, 2),
            "rnd": round(float(np.mean(null)) * 100, 2) if null else None, "p": None if p is None else round(p, 3), "win": win, "ny": len(years), "verdict": verdict}


def now_list(o, tags, cache):
    i = len(o["d"]) - 1
    out = {}
    for W, th in NOW_STY:
        q, sh, NW, bd, sd = qualify(o, W, th)
        I, J, X, Yr, D = events(o, W, th, cache)
        two = (dt.date.fromisoformat(o["d"][-1]) - dt.timedelta(days=730)).isoformat()
        sel, st2, _ = pick(I, J, X, D, two, "9999")
        _, st_all, _ = pick(I, J, X, D, "0000", "9999")
        for j in np.flatnonzero(q[i]):
            nm = o["B"][j]
            if nm in out or (tags.get(nm) or {}).get("tag") == "隔日沖": continue
            w0 = slice(i - W + 1, i + 1)
            b = o["BUY"][w0, j]; px = o["BPX"][w0, j]
            avgpx = float((b * px).sum() / b.sum()) if b.sum() > 0 else None
            xs = st_all.get(int(j), [])
            # 這一波從哪天開始(往回找連續符合的第一天)
            k0 = i
            while k0 > 0 and q[k0 - 1, j]: k0 -= 1
            out[nm] = {"n": nm, "w": W, "net": int(round(NW[i, j])), "sh": round(float(sh[i, j]), 1), "bd": int(bd[i, j]), "sd": int(sd[i, j]),
                       "px": round(avgpx, 2) if avgpx else None, "since": o["d"][k0], "tag": (tags.get(nm) or {}).get("tag"),
                       "h": {"n": len(xs), "avg": round(float(np.mean(xs)) * 100, 2) if xs else None, "win": round(float(np.mean(np.array(xs) > 0)) * 100) if xs else None},
                       "star": int(j) in sel}
    L = sorted(out.values(), key=lambda x: (-x["star"], -x["sh"]))
    return L[:6]


def main(only=None, latest=None):
    t0 = dt.datetime.now()
    try: prio = sorted(x for x in json.load(open("bk/_prio_users.json", encoding="utf-8")) if str(x).isdigit())
    except Exception: prio = []
    if only: prio = only
    try: tags = json.load(open("broker_tags.json", encoding="utf-8"))
    except Exception: tags = {}
    try: prev = json.load(open(OUT, encoding="utf-8"))
    except Exception: prev = {}
    if latest and not only and prev.get("latest") == latest and prev.get("prio") == prio:
        log(f"🧺 近期吃貨分點:資料沒有新的一天({latest}),不重算"); return prev.get("summary")
    cal, ci, sj, O, C, R, MX = load_prices()
    rng = np.random.default_rng(7)
    res = {}; tot = {"sel": [], "oth": []}
    for sid in prio:
        if sid not in sj or not os.path.isdir(os.path.join(ALL, sid)): continue
        o = load_stock(sid)
        if not o or len(o["d"]) < 500: continue
        j = sj[sid]
        idx = [ci.get(d) for d in o["d"]]
        o["x"] = np.array([(R[i, j] - MX[i]) if i is not None and np.isfinite(R[i, j]) and np.isfinite(MX[i]) else np.nan for i in idx])
        cache = {}
        try:
            now = now_list(o, tags, cache)
            pv = (prev.get("s") or {}).get(sid) or {}
            old = {x["n"] for x in (pv.get("now") or [])} if pv.get("d") != o["d"][-1] else set(pv.get("old") or [])
            for x in now: x["new"] = bool(pv) and x["n"] not in old      # 第一次算的那天不標 🆕(免得全部都是新的)
            val = validate(o, cache, rng)
            res[sid] = {"d": o["d"][-1], "days": len(o["d"]), "from": o["d"][0], "now": now, "old": sorted(old), "val": val}
            if val:
                for y in val["years"]:
                    tot["sel"].append((y["avg"], y["n"]))
                    if y["cavg"] is not None: tot["oth"].append((y["cavg"], y["cn"]))
            log(f"  {sid} 現在吃貨 {len(now)} 家{'(' + '、'.join(x['n'] for x in now[:3]) + ')' if now else ''}・驗證 {val and val['verdict']} p={val and val['p']}")
        except Exception as e:
            log(f"  {sid} 失敗:{e}")
    wavg = lambda L: round(sum(a * n for a, n in L) / max(1, sum(n for _, n in L)), 2) if L else None
    V = [r["val"] for r in res.values() if r.get("val")]
    summ = {"stocks": len(V), "sel": wavg(tot["sel"]), "oth": wavg(tot["oth"]), "n": sum(n for _, n in tot["sel"]),
            "ok": sum(1 for v in V if v["verdict"] == "有效"), "p05": sum(1 for v in V if v.get("p") is not None and v["p"] < 0.05)}
    json.dump({"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), "latest": latest, "prio": prio, "summary": summ, "s": res},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"🧺 近期吃貨分點:{len(res)} 檔・整體 ★ {summ['sel']}% vs 其他 {summ['oth']}%・有效 {summ['ok']} 檔・{(dt.datetime.now() - t0).seconds} 秒")
    return summ


if __name__ == "__main__":
    import sys
    main(sys.argv[1:] or None)
