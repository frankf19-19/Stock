"""一次性:探測新資料源(第 2 輪)"""
import os, json, requests, time
os.makedirs("probe_out", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (K-research personal dashboard; frankccc199@gmail.com)", "Accept": "*/*"}
def save(name, r=None, txt=None):
    with open(f"probe_out/{name}.txt", "w", encoding="utf-8") as f:
        if r is not None:
            f.write(f"STATUS {r.status_code}\nCT {r.headers.get('content-type')}\nLEN {len(r.content)}\n\n")
            ct = (r.headers.get("content-type") or "").lower()
            enc = "big5" if ("950" in ct or "big5" in ct) else "utf-8"
            f.write(r.content.decode(enc, errors="replace")[:5000])
        else: f.write(txt or "")
def req(name, m, url, **kw):
    h = dict(UA); h.update(kw.pop("headers", {}))
    try: r = requests.request(m, url, headers=h, timeout=60, **kw); save(name, r); return r
    except Exception as e: save(name, txt=f"ERR {e}")
# MOPS 申報轉讓(舊版 ajax 參數猜測)
base = {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii"}
for i, extra in enumerate([{"year": "115", "month": "09", "day": "01"}, {"date1": "1150901", "date2": "1150930"},
                           {"begin_date": "1150901", "end_date": "1150930"}, {"sdate": "115/09/01", "edate": "115/09/30"},
                           {"year": "115", "smonth": "09", "emonth": "09", "sday": "01", "eday": "30"}, {"step": 0}]):
    req(f"mops_v{i}", "POST", "https://mopsov.twse.com.tw/mops/web/ajax_t56sb12", data={**base, **extra}); time.sleep(3)
req("mops_new_page", "GET", "https://mops.twse.com.tw/mops/api/redirectToOld?apiName=ajax_t56sb12")
req("mops_new_api", "POST", "https://mops.twse.com.tw/mops/api/t56sb12", json={"companyId": "", "year": "115", "month": "9", "marketKind": "sii"})
# TAIFEX 歷史深度
for d in ["2016/01/04", "2020/01/06", "2023/10/02"]:
    req(f"taifex_{d[:4]}", "POST", "https://www.taifex.com.tw/cht/3/optDataDown",
        data={"down_type": "1", "commodity_id": "TXO", "commodity_id2": "", "queryStartDate": d, "queryEndDate": d}); time.sleep(3)
# FinMind 景氣指標
tok = os.environ.get("FINMIND_TOKEN", "")
req("fm_business", "GET", "https://api.finmindtrade.com/api/v4/data", params={"dataset": "TaiwanBusinessIndicator", "start_date": "1980-01-01", "token": tok})
# NDC JSON 猜測
req("ndc_json1", "POST", "https://index.ndc.gov.tw/n/json/data/eco/indicators", headers={"X-Requested-With": "XMLHttpRequest", "Referer": "https://index.ndc.gov.tw/n/zh_tw/data/eco"})
req("ndc_json2", "GET", "https://index.ndc.gov.tw/n/json/data/eco/indicators")
# FINRA:過濾與最新資料
req("finra_post", "POST", "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest",
    json={"limit": 5, "compareFilters": [{"compareType": "equal", "fieldName": "symbolCode", "fieldValue": "AAPL"}],
          "sortFields": ["-settlementDate"]}, headers={"Accept": "application/json", "Content-Type": "application/json"})
req("finra_post_date", "POST", "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest",
    json={"limit": 3, "dateRangeFilters": [{"fieldName": "settlementDate", "startDate": "2015-01-01", "endDate": "2016-01-31"}]},
    headers={"Accept": "application/json", "Content-Type": "application/json"})
req("finra_partitions", "GET", "https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest", headers={"Accept": "application/json"})
print("done")
