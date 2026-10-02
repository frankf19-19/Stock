#!/usr/bin/env python3
"""🧠 大腦・長期研究(r912)→ brain_study.json

用 archive/ 的 15 年資料(日K + 三大法人),把網站常用的訊號「倒帶」重跑一遍:
每個訊號在過去 15 年出現幾次、之後 5 / 20 個交易日漲跌如何、比同一天全市場平均好多少、
每一年是否都有效(穩定度)。大腦用這份「長期經驗」當先驗,再用實戰結果慢慢修正——
像老手:先有多年經驗,再依最近的市場微調。

訊號定義(每檔每天檢查,取「第一天觸發」避免同一波重複計算):
  inst_big_buy   法人大買:外資+投信當日淨買 > 近 60 日淨買的 2 個標準差,且為正
  inst_big_sell  法人大賣:同上,淨賣
  inst_streak3   法人開始連買:外資+投信連 3 日淨買(前一日不是)
  trust_streak3  投信開始連買:投信連 3 日淨買
  brk20          突破:收盤創 20 日新高(前一日不是)
  brk_dn_ma20    跌破月線:收盤由月線上跌到月線下
  vol_brk        量增長紅:量 > 20 日均量 2 倍且漲 > 3%
  ma_bull        多頭排列成形:5 > 20 > 60 日均線(前一日不是)
在休市日跑(資料量大),檔案小,網頁可以直接讀。
"""
import json, os, gzip, glob, statistics as st, datetime as dt

ROOT = "archive"; OUT = "brain_study.json"
NAMES = {"inst_big_buy": "法人大買", "inst_big_sell": "法人大賣", "inst_streak3": "法人開始連買(3日)",
         "trust_streak3": "投信開始連買(3日)", "brk20": "突破 20 日新高", "brk_dn_ma20": "跌破月線",
         "vol_brk": "量增長紅(2倍量、漲>3%)", "ma_bull": "多頭排列成形"}
BEAR = {"inst_big_sell", "brk_dn_ma20"}


def gz(p):
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f: return json.load(f)
    except Exception: return {}


def load_series(kind, shard):
    """把某分片所有年份的存檔接起來 → {id: {d:[..], ...}}"""
    out = {}
    for p in sorted(glob.glob(f"{ROOT}/{kind}/tw/*/{shard}.json.gz")):
        for sid, e in gz(p).items():
            o = out.setdefault(sid, {})
            for k, v in e.items(): o.setdefault(k, []).extend(v)
    return out


def main():
    shards = sorted({os.path.basename(p).split(".")[0] for p in glob.glob(f"{ROOT}/k/tw/*/*.json.gz")})
    if not shards: print("brain_study:還沒有 archive 資料"); return
    events = {k: [] for k in NAMES}          # (date, f5, f20)
    mkt = {}                                 # date → [f20 of all stocks] 用來算「贏大盤」
    n_stock = 0; first = last = None
    for sh in shards:
        K = load_series("k", sh); I = load_series("inst", sh)
        for sid, k in K.items():
            d, o = k.get("d") or [], k.get("o") or []
            n = min(len(d), len(o))
            if n < 120: continue
            n_stock += 1
            first = min(first or d[0], d[0]); last = max(last or d[n - 1], d[n - 1])
            C = [x[3] for x in o[:n]]; H = [x[1] for x in o[:n]]; V = [x[4] or 0 for x in o[:n]]
            ie = I.get(sid) or {}; imap = {}
            for j, dd in enumerate(ie.get("d") or []):
                imap[dd] = ((ie["f"][j] or 0) + (ie["t"][j] or 0), ie["t"][j] or 0)
            net = [imap.get(dd, (None, None))[0] for dd in d[:n]]; tnet = [imap.get(dd, (None, None))[1] for dd in d[:n]]
            ma = lambda i, m: sum(C[i - m + 1:i + 1]) / m
            for i in range(60, n - 20):
                if C[i] <= 0 or C[i - 1] <= 0: continue
                f5 = C[i + 5] / C[i] - 1; f20 = C[i + 20] / C[i] - 1
                mkt.setdefault(d[i], []).append(f20)
                hit = []
                if net[i] is not None:
                    w = [x for x in net[i - 60:i] if x is not None]
                    if len(w) >= 40:
                        sd = st.pstdev(w) or 1; mu = sum(w) / len(w)
                        if net[i] > 0 and net[i] > mu + 2 * sd: hit.append("inst_big_buy")
                        if net[i] < 0 and net[i] < mu - 2 * sd: hit.append("inst_big_sell")
                    if all((net[j] or 0) > 0 for j in (i, i - 1, i - 2)) and (net[i - 3] or 0) <= 0: hit.append("inst_streak3")
                if tnet[i] is not None and all((tnet[j] or 0) > 0 for j in (i, i - 1, i - 2)) and (tnet[i - 3] or 0) <= 0: hit.append("trust_streak3")
                if C[i] > max(H[i - 20:i]) and not C[i - 1] > max(H[i - 21:i - 1]): hit.append("brk20")
                m20, m20p = ma(i, 20), ma(i - 1, 20)
                if C[i] < m20 and C[i - 1] >= m20p: hit.append("brk_dn_ma20")
                av = sum(V[i - 20:i]) / 20
                if av > 0 and V[i] > 2 * av and C[i] / C[i - 1] - 1 > 0.03: hit.append("vol_brk")
                m5, m60 = ma(i, 5), ma(i, 60); m5p, m60p = ma(i - 1, 5), ma(i - 1, 60)
                if m5 > m20 > m60 and not (m5p > m20p > m60p): hit.append("ma_bull")
                for h in hit: events[h].append((d[i], f5, f20))
    mavg = {dd: st.median(v) for dd, v in mkt.items() if len(v) >= 30}      # r919:用中位數當「同日大盤」(平均值會被少數暴漲股拉高,讓每個訊號都被低估)
    res = {}
    for k, ev in events.items():
        if len(ev) < 50: continue
        bear = k in BEAR
        f5 = [e[1] for e in ev]; f20 = [e[2] for e in ev]
        ex = [e[2] - mavg[e[0]] for e in ev if e[0] in mavg]
        win = lambda v: round(100 * sum(1 for x in v if (x < 0 if bear else x > 0)) / len(v), 1)
        yr = {}
        for e in ev: yr.setdefault(e[0][:4], []).append(e)
        years = {y: {"n": len(v), "win20": win([x[2] for x in v]), "med20": round(100 * st.median([x[2] for x in v]), 2)} for y, v in sorted(yr.items()) if len(v) >= 20}
        good = sum(1 for v in years.values() if v["win20"] > 50)
        res[k] = {"name": NAMES[k], "bear": bear, "n": len(ev), "win5": win(f5), "win20": win(f20),
                  "med5": round(100 * st.median(f5), 2), "med20": round(100 * st.median(f20), 2), "avg20": round(100 * sum(f20) / len(f20), 2),
                  "excess20": round(100 * st.median(ex), 2) if ex else None,
                  "years": years, "stable": f"{good}/{len(years)}"}
    base = [x for v in mkt.values() for x in v]
    out = {"u": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"), "range": [first, last], "stocks": n_stock,
           "base": {"n": len(base), "win20": round(100 * sum(1 for x in base if x > 0) / len(base), 1) if base else None,
                    "med20": round(100 * st.median(base), 2) if base else None},
           "signals": res}
    with open(OUT, "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"🧠 長期研究:{n_stock} 檔、{first}~{last}、{len(res)} 種訊號")
    for k, r in sorted(res.items(), key=lambda kv: -(kv[1]["excess20"] or -99)):
        print(f"  {r['name']:<14} {r['n']:>7} 次 20日{'下跌' if r['bear'] else '上漲'}機率 {r['win20']}% 中位 {r['med20']}% 贏大盤 {r['excess20']}% 穩定 {r['stable']} 年")


if __name__ == "__main__":
    main()
