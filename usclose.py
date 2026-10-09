# r1041:🌙 美股昨晚收盤 → 台股隔天開盤評估(給 AI Pick 頁)
#   抓 Yahoo 日線:費半 ^SOX、那斯達克 ^IXIC、S&P ^GSPC、台積電 ADR TSM,加上加權 ^TWII 判斷「台股上次收盤後」美股走了多少。
#   歷史驗證(us_overnight_stat.json):2012~2026 共 3598 個台股交易日,用 archive/k 的 SOXX 與台股日 K 實測,三段期間分開看。
#   只用 requests(盤中輕量班沒有 pandas)。失敗回傳舊值,絕不讓主流程掛掉。
import json, time, datetime as dt
import requests

SYMS = [("^SOX", "sox", "費城半導體"), ("^IXIC", "ixic", "那斯達克"), ("^GSPC", "gspc", "S&P 500"), ("TSM", "tsm", "台積電 ADR"), ("^TWII", "twii", "加權指數")]
UA = {"User-Agent": "Mozilla/5.0"}


def _bars(sym):
    r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/" + requests.utils.quote(sym),
                     params={"range": "1mo", "interval": "1d"}, headers=UA, timeout=10)
    j = r.json()
    res = j["chart"]["result"][0]
    off = (res.get("meta") or {}).get("gmtoffset") or 0
    ts = res.get("timestamp") or []
    cl = res["indicators"]["quote"][0].get("close") or []
    out = {}
    for t, c in zip(ts, cl):
        if c:
            out[dt.datetime.utcfromtimestamp(t + off).strftime("%Y-%m-%d")] = round(float(c), 2)
    return sorted(out.items())


def _stat():
    try:
        return json.load(open("us_overnight_stat.json", encoding="utf-8"))
    except Exception:
        return None


def get(prev=None, max_age=1200):
    now = time.time()
    if prev and prev.get("ts") and now - prev["ts"] < max_age:
        return prev
    try:
        B = {}
        for sym, k, nm in SYMS:
            try:
                B[k] = _bars(sym)
            except Exception as e:
                print("usclose:", sym, e)
        tw = B.get("twii") or []
        tw_last = tw[-1][0] if tw else None
        ny_now = dt.datetime.utcnow() - dt.timedelta(hours=4)          # 美東(夏令);冬令差 1 小時只影響「盤中」判斷邊界
        ny_today, ny_min = ny_now.strftime("%Y-%m-%d"), ny_now.hour * 60 + ny_now.minute
        idx = {}
        for sym, k, nm in SYMS:
            if k == "twii" or not B.get(k):
                continue
            b = B[k]
            last_d, last_c = b[-1]
            live = (last_d == ny_today and ny_min < 16 * 60 + 5)
            done = [x for x in b if not (live and x[0] == last_d)]       # 已收盤的 K
            if len(done) < 2:
                continue
            d1, c1 = done[-1]; c0 = done[-2][1]
            it = {"nm": nm, "d": d1, "c": c1, "chg": round((c1 / c0 - 1) * 100, 2)}
            # 台股上次收盤之後美股累計走了多少(遇台股休市會累積多晚)
            if tw_last:
                base = [x for x in done if x[0] < tw_last]
                after = [x for x in done if x[0] >= tw_last]
                if base and after:
                    it["since"] = round((after[-1][1] / base[-1][1] - 1) * 100, 2)
                    it["nights"] = len(after)
            if live:
                it["live"] = round((last_c / c1 - 1) * 100, 2)
            idx[k] = it
        if not idx:
            return prev
        out = {"ts": int(now), "at": (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
               "tw_last": tw_last, "idx": idx, "stat": _stat()}
        return out
    except Exception as e:
        print("usclose 例外", e)
        return prev


if __name__ == "__main__":
    print(json.dumps(get(), ensure_ascii=False, indent=1)[:2000])
