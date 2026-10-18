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
import re
summ = []
for y, mo, d in (("115","7","15"),("115","1","15"),("114","7","15"),("114","1","15"),("113","7","16"),("113","1","16"),("112","7","14"),("111","7","15"),("110","7","15"),("108","7","15")):
    try:
        r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t56sb12", headers=UA, timeout=60,
            data={"encodeURIComponent": 1, "run": "", "step": 2, "year": y, "month": mo, "day": d, "report": "SY", "firstin": "true"})
        m = re.search(r"總計：(\d+)筆", r.text); summ.append(f"{y}/{mo}/{d} {r.status_code} {'無' if '無持股轉讓' in r.text else (m.group(1) if m else '?')}")
    except Exception as e: summ.append(f"{y}/{mo}/{d} ERR {e}")
    time.sleep(4)
save("mops_depth", txt="\n".join(summ))
req("mops_sb21q3_page", "GET", "https://mopsov.twse.com.tw/mops/web/t56sb21_q3")
req("mops_sb21q3", "POST", "https://mopsov.twse.com.tw/mops/web/ajax_t56sb21",
    data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": "113", "month": "7", "day": "16"})
H = {"Accept": "application/json", "Content-Type": "application/json"}
r = req("finra_parts", "GET", "https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest", headers={"Accept": "application/json"})
try:
    p = [x["partitions"][0] for x in r.json()["availablePartitions"]]; save("finra_parts_sum", txt=f"{len(p)} {p[:2]} {p[-3:]}")
except Exception as e: save("finra_parts_sum", txt=str(e))
print("done")
