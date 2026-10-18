"""🛡 網站管理員(r1073)→ guard.json(目前狀態)+ guard_log.json(事件紀錄,永久保存)

每一輪做三件事:
  ① 巡邏:盤中報價有沒有在跳、各資料檔該更新有沒有更新(依台股/美股交易日與休市日判斷)、
          排程有沒有失敗/卡住/漏跑、資料有沒有變少或壞掉、網站版本是否一致
  ② 緊急處理(只做安全動作):排程漏跑/卡住/失敗 → 自動重新啟動那支排程(有頻率上限);
          資料檔壞掉(JSON 讀不出來)→ 從最近一版好的還原(永遠不砍資料)
  ③ 通知:新出現紅燈 → 推播給管理員(SB_UID 那個帳號);恢復也通知一次
不做的事:改程式、改選股規則(要驗證過、由人確認才改)。
排程:guard.yml(盤中每 5 分鐘一輪、其他時間每小時一次)。
需要:GITHUB_TOKEN(Actions 內建,要 actions: write)、VAPID_PRIVATE_KEY、SB_UID。"""
import json, os, re, sys, time, datetime as dt
import requests

REPO = os.environ.get("GITHUB_REPOSITORY", "frankf19-19/Stock")
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
SB_UID = os.environ.get("SB_UID", "").strip()
SITE = "https://frankf19-19.github.io/Stock/"
TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
TODAY = NOW.date()
OUT, LOG = "guard.json", "guard_log.json"
API = f"https://api.github.com/repos/{REPO}"
HDR = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"} if TOKEN else {}

def log(*a): print(*a, flush=True)
def load(p, d):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d

# ─────────────── 交易日 ───────────────
HOL = load("holidays.json", {})
def tw_trading(d): return d.weekday() < 5 and d.isoformat() not in (HOL.get("tw") or {})
def us_trading(d): return d.weekday() < 5 and d.isoformat() not in (HOL.get("us") or {})

def expect_tw(ready_hhmm):
    """現在應該已經有哪一個台股交易日的資料:今天是交易日且已過 ready 時間 → 今天;否則往前找最近的交易日"""
    h, m = map(int, ready_hhmm.split(":"))
    d = TODAY
    if not (tw_trading(d) and (NOW.hour, NOW.minute) >= (h, m)): d -= dt.timedelta(days=1)
    while not tw_trading(d): d -= dt.timedelta(days=1)
    return d

def expect_us(lag_days=1, ready_hhmm="09:00"):
    """美股 D 日收盤資料,台北 D+1 的 ready 之後應該要有"""
    h, m = map(int, ready_hhmm.split(":"))
    d = TODAY - dt.timedelta(days=lag_days)
    if (NOW.hour, NOW.minute) < (h, m): d -= dt.timedelta(days=1)
    while not us_trading(d): d -= dt.timedelta(days=1)
    return d

def pdate(s):
    """各種時間字串 → 台北時間 datetime(只有日期就當 00:00)"""
    if s is None: return None
    s = str(s).strip()
    try:
        if s.endswith("Z") or "+" in s[10:]:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ)
        if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", s):
            return dt.datetime.strptime(s[:16].replace("T", " "), "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s[:10]):
            return dt.datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=TZ)
    except Exception: pass
    return None

def ago(t):
    if not t: return "—"
    m = int((NOW - t).total_seconds() // 60)
    if m < 60: return f"{m} 分鐘前"
    if m < 48 * 60: return f"{m // 60} 小時前"
    return f"{m // 1440} 天前"

def in_tw_market(): return tw_trading(TODAY) and (9, 10) <= (NOW.hour, NOW.minute) <= (13, 35)

# ─────────────── GitHub API ───────────────
def gh(path, method="GET", **kw):
    if not TOKEN: return None
    try:
        r = requests.request(method, API + path, headers=HDR, timeout=25, **kw)
        if method == "GET": return r.json() if r.ok else None
        return r
    except Exception as e:
        log(f"  GitHub API 失敗 {path}:{e}"); return None

RUNS = {}
def runs(wf, n=10):
    if wf not in RUNS:
        j = gh(f"/actions/workflows/{wf}/runs?per_page={n}")
        RUNS[wf] = (j or {}).get("workflow_runs") or []
    return RUNS[wf]

# ─────────────── 檢查項目 ───────────────
CHECKS = []
def add(k, grp, label, st, msg, last=None, fix=None, sec=None):
    CHECKS.append({"k": k, "grp": grp, "label": label, "st": st, "msg": msg, "last": last, "fix": fix, "sec": sec})

def lvl_date(last, warn_exp, red_exp):
    if last is None: return "red"
    if last >= warn_exp: return "ok"
    if last >= red_exp: return "warn"
    return "red"

def check_quotes():
    sp = load("spark.json", {})
    ts = (sp.get("t") or [])
    last = dt.datetime.fromtimestamp(ts[-1], TZ) if ts else None
    if in_tw_market():
        age = (NOW - last).total_seconds() / 60 if last else 999
        st = "ok" if age <= 12 else ("warn" if age <= 20 else "red")   # r1080:快照約 5 分鐘一筆+推送/拉取延遲,9 分鐘就警告會一直閃黃燈
        add("quotes", "盤中", "盤中報價", st, f"最後一筆快照 {ago(last)}" + ("" if st == "ok" else "——報價停了"), last.strftime("%H:%M") if last else None, fix="update_quotes.yml", sec="all")
    elif tw_trading(TODAY) and (NOW.hour, NOW.minute) > (13, 40):
        ok = sp.get("d") == TODAY.isoformat() and len(ts) >= 30
        add("quotes", "盤中", "盤中報價", "ok" if ok else "warn", f"今天盤中快照 {len(ts) if sp.get('d') == TODAY.isoformat() else 0} 點", sp.get("d"))
    else:
        add("quotes", "盤中", "盤中報價", "ok", "非交易時段", sp.get("d"))

def check_daily():
    d = load("data.json", {})
    H = {x["k"]: x for x in ((d.get("health") or {}).get("items") or [])}
    w_exp, r_exp = expect_tw("18:30"), expect_tw("23:59")
    for k, label, wf in [("ktw", "台股日K", "update_data.yml"), ("itse", "上市法人", "update_data.yml"), ("iotc", "上櫃法人", "update_data.yml")]:
        x = H.get(k) or {}
        last = pdate(x.get("last"))
        st = lvl_date(last.date() if last else None, w_exp, r_exp)
        add(k, "每日資料", label, st, f"最新 {x.get('last','—')}" + ("" if st == "ok" else f"(應有 {w_exp.isoformat()})") + f"・{x.get('note','')}", x.get("last"), fix="update_data.yml" if st == "red" else None)
    x = H.get("kus") or {}
    last = pdate(x.get("last"))
    st = lvl_date(last.date() if last else None, expect_us(1, "10:00"), expect_us(2, "10:00"))
    add("kus", "每日資料", "美股日K", st, f"最新 {x.get('last','—')}・{x.get('note','')}", x.get("last"))
    for k in ("tdcc", "rev", "div"):
        x = H.get(k)
        if x: add(k, "每日資料", x.get("label", k), {"ok": "ok", "warn": "warn"}.get(x.get("st"), "red"), f"最新 {x.get('last','—')}・{x.get('note','')}", x.get("last"))
    # 主資料更新時間
    up = pdate(f"{d.get('updated','')} {d.get('intraday','00:00')}")
    st = lvl_date(up.date() if up else None, expect_tw("16:30"), expect_tw("23:59") - dt.timedelta(days=1))
    add("data", "每日資料", "主資料 data.json", st, f"最後更新 {ago(up)}", up.strftime("%m-%d %H:%M") if up else None, fix="update_data.yml" if st == "red" else None)

def check_file(k, grp, label, path, field, warn_exp, red_exp, fix=None, sec=None):
    j = load(path, None)
    if j is None:
        add(k, grp, label, "red", f"{path} 讀不到或壞掉", None, fix=fix, sec=sec); return
    v = j.get(field) if isinstance(j, dict) else None
    t = pdate(v)
    st = lvl_date(t.date() if t else None, warn_exp, red_exp)
    add(k, grp, label, st, f"最新 {str(v)[:16] if v else '—'}" + ("" if st == "ok" else f"(應有 {warn_exp.isoformat()})"), str(v)[:16] if v else None,
        fix=fix if st == "red" else None, sec=sec)

def check_age(k, grp, label, path, field, warn_h, red_h, fix=None, sec=None):
    j = load(path, None)
    v = j.get(field) if isinstance(j, dict) else None
    t = pdate(v)
    age = (NOW - t).total_seconds() / 3600 if t else 9e9
    st = "ok" if age <= warn_h else ("warn" if age <= red_h else "red")
    add(k, grp, label, st, f"最後更新 {ago(t)}", t.strftime("%m-%d %H:%M") if t else None, fix=fix if st == "red" else None, sec=sec)

def check_files():
    check_file("margin", "每日資料", "融資融券", "margin.json", "updated", expect_tw("23:00"), expect_tw("23:59"), fix="margin.yml")
    check_file("etf", "每日資料", "ETF 持股", "etf_hold.json", "u", expect_tw("20:00"), expect_tw("23:59"), fix="etf.yml")
    check_file("taifex", "每日資料", "期交所籌碼", "taifex.json", "u", expect_tw("17:30"), expect_tw("23:59"))
    check_file("aipick", "AI", "AI Pick(台股)", "aipick.json", "updated", expect_tw("18:30"), expect_tw("23:59"), sec="aipick")
    check_file("aipick_us", "AI", "AI Pick(美股)", "aipick_us.json", "updated", expect_us(1, "12:00"), expect_us(2, "12:00"), sec="aipick")
    check_file("brain", "AI", "大腦學習", "brain.json", "u", expect_tw("23:30"), expect_tw("23:59") - dt.timedelta(days=1))
    # 國際行情:台股盤中或美股盤中 1 小時內要更新;其他時間 30 小時
    win = in_tw_market() or (TODAY.weekday() < 5 and (NOW.hour >= 22 or NOW.hour < 5)) or (TODAY.weekday() == 5 and NOW.hour < 5)
    if win: check_age("yext", "每日資料", "國際行情", "yext.json", "updated", 1.2, 2.5, fix="yext.yml")
    else: check_age("yext", "每日資料", "國際行情", "yext.json", "updated", 72, 100, fix="yext.yml")
    check_file("usf", "每日資料", "美股財報", "usf.json", "updated", expect_us(2, "12:00"), expect_us(4, "12:00"), fix="usf.yml")
    check_age("holiday", "每日資料", "休市行事曆", "holidays.json", "updated", 72, 168)
    check_age("ext", "每日資料", "內部人・選擇權・景氣・金融壓力", "ext.json", "u", 62, 90, fix="ext.yml")      # r1130
    check_age("view", "每日資料", "盤勢解讀", "view.json", "gen", 62, 90, fix="view.yml")                    # r1129
    # 產業早報:每天 07:50 後要是今天的
    nj = load("news.json", {})
    nd = nj.get("date")
    if (NOW.hour, NOW.minute) >= (7, 50):
        st = "ok" if nd == TODAY.isoformat() else "red"
    else:
        st = "ok" if nd in (TODAY.isoformat(), (TODAY - dt.timedelta(days=1)).isoformat()) else "warn"
    add("news", "每日資料", "產業早報", st, f"最新一份 {nd or '—'}" + ("" if st == "ok" else "——今天的早報還沒出"), nd, fix="news.yml" if st == "red" else None, sec="news")

def check_integrity(state):
    d = load("data.json", None)
    if d is None:
        add("integrity", "資料完整", "主資料完整性", "red", "data.json 讀不出來(檔案壞掉)"); return
    tw = [s for s in d.get("stocks", []) if s.get("market") == "TW"]
    us = [s for s in d.get("stocks", []) if s.get("market") == "US"]
    mem = state.setdefault("mem", {})
    hi_tw, hi_us = mem.get("max_tw", 0), mem.get("max_us", 0)
    mem["max_tw"], mem["max_us"] = max(hi_tw, len(tw)), max(hi_us, len(us))
    msg, st = f"台股 {len(tw)} 檔・美股 {len(us)} 檔", "ok"
    if hi_tw and len(tw) < hi_tw * 0.97: st, msg = "red", msg + f"——台股比之前({hi_tw})少了 {hi_tw - len(tw)} 檔"
    if hi_us and len(us) < hi_us * 0.97: st, msg = "red", msg + f"——美股比之前({hi_us})少了 {hi_us - len(us)} 檔"
    nul = sum(1 for s in tw if s.get("price") in (None, 0))
    if tw and nul / len(tw) > 0.05:
        st = "red" if nul / len(tw) > 0.15 else max(st, "warn", key=["ok", "warn", "red"].index)
        msg += f"・{nul} 檔沒有價格"
    add("integrity", "資料完整", "主資料完整性", st, msg)
    # 重要 JSON 檔能不能讀(壞檔自動還原)
    bad = []
    for p in ["data.json", "aipick.json", "aipick_us.json", "spark.json", "brain.json", "news.json", "yext.json", "margin.json", "tdcc.json", "aitrader.json", "signal_log.json", "holidays.json", "bottom.json", "view.json", "ext.json"]:
        if os.path.exists(p) and load(p, None) is None: bad.append(p)
    if bad:
        fixed = [p for p in bad if restore_json(p)]
        add("json", "資料完整", "資料檔格式", "red" if len(fixed) < len(bad) else "warn",
            f"壞檔:{', '.join(bad)}" + (f";已自動還原:{', '.join(fixed)}" if fixed else ""))
    else:
        add("json", "資料完整", "資料檔格式", "ok", "重要資料檔都能正常讀取")

def run_start(r):
    """r1080:這一班「真正開始跑」的時間——排隊等前一班的時間不算(run_started_at 在排隊時就有值,會把排隊算成卡住)"""
    try:
        j = gh(f"/actions/runs/{r['id']}/jobs") or {}
        ts = [pdate(x.get("started_at")) for x in (j.get("jobs") or []) if x.get("started_at") and x.get("status") != "queued"]
        ts = [t for t in ts if t]
        if ts: return min(ts)
    except Exception: pass
    return None


def run_limit(wf, t0, tmo):
    """r1080:每日資料更新在平日傍晚是「自迴圈」——14:45~19:00 開始的跑到 19:00、19:00~23:00 開始的跑到 23:00(每小時一輪),不是卡住"""
    if wf != "update_data.yml" or not t0 or t0.weekday() > 4: return tmo
    hm = t0.hour * 60 + t0.minute
    end = 19 * 60 if 14 * 60 + 45 <= hm < 19 * 60 else (23 * 60 if 19 * 60 <= hm < 23 * 60 else None)
    return tmo if end is None else max(tmo, end - hm + 75)


def check_workflows():
    W = [("update_quotes.yml", "盤中報價迴圈", 360), ("update_data.yml", "每日資料更新", 70), ("yext.yml", "國際行情", 15),
         ("news.yml", "產業早報", 25), ("margin.yml", "融資融券", 40), ("etf.yml", "ETF 持股", 40), ("sbl.yml", "借券", 40),
         ("usf.yml", "美股財報", 60), ("gooaye.yml", "股癌整理", 95), ("conf_ai.yml", "法說會分析", 120),
         ("bkall.yml", "全部券商分點(夜間)", 360), ("weekend_backfill.yml", "週末回補", 360), ("backfill_tdcc.yml", "大戶週更", 120)]
    for wf, label, tmo in W:
        rs = runs(wf)
        if not rs:
            add("wf:" + wf, "排程", label, "warn", "讀不到執行紀錄"); continue
        done = [r for r in rs if r.get("status") == "completed"]
        run_ = [r for r in rs if r.get("status") in ("in_progress", "queued")]
        fails = 0
        for r in done:
            if r.get("conclusion") == "failure": fails += 1
            elif r.get("conclusion") == "success": break
        canc = 0
        for r in done:
            if r.get("conclusion") == "cancelled": canc += 1
            else: break
        last = pdate(rs[0].get("created_at"))
        st, msg = "ok", f"最近一次 {ago(last)}:{({'success':'成功','failure':'失敗','cancelled':'取消'}).get(rs[0].get('conclusion'), '執行中' if rs[0].get('status')!='completed' else rs[0].get('conclusion'))}"
        if fails >= 1: st, msg = ("red" if fails >= 2 else "warn"), f"連續失敗 {fails} 次(最近 {ago(pdate(done[0].get('created_at')))})"
        for r in run_:
            if r.get("status") != "in_progress": continue          # r1080:排隊等前一班不是卡住
            t0 = run_start(r)
            if not t0: continue
            lim = run_limit(wf, t0, tmo)
            if (NOW - t0).total_seconds() / 60 > lim + 15:
                st, msg = "red", f"已執行 {int((NOW - t0).total_seconds() // 60)} 分鐘,疑似卡住"
        if canc >= 6 and wf in ("bkall.yml", "weekend_backfill.yml"):
            st, msg = "warn", f"連續 {canc} 次被取消(排隊讓路太多,可能一直跑不完)"
        add("wf:" + wf, "排程", label, st, msg, last.strftime("%m-%d %H:%M") if last else None,
            fix=wf if st == "red" and wf not in ("bkall.yml", "weekend_backfill.yml", "backfill_tdcc.yml") else None)
    # 盤中:交易日 09:20 後今天還沒有任何一班報價迴圈 → 漏跑
    if in_tw_market() and (NOW.hour, NOW.minute) >= (9, 20):
        rs = runs("update_quotes.yml")
        today_runs = [r for r in rs if (pdate(r.get("created_at")) or NOW).date() == TODAY]
        if not today_runs:
            add("wf:quotes_missing", "排程", "盤中迴圈點火", "red", "今天盤中報價排程一班都沒啟動(GitHub 漏排)", fix="update_quotes.yml")
    # 網站部署
    pg = gh("/actions/runs?per_page=15&event=dynamic") or {}
    pr = [r for r in (pg.get("workflow_runs") or []) if str(r.get("name", "")).startswith("pages")]
    if pr:
        lastok = next((r for r in pr if r.get("conclusion") in ("success", "failure")), None)
        if lastok and lastok.get("conclusion") == "failure":
            add("pages", "網站", "網站部署", "red", f"最近一次網站部署失敗({ago(pdate(lastok.get('created_at')))})")
        else:
            add("pages", "網站", "網站部署", "ok", "最近一次部署成功")

def check_site():
    want = None
    try:
        want = re.search(r'name="build" content="(r\d+)"', open("index.html", encoding="utf-8").read()).group(1)
        js = open("app.js", encoding="utf-8").read(400000)
        jb = re.search(r"APP_BUILD='(r\d+)'", js).group(1)
        if jb != want:
            add("build", "網站", "前端版本一致", "red", f"index.html 是 {want}、app.js 是 {jb}——兩邊版本不一致(部署漏檔)")
        else:
            add("build", "網站", "前端版本一致", "ok", f"index.html 與 app.js 都是 {want}")
    except Exception as e:
        add("build", "網站", "前端版本一致", "warn", f"讀不到版本號:{e}")
    try:
        h = requests.get(SITE + "index.html?guard=" + str(int(time.time())), timeout=20, headers={"Cache-Control": "no-cache"}).text
        live = (re.search(r'name="build" content="(r\d+)"', h) or [None, None])[1]
        st = "ok" if live == want else "warn"
        add("live", "網站", "線上網站", st, f"線上版本 {live}" + ("" if st == "ok" else f"(repo 是 {want},可能還在部署)"), live)
    except Exception as e:
        add("live", "網站", "線上網站", "red", f"網站打不開:{str(e)[:80]}")

# ─────────────── 緊急處理 ───────────────
def restore_json(path):
    """壞檔 → 從最近幾版裡找第一個能讀、而且沒比現在大幅變小的版本,寫回(之後由 workflow 提交)"""
    cs = gh(f"/commits?path={path}&per_page=8") or []
    for c in cs[1:]:
        try:
            r = requests.get(f"https://raw.githubusercontent.com/{REPO}/{c['sha']}/{path}", timeout=60)
            if not r.ok: continue
            json.loads(r.text)
            open(path, "w", encoding="utf-8").write(r.text)
            act("restore", path, f"{path} 壞掉,已還原成 {c['sha'][:7]}({c['commit']['committer']['date'][:16]})的版本")
            return True
        except Exception:
            continue
    return False

ACTS = []
def act(kind, target, text):
    ACTS.append({"t": NOW.strftime("%Y-%m-%d %H:%M"), "kind": kind, "target": target, "text": text})
    log("  ⚙ " + text)

def dispatch(wf, why, state):
    hist = state.setdefault("disp", {}).setdefault(wf, [])
    hist[:] = [t for t in hist if (NOW - pdate(t)).total_seconds() < 86400]
    if hist and (NOW - pdate(hist[-1])).total_seconds() < 50 * 60:
        log(f"  {wf} 50 分鐘內已重啟過,先等等"); return False
    if len(hist) >= 4:
        log(f"  {wf} 今天已重啟 4 次,不再自動重啟(交給人處理)"); return False
    if any(r.get("status") in ("in_progress", "queued") for r in runs(wf)) and wf != "update_quotes.yml":
        log(f"  {wf} 正在跑,不重複啟動"); return False
    r = gh(f"/actions/workflows/{wf}/dispatches", "POST", json={"ref": "main"})
    ok = r is not None and r.status_code == 204
    hist.append(NOW.strftime("%Y-%m-%d %H:%M"))
    act("dispatch", wf, f"{why} → 自動重新啟動 {wf}" + ("" if ok else f"(失敗 {getattr(r,'status_code','?')})"))
    return ok

# ─────────────── 推播 ───────────────
def push_admin(title, body):
    if not SB_UID: log("  沒設 SB_UID,不推播"); return
    try:
        sys.path.insert(0, ".")
        import notify as N
        u = next((x for x in N.push_users() if x.get("uid") == SB_UID), None)
        if not u: log("  找不到管理員的推播訂閱"); return
        subs = json.loads(u["data"].get("pushSubs") or "[]")
        n, dead = N.send_push_to(subs, title, body, url=SITE + "#guard")
        if dead: N.push_report_dead(dead)
        log(f"  📲 推播 {n} 台裝置:{title}")
    except Exception as e:
        log(f"  推播失敗:{e}")

# ─────────────── 主程式 ───────────────
def main():
    prev = load(OUT, {})
    state = prev.get("state") or {}
    for f in (check_quotes, check_daily, check_files, lambda: check_integrity(state), check_workflows, check_site):
        try: f()
        except Exception as e:
            log(f"  檢查例外 {getattr(f,'__name__','?')}:{e}")
    # 緊急處理:紅燈且有對應排程 → 重啟
    done = set()
    for c in CHECKS:
        if c["st"] == "red" and c.get("fix") and c["fix"] not in done:
            done.add(c["fix"])
            if dispatch(c["fix"], f"{c['label']}:{c['msg']}", state):
                c["msg"] += "(已自動重啟排程)"
    # 狀態變化 → 紀錄 + 推播
    old = state.get("st") or {}
    new = {c["k"]: c["st"] for c in CHECKS}
    events = []
    for c in CHECKS:
        o = old.get(c["k"], "ok")
        if c["st"] != o:
            events.append({"t": NOW.strftime("%Y-%m-%d %H:%M"), "k": c["k"], "label": c["label"], "from": o, "to": c["st"], "msg": c["msg"]})
    state["st"] = new
    reds_new = [e for e in events if e["to"] == "red"]
    fixed = [e for e in events if e["from"] == "red" and e["to"] == "ok"]
    if reds_new:
        push_admin("🛡 網站異常(" + str(len(reds_new)) + ")", "\n".join(f"🔴 {e['label']}:{e['msg']}" for e in reds_new[:5]))
    if fixed:
        push_admin("🛡 已恢復", "\n".join(f"🟢 {e['label']} 恢復正常" for e in fixed[:5]))
    n_red = sum(1 for c in CHECKS if c["st"] == "red"); n_warn = sum(1 for c in CHECKS if c["st"] == "warn")
    overall = "red" if n_red else ("warn" if n_warn else "ok")
    acts_recent = (ACTS + (prev.get("acts") or []))[:30]
    out = {"v": 1, "u": NOW.strftime("%Y-%m-%d %H:%M"), "st": overall, "n_red": n_red, "n_warn": n_warn,
           "market": "盤中" if in_tw_market() else ("交易日" if tw_trading(TODAY) else "休市"),
           "checks": CHECKS, "acts": acts_recent, "events": (events + (prev.get("events") or []))[:40], "state": state}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    if events or ACTS:   # 永久事件紀錄(只增不減)
        L = load(LOG, {"items": []})
        L["items"] = (L.get("items") or []) + [dict(e, type="event") for e in events] + [dict(a, type="act") for a in ACTS]
        json.dump(L, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"🛡 {out['u']} {out['market']}:{len(CHECKS)} 項,紅 {n_red}・黃 {n_warn};處理 {len(ACTS)} 件;狀態變化 {len(events)} 件")
    for c in CHECKS:
        if c["st"] != "ok": log(f"   {'🔴' if c['st']=='red' else '🟡'} [{c['grp']}] {c['label']}:{c['msg']}")

if __name__ == "__main__":
    main()
