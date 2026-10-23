#!/usr/bin/env python3
"""r1115:🔭 未來產業趨勢 → trends.json(+ trends/YYYY-MM-DD.json 永久)
把最近 14 天「產業早報」整理出來的重點(news/*.json,每則都有真實新聞來源)交給 Gemini 歸納成 4~6 個「正在成形、看 1~3 年」的產業趨勢:
趨勢名稱、為什麼(引用早報哪幾則)、階段、受惠供應鏈環節、相關台股/美股(代號只留站內清單有的)、最大風險。
每天跟著早報跑一次(news.yml);趨勢用 key 跨天對齊,算得出「連續幾天出現、第一次出現」。AI 歸納屬敘述、非驗證。"""
import json, os, re, sys, time, datetime as dt
from trends_history import read_archive, trend_stats, publish, rebuild, archive_value

TZ = dt.timezone(dt.timedelta(hours=8)); NOW = dt.datetime.now(TZ); TODAY = NOW.strftime("%Y-%m-%d")
KEY = os.environ.get("GEMINI_KEY", "").strip(); FORCE = os.environ.get("FORCE", "") == "1"
OUT = "trends.json"; DIR = "trends"; NEWS_DIR = "news"; DAYS = 14; N_MIN, N_MAX = 4, 6

def log(*a): print(*a, flush=True)

SCHEMA = {"type": "OBJECT", "properties": {
    "trends": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "key": {"type": "STRING"}, "name": {"type": "STRING"},
        "stage": {"type": "STRING", "enum": ["萌芽", "成形", "主流", "過熱"]},
        "horizon": {"type": "STRING"}, "thesis": {"type": "STRING"},
        "chain": {"type": "ARRAY", "items": {"type": "STRING"}},
        "tw": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"code": {"type": "STRING"}, "name": {"type": "STRING"}, "why": {"type": "STRING"}}, "required": ["code", "why"]}},
        "us": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"code": {"type": "STRING"}, "why": {"type": "STRING"}}, "required": ["code", "why"]}},
        "risk": {"type": "STRING"},
        "refs": {"type": "ARRAY", "items": {"type": "INTEGER"}}},
        "required": ["key", "name", "stage", "horizon", "thesis", "chain", "tw", "us", "risk", "refs"]}}},
    "required": ["trends"]}


def load_news():
    """最近 14 天的早報重點 → 編號清單(給 AI)+ 原始項目(建來源用)"""
    items = []
    if not os.path.isdir(NEWS_DIR): return items
    fns = sorted([f for f in os.listdir(NEWS_DIR) if re.match(r"\d{4}-\d{2}-\d{2}\.json$", f)], reverse=True)[:DAYS]
    for fn in sorted(fns):
        try: j = json.load(open(f"{NEWS_DIR}/{fn}", encoding="utf-8"))
        except Exception: continue
        for it in j.get("items") or []:
            items.append({"d": j.get("date") or fn[:10], "cat": it.get("cat"), "title": it.get("title"), "what": it.get("what"), "why": it.get("why"),
                          "groups": it.get("groups") or [], "codes": [c.get("id") for c in (it.get("codes") or []) if c.get("id")], "src": (it.get("src") or [])[:2], "lv": it.get("lv")})
    return items


def stocks():
    try: d = json.load(open("data.json", encoding="utf-8"))
    except Exception: return {}
    return {s["id"]: s for s in d.get("stocks", []) if s.get("id")}


def pick_flags():
    """站內已驗證的名單:三清單(短/中/長)持有、主力 20 檔持有 → 標在相關個股上"""
    F = {}
    try:
        A = json.load(open("aip3.json", encoding="utf-8"))
        for k, lab in (("short", "短期清單"), ("mid", "中期清單"), ("long", "長期清單")):
            for p in ((A.get("tw") or {}).get(k) or {}).get("slots") or []:
                if p.get("st") in ("hold", "pend"): F.setdefault(p["id"], []).append(lab)
            for p in ((A.get("us") or {}).get(k) or {}).get("slots") or []:
                if p.get("st") in ("hold", "pend"): F.setdefault(p.get("cur") or p["id"], []).append("美股" + lab)
    except Exception: pass
    try:
        P = json.load(open("aipick.json", encoding="utf-8"))
        for p in (((P.get("trader") or {}).get("pv") or {}).get("pos") or []): F.setdefault(p["id"], []).append("主力 20 檔")
    except Exception: pass
    return F


def prompt(items, prev_keys):
    lines = "\n".join(f"[{i}] {x['d'][5:]} [{x['cat']}] {x['title']}:{x['what']}" + (f"(族群:{'、'.join(x['groups'][:4])})" if x['groups'] else "") for i, x in enumerate(items))
    prev = ("上一次歸納的趨勢 key:" + "、".join(prev_keys) + "。同一個趨勢請沿用同一個 key,才能跨天對齊;真的不一樣才用新 key。\n") if prev_keys else ""
    return f"""你是台灣的產業研究員。下面是最近 {DAYS} 天「產業早報」整理出來的重點(每則都有真實新聞來源,方括號是編號)。
請從這些重點歸納出 {N_MIN}~{N_MAX} 個「正在成形、看 1~3 年」的產業趨勢——不是今天的漲跌,而是會持續改變需求、供應鏈或資金流向的方向。
{prev}
每個趨勢:
- key:英文小寫 slug(例如 ai-power、memory-upcycle、sovereign-ai),之後每天沿用
- name:10 字內的中文名稱
- stage:萌芽 / 成形 / 主流 / 過熱(依新聞密度與市場反應判斷)
- horizon:看多久(例如「1~2 年」)
- thesis:為什麼是趨勢,2~3 句,要引用清單裡的事件(用月/日),不准加清單沒有的數字或事件
- chain:受惠的供應鏈環節 3~6 個(例如 CoWoS、HBM、液冷、變壓器、BBU)
- tw:相關台股 3~6 檔,寫 4 位數代號與名稱,why 一句話講它在這條鏈的位置;只寫你很確定代號的
- us:相關美股 2~5 檔,寫代碼(例如 NVDA),why 一句話
- risk:最大風險一句話
- refs:依據的重點編號(至少 2 個)

規則:全部繁體中文(台灣用語)、白話;不要寫買進/賣出建議;不要驚嘆號;趨勢之間不要重複同一條鏈;同一檔台股最多出現在兩個趨勢(台積電、鴻海這種什麼都沾的少用,優先寫那條鏈上「最直接」的公司)。

早報重點清單:
{lines}"""


def gemini(p):
    import requests  # r1154:純歷史重建不需要網路套件
    if not KEY: log("  ✗ 沒有 GEMINI_KEY"); return None
    gc = {"maxOutputTokens": 8192, "temperature": 0.3, "responseMimeType": "application/json", "responseSchema": SCHEMA, "thinkingConfig": {"thinkingBudget": 0}}
    body = {"contents": [{"role": "user", "parts": [{"text": p}]}], "generationConfig": gc}
    for attempt, mdl in enumerate(["gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-2.5-flash"]):
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={KEY}", json=body, timeout=180)
            if r.status_code in (429, 500, 503, 404):
                log(f"  gemini {mdl} {r.status_code},換模型"); time.sleep(8 if attempt < 4 else 40); continue
            if not r.ok: log(f"  gemini {mdl} 錯誤 {r.status_code}:{r.text[:300]}"); continue
            cand = (r.json().get("candidates") or [{}])[0]
            txt = "".join(x.get("text", "") for x in ((cand.get("content") or {}).get("parts") or []) if not x.get("thought"))
            try:
                j = json.loads(txt); j["_model"] = mdl; return j
            except Exception:
                log(f"  {mdl} JSON 解析失敗(finish={cand.get('finishReason')}):{txt[:200]}")
        except Exception as e:
            log(f"  gemini 例外:{e}"); time.sleep(10)
    return None


def build(items, ai, prev):
    S = stocks(); F = pick_flags()
    # r1154:永久日檔/有效版本是統計來源,不再截斷 400 天。
    hist, _, _ = read_archive(DIR, prev)
    hist = [h for h in hist if h["d"] != TODAY]
    def stk(c, why, us=False):
        c = (c or "").strip().upper(); s = S.get(c)
        if not s or (s.get("market") == "US") != us: return None
        kv = (s.get("f") or {}).get("kv") or {}; tk = (s.get("t") or {}).get("kv") or {}
        return {"id": c, "n": s.get("name"), "why": (why or "").strip()[:80], "sector": s.get("sector"), "px": s.get("price"), "chg": s.get("chg"),
                "yoy": kv.get("月營收YoY"), "ma": tk.get("20/60MA"), "flags": F.get(c, [])}
    out = []
    for t in ai.get("trends") or []:
        refs = [r for r in dict.fromkeys(t.get("refs") or []) if type(r) is int and 0 <= r < len(items)]
        if len(refs) < 2: log(f"  丟掉(沒有依據):{t.get('name')}"); continue
        key = re.sub(r"[^a-z0-9-]", "", str(t.get("key") or "").lower()) or re.sub(r"\W", "", str(t.get("name") or ""))[:20]
        tw = [x for x in (stk(a.get("code"), a.get("why")) for a in (t.get("tw") or [])) if x][:6]
        us = [x for x in (stk(a.get("code"), a.get("why"), True) for a in (t.get("us") or [])) if x][:5]
        dropped = [a.get("code") for a in (t.get("tw") or []) + (t.get("us") or []) if a.get("code") and not any(x["id"] == str(a.get("code")).strip().upper() for x in tw + us)]
        if dropped: log(f"  {t.get('name')}:站內沒有的代號略過 {dropped}")
        src = []
        for r in refs:
            x = items[r]; src.append({"d": x["d"], "t": x["title"], "cat": x["cat"], "l": (x["src"][0].get("l") if x["src"] else ""), "s": (x["src"][0].get("s") if x["src"] else "")})
        out.append({"key": key, "name": (t.get("name") or "").strip(), "stage": t.get("stage") or "成形", "horizon": (t.get("horizon") or "").strip(),
                    "thesis": (t.get("thesis") or "").strip(), "chain": [c.strip() for c in (t.get("chain") or []) if c and c.strip()][:6],
                    "tw": tw, "us": us, "risk": (t.get("risk") or "").strip(), "src": src, "days": 1, "first": TODAY})
    hist.append({"d": TODAY, "keys": [t["key"] for t in out]})
    hist = sorted(hist, key=lambda h: h["d"])
    for t in out:
        stats = trend_stats(hist, t["key"], TODAY)
        t.update(stats); t["days"] = stats["current_streak_days"]; t["first"] = stats["first_seen"]
    return {"v": 1, "date": TODAY, "gen": NOW.strftime("%Y-%m-%dT%H:%M:%S+08:00"), "model": ai.get("_model", ""), "n_in": len(items), "days_in": DAYS,
            "trends": out, "hist": hist}


def main():
    os.makedirs(DIR, exist_ok=True)
    # r1154:修復 latest 不需重新花 AI 額度;當日首版檔案即使 FORCE 也不覆寫。
    if "--rebuild-history" in sys.argv:
        T = rebuild(DIR, OUT); log(f"已重建 {T['history_days']} 天趨勢索引"); return
    day_file = f"{DIR}/{TODAY}.json"
    if os.path.exists(day_file) and not FORCE:
        T = rebuild(DIR, OUT); log(f"今天({TODAY})已有首版,已從永久日檔同步索引"); return
    items = load_news()
    if len(items) < 20: log(f"✗ 早報重點太少({len(items)} 則),等累積幾天再歸納"); return
    try: prev = json.load(open(OUT, encoding="utf-8"))
    except Exception: prev = {}
    history, _, _ = read_archive(DIR, prev)
    prev_keys = sorted({key for h in history for key in (h.get("keys") or [])})
    ai = gemini(prompt(items, prev_keys))
    if not ai: log("✗ AI 歸納失敗,下一班再試"); return
    archive_value(DIR, TODAY, {"date": TODAY, "gen": NOW.isoformat(), "ai": ai, "input": items}, "raw")
    T = build(items, ai, prev)
    if len(T["trends"]) < 3: log(f"✗ 有效趨勢只有 {len(T['trends'])} 個,不發布"); return
    T = publish(T, DIR, OUT, raw={"date": TODAY, "gen": NOW.isoformat(), "ai": ai, "input": items})
    log(f"✓ {TODAY} 趨勢 {len(T['trends'])} 個(模型 {T['model']},輸入 {len(items)} 則早報重點)")
    for t in T["trends"]: log(f"   {t['name']}[{t['stage']}・連續 {t['days']} 天] 台股 {[x['n'] for x in t['tw']]} 美股 {[x['id'] for x in t['us']]}")


if __name__ == "__main__":
    main()
