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

  三級・最愛與追蹤(r776,Telegram 沒有上限所以可以推;同檔同種一天一次)
     ⭐ 最愛:回檔到均線帶 / 突破 20 日高 / 跌破 10 日低 / 跌破均線帶 / 停利到價 / 停損到價
     🤖 AI Pick:進入追價區 / 今日到期結算
     最愛名單與持股成本在你的帳號(Supabase)裡,後端用 service key 讀你那一列;沒設就只推一、二級。

環境變數:
  TG_TOKEN / TG_CHAT_ID       Telegram bot token 與 chat id(必要)
  LINE_TOKEN / LINE_USER_ID   選配;都設了才會同時推 LINE
  SB_SERVICE_KEY / SB_UID     選配;讀最愛名單與持股成本(三級訊號需要)
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
SB_URL = "https://vvfvtrmpkvatfhlzwpou.supabase.co"
SB_SERVICE = os.environ.get("SB_SERVICE_KEY", "").strip()
VAPID_PRIVATE = os.environ.get("VAPID_PRIVATE_KEY", "").strip()      # r784:Web Push(pywebpush)
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:frankccc199@hotmail.com").strip()
SB_UID = os.environ.get("SB_UID", "").strip()
FAV_TP, FAV_SL = 15.0, 7.0            # 最愛停利/停損預設(與前端一致;前端的自設值只在瀏覽器,後端讀不到)


# ═══ r782:多使用者 Telegram ═══
# 每個帳號在 user_data.data 裡:tgLink={code,t}(瀏覽器寫,綁定碼)/ tgChat=chat_id(後端寫)。
# 後端每輪讀 bot 的 getUpdates:看到 /start <碼> 就把 chat_id 寫進對應帳號;看到 tgLink.unbind 就清掉。
# 推播時對每個有 tgChat 的帳號各自算一份(最愛/持股不同),各自去重。
def sb_headers():
    return {"apikey": SB_SERVICE, "Authorization": f"Bearer {SB_SERVICE}", "Content-Type": "application/json"}

def all_users():
    """[{uid, data}] 全部帳號列(service key 繞過 RLS)。"""
    if not SB_SERVICE: return []
    try:
        r = requests.get(f"{SB_URL}/rest/v1/user_data", params={"select": "uid,data"}, headers=sb_headers(), timeout=15)
        return r.json() if r.ok and isinstance(r.json(), list) else []
    except Exception as e:
        log(f"  讀全部帳號失敗:{e}"); return []

def sb_patch_data(uid, data):
    try:
        r = requests.patch(f"{SB_URL}/rest/v1/user_data", params={"uid": f"eq.{uid}"}, headers={**sb_headers(), "Prefer": "return=minimal"},
                           json={"data": data, "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}, timeout=15)
        return r.ok
    except Exception:
        return False

def parse_ud(row):
    d = (row or {}).get("data") or {}
    out = {}
    for k in ("fav_ids", "port1", "tgLink", "pushSubs"):
        try: out[k] = json.loads(d.get(k)) if isinstance(d.get(k), str) else d.get(k)
        except Exception: out[k] = None
    out["tgChat"] = d.get("tgChat")
    return out

def tg_bind_sweep(st, users):
    """處理綁定/解綁:getUpdates 找 /start <碼>;tgLink.unbind 清 tgChat。回傳更新後的 users。"""
    if not TG_TOKEN: return users
    # 1) bot 名稱寫進狀態檔給前端讀(一次)
    if not st.get("bot"):
        try:
            r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getMe", timeout=15)
            if r.ok: st["bot"] = (r.json().get("result") or {}).get("username") or ""
        except Exception: pass
    # 2) 解綁
    for u in users:
        d = parse_ud(u)
        if isinstance(d.get("tgLink"), dict) and d["tgLink"].get("unbind") and d.get("tgChat"):
            nd = dict(u.get("data") or {}); nd.pop("tgChat", None); nd["tgLink"] = None
            if sb_patch_data(u["uid"], nd): u["data"] = nd; log(f"  Telegram 解除綁定:{u['uid'][:8]}…")
    # 3) 綁定:掃最近的 /start <碼>
    codes = {}
    for u in users:
        d = parse_ud(u)
        l = d.get("tgLink")
        if isinstance(l, dict) and l.get("code") and not d.get("tgChat"): codes[str(l["code"]).upper()] = u
    try:
        r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates", params={"offset": int(st.get("tg_offset") or 0), "timeout": 0}, timeout=20)
        ups = (r.json().get("result") or []) if r.ok else []
    except Exception:
        ups = []
    for up in ups:
        st["tg_offset"] = max(int(st.get("tg_offset") or 0), int(up.get("update_id", 0)) + 1)
        msg = up.get("message") or {}
        txt = (msg.get("text") or "").strip()
        chat = (msg.get("chat") or {}).get("id")
        if not chat or not txt.startswith("/start"): continue
        code = txt.split(maxsplit=1)[1].strip().upper() if " " in txt else ""
        u = codes.get(code)
        if not u:
            send_tg_to(chat, "這個綁定碼對不上任何帳號,或已過期。請回到網站帳號面板重新按「連結 Telegram」。"); continue
        nd = dict(u.get("data") or {}); nd["tgChat"] = str(chat); nd["tgLink"] = None
        if sb_patch_data(u["uid"], nd):
            u["data"] = nd; codes.pop(code, None)
            send_tg_to(chat, "✅ 已綁定 K研所。AI Pick 成交/出場/換股/到價、你的最愛與持股訊號、主力進出,之後都會推到這裡。")
            log(f"  Telegram 綁定完成:{u['uid'][:8]}… ↔ chat …{str(chat)[-4:]}")
    return users

def send_push_to(subs, title, body, url=SITE + "#aipick"):
    """r784:Web Push。subs = [{endpoint, keys:{p256dh,auth}}, ...];回傳 (成功數, 失效的 endpoint 清單)。"""
    if not VAPID_PRIVATE or not subs: return 0, []
    try:
        from pywebpush import webpush, WebPushException
    except Exception:
        log("  pywebpush 未安裝,跳過 Web Push"); return 0, []
    payload = json.dumps({"title": title, "body": body[:900], "url": url, "tag": "kyansuo-" + TODAY}, ensure_ascii=False)
    ok, dead = 0, []
    for sb in subs:
        if not isinstance(sb, dict) or not sb.get("endpoint") or not sb.get("keys"): continue
        try:
            webpush(subscription_info={"endpoint": sb["endpoint"], "keys": sb["keys"]}, data=payload,
                    vapid_private_key=VAPID_PRIVATE, vapid_claims={"sub": VAPID_SUBJECT}, ttl=6 * 3600, timeout=15)
            ok += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410): dead.append(sb["endpoint"])              # 訂閱已失效(使用者關掉/瀏覽器重裝)
            else: log(f"  Push 失敗 {code}: {str(e)[:100]}")
        except Exception as e:
            log(f"  Push 例外:{str(e)[:100]}")
    return ok, dead


def send_tg_to(chat, text):
    if not TG_TOKEN or not chat: return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=20)
        if not r.ok: log(f"  Telegram(…{str(chat)[-4:]})失敗 {r.status_code}: {r.text[:100]}")
        return r.ok
    except Exception as e:
        log(f"  Telegram 例外:{e}"); return False


def user_data():
    """讀你的帳號同步資料(fav_ids / port1)。service key 只放在 GitHub secret,不進前端。"""
    if not (SB_SERVICE and SB_UID): return {}
    try:
        r = requests.get(f"{SB_URL}/rest/v1/user_data", params={"uid": f"eq.{SB_UID}", "select": "data"},
                         headers={"apikey": SB_SERVICE, "Authorization": f"Bearer {SB_SERVICE}"}, timeout=15)
        rows = r.json() if r.ok else []
        d = (rows[0].get("data") if rows else None) or {}
        out = {}
        for k in ("fav_ids", "port1"):
            try: out[k] = json.loads(d.get(k) or "null")
            except Exception: out[k] = None
        return out
    except Exception as e:
        log(f"  讀帳號資料失敗:{e}"); return {}


def shard_key(sid):
    t = str(sid); return t[:3] if t[:2] == "00" else t[:2]

_SH = {}
def bars(sid):
    k = shard_key(sid)
    if k not in _SH:
        try: _SH[k] = json.load(open(f"k/tw{k}.json", encoding="utf-8"))
        except Exception: _SH[k] = {}
    e = _SH[k].get(sid) or {}
    d, o = e.get("d") or [], e.get("o") or []
    n = min(len(d), len(o)); return d[:n], o[:n]


def fav_levels(sid, px):
    """鏡射前端 turtleCalc:不含今日的前 20 日最高、前 10 日最低、昨收。"""
    d, o = bars(sid)
    if len(o) < 40: return None
    n = len(o)
    today_in = d[-1] == TODAY
    end = n - 1 if today_in else n                       # 「不含今日」
    h20 = max(o[i][1] for i in range(max(0, end - 20), end))
    l10 = min(o[i][2] for i in range(max(0, end - 10), end))
    prev = o[end - 1][3] if end - 1 >= 0 else None
    return {"h20": h20, "l10": l10, "prevC": prev}


_CH = {}
def chips_of(sid):
    k = shard_key(sid)
    if k not in _CH:
        try: _CH[k] = json.load(open(f"c/tw{k}.json", encoding="utf-8"))
        except Exception: _CH[k] = {}
    return _CH[k].get(sid)


def lead_signal(sid, nm):
    """r779:主力進出——鏡射前端 drvAnalyze + leadSignals。
    主導法人 = 0.6·|當日相關| + 0.4·|隔日相關| 最高者;第一名是自營商就取第二名。
    大買門檻 = 該法人在本檔近一年買超日前 20%;大賣門檻 = 賣超日前 20%。只看最新一個法人資料日。"""
    e = chips_of(sid)
    if not e or not isinstance(e.get("d"), list) or not isinstance(e.get("f"), list): return []
    d, o = bars(sid)
    if len(d) < 41: return []
    kmap = {x: i for i, x in enumerate(d)}
    F, T, G, R, R1 = [], [], [], [], []
    for i, dd in enumerate(e["d"]):
        j = kmap.get(dd)
        if j is None or j == 0 or len(o[j]) < 4 or len(o[j - 1]) < 4: continue
        c0, c1 = o[j - 1][3], o[j][3]
        if not (c0 and c1): continue
        R.append((c1 / c0 - 1) * 100)
        R1.append((o[j + 1][3] / c1 - 1) * 100 if j + 1 < len(o) and len(o[j + 1]) >= 4 and o[j + 1][3] else None)
        F.append(float((e["f"] or [0])[i] or 0)); T.append(float((e.get("t") or [0])[i] or 0)); G.append(float((e.get("g") or [0])[i] or 0))
    n = len(R)
    if n < 40: return []
    def corr(xs, ys):
        v = [(x, y) for x, y in zip(xs, ys) if y is not None]
        m = len(v)
        if m < 20: return 0.0
        mx = sum(a for a, _ in v) / m; my = sum(b for _, b in v) / m
        sx = (sum((a - mx) ** 2 for a, _ in v) / m) ** 0.5; sy = (sum((b - my) ** 2 for _, b in v) / m) ** 0.5
        if not sx or not sy: return 0.0
        return sum((a - mx) * (b - my) for a, b in v) / (m * sx * sy)
    def stat(X):
        c0, c1 = corr(X, R), corr(X, R1)
        cut = max(3, round(n * 0.2))
        idx = sorted(range(n), key=lambda i: -X[i])[:cut]
        same = [R[i] for i in idx]; buy_same = sum(same) / len(same) if same else None
        win = round(100 * sum(1 for x in same if x > 0) / len(same)) if same else None
        sidx = sorted(range(n), key=lambda i: X[i])[:cut]; ss = [R[i] for i in sidx]; sell_same = sum(ss) / len(ss) if ss else None
        pos = sorted(x for x in X if x > 0); neg = sorted(-x for x in X if x < 0)
        q = lambda a, p: a[min(len(a) - 1, round((len(a) - 1) * p))] if a else None
        s3 = []
        for i in range(2, n - 5):
            if X[i] > 0 and X[i - 1] > 0 and X[i - 2] > 0:
                s3.append(sum(R[i + j] for j in range(1, 6)))
        return {"score": abs(c0) * 0.6 + abs(c1) * 0.4, "buy_same": buy_same, "win": win, "sell_same": sell_same,
                "p80": round(q(pos, .8)) if len(pos) >= 10 else None, "s80": round(q(neg, .8)) if len(neg) >= 10 else None,
                "streak": (sum(s3) / len(s3)) if len(s3) >= 3 else None, "streak_n": len(s3)}
    rank = sorted([("外資", "f", stat(F)), ("投信", "t", stat(T)), ("自營商", "g", stat(G))], key=lambda x: -x[2]["score"])
    L = rank[1] if rank[0][0] == "自營商" and len(rank) > 1 else rank[0]
    nmL, key, st = L
    X = [float(x or 0) for x in (e.get(key) or [])]
    if len(X) < 3 or st["p80"] is None: return []
    dlast = e["d"][-1]; v, v1, v2 = X[-1], X[-2], X[-3]
    tag = nmL + ("(自營跟價,取第二名)" if rank[0][0] == "自營商" else "")
    fp = lambda x: ("—" if x is None else f"{x:+.2f}%")
    out = []
    if v >= st["p80"]:
        out.append((f"lead_b|{dlast}|{sid}", 3, f"🎯 <b>主力大買 {nm}</b>({sid})・{nmL}\n{dlast[5:].replace('-','/')} {nmL}買超 {int(v):,} 張,達本檔大買門檻 {st['p80']:,} 張(前 20%);歷史大買日當天平均 {fp(st['buy_same'])}、勝率 {st['win'] if st['win'] is not None else '—'}%——主導法人:{tag}"))
    elif v > 0 and v1 > 0 and v2 > 0 and v1 < st["p80"] and v2 < st["p80"]:
        out.append((f"lead_s3|{dlast}|{sid}", 3, f"🎯 <b>主力開始連買 {nm}</b>({sid})・{nmL}\n{nmL}已連 3 日買超({int(v2)}/{int(v1)}/{int(v)} 張);本檔連買 3 日後 5 日平均 {fp(st['streak'])}(樣本 {st['streak_n']})——主導法人:{tag}"))
    if st["s80"] is not None and v <= -st["s80"]:
        out.append((f"lead_x|{dlast}|{sid}", 3, f"🎯 <b>主力大賣 {nm}</b>({sid})・{nmL}\n{dlast[5:].replace('-','/')} {nmL}賣超 {int(-v):,} 張,達本檔大賣門檻 {st['s80']:,} 張(前 20%);歷史大賣日當天平均 {fp(st['sell_same'])}——主導法人:{tag}"))
    return out


def collect_fav_events(data, aip, prices, ud):
    """三級:最愛的六種訊號 + 持股停利/停損。鏡射前端 favSignals 的門檻。"""
    ev = []
    favs = [str(x) for x in (ud.get("fav_ids") or [])]
    port = {str(p.get("id")): p for p in (ud.get("port1") or []) if p.get("id")}
    if not favs: return ev
    by = {s["id"]: s for s in data.get("stocks") or []}
    picks = {}
    for w in aip.get("weeks") or []:
        if w.get("bt") or w.get("status") == "done": continue
        for p in w.get("picks") or []: picks[p["id"]] = (w, p)
    for sid in favs:
        s = by.get(sid)
        if not s or s.get("market") != "TW" or s.get("etf"): continue
        px = prices.get(sid)
        if not px: continue
        nm = s.get("name") or sid
        try: ev.extend(lead_signal(sid, nm))                     # r779:主力進出(法人日資料)
        except Exception: pass
        a = s.get("al") or {}
        lv = fav_levels(sid, px) or {}
        h20, l10, prev = lv.get("h20"), lv.get("l10"), lv.get("prevC")
        bull, z0, z1, stop = bool(a.get("bull")), a.get("z0"), a.get("z1"), a.get("stop")
        if bull and z0 and z1 and z0 * 0.995 <= px <= z1 * 1.005 and (not stop or px >= stop):
            ev.append((f"fz|{TODAY}|{sid}", 3, f"⭐🟢 <b>{nm}</b>({sid})回檔到均線帶\n現價 {px} 進入 {z0}~{z1}(多頭排列未破停損 {stop});左側分批參考"))
        if h20 and px >= h20 * 1.003 and (prev is None or prev <= h20):
            ev.append((f"fh|{TODAY}|{sid}", 3, f"⭐🟢 <b>{nm}</b>({sid})突破 20 日高\n現價 {px} 站上 {h20};守 {l10 or h20} 為出場線"))
        if l10 and px < l10 and (prev is None or prev >= l10 * 0.999):
            ev.append((f"fl|{TODAY}|{sid}", 3, f"⭐🔻 <b>{nm}</b>({sid})跌破 10 日低\n現價 {px} 跌破 {l10}(出場線);順勢部位宜減碼或出場"))
        elif bull and z0 and px < z0 * 0.995 and (prev is None or prev >= z0 * 0.995):
            ev.append((f"fb|{TODAY}|{sid}", 3, f"⭐🔻 <b>{nm}</b>({sid})跌破均線帶\n現價 {px} 跌破下緣 {z0};多頭結構鬆動,守停損 {stop}"))
        # 停利/停損:進場價 = 持股成本 > AI Pick 成交價
        entry, src = None, None
        pc = port.get(sid)
        if pc and float(pc.get("cost") or 0) > 0: entry, src = float(pc["cost"]), "持股成本"
        elif sid in picks:
            legs = picks[sid][1].get("legs") or []
            if legs and legs[-1].get("entry") and not legs[-1].get("xd"): entry, src = float(legs[-1]["entry"]), "AI Pick 成交"
        if entry:
            tp, sl = round(entry * (1 + FAV_TP / 100), 2), round(entry * (1 - FAV_SL / 100), 2)
            g = (px / entry - 1) * 100
            if px >= tp: ev.append((f"ftp|{TODAY}|{sid}", 3, f"⭐🎯 <b>{nm}</b>({sid})停利到價\n現價 {px} ≥ {tp}(進場 {entry}・{src} +{FAV_TP:.0f}%);獲利 {g:+.1f}%,可分批停利"))
            if px <= sl: ev.append((f"fsl|{TODAY}|{sid}", 3, f"⭐🛑 <b>{nm}</b>({sid})停損到價\n現價 {px} ≤ {sl}(進場 {entry}・{src} −{FAV_SL:.0f}%);虧損 {g:+.1f}%,依紀律執行"))
    return ev


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
            ew_end = (dt.date.fromisoformat(w["eval_week"]) + dt.timedelta(days=4)).isoformat() if w.get("eval_week") else ""
            if not cur:
                if bw <= today <= bw_end and px <= p["buy"]:
                    ev.append((f"buy|{today}|{sid}", 2, f"🟢 <b>到買價・可買進 {nm}</b>({sid})\n現價 {px} ≤ 建議買價 {p['buy']}・目標 {p['target']}・停損 {p['stop']}"))
                elif bw <= today <= bw_end and p.get("buy_hi") and px <= p["buy_hi"]:          # r776:追價區
                    ev.append((f"chase|{today}|{sid}", 3, f"🟡 <b>進入追價區 {nm}</b>({sid})\n現價 {px} 在追價上限 {p['buy_hi']} 內(建議買價 {p['buy']});可分批,守停損 {p['stop']}"))
            else:
                rt = pct(px, cur["entry"])
                if px >= cur["target"]:
                    ev.append((f"tp|{today}|{sid}", 2, f"🎯 <b>到目標・可賣出 {nm}</b>({sid})\n現價 {px} ≥ 目標 {cur['target']};{md(cur['fill'])} 買 {cur['entry']},帳面 {rt}"))
                elif px <= cur["stop"]:
                    ev.append((f"sl|{today}|{sid}", 2, f"🛑 <b>觸停損・宜賣出 {nm}</b>({sid})\n現價 {px} ≤ 停損 {cur['stop']};{md(cur['fill'])} 買 {cur['entry']},帳面 {rt}"))
                elif ew_end and today == ew_end:                                                  # r776:到期提醒
                    ev.append((f"exp|{today}|{sid}", 3, f"⏰ <b>今日到期結算 {nm}</b>({sid})\n評估週最後一個交易日,{md(cur['fill'])} 買 {cur['entry']} 的部位收盤賣出;現價 {px}({rt})"))
    # ── r785:60 分 K 型態——已突破 / 回測成功(對所有人相同,一天一次)──
    try:
        hs = load("hourly_scan.json", {})
        for x in hs.get("items") or []:
            if x.get("state") not in ("已突破", "回測成功"): continue
            ty = "+".join({"flat": "扁扁寬寬", "shadow": "長長尖尖"}[t] for t in x.get("type") or [])
            ev.append((f"hs|{today}|{x['id']}|{x['state']}", 2,
                       f"🧹 <b>{x['state']}・{ty} {x['name']}</b>({x['id']})\n整理 {x['bars']} 根小時 K、區間 {x['range_pct']}%({x['lo']}~{x['hi']})"
                       + (f",下影線 {x['shadow']['depth']}%" if x.get("shadow") else "")
                       + (f";突破 @{str(x.get('brk_at'))[5:16].replace('T',' ')}" if x.get("brk_at") else "") + f",現價 {x['last']}"))
    except Exception:
        pass
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
    if not TG_TOKEN and not VAPID_PRIVATE and not (LINE_TOKEN and LINE_USER):
        log("notify:未設 TG_TOKEN / VAPID_PRIVATE_KEY / LINE,跳過"); return
    aip = load("aipick.json", {})
    data = load("data.json", {})
    prices = {s["id"]: s.get("price") for s in data.get("stocks") or [] if s.get("price")}
    st = load(STATE, {"sent": {}, "daily": {}, "month": {}})
    sent = st.setdefault("sent", {}); daily = st.setdefault("daily", {}); month = st.setdefault("month", {})
    # r782 遷移:舊格式 sent 是平的 {鍵:日期},搬到 "secret" 收件人底下,升級後不會重推一輪
    flat = {k: v for k, v in sent.items() if isinstance(v, str)}
    if flat:
        sent.setdefault("secret", {}).update(flat)
        for k in flat: del sent[k]

    # ── r782:多使用者 ──
    users = all_users()
    users = tg_bind_sweep(st, users)
    # 收件人:每個綁定 Telegram 的帳號各一份;沒任何人綁定時退回 secret 裡的 TG_CHAT_ID(站長自己)+ 可選 LINE
    recips = []
    for u in users:
        d = parse_ud(u)
        subs = [x for x in (d.get("pushSubs") or []) if isinstance(x, dict) and x.get("endpoint")]
        if d.get("tgChat") or subs:
            recips.append({"chat": d.get("tgChat"), "subs": subs, "ud": d, "key": "u:" + u["uid"][:12], "uid": u["uid"], "row": u})
    if not recips:
        recips = [{"chat": TG_CHAT or None, "ud": user_data(), "key": "secret", "line": True}]
        if not (SB_SERVICE and SB_UID): log("  未設 SB_SERVICE_KEY/SB_UID,最愛訊號不推(一、二級照推)")
    base_ev = collect_events(aip, prices)                    # 一、二級對所有人相同,算一次
    pushed = 0
    for rc in recips:
        ev = base_ev + collect_fav_events(data, aip, prices, rc["ud"] or {})
        sent_u = sent.get(rc["key"])
        if not isinstance(sent_u, dict): sent_u = sent[rc["key"]] = {}
        new = [(k, lv, t) for k, lv, t in ev if k not in sent_u]
        if not new: continue
        dk = f"{TODAY}|{rc['key']}"
        if daily.get(dk, 0) >= NOTIFY_DAILY_MAX: log(f"  {rc['key']} 今日已達上限"); continue
        new.sort(key=lambda x: x[1])
        head = f"🤖 <b>K研所 AI Pick</b> {NOW.strftime('%m/%d %H:%M')}"
        text = f"{head}\n\n" + "\n\n".join(t for _, _, t in new) + f"\n\n{SITE}#aipick"
        ok_tg = send_tg_to(rc["chat"], text) if rc["chat"] else False
        ok_push = False
        if rc.get("subs"):
            plain = re.sub(r"</?b>", "", "\n\n".join(t for _, _, t in new))
            title = f"K研所 AI Pick・{len(new)} 則" if len(new) > 1 else "K研所 AI Pick"
            n_ok, dead = send_push_to(rc["subs"], title, plain)
            ok_push = n_ok > 0
            if dead:                                                    # 清掉失效訂閱,免得每輪都撞牆
                try:
                    nd = dict(rc["row"].get("data") or {})
                    keep = [x for x in rc["subs"] if x.get("endpoint") not in dead]
                    nd["pushSubs"] = json.dumps(keep, ensure_ascii=False)
                    sb_patch_data(rc["uid"], nd); log(f"  清掉 {len(dead)} 個失效推播訂閱")
                except Exception: pass
        ok_line = False
        if rc.get("line") and LINE_TOKEN and LINE_USER:
            if month.get(YM, 0) < LINE_MONTHLY_MAX: ok_line = send_line(text)
        if not (ok_tg or ok_line or ok_push): continue
        for k, _, _ in new: sent_u[k] = TODAY
        daily[dk] = daily.get(dk, 0) + 1
        if ok_line: month[YM] = month.get(YM, 0) + 1
        pushed += 1
        log(f"  → {rc['key']}:{len(new)} 筆事件 Telegram={'✓' if ok_tg else '—'} Push={'✓' if ok_push else '—'}")
    # 清理:已推過的鍵只留 60 天、每日計數只留 30 天
    cutoff = (NOW.date() - dt.timedelta(days=60)).isoformat()
    for rk, sm in list(sent.items()):
        if not isinstance(sm, dict): del sent[rk]; continue
        for k in [k for k, d in sm.items() if isinstance(d, str) and d < cutoff]: del sm[k]
    for d in [d for d in daily if d < (NOW.date() - dt.timedelta(days=30)).isoformat()]: del daily[d]
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, separators=(",", ":"))
    log(f"notify:推給 {pushed}/{len(recips)} 位收件人;bot={st.get('bot') or '—'}")


if __name__ == "__main__":
    main()
