"""r1053:🗂 全部券商分點、多年歷史(不再只看每天前 15 大、不再只有 1 年)
==========================================================================
資料來源(FinMind Sponsor):
  ① 每天:fetch_broker.py 抓到的「每檔每天全部券商明細」→ 這裡彙總成每家券商的 買張/賣張/買均價/賣均價,
     先寫進 bkraw/days/<日期>.tsv.gz(跟著 bkraw 快取),夜間班再併進每檔檔案。
  ② 歷史:同一份每日明細逐檔逐日往回補(分點統計表要同時指定股票+券商,不適合補全市場)。
存放:bkall/<股票>.tsv.gz,每列:日期 \t 券商 \t 買張 \t 賣張 \t 買均價 \t 賣均價(Actions 快取 bkall-*,不進 repo)
夜間班(bkall.yml):python bkall.py → 併每日檔 → 在時間/額度內往回補歷史 → 用全量資料重算 🕵️ 波段主力分點與驗證
"""
import os, io, gzip, json, time, glob, datetime as dt
import requests

TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
API = "https://api.finmindtrade.com/api/v4"
ALL = "bkall"; DAYS = os.path.join("bkraw", "days")
KEEP_YEARS = int(os.environ.get("BKALL_YEARS", "5"))
BUDGET = int(os.environ.get("BKALL_BUDGET_SEC", str(4 * 3600)))
SLEEP = float(os.environ.get("BKALL_SLEEP", "0.65"))       # ≈ 5,500 次/小時(Sponsor 6,000)
TZ = dt.timezone(dt.timedelta(hours=8))


def log(*a): print(*a, flush=True)


# ── ① 每日(fetch_broker 呼叫):全部券商彙總 → 當日暫存檔 ──
_DAYBUF = {}
def put_day(sid, day, rows):
    agg = {}
    for r in rows or []:
        nm = str(r.get("securities_trader") or r.get("securities_trader_id") or "?")
        b = float(r.get("buy") or 0); s = float(r.get("sell") or 0); px = float(r.get("price") or 0)
        a = agg.setdefault(nm, [0.0, 0.0, 0.0, 0.0]); a[0] += b; a[1] += s; a[2] += b * px; a[3] += s * px
    if agg: _DAYBUF.setdefault(day, {})[sid] = agg


def flush_days(keep=12):
    """把今天累積的全券商彙總寫到 bkraw/days/<日期>.tsv.gz(合併同日既有內容);只留最近 keep 天"""
    if not _DAYBUF: return
    os.makedirs(DAYS, exist_ok=True)
    for day, by in _DAYBUF.items():
        p = os.path.join(DAYS, f"{day}.tsv.gz"); old = {}
        if os.path.exists(p):
            try:
                for ln in gzip.open(p, "rt", encoding="utf-8"):
                    sid, rest = ln.split("\t", 1); old.setdefault(sid, []).append(ln)
            except Exception: old = {}
        for sid, agg in by.items():
            old[sid] = [f"{sid}\t{nm}\t{round(b/1000, 3)}\t{round(s/1000, 3)}\t{round(bm/b, 2) if b else 0}\t{round(sm/s, 2) if s else 0}\n"
                        for nm, (b, s, bm, sm) in agg.items()]
        with gzip.open(p, "wt", encoding="utf-8") as f:
            for sid in sorted(old): f.writelines(old[sid])
    _DAYBUF.clear()
    fs = sorted(glob.glob(os.path.join(DAYS, "*.tsv.gz")))
    for p in fs[:-keep]:
        try: os.remove(p)
        except Exception: pass


# ── 每檔檔案讀寫 ──
def load_stock(sid):
    p = os.path.join(ALL, f"{sid}.tsv.gz"); out = {}
    if not os.path.exists(p): return out
    try:
        for ln in gzip.open(p, "rt", encoding="utf-8"):
            d, nm, b, s, bp, sp = ln.rstrip("\n").split("\t")
            out[(d, nm)] = (float(b), float(s), float(bp), float(sp))
    except Exception: pass
    return out


def save_stock(sid, rec):
    os.makedirs(ALL, exist_ok=True)
    lo = (dt.date.today() - dt.timedelta(days=365 * KEEP_YEARS + 10)).isoformat()
    with gzip.open(os.path.join(ALL, f"{sid}.tsv.gz"), "wt", encoding="utf-8") as f:
        for (d, nm) in sorted(rec):
            if d < lo: continue
            b, s, bp, sp = rec[(d, nm)]
            f.write(f"{d}\t{nm}\t{b:g}\t{s:g}\t{bp:g}\t{sp:g}\n")


def merge(buf):
    """buf = {sid: {(日期, 券商): (買張, 賣張, 買均價, 賣均價)}} 併進每檔檔案(同日同券商以新資料為準)"""
    for sid, rows in buf.items():
        rec = load_stock(sid); rec.update(rows); save_stock(sid, rec)


def merge_days():
    n = 0; buf = {}
    for p in sorted(glob.glob(os.path.join(DAYS, "*.tsv.gz"))):
        day = os.path.basename(p)[:10]
        try:
            for ln in gzip.open(p, "rt", encoding="utf-8"):
                sid, nm, b, s, bp, sp = ln.rstrip("\n").split("\t")
                buf.setdefault(sid, {})[(day, nm)] = (float(b), float(s), float(bp), float(sp)); n += 1
        except Exception as e: log(f"  {p} 讀取失敗 {e}")
    if buf: merge(buf)
    try:                                                         # 每日檔有 9 成股票以上 → 這天算補齊(回補不用重抓)
        st_p = os.path.join(ALL, "_state.json")
        try: st = json.load(open(st_p, encoding="utf-8"))
        except Exception: st = {}
        nid = max(1, len(stock_ids())); cnt = {}
        for sid, rows in buf.items():
            for (d, nm) in rows: cnt.setdefault(d, set()).add(sid)
        add = [d for d, ss in cnt.items() if len(ss) >= 0.9 * nid]
        if add: st["days"] = sorted(set(st.get("days") or []) | set(add)); json.dump(st, open(st_p, "w", encoding="utf-8"))
    except Exception: pass
    log(f"每日全券商併入:{n:,} 列、{len(buf)} 檔")


# ── ② 歷史回補:每檔每天全部券商明細(TaiwanStockTradingDailyReport,Sponsor)──
#   分點統計表(SecIdAgg)要同時指定股票+券商,不能拿來補全市場;所以用每日明細逐檔逐日補(一天約 1,925 次)。
#   Sponsor 6,000 次/小時 → 一小時約補 2.8 個交易日;一天兩班(凌晨、白天)約 30 天 → 兩年約兩週、三年約三週。
def fm(dataset, **p):
    p = {"dataset": dataset, **p, "token": TOKEN}
    r = requests.get(f"{API}/data", params=p, timeout=90)
    try: j = r.json()
    except Exception: j = {}
    if r.status_code != 200 or (j.get("status") not in (200, None) and j.get("msg") != "success"):
        raise RuntimeError(f"{r.status_code} {str(j.get('msg') or j.get('detail') or r.text)[:160]}")
    return j.get("data") or []


def sponsor_ok():
    try:
        j = requests.get("https://api.web.finmindtrade.com/v2/user_info", params={"token": TOKEN}, timeout=30).json()
        si = j.get("SponsorInfo") or {}; sp = j.get("SponsorProInfo") or {}
        ok = (si.get("status_code") == 200 and si.get("subscription_expired_date")) or (sp.get("status_code") == 200 and sp.get("subscription_expired_date"))
        return bool(ok), j
    except Exception as e:
        return False, {"err": str(e)[:100]}


def calendar():
    """交易日:台積電歷史收盤(archive/k ∪ hist ∪ k)"""
    try:
        import bk_swing, importlib.util
        spec = importlib.util.spec_from_file_location("fb", "fetch_broker.py"); fb = importlib.util.module_from_spec(spec); spec.loader.exec_module(fb)
        ds, _ = bk_swing._closes_all("2330", fb.closes_of, since="2015-01-01")
        return ds
    except Exception: return []


def stock_ids():
    try:
        d = json.load(open("data.json", encoding="utf-8"))
        return sorted(s["id"] for s in d.get("stocks") or [] if s.get("market") == "TW" and not s.get("etf") and str(s["id"]).isdigit() and len(str(s["id"])) == 4)
    except Exception: return []


def have_days():
    """全券商資料裡,每天有幾檔(用來判斷哪天已補齊)"""
    cnt = {}
    for p in glob.glob(os.path.join(ALL, "*.tsv.gz")):
        seen = set()
        try:
            for ln in gzip.open(p, "rt", encoding="utf-8"):
                d = ln[:10]
                if d not in seen: seen.add(d); cnt[d] = cnt.get(d, 0) + 1
        except Exception: pass
    return cnt


def backfill(t_end):
    from concurrent.futures import ThreadPoolExecutor
    st_p = os.path.join(ALL, "_state.json")
    try: st = json.load(open(st_p, encoding="utf-8"))
    except Exception: st = {}
    ids = stock_ids(); cal = calendar()
    if not ids or not cal: log("沒有股票清單或交易日曆,略過回補"); return st
    lo = (dt.date.today() - dt.timedelta(days=365 * KEEP_YEARS)).isoformat()
    done = set(st.get("days") or [])
    if not done:                                                # 第一次:看既有檔案哪些天已齊
        for d, c in have_days().items():
            if c >= 0.9 * len(ids): done.add(d)
    todo = [d for d in reversed(cal) if lo <= d < dt.date.today().isoformat() and d not in done]
    log(f"歷史回補:目標 {KEEP_YEARS} 年;已補齊 {len(done)} 個交易日,待補 {len(todo)} 個(由近到遠)")
    THREADS, SL = 3, 1.9                                       # 3 線程 × 每 1.9 秒 ≈ 5,700 次/小時
    calls = 0; quota_hit = False; BUF = {}; nbuf = 0; PEND = []
    def flush():
        """落地:資料先寫進每檔檔案,寫完才把這些天記成完成(被砍掉也不會漏)"""
        nonlocal BUF, nbuf, PEND
        if BUF: merge(BUF); log(f"  落地 {nbuf} 個交易日")
        for d0, g0 in PEND:
            p0 = os.path.join(ALL, "_partial", f"{d0}.json")
            if len(g0) >= 0.97 * len(ids):
                done.add(d0)
                try: os.remove(p0)
                except Exception: pass
            else:
                os.makedirs(os.path.dirname(p0), exist_ok=True); json.dump(sorted(g0), open(p0, "w"))
        st.update(days=sorted(done), last=dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")); json.dump(st, open(st_p, "w", encoding="utf-8"))
        BUF = {}; nbuf = 0; PEND = []
    for day in todo:
        if time.time() > t_end or quota_hit: break
        have = set()
        p_day = os.path.join(ALL, "_partial", f"{day}.json")
        try: have = set(json.load(open(p_day)))
        except Exception: pass
        need = [s for s in ids if s not in have]
        got = set(have)
        def one(sid):
            try:
                rows = fm("TaiwanStockTradingDailyReport", data_id=sid, start_date=day, end_date=day); time.sleep(SL); return sid, rows, None
            except Exception as e:
                time.sleep(2); return sid, None, e
        with ThreadPoolExecutor(max_workers=THREADS) as ex:
            futs = []; it = iter(need)
            for _ in range(THREADS):
                try: futs.append(ex.submit(one, next(it)))
                except StopIteration: pass
            while futs:
                f = futs.pop(0); sid, rows, err = f.result(); calls += 1
                if err is not None:
                    m = str(err)
                    if "402" in m or "upper limit" in m or "level" in m:
                        quota_hit = True; log(f"  額度/權限:{m[:100]}")
                else:
                    got.add(sid)
                    agg = {}
                    for r in rows or []:
                        nm = str(r.get("securities_trader") or r.get("securities_trader_id") or "?")
                        b = float(r.get("buy") or 0); s_ = float(r.get("sell") or 0); px = float(r.get("price") or 0)
                        a = agg.setdefault(nm, [0.0, 0.0, 0.0, 0.0]); a[0] += b; a[1] += s_; a[2] += b * px; a[3] += s_ * px
                    if agg:
                        BUF.setdefault(sid, {}).update({(day, nm): (round(b / 1000, 3), round(s2 / 1000, 3), round(bm / b, 2) if b else 0, round(sm / s2, 2) if s2 else 0)
                                    for nm, (b, s2, bm, sm) in agg.items()})
                if not quota_hit and time.time() <= t_end:
                    try: futs.append(ex.submit(one, next(it)))
                    except StopIteration: pass
        nbuf += 1; PEND.append((day, got))
        log(f"  {day}:{len(got)}/{len(ids)} 檔(本班 {calls} 次)")
        if nbuf >= 8 or time.time() > t_end or quota_hit: flush()   # 8 天落地一次(每次落地要重寫每檔檔案)
    flush()
    log(f"歷史回補:本班 {calls} 次 API;累計補齊 {len(done)} 個交易日")
    return st


def coverage():
    """每檔有幾個交易日的全券商資料"""
    out = {}
    for p in glob.glob(os.path.join(ALL, "*.tsv.gz")):
        sid = os.path.basename(p).split(".")[0]; ds = set()
        try:
            for ln in gzip.open(p, "rt", encoding="utf-8"): ds.add(ln[:10])
        except Exception: pass
        out[sid] = len(ds)
    return out


def main():
    t0 = time.time(); t_end = t0 + BUDGET
    os.makedirs(ALL, exist_ok=True)
    merge_days()
    ok, info = sponsor_ok()
    status = {"t": dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "sponsor": ok,
              "sponsor_expired": ((info.get("SponsorInfo") or {}).get("subscription_expired_date")), "level": info.get("level_title")}
    if ok and TOKEN: status["backfill"] = {k: (len(v) if isinstance(v, list) else v) for k, v in backfill(t_end - 1500).items() if k in ("days", "last")}
    else: log("FinMind 贊助未啟用/已到期 → 只併每日資料,不回補歷史")
    try: stt = json.load(open(os.path.join(ALL, "_state.json"), encoding="utf-8"))
    except Exception: stt = {}
    dd = sorted(stt.get("days") or [])
    status["coverage"] = {"stocks": len(glob.glob(os.path.join(ALL, "*.tsv.gz"))), "days": len(dd), "from": dd[0] if dd else None, "to": dd[-1] if dd else None}
    log(f"全券商資料:{status['coverage']}")
    try:
        import bk_swing; status["swing"] = bk_swing.build_full(ALL, log)
    except Exception as e:
        import traceback; status["swing_err"] = traceback.format_exc()[-1500:]; log(f"波段主力分點(全量)失敗:{e}")
    os.makedirs("bk", exist_ok=True)
    json.dump(status, open("bk/_bkall_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    log(f"完成({int(time.time() - t0)}s)")


if __name__ == "__main__":
    main()
