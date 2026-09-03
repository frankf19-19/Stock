"""重要訊息推播 → Telegram(選配 LINE Messaging API)
======================================================
放在盤中輕量迴圈(update_quotes.yml)每 5 分鐘一輪的最後,以及 update_data 重班之後。
瀏覽器裡的到價提醒只在你開著網站時有用;這支從後端發,沒在看也會收到。

推什麼(只推重要的,合併成一則):
  一級・事實(來自 aipick.json 的結算紀錄,只推一次)
     🟢 已買進 / 🔄 換股買進 / 🎯 到目標賣出 / 🛑 觸停損賣出 / ⏰ 到期賣出
  二級・該行動(來自即時報價,同檔同種一天一次)
     🟢 到買價可買進 / 🎯 到目標可賣出 / 🛑 觸停損宜賣出
  不推:追價區、到期提醒、最愛的 26 種到價訊號(量太大,留在網站)

去重:notify_state.json 記「已推過的事件鍵」與每日/每月計數。事件鍵含週次、倉位、段落、代號,
      所以同一筆成交永遠只推一次;二級訊號的鍵含日期,一天一次。
上限:每日 NOTIFY_DAILY_MAX 則(Telegram 免費無上限,但沒人想被轟炸);
      LINE 另有每月 LINE_MONTHLY_MAX(免費層 200 則),超過就只走 Telegram。

環境變數:
  TG_TOKEN / TG_CHAT_ID       Telegram bot token 與 chat id(必要)
  LINE_TOKEN / LINE_USER_ID   選配;都設了才會同時推 LINE
"""
import json, os, re, datetime as dt
import requests

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
TODAY = NOW.date().isoformat()
YM = NOW.strftime("%Y-%m")
STATE = "notify_state.json"
NOTIFY_DAILY_MAX = 10
LINE_MONTHLY_MAX = 180                 # 留 20 則緩衝
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
TG_CHAT = os.environ.get("TG_CHAT_ID", "").strip()
LINE_TOKEN = os.environ.get("LINE_TOKEN", "").strip()
LINE_USER = os.environ.get("LINE_USER_ID", "").strip()
SITE = "https://frankf19-19.github.io/Stock/"


def log(*a): print(*a, flush=True)


def load(p, d):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception:
        return d


def md(iso):
    m = re.match(r"\d{4}-(\d{2})-(\d{2})", str(iso or ""))
    return f"{int(m.group(1))}/{int(m.group(2))}" if m else str(iso or "")


def pct(a, b):
    try: return f"{(a / b - 1) * 100:+.1f}%"
    except Exception: return ""


def collect_events(aip, prices):
    """回傳 [(key, level, text), ...]。level 1=事實,2=該行動。"""
    ev = []
    today = TODAY
    recent = (NOW.date() - dt.timedelta(days=21)).isoformat()     # 首次啟用只回顧最近三週,不倒陳年紀錄
    for w in aip.get("weeks") or []:
        if w.get("bt") or (w.get("buy_week") or "") < recent: continue
        bw = w.get("buy_week", ""); bw_end = (dt.date.fromisoformat(bw) + dt.timedelta(days=4)).isoformat() if bw else ""
        for si, p in enumerate(w.get("picks") or []):
            legs = p.get("legs") or []
            # ── 一級:成交 / 出場(後端已結算的事實)──
            for li, L in enumerate(legs):
                if L.get("fill") and L.get("entry"):
                    k = f"fill|{bw}|{si}|{li}|{L['id']}"
                    if li == 0:
                        ev.append((k, 1, f"🟢 <b>已買進 {L['name']}</b>({L['id']})\n"
                                         f"{md(L['fill'])} 以 {L['entry']} 成交・目標 {L['target']}({pct(L['target'], L['entry'])})・停損 {L['stop']}({pct(L['stop'], L['entry'])})"))
                    else:
                        prev = legs[li - 1]
                        ev.append((k, 1, f"🔄 <b>換股買進 {L['name']}</b>({L['id']})第 {li + 1} 段,接替 {prev.get('name')}\n"
                                         f"{md(L['fill'])} 以 {L['entry']} 成交・目標 {L['target']}・停損 {L['stop']}"))
                if L.get("xd"):
                    k = f"exit|{bw}|{si}|{li}|{L['id']}"
                    why = {"tp": "🎯 到目標賣出", "sl": "🛑 觸停損賣出", "exp": "⏰ 到期賣出"}.get(L.get("xw"), "賣出")
                    r = L.get("ret")
                    ev.append((k, 1, f"{why} <b>{L['name']}</b>({L['id']})\n"
                                     f"{md(L['fill'])} 買 {L['entry']} → {md(L['xd'])} 賣 {L['xp']},持有 {L.get('hold') or '—'} 天,實現 <b>{r:+.2f}%</b>" if isinstance(r, (int, float)) else
                                     f"{why} <b>{L['name']}</b>({L['id']}) {md(L['fill'])} 買 {L['entry']} → {md(L['xd'])} 賣 {L['xp']}"))
            # ── 二級:即時報價觸發(該行動)──
            cur = legs[-1] if legs else None
            if cur and cur.get("xd"): continue                 # 這個倉位已收工
            sid = cur["id"] if cur else p["id"]; nm = cur["name"] if cur else p["name"]
            px = prices.get(sid)
            if not px: continue
            if not cur:
                if bw <= today <= bw_end and px <= p["buy"]:
                    ev.append((f"buy|{today}|{sid}", 2, f"🟢 <b>到買價・可買進 {nm}</b>({sid})\n現價 {px} ≤ 建議買價 {p['buy']}・目標 {p['target']}・停損 {p['stop']}"))
            else:
                rt = pct(px, cur["entry"])
                if px >= cur["target"]:
                    ev.append((f"tp|{today}|{sid}", 2, f"🎯 <b>到目標・可賣出 {nm}</b>({sid})\n現價 {px} ≥ 目標 {cur['target']};{md(cur['fill'])} 買 {cur['entry']},帳面 {rt}"))
                elif px <= cur["stop"]:
                    ev.append((f"sl|{today}|{sid}", 2, f"🛑 <b>觸停損・宜賣出 {nm}</b>({sid})\n現價 {px} ≤ 停損 {cur['stop']};{md(cur['fill'])} 買 {cur['entry']},帳面 {rt}"))
    return ev


def send_tg(text):
    if not (TG_TOKEN and TG_CHAT): return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                          timeout=20)
        if not r.ok: log(f"  Telegram 失敗 {r.status_code}: {r.text[:120]}")
        return r.ok
    except Exception as e:
        log(f"  Telegram 例外:{e}"); return False


def send_line(text):
    if not (LINE_TOKEN and LINE_USER): return False
    try:
        plain = re.sub(r"</?b>", "", text)
        r = requests.post("https://api.line.me/v2/bot/message/push",
                          headers={"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"},
                          json={"to": LINE_USER, "messages": [{"type": "text", "text": plain[:4900]}]}, timeout=20)
        if not r.ok: log(f"  LINE 失敗 {r.status_code}: {r.text[:120]}")
        return r.ok
    except Exception as e:
        log(f"  LINE 例外:{e}"); return False


def main():
    if not (TG_TOKEN and TG_CHAT) and not (LINE_TOKEN and LINE_USER):
        log("notify:未設 TG_TOKEN/TG_CHAT_ID(或 LINE_TOKEN/LINE_USER_ID),跳過"); return
    aip = load("aipick.json", {})
    data = load("data.json", {})
    prices = {s["id"]: s.get("price") for s in data.get("stocks") or [] if s.get("price")}
    st = load(STATE, {"sent": {}, "daily": {}, "month": {}})
    sent = st.setdefault("sent", {}); daily = st.setdefault("daily", {}); month = st.setdefault("month", {})

    ev = collect_events(aip, prices)
    new = [(k, lv, t) for k, lv, t in ev if k not in sent]
    if not new:
        log(f"notify:事件 {len(ev)} 筆,沒有新的,不推"); return
    if daily.get(TODAY, 0) >= NOTIFY_DAILY_MAX:
        log(f"notify:今日已達上限 {NOTIFY_DAILY_MAX} 則,{len(new)} 筆新事件延後"); return

    new.sort(key=lambda x: x[1])                             # 事實在前、該行動在後
    head = f"🤖 <b>K研所 AI Pick</b> {NOW.strftime('%m/%d %H:%M')}"
    body = "\n\n".join(t for _, _, t in new)
    text = f"{head}\n\n{body}\n\n{SITE}#aipick"

    ok_tg = send_tg(text)
    ok_line = False
    if LINE_TOKEN and LINE_USER:
        if month.get(YM, 0) < LINE_MONTHLY_MAX: ok_line = send_line(text)
        else: log(f"  LINE 本月已達 {LINE_MONTHLY_MAX} 則,只走 Telegram")
    if not (ok_tg or ok_line):
        log("notify:兩個管道都失敗,事件保留下次再推"); return

    for k, _, _ in new: sent[k] = TODAY
    daily[TODAY] = daily.get(TODAY, 0) + 1
    if ok_line: month[YM] = month.get(YM, 0) + 1
    # 清理:已推過的鍵只留 60 天、每日計數只留 30 天
    cutoff = (NOW.date() - dt.timedelta(days=60)).isoformat()
    for k in [k for k, d in sent.items() if d < cutoff]: del sent[k]
    for d in [d for d in daily if d < (NOW.date() - dt.timedelta(days=30)).isoformat()]: del daily[d]
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, separators=(",", ":"))
    log(f"notify:推了 1 則(含 {len(new)} 筆事件)Telegram={'✓' if ok_tg else '✗'} LINE={'✓' if ok_line else '—'};今日 {daily[TODAY]}/{NOTIFY_DAILY_MAX}")


if __name__ == "__main__":
    main()
