"""三年籌碼/價格歷史回補 → hist/tw<分片>.json
=============================================
站上籌碼只有 130~250 天,訊號成績單、借券分位、AI Pick 因子全在小樣本上。這支用 FinMind「按日期查全市場」
(一天一次)回補 3 年:三大法人買賣超、融資融券餘額、收盤價。每檔一份:
  {d:[...], c:[收盤], f:[外資淨買張], t:[投信], g:[自營], mf:[融資餘額張], mv:[融券餘額張]}
每輪最多 MAX_CALLS 次(3 個資料集 × 天數),缺哪天補哪天;跑幾班補齊,之後每天只補當天。
"""
import json, os, glob, datetime as dt, time
import requests

TZ = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.datetime.now(TZ).date()
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
API = "https://api.finmindtrade.com/api/v4/data"
DIR = "hist"; DAYS = 3 * 365 + 30
MAX_CALLS = int(os.environ.get("HIST_MAX_CALLS", "450"))   # r803:一班約 8 分鐘;每 150 次落地一次,被砍也不會白跑
SLEEP = 0.65


def log(*a): print(*a, flush=True)


def shard_key(sid):
    t = str(sid); return t[:3] if t[:2] == "00" else t[:2]


def fm(dataset, day):
    r = requests.get(API, params={"dataset": dataset, "start_date": day, "end_date": day, "token": TOKEN}, timeout=90)
    j = r.json()
    if r.status_code != 200: raise RuntimeError(f"{dataset} {r.status_code} {str(j.get('msg'))[:80]}")
    return j.get("data") or []


def load():
    os.makedirs(DIR, exist_ok=True)
    S = {}
    for p in glob.glob(os.path.join(DIR, "tw*.json")):
        try: S[os.path.basename(p)[2:-5]] = json.load(open(p, encoding="utf-8"))
        except Exception: pass
    return S


def main():
    if not TOKEN: log("未設 FINMIND_TOKEN"); return
    S = load()
    st_p = os.path.join(DIR, "_state.json")
    try: st = json.load(open(st_p, encoding="utf-8"))
    except Exception: st = {"done": {}, "skip": []}
    done = st.setdefault("done", {}); skip = set(st.get("skip") or [])
    days = []
    d = TODAY
    while (TODAY - d).days <= DAYS:
        if d.weekday() < 5:
            iso = d.isoformat()
            if iso not in skip and len(done.get(iso) or []) < 3: days.append(iso)
        d -= dt.timedelta(days=1)
    log(f"歷史回補:待補 {len(days)} 個交易日(每日 3 個資料集),本班最多 {MAX_CALLS} 次")
    calls = 0
    def put(sid, day, key, val):
        k = shard_key(sid); e = S.setdefault(k, {}).setdefault(sid, {"d": []})
        if day not in e["d"]:
            e["d"].append(day)
            for kk in ("c", "f", "t", "g", "mf", "mv"): e.setdefault(kk, []).append(None)
            # 保持與 d 同長
            for kk in ("c", "f", "t", "g", "mf", "mv"):
                while len(e[kk]) < len(e["d"]): e[kk].append(None)
        i = e["d"].index(day); e.setdefault(key, [None] * len(e["d"]))
        while len(e[key]) < len(e["d"]): e[key].append(None)
        e[key][i] = val
    for day in days:
        got = set(done.get(day) or [])
        for ds in ("price", "inst", "margin"):
            if ds in got: continue
            if calls >= MAX_CALLS: break
            calls += 1
            try:
                if ds == "price":
                    rows = fm("TaiwanStockPrice", day)
                    if not rows and day != TODAY.isoformat(): skip.add(day); got.update(("price", "inst", "margin")); break
                    for r in rows:
                        try: put(str(r["stock_id"]), day, "c", float(r["close"]))
                        except Exception: pass
                elif ds == "inst":
                    rows = fm("TaiwanStockInstitutionalInvestorsBuySell", day)
                    acc = {}
                    for r in rows:
                        sid = str(r.get("stock_id")); nm = str(r.get("name") or "")
                        net = (float(r.get("buy") or 0) - float(r.get("sell") or 0)) / 1000
                        key = "f" if nm.startswith("Foreign") else "t" if nm.startswith("Investment") else "g" if nm.startswith("Dealer") else None
                        if key: acc.setdefault(sid, {}).setdefault(key, 0.0); acc[sid][key] += net
                    for sid, m in acc.items():
                        for key, v in m.items(): put(sid, day, key, round(v))
                else:
                    rows = fm("TaiwanStockMarginPurchaseShortSale", day)
                    for r in rows:
                        sid = str(r.get("stock_id"))
                        try:
                            put(sid, day, "mf", int(float(r.get("MarginPurchaseTodayBalance") or 0)))
                            put(sid, day, "mv", int(float(r.get("ShortSaleTodayBalance") or 0)))
                        except Exception: pass
                got.add(ds)
            except Exception as e:
                log(f"  {day} {ds} 失敗:{e}")
            time.sleep(SLEEP)
        done[day] = sorted(got)
        if calls % 150 == 0: flush(S, st, skip, done); log(f"  已落地({calls} 次)")
        if calls >= MAX_CALLS: log("  本班額度用完"); break
    flush(S, st, skip, done)
    tot = len([d for d, v in done.items() if len(v) >= 3])
    log(f"✅ 歷史:本班 {calls} 次,完整交易日 {tot},檔數 {sum(len(sh) for sh in S.values())}")


def flush(S, st, skip, done):
    for k, sh in S.items():
        for sid, e in sh.items():
            order = sorted(range(len(e["d"])), key=lambda i: e["d"][i])
            for kk in ("d", "c", "f", "t", "g", "mf", "mv"):
                arr = e.get(kk) or []
                while len(arr) < len(e["d"]): arr.append(None)
                e[kk] = [arr[i] for i in order]
        json.dump(sh, open(os.path.join(DIR, f"tw{k}.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    st["skip"] = sorted(skip); st["done"] = done; json.dump(st, open(os.path.join(DIR, "_state.json"), "w", encoding="utf-8"))


if __name__ == "__main__":
    main()
