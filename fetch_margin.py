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
            data = t.get("data") or []
            ci = col(fields, "代號")
            if ci < 0 or not data: continue
            cf = col(fields, "融資", "今日餘額")
            cq = col(fields, "融券", "今日餘額")
            # v2 位置後備:MI_MARGN 個股表的「融資/融券」在欄群層不在欄名裡,欄名只剩 買進/賣出/今日餘額…
            #             經典版式:代號,名稱,[融資]買進,賣出,現償,前餘,今餘,限額,[融券]買進,賣出,券償,前餘,今餘,限額,資券互抵,註記
            if cf < 0 and len(fields) >= 14:
                cf, cq = 6, 12
                log("mi_margn_positional", fields=fields[:8])
            if cf < 0: 
                log("mi_margn_schema", fields=fields[:16]); continue
            for row in data:
                sid = str(row[ci]).strip()
                if not sid or not sid[0].isdigit() or len(sid) > 6: continue
                f = num(row[cf]) if cf < len(row) else 0
                rec = out["s"].setdefault(sid, {})
                rec["f"] = f
                if 0 <= cq < len(row): rec["q"] = num(row[cq])
                done += 1
        log("twse_margin", n=done)
        if not done: DIAG["verdict"].append("TWSE_MARGIN_EMPTY(表頭已寫入 diag)")
    except Exception as e:
        log("twse_margin_fail", e=str(e)[:150]); DIAG["verdict"].append("TWSE_MARGIN_FAIL")

    # ── ② 上市 借券賣出(TWT93U:融券與借券賣出)──
    try:
        j = get(f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={ds}&response=json")
        tables = j.get("tables") or ([j] if j.get("data") else [])
        done = 0
        for t in tables:
            fields = t.get("fields") or []
            data = t.get("data") or []
            ci = col(fields, "代號")
            if ci < 0 or not data: continue
            cb = col(fields, "借券", "餘額")
            if cb < 0: cb = col(fields, "借券賣出", "當日餘額")
            # v2 位置後備:代號,名稱,[融券]前餘,賣出,買進,現券,今餘,限額,[借券賣出]前餘,當日賣出,當日還券,當日調整,當日餘額,限額,備註
            if cb < 0 and len(fields) >= 13:
                cb = 12
                log("twt93u_positional", fields=fields[:8])
            if cb < 0:
                log("twt93u_schema", fields=fields[:16]); continue
            for row in data:
                sid = str(row[ci]).strip()
                if not sid or not sid[0].isdigit() or len(sid) > 6: continue
                if cb < len(row): out["s"].setdefault(sid, {})["b"] = num(row[cb]) // 1000   # v3:TWT93U 單位是「股」,換成張
                done += 1
        log("twse_borrow", n=done)
    except Exception as e:
        log("twse_borrow_fail", e=str(e)[:150]); DIAG["verdict"].append("TWSE_BORROW_FAIL")

    # ── ③ 上市 當沖(v4:不猜欄位名——自己掃鍵名 + 驗證值非全零)──
    # v3 事故:openapi 回了 1,232 筆但 dt 全是 0(猜的 TradeVolume 鍵名不存在),
    #          數量對、內容空,是典型假成功。v4 改為:①動態找鍵 ②抓完檢查非零筆數,
    #          全零就當失敗換下一個候選 ③無論成敗都把實際鍵名寫進 diag。
    dt_cands = [
        ("oapi",  "https://openapi.twse.com.tw/v1/exchangeReport/TWTB4U"),
        ("rwd",   f"https://www.twse.com.tw/rwd/zh/afterTrading/TWTB4U?date={ds}&selectType=All&response=json"),
        ("legacy",f"https://www.twse.com.tw/exchangeReport/TWTB4U?date={ds}&selectType=All&response=json"),
    ]
    def pick_key(keys, must, avoid=()):
        for k in keys:
            ks = str(k)
            if any(m in ks for m in must) and not any(av in ks for av in avoid):
                return k
        return None
    done = 0
    for tag, u in dt_cands:
        got = {}
        try:
            j = get(u)
            if isinstance(j, list) and j and isinstance(j[0], dict):
                keys = list(j[0].keys())
                log("twtb4u_keys", tag=tag, keys=keys[:12])
                ck = pick_key(keys, ("Code", "代號")) or keys[0]
                vk = (pick_key(keys, ("沖銷",), avoid=("金額",))
                      or pick_key(keys, ("DayTrad", "DayTrading"), avoid=("Amount", "Value"))
                      or pick_key(keys, ("Volume", "股數"), avoid=("Amount", "Value", "金額")))
                if not vk:
                    log("twtb4u_no_volkey", tag=tag, keys=keys[:12]); continue
                log("twtb4u_pick", tag=tag, code=str(ck), vol=str(vk))
                for row in j:
                    sid = str(row.get(ck, "")).strip()
                    if not sid or not sid[0].isdigit() or len(sid) > 6: continue
                    got[sid] = num(row.get(vk, 0)) // 1000
            else:
                tables = j.get("tables") or ([j] if j.get("data") else [])
                for t in tables:
                    fields = t.get("fields") or []
                    data = t.get("data") or []
                    if not fields or not data: continue
                    log("twtb4u_fields", tag=tag, fields=[str(x) for x in fields][:12])
                    ci = col(fields, "代號")
                    cd = col(fields, "沖銷", "股數")
                    if cd < 0: cd = col(fields, "當沖", "股數")
                    if ci < 0 or cd < 0: continue
                    for row in data:
                        sid = str(row[ci]).strip()
                        if not sid or not sid[0].isdigit() or len(sid) > 6: continue
                        if cd < len(row): got[sid] = num(row[cd]) // 1000
            nz = len([1 for v in got.values() if v > 0])
            if got and nz == 0:
                log("twtb4u_all_zero", tag=tag, n=len(got)); DIAG["verdict"].append(f"DT_ALL_ZERO({tag})"); continue
            if nz:
                for sid, v in got.items(): out["s"].setdefault(sid, {})["dt"] = v
                done = nz
                log("twse_daytrade_ok", tag=tag, n=len(got), nonzero=nz); break
            log("twse_daytrade_empty", tag=tag)
        except Exception as e:
            head = ""
            try:
                req = rq.Request(u, headers={"User-Agent": UA})
                head = rq.urlopen(req, timeout=15).read(160).decode("utf-8", "ignore")
            except Exception: pass
            log("twse_daytrade_fail", tag=tag, e=str(e)[:100], head=head[:120])
    if not done: DIAG["verdict"].append("TWSE_DT_FAIL(各候選鍵名/回應已寫入 diag)")
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

    # ── 落地(v5:抓不到就別覆蓋)──
    # 事故:8/31 17:20 手動觸發,當時收盤資料尚未發布(21:00 後才有),三段全空,
    #       舊版照樣把空的 out 寫進 margin.json → 2,219 檔資料與累積的歷史全被清空。
    #       新規:本次無任何個股資料時,保留舊檔不動,只更新 diag。
    n = len(out["s"])
    if n == 0 and os.path.exists("margin.json"):
        log("keep_old_file", reason="本次零筆,保留既有 margin.json 不覆蓋")
        DIAG["verdict"].append("NO_DATA_KEEP_OLD(未覆蓋舊檔)")
    else:
        json.dump(out, open("margin.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    if not DIAG["verdict"]: DIAG["verdict"] = [f"OK({n} 檔)"]
    json.dump(DIAG, open("margin_diag.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("VERDICT:", "; ".join(DIAG["verdict"]), f"共 {n} 檔")
    if n < 100:
        print("::warning::margin 檔數過少,請檢查 margin_diag.json")

if __name__ == "__main__":
    main()
