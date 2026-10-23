import urllib.request, gzip, io, time, json
def N(s): print("::notice::"+str(s)[:700], flush=True)
def get(u, ua):
    req=urllib.request.Request(u, headers={"User-Agent":ua,"Accept":"*/*","Accept-Encoding":"gzip, deflate"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            raw=r.read()
            if r.headers.get("Content-Encoding")=="gzip": raw=gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            return r.status, len(raw), raw[:80]
    except urllib.error.HTTPError as e:
        return e.code, 0, e.read()[:120]
    except Exception as e:
        return -1, 0, str(e)[:100]
UAS=["MajiStock frankf19-19@users.noreply.github.com","Mozilla/5.0 (compatible; KLabResearch/1.0; frankccc199@gmail.com)","K-Lab research bot admin@example.com"]
for u in ("https://data.sec.gov/submissions/CIK0001045810.json",
          "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001045810&type=8-K&dateb=&owner=include&count=40&output=atom",
          "https://efts.sec.gov/LATEST/search-index?q=%22Results%20of%20Operations%22&forms=8-K&ciks=0001045810",
          "https://www.sec.gov/Archives/edgar/data/1045810/index.json",
          "https://data.sec.gov/api/xbrl/frames/us-gaap/Revenues/USD/CY2026Q2.json"):
    for ua in UAS:
        st=get(u,ua); N(f"{u[:70]} | {ua[:25]} → {st[0]} {st[1]}B {st[2]!r}"); time.sleep(1.2)
