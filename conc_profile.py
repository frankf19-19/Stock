"""r968:🧬 主力集中度個性——每檔個股「主力集中買賣之後,股價通常怎麼走」
=====================================================================
資料:分點原始摘要 bkraw(250 個交易日,前 15 大券商淨買賣 m15、成交張數 vol、前 15 大買/賣券商名單)
     + 收盤價(hist/ 三年收盤 ∪ k/ 近一年日 K)
指標:C5 = 近 5 日 m15 合計 ÷ 近 5 日成交量 ×100(%)——正=主力集中買超、負=主力集中賣超
方法(每檔獨立,walk-forward 驗證):
  ① 訓練期 = 前 70% 的日子:算 C5 與「之後 5 日報酬」的等級相關 ρ,以及「大買日(C5 ≥ 自己 80 分位)」與
     「大賣日(C5 ≤ 20 分位)」之後 5 日平均報酬的差(spread)
  ② 分類:ρ ≥ +0.15 且 spread ≥ +1% → 順勢型;ρ ≤ −0.15 且 spread ≤ −1% → 反指標型;其餘 → 不敏感
  ③ 驗證期 = 後 30% 的日子:沿用訓練期的門檻,看訊號日之後 5 日的方向是否符合分類(命中率)與 spread 是否同號
  ④ 驗證通過 = spread 同號且命中率 ≥ 55%(訊號 ≥ 5 次)
輸出:bk/tw<分片>.json 每檔加 "cp" 欄;bk/_conc_summary.json 全市場驗證統計(含隨機對照)
"""
import json, os, math, random, statistics as st

H_LIST = (1, 3, 5, 10, 20)


def _rank(a):
    o = sorted(range(len(a)), key=lambda i: a[i]); r = [0.0] * len(a)
    i = 0
    while i < len(o):                                   # 同值取平均名次
        j = i
        while j + 1 < len(o) and a[o[j + 1]] == a[o[i]]: j += 1
        for t in range(i, j + 1): r[o[t]] = (i + j) / 2
        i = j + 1
    return r


def spear(x, y):
    if len(x) < 8: return None
    rx, ry = _rank(x), _rank(y); mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def pct(a, q):
    a = sorted(a); return a[min(len(a) - 1, max(0, int(round(q * (len(a) - 1)))))]


_C = {}
def closes(sid, shard_key):
    """收盤序列:hist/(三年)∪ k/(近一年,較新者優先)→ {日期: 收盤}"""
    k = shard_key(sid)
    if k not in _C:
        h = {}; kk = {}
        try: h = json.load(open(f"hist/tw{k}.json", encoding="utf-8"))
        except Exception: pass
        try: kk = json.load(open(f"k/tw{k}.json", encoding="utf-8"))
        except Exception: pass
        _C[k] = (h, kk)
    h, kk = _C[k]; out = {}
    e = h.get(sid) or {}
    for d, c in zip(e.get("d") or [], e.get("c") or []):
        if c: out[d] = c
    e = kk.get(sid) or {}
    for d, o in zip(e.get("d") or [], e.get("o") or []):
        if o and len(o) >= 4 and o[3]: out[d] = o[3]
    return out


def series(e, px):
    """→ list of dict(day, C5, fw{h:ret%}, buyers[]),只留有價格的日子"""
    d, S = e.get("d") or [], e.get("s") or []
    days = sorted(px); pos = {x: i for i, x in enumerate(days)}
    m = [x.get("m15") or 0 for x in S]; v = [x.get("vol") or 0 for x in S]
    out = []
    for t in range(4, len(d)):
        vv = sum(v[t - 4:t + 1])
        if vv <= 0 or d[t] not in pos: continue
        i = pos[d[t]]; c0 = px[days[i]]
        fw = {h: ((px[days[i + h]] / c0 - 1) * 100 if i + h < len(days) else None) for h in H_LIST}
        out.append({"d": d[t], "C5": sum(m[t - 4:t + 1]) / vv * 100, "fw": fw,
                    "vol5": vv, "buy": [b[0] for b in (S[t].get("b") or [])[:5]], "sell": [b[0] for b in (S[t].get("s") or [])[:5]]})
    return out


def grp(rows, h):
    v = [r["fw"][h] for r in rows if r["fw"][h] is not None]
    if not v: return None
    return {"n": len(v), "avg": round(sum(v) / len(v), 2), "win": round(100 * sum(1 for x in v if x > 0) / len(v)),
            "med": round(st.median(v), 2)}


def profile(e, px, tags=None):
    R = series(e, px)
    R5 = [r for r in R if r["fw"][5] is not None]
    if len(R5) < 40: return {"type": "資料不足", "n": len(R5)}
    cut = int(len(R5) * 0.7); tr, te = R5[:cut], R5[cut:]
    C_tr = [r["C5"] for r in tr]
    hi, lo = pct(C_tr, 0.8), pct(C_tr, 0.2)
    rho_tr = spear(C_tr, [r["fw"][5] for r in tr])
    big_tr = [r for r in tr if r["C5"] >= hi]; sml_tr = [r for r in tr if r["C5"] <= lo]
    sp_tr = (sum(r["fw"][5] for r in big_tr) / len(big_tr) - sum(r["fw"][5] for r in sml_tr) / len(sml_tr)) if big_tr and sml_tr else 0
    if rho_tr is not None and rho_tr >= 0.15 and sp_tr >= 1: typ = "順勢型"
    elif rho_tr is not None and rho_tr <= -0.15 and sp_tr <= -1: typ = "反指標型"
    else: typ = "不敏感"
    # 驗證期:沿用訓練門檻
    big_te = [r for r in te if r["C5"] >= hi]; sml_te = [r for r in te if r["C5"] <= lo]
    sp_te = (sum(r["fw"][5] for r in big_te) / len(big_te) - sum(r["fw"][5] for r in sml_te) / len(sml_te)) if big_te and sml_te else None
    hit = n_sig = 0
    if typ != "不敏感":
        sgn = 1 if typ == "順勢型" else -1
        for r in big_te: n_sig += 1; hit += 1 if r["fw"][5] * sgn > 0 else 0
        for r in sml_te: n_sig += 1; hit += 1 if r["fw"][5] * sgn < 0 else 0
    hit_rate = round(100 * hit / n_sig) if n_sig else None
    passed = bool(typ != "不敏感" and sp_te is not None and n_sig >= 5 and hit_rate >= 55 and (sp_te > 0) == (typ == "順勢型"))
    # 全期間細節(給使用者看)
    allC = [r["C5"] for r in R5]
    HI, LO = pct(allC, 0.8), pct(allC, 0.2)
    big = [r for r in R if r["C5"] >= HI]; sml = [r for r in R if r["C5"] <= LO]
    det = {}
    for h in H_LIST:
        det[str(h)] = {"big": grp(big, h), "small": grp(sml, h), "all": grp(R, h)}
    best_h = None; best_v = 0
    for h in H_LIST:
        b, s_ = det[str(h)]["big"], det[str(h)]["small"]
        if b and s_ and abs(b["avg"] - s_["avg"]) > abs(best_v): best_v = b["avg"] - s_["avg"]; best_h = h
    # 五分位:C5 由低到高,之後 5 日平均
    srt = sorted(R5, key=lambda r: r["C5"]); q = len(srt) // 5; quint = []
    for i in range(5):
        seg = srt[i * q:(i + 1) * q] if i < 4 else srt[4 * q:]
        quint.append([round(sum(r["C5"] for r in seg) / len(seg), 1), round(sum(r["fw"][5] for r in seg) / len(seg), 2)])
    # 大買日是誰在買(出現次數最多的券商)
    cnt = {}
    for r in big:
        for b in r["buy"]: cnt[b] = cnt.get(b, 0) + 1
    drivers = []
    for b, c in sorted(cnt.items(), key=lambda x: -x[1])[:5]:
        t = (tags or {}).get(b) or {}
        drivers.append([b, c, t.get("tag")])
    cntS = {}
    for r in sml:
        for b in r["sell"]: cntS[b] = cntS.get(b, 0) + 1
    sellers = [[b, c, ((tags or {}).get(b) or {}).get("tag")] for b, c in sorted(cntS.items(), key=lambda x: -x[1])[:5]]
    last = R[-1] if R else None
    cur = None
    if last:
        p_now = round(100 * sum(1 for x in allC if x <= last["C5"]) / len(allC))
        cur = {"d": last["d"], "C5": round(last["C5"], 2), "pct": p_now,
               "zone": "大買" if last["C5"] >= HI else "大賣" if last["C5"] <= LO else "一般"}
    return {"type": typ, "passed": passed, "n": len(R5), "from": R5[0]["d"], "to": R[-1]["d"],
            "train": {"n": len(tr), "rho": round(rho_tr, 3) if rho_tr is not None else None, "spread": round(sp_tr, 2),
                      "hi": round(hi, 2), "lo": round(lo, 2), "to": tr[-1]["d"]},
            "test": {"n": len(te), "spread": round(sp_te, 2) if sp_te is not None else None, "sig": n_sig, "hit": hit_rate, "from": te[0]["d"]},
            "rho": {str(h): (round(spear([r["C5"] for r in R if r["fw"][h] is not None], [r["fw"][h] for r in R if r["fw"][h] is not None]) or 0, 3)) for h in (5, 10, 20)},
            "hi": round(HI, 2), "lo": round(LO, 2), "det": det, "best_h": best_h, "quint": quint,
            "drivers": drivers, "sellers": sellers, "cur": cur}


def build(R, S, shard_key, log=print, out_summary="bk/_conc_summary.json"):
    try: tags = json.load(open("broker_tags.json", encoding="utf-8"))
    except Exception: tags = {}
    stats = {"順勢型": [0, 0], "反指標型": [0, 0], "不敏感": [0, 0], "資料不足": [0, 0]}
    hits = []; n_ok = 0; null_pass = []
    for k, sh in R.items():
        for sid, e in sh.items():
            try:
                px = closes(sid, shard_key)
                if len(px) < 60: continue
                cp = profile(e, px, tags)
            except Exception as ex:
                continue
            if k in S and sid in S[k]: S[k][sid]["cp"] = cp
            t = cp.get("type"); stats.setdefault(t, [0, 0]); stats[t][0] += 1; stats[t][1] += 1 if cp.get("passed") else 0
            if cp.get("test", {}).get("hit") is not None: hits.append(cp["test"]["hit"])
            n_ok += 1
            # 隨機對照:把報酬序列循環位移後同樣分類+驗證,估計「純巧合會通過」的比例
            try:
                if random.random() < 0.25:
                    days = sorted(px); vals = [px[d] for d in days]; sh_ = random.randint(30, max(31, len(vals) - 30))
                    vals = vals[sh_:] + vals[:sh_]; fake = dict(zip(days, vals))
                    null_pass.append(1 if profile(e, fake, None).get("passed") else 0)
            except Exception: pass
    summ = {"updated": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"), "stocks": n_ok,
            "types": {t: {"n": v[0], "passed": v[1]} for t, v in stats.items()},
            "test_hit_avg": round(sum(hits) / len(hits), 1) if hits else None,
            "null_pass_rate": round(100 * sum(null_pass) / len(null_pass), 1) if null_pass else None,
            "real_pass_rate": round(100 * sum(v[1] for v in stats.values()) / max(1, n_ok), 1)}
    try: json.dump(summ, open(out_summary, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception: pass
    log(f"  🧬 集中度個性:{n_ok} 檔;" + "、".join(f"{t} {v[0]}(驗證通過 {v[1]})" for t, v in stats.items()) +
        f";驗證命中率平均 {summ['test_hit_avg']}%;實際通過率 {summ['real_pass_rate']}% vs 隨機對照 {summ['null_pass_rate']}%")
    return summ
