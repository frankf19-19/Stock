#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
國際行情抓取器 v2 —— 零 Yahoo。
國際指數/期貨/匯率/美債殖利率:Stooq(免金鑰 CSV,伺服器端直連)。
加權/櫃買指數盤中分線:證交所 MIS 官方端點(伺服器端無 CORS 問題)。
產出 yext.json,前端同源讀取。
"""
import json, time, datetime, sys, csv, io
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 目標符號(沿用前端命名)→ Stooq 候選代碼(依序嘗試,先中先用)
STOOQ = {
    "^GSPC":  ["^spx"],
    "^IXIC":  ["^ndq"],
    "^DJI":   ["^dji"],
    "^SOX":   ["^sox"],
    "^N225":  ["^nkx"],
    "^VIX":   ["^vix", "vi.f"],
    "ES=F":   ["es.f"],
    "NQ=F":   ["nq.f"],
    "EWT":    ["ewt.us"],
    "TWD=X":  ["usdtwd"],
    "JPYTWD=X": ["jpytwd"],
    "EURTWD=X": ["eurtwd"],
    "JPY=X":  ["usdjpy"],
    "DX-Y.NYB": ["dx.f", "^dxy", "usd_i"],
    "^TNX":   ["10yusy.b", "10usy.b"],
    "^FVX":   ["5yusy.b", "5usy.b"],
    "^TYX":   ["30yusy.b", "30usy.b"],
    "^TWII":  ["^twse"],
    "^TWOII": [],                     # 櫃買:Stooq 無;盤中由 MIS 供應
}
MIS_INTRA = {"^TWII": "tse_t00.tw", "^TWOII": "otc_o00.tw"}

def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def stooq_daily(code, days=200):
    d2 = datetime.date.today()
    d1 = d2 - datetime.timedelta(days=days + 90)
    url = (f"https://stooq.com/q/d/l/?s={code}"
           f"&d1={d1:%Y%m%d}&d2={d2:%Y%m%d}&i=d")
    txt = http_get(url)
    rows = list(csv.DictReader(io.StringIO(txt)))
    out_t, out_c = [], []
    for r in rows:
        try:
            c = float(r["Close"])
            ts = int(datetime.datetime.fromisoformat(r["Date"])
                     .replace(tzinfo=datetime.timezone.utc).timestamp())
            out_t.append(ts); out_c.append(round(c, 4))
        except Exception:
            continue
    return {"t": out_t[-140:], "c": out_c[-140:]} if len(out_t) >= 5 else None

def mis_intraday(ch, prev=None):
    """MIS 個股/指數當日圖:彈性掃描回應樹,找出貼近昨收的分線收盤序列。"""
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
                okrange = (prev is None or
                           all(abs(v/prev - 1) < 0.15 for v in nums[:20]))
                if okrange and len(nums) > len(best):
                    best = nums
            for x in o[:3]:
                scan(x, depth + 1)
        elif isinstance(o, dict):
            for v in o.values():
                scan(v, depth + 1)
    scan(j)
    if len(best) < 5:
        return None
    # 以台北 09:00 起等距鋪時間軸(收盤 13:30,270 分)
    tp = datetime.timezone(datetime.timedelta(hours=8))
    base = datetime.datetime.now(tp).replace(hour=9, minute=0, second=0, microsecond=0)
    n = len(best)
    ts = [int((base + datetime.timedelta(minutes=270*i/max(1, n-1))).timestamp())
          for i in range(n)]
    return {"t": ts, "c": [round(v, 2) for v in best]}

def main():
    series = {}
    for sym, cands in STOOQ.items():
        got = None
        for code in cands:
            try:
                got = stooq_daily(code)
                if got:
                    print(f"  {sym} ← stooq:{code}({len(got['t'])} 根)")
                    break
            except Exception as e:
                print(f"  {sym} stooq {code} 失敗: {e}", file=sys.stderr)
            time.sleep(0.5)
        if got:
            series[sym] = {"d": got}
        time.sleep(0.4)
    for sym, ch in MIS_INTRA.items():
        prev = None
        d = series.get(sym, {}).get("d")
        if d and len(d["c"]) >= 2:
            prev = d["c"][-2]
        m = mis_intraday(ch, prev)
        if m:
            m["prev"] = prev
            series.setdefault(sym, {})["m"] = m
            print(f"  {sym} ← MIS 盤中({len(m['t'])} 點)")
        time.sleep(0.5)
    if len(series) < 6:
        print(f"::error::只取得 {len(series)} 檔(<6),放棄寫檔")
        sys.exit(1)
    doc = {"updated": datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
           "series": series}
    with open("yext.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"完成:{len(series)} 檔 → yext.json(零 Yahoo)")

if __name__ == "__main__":
    main()
