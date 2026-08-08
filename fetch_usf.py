#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股基本面抓取器 r530 —— SEC EDGAR 官方 XBRL frames API(免費、免金鑰、官方源)
frames 一個請求=全市場一個科目一季,6 科目 × 9 季 ≈ 55 個請求跑完 538 檔。
科目:營收(兩種常用標籤聯集)、毛利、營業利益、稅後淨利、稀釋 EPS。
注意:會計年度未對齊日曆季的公司(SEC 以「最接近的日曆季」歸檔,差距數日內仍會納入;
      差距大者該季缺值,前端以可得季度呈現)。
輸出 usf.json:{"updated":ISO,"s":{"AAPL":{"q":["24Q3",...],"rev":[百萬],"gp":[],"oi":[],"ni":[],"eps":[]}}}
"""
import json, time, datetime, urllib.request, sys

UA = {"User-Agent": "MajiStockLab/1.0 (research; frankf19-19@users.noreply.github.com)",
      "Accept-Encoding": "gzip, deflate"}

def get_json(url, timeout=40, retry=2):
    for i in range(retry + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            import gzip, io
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                return json.loads(raw.decode("utf-8", "replace"))
        except Exception as e:
            if i == retry: print(f"  [warn] {url.split('/')[-1][:40]}: {e}")
            time.sleep(1.2 * (i + 1))
    return None

def last_quarters(n=9):
    """最近 n 個「已結束」的日曆季,舊→新,如 [(2024,2),...,(2026,2)]"""
    t = datetime.date.today()
    y, q = t.year, (t.month - 1) // 3 + 1      # 當前(未結束)季
    out = []
    for _ in range(n):
        q -= 1
        if q == 0: y, q = y - 1, 4
        out.append((y, q))
    return out[::-1]

TAGS = [  # (輸出鍵, us-gaap 標籤, 單位)
    ("rev", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
    ("rev", "Revenues", "USD"),                       # 舊制/金融業常用,補缺不覆蓋
    ("gp",  "GrossProfit", "USD"),
    ("oi",  "OperatingIncomeLoss", "USD"),
    ("ni",  "NetIncomeLoss", "USD"),
    ("eps", "EarningsPerShareDiluted", "USD-per-shares"),
]

def main():
    # 1) 目標清單:data.json 的美股 id
    try:
        data = json.load(open("data.json", encoding="utf-8"))
        want = {s["id"].upper() for s in data.get("stocks", []) if s.get("market") == "US"}
    except Exception:
        want = set()
    if not want:
        print("data.json 無美股清單,中止"); return 1
    print(f"目標美股 {len(want)} 檔")

    # 2) ticker ↔ CIK 對照(SEC 官方)
    mp = get_json("https://www.sec.gov/files/company_tickers.json")
    if not mp: print("對照表抓取失敗"); return 1
    t2c = {}
    for v in mp.values():
        tk = str(v.get("ticker", "")).upper()
        if tk in want and tk not in t2c:
            t2c[tk] = int(v.get("cik_str"))
    c2t = {c: t for t, c in t2c.items()}
    print(f"對到 CIK:{len(t2c)} 檔(對不到者多為 ADR 別名/已下市,前端顯示不適用)")

    # 3) frames 逐科目逐季
    qs = last_quarters(9)
    store = {t: {} for t in t2c}          # tk -> {"24Q3":{"rev":..}}
    for key, tag, unit in TAGS:
        for (y, q) in qs:
            j = get_json(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/{unit}/CY{y}Q{q}.json")
            time.sleep(0.25)
            if not j: continue
            lab = f"{y % 100}Q{q}"
            hit = 0
            for row in j.get("data") or []:
                tk = c2t.get(int(row.get("cik", 0)))
                if not tk: continue
                v = row.get("val")
                if v is None: continue
                cell = store[tk].setdefault(lab, {})
                if key not in cell:                 # 營收兩標籤:先到先贏,不互相覆蓋
                    cell[key] = float(v); hit += 1
            print(f"  {tag[:34]:<34} CY{y}Q{q}: 命中 {hit}")

    # 4) 組裝輸出(百萬美元、EPS 兩位小數;至少 4 季營收才收錄)
    labs = [f"{y % 100}Q{q}" for (y, q) in qs]
    out_s = {}
    for tk, rows in store.items():
        q_l, rev, gp, oi, ni, eps = [], [], [], [], [], []
        for lab in labs:
            c = rows.get(lab)
            if not c or c.get("rev") is None: continue
            q_l.append(lab)
            rev.append(round(c["rev"] / 1e6, 1))
            gp.append(round(c["gp"] / 1e6, 1) if c.get("gp") is not None else None)
            oi.append(round(c["oi"] / 1e6, 1) if c.get("oi") is not None else None)
            ni.append(round(c["ni"] / 1e6, 1) if c.get("ni") is not None else None)
            eps.append(round(c["eps"], 2) if c.get("eps") is not None else None)
        if len(q_l) >= 4:
            out_s[tk] = {"q": q_l, "rev": rev, "gp": gp, "oi": oi, "ni": ni, "eps": eps}
    out = {"updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "s": out_s}
    json.dump(out, open("usf.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"✅ usf.json 寫出:{len(out_s)} 檔有效(≥4 季營收)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
