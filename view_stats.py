"""🧭 盤勢解讀:落底清單的回測驗證(r1129)→ view_stats.json(每週跟 bottom.yml 一起重算)

盤勢解讀頁有一張「落底訊號清單」,每一項都在這裡用真實歷史資料驗證,跟落底燈號同一套方法:
  在「離一年高點跌 ≥8%」的日子裡,比較「條件成立 vs 不成立」之後 3 個月的上漲機率、中位報酬與最多再跌幅度。
  有效 = 3 個月上漲機率高 3 個百分點以上,或之後再跌少 1 個百分點以上(且上漲機率沒差超過 8);樣本要 ≥30 天、≥4 段行情。
  資料太短沒辦法回測的項目(美債殖利率、外資期貨、散戶小台)照實標「資料不足,僅供觀察」。
"""
import json, time, datetime as dt
import pandas as pd
from bottom import load_tw, load_us, fwd_frame, market_validate, win, r1, log, TZ

def items_tw(W):
    c, raw, f, mb = W["c"], W["raw"], W["f"], W["mb"]
    stk = [s for s in c.columns if not s.startswith("0")]
    P = c["0050"]
    F = (f.reindex(columns=stk).fillna(0) * raw[stk] * 1000).sum(axis=1) / 1e8
    M = (mb.reindex(columns=stk) * raw[stk] * 1000).sum(axis=1) / 1e8
    M = M.where(M > 0)
    newlow = P <= P.rolling(20).min()
    L = {
        "fbuy3": win((F > 0) & (F.shift(1) > 0) & (F.shift(2) > 0), 5),
        "mwash10": win(M <= 0.90 * M.rolling(60, min_periods=20).max(), 10),
        "mwash15": win(M <= 0.85 * M.rolling(60, min_periods=20).max(), 10),
        "ma60": P > P.rolling(60).mean(),
        "nolow": ~win(newlow, 5) & win(newlow, 20),
    }
    return P, L

def items_us(P):
    newlow = P <= P.rolling(20).min()
    return {"ma60": P > P.rolling(60).mean(), "nolow": ~win(newlow, 5) & win(newlow, 20)}

NAMES = {"fbuy3": "外資現貨連 3 天買超(近 5 天內)", "mwash10": "融資餘額從 60 日高點減少 1 成(近 10 天內)",
         "mwash15": "融資餘額從 60 日高點減少 15%(近 10 天內)", "ma60": "站回季線(60 日線)",
         "nolow": "5 天沒有再創 20 日新低(之前 20 天內有破底)"}
KIND = {k: "stop" for k in NAMES}; KIND["mwash10"] = KIND["mwash15"] = "low"

def run(D, L):
    D = D[D.index >= "2014-01-01"]; L = {k: v.reindex(D.index) for k, v in L.items()}
    r = market_validate(D, L, KIND, NAMES)
    return {o["k"]: {"name": o["name"], "pass": o["pass"], "ep": o["ep"], "on": o["on"], "off": o["off"]} for o in r["lights"]}

def main():
    t0 = time.time()
    W = load_tw()
    P, L = items_tw(W)
    D = fwd_frame(P); D["dd"] = P / P.rolling(250, min_periods=60).max() - 1
    out = {"u": dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "period": "2014~" + str(P.index[-1].year), "TW": run(D, L)}
    U = load_us()
    if "SOXX" in U["c"]:
        Ps = U["c"]["SOXX"].dropna()
        Ds = fwd_frame(Ps); Ds["dd"] = Ps / Ps.rolling(250, min_periods=60).max() - 1
        out["SOX"] = run(Ds, items_us(Ps))
    json.dump(out, open("view_stats.json", "w"), ensure_ascii=False, separators=(",", ":"))
    for m in ("TW", "SOX"):
        for k, v in (out.get(m) or {}).items():
            log(f"{m} {k:8s} {'✓' if v['pass'] else '✗'} ep{v['ep']} on {v['on']} | off {v['off']}")
    log(f"done {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
