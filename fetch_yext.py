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
