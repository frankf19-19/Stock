"""r975:🤖 AI 交易員(台股)——取代「每週固定名單」的新規則,由 aipick.py 重班結尾呼叫
依據:2019/06~2026/10 組合層級回測(同模型、扣成本、真實成交規則):
  現行週選股+固定目標 年化 +3.5% / 最大回落 −28%;本規則 年化 +17.0% / 最大回落 −31%、每年約 41 筆
規則:
  進場——任何交易日收盤後,v2 模型勝算 ≥ 0.54(全市場約前 1%)、股價 ≥10、同產業 ≤2 檔、有空位(上限 10 檔)
        → 隔一個交易日「開盤價」買進;開盤漲停鎖死(開=高=低 且 ≥ 昨收+9.5%)或跳空 > 訊號日收盤 +3% → 不追、取消
  出場——停損:個股結構支撐(aipick.stock_levels);不設固定目標;
        漲超過進場價 10% 後啟動移動停利:最高價回落 15% 出場(停利線只上不下);
        以官方日 K 判定:最低價 ≤ 停損/停利線 → 以停損價(跳空開低則以開盤價)出場;跌停鎖死賣不掉 → 順延
  紀錄——每筆都是官方日 K 可驗證的成交;每檔名目 NT$100,000(10 檔 = 100 萬)
"""
import json, os, datetime as dt
FILE = "trader.json"; SLOTS = 20; PMIN = 0.54; MAX_SECTOR = 999; GAP_MAX = 0.03; TRAIL_ON = 1.10; TRAIL_DD = 0.85   # r996:取消「同產業最多 2 檔」(回測沒有這條)——r995 誤把註解放在行中間,後面三個參數被註解掉導致例外
GTOPK = 15; GXPCT = 0.50
SLOT_OF = {"v": 12, "g": 28}   # r1010:選股能力——樹模型年化 α +4.8%、v2 僅 +0.4% → 資金改 7:3 偏重樹模型(α +3.5%、回落 −19.6%)
PEXIT = 0.48; HMIN = 5; TRAIL_OFF = True; ADD_GAIN = 0.10; MAX_LOTS = 2
NOTIONAL = 100000; FEE_B = 0.001425; FEE_S = 0.001425 + 0.003; START = "2026-10-05"


def fetch_divs(T, sids, today, log=print):
    """r986:持股的除權息(FinMind TaiwanStockDividend)——每天重班抓一次存在 T["divs"],盤中班直接用
    → {sid: {"t": 抓取日, "ev": [[除權息交易日, 現金股利, 股票股利(元/股)], ...]}}"""
    import urllib.request, urllib.parse, os, time
    D = T.setdefault("divs", {}); tok = os.environ.get("FINMIND_TOKEN") or ""
    y0 = f"{int(today[:4]) - 1}-01-01"
    for sid in sids:
        if (D.get(sid) or {}).get("t") == today: continue
        q = {"dataset": "TaiwanStockDividend", "data_id": sid, "start_date": y0}
        if tok: q["token"] = tok
        try:
            with urllib.request.urlopen("https://api.finmindtrade.com/api/v4/data?" + urllib.parse.urlencode(q), timeout=20) as r:
                rows = (json.load(r) or {}).get("data") or []
        except Exception as e:
            log(f"trader:除權息資料 {sid} 失敗 {e}"); continue
        ev = {}
        for x in rows:
            cash = float(x.get("CashEarningsDistribution") or 0) + float(x.get("CashStatutorySurplus") or 0)
            stk = float(x.get("StockEarningsDistribution") or 0) + float(x.get("StockStatutorySurplus") or 0)
            cd = str(x.get("CashExDividendTradingDate") or "")[:10]; sd = str(x.get("StockExDividendTradingDate") or "")[:10]
            if cash > 0 and len(cd) == 10 and cd > "1990": ev.setdefault(cd, [cd, 0.0, 0.0])[1] += cash
            if stk > 0 and len(sd) == 10 and sd > "1990": ev.setdefault(sd, [sd, 0.0, 0.0])[2] += stk
        D[sid] = {"t": today, "ev": sorted(ev.values())}
        time.sleep(0.3)
    for k in list(D):
        if k not in sids: D.pop(k, None)


def apply_div(T, p, day, ev_log):
    """除權息當天:停損價跟著下調(否則除息跳空會被誤判成跌破停損),並記錄領到的現金股利/配股
    停損新價 =(原停損 − 現金股利)÷(1 + 股票股利/10)"""
    for dd, cash, stk in ((T.get("divs") or {}).get(p["id"]) or {}).get("ev") or []:
        if dd != day or dd <= p["fill"] or dd in (p.get("exd") or []): continue
        f = 1 + stk / 10
        for k in ("stop0", "stop"):
            p[k] = round((p[k] - cash) / f, 2)
        p["cash"] = round((p.get("cash") or 0) + cash * (p.get("fac") or 1), 4)   # 每「原始一股」累積領到的現金
        p["fac"] = round((p.get("fac") or 1) * f, 6)                                 # 配股後持股倍數
        p.setdefault("exd", []).append(dd)
        ev_log.append(f"{dd} 💵 {p['name']} 除權息(現金 {cash} 元" + (f"、配股 {stk} 元" if stk else "") + f")→ 停損下調為 {p['stop']}")


def _ret(p, xp):
    """含股利的報酬:(出場價×配股倍數 + 已領現金)÷ 進場價,扣手續費與證交稅"""
    val = xp * (p.get("fac") or 1) + (p.get("cash") or 0)
    return (val - xp * (p.get("fac") or 1) * FEE_S) / (p["entry"] * (1 + FEE_B)) - 1


_REV = {}
def rev3_yoy(sid, day):
    """r990:近 3 個月營收合計年增率(day 當天已公布的最新月份;M 月營收 M+1 月 11 日起才算公開;資料晚到就用最新可得月份)"""
    import gzip
    k = sid[:3] if sid[:2] == "00" else sid[:2]
    if k not in _REV:
        try: _REV[k] = json.load(gzip.open(f"archive/rev/tw/{k}.json.gz", "rt"))
        except Exception: _REV[k] = {}
    e = _REV[k].get(sid) or {}; R = dict(zip(e.get("m") or [], e.get("r") or []))
    if not R: return None
    y, m = int(day[:4]), int(day[5:7]); m -= 1 if int(day[8:10]) >= 11 else 2
    while m <= 0: m += 12; y -= 1
    lim = f"{y}-{m:02d}"; ms = sorted(x for x in R if x <= lim)
    if len(ms) < 1: return None
    ly, lm = int(ms[-1][:4]), int(ms[-1][5:7]); cur = prev = 0.0
    for i in range(3):
        mm, yy = lm - i, ly
        while mm <= 0: mm += 12; yy -= 1
        a = R.get(f"{yy}-{mm:02d}"); b = R.get(f"{yy-1}-{mm:02d}")
        if not a or not b: return None
        cur += a; prev += b
    return cur / prev - 1 if prev > 0 else None


def _rinit(A, p):
    """r989:R 倍數基礎——R = 進場價 − 初始停損(每股願意賠的錢);補上自進場以來最低/最高(算最大浮虧 MAE、最大浮盈 MFE)"""
    if not p.get("r0"):
        r0 = p["entry"] - (p.get("stop0") or p["entry"] * 0.92)
        p["r0"] = round(r0 if r0 > 0 else p["entry"] * 0.05, 4)
    if p.get("lo") is None:
        d, o = A.bars_of(p["id"]); lo = p["entry"]; hi = p.get("hi") or p["entry"]
        for dd, b in zip(d, o):
            if dd > p["fill"] and dd <= p.get("seen", dd) and b and b[2]: lo = min(lo, b[2]); hi = max(hi, b[1])
        p["lo"] = lo; p["hi"] = hi


def _rstat(p, xp=None):
    """目前(或出場)的 R、最大浮虧 MAE(R)、最大浮盈 MFE(R)"""
    r0 = p.get("r0") or p["entry"] * 0.05
    val = None if xp is None else xp * (p.get("fac") or 1) + (p.get("cash") or 0)
    return {"r": round((val - p["entry"]) / r0, 2) if val is not None else None,
            "mae": round((min(p.get("lo") or p["entry"], p["entry"]) - p["entry"]) / r0, 2),
            "mfe": round((max(p.get("hi") or p["entry"], p["entry"]) - p["entry"]) / r0, 2)}


def journal(T):
    """交易檢討:期望值、獲利因子、平均賺/賠 R、贏家的最大浮虧、賺過 1R 又虧損出場的比例"""
    tr = [t for t in T.get("trades") or [] if t.get("R") is not None]
    if not tr: return {"n": 0}
    R = [t["R"] for t in tr]; W = [x for x in R if x > 0]; L = [x for x in R if x <= 0]
    win_mae = sorted(t["mae"] for t in tr if t["R"] > 0)
    gave = [t for t in tr if t.get("mfe", 0) >= 1 and t["R"] <= 0]
    days = sorted(t.get("days") or 0 for t in tr)
    return {"n": len(tr), "exp": round(sum(R) / len(R), 2), "pf": round(sum(W) / abs(sum(L)), 2) if L and sum(L) else None,
            "avg_w": round(sum(W) / len(W), 2) if W else None, "avg_l": round(sum(L) / len(L), 2) if L else None,
            "best": max(R), "worst": min(R), "win_mae_med": win_mae[len(win_mae) // 2] if win_mae else None,
            "gave_back": round(100 * len(gave) / len(tr), 1), "days_med": days[len(days) // 2],
            "by_why": {w: {"n": sum(1 for t in tr if t["why"] == w), "avgR": round(sum(t["R"] for t in tr if t["why"] == w) / max(1, sum(1 for t in tr if t["why"] == w)), 2)} for w in sorted({t["why"] for t in tr})}}


def _prev_close(o, i):
    return o[i - 1][3] if i > 0 and o[i - 1] and o[i - 1][3] else None


def sector_trend(A, data, last):
    """r979:產業等權指數(同產業成份股每日平均報酬累乘)是否在自己的 20 日線之上——回測:只買「產業在月線上」的訊號,
    年化 +17.0% → +19.4%、最大回落 −31.5% → −27.3%;只週三進場的穩健檢查也從 +15.5% → +21.2%(回落 −36.5% → −27.1%)"""
    rets = {}
    for s in data.get("stocks", []):
        if s.get("market") != "TW" or s.get("etf") or not s.get("sector"): continue
        d, o = A.bars_of(s["id"])
        if len(d) < 41 or d[-1] != last: continue
        c = [b[3] for b in o[-41:]]
        if any(not x for x in c): continue
        r = [max(-0.11, min(0.11, c[i] / c[i - 1] - 1)) for i in range(1, 41)]
        rets.setdefault(s["sector"], []).append(r)
    out = {}
    for sec, L in rets.items():
        if len(L) < 3: continue
        m = [sum(x[i] for x in L) / len(L) for i in range(40)]
        ix = []; v = 1.0
        for x in m: v *= 1 + x; ix.append(v)
        ma20 = sum(ix[-20:]) / 20
        out[sec] = {"up": ix[-1] >= ma20, "gap": round((ix[-1] / ma20 - 1) * 100, 2), "n": len(L)}
    return out


_GBT = {}
def gbt_prob(x):
    """r1009:梯度提升樹(aipick_gbt_model.json,sklearn 匯出,純 Python 推論,與 sklearn 結果完全一致)"""
    if "m" not in _GBT:
        try: _GBT["m"] = json.load(open("aipick_gbt_model.json", encoding="utf-8"))
        except Exception: _GBT["m"] = None
    M = _GBT["m"]
    if not M or x is None: return None
    z = M["base"]
    for t in M["trees"]:
        i = 0
        while not t[i][4]:
            f, th, l, r, _, _, mg = t[i]; v = x[f]
            i = l if (mg if v != v else v <= th) else r
        z += t[i][5]
    import math
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def _sl(x): return "g" if x.get("sleeve") == "g" else "v"


_HOLI = None
def _tw_open(day):
    """r1047:台股這天有沒有開盤(週末/holidays.json 國定假日 → 沒開)。10/9 國慶休市時,盤中班拿到 MIS 的 10/8 舊報價當成今天開盤,誤買 4 檔"""
    global _HOLI
    try:
        if _HOLI is None:
            try: _HOLI = (json.load(open("holidays.json", encoding="utf-8")).get("tw") or {})
            except Exception: _HOLI = {}
        d = dt.date.fromisoformat(str(day)[:10])
        return d.weekday() < 5 and str(day)[:10] not in _HOLI
    except Exception: return True


def _heal_closed_days(A, T, ev):
    """r1047:把「休市日」記下的盤中成交退回——買進退回待買(隔一個真的交易日開盤再買)、出場撤銷(持股放回)"""
    pend_ids = {q["id"] for q in T.get("pend") or []}
    for p in list(T.get("pos") or []):
        if not p.get("rt") or p.get("ok") or _tw_open(p.get("fill", "")): continue
        T["pos"].remove(p)
        if p["id"] in pend_ids: continue
        d, o = A.bars_of(p["id"]); spx = None
        if d and p.get("sig_d") in d: spx = o[d.index(p["sig_d"])][3]
        q = {"id": p["id"], "name": p["name"], "sector": p.get("sector"), "sig_d": p.get("sig_d"), "sig_px": spx or p["entry"], "p": p.get("p"), "sleeve": p.get("sleeve")}
        if p.get("add"): q["add"] = p["add"]
        T.setdefault("pend", []).append(q); pend_ids.add(p["id"])
        ev.append(f"{p['fill']} ↩ 核對:{p['fill']} 台股休市,{p['name']} 的盤中買進是舊報價誤判 → 撤銷,改在下一個交易日開盤買")
    for t in list(T.get("trades") or []):
        if not t.get("rt") or t.get("ok") or _tw_open(t.get("xd", "")): continue
        T["trades"].remove(t)
        T.setdefault("pos", []).append({k: t[k] for k in ("id", "name", "sector", "fill", "entry", "sh", "stop0", "p", "sig_d") if k in t} |
                                       {"stop": t.get("line", t.get("stop0")), "hi": t.get("hi", t.get("entry")), "seen": t.get("fill"), "ok": 1, "sleeve": t.get("sleeve")})
        ev.append(f"{t['xd']} ↩ 核對:{t['xd']} 台股休市,{t['name']} 的盤中出場是舊報價誤判 → 撤銷")
def _cnt(T, sl): return sum(1 for p in T["pos"] if _sl(p) == sl) + sum(1 for q in T["pend"] if _sl(q) == sl)


def has_jump(o, n=260):
    """r979:近一年有單日漲跌超過 ±11.5%(台股漲跌幅上限 10%)= 未還原的除權/減資/分割(例:緯穎 9/2 7800→2610)
    → 這檔的均線、報酬等特徵全部失真,模型分數不可信,不進場"""
    for i in range(max(1, len(o) - n), len(o)):
        a, b = o[i - 1][3], o[i][3]
        if a and b and (b / a > 1.115 or b / a < 0.885): return True
    return False


def inst_cost(A, sid):
    """近 60 個交易日「法人淨買超日」的加權均價(參考用,顯示在持股卡)"""
    ch = A.chip_of(sid) or {}; d, o = A.bars_of(sid)
    px = {dd: b[3] for dd, b in zip(d[-60:], o[-60:])}
    num = den = 0.0
    for dd, f, t in zip(ch.get("d") or [], ch.get("f") or [], ch.get("t") or []):
        nb = (f or 0) + (t or 0)
        if dd in px and nb > 0: num += nb * px[dd]; den += nb
    return round(num / den, 2) if den else None


def _tk(v):
    t = 0.01 if v < 10 else 0.05 if v < 50 else 0.1 if v < 100 else 0.5 if v < 500 else 1 if v < 1000 else 5
    return round(round(v / t) * t, 2)


def pxmap(A, data, V, sc, gsc, NG, T, last):
    """r1031:每檔(最愛/持股/AI Pick 相關)算出:
       v_sell = 收盤跌到這個價,v2 勝算會低於 PEXIT(模型轉弱)
       g_sell = 收盤跌到這個價,樹模型名次會掉到後半段
       buy    = 收盤到這個價(往上或往下找最近的),會符合買進門檻(勝算 ≥ PMIN 或樹模型前 GTOPK 名)"""
    byid = {s["id"]: s for s in data.get("stocks", [])}
    try: prio = set(json.load(open("bk/_prio_users.json", encoding="utf-8")))
    except Exception: prio = set()
    ids = prio | {p["id"] for p in T.get("pos") or []} | {q["id"] for q in T.get("pend") or []} | {x["id"] for x in (T.get("watch") or [])[:25]}
    gs = sorted([g for g, _ in gsc], reverse=True)
    import bisect
    neg = [-x for x in gs]
    def grank(g, own):
        r = bisect.bisect_left(neg, -g) + 1
        return r - (1 if own is not None and own > g else 0)
    out = {}
    for sid in ids:
        s = byid.get(sid)
        if not s or s.get("market") != "TW" or s.get("etf"): continue
        d, o = A.bars_of(sid)
        if not d or d[-1] != last or len(o) < 60: continue
        b = o[-1]; px = b[3]
        try: own_g = gbt_prob(V.feats(sid, s, d, o))
        except Exception: own_g = None
        def at(p):
            o2 = o[:-1] + [[b[0], max(b[1], p), min(b[2], p), p] + list(b[4:])]
            try: pr = V.prob(sid, s, d, o2); g = gbt_prob(V.feats(sid, s, d, o2))
            except Exception: return None, None
            return pr, (grank(g, own_g) if g is not None else None)
        r = {"px": px}
        for k in range(1, 31):                       # 往下找:模型轉弱的價
            p = _tk(px * (1 - 0.01 * k)); pr, gr = at(p)
            if pr is None: break
            if "v_sell" not in r and pr < PEXIT: r["v_sell"] = p
            if "g_sell" not in r and gr and gr > NG * GXPCT: r["g_sell"] = p
            if "v_sell" in r and "g_sell" in r: break
        pr0, gr0 = at(px)
        if pr0 is not None and (pr0 >= PMIN or (gr0 and gr0 <= GTOPK)): r["buy_now"] = 1
        else:
            for k in range(1, 21):                   # 往上、往下找最近會進入買進門檻的價
                hit = None
                for p in (_tk(px * (1 + 0.01 * k)), _tk(px * (1 - 0.01 * k)) if k <= 15 else None):
                    if p is None: continue
                    pr, gr = at(p)
                    if pr is not None and (pr >= PMIN or (gr and gr <= GTOPK)): hit = p; break
                if hit: r["buy"] = hit; break
        out[sid] = r
    return out


def run(A, data, log=print):
    """A = aipick 模組(bars_of / chip_of / stock_levels / rtick / TODAY / NOW)"""
    # 狀態存在 aipick.json 的 "trader" 欄(update_data 只 commit aipick.json,不會 commit 新檔)
    try: T = (json.load(open(A.OUT, encoding="utf-8")).get("trader")) or {}
    except Exception: T = {}
    T.setdefault("ver", "r975"); T.setdefault("start", START); T.setdefault("pos", []); T.setdefault("pend", [])
    T.setdefault("trades", []); T.setdefault("log", []); T.setdefault("sig_done", "")
    T["rules"] = {"slots": SLOTS, "pmin": PMIN, "gap_max": GAP_MAX, "trail_on": TRAIL_ON, "trail_dd": TRAIL_DD, "max_sector": MAX_SECTOR, "notional": NOTIONAL}
    T["rules"]["sector_filter"] = True; T["rules"]["pexit"] = PEXIT; T["rules"]["hmin"] = HMIN; T["rules"]["trail_off"] = TRAIL_OFF; T["rules"]["add_gain"] = ADD_GAIN; T["rules"]["max_lots"] = MAX_LOTS; T["rules"]["rev3_min"] = 0; T["rules"]["gbt"] = {"topk": GTOPK, "xpct": GXPCT, "slots": SLOT_OF["g"]}; T["rules"]["slots_v"] = SLOT_OF["v"]
    T["bt"] = {"period": "2019/06~2026/10", "cagr": 17.6, "mdd": -34.0, "trades_y": 21, "win": 15.9, "avg": 6.33, "wf": {"cagr": 16.1, "mdd": -30.6, "trades_y": 37, "win": 21.7, "avg": 8.79},
               "wf_g": {"cagr": 14.0, "mdd": -20.5, "sharpe": 1.04}, "wf_mix": {"cagr": 14.9, "mdd": -19.6, "sharpe": 1.14, "worst12": None, "alpha": 3.5, "beta": 0.43, "mix": "樹 70% / v2 30%"},
               "alpha": {"v2": 0.4, "g": 4.8},
               "old": {"cagr": 3.5, "mdd": -28.3, "trades_y": 137, "win": 44.4, "avg": 0.33}}
    byid = {s["id"]: s for s in data.get("stocks", [])}
    bd, _ = A.bars_of(A.BENCH_SID); last = bd[-1] if bd else ""
    if not last: return T
    ev = []
    try: _heal_closed_days(A, T, ev)                                       # r1047:休市日的盤中成交一律撤銷
    except Exception as e: log(f"trader:休市核對例外 {e}")
    # ⓪ r977:盤中即時成交的「官方日 K 核對」——買進價必須 = 當天官方開盤;出場必須當天最低價真的 ≤ 出場價
    for p in list(T["pos"]):
        if not p.get("rt") or p.get("ok"): continue
        d, o = A.bars_of(p["id"])
        if p["fill"] not in d: continue
        b = o[d.index(p["fill"])]
        if abs(b[0] - p["entry"]) > 1e-6:
            ev.append(f"{p['fill']} ⚠ 核對:{p['name']} 盤中記錄開盤 {p['entry']} ≠ 官方 {b[0]},以官方為準"); p["entry"] = b[0]; p["hi"] = max(p["hi"], b[0])
        p["ok"] = 1
    for t in list(T["trades"]):
        if not t.get("rt") or t.get("ok"): continue
        d, o = A.bars_of(t["id"])
        if t["xd"] not in d: continue
        b = o[d.index(t["xd"])]
        if b[2] <= t["xp"] + 1e-6: t["ok"] = 1; continue
        T["trades"].remove(t)                                              # 官方最低價沒到 → 盤中誤判,撤銷出場
        T["pos"].append({k: t[k] for k in ("id", "name", "sector", "fill", "entry", "sh", "stop0", "p", "sig_d")} |
                        {"stop": t.get("line", t["stop0"]), "hi": t.get("hi", t["entry"]), "seen": d[d.index(t["xd"]) - 1] if d.index(t["xd"]) > 0 else t["fill"], "ok": 1})
        ev.append(f"{t['xd']} ↩ 核對:{t['name']} 官方最低 {b[2]} 未觸及出場價 {t['xp']},撤銷盤中出場")
    # ① 待買單:訊號日之後第一根 K 的開盤
    keep = []
    for q in T["pend"]:
        d, o = A.bars_of(q["id"])
        idx = next((i for i in range(len(d)) if d[i] > q["sig_d"]), None)
        if idx is None: keep.append(q); continue
        b = o[idx]; pc = _prev_close(o, idx); op = b[0]
        if not op or op <= 0: ev.append(f"{d[idx]} ❎ {q['name']} 當天無成交,取消"); continue
        if pc and b[1] == b[2] and op >= pc * 1.095: ev.append(f"{d[idx]} ❎ {q['name']} 開盤漲停鎖死買不到,取消"); continue
        if op > q["sig_px"] * (1 + GAP_MAX): ev.append(f"{d[idx]} ❎ {q['name']} 開盤 {op} 跳空 > +3% 不追,取消"); continue
        if sum(1 for x in T["pos"] if _sl(x) == _sl(q)) >= SLOT_OF[_sl(q)]: ev.append(f"{d[idx]} ❎ {q['name']} 已滿 {SLOTS} 檔,取消"); continue
        lo = max(0, idx - 260); oo = o[lo:idx + 1]; dd = d[lo:idx + 1]
        tr = [max(x[1] - x[2], abs(x[1] - y[3]), abs(x[2] - y[3])) for x, y in zip(oo[1:], oo[:-1])]
        a = sum(tr[-14:]) / max(1, len(tr[-14:]))
        try: _, stp, LV = A.stock_levels(dd, oo, op, a, byid.get(q["id"]))
        except Exception: stp = op * 0.92; LV = {}
        sh = int(NOTIONAL / op)
        if q.get("add"):
            b0 = [x for x in T["pos"] if x["id"] == q["id"]]
            if b0: stp = min(x["stop0"] for x in b0); LV = {"stp_src": "沿用第一筆停損"}
        T["pos"].append({"id": q["id"], "name": q["name"], "sector": q.get("sector"), "fill": d[idx], "entry": op, "sh": sh, "add": q.get("add"), "sleeve": q.get("sleeve"),
                         "stop0": round(float(stp), 2), "stop": round(float(stp), 2), "hi": op, "p": q["p"], "sig_d": q["sig_d"], "seen": d[idx],
                         "stp_src": (LV or {}).get("stp_src"), "dn_med": (LV or {}).get("dn_med")})
        ev.append(f"{d[idx]} {'➕ 加碼' if q.get('add') else '🟢 買進'} {q['name']} 開盤 {op}(停損 {round(float(stp), 2)})")
    T["pend"] = keep
    # ② 持股:逐根 K 檢查停損 / 移動停利(除權息日先調整停損)
    try: fetch_divs(T, sorted({p["id"] for p in T["pos"]}), A.iso(A.TODAY), log)
    except Exception as e: log(f"trader:除權息資料例外 {e}")
    still = []
    for p in T["pos"]:
        try: _rinit(A, p)
        except Exception: pass
        d, o = A.bars_of(p["id"]); out = None
        for i in range(len(d)):
            if d[i] <= p["seen"]: continue
            apply_div(T, p, d[i], ev)
            b = o[i]; op, h, l = b[0], b[1], b[2]; pc = _prev_close(o, i)
            locked_dn = pc and h == l and op <= pc * 0.905
            if p.get("xsig") and d[i] > p["xsig"] and op and not locked_dn:      # r984:模型預測轉弱 → 訊號隔天開盤賣
                out = (d[i], op, "model"); p["seen"] = d[i]; break
            line = p["stop"]
            if l <= line and not locked_dn:
                xp = op if op <= line else line
                why = "trail" if line > p["stop0"] else "sl"
                out = (d[i], xp, why); p["seen"] = d[i]; break
            p["hi"] = max(p["hi"], h); p["lo"] = min(p.get("lo") or p["entry"], l)
            if not TRAIL_OFF and p["hi"] >= p["entry"] * TRAIL_ON: p["stop"] = round(max(p["stop"], p["hi"] * TRAIL_DD), 2)
            p["seen"] = d[i]
        if out:
            ret = _ret(p, out[1])
            T["trades"].append({**{k: p[k] for k in ("id", "name", "sector", "fill", "entry", "sh", "stop0", "p", "sig_d")},
                                "xd": out[0], "xp": round(float(out[1]), 2), "why": out[2], "ret": round(ret * 100, 2), "hi": p["hi"]})
            T["trades"][-1]["line"] = p["stop"]
            if out[2] == "sl": p["lo"] = min(p.get("lo") or p["entry"], out[1])
            T["trades"][-1].update({**{k: v for k, v in _rstat(p, out[1]).items() if k != "r"}, "R": _rstat(p, out[1])["r"], "r0": p.get("r0"),
                                    "days": sum(1 for x in d if p["fill"] < x <= out[0])})
            ev.append(f"{out[0]} {'🔒 移動停利' if out[2] == 'trail' else '📉 模型轉弱' if out[2] == 'model' else '🛑 停損'} {p['name']} @{round(float(out[1]), 2)}({ret*100:+.2f}%)")
        else: still.append(p)
    T["pos"] = still
    # ③ 收盤決策(每個交易日一次;最新 K 全市場入庫 ≥90% 才做)
    do_sig = last >= START and T["sig_done"] < last
    if do_sig or (last >= START and (T.get("watch_d") != last or T.get("allp_d") != last)):          # r993/r1024:關注清單、每檔評分——今天已決策過也要補算
        tot = hit = 0; lo = (dt.date.fromisoformat(last) - dt.timedelta(days=10)).isoformat()
        for s in data.get("stocks", []):
            if s.get("market") != "TW" or s.get("etf"): continue
            dd, _ = A.bars_of(s["id"])
            if not dd or dd[-1] < lo: continue
            tot += 1; hit += 1 if dd[-1] >= last else 0
        if tot and hit / tot >= 0.9:
            from aipick_v2 import V2Scorer
            V = V2Scorer(A.bars_of, A.chip_of, data, mkt="TW")
            sc = []; GP = {}
            for s in data.get("stocks", []):
                if s.get("market") != "TW" or s.get("etf"): continue
                d, o = A.bars_of(s["id"])
                if not d or d[-1] != last or not o[-1][3] or o[-1][3] < 10: continue
                if has_jump(o): continue
                try: pr = V.prob(s["id"], s, d, o); gp = gbt_prob(V.feats(s["id"], s, d, o))
                except Exception: pr = gp = None
                if pr is not None: sc.append((pr, s)); GP[s["id"]] = gp
            sc.sort(key=lambda x: -x[0])
            gsc = sorted([(g, sid) for sid, g in GP.items() if g is not None], reverse=True)
            GR = {sid: i for i, (g, sid) in enumerate(gsc)}; NG = len(gsc)
            ST = sector_trend(A, data, last); T["sectors"] = ST
            held = {p["id"] for p in T["pos"]} | {q["id"] for q in T["pend"]}
            secn = {}
            for p in T["pos"] + T["pend"]: secn[p.get("sector")] = secn.get(p.get("sector"), 0) + 1
            free = (SLOT_OF["v"] - _cnt(T, "v")) if do_sig else 0; new = []
            for pr, s in sc:
                if free <= 0 or pr < PMIN: break
                if s["id"] in held or secn.get(s.get("sector"), 0) >= MAX_SECTOR: continue
                if not (ST.get(s.get("sector")) or {"up": True})["up"]: continue      # r979:產業在月線下 → 不進場
                ry = rev3_yoy(s["id"], last)                               # r990:近 3 月營收年增 < 0 → 不進場(滾動驗證 +14.3% → +16.1%)
                if ry is None or ry < 0: continue
                d, o = A.bars_of(s["id"])
                q = {"id": s["id"], "name": s.get("name"), "sector": s.get("sector"), "sig_d": last, "sig_px": o[-1][3], "p": round(pr, 4),
                     "sec_gap": (ST.get(s.get("sector")) or {}).get("gap"), "icost": inst_cost(A, s["id"]), "rev3": round(ry * 100, 1)}
                T["pend"].append(q); new.append(q); held.add(s["id"]); secn[s.get("sector")] = secn.get(s.get("sector"), 0) + 1; free -= 1
            # r1009:🌲 樹模型組(另 20 檔)——每天全市場「樹模型排名前 15」且產業在月線上、近3月營收成長 → 明天開盤買
            gnew = []
            if do_sig and GR:
                gfree = SLOT_OF["g"] - _cnt(T, "g")
                for g, sid in gsc[:GTOPK]:
                    if gfree <= 0: break
                    s1 = byid.get(sid) or {}
                    if sid in held: continue
                    if not (ST.get(s1.get("sector")) or {"up": True})["up"]: continue
                    ry = rev3_yoy(sid, last)
                    if ry is None or ry < 0: continue
                    d1, o1 = A.bars_of(sid)
                    q = {"id": sid, "name": s1.get("name"), "sector": s1.get("sector"), "sig_d": last, "sig_px": o1[-1][3], "p": round(g, 4),
                         "sleeve": "g", "grank": GR[sid] + 1, "sec_gap": (ST.get(s1.get("sector")) or {}).get("gap"), "icost": inst_cost(A, sid), "rev3": round(ry * 100, 1)}
                    T["pend"].append(q); gnew.append(q); held.add(sid); gfree -= 1
                if gnew: ev.append(f"{last} 🌲 樹模型組:明天開盤買進 " + "、".join(f"{q['name']}(第 {q['grank']} 名)" for q in gnew))
            # r1019:每檔的模型評分(驗證過的唯一選股依據)給前端卡片用:[v2 勝算, 樹模型名次]
            T["allp"] = {s["id"]: [round(pr, 4), (GR.get(s["id"], -1) + 1) or None] for pr, s in sc}; T["allp_n"] = NG; T["allp_d"] = last
            # r1031:把「模型轉弱/買進門檻」換算成價格——假設今天收盤改成某個價,重算這檔的分數(其他股票不變),找出觸發的價位
            try:
                T["pxmap"] = pxmap(A, data, V, sc, gsc, NG, T, last)
            except Exception as e: log(f"trader:價位換算例外 {e}")
            T["gtop"] = [{"id": sid, "name": (byid.get(sid) or {}).get("name"), "p": round(g, 4), "r": i + 1} for i, (g, sid) in enumerate(gsc[:20])]
            # r993:👀 關注清單——勝算最高的 25 檔(不含已持有),逐項列出卡在哪個條件,讓人知道誰快要進場
            W = []; secc = {}
            for p in T["pos"] + T["pend"]: secc[p.get("sector")] = secc.get(p.get("sector"), 0) + 1
            for pr, s in sc:
                if len(W) >= 25: break
                if s["id"] in {p["id"] for p in T["pos"]}: continue
                d1, o1 = A.bars_of(s["id"]); ry1 = rev3_yoy(s["id"], last); su = (ST.get(s.get("sector")) or {"up": True})
                why = []
                if pr < PMIN: why.append(f"勝算差 {(PMIN - pr) * 100:.1f}%")
                if not su["up"]: why.append("產業在月線下")
                if ry1 is None: why.append("缺營收資料")
                elif ry1 < 0: why.append("近3月營收衰退")
                if secc.get(s.get("sector"), 0) >= MAX_SECTOR and not any(q["id"] == s["id"] for q in T["pend"]): why.append("同產業已 2 檔")
                st_ = "明天開盤買" if any(q["id"] == s["id"] for q in T["pend"]) else ("符合但已滿" if not why else "觀察中")
                W.append({"id": s["id"], "name": s.get("name"), "sector": s.get("sector"), "p": round(pr, 4), "px": o1[-1][3] if o1 else None,
                          "sec_gap": su.get("gap"), "rev3": round(ry1 * 100, 1) if ry1 is not None else None, "why": why, "st": st_})
            T["watch"] = W; T["watch_d"] = last
            T["top"] = [{"id": s["id"], "name": s.get("name"), "p": round(pr, 4), "sector": s.get("sector"),
                         "sec_up": (ST.get(s.get("sector")) or {"up": True})["up"]} for pr, s in sc[:15]]
            for p in T["pos"]:
                try: p["icost"] = inst_cost(A, p["id"]); p["sec_gap"] = (ST.get(p.get("sector")) or {}).get("gap")
                except Exception: pass
                # r984:出場改由模型「預測」——每天收盤重算這檔的勝算(技術・法人籌碼・估值・殖利率・相對強弱 20 項),
                #       持有滿 5 個交易日後勝算跌破 0.48 → 隔天開盤賣;不再用「最高點回落」停利,也不設固定目標
                try:
                    s0 = byid.get(p["id"]) or {}; d0, o0 = A.bars_of(p["id"])
                    pr0 = V.prob(p["id"], s0, d0, o0) if d0 and d0[-1] == last else None
                    p["prob"] = round(pr0, 4) if pr0 is not None else p.get("prob")
                    hd = sum(1 for x in d0 if x > p["fill"])
                    if TRAIL_OFF: p["stop"] = p["stop0"]
                    # r1011:賣出評估資料——每天記錄分數走勢、產業、營收、法人 5 日、持有天數,前端逐檔說明「為什麼續抱/何時會賣」
                    try:
                        gr0 = GR.get(p["id"]); sc0 = round(1 - gr0 / max(1, NG), 3) if (_sl(p) == "g" and gr0 is not None) else (round(pr0, 4) if pr0 is not None else None)
                        ph = [x for x in (p.get("ph") or []) if x[0] != last]; ph.append([last, sc0]); p["ph"] = ph[-15:]
                        p["hd"] = hd; p["sec_up"] = (ST.get(p.get("sector")) or {}).get("up"); p["rev3"] = (lambda v: round(v * 100, 1) if v is not None else None)(rev3_yoy(p["id"], last))
                        ch0 = A.chip_of(p["id"]) or {}; f5 = sum(((ch0.get("f") or [])[-5:] or [0])) + sum(((ch0.get("t") or [])[-5:] or [0])); p["f5"] = round(f5)
                        c0 = o0[-1][3] if o0 else None
                        if c0: p["ma20"] = round(sum(b[3] for b in o0[-20:]) / min(20, len(o0)), 2); p["px"] = c0
                        tr_ = [max(x[1] - x[2], abs(x[1] - y[3]), abs(x[2] - y[3])) for x, y in zip(o0[-15:], o0[-16:-1])]
                        at_ = sum(tr_) / max(1, len(tr_))
                        p["atr"] = round(at_, 2); p["reclaim"] = round(p["stop0"] + at_, 2)   # r1013:跌破防守後「站回價」= 原支撐 + 0.5 ATR(停損 = 支撐 − 0.5 ATR)
                    except Exception: pass
                    if _sl(p) == "g":                                    # r1009:樹模型組——排名跌出前 50% 才賣
                        gr = GR.get(p["id"]); p["grank"] = (gr + 1) if gr is not None else None; p["gn"] = NG
                        if gr is not None and hd >= HMIN and gr > NG * GXPCT and not p.get("xsig"):
                            p["xsig"] = last; ev.append(f"{last} 📉 🌲{p['name']} 樹模型排名掉到第 {gr+1}/{NG} 名(後半),明天開盤賣出")
                    elif pr0 is not None and hd >= HMIN and pr0 < PEXIT and not p.get("xsig"):
                        p["xsig"] = last; ev.append(f"{last} 📉 {p['name']} 模型勝算降到 {pr0*100:.1f}%(< {PEXIT*100:.0f}%),明天開盤賣出")
                except Exception: pass
            # r985:加碼——第一筆帳面賺 ≥10%、模型今天仍看好(勝算 ≥ 0.54)、這檔還不到 2 筆、還有空位 → 明天開盤再買一筆
            #       回測:年化 +19.3% → +22.5%(最大回落 −33.2% → −34.8%);賣出後條件符合也會重新買回(不限次數)
            try:
                lots = {}
                for p in T["pos"]: lots.setdefault(p["id"], []).append(p)
                pend_ids = [q["id"] for q in T["pend"]]
                for sid0, L in lots.items():
                    base = min(L, key=lambda x: x["fill"])
                    if _cnt(T, _sl(base)) >= SLOT_OF[_sl(base)]: continue
                    if len(L) + pend_ids.count(sid0) >= MAX_LOTS or base.get("xsig"): continue
                    d0, o0 = A.bars_of(sid0)
                    if not d0 or d0[-1] != last: continue
                    c0 = o0[-1][3]; pr0 = base.get("prob")
                    ok_add = (GR.get(sid0, 9e9) < GTOPK) if _sl(base) == "g" else (pr0 is not None and pr0 >= PMIN)
                    if ok_add and c0 >= base["entry"] * (1 + ADD_GAIN):
                        q = {"id": sid0, "name": base["name"], "sector": base.get("sector"), "sig_d": last, "sig_px": c0, "p": pr0, "add": len(L) + 1, "sleeve": base.get("sleeve")}
                        T["pend"].append(q); pend_ids.append(sid0)
                        ev.append(f"{last} ➕ 加碼訊號 {base['name']}(帳面 {(c0/base['entry']-1)*100:+.1f}%、勝算 {pr0*100:.1f}%),明天開盤加買第 {len(L)+1} 筆")
            except Exception as ex: log(f"trader:加碼判斷例外 {ex}")
            T["n_scored"] = len(sc)
            if do_sig: T["sig_done"] = last
            if do_sig: ev.append(f"{last} 🔍 收盤掃描 {len(sc)} 檔,勝算 ≥{PMIN} 有 {sum(1 for x in sc if x[0] >= PMIN)} 檔;" +
                      ("明天開盤買進:" + "、".join(q["name"] for q in new) if new else "沒有新進場(" + ("已滿" if free <= 0 else "沒有夠強的標的") + ")"))
        else:
            log(f"trader:{last} K 入庫 {hit}/{tot} 未達 90%,本班不做收盤決策")
    for e in ev: T["log"].insert(0, e)
    T["log"] = T["log"][:300]
    tr_ = T["trades"]
    T["stats"] = {"closed": len(tr_), "win": round(100 * sum(1 for t in tr_ if t["ret"] > 0) / len(tr_), 1) if tr_ else None,
                  "avg": round(sum(t["ret"] for t in tr_) / len(tr_), 2) if tr_ else None,
                  "realized": round(sum(t["ret"] / 100 * NOTIONAL for t in tr_))}
    try:
        T["journal"] = journal(T)
        for p in T["pos"]:
            _rinit(A, p); d0, o0 = A.bars_of(p["id"]); px = o0[-1][3] if o0 else None
            if px: p.update({"R": _rstat(p, px)["r"], "mae": _rstat(p)["mae"], "mfe": _rstat(p)["mfe"]})
    except Exception as e: log(f"trader:交易檢討例外 {e}")
    # r1006:每日淨值曲線(累計損益,元)——已實現 + 持股未實現(含股利),與 006208 同期漲跌對照
    try:
        unreal = 0.0
        for p in T["pos"]:
            d0, o0 = A.bars_of(p["id"]); c0 = o0[-1][3] if o0 else None
            if c0: unreal += (c0 * (p.get("fac") or 1) + (p.get("cash") or 0) - p["entry"]) * p.get("sh", 0)
        real = sum(t["ret"] / 100 * NOTIONAL for t in T["trades"])
        e8d, e8o = A.bars_of("006208"); e8 = e8o[-1][3] if e8o and e8d and e8d[-1] == last else None
        nav = [x for x in (T.get("nav") or []) if x[0] != last]
        nav.append([last, round(real + unreal), len(T["pos"]), e8])
        T["nav"] = nav[-400:]
    except Exception as e: log(f"trader:淨值曲線例外 {e}")
    try:                                                   # r1024:📈 量價組(純量價模型,獨立模擬帳戶)
        import pvsleeve; pvsleeve.run(A, data, T, last, log)
    except Exception as e: log(f"trader:量價組例外 {e}")
    T["updated"] = A.NOW.strftime("%Y-%m-%d %H:%M"); T["last_bar"] = last
    for e in ev: log("trader:" + e)
    return T


def run_intraday(A, data, hhmm, log=print):
    """r977:盤中即時執行(盤中 5 分鐘輕量班呼叫)——
    ① 待買單:09:00 開盤一出來就以「官方開盤價」成交(開盤跳空 > +3% 取消;開盤即漲停且還鎖著 → 先等,收盤日 K 再判)
    ② 持股:真實成交價(MIS z)跌破出場線、且今天官方最低價也 ≤ 出場線 → 當下出場,記下時間
       移動停利線用今天官方最高價即時上調
    所有盤中紀錄晚上都會再用官方日 K 核對(run 的 ⓪)"""
    try: T = (json.load(open(A.OUT, encoding="utf-8")).get("trader")) or {}
    except Exception: return None
    if not T or not ("09:00" <= hhmm <= "13:30"): return T
    today = A.iso(A.TODAY); byid = {s["id"]: s for s in data.get("stocks", [])}
    if not _tw_open(today): return None                                    # r1047:台股休市 → 盤中班什麼都不做(MIS 會回前一個交易日的舊報價)
    def live(sid):
        s = byid.get(sid) or {}
        ok = s.get("pz") == 1 and str(s.get("pt") or "")[:10] == today and s.get("dhd") == today and s.get("dhl")
        return (float(s["price"]), s["dhl"]) if ok else (None, None)
    ev = []; keep = []
    for q in T.get("pend") or []:
        if q["sig_d"] >= today: keep.append(q); continue
        px, hl = live(q["id"])
        if not hl: keep.append(q); continue
        op, h, l = hl
        d, o = A.bars_of(q["id"]); pc = o[-1][3] if o and d and d[-1] < today else q["sig_px"]
        if op > q["sig_px"] * (1 + GAP_MAX) and not (h == l and op >= pc * 1.095):
            ev.append(f"{today} {hhmm} ❎ {q['name']} 開盤 {op} 跳空 > +3% 不追,取消"); continue
        if h == l and op >= pc * 1.095: keep.append(q); continue          # 漲停鎖著:收盤後日 K 判定
        if sum(1 for x in T.get("pos") or [] if _sl(x) == _sl(q)) >= SLOT_OF[_sl(q)]: ev.append(f"{today} {hhmm} ❎ {q['name']} 已滿 {SLOTS} 檔,取消"); continue
        lo = max(0, len(o) - 260); oo = o[lo:]; dd = d[lo:]
        tr = [max(x[1] - x[2], abs(x[1] - y[3]), abs(x[2] - y[3])) for x, y in zip(oo[1:], oo[:-1])]
        a = sum(tr[-14:]) / max(1, len(tr[-14:]))
        try: _, stp, LV = A.stock_levels(dd, oo, op, a, byid.get(q["id"]))
        except Exception: stp = op * 0.92; LV = {}
        if q.get("add"):
            b0 = [x for x in T.get("pos") or [] if x["id"] == q["id"]]
            if b0: stp = min(x["stop0"] for x in b0); LV = {"stp_src": "沿用第一筆停損"}
        T.setdefault("pos", []).append({"id": q["id"], "name": q["name"], "sector": q.get("sector"), "fill": today, "ft": "09:00", "entry": op, "add": q.get("add"), "sleeve": q.get("sleeve"),
                                        "sh": int(NOTIONAL / op), "stop0": round(float(stp), 2), "stop": round(float(stp), 2), "hi": op,
                                        "p": q["p"], "sig_d": q["sig_d"], "seen": today, "rt": 1,
                                        "stp_src": (LV or {}).get("stp_src"), "dn_med": (LV or {}).get("dn_med")})
        ev.append(f"{today} 09:00 {'➕ 加碼' if q.get('add') else '🟢 買進'} {q['name']} 官方開盤 {op}(停損 {round(float(stp), 2)})")
    T["pend"] = keep
    still = []
    for p in T.get("pos") or []:
        px, hl = live(p["id"])
        if px is None or p.get("seen", "") > today or (p["fill"] == today):   # 進場當天不判出場(與回測相同)
            still.append(p); continue
        op, h, l = hl
        try: apply_div(T, p, today, ev)                                    # r986:除權息日盤中先下調停損
        except Exception: pass
        if p.get("xsig") and p["xsig"] < today and op:                      # r984:模型轉弱 → 開盤賣(官方開盤價)
            ret = _ret(p, op)
            T.setdefault("trades", []).append({**{k: p.get(k) for k in ("id", "name", "sector", "fill", "entry", "sh", "stop0", "p", "sig_d")},
                                               "xd": today, "xt": "09:00", "xp": op, "why": "model", "ret": round(ret * 100, 2), "hi": p["hi"], "line": op, "rt": 1})
            try: _rinit(A, p); rs = _rstat(p, op); T["trades"][-1].update({"R": rs["r"], "mae": rs["mae"], "mfe": rs["mfe"], "r0": p.get("r0")})
            except Exception: pass
            ev.append(f"{today} 09:00 📉 模型轉弱 {p['name']} 開盤 {op}({ret*100:+.2f}%)"); continue
        hi_now = max(p["hi"], h)
        line = round(max(p["stop"], hi_now * TRAIL_DD), 2) if (not TRAIL_OFF and hi_now >= p["entry"] * TRAIL_ON) else p["stop"]
        p["line_rt"] = line
        if px <= line and l <= line:
            xp = op if op <= line else line
            why = "trail" if line > p["stop0"] else "sl"
            ret = _ret(p, xp)
            T.setdefault("trades", []).append({**{k: p[k] for k in ("id", "name", "sector", "fill", "entry", "sh", "stop0", "p", "sig_d")},
                                               "xd": today, "xt": hhmm, "xp": round(float(xp), 2), "why": why, "ret": round(ret * 100, 2), "hi": p["hi"], "line": line, "rt": 1})
            try:
                _rinit(A, p); p["lo"] = min(p.get("lo") or p["entry"], l); rs = _rstat(p, xp)
                T["trades"][-1].update({"R": rs["r"], "mae": rs["mae"], "mfe": rs["mfe"], "r0": p.get("r0")})
            except Exception: pass
            ev.append(f"{today} {hhmm} {'🔒 移動停利' if why == 'trail' else '🛑 停損'} {p['name']} @{round(float(xp), 2)}({ret*100:+.2f}%)")
            continue
        still.append(p)
    T["pos"] = still
    # r1012:盤中即時「賣出評估」——用現價當作今天收盤,重算持股的模型分數(v2 勝算、樹模型全市場排名)
    #       只做預估顯示;正式賣出仍在收盤後用官方日 K 判定(回測驗證的方式)。今日量未完整 → 量用近 20 日均量代替
    try:
        from aipick_v2 import V2Scorer
        V = V2Scorer(A.bars_of, A.chip_of, data, mkt="TW")
        def lb(sid):
            d, o = A.bars_of(sid)
            if not d: return d, o
            if d[-1] >= today: return d, o
            px, hl = live(sid)
            if px is None: return d, o
            va = sum(b[4] for b in o[-20:]) / max(1, len(o[-20:]))
            return d + [today], o + [[hl[0], max(hl[1], px), min(hl[2], px), px, va]]
        gs = {}
        for s0 in data.get("stocks", []):
            if s0.get("market") != "TW" or s0.get("etf"): continue
            d, o = lb(s0["id"])
            if not d or not o[-1][3] or o[-1][3] < 10: continue
            try: gs[s0["id"]] = gbt_prob(V.feats(s0["id"], s0, d, o))
            except Exception: pass
        order = sorted((g, k) for k, g in gs.items() if g is not None)[::-1]; RK = {k: i for i, (g, k) in enumerate(order)}; NN = len(order)
        for p in T["pos"]:
            d, o = lb(p["id"]); e = {"t": hhmm}
            try: e["prob"] = round(V.prob(p["id"], byid.get(p["id"]) or {}, d, o), 4)
            except Exception: pass
            if p["id"] in RK: e["grank"] = RK[p["id"]] + 1; e["gn"] = NN
            p["est"] = e
    except Exception as ex:
        log(f"trader:盤中評估例外 {ex}")
    try:                                                   # r1025:📈 量價組盤中(開盤成交、即時停損停利)
        import pvsleeve; pvsleeve.intraday(A, data, T, today, hhmm, live, log)
    except Exception as ex: log(f"trader:量價組盤中例外 {ex}")
    for e in ev: T.setdefault("log", []).insert(0, e); log("trader:" + e)
    T["log"] = T.get("log", [])[:300]; T["updated"] = A.NOW.strftime("%Y-%m-%d %H:%M")
    return T


def migrate(A, weeks, J, log=print):
    """r983:單一投資組合——把每週名單「目前還在場內」的持股直接移交給每日交易管理(之後只有一套買賣)
    移交後:停損沿用原本的個股結構停損;取消固定目標;自進場以來最高價已漲過 10% 的,立刻套用「最高點回落 15%」移動停利線;
    原每週名單未成交的掛單取消;已結算的歷史紀錄保持不動。"""
    T = J.get("trader") or {}
    if T.get("migrated") or A.US: return False
    bd, _ = A.bars_of(A.BENCH_SID); last = bd[-1] if bd else A.iso(A.TODAY)
    for k in ("pos", "pend", "log", "trades"): T.setdefault(k, [])
    have = {p["id"] for p in T["pos"]}; n = c = 0; ev = []
    for w in weeks:
        if w.get("bt") or w.get("status") in ("done", "skip"): continue
        for p in w.get("picks") or []:
            legs = p.get("legs") or []; cur = legs[-1] if legs else None
            if cur and not cur.get("xd"):
                cur["xfer"] = last
                if cur["id"] in have: continue
                d, o = A.bars_of(cur["id"]); hi = cur["entry"]
                for dd, b in zip(d, o):
                    if dd >= cur["fill"] and b and b[1]: hi = max(hi, b[1])
                stop0 = round(float(cur.get("stop") or cur["entry"] * 0.92), 2); stop = stop0
                if hi >= cur["entry"] * TRAIL_ON: stop = max(stop, round(hi * TRAIL_DD, 2))
                T["pos"].append({"id": cur["id"], "name": cur.get("name"), "sector": cur.get("sector"), "fill": cur["fill"], "ft": cur.get("ft"),
                                 "entry": cur["entry"], "sh": int(NOTIONAL / cur["entry"]), "stop0": stop0, "stop": stop, "hi": hi,
                                 "p": None, "sig_d": w["buy_week"], "seen": max(last, cur["fill"]), "src": "週", "wk": w["buy_week"], "ok": 1})
                have.add(cur["id"]); n += 1
                ev.append(f"{last} 🔀 移交 {cur.get('name')}(原 {w['buy_week'][5:]} 週名單,{cur['fill'][5:]} 買 {cur['entry']})→ 出場線 {stop}")
            elif not legs and not (p.get("iv") or {}).get("fill") and not p.get("_nofill"):
                p["xfer_cancel"] = last; c += 1
        w["xfer"] = last
    T["migrated"] = last
    free = max(0, SLOTS - len(T["pos"])); kept = [q for q in T["pend"] if q["id"] not in have][:free]
    if len(kept) != len(T["pend"]):
        ev.append(f"{last} ❎ 取消待買 {len(T['pend']) - len(kept)} 筆(已持有或持股已達 {SLOTS} 檔上限)")
    T["pend"] = kept
    ev.append(f"{last} 🔀 合併為單一投資組合:移交 {n} 檔持股、取消 {c} 筆每週名單未成交掛單;之後所有買賣只由每日交易規則決定")
    for e in ev: T["log"].insert(0, e); log("trader:" + e)
    J["trader"] = T
    return True
