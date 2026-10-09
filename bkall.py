"""r1053:🗂 全部券商分點、多年歷史(不再只看每天前 15 大、不再只有 1 年)
==========================================================================
資料來源(FinMind Sponsor):
  ① 每天:fetch_broker.py 抓到的「每檔每天全部券商明細」→ 這裡彙總成每家券商的 買張/賣張/買均價/賣均價,
     先寫進 bkraw/days/<日期>.tsv.gz(跟著 bkraw 快取),夜間班再併進每檔檔案。
  ② 歷史:TaiwanStockTradingDailyReportSecIdAgg(當日券商分點統計表)——要帶 securities_trader_id、可帶日期區間,
     一次拿「一家券商在一段期間、每天、每檔」的買賣張數與均價。全台約 900 家分點 × 每月一次 → 一個月歷史約 900 次。
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
    log(f"每日全券商併入:{n:,} 列、{len(buf)} 檔")


# ── ② 歷史回補:分點統計表(依券商 × 月)──
def fm(path, **p):
    p = {**p, "token": TOKEN}
    r = requests.get(f"{API}/{path}", params=p, timeout=120)
    try: j = r.json()
    except Exception: j = {}
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {str(j.get('msg') or j.get('detail') or r.text)[:160]}")
    return j.get("data") or []


def sponsor_ok():
    try:
        j = requests.get("https://api.web.finmindtrade.com/v2/user_info", params={"token": TOKEN}, timeout=30).json()
        si = j.get("SponsorInfo") or {}; sp = j.get("SponsorProInfo") or {}
        ok = si.get("status_code") == 200 and si.get("subscription_expired_date") or sp.get("status_code") == 200 and sp.get("subscription_expired_date")
        return bool(ok and (j.get("level") or 0) >= 2), j
    except Exception as e:
        return False, {"err": str(e)[:100]}


def brokers():
    """全部券商分點代號:先試 TaiwanSecuritiesTraderInfo,失敗就用每日明細累積到的代號"""
    p = os.path.join(ALL, "_brokers.json")
    try: B = json.load(open(p, encoding="utf-8"))
    except Exception: B = {}
    if not B or time.time() - B.get("_t", 0) > 30 * 86400:
        try:
            rows = fm("data", dataset="TaiwanSecuritiesTraderInfo")
            for r in rows:
                i = str(r.get("securities_trader_id") or "").strip()
                if i: B[i] = r.get("securities_trader") or i
            B["_t"] = time.time()
            os.makedirs(ALL, exist_ok=True); json.dump(B, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as e: log(f"  券商清單失敗:{e}")
    return {k: v for k, v in B.items() if not k.startswith("_")}


def months_back(n):
    t = dt.date.today().replace(day=1); out = []
    for _ in range(n):
        last = (t + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
        out.append((t.isoformat(), min(last, dt.date.today()).isoformat())); t = (t - dt.timedelta(days=1)).replace(day=1)
    return out


def backfill(t_end):
    st_p = os.path.join(ALL, "_state.json")
    try: st = json.load(open(st_p, encoding="utf-8"))
    except Exception: st = {}
    done = set(st.get("done") or []); bad = st.get("bad") or {}
    B = brokers()
    if not B: log("沒有券商清單,略過回補"); return st
    log(f"券商分點 {len(B)} 家;已完成 {len(done):,} 組(券商×月)")
    calls = 0; rows_n = 0; buf = {}; last_flush = time.time()
    split = st.get("split") or {}                              # 某券商某月太大 → 改用半月
    for m0, m1 in months_back(12 * KEEP_YEARS)[1:]:            # 本月由每日資料負責,從上個月往回補
        for bid in sorted(B):
            key = f"{bid}:{m0[:7]}"
            if key in done or bad.get(key, 0) >= 3: continue
            if time.time() > t_end: break
            parts = [(m0, m1)] if not split.get(key) else [(m0, m0[:8] + "15"), (m0[:8] + "16", m1)]
            ok = True
            for a, b in parts:
                try:
                    rows = fm("taiwan_stock_trading_daily_report_secid_agg", securities_trader_id=bid, start_date=a, end_date=b); calls += 1
                except Exception as e:
                    msg = str(e); calls += 1
                    if "too large" in msg or "413" in msg or "size" in msg:
                        split[key] = 1; ok = False; break
                    if "402" in msg or "limit" in msg.lower() or "level" in msg:
                        log(f"  額度/權限:{msg[:120]} → 停止回補"); st.update(done=sorted(done), bad=bad, split=split); return st
                    bad[key] = bad.get(key, 0) + 1; ok = False; time.sleep(2); break
                for r in rows:
                    sid = str(r.get("stock_id") or ""); d = str(r.get("date") or "")[:10]
                    if not sid or not d: continue
                    bv = float(r.get("buy_volume") or 0) / 1000; sv = float(r.get("sell_volume") or 0) / 1000
                    buf.setdefault(sid, {})[(d, str(r.get("securities_trader") or B.get(bid) or bid))] = (round(bv, 3), round(sv, 3), float(r.get("buy_price") or 0), float(r.get("sell_price") or 0))
                    rows_n += 1
                time.sleep(SLEEP)
            if ok: done.add(key)
            if rows_n > 3_000_000 or time.time() - last_flush > 1800:   # 定期落地,避免記憶體爆掉、被砍時白做
                merge(buf); buf = {}; rows_n = 0; last_flush = time.time()
                st.update(done=sorted(done), bad=bad, split=split); json.dump(st, open(st_p, "w", encoding="utf-8"))
                log(f"  落地:{len(done):,} 組完成,本班 {calls} 次")
        else:
            continue
        break
    if buf: merge(buf)
    st.update(done=sorted(done), bad=bad, split=split, last=dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M"))
    json.dump(st, open(st_p, "w", encoding="utf-8"))
    log(f"歷史回補:本班 {calls} 次 API;累計 {len(done):,} 組(券商×月)")
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
    if ok and TOKEN: status["backfill"] = {k: (len(v) if isinstance(v, list) else v) for k, v in backfill(t_end - 1200).items() if k in ("done", "last")}
    else: log("FinMind 贊助未啟用/已到期 → 只併每日資料,不回補歷史")
    cov = coverage(); vals = sorted(cov.values())
    status["coverage"] = {"stocks": len(cov), "median_days": vals[len(vals) // 2] if vals else 0, "max_days": vals[-1] if vals else 0}
    log(f"全券商資料:{len(cov)} 檔,中位 {status['coverage']['median_days']} 個交易日")
    try:
        import bk_swing; status["swing"] = bk_swing.build_full(ALL, log)
    except Exception as e:
        import traceback; status["swing_err"] = traceback.format_exc()[-1500:]; log(f"波段主力分點(全量)失敗:{e}")
    os.makedirs("bk", exist_ok=True)
    json.dump(status, open("bk/_bkall_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    log(f"完成({int(time.time() - t0)}s)")


if __name__ == "__main__":
    main()
