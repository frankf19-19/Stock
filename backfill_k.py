#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_k.py — 全市場日K快速回補(一次性 Action;可重跑接續)
  上市:證交所 STOCK_DAY 個股月檔(官方)
  上櫃:櫃買中心 tradingStock 個股月檔(新版官方端點,舊版 st43 自動備援)
  已達 240 根的個股自動跳過 → 中斷重跑會從斷點接續
  每 100 檔存檔一次;與 update_data.py 完全同構(k/ 分片、260 根裁切)
"""
import os, json, glob, time, datetime as dt, random
import requests

KEEP_BARS = 260
TARGET    = 240      # 低於此根數才回補
MONTHS    = 14
K_DIR     = "k"
UA = {"User-Agent": "Mozilla/5.0 (backfill; personal dashboard)"}
TODAY = dt.date.today()

def get_json(url, timeout=25):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.json()

def month_heads(n):
    d0 = TODAY.replace(day=1); out=[]
    for k in range(n-1, -1, -1):
        y, m = d0.year, d0.month - k
        while m <= 0: m += 12; y -= 1
        out.append((y, m))
    return out

def parse_num(s):
    try:
        v = float(str(s).replace(",", "").replace("--","").strip() or 0)
        return v
    except Exception:
        return 0.0

def roc_to_iso(s):
    # 115/07/17 或 1150717 → 2026-07-17
    s = str(s).strip().replace(".", "/")
    p = s.split("/")
    try:
        if len(p) == 3:
            y = int(p[0]) + 1911
            return f"{y:04d}-{int(p[1]):02d}-{int(p[2]):02d}"
        if len(s) >= 7 and s.isdigit():
            y = int(s[:-4]) + 1911
            return f"{y:04d}-{s[-4:-2]}-{s[-2:]}"
    except Exception:
        pass
    return None

def rows_from_any(obj):
    """在回應樹中找出「列陣列」:每列含民國日期字串+至少4個價格欄。"""
    found = []
    def scan(o, depth=0):
        if depth > 4 or o is None: return
        if isinstance(o, list):
            if o and isinstance(o[0], list) and len(o[0]) >= 7:
                found.append(o)
            for x in o[:3]: scan(x, depth+1)
        elif isinstance(o, dict):
            for v in o.values(): scan(v, depth+1)
    scan(obj)
    for rows in found:
        if any(roc_to_iso(r[0]) for r in rows[:3]):
            return rows
    return None

def fetch_tse_month(sid, y, m):
    j = get_json(f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
                 f"?date={y}{m:02d}01&stockNo={sid}&response=json")
    out = {}
    for row in (j or {}).get("data") or []:
        try:
            iso = roc_to_iso(row[0])
            if not iso: continue
            vol = int(parse_num(row[1]) / 1000)          # 股 → 張
            o,h,l,c = (parse_num(row[3]), parse_num(row[4]),
                       parse_num(row[5]), parse_num(row[6]))
            if o>0 and h>0 and l>0 and c>0:
                out[iso] = [round(o,2), round(h,2), round(l,2), round(c,2), vol]
        except Exception: pass
    return out

def fetch_otc_month(sid, y, m):
    roc = y - 1911
    urls = [
        f"https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code={sid}&date={y}/{m:02d}/01&response=json",
        f"https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php?l=zh-tw&d={roc}/{m:02d}&stkno={sid}",
    ]
    for u in urls:
        try:
            rows = rows_from_any(get_json(u))
            if not rows: continue
            out = {}
            for row in rows:
                iso = roc_to_iso(row[0])
                if not iso: continue
                vol = int(parse_num(row[1]))              # 櫃買月檔:仟股 = 張
                o,h,l,c = (parse_num(row[3]), parse_num(row[4]),
                           parse_num(row[5]), parse_num(row[6]))
                if o>0 and h>0 and l>0 and c>0:
                    out[iso] = [round(o,2), round(h,2), round(l,2), round(c,2), vol]
            if out: return out
        except Exception:
            pass
    return {}

def load_all():
    hist = {}
    for fp in glob.glob(os.path.join(K_DIR, "*.json")):
        try:
            with open(fp, encoding="utf-8") as f: hist.update(json.load(f))
        except Exception: pass
    return hist

def save_all(hist, comps):
    os.makedirs(K_DIR, exist_ok=True)
    by_id = {c["id"]: c for c in comps}
    shards = {}
    for sid, v in hist.items():
        c = by_id.get(sid)
        if not c: continue
        shards.setdefault(f"tw{sid[0]}.json", {})[sid] = v   # 與 update_data.shard_name 同構:上市上櫃同一命名空間
    for fn, obj in shards.items():
        with open(os.path.join(K_DIR, fn), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))

def main():
    with open("data.json", encoding="utf-8") as f:
        comps = [s for s in json.load(f)["stocks"]
                 if s.get("market") == "TW" and s["id"][0].isdigit()]
    hist = load_all()
    todo = [c for c in comps if len((hist.get(c["id"]) or {}).get("d") or []) < TARGET]
    print(f"全市場 {len(comps)} 檔;需回補 {len(todo)} 檔(已達 {TARGET} 根者跳過)", flush=True)
    heads = month_heads(MONTHS)
    done = fail = 0
    t0 = time.time()
    for i, c in enumerate(todo, 1):
        sid, is_otc = c["id"], c.get("ex") == "otc"
        days = {}
        okm = 0
        for (y, m) in heads:
            got = (fetch_otc_month if is_otc else fetch_tse_month)(sid, y, m)
            if got: okm += 1
            days.update(got)
            time.sleep(0.35 + random.random()*0.15)
        e = hist.get(sid) or {"d": [], "o": []}
        for d_, o_ in zip(e.get("d") or [], e.get("o") or []):
            days.setdefault(d_, o_)                      # 官方月檔優先,舊資料補洞
        ds = sorted(days)[-KEEP_BARS:]
        if len(ds) >= 30:
            hist[sid] = {"d": ds, "o": [days[d_] for d_ in ds]}
            done += 1
        else:
            fail += 1
        if i % 10 == 0 or i == len(todo):
            el = time.time() - t0
            eta = el / i * (len(todo) - i)
            print(f"  [{i}/{len(todo)}] {sid}{'櫃' if is_otc else ''} {len(ds)}根(月檔{okm}/{MONTHS}) "
                  f"· 成功{done} 失敗{fail} · 已用{el/60:.0f}分 估剩{eta/60:.0f}分", flush=True)
        if i % 100 == 0:
            save_all(hist, comps)
            print(f"  💾 進度存檔({i} 檔)", flush=True)
    save_all(hist, comps)
    print(f"完成:成功 {done}、無法回補 {fail}(多為新上市/資料不足,排程會逐日長大)", flush=True)

if __name__ == "__main__":
    main()
