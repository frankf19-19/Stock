#!/usr/bin/env python3
"""AI 複核獨立步驟(r943):對「買進週還沒開始」的最新名單,逐檔上網研究 + 籌碼 + 複核,寫回 aipick.json
(前 10 名的 shortlist 都做,之後 aipick.py 會依複核重排一次)。每檔約 30~60 秒,預算 AI2_BUDGET。"""
import os, sys, json, datetime as dt
os.environ.setdefault("AIPICK_LIGHT", "1")
sys.argv = [sys.argv[0]]
import aipick as A

def main():
    try: J = json.load(open(A.OUT, encoding="utf-8"))
    except Exception as e: print("review:讀不到 aipick.json", e); return
    if not A.GEMINI_KEY: print("review:未設 GEMINI_KEY,略過"); return
    data = A.load_json("data.json", {}); A._DATA_CACHE.update(data)
    weeks = [w for w in J.get("weeks") or [] if not w.get("bt") and w.get("status") in ("open",)]
    if not weeks: print("review:沒有要複核的週"); return
    w = sorted(weeks, key=lambda x: x["buy_week"])[-1]
    rev = w.setdefault("reviews", {})
    todo = [sid for sid in (w.get("shortlist") or [p["id"] for p in w["picks"]]) if sid not in rev]
    if not todo: print("review:都複核過了"); return
    byid = {s["id"]: s for s in data.get("stocks") or []}
    pick_by = {p["id"]: p for p in w["picks"]}
    n = 0
    for sid in todo[:A.AI2_BUDGET // 2]:
        s = byid.get(sid) or {}; p = pick_by.get(sid)
        try:
            d, o = A.bars_of(sid); r = A._score_one(s, d, o, w["buy_week"]) if not p else None
            meta = r[2] if r else {}
            pp = p or {"id": sid, "name": s.get("name") or sid, "sector": s.get("sector"), "buy": meta.get("buy") or s.get("price"), "target": meta.get("target") or (s.get("price") or 0) * 1.1, "stop": meta.get("stop") or (s.get("price") or 0) * 0.92, "why": r[1] if r else []}
            j = A.ai_review_pick(pp, w)
        except Exception as e:
            print("review:例外", sid, e); j = None
        if j:
            rev[sid] = j; n += 1
            if p: p["ai2"] = j
            print(f"review:{pp.get('name')} → {j.get('verdict')} / 籌碼 {j.get('chip_verdict')}:{(j.get('thesis') or '')[:50]}")
        json.dump(J, open(A.OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))   # 每檔存一次,超時也不會全丟
    print(f"review:完成 {n} 檔,待複核 {len(todo) - n} 檔")

if __name__ == "__main__":
    main()
