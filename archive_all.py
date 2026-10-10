"""r1061:📚 網站自己的永久紀錄——把所有「只留最近 N 天/週」的資料,每天併進 archive/hist/(只增不刪,進 repo)
================================================================================================
外部來源(FinMind 贊助、MoneyDJ、TAIFEX、集保…)哪天停了、或只給「今天」的資料,我們自己存過的都還在。
  (每天的資料一律依「年-月」分檔:每天只改到當月那一檔,repo 不會越長越肥)
  etf/<ETF>/<年-月>      主動 ETF 每日持股(權重%、股數)、規模——MoneyDJ 只給當天,錯過就沒了
  gov/<年-月>            八大行庫每日買賣超(FinMind 贊助)
  sbl/<年-月>            借券賣出餘額(每檔)
  taifex/<年-月>         期交所三大法人期貨未平倉
  fin/<分片>.json.gz     季報:毛利率、營益率、淨利率、營收、EPS、營業現金流
  tdcc9/<年-月>          集保 9 級距持股比例(每週;官方 CSV 原檔另存 GitHub Releases tdcc-<年>)
  credit/<年-月>         大盤融資餘額
  mkt_inst/<年-月>       全市場三大法人
  gooaye.json.gz         股癌每集 AI 重點(原本只留最新一集)
  conf_ai/<年>.json.gz   法說會 AI 分析(原本 30 天後刪除)
  news/<年-月>.json.gz   新聞標題
  archive/rev/tw/        月營收(補上原本凍結在 2026-08 的長期檔)
用法:python archive_all.py(每輪資料更新最後跑;很快,只寫有變動的檔)"""
import os, json, gzip, glob, datetime as dt

H = "archive/hist"
STAT = {}


def log(*a): print(*a, flush=True)


def jload(p, default=None):
    try:
        if p.endswith(".gz"): return json.load(gzip.open(p, "rt", encoding="utf-8"))
        return json.load(open(p, encoding="utf-8"))
    except Exception: return default


def upd(path, fn, name):
    """讀 → fn(obj) 回傳新增/更新筆數 → 有變動才寫回"""
    obj = jload(path, {}) or {}
    n = fn(obj)
    if n:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
        STAT[name] = STAT.get(name, 0) + n
    return n


def put(dst, key, val):
    """dst[key] = val;回傳是否有變動"""
    if dst.get(key) == val: return 0
    dst[key] = val; return 1


def by_month(prefix, recs, name, nested=None):
    """recs = {日期: 資料} → 依「年-月」分檔寫入(每天只會改到當月那一檔,repo 不會越長越肥)
    nested = 外層鍵(例如股票代號):recs = {外層鍵: {日期: 資料}}"""
    groups = {}
    if nested:
        for k, dd in recs.items():
            for d, v in dd.items(): groups.setdefault(str(d)[:7], {}).setdefault(k, {})[d] = v
        for ym, g in groups.items():
            upd(f"{prefix}/{ym}.json.gz", lambda A, g=g: sum(put(A.setdefault(k, {}), d, v) for k, dd in g.items() for d, v in dd.items()), name)
    else:
        for d, v in recs.items(): groups.setdefault(str(d)[:7], {})[d] = v
        for ym, g in groups.items():
            upd(f"{prefix}/{ym}.json.gz", lambda A, g=g: sum(put(A, d, v) for d, v in g.items()), name)


def aligned(o, skip=("d",)):
    """{'d':[日期...], 'x':[...], 'y':[...]} → {日期: {'x':..,'y':..}}"""
    ds = o.get("d") or []
    out = {}
    for i, d in enumerate(ds):
        out[str(d)] = {k: v[i] for k, v in o.items() if k not in skip and isinstance(v, list) and len(v) == len(ds)}
    return out


def etf():
    for p in glob.glob("e/*.json"):
        e = jload(p)
        if not e or not e.get("d"): continue
        eid = e.get("id") or os.path.basename(p)[:-5]; ds = e["d"]; recs = {}
        for i, d in enumerate(ds):
            row = {sid: v[i] for sid, v in (e.get("s") or {}).items() if isinstance(v, list) and i < len(v) and v[i] is not None}
            if not row: continue
            rec = {"s": row}
            for k in ("aum", "fd"):
                if isinstance(e.get(k), list) and len(e[k]) == len(ds): rec[k] = e[k][i]
            recs[d] = rec
        upd(f"{H}/etf/{eid}/_names.json.gz", lambda A, e=e: sum(put(A, k, v) for k, v in (e.get("nm") or {}).items()), "etf_nm")
        by_month(f"{H}/etf/{eid}", recs, "etf")


def gov():
    g = jload("gov.json")
    if not g: return
    by = {}
    for sid, e in (g.get("s") or {}).items():
        for d, v in zip(e.get("d") or [], e.get("v") or []): by.setdefault(d, {})[sid] = v
    by_month(f"{H}/gov", by, "gov")


def sbl():
    recs = {}
    for p in glob.glob("sbl/tw*.json"):
        for sid, e in (jload(p) or {}).items():
            if isinstance(e, dict): recs[sid] = {d: (r.get("v") if list(r) == ["v"] else r) for d, r in aligned(e).items()}
    by_month(f"{H}/sbl", recs, "sbl", nested=True)


def taifex():
    t = jload("taifex.json")
    if t: by_month(f"{H}/taifex", t.get("days") or {}, "taifex")


def fin_rev():
    for p in glob.glob("c/tw*.json"):
        C = jload(p) or {}; key = os.path.basename(p)[2:-5]
        def fn(A, C=C):
            n = 0
            for sid, e in C.items():
                if not isinstance(e, dict): continue
                dst = A.setdefault(sid, {})
                for i, q in enumerate(e.get("fq") or []):
                    rec = {k: e[k][i] for k in ("gm", "om", "nm", "qr") if isinstance(e.get(k), list) and i < len(e[k])}
                    if rec: n += put(dst.setdefault("q", {}), q, rec)
                for q, v in zip(e.get("qe_d") or [], e.get("qe") or []): n += put(dst.setdefault("eps", {}), q, v)
                if e.get("ocfq") and e.get("ocfr") is not None: n += put(dst.setdefault("ocf", {}), e["ocfq"], e["ocfr"])
            return n
        upd(f"{H}/fin/{key}.json.gz", fn, "fin")
        # 月營收:併進既有長期檔 archive/rev/tw/<分片>.json.gz({sid:{m:[月],r:[營收]}})
        def fr(A, C=C):
            n = 0
            for sid, e in C.items():
                if not isinstance(e, dict) or not e.get("rm"): continue
                a = A.setdefault(sid, {"m": [], "r": []}); cur = dict(zip(a.get("m") or [], a.get("r") or []))
                prev = None
                for m, r in sorted(set(zip(e.get("rm") or [], e.get("ra") or [])), key=lambda x: x[0]):
                    if r is None: continue
                    if prev is not None and r == prev[1] and m > prev[0]: continue   # 跟上個月一模一樣 = 舊版標錯月份,不收
                    prev = (m, r)
                    if cur.get(m) != r: cur[m] = r; n += 1
                ms = sorted(cur); a["m"] = ms; a["r"] = [cur[m] for m in ms]
            return n
        upd(f"archive/rev/tw/{key}.json.gz", fr, "rev")


def tdcc9():
    t = jload("tdcc.json")
    if not t or not t.get("d"): return
    by = {}
    for sid, arr in (t.get("s") or {}).items():
        for d, g in zip(t["d"], arr or []):
            if g: by.setdefault(d, {})[sid] = g
    by_month(f"{H}/tdcc9", by, "tdcc9")


def market():
    D = jload("data.json") or {}
    h = ((D.get("macro") or {}).get("credit") or {}).get("h")
    if isinstance(h, dict): by_month(f"{H}/credit", aligned(h), "credit")
    m = (jload("c/meta.json") or {}).get("mkt")
    if isinstance(m, dict): by_month(f"{H}/mkt_inst", aligned(m), "mkt_inst")
    # 新聞標題(大盤 + 個股)
    rows = {}
    day = str(D.get("updated") or dt.date.today().isoformat())[:10]
    for x in D.get("news") or []:
        if isinstance(x, dict) and x.get("title"): rows[x.get("link") or x["title"]] = {"t": x["title"], "src": x.get("source"), "d": x.get("date") or day, "id": "mkt"}
    for s in D.get("stocks") or []:
        for x in s.get("news") or []:
            if isinstance(x, dict) and x.get("title"): rows[x.get("link") or x["title"]] = {"t": x["title"], "src": x.get("source"), "d": x.get("date") or day, "id": s.get("id")}
    if rows: upd(f"{H}/news/{day[:7]}.json.gz", lambda A: sum(put(A, k, v) for k, v in rows.items() if k not in A), "news")


def ai_text():
    g = jload("gooaye.json")
    if g and g.get("ep"):
        upd(f"{H}/gooaye.json.gz", lambda A: put(A, str(g["ep"]), {k: g.get(k) for k in ("t", "dt", "yt", "s")}), "gooaye")
    c = jload("conf_ai.json")
    if c and c.get("items"):
        by = {}
        for sid, it in c["items"].items():
            if isinstance(it, dict): by.setdefault(str(it.get("d") or "")[:4] or "x", {})[f"{sid}|{it.get('d')}"] = it
        for y, items in by.items():
            upd(f"{H}/conf_ai/{y}.json.gz", lambda A, items=items: sum(put(A, k, v) for k, v in items.items()), "conf_ai")


def main():
    for f in (etf, gov, sbl, taifex, fin_rev, tdcc9, market, ai_text):
        try: f()
        except Exception as e: log(f"  永久紀錄 {f.__name__} 失敗:{e}")
    log("永久紀錄:" + ("、".join(f"{k} +{v}" for k, v in STAT.items()) or "沒有新資料"))
    try:
        st = jload(f"{H}/_status.json", {}) or {}
        st["t"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"); st["last"] = STAT
        os.makedirs(H, exist_ok=True); json.dump(st, open(f"{H}/_status.json", "w", encoding="utf-8"), ensure_ascii=False)
    except Exception: pass


if __name__ == "__main__":
    main()
