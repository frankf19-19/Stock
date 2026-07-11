"""ETF 精準殖利率彙整 → dy.json
口徑:過去 365 天「實際配息事件」加總 ÷ 現價。
比 Yahoo 的殖利率欄位可靠(該欄位常混入配本金/過期資料;事件流是逐筆除息紀錄)。
排程:每週一 08:50 台北(dy.yml);台股與美股 ETF 都算。"""
import json, os, sys, time
import requests

UA = {"User-Agent": "Mozilla/5.0 (dy-digest; personal dashboard)"}
OUT = "dy.json"
YEAR = 365 * 86400

def log(*a): print(*a, flush=True)

def etf_ids():
    with open("data.json", encoding="utf-8") as f:
        data = json.load(f)
    return [s["id"] for s in data.get("stocks", []) if s.get("etf")]

def chart(sym):
    r = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
        params={"range": "1y", "interval": "1mo", "events": "div"},
        headers=UA, timeout=15)
    if not r.ok:
        return None
    j = r.json()
    res = (j.get("chart") or {}).get("result")
    return res[0] if res else None

def calc_dy(etf_id):
    """回傳 (dy%, 次數, 最近除息ts, 使用的symbol) 或 None"""
    if etf_id[0].isdigit():
        syms = [f"{etf_id}.TW", f"{etf_id}.TWO"]
    else:
        syms = [etf_id]
    for sym in syms:
        try:
            c = chart(sym)
        except Exception:
            c = None
        if not c:
            continue
        price = ((c.get("meta") or {}).get("regularMarketPrice"))
        if not price:
            continue
        divs = ((c.get("events") or {}).get("dividends") or {})
        now = time.time()
        hits = [(d.get("amount", 0), d.get("date", 0)) for d in divs.values()
                if d.get("date", 0) >= now - YEAR and d.get("amount", 0) > 0]
        total = sum(a for a, _ in hits)
        if total <= 0:
            return {"dy": 0.0, "n": 0, "last": "", "sym": sym}   # 一年沒配息:誠實回 0
        dy = round(total / price * 100, 2)
        last = max(t for _, t in hits)
        return {"dy": dy, "n": len(hits),
                "last": time.strftime("%Y-%m-%d", time.localtime(last)), "sym": sym}
    return None

def main():
    ids = etf_ids()
    log(f"ETF 共 {len(ids)} 檔,開始彙整近一年配息事件…")
    out, ok, skip = {}, 0, 0
    for i, eid in enumerate(ids):
        r = calc_dy(eid)
        if r:
            out[eid] = {"dy": r["dy"], "n": r["n"], "last": r["last"]}
            ok += 1
            if r["dy"] > 0:
                log(f"  {eid}: {r['dy']}%({r['n']} 次,最近 {r['last']})")
        else:
            skip += 1
        time.sleep(0.35)
        if (i + 1) % 50 == 0:
            log(f"  …進度 {i+1}/{len(ids)}")
    out["_meta"] = {"gen": time.strftime("%Y-%m-%d %H:%M"), "ok": ok, "skip": skip,
                    "note": "近365天實配加總/現價;0=一年未配息"}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    log(f"完成:dy.json({ok} 檔成功、{skip} 檔無資料)")
    if ok == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
