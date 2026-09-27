#!/usr/bin/env python3
"""今天是不是交易日?(r911)——讓「交易日才要跑的」和「假日才跑的重工作」自動分流。
用法:python market_day.py tw   → 台股今天有開盤就 exit 0,休市(週末/國定假日/颱風假)exit 1
      python market_day.py us   → 美股同理(用紐約日期)
依據 holidays.json(證交所官方 + NYSE 規則 + 資料學到的休市日)。"""
import json, sys, datetime as dt

mk = (sys.argv[1] if len(sys.argv) > 1 else "tw").lower()
tz = dt.timedelta(hours=8) if mk == "tw" else dt.timedelta(hours=-4)
d = (dt.datetime.utcnow() + tz).date()
try:
    H = json.load(open("holidays.json", encoding="utf-8")).get(mk) or {}
except Exception:
    H = {}
name = H.get(d.isoformat())
if d.weekday() >= 5: print(f"{mk} {d} 週末休市"); sys.exit(1)
if name: print(f"{mk} {d} 休市:{name}"); sys.exit(1)
print(f"{mk} {d} 交易日"); sys.exit(0)
