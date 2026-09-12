"""分點歷史回補 → bk/tw<分片>.json(r811 改版)
==========================================
FinMind 分點明細一次只給一天(區間查詢回 400 size too large)。所以:
  A 模式:只帶日期、不帶股票 → 一次拿全市場那一天的明細,按股票 summarize;60 個交易日 = 60 次。
  B 模式(A 被拒時):優先股清單(最愛/持股/AI Pick/綜合 ≥66 分)× 單日,每班在時間預算內盡量補。
狀態檔 bk/_hist_state.json:{"days_done":[...], "mode":"A"|"B", "b_done":{day:[sid...]}}
"""
import json, os, time, datetime as dt, importlib.util

spec = importlib.util.spec_from_file_location("fb", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch_broker.py"))
fb = importlib.util.module_from_spec(spec); spec.loader.exec_module(fb)

TZ = dt.timezone(dt.timedelta(hours=8)); TODAY = dt.datetime.now(TZ).date()
DAYS = 90                                   # 日曆日 ≈ 60 個交易日
BUDGET_SEC = int(os.environ.get("BKH_BUDGET_SEC", "1500"))
SLEEP_A, SLEEP_B = 1.0, 0.55


def log(*a): print(*a, flush=True)


def trading_days():
    """用台積電日 K 的日期當交易日曆。"""
    try:
        e = json.load(open("k/tw23.json", encoding="utf-8")).get("2330") or {}
        ds = [d for d in (e.get("d") or []) if d >= (TODAY - dt.timedelta(days=DAYS)).isoformat()]
        return sorted(ds)
    except Exception:
        out = []; d = TODAY
        while (TODAY - d).days <= DAYS:
            if d.weekday() < 5: out.append(d.isoformat())
            d -= dt.timedelta(days=1)
        return sorted(out)


def priority_ids(data):
    if os.environ.get("BKH_ALL") == "1":                    # r830:週末回補模式——全市場
        return sorted(s["id"] for s in data.get("stocks") or [] if s.get("market") == "TW" and not s.get("etf"))
    ids = set()
    for s in data.get("stocks") or []:
        if s.get("market") != "TW" or s.get("etf"): continue
        if (s.get("T") or s.get("score") or 0) >= 66: ids.add(s["id"])
    try:
        ap = json.load(open("aipick.json", encoding="utf-8"))
        for w in (ap.get("weeks") or [])[-3:]:
            for p in w.get("picks") or []: ids.add(p["id"]); [ids.add(L["id"]) for L in p.get("legs") or []]
            for b in w.get("bench") or []: ids.add(b["id"])
    except Exception: pass
    try:                                                     # 所有使用者的最愛/持股(notify 同一來源)
        import glob
        for p in glob.glob("bk/_prio_*.json"):
            for x in json.load(open(p, encoding="utf-8")): ids.add(str(x))
    except Exception: pass
    return sorted(ids)


def merge_day(S, day, rows_by_sid):
    n = 0
    for sid, rows in rows_by_sid.items():
        k = fb.shard_key(sid); e = S.setdefault(k, {}).setdefault(sid, {"d": [], "s": []})
        if day in e["d"]: continue
        prev = None
        for d, s in zip(e["d"], e["s"]):
            if d < day: prev = s
        summ = fb.summarize(rows, prev)
        if not summ: continue
        e["d"].append(day); e["s"].append(summ)
        order = sorted(range(len(e["d"])), key=lambda i: e["d"][i])
        e["d"] = [e["d"][i] for i in order][-fb.KEEP:]; e["s"] = [e["s"][i] for i in order][-fb.KEEP:]
        n += 1
    return n


def main():
    if not fb.TOKEN: log("未設 FINMIND_TOKEN"); return
    os.makedirs(fb.DIR, exist_ok=True)
    st_p = os.path.join(fb.DIR, "_hist_state.json")
    try: st = json.load(open(st_p, encoding="utf-8"))
    except Exception: st = {}
    st.setdefault("days_done", []); st.setdefault("mode", "A"); st.setdefault("b_done", {})
    try: data = json.load(open("data.json", encoding="utf-8"))
    except Exception: log("沒有 data.json"); return
    doneset = set(st["days_done"]) | (set() if os.environ.get("BKH_ALL") == "1" else set(st.get("prio_done") or []))
    days = [d for d in trading_days() if d not in doneset]
    days.sort(reverse=True)                                    # 先補最近的
    if not days: log("分點歷史:全部補齊"); return
    S = fb.load_shards(); t0 = time.time(); n_days = 0
    log(f"分點歷史:待補 {len(days)} 個交易日(模式 {st['mode']}),本班最多 {BUDGET_SEC//60} 分鐘")
    for day in days:
        if time.time() - t0 > BUDGET_SEC: log("  時間到,下一班接著"); break
        if st["mode"] == "A":
            try:
                rows = fb.fm("TaiwanStockTradingDailyReport", start_date=day, end_date=day)
                by = {}
                for r in rows: by.setdefault(str(r.get("stock_id") or ""), []).append(r)
                by.pop("", None)
                n = merge_day(S, day, by)
                st["days_done"].append(day); n_days += 1
                log(f"  {day}:全市場 {len(by)} 檔,寫入 {n}({len(rows):,} 列)")
                time.sleep(SLEEP_A); continue
            except Exception as e:
                msg = str(e)
                log(f"  {day} A 模式失敗:{msg[:120]}")
                if "too large" in msg or "400" in msg or "level" in msg:
                    st["mode"] = "B"; log("  → 改用 B 模式(優先股 × 單日)")
                else:
                    time.sleep(3); continue
        # B 模式
        ids = priority_ids(data); done = set(st["b_done"].get(day) or [])
        todo = [i for i in ids if i not in done]
        by = {}
        for sid in todo:
            if time.time() - t0 > BUDGET_SEC: break
            try:
                rows = fb.fm("TaiwanStockTradingDailyReport", data_id=sid, start_date=day, end_date=day)
                if rows: by[sid] = rows
                done.add(sid)
            except Exception as e:
                log(f"  {sid}@{day} 失敗:{str(e)[:80]}"); time.sleep(2)
            time.sleep(SLEEP_B)
        merge_day(S, day, by); st["b_done"][day] = sorted(done)
        if len(done) >= len(ids):
            n_days += 1
            if os.environ.get("BKH_ALL") == "1": st["days_done"].append(day)          # r830:只有全市場補齊才算這天完成
            else: st.setdefault("prio_done", []).append(day)
        log(f"  {day}:優先股 {len(done)}/{len(ids)} 檔")
        fb.save_shards(S); json.dump(st, open(st_p, "w"), ensure_ascii=False)
    # 關鍵分點重算
    nk = 0
    for k, sh in S.items():
        for sid, e in sh.items():
            try:
                kb = fb.key_brokers(e, sid)
                if kb: e["kb"] = kb; nk += 1
            except Exception: pass
    fb.save_shards(S); json.dump(st, open(st_p, "w"), ensure_ascii=False)
    log(f"✅ 分點歷史:本班補 {n_days} 個交易日,累計 {len(st['days_done'])};關鍵分點已算 {nk} 檔")


if __name__ == "__main__":
    main()
