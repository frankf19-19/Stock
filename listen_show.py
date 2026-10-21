#!/usr/bin/env python3
"""r1108:節目自動聆聽整理(通用版)——跟 listen_gooaye.py(股癌)同一套邏輯,改成「一個設定一個節目」:
   iTunes 查最新集 → 同集已整理過就直接結束(零成本)
   → 優先找 YouTube 版(頻道 RSS,用標題比對)→ 找不到(機房被 YouTube 擋是常態)→ 路線C:
     podcast RSS 的 mp3 直下 → Gemini Files API 上傳 → 聆聽整理。
   每集整理永久保留:<out>.json 放最近 N 集(前端用),<hist_dir>/YYYY-MM.json 按月歸檔(永久)。
用法:python listen_show.py yth     需要 Secret:GEMINI_KEY(免費 Gemini 金鑰)。"""
import json, os, re, sys, time
import requests

SHOWS = {
    "yth": {"apple": "1488295306", "out": "yth.json", "hist_dir": "yth_hist", "keep": 20,
            "name": "游庭皓的財經皓角", "host": "游庭皓", "tag": "早晨財經速解讀",
            "yt_cid": "UC0lbAQVpenvfA2QqzsRtL_g",
            "kind": "財經直播節目「游庭皓的財經皓角・早晨財經速解讀」(主持人游庭皓,每個交易日早上 8:30 開盤前,約 30~40 分鐘,"
                    "解讀前一晚美股、總經數據、國際新聞與資金面對台股的影響)"},
}
KEY   = os.environ.get("GEMINI_KEY", "").strip()
MODELS = ["gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"]   # 免費額度各自獨立:2.5 flash 限流/過載就換下一個(2.5 flash-lite、2.0 flash 已下架,404 時 API 指名改用 3.5 flash-lite / 3.8 flash)
UA    = {"User-Agent": "Mozilla/5.0 (kyansuo-digest; personal dashboard)"}

def log(*a): print(*a, flush=True)

def norm(t):
    """標題正規化:去掉日期前綴 2026/10/15(四)、【…】標籤、空白與標點,拿來比對 podcast 標題與 YouTube 標題"""
    t = re.sub(r"^\s*\d{4}/\d{1,2}/\d{1,2}\s*[(（][一二三四五六日天][)）]\s*", "", str(t or ""))
    t = re.sub(r"【[^】]*】", "", t)
    return re.sub(r"[\s\W_]+", "", t).lower()

def newest_episode(C):
    """節目 RSS(Apple 目錄解析出 feedUrl)首項 = 最新集;退回 iTunes episode lookup"""
    try:
        j = requests.get(f"https://itunes.apple.com/lookup?id={C['apple']}", headers=UA, timeout=20).json()
        feed = ((j.get("results") or [{}])[0]).get("feedUrl")
        if feed:
            xml = requests.get(feed, headers=UA, timeout=25).text
            m = re.search(r"<item>(.*?)</item>", xml, re.S)
            if m:
                blk = m.group(1)
                def tag(t):
                    mm = re.search(rf"<{t}[^>]*>(.*?)</{t}>", blk, re.S)
                    v = (mm.group(1) if mm else "").strip()
                    v = re.sub(r"^<!\[CDATA\[(.*)\]\]>$", r"\1", v, flags=re.S).strip()
                    return v
                title = tag("title")
                enc = (re.search(r'<enclosure[^>]*url="([^"]+)"', blk) or [None, ""])[1]
                link = tag("link"); pub = tag("pubDate"); iso = ""
                try:
                    from email.utils import parsedate_to_datetime
                    iso = parsedate_to_datetime(pub).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception: pass
                if title:
                    log(f"  RSS 最新集:{title}")
                    return {"trackName": title, "releaseDate": iso, "episodeUrl": enc, "trackViewUrl": link or enc}
    except Exception as e:
        log(f"  RSS 路失敗({e}),退回 iTunes episode lookup")
    j = requests.get(f"https://itunes.apple.com/lookup?id={C['apple']}&entity=podcastEpisode&limit=5&country=tw",
                     headers=UA, timeout=20).json()
    eps = [x for x in j.get("results", []) if x.get("kind") == "podcast-episode"]
    eps.sort(key=lambda x: x.get("releaseDate", ""), reverse=True)
    return eps[0] if eps else None

def youtube_url(C, title):
    """路線 A:頻道 RSS(頻道 ID 已知)→ 標題比對(podcast 標題去掉日期/標籤後,包含在 YouTube 標題裡)"""
    cid = C.get("yt_cid")
    if not cid: return None
    want = norm(title)
    if len(want) < 6: return None
    try:
        xml = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", headers=UA, timeout=20,
                           cookies={"CONSENT": "YES+cb", "SOCS": "CAI"}).text
        ents = re.findall(r"<entry>(.*?)</entry>", xml, re.S)
        log(f"  頻道 RSS:{len(ents)} 支影片" + (f",最新:{(re.search(r'<title>(.*?)</title>', ents[0], re.S) or [None, ''])[1][:40]}" if ents else "(可能是同意頁/被擋)"))
        for blk in ents:
            t = (re.search(r"<title>(.*?)</title>", blk, re.S) or [None, ""])[1]
            if want in norm(t) or norm(t) in want:
                vid = (re.search(r"<yt:videoId>([\w-]+)</yt:videoId>", blk) or [None, None])[1]
                if vid:
                    u = f"https://www.youtube.com/watch?v={vid}"
                    log(f"  路線A(頻道RSS)找到:{u}({t[:40]})")
                    return u
        log("  路線A:頻道 RSS 裡沒有對得上的標題(直播可能還沒轉成影片)")
    except Exception as e:
        log(f"  路線A 失敗:{e}(機房可能被 YouTube 擋)")
    return None

def gemini_upload_audio(mp3_url, tagname):
    """路線C:下載 podcast mp3 → Gemini Files API resumable 上傳 → 等 ACTIVE → 回 (uri, mime)"""
    log(f"  路線C:下載音檔 {mp3_url[:90]}…")
    ar = requests.get(mp3_url, headers=UA, timeout=300); ar.raise_for_status()
    data = ar.content
    mime = (ar.headers.get("Content-Type", "audio/mpeg").split(";")[0].strip()) or "audio/mpeg"
    if not mime.startswith("audio/"): mime = "audio/mpeg"
    log(f"  音檔 {len(data)/1e6:.1f} MB({mime}),上傳 Gemini Files…")
    r = requests.post(f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={KEY}",
                      headers={"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                               "X-Goog-Upload-Header-Content-Length": str(len(data)),
                               "X-Goog-Upload-Header-Content-Type": mime, "Content-Type": "application/json"},
                      json={"file": {"display_name": tagname}}, timeout=60)
    up = r.headers.get("X-Goog-Upload-URL") or r.headers.get("x-goog-upload-url")
    if not up:
        log(f"  ✗ Files 起始失敗 {r.status_code}: {r.text[:200]}"); return None, None
    r2 = requests.post(up, headers={"X-Goog-Upload-Command": "upload, finalize", "X-Goog-Upload-Offset": "0"}, data=data, timeout=900)
    fj = (r2.json() or {}).get("file", {})
    name, uri, state = fj.get("name"), fj.get("uri"), fj.get("state")
    for _ in range(60):
        if state == "ACTIVE": break
        time.sleep(6)
        try:
            fj = requests.get(f"https://generativelanguage.googleapis.com/v1beta/{name}?key={KEY}", timeout=30).json()
            state = fj.get("state")
        except Exception: pass
    if state != "ACTIVE":
        log(f"  ✗ 音檔處理未完成(state={state})"); return None, None
    log("  ✓ 音檔就緒")
    return (fj.get("uri") or uri), mime

def listen(C, src, title, retry=False):
    """同股癌的整理格式(前端「本集提到的個股與產業」卡片靠這個格式解析),內容描述改成這個節目的性質"""
    body = {"contents": [{"role": "user", "parts": [
        ({"file_data": {"file_uri": src[0], "mime_type": src[1]}} if isinstance(src, tuple) else {"file_data": {"file_uri": src}}),
        {"text": f"""請完整聽完這一集{C['kind']}:「{title}」,用繁體中文寫一份「聽完可以不用再聽」等級的詳細整理,總長 800~1500 字,直接開始不要開場白。
重要:如果你實際上拿不到或聽不到這個影片/音檔的內容(例如影片還在處理、無法存取、只有封面或靜音),請只回覆一行「NO_AUDIO」,絕對不要憑標題或常識編一份看起來像的整理。

格式要求:
## 依節目順序,每個主題一個段落
每段:**主題小標** + 他實際講了什麼(3~5 句,務必包含他引用的數據、數字、公司名、比喻與他的解讀)+ 他的結論或立場是什麼。不要只寫一句話標題,要寫出內容本身。

## 市場/總經觀點
他對大盤、利率/通膨、資金環境、產業循環的判斷,以及**他給的理由**(不是只寫結論);有講到今天台股開盤要注意什麼就寫出來。

## 提及的個股與族群(有講才寫,沒講就整段省略)
每檔一個項目,格式固定:* **股名(代號)**:偏多/偏空/中性。他怎麼說的(原話意思)+他的邏輯。
產業/族群也要各列一項(例如 **記憶體族群**、**散熱族群**、**金融股**),同樣標偏多/偏空/中性。
只是舉例帶過、沒有表態的標「中性(舉例)」;不確定代號就只寫股名,不要猜。

## 本集推薦的書(有講才寫,沒講就整段省略)
每本一個項目,格式固定:* **書名**(作者):他為什麼推薦、書裡講什麼(1~2 句)。只寫他明確講出書名的,不要猜、不要補。

## 值得追蹤的後續(有才寫)
例如他點名的數據公布、財報、事件與他預期的影響。

規則:純閒聊可以一句帶過;會員/贊助/業配段落完全跳過;他沒講的不要腦補;聽不清楚的段落註明。{'他若引用歌詞、詩句或文章原文,一律改用你自己的話描述,不要逐字引用。' if retry else ''}最後一行固定:AI 聆聽全集整理,觀點屬節目主持人,非投資建議。"""}]}],
        "generationConfig": {"maxOutputTokens": 8192, "thinkingConfig": {"thinkingBudget": 0}}}   # 關思考:思考會吃掉輸出額度而斷頭(前端同樣設定)
    r = None
    for model in MODELS:
        for att in range(1, 4):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={KEY}", json=body, timeout=1500)
                if r.ok: break
                if r.status_code in (429, 500, 502, 503):
                    log(f"  {model} 第{att}次 {r.status_code}" + (",60秒後重試…" if att < 3 else ",換下一個模型")); time.sleep(60 if att < 3 else 2); continue
                log(f"  ✗ {model} {r.status_code}: {r.text[:200]},換下一個模型"); break
            except requests.exceptions.Timeout:
                log(f"  {model} 第{att}次讀取逾時(1500s)")
            except Exception as e:
                log(f"  {model} 第{att}次連線異常:{e}"); time.sleep(30)
        if r is not None and r.ok: log(f"  使用模型 {model}"); break
    if r is None or not r.ok:
        log("✗ Gemini 全部模型都失敗(多半是免費額度限流),下次排程再試。"); return "", None
    cand = (r.json().get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    fr = cand.get("finishReason")
    txt = "".join(p.get("text", "") for p in parts).strip()
    txt = re.sub(r"^(好的|以下|這是|當然)[^\n]{0,40}[:：]\s*\n+", "", txt)        # 去掉「好的,這是您需要的整理:」這類開場白
    log(f"  Gemini 回 {len(txt)} 字,finishReason={fr}")
    listen.model = model
    return txt, fr

def title_match(title, txt):
    """標題裡的關鍵詞(去日期/節目名/標點後,長度 ≥2 的中文詞或英文字)至少有一個出現在整理裡;標題抽不出詞就放行"""
    t = re.sub(r"\d{4}/\d{1,2}/\d{1,2}\([一二三四五六日]\)|【.*?】|早晨財經速解讀|股癌|EP\.?\s*\d+", " ", title or "")
    toks = set()
    for w in re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}", t):
        for i in range(0, max(1, len(w) - 1)):
            if re.match(r"[\u4e00-\u9fff]", w): toks.add(w[i:i + 2])
            else: toks.add(w.lower()); break
    stop = {"了嗎", "嗎年", "是否", "什麼", "怎麼", "還是", "真正", "卻警", "警告", "剛開", "開始", "行情", "啟動", "今天", "這樣", "可以", "還有"}
    toks = {x for x in toks if x not in stop}
    if not toks: return True
    body = (txt or "").lower()
    hit = [x for x in toks if x in body]
    return len(hit) >= max(1, min(2, len(toks) // 6))


def main():
    show = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SHOW") or "yth").strip()
    C = SHOWS.get(show)
    if not C: log(f"✗ 不認識的節目 {show}"); sys.exit(1)
    if not KEY: log("✗ 未設定 GEMINI_KEY Secret"); sys.exit(1)
    ep = newest_episode(C)
    if not ep: log("⚠ 查無集數"); sys.exit(1)
    title = ep.get("trackName", "")
    log(f"{C['name']} 最新集:{title}")
    old = {}
    try:
        with open(C["out"], encoding="utf-8") as f: old = json.load(f)
    except Exception: pass
    eps = [x for x in (old.get("eps") or []) if x.get("t") and x.get("s")]
    if os.environ.get("FORCE") != "1" and any(x["t"] == title and len(x["s"]) >= 500 for x in eps):
        log("同一集已整理過,結束(零成本)。"); return
    # r1127:10/20 那集 YouTube 剛上架、影片還在處理,Gemini 讀不到內容卻憑標題編了一篇(拜登會見以色列顧問……2023 年的事)。
    #       改成:① 先用 podcast 的 mp3(真正的音檔位元組,上傳 Gemini Files)聽;YouTube 只當備援與連結
    #            ② 提示詞要求讀不到就回 NO_AUDIO ③ 整理內容必須跟標題對得上(標題關鍵詞至少命中一個),否則丟掉、下一班再試
    yt = youtube_url(C, title)
    link = yt or ep.get("trackViewUrl") or ""
    mp3 = ep.get("episodeUrl") or ""
    srcs = []
    if mp3:
        uri, mime = gemini_upload_audio(mp3, f"{show}_ep")
        if uri: srcs.append(((uri, mime), "音檔直讀(podcast mp3)"))
        else: log("  路線C上傳失敗,改試 YouTube")
    if yt: srcs.append((yt, f"YouTube {yt}"))
    if not srcs:
        log("⚠ 既沒有音檔直鏈也找不到 YouTube,下次排程再試。"); return
    def _ok(txt):
        if not txt or len(txt) < 500 or "NO_AUDIO" in txt[:40]: return False
        return title_match(title, txt)
    s = fr = None
    for src, how in srcs:
        log(f"{how},開始聆聽(30~40 分鐘節目約需 1~3 分鐘)…")
        s, fr = listen(C, src, title)
        if "NO_AUDIO" in (s or "")[:40]: log("  模型回 NO_AUDIO(讀不到內容),換下一個來源"); s = ""; continue
        if (not s or len(s) < 500 or (fr and fr != "STOP")):
            # 太短或被中途截斷(例如引用歌詞觸發 RECITATION)→ 換個說法再聽一次
            log(f"  整理太短或中斷({len(s or '')} 字,{fr}),重試一次…")
            s2, fr2 = listen(C, src, title, retry=True)
            if len(s2 or "") > len(s or ""): s, fr = s2, fr2
        if s and not title_match(title, s):
            log(f"  ✗ 整理內容跟標題對不上(標題關鍵詞一個都沒出現),視為讀錯來源,丟掉:{s[:60]!r}"); s = ""; continue
        if _ok(s): break
    if not s: log("✗ 沒有可用的整理,下次排程再試"); return
    eps = [x for x in eps if x.get("t") != title]
    rec = {"t": title, "dt": ep.get("releaseDate", ""), "yt": link, "s": s, "m": getattr(listen, "model", None), "u": time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 8 * 3600))}
    eps = [rec] + eps
    eps = eps[:C["keep"]]
    out = {"v": 1, "show": show, "name": C["name"], "t": title, "dt": rec["dt"], "yt": link, "s": s, "eps": eps}
    with open(C["out"], "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False)
    # 永久歸檔(每月一檔,只增不減)
    try:
        os.makedirs(C["hist_dir"], exist_ok=True)
        ym = (rec["dt"] or rec["u"])[:7]
        hp = os.path.join(C["hist_dir"], f"{ym}.json")
        H = []
        try:
            with open(hp, encoding="utf-8") as f: H = json.load(f) or []
        except Exception: pass
        H = [x for x in H if x.get("t") != title] + [rec]
        if True:
            with open(hp, "w", encoding="utf-8") as f: json.dump(H, f, ensure_ascii=False)
            log(f"  歸檔:{hp}({len(H)} 集)")
    except Exception as e:
        log(f"  歸檔失敗(不影響):{e}")
    log(f"完成:{C['out']}({len(s)} 字,最近 {len(eps)} 集)")

if __name__ == "__main__":
    main()
