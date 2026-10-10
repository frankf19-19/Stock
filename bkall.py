"""r1053:🗂 全部券商分點、多年歷史(不再只看每天前 15 大、不再只有 1 年)
==========================================================================
資料來源(FinMind Sponsor):
  ① 每天:fetch_broker.py 抓到的「每檔每天全部券商明細」→ 這裡彙總成每家券商的 買張/賣張/買均價/賣均價,
     先寫進 bkraw/days/<日期>.tsv.gz(跟著 bkraw 快取),夜間班再併進每檔檔案。
  ② 歷史:同一份每日明細逐檔逐日往回補(分點統計表要同時指定股票+券商,不適合補全市場)。
存放:bkall/<股票>/<年>.tsv.gz(只附加),每列:日期 \t 券商 \t 買張 \t 賣張 \t 買均價 \t 賣均價(Actions 快取 bkall-*,不進 repo)
夜間班(bkall.yml):python bkall.py → 併每日檔 → 在時間/額度內往回補歷史 → 用全量資料重算 🕵️ 波段主力分點與驗證
"""
import os, io, gzip, json, time, glob, datetime as dt
import requests

TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
API = "https://api.finmindtrade.com/api/v4"
ALL = "bkall"; DAYS = os.path.join("bkraw", "days")
KEEP_YEARS = int(os.environ.get("BKALL_YEARS", "6"))
FROM = os.environ.get("BKALL_FROM", "2021-07-01")              # FinMind 分點每日明細最早到 2021-07(實測 2021-03 以前是空的)
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


# ── 每檔檔案讀寫:bkall/<股票>/<年>.tsv.gz,只「附加」不重寫(gzip 多段串接;讀的時候同日同券商以後寫的為準)──
def _lo():
    return max(FROM, (dt.date.today() - dt.timedelta(days=365 * KEEP_YEARS + 10)).isoformat())


def load_stock(sid, years=None):
    out = {}
    for p in sorted(glob.glob(os.path.join(ALL, sid, "*.tsv.gz"))):
        if years and os.path.basename(p)[:4] not in years: continue
        try:
            for ln in gzip.open(p, "rt", encoding="utf-8"):
                t = ln.rstrip("\n").split("\t")
                if len(t) == 6: out[(t[0], t[1])] = (float(t[2]), float(t[3]), float(t[4]), float(t[5]))
        except Exception: pass                                   # 被砍斷的最後一段讀不到就算了
    return out


RUN = os.environ.get("GITHUB_RUN_ID") or dt.datetime.now(TZ).strftime("%Y%m%d%H%M%S")
def merge(buf, delta=True):
    """buf = {sid: {(日期, 券商): (買張, 賣張, 買均價, 賣均價)}} → 依年份附加到每檔檔案
    r1060:同時寫一份「本班新增」到 bkall/_delta/<run>.tsv.gz → 收班時上傳 GitHub Releases(bkall-delta-年-月)永久保存,
          每一班抓到的都立刻有網站自己的備份,不靠 Actions 快取、也不靠 FinMind"""
    lo = _lo()
    if delta and buf:
        os.makedirs(os.path.join(ALL, "_delta"), exist_ok=True)
        with gzip.open(os.path.join(ALL, "_delta", f"{RUN}.tsv.gz"), "at", encoding="utf-8") as f:
            for sid, rows in buf.items():
                f.writelines(f"{sid}\t{d}\t{nm}\t{v[0]:g}\t{v[1]:g}\t{v[2]:g}\t{v[3]:g}\n" for (d, nm), v in sorted(rows.items()) if d >= lo)
    for sid, rows in buf.items():
        by = {}
        for (d, nm), v in rows.items():
            if d >= lo: by.setdefault(d[:4], []).append((d, nm, v))
        if not by: continue
        os.makedirs(os.path.join(ALL, sid), exist_ok=True)
        for y, lst in by.items():
            lst.sort()
            with gzip.open(os.path.join(ALL, sid, f"{y}.tsv.gz"), "at", encoding="utf-8") as f:
                f.writelines(f"{d}\t{nm}\t{v[0]:g}\t{v[1]:g}\t{v[2]:g}\t{v[3]:g}\n" for d, nm, v in lst)


def compact(sid):
    """重寫一檔(去重、排序);每週一次"""
    for p in glob.glob(os.path.join(ALL, sid, "*.tsv.gz")):
        rec = load_stock(sid, years={os.path.basename(p)[:4]})
        tmp = p + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            for (d, nm) in sorted(rec):
                v = rec[(d, nm)]; f.write(f"{d}\t{nm}\t{v[0]:g}\t{v[1]:g}\t{v[2]:g}\t{v[3]:g}\n")
        os.replace(tmp, p)


def merge_days():
    """bkraw/days 的每日全券商檔 → 附加到每檔(已併過且沒變的跳過)"""
    st_p = os.path.join(ALL, "_state.json")
    try: st = json.load(open(st_p, encoding="utf-8"))
    except Exception: st = {}
    seen = st.get("merged") or {}; n = 0; buf = {}; cnt = {}
    for p in sorted(glob.glob(os.path.join(DAYS, "*.tsv.gz"))):
        day = os.path.basename(p)[:10]; sig = f"{os.path.getsize(p)}"
        if seen.get(day) == sig: continue
        try:
            for ln in gzip.open(p, "rt", encoding="utf-8"):
                sid, nm, b, s_, bp, sp = ln.rstrip("\n").split("\t")
                buf.setdefault(sid, {})[(day, nm)] = (float(b), float(s_), float(bp), float(sp)); n += 1; cnt.setdefault(day, set()).add(sid)
            seen[day] = sig
        except Exception as e: log(f"  {p} 讀取失敗 {e}")
    if buf: merge(buf)
    nid = max(1, len(stock_ids()))
    add = [d for d, ss in cnt.items() if len(ss) >= 0.9 * nid]
    st["merged"] = dict(sorted(seen.items())[-40:])
    if add: st["days"] = sorted(set(st.get("days") or []) | set(add))
    os.makedirs(ALL, exist_ok=True); json.dump(st, open(st_p, "w", encoding="utf-8"))
    log(f"每日全券商併入:{n:,} 列、{len(buf)} 檔;新增補齊日 {len(add)}")


# ── ② 歷史回補:每檔每天全部券商明細(TaiwanStockTradingDailyReport,Sponsor)──
#   分點統計表(SecIdAgg)要同時指定股票+券商,不能拿來補全市場;所以用每日明細逐檔逐日補(一天約 1,925 次)。
#   Sponsor 6,000 次/小時 → 一小時約補 2.8 個交易日;r1056 起全天接力(每小時排一班,前一班結束就接上)。
def fm(dataset, **p):
    p = {"dataset": dataset, **p, "token": TOKEN}
    r = requests.get(f"{API}/data", params=p, timeout=90)
    try: j = r.json()
    except Exception: j = {}
    if r.status_code != 200 or (j.get("status") not in (200, None) and j.get("msg") != "success"):
        raise RuntimeError(f"{r.status_code} {str(j.get('msg') or j.get('detail') or r.text)[:160]}")
    return j.get("data") or []


# r1056:「有空檔就抓」——全天接力跑,依 FinMind 這小時用量自動讓速(大家共用 6,000 次/小時)
import threading
_GL = threading.Lock(); _G = {"n": 0, "t": 0.0}
def _used():
    try:
        j = requests.get("https://api.web.finmindtrade.com/v2/user_info", params={"token": TOKEN}, timeout=20).json()
        return int(j.get("user_count") or 0)
    except Exception: return None
def _soft():
    """這小時總用量的上限:交易日傍晚(每日分點/歷史回補在跑)只用到 3,000,其他時間 5,600(留一點給別的排程)"""
    now = dt.datetime.now(TZ); hm = now.hour * 60 + now.minute
    if now.weekday() < 5 and 16 * 60 + 20 <= hm <= 20 * 60 + 30: return int(os.environ.get("BKALL_SOFT_EVE", "3000"))
    return int(os.environ.get("BKALL_SOFT", "5600"))
def gov(t_end):
    with _GL:                                                  # 等待時鎖住 → 所有線程一起暫停
        _G["n"] += 1
        if _G["n"] % 50 and time.time() - _G["t"] < 120: return
        _G["t"] = time.time()
        while time.time() < t_end:
            u, lim = _used(), _soft()
            if u is None or u < lim: return
            log(f"  讓速:這小時已用 {u} 次(上限 {lim}),等 1 分鐘"); time.sleep(60)


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
    for sd in glob.glob(os.path.join(ALL, "[0-9]*")):
        seen = set()
        for p in glob.glob(os.path.join(sd, "*.tsv.gz")):
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
    lo = _lo()
    done = set(st.get("days") or [])
    if not done:                                                # 第一次:看既有檔案哪些天已齊
        for d, c in have_days().items():
            if c >= 0.9 * len(ids): done.add(d)
    todo = [d for d in reversed(cal) if lo <= d < dt.date.today().isoformat() and d not in done]
    log(f"歷史回補:目標 {KEEP_YEARS} 年;已補齊 {len(done)} 個交易日,待補 {len(todo)} 個(由近到遠)")
    THREADS, SL = 3, float(os.environ.get("BKALL_SL", "1.7"))  # 3 線程 × 每 1.7 秒 ≈ 6,000 次/小時上限;實際由 gov() 依總用量讓速
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
    def fetch_day(day, need, got):
        """抓某一天、某些股票的全部券商明細 → BUF;成功的加進 got"""
        nonlocal calls, quota_hit
        def one(sid):
            try:
                gov(t_end)
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
                    if "level" in m:
                        quota_hit = True; log(f"  權限不足:{m[:100]}")
                    elif "402" in m or "upper limit" in m:
                        log(f"  額度用完,等 10 分鐘:{m[:80]}"); time.sleep(600)
                        if time.time() < t_end: futs.append(ex.submit(one, sid))   # 這檔重抓
                        continue
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
        return got
    def partial(day):
        try: return set(json.load(open(os.path.join(ALL, "_partial", f"{day}.json"))))
        except Exception: return set()
    # ① r1059:使用者的最愛/持股先補(bk/_prio_users.json,notify.py 產生)——每檔一路往回補到 2021-07,再補全市場
    idset = set(ids)
    try: prio = sorted(x for x in json.load(open("bk/_prio_users.json", encoding="utf-8")) if str(x) in idset)
    except Exception: prio = []
    up = st.setdefault("prio_upto", {})
    days_desc = [d for d in reversed(cal) if lo <= d < dt.date.today().isoformat()]
    oldest = days_desc[-1] if days_desc else lo
    left = [x for x in prio if not (up.get(x) and up[x] <= oldest)]
    if left:
        log(f"最愛/持股優先:{len(prio)} 檔,還沒補完 {len(left)} 檔")
        broken = set()
        for day in days_desc:
            if time.time() > t_end or quota_hit: break
            cand = [x for x in left if x not in broken and not (up.get(x) and day >= up[x])]
            if not cand: continue
            if day in done:
                for x in cand: up[x] = day
                continue
            have = partial(day); got = set(have)
            need = [x for x in cand if x not in have]
            if need: fetch_day(day, need, got)
            for x in cand:
                if x in got: up[x] = day
                else: broken.add(x)                                  # 這檔這天沒抓到 → 這班不再往前,下班從這天接
            nbuf += 1; PEND.append((day, got))
            if nbuf >= 20: flush(); log(f"  最愛優先:補到 {day}(本班 {calls} 次)")
        flush()
        left = [x for x in prio if not (up.get(x) and up[x] <= oldest)]
    allup = None if (not prio or any(not up.get(x) for x in prio)) else max(up[x] for x in prio)   # 全部最愛都已補到哪一天
    if prio: log(f"最愛/持股優先:{len(prio)} 檔,還剩 {len(left)} 檔沒補完;全部最愛都已補到 {allup or '—'}")
    st["prio"] = {"n": len(prio), "done": len(prio) - len(left), "upto": allup}
    # ② 全市場,由近到遠
    for day in todo:
        if time.time() > t_end or quota_hit: break
        have = partial(day)
        need = [s for s in ids if s not in have]
        got = fetch_day(day, need, set(have))
        nbuf += 1; PEND.append((day, got))
        log(f"  {day}:{len(got)}/{len(ids)} 檔(本班 {calls} 次)")
        if nbuf >= 4 or time.time() > t_end or quota_hit: flush()   # 4 天落地一次(附加寫入,很快)
    flush()
    st["remain"] = len([d for d in todo if d not in done])          # r1059:還有幾天沒補 → 決定要不要自己接下一班
    log(f"歷史回補:本班 {calls} 次 API;累計補齊 {len(done)} 個交易日;還剩 {st['remain']} 個")
    return st


def main():
    t0 = time.time(); t_end = t0 + BUDGET
    os.makedirs(ALL, exist_ok=True)
    merge_days()
    ok, info = sponsor_ok()
    status = {"t": dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "sponsor": ok,
              "sponsor_expired": ((info.get("SponsorInfo") or {}).get("subscription_expired_date")), "level": info.get("level_title")}
    if ok and TOKEN:
        b = backfill(t_end - 1500)
        status["backfill"] = {k: (len(v) if isinstance(v, list) else v) for k, v in b.items() if k in ("days", "last", "remain", "prio")}
        status["more"] = bool(b.get("remain", 1)) or (b.get("prio") or {}).get("done", 0) < (b.get("prio") or {}).get("n", 0)   # 還沒補完 → workflow 收尾時自己排下一班
    else: log("FinMind 贊助未啟用/已到期 → 只併每日資料,不回補歷史")
    try: stt = json.load(open(os.path.join(ALL, "_state.json"), encoding="utf-8"))
    except Exception: stt = {}
    dd = sorted(stt.get("days") or [])
    status["coverage"] = {"stocks": len(glob.glob(os.path.join(ALL, "[0-9]*"))), "days": len(dd), "from": dd[0] if dd else None, "to": dd[-1] if dd else None}
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
