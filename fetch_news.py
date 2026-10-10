"""📰 每日產業早報 → news.json(最新一份 + 歷史索引)+ news/YYYY-MM-DD.json(每天一份,永久保存)
流程:Google 新聞 RSS(中英文、過去約一天)收集標題
      → Gemini 從「真的有的標題」挑 6~10 則最重要的,寫「發生什麼事/為什麼重要/影響族群」
      → 每則都要附對應的新聞編號;編號對不到真實標題的直接丟掉(不准編造)
      → 個股代號只留站上真的有的。
需要 Secret:GEMINI_KEY。排程:news.yml(台北每天 06:35 / 07:35 兩班,當天已產生就跳過)。"""
import json, os, re, sys, time, html as H
import datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import requests

KEY = os.environ.get("GEMINI_KEY", "").strip()
FORCE = os.environ.get("FORCE", "").strip() in ("1", "true", "yes")
UA = {"User-Agent": "Mozilla/5.0 (K-research daily brief; personal dashboard)"}
TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
TODAY = NOW.strftime("%Y-%m-%d")
OUT = "news.json"
DIR = "news"
HOURS = 30          # 收過去幾小時的新聞(週一早上放寬到 64 小時,涵蓋週末)

def log(*a): print(*a, flush=True)

# (查詢字, 語言) —— 中文看台股/產業,英文看美股/外電
Q_ZH = [
    "台股 外資 盤勢", "台積電 OR CoWoS OR 先進封裝", "AI伺服器 鴻海 OR 廣達 OR 緯創 OR 緯穎",
    "記憶體 HBM OR DRAM OR NAND 報價", "美股 費半 輝達", "聯準會 利率 OR 通膨 OR 非農",
    "關稅 OR 出口管制 半導體", "法說會 OR 營收 創新高 台股", "新台幣 匯率 OR 美債殖利率",
    "PCB OR 散熱 OR 光通訊 OR 矽光子 台股", "機器人 OR 電動車 OR 儲能 供應鏈", "產業 漲價 缺貨 台股",
]
Q_EN = [
    "stock market today Nasdaq S&P 500", "Nvidia OR AMD OR Broadcom shares", "TSMC OR semiconductor stocks",
    "Fed rate inflation Treasury yields", "export controls chips tariffs", "AI data center capex hyperscaler",
    "Apple OR Microsoft OR Meta OR Alphabet OR Amazon OR Tesla earnings", "oil prices OPEC dollar",
]

def rss(q, lang):
    if lang == "zh":
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(q + ' when:2d')}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    else:
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(q + ' when:2d')}&hl=en-US&gl=US&ceid=US:en"
    out = []
    for attempt in range(3):
        try:
            root = ET.fromstring(requests.get(url, headers=UA, timeout=20).content)
            for it in root.iter("item"):
                title = H.unescape(it.findtext("title") or "").strip()
                src = (it.find("source").text if it.find("source") is not None else "") or ""
                if src and title.endswith(" - " + src): title = title[: -len(src) - 3]
                elif " - " in title and not src: title, src = title.rsplit(" - ", 1)
                try: pub = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(TZ)
                except Exception: pub = None
                out.append({"t": title.strip(), "s": src.strip(), "l": it.findtext("link") or "", "p": pub, "lang": lang})
            return out
        except Exception as e:
            log(f"  RSS 失敗({q}):{e}"); time.sleep(3)
    return out

def norm(t): return re.sub(r"[\W_]+", "", t.lower())[:40]

def collect():
    hrs = 64 if NOW.weekday() == 0 else HOURS
    cut = NOW - dt.timedelta(hours=hrs)
    seen, pool = set(), []
    for q in Q_ZH: pool += [dict(x, q=q) for x in rss(q, "zh")]; time.sleep(0.6)
    for q in Q_EN: pool += [dict(x, q=q) for x in rss(q, "en")]; time.sleep(0.6)
    items = []
    for x in sorted(pool, key=lambda x: x["p"] or NOW, reverse=True):
        if not x["t"] or (x["p"] and x["p"] < cut): continue
        k = norm(x["t"])
        if k in seen: continue
        seen.add(k); items.append(x)
    # 每個查詢最多 12 則,總數 ≤ 160(給 AI 的清單不要太長)
    per, kept = {}, []
    for x in items:
        if per.get(x["q"], 0) >= 12: continue
        per[x["q"]] = per.get(x["q"], 0) + 1; kept.append(x)
    kept = kept[:160]
    log(f"  收到 {len(pool)} 則 → 去重/限時後 {len(items)} → 交給 AI {len(kept)} 則(近 {hrs} 小時)")
    return kept

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "mood": {"type": "STRING"},
        "items": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "cat": {"type": "STRING", "enum": ["美股", "AI/半導體", "台股", "總經", "政策/地緣", "其他產業"]},
            "title": {"type": "STRING"}, "what": {"type": "STRING"}, "why": {"type": "STRING"},
            "groups": {"type": "ARRAY", "items": {"type": "STRING"}},
            "codes": {"type": "ARRAY", "items": {"type": "STRING"}},
            "refs": {"type": "ARRAY", "items": {"type": "INTEGER"}},
            "lv": {"type": "INTEGER"}},
            "required": ["cat", "title", "what", "why", "refs", "lv"]}},
        "watch": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "t": {"type": "STRING"}, "refs": {"type": "ARRAY", "items": {"type": "INTEGER"}}},
            "required": ["t", "refs"]}},
    },
    "required": ["mood", "items", "watch"],
}

def prompt(items):
    wd = "一二三四五六日"[NOW.weekday()]
    lines = "\n".join(f"[{i}] ({x['s'] or '?'}{' ' + x['p'].strftime('%m/%d %H:%M') if x['p'] else ''}) {x['t']}" for i, x in enumerate(items))
    return f"""你是台灣的產業研究員,要幫投資人寫今天({TODAY} 週{wd})早上的「產業早報」。
風格參考 Podcast《股癌》:重視產業趨勢與供應鏈邏輯,不是只報漲跌;要講清楚「為什麼重要、影響到誰(哪些台股族群)」。

下面是過去一天的新聞標題清單(中英文都有,方括號是編號)。規則:
1. 只能根據清單裡的標題寫,不准加清單沒有的數字或事件;數字一律照標題寫的。
2. 挑出最重要的 6~10 則(同一件事的多則標題合併成一則,refs 列出所有相關編號,至少 1 個)。
   優先順序:美股盤後與大型科技股 > AI/半導體供應鏈 > 台股重要個股/法說/營收 > 總經(利率、通膨、匯率、油價)> 政策/地緣 > 其他產業。
   不要選:個人理財、純股價漲跌榜、廣告、重複的盤中快訊。
3. 每則:title(15 字內標題)、what(發生什麼事,1~2 句)、why(為什麼重要、對哪些產業/台股族群有什麼影響,1~2 句,要有判斷)、
   groups(受影響的台股族群,例如 晶圓代工、CoWoS、AI伺服器、記憶體、PCB、散熱、光通訊、電源、網通、航運、金融)、
   codes(受影響的台股 4 位數代號或美股代碼,只寫你很確定的,最多 5 個)、lv(重要度 1~3,3 最重要)。
4. mood:一句話(30 字內)講今天市場氛圍。
5. watch:清單裡有提到的「今天/本週即將發生」的事件(財報、經濟數據、法說會、央行會議),每條附 refs;沒有就給空陣列。
6. 全部用繁體中文(台灣用語),白話、精簡;不要寫買進/賣出建議;不要用驚嘆號。

新聞清單:
{lines}"""

def gemini(p):
    if not KEY: log("  ✗ 沒有 GEMINI_KEY"); return None
    gc = {"maxOutputTokens": 8192, "temperature": 0.3, "responseMimeType": "application/json",
          "responseSchema": SCHEMA, "thinkingConfig": {"thinkingBudget": 2048}}
    body = {"contents": [{"role": "user", "parts": [{"text": p}]}], "generationConfig": gc}
    for attempt, mdl in enumerate(["gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-2.0-flash", "gemini-2.5-flash"]):
        try:
            if mdl.startswith("gemini-2.0"): gc.pop("thinkingConfig", None)
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={KEY}",
                              json=body, timeout=180)
            if r.status_code in (429, 500, 503, 404):
                log(f"  gemini {mdl} {r.status_code},換模型"); time.sleep(8 if attempt < 4 else 40); continue
            if not r.ok:
                log(f"  gemini {mdl} 錯誤 {r.status_code}:{r.text[:300]}"); continue
            cand = (r.json().get("candidates") or [{}])[0]
            txt = "".join(x.get("text", "") for x in ((cand.get("content") or {}).get("parts") or []) if not x.get("thought"))
            try:
                j = json.loads(txt); j["_model"] = mdl; return j
            except Exception:
                log(f"  {mdl} JSON 解析失敗(finish={cand.get('finishReason')}):{txt[:200]}")
        except Exception as e:
            log(f"  gemini 例外:{e}"); time.sleep(10)
    return None

def known_codes():
    try:
        d = json.load(open("data.json", encoding="utf-8"))
        return {s["id"]: s.get("name", "") for s in d.get("stocks", []) if s.get("id")}
    except Exception:
        return {}

def build(items, ai):
    codes = known_codes()
    def src(i):
        x = items[i]
        return {"t": x["t"][:120], "s": x["s"], "l": x["l"], "d": x["p"].strftime("%m/%d %H:%M") if x["p"] else "", "en": x["lang"] == "en"}
    out_items = []
    for it in ai.get("items") or []:
        refs = [r for r in dict.fromkeys(it.get("refs") or []) if isinstance(r, int) and 0 <= r < len(items)]
        if not refs:
            log(f"  丟掉(沒有真實來源):{it.get('title')}"); continue
        cs = [c.strip().upper() for c in (it.get("codes") or []) if isinstance(c, str)]
        cs = [c for c in dict.fromkeys(cs) if c in codes][:5]
        out_items.append({
            "cat": it.get("cat") or "其他產業", "title": (it.get("title") or "").strip(),
            "what": (it.get("what") or "").strip(), "why": (it.get("why") or "").strip(),
            "groups": [g.strip() for g in (it.get("groups") or []) if g and g.strip()][:6],
            "codes": [{"id": c, "n": codes[c]} for c in cs],
            "lv": max(1, min(3, int(it.get("lv") or 2))),
            "src": [src(r) for r in refs[:4]],
        })
    watch = []
    for w in ai.get("watch") or []:
        refs = [r for r in (w.get("refs") or []) if isinstance(r, int) and 0 <= r < len(items)]
        if refs and (w.get("t") or "").strip(): watch.append({"t": w["t"].strip(), "src": [src(r) for r in refs[:2]]})
    return {"v": 1, "date": TODAY, "gen": NOW.strftime("%Y-%m-%dT%H:%M:%S+08:00"), "model": ai.get("_model", ""),
            "mood": (ai.get("mood") or "").strip(), "n_in": len(items), "items": out_items, "watch": watch[:8]}

def main():
    os.makedirs(DIR, exist_ok=True)
    day_file = f"{DIR}/{TODAY}.json"
    if os.path.exists(day_file) and not FORCE:
        log(f"今天({TODAY})的早報已經產生過,跳過"); return
    items = collect()
    if len(items) < 15:
        log("✗ 新聞太少(RSS 可能暫時抓不到),這班不產生,等下一班"); sys.exit(0)
    ai = gemini(prompt(items))
    if not ai: log("✗ AI 整理失敗,等下一班"); sys.exit(0)
    brief = build(items, ai)
    if len(brief["items"]) < 4:
        log(f"✗ 有效重點只有 {len(brief['items'])} 則(低於 4),不發布"); sys.exit(0)
    json.dump(brief, open(day_file, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    # 歷史索引:掃整個資料夾重建(永久保存,只增不減)
    idx = []
    for fn in sorted(os.listdir(DIR), reverse=True):
        if not re.match(r"\d{4}-\d{2}-\d{2}\.json$", fn): continue
        try:
            j = json.load(open(f"{DIR}/{fn}", encoding="utf-8"))
            idx.append({"d": j["date"], "mood": j.get("mood", ""), "n": len(j.get("items", []))})
        except Exception: pass
    latest = dict(brief, dates=idx)
    json.dump(latest, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"✓ {TODAY} 早報:{len(brief['items'])} 則重點、{len(brief['watch'])} 項行事曆(模型 {brief['model']});歷史共 {len(idx)} 天")
    for x in brief["items"]: log(f"   [{x['cat']}] {x['title']} ← {x['src'][0]['s']}:{x['src'][0]['t'][:40]}")

if __name__ == "__main__":
    main()
