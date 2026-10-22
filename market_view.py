"""🧭 盤勢解讀(r1129)→ view.json(最新一份 + 歷史索引)+ view/YYYY-MM-DD_am|pm.json(每一份永久保存)

回答三個問題:為什麼漲/跌?現在跌到哪裡了?什麼時候/看到什麼才算落底?
分工(數字全部由程式算,AI 只負責「解釋」):
  ・程式:大盤位置(20 週乖離分位、離高點)、融資、外資現貨/期貨、散戶小台、美債殖利率、油價、恐懼貪婪、
          落底燈號、關鍵價位、落底清單現況 —— 全部取自站上既有資料檔。
  ・回測:落底清單每一項都用 view_stats.json(2014 起真實資料)標「有效 / 沒比較好 / 資料不足」;
          週乖離低檔區之後的表現來自 bias.json(同樣是歷史回測)。
  ・AI(Gemini):只能根據「程式算好的數字」與「真實新聞標題」寫原因、時間點、三種劇本;
          原因每一條都要附新聞編號,對不到真實標題的整條丟掉;不寫買賣建議。
需要 Secret:GEMINI_KEY。排程:view.yml(台北 07:50 美股收盤後、21:50 台股盤後資料齊了)。
手動:SEED=檔案.json 用人工寫好的解讀(格式同 AI 輸出)產生一份,DATE/SLOT 可指定。"""
import json, os, re, sys, time, math
import datetime as dt
import requests
from fetch_news import rss, norm, KEY

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
DATE = os.environ.get("DATE", "").strip() or NOW.strftime("%Y-%m-%d")
SLOT = os.environ.get("SLOT", "").strip() or ("am" if NOW.hour < 14 else "pm")
# r1134:GitHub 排程常整班延後好幾小時(10/21 的 21:50 班拖到隔天 02:16 才跑)→ 跑的時候已過午夜,
#   會被當成「隔天早上版」去抓還沒收盤的美股而失敗。00:00~05:59 一律視為前一天晚上版(已產生就跳過)。
if not os.environ.get("SLOT", "").strip() and not os.environ.get("DATE", "").strip() and NOW.hour < 6:
    DATE, SLOT = (NOW - dt.timedelta(days=1)).strftime("%Y-%m-%d"), "pm"
FORCE = os.environ.get("FORCE", "").strip() in ("1", "true", "yes")
SEED = os.environ.get("SEED", "").strip()
OUT, DIR = "view.json", "view"

# 2026 年 FOMC 會議(聯準會官網公布的日程;美東日期,結果在台北隔天清晨)
FOMC = ["2026-01-27/28", "2026-03-17/18", "2026-04-28/29", "2026-06-16/17", "2026-07-28/29",
        "2026-09-15/16", "2026-10-27/28", "2026-12-08/09"]


def log(*a): print(*a, flush=True)
def jl(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d
def r(x, n=1):
    try:
        x = float(x); return None if not math.isfinite(x) else round(x, n)
    except Exception: return None
def ydaily(Y, sym):
    d = (Y.get("series", {}).get(sym) or {}).get("d") or {}
    return [(dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat(), float(c)) for t, c in zip(d.get("t") or [], d.get("c") or []) if c is not None]
def fmt(v, big=False):
    if v is None: return "—"
    return f"{v:,.0f}" if big or abs(v) >= 1000 else (f"{v:,.1f}" if abs(v) >= 100 else f"{v:,.2f}")


# ══════════════════════ 一、程式算的事實 ══════════════════════
IDX = [("TW", "^TWII", "加權指數", True), ("OTC", "^TWOII", "櫃買指數", False), ("SOX", "^SOX", "費城半導體", True),
       ("NDX", "^IXIC", "那斯達克", True), ("SPX", "^GSPC", "S&P 500", True)]
BTM_KEY = {"TW": "TW", "SOX": "SOX", "NDX": "NDX", "SPX": "SPX"}
MNAME = {"b60": "中線超跌", "b20": "短線急跌", "fx": "外資賣到極端", "br": "全面殺盤", "nl": "恐慌拋售",
         "thr": "廣度急升(止跌)", "up": "站回 10 日線(止跌)"}


def btm_state(m):
    """跟前端 btmMktOn 同一套:收盤價判斷每顆燈"""
    P = m["last"]
    on = dict(m.get("on") or {})
    on["b20"] = P <= m["p20"]; on["b60"] = P <= m["p60"]
    on["up"] = P > m["pma10"] and not m["nl2"] and P > m["lo19"]
    return on


def facts():
    Y, B, BS = jl("yext.json", {}), jl("bias.json", {}), jl("bottom.json", {})
    D = jl("data.json", {}); M = D.get("macro") or {}
    S = jl("bottom_stats.json", {})
    bias = {x["sym"]: x for x in (B.get("idx") or [])}
    F = {"idx": [], "lights": {}, "levels": {}}
    for k, sym, name, main in IDX:
        x = bias.get(sym); dl = ydaily(Y, sym)
        if not x: continue
        w = (x.get("ma") or {}).get("20") or {}
        cl = [c for _, c in dl]
        hi = max(cl) if cl else None
        hid = dl[cl.index(hi)][0] if cl else None
        row = {"k": k, "name": name, "last": r(x["last"], 2), "d": x.get("as_of"), "chg1": r((cl[-1] / cl[-2] - 1) * 100, 2) if len(cl) >= 2 else None,
               "hi": r(hi, 2), "hid": hid, "dd": r((x["last"] / hi - 1) * 100) if hi else None,
               "wb": r(w.get("bias")), "wpct": r(w.get("pct"), 0), "zone": x.get("zone"), "zone_since": x.get("zone_since"),
               "wma": r(w.get("ma"), 2), "wp10": w.get("p10"), "wp25": w.get("p25")}
        if x.get("zone") in ("低檔", "極低") and x.get("low_bt"):
            row["bt"] = {h: x["low_bt"][h] for h in ("4", "8", "26") if h in x["low_bt"]}
            row["base"] = {h: x["base"][h] for h in ("4", "8", "26") if h in (x.get("base") or {})}
        F["idx"].append(row)
        bk = BTM_KEY.get(k); m = (BS.get("mkt") or {}).get(bk) if bk else None
        if m:
            on = btm_state(m); ps = m.get("pass") or []
            st = ((S.get("mkt") or {}).get(bk) or {}).get("lights") or []
            low = [l["k"] for l in st if l.get("pass") and l["kind"] == "low"]
            stop = [l["k"] for l in st if l.get("pass") and l["kind"] == "stop"]
            F["lights"][k] = {"name": m.get("name") or name, "d": m["d"], "low": low, "stop": stop,
                              "on": [l for l in low + stop if on.get(l)], "nLow": sum(1 for l in low if on.get(l)),
                              "nStop": sum(1 for l in stop if on.get(l))}
            P = m["last"]; big = k == "TW"
            ma60 = (m["S59"] + P) / 60
            lv = [{"n": "止跌確認價", "p": r(m["pma10"], 2), "w": "收盤站上 10 日線、而且 3 天不破底 → 止跌燈亮"},
                  {"n": "季線(60 日線)", "p": r(ma60, 2), "w": "回測:加權跌深後站回季線,3 個月上漲機率較高" if k == "TW" else "季線"},
                  {"n": "破底警戒", "p": r(m["lo19"], 2), "w": "跌破 = 創 20 日新低"},
                  {"n": "短線急跌價", "p": r(m["p20"], 2), "w": "跌到這以下,短線急跌燈亮(20 日乖離到歷史低檔)"},
                  {"n": "中線超跌價", "p": r(m["p60"], 2), "w": "跌到這以下,中線超跌燈亮(60 日乖離到歷史低檔)"}]
            if row.get("wma"):
                lv.append({"n": "20 週均線", "p": row["wma"], "w": "中期多空分界"})
                if row.get("wp10") is not None:
                    lv.append({"n": "20 週乖離低檔區", "p": r(row["wma"] * (1 + row["wp10"] / 100), 2),
                               "w": "跌到這裡 = 20 週乖離進入歷史最低 10%(過去少見的低點)"})
            lv = [z for z in lv if z["p"]]
            lv.sort(key=lambda z: -z["p"])
            for z in lv: z["dist"] = r((z["p"] / P - 1) * 100)
            F["levels"][k] = {"name": name, "last": P, "d": m["d"], "big": big, "lv": lv, "ma60": r(ma60, 2)}
    # 融資
    cr = M.get("credit") or {}
    h = cr.get("h") or {}
    fin = [(d, v) for d, v in zip(h.get("d") or [], h.get("fin") or []) if v]
    if fin:
        last60 = fin[-60:]; mx = max(last60, key=lambda z: z[1])
        F["margin"] = {"v": r(fin[-1][1], 0), "d": fin[-1][0], "max": r(mx[1], 0), "maxd": mx[0],
                       "off": r((fin[-1][1] / mx[1] - 1) * 100), "t10": r(mx[1] * 0.9, 0),
                       "d5": r(fin[-1][1] - fin[-6][1], 0) if len(fin) >= 6 else None}
    # 外資期貨、散戶小台、P/C
    T = jl("taifex.json", {}).get("stat") or {}
    ft = (M.get("futtab") or [])
    if T:
        F["fut"] = {"fx": T.get("foreign"), "pct": T.get("foreign_pct"), "d5": T.get("foreign_d5"), "d": T.get("as_of"),
                    "days": T.get("days")}
    if ft:
        F["leek"] = {"v": ft[-1].get("leek"), "prev": ft[-2].get("leek") if len(ft) > 1 else None, "d": ft[-1].get("d"),
                     "pcr": ft[-1].get("pcr")}
    # 外資現貨
    tw = (BS.get("mkt") or {}).get("TW") or {}
    if tw.get("Fd"):
        F["fspot"] = {"d": [x[0] for x in tw["Fd"]], "v": [x[1] for x in tw["Fd"]], "F20": tw.get("F20"), "F20q": tw.get("F20q")}
    elif tw.get("F20") is not None:
        F["fspot"] = {"F20": tw.get("F20"), "F20q": tw.get("F20q")}
    # 利率、油價、美元、VIX、恐懼貪婪
    def ser(sym):
        x = ydaily(Y, sym); return x
    tnx = ser("^TNX")
    if len(tnx) >= 21:
        c = [v for _, v in tnx]; hi20 = max(c[-20:])
        F["tnx"] = {"v": r(c[-1], 2), "d": tnx[-1][0], "hi20": r(hi20, 2), "chg20": r(c[-1] - c[-21], 2), "off": r(c[-1] - hi20, 2)}
    for sym, key in (("BZ=F", "brent"), ("DX-Y.NYB", "dxy"), ("^VIX", "vix")):
        x = ser(sym)
        if len(x) >= 21: F[key] = {"v": r(x[-1][1], 2), "d": x[-1][0], "chg20": r((x[-1][1] / x[-21][1] - 1) * 100)}
    fg = Y.get("fng") or {}
    if fg.get("s") is not None: F["fng"] = {"v": fg["s"], "r": fg.get("r"), "w": fg.get("w"), "m": fg.get("m"), "ts": (fg.get("ts") or "")[:10]}
    # 近期新低(加權、費半)
    for k, sym in (("TW", "^TWII"), ("SOX", "^SOX")):
        c = [v for _, v in ydaily(Y, sym)]
        if len(c) >= 40:
            nl = [c[i] <= min(c[i - 19:i + 1]) for i in range(len(c) - 20, len(c))]
            F.setdefault("nl", {})[k] = {"last5": any(nl[-5:]), "last20": any(nl)}
    # 事件:財報(yext earn)+ FOMC
    ev = []
    today = DATE
    for e in Y.get("earn") or []:
        if e.get("d") and e["d"] >= today:
            ev.append({"d": e["d"], "t": f"{e.get('sym')} 財報" + ("(美股盤後)" if e.get("t") == "amc" else ""), "k": "earn"})
    for f in FOMC:
        d0 = f.split("/")[0]; d1 = d0[:8] + f.split("/")[1]
        if d1 >= today:
            nd = (dt.date.fromisoformat(d1) + dt.timedelta(days=1)).isoformat()
            ev.append({"d": d1, "t": f"FOMC 利率決議({d0[5:].replace('-', '/')}~{d1[8:]},台北 {nd[5:].replace('-', '/')} 清晨公布)", "k": "fomc"})
    ev.sort(key=lambda z: z["d"])
    F["events"] = [e for e in ev if e["d"] <= (dt.date.fromisoformat(today) + dt.timedelta(days=45)).isoformat()][:10]
    # r1130:外部資料(景氣燈號、美國金融壓力、選擇權支撐壓力)
    X = jl("ext.json", {}) or {}
    try:
        b = (X.get("biz") or {}).get("last")
        if b:
            NM = {"B": "藍燈", "YB": "黃藍燈", "G": "綠燈", "YR": "黃紅燈", "R": "紅燈"}
            F["biz"] = {"m": b[0], "score": b[1], "color": NM.get(b[2], b[2]), "c": b[2], "lead_up3": (X.get("biz") or {}).get("lead_up3")}
        fr = X.get("fred") or {}
        cur = fr.get("cur") or {}
        if cur.get("BAA10Y"):
            F["fred"] = {"baa": cur["BAA10Y"]["v"], "baa_c20": cur["BAA10Y"].get("c20"), "q90": fr.get("q90"),
                         "curve": (cur.get("T10Y3M") or {}).get("v"), "nfci": (cur.get("NFCI") or {}).get("v"),
                         "stl": (cur.get("STLFSI4") or {}).get("v"), "d": cur["BAA10Y"]["d"],
                         "on": [k for k, v in (fr.get("on") or {}).items() if v]}
        O = X.get("opt") or {}; OS = ((O.get("stats") or {}).get("lights") or {})
        tw = F["levels"].get("TW")
        if tw and O.get("c"):
            for kind, nm in (("w", "週選"), ("m", "月選")):
                x = O["c"].get(kind)
                if not x: continue
                for side, key, lab in (("put", "pw", "支撐"), ("call", "cw", "壓力")):
                    if not x.get(key): continue
                    st = OS.get(f"{kind}_{side}") or {}
                    v = f"回測:到結算前守住 {st.get('held')}%(同距離基準 {st.get('exp')}%)" + ("" if st.get("pass") else ",歷史上不可靠") if st else "回測資料累積中"
                    tw["lv"].append({"n": f"選擇權{lab}({nm}最大{'賣' if side == 'put' else '買'}權)", "p": float(x[key]),
                                     "w": f"{x.get(key + 'oi') or 0:,} 口未平倉;{v}", "opt": True, "ok": bool(st.get("pass"))})
            tw["lv"].sort(key=lambda z: -z["p"])
            for z in tw["lv"]: z["dist"] = r((z["p"] / tw["last"] - 1) * 100)
            F["opt"] = {k: {"pw": v.get("pw"), "cw": v.get("cw"), "pcr": v.get("pcr"), "con": v.get("con")} for k, v in O["c"].items()}
    except Exception as e: log(f"  外部資料略過:{e}")
    F["asof"] = BS.get("asof") or {}
    return F


# ══════════════════════ 二、落底清單:現況 + 回測 ══════════════════════
def vstat(VS, m, k, nodata=None):
    if nodata: return {"st": "nodata", "note": nodata}
    x = (VS.get(m) or {}).get(k)
    if not x: return {"st": "nodata", "note": "回測資料還沒產生"}
    return {"st": "ok" if x["pass"] else "fail", "on": x["on"], "off": x["off"], "ep": x["ep"]}


def checklist(F):
    VS = jl("view_stats.json", {}) or {}
    L = []
    lv = F.get("levels", {})
    tw = lv.get("TW"); sx = lv.get("SOX")
    nl = F.get("nl", {})
    if tw:
        L.append({"g": "台股", "k": "ma60", "t": "加權站回季線", "now": tw["last"] > tw["ma60"],
                  "v": f"現在 {fmt(tw['last'], 1)},季線 {fmt(tw['ma60'], 1)}", **vstat(VS, "TW", "ma60")})
    if "TW" in nl:
        L.append({"g": "台股", "k": "nolow", "t": "加權 5 天不再創新低", "now": (not nl["TW"]["last5"]) and nl["TW"]["last20"],
                  "v": "近 5 天有創 20 日新低" if nl["TW"]["last5"] else ("近 20 天有破底、這 5 天守住" if nl["TW"]["last20"] else "近 20 天收盤都沒有創 20 日新低"),
                  **vstat(VS, "TW", "nolow")})
    fs = F.get("fspot") or {}
    if fs.get("v"):
        v = fs["v"]; n3 = len(v) >= 3 and all(x > 0 for x in v[-3:])
        L.append({"g": "台股", "k": "fbuy3", "t": "外資現貨連 3 天買超", "now": n3,
                  "v": "近 5 日(億):" + "、".join(f"{x:+,.0f}" for x in v[-5:]), **vstat(VS, "TW", "fbuy3")})
    mg = F.get("margin")
    if mg:
        L.append({"g": "台股", "k": "mwash10", "t": "融資洗掉 1 成(散戶認賠)", "now": mg["v"] <= mg["t10"],
                  "v": f"現在 {fmt(mg['v'], True)} 億,60 日高點 {fmt(mg['max'], True)} 億({mg['off']:+.1f}%),洗 1 成 = {fmt(mg['t10'], True)} 億",
                  **vstat(VS, "TW", "mwash10")})
    fu = F.get("fut")
    if fu and fu.get("fx") is not None:
        L.append({"g": "台股", "k": "fut", "t": "外資台指期空單回補", "now": (fu.get("d5") or 0) > 0,
                  "v": f"淨部位 {fu['fx']:+,} 口(近 5 日 {fu.get('d5') or 0:+,} 口,一年分位 {fu.get('pct')})",
                  **vstat(VS, "", "", f"站上只有 {fu.get('days') or '約 250'} 天資料,無法回測,僅供觀察")})
    lk = F.get("leek")
    if lk and lk.get("v") is not None:
        L.append({"g": "台股", "k": "leek", "t": "散戶小台多空比轉負(散戶認輸)", "now": lk["v"] < 0,
                  "v": f"現在 {lk['v']:+.1f}%" + (f"(前一天 {lk['prev']:+.1f}%)" if lk.get("prev") is not None else ""),
                  **vstat(VS, "", "", "站上只有十幾天資料,無法回測,僅供觀察")})
    tn = F.get("tnx")
    if tn:
        L.append({"g": "利率", "k": "tnx", "t": "美債 10 年殖利率從高點回落 0.15 以上", "now": tn["off"] <= -0.15,
                  "v": f"現在 {tn['v']:.2f}%,20 日高點 {tn['hi20']:.2f}%({tn['off']:+.2f})",
                  **vstat(VS, "", "", "站上只有約半年資料,無法回測,僅供觀察")})
    if sx:
        L.append({"g": "半導體", "k": "sox_ma60", "t": "費半站回季線", "now": sx["last"] > sx["ma60"],
                  "v": f"現在 {fmt(sx['last'], 1)},季線 {fmt(sx['ma60'], 1)}", **vstat(VS, "SOX", "ma60")})
    if "SOX" in nl:
        L.append({"g": "半導體", "k": "sox_nolow", "t": "費半 5 天不再創新低", "now": (not nl["SOX"]["last5"]) and nl["SOX"]["last20"],
                  "v": "近 5 天有創 20 日新低" if nl["SOX"]["last5"] else ("近 20 天有破底、這 5 天守住" if nl["SOX"]["last20"] else "近 20 天收盤都沒有創 20 日新低"),
                  **vstat(VS, "SOX", "nolow")})
    # r1130:美國金融壓力(FRED 1990 起回測;美股跌深時)
    try:
        X = jl("ext.json", {}) or {}; fr = X.get("fred") or {}; FL = ((fr.get("stats") or {}).get("lights") or {}); on = fr.get("on") or {}
        cur = fr.get("cur") or {}
        for k, t, v in (("vix_hi", "VIX ≥ 30(美股恐慌)", f"現在 VIX {((cur.get('VIXCLS') or {}).get('v'))}"),
                        ("credit_hi", "美國公司債利差飆高(近 3 年最高 10%)", f"現在 {((cur.get('BAA10Y') or {}).get('v'))}%,門檻 {fr.get('q90')}%")):
            x = FL.get(k)
            if not x: continue
            o, f = x.get("on") or {}, x.get("off") or {}
            st = "danger" if x.get("flip") else ("ok" if x.get("pass") else "fail")
            L.append({"g": "美股・利率", "k": k, "t": t, "now": bool(on.get(k)), "v": v, "st": st,
                      "on": {"n": o.get("n"), "w20": o.get("w60"), "w60": o.get("w120"), "m60": o.get("m120"), "dd": o.get("dd")},
                      "off": {"n": f.get("n"), "w20": f.get("w60"), "w60": f.get("w120"), "m60": f.get("m120"), "dd": f.get("dd")}, "ep": x.get("ep"), "hz": "6m"})
    except Exception: pass
    # 回測條件是「離一年高點跌 8% 以上」:還沒跌深時,價格/籌碼類項目不適用,不打勾也不打叉
    dd = {x["k"]: x.get("dd") for x in F.get("idx", [])}
    for c in L:
        m = "SOX" if c["g"] == "半導體" else "TW" if c["g"] == "台股" else "SPX" if c["g"] == "美股・利率" else None
        if m and c["st"] != "nodata" and dd.get(m) is not None and dd[m] > -8:
            c["na"] = f"{'費半' if m == 'SOX' else 'S&P 500' if m == 'SPX' else '加權'}離高點只跌 {abs(dd[m]):.1f}%,還不算跌深(回測條件是跌 8% 以上),這項先不適用"
    return L, VS.get("period") or ""


# ══════════════════════ 三、AI 解讀 ══════════════════════
Q_ZH = ["台股 大跌 原因", "台股 大漲 原因", "台股 外資 賣超 OR 買超", "費半 半導體 股價", "聯準會 升息 OR 降息 通膨",
        "美債殖利率 美股", "台積電 股價 外資", "記憶體 股價", "AI 泡沫 OR 資本支出", "融資 斷頭 OR 追繳"]
Q_EN = ["stock market today why stocks", "semiconductor stocks selloff OR rally", "Fed rate hike OR cut odds",
        "Treasury yields stocks", "AI spending bubble fears", "Nvidia OR Broadcom OR Micron shares", "oil prices stocks"]


def collect():
    hrs = 64 if NOW.weekday() in (0, 6) else 36
    cut = NOW - dt.timedelta(hours=hrs)
    seen, pool = set(), []
    for q in Q_ZH: pool += [dict(x, q=q) for x in rss(q, "zh")]; time.sleep(0.6)
    for q in Q_EN: pool += [dict(x, q=q) for x in rss(q, "en")]; time.sleep(0.6)
    items, per = [], {}
    for x in sorted(pool, key=lambda x: x["p"] or NOW, reverse=True):
        if not x["t"] or (x["p"] and x["p"] < cut): continue
        k = norm(x["t"])
        if k in seen or per.get(x["q"], 0) >= 12: continue
        seen.add(k); per[x["q"]] = per.get(x["q"], 0) + 1; items.append(x)
    log(f"  新聞:收到 {len(pool)} → 給 AI {min(len(items), 140)} 則")
    return items[:140]


SCHEMA = {"type": "OBJECT", "properties": {
    "head": {"type": "STRING"},
    "causes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "t": {"type": "STRING"}, "body": {"type": "STRING"}, "refs": {"type": "ARRAY", "items": {"type": "INTEGER"}}},
        "required": ["t", "body", "refs"]}},
    "where": {"type": "STRING"},
    "timing": {"type": "STRING"},
    "scen": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "n": {"type": "STRING", "enum": ["樂觀", "中性", "悲觀"]}, "likely": {"type": "BOOLEAN"}, "body": {"type": "STRING"}},
        "required": ["n", "body"]}},
    "tips": {"type": "ARRAY", "items": {"type": "STRING"}},
}, "required": ["head", "causes", "where", "timing", "scen", "tips"]}


def facts_text(F, CL):
    L = []
    for x in F["idx"]:
        s = f"{x['name']} {fmt(x['last'])}({x['d']}"
        if x.get("chg1") is not None: s += f",當天 {x['chg1']:+.2f}%"
        s += ")"
        if x.get("dd") is not None: s += f";離近半年高點 {fmt(x['hi'])}({x['hid']}){x['dd']:+.1f}%"
        if x.get("wb") is not None and x.get("wpct") is not None: s += f";20 週乖離 {x['wb']:+.1f}%(歷史第 {x['wpct']:.0f} 百分位,區域:{x['zone']})"
        if x.get("bt"):
            b = x["bt"]; s += "。歷史上跌進這個低檔區之後:" + "、".join(f"{h} 週後上漲機率 {b[h]['win']}% 中位 {b[h]['med']:+.1f}%" for h in b)
        L.append("・" + s)
    for k, v in F["lights"].items():
        L.append(f"・落底燈號 {v['name']}:落底燈 {v['nLow']}/{len(v['low'])} 亮、止跌燈 {v['nStop']}/{len(v['stop'])} 亮(亮的:{'、'.join(MNAME.get(z, z) for z in v['on']) or '無'})")
    for k, v in F["levels"].items():
        L.append(f"・{v['name']} 關鍵價位:" + "、".join(f"{z['n']} {fmt(z['p'])}({z['dist']:+.1f}%)" for z in v["lv"]))
    if F.get("margin"): m = F["margin"]; L.append(f"・融資餘額 {fmt(m['v'], True)} 億({m['d']}),60 日高點 {fmt(m['max'], True)} 億({m['maxd']}),只少 {m['off']:+.1f}%")
    if F.get("fspot", {}).get("v"): f = F["fspot"]; L.append(f"・外資現貨近 5 日(億):{'、'.join(f'{x:+,.0f}' for x in f['v'][-5:])};近 20 日累計 {fmt(f['F20'], True)} 億(近 3 年最極端 10% 門檻 {fmt(f['F20q'], True)} 億)")
    if F.get("fut"): f = F["fut"]; L.append(f"・外資台指期淨部位 {f['fx']:+,} 口(近 5 日變化 {f.get('d5') or 0:+,},一年分位 {f.get('pct')})")
    if F.get("leek"): f = F["leek"]; L.append(f"・散戶小台多空比 {f['v']:+.1f}%(前一天 {f.get('prev')}),選擇權 P/C {f.get('pcr')}")
    if F.get("tnx"): t = F["tnx"]; L.append(f"・美債 10 年殖利率 {t['v']:.2f}%(20 日前起 {t['chg20']:+.2f},20 日高點 {t['hi20']:.2f}%)")
    if F.get("brent"): L.append(f"・布蘭特原油 {F['brent']['v']}(20 日 {F['brent']['chg20']:+.1f}%)")
    if F.get("vix"): L.append(f"・VIX {F['vix']['v']}")
    if F.get("biz"): b = F["biz"]; L.append(f"・台灣景氣對策信號 {b['m']} {b['score']} 分({b['color']}){',領先指標連 3 個月上升' if b.get('lead_up3') else ''}")
    if F.get("fred"): f = F["fred"]; L.append(f"・美國 Baa 公司債利差 {f['baa']}%(20 日 {f.get('baa_c20')},近 3 年最高 10% 門檻 {f.get('q90')}%);10 年−3 個月殖利率差 {f.get('curve')}%;芝加哥 Fed 金融情勢 {f.get('nfci')}")
    if F.get("fng"): L.append(f"・CNN 恐懼貪婪指數 {F['fng']['v']}({F['fng']['r']};一週前 {F['fng'].get('w')})")
    if F.get("events"): L.append("・即將發生:" + ";".join(f"{e['d']} {e['t']}" for e in F["events"]))
    now = lambda c: "目前不適用(還沒跌深)" if c.get("na") else "目前成立" if c["now"] else "目前未成立"
    for st, lab in (("ok", "【回測有效】(跌深時可以當依據)"), ("danger", "【回測有效・危險訊號】(成立時之後更容易再跌)"), ("fail", "【回測沒比較好】(歷史上不可靠,不能當依據)"), ("nodata", "【無法回測】(僅供觀察)")):
        g = [c for c in CL if c["st"] == st]
        if g: L.append(f"・落底清單{lab}:" + ";".join(f"{c['t']}({now(c)})" for c in g))
    return "\n".join(L)


def prompt(F, CL, items):
    wd = "一二三四五六日"[dt.date.fromisoformat(DATE).weekday()]
    news = "\n".join(f"[{i}] ({x['s'] or '?'}{' ' + x['p'].strftime('%m/%d %H:%M') if x['p'] else ''}) {x['t']}" for i, x in enumerate(items))
    return f"""你是台灣的總經與盤勢研究員,要幫一般投資人寫今天({DATE} 週{wd},{'早上,美股剛收盤' if SLOT == 'am' else '晚上,台股盤後資料已出齊'})的「盤勢解讀」。
讀者不懂術語,要白話、具體、有價位;語氣冷靜,不嚇人也不喊多。

【程式算好的數據(唯一可以用的數字來源)】
{facts_text(F, CL)}

【過去一兩天的新聞標題(方括號是編號)】
{news}

規則:
1. 數字只能用上面「數據」或新聞標題裡出現的,不准自己編數字、日期、機率。
2. head:一段話(80 字內)直接回答「這波漲跌的真正原因是什麼、現在在什麼位置」。如果市場其實沒什麼波動,就照實說盤勢平穩。
3. causes:3~5 條,由重到輕,每條 t(15 字內標題)、body(2~3 句,講清楚因果)、refs(對應的新聞編號,至少 1 個;找不到新聞佐證的原因不要寫)。
4. where:2~4 句,用數據說明現在跌到/漲到哪裡、哪個市場已經到歷史低檔、哪個還沒有、籌碼(融資/外資/散戶)洗乾淨了沒。
5. timing:2~3 句,說明接下來哪些事件會決定方向(用數據裡的「即將發生」事件和新聞),以及「看到什麼」才比較可能落底/轉弱。
   提到落底清單時,要尊重回測結果:【回測有效】的可以當依據;【回測沒比較好】的要說「歷史上不可靠」;【無法回測】的說「僅供觀察」。
5b. 寫原因時要像資深研究員講「因果鏈」(例如 通膨高於預期 → 升息機率上升 → 高本益比的半導體先被賣),
   並分清楚是「需求/基本面變差」還是「利率/資金/籌碼」的問題——這會決定要等什麼才會落底;至少一條講台股自己的原因。
6. scen:樂觀、中性、悲觀三種劇本,各 1~2 句,要帶關鍵價位(用數據裡的價位);likely=true 標你認為最可能的那一個(只能一個)。
7. tips:2~3 條一般性的參考做法(例如分批、先看哪類股票),不要寫具體買賣某檔股票的建議;
   不准把【回測沒比較好】的訊號當成進場或止穩依據(例如那些項目不能寫成「若…就是止穩訊號」)。
8. 全部繁體中文(台灣用語),不要用驚嘆號,不要寫「投資一定有風險」這類套話(網站會統一加註)。"""


TRIED = []


def gemini(p):
    """先試推理能力較強的 2.5 Pro(免費額度),不行再用 Flash 系列"""
    if not KEY: log("  ✗ 沒有 GEMINI_KEY"); return None
    TRIED.clear()
    order = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-2.0-flash"]
    try:   # 查目前真的有的模型:最新版的 Pro 排最前面(推理較好),沒有/額度用完再退回 Flash
        ms = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={KEY}&pageSize=200", timeout=30).json().get("models") or []
        names = [m["name"].split("/")[-1] for m in ms if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        ver = lambda n: tuple(int(x) for x in re.findall(r"gemini-(\d+)\.?(\d*)", n)[0] if x) if re.match(r"gemini-\d", n) else (0,)
        pro = sorted([n for n in names if re.fullmatch(r"gemini-\d+(\.\d+)?-pro(-latest)?", n)], key=ver, reverse=True)[:2]
        order = pro + [n for n in order if n in names or not names]
    except Exception as e:
        TRIED.append(f"models:{str(e)[:40]}")
    for mdl in order:
        gc = {"maxOutputTokens": 12000, "temperature": 0.3, "responseMimeType": "application/json", "responseSchema": SCHEMA}
        if not mdl.startswith("gemini-2.0"): gc["thinkingConfig"] = {"thinkingBudget": 4096}
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={KEY}",
                              json={"contents": [{"role": "user", "parts": [{"text": p}]}], "generationConfig": gc}, timeout=240)
            if not r.ok: TRIED.append(f"{mdl}:{r.status_code}"); log(f"  gemini {mdl} {r.status_code},換模型"); time.sleep(6); continue
            cand = (r.json().get("candidates") or [{}])[0]
            txt = "".join(x.get("text", "") for x in ((cand.get("content") or {}).get("parts") or []) if not x.get("thought"))
            j = json.loads(txt); j["_model"] = mdl; return j
        except Exception as e:
            TRIED.append(f"{mdl}:{str(e)[:60]}"); log(f"  gemini {mdl} 失敗:{str(e)[:150]}"); time.sleep(6)
    return None


# 回測沒比較好的項目:建議裡同時出現這些字 → 該條建議拿掉(避免 AI 把不可靠的訊號當依據)
FAIL_KW = {"fbuy3": [["外資", "買超"], ["外資", "回補現貨"]], "mwash10": [["融資", "洗"], ["融資", "減少"]],
           "nolow": [["加權", "新低"]], "sox_ma60": [["費半", "季線"], ["費城", "季線"]], "sox_nolow": [["費半", "新低"], ["費城", "新低"]]}


def bad_tip(t, CL):
    for c in CL:
        if c.get("st") == "fail":
            for kws in FAIL_KW.get(c["k"], []):
                if all(k in t for k in kws): return True
    return False


def ai_view(F, CL, items):
    j = gemini(prompt(F, CL, items))
    if not j: return None
    def src(i):
        x = items[i]
        return {"t": x["t"][:120], "s": x["s"], "l": x["l"], "d": x["p"].strftime("%m/%d %H:%M") if x["p"] else "", "en": x["lang"] == "en"}
    causes = []
    for c in j.get("causes") or []:
        refs = [q for q in dict.fromkeys(c.get("refs") or []) if isinstance(q, int) and 0 <= q < len(items)]
        if not refs: log(f"  丟掉原因(沒有新聞佐證):{c.get('t')}"); continue
        causes.append({"t": c["t"].strip(), "body": c["body"].strip(), "src": [src(q) for q in refs[:3]]})
    scen = [{"n": s["n"], "likely": bool(s.get("likely")), "body": s["body"].strip()} for s in j.get("scen") or [] if s.get("body")]
    if sum(s["likely"] for s in scen) > 1:
        seen = False
        for s in scen:
            if s["likely"] and seen: s["likely"] = False
            seen = seen or s["likely"]
    return {"head": (j.get("head") or "").strip(), "causes": causes, "where": (j.get("where") or "").strip(),
            "timing": (j.get("timing") or "").strip(), "scen": scen, "tips": [t.strip() for t in j.get("tips") or [] if t.strip() and not bad_tip(t, CL)][:3],
            "model": j.get("_model", ""), "n_in": len(items), "tried": list(TRIED)}


# ══════════════════════ 主程式 ══════════════════════
def main():
    os.makedirs(DIR, exist_ok=True)
    fp = f"{DIR}/{DATE}_{SLOT}.json"
    if os.path.exists(fp) and not FORCE:
        log(f"{fp} 已經產生過,跳過"); return
    F = facts()
    CL, period = checklist(F)
    log(f"  事實:{len(F['idx'])} 個指數、{len(F['levels'])} 組價位、清單 {len(CL)} 項")
    if SEED:
        A = jl(SEED); A.setdefault("model", "Claude(人工撰寫)"); A.setdefault("n_in", 0)
    else:
        items = collect()
        if len(items) < 12: log("✗ 新聞太少,這班不產生"); sys.exit(0)
        A = ai_view(F, CL, items)
        if not A or len(A["causes"]) < 2 or not A["head"]:
            log("✗ AI 解讀失敗或有效原因不到 2 條,不發布"); sys.exit(0)
    view = {"v": 1, "date": DATE, "slot": SLOT, "gen": NOW.strftime("%Y-%m-%dT%H:%M:%S+08:00"), "facts": F,
            "check": CL, "period": period, **A}
    json.dump(view, open(fp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    idx = []
    for fn in sorted(os.listdir(DIR), reverse=True):
        mm = re.match(r"(\d{4}-\d{2}-\d{2})_(am|pm)\.json$", fn)
        if not mm: continue
        try:
            j = json.load(open(f"{DIR}/{fn}", encoding="utf-8"))
            idx.append({"d": mm.group(1), "s": mm.group(2), "h": (j.get("head") or "")[:60]})
        except Exception: pass
    idx.sort(key=lambda z: (z["d"], z["s"]), reverse=True)
    json.dump(dict(view, dates=idx), open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"✓ {fp}:{A.get('head', '')[:60]}… 原因 {len(A.get('causes') or [])} 條(模型 {A.get('model')});歷史 {len(idx)} 份")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        tb = traceback.extract_tb(e.__traceback__)[-1]
        print(f"::error::盤勢解讀失敗:{type(e).__name__}: {str(e)[:160]} @ {tb.name}:{tb.lineno} {tb.line[:120] if tb.line else ''}")
        sys.exit(1)
