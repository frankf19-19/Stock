# -*- coding: utf-8 -*-
"""
update_quotes.py v3 — 盤中報價快更(零 Yahoo)
來源:證交所 MIS 官方即時(getStockInfo 批次);GitHub 機房被擋時自動借道
     自家 Cloudflare Worker(repo 的 proxy.json)。
產出:
  1. data.json:全台股 price/chg + 加權/櫃買指數 + 財經頭條(RSS,非Yahoo)
  2. spark.json:全市場「每5分鐘一點」的當日價格快照——盤後任何裝置都能畫當日走勢
用法:pip install requests && python update_quotes.py
"""
import json, time, datetime as dt
import urllib.parse
import requests

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/stock/index.jsp"}
BATCH = 80          # MIS 單次上限約百檔,取 80 保守
TP = dt.timezone(dt.timedelta(hours=8))

def proxy_url():
    # Worker 已停用:proxy.json 不存在屬正常,回空字串即可(改用 MIS 直連)
    import os
    if not os.path.exists("proxy.json"):
        return ""
    try:
        u = json.load(open("proxy.json", encoding="utf-8")).get("url", "").strip()
        return u if u.startswith("https://") else ""
    except Exception:
        return ""

PROXY = proxy_url()

def mis_get(ex_chs):
    """MIS getStockInfo 批次:直連 → 自家 Worker。回 msgArray 或 []。"""
    q = ("https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
         f"?ex_ch={'|'.join(ex_chs)}&json=1&delay=0&_={int(time.time()*1000)}")
    for url in ([q] + ([f"{PROXY}/?url=" + urllib.parse.quote(q, safe="")] if PROXY else [])):
        try:
            j = requests.get(url, headers=UA, timeout=20).json()
            arr = j.get("msgArray") or []
            if arr:
                return arr
        except Exception:
            continue
    return []

def px(m, key="z"):
    try:
        v = float(str(m.get(key, "-")).split("_")[0])
        return v if v > 0 else None
    except Exception:
        return None

def main():
    with open("data.json", encoding="utf-8") as f:
        data = json.load(f)
    tw = [(s["id"], s.get("ex", "tse")) for s in data["stocks"] if s.get("market") == "TW"]
    by_id = {s["id"]: s for s in data["stocks"]}
    now = dt.datetime.now(TP)

    # ── 1. 全台股報價(MIS 官方即時) ──
    n, quotes = 0, {}
    for i in range(0, len(tw), BATCH):
        chunk = tw[i:i + BATCH]
        arr = mis_get([f"{'otc' if ex == 'otc' else 'tse'}_{sid}.tw" for sid, ex in chunk])
        for m in arr:
            sid = str(m.get("c", "")).strip()
            s = by_id.get(sid)
            if not s:
                continue
            last = px(m, "z") or px(m, "b") or px(m, "y")   # 成交→買一→昨收
            prev = px(m, "y")
            if not last:
                continue
            s["price"] = round(last, 2)
            if prev:
                s["chg"] = round((last - prev) / prev * 100, 2)
            quotes[sid] = round(last, 2)
            n += 1
        time.sleep(0.4)

    # ── 2. 加權/櫃買指數 ──
    try:
        arr = mis_get(["tse_t00.tw", "otc_o00.tw"])
        idx = data.setdefault("macro", {}).setdefault("idx", [])
        for m in arr:
            last, prev = px(m, "z") or px(m, "b"), px(m, "y")
            if not (last and prev):
                continue
            name = "加權指數" if "t00" in str(m.get("ch", "")) else "櫃買指數"
            it = next((x for x in idx if name in x.get("name", "")), None)
            if not it:
                it = {"name": name}
                idx.insert(0, it)
            it["val"], it["chg"] = round(last, 2), round((last - prev) / prev * 100, 2)
    except Exception as e:
        print(f"  [warn] 指數: {e}")

    # ── 3. spark.json:盤中每輪累積一點(08:55~13:40),供盤後全裝置畫當日走勢 ──
    hm = now.hour * 60 + now.minute
    if 8 * 60 + 55 <= hm <= 13 * 60 + 40 and quotes:
        today = now.strftime("%Y-%m-%d")
        try:
            sp = json.load(open("spark.json", encoding="utf-8"))
            if sp.get("d") != today:
                sp = None
        except Exception:
            sp = None
        if not sp:
            sp = {"d": today, "t": [], "s": {}}
        L = len(sp["t"])
        sp["t"].append(int(now.timestamp()))
        for sid, v in quotes.items():
            arr = sp["s"].setdefault(sid, [None] * L)
            if len(arr) < L:
                arr += [None] * (L - len(arr))
            arr.append(v)
        for sid, arr in sp["s"].items():      # 本輪沒報到的補 null 對齊
            if len(arr) < L + 1:
                arr.append(None)
        with open("spark.json", "w", encoding="utf-8") as f:
            json.dump(sp, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  spark.json:第 {L+1} 點({len(sp['s'])} 檔)")

    data["intraday"] = now.strftime("%H:%M")

    # ── 4. 財經頭條(Google News RSS,非 Yahoo) ──
    try:
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
            if len(items) >= 10:
                break
        if items:
            data["news"] = items
    except Exception as e:
        print(f"  [warn] 新聞: {e}")

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"盤中更新:{n} 檔(MIS官方{'+Worker備援' if PROXY else ''}),台北 {data['intraday']}")
    if n < 100:
        print("::warning::報價取得偏少,MIS 直連與 Worker 皆可能受阻,請檢查")

if __name__ == "__main__":
    main()
