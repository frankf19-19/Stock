"""分點歷史回補(每檔一次抓 90 個日曆日)→ bk/tw<分片>.json
=========================================================
關鍵分點分析要每檔 ≥60 個交易日的分點紀錄。fetch_broker.py 每天只累積當天;這支對每檔用日期區間一次拉回
(TaiwanStockTradingDailyReport data_id + start/end),按日 summarize 後補進同一個分片(已有的日子不覆蓋)。
每班最多 BUDGET_SEC 秒,狀態檔記做到哪;跑幾班補齊,之後不再需要。
"""
import json, os, time, datetime as dt
import requests, importlib.util

spec = importlib.util.spec_from_file_location("fb", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch_broker.py"))
fb = importlib.util.module_from_spec(spec); spec.loader.exec_module(fb)

TZ = dt.timezone(dt.timedelta(hours=8)); TODAY = dt.datetime.now(TZ).date()
DAYS = 95
BUDGET_SEC = int(os.environ.get("BKH_BUDGET_SEC", "1500"))
SLEEP = 0.8


def log(*a): print(*a, flush=True)


def main():
    if not fb.TOKEN: log("未設 FINMIND_TOKEN"); return
    st_p = os.path.join(fb.DIR, "_hist_state.json"); os.makedirs(fb.DIR, exist_ok=True)
    try: st = json.load(open(st_p, encoding="utf-8"))
    except Exception: st = {"done": []}
    done = set(st.get("done") or [])
    try: data = json.load(open("data.json", encoding="utf-8"))
    except Exception: log("沒有 data.json"); return
    ids = [s["id"] for s in data.get("stocks") or [] if s.get("market") == "TW" and not s.get("etf")]
    todo = [i for i in ids if i not in done]
    if not todo: log("分點歷史:全部補齊"); return
    S = fb.load_shards()
    d0 = (TODAY - dt.timedelta(days=DAYS)).isoformat(); d1 = TODAY.isoformat()
    t0 = time.time(); n = 0; fail = 0
    log(f"分點歷史:待補 {len(todo)}/{len(ids)} 檔,{d0}~{d1},本班最多 {BUDGET_SEC//60} 分鐘")
    for sid in todo:
        if time.time() - t0 > BUDGET_SEC: log("  時間到,下一班接著"); break
        try:
            rows = fb.fm("TaiwanStockTradingDailyReport", data_id=sid, start_date=d0, end_date=d1)
        except Exception as e:
            fail += 1
            if fail <= 3: log(f"  {sid} 失敗:{e}")
            if fail >= 15: log("  失敗太多,停"); break
            time.sleep(2); continue
        time.sleep(SLEEP)
        by = {}
        for r in rows: by.setdefault(str(r.get("date") or "")[:10], []).append(r)
        k = fb.shard_key(sid); e = S.setdefault(k, {}).setdefault(sid, {"d": [], "s": []})
        have = dict(zip(e["d"], e["s"]))
        prev = None
        for day in sorted(by):
            if not day: continue
            if day in have: prev = have[day]; continue
            summ = fb.summarize(by[day], prev)
            if summ: have[day] = summ; prev = summ
        days = sorted(have)[-fb.KEEP:]
        e["d"] = days; e["s"] = [have[d] for d in days]
        done.add(sid); n += 1
        if n % 100 == 0:
            st["done"] = sorted(done); json.dump(st, open(st_p, "w")); fb.save_shards(S); log(f"  進度 {n}({int(time.time()-t0)}s)")
    for k, sh in S.items():
        for sid, e in sh.items():
            try:
                kb = fb.key_brokers(e, sid)
                if kb: e["kb"] = kb
            except Exception: pass
    st["done"] = sorted(done); json.dump(st, open(st_p, "w")); fb.save_shards(S)
    log(f"✅ 分點歷史:本班 {n} 檔(失敗 {fail}),累計 {len(done)}/{len(ids)}")


if __name__ == "__main__":
    main()
