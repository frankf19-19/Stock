"""r971:🔍 關鍵分點 walk-forward 驗證——分週期(1/3/5/10/20 日)
「關鍵分點」原本只看 10 日;不同券商的影響週期不同(隔日沖看 1~3 日、波段看 10~20 日)。
每檔切 訓練期(前 70%)/ 驗證期(後 30%):每個週期 h 各自用訓練期挑關鍵分點(勝率 ≥60%、平均贏過基準),
再看驗證期它們出手後 h 日的表現,並和「訓練期有出手但沒被選上」的一般券商對照。
→ bk/_kb_validation.json(全市場各週期)+ 每檔 "kbv"(各週期的關鍵分點與後段結果)
"""
import json, statistics as st, datetime as dt

HZ = (1, 3, 5, 10, 20)
THR = {1: (0.5, 0.3), 3: (1.0, 0.6), 5: (1.5, 1.0), 10: (2.0, 1.5), 20: (3.0, 2.0)}   # (最低平均%, 需贏基準%)
MIN_ROWS = 60


def _px(closes_of, sid):
    idx, C = closes_of(sid)
    return sorted(idx, key=lambda d: idx[d]), C


def per_stock(e, ds, C):
    pos = {d: i for i, d in enumerate(ds)}
    rows = []
    for d, summ in zip(e.get("d") or [], e.get("s") or []):
        j = pos.get(d)
        if j is None or not C[j]: continue
        fw = {}; fd = {}
        for h in HZ:
            if j + h < len(C) and C[j + h]: fw[h] = (C[j + h] / C[j] - 1) * 100; fd[h] = ds[j + h]
        rows.append((d, fd, fw, [x[0] for x in (summ.get("b") or [])], [x[0] for x in (summ.get("s") or [])]))
    rr = [r for r in rows if 10 in r[2]]
    if len(rr) < MIN_ROWS: return None
    cut = rr[int(len(rr) * 0.7)][0]
    out = {"cut": cut, "hz": {}}
    te_all = [r for r in rows if r[0] > cut]
    te_idx = {3: {}, 4: {}}                                    # r971b:驗證期「券商 → 出手的列」先建索引(原本每家都掃一遍,分週期後超時)
    for i, r in enumerate(te_all):
        for col in (3, 4):
            for nm in r[col]: te_idx[col].setdefault(nm, []).append(i)
    for h in HZ:
        tr = [r for r in rows if h in r[2] and r[1][h] <= cut]       # 不偷看:h 日後的價格也在切點前
        te = [r for r in rows if h in r[2] and r[0] > cut]
        if len(tr) < 30 or len(te) < 10: continue
        btr = st.mean(r[2][h] for r in tr); bte = st.mean(r[2][h] for r in te)
        lo, mg = THR[h]
        H = {"base_tr": round(btr, 2), "base_te": round(bte, 2), "buy": [], "sell": [], "ctl_b": [], "ctl_s": []}
        for side, col in (("b", 3), ("s", 4)):
            ev = {}
            for r in tr:
                for nm in r[col]: ev.setdefault(nm, []).append(r[2][h])
            for nm, v in ev.items():
                if len(v) < 3: continue
                w = sum(1 for x in v if (x > 0 if side == "b" else x < 0)) / len(v) * 100; a = st.mean(v)
                key = (w >= 60 and a >= max(lo, btr + mg)) if side == "b" else (w >= 60 and a <= min(-lo, btr - mg))
                tv = [te_all[i][2][h] for i in te_idx[col].get(nm, ()) if h in te_all[i][2]]
                it = [nm, len(v), round(a, 2), round(w), len(tv), round(st.mean(tv), 2) if tv else None,
                      round(sum(1 for x in tv if (x > 0 if side == "b" else x < 0)) / len(tv) * 100) if tv else None]
                (H["buy" if side == "b" else "sell"] if key else H["ctl_" + side]).append(it)
        out["hz"][h] = H
    return out


def build(R, S, closes_of, log=print, out_path="bk/_kb_validation.json"):
    agg = {h: {k: [] for k in ("buy", "sell", "ctl_b", "ctl_s")} for h in HZ}
    n_st = 0
    for k, sh in R.items():
        for sid, e in sh.items():
            try:
                ds, C = _px(closes_of, sid); v = per_stock(e, ds, C)
            except Exception:
                continue
            if not v: continue
            n_st += 1
            keep = {"cut": v["cut"], "hz": {}}
            for h, H in v["hz"].items():
                for key in agg[h]:
                    for it in H[key]:
                        if it[4]: agg[h][key].append((it[5] - H["base_te"], it[6], it[4]))
                keep["hz"][str(h)] = {"base_tr": H["base_tr"], "base_te": H["base_te"],
                                      "buy": sorted(H["buy"], key=lambda x: -(x[4] or 0))[:10], "sell": sorted(H["sell"], key=lambda x: -(x[4] or 0))[:10]}
            h10 = keep["hz"].get("10") or {}
            keep.update({"base_tr": h10.get("base_tr"), "base_te": h10.get("base_te"), "buy": h10.get("buy", []), "sell": h10.get("sell", [])})   # 舊欄位相容
            if k in S and sid in S[k]: S[k][sid]["kbv"] = keep

    def summ(L):
        if not L: return None
        ex = [x[0] for x in L]; hit = [x[1] for x in L if x[1] is not None]; w = [x[2] for x in L]
        return {"brokers": len(L), "events": sum(w), "excess_avg": round(st.mean(ex), 2),
                "excess_wavg": round(sum(x[0] * x[2] for x in L) / max(1, sum(w)), 2), "excess_med": round(st.median(ex), 2),
                "hit_avg": round(st.mean(hit), 1) if hit else None, "pos_share": round(100 * sum(1 for x in ex if x > 0) / len(ex), 1)}
    res = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "stocks": n_st, "hz": {}}
    for h in HZ:
        a = agg[h]
        res["hz"][str(h)] = {"buy": summ(a["buy"]), "ctl_b": summ(a["ctl_b"]), "sell": summ(a["sell"]), "ctl_s": summ(a["ctl_s"])}
    h10 = res["hz"]["10"]                                       # 舊欄位相容(前端 r970 讀這幾個)
    res.update({"起漲分點(驗證期)": h10["buy"], "對照:一般買方券商": h10["ctl_b"], "出貨分點(驗證期)": h10["sell"], "對照:一般賣方券商": h10["ctl_s"],
                "說明": "excess=驗證期該券商出手後 h 日報酬 − 該檔驗證期任意日 h 日報酬;起漲分點應 >0 且高於對照,出貨分點應 <0 且低於對照"})
    try: json.dump(res, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception: pass
    log("  🔍 關鍵分點驗證(分週期):" + ";".join(
        f"{h}日 起漲 {(res['hz'][str(h)]['buy'] or {}).get('excess_avg')}% vs 對照 {(res['hz'][str(h)]['ctl_b'] or {}).get('excess_avg')}%" for h in HZ))
    return res
