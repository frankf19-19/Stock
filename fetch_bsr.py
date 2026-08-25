#!/usr/bin/env python3
# fetch_bsr.py - TWSE BSR (broker branch report) PoC probe.
# Goal: test if GitHub Actions can auto-fetch bsr.twse.com.tw without captcha.
# Output: bsr_diag.json (always) + c/bsr/{id}.json on success. Exit 0 always.
import json, os, re, time, random, datetime
import urllib.request as rq

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36"
D = {"ts": datetime.datetime.now().isoformat(), "steps": [], "verdict": None}

def log(s, **k):
    D["steps"].append({"s": s, **k}); print("[bsr]", s, k, flush=True)

def http(u, data=None, hd=None):
    h = {"User-Agent": UA, "Accept-Language": "zh-TW"}
    if hd: h.update(hd)
    with rq.urlopen(rq.Request(u, data=data, headers=h), timeout=25) as r:
        return r.status, r.read().decode("utf-8", "ignore")

def ids():
    for p in ("wf/bsr_watch.json", "bsr_watch.json"):
        if os.path.exists(p):
            try:
                v = json.load(open(p))
                if isinstance(v, list) and v: return [str(x) for x in v][:60]
            except Exception as e: log("watch_fail", e=str(e))
    return ["2330", "2317", "3665"]

def main():
    os.makedirs("c/bsr", exist_ok=True)
    try:
        st, body = http("https://bsr.twse.com.tw/bshtm/bsMenu.aspx")
        cap = ("CaptchaImage" in body) or ("captcha" in body.lower())
        vs = re.search(r'id="__VIEWSTATE" value="([^"]+)"', body)
        log("menu", st=st, captcha=cap, vs=bool(vs), size=len(body))
    except Exception as e:
        log("menu_fail", e=str(e)[:200]); st, cap, vs = None, None, None
    if st is None: D["verdict"] = "UNREACHABLE"
    elif st != 200: D["verdict"] = "HTTP_%s" % st
    elif cap: D["verdict"] = "CAPTCHA_BLOCKED"
    elif not vs: D["verdict"] = "FORM_CHANGED"
    else:
        sid = ids()[0]
        try:
            form = ("__VIEWSTATE=%s&RadioButton_Normal=RadioButton_Normal&TextBox_Stkno=%s&btnOK=%%E6%%9F%%A5%%E8%%A9%%A2"
                    % (rq.quote(vs.group(1)), sid)).encode()
            st2, b2 = http("https://bsr.twse.com.tw/bshtm/bsMenu.aspx", data=form,
                           hd={"Content-Type": "application/x-www-form-urlencoded",
                               "Referer": "https://bsr.twse.com.tw/bshtm/bsMenu.aspx"})
            ok = ("bsContent" in b2) or ("HiddenField" in b2)
            log("post", st=st2, ok=ok)
            if ok:
                time.sleep(1.2 + random.random())
                st3, csv = http("https://bsr.twse.com.tw/bshtm/bsContent.aspx?v=t&stock_id=%s" % sid)
                rows = [r for r in csv.splitlines() if r.count(",") >= 4]
                log("content", st=st3, rows=len(rows))
                if len(rows) > 5:
                    json.dump({"id": sid, "d": datetime.date.today().isoformat(), "rows": rows[:2000]},
                              open("c/bsr/%s.json" % sid, "w"), ensure_ascii=False)
                    D["verdict"] = "SUCCESS_%s_rows_%d" % (sid, len(rows))
                else: D["verdict"] = "EMPTY"
            else: D["verdict"] = "POST_REJECTED"
        except Exception as e:
            log("query_fail", e=str(e)[:200]); D["verdict"] = "QUERY_ERROR"
    json.dump(D, open("bsr_diag.json", "w"), ensure_ascii=False, indent=1)
    print("VERDICT:", D["verdict"])

if __name__ == "__main__":
    main()
