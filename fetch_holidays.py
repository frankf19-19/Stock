#!/usr/bin/env python3
"""K研所 · 休市行事曆(r904)→ holidays.json

三個來源,合併成一份,網站前後端都讀它:
  ① 台股:證交所官方 OpenAPI(holidaySchedule),民國年日期轉西元;排除「開始交易日/最後交易日」這類其實有開盤的列
  ② 美股:NYSE 固定規則自己算(元旦、MLK、總統日、耶穌受難日、陣亡將士、六月節、獨立、勞動、感恩、聖誕;週末順延)
  ③ 從資料學:過去交易日裡,平日卻完全沒有 K 線的日子(颱風假、臨時休市)→ 自動記下來,之後就認得
官方抓不到時沿用上一版 holidays.json,不會變成空的。
"""
import json, os, datetime as dt, glob

OUT = "holidays.json"
TODAY = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()


def load(p, d):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return d


def tw_official():
    import requests
    r = requests.get("https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule", timeout=30,
                     headers={"User-Agent": "Mozilla/5.0 (kyansuo)"})
    out = {}
    for x in r.json():
        name = str(x.get("Name") or "").strip(); raw = str(x.get("Date") or "").strip()
        if not raw.isdigit() or len(raw) < 7: continue
        if "開始交易" in name or "最後交易" in name: continue          # 這兩類當天有開盤
        y = int(raw[:-4]) + 1911; d = dt.date(y, int(raw[-4:-2]), int(raw[-2:]))
        if d.weekday() >= 5: continue                                 # 週末本來就休
        out[d.isoformat()] = "休市(結算交割)" if "無交易" in name else name
    return out


def us_rules(year):
    def nth(m, wd, n):                 # 第 n 個星期 wd(0=一)
        d = dt.date(year, m, 1); d += dt.timedelta(days=(wd - d.weekday()) % 7); return d + dt.timedelta(weeks=n - 1)
    def last(m, wd):
        d = dt.date(year, m + 1, 1) - dt.timedelta(days=1) if m < 12 else dt.date(year, 12, 31)
        return d - dt.timedelta(days=(d.weekday() - wd) % 7)
    def obs(d):                        # 週六→週五、週日→週一
        return d - dt.timedelta(days=1) if d.weekday() == 5 else d + dt.timedelta(days=1) if d.weekday() == 6 else d
    def easter(y):                     # 西方復活節(Anonymous Gregorian)
        a = y % 19; b, c = divmod(y, 100); d, e = divmod(b, 4); f = (b + 8) // 25; g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30; i, k = divmod(c, 4); l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451; mo = (h + l - 7 * m + 114) // 31; da = ((h + l - 7 * m + 114) % 31) + 1
        return dt.date(y, mo, da)
    H = {}
    ny = dt.date(year, 1, 1)
    if ny.weekday() != 5: H[obs(ny)] = "New Year's Day(元旦)"      # 元旦逢週六:NYSE 不在前一年補休
    H[nth(1, 0, 3)] = "MLK Day(金恩紀念日)"
    H[nth(2, 0, 3)] = "Presidents' Day(總統日)"
    H[easter(year) - dt.timedelta(days=2)] = "Good Friday(耶穌受難日)"
    H[last(5, 0)] = "Memorial Day(陣亡將士紀念日)"
    H[obs(dt.date(year, 6, 19))] = "Juneteenth(六月節)"
    H[obs(dt.date(year, 7, 4))] = "Independence Day(獨立紀念日)"
    H[nth(9, 0, 1)] = "Labor Day(勞動節)"
    H[nth(11, 3, 4)] = "Thanksgiving(感恩節)"
    H[obs(dt.date(year, 12, 25))] = "Christmas(聖誕節)"
    return {d.isoformat(): n for d, n in H.items() if d.weekday() < 5}


def learned_gaps(prefix, bench, known):
    """從 K 線學:基準股資料範圍內,平日卻沒有 K 棒 → 休市(颱風假等)"""
    days = None
    for p in glob.glob(f"k/{prefix}*.json"):
        j = load(p, {})
        if bench in j and isinstance(j[bench], dict): days = j[bench].get("d") or []; break
    if not days: return {}
    have = set(days); out = {}
    d = dt.date.fromisoformat(days[0]); end = dt.date.fromisoformat(days[-1])
    while d <= end:
        s = d.isoformat()
        if d.weekday() < 5 and s not in have and s not in known: out[s] = "無交易(資料推斷:颱風假或臨時休市)"
        d += dt.timedelta(days=1)
    return out


def main():
    prev = load(OUT, {})
    tw = dict(prev.get("tw") or {})
    try:
        o = tw_official()
        if len(o) >= 5: tw.update(o); print(f"holidays:證交所官方 {len(o)} 天")
    except Exception as e:
        print(f"holidays:證交所 API 失敗 {e},沿用上一版")
    us = dict(prev.get("us") or {})
    for y in (TODAY.year - 1, TODAY.year, TODAY.year + 1): us.update(us_rules(y))
    lt = learned_gaps("tw", "2330", tw); lu = learned_gaps("us_", "SPY", us)
    learned = dict(prev.get("learned") or {}); learned.update({"tw:" + k: v for k, v in lt.items()}); learned.update({"us:" + k: v for k, v in lu.items()})
    for k, v in learned.items():
        m, d = k.split(":", 1)
        (tw if m == "tw" else us).setdefault(d, v)
    keep = (TODAY - dt.timedelta(days=800)).isoformat()                # 只留兩年多
    tw = {k: v for k, v in sorted(tw.items()) if k >= keep}; us = {k: v for k, v in sorted(us.items()) if k >= keep}
    res = {"updated": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"), "tw": tw, "us": us,
           "learned": {k: v for k, v in learned.items() if k.split(":", 1)[1] >= keep}}
    with open(OUT, "w", encoding="utf-8") as f: json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    nxt = lambda H: next(((k, v) for k, v in H.items() if k >= TODAY.isoformat()), None)
    print(f"holidays:台股 {len(tw)}、美股 {len(us)}、資料推斷 {len(learned)};下一個台股休市 {nxt(tw)},美股 {nxt(us)}")


if __name__ == "__main__":
    try: main()
    except Exception as e: print("holidays 例外", e)
