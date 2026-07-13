#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
國際行情抓取器 v3 —— 零 Yahoo、零 stooq(它擋機器人)。
美股指數/美債殖利率/VIX/日經/美元指數:FRED(聯準會官方 API,免費金鑰)
加權/櫃買盤中分線:證交所 MIS(僅台北盤中時段有資料)
匯率:open.er-api.com(免金鑰)
需要環境變數 FRED_API_KEY(GitHub Secrets 設定)。
"""
import json, time, datetime, sys, os
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
FRED_KEY = os.environ.get("FRED_API_KEY", "").strip()

# 前端符號 → FRED series id(全部日頻,官方 T+0~T+1 更新)
FRED = {
    "^GSPC": "SP500",
    "^IXIC": "NASDAQCOM",
    "^DJI":  "DJIA",
    "^N225": "NIKKEI225",
    "^VIX":  "VIXCLS",
    "^TNX":  "DGS10",        # 10年期美債殖利率(%)
    "^FVX":  "DGS5",
    "^TYX":  "DGS30",
    "DX-Y.NYB": "DTWEXBGS",  # 廣義美元指數(聯準會版;量級與 DXY 不同,趨勢一致)
}
MIS_INTRA = {"^TWII": "tse_t00.tw", "^TWOII": "otc_o00.tw"}
ERAPI_FX = True   # TWD=X / JPYTWD=X / EURTWD=X / JPY=X

def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def fred_daily(series, days=200):
    d2 = datetime.date.today()
    d1 = d2 - datetime.timedelta(days=days + 120)
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series}&api_key={FRED_KEY}&file_type=json"
           f"&observation_start={d1.isoformat()}&observation_end={d2.isoformat()}")
    j = json.loads(http_get(url, timeout=30))
    t, c = [], []
    for o in j.get("observations", []):
        v = o.get("value", ".")
        if v in (".", "", None):
            continue
        try:
            ts = int(datetime.datetime.fromisoformat(o["date"])
                     .replace(tzinfo=datetime.timezone.utc).timestamp())
            t.append(ts); c.append(round(float(v), 4))
        except Exception:
            continue
    return {"t": t[-140:], "c": c[-140:]} if len(t) >= 5 else None

def nasdaq_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA["User-Agent"],
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def _nasdaq_points(j):
    rows = ((j.get("data") or {}).get("chart")) or []
    tt, cc = [], []
    for p in rows:
        try:
            x = p.get("x"); y = p.get("y")
            if x is None or y is None:
                continue
            ts = int(x / 1000) if x > 10**11 else int(x)   # 毫秒→秒
            v = float(str(y).replace(",", ""))
            tt.append(ts); cc.append(round(v, 2))
        except Exception:
            continue
    return tt, cc

def nasdaq_daily(sym="SOX", days=200):
    """費城半導體(SOX)是 Nasdaq 自家指數 → 直接向 Nasdaq 官方 chart API 取日線。
    零 Yahoo。機房若被擋則略過,不影響其它資料。"""
    d2 = datetime.date.today()
    d1 = d2 - datetime.timedelta(days=days)
    try:
        j = nasdaq_get(f"https://api.nasdaq.com/api/quote/{sym}/chart"
                       f"?assetclass=index&fromdate={d1.isoformat()}&todate={d2.isoformat()}")
    except Exception as e:
        print(f"  {sym} Nasdaq 端點失敗: {e}", file=sys.stderr)
        return None
    tt, cc = _nasdaq_points(j)
    return {"t": tt[-140:], "c": cc[-140:]} if len(tt) >= 5 else None

# 美股四大指數盤中 1 分線(Nasdaq 官方,延遲約15分;本排程美股時段每20分鐘一班)
NASDAQ_INTRA = {"^GSPC": ["SPX"], "^IXIC": ["COMP"],
                "^DJI": ["DJIA", "DJI"], "^SOX": ["SOX"]}

def nasdaq_intraday(cands):
    for sym in cands:
        try:
            j = nasdaq_get(f"https://api.nasdaq.com/api/quote/{sym}/chart?assetclass=index")
        except Exception as e:
            print(f"  {sym} Nasdaq 盤中失敗: {e}", file=sys.stderr)
            continue
        tt, cc = _nasdaq_points(j)
        if len(tt) >= 5:
            return {"t": tt, "c": cc}
        time.sleep(0.6)
    return None

def mis_intraday(ch, prev=None):
    url = (f"https://mis.twse.com.tw/stock/api/getChartOhlcStatis.jsp"
           f"?ex_ch={ch}&_={int(time.time()*1000)}")
    try:
        j = json.loads(http_get(url, timeout=15))
    except Exception:
        return None
    best = []
    def scan(o, depth=0):
        nonlocal best
        if depth > 4 or o is None:
            return
        if isinstance(o, list):
            nums = []
            for x in o:
                v = x[1] if isinstance(x, list) and len(x) > 1 else x
                try:
                    v = float(v)
                    if v == v:
                        nums.append(v)
                except Exception:
                    pass
            if len(nums) >= 5:
                okr = (prev is None or all(abs(v/prev - 1) < 0.15 for v in nums[:20]))
                if okr and len(nums) > len(best):
                    best = nums
            for x in o[:3]:
                scan(x, depth + 1)
        elif isinstance(o, dict):
            for v in o.values():
                scan(v, depth + 1)
    scan(j)
    if len(best) < 5:
        return None
    tp = datetime.timezone(datetime.timedelta(hours=8))
    base = datetime.datetime.now(tp).replace(hour=9, minute=0, second=0, microsecond=0)
    n = len(best)
    ts = [int((base + datetime.timedelta(minutes=270*i/max(1, n-1))).timestamp())
          for i in range(n)]
    return {"t": ts, "c": [round(v, 2) for v in best]}

def main():
    series = {}
    if not FRED_KEY:
        print("::warning::未設定 FRED_API_KEY,略過美股/殖利率(請到 repo Secrets 加入)")
    else:
        for sym, sid in FRED.items():
            for attempt in range(2):
                try:
                    got = fred_daily(sid)
                    if got:
                        series[sym] = {"d": got}
                        print(f"  {sym} ← FRED:{sid}({len(got['t'])} 根)")
                        break
                except Exception as e:
                    print(f"  {sym} FRED {sid} 失敗: {e}", file=sys.stderr)
                time.sleep(1.2)
            time.sleep(0.4)
    # 費城半導體:FRED 無此系列 → Nasdaq 官方端點(指數擁有者;零 Yahoo)
    got_sox = nasdaq_daily("SOX")
    if got_sox:
        series["^SOX"] = {"d": got_sox}
        print(f"  ^SOX ← Nasdaq 官方日線({len(got_sox['t'])} 根)")
    else:
        print("  ^SOX Nasdaq 未取得(機房被擋屬正常,本輪略過)")
    # 美股四大指數盤中分線(Nasdaq 官方;非交易時段回傳前一交易日全日走勢,同樣照存)
    for fsym, cands in NASDAQ_INTRA.items():
        m = nasdaq_intraday(cands)
        if not m:
            print(f"  {fsym} 盤中分線未取得(機房被擋或休市空檔,略過)")
            continue
        d = (series.get(fsym) or {}).get("d")
        if d and d.get("t") and d.get("c"):
            # 昨收:比對「分線最後一點的美東日期」與「FRED 日線最後一根日期」
            et = datetime.timezone(datetime.timedelta(hours=-4))
            intra_day = datetime.datetime.fromtimestamp(m["t"][-1], et).date()
            daily_day = datetime.datetime.fromtimestamp(d["t"][-1],
                        datetime.timezone.utc).date()
            if daily_day >= intra_day and len(d["c"]) >= 2:
                m["prev"] = d["c"][-2]     # FRED 已含當日 → 昨收=倒數第二根
            else:
                m["prev"] = d["c"][-1]     # FRED 尚未含當日 → 昨收=最後一根
        series.setdefault(fsym, {})["m"] = m
        print(f"  {fsym} ← Nasdaq 盤中({len(m['t'])} 點,昨收 {m.get('prev','—')})")
        time.sleep(0.5)
    # 台股指數盤中(收盤後 MIS 清空屬正常,僅盤中班次會有)
    for sym, ch in MIS_INTRA.items():
        m = mis_intraday(ch)
        if m:
            series.setdefault(sym, {})["m"] = m
            print(f"  {sym} ← MIS 盤中({len(m['t'])} 點)")
        time.sleep(0.5)
    # 匯率
    if ERAPI_FX:
        try:
            j = json.loads(http_get("https://open.er-api.com/v6/latest/USD", timeout=20))
            r = j.get("rates") or {}
            now = int(time.time())
            def put(sym, val, dg):
                if val:
                    series[sym] = {"d": {"t": [now-86400, now],
                                         "c": [round(val, dg), round(val, dg)]}}
            twd, jpy, eur = r.get("TWD"), r.get("JPY"), r.get("EUR")
            put("TWD=X", twd, 3)
            if twd and jpy: put("JPYTWD=X", twd/jpy, 4)
            if twd and eur: put("EURTWD=X", twd/eur, 3)
            put("JPY=X", jpy, 2)
            print(f"  匯率 ← er-api(USD/TWD={twd})")
        except Exception as e:
            print(f"  匯率 er-api 失敗: {e}", file=sys.stderr)
    if len(series) < 4:
        print(f"::error::只取得 {len(series)} 檔(<4),放棄寫檔")
        sys.exit(1)
    doc = {"updated": datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
           "series": series}
    with open("yext.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"完成:{len(series)} 檔 → yext.json(FRED+MIS+er-api,零 Yahoo)")

if __name__ == "__main__":
    main()
