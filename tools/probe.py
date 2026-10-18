"""一次性:探測新資料源的格式(輸出到 probe_out/,不影響網站)"""
import os, json, requests, io, zipfile, re, time
os.makedirs("probe_out", exist_ok=True)
UA = {"User-Agent": "K-research personal dashboard frankccc199@gmail.com", "Accept": "*/*"}
def save(name, r=None, txt=None, extra=""):
    with open(f"probe_out/{name}.txt", "w", encoding="utf-8") as f:
        if r is not None:
            f.write(f"STATUS {r.status_code}\nCT {r.headers.get('content-type')}\nLEN {len(r.content)}\n{extra}\n")
            try: t = r.content.decode("utf-8")
            except Exception:
                try: t = r.content.decode("big5", errors="replace")
                except Exception: t = repr(r.content[:2000])
            f.write(t[:6000])
        else: f.write(txt or "")
def get(name, url, **kw):
    try: r = requests.get(url, headers=UA, timeout=60, **kw); save(name, r); return r
    except Exception as e: save(name, txt=f"ERR {e}")
def post(name, url, **kw):
    try: r = requests.post(url, headers=UA, timeout=60, **kw); save(name, r); return r
    except Exception as e: save(name, txt=f"ERR {e}")

# ── TW 內部人 ──
r = get("twse_swagger", "https://openapi.twse.com.tw/v1/swagger.json")
try:
    sw = r.json(); hits = [(p, json.dumps(v, ensure_ascii=False)[:200]) for p, v in sw.get("paths", {}).items()]
    save("twse_paths", txt="\n".join(f"{p} {d}" for p, d in hits))
except Exception as e: save("twse_paths", txt=str(e))
r = get("tpex_swagger", "https://www.tpex.org.tw/openapi/swagger.json")
try:
    sw = r.json(); save("tpex_paths", txt="\n".join(f"{p} {json.dumps(v, ensure_ascii=False)[:200]}" for p, v in sw.get("paths", {}).items()))
except Exception as e: save("tpex_paths", txt=str(e))
for ds in (20767, 20768, 22813, 22814, 31564):
    get(f"dgov_{ds}", f"https://data.gov.tw/api/v2/rest/dataset/{ds}")
post("mops_t56sb12", "https://mopsov.twse.com.tw/mops/web/ajax_t56sb12",
     data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": "115", "month": "9"})
get("mops_t56sb12_page", "https://mopsov.twse.com.tw/mops/web/t56sb12")
# ── SEC ──
get("sec_form345_page", "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets")
get("sec_sub_aapl", "https://data.sec.gov/submissions/CIK0000320193.json")
for u in ["https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2026q2_form345.zip",
          "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2026q1_form345.zip"]:
    try:
        r = requests.get(u, headers=UA, timeout=120)
        info = ""
        if r.ok:
            z = zipfile.ZipFile(io.BytesIO(r.content)); info = "FILES " + str([(i.filename, i.file_size) for i in z.infolist()])
            for fn in z.namelist():
                if fn.endswith(".tsv"): info += f"\n== {fn}\n" + z.read(fn)[:1500].decode("utf-8", "replace")
        save("sec_zip_" + u[-18:-12], r, extra=info)
    except Exception as e: save("sec_zip_" + u[-18:-12], txt=str(e))
# ── TAIFEX 選擇權 ──
post("taifex_opt", "https://www.taifex.com.tw/cht/3/optDataDown",
     data={"down_type": "1", "commodity_id": "TXO", "commodity_id2": "", "queryStartDate": "2026/10/15", "queryEndDate": "2026/10/16"})
get("taifex_opt_hist_page", "https://www.taifex.com.tw/cht/3/dlOptDataDown")
# ── 國發會 ──
get("ndc_index", "https://index.ndc.gov.tw/n/zh_tw/data/eco")
# ── FRED ──
for s in ["BAMLH0A0HYM2", "BAA10Y", "T10Y3M", "NFCI", "STLFSI4", "VIXCLS"]:
    try:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}", headers=UA, timeout=60)
        lines = r.text.strip().splitlines()
        save(f"fred_{s}", txt=f"STATUS {r.status_code} rows {len(lines)}\n" + "\n".join(lines[:4] + ["..."] + lines[-4:]))
    except Exception as e: save(f"fred_{s}", txt=str(e))
# ── FINRA ──
post("finra_si", "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest",
     json={"limit": 5, "compareFilters": [{"compareType": "equal", "fieldName": "symbolCode", "fieldValue": "AAPL"}]},
     headers={**UA, "Accept": "application/json", "Content-Type": "application/json"})
get("finra_si_get", "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest?limit=3")
print("done")
