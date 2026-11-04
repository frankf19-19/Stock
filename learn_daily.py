#!/usr/bin/env python3
"""r1225:📚 每天學一點(Frank 11/04:「網站要不斷學習進步,每天都要新的新聞、推薦書籍、好的節目內容、產業新聞」)
每天早上(news.yml 早報之後)產生 learn_daily.json,永久累積、只增不減:
  今日一課  — AI 從今天的早報/盤勢/節目挑「一個」新手該懂的觀念,白話 3 段(是什麼・今天為什麼重要・下次看到怎麼用);
              會看過去 90 天教過的題目,不重複,所以每天都是新的一課
  今日好書  — 從節目推薦過的書(yth_books.json)挑一本跟今天主題最有關的,一句為什麼;沒 AI 就照日期輪著推
  節目重點  — 股癌、財經皓角最新一集各 3 句重點(從 AI 聆聽整理擷取)+ 連結
  產業新聞  — 今天早報依「受影響族群」分組(早報本來就有,這裡整理成族群 → 幾則)
用法:python learn_daily.py   (FORCE=1 當天重做)"""
import json, os, re, sys, time, datetime as dt
import requests

KEY = os.environ.get("GEMINI_KEY", "").strip()
TP = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.datetime.now(TP).strftime("%Y-%m-%d")
OUT = "learn_daily.json"

def log(*a): print(*a, flush=True)

def jl(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d

def sect(md, head):
    """從 AI 聆聽整理(markdown)抓某個 ## 段落的文字"""
    m = re.search(r"##\s*" + head + r"[^\n]*\n(.*?)(?=\n##\s|\Z)", md or "", re.S)
    return (m.group(1).strip() if m else "")

def bullets(txt, n=3):
    L = [re.sub(r"^[\*\-•\s]+", "", x).strip() for x in (txt or "").split("\n")]
    L = [x for x in L if len(x) >= 8]
    if not L:   # 沒有條列就切句
        L = [x.strip() for x in re.split(r"(?<=[。！？])", txt or "") if len(x.strip()) >= 12]
    def cut(x):
        if len(x) <= 120: return x
        i = max(x.rfind("。", 0, 120), x.rfind("；", 0, 120), x.rfind("，", 0, 120))
        return (x[:i + 1] if i >= 40 else x[:118] + "…")
    return [cut(x) for x in L[:n]]

def show_items():
    out = []
    for key, p, name in (("gooaye", "gooaye.json", "股癌"), ("yth", "yth.json", "財經皓角")):
        J = jl(p) or {}
        ep = ((J.get("eps") or [None])[0]) or J
        s = ep.get("s") or ""
        view = sect(s, "市場/總經觀點") or sect(s, "市場總經觀點") or sect(s, "總經") or ""
        pts = bullets(view) or bullets(s)
        out.append({"show": key, "name": name, "t": ep.get("t") or J.get("t") or "", "dt": (ep.get("dt") or J.get("dt") or "")[:10],
                    "url": ep.get("yt") or J.get("yt") or "", "pts": pts})
    return out

def news_groups(N):
    g = {}
    for it in (N or {}).get("items") or []:
        for grp in it.get("groups") or []:
            g.setdefault(grp, []).append({"title": it.get("title", ""), "lv": it.get("lv", 1), "codes": (it.get("codes") or [])[:4]})
    return [{"g": k, "n": len(v), "items": v[:4]} for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))][:10]

def book_pool():
    B = (jl("yth_books.json") or {}).get("books") or []
    seen, out = set(), []
    for b in B:
        t = (b.get("title") or "").strip().strip("》《")
        if not t or t in seen: continue
        seen.add(t); out.append({"title": t, "author": b.get("author", ""), "why": b.get("why", ""), "pub": b.get("pub", ""),
                                 "url": b.get("url") or b.get("yt_url") or "", "ep": b.get("ep", ""), "ep_dt": b.get("ep_dt", "")})
    return out

SCHEMA = {"type": "object", "properties": {
    "lesson": {"type": "object", "properties": {
        "title": {"type": "string"}, "what": {"type": "string"}, "why_today": {"type": "string"}, "how": {"type": "string"},
        "terms": {"type": "array", "items": {"type": "string"}}}, "required": ["title", "what", "why_today", "how"]},
    "book_idx": {"type": "integer"}, "book_why": {"type": "string"},
    "one_line": {"type": "string"}}, "required": ["lesson", "book_idx", "book_why", "one_line"]}

def gemini(p):
    if not KEY: log("  ✗ 沒有 GEMINI_KEY"); return None
    gc = {"maxOutputTokens": 4096, "temperature": 0.5, "responseMimeType": "application/json", "responseSchema": SCHEMA}
    body = {"contents": [{"role": "user", "parts": [{"text": p}]}], "generationConfig": gc}
    for attempt, mdl in enumerate(["gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]):
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={KEY}", json=body, timeout=180)
            if r.status_code in (429, 500, 503, 404):
                log(f"  gemini {mdl} {r.status_code},換模型"); time.sleep(8 if attempt < 3 else 40); continue
            if not r.ok: log(f"  gemini {mdl} 錯誤 {r.status_code}:{r.text[:200]}"); continue
            cand = (r.json().get("candidates") or [{}])[0]
            txt = "".join(x.get("text", "") for x in ((cand.get("content") or {}).get("parts") or []) if not x.get("thought"))
            j = json.loads(txt); j["_model"] = mdl; return j
        except Exception as e:
            log(f"  gemini 例外:{e}"); time.sleep(8)
    return None

def prompt(N, V, shows, books, past_titles):
    news = "\n".join(f"- {it.get('title','')}:{it.get('what','')} {it.get('why','')}" for it in (N.get("items") or [])[:10])
    head = (V or {}).get("head", "")
    sh = "\n".join(f"- {s['name']}《{s['t'][:40]}》:" + " / ".join(s["pts"]) for s in shows)
    bk = "\n".join(f"[{i}] 《{b['title']}》{b.get('author','')}:{(b.get('why') or '')[:80]}" for i, b in enumerate(books[:60]))
    past = "、".join(past_titles[-90:]) or "(還沒有)"
    return f"""你是幫股票新手上課的老師。今天是 {TODAY}。請從今天的市場內容裡挑「一個」新手最該學會的觀念,寫成一課。

【今天的盤勢一句話】{head}
【今天的產業早報】
{news}
【節目最新一集的重點】
{sh}
【過去已經教過的題目(不要重複、也不要換個說法再教一次)】{past}

規則:
1. lesson.title:題目,12 字內,白話(例:「融資斷頭是什麼」「為什麼財報好股價還跌」)。
2. lesson.what:這個觀念是什麼,2~3 句,完全白話,不用術語;非用不可就括號解釋。
3. lesson.why_today:今天為什麼值得學,要連到上面某一則新聞或節目內容,2 句。
4. lesson.how:下次在網站或新聞看到這個字,該怎麼判讀、怎麼用在自己的買賣,2~3 句,要具體。
5. lesson.terms:這一課用到的 1~3 個關鍵字(名詞)。
6. 從下面的書單挑一本跟今天這一課最有關的,book_idx 填方括號裡的編號,book_why 一句話說為什麼今天適合看它(20 字內);書單:
{bk}
7. one_line:用一句話(30 字內)總結「今天學到的一件事」。
8. 全部繁體中文(台灣用語),不用驚嘆號,不寫投資建議。"""

def main():
    D = jl(OUT) or {"v": 1, "days": {}, "dates": []}
    if TODAY in D["days"] and D["days"][TODAY].get("lesson") and os.environ.get("FORCE") != "1":
        log(f"{TODAY} 已有,跳過"); return
    N = jl("news.json") or {}
    V = jl("view.json") or {}
    shows = show_items()
    books = book_pool()
    groups = news_groups(N)
    past = [D["days"][d].get("lesson", {}).get("title", "") for d in D["dates"] if D["days"].get(d, {}).get("lesson")]
    past = [t for t in past if t]
    ai = gemini(prompt(N, V, shows, books, past)) if N.get("items") else None
    day = {"d": TODAY, "gen": dt.datetime.now(TP).strftime("%Y-%m-%d %H:%M"), "shows": shows, "groups": groups,
           "news_mood": N.get("mood", ""), "head": V.get("head", "")}
    if ai and ai.get("lesson", {}).get("title"):
        L = ai["lesson"]; L["title"] = L["title"].strip()[:24]
        day["lesson"] = L; day["one_line"] = ai.get("one_line", "")
        bi = ai.get("book_idx")
        if isinstance(bi, int) and 0 <= bi < len(books):
            day["book"] = dict(books[bi], pick_why=ai.get("book_why", ""), by="ai")
        day["model"] = ai.get("_model", "")
        log(f"  今日一課:{L['title']}")
    else:
        log("  AI 沒產出,今日一課留空(明天再補)")
    if "book" not in day and books:
        i = int(dt.datetime.strptime(TODAY, "%Y-%m-%d").timestamp() // 86400) % len(books)
        day["book"] = dict(books[i], pick_why="節目推薦過的好書,今天輪到它", by="rotate")
    D["days"][TODAY] = day
    if TODAY not in D["dates"]: D["dates"].append(TODAY)
    D["dates"].sort()
    D["u"] = day["gen"]; D["n_books"] = len(books)
    json.dump(D, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"✅ {OUT}:{len(D['dates'])} 天")

if __name__ == "__main__":
    main()
