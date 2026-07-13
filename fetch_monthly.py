#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
月K庫產生器:為 data.json 裡每一檔股票抓「上市以來全歷史月K」,
寫入 m/{id}.json = {"d":["YYYY-MM",...],"k":[[開,高,低,收,量(張)],...]}
伺服器端執行(GitHub Actions),前端同源讀取——K線月K/全部區間與
歷史月份行情(季節性)從此不再依賴 Yahoo 瀏覽器端請求。
每月跑一次即可(月K一個月才長一根);首次執行會回補全歷史,約 40 分鐘。
"""
import json, os, time, sys, datetime

def main():
    import yfinance as yf
    data = json.load(open("data.json", encoding="utf-8"))
    stocks = data.get("stocks", [])
    os.makedirs("m", exist_ok=True)
    ok = skip = fail = 0
    for idx, s in enumerate(stocks):
        sid = s.get("id"); mkt = s.get("market")
        if not sid: continue
        path = f"m/{sid}.json"
        # 30 天內更新過就跳過(重跑/續跑友善)
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < 30*86400:
            skip += 1; continue
        if mkt == "TW":
            syms = [f"{sid}.TW", f"{sid}.TWO"] if s.get("ex") != "otc" else [f"{sid}.TWO", f"{sid}.TW"]
        else:
            syms = [sid]
        got = None
        for sym in syms:
            try:
                h = yf.Ticker(sym).history(period="max", interval="1mo", auto_adjust=False)
                if h is not None and len(h) >= 3:
                    h = h.dropna(subset=["Close"])
                    got = h; break
            except Exception:
                pass
            time.sleep(0.4)
        if got is None:
            fail += 1
            print(f"  ✗ {sid} {s.get('name','')}", file=sys.stderr)
        else:
            d, k = [], []
            for ts, row in got.iterrows():
                if row["Open"] != row["Open"]:  # NaN
                    continue
                d.append(f"{ts.year}-{ts.month:02d}")
                vol = row.get("Volume", 0) or 0
                k.append([round(float(row["Open"]),2), round(float(row["High"]),2),
                          round(float(row["Low"]),2),  round(float(row["Close"]),2),
                          int(vol/1000) if mkt=="TW" else int(vol)])
            json.dump({"d": d, "k": k}, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))
            ok += 1
        time.sleep(0.5)                       # 溫柔限速
        if idx % 100 == 99: time.sleep(5)     # 每百檔多歇 5 秒
        if idx % 200 == 0:
            print(f"進度 {idx+1}/{len(stocks)}(成功{ok} 略過{skip} 失敗{fail})")
    print(f"完成:成功 {ok}、略過 {skip}、失敗 {fail}")
    if ok + skip < 50:
        print("::error::產出過少,標記失敗"); sys.exit(1)

if __name__ == "__main__":
    main()
