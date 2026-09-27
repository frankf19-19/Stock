#!/usr/bin/env python3
"""K研所 · 每日分數歷史(r909)→ score_hist/YYYY-MM.json(永久保存,每月一檔)

data.json 只放「現在」的三力分數;過去每天的分數原本只存在 GitHub 的版本快照裡。
這支把每檔股票每天的 價格、漲跌%、基本面、籌碼、技術 分數存成精簡的永久紀錄:
  score_hist/2026-09.json = {"days": {"2026-09-26": {"u": "更新時間", "s": {"2330": [2475, -1.0, 75, 51, 82], ...}}}}
同一天跑多輪 → 以最後一輪(收盤後最完整)覆蓋;週末不記。
用法:python score_hist.py              (每輪自動記今天)
      python score_hist.py <data.json> (回補用:指定某個歷史版本檔)
"""
import json, os, sys, datetime as dt

DIR = "score_hist"


def snap(D):
    """把一份 data.json 壓成當日快照;回傳 (日期, 快照) 或 (None, None)"""
    u = str(D.get("updated") or "")
    # 日期 = 這份資料對應的「交易日」:優先用健康度裡台股日K的最新日期;
    # 沒有就用更新時間推(下午 2 點前 = 前一個交易日的收盤;週末 = 週五)
    d = None
    try:
        for it in ((D.get("health") or {}).get("items") or []):
            if it.get("k") == "ktw" and len(str(it.get("last", ""))) == 10: d = dt.date.fromisoformat(it["last"]); break
    except Exception: d = None
    if d is None:
        try:
            t = dt.datetime.fromisoformat(u[:16].replace(" ", "T"))
        except Exception:
            return None, None
        d = t.date() - dt.timedelta(days=1) if t.hour < 14 else t.date()
        while d.weekday() >= 5: d -= dt.timedelta(days=1)
    S = {}
    for s in D.get("stocks") or []:
        sid = s.get("id"); px = s.get("price")
        if not sid or px in (None, ""): continue
        sc = lambda k: (s.get(k) or {}).get("score") if isinstance(s.get(k), dict) else None
        S[str(sid)] = [px, s.get("chg"), sc("f"), sc("c"), sc("t")]
    return (d.isoformat(), {"u": u, "s": S}) if S else (None, None)


def put(day, rec):
    os.makedirs(DIR, exist_ok=True)
    p = f"{DIR}/{day[:7]}.json"
    try:
        with open(p, encoding="utf-8") as f: H = json.load(f)
    except Exception:
        H = {"days": {}}
    old = H["days"].get(day)
    if old and str(old.get("u", "")) > rec["u"]: return False       # 已有更晚的版本,不覆蓋
    H["days"][day] = rec
    H["days"] = dict(sorted(H["days"].items()))
    with open(p, "w", encoding="utf-8") as f: json.dump(H, f, ensure_ascii=False, separators=(",", ":"))
    return True


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "data.json"
    try:
        with open(src, encoding="utf-8") as f: D = json.load(f)
    except Exception as e:
        print("score_hist:讀不到", src, e); return
    day, rec = snap(D)
    if not day: print("score_hist:非交易日或無資料,略過"); return
    ok = put(day, rec)
    print(f"score_hist:{day} {len(rec['s'])} 檔 {'已寫入' if ok else '已有較新版本'}")


if __name__ == "__main__":
    main()
