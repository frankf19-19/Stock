#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_margin.py — 散戶槓桿資料:融資融券餘額 / 借券賣出 / 當沖成交(上市+上櫃)
來源:證交所 rwd JSON(免費官方)+ 櫃買中心(多候選端點探測)。
輸出:margin.json(前端用,含 12 日融資餘額歷史供趨勢判讀)+ margin_diag.json(診斷)。
設計:任何一段失敗都不炸整包——抓到多少寫多少,診斷寫明哪段斷了。永遠 exit 0。
"""
import json, os, time, datetime, urllib.request as rq

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36"
DIAG = {"ts": datetime.datetime.now().isoformat(), "steps": [], "verdict": []}
def log(s, **k):
    DIAG["steps"].append({"s": s, **k}); print("[margin]", s, k, flush=True)

def get(u, timeout=30):
    req = rq.Request(u, headers={"User-Agent": UA, "Accept": "application/json"})
    with rq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))

def num(x):
    try: return int(str(x).replace(",", "").split(".")[0])
    except Exception: return 0

def col(fields, *kw):
    """依表頭關鍵字找欄位索引(全部關鍵字都要出現在同一欄名裡)"""
    for i, f in enumerate(fields):
        f2 = str(f)
        if all(k in f2 for k in kw): return i
    return -1

def tw_date():
    d = datetime.date.today()
    while d.weekday() >= 5: d -= datetime.timedelta(days=1)
    return d

def main():
    d = tw_date(); ds = d.strftime("%Y%m%d"); iso = d.isoformat()
    out = {"updated": iso, "s": {}, "hist": {}}
    # 讀舊檔繼承歷史(跨日累積)
    old_hist = {}
    if os.path.exists("margin.json"):
        try:
            oldj = json.load(open("margin.json", encoding="utf-8"))
            old_hist = oldj.get("hist", {}) or {}
        except Exception as e: log("old_read_fail", e=str(e)[:80])

    # ── ① 上市 融資融券(MI_MARGN,rwd JSON)──
    try:
        j = get(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ds}&selectType=ALL&response=json")
        tables = j.get("tables") or ([j] if j.get("data") else [])
        done = 0
        for t in tables:
            fields = t.get("fields") or []
            ci = col(fields, "代號")
            cf = col(fields, "融資", "今日餘額")
            cq = col(fields, "融券", "今日餘額")
            if ci < 0 or cf < 0: continue
            for row in t.get("data") or []:
                sid = str(row[ci]).strip()
                if not sid or not sid[0].isdigit(): continue
                rec = out["s"].setdefault(sid, {})
                rec["f"] = num(row[cf])
                if cq >= 0: rec["q"] = num(row[cq])
                done += 1
        log("twse_margin", n=done)
        if not done: DIAG["verdict"].append("TWSE_MARGIN_EMPTY(可能假日或表頭改版)")
    except Exception as e:
        log("twse_margin_fail", e=str(e)[:150]); DIAG["verdict"].append("TWSE_MARGIN_FAIL")

    # ── ② 上市 借券賣出(TWT93U:融券與借券賣出)──
    try:
        j = get(f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={ds}&response=json")
        tables = j.get("tables") or ([j] if j.get("data") else [])
        done = 0
        for t in tables:
            fields = t.get("fields") or []
            ci = col(fields, "代號")
            cb = col(fields, "借券", "餘額")
            if cb < 0: cb = col(fields, "借券賣出", "當日餘額")
            if ci < 0 or cb < 0: continue
            for row in t.get("data") or []:
                sid = str(row[ci]).strip()
                if not sid or not sid[0].isdigit(): continue
                out["s"].setdefault(sid, {})["b"] = num(row[cb])
                done += 1
        log("twse_borrow", n=done)
    except Exception as e:
        log("twse_borrow_fail", e=str(e)[:150]); DIAG["verdict"].append("TWSE_BORROW_FAIL")

    # ── ③ 上市 當沖成交股數(TWTB4U)──
    try:
        j = get(f"https://www.twse.com.tw/rwd/zh/afterTrading/TWTB4U?date={ds}&selectType=All&response=json")
        tables = j.get("tables") or ([j] if j.get("data") else [])
        done = 0
        for t in tables:
            fields = t.get("fields") or []
            ci = col(fields, "代號")
            cd = col(fields, "當日沖銷", "成交股數")
            if cd < 0: cd = col(fields, "當沖", "股數")
            if ci < 0 or cd < 0: continue
            for row in t.get("data") or []:
                sid = str(row[ci]).strip()
                if not sid or not sid[0].isdigit(): continue
                out["s"].setdefault(sid, {})["dt"] = num(row[cd]) // 1000   # 股→張
                done += 1
        log("twse_daytrade", n=done)
    except Exception as e:
        log("twse_daytrade_fail", e=str(e)[:150]); DIAG["verdict"].append("TWSE_DT_FAIL")

    # ── ④ 上櫃(TPEx):多候選端點探測 ──
    roc = f"{d.year-1911}/{d.month:02d}/{d.day:02d}"
    tpex_margin_cands = [
        f"https://www.tpex.org.tw/www/zh-tw/margin/balance?date={roc}&response=json",
        f"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&d={roc}&o=json",
        "https://www.tpex.org.tw/openapi/v1/tpex_mgtq_bal",
    ]
    got_tpex = 0
    for u in tpex_margin_cands:
        try:
            j = get(u)
            rows = j.get("aaData") or j.get("data") or (j.get("tables",[{}])[0].get("data") if j.get("tables") else None) or (j if isinstance(j,list) else None)
            if not rows: log("tpex_probe_empty", u=u.split("?")[0][-40:]); continue
            for row in rows:
                if isinstance(row, dict):
                    sid = str(row.get("SecuritiesCompanyCode") or row.get("股票代號") or row.get("code") or "").strip()
                    f = num(row.get("MarginPurchaseTodayBalance") or row.get("融資今日餘額") or 0)
                    q = num(row.get("ShortSaleTodayBalance") or row.get("融券今日餘額") or 0)
                else:
                    sid = str(row[0]).strip()
                    f = num(row[6]) if len(row) > 6 else 0
                    q = num(row[12]) if len(row) > 12 else 0
                if not sid or not sid[0].isdigit(): continue
                rec = out["s"].setdefault(sid, {})
                if f: rec["f"] = f
                if q: rec["q"] = q
                got_tpex += 1
            if got_tpex: log("tpex_margin_ok", u=u.split("?")[0][-40:], n=got_tpex); break
        except Exception as e:
            log("tpex_probe_fail", u=u.split("?")[0][-40:], e=str(e)[:100])
    if not got_tpex: DIAG["verdict"].append("TPEX_MARGIN_FAIL(候選端點全滅,貼 diag 給 Claude 修路徑)")

    # ── ⑤ 融資餘額歷史(12 日)──
    for sid, rec in out["s"].items():
        h = [x for x in (old_hist.get(sid) or []) if x and x[0] != iso]
        if "f" in rec: h.append([iso, rec["f"]])
        out["hist"][sid] = h[-12:]

    # ── 落地 ──
    n = len(out["s"])
    json.dump(out, open("margin.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    if not DIAG["verdict"]: DIAG["verdict"] = [f"OK({n} 檔)"]
    json.dump(DIAG, open("margin_diag.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("VERDICT:", "; ".join(DIAG["verdict"]), f"共 {n} 檔")
    if n < 100:
        print("::warning::margin 檔數過少,請檢查 margin_diag.json")

if __name__ == "__main__":
    main()
