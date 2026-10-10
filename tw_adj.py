"""r1008:台股除權息還原因子(FinMind TaiwanStockDividendResult:除權息前收盤 before_price、參考價 after_price)
→ archive/adj_tw.json.gz:{"updated":..,"s":{"2330":[["2024-06-13",0.9967],...]}}
還原方式:某除權息日之前的所有價格 × (after/before),即可得到含息報酬的連續價格。每檔一個請求,增量更新(只補最近 400 天)。"""
import json, gzip, os, time, datetime, urllib.request, urllib.parse
OUT = "archive/adj_tw.json.gz"
def fm(params):
    tok = os.environ.get("FINMIND_TOKEN") or ""
    if tok: params["token"] = tok
    with urllib.request.urlopen("https://api.finmindtrade.com/api/v4/data?" + urllib.parse.urlencode(params), timeout=30) as r:
        j = json.load(r)
    if j.get("status") not in (200, None) and j.get("msg") != "success": raise RuntimeError(j.get("msg"))
    return j.get("data") or []
def main(budget_sec=1500, log=print):
    t0 = time.time()
    try: H = json.load(gzip.open(OUT, "rt"))
    except Exception: H = {"s": {}, "done": {}}
    try: ids = [s["id"] for s in json.load(open("data.json", encoding="utf-8"))["stocks"] if s.get("market") == "TW"]
    except Exception: log("tw_adj:沒有 data.json"); return
    S = H.setdefault("s", {}); done = H.setdefault("done", {}); today = datetime.date.today().isoformat(); n = 0
    for sid in ids:
        if time.time() - t0 > budget_sec: log("tw_adj:時間到,下次接著抓"); break
        if done.get(sid) == today: continue
        start = "2012-01-01" if sid not in done else (datetime.date.today() - datetime.timedelta(days=400)).isoformat()
        try: rows = fm({"dataset": "TaiwanStockDividendResult", "data_id": sid, "start_date": start})
        except Exception as e: log(f"tw_adj:{sid} 失敗 {e}"); time.sleep(2); continue
        ev = {d: f for d, f in (S.get(sid) or [])}
        for r in rows:
            b, a, d = r.get("before_price"), r.get("after_price"), str(r.get("date") or "")[:10]
            try: b, a = float(b), float(a)
            except Exception: continue
            if b > 0 and a > 0 and 0.2 < a / b <= 1.0 and len(d) == 10: ev[d] = round(a / b, 6)
        S[sid] = sorted([[d, f] for d, f in ev.items()]); done[sid] = today; n += 1
        time.sleep(0.12)
    H["updated"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    os.makedirs("archive", exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f: json.dump(H, f, separators=(",", ":"))
    log(f"tw_adj:本次 {n} 檔,共 {len(S)} 檔有資料,{int(time.time()-t0)} 秒")
    write_1y(H)
def write_1y(H=None):
    """r1055:網站用的「近 400 天除權息因子」小檔 adj1y.json(📏 離 52 週高要用還原價,不然除息後會看起來離高點比較遠)"""
    if H is None:
        try: H = json.load(gzip.open(OUT, "rt"))
        except Exception: return
    cut = (datetime.date.today() - datetime.timedelta(days=400)).isoformat()
    s = {sid: [[d, f] for d, f in v if d >= cut] for sid, v in (H.get("s") or {}).items()}
    s = {k: v for k, v in s.items() if v}
    with open("adj1y.json", "w", encoding="utf-8") as f: json.dump({"u": H.get("updated"), "s": s}, f, separators=(",", ":"))
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "1y": write_1y()
    else: main()
