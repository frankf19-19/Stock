import urllib.request, gzip, io, time
def N(s): print("::notice::"+str(s)[:300], flush=True)
def get(u, ua):
    req=urllib.request.Request(u, headers={"User-Agent":ua,"Accept":"*/*","Accept-Encoding":"gzip, deflate"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
    except Exception as e: return str(e)[:40]
UAS=["Mozilla/5.0 (compatible; KLabResearch/1.0; klab@frankf19-19.github.io)",
     "Mozilla/5.0 (compatible; KLabResearch/1.0; klab.research@gmail.com)",
     "KLabResearch klab.research@gmail.com",
     "Mozilla/5.0 (compatible; KLabResearch/1.0; frankccc199@gmail.com)",
     "K-Lab research bot admin@example.com"]
u="https://data.sec.gov/submissions/CIK0001045810.json"
for ua in UAS:
    N(f"{ua} → {get(u,ua)}"); time.sleep(1.5)
