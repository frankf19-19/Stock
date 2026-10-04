"""r969:🔍 關鍵分點 walk-forward 驗證
「關鍵分點」(fetch_broker.key_brokers)是用全部 250 日算的:某券商在這檔進前 15 大買超後 10 日勝率 ≥60%、
平均 ≥ max(2%, 基準+1.5%) 就標「起漲分點」——全樣本內挑出來,沒驗證過會不會延續。
這裡每檔切成 訓練期(前 70%)/ 驗證期(後 30%),只用訓練期挑關鍵分點,再看它們在驗證期出手後的表現,
並和「訓練期也有出手、但沒被選為關鍵」的對照組比較。結果 → bk/_kb_validation.json,每檔 → cp 旁的 "kbv"。
"""
import json, statistics as st, datetime as dt


def _px(closes_of, sid):
    idx, C = closes_of(sid)
    ds = sorted(idx, key=lambda d: idx[d])
    return ds, C


MIN_ROWS = 60


def per_stock(e, ds, C):
    pos = {d: i for i, d in enumerate(ds)}
    rows = []
    for d, summ in zip(e.get("d") or [], e.get("s") or []):
        j = pos.get(d)
        if j is None or j + 10 >= len(C) or not C[j]: continue
        f10 = (C[j + 10] / C[j] - 1) * 100
        rows.append((d, ds[j + 10], f10, [x[0] for x in (summ.get("b") or [])], [x[0] for x in (summ.get("s") or [])]))
    if len(rows) < MIN_ROWS: return None
    cut = rows[int(len(rows) * 0.7)][0]
    tr = [r for r in rows if r[1] <= cut]                 # 訓練期:連 10 日後的價格都在切點前(不偷看)
    te = [r for r in rows if r[0] > cut]
    if len(tr) < 30 or len(te) < 15: return None
    base_tr = st.mean(r[2] for r in tr); base_te = st.mean(r[2] for r in te)
    out = {"cut": cut, "base_tr": round(base_tr, 2), "base_te": round(base_te, 2), "buy": [], "sell": [], "ctl_b": [], "ctl_s": []}
    for side, col in (("b", 3), ("s", 4)):
        ev = {}
        for r in tr:
            for nm in r[col]: ev.setdefault(nm, []).append(r[2])
        for nm, v in ev.items():
            if len(v) < 3: continue
            w = sum(1 for x in v if (x > 0 if side == "b" else x < 0)) / len(v) * 100; a = st.mean(v)
            key = (w >= 60 and a >= max(2.0, base_tr + 1.5)) if side == "b" else (w >= 60 and a <= min(-2.0, base_tr - 1.5))
            tv = [r[2] for r in te if nm in r[col]]
            item = [nm, len(v), round(a, 2), round(w), len(tv), round(st.mean(tv), 2) if tv else None,
                    round(sum(1 for x in tv if (x > 0 if side == "b" else x < 0)) / len(tv) * 100) if tv else None]
            if key: out["buy" if side == "b" else "sell"].append(item)
            else: out["ctl_" + side].append(item)
    return out


def build(R, S, closes_of, log=print, out_path="bk/_kb_validation.json"):
    agg = {k: [] for k in ("buy", "sell", "ctl_b", "ctl_s")}
    n_st = 0
    for k, sh in R.items():
        for sid, e in sh.items():
            try:
                ds, C = _px(closes_of, sid)
                v = per_stock(e, ds, C)
            except Exception:
                continue
            if not v: continue
            n_st += 1
            for key in agg:
                for it in v[key]:
                    if it[4]:                                  # 驗證期有出手
                        agg[key].append((it[5] - v["base_te"], it[6], it[4]))
            if k in S and sid in S[k]:
                S[k][sid]["kbv"] = {"cut": v["cut"], "base_tr": v["base_tr"], "base_te": v["base_te"],
                                    "buy": sorted(v["buy"], key=lambda x: -(x[4] or 0))[:8], "sell": sorted(v["sell"], key=lambda x: -(x[4] or 0))[:8]}

    def summ(L):
        if not L: return None
        ex = [x[0] for x in L]; hit = [x[1] for x in L if x[1] is not None]; w = [x[2] for x in L]
        wex = sum(x[0] * x[2] for x in L) / max(1, sum(w))
        return {"brokers": len(L), "events": sum(w), "excess_avg": round(st.mean(ex), 2), "excess_wavg": round(wex, 2),
                "excess_med": round(st.median(ex), 2), "hit_avg": round(st.mean(hit), 1) if hit else None,
                "pos_share": round(100 * sum(1 for x in ex if x > 0) / len(ex), 1)}
    res = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "stocks": n_st,
           "起漲分點(驗證期)": summ(agg["buy"]), "對照:一般買方券商": summ(agg["ctl_b"]),
           "出貨分點(驗證期)": summ(agg["sell"]), "對照:一般賣方券商": summ(agg["ctl_s"]),
           "說明": "excess=驗證期該券商出手後 10 日報酬 − 該檔驗證期任意日 10 日報酬;起漲分點應 >0 且明顯高於對照,出貨分點應 <0 且明顯低於對照"}
    try: json.dump(res, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception: pass
    b, cb, s_, cs = res["起漲分點(驗證期)"], res["對照:一般買方券商"], res["出貨分點(驗證期)"], res["對照:一般賣方券商"]
    log(f"  🔍 關鍵分點驗證:{n_st} 檔;起漲分點驗證期超額 {b and b['excess_avg']}%(對照 {cb and cb['excess_avg']}%);出貨分點 {s_ and s_['excess_avg']}%(對照 {cs and cs['excess_avg']}%)")
    return res
