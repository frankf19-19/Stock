"""一次性:SEC 連線測試(哪種 User-Agent 會被接受)"""
import os, requests
os.makedirs("probe_out", exist_ok=True)
u = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2026q1_form345.zip"
out = []
for ua in ["K-research-dashboard github.com/frankf19-19/Stock research@frankf19-19.github.io",
           "K-research-dashboard admin@frankf19-19.github.io",
           "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
           "K-research personal dashboard"]:
    try:
        r = requests.head(u, headers={"User-Agent": ua}, timeout=30, allow_redirects=True)
        r2 = requests.get("https://data.sec.gov/submissions/CIK0000320193.json", headers={"User-Agent": ua}, timeout=30)
        out.append(f"{r.status_code} {r2.status_code} | {ua}")
    except Exception as e: out.append(f"ERR {e} | {ua}")
open("probe_out/sec_ua.txt", "w").write("\n".join(out))
