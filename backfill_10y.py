#!/usr/bin/env python3
"""K研所 · 長期歷史回補(r910)→ archive/(永久存檔,gzip 壓縮)

從 2012 年起(約 15 年),每檔股票每個資料集只要打 1 次 API:
  台股(FinMind,贊助版額度):
    price  日K        → archive/k/tw/<年>/<分片>.json.gz      {id:{d:[..], o:[[開,高,低,收,量(張)],..]}}
    inst   三大法人   → archive/inst/tw/<年>/<分片>.json.gz   {id:{d:[..], f:[外資淨張], t:[投信淨張], g:[自營淨張]}}
    margin 融資融券   → archive/margin/tw/<年>/<分片>.json.gz {id:{d:[..], mb:[融資餘額], sb:[融券餘額]}}
    per    本益比等   → archive/per/tw/<年>/<分片>.json.gz    {id:{d:[..], pe:[..], pb:[..], dy:[..]}}
    rev    月營收     → archive/rev/tw/<分片>.json.gz          {id:{m:[YYYY-MM..], r:[營收(千元)..]}}
  美股(Yahoo 日線):
    price  日K        → archive/k/us/<年>/<字母>.json.gz
可中斷續跑:archive/_state.json 記錄每個 (資料集,股票) 做完沒;每次最多打 BUDGET 次 API(預設 4500,留額度給平日更新)。
檔案一旦寫好就不再改動(只補新股票),所以不會讓倉庫一直變大。
"""
import json, os, gzip, time, datetime as dt, sys
import requests

START = os.environ.get("BF_START", "2012-01-01")
BUDGET = int(os.environ.get("BF_BUDGET", "4500"))
DEADLINE = time.time() + int(os.environ.get("BF_MINUTES", "300")) * 60
TOKEN = os.environ.get("FINMIND_TOKEN", "")
ROOT = "archive"
STATE = f"{ROOT}/_state.json"
FM = "https://api.finmindtrade.com/api/v4/data"
calls = 0


def log(*a): print(*a, flush=True)


def shard_tw(sid):
    t = str(sid); return t[:3] if t[:2] == "00" else t[:2]


def gz_load(p):
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f: return json.load(f)
    except Exception: return {}


def gz_save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9) as f: json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)


def fm(ds, sid, start=START):
    global calls
    for i in range(3):
        if calls >= BUDGET or time.time() > DEADLINE: raise StopIteration
        calls += 1
        try:
            r = requests.get(FM, params={"dataset": ds, "data_id": sid, "start_date": start, "token": TOKEN}, timeout=60)
            j = r.json()
            if j.get("status") not in (200, None) and "upper limit" in str(j.get("msg", "")).lower():
                log("  FinMind 額度用完,停止本輪"); raise StopIteration
            return j.get("data") or []
        except StopIteration: raise
        except Exception as e:
            log(f"  {ds} {sid} 失敗 {e},重試"); time.sleep(3 * (i + 1))
    return None


def by_year(rows, keyf, valf):
    out = {}
    for x in rows:
        d = x["date"][:10]; y = d[:4]
        e = out.setdefault(y, {"d": []}); v = valf(x)
        if v is None: continue
        e["d"].append(d)
        for k, val in v.items(): e.setdefault(k, []).append(val)
    return out


def tw_price(rows):
    return by_year(rows, None, lambda x: {"o": [x["open"], x["max"], x["min"], x["close"], round((x.get("Trading_Volume") or 0) / 1000)]} if x.get("close") else None)


def tw_inst(rows):
    agg = {}
    for x in rows:
        d = x["date"][:10]; n = x.get("name", ""); net = ((x.get("buy") or 0) - (x.get("sell") or 0)) / 1000
        a = agg.setdefault(d, [0.0, 0.0, 0.0])
        if n.startswith("Foreign"): a[0] += net
        elif n == "Investment_Trust": a[1] += net
        elif n.startswith("Dealer"): a[2] += net
    rows2 = [{"date": d, "v": v} for d, v in sorted(agg.items())]
    return by_year(rows2, None, lambda x: {"f": round(x["v"][0]), "t": round(x["v"][1]), "g": round(x["v"][2])})


def tw_margin(rows):
    return by_year(rows, None, lambda x: {"mb": x.get("MarginPurchaseTodayBalance"), "sb": x.get("ShortSaleTodayBalance")})


def tw_per(rows):
    return by_year(rows, None, lambda x: {"pe": x.get("PER"), "pb": x.get("PBR"), "dy": x.get("dividend_yield")})


DATASETS = [  # (代號, FinMind 資料集, 轉換, 目錄, 起始)
    ("price", "TaiwanStockPrice", tw_price, "k/tw", START),
    ("inst", "TaiwanStockInstitutionalInvestorsBuySell", tw_inst, "inst/tw", START),
    ("margin", "TaiwanStockMarginPurchaseShortSale", tw_margin, "margin/tw", START),
    ("per", "TaiwanStockPER", tw_per, "per/tw", START),
]


def us_price(sym):
    global calls
    if calls >= BUDGET or time.time() > DEADLINE: raise StopIteration
    calls += 1
    p1 = int(dt.datetime.fromisoformat(START).timestamp()); p2 = int(time.time())
    for host in ("query1", "query2"):
        try:
            r = requests.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"period1": p1, "period2": p2, "interval": "1d", "events": "div,splits"},
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
            q = r.json()["chart"]["result"][0]; t = q["timestamp"]; o = q["indicators"]["quote"][0]
            rows = []
            for i, ts in enumerate(t):
                c = o["close"][i]
                if c is None: continue
                d = dt.datetime.utcfromtimestamp(ts - 4 * 3600).date().isoformat()
                rows.append({"date": d, "o": [round(o["open"][i] or c, 4), round(o["high"][i] or c, 4), round(o["low"][i] or c, 4), round(c, 4), int(o["volume"][i] or 0)]})
            return by_year(rows, None, lambda x: {"o": x["o"]})
        except Exception as e:
            log(f"  Yahoo {sym} {host} 失敗 {e}")
    return None


def main():
    try:
        with open("data.json", encoding="utf-8") as f: D = json.load(f)
    except Exception as e:
        log("讀不到 data.json", e); return
    st = {}
    try:
        with open(STATE, encoding="utf-8") as f: st = json.load(f)
    except Exception: pass
    done = st.setdefault("done", {})
    tw = sorted({s["id"] for s in D.get("stocks") or [] if s.get("market") == "TW"})
    us = sorted({s["id"] for s in D.get("stocks") or [] if s.get("market") == "US"})
    shards = {}
    for sid in tw: shards.setdefault(shard_tw(sid), []).append(sid)
    try:
        # 台股:依分片處理,一個分片做完才寫檔(記憶體小、可中斷)
        for sh in sorted(shards):
            pend = {}   # (dir, year) → {sid: series}
            revs = {}
            for sid in shards[sh]:
                for key, ds, conv, sub, start in DATASETS:
                    k = f"{key}:{sid}"
                    if k in done: continue
                    rows = fm(ds, sid, start)
                    if rows is None: continue
                    for y, ser in conv(rows).items(): pend.setdefault((sub, y), {})[sid] = ser
                    done[k] = TODAY
                k = f"rev:{sid}"
                if k not in done:
                    rows = fm("TaiwanStockMonthRevenue", sid, START)
                    if rows is not None:
                        rows = sorted(rows, key=lambda x: (x.get("revenue_year", 0), x.get("revenue_month", 0)))
                        revs[sid] = {"m": [f"{x['revenue_year']}-{int(x['revenue_month']):02d}" for x in rows],
                                     "r": [round((x.get("revenue") or 0) / 1000) for x in rows]}
                        done[k] = TODAY
            for (sub, y), mp in pend.items():
                p = f"{ROOT}/{sub}/{y}/{sh}.json.gz"; A = gz_load(p)
                for sid, ser in mp.items(): A = merge_into_obj(A, sid, ser)
                gz_save(p, A)
            if revs:
                p = f"{ROOT}/rev/tw/{sh}.json.gz"; A = gz_load(p); A.update(revs); gz_save(p, A)
            save_state(st)
            log(f"  分片 {sh} 完成({len(shards[sh])} 檔),已用 API {calls}")
        # 美股
        pend = {}
        for sym in us:
            k = f"price:{sym}"
            if k in done: continue
            got = us_price(sym)
            if got is None: continue
            for y, ser in got.items(): pend.setdefault((sym[0].lower(), y), {})[sym] = ser
            done[k] = TODAY
            if len(pend) > 400: flush_us(pend); save_state(st)
        flush_us(pend); save_state(st)
    except StopIteration:
        log(f"本輪到上限(API {calls} 次),下次接著跑")
    save_state(st)
    n_tw = sum(1 for k in done if k.split(":")[0] in ("price", "inst", "margin", "per", "rev") and not k.split(":")[1].isalpha())
    log(f"✅ 長期歷史回補:本輪 API {calls} 次;累計完成 {len(done)} 項(台股 {n_tw} / 目標 {len(tw) * 5},美股 {sum(1 for k in done if k.startswith('price:') and k.split(':')[1].isalpha())} / {len(us)})")


def merge_into_obj(A, sid, series):
    old = A.get(sid) or {}
    m = {}
    for i, d in enumerate(old.get("d") or []): m[d] = {k: old[k][i] for k in old if k != "d" and i < len(old[k])}
    for i, d in enumerate(series["d"]): m[d] = {k: series[k][i] for k in series if k != "d" and i < len(series[k])}
    ds = sorted(m); keys = sorted({k for v in m.values() for k in v})
    A[sid] = {"d": ds, **{k: [m[d].get(k) for d in ds] for k in keys}}
    return A


def flush_us(pend):
    for (letter, y), mp in list(pend.items()):
        p = f"{ROOT}/k/us/{y}/{letter}.json.gz"; A = gz_load(p)
        for sid, ser in mp.items(): A = merge_into_obj(A, sid, ser)
        gz_save(p, A)
    pend.clear()


def save_state(st):
    os.makedirs(ROOT, exist_ok=True)
    st["u"] = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    with open(STATE, "w", encoding="utf-8") as f: json.dump(st, f, ensure_ascii=False, separators=(",", ":"))


TODAY = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date().isoformat()

if __name__ == "__main__":
    main()
