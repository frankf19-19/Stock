#!/usr/bin/env python3
"""K研所 · 🤖 AI Pick 三期制(r1092)——短期 / 中期 / 長期 各 5 檔,台股、美股 → aip3.json
研究與驗證:專案文件「AI_Pick三期制研究_2026-10-14」。規則與回測一致,實戰逐日追蹤,紀錄永久保留。

台股
  🏃 短期(2~3 週):每週最後一個交易日收盤選「近 52 週高 × 強勢訊號」綜合分最高 5 檔(扣除持有中),
       下個交易日開盤買,最多持 15 個交易日(第 15 天收盤出場),不設停損停利。
       回測 2016~2026(含成本):年化 +31.8%、最大回落 −37%、最差年 −25%。訊號 5/10/20 天贏大盤 +0.5/+1.1/+1.5%,14 年全正。
  🌊 中期(波段):量價籌碼模型(主力組同一套)排名前 5 補進空位,下個交易日開盤買;掉出前 200 名 → 隔天開盤賣,不設停利停損。
       回測 2016~2026(含成本):年化 +40.8%、最大回落 −37%、最差年 +9.9%、11 年全正,每年約 39 筆。
  🏦 長期(有未來性的成長股 + 產業):每季第一個交易日選:成交值前 40% + 近 3 月營收年增 10~100%(穩定成長、不是暴衝)+ 連 6 個月營收年增為正
       + 近 3 個月營收合計創 13 個月新高 + 本益比 10~35 + 離 52 週高 ≤15% + 站上年線
       → 綜合(6 月營收年增、ROE、離高、成交值、所屬產業營收成長)最高 5 檔,持有到下一季;每檔另附 AI 產業分析(Google 搜尋,敘述、非驗證)。
       回測 2013~2026:半年比大盤 +9.0%(13 年中 10 年)、一年 +14.7%(12 年中 10 年);季換股年化 +28%、最大回落 −32%、最差年 −16%。
       產業面的實證:產業營收成長前 1/3 的股票一年 +1.4%(弱);「產業龍頭」(產業內成交值前 3)一年反而 −2.6~−5.6% → 產業只當排序因子,不獎勵龍頭。
美股(限制:只有目前 S&P 500 成分股,有倖存者偏差)
  🏃 短期:現有每週模型(walk-forward 驗證,回測 25 週勝率 54%、平均 +1.6%)最新一週前 5 名,成交/出場跟 aipick_us.json 一致。
  🌊 中期(參考・高波動):跌深低接——第一天離 60 日高跌 ≥25% → 隔天開盤買,+20% 停利 / −15% 停損 / 最多 60 天;5 個槽位,沒機會就空著。
       每筆贏隨機 +1.9%(14/14 年),但 5 檔組合回落 −48%、2022 年 −39%。
  🏦 長期(弱驗證):年線上、成交值前 20 的龍頭裡,近一年營收成長最高 5 檔,每季檢視。一年比大盤 +15.8%(10 年中 6 年);純龍頭版 +6.7%(13 年中 10 年)。
"""
import json, re, os, glob, datetime as dt

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
OUT = "aip3.json"
VER = "r1099"
LONG_RV = "r1095"   # 長期規則版本——改版且清單尚未成交時,重新選股
AI_TTL_D = 45       # AI 未來性評分快取天數(選股時 45 天內不重打;每月第一班另外更新持股)
AI_POOL_N = 12      # 每個市場最多替量化排序前 12 檔候選打 AI 分(每檔一次搜尋約 15~20 秒)
AI_BUDGET_SEC = 480 # 整班 AI 呼叫時間上限;超過就不再打,沒評到的候選排在有評分的後面,下一班再補
import time as _time
_T0 = _time.time()
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
        ra15 = ra_all[-15:]; q3 = [sum(ra15[j - 2:j + 1]) for j in range(2, len(ra15)) if all(x is not None for x in ra15[j - 2:j + 1])]
        rev13hi = len(q3) >= 13 and q3[-1] >= max(q3[-13:])             # 近 3 個月營收合計創 13 個月新高(大型股月營收起伏大,用 3 月合計)
        roe = (pb / pe) if (pe and pb and pe > 0 and pb > 0) else None
        dh = C[i] / max(H[max(0, i - 249):i + 1]) - 1; m240 = sma(C, 240, i)
        rows.append(dict(id=sid, name=s.get("name"), sector=s.get("sector"), liq=liq, pe=pe, dy=dy, roe=roe, yoy3=yoy3, yoy6=yoy6, pos6=pos6, rev13hi=rev13hi,
                         rm=rm_all[-1] if rm_all else None, dh=dh, up=bool(m240 and C[i] > m240), px=C[i]))
    rows.sort(key=lambda r: -r["liq"]); cut = int(len(rows) * 0.4); big = rows[:cut]
    # 產業層:同產業(池子裡 ≥5 檔)近 3 月營收年增中位數 = 這個產業現在有沒有在成長
    import statistics as st
    bysec = {}
    for r in big:
        if r["yoy3"] is not None: bysec.setdefault(r["sector"] or "", []).append(r["yoy3"])
    secg = {k: st.median(v) for k, v in bysec.items() if len(v) >= 5}
    for r in big: r["sec_g"] = secg.get(r["sector"] or ""); r["sec_n"] = len(bysec.get(r["sector"] or "", []))
    # 百分位排名(在成交值前 40% 的池子裡)
    def prk(key):
        vals = sorted(r[key] for r in big if r.get(key) is not None); n = len(vals)
        return {r["id"]: (sum(1 for v in vals if v <= r[key]) / n if (r.get(key) is not None and n) else 0.5) for r in big}
    R = {k: prk(k) for k in ("yoy6", "roe", "dh", "liq", "sec_g")}
    for r in big:
        if r["pe"] and 10 <= r["pe"] <= 35 and r["yoy3"] is not None and 10 <= r["yoy3"] <= 100 and r["pos6"] and r["rev13hi"] and r["dh"] >= -0.15 and r["up"]:
            r["comp"] = sum(R[k][r["id"]] for k in ("yoy6", "roe", "dh", "liq", "sec_g")) / 5
            r["sec_pct"] = round(R["sec_g"][r["id"]] * 100)
            r["why"] = [f"近 3 月營收年增 {r['yoy3']:+.0f}%", f"連 6 個月營收成長,近 3 月合計創 13 個月新高({r['rm']})", f"本益比 {r['pe']:.1f}" + (f"・ROE 約 {r['roe']*100:.0f}%" if r["roe"] else ""),
                        (f"產業「{r['sector']}」營收年增中位數 {r['sec_g']:+.0f}%(同業成長前 {100 - r['sec_pct']}%)" if r.get("sec_g") is not None else f"產業「{r['sector']}」樣本少"),
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


def ai_future(p, us=False):
    """r1095:AI 未來性評分——Gemini + Google 搜尋最近 3 個月產業/公司新聞,回 {"score":1~10,"txt":分析,"src":依據,"d":日期};沒金鑰 → None
    這是「參考」:沒有歷史新聞可回測,所以只拿來在已驗證的候選池裡排序,不決定候選池本身"""
    try:
        import aipick
        if not aipick.GEMINI_KEY: return None
        aipick.AI2_BUDGET = max(aipick.AI2_BUDGET, 60)
        nm = p.get("name") or p["id"]; sec = p.get("sector") or ""
        q = (f"你是產業研究員。請評估「{nm}({p['id']}){'(美股)' if us else '(台股)'}」(產業:{sec})未來 2~3 年的「未來性」。"
             "先用網路搜尋最近 3 個月的產業與公司新聞(需求、訂單、產能、技術、政策、競爭),只用有根據的事實。"
             "輸出格式(繁體中文、純文字、三行):"
             "第一行「分數:N」,N 是 1~10 的整數——9~10=產業結構性成長、公司是關鍵供應者、能見度到明年以後;7~8=產業成長、公司受惠但競爭多或能見度較短;"
             "5~6=產業持平、靠公司自身努力;3~4=產業成熟或成長明顯放緩;1~2=產業衰退或面臨替代。"
             "第二行「分析:」接 160 字以內一段:①產業未來 2~3 年的成長動能(具體需求來源或技術趨勢)②公司在產業鏈的位置與優勢③最大風險。"
             "第三行「依據:」寫 1~2 則最近新聞的重點與月份。不要喊口號、不要用「建議買進」這類字眼、不要用驚嘆號。")
        txt = aipick._gemini_raw(q, 900, search=True) or ""
        m = re.search(r"分數[::]\s*(\d+)", txt); sc = int(m.group(1)) if m else None
        if sc is not None: sc = max(1, min(10, sc))
        m2 = re.search(r"分析[::]\s*(.+?)(?=\n\s*依據[::]|$)", txt, re.S); ana = (m2.group(1) if m2 else txt).strip().replace("\n", " ")[:360]
        m3 = re.search(r"依據[::]\s*(.+)", txt, re.S); src = (m3.group(1) if m3 else "").strip().replace("\n", " ")[:220]
        return {"score": sc, "txt": ana, "src": src, "d": NOW.strftime("%Y-%m-%d")}
    except Exception as e:
        log(f"  AI 未來性略過:{e}"); return {"score": None, "txt": "", "src": "", "d": NOW.strftime("%Y-%m-%d")}


def ensure_ai(p, cache, us=False, max_age=AI_TTL_D):
    """把 AI 未來性套到候選/槽位 p(快取夠新就不打);回 False 代表沒金鑰(整班停做)"""
    e = cache.get(p["id"])
    try: age = (NOW.date() - dt.date.fromisoformat((e or {}).get("d") or "2000-01-01")).days
    except Exception: age = 9999
    if not (e and e.get("score") is not None and age <= max_age):
        if _time.time() - _T0 > AI_BUDGET_SEC: return True                 # 時間用完:這檔先不評,下一班再補
        r = ai_future(p, us)
        if r is None: return False
        if r.get("score") is None and not r.get("txt"): return True        # 這班失敗,下次再試
        cache[p["id"]] = e = r
    p["ai"] = e.get("score"); p["ai_d"] = e.get("d"); p["ind"] = e.get("txt") or ""; p["ind_src"] = e.get("src") or ""; p["ind_try"] = 1
    if p.get("ai0") is None: p["ai0"] = p["ai"]
    return True


def ai_rank(cand, cache, us=False):
    """候選池(已驗證)每檔補 AI 未來性分數,依(未來性, 量化綜合)排序;沒金鑰時維持量化排序。回 (有分數的檔數, 是否有金鑰)"""
    ok = True
    for c in cand[:AI_POOL_N]:                                             # 量化排序前 12 檔才打分(候選池平均 11 檔)
        if not ensure_ai(c, cache, us): ok = False; break
    n = sum(1 for c in cand if c.get("ai") is not None)
    cand.sort(key=lambda c: (-(c["ai"] if c.get("ai") is not None else -1), -(c.get("comp") if c.get("comp") is not None else (c.get("g") or 0))))
    return n, ok


def ai_industry(p, us=False):
    """r1092:長期清單每檔附 AI 產業分析(Gemini + Google 搜尋;敘述,非驗證)。只在新進清單時做一次,存進 slot。"""
    try:
        import aipick
        if not aipick.GEMINI_KEY: return None
        nm = p.get("name") or p["id"]; sec = p.get("sector") or ""
        q = (f"你是產業研究員。請用繁體中文、160 字以內、純文字不分段,寫「{nm}({p['id']}){'(美股)' if us else ''}」所屬產業「{sec}」未來 2~3 年的分析:"
             f"① 這個產業的成長動能是什麼(具體的需求來源或技術趨勢);② 這家公司在產業鏈的位置與優勢;③ 最大的風險一句話。"
             f"請用網路搜尋最近 3 個月的資訊,只寫有根據的事,不要喊口號,不要用「建議買進」這類字眼,不要用驚嘆號。")
        txt = aipick._gemini_raw(q, 600, search=True)
        return (txt or "").strip().replace("\n", " ")[:360]
    except Exception as e:
        log(f"  產業分析略過:{e}"); return ""


# ═══════════════ 參考價位(r1097)═══════════════
def _atr14(o):
    tr = [max(x[1] - x[2], abs(x[1] - y[3]), abs(x[2] - y[3])) for x, y in zip(o[-15:], o[-16:-1])]
    return sum(tr) / max(1, len(tr))


def levels(p, key, us=False, prev=None):
    """r1097:每檔的參考價位——🛑 停損 / 🎯 停利 / ➕ 加碼 / 🔁 賣出後再買回。給人自己下單用、前端即時比對現價;
    模型帳仍照各清單規則進出(回測顯示三個清單加價格停損反而變差)。
    停損 = 短期/中期:個股結構支撐(aipick.stock_levels:20/60 日低、月季線、波段低、量能密集區,留 0.5 ATR;不緊於 1.5 ATR、不寬於 2.5 ATR/10%);長期:季線 −3%(最多 −15%);持有中只上不下
    停利 = 短期:第一道有意義的壓力(20/60 日高、波段高、量能密集區,賺賠比 ≥1.5);中期:進場 +25%(回測變體);長期:進場 +30%(減碼一半)
    加碼 = 短期:進場 +5%;中期:進場 +10%(每日交易加碼規則);長期:回到月線附近(月線在進場價之下時),否則進場 +10%
    再買回 = 停損參考價 + 1 ATR(站回支撐之上就可買回,當天也可以)"""
    try:
        import aipick
        B = bars(p["id"], us)
        if len(B) < 60: return prev
        d = [b[0] for b in B]; o = [b[1] for b in B]; C = [x[3] for x in o]
        buy = p.get("entry") or p.get("sel_px") or C[-1]
        if not buy or buy <= 0: return prev
        a = _atr14(o); sinfo = STK.get(p["id"]) or {}
        old = aipick.US; aipick.US = bool(us)
        try:
            tgt, stp, LV = aipick.stock_levels(d, o, buy, a, sinfo)
            ma20 = sum(C[-20:]) / 20; ma240 = sum(C[-240:]) / 240 if len(C) >= 240 else None
            # r1098:依三清單各自的回測結果定(研究:專案文件「三清單停損停利研究_2026-10-14」)
            if us and key == "short":                                        # 美股短期 = 每週模型自己的結構目標/停損
                sl, sls = stp, f"結構支撐({LV.get('stp_src')},每週模型規則)"; tp, tps = tgt, f"第一道壓力({LV.get('tgt_src')},每週模型規則)"; add, adds = buy * 1.05, "進場 +5%"
            elif us and key == "mid":                                        # 美股中期 = 跌深低接規則 +20% / −15%
                sl, sls = buy * 0.85, "進場 −15%(模型規則)"; tp, tps = buy * 1.20, "進場 +20%(模型規則)"; add, adds = buy * 1.10, "進場 +10%"
            elif key == "short":
                sl, sls = buy * 0.85, "進場 −15%(災難停損;回測:緊停損會把年化從 +33% 砍到 +7~27%)"
                tp, tps = buy * 1.20, "進場 +20%(回測:年化 +34.2%、回落 −34%、最差年 −10%)"
                add, adds = buy * 1.05, "進場 +5%(回測:加碼後平均再 +2.2%,和新買一檔差不多)"
            elif key == "mid":
                sl, sls = (p.get("sl_px") or (buy - 4 * a)), "進場 − 4 ATR(原回測設定:年化 +38.5%、回落 −37%;緊停損反而差)"
                tp, tps = buy * 1.25, "進場 +25%(回測:年化 +41.5%、最差年 −4%)"
                add, adds = buy * 1.10, "進場 +10% 且仍在量價前 20 名(回測:加碼後平均再 +4.2%、61% 賺)"
            else:
                sl, sls = buy * 0.92, "進場 −8%(回測:長期任何停損都降年化,但不補位可把回落 −46% 壓到 −28%;停損後等下一季,不要換股)"
                tp, tps = buy * 1.40, "進場 +40% 減碼一半(回測:長期全賣的停利都讓年化變差,+40% 影響最小)"
                add, adds = buy * 1.10, "進場 +10%(回測:加碼後平均再 +12.4%、56% 賺——長期贏家會續強)"
            if prev and prev.get("sl") and p.get("fill_d"): sl = max(sl, prev["sl"]); sls = prev.get("sl_src") if prev["sl"] >= sl else sls
            if add <= sl * 1.02: add, adds = buy * 1.10, "進場 +10%"               # 加碼價不能貼著停損
            re_ = sl + 1.0 * a
            R = lambda v: aipick.rtick(float(v), "near")
            return {"sl": R(sl), "sl_src": sls, "tp": R(tp), "tp_src": tps, "add": R(add), "add_src": adds, "re": R(re_), "re_src": "停損價 + 1 ATR 站回就可買回(回測:停損後 10 天內買回,三個清單都平均虧 −2%、勝率 3 成 → 不建議,除非有新理由)",
                    "atr": round(a, 2), "d": d[-1], "anchor": round(float(buy), 2), "rr": LV.get("rr")}
        finally: aipick.US = old
    except Exception as e:
        log(f"  參考價位略過 {p.get('id')}:{e}"); return prev


def hist_levels(T, key, us=False):
    """已出場的近 15 天內:🔁 再買回參考——停損型出場 = 停損價 + 1 ATR;其他出場(到期/掉出排名/季檢視/停利)= 站回出場價"""
    try:
        import aipick
        cut = (NOW - dt.timedelta(days=15)).strftime("%Y-%m-%d")
        for h in T["hist"][-15:]:
            if h.get("re") is not None or not h.get("xd") or h["xd"] < cut: continue
            B = bars(h["id"], us)
            if len(B) < 20: continue
            o = [b[1] for b in B]; a = _atr14(o)
            old = aipick.US; aipick.US = bool(us)
            try:
                lv = h.get("lv") or {}
                if h.get("xw") == "sl" and lv.get("sl"): h["re"] = aipick.rtick(lv["sl"] + a, "near"); h["re_src"] = "停損參考價 + 1 ATR"
                else: h["re"] = aipick.rtick(float(h["xp"]), "near"); h["re_src"] = "站回出場價(賣掉後又站回去就買回,當天也可以)"
            finally: aipick.US = old
            u = h["xd"]
            for _ in range(10): u = next_td(u, us) or u                     # 出場後 10 個交易日內有效
            h["re_until"] = u
    except Exception as e:
        log(f"  再買回價位略過:{e}")


def tech_of(p, us=False):
    """r1099:技術線與量能快照(給前端即時比對):5/10/20 日線、20 日均量、昨量;短期清單用來看「量 + 技術線」"""
    try:
        B = raw_bars(p["id"], us)
        if len(B) < 21: return None
        o = [b[1] for b in B]; C = [x[3] for x in o]; V = [x[4] if len(x) > 4 else 0 for x in o]
        ma = lambda n: round(sum(C[-n:]) / n, 2)
        vavg = sum(V[-21:-1]) / 20
        return {"d": B[-1][0], "ma5": ma(5), "ma10": ma(10), "ma20": ma(20), "vavg": round(vavg), "v1": round(V[-1]), "vr1": round(V[-1] / vavg, 2) if vavg else None,
                "hi20": round(max(x[1] for x in o[-20:]), 2), "lo10": round(min(x[2] for x in o[-10:]), 2)}
    except Exception: return None


def tier_levels(T, key, us=False):
    for p in T["slots"]:
        if p.get("st") == "done": continue
        lv = levels(p, key, us, p.get("lv"))
        if lv: p["lv"] = lv
        t = tech_of(p, us)
        if t: p["tech"] = t
    hist_levels(T, key, us)


# ═══════════════ 槽位引擎 ═══════════════
def new_tier(rule, val, note=""):
    return {"rule": rule, "val": val, "note": note, "slots": [], "hist": [], "upd": None, "sel_d": None}


def slot(c, day, extra=None):
    x = {"id": c["id"], "name": c.get("name"), "sector": c.get("sector"), "sel_d": day, "sel_px": c.get("px"), "fill_d": None, "entry": None,
         "last": None, "last_d": None, "ret": None, "hi": None, "lo": None, "days": 0, "why": c.get("why") or [], "st": "pend"}
    for k in ("ai", "ai0", "ai_d", "ind", "ind_src", "ind_try"):                 # r1095:AI 未來性(候選時已算好)帶進槽位
        if c.get(k) is not None: x[k] = c[k]
    if extra: x.update(extra)
    return x


def fill_and_track(T, us, tp=None, sl=None, hold_max=None, exit_close_on=None, sl_atr=None):
    """成交(選股日之後第一個交易日開盤)+ 逐日更新 + 固定規則出場。exit_close_on: {sid: 'close'} 今天收盤出場的名單
    r1098:sl_atr = 進場價 − N×ATR(14)(成交日前 14 根 K 算),中期清單用 4 ATR(原回測設定)"""
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
            if sl_atr:
                prev = [b[1] for b in B if b[0] < d0][-15:]
                if len(prev) >= 15: p["sl_px"] = round(p["entry"] - sl_atr * _atr14(prev), 2); p["sl_why"] = f"進場價 − {sl_atr:g}×ATR"
        held = [b for b in B if b[0] >= p["fill_d"]]
        if not held: keep.append(p); continue
        xd = xp = xw = None
        for n, (d, o) in enumerate(held, 1):
            p["hi"] = max(p["hi"] or 0, o[1]); p["lo"] = min(p["lo"] or 1e18, o[2])
            if True:
                if sl and o[2] <= p["entry"] * (1 - sl) and n > 0: xd, xp, xw = d, round(min(o[0], p["entry"] * (1 - sl)), 2), "sl"; break
                if p.get("sl_px") and o[2] <= p["sl_px"]: xd, xp, xw = d, round(min(o[0], p["sl_px"]), 2), "sl"; break
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


def ai_refresh(T, cache, us=False):
    """r1095:每月第一班把持股的 AI 未來性分數與分析重新評一次(用最新新聞);其他班只補沒有分析的槽位"""
    m = NOW.strftime("%Y-%m"); monthly = T.get("ai_m") != m
    ok = True
    for p in T["slots"]:
        if p.get("st") == "done": continue
        if monthly or not p.get("ind"):
            if not ensure_ai(p, cache, us, max_age=20 if monthly else AI_TTL_D): ok = False; break
    if monthly and ok and T["slots"]: T["ai_m"] = m


def perf(T):
    H = T["hist"]; r = [h["ret"] for h in H if h.get("ret") is not None]
    T["perf"] = {"n": len(r), "win": round(100 * sum(1 for x in r if x > 0) / len(r)) if r else None, "avg": round(sum(r) / len(r), 2) if r else None,
                 "sum": round(sum(r), 2) if r else None, "open": len(T["slots"]), "open_avg": (lambda v: round(sum(v) / len(v), 2) if v else None)([p["ret"] for p in T["slots"] if p.get("ret") is not None])}


def main():
    J = load(OUT, {}) or {}
    tw = J.get("tw") or {}; us = J.get("us") or {}
    tw.setdefault("short", new_tier("", ""))
    tw["short"].update(rule="每週最後一個交易日收盤,用量與技術線選 5 檔(離 52 週高 10% 內 × 創新高/帶量突破 20・55 日高/爆量長紅/OBV 新高/KD・RSI 高檔/均線多頭/投信外資買超);下個交易日開盤買,最多持 15 個交易日;停利 +20%、停損 −15%(盤中碰到就出)",
                       val="回測 2016~2026 含成本:停利 +20% + 停損 −15% 年化 +34.2%、最大回落 −34%、最差年 −10%(不設 +32.6% / −38% / −25%);用均線或量能出場都更差:跌破 5 日線 +1%、10 日線 +12%、20 日線 +30%、爆量不漲 +12%、量縮收黑 +25%、乖離停利 +8~17%——強勢股 2~3 週內常先洗再漲",
                       note="⚠ 強勢股集中,波動大於中期")
    tw.setdefault("mid", new_tier("", ""))
    tw["mid"].update(rule="量價籌碼模型前 5 名補進空位,下個交易日開盤買;掉出前 200 名 → 隔天開盤賣;停損 = 進場價 − 4 ATR(約 −12%)、停利 +25%(盤中碰到就出)",
                     val="回測 2016~2026 含成本:4 ATR 停損 + 停利 +25% 年化 +41.5%、最大回落 −39%、最差年 −4%;只停損不停利 +38.5% / −37% / +10%;緊停損(≤2.5 ATR 或 ≤10%)年化掉到 +20~37%",
                     note="✅ 三個清單裡最穩")
    tw.setdefault("long", new_tier("", ""))
    tw["long"].update(rule="每季第一個交易日:先用驗證過的量化條件選出候選池(成交值前 40%、近 3 月營收年增 10~100%、連 6 個月營收成長、近 3 個月營收合計創 13 個月新高、本益比 10~35、離 52 週高 ≤15%、站上年線),再由 AI 搜尋最近 3 個月的產業與公司新聞,給每檔「未來性」1~10 分,取最高 5 檔(同產業最多 2 檔)持有到下一季;每月第一班重新評分與更新分析;候選不足 5 檔就留空",
                      val="候選池回測 2013~2026:一年比大盤 +13.1%(12 年中 9 年)、半年 +9.7%(13 年中 11 年);池內用量化排序取 5 檔一年 +14.7%——優勢來自候選池本身,池內怎麼排影響小。AI 未來性排序沒有歷史新聞可回測,標參考",
                      note="✅ 候選池已驗證・🔮 AI 未來性排序為參考")
    us.setdefault("short", new_tier("每週模型(14 年資料、每週 walk-forward)最新一週前 5 名;成交/出場與美股 AI Pick 一致",
                                     "回測 25 週:勝率 54%、平均 +1.6%;實戰自 2026-09-28", "✅ 已驗證"))
    us.setdefault("mid", new_tier("跌深低接:第一天離 60 日高跌 ≥25% → 隔天開盤買;停利 +20% / 停損 −15% / 最多 60 天;5 個槽位,沒機會就空著",
                                   "每筆贏隨機 +1.9%(14/14 年);但 5 檔組合回測年化 +17%、最大回落 −48%、2022 年 −39%", "⚠ 參考・高波動(資料只有現在的成分股,有倖存者偏差)"))
    us.setdefault("long", new_tier("", ""))
    us["long"].update(rule="每季第一個交易日:年線上、成交值前 20 的龍頭中近一年營收有成長的為候選池,再由 AI 搜尋最近 3 個月新聞給每檔「未來性」1~10 分,取最高 5 檔持有到下一季;每月第一班重新評分",
                      val="候選池回測 2014~2026:純龍頭版一年比大盤 +6.7%(13 年中 10 年)、營收成長前 5 版 +15.8%(10 年中 6 年);季換股年化 +26%、回落 −35%。AI 排序無法回測",
                      note="🟡 弱驗證:資料短、倖存者偏差・🔮 AI 排序為參考")
    twd = last_day(); usd = last_day(True)
    log(f"aip3:台股最後交易日 {twd}、美股 {usd}")
    # ── 台股 短期 ──
    T = tw["short"]
    fill_and_track(T, False, hold_max=15, tp=0.20, sl=0.15)             # r1098:停利 +20% / 停損 −15%(回測 +34.2%、回落 −34%、最差年 −10%)
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
        fill_and_track(T, False, tp=0.25, sl_atr=4)                       # r1098:4 ATR 停損(原回測設定)+ 停利 +25%(回測 +41.5%)
        held = {p["id"] for p in T["slots"]}; sold_today = {h["id"] for h in T["hist"] if h.get("xd") == twd}
        for c in top:
            if len(T["slots"]) >= K: break
            if c["id"] in held or c["id"] in sold_today: continue
            T["slots"].append(slot(c, twd, {"sel_px": (STK.get(c["id"]) or {}).get("price")})); held.add(c["id"])
        T["sel_d"] = twd
    else:
        fill_and_track(T, False, tp=0.25, sl_atr=4); log(f"  中期:量價排名日 {rd} 與 K 線 {twd} 不同,今天不換股")
    # ── 台股 長期 ──
    T = tw["long"]; AIC = J.setdefault("ai_cache", {})
    if T.get("rv") != LONG_RV:                                          # r1095:規則改版(加 AI 未來性排序)——清單還沒成交就重選
        if not any(p.get("fill_d") for p in T["slots"]): T["slots"] = []; T["sel_d"] = None; log("  長期:規則改版,重新選股")
        T["rv"] = LONG_RV
    if twd and (q_first(twd) or not T["sel_d"]) and T["sel_d"] != twd:
        cand = tw_long_candidates(twd); n_ai, has_key = ai_rank(cand, AIC); pick = pick_div(cand, K); ids = {c["id"] for c in pick}
        fill_and_track(T, False, exit_close_on={**{p["id"]: twd for p in T["slots"] if p["id"] not in ids and p["fill_d"]}, "_why": "quarter"})
        held = {p["id"] for p in T["slots"]}
        for c in pick:
            if c["id"] not in held: T["slots"].append(slot(c, twd, {"sec_g": c.get("sec_g"), "sec_pct": c.get("sec_pct")}))
        T["sel_d"] = twd; T["cand_n"] = len(cand); T["ai_n"] = n_ai; T["ai_m"] = NOW.strftime("%Y-%m") if (has_key and n_ai) else None
        T["pool"] = [{"id": c["id"], "name": c.get("name"), "ai": c.get("ai"), "comp": round(c.get("comp") or 0, 3)} for c in cand]
        log(f"  長期:候選 {len(cand)}、AI 評分 {n_ai} → {[(c['name'], c.get('ai')) for c in pick]}")
    else:
        fill_and_track(T, False)
    ai_refresh(T, AIC, False)
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
    if T.get("rv") != LONG_RV:
        if not any(p.get("fill_d") for p in T["slots"]): T["slots"] = []; T["sel_d"] = None; log("  美股長期:規則改版,重新選股")
        T["rv"] = LONG_RV
    if usd and (q_first(usd, True) or not T["sel_d"]) and T["sel_d"] != usd:
        cand = us_long_candidates(usd); n_ai, has_key = ai_rank(cand, AIC, True); pick = pick_div(cand, K); ids = {c["id"] for c in pick}
        fill_and_track(T, True, exit_close_on={**{p["id"]: usd for p in T["slots"] if p["id"] not in ids and p["fill_d"]}, "_why": "quarter"})
        held = {p["id"] for p in T["slots"]}
        for c in pick:
            if c["id"] not in held: T["slots"].append(slot(c, usd))
        T["sel_d"] = usd; T["cand_n"] = len(cand); T["ai_n"] = n_ai; T["ai_m"] = NOW.strftime("%Y-%m") if (has_key and n_ai) else None
        T["pool"] = [{"id": c["id"], "name": c.get("name"), "ai": c.get("ai"), "g": round((c.get("g") or 0) * 100, 1)} for c in cand]
        log(f"  美股長期:候選 {len(cand)}、AI 評分 {n_ai} → {[(c['id'], c.get('ai')) for c in pick]}")
    else:
        fill_and_track(T, True)
    ai_refresh(T, AIC, True)
    for mk in (tw, us):
        for k, T in mk.items():
            try: tier_levels(T, k, mk is us)                                # r1097:每檔參考價位(停損/停利/加碼/再買回)
            except Exception as e: log(f"  {k} 參考價位例外 {e}")
            if not (k == "short" and mk is us): perf(T)
            T["upd"] = NOW.strftime("%Y-%m-%d %H:%M")
    cut = (NOW - dt.timedelta(days=120)).strftime("%Y-%m-%d")
    out = {"ver": VER, "u": NOW.strftime("%Y-%m-%d %H:%M"), "tw_day": twd, "us_day": usd, "tw": tw, "us": us,
           "start": J.get("start") or NOW.strftime("%Y-%m-%d"), "ai_cache": {k: v for k, v in (J.get("ai_cache") or {}).items() if (v or {}).get("d", "") >= cut}}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log("aip3:完成 " + " ".join(f"{m}.{k}={len(T['slots'])}檔" for m, mk in (("tw", tw), ("us", us)) for k, T in mk.items()))


if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc(); print("aip3:例外", e)
