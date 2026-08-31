"""主動式 ETF 每日持股 → etf_hold.json + 每日快照分片 e/<代號>.json
================================================================
來源:MoneyDJ ETF「持股明細」頁(Basic0007B)+「基本資料」頁(Basic0004,取 ETF 規模)。

r748 重寫,修掉四個系統性解析錯誤:
  1. 舊版用全頁 regex,會把頁面自己的「盤中報價」連結當成第一名持股 → 每檔第一名都被吃掉。
     改成先把「個股名稱/投資比例/持有股數」那張表整塊切出來,只在表內解析。
  2. 舊版會抓到側欄「相關ETF」表(ETF代碼/市價/一日報酬%),把 0050 的市價 106.95 當成權重。
     表格隔離後自然消失,另外保留 0<=權重<=100 的防呆。
  3. MoneyDJ 的 HTTP header 沒宣告 charset(只在 meta 宣告 UTF-8),requests 會誤判成 latin-1
     → 中文全部變亂碼。改成明確指定 r.encoding="utf-8"。
  4. 舊版 d 存的是「抓取日」而非「資料日」,兩次抓到同一份快照會被當成新的一天。改存頁面的資料日期。
另補:ETF 規模(算張數/市值用,舊版一直是 None)、期貨/現金等非股票部位也收進來(標 k="f")。

輸出:
  etf_hold.json  {"u":抓取日,"h":{代號:{"d":資料日,"aum":規模元,"top":[[代號,名稱,權重%,股數,種類],...]}}}
  e/<代號>.json  {"id":代號,"d":[資料日...],"s":{代號:[[權重,股數],...]},"aum":[...],"nm":{代號:名稱}}
                 —— 每日快照歷史,保留最近 HIST_KEEP 個資料日,供前端算 1/2/3/5/10 日增減與連續加碼天數。

排程:每交易日傍晚一班(MoneyDJ 更新時間不固定,常延遲 1~3 日;抓不到的檔維持舊資料,不清空)。
"""
import json, os, sys, re, time, html, datetime as dt
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
OUT = "etf_hold.json"
HIST_DIR = "e"
HIST_KEEP = 20                      # 保留最近 20 個資料日(足夠算 10 日視窗)
TODAY = dt.date.today()
URL_HOLD = "https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={eid}.TW"
URL_INFO = "https://www.moneydj.com/ETF/X/Basic/Basic0004.xdjhtm?etfid={eid}.TW"

# 表內每一列:<a ...etfid=2330.TW...>台積電(2330.TW)</a> ... <td>9.29</td><td>11,264,000</td>
ROW_STOCK = re.compile(r'etfid=([0-9]{4,6}[A-Z]?)\.TW[^>]*>([^<]+)</a>', re.I)
# 期貨/其他非股票部位沒有 .TW 連結,例:台指期貨 2026/09(FITXN*1.TF)
ROW_OTHER = re.compile(r'>\s*([^<>]*?\(([A-Z0-9*]+)\.T[FW]\))\s*<', re.I)
NUM_TD = re.compile(r'<td[^>]*>\s*([\d,]+(?:\.\d+)?)\s*</td>', re.I)
TR_SPLIT = re.compile(r'<tr[^>]*>', re.I)


def log(*a): print(*a, flush=True)


def numf(x):
    try: return float(str(x).replace(",", "").replace("%", "").strip())
    except Exception: return None


def active_etfs():
    with open("data.json", encoding="utf-8") as f:
        data = json.load(f)
    return [(s["id"], s["name"]) for s in data.get("stocks", [])
            if s.get("etf") and "主動" in s.get("name", "")]


def get(url):
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    r.encoding = "utf-8"          # header 沒宣告 charset,不指定會被猜成 latin-1 → 中文亂碼
    return r.text


def holdings_block(t):
    """把「個股名稱/投資比例/持有股數」那張表整塊切出來(含巢狀表的深度配對)。"""
    i = t.find("個股名稱")
    if i < 0: return ""
    st = t.rfind("<table", 0, i)
    if st < 0: return ""
    depth, p, n = 0, st, len(t)
    while p < n:
        if t.startswith("<table", p): depth += 1; p += 6; continue
        if t.startswith("</table", p):
            depth -= 1; p += 7
            if depth == 0: return t[st:p]
            continue
        p += 1
    return ""


def parse_rows(block, eid):
    rows, seen = [], set()
    for tr in TR_SPLIT.split(block)[1:]:
        nums = [numf(x) for x in NUM_TD.findall(tr)]
        if len(nums) < 2: continue
        w, sh = nums[0], nums[1]
        if w is None or sh is None: continue
        if not (0 <= w <= 100) or sh <= 0: continue          # 防呆:權重必在 0~100
        m = ROW_STOCK.search(tr)
        if m:
            sid, kind = m.group(1), "s"
            if sid == eid: continue                          # ETF 自己的「盤中報價」連結,不是持股
            name = html.unescape(m.group(2)).strip()
        else:
            m2 = ROW_OTHER.search(tr)
            if not m2: continue
            sid, kind = m2.group(2).replace("*", ""), "f"     # 期貨/其他部位
            name = html.unescape(m2.group(1)).strip()
        name = re.sub(r'\([A-Z0-9*]{1,8}\.T[FW]\)', '', name).strip() or sid
        if sid in seen: continue
        seen.add(sid)
        rows.append([sid, name, round(w, 2), int(sh), kind])
    return rows


def fetch_aum(eid):
    """ETF 規模(元)與其資料日;取不到回 (None, None)。"""
    try:
        t = re.sub(r'<[^>]*>', ' ', get(URL_INFO.format(eid=eid)))
        m = re.search(r'ETF規模\s*([\d,]+\.?\d*)\s*\(百萬台幣\)\s*\((\d{4})/(\d{2})/(\d{2})\)', t)
        if not m: return None, None
        return int(round(float(m.group(1).replace(",", "")) * 1e6)), f"{m.group(2)}-{m.group(3)}-{m.group(4)}"
    except Exception:
        return None, None


def fetch_one(eid):
    try:
        t = get(URL_HOLD.format(eid=eid))
    except Exception as e:
        return None, str(e)
    block = holdings_block(t)
    if not block: return None, "找不到持股明細表(頁面可能改版)"
    rows = parse_rows(block, eid)
    if not rows: return None, "表格解析到 0 檔"
    md = re.search(r'資料日期[：:]\s*(\d{4})/(\d{2})/(\d{2})', t)
    ddate = f"{md.group(1)}-{md.group(2)}-{md.group(3)}" if md else TODAY.isoformat()
    aum, _ = fetch_aum(eid)
    return {"top": rows, "d": ddate, "aum": aum}, None


def save_hist(eid, rec):
    """把當日快照併進 e/<代號>.json(以資料日為鍵,同一日只留一份)。"""
    os.makedirs(HIST_DIR, exist_ok=True)
    path = os.path.join(HIST_DIR, f"{eid}.json")
    try:
        J = json.load(open(path, encoding="utf-8"))
        if J.get("id") != eid: raise ValueError
    except Exception:
        J = {"id": eid, "d": [], "s": {}, "aum": [], "nm": {}}
    d = rec["d"]
    if d in J["d"]:                                   # 同一資料日重跑 → 覆蓋該格
        k = J["d"].index(d)
    else:
        J["d"].append(d); k = len(J["d"]) - 1
        J["aum"].append(None)
        for v in J["s"].values(): v.append(None)
    while len(J["aum"]) < len(J["d"]): J["aum"].append(None)
    J["aum"][k] = rec.get("aum")
    for sym, name, w, sh, kind in rec["top"]:
        if sym not in J["s"]: J["s"][sym] = [None] * len(J["d"])
        while len(J["s"][sym]) < len(J["d"]): J["s"][sym].append(None)
        J["s"][sym][k] = [w, sh]
        J["nm"][sym] = name
    for v in J["s"].values():
        while len(v) < len(J["d"]): v.append(None)
    if len(J["d"]) > HIST_KEEP:                       # 只留最近 HIST_KEEP 天
        cut = len(J["d"]) - HIST_KEEP
        J["d"] = J["d"][cut:]; J["aum"] = J["aum"][cut:]
        for sym in list(J["s"]):
            J["s"][sym] = J["s"][sym][cut:]
            if not any(x for x in J["s"][sym]):        # 期間內完全沒持有 → 移除
                del J["s"][sym]; J["nm"].pop(sym, None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(J, f, ensure_ascii=False, separators=(",", ":"))
    return len(J["d"])


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
            n = save_hist(eid, h)
            wsum = round(sum(r[2] for r in h["top"]), 1)
            log(f"  ✓ {eid} {nm}:{len(h['top'])} 檔 權重和 {wsum}% "
                f"規模 {(h['aum']/1e8):.0f} 億 資料日 {h['d']}(歷史 {n} 天)"
                if h.get("aum") else
                f"  ✓ {eid} {nm}:{len(h['top'])} 檔 權重和 {wsum}% 規模 — 資料日 {h['d']}(歷史 {n} 天)")
        else:
            log(f"  · {eid} {nm}:未取得({err})——維持舊資料")
        time.sleep(0.8)
    if ok == 0:
        log(f"✗ 0 檔成功,不覆寫 {OUT}(可能 MoneyDJ 改版或擋爬)")
        sys.exit(1)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"u": TODAY.isoformat(), "h": result}, f, ensure_ascii=False, separators=(",", ":"))
    log(f"✅ 寫出 {OUT}:本次 {ok} 檔更新,共 {len(result)} 檔;快照歷史寫入 {HIST_DIR}/")


if __name__ == "__main__":
    main()
