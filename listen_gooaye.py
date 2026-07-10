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

def youtube_url(ep_no):
    page = requests.get("https://www.youtube.com/@Gooaye", headers=UA, timeout=20).text
    cid = (re.search(r'"channelId":"(UC[\w-]{22})"', page) or [None, None])[1]
    if not cid:
        log("⚠ 抓不到頻道 ID"); return None
    xml = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
                       headers=UA, timeout=20).text
    for m in re.finditer(r"<entry>(.*?)</entry>", xml, re.S):
        blk = m.group(1)
        t = (re.search(r"<title>(.*?)</title>", blk) or [None, ""])[1]
        if re.search(rf"EP\s?{ep_no}\b", t, re.I):
            u = (re.search(r'href="(https://www\.youtube\.com/watch\?v=[\w-]+)"', blk) or [None, None])[1]
            return u
    return None

def listen(yt, title):
    body = {"contents": [{"role": "user", "parts": [
        {"file_data": {"file_uri": yt}},
        {"text": f"""請完整聽完這一集台股 Podcast「股癌」({title}),用繁體中文整理,直接條列不要開場白:
1) 本集主題大綱(依節目順序)
2) 對市場/總經的核心觀點與理由
3) 提及的台股/美股族群與個股(股名+代號),各自的多空看法
4) 值得追蹤的後續
請忽略開頭與中間的業配廣告段落。最後一行固定:AI 聆聽全集整理,觀點屬節目主持人,非投資建議。"""}]}],
        "generationConfig": {"maxOutputTokens": 1600}}
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
    if old.get("t") == title and old.get("s"):
        log("同一集已整理過,結束(零成本)。"); return
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
        json.dump({"t": title, "ep": ep_no, "dt": ep.get("releaseDate", ""),
                   "yt": yt, "s": s}, f, ensure_ascii=False)
    log(f"完成:gooaye.json({len(s)} 字)")

if __name__ == "__main__":
    main()
