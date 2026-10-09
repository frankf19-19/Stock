"""分點(券商買賣明細)每日摘要 + 八大行庫 → bk/tw<分片>.json、gov.json
======================================================================
FinMind Sponsor:TaiwanStockTradingDailyReport(每檔每日各券商買賣)、TaiwanStockGovernmentBankBuySell(八大行庫)。
分點是台股最有效的籌碼訊號:主力分點連買、隔日沖券商進場、買賣家數差。每天收盤後對全市場每檔各打一次
(約 2,100 次,Sponsor 6,000/小時),存「摘要」不存明細(明細一天幾十 MB):
  s = {b:[[券商,淨買張,均價]×5], s:[[券商,淨賣張,均價]×5], nb:淨買家數, ns:淨賣家數,
       m15:前 15 大淨買賣張(主力淨額), conc:前 15 大|淨額|合計 ÷ 成交張(集中度), vol:成交張,
       dt:[隔日沖券商](昨天前五大買、今天前五大賣), bp:買方均價, sp:賣方均價}
每檔保留 60 日。狀態檔 bk/_state.json 記「哪一天做到哪」,超時下一輪接著做。
"""
import json, os, glob, time, datetime as dt
import requests

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
API = "https://api.finmindtrade.com/api/v4/data"
DIR = "bk"; KEEP = 60                                         # repo 內顯示用:60 日
RAW = "bkraw"; KEEP_RAW = 250                                 # r838:原始摘要 250 日,放 Actions cache(不進 repo),關鍵分點統計用
BUDGET_SEC = int(os.environ.get("BK_BUDGET_SEC", "3000"))     # 一輪最多 50 分鐘(r803:45 分鐘只抓到 1,925/2,100)
SLEEP = 1.1                                                    # r820:雙線程,每線程 1.1s ≈ 合計 5,000/小時以內
THREADS = 2


def log(*a): print(*a, flush=True)


def shard_key(sid):
    t = str(sid); return t[:3] if t[:2] == "00" else t[:2]


def fm(dataset, **p):
    p = {"dataset": dataset, "token": TOKEN, **p}
    r = requests.get(API, params=p, timeout=60)
    j = r.json()
    if r.status_code != 200 or j.get("status") not in (200, None) and j.get("msg") != "success":
        raise RuntimeError(f"{dataset} {r.status_code} {str(j.get('msg'))[:80]}")
    return j.get("data") or []


def last_trade_day():
    """以台積電日 K 最後一天為準(update_data.py 已先跑)。"""
    try:
        e = json.load(open("k/tw23.json", encoding="utf-8")).get("2330") or {}
        return (e.get("d") or [])[-1]
    except Exception:
        d = NOW.date()
        while d.weekday() >= 5: d -= dt.timedelta(days=1)
        return d.isoformat()


def summarize(rows, prev):
    """rows = 該檔該日各券商明細;prev = 前一日摘要(算隔日沖)。"""
    agg = {}
    for r in rows:
        name = str(r.get("securities_trader") or r.get("securities_trader_id") or "?")
        b = float(r.get("buy") or 0); s = float(r.get("sell") or 0); px = float(r.get("price") or 0)
        a = agg.setdefault(name, [0.0, 0.0, 0.0, 0.0])           # buy 股, sell 股, buy$,sell$
        a[0] += b; a[1] += s; a[2] += b * px; a[3] += s * px
    if not agg: return None
    items = []
    for name, (b, s, bm, sm) in agg.items():
        net = (b - s) / 1000
        items.append((name, net, (bm / b if b else 0), (sm / s if s else 0), b, s))
    items.sort(key=lambda x: -x[1])
    vol = max(sum(x[4] for x in items), sum(x[5] for x in items)) / 1000
    top15 = sorted(items, key=lambda x: -abs(x[1]))[:15]
    buys = [x for x in items if x[1] > 0][:15]                          # r804:存前 15 大(關鍵分點分析要用;前端只顯示前五)
    sells = [x for x in sorted(items, key=lambda x: x[1]) if x[1] < 0][:15]
    tb = sum(x[4] for x in items); ts = sum(x[5] for x in items)
    bp = sum(x[4] * x[2] for x in items) / tb if tb else None
    sp = sum(x[5] * x[3] for x in items) / ts if ts else None
    dtl = []
    if prev and prev.get("b"):
        pb = set(x[0] for x in prev["b"])
        dtl = [x[0] for x in sells if x[0] in pb]
    return {"b": [[x[0], round(x[1]), round(x[2], 2)] for x in buys],
            "s": [[x[0], round(x[1]), round(x[3], 2)] for x in sells],
            "nb": sum(1 for x in items if x[1] > 0), "ns": sum(1 for x in items if x[1] < 0),
            "m15": round(sum(x[1] for x in top15)), "conc": round(sum(abs(x[1]) for x in top15) / vol * 100, 1) if vol else None,
            "vol": round(vol), "dt": dtl, "bp": round(bp, 2) if bp else None, "sp": round(sp, 2) if sp else None}


# ═══ r804:關鍵分點——這檔「誰買之後會漲、誰賣之後會跌」═══
# 對每檔:每家券商出現在「當日淨買前 15」的日子 → 之後 5/10 日報酬;出現在「淨賣前 15」→ 之後 5/10 日報酬。
# 進場次數 ≥ 3 才列;起漲分點 = 買後 10 日勝率 ≥ 60% 且平均 ≥ +2%;出貨分點 = 賣後 10 日平均 ≤ −2% 且「跌」的比率 ≥ 60%。
_K = {}
_H = {}
def closes_of(sid):
    """r969:hist/(三年收盤)∪ k/(近一年日 K,較新者優先)——hist 停在 9/11 沒更新,舊版只用 hist 會讓之後的分點日全部找不到後續報酬"""
    k = shard_key(sid)
    if k not in _H:
        try: _H[k] = json.load(open(f"hist/tw{k}.json", encoding="utf-8"))
        except Exception: _H[k] = {}
    if k not in _K:
        try: _K[k] = json.load(open(f"k/tw{k}.json", encoding="utf-8"))
        except Exception: _K[k] = {}
    m = {}
    h = _H[k].get(sid) or {}
    for dd, c in zip(h.get("d") or [], h.get("c") or []):
        if c: m[dd] = c
    e = _K[k].get(sid) or {}
    for dd, o in zip(e.get("d") or [], e.get("o") or []):
        if o and len(o) >= 4 and o[3]: m[dd] = o[3]
    ds = sorted(m)
    return {dd: i for i, dd in enumerate(ds)}, [m[dd] for dd in ds]


def key_brokers(e, sid):
    idx, C = closes_of(sid)
    if not C or len(e.get("d") or []) < 15: return None
    # 基準:這段期間任意一天之後 5/10 日的平均報酬(券商要贏過它才算關鍵,否則多頭股裡人人都是先知)
    js = [idx[d] for d in e["d"] if d in idx]
    b5 = [(C[j + 5] / C[j] - 1) * 100 for j in js if j + 5 < len(C)]; b10 = [(C[j + 10] / C[j] - 1) * 100 for j in js if j + 10 < len(C)]
    base5 = sum(b5) / len(b5) if b5 else 0.0; base10 = sum(b10) / len(b10) if b10 else 0.0
    stat = {}
    for day, summ in zip(e["d"], e["s"]):
        j = idx.get(day)
        if j is None: continue
        f5 = (C[j + 5] / C[j] - 1) * 100 if j + 5 < len(C) else None
        f10 = (C[j + 10] / C[j] - 1) * 100 if j + 10 < len(C) else None
        # r829:時間軸——之後 1/3/5/10/20 日報酬、幾天到高點/低點、第幾天開始漲/跌
        fw = {h: ((C[j + h] / C[j] - 1) * 100 if j + h < len(C) else None) for h in (1, 3, 5, 10, 20)}
        path = [(C[j + k] / C[j] - 1) * 100 for k in range(1, 21) if j + k < len(C)]
        dpk = (path.index(max(path)) + 1) if path else None; dtr = (path.index(min(path)) + 1) if path else None
        d_up = next((k + 1 for k, v in enumerate(path) if v > 0), None); d_dn = next((k + 1 for k, v in enumerate(path) if v < 0), None)
        vol = summ.get("vol") or 0
        for side, rows in (("b", summ.get("b") or []), ("s", summ.get("s") or [])):
            for name, net, px in rows:
                st = stat.setdefault((side, name), {"n": 0, "s5": 0.0, "n5": 0, "w5": 0, "s10": 0.0, "n10": 0, "w10": 0, "last": day, "lots": 0, "ev": []})
                st["n"] += 1; st["last"] = max(st["last"], day); st["lots"] += abs(net)
                share = (abs(net) / vol * 100) if vol else 0.0                      # r826:這次佔當日成交的 %(量大小)
                st["ev"].append((share, f10))
                st.setdefault("evx", []).append({"lots": abs(net), "share": share, "fw": fw, "dpk": dpk, "dtr": dtr, "d_up": d_up, "d_dn": d_dn, "d": day})
                if f5 is not None: st["s5"] += f5; st["n5"] += 1; st["w5"] += 1 if (f5 > 0 if side == "b" else f5 < 0) else 0
                if f10 is not None: st["s10"] += f10; st["n10"] += 1; st["w10"] += 1 if (f10 > 0 if side == "b" else f10 < 0) else 0
    out = {"b": [], "s": [], "x": {}}
    def med(a):
        a = sorted(x for x in a if x is not None); return a[len(a) // 2] if a else None
    def size_curve(side, evx):
        """張數 → 成績:三分位 + 有效門檻(最小張數,使得 ≥ 它的樣本 10 日勝率 ≥60%、平均贏過基準)+ 時間軸。"""
        good = lambda f: (f > 0) if side == "b" else (f < 0)
        ev = [e for e in evx if e["fw"][10] is not None]
        if len(ev) < 3: return None
        ev.sort(key=lambda e: e["lots"])
        k = len(ev); cuts = [ev[:k // 3] or ev[:1], ev[k // 3: 2 * k // 3] or ev[:1], ev[2 * k // 3:] or ev[-1:]]
        tiers = []
        for grp in cuts:
            a = sum(e["fw"][10] for e in grp) / len(grp); w = round(100 * sum(1 for e in grp if good(e["fw"][10])) / len(grp))
            tiers.append([int(min(e["lots"] for e in grp)), int(max(e["lots"] for e in grp)), len(grp), round(a, 2), w])
        eff = None
        for i in range(len(ev)):
            sub = ev[i:]
            if len(sub) < 3: break
            a = sum(e["fw"][10] for e in sub) / len(sub); w = 100 * sum(1 for e in sub if good(e["fw"][10])) / len(sub)
            ok = (w >= 60 and a >= max(2.0, base10 + 1.5)) if side == "b" else (w >= 60 and a <= min(-2.0, base10 - 1.5))
            if ok: eff = {"lots": int(ev[i]["lots"]), "share": round(ev[i]["share"], 2), "n": len(sub), "a10": round(a, 2), "w10": round(w)}; break
        hz = {}
        for h in (1, 3, 5, 10, 20):
            vals = [e["fw"][h] for e in ev if e["fw"][h] is not None]
            if vals: hz[str(h)] = [round(sum(vals) / len(vals), 2), round(100 * sum(1 for v in vals if good(v)) / len(vals)), len(vals)]
        best = max(hz.items(), key=lambda kv: (kv[1][0] if side == "b" else -kv[1][0])) if hz else None
        return {"tiers": tiers, "eff": eff, "hz": hz, "best_h": int(best[0]) if best else None,
                "d_start": med([e["d_up" if side == "b" else "d_dn"] for e in ev]), "d_peak": med([e["dpk" if side == "b" else "dtr"] for e in ev])}
    for (side, name), st in stat.items():
        if st["n10"] < 3: continue
        try:
            xc = size_curve(side, st.get("evx") or [])
            if xc: out["x"][side + ":" + name] = xc
        except Exception: pass
        a5 = st["s5"] / st["n5"] if st["n5"] else None; a10 = st["s10"] / st["n10"]
        w5 = round(100 * st["w5"] / st["n5"]) if st["n5"] else None; w10 = round(100 * st["w10"] / st["n10"])
        # r826:量的維度——典型佔比(中位)、大買/大賣(≥ 自己中位且 ≥2%)的 10 日成績
        shares = sorted(x[0] for x in st["ev"]); med_share = shares[len(shares) // 2] if shares else 0.0
        thr = max(2.0, med_share)
        big = [f for sh, f in st["ev"] if sh >= thr and f is not None]
        n_big = len(big); a10_big = (sum(big) / n_big) if n_big else None
        w10_big = round(100 * sum(1 for f in big if (f > 0 if side == "b" else f < 0)) / n_big) if n_big else None
        # 關鍵判定:大買樣本 ≥3 用大買成績,否則用全部
        ua, uw = (a10_big, w10_big) if n_big >= 3 else (a10, w10)
        key = (uw >= 60 and ua >= max(2.0, base10 + 1.5)) if side == "b" else (uw >= 60 and ua <= min(-2.0, base10 - 1.5))
        out[side].append([name, st["n"], round(a5, 2) if a5 is not None else None, w5, round(a10, 2), w10, st["last"], 1 if key else 0, st["lots"],
                          round(med_share, 2), n_big, round(a10_big, 2) if a10_big is not None else None, w10_big, round(thr, 2)])
    # 排序:關鍵優先,再依 10 日平均 × 勝率
    out["b"].sort(key=lambda x: (-x[7], -(x[4] * x[5])))
    out["s"].sort(key=lambda x: (-x[7], (x[4] * x[5])))
    keep = set(x[0] for x in out["b"][:8]) | set(x[0] for x in out["s"][:8])
    xo = {k: v for k, v in out["x"].items() if k.split(":", 1)[1] in keep}
    try: prof = broker_profiles(e, sid, out)
    except Exception: prof = {}
    return {"b": out["b"][:8], "s": out["s"][:8], "x": xo, "p": prof, "days": len(e["d"]), "base5": round(base5, 2), "base10": round(base10, 2)}


_TAGS = None
def broker_profiles(e, sid, out):
    """r841:這檔的分點生態——每家券商在這檔的角色:持有天數(FIFO)、隔日沖率、專門度、淨累積、買/賣後 10 日。"""
    global _TAGS
    if _TAGS is None:
        try: _TAGS = json.load(open("broker_tags.json", encoding="utf-8"))
        except Exception: _TAGS = {}
    d, S = e["d"], e["s"]; n = len(d)
    ev = {}                                                  # name → list of (i, net) 只含前 15 大出現
    for i, summ in enumerate(S):
        for nm, net, px in (summ.get("b") or []): ev.setdefault(nm, []).append((i, net))
        for nm, net, px in (summ.get("s") or []): ev.setdefault(nm, []).append((i, net))
    keyb = {x[0]: x for x in out["b"] if x[7]}; keys_ = {x[0]: x for x in out["s"] if x[7]}
    allb = {x[0]: x for x in out["b"]}; alls = {x[0]: x for x in out["s"]}
    FOREIGN = ("美商", "港商", "港麥", "瑞銀", "摩根", "美林", "花旗", "法銀", "德意志", "野村", "大和", "高盛", "巴克萊", "麥格理", "匯豐", "瑞士信貸", "法國巴黎", "新加坡")
    prof = {}
    for nm, lst in ev.items():
        if len(lst) < 3: continue
        lst.sort()
        buys = [(i, v) for i, v in lst if v > 0]; sells = [(i, -v) for i, v in lst if v < 0]
        lb = sum(v for _, v in buys); ls = sum(v for _, v in sells)
        # 隔日沖率:買超日的下一個交易日出現在賣超
        sell_days = set(i for i, _ in sells); dt = sum(1 for i, _ in buys if (i + 1) in sell_days)
        dtr = dt / len(buys) if buys else 0.0
        # FIFO 持有天數
        q = []; held = 0.0; matched = 0
        for i, v in sorted(buys + [(i, -v) for i, v in sells]):
            if v > 0: q.append([i, v])
            else:
                need = -v
                while need > 0 and q:
                    j, rem = q[0]; take = min(rem, need); held += take * (i - j); matched += take; need -= take; q[0][1] -= take
                    if q[0][1] <= 0: q.pop(0)
        hold = held / matched if matched else None
        still = sum(rem for _, rem in q)
        tot = (_TAGS.get(nm) or {}).get("lots") or 0; spec = (lb + ls) / tot * 100 if tot else None
        net = lb - ls
        kb_ = keyb.get(nm); ks_ = keys_.get(nm)
        if any(f in nm for f in FOREIGN): role = "外資"
        elif kb_ and (spec is None or spec >= 10 or lb >= 0.5 * max(1, lb + ls)): role = "拉抬主力"
        elif ks_: role = "出貨主力"
        elif dtr >= 0.35: role = "隔日沖"
        elif hold is not None and hold <= 10: role = "短線"
        elif hold is not None and hold <= 40: role = "波段"
        elif (hold is None and still > 0 and net > 0) or (hold is not None and hold > 40): role = "長線"
        else: role = "一般"
        prof[nm] = {"role": role, "n": len(lst), "lb": int(lb), "ls": int(ls), "net": int(net), "dt": round(dtr * 100), "hold": round(hold, 1) if hold is not None else None,
                    "still": int(still), "spec": round(spec, 1) if spec is not None else None,
                    "a10b": allb[nm][4] if nm in allb else None, "w10b": allb[nm][5] if nm in allb else None,
                    "a10s": alls[nm][4] if nm in alls else None, "w10s": alls[nm][5] if nm in alls else None, "last": d[lst[-1][0]]}
    top = sorted(prof.items(), key=lambda kv: -(kv[1]["lb"] + kv[1]["ls"]))[:14]
    return dict(top)


def load_shards(d=None):
    d = d or DIR; os.makedirs(d, exist_ok=True)
    S = {}
    for p in glob.glob(os.path.join(d, "tw*.json")):
        try: S[os.path.basename(p)[2:-5]] = json.load(open(p, encoding="utf-8"))
        except Exception: pass
    return S


def save_shards(S, d=None):
    d = d or DIR; os.makedirs(d, exist_ok=True)
    for k, sh in S.items():
        json.dump(sh, open(os.path.join(d, f"tw{k}.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


def raw_load():
    """r838:原始 250 日摘要(Actions cache)。cache 掉了就以 repo 的 60 日當種子。"""
    R = load_shards(RAW)
    if not R:
        R = load_shards(DIR); log("  bkraw 不存在,以 bk/ 60 日當種子")
        for sh in R.values():
            for e in sh.values(): e.pop("kb", None)
    return R


def raw_put(R, sid, day, summ):
    k = shard_key(sid); e = R.setdefault(k, {}).setdefault(sid, {"d": [], "s": []})
    if day in e["d"]:
        e["s"][e["d"].index(day)] = summ
    else:
        e["d"].append(day); e["s"].append(summ)
        order = sorted(range(len(e["d"])), key=lambda i: e["d"][i])
        e["d"] = [e["d"][i] for i in order][-KEEP_RAW:]; e["s"] = [e["s"][i] for i in order][-KEEP_RAW:]


def raw_to_display(R, S):
    """把 raw 最近 60 日同步到 repo 的 bk/(顯示用),kb 由 raw 算。"""
    for k, sh in R.items():
        for sid, e in sh.items():
            d = S.setdefault(k, {}).setdefault(sid, {"d": [], "s": []})
            d["d"] = e["d"][-KEEP:]; d["s"] = e["s"][-KEEP:]


def gov_banks(day):
    """八大行庫:{sid: 淨買張};date-only 查詢。"""
    rows = fm("TaiwanStockGovernmentBankBuySell", start_date=day, end_date=day)
    out = {}
    for r in rows:
        sid = str(r.get("stock_id") or "")
        b = float(r.get("buy") or 0); s = float(r.get("sell") or 0)
        if sid: out[sid] = out.get(sid, 0) + round((b - s) / 1000)
    return out


LOOKBACK = 6        # r957:每班都回頭檢查最近 6 個交易日的缺口
MAX_TRIES = 4       # 有成交卻回空 → 最多再試 4 班(FinMind 傍晚陸續上架,早抓會拿到空的)


def recent_days(day, n):
    try:
        ds = [d for d in (json.load(open("k/tw23.json", encoding="utf-8")).get("2330") or {}).get("d") or [] if d <= day]
        return ds[-n:] if ds else [day]
    except Exception:
        return [day]


_KV = {}
def traded(sid, d):
    """這檔這天有沒有成交(日 K 有棒且量 > 0);查不到就當有,照樣去抓"""
    k = shard_key(sid)
    if k not in _KV:
        try: _KV[k] = json.load(open(f"k/tw{k}.json", encoding="utf-8"))
        except Exception: _KV[k] = {}
    e = _KV[k].get(sid)
    if not e or not e.get("d"): return True
    if d < e["d"][0]: return True
    try:
        i = e["d"].index(d)
    except ValueError:
        return False                                         # 這天沒有 K 棒 = 停牌/未上市
    b = e["o"][i] if i < len(e.get("o") or []) else None
    return bool(b and len(b) >= 5 and (b[4] or 0) > 0)


def has_raw(R, sid, d):
    e = (R.get(shard_key(sid)) or {}).get(sid)
    return bool(e and d in (e.get("d") or []))


def prev_summ(R, sid, d):
    e = (R.get(shard_key(sid)) or {}).get(sid) or {}
    best = None
    for dd, ss in zip(e.get("d") or [], e.get("s") or []):
        if dd < d and (best is None or dd > best[0]): best = (dd, ss)
    return best[1] if best else None


def main():
    """r957 改版:
    舊版:狀態檔只記「今天」,抓過就標記完成——FinMind 傍晚分批上架,16:40 先抓到的大量空回應也被當完成,
          隔天狀態歸零、前一天永遠不補 → 9/29 只剩 63%、9/30 56%、10/02 86% 的股票有分點。
    新版:①有成交卻回空的不算完成,下一班再試(最多 MAX_TRIES 班);②每班回頭檢查最近 LOOKBACK 個交易日,
          以「raw 裡實際有沒有那天的資料」判斷缺口(不信狀態檔),先補今天再補舊的。"""
    if not TOKEN: log("未設 FINMIND_TOKEN"); return
    day = last_trade_day()
    st_p = os.path.join(DIR, "_state.json"); os.makedirs(DIR, exist_ok=True)
    try: st = json.load(open(st_p, encoding="utf-8"))
    except Exception: st = {}
    tries = st.get("tries") if isinstance(st.get("tries"), dict) else {}
    days = recent_days(day, LOOKBACK)
    tries = {d: v for d, v in tries.items() if d in days}
    try: data = json.load(open("data.json", encoding="utf-8"))
    except Exception: log("沒有 data.json"); return
    ids = [s["id"] for s in data.get("stocks") or [] if s.get("market") == "TW" and not s.get("etf")]
    S = load_shards(); R = raw_load()
    try:                                                     # r1051c:🕵️ 波段主力分點先算(抓資料前)——收尾的後處理常被 timeout 砍掉
        import bk_swing; bk_swing.build(R, S, closes_of, log); save_shards(S)
    except Exception as ex0: log(f"  波段主力分點失敗:{ex0}")
    t0 = time.time(); n = 0; empty = 0; fail = 0
    # ── 八大行庫(當天一次)──
    if st.get("gov_day") != day and not (st.get("date") == day and st.get("gov")):
        try:
            g = gov_banks(day)
            try: G = json.load(open("gov.json", encoding="utf-8"))
            except Exception: G = {"d": [], "s": {}}
            if day not in G["d"]:
                G["d"].append(day); G["d"] = G["d"][-KEEP:]
                for sid, v in g.items():
                    e = G["s"].setdefault(sid, {"d": [], "v": []}); e["d"].append(day); e["v"].append(v)
                    e["d"] = e["d"][-KEEP:]; e["v"] = e["v"][-KEEP:]
                top = sorted(g.items(), key=lambda x: -x[1])
                G["top"] = {"d": day, "buy": top[:10], "sell": sorted(g.items(), key=lambda x: x[1])[:10], "net_all": sum(g.values())}
                json.dump(G, open("gov.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
            st["gov_day"] = day; log(f"  八大行庫 {day}:{len(g)} 檔,全市場淨 {sum(g.values()):+,} 張")
        except Exception as e:
            log(f"  八大行庫失敗:{e}")
    # ── 缺口清單:今天優先,其餘由近到遠 ──
    tasks = []; cov = {}
    for d in [day] + [x for x in reversed(days) if x != day]:
        tr = tries.setdefault(d, {})
        need = [sid for sid in ids if not has_raw(R, sid, d) and traded(sid, d) and tr.get(sid, 0) < MAX_TRIES]
        have = sum(1 for sid in ids if has_raw(R, sid, d))
        cov[d] = have
        tasks += [(d, sid) for sid in need]
    log("分點缺口:" + "、".join(f"{d[5:]} 有 {cov[d]}/{len(ids)}" for d in sorted(cov)) + f";本班待抓 {len(tasks)} 筆(上限 {BUDGET_SEC//60} 分鐘,{THREADS} 線程)")
    from concurrent.futures import ThreadPoolExecutor
    def one(task):
        d, sid = task
        try:
            r = fm("TaiwanStockTradingDailyReport", data_id=sid, start_date=d, end_date=d); time.sleep(SLEEP); return task, r, None
        except Exception as e:
            time.sleep(2); return task, None, e
    ex = ThreadPoolExecutor(max_workers=THREADS)
    pending = []; it = iter(tasks); got = {}
    def submit_next():
        try: pending.append(ex.submit(one, next(it))); return True
        except StopIteration: return False
    for _ in range(THREADS): submit_next()
    while pending:
        f = pending.pop(0); (d, sid), rows, err = f.result()
        if time.time() - t0 <= BUDGET_SEC: submit_next()
        elif not pending: log("  時間到,下一輪接著抓")
        if err is not None:
            fail += 1
            if fail <= 3: log(f"  {sid}@{d} 失敗:{err}")
            if fail >= 20: log("  連續失敗太多,停"); break
            continue
        try:                                                     # r1053:全部券商(不只前 15 大)→ bkraw/days/
            import bkall; bkall.put_day(sid, d, rows)
        except Exception: pass
        summ = summarize(rows, prev_summ(R, sid, d))
        if summ is None:
            empty += 1; tries[d][sid] = tries[d].get(sid, 0) + 1          # 有成交卻沒資料 → 下一班再試
        else:
            raw_put(R, sid, d, summ); got[d] = got.get(d, 0) + 1
        n += 1
        if n % 200 == 0:
            st["tries"] = tries; json.dump(st, open(st_p, "w"), ensure_ascii=False); save_shards(R, RAW)
            try: import bkall; bkall.flush_days()
            except Exception: pass
            log(f"  進度 {n}/{len(tasks)}({int(time.time()-t0)}s)")
    ex.shutdown(wait=False)
    st.update({"date": day, "tries": tries, "cov": {d: cov[d] + got.get(d, 0) for d in cov}, "ids": len(ids)})
    st.pop("done", None)
    json.dump(st, open(st_p, "w"), ensure_ascii=False)
    save_shards(R, RAW); raw_to_display(R, S)
    try: import bkall; bkall.flush_days()
    except Exception as e0: log(f"  全券商暫存失敗:{e0}")
    # r804:關鍵分點(有 15 天以上才算);r838:用 raw 250 日算,寫進 repo 的 60 日分片
    nk = 0
    for k, sh in R.items():
        for sid, e in sh.items():
            try:
                kb = key_brokers(e, sid)
                if kb: S[k][sid]["kb"] = kb; nk += 1
            except Exception: pass
    try: broker_tags(R)
    except Exception as ex2: log(f"  券商標籤失敗:{ex2}")
    try:                                                     # r968:🧬 主力集中度個性(每檔 250 日,walk-forward 驗證)
        import conc_profile; conc_profile.build(R, S, shard_key, log)
    except Exception as ex3: log(f"  集中度個性失敗:{ex3}")
    try:                                                     # r969:🔍 關鍵分點 walk-forward 驗證
        import kb_validate; kb_validate.build(R, S, closes_of, log)
    except Exception as ex4: log(f"  關鍵分點驗證失敗:{ex4}")
    try:                                                     # r1051:🕵️ 波段主力分點(低檔吃貨、高檔出貨)+ walk-forward 驗證
        import bk_swing; bk_swing.build(R, S, closes_of, log)
    except Exception as ex5: log(f"  波段主力分點失敗:{ex5}")
    save_shards(S)
    try: kb_today(S, day)
    except Exception as e: log(f"  kb_today 失敗:{e}")
    log(f"✅ 分點:本輪抓 {n} 筆(補進 {sum(got.values())}、仍空 {empty}、失敗 {fail});覆蓋 " +
        "、".join(f"{d[5:]} {st['cov'][d]}/{len(ids)}" for d in sorted(st["cov"])) + f";關鍵分點已算 {nk} 檔")


def broker_tags(R):
    """r838:券商屬性——從全市場 raw 推:隔日沖率(今天前 15 買、明天前 15 賣的比例)、出現檔數、平均連續天數、外資窗口(名稱)。
       tag:外資 / 隔日沖 / 短線 / 波段 / 一般。→ broker_tags.json"""
    st = {}
    for k, sh in R.items():
        for sid, e in sh.items():
            d, S = e.get("d") or [], e.get("s") or []
            for i, summ in enumerate(S):
                nb = set(x[0] for x in (summ.get("b") or [])); ns_next = set(x[0] for x in (S[i + 1].get("s") or [])) if i + 1 < len(S) else set()
                for nm, net, px in (summ.get("b") or []) + (summ.get("s") or []):
                    st.setdefault(nm, {"app": 0, "dt": 0, "stocks": set(), "runs": [], "cur": 0, "lots": 0})["lots"] += abs(net)
                for nm in nb:
                    t = st.setdefault(nm, {"app": 0, "dt": 0, "stocks": set(), "runs": [], "cur": 0, "lots": 0})
                    t["app"] += 1; t["stocks"].add(sid)
                    if nm in ns_next: t["dt"] += 1
            # 連續天數(同檔連續在買超前 15)
            names = set()
            for summ in S: names |= set(x[0] for x in (summ.get("b") or []))
            for nm in names:
                run = 0
                for summ in S:
                    if any(x[0] == nm for x in (summ.get("b") or [])): run += 1
                    else:
                        if run: st[nm]["runs"].append(run); run = 0
                if run: st[nm]["runs"].append(run)
    FOREIGN = ("美商", "港商", "港麥", "瑞銀", "摩根", "美林", "花旗", "法銀", "德意志", "野村", "大和", "台灣摩根", "高盛", "巴克萊", "麥格理", "匯豐", "瑞士信貸", "法國巴黎", "新加坡")
    out = {}
    _dl = sorted(len(e.get("d") or []) for sh in R.values() for e in sh.values())
    ndays = _dl[len(_dl) // 2] if _dl else 0                    # r846:用全市場中位數,不被少數有 60 天的優先股帶高
    for nm, t in st.items():
        if t["app"] < 20: continue
        dtr = t["dt"] / t["app"]; avg_run = (sum(t["runs"]) / len(t["runs"])) if t["runs"] else 1
        if ndays < 60:                                            # r841:資料不足 60 天,只標外資、其餘不貼標
            tag = "外資" if any(f in nm for f in FOREIGN) else None
            out[nm] = {"tag": tag, "dt": round(dtr * 100), "n": t["app"], "stocks": len(t["stocks"]), "run": round(avg_run, 1), "lots": int(t["lots"])}; continue
        if any(f in nm for f in FOREIGN): tag = "外資"
        elif dtr >= 0.35: tag = "隔日沖"
        elif dtr >= 0.2 or avg_run < 1.5: tag = "短線"
        elif avg_run >= 3: tag = "波段"
        else: tag = "一般"
        out[nm] = {"tag": tag, "dt": round(dtr * 100), "n": t["app"], "stocks": len(t["stocks"]), "run": round(avg_run, 1), "lots": int(t["lots"])}
    json.dump(out, open("broker_tags.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    from collections import Counter
    log(f"  券商標籤:{len(out)} 家 {dict(Counter(v['tag'] for v in out.values()))}")


def kb_today(S, day):
    """r827:全市場「今天關鍵分點大買/大賣」清單 → kb_today.json(個股分頁機會雷達用,不只最愛)。"""
    buy, sell = [], []
    for k, sh in S.items():
        for sid, e in sh.items():
            kb = e.get("kb"); d = e.get("d") or []
            if not kb or not d or d[-1] != day: continue
            last = e["s"][-1]; vol = last.get("vol") or 0
            def pick(side, rows):
                keyset = {x[0]: x for x in (kb.get(side) or []) if x[7]}
                out = []
                for name, net, px in rows:
                    x = keyset.get(name)
                    if not x: continue
                    share = abs(net) / vol * 100 if vol else 0.0
                    thr = x[13] if len(x) > 13 and x[13] is not None else 2.0
                    if share < thr: continue
                    a10 = x[11] if len(x) > 11 and x[10] >= 3 and x[11] is not None else x[4]
                    w10 = x[12] if len(x) > 12 and x[10] >= 3 and x[12] is not None else x[5]
                    out.append([name, net, round(share, 1), (x[9] if len(x) > 9 else None), x[1], a10, w10])
                return out
            b = pick("b", last.get("b") or []); x_ = pick("s", last.get("s") or [])
            if b: buy.append({"id": sid, "br": b, "m15": last.get("m15"), "vol": vol})
            if x_: sell.append({"id": sid, "br": x_, "m15": last.get("m15"), "vol": vol})
    buy.sort(key=lambda r: (-len(r["br"]), -max(x[2] for x in r["br"])))
    sell.sort(key=lambda r: (-len(r["br"]), -max(x[2] for x in r["br"])))
    json.dump({"d": day, "buy": buy, "sell": sell}, open("kb_today.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"  kb_today {day}:大買 {len(buy)} 檔、大賣 {len(sell)} 檔")


if __name__ == "__main__":
    main()
