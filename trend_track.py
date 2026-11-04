#!/usr/bin/env python3
"""r1227:🔭 未來產業的「績效追蹤」與「未來性評分」→ trends_perf.json(永久累積)
① 績效:每個趨勢從第一次被收錄那天起,相關台股的平均漲跌 vs 大盤(0050)同期;用來驗證 AI 歸納的趨勢有沒有用。
   每個趨勢的「首日價格」只在第一次看到時寫一次,之後不改(所以不會事後美化)。
② 未來性:趨勢裡每一檔相關台股都跑 aip3.ai_future(跟 AI Pick 長期清單同一套、同一個快取 aip3_ai.json),
   45 天內不重評;每班最多評 EACH 檔(免費額度),沒評到的下一班補。
跟著 news.yml 在 fetch_trends 之後跑。用法:python trend_track.py"""
import json, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TZ = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.datetime.now(TZ).strftime("%Y-%m-%d")
OUT = "trends_perf.json"
EACH = int(os.environ.get("TREND_AI_EACH", "8"))

def log(*a): print(*a, flush=True)

def jl(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d

def close_on(bars, d):
    """d 當天或之前最近一個收盤;回 (日期, 收盤)"""
    best = None
    for dd, o in bars:
        if dd <= d: best = (dd, o[3])
        else: break
    return best

def main():
    import aip3
    T = jl("trends.json") or {}
    P = jl(OUT) or {"v": 1, "trends": {}, "scores": {}}
    mk = aip3.bars("0050")
    if not mk: log("✗ 沒有 0050 K 線,無法算大盤同期"); return
    mk_now = close_on(mk, TODAY)
    cache_f = jl("aip3_ai.json") or {"ai_cache": {}}
    cache = cache_f.setdefault("ai_cache", {})
    budget = EACH; changed_cache = False
    for t in T.get("trends") or []:
        key = t.get("key") or t.get("name"); first = t.get("first_seen") or t.get("first") or TODAY
        rec = P["trends"].setdefault(key, {"name": t.get("name"), "first": first, "stage0": t.get("stage"), "base": {}})
        rec["name"] = t.get("name"); rec["stage"] = t.get("stage"); rec["last"] = TODAY
        if "mk0" not in rec:
            m0 = close_on(mk, first)
            if m0: rec["mk0"] = m0[1]; rec["mk0_d"] = m0[0]
        rets = []
        for x in t.get("tw") or []:
            sid = x["id"]; b = aip3.bars(sid)
            if not b: continue
            if sid not in rec["base"]:
                c0 = close_on(b, first)
                if c0: rec["base"][sid] = {"n": x.get("n"), "px0": c0[1], "d0": c0[0]}
            bs = rec["base"].get(sid); cn = close_on(b, TODAY)
            if bs and cn and bs["px0"]:
                bs["px"] = cn[1]; bs["ret"] = round((cn[1] / bs["px0"] - 1) * 100, 1); rets.append(bs["ret"])
            # 未來性評分(同 AI Pick 長期清單)
            e = cache.get(sid); ok = False
            try: ok = e and e.get("score") is not None and (dt.date.fromisoformat(TODAY) - dt.date.fromisoformat(e.get("d") or "2000-01-01")).days <= aip3.AI_TTL_D
            except Exception: ok = False
            if not ok and budget > 0 and not aip3._AI["dead"]:
                p = {"id": sid, "name": x.get("n") or sid, "sector": x.get("sector") or ""}
                try:
                    if aip3.ensure_ai(p, cache, False) and p.get("ai") is not None:
                        budget -= 1; changed_cache = True; log(f"  未來性 {sid} {p.get('name')}:{p['ai']}")
                except Exception as ex: log(f"  未來性 {sid} 失敗:{ex}")
                e = cache.get(sid)
            if e and e.get("score") is not None:
                P["scores"][sid] = {"n": x.get("n"), "ai": e["score"], "d": e.get("d"), "txt": (e.get("txt") or "")[:200]}
        if rets:
            rec["avg"] = round(sum(rets) / len(rets), 1); rec["n"] = len(rets); rec["win"] = round(sum(1 for r in rets if r > 0) / len(rets) * 100)
            if rec.get("mk0") and mk_now: rec["mk"] = round((mk_now[1] / rec["mk0"] - 1) * 100, 1)
            rec["days"] = max(0, (dt.date.fromisoformat(TODAY) - dt.date.fromisoformat(rec["first"])).days)
    if changed_cache:
        cache_f["u"] = dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
        json.dump(cache_f, open("aip3_ai.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    P["u"] = dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M"); P["mk_d"] = mk_now[0] if mk_now else None
    json.dump(P, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"✅ {OUT}:{len(P['trends'])} 個趨勢、{len(P['scores'])} 檔有未來性評分")
    for k, r in P["trends"].items():
        if r.get("avg") is not None: log(f"   {r['name']}:自 {r['first']} 起 {r['n']} 檔平均 {r['avg']:+.1f}%(大盤 {r.get('mk', 0):+.1f}%),{r.get('days')} 天")

if __name__ == "__main__":
    main()
