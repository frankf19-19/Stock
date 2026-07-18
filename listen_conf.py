"""法說會 AI 聽讀分析 → conf_ai.json(架構同 listen_gooaye.py,共用 GEMINI_KEY 免費金鑰)
對「近 4 天開過法說」的個股,依序嘗試三層素材,由深至淺:
  ① YouTube 完整影片(conf_media.json 手動指定,或 Gemini 搜尋+oEmbed 驗證)→ 聽整場
  ② 公司簡報/逐字稿 PDF(MOPS + 擇要內附的公司 IR 連結)→ 讀全文
  ③ 擇要+相關報導文字 → 基本分析
輸出獨立檔 conf_ai.json(不動 data.json,避免與盤中報價工作流互撞);同場次不重跑(零成本)。
需要 Secret:GEMINI_KEY。排程:conf_ai.yml(平日台北 18:40 + 手動)。"""
import base64
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.parse

import requests

KEY = os.environ.get("GEMINI_KEY", "").strip()
PV = 2   # 提示詞版本:升版後既有場次會自動以新規格重寫一次
MODEL = "gemini-2.5-flash"
OUT = "conf_ai.json"
UA = {"User-Agent": "Mozilla/5.0 (conf-digest; personal dashboard)"}
MAX_PER_RUN = 6
PDF_BYTES_CAP = 18 * 1024 * 1024


def log(*a):
    print(*a, flush=True)


def proxy_url():
    try:
        u = json.load(open("proxy.json", encoding="utf-8")).get("url", "").strip()
        return u.rstrip("/") if u.startswith("https://") else ""
    except Exception:
        return ""


PROXY = proxy_url()


def http_get(url, timeout=45, binary=False):
    for u in ([url] + ([PROXY + "/?url=" + urllib.parse.quote(url, safe="")] if PROXY else [])):
        try:
            r = requests.get(u, headers=UA, timeout=timeout)
            if r.ok:
                return r.content if binary else r.text
        except Exception:
            continue
    return None


def http_post(url, data, timeout=60):
    for u in ([url] + ([PROXY + "/?url=" + urllib.parse.quote(url, safe="")] if PROXY else [])):
        try:
            r = requests.post(u, data=data, headers=UA, timeout=timeout)
            if r.ok and len(r.text) > 300:
                return r.text
        except Exception:
            continue
    return None


_G = {"n": 0}
def gemini(parts, max_tokens=4096, tools=None, timeout=600):
    """免費層節流:呼叫間隔 6 秒、單輪上限 15 次;429/5xx 退避重試 3 次,
    仍失敗即拋 RuntimeError('RATE')——由主流程提前收工、不記失敗(佇列留給下一班)。"""
    import time as _t
    if _G["n"] >= 15:
        raise RuntimeError("BUDGET")
    if _G["n"] > 0:
        _t.sleep(6)
    _G["n"] += 1
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": max_tokens}}
    if tools:
        body["tools"] = tools
    for attempt in range(3):
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}",
                json=body, timeout=timeout)
        except Exception as e:
            log(f"  Gemini 連線例外(第{attempt+1}次):{str(e)[:80]}")
            _t.sleep(20 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 503):
            log(f"  Gemini {r.status_code}(第{attempt+1}次),退避重試…")
            _t.sleep(25 * (attempt + 1) + 5)
            continue
        if not r.ok:
            log(f"  ✗ Gemini {r.status_code}: {r.text[:200]}")
            return ""
        ps = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in ps).strip()
    raise RuntimeError("RATE")


def yt_title(url):
    try:
        j = requests.get("https://www.youtube.com/oembed",
                         params={"url": url, "format": "json"}, headers=UA, timeout=15).json()
        return j.get("title", "")
    except Exception:
        return ""


def find_youtube(s, c):
    """① conf_media.json 手動指定 ② Gemini 搜尋 + oEmbed 標題驗證(公司名+法說關鍵字都要對)"""
    try:
        mm = json.load(open("conf_media.json", encoding="utf-8"))
        u = (mm.get(s["id"]) or "").strip()
        if re.fullmatch(r"https://www\.youtube\.com/watch\?v=[\w-]{6,}", u):   # 嚴格格式,擋掉範例占位字
            log(f"    conf_media.json 指定影片:{u}")
            return u
    except Exception:
        pass
    try:
        d = dt.date.fromisoformat(c["d"])
        q = (f"搜尋「{s['name']}」({s['id']})在 {d.year} 年 {d.month} 月召開的法人說明會/法說會完整影片"
             f"(YouTube)。只回覆一行影片網址(https://www.youtube.com/watch?v=開頭),"
             f"找不到就只回覆 NONE,不要任何其他文字。")
        txt = gemini([{"text": q}], max_tokens=100,
                     tools=[{"google_search": {}}], timeout=90)
        u = (re.search(r"https://www\.youtube\.com/watch\?v=[\w-]{6,}", txt) or [None])[0]
        if not u:
            return None
        t = yt_title(u)
        if s["name"] in t and re.search(r"法說|法人說明會|earnings|investor", t, re.I):
            log(f"    Gemini 搜尋找到並驗證:{u}({t[:40]})")
            return u
        log(f"    搜尋到 {u} 但標題不符({t[:40]}),棄用")
    except Exception as e:
        log(f"    影片搜尋失敗:{e}")
    return None


def gather_pdfs(s, c):
    """MOPS 該公司法說頁 + 擇要內附的公司 IR 連結 → 收 PDF(簡報/逐字稿),總量 18MB 內"""
    pdfs, total = [], 0

    def add(url):
        nonlocal total
        if len(pdfs) >= 3 or total >= PDF_BYTES_CAP:
            return
        blob = http_get(url, timeout=90, binary=True)
        if blob and blob[:4] == b"%PDF" and total + len(blob) <= PDF_BYTES_CAP:
            pdfs.append((url, blob))
            total += len(blob)
            log(f"    PDF {len(blob)//1024}KB ← {url[:80]}")

    try:
        d = dt.date.fromisoformat(c["d"])
        typek = "otc" if s.get("ex") == "otc" else "sii"
        html = http_post("https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1",
                         {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
                          "isQuery": "Y", "TYPEK": typek, "year": str(d.year - 1911),
                          "co_id": s["id"]})
        if html:
            links = re.findall(r"href=['\"]([^'\"]+?\.pdf)['\"]", html, re.I)
            zh = [x for x in links if re.search(r"[Cc]\.pdf$|_c", x)] or links
            for u in zh[:2]:
                if u.startswith("/"):
                    u = "https://mopsov.twse.com.tw" + u
                elif not u.startswith("http"):
                    u = "https://mopsov.twse.com.tw/" + u.lstrip("./")
                add(u)
    except Exception as e:
        log(f"    MOPS PDF 蒐集失敗:{e}")
    try:
        m = re.search(r"https?://[\w\-./?=&%#]+", c.get("msg", ""))
        if m:
            page = http_get(m.group(0), timeout=45)
            if page:
                for u in re.findall(r"href=['\"]([^'\"]+?\.pdf)['\"]", page, re.I)[:4]:
                    u = urllib.parse.urljoin(m.group(0), u)
                    if re.search(r"transcript|presentation|逐字|簡報|chinese|mandarin", u, re.I):
                        add(u)
    except Exception as e:
        log(f"    IR 頁 PDF 蒐集失敗:{e}")
    return pdfs


PROMPT_DEEP = """你是台股研究員。請根據{src_desc},用繁體中文寫「{name}({sid}){d} 法人說明會完整整理」,總長 700~1400 字,目標是「看完可以不用再看原始素材」的詳細度,直接開始不要開場白。

格式:
## 本季成績單
實際數字逐項寫出:營收(含年增/季增)、毛利率、營益率、EPS、重要產品線佔比——務必照素材原文的數字,並用一兩句說明管理層怎麼歸因。

## 依議程逐段重點
每個主題一段:**小標** + 管理層實際說了什麼(3~6 句,務必包含具體數字、產品線/客戶群名稱、管理層用的措辭或比喻)+ 這段透露了什麼。不要只寫一句話標題,要寫出內容本身。

## 展望與指引
下季與全年的具體指引:營收區間、毛利率區間、資本支出金額與變動方向;管理層口吻偏樂觀或保守,從哪些用字看出來。

## 產業與需求判讀
各終端市場(AI/HPC、手機、車用、消費性等,素材有提到的才寫)管理層的看法與依據。

## 風險與保守訊號
提到的逆風、下修、供應鏈或地緣風險,以及刻意輕描淡寫或迴避的部分。

{qa_line}## 一句話結論
這場法說整體偏多/偏空/中性,一句話說出最關鍵的理由。

規則:只寫素材裡真的有的內容,沒有的段落整段省略、絕不腦補;數字務必照原文;聽不清楚或原文模糊的地方註明。最後一行固定:AI 自動分析,非投資建議,請以公司原始資料為準。"""

PROMPT_LITE = """你是台股研究員。請根據{src_desc},用繁體中文寫「{name}({sid}){d} 法人說明會重點分析」,200~500 字,直接開始不要開場白,條列格式:

**關鍵財務數字**:素材中實際出現的數字(有才寫)。
**展望與指引**:具體指引與管理層口吻(有才寫)。
**風險與保守訊號**:有才寫。
{qa_line}**一句話結論**:偏多/偏空/中性+理由;素材不足以判斷就誠實寫中性並說明原因。

規則:只寫素材裡真的有的內容,絕不腦補。最後一行固定:AI 自動分析,非投資建議,請以公司原始資料為準。"""

def analyze(s, c, news_titles):
    d = c["d"]
    yt = find_youtube(s, c)
    if yt:
        parts = [{"file_data": {"file_uri": yt}},
                 {"text": PROMPT_DEEP.format(src_desc="這段法說會完整影片(請聽完全場,包含 QA)",
                                             name=s["name"], sid=s["id"], d=d,
                                             qa_line="## QA 重點\n逐組整理:法人問了什麼、管理層怎麼答、哪些問題被迴避或答得保守——這通常是整場最有資訊量的部分,請完整寫。\n\n")}]
        txt = gemini(parts, max_tokens=8192)
        if txt:
            return txt, "yt", yt
    pdfs = gather_pdfs(s, c)
    if pdfs:
        parts = [{"inline_data": {"mime_type": "application/pdf",
                                  "data": base64.b64encode(b).decode()}} for _, b in pdfs]
        has_ts = any(re.search(r"transcript|逐字", u, re.I) for u, _ in pdfs)
        parts.append({"text": PROMPT_DEEP.format(
            src_desc="附上的公司法說簡報" + ("與逐字稿" if has_ts else "") + " PDF(請讀完全文)",
            name=s["name"], sid=s["id"], d=d,
            qa_line=("## QA 重點\n逐組整理逐字稿中的法人提問與管理層回答,哪些答得保守或迴避。\n\n" if has_ts else ""))})
        txt = gemini(parts, max_tokens=8192)
        if txt:
            return txt, "pdf", pdfs[0][0]
    material = "擇要:" + c.get("msg", "") + "\n報導標題:\n" + "\n".join(news_titles[:6])
    if len(material) > 40:
        txt = gemini([{"text": PROMPT_LITE.format(src_desc="以下擇要訊息與新聞標題(素材有限,請保守撰寫)",
                                                  name=s["name"], sid=s["id"], d=d, qa_line="")
                       + "\n\n=== 素材 ===\n" + material[:6000]}], max_tokens=4096)
        if txt:
            return txt, "text", ""
    return "", "", ""


def main():
    if not KEY:
        log("✗ 未設定 GEMINI_KEY Secret")
        sys.exit(1)
    try:
        data = json.load(open("data.json", encoding="utf-8"))
    except Exception as e:
        log(f"✗ data.json 讀取失敗:{e}")
        sys.exit(1)
    try:
        store = json.load(open(OUT, encoding="utf-8"))
        assert isinstance(store.get("items"), dict)
    except Exception:
        store = {"v": 1, "items": {}}
    if store.get("fv") != 2:                             # 一次性遷移:清掉 2026-07-18 額度事故造成的冤枉失敗記錄
        n0 = len(store["items"])
        store["items"] = {k: v for k, v in store["items"].items() if v.get("ai")}
        store["fv"] = 2
        if n0 != len(store["items"]):
            log(f"  清除額度事故空記錄:{n0 - len(store['items'])} 筆(重新給予完整重試機會)")
    today = dt.date.today()
    news = [n.get("title", "") for n in (data.get("news") or [])]
    targets = []
    for s in data.get("stocks") or []:
        c = s.get("conf")
        if not c or not c.get("d"):
            continue
        try:
            d = dt.date.fromisoformat(c["d"])
        except Exception:
            continue
        if not (today - dt.timedelta(days=4) <= d <= today):
            continue
        prev = store["items"].get(s["id"])
        if prev and prev.get("d") == c["d"] and prev.get("pv") == PV:
            if prev.get("ai"):
                continue                                  # 已成功分析
            if prev.get("fail", 0) >= 2:
                continue                                  # 失敗兩次:讓位,等素材出現(pv 升版會重試)
        targets.append((s, c))
    if not targets:
        log("近 4 天無待分析場次(或皆已分析),結束(零成本)。")
        return
    def _cap(t):                                          # 🥇 市值大的優先(台積電這種指標場次不被排擠)
        try:
            return float(((t[0].get("co") or {}).get("cap")) or 0)
        except Exception:
            return 0.0
    targets.sort(key=_cap, reverse=True)
    log(f"待分析:{len(targets)} 檔(本輪最多 {MAX_PER_RUN})→ 佇列:{[t[0]['id'] for t in targets[:MAX_PER_RUN]]}")
    done = 0
    for s, c in targets[:MAX_PER_RUN]:
        log(f"▶ {s['id']} {s['name']} {c['d']}")
        titles = [t for t in news if s["name"] in t or s["id"] in t]
        try:
            txt, src, ref = analyze(s, c, titles)
        except RuntimeError as e:
            log(f"  ⏸ Gemini 額度/頻率受限({e})——本輪提前收工,不記失敗,佇列留給下一班(18:40/21:40 自動續跑)")
            break
        except Exception as e:
            log(f"    例外:{e}")
            continue
        if not txt:
            prev = store["items"].get(s["id"]) or {}
            nfail = (prev.get("fail", 0) + 1) if (prev.get("d") == c["d"] and prev.get("pv") == PV) else 1
            store["items"][s["id"]] = {"d": c["d"], "pv": PV, "src": "", "ref": "", "ai": "",
                                       "fail": nfail,
                                       "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
            log(f"    三層素材皆不可得(第 {nfail} 次)——已記錄,重試 2 次後讓位")
            continue
        store["items"][s["id"]] = {"d": c["d"], "src": src, "ref": ref, "pv": PV,
                                   "ai": txt[:6000],
                                   "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
        done += 1
        log(f"    ✅ 完成({ {'yt':'聽完全場影片','pdf':'讀完簡報/逐字稿','text':'文字素材'}[src] },{len(txt)} 字)")
    # 清理:超過 30 天的舊分析
    for sid in list(store["items"]):
        try:
            if dt.date.fromisoformat(store["items"][sid]["d"]) < today - dt.timedelta(days=30):
                del store["items"][sid]
        except Exception:
            del store["items"][sid]
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False)
    log(f"完成:{done} 檔 → {OUT}(庫存 {len(store['items'])} 檔)")


if __name__ == "__main__":
    main()
