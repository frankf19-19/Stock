#!/usr/bin/env python3
"""K研所 · 🤖 AI Pick 三期制(r1092)——短期 / 中期 / 長期 各 5 檔,台股、美股 → aip3.json
研究與驗證:專案文件「AI_Pick三期制研究_2026-10-14」。規則與回測一致,實戰逐日追蹤,紀錄永久保留。

台股
  🏃 短期(2~3 週):每週最後一個交易日收盤選「近 52 週高 × 強勢訊號」綜合分最高 5 檔(扣除持有中),
       下個交易日開盤買,最多持 15 個交易日(第 15 天收盤出場),不設停損停利。
       回測 2016~2026(含成本):年化 +31.8%、最大回落 −37%、最差年 −25%。訊號 5/10/20 天贏大盤 +0.5/+1.1/+1.5%,14 年全正。
  🌊 中期(波段):量價籌碼模型(主力組同一套)排名前 5 補進空位,下個交易日開盤買;掉出前 200 名 → 隔天開盤賣,不設停利停損。
       回測 2016~2026(含成本):年化 +40.8%、最大回落 −37%、最差年 +9.9%、11 年全正,每年約 39 筆。
  🏦 長期(有未來性的成長股):每季第一個交易日選:成交值前 40% + 近 3 月營收年增 10~100%(穩定成長、不是暴衝)+ 連 6 個月營收年增為正
       + 當月營收創 13 個月新高 + 本益比 10~35 + 離 52 週高 ≤15% + 站上年線 → 綜合(6 月營收年增、ROE、離高、成交值)最高 5 檔,持有到下一季。
       回測 2013~2026:半年比大盤 +13.3%(14 年中 9 年)、一年 +21.9%;季換股年化 +36%、最大回落 −24%、最差年 −9%。候選少(平均 8 檔),不足 5 檔就留空。
美股(限制:只有目前 S&P 500 成分股,有倖存者偏差)
  🏃 短期:現有每週模型(walk-forward 驗證,回測 25 週勝率 54%、平均 +1.6%)最新一週前 5 名,成交/出場跟 aipick_us.json 一致。
  🌊 中期(參考・高波動):跌深低接——第一天離 60 日高跌 ≥25% → 隔天開盤買,+20% 停利 / −15% 停損 / 最多 60 天;5 個槽位,沒機會就空著。
       每筆贏隨機 +1.9%(14/14 年),但 5 檔組合回落 −48%、2022 年 −39%。
  🏦 長期(弱驗證):年線上、成交值前 20 的龍頭裡,近一年營收成長最高 5 檔,每季檢視。一年比大盤 +15.8%(10 年中 6 年);純龍頭版 +6.7%(13 年中 10 年)。
"""
import json, os, glob, datetime as dt

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
OUT = "aip3.json"
VER = "r1092"
K = 5


def log(*a): print(*a, flush=True)


def load(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d


DATA = load("data.json", {}) or {}
STK = {s["id"]: s for s in DATA.get("stocks") or []}
HOL = load("holidays.json", {}) or {}
ADJ = (load("adj1y.json", {}) or {}).get("s") or {}


def shard_key(sid):
    t = str(sid); return t[:3] if t[:2] == "00" else t[:2]


_SH = {}
def bars(sid, us=False):
    """[(日期, [o,h,l,c,v]), ...] 升冪(台股除權息還原:adj1y 因子)"""
    k = (str(sid)[0].lower() if us else shard_key(sid))
    p = f"k/us_{k}.json" if us else f"k/tw{k}.json"
    if p not in _SH: _SH[p] = load(p, {}) or {}
    e = _SH[p].get(sid)
    if not e or not isinstance(e.get("d"), list): return []
    d, o = e["d"], e["o"]; n = min(len(d), len(o))
    rows = [(d[i], list(o[i])) for i in range(n) if o[i] and len(o[i]) >= 4 and o[i][3]]
    if not us and ADJ.get(sid):
        for ex, f in ADJ[sid]:
            for r in rows:
                if r[0] < ex:
                    for j in range(4): r[1][j] = r[1][j] * f
    return rows


def raw_bars(sid, us=False):
    """未還原(實際成交價,成交/出場用)"""
    k = (str(sid)[0].lower() if us else shard_key(sid))
    p = f"k/us_{k}.json" if us else f"k/tw{k}.json"
    if p not in _SH: _SH[p] = load(p, {}) or {}
    e = _SH[p].get(sid)
    if not e or not isinstance(e.get("d"), list): return []
    d, o = e["d"], e["o"]; n = min(len(d), len(o))
    return [(d[i], o[i]) for i in range(n) if o[i] and len(o[i]) >= 4 and o[i][3]]


_C = {}
def chips(sid):
    k = shard_key(sid); p = f"c/tw{k}.json"
    if p not in _C: _C[p] = load(p, {}) or {}
    return _C[p].get(sid) or {}


def last_day(us=False):
    sid = "SPY" if us else "2330"
    b = raw_bars(sid, us)
    return b[-1][0] if b else None


def trading(d, us=False):
    H = HOL.get("us" if us else "tw") or {}
    x = dt.date.fromisoformat(d)
    return x.weekday() < 5 and d not in H


def next_td(d, us=False):
    x = dt.date.fromisoformat(d)
    for _ in range(10):
        x += dt.timedelta(days=1)
        if trading(x.isoformat(), us): return x.isoformat()
    return None


def week_last(d, us=False):
    """d 是不是這週最後一個交易日"""
    x = dt.date.fromisoformat(d)
    for i in range(1, 5):
        y = x + dt.timedelta(days=i)
        if y.weekday() >= 5: break
        if trading(y.isoformat(), us): return False
    return True


def q_first(d, us=False):
    """d 是不是這一季第一個交易日"""
    x = dt.date.fromisoformat(d)
    if x.month not in (1, 4, 7, 10): return False
    y = x
    while True:
        y -= dt.timedelta(days=1)
        if y.month != x.month: return True
        if trading(y.isoformat(), us): return False


def sma(v, n, i):
    if i + 1 < n: return None
    return sum(v[i + 1 - n:i + 1]) / n


# ═══════════════ 選股 ═══════════════
def tw_short_candidates(day):
    """近 52 週高 × 強勢訊號綜合分(與回測 h3_short3 相同)"""
    out = []
    for sid, s in STK.items():
        if s.get("market") == "US" or s.get("etf"): continue
        B = bars(sid)
        if len(B) < 130 or B[-1][0] != day: continue
        o = [b[1] for b in B]; C = [x[3] for x in o]; H = [x[1] for x in o]; L = [x[2] for x in o]; V = [x[4] if len(x) > 4 else 0 for x in o]
        i = len(C) - 1
        liq = sum(C[j] * V[j] for j in range(i - 19, i + 1)) / 20
        if liq < 2e4: continue
        hi250 = max(H[max(0, i - 249):i + 1]); dh = C[i] / hi250 - 1
        if dh < -0.10: continue
        phi = max(H[max(0, i - 250):i]); new52 = C[i] > phi and i >= 200
        h20 = max(H[i - 20:i]); v5 = sum(V[i - 4:i + 1]) / 5; v20b = sum(V[i - 24:i - 4]) / 20 if i >= 24 else 0
        brk20 = C[i] > h20 and v5 > v20b
        brk55 = C[i] > max(H[i - 55:i])
        # RSI14
        g = l = 0.0; ag = al = None
        for j in range(1, i + 1):
            d1 = C[j] - C[j - 1]; gg = max(d1, 0); ll = max(-d1, 0)
            if ag is None: ag, al = gg, ll
            else: ag = ag + (gg - ag) / 14; al = al + (ll - al) / 14
        rsi = 100 - 100 / (1 + ag / al) if al else 100
        # KD(9)
        Kv = 50.0; Ks = []
        for j in range(i - 30, i + 1):
            lo9 = min(L[j - 8:j + 1]); hi9 = max(H[j - 8:j + 1]); rsv = (C[j] - lo9) / (hi9 - lo9) * 100 if hi9 > lo9 else 50
            Kv = Kv + (rsv - Kv) / 3; Ks.append(Kv)
        kd3 = len(Ks) >= 3 and all(x >= 80 for x in Ks[-3:])
        m20 = sma(C, 20, i); m60 = sma(C, 60, i); bull = bool(m20 and m60 and C[i] > m20 > m60)
        rv1 = V[i] / (sum(V[i - 20:i]) / 20) if sum(V[i - 20:i]) else 0; big = rv1 >= 2 and C[i] / C[i - 1] - 1 >= 0.03
        obv = 0.0; obvs = []
        for j in range(1, i + 1):
            obv += (1 if C[j] > C[j - 1] else -1 if C[j] < C[j - 1] else 0) * V[j]; obvs.append(obv)
        obvHi = len(obvs) >= 60 and obvs[-1] >= max(obvs[-60:])
        ch = chips(sid); cd = ch.get("d") or []; t = ch.get("t") or []; f = ch.get("f") or []
        tb = fb = 0.0
        if cd and cd[-1] == day and len(t) >= 5:
            vol5 = sum(V[i - 4:i + 1]) or 1; tb = sum(t[-5:]) / vol5; fb = sum(f[-5:]) / vol5
        sc = new52 * 2 + brk20 + brk55 + (rsi >= 70) + kd3 + big + obvHi + (tb >= 0.03) * 2 + (fb >= 0.05) + bull
        if sc < 4: continue
        why = [w for w, ok in [("創 52 週新高", new52), ("帶量突破 20 日高", brk20), ("突破 55 日高", brk55), ("RSI ≥70", rsi >= 70), ("KD 高檔鈍化", kd3),
                               ("爆量長紅", big), ("OBV 新高", obvHi), ("投信 5 日買超", tb >= 0.03), ("外資 5 日買超", fb >= 0.05), ("均線多頭", bull)] if ok]
        out.append({"id": sid, "name": s.get("name"), "sector": s.get("sector"), "sc": int(sc), "tb": round(tb, 4), "r5": round(C[i] / C[i - 5] - 1, 4),
                    "dh": round(dh * 100, 1), "px": C[i], "why": why})
    out.sort(key=lambda x: (-x["sc"], -x["tb"], x["r5"]))
    return out


def tw_long_candidates(day):
    out = []; rows = []
    for sid, s in STK.items():
        if s.get("market") == "US" or s.get("etf"): continue
        B = bars(sid)
        if len(B) < 245 or B[-1][0] != day: continue
        o = [b[1] for b in B]; C = [x[3] for x in o]; H = [x[1] for x in o]; V = [x[4] if len(x) > 4 else 0 for x in o]; i = len(C) - 1
        liq = sum(C[j] * V[j] for j in range(i - 19, i + 1)) / 20
        if liq < 3e4: continue
        pe = s.get("pe"); pb = s.get("pb"); dy = ((s.get("dv") or {}).get("y"))
        ch = chips(sid); ry_all = ch.get("ry") or []; ra_all = ch.get("ra") or []; rm_all = ch.get("rm") or []
        ry3 = [x for x in ry_all[-3:] if x is not None]; ry6 = [x for x in ry_all[-6:] if x is not None]
        yoy3 = sum(ry3) / len(ry3) if len(ry3) == 3 else None; yoy6 = sum(ry6) / len(ry6) if len(ry6) == 6 else None
        pos6 = len(ry6) == 6 and all(x > 0 for x in ry6)
        ra13 = [x for x in ra_all[-13:] if x is not None]; rev13hi = len(ra13) >= 13 and ra13[-1] >= max(ra13)
        roe = (pb / pe) if (pe and pb and pe > 0 and pb > 0) else None
        dh = C[i] / max(H[max(0, i - 249):i + 1]) - 1; m240 = sma(C, 240, i)
        rows.append(dict(id=sid, name=s.get("name"), sector=s.get("sector"), liq=liq, pe=pe, dy=dy, roe=roe, yoy3=yoy3, yoy6=yoy6, pos6=pos6, rev13hi=rev13hi,
                         rm=rm_all[-1] if rm_all else None, dh=dh, up=bool(m240 and C[i] > m240), px=C[i]))
    rows.sort(key=lambda r: -r["liq"]); cut = int(len(rows) * 0.4); big = rows[:cut]
    # 百分位排名(在成交值前 40% 的池子裡)
    def prk(key):
        vals = sorted(r[key] for r in big if r.get(key) is not None); n = len(vals)
        return {r["id"]: (sum(1 for v in vals if v <= r[key]) / n if (r.get(key) is not None and n) else 0.0) for r in big}
    R = {k: prk(k) for k in ("yoy6", "roe", "dh", "liq")}
    for r in big:
        if r["pe"] and 10 <= r["pe"] <= 35 and r["yoy3"] is not None and 10 <= r["yoy3"] <= 100 and r["pos6"] and r["rev13hi"] and r["dh"] >= -0.15 and r["up"]:
            r["comp"] = sum(R[k][r["id"]] for k in ("yoy6", "roe", "dh", "liq")) / 4
            r["why"] = [f"近 3 月營收年增 {r['yoy3']:+.0f}%", f"連 6 個月營收成長({r['rm']} 創 13 個月新高)", f"本益比 {r['pe']:.1f}" + (f"・ROE 約 {r['roe']*100:.0f}%" if r["roe"] else ""),
                        f"離 52 週高 {r['dh']*100:.1f}%", "站上年線", "成交值前 40%"]
            out.append(r)
    out.sort(key=lambda r: -r["comp"])
    return out


def tw_mid_candidates():
    pv = ((load("aipick.json", {}) or {}).get("trader") or {}).get("pv") or {}
    ra = pv.get("rank_all") or {}; d = pv.get("rank_d")
    top = sorted(((v[0], sid) for sid, v in ra.items() if v and v[0] <= K), key=lambda x: x[0])
    return d, ra, [{"id": sid, "name": (STK.get(sid) or {}).get("name"), "sector": (STK.get(sid) or {}).get("sector"), "rank": rk, "why": [f"量價籌碼模型第 {rk} 名"]} for rk, sid in top]


def is_etf_name(s):
    n = str(s.get("name") or "") + " " + str(s.get("sector") or "")
    return any(k in n for k in ("ETF", "SPDR", "Invesco", "iShares", "Vanguard", "指數", "標普", "那斯達克100", "道瓊"))


def pick_div(cands, n, held_secs=None, cap=2):
    """同產業最多 cap 檔(短期、長期清單用;中期照模型排名不加限制)"""
    cnt = dict(held_secs or {}); out = []
    for c in cands:
        sec = c.get("sector") or ""
        if cnt.get(sec, 0) >= cap: continue
        out.append(c); cnt[sec] = cnt.get(sec, 0) + 1
        if len(out) >= n: break
    return out


def us_long_candidates(day):
    rows = []
    for sid, s in STK.items():
        if s.get("market") != "US" or s.get("etf") or is_etf_name(s): continue
        B = bars(sid, True)
        if len(B) < 245 or B[-1][0] != day: continue
        o = [b[1] for b in B]; C = [x[3] for x in o]; V = [x[4] if len(x) > 4 else 0 for x in o]; i = len(C) - 1
        liq = sum(C[j] * V[j] for j in range(i - 19, i + 1)) / 20; m240 = sma(C, 240, i)
        if m240 and C[i] > m240: rows.append(dict(id=sid, name=s.get("name"), sector=s.get("sector"), liq=liq, px=C[i]))
    rows.sort(key=lambda r: -r["liq"]); lead = rows[:20]
    UF = ((load("usf.json", {}) or {}).get("s")) or {}
    out = []
    for r in lead:
        f = UF.get(r["id"]) or {}; q = f.get("q") or []; rev = f.get("rev") or []
        g = None
        if q and rev and rev[-1]:
            last = q[-1]; want = f"{int(last[:2]) - 1:02d}{last[2:]}"
            if want in q and rev[q.index(want)]: g = rev[-1] / rev[q.index(want)] - 1
            elif len([x for x in rev if x]) >= 8:
                v = [x for x in rev if x]; g = sum(v[-4:]) / sum(v[-8:-4]) - 1
        if g is None: continue
        r["g"] = g; r["why"] = [f"近一年營收成長 {g*100:+.0f}%", "年線上的成交值前 20 龍頭", f"20 日均成交值 {r['liq']/1e8:.0f} 億美元"]
        out.append(r)
    out.sort(key=lambda r: -r["g"]); return out


def us_dip_candidates(day):
    out = []
    for sid, s in STK.items():
        if s.get("market") != "US": continue
        B = bars(sid, True)
        if len(B) < 70 or B[-1][0] != day: continue
        o = [b[1] for b in B]; C = [x[3] for x in o]; H = [x[1] for x in o]; V = [x[4] if len(x) > 4 else 0 for x in o]; i = len(C) - 1
        liq = sum(C[j] * V[j] for j in range(i - 19, i + 1)) / 20
        if liq < 2e7: continue
        dd = C[i] / max(H[i - 59:i + 1]) - 1; dd1 = C[i - 1] / max(H[i - 60:i]) - 1
        if dd <= -0.25 and dd1 > -0.25:
            out.append(dict(id=sid, name=s.get("name"), sector=s.get("sector"), liq=liq, px=C[i], why=[f"今天第一天離 60 日高 {dd*100:.0f}%", "停利 +20% / 停損 −15% / 最多 60 天"]))
    out.sort(key=lambda r: -r["liq"]); return out


# ═══════════════ 槽位引擎 ═══════════════
def new_tier(rule, val, note=""):
    return {"rule": rule, "val": val, "note": note, "slots": [], "hist": [], "upd": None, "sel_d": None}


def slot(c, day, extra=None):
    x = {"id": c["id"], "name": c.get("name"), "sector": c.get("sector"), "sel_d": day, "sel_px": c.get("px"), "fill_d": None, "entry": None,
         "last": None, "last_d": None, "ret": None, "hi": None, "lo": None, "days": 0, "why": c.get("why") or [], "st": "pend"}
    if extra: x.update(extra)
    return x


def fill_and_track(T, us, tp=None, sl=None, hold_max=None, exit_close_on=None):
    """成交(選股日之後第一個交易日開盤)+ 逐日更新 + 固定規則出場。exit_close_on: {sid: 'close'} 今天收盤出場的名單"""
    exit_close_on = exit_close_on or {}
    keep = []
    for p in T["slots"]:
        B = raw_bars(p["id"], us)
        if not B: keep.append(p); continue
        if not p["fill_d"]:
            nxt = [b for b in B if b[0] > p["sel_d"]]
            if not nxt: keep.append(p); continue
            d0, o0 = nxt[0]
            if not us and o0[0] <= 0: keep.append(p); continue
            p["fill_d"], p["entry"], p["st"] = d0, round(o0[0], 2), "hold"; p["hi"], p["lo"] = o0[1], o0[2]
        held = [b for b in B if b[0] >= p["fill_d"]]
        if not held: keep.append(p); continue
        xd = xp = xw = None
        for n, (d, o) in enumerate(held, 1):
            p["hi"] = max(p["hi"] or 0, o[1]); p["lo"] = min(p["lo"] or 1e18, o[2])
            if True:
                if sl and o[2] <= p["entry"] * (1 - sl) and n > 0: xd, xp, xw = d, round(min(o[0], p["entry"] * (1 - sl)), 2), "sl"; break
                if tp and o[1] >= p["entry"] * (1 + tp): xd, xp, xw = d, round(max(o[0], p["entry"] * (1 + tp)), 2), "tp"; break
            if exit_close_on.get(p["id"]) == d: xd, xp, xw = d, round(o[3], 2), exit_close_on.get("_why", "rule"); break
            if p.get("x_open") and d > p["x_open"]: xd, xp, xw = d, round(o[0], 2), p.get("x_why", "rank"); break
            if hold_max and n >= hold_max: xd, xp, xw = d, round(o[3], 2), "time"; break
            p["last"], p["last_d"], p["days"] = round(o[3], 2), d, n
        if xd:
            p.update(xd=xd, xp=xp, xw=xw, ret=round((xp / p["entry"] - 1) * 100, 2), st="done", last=xp, last_d=xd, days=n)
            T["hist"].append(p); T["hist"] = T["hist"][-400:]
        else:
            p["ret"] = round((p["last"] / p["entry"] - 1) * 100, 2) if p["last"] and p["entry"] else None
            keep.append(p)
    T["slots"] = keep


def perf(T):
    H = T["hist"]; r = [h["ret"] for h in H if h.get("ret") is not None]
    T["perf"] = {"n": len(r), "win": round(100 * sum(1 for x in r if x > 0) / len(r)) if r else None, "avg": round(sum(r) / len(r), 2) if r else None,
                 "sum": round(sum(r), 2) if r else None, "open": len(T["slots"]), "open_avg": (lambda v: round(sum(v) / len(v), 2) if v else None)([p["ret"] for p in T["slots"] if p.get("ret") is not None])}


def main():
    J = load(OUT, {}) or {}
    tw = J.get("tw") or {}; us = J.get("us") or {}
    tw.setdefault("short", new_tier("每週最後一個交易日收盤選 5 檔(近 52 週高 × 強勢訊號);下個交易日開盤買,最多持 15 個交易日,不設停損停利",
                                     "回測 2016~2026 含成本:年化 +31.8%、最大回落 −37%、最差年 −25%;訊號 5/10/20 天贏大盤 +0.5/+1.1/+1.5%,14 年全正", "⚠ 強勢股集中,波動大於中期"))
    tw.setdefault("mid", new_tier("量價籌碼模型前 5 名補進空位,下個交易日開盤買;掉出前 200 名 → 隔天開盤賣,不設停利停損",
                                   "回測 2016~2026 含成本:年化 +40.8%、最大回落 −37%、最差年 +9.9%、11 年全正,每年約 39 筆", "✅ 三個清單裡最穩"))
    tw.setdefault("long", new_tier("每季第一個交易日:成交值前 40% + 近 3 月營收年增 10~100% + 連 6 個月營收成長 + 當月營收創 13 個月新高 + 本益比 10~35 + 離 52 週高 ≤15% + 站上年線 → 綜合(成長、ROE、離高、成交值)最高 5 檔,持有到下一季;不足 5 檔就留空",
                                    "回測 2013~2026:半年比大盤 +13.3%(14 年中 9 年)、一年 +21.9%;季換股年化 +36%、最大回落 −24%、最差年 −9%。候選平均只有 8 檔", "✅ 有未來性:營收持續創高的成長股"))
    us.setdefault("short", new_tier("每週模型(14 年資料、每週 walk-forward)最新一週前 5 名;成交/出場與美股 AI Pick 一致",
                                     "回測 25 週:勝率 54%、平均 +1.6%;實戰自 2026-09-28", "✅ 已驗證"))
    us.setdefault("mid", new_tier("跌深低接:第一天離 60 日高跌 ≥25% → 隔天開盤買;停利 +20% / 停損 −15% / 最多 60 天;5 個槽位,沒機會就空著",
                                   "每筆贏隨機 +1.9%(14/14 年);但 5 檔組合回測年化 +17%、最大回落 −48%、2022 年 −39%", "⚠ 參考・高波動(資料只有現在的成分股,有倖存者偏差)"))
    us.setdefault("long", new_tier("每季第一個交易日:年線上、成交值前 20 的龍頭裡,近一年營收成長最高 5 檔,持有到下一季",
                                    "回測 2014~2026:一年比大盤 +15.8%(10 年中 6 年);純龍頭版 +6.7%(13 年中 10 年)。季換股年化 +26%、回落 −35%", "🟡 弱驗證:資料短、倖存者偏差"))
    twd = last_day(); usd = last_day(True)
    log(f"aip3:台股最後交易日 {twd}、美股 {usd}")
    # ── 台股 短期 ──
    T = tw["short"]
    fill_and_track(T, False, hold_max=15)
    if twd and (week_last(twd) or not T["sel_d"]) and T["sel_d"] != twd:
        held = {p["id"] for p in T["slots"]}
        if len(T["slots"]) < K:
            cand = [c for c in tw_short_candidates(twd) if c["id"] not in held]
            secs = {}
            for p in T["slots"]: secs[p.get("sector") or ""] = secs.get(p.get("sector") or "", 0) + 1
            add = pick_div(cand, K - len(T["slots"]), secs)
            for c in add: T["slots"].append(slot(c, twd))
            log(f"  短期:候選 {len(cand)},補進 {len(add)} 檔(同產業最多 2 檔)")
        T["sel_d"] = twd
    # ── 台股 中期 ──
    T = tw["mid"]
    rd, ra, top = tw_mid_candidates()
    if rd and twd and rd == twd:
        for p in T["slots"]:
            if p["fill_d"] and p["fill_d"] < twd and not p.get("x_open"):
                rk = (ra.get(p["id"]) or [9999])[0]
                if rk > 200: p["x_open"], p["x_why"] = twd, "rank"; log(f"  中期:{p['name']} 掉到第 {rk} 名 → 隔天開盤賣")
        fill_and_track(T, False)
        held = {p["id"] for p in T["slots"]}; sold_today = {h["id"] for h in T["hist"] if h.get("xd") == twd}
        for c in top:
            if len(T["slots"]) >= K: break
            if c["id"] in held or c["id"] in sold_today: continue
            T["slots"].append(slot(c, twd, {"sel_px": (STK.get(c["id"]) or {}).get("price")})); held.add(c["id"])
        T["sel_d"] = twd
    else:
        fill_and_track(T, False); log(f"  中期:量價排名日 {rd} 與 K 線 {twd} 不同,今天不換股")
    # ── 台股 長期 ──
    T = tw["long"]
    if twd and (q_first(twd) or not T["sel_d"]) and T["sel_d"] != twd:
        cand = tw_long_candidates(twd); pick = pick_div(cand, K); ids = {c["id"] for c in pick}
        fill_and_track(T, False, exit_close_on={**{p["id"]: twd for p in T["slots"] if p["id"] not in ids and p["fill_d"]}, "_why": "quarter"})
        held = {p["id"] for p in T["slots"]}
        for c in pick:
            if c["id"] not in held: T["slots"].append(slot(c, twd))
        T["sel_d"] = twd; T["cand_n"] = len(cand)
        log(f"  長期:候選 {len(cand)} → {[c['name'] for c in pick]}")
    else:
        fill_and_track(T, False)
    # ── 美股 短期(鏡射每週模型)──
    T = us["short"]
    AU = load("aipick_us.json", {}) or {}
    live = [w for w in (AU.get("weeks") or []) if not w.get("bt") and w.get("status") != "skip"]
    if live:
        w = live[-1]; picks = sorted(w.get("picks") or [], key=lambda p: -(p.get("score") or 0))[:K]
        T["slots"] = []
        for p in picks:
            legs = p.get("legs") or []; L = legs[-1] if legs else None
            T["slots"].append({"id": p["id"], "name": p.get("name"), "sector": p.get("sector"), "sel_d": w.get("ref_day"), "sel_px": p.get("ref_close"),
                               "fill_d": L["fill"] if L else None, "entry": L["entry"] if L else None, "last": L.get("last") if L else None, "last_d": L.get("last_day") if L else None,
                               "ret": L.get("ret") if L else None, "days": L.get("hold") if L else 0, "why": (p.get("why") or [])[:3] + [f"買價 ${p.get('buy')}・目標 ${p.get('target')}・停損 ${p.get('stop')}"],
                               "st": "done" if (L and L.get("xd")) else ("hold" if L else ("nofill" if p.get("result") == "nofill" else "pend")),
                               "xd": L.get("xd") if L else None, "xp": L.get("xp") if L else None, "xw": L.get("xw") if L else None, "cur": L["id"] if L else None})
        T["sel_d"] = w.get("buy_week"); T["week"] = w.get("buy_week")
        r = [L["ret"] for ww in live for p in (ww.get("picks") or []) for L in (p.get("legs") or []) if L.get("xd") and L.get("ret") is not None]
        op = [L["ret"] for ww in live for p in (ww.get("picks") or []) for L in (p.get("legs") or [])[-1:] if not L.get("xd") and L.get("ret") is not None]
        T["perf"] = {"n": len(r), "win": round(100 * sum(1 for x in r if x > 0) / len(r)) if r else None, "avg": round(sum(r) / len(r), 2) if r else None,
                     "sum": round(sum(r), 2) if r else None, "open": len(op), "open_avg": round(sum(op) / len(op), 2) if op else None, "src": "aipick_us"}
    # ── 美股 中期 跌深低接 ──
    T = us["mid"]
    fill_and_track(T, True, tp=0.20, sl=0.15, hold_max=60)
    if usd and T["sel_d"] != usd:
        held = {p["id"] for p in T["slots"]}
        if len(T["slots"]) < K:
            cand = [c for c in us_dip_candidates(usd) if c["id"] not in held]
            for c in cand[:K - len(T["slots"])]: T["slots"].append(slot(c, usd))
            log(f"  美股跌深:觸發 {len(cand)},補進 {min(len(cand), K - len(held))} 檔")
        T["sel_d"] = usd
    # ── 美股 長期 ──
    T = us["long"]
    if usd and (q_first(usd, True) or not T["sel_d"]) and T["sel_d"] != usd:
        cand = us_long_candidates(usd); pick = pick_div(cand, K); ids = {c["id"] for c in pick}
        fill_and_track(T, True, exit_close_on={**{p["id"]: usd for p in T["slots"] if p["id"] not in ids and p["fill_d"]}, "_why": "quarter"})
        held = {p["id"] for p in T["slots"]}
        for c in pick:
            if c["id"] not in held: T["slots"].append(slot(c, usd))
        T["sel_d"] = usd; T["cand_n"] = len(cand)
        log(f"  美股長期:{[c['id'] for c in pick]}")
    else:
        fill_and_track(T, True)
    for mk in (tw, us):
        for k, T in mk.items():
            if not (k == "short" and mk is us): perf(T)
            T["upd"] = NOW.strftime("%Y-%m-%d %H:%M")
    out = {"ver": VER, "u": NOW.strftime("%Y-%m-%d %H:%M"), "tw_day": twd, "us_day": usd, "tw": tw, "us": us,
           "start": J.get("start") or NOW.strftime("%Y-%m-%d")}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log("aip3:完成 " + " ".join(f"{m}.{k}={len(T['slots'])}檔" for m, mk in (("tw", tw), ("us", us)) for k, T in mk.items()))


if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc(); print("aip3:例外", e)
