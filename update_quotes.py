# -*- coding: utf-8 -*-
"""
update_quotes.py v2 — 盤中報價快更(Yahoo 版,GitHub 機房可達)
只更新 data.json 的 price / chg / 加權指數 / 新聞,不動基本面與籌碼。
原理:Yahoo 的「當日日K」在盤中會即時跟著現價更新,批次抓最後一根即為最新價。
用法:pip install requests pandas yfinance && python update_quotes.py
"""
import json, time, datetime as dt
import requests

def main():
    import yfinance as yf
    with open("data.json", encoding="utf-8") as f:
        data = json.load(f)

    # 目標:全部台股 + 加權指數(美股盤中在台北時間為休市,由每日更新涵蓋)
    tw = [(s["id"], s.get("ex", "tse")) for s in data["stocks"] if s.get("market") == "TW"]
    idmap = {}
    for sid, ex in tw:
        idmap[f"{sid}.{'TW' if ex == 'tse' else 'TWO'}"] = sid
    tickers = list(idmap)

    n = 0
    for i in range(0, len(tickers), 150):
        chunk = tickers[i:i+150]
        try:
            df = yf.download(chunk, period="5d", interval="1d",
                             group_by="ticker", threads=True, progress=False,
                             auto_adjust=False)
            for tk in chunk:
                try:
                    sub = (df[tk] if len(chunk) > 1 else df)["Close"].dropna()
                    if len(sub) < 2: continue
                    last, prev = float(sub.iloc[-1]), float(sub.iloc[-2])
                    sid = idmap[tk]
                    for s in data["stocks"]:
                        if s["id"] == sid:
                            s["price"] = round(last, 2)
                            s["chg"] = round((last - prev) / prev * 100, 2) if prev else 0
                            n += 1
                            break
                except Exception:
                    continue
        except Exception as e:
            print(f"  [warn] 批次 {i//150+1}: {e}")
        time.sleep(1.0)

    try:  # 加權指數
        h = yf.Ticker("^TWII").history(period="5d")["Close"].dropna()
        if len(h) >= 2:
            v, p = float(h.iloc[-1]), float(h.iloc[-2])
            idx = data.setdefault("macro", {}).setdefault("idx", [])
            it = next((x for x in idx if "加權" in x.get("name", "")), None)
            if not it:
                it = {"name": "加權指數"}; idx.insert(0, it)
            it["val"], it["chg"] = round(v, 2), round((v - p) / p * 100, 2)
    except Exception as e:
        print(f"  [warn] 加權指數: {e}")

    taipei = dt.datetime.utcnow() + dt.timedelta(hours=8)
    data["intraday"] = taipei.strftime("%H:%M")

    try:  # 財經頭條
        import xml.etree.ElementTree as ET, html as H
        url = ("https://news.google.com/rss/search?"
               "q=%E5%8F%B0%E8%82%A1%20OR%20%E5%8F%B0%E7%A9%8D%E9%9B%BB%20OR%20%E7%BE%8E%E8%82%A1%20OR%20%E8%81%AF%E6%BA%96%E6%9C%83"
               "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
        root = ET.fromstring(requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).content)
        items = []
        for it in root.iter("item"):
            title = H.unescape(it.findtext("title") or "")
            parts = title.rsplit(" - ", 1)
            items.append({"title": parts[0], "source": parts[1] if len(parts) > 1 else "",
                          "link": it.findtext("link") or "#",
                          "time": (it.findtext("pubDate") or "")[5:16]})
            if len(items) >= 10: break
        if items: data["news"] = items
    except Exception as e:
        print(f"  [warn] 新聞: {e}")

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"盤中更新:{n} 檔 + 加權指數,台北 {data['intraday']}")

if __name__ == "__main__":
    main()
