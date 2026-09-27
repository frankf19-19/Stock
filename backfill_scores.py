#!/usr/bin/env python3
"""一次性回補(r909):從 GitHub 版本歷史抽出「網站誕生至今」每一天收盤後的分數 → score_hist/
每個日期取「當天最後一個 data.json 版本」(台北時間),交給 score_hist.put() 寫入。需要完整歷史(fetch-depth: 0)。"""
import json, subprocess, datetime as dt, sys
import score_hist as SH

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, timeout=600).stdout

log = git("log", "--format=%H %cI", "--", "data.json").split("\n")
last = {}
for ln in log:
    if not ln.strip(): continue
    sha, ts = ln.split(" ", 1)
    t = dt.datetime.fromisoformat(ts.strip()).astimezone(dt.timezone(dt.timedelta(hours=8)))
    d = t.date().isoformat()
    if d not in last or t > last[d][1]: last[d] = (sha, t)
print(f"data.json 共 {len(log)} 個版本,涵蓋 {len(last)} 天")
n = 0
for d in sorted(last):
    sha = last[d][0]
    raw = subprocess.run(["git", "show", f"{sha}:data.json"], capture_output=True, timeout=600).stdout
    try: D = json.loads(raw.decode("utf-8"))
    except Exception as e: print(" ", d, "解析失敗", e); continue
    day, rec = SH.snap(D)
    if not day: continue
    if SH.put(day, rec): n += 1
    print(" ", d, "→", day, len(rec["s"]), "檔")
print(f"✅ 回補完成:寫入 {n} 天")
