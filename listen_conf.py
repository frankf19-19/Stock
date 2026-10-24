"""法說會 AI 讀簡報分析 v3 → ir/<代號>.json(永久保存)+ conf_ai.json(每檔最新一場,前端卡片用)+ ir_index.json

v3(2026-10-23)重做原因:舊版到 MOPS 找 href=*.pdf 的連結,但公開資訊觀測站的簡報是用表單 POST 下載
(fileName=代號+日期+M001.pdf),所以從來沒讀到簡報,全部退化成「只看擇要」,分析內容空洞(鴻海那篇什麼都沒有)。

流程:
  ① mopsov.twse.com.tw ajax_t100sb02_1(上市 sii / 上櫃 otc,逐月)→ 全部場次:日期、時間、地點、擇要、簡報檔名(中/英)、影音連結
  ② 沒分析過的場次(最新優先、市值大優先)→ POST /server-java/FileDownLoad 下載簡報(pdf 或 pptx)
  ③ Gemini(免費金鑰)讀整份簡報 → 結構化 JSON(語氣/指引/關鍵數字/成長動能/風險/觀察點)+ 深度分析文
  ④ 寫進 ir/<代號>.json(所有歷史場次都留著)、conf_ai.json(最新一場)、ir_index.json
環境變數:GEMINI_KEY(必要)、MONTHS_BACK(回補幾個月,預設 2)、MAX_PER_RUN(每班幾場,預設 30)、ONLY=代號(只跑一檔)
"""
import base64
import datetime as dt
import io
import json
import os
import re
import sys
import time
import zipfile

import requests

KEY = os.environ.get("GEMINI_KEY", "").strip()
PV = 3
MODELS = ["gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"]
OUT = "conf_ai.json"
DIR = "ir"
IDX = "ir_index.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "*/*"}
MOPS = "https://mopsov.twse.com.tw"
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "60") or 60)
MONTHS_BACK = int(os.environ.get("MONTHS_BACK", "2") or 2)
ONLY = os.environ.get("ONLY", "").strip()
INLINE_CAP = 15 * 1024 * 1024          # 超過就走 Files API
NOW = dt.datetime.utcnow() + dt.timedelta(hours=8)
TODAY = NOW.date()


def log(*a):
    print(*a, flush=True)


# ─────────────────────────── ① 法說會清單 ───────────────────────────
def roc(d):
    """'115/10/08' / '115/10/08 至 115/10/13' → ISO(取第一個日期)"""
    m = re.search(r"(\d{3})/(\d{1,2})/(\d{1,2})", str(d))
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))).isoformat()
    except Exception:
        return None


def month_list(typek, y, m):
    """某市場某月的全部場次 → [dict]"""
    for attempt in range(3):
        try:
            r = requests.post(f"{MOPS}/mops/web/ajax_t100sb02_1", headers=UA, timeout=60,
                              data={"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
                                    "TYPEK": typek, "year": str(y - 1911), "month": f"{m:02d}"})
            if r.ok and ("tblHead" in r.text or "查無" in r.text):
                break
        except Exception as e:
            log(f"  清單 {typek} {y}/{m} 失敗:{str(e)[:80]}")
        time.sleep(5 * (attempt + 1))
    else:
        return None
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
        if "<td" not in tr:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        txt = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in cells]
        if len(txt) < 8 or not re.fullmatch(r"[0-9A-Z]{4,6}", txt[0]):
            continue
        files = re.findall(r'fileName\.value="([^"]+)"', tr)
        fm = next((f for f in files if re.search(r"M\d{3}\.", f)), None)
        fe = next((f for f in files if re.search(r"E\d{3}\.", f)), None)
        links = re.findall(r"href=['\"](https?://[^'\"]+)['\"]", tr)
        vod = next((u for u in links if re.search(r"webpro\.twse|vod|youtube|youtu\.be|video|\.mp4|webcast|cnyes|irwebcast", u, re.I)), "")
        if not vod:
            m2 = re.search(r"https?://\S+", txt[9] if len(txt) > 9 else "")
            if m2:
                vod = m2.group(0)
        d = roc(txt[2])
        if not d:
            continue
        out.append({"id": txt[0], "name": txt[1], "d": d, "t": txt[3][:8], "loc": txt[4][:80], "msg": txt[5][:400],
                    "fm": fm, "fe": fe, "site": (txt[8] if len(txt) > 8 and txt[8].startswith("http") else ""),
                    "vod": vod[:200], "mk": typek})
    return out


def collect(months_back):
    y, m = TODAY.year, TODAY.month
    ym = []
    for i in range(months_back + 1):
        ym.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    allc = []
    for typek in ("sii", "otc"):
        for (yy, mm) in ym:
            rows = month_list(typek, yy, mm)
            if rows is None:
                log(f"  [warn] {typek} {yy}/{mm:02d} 清單抓不到")
                continue
            log(f"  {typek} {yy}/{mm:02d}:{len(rows)} 場")
            allc += rows
            time.sleep(1.5)
    return allc


# ─────────────────────────── ② 簡報下載 ───────────────────────────
def download(fn):
    for attempt in range(2):
        try:
            r = requests.post(f"{MOPS}/server-java/FileDownLoad", headers=UA, timeout=180,
                              data={"step": "9", "filePath": "/home/html/nas/STR/", "fileName": fn, "functionName": "t100sb02_1"})
            b = r.content
            if r.ok and (b[:4] == b"%PDF" or b[:2] == b"PK"):
                return b
            log(f"    下載 {fn}:{r.status_code} {len(b)}B 不是簡報({b[:12]!r})")
        except Exception as e:
            log(f"    下載 {fn} 失敗:{str(e)[:80]}")
        time.sleep(5)
    return None


def pptx_parts(b):
    """pptx → 文字(每頁)+ 圖片(文字太少時當圖片簡報餵給 Gemini)"""
    z = zipfile.ZipFile(io.BytesIO(b))
    slides = sorted([n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)],
                    key=lambda n: int(re.search(r"(\d+)", n).group(1)))
    texts = []
    for n in slides:
        x = z.read(n).decode("utf-8", "replace")
        t = " ".join(re.findall(r"<a:t>([^<]*)</a:t>", x)).strip()
        if t:
            texts.append(f"[第 {len(texts)+1} 頁] {t}")
    txt = "\n".join(texts)
    parts = []
    if len(txt) >= 600:
        parts.append({"text": "以下是法說會簡報(pptx)逐頁文字:\n" + txt[:60000]})
    else:
        media = [n for n in z.namelist() if n.startswith("ppt/media/") and re.search(r"\.(png|jpe?g)$", n, re.I)]
        tot = 0
        for n in media[:24]:
            raw = z.read(n)
            if tot + len(raw) > 12 * 1024 * 1024:
                break
            tot += len(raw)
            parts.append({"inline_data": {"mime_type": "image/png" if n.lower().endswith("png") else "image/jpeg",
                                          "data": base64.b64encode(raw).decode()}})
        if txt:
            parts.append({"text": "簡報可擷取文字:\n" + txt[:20000]})
    return parts, len(slides)


def pdf_parts(b):
    if len(b) <= INLINE_CAP:
        return [{"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(b).decode()}}]
    # Files API(大檔)
    r = requests.post(f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={KEY}",
                      headers={"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                               "X-Goog-Upload-Header-Content-Length": str(len(b)),
                               "X-Goog-Upload-Header-Content-Type": "application/pdf", "Content-Type": "application/json"},
                      json={"file": {"display_name": "conf.pdf"}}, timeout=60)
    up = r.headers.get("X-Goog-Upload-URL") or r.headers.get("x-goog-upload-url")
    if not up:
        raise RuntimeError(f"Files API 起始失敗 {r.status_code}")
    r2 = requests.post(up, headers={"X-Goog-Upload-Command": "upload, finalize", "X-Goog-Upload-Offset": "0"}, data=b, timeout=600)
    fj = (r2.json() or {}).get("file", {})
    name, uri, state = fj.get("name"), fj.get("uri"), fj.get("state")
    for _ in range(40):
        if state == "ACTIVE":
            break
        time.sleep(5)
        fj = requests.get(f"https://generativelanguage.googleapis.com/v1beta/{name}?key={KEY}", timeout=30).json()
        state = fj.get("state")
    if state != "ACTIVE":
        raise RuntimeError("Files API 未就緒")
    return [{"file_data": {"file_uri": fj.get("uri") or uri, "mime_type": "application/pdf"}}]


# ─────────────────────────── ③ Gemini ───────────────────────────
SCHEMA = {"type": "OBJECT", "properties": {
    "readable": {"type": "BOOLEAN"},
    "tone": {"type": "STRING"},
    "head": {"type": "STRING"},
    "period": {"type": "STRING"},
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

PROMPT = """你是資深台股研究員。附上的是「{name}({sid})」{d} 法人說明會的公司簡報(公開資訊觀測站原檔{extra})。請完整讀完每一頁(含圖表裡的數字),用繁體中文輸出 JSON:

- readable:簡報內容是否真的可讀(若檔案空白、只有封面、完全無法辨識 → false,其他欄位留空,絕不憑公司名稱腦補)
- tone:管理層整體語氣,只能是「正面」「中性」「保守」其一
- head:一句話(30 字內)講出這場法說最關鍵的訊息(像財經媒體標題,要有結論,不要「公司說明營運概況」這種空話)
- period:簡報涵蓋的財務期間(例「2026 Q2 / 上半年」)
- summary:200~350 字摘要——公司現況、本季/上半年表現與原因、對未來的看法;數字照簡報原文
- numbers:簡報中的關鍵數字 6~12 項 [{{k:項目, v:數值(含單位), chg:年增/季增(有才寫)}}],例如營收、毛利率、營益率、EPS、各產品線占比、資本支出、產能利用率、訂單能見度
- guidance:公司對下一季/下半年/明年的具體指引或展望 2~6 條(數字與方向;沒有就寫「未給具體指引」一條)
- drivers:成長動能 2~5 條(新產品、新客戶、擴產、產業趨勢;要具體到簡報內容)
- products:主要產品/業務與營收占比(有才寫)
- capex:資本支出與擴產計畫(有才寫,含金額/時程)
- risks:簡報提到或數字顯露的風險與保守訊號 2~5 條(匯率、庫存、價格、客戶集中、毛利壓力…)
- watch:投資人接下來最該追蹤的 2~4 個觀察點
- quotes:簡報裡最有代表性的原句 0~3 句(照抄,沒有就空)
- deep:一篇 600~1100 字的深度分析文(Markdown):破題導言(本場最大張力或亮點+核心數字)→ 2~4 段「有結論的小標 + 把數字放進因果脈絡的敘事」→「### 投資人接下來該盯什麼」收尾。不做買賣建議。

金額單位檢查:每一筆金額都同時核對幣別與倍率，summary、numbers、guidance、deep必須表示同一實際金額。billion／十億元＝10億元；million／百萬元＝0.01億元。若保留46.72 billion，請寫46.72十億美元或467.2億美元，不可寫46.72億美元。EPS每股元、百分比與金額科目分開，不能套金額倍率。輸出前逐項比對摘要與numbers，不確定保留來源單位並註明待核對。

鐵則:只寫簡報裡真的有的內容,數字務必照原文,沒有的欄位留空或寫「簡報未提供」;絕不編造數字、引言或指引。"""


_G = {"n": 0}


def gemini_json(parts, max_tokens=8192):
    if _G["n"] > 0:
        time.sleep(4)
    _G["n"] += 1
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3,
                                 "responseMimeType": "application/json", "responseSchema": SCHEMA}}
    last = ""
    for mdl in MODELS:
        for attempt in range(2):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={KEY}",
                                  json=body, timeout=900)
            except Exception as e:
                last = f"連線 {str(e)[:60]}"; time.sleep(15); continue
            if r.status_code == 429:
                last = f"{mdl} 429"; log(f"    {mdl} 429 → 換模型"); break
            if r.status_code in (500, 503):
                last = f"{mdl} {r.status_code}"; time.sleep(20 * (attempt + 1)); continue
            if r.status_code == 404:
                last = f"{mdl} 404"; break
            if not r.ok:
                last = f"{mdl} {r.status_code} {r.text[:120]}"; break
            j = r.json()
            ps = ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            txt = "".join(p.get("text", "") for p in ps).strip()
            if not txt:
                last = f"{mdl} 空回應"; break
            try:
                o = json.loads(txt)
            except Exception:
                m = re.search(r"\{[\s\S]*\}", txt)
                o = json.loads(m.group(0)) if m else None
            if isinstance(o, dict):
                o["_model"] = mdl
                return o
            last = f"{mdl} JSON 解析失敗"; break
    raise RuntimeError(last or "Gemini 全部失敗")


# ─────────────────────────── ④ 儲存 ───────────────────────────
def load_ir(sid):
    try:
        return json.load(open(f"{DIR}/{sid}.json", encoding="utf-8"))
    except Exception:
        return {"v": 3, "id": sid, "conf": []}


def save_ir(sid, j):
    os.makedirs(DIR, exist_ok=True)
    j["conf"].sort(key=lambda c: c["d"], reverse=True)
    with open(f"{DIR}/{sid}.json", "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, separators=(",", ":"))


def upsert(j, c):
    """同一檔同一天(或同簡報檔名)視為同一場"""
    for x in j["conf"]:
        if x["d"] == c["d"] or (c.get("fm") and x.get("fm") == c["fm"]):
            for k in ("t", "loc", "msg", "fm", "fe", "site", "vod", "mk", "name"):
                if c.get(k) and not x.get(k):
                    x[k] = c[k]
            return x
    x = {k: c.get(k) for k in ("d", "t", "loc", "msg", "fm", "fe", "site", "vod", "mk", "name")}
    j["conf"].append(x)
    return x


def main():
    if not KEY:
        log("✗ 未設定 GEMINI_KEY Secret"); sys.exit(1)
    try:
        data = json.load(open("data.json", encoding="utf-8"))
        S = {s["id"]: s for s in data.get("stocks") or []}
    except Exception:
        S = {}
    log(f"① 抓法說會清單(近 {MONTHS_BACK + 1} 個月)…")
    allc = collect(MONTHS_BACK)
    log(f"  共 {len(allc)} 場")
    # 併入 ir/ 永久檔
    touched = {}
    for c in allc:
        if ONLY and c["id"] != ONLY:
            continue
        j = touched.get(c["id"]) or load_ir(c["id"])
        upsert(j, c)
        touched[c["id"]] = j
    # 待分析佇列:有簡報檔、還沒 AI(或舊版 pv)、日期 ≤ 今天;最新優先、市值大優先
    def cap(sid):
        try:
            return float(((S.get(sid) or {}).get("co") or {}).get("cap") or 0)
        except Exception:
            return 0.0
    queue = []
    for sid, j in touched.items():
        for x in j["conf"]:
            if x["d"] > TODAY.isoformat() or not (x.get("fm") or x.get("fe")):
                continue
            if x.get("ai") and x.get("pv") == PV:
                continue
            if (x.get("fail") or 0) >= 2 and x.get("pv") == PV:
                continue
            queue.append((sid, x))
    queue.sort(key=lambda q: (q[1]["d"], cap(q[0])), reverse=True)
    log(f"② 待分析 {len(queue)} 場,本班最多 {MAX_PER_RUN}:{[(q[0], q[1]['d']) for q in queue[:MAX_PER_RUN]]}")
    done = 0
    for sid, x in queue[:MAX_PER_RUN]:
        name = x.get("name") or (S.get(sid) or {}).get("name") or sid
        log(f"▶ {sid} {name} {x['d']} 檔案 {x.get('fm') or x.get('fe')}")
        try:
            fn = x.get("fm") or x.get("fe")
            b = download(fn)
            if not b and x.get("fm") and x.get("fe"):
                fn = x["fe"]; b = download(fn)
            if not b:
                x["fail"] = (x.get("fail") or 0) + 1; x["pv"] = PV
                log("    簡報下載不到,記一次失敗"); continue
            extra = ""
            if b[:4] == b"%PDF":
                parts = pdf_parts(b); src = "pdf"
            else:
                parts, n = pptx_parts(b); src = "pptx"; extra = f",pptx 共 {n} 頁"
                if not parts:
                    x["fail"] = (x.get("fail") or 0) + 1; x["pv"] = PV
                    log("    pptx 沒有可用內容"); continue
            if fn.upper().find("E0") > 0 and not x.get("fm"):
                extra += ",英文版"
            parts.append({"text": PROMPT.format(name=name, sid=sid, d=x["d"], extra=extra)})
            o = gemini_json(parts)
        except RuntimeError as e:
            log(f"  ⏸ Gemini 受限({e})——本班提前收工,佇列留給下一班"); break
        except Exception as e:
            log(f"    例外:{str(e)[:160]}"); continue
        if not o.get("readable") or not o.get("summary"):
            x["fail"] = (x.get("fail") or 0) + 1; x["pv"] = PV
            log(f"    AI 判定簡報不可讀(readable={o.get('readable')}),記一次失敗"); continue
        ai = {k: o.get(k) for k in ("tone", "head", "period", "summary", "numbers", "guidance", "drivers", "products", "capex", "risks", "watch", "quotes", "deep")}
        if ai.get("deep"):   # flash-lite 常把 Markdown 小標黏在同一行 → 補換行
            ai["deep"] = re.sub(r"\s*(#{2,4} )", r"\n\n\1", ai["deep"]).strip()
        x["ai"] = ai; x["pv"] = PV; x["src"] = src; x["file"] = fn; x["model"] = o.get("_model")
        x["ts"] = NOW.strftime("%Y-%m-%d %H:%M"); x.pop("fail", None)
        done += 1
        log(f"    ✅ {ai.get('tone')}|{str(ai.get('head'))[:50]}({len(ai.get('deep') or '')} 字,{o.get('_model')})")
    # 寫檔
    for sid, j in touched.items():
        save_ir(sid, j)
    # conf_ai.json(每檔最新一場有 AI 的)+ ir_index.json
    try:
        store = json.load(open(OUT, encoding="utf-8"))
        assert isinstance(store.get("items"), dict)
    except Exception:
        store = {"v": 2, "items": {}}
    store["v"] = 2
    idx = {}
    for fn in os.listdir(DIR) if os.path.isdir(DIR) else []:
        if not fn.endswith(".json"):
            continue
        sid = fn[:-5]
        try:
            j = json.load(open(f"{DIR}/{fn}", encoding="utf-8"))
        except Exception:
            continue
        idx[sid] = [c["d"] for c in j["conf"]]
        latest = next((c for c in j["conf"] if c.get("ai")), None)
        if latest:
            a = latest["ai"]
            store["items"][sid] = {"d": latest["d"], "src": latest.get("src", "pdf"), "ref": latest.get("file", ""),
                                   "pv": PV, "ts": latest.get("ts", ""), "tone": a.get("tone"), "head": a.get("head"),
                                   "period": a.get("period"), "summary": a.get("summary"), "guidance": a.get("guidance"),
                                   "numbers": a.get("numbers"), "drivers": a.get("drivers"), "risks": a.get("risks"),
                                   "watch": a.get("watch"), "capex": a.get("capex"), "ai": a.get("deep", "")}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))
    with open(IDX, "w", encoding="utf-8") as f:
        json.dump({"t": NOW.strftime("%Y-%m-%d %H:%M"), "n": len(idx), "s": idx}, f, ensure_ascii=False, separators=(",", ":"))
    left = max(0, len(queue) - done)
    log(f"完成:本班分析 {done} 場;庫存 {len(idx)} 檔有法說紀錄、{len(store['items'])} 檔有 AI 分析;待分析還剩約 {left} 場")
    print(f"::notice::法說會:本班分析 {done} 場,待分析剩 {left} 場,庫存 {len(store['items'])} 檔")


if __name__ == "__main__":
    main()
