#!/usr/bin/env python3
"""r1109 研究:大盤週乖離「什麼時候該賣」——跟現有「低檔進場回測」同一套資料(六個指數十年週線、20 週乖離、自身十年分佈分位),
反過來測高檔:進入高檔(≥90 分位)、從高檔回落、跌破 20 週線…之後 4/8/13/26 週的報酬與回檔,對照任意時點;
再測「乖離高檔賣、低檔買回」的機械策略 vs 一直抱著。輸出 logs/bias_sell_study.txt + bias_sell_study.json 給人看、不進前端。
用法:python bias_sell_study.py(在 GitHub Actions 跑,機房可通 Yahoo/FinMind)"""
import json, os, statistics as st, datetime as dt
import fetch_bias as FB

FWD = [4, 8, 13, 26]
OUT_J = "bias_sell_study.json"; OUT_T = "logs/bias_sell_study.txt"
L = []
def log(s=""): print(s, flush=True); L.append(s)


def series(sym, name, mkt, prev):
    wk = FB.fetch_weekly(sym)
    if mkt == "TW" and sym in FB.FM_IDX:
        stale = (not wk) or (dt.date.fromisoformat(wk[-1][0]) < FB.NOW.date() - dt.timedelta(days=10))
        if stale:
            w2 = FB.fetch_weekly_finmind(FB.FM_IDX[sym], start=(FB.NOW - dt.timedelta(days=3652)).strftime("%Y-%m-%d"))
            if w2: wk = w2
    if not wk: return None
    if mkt == "TW":
        ext = [tuple(e) for e in ((prev.get(sym) or {}).get("wk_ext") or [])]
        wk, _ = FB.splice(wk, ext + FB.yext_daily(sym))
    return wk


def bias_series(C, m):
    n = len(C); b = [None] * n; s = sum(C[:m])
    for i in range(m - 1, n):
        if i >= m: s += C[i] - C[i - m]
        b[i] = (C[i] / (s / m) - 1) * 100
    return b


def pct_of(hist, v):
    return 100.0 * sum(1 for x in hist if x <= v) / len(hist)


def stat(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 3: return None
    return {"n": len(xs), "win": round(100 * sum(1 for x in xs if x > 0) / len(xs)), "med": round(st.median(xs), 2),
            "avg": round(sum(xs) / len(xs), 2), "worst": round(min(xs), 2), "best": round(max(xs), 2)}


def fwd_stats(C, idxs, n):
    """事件週之後 k 週報酬;13/26 週內最深回檔(相對訊號價);13 週內「曾經比訊號價低 ≥3%」的比例(= 賣了之後有沒有更便宜的買回點)"""
    out = {}
    for k in FWD:
        out[str(k)] = stat([(C[i + k] / C[i] - 1) * 100 for i in idxs if i + k < n])
    for k in (13, 26):
        dd = [(min(C[i + 1:i + k + 1]) / C[i] - 1) * 100 for i in idxs if i + k < n]
        out[f"dd{k}"] = stat(dd)
        if dd: out[f"lower3_{k}"] = round(100 * sum(1 for x in dd if x <= -3) / len(dd))
    return out


def study(name, wk):
    C = [c for _, c in wk]; D = [d for d, _ in wk]; n = len(C)
    b = bias_series(C, 20); b10 = bias_series(C, 10); b52 = bias_series(C, 52)
    hist = [x for x in b if x is not None]; sh = sorted(hist)
    q = lambda p: sh[min(len(sh) - 1, int(len(sh) * p))]
    p10, p25, p50, p75, p90 = q(.10), q(.25), q(.50), q(.75), q(.90)
    h10 = sorted(x for x in b10 if x is not None); h52 = sorted(x for x in b52 if x is not None)
    p90_10 = h10[int(len(h10) * .9)]; p90_52 = h52[int(len(h52) * .9)] if h52 else None
    ok = lambda i: b[i] is not None and b[i - 1] is not None
    rules = {}
    rules["R1 進入高檔(20週乖離≥90分位)"] = [i for i in range(21, n) if ok(i) and b[i] >= p90 and b[i - 1] < p90]
    rules["R2 從高檔回落(曾≥90分位,跌回90分位以下)"] = [i for i in range(21, n) if ok(i) and b[i] < p90 and b[i - 1] >= p90]
    rules["R3 進入偏高(≥75分位)"] = [i for i in range(21, n) if ok(i) and b[i] >= p75 and b[i - 1] < p75]
    rules["R4 從偏高回落(跌回75分位以下)"] = [i for i in range(21, n) if ok(i) and b[i] < p75 and b[i - 1] >= p75]
    # R5:曾進高檔後,第一次跌回 75 分位以下(高檔頂部確認)
    r5 = []; armed = False
    for i in range(21, n):
        if not ok(i): continue
        if b[i] >= p90: armed = True
        elif armed and b[i] < p75: r5.append(i); armed = False
    rules["R5 高檔後首次跌回75分位以下"] = r5
    # R6:近 13 週內曾 ≥75 分位,本週跌破 20 週線(乖離由正轉負)
    rules["R6 偏高後跌破20週線"] = [i for i in range(34, n) if ok(i) and b[i] < 0 <= b[i - 1] and any(x is not None and x >= p75 for x in b[i - 13:i])]
    rules["R7 高檔連續2週(≥90分位)"] = [i for i in range(22, n) if ok(i) and b[i] >= p90 and b[i - 1] >= p90 and (b[i - 2] is None or b[i - 2] < p90)]
    rules["R8 10週乖離進入高檔(≥90分位)"] = [i for i in range(11, n) if b10[i] is not None and b10[i - 1] is not None and b10[i] >= p90_10 and b10[i - 1] < p90_10]
    if p90_52 is not None:
        rules["R9 52週乖離進入高檔(≥90分位)"] = [i for i in range(53, n) if b52[i] is not None and b52[i - 1] is not None and b52[i] >= p90_52 and b52[i - 1] < p90_52]
    # 對照:低檔進場(現有卡片)與任意時點
    rules["(對照)進入低檔(≤10分位)"] = [i for i in range(21, n) if ok(i) and b[i] <= p10 and b[i - 1] > p10]
    base = fwd_stats(C, list(range(20, n)), n)
    res = {"name": name, "weeks": n, "from": D[0], "to": D[-1], "p": {"p10": round(p10, 2), "p25": round(p25, 2), "p50": round(p50, 2), "p75": round(p75, 2), "p90": round(p90, 2)},
           "base": base, "rules": {}}
    log(f"\n══ {name}({D[0]} ~ {D[-1]},{n} 週;20 週乖離分位:p10 {p10:+.1f}% p25 {p25:+.1f}% p50 {p50:+.1f}% p75 {p75:+.1f}% p90 {p90:+.1f}%)")
    def row(lab, S):
        f = lambda k: (f"{S[k]['win']:>3}%/{S[k]['med']:+6.1f}" if S.get(k) else "   —   ")
        dd = lambda k: (f"{S[k]['med']:+6.1f}" if S.get(k) else "  —  ")
        return f"{lab:36s} n={S['4']['n'] if S.get('4') else 0:3d} | 4週 {f('4')} | 8週 {f('8')} | 13週 {f('13')} | 26週 {f('26')} | 13週內最深 {dd('dd13')} 低3%↓ {S.get('lower3_13','—')}% | 26週內最深 {dd('dd26')}"
    log(row("任意時點(基準)", base))
    for k, idxs in rules.items():
        S = fwd_stats(C, idxs, n); S["eps"] = [D[i] for i in idxs][-6:]; res["rules"][k] = S
        log(row(k, S) + f"  最近:{','.join(x[2:7] for x in S['eps'])}")
    # ── 機械策略:乖離高檔賣、低檔買回 vs 一直抱著 ──
    log("  ── 機械策略(週收盤執行,不含成本)vs 一直抱著 ──")
    bh = (C[-1] / C[20] - 1) * 100
    peak = C[20]; mdd = 0
    for x in C[20:]: peak = max(peak, x); mdd = min(mdd, (x / peak - 1) * 100)
    yrs = (n - 20) / 52
    cagr = lambda tot: ((1 + tot / 100) ** (1 / yrs) - 1) * 100
    log(f"  {'一直抱著':40s} 總報酬 {bh:+7.0f}%  年化 {cagr(bh):+5.1f}%  最大回檔 {mdd:6.1f}%  在場 100%")
    res["strategies"] = {"buy_hold": {"total": round(bh), "cagr": round(cagr(bh), 1), "mdd": round(mdd, 1)}}
    sells = {"R1 進入高檔": set(rules["R1 進入高檔(20週乖離≥90分位)"]), "R2 高檔回落": set(rules["R2 從高檔回落(曾≥90分位,跌回90分位以下)"]),
             "R4 偏高回落": set(rules["R4 從偏高回落(跌回75分位以下)"]), "R5 高檔後跌回75": set(rules["R5 高檔後首次跌回75分位以下"]),
             "R6 偏高後破20週線": set(rules["R6 偏高後跌破20週線"])}
    rebuys = {"乖離回到≤50分位": lambda i: b[i] is not None and b[i] <= p50, "乖離回到≤25分位": lambda i: b[i] is not None and b[i] <= p25,
              "乖離進入低檔≤10": lambda i: b[i] is not None and b[i] <= p10, "站回20週線上(乖離由負轉正)": lambda i: b[i] is not None and b[i - 1] is not None and b[i] > 0 >= b[i - 1]}
    for sk, sidx in sells.items():
        for rk, rf in rebuys.items():
            eq = 1.0; inm = True; peak = 1.0; mdd2 = 0; weeks_in = 0; trades = 0
            for i in range(21, n):
                r = C[i] / C[i - 1]
                if inm: eq *= r; weeks_in += 1
                peak = max(peak, eq); mdd2 = min(mdd2, (eq / peak - 1) * 100)
                if inm and i in sidx: inm = False; trades += 1
                elif (not inm) and rf(i): inm = True
            tot = (eq - 1) * 100
            res["strategies"][f"{sk} → {rk}"] = {"total": round(tot), "cagr": round(cagr(tot), 1), "mdd": round(mdd2, 1), "in_pct": round(100 * weeks_in / (n - 21)), "trades": trades}
            log(f"  {sk + ' → ' + rk:40s} 總報酬 {tot:+7.0f}%  年化 {cagr(tot):+5.1f}%  最大回檔 {mdd2:6.1f}%  在場 {100 * weeks_in / (n - 21):3.0f}%  賣出 {trades} 次")
    return res


def main():
    os.makedirs("logs", exist_ok=True)
    prev = {}
    try: prev = {x["sym"]: x for x in json.load(open("bias.json", encoding="utf-8")).get("idx", [])}
    except Exception: pass
    out = {"u": FB.NOW.strftime("%Y-%m-%d %H:%M"), "idx": {}}
    log(f"大盤週乖離「什麼時候該賣」研究 {out['u']}(勝率/中位數 = 之後 k 週報酬;13週內最深 = 訊號後 13 週內最低點相對訊號價;低3%↓ = 13 週內曾比訊號價低 3% 以上的比例)")
    for sym, name, mkt in FB.INDICES:
        wk = series(sym, name, mkt, prev)
        if not wk: log(f"{name}:抓不到"); continue
        try: out["idx"][sym] = study(name, wk)
        except Exception as e: log(f"{name}:研究失敗 {e}")
    json.dump(out, open(OUT_J, "w", encoding="utf-8"), ensure_ascii=False)
    open(OUT_T, "w", encoding="utf-8").write("\n".join(L))
    log(f"✅ {OUT_J} / {OUT_T}")


if __name__ == "__main__":
    main()
