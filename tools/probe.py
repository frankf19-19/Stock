"""一次性:探測新資料源(第 3 輪)"""
import os, json, requests, time
os.makedirs("probe_out", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (K-research personal dashboard)", "Accept": "*/*"}
def save(name, r=None, txt=None):
    with open(f"probe_out/{name}.txt", "w", encoding="utf-8") as f:
        if r is not None:
            f.write(f"STATUS {r.status_code}\nCT {r.headers.get('content-type')}\nLEN {len(r.content)}\n\n")
            f.write(r.content.decode("utf-8", errors="replace")[:12000])
        else: f.write(txt or "")
def req(name, m, url, **kw):
    h = dict(UA); h.update(kw.pop("headers", {}))
    try: r = requests.request(m, url, headers=h, timeout=60, **kw); save(name, r); return r
    except Exception as e: save(name, txt=f"ERR {e}")
for q in ("q1", "q2"):
    for y, mo, d in (("115", "10", "15"), ("105", "3", "15"), ("98", "3", "16")):
        req(f"mops_{q}_{y}", "POST", f"https://mopsov.twse.com.tw/mops/web/ajax_t56sb12_{q}",
            data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "year": y, "month": mo, "day": d}); time.sleep(4)
H = {"Accept": "application/json", "Content-Type": "application/json"}
req("finra_eq", "POST", "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest",
    json={"limit": 5, "compareFilters": [{"compareType": "equal", "fieldName": "settlementDate", "fieldValue": "2026-09-30"}],
          "domainFilters": [{"fieldName": "symbolCode", "values": ["AAPL", "NVDA", "SMCI"]}]}, headers=H)
r = req("finra_parts", "GET", "https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest", headers={"Accept": "application/json"})
try:
    p = [x["partitions"][0] for x in r.json()["availablePartitions"]]; save("finra_parts_sum", txt=f"{len(p)} {p[:2]} {p[-3:]}")
except Exception as e: save("finra_parts_sum", txt=str(e))
print("done")
