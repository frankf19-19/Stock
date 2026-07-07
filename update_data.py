# -*- coding: utf-8 -*-
"""
update_data.py v4 — 三力選股儀表板(全市場版)
涵蓋:台股全部上市+上櫃(約1,800檔)+ 美股 S&P 500 全成分股(約500檔)
產業:台股用證交所官方「產業別」、美股用 GICS 分類
輸出:data.json(清單+評分+訊號)、k/*.json(K線分片)、c/*.json(籌碼歷史分片:法人65日/大戶26週/營收13月)

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

# ── 籌碼歷史(v5 新增):法人逐日 / 大戶逐週 / 營收逐月,分片存 c/*.json ──
C_DIR = "c"            # 籌碼歷史分片資料夾
CHIP_DAYS = 65         # 法人買賣超保留 65 個交易日(約 3 個月)
BIG_WEEKS = 26         # 400張大戶保留 26 週(約半年)
REV_MONTHS = 26        # 月營收保留 26 個月(兩年以上年增趨勢)
CHIP_BACKFILL = 70     # 單次執行最多回補幾個交易日的法人資料(首次執行約需 7 分鐘)

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
    """主要來源:GitHub 開放資料集(twstock codes,含產業別);備援:官方 OpenAPI。
    註:證交所/櫃買官方 API 會封鎖海外雲端 IP,GitHub Actions 機房常被擋。"""
    out = []
    for url, ex in (("https://raw.githubusercontent.com/mlouielu/twstock/master/twstock/codes/twse_equities.csv", "tse"),
                    ("https://raw.githubusercontent.com/mlouielu/twstock/master/twstock/codes/tpex_equities.csv", "otc")):
        try:
            df = pd.read_csv(StringIO(requests.get(url, headers=UA, timeout=40).text))
            df = df[(df["type"] == "股票")]
            n = 0
            for _, r in df.iterrows():
                sid = str(r["code"]).strip()
                if not (sid.isdigit() and len(sid) == 4): continue
                grp = str(r.get("group", "")).strip()
                out.append({"id": sid, "name": str(r["name"]).strip(),
                            "full": str(r["name"]).strip(),
                            "market": "TW", "ex": ex,
                            "sector": grp if grp and grp != "nan" else "未分類"})
                n += 1
            print(f"  {'上市' if ex=='tse' else '上櫃'}(開放資料集):{n} 檔")
        except Exception as e:
            print(f"  [warn] 名單資料集 {ex}: {e}")
    if len(out) > 500:
        return out
    # 備援:官方 OpenAPI(在台灣本機執行時可用)
    print("  → 改用官方 OpenAPI 名單")
    out = []
    for url, ex in (("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "tse"),
                    ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "otc")):
        try:
            arr = get_json(url, timeout=60)
            keys = list(arr[0].keys())
            k_id  = next((k for k in keys if "代號" in k), None)
            k_ab  = next((k for k in keys if "簡稱" in k), None)
            k_ind = next((k for k in keys if "產業" in k), None)
            for r in arr:
                sid = str(r.get(k_id, "")).strip()
                if not (sid.isdigit() and len(sid) == 4): continue
                ind = str(r.get(k_ind, "")).strip()
                out.append({"id": sid, "name": str(r.get(k_ab, sid)).strip(),
                            "full": str(r.get(k_ab, sid)).strip(), "market": "TW", "ex": ex,
                            "sector": TW_IND.get(ind, ind if ind else "未分類")})
        except Exception as e:
            print(f"  [warn] 官方名單 {ex}: {e}")
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
    # 補充:台廠 ADR + 費半非 S&P500 成分 + 重點外籍半導體(S&P500 名單天生沒有外國公司)
    EXTRA_US = [
        ("TSM",  "台積電 ADR",       "美股·資訊科技"),
        ("UMC",  "聯電 ADR",         "美股·資訊科技"),
        ("ASX",  "日月光 ADR",       "美股·資訊科技"),
        ("CHT",  "中華電信 ADR",     "美股·通訊服務"),
        ("HIMX", "奇景光電 ADR",     "美股·資訊科技"),
        ("SIMO", "慧榮科技 ADR",     "美股·資訊科技"),
        ("ASML", "ASML 艾司摩爾",    "美股·資訊科技"),
        ("ARM",  "Arm Holdings",     "美股·資訊科技"),
        ("GFS",  "GlobalFoundries",  "美股·資訊科技"),
        ("STM",  "意法半導體",       "美股·資訊科技"),
        ("AMKR", "Amkor 艾克爾",     "美股·資訊科技"),
        ("ONTO", "Onto Innovation",  "美股·資訊科技"),
        ("LSCC", "Lattice 萊迪思",   "美股·資訊科技"),
        ("ALAB", "Astera Labs",      "美股·資訊科技"),
        ("CRDO", "Credo",            "美股·資訊科技"),
        ("RMBS", "Rambus",           "美股·資訊科技"),
        ("MSTR", "MicroStrategy",    "美股·資訊科技"),
        ("IONQ", "IonQ 量子運算",    "美股·資訊科技"),
    ]
    have = {o["id"] for o in out}
    added = 0
    for sym, nm, sec in EXTRA_US:
        if sym not in have:
            out.append({"id": sym, "name": nm, "full": nm,
                        "market": "US", "ex": "us", "sector": sec})
            added += 1
    print(f"  S&P 500 成分股:{len(out)-added} 檔 + 補充 {added} 檔(台廠ADR/費半/外籍半導體)")
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

# ═══════════════ 籌碼歷史分片(法人日資料 / 大戶週資料 / 月營收)═══════════════
# 每檔結構:{"d":[日期],"f":[外資張],"t":[投信張],"g":[自營張],
#            "bd":[大戶週日期],"bp":[大戶持股%],
#            "rm":[營收年月],"ry":[YoY%],"ra":[當月營收(千元)]}
def load_chips():
    chips, meta = {}, {"dates": []}
    for fp in glob.glob(os.path.join(C_DIR, "*.json")):
        try:
            with open(fp, encoding="utf-8") as f:
                obj = json.load(f)
            if os.path.basename(fp) == "meta.json": meta = obj
            else: chips.update(obj)
        except Exception: pass
    print(f"  既有籌碼歷史:{len(chips)} 檔、{len(meta.get('dates', []))} 個交易日")
    return chips, meta

def save_chips(chips, meta, comps):
    os.makedirs(C_DIR, exist_ok=True)
    tw_ids = {c["id"] for c in comps if c["market"] == "TW"}
    shards = {}
    for sid, v in chips.items():
        if sid not in tw_ids: continue
        shards.setdefault(f"tw{sid[0]}.json", {})[sid] = v
    for fn, obj in shards.items():
        with open(os.path.join(C_DIR, fn), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(C_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print(f"  籌碼分片:寫出 {len(shards)} 個檔案")

def fetch_inst_day(d):
    """抓單一交易日全市場三大法人買賣超(單位:張)。回傳 {sid:[外資,投信,自營]};非交易日回 None。"""
    ds = d.strftime("%Y%m%d")
    day = {}
    try:
        j = get_json("https://www.twse.com.tw/rwd/zh/fund/T86",
                     {"date": ds, "selectType": "ALLBUT0999", "response": "json"})
    except Exception as e:
        print(f"  [warn] T86 {ds}: {e}"); return None
    if j.get("stat") != "OK" or not j.get("data"): return None
    flds = j["fields"]
    i_id = _pick(flds, "證券代號")
    i_f  = _pick(flds, "外陸資買賣超", "不含")
    if i_f is None: i_f = _pick(flds, "外陸資買賣超")
    i_t  = _pick(flds, "投信買賣超")
    i_g  = next((i for i, f in enumerate(flds) if str(f).strip() == "自營商買賣超股數"), None)
    if i_g is None: i_g = _pick(flds, "自營商買賣超")
    def sh2lot(x): return int(round((x or 0) / 1000))
    for r in j["data"]:
        day[str(r[i_id]).strip()] = [sh2lot(numf(r[i_f])), sh2lot(numf(r[i_t])),
                                     sh2lot(numf(r[i_g])) if i_g is not None else 0]
    try:
        j2 = get_json("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",
                      {"type": "Daily", "sect": "EW",
                       "date": d.strftime("%Y/%m/%d"), "response": "json"})
        for tb in j2.get("tables", []):
            flds2 = tb.get("fields", [])
            i2_id = _pick(flds2, "代號")
            i2_f  = _pick(flds2, "外資", "買賣超")
            i2_t  = _pick(flds2, "投信", "買賣超")
            i2_g  = _pick(flds2, "自營", "買賣超")
            if None in (i2_id, i2_f, i2_t): continue
            for r in tb.get("data", []):
                day[str(r[i2_id]).strip()] = [sh2lot(numf(r[i2_f])), sh2lot(numf(r[i2_t])),
                                              sh2lot(numf(r[i2_g])) if i2_g is not None else 0]
    except Exception as e2:
        print(f"  [warn] 櫃買法人 {ds}: {e2}")
    return day

def fetch_mkt_day(d):
    """大盤三大法人買賣超金額(億,集中市場 BFI82U)。回傳 [外資,投信,自營] 或 None。"""
    ds = d.strftime("%Y%m%d")
    try:
        j = get_json("https://www.twse.com.tw/rwd/zh/fund/BFI82U",
                     {"dayDate": ds, "type": "day", "response": "json"})
        if j.get("stat") != "OK" or not j.get("data"): return None
        f = t = g = 0.0
        for r in j["data"]:
            name, net = str(r[0]), (numf(r[3]) or 0) / 1e8
            if "外資" in name: f += net
            elif "投信" in name: t += net
            elif "自營" in name: g += net
        return [round(f, 1), round(t, 1), round(g, 1)]
    except Exception as e:
        print(f"  [warn] BFI82U {ds}: {e}")
        return None

def update_chip_hist(chips, meta):
    """回補/續抓法人逐日資料,累積至 CHIP_DAYS 個交易日。同步累積大盤法人買賣金額(meta['mkt'])。"""
    have = set(meta.get("dates", []))
    want, d, walked = [], TODAY, 0
    while walked < 110 and len(want) < CHIP_BACKFILL and (len(have) + len(want)) < CHIP_DAYS + 4:
        if d.weekday() < 5 and d.isoformat() not in have:
            want.append(d)
        d -= dt.timedelta(days=1); walked += 1
    newdays, newmkt = {}, {}
    for d in sorted(want):
        day = fetch_inst_day(d)
        time.sleep(1.2)
        if day:
            iso = d.isoformat()
            newdays[iso] = day
            have.add(iso)
            mk = fetch_mkt_day(d)
            if mk: newmkt[iso] = mk
            time.sleep(1.2)
    if newdays:
        allsids = set()
        for x in newdays.values(): allsids |= set(x)
        for sid in allsids:
            e = chips.setdefault(sid, {})
            g_old = e.get("g") or [0] * len(e.get("d", []))
            m = {dd: [e["f"][i], e["t"][i], g_old[i]] for i, dd in enumerate(e.get("d", []))}
            for dd, day in newdays.items():
                if sid in day: m[dd] = day[sid]
            ds = sorted(m)[-CHIP_DAYS:]
            e["d"] = ds
            e["f"] = [m[x][0] for x in ds]
            e["t"] = [m[x][1] for x in ds]
            e["g"] = [m[x][2] for x in ds]
    # 大盤法人歷史(供首頁總經卡片點入的詳細頁使用)
    mk_old = meta.get("mkt") or {"d": [], "f": [], "t": [], "g": []}
    mm = {dd: [mk_old["f"][i], mk_old["t"][i], mk_old["g"][i]] for i, dd in enumerate(mk_old.get("d", []))}
    mm.update(newmkt)
    mds = sorted(mm)[-CHIP_DAYS:]
    meta["mkt"] = {"d": mds, "f": [mm[x][0] for x in mds],
                   "t": [mm[x][1] for x in mds], "g": [mm[x][2] for x in mds]}
    meta["dates"] = sorted(have)[-CHIP_DAYS:]
    print(f"  法人日資料:本次新增 {len(newdays)} 個交易日,累積 {len(meta['dates'])} 日(大盤金額 {len(mds)} 日)")

def append_tdcc(chips, tdcc, date):
    """400張大戶週資料:每次執行把最新一週附加進歷史(同週覆蓋)。"""
    if not tdcc or not date: return
    for sid, p in tdcc.items():
        e = chips.setdefault(sid, {})
        bd, bp = e.setdefault("bd", []), e.setdefault("bp", [])
        if bd and bd[-1] == date:
            bp[-1] = p; continue
        bd.append(date); bp.append(p)
        if len(bd) > BIG_WEEKS:
            e["bd"], e["bp"] = bd[-BIG_WEEKS:], bp[-BIG_WEEKS:]

def append_rev(chips, rev_bulk):
    """月營收:每月附加一筆(同月覆蓋),保留 REV_MONTHS 個月。"""
    for sid, v in rev_bulk.items():
        yoy, ym = v[0], v[1]
        amt = v[2] if len(v) > 2 else None
        if not ym: continue
        e = chips.setdefault(sid, {})
        rm, ry, ra = e.setdefault("rm", []), e.setdefault("ry", []), e.setdefault("ra", [])
        while len(ra) < len(rm): ra.append(None)
        if rm and rm[-1] == ym:
            ry[-1] = yoy; ra[-1] = amt; continue
        rm.append(ym); ry.append(yoy); ra.append(amt)
        if len(rm) > REV_MONTHS:
            e["rm"], e["ry"], e["ra"] = rm[-REV_MONTHS:], ry[-REV_MONTHS:], ra[-REV_MONTHS:]

def latest_rev(sid, rev_bulk, chips):
    """回傳該股「最新月份」的 (YoY, 年月, 金額):比較本次官方彙總與站內逐月歷史,
    一律取月份較新者。避免某次來源抓失敗時,基本面卡片倒退回舊月份、與營收趨勢圖不同步。"""
    rv = rev_bulk.get(sid)                       # (yoy, ym, amt) 或 None
    e = (chips or {}).get(sid) or {}
    rm, ry = e.get("rm") or [], e.get("ry") or []
    if rm and ry and ry[-1] is not None:
        if (not rv) or (str(rm[-1]) > str(rv[1] or "")):
            ra = e.get("ra") or []
            rv = (ry[-1], rm[-1], ra[-1] if ra else None)
    return rv

def build_inst(chips):
    """從籌碼歷史彙算 5/20/60 日合計與外資連買天數,供評分與前端摘要。"""
    inst = {}
    for sid, e in chips.items():
        f, t, g = e.get("f") or [], e.get("t") or [], e.get("g") or []
        if not f: continue
        st = 0
        for v in reversed(f):
            if v > 0: st += 1
            else: break
        inst[sid] = {"f5": sum(f[-5:]), "t5": sum(t[-5:]),
                     "f20": sum(f[-20:]), "t20": sum(t[-20:]),
                     "f60": sum(f[-60:]), "t60": sum(t[-60:]),
                     "g5": sum(g[-5:]), "fst": st, "nd": len(f)}
    return inst

# ═══════════════ 台股價格:Yahoo 批次(GitHub 機房可達)═══════════════
def _yahoo_batch(tickers, hist, idmap):
    """批次下載日K,寫入 hist。idmap: yahoo代碼 → 我們的代號。回傳成功集合。"""
    import yfinance as yf
    ok = set()
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i+100]
        try:
            df = yf.download(chunk, period="7mo", interval="1d",
                             group_by="ticker", threads=True, progress=False,
                             auto_adjust=False)
            for tk in chunk:
                try:
                    sub = (df[tk] if len(chunk) > 1 else df).dropna(subset=["Close"])
                    if len(sub) < 15: continue
                    e = {"d": [], "o": []}
                    for idx, r in sub.tail(KEEP_BARS).iterrows():
                        e["d"].append(str(idx)[:10])
                        e["o"].append([round(float(r["Open"]),2), round(float(r["High"]),2),
                                       round(float(r["Low"]),2), round(float(r["Close"]),2),
                                       int((r.get("Volume") or 0) // (1000 if tk.endswith((".TW",".TWO")) else 1))])
                    hist[idmap[tk]] = e; ok.add(tk)
                except Exception: continue
        except Exception as e:
            print(f"  [warn] Yahoo 批次: {e}")
        time.sleep(1.5)
    return ok

def update_tw_prices(hist, tw_comps):
    idmap = {}
    tickers = []
    for c in tw_comps:
        tk = f"{c['id']}.{'TW' if c['ex']=='tse' else 'TWO'}"
        idmap[tk] = c["id"]; tickers.append(tk)
    ok = _yahoo_batch(tickers, hist, idmap)
    # 失敗者換另一個字尾再試(上市/上櫃標記偶有出入)
    retry, rmap = [], {}
    for c in tw_comps:
        tk = f"{c['id']}.{'TW' if c['ex']=='tse' else 'TWO'}"
        if tk in ok: continue
        alt = f"{c['id']}.{'TWO' if c['ex']=='tse' else 'TW'}"
        retry.append(alt); rmap[alt] = c["id"]
    if retry:
        ok2 = _yahoo_batch(retry, hist, rmap)
        print(f"  台股價格:{len(ok)+len(ok2)}/{len(tw_comps)} 檔(重試補回 {len(ok2)})")
    else:
        print(f"  台股價格:{len(ok)}/{len(tw_comps)} 檔")

# ═══════════════ 美股價格(批次)═══════════════
def update_us_prices(hist, us_comps):
    idmap = {c["id"]: c["id"] for c in us_comps}
    ok = _yahoo_batch(list(idmap), hist, idmap)
    missing = [s for s in idmap if s not in ok][:40]
    for sym in missing:  # Stooq 只救少量缺漏
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
    print(f"  美股價格:{len(ok)}/{len(us_comps)} 檔")

# ═══════════════ 官方彙總:營收 / 法人 / 大戶 ═══════════════
def fetch_rev_mops_live():
    """MOPS 當月即時彙總:公司 1~10 日陸續申報,申報當天此頁就有(上市+上櫃)。"""
    out = {}
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    roc = y - 1911
    for mk in ("sii", "otc"):
        for sfx in ("0", "1"):   # 0=國內公司、1=KY(國外)公司 —— 兩頁都要抓,否則 KY 股永遠沒即時營收
            try:
                u = f"https://mops.twse.com.tw/nas/t21/{mk}/t21sc03_{roc}_{m}_{sfx}.html"
                r = requests.get(u, headers={**UA, "Referer": "https://mops.twse.com.tw/"}, timeout=20)
                if r.status_code != 200 or len(r.content) < 2000:
                    continue
                html = r.content.decode("big5", errors="ignore")
                tabs = pd.read_html(StringIO(html))
                n0 = len(out)
                for df in tabs:
                    cols = ["".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in df.columns]
                    def ci(*pats):
                        return next((i for i, c in enumerate(cols) if all(p in c for p in pats)), None)
                    i_id  = ci("公司", "代號")
                    i_yoy = ci("去年同月", "增減")
                    i_amt = ci("當月營收")
                    if None in (i_id, i_yoy): continue
                    for _, row in df.iterrows():
                        sid = str(row.iloc[i_id]).strip()
                        if not (sid.isdigit() and 4 <= len(sid) <= 6): continue
                        yoy = numf(row.iloc[i_yoy])
                        if yoy is None: continue
                        amt = numf(row.iloc[i_amt]) if i_amt is not None else None
                        out[sid] = (yoy, f"{y}-{m:02d}", amt)
                if len(out) > n0:
                    print(f"  MOPS 即時營收({mk}/{sfx} {y}-{m:02d}):+{len(out)-n0} 家")
            except Exception as e:
                print(f"  [warn] MOPS 即時營收({mk}/{sfx}): {e}")
    return out

def fetch_rev_finmind_bulk():
    """FinMind 上月營收全市場備援(第三來源):MOPS 常封鎖 GitHub 海外 IP,
    此路徑用單月 date-only 查詢 + 去年同月自算 YoY;若方案不支援(回空)則安靜略過。"""
    out = {}
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)

    def _month(yy, mm2):
        params = {"dataset": "TaiwanStockMonthRevenue",
                  "start_date": f"{yy}-{mm2:02d}-01",
                  "end_date": f"{yy}-{mm2:02d}-28"}
        tok = os.environ.get("FINMIND_TOKEN", "")
        if tok: params["token"] = tok
        j = get_json("https://api.finmindtrade.com/api/v4/data", params=params, timeout=60)
        rows = j.get("data") if isinstance(j, dict) else None
        d = {}
        for r in rows or []:
            sid = str(r.get("stock_id", "")).strip()
            rv = numf(r.get("revenue"))
            if sid and rv:
                d[sid] = rv
        return d

    try:
        cur = _month(y, m)
        if not cur:
            return out
        prv = _month(y - 1, m)
        ym = f"{y}-{m:02d}"
        for sid, rv in cur.items():
            p = prv.get(sid)
            if p:
                out[sid] = (round((rv / p - 1) * 100, 2), ym, rv / 1000.0)  # FinMind 為元 → 千元對齊官方
        if out:
            print(f"  FinMind 營收備援({ym}):{len(out)} 家")
    except Exception as e:
        print(f"  [warn] FinMind 營收備援: {e}")
    return out

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
            k_amt = next((k for k in keys if k.endswith("當月營收") and "去年" not in k and "上月" not in k), None)
            for r in arr:
                sid, yoy = str(r.get(k_id, "")).strip(), numf(r.get(k_yoy))
                if sid and yoy is not None:
                    ym = "".join(ch for ch in str(r.get(k_ym, "")) if ch.isdigit())
                    if len(ym) >= 5:  # 民國 11405 → 2025-05;若已是西元則直接切
                        y = int(ym[:-2])
                        ym = f"{y + 1911 if y < 1900 else y}-{ym[-2:]}"
                    out[sid] = (yoy, ym, numf(r.get(k_amt)) if k_amt else None)
        except Exception as e:
            print(f"  [warn] 營收彙總: {e}")
    live = fetch_rev_mops_live()
    n_new = 0
    for sid, v in live.items():
        cur = out.get(sid)
        if not cur or v[1] > cur[1]:   # 只用「更新的月份」覆蓋
            out[sid] = v; n_new += 1
    # 第三來源:MOPS 抓不到或只抓到部分(海外IP被擋/KY頁缺漏)時,由 FinMind 補上月即時營收
    now8 = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    py, pm = (now8.year, now8.month - 1) if now8.month > 1 else (now8.year - 1, 12)
    want = f"{py}-{pm:02d}"
    cov = sum(1 for v in out.values() if v[1] >= want)
    if out and cov < len(out) * 0.9:   # 上月覆蓋率不足 → 啟動備援補洞
        fm = fetch_rev_finmind_bulk()
        for sid, v in fm.items():
            cur = out.get(sid)
            if not cur or v[1] > cur[1]:
                out[sid] = v; n_new += 1
    print(f"  月營收:{len(out)} 家(其中上月即時 {n_new} 家)")
    return out

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

def prev_q(q):
    y, s = int(q[:4]), int(q[-1])
    return f"{y-1}Q4" if s == 1 else f"{y}Q{s-1}"

def fetch_margin_bulk():
    """最新一季營益分析(毛利率/營益率/稅後純益率/營收)。來源:證交所+櫃買 OpenAPI(僅最新季)。"""
    out = {}
    for url in ("https://openapi.twse.com.tw/v1/opendata/t187ap17_L",
                "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap17_O"):
        try:
            arr = get_json(url, timeout=60)
            keys = list(arr[0].keys())
            k_id  = next((k for k in keys if "代號" in k), None)
            k_y   = next((k for k in keys if "年度" in k), None)
            k_s   = next((k for k in keys if "季" in k), None)
            k_rev = next((k for k in keys if "營業收入" in k), None)
            k_gm  = next((k for k in keys if "毛利率" in k), None)
            k_om  = next((k for k in keys if "營業利益率" in k), None)
            k_nm  = next((k for k in keys if "稅後純益率" in k), None)
            if None in (k_id, k_gm, k_om, k_nm): continue
            for r in arr:
                sid = str(r.get(k_id, "")).strip()
                gm, om, nm = numf(r.get(k_gm)), numf(r.get(k_om)), numf(r.get(k_nm))
                if not sid or None in (gm, om, nm): continue
                y = int(numf(r.get(k_y)) or 0)
                y = y + 1911 if 0 < y < 1900 else y
                s_ = int(numf(r.get(k_s)) or 0)
                if not (y > 1900 and 1 <= s_ <= 4): continue
                out[sid] = (f"{y}Q{s_}", gm, om, nm, numf(r.get(k_rev)))
        except Exception as e:
            print(f"  [warn] 營益分析: {e}")
    print(f"  營益分析(三率):{len(out)} 家")
    return out

def fetch_margin_mops(year, season):
    """歷史季別營益彙總(公開資訊觀測站),用於首次回補上一季。"""
    out = {}
    for typek in ("sii", "otc"):
        try:
            r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t163sb06",
                data={"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
                      "isQuery": "Y", "TYPEK": typek,
                      "year": str(year - 1911), "season": f"{season:02d}"},
                headers=UA, timeout=60)
            for df in pd.read_html(StringIO(r.text)):
                cols = [str(c) for c in df.columns]
                if not any("毛利率" in c for c in cols): continue
                c_id = next(c for c in df.columns if "代號" in str(c))
                c_gm = next(c for c in df.columns if "毛利率" in str(c))
                c_om = next(c for c in df.columns if "營業利益率" in str(c))
                c_nm = next(c for c in df.columns if "稅後純益率" in str(c))
                c_rv = next((c for c in df.columns if "營業收入" in str(c)), None)
                for _, row in df.iterrows():
                    sid = str(row[c_id]).strip()
                    if not (sid.isdigit() and len(sid) == 4): continue
                    gm, om, nm = numf(row[c_gm]), numf(row[c_om]), numf(row[c_nm])
                    if None in (gm, om, nm): continue
                    out[sid] = (gm, om, nm, numf(row[c_rv]) if c_rv is not None else None)
        except Exception as e:
            print(f"  [warn] MOPS 營益 {typek} {year}Q{season}: {e}")
        time.sleep(1.5)
    return out

def append_margins(chips, cur):
    """把季度三率寫入籌碼歷史(fq/gm/om/nm/qr,保留8季);上一季不足時嘗試 MOPS 回補一次。"""
    if not cur: return
    q_now = max(v[0] for v in cur.values())
    pq = prev_q(q_now)
    have_prev = sum(1 for sid in cur if pq in (chips.get(sid, {}).get("fq") or []))
    if have_prev < 200:
        y, s_ = int(pq[:4]), int(pq[-1])
        print(f"  上一季三率資料不足({have_prev} 家),向 MOPS 回補 {pq} …")
        prev = fetch_margin_mops(y, s_)
        print(f"  MOPS 回補:{len(prev)} 家")
        for sid, (gm, om, nm, rv) in prev.items():
            _put_margin(chips.setdefault(sid, {}), pq, gm, om, nm, rv)
    for sid, (q, gm, om, nm, rv) in cur.items():
        _put_margin(chips.setdefault(sid, {}), q, gm, om, nm, rv)

def _put_margin(e, q, gm, om, nm, rv):
    m = {e["fq"][i]: [e["gm"][i], e["om"][i], e["nm"][i],
                      (e.get("qr") or [None]*len(e["fq"]))[i]]
         for i in range(len(e.get("fq") or []))}
    m[q] = [gm, om, nm, rv]
    qs = sorted(m)[-8:]
    e["fq"] = qs
    e["gm"] = [m[x][0] for x in qs]
    e["om"] = [m[x][1] for x in qs]
    e["nm"] = [m[x][2] for x in qs]
    e["qr"] = [m[x][3] for x in qs]

def _finmind_fut(day):
    """FinMind 期貨法人未平倉(TX 大台 + MTX 小台),一次取 90 天歷史。"""
    start = (dt.datetime.now() - dt.timedelta(days=95)).strftime("%Y-%m-%d")
    for pid in ("TX", "MTX"):
        try:
            j = get_json("https://api.finmindtrade.com/api/v4/data"
                         f"?dataset=TaiwanFuturesInstitutionalInvestors&data_id={pid}&start_date={start}",
                         timeout=40)
            rows = j.get("data") if isinstance(j, dict) else (j if isinstance(j, list) else None)
            if not rows:
                print(f"  [warn] FinMind {pid}:無資料")
                continue
            for r in rows:
                d0 = str(r.get("date", "")).replace("-", "/")
                nm = str(r.get("institutional_investors") or r.get("name") or "")
                try:
                    net = int(float(r.get("long_open_interest_balance_volume", 0))) -                           int(float(r.get("short_open_interest_balance_volume", 0)))
                except Exception:
                    continue
                e = day.setdefault(d0, {})
                if pid == "TX":
                    if "外資" in nm: e["fx"] = net
                    elif "投信" in nm: e["it"] = net
                    elif "自營" in nm: e["dl"] = net
                else:
                    if any(k in nm for k in ("外資", "投信", "自營")):
                        e["mtx"] = e.get("mtx", 0) + net
            print(f"  [info] FinMind {pid}:{len(rows)} 列")
        except Exception as e2:
            print(f"  [warn] FinMind {pid}: {e2}")

def _taifex_csv_fallback():
    """期交所傳統下載端點:三大法人+大額交易人(近10個交易日回填)。"""
    day = {}
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    dates = []
    d0 = today
    while len(dates) < 10:
        if d0.weekday() < 5:
            dates.append(d0.strftime("%Y/%m/%d"))
        d0 -= dt.timedelta(days=1)
    import csv as _csv, io as _io
    def dl(url, form):
        r = requests.post(url, data=form, headers=UA, timeout=15)
        r.raise_for_status()
        txt = None
        for enc in ("utf-8-sig", "big5", "cp950", "utf-8"):
            try: txt = r.content.decode(enc); break
            except Exception: continue
        if txt is None: txt = r.text
        return list(_csv.reader(_io.StringIO(txt)))
    # 三大法人(依商品)
    ok1 = 0
    for qd in dates:
        try:
            rows = dl("https://www.taifex.com.tw/cht/3/futContractsDateDown",
                     {"queryType": "1", "goDay": "", "doQuery": "1",
                      "dateaddcnt": "", "queryDate": qd, "commodityId": ""})
            rows = [r for r in rows if r and any(c.strip() for c in r)]
            if len(rows) < 2:
                if ok1 == 0 and qd == dates[0]:
                    print(f"  [debug] 法人端點回應過短:{rows[:1]}")
                continue
            hdr = rows[0]
            def col(*ns):
                return next((i for i, h in enumerate(hdr) if all(n in h for n in ns)), None)
            ci_d, ci_p, ci_i = col("日期"), col("商品"), col("身")
            ci_net = col("多空", "未平倉", "淨額") or col("多空未平倉口數淨額")
            if None in (ci_d, ci_p, ci_i, ci_net):
                if ok1 == 0 and qd == dates[0]:
                    print(f"  [debug] 法人表頭無法配對:{hdr[:16]}")
                continue
            fday = {}   # 單檔內解析,跨檔以「覆蓋」合併(同日重複下載不會重複累加)
            for r0 in rows[1:]:
                if len(r0) <= ci_net: continue
                dte, prod, ident = r0[ci_d].strip(), r0[ci_p].strip(), r0[ci_i].strip()
                try: net = int(float(r0[ci_net].replace('"', '').replace(",", "")))
                except Exception: continue
                e = fday.setdefault(dte, {})
                if "臺股期貨" in prod and "小型" not in prod and "微型" not in prod:
                    if "外資" in ident: e["fx"] = net
                    elif "投信" in ident: e["it"] = net
                    elif "自營" in ident: e["dl"] = net
                if "小型臺指" in prod and any(n in ident for n in ("外資", "投信", "自營")):
                    e["mtx"] = e.get("mtx", 0) + net
            for dte, e in fday.items():
                day.setdefault(dte, {}).update(e)
            ok1 += 1
        except Exception:
            pass
        time.sleep(0.4)
    # 大額交易人(回填 45 個交易日,含特定法人獨立列)
    dates2 = []
    d0 = today
    while len(dates2) < 45:
        if d0.weekday() < 5:
            dates2.append(d0.strftime("%Y/%m/%d"))
        d0 -= dt.timedelta(days=1)
    ok2 = 0
    for qd in dates2:
        try:
            rows = dl("https://www.taifex.com.tw/cht/3/largeTraderFutDown",
                     {"queryStartDate": qd, "queryEndDate": qd})
            rows = [r for r in rows if r and any(c.strip() for c in r)]
            if len(rows) < 2: continue
            hdr = rows[0]
            def col(*ns):
                return next((i for i, h in enumerate(hdr) if all(n in h for n in ns)), None)
            ci_d, ci_c, ci_m = col("日期"), col("契約"), col("月份") if col("月份") is not None else col("週別")
            # 十大(全部)買賣:排除「特定」欄
            ci_b = next((i for i,h in enumerate(hdr) if "十大" in h and "買" in h and "特定" not in h), None)
            ci_s = next((i for i,h in enumerate(hdr) if "十大" in h and "賣" in h and "特定" not in h), None)
            # 十大特定法人:獨立欄位格式
            ci_pb = next((i for i,h in enumerate(hdr) if "十大" in h and "特定" in h and "買" in h), None)
            ci_ps = next((i for i,h in enumerate(hdr) if "十大" in h and "特定" in h and "賣" in h), None)
            ci_t = col("類別")   # 「交易人類別」列格式
            if None in (ci_d, ci_c, ci_b, ci_s):
                continue
            if ok2 == 0:
                print(f"  [debug] 大額表頭(成功日 {qd}):{hdr}")
                print(f"  [debug] 首列樣本:{rows[1][:10] if len(rows)>1 else '無'}")
            import re as _r2
            def num(v):
                m = _r2.match(r"\s*\"?([\d,]+)", str(v))
                return int(m.group(1).replace(",", "")) if m else 0
            def spec(v):
                m = _r2.search(r"\(([\d,]+)\)", str(v))
                if not m: return None
                inner = m.group(1)
                if "%" in str(v) or "." in inner: return None   # 百分比,不是口數
                return int(inner.replace(",", ""))
            for r0 in rows[1:]:
                if len(r0) <= max(ci_b, ci_s): continue
                if "TX" != r0[ci_c].strip() and "臺股期貨" not in r0[ci_c]: continue
                mv = r0[ci_m] if ci_m is not None and len(r0) > ci_m else ""
                if not ("999999" in mv or "所有" in mv or "全部" in mv): continue
                dte = r0[ci_d].strip()
                e = day.setdefault(dte, {})
                net10 = num(r0[ci_b]) - num(r0[ci_s])
                kind = r0[ci_t].strip() if (ci_t is not None and len(r0) > ci_t) else ""
                if "特定" in kind:
                    e["sp"] = net10                                   # 格式A:特定法人獨立「列」
                else:
                    e["b10"] = net10
                    if ci_pb is not None and ci_ps is not None and len(r0) > max(ci_pb, ci_ps):
                        e["sp"] = num(r0[ci_pb]) - num(r0[ci_ps])     # 格式B:特定法人獨立「欄」
                    else:
                        sb, ss = spec(r0[ci_b]), spec(r0[ci_s])
                        if sb is not None and ss is not None and e.get("sp") is None:
                            e["sp"] = sb - ss                          # 格式C:括號含口數(舊)
            ok2 += 1
        except Exception:
            pass
        time.sleep(0.4)
    print(f"  [info] 傳統端點回填:法人 {ok1}/{len(dates)} 日、大額 {ok2}/{len(dates2)} 日")
    return day

def fetch_credit_stocks(stocks):
    """個股融資融券餘額(MI_MARGN,上市)+融券借券賣出餘額(TWT93U)。單位:張。"""
    by_id = {s["id"]: s for s in stocks if s.get("market") == "TW"}
    def pick(keys, *pats):
        for k in keys:
            if all(p.lower() in k.lower() for p in pats): return k
        return None
    n1 = 0
    try:
        arr = get_json("https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN", timeout=60)
        keys = list(arr[0].keys())
        kc = pick(keys, "Code") or pick(keys, "代號")
        kft = pick(keys, "MarginBalanceOfTheDay") or pick(keys, "融資", "今日餘額")
        kfp = pick(keys, "MarginBalanceOfPreviousDay") or pick(keys, "融資", "前日餘額")
        kst = pick(keys, "ShortBalanceOfTheDay") or pick(keys, "融券", "今日餘額")
        ksp = pick(keys, "ShortBalanceOfPreviousDay") or pick(keys, "融券", "前日餘額")
        if not all((kc, kft, kfp)):
            print(f"  [debug] MI_MARGN 欄位:{keys[:12]}")
        else:
            for r in arr:
                s = by_id.get(str(r.get(kc, "")).strip())
                if not s: continue
                def iv(k):
                    try: return int(float(str(r.get(k, "0")).replace(",", "")))
                    except Exception: return None
                ft, fp = iv(kft), iv(kfp)
                st_, sp = (iv(kst), iv(ksp)) if kst and ksp else (None, None)
                if ft is None: continue
                mg = s.setdefault("mg", {})
                mg["f"] = ft
                if fp is not None: mg["fd"] = ft - fp
                if st_ is not None:
                    mg["s"] = st_
                    if sp is not None: mg["sd"] = st_ - sp
                n1 += 1
    except Exception as e:
        print(f"  [warn] 融資融券(MI_MARGN): {e}")
    n2 = 0
    try:
        arr = None
        d0 = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
        for back in range(6):
            qd = (d0 - dt.timedelta(days=back))
            if qd.weekday() >= 5: continue
            u = f"https://www.twse.com.tw/rwd/zh/afterTrading/TWT93U?date={qd.strftime('%Y%m%d')}&response=json"
            try:
                j = get_json(u, timeout=30)
                if isinstance(j, dict) and j.get("stat") == "OK" and j.get("data"):
                    flds = j.get("fields") or []
                    arr = [dict(zip(flds, row)) for row in j["data"]]
                    print(f"  借券賣出資料日:{qd.strftime('%Y/%m/%d')}")
                    break
            except Exception:
                continue
        if not arr:
            raise RuntimeError("rwd TWT93U 無資料")
        keys = list(arr[0].keys())
        kc = pick(keys, "Code") or pick(keys, "代號")
        klt = pick(keys, "借券", "當日餘額") or pick(keys, "借券", "今日餘額") or pick(keys, "SBL", "TheDay") or pick(keys, "Lending", "TheDay")
        klp = pick(keys, "借券", "前日餘額") or pick(keys, "SBL", "Previous") or pick(keys, "Lending", "Previous")
        if not klt:
            print(f"  [debug] TWT93U 欄位:{keys[:14]}")
        if not all((kc, klt)):
            print(f"  [debug] TWT93U 欄位:{keys[:12]}")
        else:
            for r in arr:
                s = by_id.get(str(r.get(kc, "")).strip())
                if not s: continue
                def iv(k):
                    try: return int(float(str(r.get(k, "0")).replace(",", "")))
                    except Exception: return None
                lt = iv(klt)
                if lt is None: continue
                lt = round(lt / 1000)                       # 股 → 張
                mg = s.setdefault("mg", {})
                mg["l"] = lt
                lp = iv(klp) if klp else None
                if lp is not None: mg["ld"] = lt - round(lp / 1000)
                n2 += 1
    except Exception as e:
        print(f"  [warn] 借券賣出(TWT93U): {e}")
    print(f"  信用交易:融資融券 {n1} 檔、借券賣出 {n2} 檔")

def fetch_credit_macro(prev):
    """大盤融資餘額(億元,FinMind 90 日歷史)。"""
    try:
        start = (dt.datetime.now() - dt.timedelta(days=95)).strftime("%Y-%m-%d")
        j = get_json("https://api.finmindtrade.com/api/v4/data"
                     f"?dataset=TaiwanStockTotalMarginPurchaseShortSale&start_date={start}",
                     timeout=40)
        rows = j.get("data") if isinstance(j, dict) else (j if isinstance(j, list) else [])
        hist = {}
        for r in rows or []:
            nm = str(r.get("name", ""))
            if "MarginPurchaseMoney" not in nm: continue
            d0 = str(r.get("date", ""))
            try: bal = float(r.get("TodayBalance", r.get("balance", 0)))
            except Exception: continue
            hist[d0] = round(bal / 1e8, 1)                  # 元 → 億
        if not hist and prev: return prev
        ds = sorted(hist)[-60:]
        if not ds: return prev
        h = {"d": ds, "fin": [hist[d] for d in ds]}
        last, p = h["fin"][-1], (h["fin"][-2] if len(ds) > 1 else None)
        out = {"d": ds[-1], "fin": last,
               "finD": round(last - p, 1) if p is not None else None, "h": h}
        print(f"  大盤融資餘額:{last} 億(歷史 {len(ds)} 日)")
        return out
    except Exception as e:
        print(f"  [warn] 大盤融資: {e}")
        return prev

def fetch_taifex(prev_fut=None):
    """台指期籌碼:三大法人/十大交易人/散戶小台,含 60 日歷史(供詳細頁畫圖)。"""
    day = {}   # date -> {fx,it,dl,rt,b10,sp}
    try:
        arr = get_json("https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsByDate", timeout=60)
        keys = list(arr[0].keys())
        print(f"  [debug] 期貨法人欄位: {keys[:10]}")
        k = lambda *ns: next((x for x in keys if all(n in x for n in ns)), None)
        kd, kp, ki = k("日期") or k("Date"), k("商品名稱") or k("商品") or k("Commodity") or k("Contract"), k("身份別") or k("身分別") or k("Investor") or k("Institut")
        kn = k("多空", "淨額")
        for r in arr:
            d = str(r.get(kd, "")).strip()
            prod, ident = str(r.get(kp, "")), str(r.get(ki, ""))
            try: net = int(float(str(r.get(kn, "0")).replace(",", "")))
            except Exception: continue
            e = day.setdefault(d, {})
            if "臺股期貨" in prod and "小型" not in prod and "微型" not in prod:
                if "外資" in ident: e["fx"] = net
                elif "投信" in ident: e["it"] = net
                elif "自營" in ident: e["dl"] = net
            if "小型臺指" in prod and any(n in ident for n in ("外資", "投信", "自營")):
                e["mtx"] = e.get("mtx", 0) + net
    except Exception as e:
        print(f"  [warn] 期貨法人: {e}")
    try:
        arr = get_json("https://openapi.taifex.com.tw/v1/OpenInterestOfLargeTradersFutures", timeout=60)
        keys = list(arr[0].keys())
        k = lambda *ns: next((x for x in keys if all(n in x for n in ns)), None)
        kd = k("日期"); kp = k("契約") or k("商品"); km = k("月份") or k("週別")
        kb10 = k("十大", "買方", "部位數") or k("十大", "買方")
        ks10 = k("十大", "賣方", "部位數") or k("十大", "賣方")
        def num(v):
            m = _re.match(r"\s*([\d,]+)", str(v) or "")
            return int(m.group(1).replace(",", "")) if m else 0
        def spec(v):
            m = _re.search(r"\(([\d,]+)\)", str(v) or "")
            return int(m.group(1).replace(",", "")) if m else None
        for r in arr:
            d = str(r.get(kd, "")).strip()
            if "臺股期貨" not in str(r.get(kp, "")) or "小型" in str(r.get(kp, "")): continue
            mv = str(r.get(km, ""))
            if not ("999999" in mv or "所有" in mv or "全部" in mv): continue
            b, s2 = r.get(kb10), r.get(ks10)
            e = day.setdefault(d, {})
            e["b10"] = num(b) - num(s2)
            sb, ss = spec(b), spec(s2)
            if sb is not None and ss is not None: e["sp"] = sb - ss
    except Exception as e:
        print(f"  [warn] 十大交易人: {e}")
    # 備援一:FinMind(法人+小台,90日歷史,一次到位)
    if not any(e.get("fx") is not None for e in day.values()):
        try:
            _finmind_fut(day)
        except Exception as e:
            print(f"  [warn] FinMind: {e}")
    # 備援二:期交所傳統下載端點(主要補十大交易人;法人若仍缺也一併嘗試)
    need_big = not any(e.get("b10") is not None for e in day.values())
    need_inst = not any(e.get("fx") is not None for e in day.values())
    if need_big or need_inst:
        print(f"  [info] 傳統端點補洞(十大:{need_big}/法人:{need_inst})…")
        try:
            fb = _taifex_csv_fallback()
            for dte, e in (fb or {}).items():
                tgt = day.setdefault(dte, {})
                for k, v in e.items():
                    if tgt.get(k) is None:
                        tgt[k] = v
        except Exception as e:
            print(f"  [warn] 傳統端點: {e}")
    if not day:
        print("  台指期籌碼:無資料")
        return None
    # 併入舊歷史,去重排序留 60 日
    hist = {}
    if prev_fut and isinstance(prev_fut.get("h"), dict):
        ph = prev_fut["h"]
        for i, d in enumerate(ph.get("d", [])):
            hist[d] = {kk: (ph.get(kk2) or [None]*len(ph["d"]))[i]
                       for kk, kk2 in [("fx","fx"),("it","it"),("dl","dl"),("rt","rt"),("b10","b10"),("sp","sp")]}
    for d, e in day.items():
        h = hist.setdefault(d, {})
        for kk in ("fx","it","dl","b10","sp"):
            if e.get(kk) is not None: h[kk] = e[kk]
        if e.get("mtx") is not None: h["rt"] = -e["mtx"]
    ds = sorted(hist)[-60:]
    H = {"d": ds}
    for kk in ("fx","it","dl","rt","b10","sp"):
        H[kk] = [hist[d].get(kk) for d in ds]
    last, prev = ds[-1], (ds[-2] if len(ds) > 1 else None)
    def pair(kk):
        v = hist[last].get(kk)
        if v is None: return None
        pv = hist[prev].get(kk) if prev else None
        return [v, (v - pv) if pv is not None else None]
    fut = {"d": last, "h": H,
           "inst": [[nm, *(pair(kk) or [None, None])] for nm, kk in
                    [("外資","fx"),("投信","it"),("自營商","dl")] if pair(kk)],
           "big": ([hist[last].get("b10"), hist[last].get("sp")]
                   if hist[last].get("b10") is not None else None),
           "ret": pair("rt")}
    print(f"  台指期籌碼:{last}(歷史 {len(ds)} 日/法人 {len(fut['inst'])} 項/十大 {'有' if fut['big'] else '無'})")
    return fut

def fetch_cobasic():
    """公司基本資料(董事長/掛牌/資本額/官網/產業別),全市場。"""
    out = {}
    for url in ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
                "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"):
        try:
            arr = get_json(url, timeout=60)
            keys = list(arr[0].keys())
            k = lambda *ns: next((x for x in keys if any(n in x for n in ns)), None)
            kid, kch = k("公司代號"), k("董事長")
            kipo, kcap = k("上市日期", "上櫃日期"), k("實收資本額")
            kweb, kind = k("網址"), k("產業別")
            for r in arr:
                sid = str(r.get(kid, "")).strip()
                if not sid: continue
                out[sid] = {"ch": str(r.get(kch, "") or ""),
                            "ipo": str(r.get(kipo, "") or ""),
                            "cap": str(r.get(kcap, "") or ""),
                            "web": str(r.get(kweb, "") or ""),
                            "ind": str(r.get(kind, "") or "")}
        except Exception as e:
            print(f"  [warn] 公司基本資料: {e}")
    print(f"  公司基本資料:{len(out)} 家")
    return out

import re as _re
def fetch_biz(sid):
    """MOPS 個股基本資料 → 主要經營業務(中文)。"""
    try:
        r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t05st03",
            data={"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
                  "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "co_id": sid},
            headers=UA, timeout=8)
        m = _re.search(r"主要經營業務[\s\S]{0,200}?<td[^>]*>([\s\S]*?)</td>", r.text)
        if m:
            txt = _re.sub(r"<[^>]+>", "", m.group(1))
            txt = _re.sub(r"\s+", " ", txt).strip()
            if len(txt) > 8:
                return txt[:400]
    except Exception:
        pass
    return None

def fetch_targets(stocks):
    """用 yfinance 抓分析師目標價(自帶 cookie/crumb 處理,最穩)。
    覆蓋:台股綜合分前150 + 精選論點股 + 美股前60,寫入 s["tp"]={m,h,l}。"""
    try:
        import yfinance as yf
    except Exception as e:
        print(f"  [warn] yfinance 不可用({e}),略過目標價")
        return
    def tot(s):
        return s["f"]["score"]*0.4 + s["c"]["score"]*0.35 + s["t"]["score"]*0.25
    tw = sorted([s for s in stocks if s["market"] == "TW"], key=lambda s: -tot(s))[:300]
    thes = [s for s in stocks if s.get("thesis") and s not in tw]
    us = sorted([s for s in stocks if s["market"] == "US"], key=lambda s: -tot(s))[:80]
    picks, n = tw + thes + us, 0
    t0, fails = time.time(), 0
    for s in picks:
        if time.time() - t0 > 600:
            print("  [warn] 目標價超過時間預算(10分),提前收工"); break
        if fails >= 10 and n == 0:
            print("  [warn] 目標價連續失敗,來源可能被擋,跳過"); break
        sym = (f"{s['id']}.{'TW' if s['ex']=='tse' else 'TWO'}"
               if s["market"] == "TW" else s["id"])
        try:
            pt = yf.Ticker(sym).analyst_price_targets
            if pt and pt.get("mean"):
                s["tp"] = {"m": round(float(pt["mean"]), 2),
                           "h": round(float(pt["high"]), 2) if pt.get("high") else None,
                           "l": round(float(pt["low"]), 2) if pt.get("low") else None}
                n += 1; fails = 0
            else:
                fails += 1
        except Exception:
            fails += 1
        time.sleep(0.35)
    print(f"  分析師目標價(yfinance):{n}/{len(picks)} 檔")
    nb, bf, tb = 0, 0, time.time()
    # 補洞優先:全市場尚無業務簡介者排前面(重點股其次刷新)——約兩週覆蓋全市場
    holes = [s for s in stocks if s.get("market") == "TW" and not s.get("bz")]
    todo = holes + [s for s in picks if s.get("market") == "TW" and s.get("bz")]
    for s in todo:
        if s["market"] != "TW": continue
        if time.time() - tb > 300:
            print("  [warn] 業務抓取超過時間預算(5分),提前收工"); break
        if bf >= 8 and nb == 0:
            print("  [warn] MOPS 連續失敗,來源可能封鎖 GitHub 機房,跳過"); break
        bz = fetch_biz(s["id"])
        if bz:
            s["bz"] = bz; nb += 1; bf = 0
        else:
            bf += 1
        time.sleep(0.6)
    print(f"  主要經營業務(MOPS):{nb} 檔")

def load_prev():
    try:
        with open("data.json", encoding="utf-8") as f:
            old = json.load(f)
        return {s["id"]: (s.get("c", {}).get("raw") or {}) for s in old.get("stocks", [])}
    except Exception:
        return {}

# ═══════════════ 評分與訊號 ═══════════════
def avg(a): return sum(a) / len(a)

def score_stock(c, bars, rev_bulk, inst, tdcc, tdcc_date, prev, chips=None):
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
        if is_tw:  # 盤中即時警示用的關鍵價位(買進區/突破價/均量)
            h20 = max(x[1] for x in o[-20:])
            z1, z0 = max(ma20, ma60), min(ma20, ma60)
            out["al"] = {"z1": round(z1, 2), "z0": round(z0, 2),
                         "stop": round(z0 * 0.97, 2), "h20": round(h20, 2),
                         "v20": int(avg(vols[-20:])), "bull": 1 if bull else 0}
    else:
        ma20 = avg(closes[-min(20, n):]); ma60 = ma20; bull = None
        out["t"] = {"score": 50, "kv": {"K線累積": f"{n}/60 天"},
                    "note": "K線資料累積中,滿60天後開始評分。"}

    # 基本面(台股)—— 取「本次彙總 vs 站內逐月歷史」較新月份,卡片與營收趨勢圖同源不倒退
    f, f_kv = 50, {}
    rv = latest_rev(sid, rev_bulk, chips) if is_tw else None
    if is_tw and rv:
        yoy, ym = rv[0], rv[1]
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
            v = inst[sid]
            f5, t5 = v["f5"], v["t5"]
            c_kv["外資5日"], c_kv["投信5日"] = f"{f5:+,.0f} 張", f"{t5:+,.0f} 張"
            c_kv["外資20日"], c_kv["投信20日"] = f"{v['f20']:+,.0f} 張", f"{v['t20']:+,.0f} 張"
            if v.get("nd", 0) >= 40:
                c_kv["外資60日"] = f"{v['f60']:+,.0f} 張"
            if v.get("fst", 0) >= 3:
                c_kv["外資連買"] = f"{v['fst']} 日"
            c_raw["f5"], c_raw["t5"] = int(f5), int(t5)
            c_raw["f20"], c_raw["t20"] = int(v["f20"]), int(v["t20"])
            c_raw["fst"] = int(v.get("fst", 0))
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

# ═══════════════ 個股新聞(訊號股 + 精選 + 評分前段班)═══════════════
def fetch_stock_news(stocks, cap=150, per=3):
    import xml.etree.ElementTree as ET, html as H
    def T(s): return round(s["f"]["score"]*.40 + s["c"]["score"]*.35 + s["t"]["score"]*.25)
    cands = [s for s in stocks if s.get("sig") or s["id"] in THESIS]
    rest = sorted([s for s in stocks if s not in cands and s.get("price") is not None],
                  key=T, reverse=True)
    targets = (cands + rest)[:cap]
    got = 0
    for s in targets:
        q = requests.utils.quote(f'"{s["name"]}" {("股價" if s["market"]=="TW" else "stock")}')
        url = (f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
        try:
            root = ET.fromstring(requests.get(url, headers=UA, timeout=15).content)
            items = []
            for it in root.iter("item"):
                title = H.unescape(it.findtext("title") or "")
                parts = title.rsplit(" - ", 1)
                items.append({"t": parts[0][:80], "s": parts[1] if len(parts) > 1 else "",
                              "l": it.findtext("link") or "#",
                              "d": (it.findtext("pubDate") or "")[5:16]})
                if len(items) >= per: break
            if items:
                s["news"] = items; got += 1
                for it in items:   # 漲價/缺料題材掃描
                    if _re.search(r"(漲價|調漲|喊漲|缺料|缺貨|供不應求|急單|報價(上|調)漲|價格勁揚|吃緊|漲勢延續)", it["t"]):
                        sig = s.setdefault("sig", [])
                        if not any(g.get("type") == "price" for g in sig):
                            sig.append({"type": "price", "label": "漲價/缺料",
                                        "desc": "新聞:" + it["t"][:60]})
                        break
        except Exception:
            pass
        time.sleep(0.5)
    print(f"  個股新聞:{got}/{len(targets)} 檔")

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
        import yfinance as yf
        for name, tkr in [("加權指數", "^TWII"), ("S&P 500", "^GSPC"),
                          ("那斯達克", "^IXIC"), ("費城半導體", "^SOX")]:
            try:
                h = yf.Ticker(tkr).history(period="5d")["Close"].dropna()
                if len(h) >= 2:
                    v, p = float(h.iloc[-1]), float(h.iloc[-2])
                    idx.append({"name": name, "val": round(v, 2), "chg": round(pct(v, p), 2)})
            except Exception as e:
                print(f"  [warn] 指數 {tkr}: {e}")
    except Exception: pass
    if not any(i["name"] == "S&P 500" for i in idx):  # Stooq 備援
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
    update_tw_prices(hist, [c for c in comps if c["market"] == "TW"])
    update_us_prices(hist, [c for c in comps if c["market"] == "US"])
    save_hist(hist, comps)

    print("③ 官方彙總:營收 / 法人 / 大戶(台灣官方站可能封鎖海外IP,抓不到則以中性計分)...")
    rev_bulk = fetch_rev_bulk()
    chips, cmeta = load_chips()
    update_chip_hist(chips, cmeta)          # 法人逐日,累積至 65 個交易日
    tdcc, tdcc_date = fetch_tdcc_bulk()
    append_tdcc(chips, tdcc, tdcc_date)     # 大戶逐週,保留 26 週
    append_rev(chips, rev_bulk)             # 營收逐月,保留 13 個月
    append_margins(chips, fetch_margin_bulk())  # 季度三率,保留 8 季(供三率三升)
    inst = build_inst(chips)
    save_chips(chips, cmeta, comps)

    print("④ 計算評分與訊號 ...")
    stocks, ok = [], 0
    for c in comps:
        bars = hist.get(c["id"])
        if bars and len(bars.get("o", [])) >= 2:
            try:
                d = score_stock(c, bars, rev_bulk, inst, tdcc, tdcc_date, prev, chips)
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
        # 營收三率三升:最新季毛利/營益/淨利率皆高於上一季,且營收成長(月YoY>0 或 季營收QoQ>0)
        me = chips.get(c["id"], {})
        fq = me.get("fq") or []
        if c["market"] == "TW" and len(fq) >= 2:
            g, o2, n2, qr = me["gm"], me["om"], me["nm"], me.get("qr") or []
            if g[-1] > g[-2] and o2[-1] > o2[-2] and n2[-1] > n2[-2]:
                _rv = latest_rev(c["id"], rev_bulk, chips)
                yoy = _rv[0] if _rv else None
                rev_ok = (yoy is not None and yoy > 0) or (
                    len(qr) >= 2 and qr[-1] and qr[-2] and qr[-1] > qr[-2])
                if rev_ok:
                    d["t3"] = {"q": fq[-1],
                               "gm": [g[-2], g[-1]], "om": [o2[-2], o2[-1]],
                               "nm": [n2[-2], n2[-1]], "ry": yoy}
        if c["id"] in THESIS: d["thesis"] = THESIS[c["id"]]
        stocks.append(d)

    print("⑤ 個股新聞(訊號股與評分前段班)...")
    try:
        fetch_stock_news(stocks)
    except Exception as e:
        print(f"  [warn] 個股新聞: {e}")

    print("⑥ 市場總覽與新聞 ...")
    taipei = (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d")
    prev_all = {}
    try:
        with open("data.json", encoding="utf-8") as _f:
            prev_all = json.load(_f)
    except Exception:
        pass
    # ══ 第一階段:核心保底——評分/K線/總經先寫出,今日資料保證上線 ══
    _macro = fetch_macro()
    _news = fetch_news()
    out = {"updated": taipei, "source": "live",
           "macro": _macro, "news": _news, "stocks": stocks}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  ✅ 核心資料已寫出(第一階段保底):{len(stocks)} 檔")
    # ══ 第二階段:豐富化——任何一項爆掉都不影響核心 ══
    # 跨日繼承:昨天抓到的目標價/業務先搬過來,之後的抓取只是刷新/補洞
    try:
        _prev_by_id = {s.get("id"): s for s in (prev_all.get("stocks") or [])}
        _c_tp = _c_bz = 0
        for s in stocks:
            p = _prev_by_id.get(s["id"])
            if not p: continue
            if p.get("tp") and not s.get("tp"): s["tp"] = p["tp"]; _c_tp += 1
            if p.get("bz") and not s.get("bz"): s["bz"] = p["bz"]; _c_bz += 1
        print(f"  跨日繼承:目標價 {_c_tp} 檔、業務 {_c_bz} 檔")
    except Exception as e:
        print(f"  [warn] 繼承: {e}")
    try:
        fut = fetch_taifex((prev_all.get("macro") or {}).get("fut"))
        if fut: _macro["fut"] = fut
    except Exception as e:
        print(f"  [warn] 期貨籌碼跳過: {e}")
    try:
        fetch_credit_stocks(stocks)
    except Exception as e:
        print(f"  [warn] 信用交易跳過: {e}")
    try:
        _macro["credit"] = fetch_credit_macro((prev_all.get("macro") or {}).get("credit"))
    except Exception as e:
        print(f"  [warn] 大盤融資跳過: {e}")
    try:
        cob = fetch_cobasic()
        for s in stocks:
            c = cob.get(s["id"])
            if c:
                s["co"] = {k: v for k, v in c.items() if v}
    except Exception as e:
        print(f"  [warn] 公司資料跳過: {e}")
    try:
        fetch_targets(stocks)
    except Exception as e:
        print(f"  [warn] 目標價/業務跳過: {e}")
    out = {"updated": taipei, "source": "live",
           "macro": _macro, "news": _news, "stocks": stocks}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    sz = os.path.getsize("data.json") // 1024
    print(f"完成:{len(stocks)} 檔({ok} 檔有完整數據),data.json {sz}KB")

if __name__ == "__main__":
    main()
