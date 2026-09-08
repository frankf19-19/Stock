"""借券賣出餘額・逐日歷史回補與維護 → sbl/tw<分片>.json
=========================================================
借券賣出是法人/大戶的空方部位(散戶用融券),每檔的「借券承受力」完全不同:
台積電借券 20 萬張照漲、小型股 2 萬張可能就壓死。要判斷「借券到多少股價就難漲、到多低容易漲」,
必須看它自己一年的借券分佈對照之後的漲跌——這需要 ≥250 個交易日的逐日餘額。

資料:FinMind TaiwanDailyShortSaleBalances(上市;一次一個日期回全市場)→ 借券賣出當日餘額(股→張)。
      抓不到的日期退回 TWSE TWT93U?date=(GitHub IP 常被擋,備援用)。
      上櫃暫無穩定來源,先做上市。
輸出:sbl/tw<key>.json = {sid: {"d":[ISO...], "v":[張...]}},依 k/ 分片同一種切法。
每班最多 MAX_CALLS 次(FinMind 免費 600/小時),缺哪天補哪天;跑幾班就把一年補齊,之後每天只補當天。
"""
import json, os, glob, datetime as dt, time
import requests

TZ = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.datetime.now(TZ).date()
OUT_DIR = "sbl"
DAYS = 270                 # 回補天數(日曆日;約 185 個交易日,足夠做分位統計)
MAX_CALLS = int(os.environ.get("SBL_MAX_CALLS", "120"))
FM_TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def log(*a): print(*a, flush=True)


def shard_key(sid):
    t = str(sid); return t[:3] if t[:2] == "00" else t[:2]


def load_shards():
    os.makedirs(OUT_DIR, exist_ok=True)
    S = {}
    for p in glob.glob(os.path.join(OUT_DIR, "tw*.json")):
        try: S[os.path.basename(p)[2:-5]] = json.load(open(p, encoding="utf-8"))
        except Exception: pass
    return S


def have_dates(S):
    ds = set()
    for sh in S.values():
        for e in sh.values():
            ds.update(e.get("d") or [])
    return ds


_FM_MSG = {"n": 0}
def fetch_finmind(day):
    """{sid: 張} 或 None"""
    if not FM_TOKEN: return None
    try:
        r = requests.get("https://api.finmindtrade.com/api/v4/data",
                         params={"dataset": "TaiwanDailyShortSaleBalances", "start_date": day, "end_date": day, "token": FM_TOKEN},
                         timeout=60)
        j = r.json()
        rows = j.get("data") or []
        if not rows:
            if j.get("msg") != "success" and _FM_MSG["n"] < 3: _FM_MSG["n"] += 1; log(f"  FinMind 按日查詢回應:{r.status_code} {str(j.get('msg'))[:80]}")
            return {} if j.get("msg") == "success" else None
        k = next((c for c in rows[0].keys() if "SBL" in c and "CurrentDay" in c), None) or \
            next((c for c in rows[0].keys() if "SBL" in c and "Balance" in c and "Previous" not in c), None)
        if not k: log(f"  FinMind 欄位不認得:{list(rows[0].keys())[:8]}"); return None
        out = {}
        for x in rows:
            try: out[str(x["stock_id"])] = round(float(x[k]) / 1000)
            except Exception: pass
        return out
    except Exception as e:
        log(f"  FinMind {day} 失敗:{e}"); return None


def fetch_finmind_stock(sid, start):
    """一檔一次抓一段:{日期: 張} 或 None。這個資料集『按日抓全市場』不通,但『按股抓區間』一次就回一年。"""
    if not FM_TOKEN: return None
    try:
        r = requests.get("https://api.finmindtrade.com/api/v4/data",
                         params={"dataset": "TaiwanDailyShortSaleBalances", "data_id": sid, "start_date": start, "token": FM_TOKEN}, timeout=60)
        j = r.json()
        if j.get("msg") != "success":
            if _FM_MSG["n"] < 3: _FM_MSG["n"] += 1; log(f"  FinMind {sid} 回應:{r.status_code} {str(j.get('msg'))[:80]}")
            return None
        out = {}
        for x in (j.get("data") or []):
            try: out[str(x["date"])[:10]] = round(float(x["SBLShortSalesCurrentDayBalance"]) / 1000)
            except Exception: pass
        return out
    except Exception as e:
        log(f"  FinMind {sid} 失敗:{e}"); return None


def fetch_twse(day):
    try:
        u = f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={day.replace('-', '')}&response=json"
        j = requests.get(u, headers=UA, timeout=30).json()
        if not (isinstance(j, dict) and j.get("stat") == "OK" and j.get("data")): return {}
        f = j.get("fields") or []
        ic = next((i for i, c in enumerate(f) if "代號" in c or "Code" in c), 0)
        ib = next((i for i, c in enumerate(f) if "借券" in c and ("當日餘額" in c or "今日餘額" in c)), None)
        if ib is None: return None
        out = {}
        for row in j["data"]:
            try: out[str(row[ic]).strip()] = round(float(str(row[ib]).replace(",", "")) / 1000)
            except Exception: pass
        return out
    except Exception as e:
        log(f"  TWSE {day} 失敗:{e}"); return None


def main():
    S = load_shards()
    had = have_dates(S)
    # 要補的交易日(週一到週五;放假日 FinMind 會回空,記進 skip 檔避免每班重打)
    skip_p = os.path.join(OUT_DIR, "_skip.json")
    try: skip = set(json.load(open(skip_p, encoding="utf-8")))
    except Exception: skip = set()
    days = []
    d = TODAY
    while (TODAY - d).days <= DAYS:
        if d.weekday() < 5:
            iso = d.isoformat()
            if iso not in had and iso not in skip: days.append(iso)
        d -= dt.timedelta(days=1)
    days.sort(reverse=True)                                    # 先補最近的,前端最快有感
    log(f"借券回補:已有 {len(had)} 個交易日,待補 {len(days)} 個,本班最多 {MAX_CALLS} 次")
    calls = n_ok = 0
    # ── 第一段:按日抓全市場(便宜;這個資料集常不通,通了就賺到)──
    byday_ok = None
    for day in days[:3]:
        if calls >= MAX_CALLS: break
        calls += 1
        data = fetch_finmind(day)
        if data is None: data = fetch_twse(day)
        if data is None: byday_ok = False; break
        byday_ok = True
        if not data:
            if day != TODAY.isoformat(): skip.add(day)
            continue
        for sid, v in data.items():
            k = shard_key(sid)
            e = S.setdefault(k, {}).setdefault(sid, {"d": [], "v": []})
            if day in e["d"]: continue
            e["d"].append(day); e["v"].append(v)
        n_ok += 1
        time.sleep(0.5)
    if byday_ok:
        for day in days[3:]:
            if calls >= MAX_CALLS: break
            calls += 1
            data = fetch_finmind(day)
            if data is None: data = fetch_twse(day)
            if data is None: continue
            if not data:
                if day != TODAY.isoformat(): skip.add(day)
                continue
            for sid, v in data.items():
                k = shard_key(sid)
                e = S.setdefault(k, {}).setdefault(sid, {"d": [], "v": []})
                if day in e["d"]: continue
                e["d"].append(day); e["v"].append(v)
            n_ok += 1
            time.sleep(0.5)
    else:
        # ── 第二段:按股抓區間(一檔一次就回一年;上市約 1,000 檔,每班 MAX_CALLS 檔,缺得最多的先補)──
        try: stocks = [x for x in json.load(open("data.json", encoding="utf-8")).get("stocks") or [] if x.get("market") == "TW" and not x.get("etf")]
        except Exception: stocks = []
        cutoff = (TODAY - dt.timedelta(days=DAYS)).isoformat()
        def last_of(sid):
            e = S.get(shard_key(sid), {}).get(sid); return (e["d"][-1] if e and e["d"] else "")
        stocks.sort(key=lambda x: last_of(x["id"]))            # 完全沒有的排最前
        log(f"  按日查詢不通 → 改按股抓區間:{len(stocks)} 檔,本班處理 {min(MAX_CALLS - calls, len(stocks))} 檔")
        done = 0
        for st in stocks:
            if calls >= MAX_CALLS: break
            sid = st["id"]; last = last_of(sid)
            if last >= (TODAY - dt.timedelta(days=1)).isoformat(): continue     # 已是最新
            start = cutoff if not last else (dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()
            calls += 1
            data = fetch_finmind_stock(sid, start)
            if data is None:
                if _FM_MSG["n"] >= 3 and done == 0 and calls >= 6: log("  FinMind 連續失敗,本班停止"); break
                continue
            e = S.setdefault(shard_key(sid), {}).setdefault(sid, {"d": [], "v": []})
            have = set(e["d"])
            for day, v in data.items():
                if day in have: continue
                e["d"].append(day); e["v"].append(v)
            done += 1; n_ok += 1
            time.sleep(0.35)
        log(f"  按股補入 {done} 檔")
    # 排序 + 只留 DAYS 內
    cutoff = (TODAY - dt.timedelta(days=DAYS)).isoformat()
    for k, sh in S.items():
        for sid, e in sh.items():
            pairs = sorted(zip(e["d"], e["v"]))
            pairs = [p for p in pairs if p[0] >= cutoff]
            e["d"] = [p[0] for p in pairs]; e["v"] = [p[1] for p in pairs]
        json.dump(sh, open(os.path.join(OUT_DIR, f"tw{k}.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(sorted(skip), open(skip_p, "w", encoding="utf-8"))
    tot = len(have_dates(S))
    log(f"✅ 借券:本班補 {n_ok}/{calls} 個交易日,累積 {tot} 個交易日,{sum(len(sh) for sh in S.values())} 檔")


if __name__ == "__main__":
    main()
