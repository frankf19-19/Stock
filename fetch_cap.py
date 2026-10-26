"""每週抓取上市+上櫃公司實收資本額 → cap.json(約30KB)
讓前端秒讀股本,不再叫每個訪客的瀏覽器去搬證交所 1~2MB 的原始檔。
觸發:co_basic.yml(每週一排程 + 可手動);跑一次約 10 秒。"""
import json, os, datetime as dt
import requests

URLS = ["https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"]

def log(*a): print(*a, flush=True)

def main():
    d = {}; fresh = set()
    for u in URLS:
        try:
            arr = requests.get(u, timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (cap-fetch; personal dashboard)"}).json()
        except Exception as e:
            log(f"⚠ {u} 抓取失敗:{e}")
            continue
        if not isinstance(arr, list) or not arr:
            log(f"⚠ {u} 回應非預期"); continue
        keys = list(arr[0].keys())
        k = lambda *ns: next((x for x in keys if any(n in x for n in ns)), None)
        kid, kcap = k("公司代號"), k("實收資本額")
        if not kid or not kcap:
            log(f"⚠ {u} 找不到欄位(有:{keys[:8]}…)"); continue
        n0 = len(d)
        for r in arr:
            sid = str(r.get(kid, "")).strip()
            try: cap = float(str(r.get(kcap, "")).replace(",", ""))
            except ValueError: continue
            if sid and cap > 0:
                d[sid] = round(cap / 1e8, 1); fresh.add(sid)      # 元 → 億
        log(f"{u.split('/')[2]}:+{len(d)-n0} 檔")
    # r1177:櫃買 OpenAPI 常擋 GitHub 連線 → 上櫃 880 檔全缺股本(網站算不出市值)。
    #   備援 1:沿用上一版 cap.json 已有的;備援 2:FinMind TaiwanStockShareholding(外資持股表,含 NumberOfSharesIssued)
    #   用「已發行股數 × 10 元面額」換回實收資本額(億)。全市場一次查一天(date-only),往回找最近有資料的交易日。
    try:
        old = json.load(open("cap.json", encoding="utf-8")).get("c") or {}
        n0 = len(d)
        for k, v in old.items(): d.setdefault(k, v)
        if len(d) > n0: log(f"沿用上一版 cap.json:+{len(d)-n0} 檔")
    except Exception: pass
    tok = os.environ.get("FINMIND_TOKEN", "").strip()
    if tok:
        for back in range(0, 10):
            day = (dt.date.today() - dt.timedelta(days=back)).isoformat()
            try:
                j = requests.get("https://api.finmindtrade.com/api/v4/data", timeout=90,
                                 params={"dataset": "TaiwanStockShareholding", "start_date": day, "end_date": day},
                                 headers={"Authorization": f"Bearer {tok}"}).json()
            except Exception as e:
                log(f"⚠ FinMind {day}:{e}"); continue
            rows = j.get("data") or []
            if len(rows) < 500: continue
            n0 = len(d); upd = 0
            for r in rows:
                sid = str(r.get("stock_id", "")).strip(); sh = r.get("NumberOfSharesIssued")
                try: sh = float(sh)
                except (TypeError, ValueError): continue
                if not sid or sh <= 0: continue
                cap = round(sh * 10 / 1e8, 1)
                if sid not in d: d[sid] = cap
                elif abs(d[sid] - cap) / max(cap, 0.1) > 0.02 and sid not in fresh: d[sid] = cap; upd += 1   # 舊版沿用的值若已變動,以最新股數為準
            log(f"FinMind 已發行股數({day}):+{len(d)-n0} 檔、更新 {upd} 檔")
            break
    if len(d) < 300:
        log(f"✗ 僅取得 {len(d)} 檔,疑似來源異常,不覆寫 cap.json")
        raise SystemExit(1)
    out = {"u": dt.date.today().isoformat(), "c": d}
    with open("cap.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    log(f"完成:cap.json 共 {len(d)} 檔(單位:億)")

if __name__ == "__main__":
    main()
