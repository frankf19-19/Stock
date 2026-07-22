#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
國際行情抓取器 v4 —— 零 Yahoo、零 stooq(它擋機器人)。
美股指數/美債殖利率/VIX/日經/美元指數:FRED(聯準會官方 API,免費金鑰)
加權全日分線:證交所官方「每5秒指數統計」MI_5MINS_INDEX(帶日期參數,收盤後/深夜也拿得到最近時段全日)
櫃買全日分線:MIS 006201 富櫃50 ETF 分線 × 指數比例換算(MIS 分線端點不支援指數頻道,但支援 ETF)
匯率:open.er-api.com(免金鑰)
機房被擋時自動借道 repo 根目錄 proxy.json 指定的自家 Cloudflare Worker。
需要環境變數 FRED_API_KEY(GitHub Secrets 設定)。
"""
import json, time, datetime, sys, os
import urllib.request
import urllib.parse

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
FRED_KEY = os.environ.get("FRED_API_KEY", "").strip()

def _proxy_url():
    """repo 根目錄 proxy.json 的自家 Worker 網址(無檔案=不用代理)"""
    try:
        u = json.load(open("proxy.json", encoding="utf-8")).get("url", "").strip()
        return u.rstrip("/") if u.startswith("https://") else ""
    except Exception:
        return ""

def _sess_date():
    """最近交易時段日(台北):00:00~08:29 算前一天;週末回退到週五"""
    tp = datetime.timezone(datetime.timedelta(hours=8))
    d = datetime.datetime.now(tp)
    if d.hour * 60 + d.minute < 8 * 60 + 30:
        d -= datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d.replace(hour=0, minute=0, second=0, microsecond=0)

def _tp_day(ts):
    tp = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.fromtimestamp(ts, tp).date()


# 前端符號 → FRED series id(全部日頻,官方 T+0~T+1 更新)
FRED = {
    "^GSPC": "SP500",
    "^IXIC": "NASDAQCOM",
    "^DJI":  "DJIA",
    "^N225": "NIKKEI225",
    "^VIX":  "VIXCLS",
    "^TNX":  "DGS10",        # 10年期美債殖利率(%)
    "^FVX":  "DGS5",
    "^TYX":  "DGS30",
    "DX-Y.NYB": "DTWEXBGS",  # 廣義美元指數(聯準會版;量級與 DXY 不同,趨勢一致)
}
# (v4)加權改官方每5秒統計、櫃買改 ETF 換算——不再使用 MIS 指數頻道
ERAPI_FX = True   # TWD=X / JPYTWD=X / EURTWD=X / JPY=X

def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def http_get_px(url, timeout=25):
    """直連 → 失敗自動借道自家 Worker(proxy.json)"""
    try:
        return http_get(url, timeout=timeout)
    except Exception:
        pu = _proxy_url()
        if not pu:
            raise
        return http_get(pu + "/?url=" + urllib.parse.quote(url, safe=""), timeout=timeout + 15)

def mis_quote(codes):
    """MIS getStockInfo 批次報價:回 {代號:{'z':現價,'y':昨收}};深夜也會回最近時段值。
    codes 例:['tse_t00.tw','otc_o00.tw','otc_006201.tw']"""
    q = ("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch="
         + "|".join(codes) + f"&json=1&delay=0&_={int(time.time()*1000)}")
    try:
        j = json.loads(http_get_px(q, timeout=15))
    except Exception:
        return {}
    out = {}
    for m in (j.get("msgArray") or []):
        cid = str(m.get("c") or "").strip()
        def num(k):
            try:
                v = float(str(m.get(k, "")).replace(",", ""))
                return v if v == v and v > 0 else None
            except Exception:
                return None
        if cid:
            out[cid] = {"z": num("z"), "y": num("y")}
    return out


def fred_daily(series, days=200):
    d2 = datetime.date.today()
    d1 = d2 - datetime.timedelta(days=days + 120)
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series}&api_key={FRED_KEY}&file_type=json"
           f"&observation_start={d1.isoformat()}&observation_end={d2.isoformat()}")
    j = json.loads(http_get(url, timeout=30))
    t, c = [], []
    for o in j.get("observations", []):
        v = o.get("value", ".")
        if v in (".", "", None):
            continue
        try:
            ts = int(datetime.datetime.fromisoformat(o["date"])
                     .replace(tzinfo=datetime.timezone.utc).timestamp())
            t.append(ts); c.append(round(float(v), 4))
        except Exception:
            continue
    return {"t": t[-140:], "c": c[-140:]} if len(t) >= 5 else None

def nasdaq_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA["User-Agent"],
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def _et_fix(ts_fake):
    """Nasdaq chart 的 x 是「美東牆上時間」偽裝成 UTC epoch → 轉回真實 epoch。
    夏令時(3月第二個週日~11月第一個週日)=UTC-4,其餘 UTC-5。"""
    d = datetime.datetime.fromtimestamp(ts_fake, datetime.timezone.utc)
    y = d.year
    def nth_sun(mo, n):
        first = datetime.date(y, mo, 1)
        off = (6 - first.weekday()) % 7
        return datetime.date(y, mo, 1 + off + 7 * (n - 1))
    dst = nth_sun(3, 2) <= d.date() < nth_sun(11, 1)
    return ts_fake + (4 if dst else 5) * 3600

def _nasdaq_points(j):
    rows = ((j.get("data") or {}).get("chart")) or []
    tt, cc = [], []
    for p in rows:
        try:
            x = p.get("x"); y = p.get("y")
            if x is None or y is None:
                continue
            ts = int(x / 1000) if x > 10**11 else int(x)   # 毫秒→秒
            ts = _et_fix(ts)                                # 美東牆上時間 → 真實 epoch
            v = float(str(y).replace(",", ""))
            tt.append(ts); cc.append(round(v, 2))
        except Exception:
            continue
    return tt, cc

def nasdaq_daily(sym="SOX", days=200):
    """費城半導體(SOX)是 Nasdaq 自家指數 → 直接向 Nasdaq 官方 chart API 取日線。
    零 Yahoo。機房若被擋則略過,不影響其它資料。"""
    d2 = datetime.date.today()
    d1 = d2 - datetime.timedelta(days=days)
    try:
        j = nasdaq_get(f"https://api.nasdaq.com/api/quote/{sym}/chart"
                       f"?assetclass=index&fromdate={d1.isoformat()}&todate={d2.isoformat()}")
    except Exception as e:
        print(f"  {sym} Nasdaq 端點失敗: {e}", file=sys.stderr)
        return None
    tt, cc = _nasdaq_points(j)
    return {"t": tt[-140:], "c": cc[-140:]} if len(tt) >= 5 else None

# 美股四大指數盤中 1 分線(Nasdaq 官方,延遲約15分;本排程美股時段每20分鐘一班)
NASDAQ_INTRA = {"^GSPC": ["SPX"], "^IXIC": ["COMP"],
                "^DJI": ["DJIA", "DJI"], "^SOX": ["SOX"]}

def nasdaq_intraday(cands):
    for sym in cands:
        try:
            j = nasdaq_get(f"https://api.nasdaq.com/api/quote/{sym}/chart?assetclass=index")
        except Exception as e:
            print(f"  {sym} Nasdaq 盤中失敗: {e}", file=sys.stderr)
            continue
        tt, cc = _nasdaq_points(j)
        if len(tt) >= 5:
            return {"t": tt, "c": cc}
        time.sleep(0.6)
    return None

def mis_intraday(ch, prev=None, sess=None):
    """MIS 分線端點(僅支援個股/ETF 頻道,不支援指數頻道)。
    時間軸錨定「最近交易時段日」09:00 起逐分鐘——深夜執行不會標成未來時間。"""
    url = (f"https://mis.twse.com.tw/stock/api/getChartOhlcStatis.jsp"
           f"?ex_ch={ch}&_={int(time.time()*1000)}")
    try:
        j = json.loads(http_get_px(url, timeout=15))
    except Exception:
        return None
    best = []
    def scan(o, depth=0):
        nonlocal best
        if depth > 4 or o is None:
            return
        if isinstance(o, list):
            nums = []
            for x in o:
                v = x[1] if isinstance(x, list) and len(x) > 1 else x
                try:
                    v = float(v)
                    if v == v:
                        nums.append(v)
                except Exception:
                    pass
            if len(nums) >= 5:
                okr = (prev is None or all(abs(v/prev - 1) < 0.15 for v in nums[:20]))
                if okr and len(nums) > len(best):
                    best = nums
            for x in o[:3]:
                scan(x, depth + 1)
        elif isinstance(o, dict):
            for v in o.values():
                scan(v, depth + 1)
    scan(j)
    if len(best) < 5:
        return None
    base = (sess or _sess_date()).replace(hour=9, minute=0)
    t0 = int(base.timestamp())
    ts = [t0 + i * 60 for i in range(len(best))]
    return {"t": ts, "c": [round(v, 2) for v in best]}

def twse_5s_index(sess, prev=None):
    """加權全日分線:證交所官方「每5秒指數統計」,帶日期參數 → 深夜/週末也拿得到最近時段。
    欄位先認欄名、認不到再用值域(貼近昨收±15%)偵測,官方改版欄序也不會壞。"""
    ds = sess.strftime("%Y%m%d")
    url = (f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_INDEX"
           f"?response=json&date={ds}&_={int(time.time()*1000)}")
    try:
        j = json.loads(http_get_px(url, timeout=30))
    except Exception as e:
        print(f"  MI_5MINS_INDEX 失敗: {e}", file=sys.stderr)
        return None
    rows = j.get("data") or []
    if not rows:
        return None
    fields = [str(x) for x in (j.get("fields") or [])]
    vcol = next((i for i, f in enumerate(fields) if "發行量加權股價指數" in f), None)
    tcol = next((i for i, r0 in enumerate(rows[0])
                 if isinstance(r0, str) and r0.count(":") == 2), 0)
    if vcol is None and prev:
        for ci in range(len(rows[0])):
            if ci == tcol:
                continue
            vals = []
            for r in rows[:60]:
                try:
                    vals.append(float(str(r[ci]).replace(",", "")))
                except Exception:
                    pass
            if len(vals) >= 5 and sum(1 for v in vals if prev*0.85 < v < prev*1.15) >= len(vals)*0.9:
                vcol = ci
                break
    if vcol is None:
        return None
    t, c = [], []
    last_min = None
    for r in rows:
        tm = str(r[tcol]).strip()
        try:
            v = float(str(r[vcol]).replace(",", ""))
        except Exception:
            continue
        hms = tm.split(":")
        if len(hms) != 3:
            continue
        key = hms[0] + ":" + hms[1]
        if key == last_min:
            c[-1] = round(v, 2)                      # 同一分鐘取最後一筆=分收
            continue
        last_min = key
        ts = int(sess.replace(hour=int(hms[0]), minute=int(hms[1])).timestamp())
        t.append(ts)
        c.append(round(v, 2))
    return {"t": t, "c": c} if len(c) >= 5 else None

def main():
    series = {}
    if not FRED_KEY:
        print("::warning::未設定 FRED_API_KEY,略過美股/殖利率(請到 repo Secrets 加入)")
    else:
        for sym, sid in FRED.items():
            for attempt in range(2):
                try:
                    got = fred_daily(sid)
                    if got:
                        series[sym] = {"d": got}
                        print(f"  {sym} ← FRED:{sid}({len(got['t'])} 根)")
                        break
                except Exception as e:
                    print(f"  {sym} FRED {sid} 失敗: {e}", file=sys.stderr)
                time.sleep(1.2)
            time.sleep(0.4)
    # 費城半導體:FRED 無此系列 → Nasdaq 官方端點(指數擁有者;零 Yahoo)
    got_sox = nasdaq_daily("SOX")
    if got_sox:
        series["^SOX"] = {"d": got_sox}
        print(f"  ^SOX ← Nasdaq 官方日線({len(got_sox['t'])} 根)")
    else:
        print("  ^SOX Nasdaq 未取得(機房被擋屬正常,本輪略過)")
    # 美股四大指數盤中分線(Nasdaq 官方;非交易時段回傳前一交易日全日走勢,同樣照存)
    for fsym, cands in NASDAQ_INTRA.items():
        m = nasdaq_intraday(cands)
        if not m:
            print(f"  {fsym} 盤中分線未取得(機房被擋或休市空檔,略過)")
            continue
        d = (series.get(fsym) or {}).get("d")
        if d and d.get("t") and d.get("c"):
            # 昨收:比對「分線最後一點的美東日期」與「FRED 日線最後一根日期」
            et = datetime.timezone(datetime.timedelta(hours=-4))
            intra_day = datetime.datetime.fromtimestamp(m["t"][-1], et).date()
            daily_day = datetime.datetime.fromtimestamp(d["t"][-1],
                        datetime.timezone.utc).date()
            if daily_day >= intra_day and len(d["c"]) >= 2:
                m["prev"] = d["c"][-2]     # FRED 已含當日 → 昨收=倒數第二根
            else:
                m["prev"] = d["c"][-1]     # FRED 尚未含當日 → 昨收=最後一根
        series.setdefault(fsym, {})["m"] = m
        print(f"  {fsym} ← Nasdaq 盤中({len(m['t'])} 點,昨收 {m.get('prev','—')})")
        time.sleep(0.5)
    # ── 台股指數全日分線(v4):加權=證交所官方每5秒統計、櫃買=006201 ETF 分線×比例換算 ──
    old_series = {}
    try:
        with open("yext.json", encoding="utf-8") as f:
            old_series = (json.load(f).get("series")) or {}
    except Exception:
        pass

    def keep_better(sym, new_m):
        """同時段舊資料比新資料長 → 保留舊的(防止端點回半截把好資料蓋掉)"""
        om = (old_series.get(sym) or {}).get("m")
        if new_m and om and om.get("t") and new_m.get("t"):
            try:
                if (_tp_day(om["t"][-1]) == _tp_day(new_m["t"][-1])
                        and len(om["c"]) > len(new_m["c"])):
                    if om.get("prev") is None and new_m.get("prev") is not None:
                        om["prev"] = new_m["prev"]
                    print(f"  {sym} 新資料較短({len(new_m['c'])}<{len(om['c'])}點),保留舊檔")
                    return om
            except Exception:
                pass
        return new_m

    sess = _sess_date()
    q = mis_quote(["tse_t00.tw", "otc_o00.tw", "otc_006201.tw"])
    ty = (q.get("t00") or {}).get("y")
    oy = (q.get("o00") or {}).get("y")
    ey = (q.get("006201") or {}).get("y")
    # 加權:官方每5秒統計(主)→ MIS ETF 0050 換算(備,理論上用不到)
    m_tw = twse_5s_index(sess, ty)
    if m_tw:
        if ty:
            m_tw["prev"] = round(ty, 2)
        m_tw = keep_better("^TWII", m_tw)
        series.setdefault("^TWII", {})["m"] = m_tw
        print(f"  ^TWII ← 官方每5秒統計({len(m_tw['t'])} 點,{sess.date()},昨收 {m_tw.get('prev','—')})")
    else:
        om = (old_series.get("^TWII") or {}).get("m")
        if om:
            series.setdefault("^TWII", {})["m"] = om
            print("  ^TWII ← 沿用前檔走勢(官方端點暫不可用)")
        else:
            print("  ^TWII 未取得(官方端點與前檔皆無)", file=sys.stderr)
    # 櫃買:MIS 分線端點不支援指數頻道 → 006201 富櫃50 ETF 分線 × (指數昨收/ETF昨收)
    m_otc = None
    if oy and ey:
        m_e = mis_intraday("otc_006201.tw", prev=ey, sess=sess)
        if m_e:
            r = oy / ey
            m_otc = {"t": m_e["t"], "c": [round(v * r, 2) for v in m_e["c"]],
                     "prev": round(oy, 2), "approx": 1}
    if m_otc:
        m_otc = keep_better("^TWOII", m_otc)
        series.setdefault("^TWOII", {})["m"] = m_otc
        print(f"  ^TWOII ← 006201 ETF 換算({len(m_otc['t'])} 點,{sess.date()},昨收 {m_otc.get('prev','—')})")
    else:
        om = (old_series.get("^TWOII") or {}).get("m")
        if om:
            if oy and om.get("prev") is None:
                om["prev"] = round(oy, 2)
            series.setdefault("^TWOII", {})["m"] = om
            print("  ^TWOII ← 沿用前檔走勢(ETF 分線深夜清空屬正常;15:10 收盤快照會存好全日)")
        else:
            print("  ^TWOII 未取得(ETF 端點與前檔皆無;下個台股盤中班次會補上)", file=sys.stderr)
    time.sleep(0.5)
    # 匯率
    if ERAPI_FX:
        try:
            j = json.loads(http_get("https://open.er-api.com/v6/latest/USD", timeout=20))
            r = j.get("rates") or {}
            now = int(time.time())
            def put(sym, val, dg):
                if val:
                    series[sym] = {"d": {"t": [now-86400, now],
                                         "c": [round(val, dg), round(val, dg)]}}
            twd, jpy, eur = r.get("TWD"), r.get("JPY"), r.get("EUR")
            put("TWD=X", twd, 3)
            if twd and jpy: put("JPYTWD=X", twd/jpy, 4)
            if twd and eur: put("EURTWD=X", twd/eur, 3)
            put("JPY=X", jpy, 2)
            print(f"  匯率 ← er-api(USD/TWD={twd})")
        except Exception as e:
            print(f"  匯率 er-api 失敗: {e}", file=sys.stderr)
    # ── 原物料(Stooq 免費 CSV;日線含今日進行中價格,約15分鐘延遲;供前端卡片漲跌%徽章)──
    CMD_STOOQ = {"GC=F": "gc.f", "SI=F": "si.f", "HG=F": "hg.f", "CL=F": "cl.f",
                 "BZ=F": "cb.f", "NG=F": "ng.f", "NI=F": "ni.f", "ALI=F": "ali.f"}
    for sym, st in CMD_STOOQ.items():
        try:
            try:
                csvt = http_get(f"https://stooq.com/q/d/l/?s={st}&i=d", timeout=25)
            except Exception:
                csvt = http_get_px(f"https://stooq.com/q/d/l/?s={st}&i=d", timeout=25)
            rows = [r.split(",") for r in csvt.strip().splitlines()[1:] if r.count(",") >= 4]
            rows = [r for r in rows if r[4] not in ("", "N/D")]
            if len(rows) < 2:
                raise ValueError("no data")
            rows = rows[-90:]
            t, c = [], []
            for r in rows:
                y, m, dd = map(int, r[0].split("-"))
                t.append(int(datetime.datetime(y, m, dd,
                             tzinfo=datetime.timezone.utc).timestamp()))
                c.append(round(float(r[4]), 4))
            series[sym] = {"d": {"t": t, "c": c, "prev": c[-2]}}
            print(f"  {sym} ← Stooq:{st}({len(t)} 根,最新 {c[-1]})")
        except Exception as e:
            print(f"  [warn] {sym} Stooq {st}: {str(e)[:50]}")
        time.sleep(0.4)
    # ── 📡 美股重磅財報雷達(Nasdaq 官方行事曆;未來14天,聚焦台鏈連動大型股)──
    EARN_WATCH = {"NVDA", "MSFT", "GOOGL", "AAPL", "AMZN", "META", "TSLA", "AMD", "AVGO",
                  "QCOM", "MU", "INTC", "ORCL", "MRVL", "ARM", "TSM", "SMCI", "DELL", "ANET"}
    earn = []
    _tp8 = datetime.timezone(datetime.timedelta(hours=8))
    _base = datetime.datetime.now(_tp8).date()
    for i in range(0, 15):
        d = _base + datetime.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        u = f"https://api.nasdaq.com/api/calendar/earnings?date={d.isoformat()}"
        try:
            try:
                j = json.loads(http_get(u, timeout=20))
            except Exception:
                j = json.loads(http_get_px(u, timeout=20))
            rows = ((j.get("data") or {}).get("rows")) or []
            for r in rows:
                sym = str(r.get("symbol", "")).upper().strip()
                if sym not in EARN_WATCH:
                    continue
                tcode = str(r.get("time", ""))
                t = "amc" if "after" in tcode else ("bmo" if "pre" in tcode else "tbd")
                eps = str(r.get("epsForecast", "") or "").replace("$", "").strip()
                nm = str(r.get("companyName", "") or r.get("name", "") or "")[:40]
                earn.append({"d": d.isoformat(), "sym": sym, "n": nm, "t": t, "eps": eps})
        except Exception as e:
            print(f"  [warn] 財報行事曆 {d}: {str(e)[:40]}")
        time.sleep(0.35)
    if earn:
        print(f"  財報雷達 ← Nasdaq({len(earn)} 場)")
    else:                                               # 來源閃失 → 沿用前檔,不歸零
        try:
            with open("yext.json", encoding="utf-8") as f:
                earn = json.load(f).get("earn") or []
            if earn:
                print("  財報雷達:沿用前檔")
        except Exception:
            pass
    if len(series) < 4:
        print(f"::error::只取得 {len(series)} 檔(<4),放棄寫檔")
        sys.exit(1)
    # ── CNN 恐懼貪婪指數(公開 JSON;零成本)──
    fng = None
    _fng_url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    for u in (_fng_url,
              "https://api.allorigins.win/raw?url=" + urllib.parse.quote(_fng_url, safe="")):
        try:
            req = urllib.request.Request(u, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.load(r)
            fg = j.get("fear_and_greed") or {}
            sc = float(fg.get("score"))
            fng = {"s": round(sc, 1),
                   "r": str(fg.get("rating", "")),
                   "p": round(float(fg.get("previous_close", sc)), 1),
                   "w": round(float(fg.get("previous_1_week", sc)), 1),
                   "m": round(float(fg.get("previous_1_month", sc)), 1),
                   "ts": str(fg.get("timestamp", ""))[:19]}
            print(f"  恐懼貪婪指數 ← CNN({fng['s']:.0f} {fng['r']})")
            break
        except Exception as e:
            print(f"  [warn] 恐懼貪婪指數({'直連' if u == _fng_url else '代理'}): {str(e)[:60]}")
    if fng is None:                                     # 來源閃失 → 沿用前檔,不歸零
        try:
            with open("yext.json", encoding="utf-8") as f:
                fng = json.load(f).get("fng")
            if fng:
                print("  恐懼貪婪指數:沿用前檔")
        except Exception:
            pass
    doc = {"updated": datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
           "series": series}
    if fng:
        doc["fng"] = fng
    if earn:
        doc["earn"] = earn
    with open("yext.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"完成:{len(series)} 檔 → yext.json(FRED+MIS+er-api,零 Yahoo)")

if __name__ == "__main__":
    main()
