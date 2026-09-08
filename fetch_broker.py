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
DIR = "bk"; KEEP = 60
BUDGET_SEC = int(os.environ.get("BK_BUDGET_SEC", "3000"))     # 一輪最多 50 分鐘(r803:45 分鐘只抓到 1,925/2,100)
SLEEP = 0.55                                                   # 含往返約 1 秒/次 ≈ 3,600/小時,遠低於 6,000


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
    buys = [x for x in items if x[1] > 0][:5]
    sells = [x for x in sorted(items, key=lambda x: x[1]) if x[1] < 0][:5]
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


def load_shards():
    os.makedirs(DIR, exist_ok=True)
    S = {}
    for p in glob.glob(os.path.join(DIR, "tw*.json")):
        try: S[os.path.basename(p)[2:-5]] = json.load(open(p, encoding="utf-8"))
        except Exception: pass
    return S


def save_shards(S):
    for k, sh in S.items():
        json.dump(sh, open(os.path.join(DIR, f"tw{k}.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


def gov_banks(day):
    """八大行庫:{sid: 淨買張};date-only 查詢。"""
    rows = fm("TaiwanStockGovernmentBankBuySell", start_date=day, end_date=day)
    out = {}
    for r in rows:
        sid = str(r.get("stock_id") or "")
        b = float(r.get("buy") or 0); s = float(r.get("sell") or 0)
        if sid: out[sid] = out.get(sid, 0) + round((b - s) / 1000)
    return out


def main():
    if not TOKEN: log("未設 FINMIND_TOKEN"); return
    day = last_trade_day()
    st_p = os.path.join(DIR, "_state.json"); os.makedirs(DIR, exist_ok=True)
    try: st = json.load(open(st_p, encoding="utf-8"))
    except Exception: st = {}
    if st.get("date") != day: st = {"date": day, "done": [], "gov": False}
    done = set(st.get("done") or [])
    try: data = json.load(open("data.json", encoding="utf-8"))
    except Exception: log("沒有 data.json"); return
    ids = [s["id"] for s in data.get("stocks") or [] if s.get("market") == "TW" and not s.get("etf")]
    todo = [i for i in ids if i not in done]
    S = load_shards()
    t0 = time.time(); n = 0; empty = 0; fail = 0
    # ── 八大行庫(一次)──
    if not st.get("gov"):
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
            st["gov"] = True; log(f"  八大行庫 {day}:{len(g)} 檔,全市場淨 {sum(g.values()):+,} 張")
        except Exception as e:
            log(f"  八大行庫失敗:{e}")
    log(f"分點 {day}:待抓 {len(todo)}/{len(ids)} 檔(本輪上限 {BUDGET_SEC//60} 分鐘)")
    for sid in todo:
        if time.time() - t0 > BUDGET_SEC: log("  時間到,下一輪接著抓"); break
        try:
            rows = fm("TaiwanStockTradingDailyReport", data_id=sid, start_date=day, end_date=day)
        except Exception as e:
            fail += 1
            if fail <= 3: log(f"  {sid} 失敗:{e}")
            if fail >= 20: log("  連續失敗太多,停"); break
            time.sleep(2); continue
        time.sleep(SLEEP)
        k = shard_key(sid); e = S.setdefault(k, {}).setdefault(sid, {"d": [], "s": []})
        prev = e["s"][-1] if e["d"] and e["d"][-1] < day else None
        summ = summarize(rows, prev)
        if summ is None: empty += 1
        else:
            if day in e["d"]:
                i = e["d"].index(day); e["s"][i] = summ
            else:
                e["d"].append(day); e["s"].append(summ)
                e["d"] = e["d"][-KEEP:]; e["s"] = e["s"][-KEEP:]
        done.add(sid); n += 1
        if n % 200 == 0:
            st["done"] = sorted(done); json.dump(st, open(st_p, "w"), ensure_ascii=False); save_shards(S)
            log(f"  進度 {n}/{len(todo)}({int(time.time()-t0)}s)")
    st["done"] = sorted(done); json.dump(st, open(st_p, "w"), ensure_ascii=False); save_shards(S)
    log(f"✅ 分點 {day}:本輪 {n} 檔(無資料 {empty}、失敗 {fail}),累計 {len(done)}/{len(ids)}")


if __name__ == "__main__":
    main()
