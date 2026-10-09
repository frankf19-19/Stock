"""FinMind 分點資料能力探測(r1053):分點統計表(可帶日期區間)多早有資料、一次能拿多長;整日 parquet 物件能不能下載"""
import os, json, time, requests
T = os.environ.get("FINMIND_TOKEN", "").strip(); H = {"Authorization": f"Bearer {T}"}
API = "https://api.finmindtrade.com/api/v4"
out = {}
def q(url, **p):
    t0 = time.time()
    try:
        p = {**p, "token": T}
        r = requests.get(url, params=p, timeout=120, allow_redirects=False)
        j = None
        try: j = r.json()
        except Exception: pass
        d = (j or {}).get("data") if isinstance(j, dict) else None
        return {"code": r.status_code, "sec": round(time.time() - t0, 1), "rows": len(d) if isinstance(d, list) else None,
                "msg": (j or {}).get("msg") if isinstance(j, dict) else r.text[:200], "first": d[0] if d else None,
                "dmin": min(x.get("date") for x in d) if d else None, "dmax": max(x.get("date") for x in d) if d else None,
                "loc": r.headers.get("Location", "")[:80], "len": len(r.content), "body": __import__("re").sub(r'"token_tail":"[^"]*"', '', r.text[:300])}
    except Exception as e:
        return {"err": str(e)[:200]}
# 券商清單(免費資料)→ 挑幾家測「依券商 × 日期區間」
try:
    r = requests.get(f"{API}/data", params={"dataset": "TaiwanSecuritiesTraderInfo", "token": T}, timeout=60).json().get("data") or []
    out["brokers_n"] = len(r); ids = [x.get("securities_trader_id") for x in r][:400]
    out["brokers_sample"] = [(x.get("securities_trader_id"), x.get("securities_trader")) for x in r[:5]]
except Exception as e: ids = []; out["brokers_err"] = str(e)[:100]
big = [i for i in ids if i in ("9800", "9A00", "1020", "5920", "9600")] or ids[:2]
for bid in big[:2]:
    for y in ("2016", "2019", "2021", "2023", "2025"):
        out[f"agg_{bid}_{y}-03"] = q(f"{API}/taiwan_stock_trading_daily_report_secid_agg", securities_trader_id=bid, start_date=f"{y}-03-01", end_date=f"{y}-03-31"); time.sleep(1)
    out[f"agg_{bid}_2025_year"] = q(f"{API}/taiwan_stock_trading_daily_report_secid_agg", securities_trader_id=bid, start_date="2025-01-01", end_date="2025-12-31")
    out[f"agg_{bid}_2330_2024_2026"] = q(f"{API}/taiwan_stock_trading_daily_report_secid_agg", securities_trader_id=bid, data_id="2330", start_date="2024-01-01", end_date="2026-10-08")
for y in ("2019", "2021", "2023", "2025"):
    out[f"data_agg_2330_{y}-03"] = q(f"{API}/data", dataset="TaiwanStockTradingDailyReportSecIdAgg", data_id="2330", start_date=f"{y}-03-01", end_date=f"{y}-03-31")
out["data_daily_2330_2021"] = q(f"{API}/data", dataset="TaiwanStockTradingDailyReport", data_id="2330", start_date="2021-03-02", end_date="2021-03-02")
out["data_daily_2330_2019"] = q(f"{API}/data", dataset="TaiwanStockTradingDailyReport", data_id="2330", start_date="2019-03-04", end_date="2019-03-04")
out["daily_2330_2020"] = q(f"{API}/taiwan_stock_trading_daily_report", data_id="2330", date="2020-03-02")
out["obj_2026-10-08"] = q(f"{API}/storage_objects", dataset="TaiwanStockTradingDailyReport", date="2026-10-08")
out["obj_2021-03-02"] = q(f"{API}/storage_objects", dataset="TaiwanStockTradingDailyReport", date="2021-03-02")
try:
    r = requests.get("https://api.web.finmindtrade.com/v2/user_info", params={"token": T}, timeout=30); j = r.json()
    out["user"] = {k: v for k, v in j.items() if k not in ("token", "email", "user_id", "username", "name")}
    out["token_len"] = len(T)
except Exception as e: out["user"] = str(e)[:100]
json.dump(out, open("fm_probe.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(out, ensure_ascii=False, indent=1, default=str)[:4000])
