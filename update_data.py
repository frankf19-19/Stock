# -*- coding: utf-8 -*-
"""
update_data.py v4 — 三力選股儀表板(全市場版)
涵蓋:台股全部上市+上櫃(約1,800檔)+ 美股 S&P 500 全成分股(約500檔)
產業:台股用證交所官方「產業別」、美股用 GICS 分類
輸出:data.json(清單+評分+訊號)、k/*.json(K線分片,個股頁點開才載入)

★ 全部免費、不需任何註冊或 token。資料來源:
  台股公司名單/產業別: 證交所+櫃買 OpenAPI 公司基本資料
  台股整市場日行情:     證交所 MI_INDEX + 櫃買日行情表(一天一次呼叫,K線逐日累積)
  月營收:               證交所/櫃買 月營收彙總表
  三大法人:             證交所 T86 + 櫃買法人日報表(近5交易日)
  400張大戶:            集保 TDCC 開放資料;週變化與上一版比對
  美股名單/產業:        S&P 500 成分股開放清單(GICS)
  美股價格:             Yahoo 批次下載 → Stooq 備援

第一次執行會回補約 130 個交易日的 K 線(約 10~15 分鐘),之後每天只補新的一天。
"""
import json, os, time, glob, datetime as dt
from io import StringIO
import requests
import pandas as pd

TODAY = dt.date.today()
UA = {"User-Agent": "Mozilla/5.0"}
K_DIR = "k"
KEEP_BARS = 130

# ── 台股官方產業別代碼(t187ap03 若回傳代碼時使用)──
TW_IND = {"01":"水泥工業","02":"食品工業","03":"塑膠工業","04":"紡織纖維","05":"電機機械",
 "06":"電器電纜","08":"玻璃陶瓷","09":"造紙工業","10":"鋼鐵工業","11":"橡膠工業",
 "12":"汽車工業","14":"建材營造","15":"航運業","16":"觀光餐旅","17":"金融保險",
 "18":"貿易百貨","19":"綜合","20":"其他","21":"化學工業","22":"生技醫療",
 "23":"油電燃氣","24":"半導體業","25":"電腦及週邊設備業","26":"光電業","27":"通信網路業",
 "28":"電子零組件業","29":"電子通路業","30":"資訊服務業","31":"其他電子業",
 "32":"文化創意業","33":"農業科技","34":"電子商務","35":"綠能環保","36":"數位雲端",
 "37":"運動休閒","38":"居家生活"}
GICS_ZH = {"Information Technology":"美股·資訊科技","Communication Services":"美股·通訊服務",
 "Consumer Discretionary":"美股·非必需消費","Consumer Staples":"美股·必需消費",
 "Energy":"美股·能源","Financials":"美股·金融","Health Care":"美股·醫療保健",
 "Industrials":"美股·工業","Materials":"美股·原物料","Real Estate":"美股·房地產",
 "Utilities":"美股·公用事業"}

# ── 精選投資論點(這些代號的個股頁會顯示;其餘顯示產業與數據)──
THESIS = {
 "2330":"護城河最深的 AI 核心持股:先進製程近乎獨占+CoWoS 瓶頸在手,是台股景氣的領先指標。",
 "2382":"AI 伺服器 ODM 龍頭,機櫃級整合與液冷導入拉升單櫃價值,看點在毛利率能否走升。",
 "6669":"直供 CSP 的白牌模式成長斜率最陡,但客戶集中、波動大,適合拉回分批。",
 "2317":"AI 伺服器代工市占最大,GB 機櫃主力組裝廠,估值低於同業、屬防禦型 AI 部位。",
 "3081":"1.6T/CPO 上游雷射磊晶卡位股,題材與基本面銜接中,籌碼與量能為操作主軸。",
 "3363":"CPO 供應鏈 FAU 寡佔者,滲透率自低基期起漲的高純度標的,倉位宜控。",
 "2383":"M8 以上高階 CCL 幾乎獨供,AI 板材升級最大受惠者,三力俱佳的攻擊核心。",
 "6213":"CCL 二線補漲邏輯:估值低於龍頭、高階佔比爬升,適合作衛星配置。",
 "1815":"Low-Dk 玻纖布漲價循環高 Beta 代表,務必設好停損停利紀律。",
 "8358":"HVLP 高階銅箔國產替代+漲價雙題材,波動大、順勢操作。",
 "3711":"OSAT 龍頭吃下 CoWoS 委外與測試外溢訂單,先進封裝題材的穩健打法。",
 "3661":"ASIC 設計服務純度最高,長線案量邏輯未變,留意估值消化與籌碼變化。",
 "5274":"伺服器 BMC 近乎獨占,高毛利+高市占,是 AI 伺服器出貨量的純度指標。",
 "8299":"NAND 漲價循環+企業級 SSD 放量,循環股操作紀律優先。",
 "2408":"純 DRAM 循環股,HBM 排擠讓傳統 DRAM 緊俏;循環股買在虧損、賣在大賺。",
 "3017":"氣冷+液冷雙吃的散熱龍頭,液冷滲透率爬升期能見度高,攻守兼備。",
 "2308":"AI 電源架構升級(800V HVDC)最大市值受惠者,兼具流動性與題材純度。",
 "1519":"AI 用電荒+電網汰換的長線訂單型公司,確定性高,適合作組合穩定器。",
 "3665":"GB 機櫃銅纜線束含量倍增的直接受惠者,資料中心+車用雙引擎,成長品質佳。",
 "3533":"CPU Socket 與高速連接器寡佔,伺服器平台升級即漲價,長線績優成長股。",
 "2059":"伺服器滑軌獨佔級供應商,機櫃出貨量的直接函數,高毛利隱形冠軍。",
 "NVDA":"整條 AI 供應鏈的定價者,財測直接決定台鏈拉貨力道。",
 "AVGO":"自研 ASIC 趨勢最大贏家,與世芯、創意邏輯互為印證。",
 "MU":"HBM 三強之一,記憶體漲價循環的美股直接對照。",
 "TSM":"美元部位持有台積電的工具,ADR 溢價率是外資熱度溫度計。",
 "MSFT":"AI 商業化最完整的雲端巨頭,Azure+Copilot 是 AI 變現速度的風向球。",
 "VRT":"資料中心電力+液冷系統整合商,驗證台股散熱、重電族群趨勢。",
 "ANET":"AI 資料中心交換器龍頭,800G 放量直接對應台股 CCL/光通訊景氣。",
}

def clamp(x, lo=0, hi=100): return int(max(lo, min(hi, round(x))))
def pct(a, b): return (a - b) / b * 100 if b else 0.0
def numf(s):
    try:
        v = str(s).replace(",", "").strip()
        return None if v in ("", "--", "-", "N/A", "nan") else float(v)
    except ValueError:
        return None

def get_json(url, params=None, timeout=30):
    return requests.get(url, params=params, headers=UA, timeout=timeout).json()

def _pick(fields, *needles):
    for i, f in enumerate(fields):
        if all(n in str(f) for n in needles): return i
    return None

# ═══════════════ 名單:台股全上市上櫃 + S&P 500 ═══════════════
def fetch_tw_companies():
    out = []
    for url, ex in (("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "tse"),
                    ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "otc")):
        try:
            arr = get_json(url, timeout=60)
            keys = list(arr[0].keys())
            k_id  = next((k for k in keys if "代號" in k), None)
            k_ab  = next((k for k in keys if "簡稱" in k), None)
            k_full= next((k for k in keys if k.endswith("名稱") and "簡稱" not in k), k_ab)
            k_ind = next((k for k in keys if "產業" in k), None)
            n = 0
            for r in arr:
                sid = str(r.get(k_id, "")).strip()
                if not (sid.isdigit() and len(sid) == 4): continue
                ind = str(r.get(k_ind, "")).strip()
                sector = TW_IND.get(ind, ind if ind else "未分類")
                out.append({"id": sid, "name": str(r.get(k_ab, sid)).strip(),
                            "full": str(r.get(k_full, "")).strip(),
                            "market": "TW", "ex": ex, "sector": sector})
                n += 1
            print(f"  {'上市' if ex=='tse' else '上櫃'}公司:{n} 檔")
        except Exception as e:
            print(f"  [warn] 公司名單 {ex}: {e}")
    return out

def fetch_us_companies():
    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
    df = pd.read_csv(StringIO(requests.get(url, headers=UA, timeout=30).text))
    out = []
    for _, r in df.iterrows():
        sym = str(r["Symbol"]).strip().replace(".", "-")
        out.append({"id": sym, "name": str(r["Security"]),
                    "full": f'{r["Security"]}|{r["GICS Sub-Industry"]}',
                    "market": "US", "ex": "us",
                    "sector": GICS_ZH.get(str(r["GICS Sector"]).strip(), "美股·其他")})
    print(f"  S&P 500 成分股:{len(out)} 檔")
    return out

# ═══════════════ K線分片存取 ═══════════════
def shard_name(s):
    return f"tw{s['id'][0]}.json" if s["market"] == "TW" else f"us_{s['id'][0].lower()}.json"

def load_hist():
    hist = {}
    for fp in glob.glob(os.path.join(K_DIR, "*.json")):
        try:
            with open(fp, encoding="utf-8") as f:
                hist.update(json.load(f))
        except Exception: pass
    print(f"  既有 K 線:{len(hist)} 檔")
    return hist

def save_hist(hist, comps):
    os.makedirs(K_DIR, exist_ok=True)
    shards = {}
    by_id = {c["id"]: c for c in comps}
    for sid, v in hist.items():
        c = by_id.get(sid)
        if not c: continue
        shards.setdefault(shard_name(c), {})[sid] = v
    for fn, obj in shards.items():
        with open(os.path.join(K_DIR, fn), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  K 線分片:寫出 {len(shards)} 個檔案")

def append_bar(hist, sid, date, o, h, l, c, v):
    e = hist.setdefault(sid, {"d": [], "o": []})
    if e["d"] and date <= e["d"][-1]: return
    e["d"].append(date); e["o"].append([o, h, l, c, v])
    if len(e["d"]) > KEEP_BARS:
        e["d"] = e["d"][-KEEP_BARS:]; e["o"] = e["o"][-KEEP_BARS:]

# ═══════════════ 台股整市場日行情 ═══════════════
def twse_day_all(d):
    """證交所 MI_INDEX:單一日期、全部上市個股。回傳 {sid:(o,h,l,c,v張)}"""
    try:
        j = get_json("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                     {"date": d.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"})
        if j.get("stat") != "OK": return {}
        for tb in j.get("tables", []):
            flds = tb.get("fields", [])
            if _pick(flds, "證券代號") is not None and _pick(flds, "收盤價") is not None:
                i_id, i_v = _pick(flds, "證券代號"), _pick(flds, "成交股數")
                i_o, i_h = _pick(flds, "開盤價"), _pick(flds, "最高價")
                i_l, i_c = _pick(flds, "最低價"), _pick(flds, "收盤價")
                out = {}
                for r in tb.get("data", []):
                    sid = str(r[i_id]).strip()
                    o, h, l, c = numf(r[i_o]), numf(r[i_h]), numf(r[i_l]), numf(r[i_c])
                    if None in (o, h, l, c): continue
                    out[sid] = (o, h, l, c, int((numf(r[i_v]) or 0) // 1000))
                return out
        return {}
    except Exception as e:
        print(f"  [warn] MI_INDEX {d}: {e}")
        return {}

def tpex_day_all(d):
    """櫃買日行情:單一日期、全部上櫃。回傳 {sid:(o,h,l,c,v張)}"""
    out = {}
    try:  # 新版
        j = get_json("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc",
                     {"date": d.strftime("%Y/%m/%d"), "type": "EW", "response": "json"})
        for tb in j.get("tables", []):
            flds = tb.get("fields", [])
            i_id = _pick(flds, "代號")
            i_c, i_o = _pick(flds, "收盤"), _pick(flds, "開盤")
            i_h, i_l = _pick(flds, "最高"), _pick(flds, "最低")
            i_v = _pick(flds, "成交股數")
            if None in (i_id, i_c, i_o, i_h, i_l): continue
            for r in tb.get("data", []):
                sid = str(r[i_id]).strip()
                if not (sid.isdigit() and len(sid) == 4): continue
                o, h, l, c = numf(r[i_o]), numf(r[i_h]), numf(r[i_l]), numf(r[i_c])
                if None in (o, h, l, c): continue
                v = numf(r[i_v]) if i_v is not None else 0
                out[sid] = (o, h, l, c, int((v or 0) // 1000))
        if out: return out
    except Exception: pass
    try:  # 舊版 stk_wn1430:欄位順序 [代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數,...]
        j = get_json("https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php",
                     {"l": "zh-tw", "d": f"{d.year-1911}/{d.month:02d}/{d.day:02d}", "se": "EW"})
        for r in j.get("aaData", []):
            sid = str(r[0]).strip()
            if not (sid.isdigit() and len(sid) == 4): continue
            c, o, h, l = numf(r[2]), numf(r[4]), numf(r[5]), numf(r[6])
            if None in (o, h, l, c): continue
            out[sid] = (o, h, l, c, int((numf(r[8]) or 0) // 1000))
    except Exception as e:
        print(f"  [warn] 櫃買日行情 {d}: {e}")
    return out

def update_tw_prices(hist):
    """回補/增量:找出缺少的交易日,一天兩個呼叫補齊全市場。"""
    last = max((v["d"][-1] for v in hist.values() if v["d"]), default=None)
    if last:
        start = dt.datetime.strptime(last, "%Y-%m-%d").date() + dt.timedelta(days=1)
        lookback = (TODAY - start).days + 1
        print(f"  增量模式:自 {start} 起補")
    else:
        lookback = 190
        print("  首次執行:回補約 130 個交易日(需 10~15 分鐘,只有第一次)")
    dates = [TODAY - dt.timedelta(days=i) for i in range(lookback)][::-1]
    got = 0
    for d in dates:
        if d.weekday() >= 5: continue
        tw = twse_day_all(d)
        if not tw:
            time.sleep(1.2); continue
        ds = d.strftime("%Y-%m-%d")
        for sid, (o, h, l, c, v) in tw.items():
            append_bar(hist, sid, ds, o, h, l, c, v)
        time.sleep(1.0)
        otc = tpex_day_all(d)
        for sid, (o, h, l, c, v) in otc.items():
            append_bar(hist, sid, ds, o, h, l, c, v)
        got += 1
        print(f"  {ds}:上市 {len(tw)} 檔、上櫃 {len(otc)} 檔")
        time.sleep(1.5)
    print(f"  台股價格:本次補 {got} 個交易日")

# ═══════════════ 美股價格(批次)═══════════════
def update_us_prices(hist, us_comps):
    syms = [c["id"] for c in us_comps]
    ok = set()
    try:
        import yfinance as yf
        for i in range(0, len(syms), 100):
            chunk = syms[i:i+100]
            try:
                df = yf.download(chunk, period="7mo", interval="1d",
                                 group_by="ticker", threads=True, progress=False)
                for sym in chunk:
                    try:
                        sub = df[sym].dropna() if len(chunk) > 1 else df.dropna()
                        if len(sub) < 20: continue
                        e = {"d": [], "o": []}
                        for idx, r in sub.tail(KEEP_BARS).iterrows():
                            e["d"].append(str(idx)[:10])
                            e["o"].append([round(float(r["Open"]),2), round(float(r["High"]),2),
                                           round(float(r["Low"]),2), round(float(r["Close"]),2),
                                           int(r.get("Volume") or 0)])
                        hist[sym] = e; ok.add(sym)
                    except Exception: continue
                print(f"  美股批次 {i//100+1}:累計 {len(ok)} 檔")
            except Exception as e:
                print(f"  [warn] yfinance 批次: {e}")
            time.sleep(2)
    except Exception as e:
        print(f"  [warn] yfinance: {e}")
    # Stooq 只救少量缺漏,避免觸發它的每日上限
    missing = [s for s in syms if s not in ok][:40]
    for sym in missing:
        try:
            d1 = (TODAY - dt.timedelta(days=230)).strftime("%Y%m%d")
            df = pd.read_csv(StringIO(requests.get(
                f"https://stooq.com/q/d/l/?s={sym.lower()}.us&d1={d1}&d2={TODAY:%Y%m%d}&i=d",
                headers=UA, timeout=20).text))
            if "Close" not in df.columns or len(df) < 20: continue
            e = {"d": [], "o": []}
            for _, r in df.tail(KEEP_BARS).iterrows():
                e["d"].append(str(r["Date"])[:10])
                e["o"].append([round(float(r["Open"]),2), round(float(r["High"]),2),
                               round(float(r["Low"]),2), round(float(r["Close"]),2),
                               int(r.get("Volume") or 0)])
            hist[sym] = e; ok.add(sym)
            time.sleep(0.6)
        except Exception: continue
    print(f"  美股價格:{len(ok)}/{len(syms)} 檔")

# ═══════════════ 官方彙總:營收 / 法人 / 大戶 ═══════════════
def fetch_rev_bulk():
    out = {}
    for url in ("https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
                "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"):
        try:
            arr = get_json(url, timeout=60)
            keys = list(arr[0].keys())
            k_id  = next((k for k in keys if "代號" in k), None)
            k_yoy = next((k for k in keys if "去年同月增減" in k), None)
            k_ym  = next((k for k in keys if "資料年月" in k), None)
            for r in arr:
                sid, yoy = str(r.get(k_id, "")).strip(), numf(r.get(k_yoy))
                if sid and yoy is not None:
                    out[sid] = (yoy, str(r.get(k_ym, "")))
        except Exception as e:
            print(f"  [warn] 營收彙總: {e}")
    print(f"  月營收:{len(out)} 家")
    return out

def fetch_inst_bulk(days=5, max_try=12):
    agg, got, d = {}, 0, TODAY
    for _ in range(max_try):
        ds = d.strftime("%Y%m%d")
        try:
            j = get_json("https://www.twse.com.tw/rwd/zh/fund/T86",
                         {"date": ds, "selectType": "ALLBUT0999", "response": "json"})
            if j.get("stat") == "OK" and j.get("data"):
                flds = j["fields"]
                i_id = _pick(flds, "證券代號")
                i_f  = _pick(flds, "外陸資買賣超", "不含")
                if i_f is None: i_f = _pick(flds, "外陸資買賣超")
                i_t  = _pick(flds, "投信買賣超")
                for r in j["data"]:
                    e = agg.setdefault(str(r[i_id]).strip(), {"f5": 0.0, "t5": 0.0})
                    e["f5"] += (numf(r[i_f]) or 0) / 1000
                    e["t5"] += (numf(r[i_t]) or 0) / 1000
                try:
                    j2 = get_json("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",
                                  {"type": "Daily", "sect": "EW",
                                   "date": d.strftime("%Y/%m/%d"), "response": "json"})
                    for tb in j2.get("tables", []):
                        flds2 = tb.get("fields", [])
                        i2_id = _pick(flds2, "代號")
                        i2_f  = _pick(flds2, "外資", "買賣超")
                        i2_t  = _pick(flds2, "投信", "買賣超")
                        if None in (i2_id, i2_f, i2_t): continue
                        for r in tb.get("data", []):
                            e = agg.setdefault(str(r[i2_id]).strip(), {"f5": 0.0, "t5": 0.0})
                            e["f5"] += (numf(r[i2_f]) or 0) / 1000
                            e["t5"] += (numf(r[i2_t]) or 0) / 1000
                except Exception as e2:
                    print(f"  [warn] 櫃買法人 {ds}: {e2}")
                got += 1
                if got >= days: break
        except Exception as e:
            print(f"  [warn] T86 {ds}: {e}")
        d -= dt.timedelta(days=1)
        time.sleep(2.0)
    print(f"  三大法人:{got} 個交易日、{len(agg)} 檔")
    return agg

def fetch_tdcc_bulk():
    try:
        r = requests.get("https://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
                         headers=UA, timeout=180)
        df = pd.read_csv(StringIO(r.text), dtype=str)
        col_date = next(c for c in df.columns if "日期" in c)
        col_id   = next(c for c in df.columns if "代號" in c)
        col_lv   = next(c for c in df.columns if "分級" in c)
        col_pc   = next(c for c in df.columns if "比例" in c)
        date = str(df[col_date].iloc[0])
        big = df[df[col_lv].astype(str).str.strip().isin(["12","13","14","15"])].copy()
        big[col_pc] = pd.to_numeric(big[col_pc], errors="coerce")
        out = big.groupby(big[col_id].str.strip())[col_pc].sum().round(2).to_dict()
        print(f"  TDCC 大戶:{len(out)} 檔,資料日期 {date}")
        return out, date
    except Exception as e:
        print(f"  [warn] TDCC: {e}")
        return {}, ""

def load_prev():
    try:
        with open("data.json", encoding="utf-8") as f:
            old = json.load(f)
        return {s["id"]: (s.get("c", {}).get("raw") or {}) for s in old.get("stocks", [])}
    except Exception:
        return {}

# ═══════════════ 評分與訊號 ═══════════════
def avg(a): return sum(a) / len(a)

def score_stock(c, bars, rev_bulk, inst, tdcc, tdcc_date, prev):
    sid, is_tw = c["id"], c["market"] == "TW"
    o = bars["o"]; closes = [x[3] for x in o]; vols = [x[4] for x in o]
    last = closes[-1]; prev_c = closes[-2] if len(closes) > 1 else last
    n = len(closes)
    out = {"price": round(last, 2), "chg": round(pct(last, prev_c), 2)}

    # 技術面
    if n >= 60:
        ma20, ma60 = avg(closes[-20:]), avg(closes[-60:])
        bias20 = pct(last, ma20)
        vol_ratio = (avg(vols[-5:]) / max(avg(vols[-20:]), 1)) if n >= 20 else 1
        above20, bull = last > ma20, ma20 > ma60
        t = 50 + (12 if above20 else -12) + (12 if bull else -12)
        t += 8 if 0 < bias20 <= 6 else (-6 if bias20 > 10 else (-8 if bias20 < -5 else 0))
        t += 6 if vol_ratio > 1.15 and above20 else 0
        out["t"] = {"score": clamp(t), "kv": {
            "收盤": f"{last:.2f}", "站上20MA": "是" if above20 else "否",
            "20/60MA": "多頭排列" if bull else "空方/糾結",
            "乖離(20MA)": f"{bias20:+.1f}%"},
            "note": ("多頭排列。" if bull else "均線偏弱。")}
    else:
        ma20 = avg(closes[-min(20, n):]); ma60 = ma20; bull = None
        out["t"] = {"score": 50, "kv": {"K線累積": f"{n}/60 天"},
                    "note": "K線資料累積中,滿60天後開始評分。"}

    # 基本面(台股)
    f, f_kv = 50, {}
    if is_tw and sid in rev_bulk:
        yoy, ym = rev_bulk[sid]
        f_kv["月營收YoY"], f_kv["資料年月"] = f"{yoy:+.1f}%", ym
        f += 25 if yoy > 40 else 18 if yoy > 20 else 8 if yoy > 5 else -5 if yoy > -10 else -18
    elif not is_tw:
        f_kv["財報"] = "點下方外部連結查閱"
    out["f"] = {"score": clamp(f), "kv": f_kv or {"月營收": "—"},
                "note": "營收動能強勁。" if f >= 70 else "營收平穩。" if f >= 50 else "營收轉弱。"}

    # 籌碼面
    cs, c_kv, c_raw = 50, {}, {}
    if is_tw:
        if sid in inst:
            f5, t5 = inst[sid]["f5"], inst[sid]["t5"]
            c_kv["外資5日"], c_kv["投信5日"] = f"{f5:+,.0f} 張", f"{t5:+,.0f} 張"
            c_raw["f5"], c_raw["t5"] = int(f5), int(t5)
            cs += 15 if f5 > 0 else -10
            cs += 12 if t5 > 0 else (-6 if t5 < 0 else 0)
        if sid in tdcc:
            big = tdcc[sid]; c_raw["big"], c_raw["big_date"] = big, tdcc_date
            p = prev.get(sid, {})
            if p.get("big") is not None and p.get("big_date") and p["big_date"] != tdcc_date:
                c_raw["bigw"] = round(big - p["big"], 2)
            elif p.get("bigw") is not None and p.get("big_date") == tdcc_date:
                c_raw["bigw"] = p["bigw"]
            if "bigw" in c_raw:
                c_kv["400張大戶"] = f"{big:.1f}%(週{c_raw['bigw']:+.2f})"
                cs += 12 if c_raw["bigw"] > 0 else -8
            else:
                c_kv["400張大戶"] = f"{big:.1f}%"
    else:
        hi130 = max(x[1] for x in o)
        off = pct(last, hi130)
        c_kv["距波段高點"] = f"{off:+.1f}%"
        cs += 10 if off > -8 else (-8 if off < -20 else 0)
    out["c"] = {"score": clamp(cs), "kv": c_kv or {"籌碼": "—"}, "raw": c_raw,
                "note": "籌碼偏多。" if cs >= 68 else "籌碼中性。" if cs >= 45 else "籌碼偏空。"}

    # 訊號(伺服器端計算,首頁機會雷達直接使用)
    T = round(out["f"]["score"]*0.40 + out["c"]["score"]*0.35 + out["t"]["score"]*0.25)
    sig = []
    if c_raw.get("bigw", 0) >= 0.7:
        sig.append({"type": "whale", "label": "大戶進場",
            "desc": f"400張大戶持股週增 +{c_raw['bigw']:.2f} 個百分點"
                    + (",投信同步買超" if c_raw.get("t5", 0) > 0 else "")})
    if n >= 60:
        c60 = closes[-60:]
        prior = c60[-45:-5] if len(c60) >= 45 else c60[:-5]
        if prior:
            hi, lo = max(prior), min(prior)
            if last > hi and lo and (hi - lo) / lo < 0.15 and T >= 65:
                sig.append({"type": "break", "label": "突破整理區",
                    "desc": f"站上平台高點 {hi:.1f},整理區間僅 {(hi-lo)/lo*100:.0f}%,綜合 {T} 分"})
        h20 = max(c60[-20:]); ma60_v = avg(c60)
        off = pct(last, h20); d60 = pct(last, ma60_v)
        if T >= 64 and off <= -7 and -4 <= d60 <= 4:
            sig.append({"type": "dip", "label": "下殺近關鍵價",
                "desc": f"自波段高點回檔 {abs(off):.0f}%,回測季線 {ma60_v:.1f} 附近,綜合 {T} 分"})
        if T >= 78 and last > ma20 and bull:
            sig.append({"type": "strong", "label": "三力強勢",
                "desc": f"綜合 {T} 分,多頭排列沿 20MA 推進"})
    if sig: out["sig"] = sig
    return out

# ═══════════════ 市場總覽 / 新聞 ═══════════════
def stooq_index(sym):
    d1 = (TODAY - dt.timedelta(days=15)).strftime("%Y%m%d")
    df = pd.read_csv(StringIO(requests.get(
        f"https://stooq.com/q/d/l/?s={sym}&d1={d1}&d2={TODAY:%Y%m%d}&i=d",
        headers=UA, timeout=20).text))
    if "Close" not in df.columns or len(df) < 2: return None
    v, p = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
    return round(v, 2), round(pct(v, p), 2)

def fetch_macro():
    idx = []
    try:
        arr = get_json("https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK", timeout=30)
        if len(arr) >= 2:
            v, p = numf(arr[-1].get("TAIEX")), numf(arr[-2].get("TAIEX"))
            if v and p: idx.append({"name": "加權指數", "val": v, "chg": round(pct(v, p), 2)})
    except Exception as e:
        print(f"  [warn] 加權指數: {e}")
    for name, sym in [("S&P 500", "^spx"), ("那斯達克", "^ndq"), ("費城半導體", "^sox")]:
        try:
            r = stooq_index(sym)
            if r: idx.append({"name": name, "val": r[0], "chg": r[1]})
        except Exception: pass
    fx = {}
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=20).json()["rates"]
        fx = {"USDTWD": round(r["TWD"], 3), "JPYTWD": round(r["TWD"]/r["JPY"], 4),
              "EURTWD": round(r["TWD"]/r["EUR"], 3), "USDJPY": round(r["JPY"], 2)}
    except Exception as e:
        print(f"  [warn] 匯率: {e}")
    return {"idx": idx, "fx": fx}

def fetch_news(n=10):
    import xml.etree.ElementTree as ET, html as H
    url = ("https://news.google.com/rss/search?"
           "q=%E5%8F%B0%E8%82%A1%20OR%20%E5%8F%B0%E7%A9%8D%E9%9B%BB%20OR%20%E7%BE%8E%E8%82%A1%20OR%20%E8%81%AF%E6%BA%96%E6%9C%83"
           "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
    items = []
    try:
        root = ET.fromstring(requests.get(url, headers=UA, timeout=20).content)
        for it in root.iter("item"):
            title = H.unescape(it.findtext("title") or "")
            parts = title.rsplit(" - ", 1)
            items.append({"title": parts[0], "source": parts[1] if len(parts) > 1 else "",
                          "link": it.findtext("link") or "#",
                          "time": (it.findtext("pubDate") or "")[5:16]})
            if len(items) >= n: break
    except Exception as e:
        print(f"  [warn] 新聞: {e}")
    return items

# ═══════════════ 主流程 ═══════════════
def main():
    print("① 讀取名單與既有 K 線 ...")
    comps = fetch_tw_companies() + fetch_us_companies()
    hist = load_hist()
    prev = load_prev()

    print("② 更新價格(台股逐日累積 / 美股批次)...")
    update_tw_prices(hist)
    update_us_prices(hist, [c for c in comps if c["market"] == "US"])
    save_hist(hist, comps)

    print("③ 官方彙總:營收 / 法人 / 大戶 ...")
    rev_bulk = fetch_rev_bulk()
    inst = fetch_inst_bulk()
    tdcc, tdcc_date = fetch_tdcc_bulk()

    print("④ 計算評分與訊號 ...")
    stocks, ok = [], 0
    for c in comps:
        bars = hist.get(c["id"])
        if bars and len(bars.get("o", [])) >= 2:
            try:
                d = score_stock(c, bars, rev_bulk, inst, tdcc, tdcc_date, prev)
                ok += 1
            except Exception as e:
                print(f"  [error] {c['id']}: {e}")
                d = {"price": None, "chg": 0,
                     "f": {"score": 50, "kv": {"狀態": "計算失敗"}, "note": ""},
                     "c": {"score": 50, "kv": {}, "note": "", "raw": {}},
                     "t": {"score": 50, "kv": {}, "note": ""}}
        else:
            d = {"price": None, "chg": 0,
                 "f": {"score": 50, "kv": {"狀態": "資料暫缺"}, "note": "等下次更新"},
                 "c": {"score": 50, "kv": {}, "note": "", "raw": {}},
                 "t": {"score": 50, "kv": {}, "note": ""}}
        d.update({"id": c["id"], "name": c["name"], "full": c["full"],
                  "market": c["market"], "ex": c["ex"], "sector": c["sector"]})
        if c["id"] in THESIS: d["thesis"] = THESIS[c["id"]]
        stocks.append(d)

    print("⑤ 市場總覽與新聞 ...")
    out = {"updated": TODAY.strftime("%Y-%m-%d"), "source": "live",
           "macro": fetch_macro(), "news": fetch_news(), "stocks": stocks}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    sz = os.path.getsize("data.json") // 1024
    print(f"完成:{len(stocks)} 檔({ok} 檔有完整數據),data.json {sz}KB")

if __name__ == "__main__":
    main()
