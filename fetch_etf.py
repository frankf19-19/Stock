"""主動式 ETF 每日持股 → etf_hold.json
====================================
來源:MoneyDJ ETF「持股明細」頁(格式統一,一個模板涵蓋全部主動式 ETF)。
原 fetch_etf_holdings 靠 Yahoo(已隨零 Yahoo 政策停用),本程式接手。

輸出 etf_hold.json:
  { "u":"2026-07-15", "h": { "00980A": {"top":[[代號,名稱,權重%,股數],...], "d":"2026/06/17"}, ... } }

主程式 update_data.py 讀此檔填入 s["hold"]["top"],_act_delta 據此算每日調倉。

排程建議:每交易日 18:00 一班(MoneyDJ 更新時間不固定,傍晚抓較穩)。
註:MoneyDJ 更新頻率非每日即時(常延遲數日),但一個來源涵蓋全部、格式穩定;
    要更即時可日後逐家接投信官網 PCF。抓不到的檔維持舊資料,不清空。
"""
import json, os, sys, re, time, html, datetime as dt
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
OUT = "etf_hold.json"
TODAY = dt.date.today()
# 完整持股頁(Basic0007B = 全部持股;Basic0007 = 前十大+產業)
URL = "https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={eid}.TW"
URL_TOP = "https://www.moneydj.com/etf/x/basic/basic0007.xdjhtm?etfid={eid}.TW"

def log(*a): print(*a, flush=True)

def numf(x):
    try: return float(str(x).replace(",", "").replace("%", "").strip())
    except Exception: return None

def active_etfs():
    with open("data.json", encoding="utf-8") as f:
        data = json.load(f)
    return [(s["id"], s["name"]) for s in data.get("stocks", [])
            if s.get("etf") and "主動" in s.get("name", "")]

# 解析 MoneyDJ 持股明細表格:每列 個股名稱(代號.TW) | 比例% | 股數
ROW_RE = re.compile(
    r'etfid=(\d{4,6}[A-Z]?)\.TW[^>]*>([^<]+)</a>'   # 代號 + 名稱(來自連結)
    r'.*?>\s*([\d.]+)\s*</td>'                       # 投資比例%
    r'\s*<td[^>]*>\s*([\d,]+(?:\.\d+)?)\s*</td>',    # 持有股數
    re.S)

def fetch_one(eid):
    last = None
    for url in (URL.format(eid=eid), URL_TOP.format(eid=eid)):
        try:
            r = requests.get(url, headers=UA, timeout=25)
            if not r.ok:
                last = f"HTTP {r.status_code}"; continue
            t = r.text
            # 資料日期(持股明細)
            md = re.search(r'持股明細[\s\S]{0,80}?資料日期[：:]\s*([\d/]+)', t) \
                 or re.search(r'資料日期[：:]\s*([\d/]+)', t)
            ddate = md.group(1) if md else None
            top = []
            for m in ROW_RE.finditer(t):
                sid, name, wt, sh = m.group(1), html.unescape(m.group(2)).strip(), numf(m.group(3)), numf(m.group(4))
                if not sid or wt is None: continue
                # 排除自我參照/重複
                if any(x[0] == sid for x in top): continue
                top.append([sid, name, round(wt, 2), int(sh) if sh else 0])
            if top:
                return {"top": top, "d": ddate or TODAY.isoformat()}, None
            last = "解析到 0 檔(頁面格式可能改版)"
        except Exception as e:
            last = str(e)
        time.sleep(0.4)
    return None, last

def main():
    etfs = active_etfs()
    log(f"主動式 ETF:{len(etfs)} 檔")
    prev = {}
    if os.path.exists(OUT):
        try: prev = json.load(open(OUT, encoding="utf-8")).get("h", {})
        except Exception: pass
    result = dict(prev)
    ok = 0
    for eid, nm in etfs:
        h, err = fetch_one(eid)
        if h and h.get("top"):
            result[eid] = h; ok += 1
            log(f"  ✓ {eid} {nm}:{len(h['top'])} 檔持股(資料日 {h['d']})")
        else:
            log(f"  · {eid} {nm}:未取得({err})——維持舊資料")
        time.sleep(0.8)   # 禮貌節奏,避免被 MoneyDJ 擋
    if ok == 0:
        log(f"✗ 0 檔成功,不覆寫 {OUT}(可能 MoneyDJ 改版或擋爬,把上方錯誤貼給我調整)")
        sys.exit(1)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"u": TODAY.isoformat(), "h": result}, f, ensure_ascii=False, separators=(",", ":"))
    log(f"✅ 寫出 {OUT}:本次 {ok} 檔更新,共 {len(result)} 檔")

if __name__ == "__main__":
    main()
