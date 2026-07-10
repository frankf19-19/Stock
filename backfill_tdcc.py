"""一次性回補:FinMind 股權分散表 → tdcc.json(v2, 9組級距, 近~18週)
v2 改版重點:
  1. token 改用 Authorization: Bearer header(FinMind 正式認證方式;URL 參數同時保留)
  2. 開跑先自我檢查 token 是否生效,無效立刻大聲報錯,不再默默匿名空轉
  3. 每 150 檔 commit 一次(斷頭/取消只損失最後一批),tdcc_state.json 記錄進度
  4. 重跑自動從斷點續補(已完成的檔直接跳過)
  5. 全程即時進度輸出(搭配 yml 的 PYTHONUNBUFFERED=1)
  6. 連續限流 → 保存進度後提前結束,不空耗時數
用法:GitHub Actions 手動觸發 backfill_tdcc.yml;有 token 約 3~3.5 小時,可分多次跑完。"""
import json, os, re, sys, time, subprocess, datetime as dt
import requests

TOK        = os.environ.get("FINMIND_TOKEN", "").strip()
START      = (dt.date.today() - dt.timedelta(days=130)).isoformat()
API        = "https://api.finmindtrade.com/api/v4/data"
STATE_FILE = "tdcc_state.json"
OUT_FILE   = "tdcc.json"
BATCH      = 150          # 每幾檔 commit 一次
SLEEP      = 6.1          # 600次/hr → 每 6 秒 1 次(保險值)

SES = requests.Session()
if TOK:
    SES.headers["Authorization"] = "Bearer " + TOK   # ← 正確的認證方式

def log(*a): print(*a, flush=True)

def lv_group(label):
    """FinMind 級距標籤 → 9 組索引(以級距下限股數判斷)"""
    digs = re.findall(r"[\d,]+", str(label))
    lo = int(digs[0].replace(",", "")) if digs else 0
    if lo >= 1000001: return 0      # L15 >1000張
    if lo >= 800001:  return 1      # L14
    if lo >= 600001:  return 2      # L13
    if lo >= 400001:  return 3      # L12
    if lo >= 200001:  return 4      # L11
    if lo >= 100001:  return 5      # L10
    if lo >= 50001:   return 6      # L9
    if lo >= 40001:   return 7      # L8
    return 8                        # L1-7(「差異數調整」等雜項已排除)

def fetch(sid):
    """抓一檔;回傳 (週資料dict, 狀態字串)。狀態:'ok' / 'rate' / 'err'"""
    p = {"dataset": "TaiwanStockHoldingSharesPer", "data_id": sid, "start_date": START}
    if TOK: p["token"] = TOK        # 參數也帶,雙保險
    try:
        r = SES.get(API, params=p, timeout=45)
        j = r.json()
    except Exception as e:
        return None, f"err:{e}"
    msg = str(j.get("msg", ""))
    if j.get("status") == 402 or "level" in msg.lower() or "upper limit" in msg.lower():
        return None, "rate"
    wk = {}
    for row in j.get("data") or []:
        lab = row.get("HoldingSharesLevel", "")
        if "調整" in str(lab): continue
        d = row.get("date"); g = wk.setdefault(d, [0.0] * 9)
        g[lv_group(lab)] += float(row.get("percent") or 0)
    return {d: [round(x, 2) for x in g] for d, g in wk.items()}, "ok"

def token_selfcheck():
    """開跑前確認 token 真的生效:抓 2330 一小段,看回應是否正常"""
    if not TOK:
        log("⚠ 未設定 FINMIND_TOKEN — 將以匿名身分執行。GitHub runner 的共用 IP")
        log("  匿名額度幾乎必定已被耗盡,強烈建議設定免費註冊 token 後再跑。")
        return
    log(f"token 已載入(長度 {len(TOK)}),自我檢查中…")
    wk, st = fetch("2330")
    if st == "rate":
        log("✗ 自我檢查:立刻被限流 — token 很可能無效或未生效!")
        log("  請確認 Secret 值是 eyJ0 開頭的完整字串(不含 Bearer 字樣、無多餘空白換行)。")
        sys.exit(1)
    if st.startswith("err"):
        log(f"⚠ 自我檢查:網路錯誤({st}),繼續嘗試主流程。")
    else:
        log(f"✓ 自我檢查通過:2330 取得 {len(wk or {})} 週資料。")
        log("  (跑幾分鐘後可到 FinMind 會員頁確認「api 已使用次數」在增加)")
    time.sleep(SLEEP)

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
    """raw: {sid: {date: [9]}} → v2 對齊格式,寫入 OUT_FILE"""
    dates = sorted({d for m in raw.values() for d in m})[-26:]
    J = {"v": 2, "d": dates,
         "s": {sid: [m.get(d) for d in dates] for sid, m in raw.items() if m}}
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(J, f, ensure_ascii=False, separators=(",", ":"))
    return len(dates), len(J["s"])

def main():
    reset = os.environ.get("RESET", "") == "true"
    with open("data.json", encoding="utf-8") as f:
        stocks = [s["id"] for s in json.load(f)["stocks"]
                  if s.get("market") == "TW" and not s.get("etf")]

    # 斷點續傳:讀 state + 既有 tdcc.json 還原 raw
    done, raw = set(), {}
    if not reset:
        st = load_json(STATE_FILE)
        if st and st.get("start") == START:
            done = set(st.get("done") or [])
        old = load_json(OUT_FILE)
        if done and old and old.get("v") == 2:
            for sid, arr in (old.get("s") or {}).items():
                raw[sid] = {d: g for d, g in zip(old["d"], arr or []) if g}
    todo = [s for s in stocks if s not in done]
    log(f"回補 {len(stocks)} 檔(已完成 {len(done)},本次待補 {len(todo)}),起日 {START}")
    if not todo:
        log("全部完成,無需回補。"); return

    token_selfcheck()
    rate_streak = 0
    for k, sid in enumerate(todo, 1):
        wk, st = None, ""
        for attempt in range(3):
            wk, st = fetch(sid)
            if st == "ok":
                rate_streak = 0; break
            if st == "rate":
                rate_streak += 1
                if rate_streak >= 6:
                    log(f"✗ 連續 {rate_streak} 次限流 — 保存進度後提前結束(re-run 會從斷點續跑)。")
                    build_output(raw)
                    with open(STATE_FILE, "w") as f:
                        json.dump({"start": START, "done": sorted(done)}, f)
                    commit_push(f"TDCC 回補中斷點 {len(done)}/{len(stocks)}")
                    sys.exit(1)
                log(f"  [限流] {sid} 休息 5 分鐘後重試({attempt+1}/3)…")
                time.sleep(300)
            else:
                time.sleep(8)
        if st == "ok" and wk is not None:
            for d, g in wk.items(): raw.setdefault(sid, {})[d] = g
            done.add(sid)
        else:
            log(f"  [跳過] {sid}({st})")
            done.add(sid)   # 記為已處理避免每輪重卡同一檔;要重抓可用 RESET
        if k % 25 == 0:
            log(f"  進度 {k}/{len(todo)}(累計完成 {len(done)}/{len(stocks)})")
        if k % BATCH == 0:
            w, n = build_output(raw)
            with open(STATE_FILE, "w") as f:
                json.dump({"start": START, "done": sorted(done)}, f)
            commit_push(f"TDCC 回補進度 {len(done)}/{len(stocks)}({w} 週×{n} 檔)")
        time.sleep(SLEEP)

    w, n = build_output(raw)
    if os.path.exists(STATE_FILE): os.remove(STATE_FILE)
    git("rm", "--cached", STATE_FILE)
    commit_push(f"TDCC 歷史回補完成({w} 週×{n} 檔)")
    log(f"完成:{w} 週 × {n} 檔")

if __name__ == "__main__":
    main()
