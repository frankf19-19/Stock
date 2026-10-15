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
MODEL = "gemini-2.5-flash"
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
        for m in re.finditer(r"<entry>(.*?)</entry>", xml, re.S):
            blk = m.group(1)
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

def listen(C, src, title):
    """同股癌的整理格式(前端「本集提到的個股與產業」卡片靠這個格式解析),內容描述改成這個節目的性質"""
    body = {"contents": [{"role": "user", "parts": [
        ({"file_data": {"file_uri": src[0], "mime_type": src[1]}} if isinstance(src, tuple) else {"file_data": {"file_uri": src}}),
        {"text": f"""請完整聽完這一集{C['kind']}:「{title}」,用繁體中文寫一份「聽完可以不用再聽」等級的詳細整理,總長 800~1500 字,直接開始不要開場白。

格式要求:
## 依節目順序,每個主題一個段落
每段:**主題小標** + 他實際講了什麼(3~5 句,務必包含他引用的數據、數字、公司名、比喻與他的解讀)+ 他的結論或立場是什麼。不要只寫一句話標題,要寫出內容本身。

## 市場/總經觀點
他對大盤、利率/通膨、資金環境、產業循環的判斷,以及**他給的理由**(不是只寫結論);有講到今天台股開盤要注意什麼就寫出來。

## 提及的個股與族群(有講才寫,沒講就整段省略)
每檔一個項目,格式固定:* **股名(代號)**:偏多/偏空/中性。他怎麼說的(原話意思)+他的邏輯。
產業/族群也要各列一項(例如 **記憶體族群**、**散熱族群**、**金融股**),同樣標偏多/偏空/中性。
只是舉例帶過、沒有表態的標「中性(舉例)」;不確定代號就只寫股名,不要猜。

## 值得追蹤的後續(有才寫)
例如他點名的數據公布、財報、事件與他預期的影響。

規則:純閒聊可以一句帶過;會員/贊助/業配段落完全跳過;他沒講的不要腦補;聽不清楚的段落註明。最後一行固定:AI 聆聽全集整理,觀點屬節目主持人,非投資建議。"""}]}],
        "generationConfig": {"maxOutputTokens": 8192}}
    r = None
    for att in range(1, 4):
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}", json=body, timeout=1500)
            if r.ok: break
            if r.status_code in (429, 500, 502, 503):
                log(f"  第{att}次 Gemini {r.status_code},60秒後重試…"); time.sleep(60); continue
            log(f"✗ Gemini {r.status_code}: {r.text[:300]}"); sys.exit(1)
        except requests.exceptions.Timeout:
            log(f"  第{att}次讀取逾時(1500s),重試…")
        except Exception as e:
            log(f"  第{att}次連線異常:{e},60秒後重試…"); time.sleep(60)
    if r is None or not r.ok:
        log("✗ Gemini 連續失敗,下次排程再試。"); sys.exit(1)
    parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts).strip()

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
    if any(x["t"] == title for x in eps):
        log("同一集已整理過,結束(零成本)。"); return
    yt = youtube_url(C, title)
    src = yt; link = yt
    if not yt:
        mp3 = ep.get("episodeUrl") or ""
        if not mp3:
            log("⚠ YouTube 未找到且 RSS 無音檔直鏈,下次排程再試。"); return
        uri, mime = gemini_upload_audio(mp3, f"{show}_ep")
        if not uri:
            log("✗ 路線C上傳失敗,下次排程再試。"); return
        src = (uri, mime); link = ep.get("trackViewUrl") or mp3
        log("以音檔直讀模式聆聽…")
    else:
        log(f"YouTube:{yt},開始聆聽(30~40 分鐘節目約需 1~3 分鐘)…")
    s = listen(C, src, title)
    if not s: log("✗ 空回應"); sys.exit(1)
    rec = {"t": title, "dt": ep.get("releaseDate", ""), "yt": link, "s": s, "u": time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 8 * 3600))}
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
        if not any(x.get("t") == title for x in H):
            H.append(rec)
            with open(hp, "w", encoding="utf-8") as f: json.dump(H, f, ensure_ascii=False)
            log(f"  歸檔:{hp}({len(H)} 集)")
    except Exception as e:
        log(f"  歸檔失敗(不影響):{e}")
    log(f"完成:{C['out']}({len(s)} 字,最近 {len(eps)} 集)")

if __name__ == "__main__":
    main()
