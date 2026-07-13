#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
國際行情抓取器(取代前端 Yahoo 直連)
伺服器端執行(GitHub Actions),無 CORS 問題、無需代理,天生穩定。
產出 yext.json:14 檔指數/期貨/匯率的「當日分線 + 六個月日線」。
前端 yChart() 同源讀取此檔,瀏覽器端零 Yahoo 請求。
"""
import json, time, datetime, sys

SYMS = ["^TWII","^TWOII","^GSPC","^IXIC","^SOX","^DJI","^N225","^VIX",
        "ES=F","NQ=F","EWT","TWD=X","JPYTWD=X","DX-Y.NYB",
        "^TNX","^FVX","^TYX",          # 美債殖利率:10年/5年/30年
        "EURTWD=X","JPY=X"]            # 歐元/台幣、美元/日圓

def fetch_sym(t, sym):
    out = {}
    try:  # 當日(或最近交易日)分線
        h = t.history(period="1d", interval="1m")
        if h is None or len(h) < 3:
            h = t.history(period="1d", interval="5m")
        if h is not None and len(h) >= 3:
            hh = h.dropna(subset=["Close"])
            ts = [int(x.timestamp()) for x in hh.index]
            cs = [round(float(c), 4) for c in hh["Close"]]
            # 瘦身:超過 400 點做等距抽樣
            if len(ts) > 400:
                step = len(ts) / 400.0
                idx = [int(i * step) for i in range(400)]
                ts = [ts[i] for i in idx]; cs = [cs[i] for i in idx]
            out["m"] = {"t": ts, "c": cs}
    except Exception as e:
        print(f"  {sym} 分線失敗: {e}", file=sys.stderr)
    try:  # 六個月日線
        d = t.history(period="6mo", interval="1d")
        if d is not None and len(d) >= 5:
            dd = d.dropna(subset=["Close"])
            out["d"] = {"t": [int(x.timestamp()) for x in dd.index],
                        "c": [round(float(c), 4) for c in dd["Close"]]}
            if "m" in out:
                out["m"]["prev"] = out["d"]["c"][-2] if len(dd) >= 2 else None
    except Exception as e:
        print(f"  {sym} 日線失敗: {e}", file=sys.stderr)
    return out or None

def main():
    import yfinance as yf
    series = {}
    for sym in SYMS:
        print(f"抓取 {sym} …")
        for attempt in range(2):
            try:
                got = fetch_sym(yf.Ticker(sym), sym)
                if got:
                    series[sym] = got
                    break
            except Exception as e:
                print(f"  {sym} 第{attempt+1}次失敗: {e}", file=sys.stderr)
            time.sleep(2)
        time.sleep(0.6)  # 溫柔限速
    if len(series) < 6:
        print(f"::error::只抓到 {len(series)} 檔(<6),放棄寫檔以免覆蓋好資料")
        sys.exit(1)
    doc = {"updated": datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
           "series": series}
    with open("yext.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"完成:{len(series)}/{len(SYMS)} 檔 → yext.json")

if __name__ == "__main__":
    main()
