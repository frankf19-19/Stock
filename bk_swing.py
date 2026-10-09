"""r1051:🕵️ 波段主力分點——找出每檔「低檔慢慢吃貨、高檔出貨」的分點,並 walk-forward 驗證
資料:bkraw(每檔每日淨買前 15 / 淨賣前 15 分點,約 250 個交易日)+ 收盤價。
定義(只用當時已知資料):
  價格位置 = 當天收盤在「近 60 日收盤最低~最高」的哪裡(0=最低、1=最高)
  波段主力分點(訓練期判定):買進天數 ≥5、賣出天數 ≥3、買進張數 ≥ 半天成交量、賣出 ≥ 買進 30%;
      買進張數加權的價格位置 ≤0.4(低檔吃)、賣出加權 ≥0.6(高檔賣)、賣出均價比買進均價高 ≥5%
  吃貨訊號:這家分點近 10 個交易日淨買 ≥ 0.2 天成交量、其中買進 ≥3 天、價格位置 ≤0.5(第一天出現才算)
  出貨訊號:近 10 日淨賣 ≥ 0.2 天成交量、賣出 ≥3 天、價格位置 ≥0.5
驗證:每檔前 60% 交易日找分點,後 40% 看它們再出現吃貨/出貨訊號後 10、20 日股價(減全市場同日平均),
      對照組 = 同樣訊號、但不是波段主力的分點。 → bk/_swing_validation.json;每檔 → "sw"
"""
import json, os, statistics as st, datetime as dt

TRAIN = 0.6; WIN = 10; MIN_DAYS = int(os.environ.get("SW_MIN_DAYS", "120"))


def _rows(e, pos, C):
    B = {}; vols = []
    for d, s in zip(e.get("d") or [], e.get("s") or []):
        j = pos.get(d)
        if j is None or not C[j] or not s: continue
        w = [x for x in C[max(0, j - 59):j + 1] if x]
        lo, hi = min(w), max(w); pp = (C[j] - lo) / (hi - lo) if hi > lo else 0.5
        if s.get("vol"): vols.append(s["vol"])
        for side in ("b", "s"):
            for x in s.get(side) or []:
                nm, net, px = x[0], x[1], (x[2] if len(x) > 2 and x[2] else C[j])
                if net: B.setdefault(nm, []).append((d, j, net, px, pp))
    return B, (st.median(vols) if vols else None)


def _profile(rows, vol):
    buys = [r for r in rows if r[2] > 0]; sells = [r for r in rows if r[2] < 0]
    bl = sum(r[2] for r in buys); sl = -sum(r[2] for r in sells)
    if not buys or not sells or bl <= 0 or sl <= 0: return None
    bv = sum(r[2] * r[3] for r in buys) / bl; sv = sum(-r[2] * r[3] for r in sells) / sl
    bp = sum(r[2] * r[4] for r in buys) / bl; sp = sum(-r[2] * r[4] for r in sells) / sl
    return {"nb": len(buys), "ns": len(sells), "bl": round(bl), "sl": round(sl), "bv": round(bv, 2), "sv": round(sv, 2),
            "spread": round((sv / bv - 1) * 100, 1), "bpos": round(bp, 2), "spos": round(sp, 2), "vol": vol}


def _is_swing(p):
    return bool(p and p["nb"] >= 5 and p["ns"] >= 3 and p["vol"] and p["bl"] >= 0.5 * p["vol"] and p["sl"] >= 0.3 * p["bl"]
                and p["bpos"] <= 0.4 and p["spos"] >= 0.6 and p["spread"] >= 5)


def _signals(rows, ds, vol, lo_j, hi_j):
    """回傳 [(j, 'acc'|'dist', 淨張)]:第 j 天(lo_j<=j<hi_j)出現吃貨/出貨訊號(第一天);前綴和 O(n)"""
    if not vol: return []
    by = {}; pp = {}
    for r in rows:
        by[r[1]] = by.get(r[1], 0) + r[2]; pp[r[1]] = r[4]
    act = sorted(j for j in by if lo_j <= j < hi_j)
    if not act: return []
    base = lo_j - WIN; n = hi_j - base + 1
    net = [0.0] * n; pos = [0] * n; neg = [0] * n
    for j, v in by.items():
        if base <= j < hi_j:
            net[j - base] = v; pos[j - base] = 1 if v > 0 else 0; neg[j - base] = 1 if v < 0 else 0
    cn = [0.0]; cp = [0]; cg = [0]
    for i in range(n): cn.append(cn[-1] + net[i]); cp.append(cp[-1] + pos[i]); cg.append(cg[-1] + neg[i])
    out = []; last = {"acc": -99, "dist": -99}
    for j in act:
        i1 = j - base + 1; i0 = max(0, i1 - WIN)
        w = cn[i1] - cn[i0]; nb = cp[i1] - cp[i0]; ns = cg[i1] - cg[i0]; p = pp.get(j, 0.5)
        if w >= 0.2 * vol and nb >= 3 and p <= 0.5:
            if j - last["acc"] > WIN: out.append((j, "acc", w))
            last["acc"] = j
        if -w >= 0.2 * vol and ns >= 3 and p >= 0.5:
            if j - last["dist"] > WIN: out.append((j, "dist", w))
            last["dist"] = j
    return out


def build(R, S, closes_of, log=print, shard_key=None):
    try:                                                    # r1053:已經有「全部券商」版本就不用前 15 大版本覆蓋
        if json.load(open("bk/_swing_validation.json", encoding="utf-8")).get("src") == "全部券商": return None
    except Exception: pass
    # 全市場同日平均(10、20 日後)
    px = {}; mk = {10: {}, 20: {}}
    for k, sh in R.items():
        for sid in sh:
            try:
                idx, C = closes_of(sid)
                if len(C) < 80: continue
                ds = sorted(idx, key=lambda d: idx[d]); px[sid] = (ds, C)
                for h in (10, 20):
                    for i in range(max(0, len(C) - 300), len(C) - h):
                        if C[i] and C[i + h]: mk[h].setdefault(ds[i], []).append(C[i + h] / C[i] - 1)
            except Exception: pass
    mkm = {h: {d: sum(v) / len(v) for d, v in mk[h].items() if len(v) >= 50} for h in mk}
    ev = {g: {h: [] for h in (10, 20)} for g in ("acc_sw", "acc_ctl", "dist_sw", "dist_ctl")}
    nst = 0; nsw = 0; today = {"acc": [], "dist": []}
    for k, sh in R.items():
        for sid, e in sh.items():
            if sid not in px or len(e.get("d") or []) < MIN_DAYS: continue
            ds, C = px[sid]; pos = {d: i for i, d in enumerate(ds)}
            B, vol = _rows(e, pos, C)
            if not vol: continue
            dd = sorted(pos[d] for d in e["d"] if d in pos)
            if len(dd) < MIN_DAYS: continue
            cut_j = dd[int(len(dd) * TRAIN)]; nst += 1
            # ── walk-forward 驗證 ──
            for nm, rows in B.items():
                tr = [r for r in rows if r[1] < cut_j]
                p = _profile(tr, vol); sw = _is_swing(p)
                if not p or p["nb"] < 3: continue                     # 對照組也要訓練期有在這檔交易
                for j, kind, net in _signals(rows, ds, vol, cut_j, len(C)):
                    for h in (10, 20):
                        if j + h < len(C) and C[j] and C[j + h] and ds[j] in mkm[h]:
                            ex = (C[j + h] / C[j] - 1) - mkm[h][ds[j]]
                            ev[f"{kind}_{'sw' if sw else 'ctl'}"][h].append(ex)
            # ── 每檔目前狀態(全期間判定)──
            out = []
            last_j = dd[-1]
            for nm, rows in B.items():
                p = _profile(rows, vol)
                if not _is_swing(p): continue
                rec = [r for r in rows if r[1] > last_j - 20]
                n10 = sum(r[2] for r in rows if r[1] > last_j - 10); n20 = sum(r[2] for r in rec)
                bd10 = sum(1 for r in rows if r[1] > last_j - 10 and r[2] > 0); sd10 = sum(1 for r in rows if r[1] > last_j - 10 and r[2] < 0)
                st_ = "吃貨中" if n10 >= 0.2 * vol and bd10 >= 3 else "出貨中" if -n10 >= 0.2 * vol and sd10 >= 3 else "觀望"
                # 目前估計持有(全期間淨買)與成本
                held = sum(r[2] for r in rows)
                out.append({"n": nm, **{x: p[x] for x in ("nb", "ns", "bl", "sl", "bv", "sv", "spread", "bpos", "spos")},
                            "st": st_, "n10": round(n10), "n20": round(n20), "held": round(held),
                            "last": max(r[0] for r in rows)})
            out.sort(key=lambda x: (-(x["st"] == "吃貨中"), -x["spread"] * x["bl"]))
            if out:
                nsw += 1
                for side, tag in (("acc", "吃貨中"), ("dist", "出貨中")):
                    br = [[b["n"], b["n10"], b["bv"], b["sv"], b["spread"], b["nb"], b["ns"]] for b in out if b["st"] == tag]
                    if br: today[side].append({"id": sid, "px": C[last_j], "br": br[:3]})
                if S.get(k, {}).get(sid) is not None:
                    S[k][sid]["sw"] = {"u": ds[last_j], "vol": round(vol), "days": len(dd), "b": out[:8]}
            elif S.get(k, {}).get(sid) is not None:
                S[k][sid].pop("sw", None)
    def agg(a):
        if not a: return None
        return {"n": len(a), "avg": round(sum(a) / len(a) * 100, 2), "med": round(st.median(a) * 100, 2), "up": round(sum(1 for x in a if x > 0) / len(a) * 100, 1)}
    V = {"updated": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"), "stocks": nst, "with_swing": nsw,
         "rule": "前 60% 交易日找分點、後 40% 驗證;報酬 = 訊號日收盤後 h 日 − 全市場同日平均",
         "res": {g: {str(h): agg(v) for h, v in hv.items()} for g, hv in ev.items()}}
    a = (V["res"]["acc_sw"].get("20") or {}); c = (V["res"]["acc_ctl"].get("20") or {})
    V["pass_acc"] = bool(a and c and a["n"] >= 200 and a["avg"] - c["avg"] >= 1.0 and a["up"] > c["up"])
    a2 = (V["res"]["dist_sw"].get("20") or {}); c2 = (V["res"]["dist_ctl"].get("20") or {})
    V["pass_dist"] = bool(a2 and c2 and a2["n"] >= 200 and c2["avg"] - a2["avg"] >= 1.0 and a2["up"] < c2["up"])
    os.makedirs("bk", exist_ok=True)
    json.dump(V, open("bk/_swing_validation.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for side in today: today[side].sort(key=lambda x: -sum(abs(b[1]) for b in x["br"]))
    json.dump({"d": max((e.get("d") or [""])[-1] for sh in R.values() for e in sh.values()), **today}, open("bk/_swing_today.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"  🕵️ 波段主力分點:{nst} 檔可算、{nsw} 檔有;驗證 吃貨 {a} vs 對照 {c};出貨 {a2} vs 對照 {c2}")
    return V


if __name__ == "__main__":                                     # 獨立執行:python bk_swing.py [raw 目錄,預設 bkraw](swing.yml 用)
    import importlib.util, sys, traceback
    spec = importlib.util.spec_from_file_location("fb", "fetch_broker.py"); fb = importlib.util.module_from_spec(spec); spec.loader.exec_module(fb)
    try:
        R = fb.load_shards(sys.argv[1] if len(sys.argv) > 1 else "bkraw")
        if not R: R = fb.load_shards("bk")
        S = fb.load_shards()
        n = sum(len(sh) for sh in R.values()); dmax = max((len(e.get("d") or []) for sh in R.values() for e in sh.values()), default=0)
        print(f"raw 股票 {n} 檔,最長 {dmax} 天", flush=True)
        build(R, S, fb.closes_of)
        if os.environ.get("SW_SAVE", "1") == "1": fb.save_shards(S)
    except Exception:
        os.makedirs("bk", exist_ok=True)
        json.dump({"error": traceback.format_exc()[-3000:]}, open("bk/_swing_status.json", "w", encoding="utf-8"), ensure_ascii=False)
        raise


# ═══ r1053:全券商、多年版本(bkall/<股票>.tsv.gz)═══
_ARC = {}
def _closes_all(sid, closes_of, since="2019-01-01"):
    """收盤:archive/k(多年,分片快取)∪ hist ∪ k(較新者優先)"""
    import gzip, glob
    m = {}
    try:
        k = sid[:3] if sid[:2] == "00" else sid[:2]
        if k not in _ARC:
            _ARC[k] = {}
            for p in sorted(glob.glob(f"archive/k/tw/*/{k}.json.gz")):
                if os.path.basename(os.path.dirname(p)) < since[:4]: continue
                try:
                    for s2, e in (json.load(gzip.open(p, "rt", encoding="utf-8")) or {}).items():
                        dd = _ARC[k].setdefault(s2, {})
                        for d, o in zip(e.get("d") or [], e.get("o") or []):
                            if o and len(o) >= 4 and o[3]: dd[d] = o[3]
                except Exception: pass
        m.update(_ARC[k].get(sid) or {})
    except Exception: pass
    try:
        idx, C = closes_of(sid)
        for d, i in idx.items():
            if C[i]: m[d] = C[i]
    except Exception: pass
    ds = sorted(m)
    return ds, [m[d] for d in ds]


def build_full(ALL, log=print):
    import gzip, glob, importlib.util
    spec = importlib.util.spec_from_file_location("fb", "fetch_broker.py"); fb = importlib.util.module_from_spec(spec); spec.loader.exec_module(fb)
    files = sorted(glob.glob(os.path.join(ALL, "*.tsv.gz")))
    if not files: log("  全券商資料還沒有"); return None
    # 收盤與全市場同日平均
    px = {}; mk = {10: {}, 20: {}}
    for p in files:
        sid = os.path.basename(p).split(".")[0]
        ds, C = _closes_all(sid, fb.closes_of)
        if len(C) < 80: continue
        px[sid] = (ds, C)
        for h in (10, 20):
            for i in range(len(C) - h):
                if C[i] and C[i + h]: mk[h].setdefault(ds[i], []).append(C[i + h] / C[i] - 1)
    mkm = {h: {d: sum(v) / len(v) for d, v in mk[h].items() if len(v) >= 50} for h in mk}
    ev = {}; nst = 0; nsw = 0; today = {"acc": [], "dist": []}; per = {}; span = [None, None]
    S = fb.load_shards()
    for p in files:
        sid = os.path.basename(p).split(".")[0]
        if sid not in px: continue
        ds, C = px[sid]; pos = {d: i for i, d in enumerate(ds)}
        B = {}; vold = {}
        try:
            for ln in gzip.open(p, "rt", encoding="utf-8"):
                d, nm, b, s, bp, sp = ln.rstrip("\n").split("\t"); b = float(b); s = float(s)
                j = pos.get(d)
                if j is None or not C[j]: continue
                vold[d] = vold.get(d, 0) + b
                net = b - s
                if abs(net) < 1: continue
                B.setdefault(nm, []).append([d, j, net, (float(bp) if net > 0 else float(sp)) or C[j], None])
        except Exception: continue
        if len(vold) < MIN_DAYS: continue
        vol = st.median(vold.values()) if vold else None
        if not vol: continue
        nst += 1
        dd = sorted(pos[d] for d in vold)
        span[0] = min(span[0] or ds[dd[0]], ds[dd[0]]); span[1] = max(span[1] or ds[dd[-1]], ds[dd[-1]])
        ppos = {}
        for j in dd:
            w = [x for x in C[max(0, j - 59):j + 1] if x]; lo, hi = min(w), max(w); ppos[j] = (C[j] - lo) / (hi - lo) if hi > lo else 0.5
        for rows in B.values():
            for r in rows: r[4] = ppos.get(r[1], 0.5)
        years = sorted({ds[j][:4] for j in dd})
        # ── 逐年 walk-forward:用前兩年(只看過去)找分點,當年驗證 ──
        for y in years[1:]:
            y0 = next((j for j in dd if ds[j][:4] == y), None)
            if y0 is None: continue
            tr_lo = next((j for j in dd if ds[j] >= f"{int(y) - 2}-01-01"), dd[0])
            y1 = next((j for j in dd if ds[j][:4] > y), len(C))
            if sum(1 for j in dd if tr_lo <= j < y0) < 120: continue
            for nm, rows in B.items():
                tr = [r for r in rows if tr_lo <= r[1] < y0]
                pr = _profile(tr, vol)
                if not pr or pr["nb"] < 3: continue
                sw = _is_swing(pr)
                for j, kind, net in _signals(rows, ds, vol, y0, y1):
                    for h in (10, 20):
                        if j + h < len(C) and C[j] and C[j + h] and ds[j] in mkm[h]:
                            ex = (C[j + h] / C[j] - 1) - mkm[h][ds[j]]
                            ev.setdefault(f"{kind}_{'sw' if sw else 'ctl'}", {}).setdefault(h, []).append(ex)
                            per.setdefault(y, {}).setdefault(f"{kind}_{'sw' if sw else 'ctl'}", []).append(ex) if h == 20 else None
        # ── 目前狀態(最近兩年)──
        last_j = dd[-1]; lo2 = next((j for j in dd if ds[j] >= f"{int(ds[last_j][:4]) - 2}{ds[last_j][4:]}"), dd[0])
        out = []
        for nm, rows in B.items():
            rr = [r for r in rows if r[1] >= lo2]
            pr = _profile(rr, vol)
            if not _is_swing(pr): continue
            n10 = sum(r[2] for r in rr if r[1] > last_j - 10)
            bd10 = sum(1 for r in rr if r[1] > last_j - 10 and r[2] > 0); sd10 = sum(1 for r in rr if r[1] > last_j - 10 and r[2] < 0)
            st_ = "吃貨中" if n10 >= 0.2 * vol and bd10 >= 3 else "出貨中" if -n10 >= 0.2 * vol and sd10 >= 3 else "觀望"
            out.append({"n": nm, **{x: pr[x] for x in ("nb", "ns", "bl", "sl", "bv", "sv", "spread", "bpos", "spos")}, "st": st_,
                        "n10": round(n10), "n20": round(sum(r[2] for r in rr if r[1] > last_j - 20)), "held": round(sum(r[2] for r in rr)), "last": max(r[0] for r in rr)})
        out.sort(key=lambda x: (-(x["st"] == "吃貨中"), -x["spread"] * x["bl"]))
        k = fb.shard_key(sid)
        if out:
            nsw += 1
            if S.get(k, {}).get(sid) is not None: S[k][sid]["sw"] = {"u": ds[last_j], "vol": round(vol), "days": len(dd), "all": 1, "b": out[:8]}
            for side, tag in (("acc", "吃貨中"), ("dist", "出貨中")):
                br = [[b["n"], b["n10"], b["bv"], b["sv"], b["spread"], b["nb"], b["ns"]] for b in out if b["st"] == tag]
                if br: today[side].append({"id": sid, "px": C[last_j], "br": br[:3]})
        elif S.get(k, {}).get(sid) is not None: S[k][sid].pop("sw", None)

    def agg(a):
        if not a: return None
        return {"n": len(a), "avg": round(sum(a) / len(a) * 100, 2), "med": round(st.median(a) * 100, 2), "up": round(sum(1 for x in a if x > 0) / len(a) * 100, 1)}
    V = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "src": "全部券商", "span": span, "stocks": nst, "with_swing": nsw,
         "rule": "逐年 walk-forward:用前兩年找分點、當年驗證;報酬 = 訊號日收盤後 h 日 − 全市場同日平均",
         "res": {g: {str(h): agg(v) for h, v in hv.items()} for g, hv in ev.items()},
         "years": {y: {g: agg(v) for g, v in gv.items()} for y, gv in sorted(per.items())}}
    a = (V["res"].get("acc_sw") or {}).get("20") or {}; c = (V["res"].get("acc_ctl") or {}).get("20") or {}
    ys = [y for y, gv in V["years"].items() if gv.get("acc_sw") and gv.get("acc_ctl") and gv["acc_sw"]["n"] >= 30]
    yw = sum(1 for y in ys if V["years"][y]["acc_sw"]["avg"] > V["years"][y]["acc_ctl"]["avg"])
    V["pass_acc"] = bool(a and c and a["n"] >= 200 and a["avg"] - c["avg"] >= 1.0 and a["up"] > c["up"] and (not ys or yw >= 0.7 * len(ys)))
    a2 = (V["res"].get("dist_sw") or {}).get("20") or {}; c2 = (V["res"].get("dist_ctl") or {}).get("20") or {}
    V["pass_dist"] = bool(a2 and c2 and a2["n"] >= 200 and c2["avg"] - a2["avg"] >= 1.0 and a2["up"] < c2["up"])
    json.dump(V, open("bk/_swing_validation.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for side in today: today[side].sort(key=lambda x: -sum(abs(b[1]) for b in x["br"]))
    json.dump({"d": span[1], "all": 1, **today}, open("bk/_swing_today.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    fb.save_shards(S)
    log(f"  🕵️ 全券商波段主力分點:{nst} 檔、{nsw} 檔有;吃貨 {a} vs {c}")
    return {"stocks": nst, "with_swing": nsw, "pass_acc": V["pass_acc"], "pass_dist": V["pass_dist"]}
