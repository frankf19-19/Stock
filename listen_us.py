"""美股財報新聞稿 AI 整理 → ir_us/<代號>.json(永久保存)+ ir_us_index.json

台股有「法說會簡報」;美股對應的第一手資料是公司在財報日向 SEC 申報的 8-K(Item 2.02 Results of Operations)
附件 EX-99.1 財報新聞稿:當季營收/EPS/各部門、下一季/全年指引、庫藏股/股利、管理層原話。
零成本:SEC EDGAR 官方 API(免金鑰)+ Gemini 免費金鑰。
流程:
  ① us_cik.json 每檔 → data.sec.gov/submissions → 近 N 個月的 8-K(含 2.02)
  ② 取附件 EX-99.1(htm)→ 去 HTML 標籤 → Gemini 結構化 JSON(語氣/標題/摘要/關鍵數字/指引/動能/風險/觀察點/深度文,繁體中文)
  ③ ir_us/<SYM>.json(每檔所有歷史)、ir_us_index.json
環境變數:GEMINI_KEY(必要)、MONTHS_BACK(預設 3)、MAX_PER_RUN(預設 30)、ONLY=代號
"""
import datetime as dt
import html as H
import json
import os
import re
import sys
import time

import requests
import urllib.error

KEY = os.environ.get("GEMINI_KEY", "").strip()
PV = 1
MODELS = ["gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"]
DIR = "ir_us"
IDX = "ir_us_index.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; KLabResearch/1.0; klab.research@gmail.com)", "Accept": "application/json, text/html, */*"}
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "30") or 30)
MONTHS_BACK = int(os.environ.get("MONTHS_BACK", "3") or 3)
ONLY = os.environ.get("ONLY", "").strip().upper()
NOW = dt.datetime.utcnow() + dt.timedelta(hours=8)
TODAY = NOW.date()


def log(*a):
    print(*a, flush=True)


import urllib.parse as _up
_ROUTE = {"win": None}
def sec_get(url, timeout=60, json_=True):
    """直連 → 公共代理(機房對 data.sec.gov 偶爾被擋;fetch_usf 同款路由)"""
    q = _up.quote(url, safe="")
    routes = [("direct", url), ("allorigins", "https://api.allorigins.win/raw?url=" + q),
              ("corsproxy", "https://corsproxy.io/?url=" + q), ("codetabs", "https://api.codetabs.com/v1/proxy?quest=" + q)]
    routes.sort(key=lambda r: 0 if r[0] == _ROUTE["win"] else 1)
    last = ""
    for name, u in routes:
        for attempt in range(2 if name == "direct" else 1):
            try:
                # fetch_usf 同款:urllib + 明示 gzip(SEC 對 requests 的連線直接回 403)
                import urllib.request, gzip, io
                req = urllib.request.Request(u, headers={"User-Agent": UA["User-Agent"], "Accept": "application/json, text/html, */*", "Accept-Encoding": "gzip, deflate"})
                with urllib.request.urlopen(req, timeout=timeout) as rr:
                    raw = rr.read()
                    if rr.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                    txt = raw.decode("utf-8", "replace")
                if (not json_) or txt.lstrip().startswith(("{", "[")):
                    _ROUTE["win"] = name
                    return json.loads(txt) if json_ else txt
                last += f" | {name} 非JSON {txt[:50]!r}"
            except urllib.error.HTTPError as e:
                if e.code == 404 and name == "direct":
                    return None
                if e.code == 429:
                    time.sleep(8); continue
                last += f" | {name} {e.code}"
            except Exception as e:
                last += f" | {name} {str(e)[:50]}"
            time.sleep(1)
    log(f"    SEC 抓不到 {url[-70:]}:{last[:400]}")
    return None


def filings_atom(cik, since):
    """備援:www.sec.gov browse-edgar Atom(data.sec.gov/submissions 在 GitHub 機房回 403)。
       Atom 沒有 Items 欄位 → 先收全部 8-K,Item 2.02 由 index 頁判斷(見 is_earnings_8k)。"""
    t = sec_get(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(cik):010d}&type=8-K&dateb=&owner=include&count=40&output=atom", json_=False)
    if not t:
        return []
    out = []
    for ent in re.findall(r"<entry>(.*?)</entry>", t, re.S):
        form = (re.search(r"<filing-type>([^<]+)</filing-type>", ent) or [None, ""])[1].strip()
        d = (re.search(r"<filing-date>([^<]+)</filing-date>", ent) or [None, ""])[1].strip()
        acc = (re.search(r"<accession-number>([^<]+)</accession-number>", ent) or [None, ""])[1].strip()
        if form not in ("8-K", "8-K/A") or not d or not acc or d < since:
            continue
        out.append({"d": d, "acc": acc, "doc": "", "rd": "", "chk": 1})
    return out


def is_earnings_8k(cik, acc):
    """index 頁(-index.htm)有列 Items → 看有沒有 2.02"""
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}"
    t = sec_get(f"{base}/{acc}-index.htm", json_=False) or ""
    m = re.search(r"Items?\s*:?\s*</[^>]+>\s*<[^>]+>\s*([^<]{0,200})", t) or re.search(r"Items?[^<]{0,10}:\s*([^<]{0,200})", t)
    items = (m.group(1) if m else "")
    if ONLY: log(f"    index 頁 Items=「{items.strip()[:80]}」 len={len(t)}")
    return bool(re.search(r"\b2\.02\b", items)) if items else ("Results of Operations" in t)


def filings(cik, since):
    j = sec_get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
    if not j:
        fl = filings_atom(cik, since)
        log(f"    submissions 抓不到(CIK {cik})→ Atom 備援 {len(fl)} 筆 8-K")
        return fl
    rec = (j.get("filings") or {}).get("recent") or {}
    if ONLY:
        fs = rec.get("form") or []
        log(f"    submissions:{len(fs)} 筆,8-K {sum(1 for f in fs if f.startswith('8-K'))} 筆;最近 5 筆 {list(zip(fs[:5], (rec.get('filingDate') or [])[:5], (rec.get('items') or [])[:5]))}")
    out = []
    for i, form in enumerate(rec.get("form") or []):
        if form not in ("8-K", "8-K/A"):
            continue
        items = str((rec.get("items") or [""] * 999)[i] or "")
        if "2.02" not in items:
            continue
        d = (rec.get("filingDate") or [""])[i]
        if d < since:
            continue
        out.append({"d": d, "acc": (rec.get("accessionNumber") or [""])[i], "doc": (rec.get("primaryDocument") or [""])[i],
                    "rd": (rec.get("reportDate") or [""])[i]})
    return out


def exhibit_text(cik, acc):
    """8-K 附件 EX-99.1(財報新聞稿)→ 純文字"""
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}"
    j = sec_get(base + "/index.json")
    if not j:
        log("    index.json 抓不到"); return None, None
    items = (j.get("directory") or {}).get("item") or []
    names = [x.get("name", "") for x in items]
    if ONLY: log(f"    附件 {names[:12]}")
    cands = [n for n in names if re.search(r"ex[-_]?99", n, re.I) and n.lower().endswith((".htm", ".html"))]
    cands.sort(key=lambda n: (0 if re.search(r"99[-_.]?1\b|991", n) else 1, len(n)))
    if not cands:   # 沒有 EX-99 附件 → 不是財報新聞稿型的 8-K(純公告),不分析
        return None, "NOEX99"
    for n in cands[:2]:
        t = sec_get(f"{base}/{n}", json_=False)
        if not t:
            continue
        t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
        t = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>|</li>|</h\d>", "\n", t)
        t = re.sub(r"(?i)</td>|</th>", " | ", t)
        t = re.sub(r"<[^>]+>", " ", t)
        t = H.unescape(t)
        t = re.sub(r"[ \t\xa0]+", " ", t)
        t = re.sub(r"\n\s*\n+", "\n", t).strip()
        if len(t) > 1500:
            return t[:90000], f"{base}/{n}"
        time.sleep(0.3)
    return None, None


SCHEMA = {"type": "OBJECT", "properties": {
    "readable": {"type": "BOOLEAN"}, "tone": {"type": "STRING"}, "head": {"type": "STRING"}, "period": {"type": "STRING"},
    "summary": {"type": "STRING"},
    "numbers": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"k": {"type": "STRING"}, "v": {"type": "STRING"}, "chg": {"type": "STRING"}}, "required": ["k", "v"]}},
    "guidance": {"type": "ARRAY", "items": {"type": "STRING"}},
    "drivers": {"type": "ARRAY", "items": {"type": "STRING"}},
    "products": {"type": "ARRAY", "items": {"type": "STRING"}},
    "capex": {"type": "STRING"},
    "risks": {"type": "ARRAY", "items": {"type": "STRING"}},
    "watch": {"type": "ARRAY", "items": {"type": "STRING"}},
    "quotes": {"type": "ARRAY", "items": {"type": "STRING"}},
    "deep": {"type": "STRING"}},
    "required": ["readable", "tone", "head", "summary", "numbers", "guidance", "drivers", "risks", "watch", "deep"]}

PROMPT = """你是資深美股研究員。以下是「{name}({sym})」{d} 向 SEC 申報的 8-K 財報新聞稿(EX-99.1)全文。請讀完,用繁體中文輸出 JSON(金額保留原幣別與單位,如 US$ 億/百萬):

- readable:內容是否真的是財報新聞稿且可讀(若只是一般公告、無財務數字 → false,其他欄位留空,絕不腦補)
- tone:管理層整體語氣,只能是「正面」「中性」「保守」其一
- head:一句話(30 字內)講出這份財報最關鍵的訊息(像財經媒體標題,要有結論)
- period:財報期間(例「FY2026 Q3(截至 2026/9/27)」)
- summary:200~350 字摘要——本季營收/EPS 與年增、各部門表現與原因、指引;數字照原文
- numbers:關鍵數字 6~12 項 [{{k:項目, v:數值(含單位), chg:年增(有才寫)}}]:營收、毛利率、營業利益、淨利、EPS(GAAP/非GAAP 註明)、各部門營收、自由現金流、庫藏股/股利
- guidance:公司對下一季/全年的指引 2~6 條(數字與方向;沒有就寫「未給指引」一條)
- drivers:成長動能 2~5 條(具體到新聞稿內容)
- products:主要產品/部門與營收占比(有才寫)
- capex:資本支出/投資計畫(有才寫)
- risks:新聞稿提到或數字顯露的風險與保守訊號 2~5 條
- watch:投資人接下來最該追蹤的 2~4 個觀察點
- quotes:管理層最有代表性的原句 0~3 句(翻成中文,標明誰說的)
- deep:600~1100 字深度分析文(Markdown):破題導言 → 2~4 段「有結論的小標 + 把數字放進因果脈絡」→「### 投資人接下來該盯什麼」收尾。不做買賣建議。

鐵則:只寫新聞稿裡真的有的內容,數字照原文;沒有的欄位留空或寫「未提供」;絕不編造。

=== 新聞稿全文 ===
{text}"""

_G = {"n": 0}


def gemini_json(text, name, sym, d):
    if _G["n"] > 0:
        time.sleep(4)
    _G["n"] += 1
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT.format(name=name, sym=sym, d=d, text=text)}]}],
            "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.3, "responseMimeType": "application/json", "responseSchema": SCHEMA}}
    last = ""
    for mdl in MODELS:
        for attempt in range(2):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={KEY}", json=body, timeout=600)
            except Exception as e:
                last = f"連線 {str(e)[:60]}"; time.sleep(15); continue
            if r.status_code == 429:
                last = f"{mdl} 429"; log(f"    {mdl} 429 → 換模型"); break
            if r.status_code in (500, 503):
                last = f"{mdl} {r.status_code}"; time.sleep(20 * (attempt + 1)); continue
            if not r.ok:
                last = f"{mdl} {r.status_code} {r.text[:120]}"; break
            ps = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            txt = "".join(p.get("text", "") for p in ps).strip()
            try:
                o = json.loads(txt)
            except Exception:
                m = re.search(r"\{[\s\S]*\}", txt); o = json.loads(m.group(0)) if m else None
            if isinstance(o, dict):
                o["_model"] = mdl; return o
            last = f"{mdl} JSON 解析失敗"; break
    raise RuntimeError(last or "Gemini 全部失敗")


def load_ir(sym):
    try:
        return json.load(open(f"{DIR}/{sym}.json", encoding="utf-8"))
    except Exception:
        return {"v": 1, "id": sym, "conf": []}


def main():
    if not KEY:
        log("✗ 未設定 GEMINI_KEY"); sys.exit(1)
    cik = json.load(open("us_cik.json", encoding="utf-8"))
    try:
        S = {s["id"]: s for s in json.load(open("data.json", encoding="utf-8")).get("stocks") or [] if s.get("market") == "US"}
    except Exception:
        S = {}
    since = (TODAY - dt.timedelta(days=30 * MONTHS_BACK + 5)).isoformat()
    syms = [ONLY] if ONLY else sorted(cik, key=lambda s: -float(((S.get(s) or {}).get("co") or {}).get("cap") or 0))
    log(f"① 掃 {len(syms)} 檔 8-K(自 {since})…")
    touched, queue = {}, []
    for i, sym in enumerate(syms):
        if sym not in cik:
            continue
        fl = filings(cik[sym], since)
        time.sleep(0.12)
        j = load_ir(sym)
        if not fl and not j["conf"]:
            continue
        for f in fl:
            x = next((c for c in j["conf"] if c.get("acc") == f["acc"]), None)
            if not x:
                x = {"d": f["d"], "acc": f["acc"], "rd": f.get("rd")}
                if f.get("chk"): x["chk"] = 1
                j["conf"].append(x)
        for x in j["conf"]:   # 含之前失敗一次的(清單抓不到也要重試)
            if x["d"] >= since and not x.get("skip") and not (x.get("ai") and x.get("pv") == PV) and (x.get("fail") or 0) < 3:
                queue.append((sym, x))
        touched[sym] = j
        if (i + 1) % 100 == 0:
            log(f"  …{i + 1} 檔,待分析 {len(queue)}")
    queue.sort(key=lambda q: q[1]["d"], reverse=True)
    log(f"② 待分析 {len(queue)} 份,本班最多 {MAX_PER_RUN}:{[(q[0], q[1]['d']) for q in queue[:MAX_PER_RUN]]}")
    done = 0
    for sym, x in queue[:MAX_PER_RUN]:
        name = (S.get(sym) or {}).get("name") or sym
        log(f"▶ {sym} {name} {x['d']} {x['acc']}")
        try:
            if x.get("chk"):                                   # Atom 備援來的:先確認是財報(Item 2.02)
                if not is_earnings_8k(cik[sym], x["acc"]):
                    x["ai"] = None; x["skip"] = 1; x["pv"] = PV; log("    非財報 8-K,略過"); continue
                x.pop("chk", None)
            text, url = exhibit_text(cik[sym], x["acc"])
            if url == "NOEX99":
                x["skip"] = 1; x["pv"] = PV; log("    沒有 EX-99 附件(非財報新聞稿),略過"); continue
            if not text:
                x["fail"] = (x.get("fail") or 0) + 1; x["pv"] = PV; log("    找不到新聞稿附件"); continue
            x["url"] = url
            o = gemini_json(text, name, sym, x["d"])
        except RuntimeError as e:
            log(f"  ⏸ Gemini 受限({e})——本班提前收工"); break
        except Exception as e:
            log(f"    例外:{str(e)[:160]}"); continue
        if not o.get("readable") or not o.get("summary"):
            x["fail"] = (x.get("fail") or 0) + 1; x["pv"] = PV; log(f"    AI 判定非財報新聞稿(readable={o.get('readable')})"); continue
        ai = {k: o.get(k) for k in ("tone", "head", "period", "summary", "numbers", "guidance", "drivers", "products", "capex", "risks", "watch", "quotes", "deep")}
        if ai.get("deep"):
            ai["deep"] = re.sub(r"\s*(#{2,4} )", r"\n\n\1", ai["deep"]).strip()
        x["ai"] = ai; x["pv"] = PV; x["src"] = "8k"; x["model"] = o.get("_model"); x["ts"] = NOW.strftime("%Y-%m-%d %H:%M"); x.pop("fail", None)
        done += 1
        log(f"    ✅ {ai.get('tone')}|{str(ai.get('head'))[:50]}({o.get('_model')})")
    os.makedirs(DIR, exist_ok=True)
    for sym, j in touched.items():
        j["conf"].sort(key=lambda c: c["d"], reverse=True)
        with open(f"{DIR}/{sym}.json", "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False, separators=(",", ":"))
    idx = {}
    for fn in os.listdir(DIR):
        if fn.endswith(".json"):
            try:
                j = json.load(open(f"{DIR}/{fn}", encoding="utf-8")); idx[fn[:-5]] = [c["d"] for c in j["conf"] if c.get("ai")]
            except Exception:
                pass
    with open(IDX, "w", encoding="utf-8") as f:
        json.dump({"t": NOW.strftime("%Y-%m-%d %H:%M"), "n": len(idx), "s": idx}, f, ensure_ascii=False, separators=(",", ":"))
    left = max(0, len(queue) - done)
    log(f"完成:本班 {done} 份;庫存 {len(idx)} 檔;待分析剩 {left}")
    print(f"::notice::美股財報新聞稿:本班 {done} 份,待分析剩 {left},庫存 {len(idx)} 檔")


if __name__ == "__main__":
    main()
