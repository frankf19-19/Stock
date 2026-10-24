"""📦 外部資料擴充(r1130)——六種新資料,全部永久存進 archive/ext/(只增不刪)
用法:python ext_fetch.py <來源> [backfill]
  insider_tw  台股內部人持股轉讓事前申報(公開資訊觀測站 t56sb21 每月彙總;上市+上櫃;backfill 從 2012 起)
  form4       美股內部人買賣 Form 4(SEC 季度資料集 2012 起 + EDGAR 每日索引補最近幾天;只留站上 S&P500 等股票)
  opt         台指選擇權各履約價未沖銷量(期交所;backfill 從 2016 起,每天留最近的月選與週選)
  finra       美股空單餘額(FINRA,每月兩次;2017 年底起)
  fred        美國金融壓力(FRED:Baa 公司債利差、殖利率曲線、芝加哥 Fed 金融情勢、聖路易 Fed 金融壓力、VIX)
  biz         台灣景氣對策信號與領先/同時指標(FinMind TaiwanBusinessIndicator,1982 起)
每日排程:ext.yml;回補:ext_backfill.yml(週末/手動)。"""
import os, sys, re, io, json, gzip, time, html, zipfile, datetime as dt
import requests

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
D = "archive/ext"
os.makedirs(D, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (K-research personal dashboard)"}
SEC_UA = {"User-Agent": "KLabResearch/1.0 klab.research@gmail.com", "Accept-Encoding": "gzip, deflate"}   # r1158:依 AGENTS 使用專案聯絡信箱


def log(*a): print(*a, flush=True)
def gz_load(p, d=None):
    try: return json.loads(gzip.open(p).read())
    except Exception: return d
def gz_save(p, o):
    tmp = p + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f: json.dump(o, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)
def num(s):
    s = re.sub(r"[^\d.\-]", "", s or "")
    try: return float(s) if "." in s else int(s)
    except Exception: return None
def roc2iso(s):
    m = re.match(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", s.strip())
    return f"{int(m.group(1)) + 1911:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
def cells(tr):
    out = []
    for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I):
        c = re.sub(r"<br\s*/?>", " ", c, flags=re.I); c = re.sub(r"<[^>]+>", "", c)
        out.append(re.sub(r"\s+", " ", html.unescape(c)).strip())
    return out


# ══════════════════ 1. 台股內部人申報轉讓 ══════════════════
def insider_tw(backfill=False):
    P = f"{D}/insider_tw.json.gz"
    A = gz_load(P, {"rows": {}})
    rows = A["rows"]
    if backfill:
        months = [(y, m) for y in range(2012, NOW.year + 1) for m in range(1, 13) if (y, m) <= (NOW.year, NOW.month)]
        done = set(A.get("done") or [])
        months = [x for x in months if f"{x[0]}-{x[1]:02d}" not in done or x >= (NOW.year, NOW.month - 1)]
    else:
        prev = (NOW.replace(day=1) - dt.timedelta(days=1))
        months = [(prev.year, prev.month), (NOW.year, NOW.month)]
    n_new = 0
    for (y, m) in months:
        for mk in ("sii", "otc"):
            data = {"encodeURIComponent": 1, "run": "", "step": 1, "TYPEK": mk, "year": str(y - 1911),
                    "smonth": f"{m:02d}", "emonth": f"{m:02d}", "sstep": 1, "firstin": "true"}
            t = None
            for k in range(4):
                try:
                    r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t56sb21", data=data, headers=UA, timeout=90)
                    if r.ok and ("申報日期" in r.text or "無" in r.text): t = r.text; break
                    log(f"  {y}-{m} {mk} 狀態 {r.status_code},重試")
                except Exception as e: log(f"  {y}-{m} {mk} 錯誤 {e}")
                time.sleep(10 * (k + 1))
            if t is None: continue
            cnt = 0; got = {}
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S | re.I):
                c = cells(tr)
                i = next((j for j, x in enumerate(c[:3]) if re.match(r"\d{2,3}/\d{2}/\d{2}$", x)), None)
                if i is None or len(c) < i + 15: continue
                c = c[i:]
                d = roc2iso(c[0]); code = c[1]
                if not d or not re.match(r"^\d{4,6}[A-Z]?$", code): continue
                # 欄位:申報日、代號、名稱、身分、姓名、轉讓方式、盤中最大可轉讓、受讓人(2 欄)、目前持股(自有/信託)、
                #       預定轉讓(自有/信託)、轉讓後(自有/信託)、有效期間(2026-10 實測:受讓人後面多一個空欄)
                off = 1 if len(c) >= 16 else 0
                per = " ".join(c[14 + off:16 + off]).replace(" ", "")
                pm = re.findall(r"\d{2,3}/\d{2}/\d{2}", per)
                rec = {"d": d, "id": code, "n": c[2], "role": c[3], "who": c[4], "how": c[5], "max": (num(c[6]) or num(c[7])) if off else num(c[6]), "to": c[8] if off else c[7],
                       "hold": num(c[8 + off]), "hold_t": num(c[9 + off]), "sh": num(c[10 + off]), "sh_t": num(c[11 + off]),
                       "after": num(c[12 + off]), "after_t": num(c[13 + off]),
                       "p0": roc2iso(pm[0]) if pm else None, "p1": roc2iso(pm[1]) if len(pm) > 1 else None, "mk": mk}
                if rec["hold"] is not None and rec["sh"] is not None and rec["after"] is not None and abs(rec["hold"] - rec["sh"] - rec["after"]) > max(1000, 0.001 * rec["hold"]):
                    log(f"  ⚠ 欄位對不上,略過:{code} {c[4]} {c[8:16]}"); continue
                key = f"{d}|{code}|{c[4]}|{c[5]}|{rec['sh']}|{rec['hold']}|{rec['sh_t']}|{rec['to'] or ''}"
                got[key] = rec; cnt += 1
            if got or "無持股轉讓" in t:   # 這個月重抓成功 → 用新抓的取代同月同市場的舊紀錄(同一份資料,欄位更完整)
                pre = f"{y}-{m:02d}"
                for k in [k for k, v in rows.items() if v.get("d", "").startswith(pre) and v.get("mk") == mk and k not in got]: rows.pop(k)
                n_new += sum(1 for k in got if k not in rows)
                rows.update(got)
            log(f"  {y}-{m:02d} {mk}:{cnt} 筆")
            time.sleep(3.5)
        if backfill:
            A.setdefault("done", [])
            if f"{y}-{m:02d}" not in A["done"]: A["done"].append(f"{y}-{m:02d}")
            if len(A["done"]) % 6 == 0: A["u"] = NOW.strftime("%Y-%m-%d %H:%M"); gz_save(P, A)
    A["u"] = NOW.strftime("%Y-%m-%d %H:%M")
    gz_save(P, A)
    log(f"✓ 台股內部人申報:共 {len(rows)} 筆(新增 {n_new})")


# ══════════════════ 2. 美股 Form 4 ══════════════════
def _sec_get(url, tries=4):
    for k in range(tries):
        try:
            r = requests.get(url, headers=SEC_UA, timeout=120)
            if r.status_code == 200: return r
            if r.status_code == 404: return None
            log(f"  SEC {r.status_code} {url[-40:]}")
        except Exception as e: log(f"  SEC 錯誤 {e}")
        time.sleep(5 * (k + 1))
    return None


def _sec_date(s):
    s = (s or "").strip()
    for f in ("%d-%b-%Y", "%Y-%m-%d"):
        try: return dt.datetime.strptime(s.title() if "-" in s and s[3:6].isalpha() else s, f).date().isoformat()
        except Exception: pass
    return None


def _role(rel, title):
    rel = (rel or "").lower(); t = (title or "").upper()
    if "ceo" in t.lower() or "CHIEF EXECUTIVE" in t: return "CEO"
    if "CFO" in t or "CHIEF FINANCIAL" in t: return "CFO"
    if "officer" in rel: return "Officer"
    if "director" in rel: return "Director"
    if "tenpercent" in rel.replace(" ", "") or "10%" in rel: return "10%"
    return rel[:12] or "?"


def form4(backfill=False):
    P = f"{D}/form4_us.json.gz"
    A = gz_load(P, {"rows": {}, "q": []})
    rows = A["rows"]
    cik = {int(v): k for k, v in (json.load(open("us_cik.json")) or {}).items()}
    if backfill:
        qs = [(y, q) for y in range(2012, NOW.year + 1) for q in (1, 2, 3, 4)]
        last_full = ((NOW.year * 4 + (NOW.month - 1) // 3) - 1)
        qs = [x for x in qs if x[0] * 4 + x[1] - 1 <= last_full and f"{x[0]}q{x[1]}" not in A["q"]]
        for (y, q) in qs:
            r = _sec_get(f"https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{y}q{q}_form345.zip")
            if r is None: log(f"  {y}q{q} 沒有檔案"); continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            def tsv(name):
                with z.open(name) as f:
                    rd = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                    hdr = rd.readline().rstrip("\n").split("\t")
                    for line in rd:
                        yield dict(zip(hdr, line.rstrip("\n").split("\t")))
            sub = {}
            for s in tsv("SUBMISSION.tsv"):
                if s.get("DOCUMENT_TYPE") not in ("4", "4/A"): continue
                try: c = int(s.get("ISSUERCIK") or 0)
                except Exception: continue
                if c in cik: sub[s["ACCESSION_NUMBER"]] = (cik[c], _sec_date(s.get("FILING_DATE")))
            own = {}
            for o in tsv("REPORTINGOWNER.tsv"):
                a = o.get("ACCESSION_NUMBER")
                if a in sub and a not in own: own[a] = (o.get("RPTOWNERNAME", "")[:40], _role(o.get("RPTOWNER_RELATIONSHIP"), o.get("RPTOWNER_TITLE")))
            n = 0
            for t in tsv("NONDERIV_TRANS.tsv"):
                a = t.get("ACCESSION_NUMBER")
                if a not in sub or t.get("TRANS_CODE") not in ("P", "S"): continue
                sym, fd = sub[a]; who, role = own.get(a, ("?", "?"))
                sh = num(t.get("TRANS_SHARES")); px = num(t.get("TRANS_PRICEPERSHARE"))
                rec = {"fd": fd, "td": _sec_date(t.get("TRANS_DATE")), "s": sym, "c": t["TRANS_CODE"], "sh": sh, "px": px,
                       "v": round(sh * px) if sh and px else None, "who": who, "role": role,
                       "after": num(t.get("SHRS_OWND_FOLWNG_TRANS")), "acc": a}
                rows[f"{a}|{t.get('NONDERIV_TRANS_SK')}"] = rec; n += 1
            A["q"].append(f"{y}q{q}")
            log(f"  {y}q{q}:{len(sub)} 份申報、{n} 筆買賣")
            A["u"] = NOW.strftime("%Y-%m-%d %H:%M"); gz_save(P, A)
            time.sleep(1)
    # 每日:EDGAR 每日索引(最近 10 天;季度資料集還沒出的部分)
    seen = set(A.get("idx_done") or [])
    # 季度資料集還沒出的那段(最多 200 天),每天補 40 個交易日的每日索引,幾天內就補齊
    lastq = max(A["q"]) if A["q"] else None
    qend = dt.date(int(lastq[:4]), int(lastq[-1]) * 3, 28) if lastq else (NOW - dt.timedelta(days=100)).date()
    span = min(200, max(12, (NOW.date() - qend).days))
    days = [(NOW - dt.timedelta(days=i)).date() for i in range(2, span)]   # 前一天的索引美東晚上才完整,從前兩天開始
    days = [d for d in days if d.isoformat() not in seen and d.weekday() < 5]
    days = sorted(days, reverse=True)[:40 if not backfill else 200]
    n_new = 0
    for day in sorted(days):
        if day.weekday() >= 5 or day.isoformat() in seen: continue
        q = (day.month - 1) // 3 + 1
        r = _sec_get(f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/form.{day.strftime('%Y%m%d')}.idx", tries=2)
        if r is None: continue
        files = []
        for line in r.text.splitlines():
            if not (line.startswith("4 ") or line.startswith("4/A ")): continue
            m = re.search(r"\s(\d{3,10})\s+(\d{4}-?\d{2}-?\d{2})\s+(edgar/\S+)", line)
            if m and int(m.group(1)) in cik: files.append(m.group(3))
        for fp in dict.fromkeys(files):
            acc = fp.split("/")[-1].replace(".txt", "")
            if any(k.startswith(acc + "|") for k in rows): continue
            rr = _sec_get("https://www.sec.gov/Archives/" + fp, tries=2)
            time.sleep(0.15)
            if rr is None: continue
            x = rr.text
            mi = re.search(r"<issuerCik>\s*0*(\d+)", x)
            if not mi or int(mi.group(1)) not in cik: continue
            sym = cik[int(mi.group(1))]
            who = (re.search(r"<rptOwnerName>(.*?)</rptOwnerName>", x, re.S) or [None, "?"])[1].strip()[:40]
            rel = " ".join(k for k in ("isDirector", "isOfficer", "isTenPercentOwner") if re.search(rf"<{k}>\s*(1|true)", x, re.I))
            title = (re.search(r"<officerTitle>(.*?)</officerTitle>", x, re.S) or [None, ""])[1]
            role = _role(rel.replace("is", "").replace("TenPercentOwner", "tenpercent"), title)
            for j, blk in enumerate(re.findall(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>", x, re.S)):
                code = (re.search(r"<transactionCode>(\w)</transactionCode>", blk) or [None, ""])[1]
                if code not in ("P", "S"): continue
                g = lambda tag: (re.search(rf"<{tag}>\s*(?:<value>)?\s*([^<\s]+)", blk) or [None, None])[1]
                sh = num(g("transactionShares")); px = num(g("transactionPricePerShare"))
                rows[f"{acc}|d{j}"] = {"fd": day.isoformat(), "td": g("transactionDate"), "s": sym, "c": code, "sh": sh, "px": px,
                                       "v": round(sh * px) if sh and px else None, "who": who, "role": role,
                                       "after": num(g("sharesOwnedFollowingTransaction")), "acc": acc}
                n_new += 1
        seen.add(day.isoformat())
    A["idx_done"] = sorted(seen)[-600:]
    A["u"] = NOW.strftime("%Y-%m-%d %H:%M")
    gz_save(P, A)
    log(f"✓ Form 4:共 {len(rows)} 筆(每日索引新增 {n_new})")


# ══════════════════ 3. 台指選擇權未平倉 ══════════════════
def _opt_parse(text):
    """→ {date: {contract: {"c": {strike: oi}, "p": {...}, "x": 到期日}}}(只留一般交易時段)"""
    out = {}
    lines = text.splitlines()
    if not lines or "交易日期" not in lines[0]: return out
    hdr = [h.strip() for h in lines[0].split(",")]
    ix = {h: i for i, h in enumerate(hdr)}
    for ln in lines[1:]:
        f = ln.split(",")
        if len(f) < 12 or f[ix["契約"]].strip() != "TXO": continue
        if "交易時段" in ix and f[ix["交易時段"]].strip() not in ("一般", ""): continue
        d = f[0].strip().replace("/", "-"); con = f[ix["到期月份(週別)"]].strip()
        try: k = int(float(f[ix["履約價"]])); oi = int(f[ix["未沖銷契約數"]].replace("-", "0") or 0)
        except Exception: continue
        cp = "c" if "買" in f[ix["買賣權"]] else "p"
        e = out.setdefault(d, {}).setdefault(con, {"c": {}, "p": {}})
        if "契約到期日" in ix and f[ix["契約到期日"]].strip(): e["x"] = f[ix["契約到期日"]].strip()
        if oi > 0: e[cp][k] = oi
    return out


def _opt_slim(day):
    """每天只留:最近 2 個月選 + 最近 2 個週選(還有未平倉的);履約價壓成 [履約價, 買權OI, 賣權OI]"""
    mon = sorted(c for c in day if re.fullmatch(r"\d{6}", c))[:2]
    wk = sorted((c for c in day if not re.fullmatch(r"\d{6}", c)), key=lambda c: (day[c].get("x") or c[:6] + "99", c))[:3]
    o = {}
    for c in mon + wk:
        e = day[c]; ks = sorted(set(e["c"]) | set(e["p"]))
        if not ks: continue
        o[c] = {"k": [[k, e["c"].get(k, 0), e["p"].get(k, 0)] for k in ks]}
        if e.get("x"): o[c]["x"] = e["x"]
    return o


def opt(backfill=False):
    if backfill:
        start = dt.date(2016, 1, 1)
    else:
        start = (NOW - dt.timedelta(days=6)).date()
    end = NOW.date()
    cur = start
    while cur <= end:
        nxt = min((cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1), end)
        fp = f"{D}/opt/{cur.year}.json.gz"; os.makedirs(f"{D}/opt", exist_ok=True)
        Y = gz_load(fp, {})
        if backfill and all(d in Y for d in [(cur + dt.timedelta(days=i)).isoformat() for i in range((nxt - cur).days + 1)]
                            if dt.date.fromisoformat(d).weekday() < 5) and cur.month != NOW.month:
            cur = nxt + dt.timedelta(days=1); continue
        txt = None
        for k in range(4):
            try:
                r = requests.post("https://www.taifex.com.tw/cht/3/optDataDown", headers=UA, timeout=180,
                                  data={"down_type": "1", "commodity_id": "TXO", "commodity_id2": "",
                                        "queryStartDate": cur.strftime("%Y/%m/%d"), "queryEndDate": nxt.strftime("%Y/%m/%d")})
                if r.ok: txt = r.content.decode("big5", errors="replace"); break
            except Exception as e: log(f"  期交所錯誤 {e}")
            time.sleep(10 * (k + 1))
        if txt:
            P = _opt_parse(txt)
            for d, day in P.items(): Y[d] = _opt_slim(day)
            gz_save(fp, Y)
            log(f"  {cur}~{nxt}:{len(P)} 天")
        cur = nxt + dt.timedelta(days=1)
        time.sleep(3)
    log("✓ 選擇權未平倉完成")


# ══════════════════ 4. FINRA 空單餘額 ══════════════════
def finra(backfill=False):
    # r1158: publication calendar is archived independently; a fetch failure preserves known dates.
    from finra_calendar import update_calendar
    try: update_calendar()
    except Exception as exc: log(f"FINRA publication calendar: {type(exc).__name__}; retained existing dates")
    P = f"{D}/finra_si.json.gz"
    A = gz_load(P, {"s": {}, "done": []})
    syms = set()
    import glob
    for p in glob.glob("k/us_*.json"):
        try: syms |= set(json.load(open(p)).keys())
        except Exception: pass
    syms = sorted(s for s in syms if re.fullmatch(r"[A-Z.]{1,6}", s))
    r = requests.get("https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest", headers={"Accept": "application/json"}, timeout=60)
    parts = sorted(x["partitions"][0] for x in r.json()["availablePartitions"])
    todo = [p for p in parts if p not in A["done"]] if backfill else [p for p in parts[-3:]]
    for p in todo:
        got = 0
        for i in range(0, len(syms), 400):
            body = {"limit": 5000, "compareFilters": [{"compareType": "equal", "fieldName": "settlementDate", "fieldValue": p}],
                    "domainFilters": [{"fieldName": "symbolCode", "values": syms[i:i + 400]}]}
            for k in range(3):
                try:
                    rr = requests.post("https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest", json=body,
                                       headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=90)
                    if rr.status_code == 204: js = []; break
                    if rr.ok: js = rr.json(); break
                except Exception as e: log(f"  FINRA 錯誤 {e}")
                time.sleep(5); js = None
            for x in js or []:
                s = x.get("symbolCode")
                a = A["s"].setdefault(s, {})
                a[p] = [x.get("currentShortPositionQuantity"), x.get("averageDailyVolumeQuantity"), x.get("daysToCoverQuantity")]
                got += 1
            time.sleep(1)
        if p not in A["done"]: A["done"].append(p)
        log(f"  {p}:{got} 檔")
    A["u"] = NOW.strftime("%Y-%m-%d %H:%M")
    gz_save(P, A)
    log(f"✓ FINRA 空單:{len(A['s'])} 檔、{len(A['done'])} 期")


# ══════════════════ 5. FRED ══════════════════
FRED_SERIES = {"BAA10Y": "Baa 公司債利差", "T10Y3M": "10年-3個月殖利率差", "T10Y2Y": "10年-2年殖利率差", "NFCI": "芝加哥 Fed 金融情勢",
               "STLFSI4": "聖路易 Fed 金融壓力", "VIXCLS": "VIX", "BAMLH0A0HYM2": "高收益債利差", "DGS10": "10年期公債殖利率"}


def fred(backfill=False):
    P = f"{D}/fred.json.gz"
    A = gz_load(P, {"s": {}})
    key = os.environ.get("FRED_API_KEY", "").strip()
    for sid in FRED_SERIES:
        s = A["s"].setdefault(sid, {}); n0 = len(s)
        try:
            if key:   # 官方 API(有金鑰最穩)
                r = requests.get("https://api.stlouisfed.org/fred/series/observations", timeout=60,
                                 params={"series_id": sid, "api_key": key, "file_type": "json", "observation_start": "1970-01-01"})
                for o in r.json().get("observations") or []:
                    try: s[o["date"]] = float(o["value"])
                    except Exception: pass
            if len(s) == n0:   # 備援:CSV 下載
                r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"}, timeout=90)
                for ln in r.text.strip().splitlines()[1:]:
                    d, _, v = ln.partition(",")
                    try: s[d] = float(v)
                    except Exception: pass
            log(f"  {sid}:{len(s)} 筆(+{len(s) - n0})")
        except Exception as e: log(f"  {sid} 失敗 {e}")
        time.sleep(1)
    A["u"] = NOW.strftime("%Y-%m-%d %H:%M")
    gz_save(P, A)
    log("✓ FRED 完成")


# ══════════════════ 6. 景氣指標 ══════════════════
def biz(backfill=False):
    P = f"{D}/biz.json.gz"
    A = gz_load(P, {"m": {}})
    tok = os.environ.get("FINMIND_TOKEN", "")
    r = requests.get("https://api.finmindtrade.com/api/v4/data", params={"dataset": "TaiwanBusinessIndicator", "start_date": "1980-01-01", "token": tok}, timeout=60)
    for x in r.json().get("data") or []:
        A["m"][x["date"][:7]] = {k: x.get(k) for k in ("leading", "leading_notrend", "coincident", "coincident_notrend", "lagging", "monitoring", "monitoring_color")}
    A["u"] = NOW.strftime("%Y-%m-%d %H:%M")
    gz_save(P, A)
    log(f"✓ 景氣指標:{len(A['m'])} 個月,最新 {max(A['m'])} {A['m'][max(A['m'])]}")


if __name__ == "__main__":
    src = sys.argv[1]; bf = len(sys.argv) > 2 and sys.argv[2] == "backfill"
    {"insider_tw": insider_tw, "form4": form4, "opt": opt, "finra": finra, "fred": fred, "biz": biz}[src](bf)
