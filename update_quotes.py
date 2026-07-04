# -*- coding: utf-8 -*-
"""
update_quotes.py — 盤中即時報價快更
用證交所 MIS 即時 API(mis.twse.com.tw)只更新 data.json 內的
price / chg / 加權指數,不動基本面與籌碼欄位。輕量、10 秒內跑完。

搭配 .github/workflows/update_quotes.yml:
開盤時段(台北 09:00–13:50)每 10 分鐘自動執行並 commit,
網頁端每 3 分鐘重抓 data.json,即可在開盤時看到接近即時的報價。

用法:pip install requests && python update_quotes.py
"""
import json, datetime as dt
import requests

MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"


def to_f(v):
    try:
        v = str(v).split("_")[0]
        return float(v) if v not in ("", "-") else None
    except (TypeError, ValueError):
        return None


def last_price(m):
    """成交價 z 為主;尚無成交時退而用最佳買價 b、再退昨收 y。"""
    for key in ("z", "b", "y"):
        v = to_f(m.get(key))
        if v:
            return v
    return None


def main():
    with open("data.json", encoding="utf-8") as f:
        data = json.load(f)

    tw = [(s["id"], s.get("ex", "tse")) for s in data["stocks"] if s.get("market") == "TW"]
    # 依上市/上櫃標記精準查詢(全市場約1800檔,分批每批40檔)
    chans = ["tse_t00.tw"] + [f"{'tse' if ex=='tse' else 'otc'}_{sid}.tw" for sid, ex in tw]

    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0"
    sess.get("https://mis.twse.com.tw/stock/index.jsp", timeout=15)  # 取得 session cookie

    quotes = {}
    import time as _t
    for i in range(0, len(chans), 40):
        try:
            r = sess.get(MIS, params={"ex_ch": "|".join(chans[i:i + 40]),
                                      "json": "1", "delay": "0"}, timeout=15)
            for m in r.json().get("msgArray", []):
                if m.get("c") and m.get("y"):
                    quotes[m["c"]] = m
        except Exception as e:
            print(f"  [warn] 批次 {i//40+1}: {e}")
        _t.sleep(0.3)

    n = 0
    for s in data["stocks"]:
        m = quotes.get(s["id"])
        if not m:
            continue
        last, y = last_price(m), to_f(m.get("y"))
        if last and y:
            s["price"] = round(last, 2)
            s["chg"] = round((last - y) / y * 100, 2)
            n += 1

    m = quotes.get("t00")  # 加權指數
    if m:
        last, y = last_price(m), to_f(m.get("y"))
        if last and y:
            idx = data.setdefault("macro", {}).setdefault("idx", [])
            it = next((x for x in idx if "加權" in x.get("name", "")), None)
            if not it:
                it = {"name": "加權指數"}
                idx.insert(0, it)
            it["val"], it["chg"] = round(last, 2), round((last - y) / y * 100, 2)

    taipei = dt.datetime.utcnow() + dt.timedelta(hours=8)
    data["intraday"] = taipei.strftime("%H:%M")

    # 順手更新財經頭條(Google News RSS,免費)
    try:
        import xml.etree.ElementTree as ET, html as H
        url = ("https://news.google.com/rss/search?"
               "q=%E5%8F%B0%E8%82%A1%20OR%20%E5%8F%B0%E7%A9%8D%E9%9B%BB%20OR%20%E7%BE%8E%E8%82%A1%20OR%20%E8%81%AF%E6%BA%96%E6%9C%83"
               "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
        root = ET.fromstring(requests.get(url, timeout=20).content)
        items = []
        for it in root.iter("item"):
            title = H.unescape(it.findtext("title") or "")
            parts = title.rsplit(" - ", 1)
            items.append({"title": parts[0], "source": parts[1] if len(parts) > 1 else "",
                          "link": it.findtext("link") or "#",
                          "time": (it.findtext("pubDate") or "")[5:16]})
            if len(items) >= 10:
                break
        if items:
            data["news"] = items
    except Exception as e:
        print(f"  [warn] 新聞: {e}")

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"盤中更新完成:{n} 檔個股 + 加權指數,台北時間 {data['intraday']}")


if __name__ == "__main__":
    main()
