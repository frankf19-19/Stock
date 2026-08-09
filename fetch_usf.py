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

UA = {"User-Agent": "MajiStock frankf19-19@users.noreply.github.com",
      "Accept": "application/json",
      "Accept-Encoding": "gzip, deflate"}

def _proxy_url():
    """repo 根目錄 proxy.json 的自家 Cloudflare Worker(無檔案=不借道)"""
    try:
        u = json.load(open("proxy.json", encoding="utf-8")).get("url", "").strip()
        return u.rstrip("/") if u.startswith("https://") else ""
    except Exception:
        return ""

def _fetch(url, timeout):
    req = urllib.request.Request(url, headers=UA)
    import gzip, io
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        return json.loads(raw.decode("utf-8", "replace"))

def get_json(url, timeout=15, retry=1):
    """r534 路由記憶版:每個主機記住「上次成功的路」優先走、剛失敗的路冷卻 10 分鐘;
    直連 15s/代理 25s 短逾時,不再讓單一請求最壞拖 5 分鐘(上次 20 分鐘被砍的主因)。"""
    import urllib.parse
    host = urllib.parse.urlsplit(url).netloc
    st = ROUTE_ST.setdefault(host, {"win": None, "dead": {}})
    q = urllib.parse.quote(url, safe="")
    routes = [("direct", url, timeout)]
    pu = _proxy_url()
    if pu:
        routes.append(("worker", pu + "/?url=" + q, timeout + 10))
    routes += [
        ("allorigins", "https://api.allorigins.win/raw?url=" + q, timeout + 10),
        ("corsproxy",  "https://corsproxy.io/?url=" + q,          timeout + 10),
        ("codetabs",   "https://api.codetabs.com/v1/proxy?quest=" + q, timeout + 10),
    ]
    now = time.time()
    live = [r for r in routes if now - st["dead"].get(r[0], 0) > 600]   # 冷卻 10 分鐘
    if not live: live = routes                                          # 全冷卻→重新全試
    live.sort(key=lambda r: 0 if r[0] == st["win"] else 1)              # 上次成功的路排最前
    err = None
    for name, u, to in live:
        tries = (retry + 1) if name == "direct" else 1
        for _ in range(tries):
            try:
                j = _fetch(u, to)
                if j is not None:
                    st["win"] = name
                    return j
            except Exception as e:
                err = e
        st["dead"][name] = time.time()
    print(f"  [warn] {url.split('/')[-1][:44]}: {err}", flush=True)
    return None

ROUTE_ST = {}
T0 = time.time()
DEADLINE = 14 * 60          # 全域時限:14 分鐘後停抓、用已到手的季度組檔(部分資料勝過整批全丟)

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
        print("data.json 無美股清單,中止", flush=True); return 1
    print(f"目標美股 {len(want)} 檔", flush=True)

    # 2) ticker ↔ CIK 對照(SEC 官方)
    mp = get_json("https://www.sec.gov/files/company_tickers.json")
    t2c = {}
    if mp:
        for v in mp.values():
            tk = str(v.get("ticker", "")).upper()
            if tk in want and tk not in t2c:
                t2c[tk] = int(v.get("cik_str"))
        try:  # 成功 → 回寫 repo 快取,日後 SEC 封 IP 也不斷炊(對照表變動極慢)
            json.dump(t2c, open("us_cik.json", "w"), separators=(",", ":"))
        except Exception:
            pass
    else:
        try:
            t2c = {k: int(v) for k, v in json.load(open("us_cik.json", encoding="utf-8")).items()}
            print(f"  對照表走 repo 快取 us_cik.json({len(t2c)} 檔)", flush=True)
        except Exception:
            pass
    if not t2c:
        print("對照表三路皆失敗(官方/Worker/快取),中止", flush=True); return 1
    c2t = {c: t for t, c in t2c.items()}
    print(f"對到 CIK:{len(t2c)} 檔(對不到者多為 ADR 別名/已下市,前端顯示不適用)", flush=True)

    # 3) frames 逐科目逐季
    qs = last_quarters(9)
    store = {t: {} for t in t2c}          # tk -> {"24Q3":{"rev":..}}
    cut = False
    for key, tag, unit in TAGS:
        if cut: break
        for (y, q) in qs:
            if time.time() - T0 > DEADLINE:
                print("  ⏱ 已達全域時限,以現有季度組檔", flush=True); cut = True; break
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
            print(f"  {tag[:34]:<34} CY{y}Q{q}: 命中 {hit}", flush=True)

    # 4) 組裝輸出(百萬美元、EPS 兩位小數;至少 4 季營收才收錄)
    # r551 增量合併:載入既有 usf.json,新資料「補洞不清舊」——每天收斂更完整,單次失敗不倒退
    try:
        prev = json.load(open("usf.json", encoding="utf-8")).get("s", {})
        for tk, pe in prev.items():
            if tk not in store: store[tk] = {}
            for i, lab in enumerate(pe.get("q", [])):
                cell = store[tk].setdefault(lab, {})
                for key, arr in (("rev", pe.get("rev")), ("gp", pe.get("gp")), ("oi", pe.get("oi")),
                                 ("ni", pe.get("ni")), ("eps", pe.get("eps"))):
                    if arr and i < len(arr) and arr[i] is not None and key not in cell:
                        cell[key] = arr[i] * (1e6 if key != "eps" else 1)
        print(f"  合併既有 usf.json:{len(prev)} 檔舊資料補洞", flush=True)
    except Exception:
        pass
    # r556:流通股數(dei 即期 frames)-> 前端市值熱力圖權重;近4個即期季由舊到新覆蓋取最新
    shares = {}
    for (y, q) in qs[-4:]:
        j = get_json(f"https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/CY{y}Q{q}I.json")
        time.sleep(0.25)
        if not j: continue
        hit = 0
        for row in j.get("data") or []:
            tk = c2t.get(int(row.get("cik", 0)))
            v = row.get("val")
            if tk and v and v > 0:
                shares[tk] = round(float(v) / 1e6, 1); hit += 1
        print(f"  SharesOutstanding CY{y}Q{q}I: hit {hit}", flush=True)
    try:
        for tk, pe in json.load(open("usf.json", encoding="utf-8")).get("s", {}).items():
            if tk not in shares and pe.get("sh"): shares[tk] = pe["sh"]
    except Exception:
        pass
    labs = sorted({lab for rows in store.values() for lab in rows} | {f"{y % 100}Q{q}" for (y, q) in qs})[-10:]
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
            if shares.get(tk): out_s[tk]["sh"] = shares[tk]
    for tk, sh in shares.items():   # 財報不足4季者也保留股數(熱力圖仍可用)
        out_s.setdefault(tk, {"q": [], "rev": [], "gp": [], "oi": [], "ni": [], "eps": []})["sh"] = sh
    out = {"updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "s": out_s}
    json.dump(out, open("usf.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"✅ usf.json 寫出:{len(out_s)} 檔有效(≥4 季營收)", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
