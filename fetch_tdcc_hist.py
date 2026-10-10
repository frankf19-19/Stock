"""r1056:集保股權分散表多年歷史(FinMind Sponsor:TaiwanStockHoldingSharesPer,每檔一次、2012 起)
→ archive/tdcc_hist.json.gz:{"u":..,"s":{sid:{"d":[週],"b4":[≥400張%],"b10":[≥1000張%],"r5":[≤5張%],"p":[總人數]}}}
用途:驗證「大戶進場」(400 張大戶週增)與散戶持股變化——之前只有半年集保資料,無法回測。"""
import os, json, gzip, time, re, requests, datetime as dt
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
OUT = "archive/tdcc_hist.json.gz"
def log(*a): print(*a, flush=True)
def fm(sid):
    for k in range(6):
        r = requests.get("https://api.finmindtrade.com/api/v4/data", params={"dataset": "TaiwanStockHoldingSharesPer", "data_id": sid, "start_date": "2012-01-01", "token": TOKEN}, timeout=90)
        try: j = r.json()
        except Exception: j = {}
        if r.status_code == 200 and (j.get("status") in (200, None) or j.get("msg") == "success"): return j.get("data") or []
        m = str(j.get("msg") or r.text)[:120]
        if r.status_code == 402 or "upper limit" in m: log(f"  額度滿,等 2 分鐘:{m}"); time.sleep(120); continue
        if "level" in m: raise SystemExit(f"權限不足:{m}")
        time.sleep(3)
    return None
def lo_hi(s):
    s = str(s).replace(",", "")
    if "total" in s.lower(): return "T", None
    n = [int(x) for x in re.findall(r"\d+", s)]
    if "more" in s.lower() or "以上" in s: return (n[0] if n else None), 10**12
    if len(n) >= 2: return n[0], n[1]
    return None, None
def main():
    t0 = time.time(); budget = int(os.environ.get("TDCC_BUDGET_SEC", "6000"))
    try: H = json.load(gzip.open(OUT, "rt"))
    except Exception: H = {"s": {}}
    S = H.setdefault("s", {})
    d = json.load(open("data.json", encoding="utf-8"))
    ids = sorted(s["id"] for s in d["stocks"] if s.get("market") == "TW" and str(s["id"]).isdigit() and len(str(s["id"])) == 4)
    todo = [i for i in ids if i not in S]
    log(f"集保歷史:共 {len(ids)} 檔,已有 {len(S)},待抓 {len(todo)}")
    n = 0
    for sid in todo:
        if time.time() - t0 > budget: log("時間到,下次接著"); break
        rows = fm(sid)
        if rows is None: continue
        W = {}
        for r in rows:
            wk = str(r.get("date"))[:10]; lo, hi = lo_hi(r.get("HoldingSharesLevel"))
            w = W.setdefault(wk, {"b4": 0.0, "b10": 0.0, "r5": 0.0, "p": 0})
            pc = float(r.get("percent") or 0)
            if lo == "T": w["p"] = int(r.get("people") or 0); continue
            if lo is None: continue
            if lo >= 400001: w["b4"] += pc
            if lo >= 1000001: w["b10"] += pc
            if hi is not None and hi <= 5000: w["r5"] += pc
        ks = sorted(W)
        S[sid] = {"d": ks, "b4": [round(W[k]["b4"], 2) for k in ks], "b10": [round(W[k]["b10"], 2) for k in ks],
                  "r5": [round(W[k]["r5"], 2) for k in ks], "p": [W[k]["p"] for k in ks]}
        n += 1; time.sleep(0.7)
        if n % 200 == 0:
            H["u"] = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"); os.makedirs("archive", exist_ok=True)
            with gzip.open(OUT, "wt", encoding="utf-8") as f: json.dump(H, f, separators=(",", ":"))
            log(f"  進度 {n}/{len(todo)}({int(time.time()-t0)}s)")
    H["u"] = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    os.makedirs("archive", exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f: json.dump(H, f, separators=(",", ":"))
    log(f"完成:本次 {n} 檔,共 {len(S)} 檔")
if __name__ == "__main__": main()
