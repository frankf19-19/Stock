"""股癌最新集自動聆聽整理 → gooaye.json
流程:iTunes 查最新集 → 同集已整理過就直接結束(零成本)→ 找 YouTube 版
      → Gemini 聽完全集 → 寫入 gooaye.json 供前端秒開。
需要 Secret:GEMINI_KEY(免費 Gemini 金鑰)。排程:每 4 小時(gooaye.yml)。"""
import json, os, re, sys
import requests

GA_ID = "1500839292"
KEY   = os.environ.get("GEMINI_KEY", "").strip()
MODEL = "gemini-2.5-flash"
OUT   = "gooaye.json"
UA    = {"User-Agent": "Mozilla/5.0 (gooaye-digest; personal dashboard)"}

def log(*a): print(*a, flush=True)

def newest_episode():
    j = requests.get(f"https://itunes.apple.com/lookup?id={GA_ID}&entity=podcastEpisode&limit=5&country=tw",
                     headers=UA, timeout=20).json()
    eps = [x for x in j.get("results", []) if x.get("kind") == "podcast-episode"]
    eps.sort(key=lambda x: x.get("releaseDate", ""), reverse=True)
    return eps[0] if eps else None

def yt_title(url):
    """oEmbed 驗證影片標題(免金鑰)"""
    try:
        j = requests.get("https://www.youtube.com/oembed",
                         params={"url": url, "format": "json"}, headers=UA, timeout=15).json()
        return j.get("title", "")
    except Exception:
        return ""

def youtube_url(ep_no):
    # 路線 A:頻道頁 → 頻道ID → RSS(加 CONSENT cookie 繞同意頁)
    cid = None
    for pu in ["https://www.youtube.com/@Gooaye/videos", "https://www.youtube.com/@Gooaye"]:
        try:
            page = requests.get(pu, headers=UA, timeout=20,
                                cookies={"CONSENT": "YES+cb", "SOCS": "CAI"}).text
            cid = (re.search(r'"channelId":"(UC[\w-]{22})"', page) or
                   re.search(r'channel_id=(UC[\w-]{22})', page) or [None, None])[1]
            if cid: break
        except Exception as e:
            log(f"  頻道頁 {pu} 失敗:{e}")
    if cid:
        try:
            xml = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
                               headers=UA, timeout=20).text
            for m in re.finditer(r"<entry>(.*?)</entry>", xml, re.S):
                blk = m.group(1)
                t = (re.search(r"<title>(.*?)</title>", blk) or [None, ""])[1]
                if re.search(rf"EP\s?{ep_no}\b", t, re.I):
                    u = (re.search(r'href="(https://www\.youtube\.com/watch\?v=[\w-]+)"', blk) or [None, None])[1]
                    if u:
                        log(f"  路線A(頻道RSS)找到:{u}")
                        return u
        except Exception as e:
            log(f"  頻道 RSS 失敗:{e}")
    else:
        log("  路線A:抓不到頻道 ID(機房可能被 YouTube 擋)")
    # 路線 B:請 Gemini 上網搜尋影片網址,再用 oEmbed 驗證標題含集數
    try:
        body = {"contents": [{"role": "user", "parts": [{"text":
            f"搜尋台股 Podcast「股癌 Gooaye」EP{ep_no} 在 YouTube 官方頻道(@Gooaye)的完整影片。"
            f"只回覆一行影片網址(https://www.youtube.com/watch?v=開頭),不要任何其他文字。"}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"maxOutputTokens": 100}}
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}",
            json=body, timeout=60)
        txt = "".join(p.get("text", "") for p in
              ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
        u = (re.search(r"https://www\.youtube\.com/watch\?v=[\w-]{6,}", txt) or [None])[0]
        if u:
            t = yt_title(u)
            if re.search(rf"EP\s?{ep_no}\b", t, re.I):
                log(f"  路線B(Gemini搜尋)找到並驗證:{u}({t[:40]})")
                return u
            log(f"  路線B找到 {u} 但標題不符({t[:40]}),棄用")
    except Exception as e:
        log(f"  路線B失敗:{e}")
    return None

def listen(yt, title):
    body = {"contents": [{"role": "user", "parts": [
        {"file_data": {"file_uri": yt}},
        {"text": f"""請完整聽完這一集台股 Podcast「股癌」({title}),用繁體中文寫一份「聽完可以不用再聽」等級的詳細整理,總長 800~1500 字,直接開始不要開場白。

格式要求:
## 依節目順序,每個主題一個段落
每段:**主題小標** + 他實際講了什麼(3~5 句,務必包含他舉的具體例子、數字、公司名、比喻)+ 他的結論或立場是什麼。不要只寫一句話標題,要寫出內容本身。

## 市場/總經觀點
他對大盤、產業循環、資金環境的判斷,以及**他給的理由**(不是只寫結論)。

## 提及的個股與族群(有講才寫,沒講就整段省略)
每檔:股名+代號、他怎麼說的(原話意思)、偏多/偏空/中性、他的邏輯。

## 值得追蹤的後續(有才寫)

規則:純閒聊哏可以一句帶過;業配段落完全跳過;他沒講的不要腦補;聽不清楚的段落註明。最後一行固定:AI 聆聽全集整理,觀點屬節目主持人,非投資建議。"""}]}],
        "generationConfig": {"maxOutputTokens": 8192}}
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}",
        json=body, timeout=600)
    if not r.ok:
        log(f"✗ Gemini {r.status_code}: {r.text[:300]}"); sys.exit(1)
    parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts).strip()

def main():
    if not KEY:
        log("✗ 未設定 GEMINI_KEY Secret"); sys.exit(1)
    ep = newest_episode()
    if not ep:
        log("⚠ iTunes 查無集數"); sys.exit(1)
    title = ep.get("trackName", "")
    log(f"最新集:{title}")
    old = {}
    try:
        with open(OUT, encoding="utf-8") as f: old = json.load(f)
    except Exception: pass
    if old.get("t") == title and old.get("s") and old.get("v") == 3:
        log("同一集已整理過(v3),結束(零成本)。"); return
    ep_no = (re.search(r"EP\s?(\d+)", title, re.I) or [None, None])[1]
    if not ep_no:
        log("⚠ 標題無集數編號,跳過"); return
    yt = youtube_url(ep_no)
    if not yt:
        log("⚠ YouTube 版尚未上架,下次排程再試。"); return
    log(f"YouTube:{yt},開始聆聽(50 分鐘節目約需 1~3 分鐘)…")
    s = listen(yt, title)
    if not s:
        log("✗ 空回應"); sys.exit(1)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"v": 3, "t": title, "ep": ep_no, "dt": ep.get("releaseDate", ""),
                   "yt": yt, "s": s}, f, ensure_ascii=False)
    log(f"完成:gooaye.json({len(s)} 字)")

if __name__ == "__main__":
    main()
