"""一次性回補:FinMind 股權分散表 → tdcc.json(v2, 9組級距, 近~18週)
用法:GitHub Actions 手動觸發 backfill_tdcc.yml;約 3~4 小時(免費速率 600/hr)。"""
import json, os, re, time, datetime as dt
import requests

TOK = os.environ.get("FINMIND_TOKEN", "")
START = (dt.date.today() - dt.timedelta(days=130)).isoformat()

def lv_group(label):
    """FinMind 級距標籤 → 9 組索引(以級距下限股數判斷)"""
    digs = re.findall(r"[\d,]+", str(label))
    lo = int(digs[0].replace(",", "")) if digs else 0
    if lo >= 1000001: return 0      # L15 >1000張
    if lo >= 800001:  return 1      # L14
    if lo >= 600001:  return 2      # L13
    if lo >= 400001:  return 3      # L12
    if lo >= 200001:  return 4      # L11
    if lo >= 100001:  return 5      # L10
    if lo >= 50001:   return 6      # L9
    if lo >= 40001:   return 7      # L8
    return 8                        # L1-7(含「差異數調整」等雜項歸此,占比~0)

def main():
    with open("data.json", encoding="utf-8") as f:
        stocks = [s["id"] for s in json.load(f)["stocks"]
                  if s.get("market") == "TW" and not s.get("etf")]
    J = {"v": 2, "d": [], "s": {}}
    dates_seen = set()
    print(f"回補 {len(stocks)} 檔,起日 {START}")
    for k, sid in enumerate(stocks, 1):
        for attempt in range(2):
            try:
                p = {"dataset": "TaiwanStockHoldingSharesPer",
                     "data_id": sid, "start_date": START}
                if TOK: p["token"] = TOK
                r = requests.get("https://api.finmindtrade.com/api/v4/data",
                                 params=p, timeout=45)
                j = r.json()
                if j.get("status") == 402 or "level" in str(j.get("msg", "")).lower():
                    print(f"  [止] 速率/權限:{j.get('msg')} — 休息 10 分鐘")
                    time.sleep(600); continue
                wk = {}
                for row in j.get("data") or []:
                    d = row.get("date"); g = wk.setdefault(d, [0.0]*9)
                    lab = row.get("HoldingSharesLevel", "")
                    if "調整" in str(lab): continue
                    g[lv_group(lab)] += float(row.get("percent") or 0)
                for d, g in wk.items():
                    dates_seen.add(d)
                    J["s"].setdefault(sid, {})[d] = [round(x, 2) for x in g]
                break
            except Exception as e:
                if attempt: print(f"  [跳過] {sid}: {e}")
                else: time.sleep(8)
        if k % 100 == 0: print(f"  進度 {k}/{len(stocks)}")
        time.sleep(6.1)                          # 免費速率 600/hr 保險
    J["d"] = sorted(dates_seen)[-26:]
    for sid in list(J["s"].keys()):
        J["s"][sid] = [J["s"][sid].get(d) for d in J["d"]]
    with open("tdcc.json", "w", encoding="utf-8") as f:
        json.dump(J, f, ensure_ascii=False, separators=(",", ":"))
    print(f"完成:{len(J['d'])} 週 × {len(J['s'])} 檔")

if __name__ == "__main__":
    main()
