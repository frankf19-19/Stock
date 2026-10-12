#!/usr/bin/env python3
"""r1081:⏰ 排程保險——GitHub 自己的排程常延遲好幾小時、甚至整班丟掉(10/12 早報兩班都沒跑、融資融券晚 8 小時)。
由 Worker 準時觸發的「股癌整理」(每 2 小時)順便跑這支:時間到了、該有的資料還沒出 → 印出要補啟動的排程檔名。
  📰 早報 news.yml       :台北 06:00 後,今天的早報還沒出
  💳 融資融券 margin.yml :最近一個「21:45 已過」的台股交易日,margin.json 還不是那天
  🛡 網站管理員 guard.yml:巡檢超過 2 小時沒更新
用法:python cron_guard.py  → stdout 一行一個 workflow 檔名(說明寫在 stderr)"""
import json, sys, datetime as dt

NOW = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=8)   # 台北時間(沒有夏令時間)
TODAY = NOW.date()


def load(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d


def log(*a): print(*a, file=sys.stderr, flush=True)


HOL = (load("holidays.json", {}) or {}).get("tw") or {}
def trading(d): return d.weekday() < 5 and d.isoformat() not in HOL


out = []
# 📰 早報
nd = (load("news.json", {}) or {}).get("date")
if NOW.hour >= 6 and nd != TODAY.isoformat():
    log(f"早報:最新 {nd},今天 {TODAY} 還沒出"); out.append("news.yml")
# 💳 融資融券(證交所/櫃買約 21:00 後才齊)
d = TODAY
if not (trading(d) and (NOW.hour, NOW.minute) >= (21, 45)):
    d -= dt.timedelta(days=1)
    while not trading(d): d -= dt.timedelta(days=1)
mu = str((load("margin.json", {}) or {}).get("updated") or "")[:10]
if mu < d.isoformat():
    log(f"融資融券:最新 {mu or '—'},應有 {d}"); out.append("margin.yml")
# 🛡 網站管理員
gu = str((load("guard.json", {}) or {}).get("u") or "")
try: gt = dt.datetime.strptime(gu[:16], "%Y-%m-%d %H:%M")
except Exception: gt = None
if gt is None or (NOW - gt).total_seconds() > 2 * 3600:
    log(f"網站管理員:上次巡檢 {gu or '—'},超過 2 小時"); out.append("guard.yml")
if not out: log("排程保險:都正常")
print("\n".join(out))
