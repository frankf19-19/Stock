"""主動式 ETF 選股能力評估 → etf_edge.json
========================================
問題:「哪些主動式 ETF 買了之後,股票比較會漲?」

作法(事件研究法):
  1. 事件 = 某檔 ETF 在相鄰兩個申報日之間,對某一成分股的持有張數變化。
       new  首次買入(昨天沒有、今天有)
       add  加碼(張數增加,且幅度超過雜訊門檻)
       cut  減碼(張數減少)
       out  完全出清
  2. 進場日 = 「你實際看得到這筆申報的隔一個交易日」收盤。
       MoneyDJ 申報常延遲 1~3 個交易日,若直接從申報日起算就是偷看未來。
       快照有記錄抓取日(fd)就用它,沒有就退回「申報日 + LAG 個交易日」。
  3. 前瞻報酬 = 進場日收盤 → +5 / +10 / +20 個交易日收盤。
  4. 超額報酬 = 個股報酬 − 當日基準。
       基準 = 當天被任一主動式 ETF 持有的所有個股的「中位數報酬」。
       沒有指數序列可用,而且這個基準問的問題更精準:
       「這檔 ETF 買的,有沒有比同類 ETF 會買的股票更好?」
  5. 每檔 ETF 分別統計 add/new 與 cut/out 的勝率與平均超額。
       cut 是對照組:如果加碼和減碼都「贏」,那只是大盤在漲,不是選股能力。

輸出 etf_edge.json:
  {"u":產生時間,"lag":假設延遲,"days":快照天數,"n":事件總數,
   "bench":"held-median",
   "etf":[{"id","name","add":{"n",h5/h10/h20:{"win","exc","med"}},"cut":{...}}, ...]}

注意:樣本數少於 MIN_N 的一律標記 thin=true,前端要顯示「樣本不足」而不是當成結論。
"""
import json, os, glob, statistics as st, datetime as dt

HIST_DIR = "e"
OUT = "etf_edge.json"
HORIZONS = [5, 10, 20]      # 前瞻交易日
LAG = 2                     # 沒有抓取日時,假設申報延遲幾個交易日才看得到
MIN_LOT = 1                 # 張數變化門檻(絕對值)
MIN_PCT = 0.05              # 張數變化門檻(相對於原持股)
MIN_N = 20                  # 低於此樣本數視為不足,只列不下結論


def log(*a): print(*a, flush=True)


def shard_key(sid):
    t = str(sid)
    return t[:3] if t[:2] == "00" else t[:2]


_SH = {}
def closes_of(sid):
    """回傳 {日期: 收盤價};讀 k/tw*.json 分片。"""
    k = shard_key(sid)
    if k not in _SH:
        try:
            with open(f"k/tw{k}.json", encoding="utf-8") as f: _SH[k] = json.load(f)
        except Exception:
            _SH[k] = {}
    e = _SH[k].get(sid)
    if not e: return {}
    d, o = e.get("d") or [], e.get("o") or []
    n = min(len(d), len(o))
    return {d[i]: o[i][3] for i in range(n) if len(o[i]) >= 4 and o[i][3]}


def load_hist():
    out = {}
    for p in sorted(glob.glob(os.path.join(HIST_DIR, "*.json"))):
        try:
            J = json.load(open(p, encoding="utf-8"))
            if J.get("d") and J.get("s"): out[J.get("id") or os.path.basename(p)[:-5]] = J
        except Exception:
            pass
    return out


def build_events(hist):
    """把相鄰兩個申報日的持股相減,展開成事件清單。"""
    ev = []
    for eid, J in hist.items():
        ds, fds = J["d"], (J.get("fd") or [])
        for i in range(1, len(ds)):
            seen = fds[i] if i < len(fds) and fds[i] else None      # 抓取日(有記錄才用)
            for sym, series in J["s"].items():
                if i >= len(series): continue
                a, b = series[i - 1], series[i]
                sh0 = (a or [None, 0])[1] or 0
                sh1 = (b or [None, 0])[1] or 0
                if a is None and b is None: continue
                if not sh0 and not sh1: continue
                d_sh = sh1 - sh0
                if a is None or not sh0:
                    kind = "new"
                elif b is None or not sh1:
                    kind = "out"
                elif d_sh > 0:
                    kind = "add"
                elif d_sh < 0:
                    kind = "cut"
                else:
                    continue
                if kind in ("add", "cut") and abs(d_sh) < max(MIN_LOT * 1000, sh0 * MIN_PCT):
                    continue                                        # 幅度太小,視為雜訊
                ev.append({"etf": eid, "sym": sym, "date": ds[i], "seen": seen,
                           "kind": kind, "dsh": int(round(d_sh / 1000))})
    return ev


def main():
    hist = load_hist()
    if not hist:
        log(f"沒有 {HIST_DIR}/ 快照,尚無法評估(每個交易日累積一筆)"); return
    days = sorted({d for J in hist.values() for d in J["d"]})
    log(f"主動式 ETF {len(hist)} 檔,快照 {len(days)} 個申報日({days[0]}~{days[-1]})")

    ev = build_events(hist)
    log(f"展開事件 {len(ev)} 筆")

    # 交易日曆:用台積電的 K 當基準
    cal = sorted(closes_of("2330"))
    pos = {d: i for i, d in enumerate(cal)}
    held = {sym for J in hist.values() for sym in J["s"]}      # 基準池 = 曾被任一主動式 ETF 持有的個股
    px = {}                                                    # 個股收盤快取
    for sym in held | {e["sym"] for e in ev}:
        c = closes_of(sym)
        if c: px[sym] = c

    def entry_idx(e):
        """可行動日:看得到的那天之後第一個交易日。"""
        base = e["seen"] or e["date"]
        i = None
        for d in cal:
            if d > base: i = pos[d]; break
        if i is None: return None
        if not e["seen"]: i += LAG - 1                          # 沒抓取日 → 補上假設延遲
        return i if 0 <= i < len(cal) else None

    # 先算每一筆的個股報酬,再用「當日全體持股中位數」當基準
    raw = []
    for e in ev:
        i = entry_idx(e)
        if i is None: continue
        c = px.get(e["sym"])
        if not c: continue
        d0 = cal[i]
        p0 = c.get(d0)
        if not p0: continue
        rr = {}
        for H in HORIZONS:
            j = i + H
            if j >= len(cal): continue
            p1 = c.get(cal[j])
            if p1: rr[H] = (p1 / p0 - 1) * 100
        if rr: raw.append({**e, "i": i, "ret": rr})

    # 基準:同一個進場日,全體「被主動式 ETF 持有的個股」的中位數前瞻報酬。
    # 用事件股當基準是錯的——事件本來就少,而且會被自己拉動。
    bench = {H: {} for H in HORIZONS}
    for i in sorted({r["i"] for r in raw}):
        d0 = cal[i]
        for H in HORIZONS:
            j = i + H
            if j >= len(cal): continue
            d1 = cal[j]
            xs = []
            for sym in held:
                c = px.get(sym)
                if not c: continue
                p0, p1 = c.get(d0), c.get(d1)
                if p0 and p1: xs.append((p1 / p0 - 1) * 100)
            if len(xs) >= 5: bench[H][i] = st.median(xs)

    def agg(rows, H):
        xs = [r["ret"][H] - bench[H][r["i"]] for r in rows
              if H in r["ret"] and r["i"] in bench[H]]
        if not xs: return None
        return {"n": len(xs), "win": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 1),
                "exc": round(sum(xs) / len(xs), 2), "med": round(st.median(xs), 2)}

    out = []
    for eid, J in hist.items():
        rows = [r for r in raw if r["etf"] == eid]
        buy = [r for r in rows if r["kind"] in ("add", "new")]
        sell = [r for r in rows if r["kind"] in ("cut", "out")]
        rec = {"id": eid, "name": (J.get("nm") or {}).get(eid) or eid,
               "add": {str(H): agg(buy, H) for H in HORIZONS},
               "cut": {str(H): agg(sell, H) for H in HORIZONS},
               "n_add": len(buy), "n_cut": len(sell)}
        rec["thin"] = len(buy) < MIN_N
        out.append(rec)
    out.sort(key=lambda r: -((r["add"].get("20") or {}).get("exc") or
                             (r["add"].get("10") or {}).get("exc") or
                             (r["add"].get("5") or {}).get("exc") or -999))

    res = {"u": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "lag": LAG, "min_n": MIN_N,
           "days": len(days), "span": [days[0], days[-1]], "n": len(ev), "scored": len(raw),
           "bench": "held-median", "horizons": HORIZONS, "etf": out}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))

    ready = [r for r in out if not r["thin"]]
    log(f"✅ 寫出 {OUT}:{len(out)} 檔 ETF,可評分事件 {len(raw)}/{len(ev)} 筆,"
        f"樣本足夠({MIN_N}+)的有 {len(ready)} 檔")
    if len(days) < 2:
        log("   目前只有 1 個申報日 → 還算不出任何事件;每個交易日累積一筆,"
            "約 1 個月可看 +5 日初步結果、2~3 個月才有結論。")
    for r in ready[:5]:
        a = r["add"].get("20") or r["add"].get("5") or {}
        log(f"   {r['id']} {r['name']}:加碼 {r['n_add']} 次,勝率 {a.get('win')}%,平均超額 {a.get('exc')}%")


if __name__ == "__main__":
    main()
