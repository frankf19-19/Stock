"""TDCC 大戶持股收數 v4:集保官方 CSV(每週自動)+ Wayback 歷史快照(手動完整模式)→ tdcc.json
模式:MODE=weekly(排程用)只抓官方最新一週,約 1 分鐘;未設定(手動)跑完整流程含 Wayback。
背景:FinMind 已將「股權分散表」移至贊助等級,免費 token 無法使用,故改用零成本官方來源。
來源:
  1. 集保 TDCC 開放資料 CSV(id=1-5,含全市場最新一週)
  2. Internet Archive 對同一 CSV 的歷史快照(每份快照 = 完整一週 × 全市場)
特性:每處理完一週 commit 一次、tdcc_state.json 斷點續傳、進度即時輸出、不需任何 token。
誠實聲明:歷史涵蓋率取決於 Archive 快照密度,可能非每週都有;缺週由每週例行更新自然補齊。"""
import csv, io, json, os, sys, subprocess, datetime as dt
import requests

CSV_URL    = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
CDX_API    = "https://web.archive.org/cdx/search/cdx"
STATE_FILE = "tdcc_state.json"
OUT_FILE   = "tdcc.json"
DAYS_BACK  = 190          # 往回撈多少天的快照(~27週,取到 26 週上限)

SES = requests.Session()
SES.headers["User-Agent"] = "Mozilla/5.0 (tdcc-backfill; personal dashboard)"

def log(*a): print(*a, flush=True)

# 集保 CSV 持股分級(1~15)→ 9 組索引;16=差異數調整、17=合計 → 跳過
LV9 = {15:0, 14:1, 13:2, 12:3, 11:4, 10:5, 9:6, 8:7,
       1:8, 2:8, 3:8, 4:8, 5:8, 6:8, 7:8}

def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)

def commit_push(msg):
    git("config", "user.name", "bot")
    git("config", "user.email", "bot@users.noreply.github.com")
    git("add", OUT_FILE, STATE_FILE)
    c = git("commit", "-m", msg + " [CI Skip]")
    if "nothing to commit" in (c.stdout + c.stderr):
        log("  (無變更可提交)"); return
    git("pull", "--rebase", "origin", "main")
    p = git("push")
    log(f"  已提交:{msg}" + ("" if p.returncode == 0 else f"(push 失敗:{p.stderr.strip()[:120]})"))

def load_json(path):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except Exception: return None

def build_output(raw):
    dates = sorted({d for m in raw.values() for d in m})[-26:]
    J = {"v": 2, "d": dates,
         "s": {sid: [m.get(d) for d in dates] for sid, m in raw.items() if m}}
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(J, f, ensure_ascii=False, separators=(",", ":"))
    return len(dates), len(J["s"])

def parse_csv(text, want):
    """CSV 內容 → (資料日期 'YYYY-MM-DD', {sid: [9組%]});want=要保留的股票代號集合"""
    rd = csv.reader(io.StringIO(text))
    header = next(rd, None)
    if not header: return None, {}
    date, out = None, {}
    for row in rd:
        if len(row) < 6: continue
        d, sid, lv = row[0].strip(), row[1].strip(), row[2].strip()
        if sid not in want: continue
        try: lv = int(lv)
        except ValueError: continue
        gi = LV9.get(lv)
        if gi is None: continue                     # 16 差異調整 / 17 合計
        try: pct = float(row[5])
        except ValueError: continue
        g = out.setdefault(sid, [0.0]*9)
        g[gi] += pct
        if date is None and len(d) >= 8:
            dd = d.replace("-", "")
            date = f"{dd[:4]}-{dd[4:6]}-{dd[6:8]}"
    return date, {sid: [round(x, 2) for x in g] for sid, g in out.items()}

def download(url, timeout=300):
    r = SES.get(url, timeout=timeout)
    r.raise_for_status()
    b = r.content
    for enc in ("utf-8-sig", "utf-8", "cp950"):
        try: return b.decode(enc)
        except UnicodeDecodeError: continue
    return b.decode("utf-8", errors="replace")

def wayback_snapshots():
    """回傳近 DAYS_BACK 天的快照 timestamp 清單(新→舊)"""
    frm = (dt.date.today() - dt.timedelta(days=DAYS_BACK)).strftime("%Y%m%d")
    try:
        r = SES.get(CDX_API, params={
            "url": CSV_URL, "output": "json", "from": frm,
            "filter": "statuscode:200", "collapse": "timestamp:8", "limit": "300"
        }, timeout=60)
        rows = r.json()
    except Exception as e:
        log(f"⚠ 查詢 Wayback 快照清單失敗:{e}")
        return []
    ts = [x[1] for x in rows[1:]] if rows and len(rows) > 1 else []
    ts.sort(reverse=True)
    return ts

def main():
    reset = os.environ.get("RESET", "") == "true"
    with open("data.json", encoding="utf-8") as f:
        want = {s["id"] for s in json.load(f)["stocks"]
                if s.get("market") == "TW" and not s.get("etf")}
    log(f"目標股池 {len(want)} 檔(台股個股)")

    # 續傳:還原既有 tdcc.json + 已處理快照清單
    done_ts, raw = set(), {}
    if not reset:
        st = load_json(STATE_FILE)
        if st: done_ts = set(st.get("ts") or [])
        old = load_json(OUT_FILE)
        if old and old.get("v") == 2 and old.get("d"):
            for sid, arr in (old.get("s") or {}).items():
                raw[sid] = {d: g for d, g in zip(old["d"], arr or []) if g}
            log(f"讀入既有 tdcc.json:{len(old['d'])} 週 × {len(raw)} 檔")
    have_dates = {d for m in raw.values() for d in m}

    def absorb(label, date, data):
        if not date or not data:
            log(f"  {label}:無有效資料,跳過"); return False
        if date in have_dates:
            log(f"  {label}:{date} 已存在,跳過"); return False
        for sid, g in data.items(): raw.setdefault(sid, {})[date] = g
        have_dates.add(date)
        w, n = build_output(raw)
        with open(STATE_FILE, "w") as f:
            json.dump({"ts": sorted(done_ts)}, f)
        commit_push(f"TDCC 回補 {date}(累計 {w} 週×{n} 檔)")
        return True

    # 1) 官方最新一週
    log("下載集保官方最新 CSV…")
    try:
        date, data = parse_csv(download(CSV_URL), want)
        log(f"  最新週:{date},{len(data)} 檔")
        absorb("官方最新", date, data)
    except Exception as e:
        log(f"⚠ 官方 CSV 下載失敗:{e}(繼續嘗試歷史快照)")

    if os.environ.get("MODE", "") == "weekly":
        log("weekly 模式:官方最新週已處理,收工(Wayback 掃描僅手動模式執行)。")
        return

    # 2) Wayback 歷史快照
    ts_list = [t for t in wayback_snapshots() if t not in done_ts]
    log(f"Wayback 找到 {len(ts_list)} 份待處理快照(近 {DAYS_BACK} 天)")
    if not ts_list and len(have_dates) <= 1:
        log("⚠ Archive 沒有可用的歷史快照 — 歷史只能靠每週例行更新自然累積。")
    ok = 0
    for i, t in enumerate(ts_list, 1):
        u = f"https://web.archive.org/web/{t}id_/{CSV_URL}"
        log(f"[{i}/{len(ts_list)}] 快照 {t[:8]} 下載中…")
        try:
            date, data = parse_csv(download(u), want)
            if absorb(f"快照{t[:8]}", date, data): ok += 1
        except Exception as e:
            log(f"  快照 {t[:8]} 失敗:{e}(跳過)")
        done_ts.add(t)
        with open(STATE_FILE, "w") as f:
            json.dump({"ts": sorted(done_ts)}, f)

    w, n = build_output(raw)
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE); git("rm", "--cached", STATE_FILE)
    commit_push(f"TDCC 歷史回補完成({w} 週×{n} 檔,本輪新增 {ok} 週)")
    log(f"完成:tdcc.json 共 {w} 週 × {n} 檔;本輪由快照新增 {ok} 週。")
    if w < 8:
        log("提醒:目前累積週數仍少,趨勢圖會先短一點,之後每週自動 +1 週。")

if __name__ == "__main__":
    main()
