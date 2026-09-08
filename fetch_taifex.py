"""期交所籌碼 → taifex.json
=======================
大盤擇時最缺的一塊:週乖離只看價格,這裡看「部位」。每日一份,逐日累積 250 個交易日。
  1. 三大法人臺股期貨未平倉淨額(外資/投信/自營,口)——futContractsDateDown(CSV)
  2. 全市場選擇權 P/C ratio(未平倉量比)——pcRatioDown(CSV)
  3. 大額交易人:前十大特定法人 臺股期貨 近月 淨部位——largeTraderFutQryDown(CSV)
統計:外資淨未平倉放進自己 250 日分佈的分位;P/C ratio 分位。極端值(≤10 / ≥90 分位)給標籤。
期交所提供近三年查詢;GitHub IP 通常可通。抓不到就沿用舊值,不影響其他資料。
"""
import json, os, csv, io, datetime as dt, re
import requests

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ); TODAY = NOW.date()
OUT = "taifex.json"; KEEP = 250
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Referer": "https://www.taifex.com.tw/cht/3/futContractsDate"}
BASE = "https://www.taifex.com.tw/cht/3/"


def log(*a): print(*a, flush=True)


def post_csv(path, form):
    r = requests.post(BASE + path, data=form, headers=UA, timeout=40)
    if not r.ok: raise RuntimeError(f"{path} HTTP {r.status_code}")
    raw = r.content
    for enc in ("utf-8-sig", "cp950", "big5", "utf-8"):
        try: txt = raw.decode(enc); break
        except Exception: txt = None
    if txt is None: raise RuntimeError("decode fail")
    if "<html" in txt[:500].lower(): raise RuntimeError(f"{path} 回 HTML(可能被擋)")
    return list(csv.reader(io.StringIO(txt)))


def num(x):
    try: return int(float(str(x).replace(",", "").strip()))
    except Exception: return None


def fut_institutional(d0, d1):
    """{date: {foreign, trust, dealer}} 臺股期貨 未平倉多空淨額(口)"""
    rows = post_csv("futContractsDateDown", {"queryStartDate": d0, "queryEndDate": d1, "commodityId": "TXF"})
    out = {}
    hdr = rows[0] if rows else []
    # 欄位:日期,商品名稱,身份別,多方交易口數,...,多空淨額未平倉口數(第 13 欄左右);找「未平倉」「淨額」「口數」
    ix = next((i for i, c in enumerate(hdr) if "未平倉" in c and "淨" in c and "口" in c), None)
    if ix is None: ix = 13
    for r in rows[1:]:
        if len(r) <= ix: continue
        d = r[0].strip().replace("/", "-")
        who = r[2].strip() if len(r) > 2 else ""
        v = num(r[ix])
        if v is None: continue
        k = "foreign" if "外資" in who else "trust" if "投信" in who else "dealer" if "自營" in who else None
        if not k: continue
        out.setdefault(d, {})[k] = v
    return out


def pc_ratio(d0, d1):
    """{date: {pc_oi, pc_vol}} 全市場選擇權 P/C(未平倉量比、成交量比,%)"""
    rows = post_csv("pcRatioDown", {"queryStartDate": d0, "queryEndDate": d1})
    out = {}
    hdr = rows[0] if rows else []
    io_ = next((i for i, c in enumerate(hdr) if "未平倉" in c and "比" in c), None)
    iv_ = next((i for i, c in enumerate(hdr) if "成交量" in c and "比" in c), None)
    for r in rows[1:]:
        if not r or not re.match(r"\d{4}/\d{2}/\d{2}", r[0].strip()): continue
        d = r[0].strip().replace("/", "-")
        e = out.setdefault(d, {})
        try:
            if io_ is not None: e["pc_oi"] = float(str(r[io_]).replace(",", ""))
            if iv_ is not None: e["pc_vol"] = float(str(r[iv_]).replace(",", ""))
        except Exception: pass
    return out


def large_traders(d0, d1):
    """{date: {top10_spec_net}} 臺股期貨 近月 前十大特定法人 淨部位(口)"""
    rows = post_csv("largeTraderFutQryDown", {"queryStartDate": d0, "queryEndDate": d1})
    out = {}
    for r in rows[1:]:
        if len(r) < 8: continue
        d = r[0].strip().replace("/", "-")
        name, kind = r[1].strip(), r[2].strip()
        if "臺股期貨" not in name or "近月" not in kind and "當月" not in kind: continue
        # 欄位大致:日期,契約名稱,到期月份,前五大買方(交易人),前五大買方(特定法人),前十大買方,前十大買方(特定法人),前五大賣方,前五大賣方(特定),前十大賣方,前十大賣方(特定),全市場未沖銷
        try:
            b10s = num(r[6]); s10s = num(r[10])
            if b10s is not None and s10s is not None: out.setdefault(d, {})["top10_spec_net"] = b10s - s10s
        except Exception: pass
    return out


def html_latest(path, want_name="臺股期貨"):
    """CSV 下載被擋時的備援:GET 查詢頁(HTML 表格,最新一個交易日)。回傳 (date, rows)。"""
    import re as _re
    r = requests.get(BASE + path, headers=UA, timeout=40)
    if not r.ok or "<table" not in r.text.lower(): raise RuntimeError(f"{path} HTML 無表格")
    try:
        import pandas as pd
        tables = pd.read_html(io.StringIO(r.text))
    except Exception as e:
        raise RuntimeError(f"read_html 失敗 {e}")
    m = _re.search(r"日期\s*(\d{4}/\d{2}/\d{2})", r.text)
    day = m.group(1).replace("/", "-") if m else TODAY.isoformat()
    return day, tables


def fut_inst_html():
    day, tables = html_latest("futContractsDate")
    out = {}
    for t in tables:
        t = t.copy(); t.columns = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
        if not any("身份別" in c or "身分別" in c for c in t.columns): continue
        cn = next(c for c in t.columns if "商品" in c); cw = next(c for c in t.columns if "身份別" in c or "身分別" in c)
        cols = [c for c in t.columns if "未平倉" in c and "淨" in c and "口數" in c]
        if not cols: continue
        for _, r in t.iterrows():
            if "臺股期貨" not in str(r[cn]): continue
            who = str(r[cw]); v = num(r[cols[0]])
            k = "foreign" if "外資" in who else "trust" if "投信" in who else "dealer" if "自營" in who else None
            if k and v is not None: out.setdefault(day, {})[k] = v
        if out: break
    if not out: raise RuntimeError("HTML 表格找不到臺股期貨列")
    return out


def large_html():
    day, tables = html_latest("largeTraderFutQry")
    out = {}
    for t in tables:
        t = t.copy(); t.columns = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
        flat = t.astype(str)
        for i, r in flat.iterrows():
            row = list(r.values)
            if not any("臺股期貨" in x for x in row): continue
            # 找「前十大…特定法人」買方與賣方兩個欄位:取含 "十大" 的欄位,依序 買/賣
            idx = [j for j, c in enumerate(t.columns) if "十大" in c and "特定" in c]
            if len(idx) >= 2:
                b = num(row[idx[0]]); s = num(row[idx[1]])
                if b is not None and s is not None: out[day] = {"top10_spec_net": b - s}; break
        if out: break
    if not out: raise RuntimeError("HTML 表格找不到十大特定法人")
    return out


def pct_rank(xs, v):
    xs = [x for x in xs if x is not None]
    if not xs or v is None: return None
    return round(100 * sum(1 for x in xs if x <= v) / len(xs))


def main():
    try: prev = json.load(open(OUT, encoding="utf-8"))
    except Exception: prev = {"days": {}}
    days = prev.get("days") or {}
    have = sorted(days)
    d1 = TODAY.strftime("%Y/%m/%d")
    d0 = (TODAY - dt.timedelta(days=(400 if not have else 12))).strftime("%Y/%m/%d")   # 首次抓一年多,之後補近兩週
    got = 0
    for name, fn, fb in (("三大法人期貨", fut_institutional, fut_inst_html), ("P/C ratio", pc_ratio, None), ("大額交易人", large_traders, large_html)):
        try:
            res = fn(d0, d1)
            for d, e in res.items(): days.setdefault(d, {}).update(e)
            got += len(res); log(f"  {name}:{len(res)} 天")
        except Exception as ex:
            log(f"  {name} 失敗:{ex}")
            if fb:
                try:
                    res = fb()
                    for d, e in res.items(): days.setdefault(d, {}).update(e)
                    log(f"  {name}:HTML 備援補 {list(res)[0]}")
                except Exception as ex2:
                    log(f"  {name} HTML 備援也失敗:{ex2}")
    keys = sorted(days)[-KEEP:]
    days = {k: days[k] for k in keys}
    # 統計
    F = [days[k].get("foreign") for k in keys]; P = [days[k].get("pc_oi") for k in keys]; T = [days[k].get("top10_spec_net") for k in keys]
    last = days[keys[-1]] if keys else {}
    def d5(arr):
        v = [x for x in arr if x is not None]
        return (v[-1] - v[-6]) if len(v) >= 6 else None
    stat = {"as_of": keys[-1] if keys else None, "foreign": last.get("foreign"), "foreign_pct": pct_rank(F, last.get("foreign")), "foreign_d5": d5(F),
            "trust": last.get("trust"), "dealer": last.get("dealer"),
            "pc_oi": last.get("pc_oi"), "pc_pct": pct_rank(P, last.get("pc_oi")), "pc_vol": last.get("pc_vol"),
            "top10_spec_net": last.get("top10_spec_net"), "top10_pct": pct_rank(T, last.get("top10_spec_net")), "top10_d5": d5(T),
            "days": len(keys)}
    tags = []
    if stat["foreign_pct"] is not None:
        if stat["foreign_pct"] >= 90: tags.append("外資期貨淨多在一年高檔(≥90 分位)——偏多但擁擠")
        elif stat["foreign_pct"] <= 10: tags.append("外資期貨淨空在一年低檔(≤10 分位)——極端偏空,歷史上常見反彈")
    if stat["pc_pct"] is not None:
        if stat["pc_pct"] >= 90: tags.append("P/C 未平倉比在高檔——賣權部位重,市場偏多(反向:過熱)")
        elif stat["pc_pct"] <= 10: tags.append("P/C 未平倉比在低檔——買權部位重,市場偏空(反向:恐慌)")
    if stat["top10_pct"] is not None:
        if stat["top10_pct"] >= 85: tags.append("十大特定法人近月淨多在高檔——大戶看多")
        elif stat["top10_pct"] <= 15: tags.append("十大特定法人近月淨空在低檔——大戶看空")
    stat["tags"] = tags
    res = {"u": NOW.strftime("%Y-%m-%d %H:%M"), "days": days, "stat": stat,
           "spark": {"d": keys[-60:], "foreign": F[-60:], "pc_oi": P[-60:], "top10": T[-60:]}}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"✅ {OUT}:{len(keys)} 個交易日;外資 {stat['foreign']}(分位 {stat['foreign_pct']}),P/C {stat['pc_oi']}(分位 {stat['pc_pct']}),十大特定 {stat['top10_spec_net']}")


if __name__ == "__main__":
    main()
