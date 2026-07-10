"""每週抓取上市+上櫃公司實收資本額 → cap.json(約30KB)
讓前端秒讀股本,不再叫每個訪客的瀏覽器去搬證交所 1~2MB 的原始檔。
觸發:co_basic.yml(每週一排程 + 可手動);跑一次約 10 秒。"""
import json, datetime as dt
import requests

URLS = ["https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"]

def log(*a): print(*a, flush=True)

def main():
    d = {}
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
                d[sid] = round(cap / 1e8, 1)      # 元 → 億
        log(f"{u.split('/')[2]}:+{len(d)-n0} 檔")
    if len(d) < 300:
        log(f"✗ 僅取得 {len(d)} 檔,疑似來源異常,不覆寫 cap.json")
        raise SystemExit(1)
    out = {"u": dt.date.today().isoformat(), "c": d}
    with open("cap.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    log(f"完成:cap.json 共 {len(d)} 檔(單位:億)")

if __name__ == "__main__":
    main()
