"""訊號成績單 → signal_stats.json
================================
站上幾十種訊號(AI Pick 成交/出場、最愛均線帶/突破/跌破、主力大買大賣、60 分 K 突破、大盤週乖離…),
只有 AI Pick 有戰績。notify.py 每輪把所有事件記進 signal_log.json;這支在重班回頭用日 K 補「訊號後 5 / 20 日報酬」,
再按類別、按事件種類彙總:次數、勝率、中位、平均、最差。半年後沒用的訊號就砍。
訊號後報酬 = 訊號日之後第 5/20 個交易日收盤 ÷ 訊號當下價格 − 1(沒有當下價格就用訊號日收盤)。
"""
import json, os, datetime as dt, statistics as st

LOG, OUT = "signal_log.json", "signal_stats.json"
_SH = {}


def log(*a): print(*a, flush=True)


def shard_key(sid):
    t = str(sid); return t[:3] if t[:2] == "00" else t[:2]


def bars_of(sid):
    if not sid: return [], []
    k = shard_key(sid)
    if k not in _SH:
        try: _SH[k] = json.load(open(f"k/tw{k}.json", encoding="utf-8"))
        except Exception: _SH[k] = {}
    e = _SH[k].get(sid) or {}
    d, o = e.get("d") or [], e.get("o") or []
    n = min(len(d), len(o)); return d[:n], o[:n]


def fill(items):
    n = 0
    for x in items:
        if x.get("f20") is not None or not x.get("id"): continue
        d, o = bars_of(x["id"])
        if not d: continue
        i = next((i for i, dd in enumerate(d) if dd >= x["d"]), None)
        if i is None: continue
        base = x.get("px") or o[i][3]
        if not base: continue
        if x.get("f5") is None and i + 5 < len(d): x["f5"] = round((o[i + 5][3] / base - 1) * 100, 2); n += 1
        if i + 20 < len(d): x["f20"] = round((o[i + 20][3] / base - 1) * 100, 2); n += 1
    return n


def agg(items):
    groups = {}
    for x in items:
        kind = str(x["k"]).split("|")[0]
        for g in (("cat", x.get("cat")), ("kind", kind)):
            groups.setdefault(g, []).append(x)
    out = {"cat": {}, "kind": {}}
    for (typ, key), xs in groups.items():
        r = {"n": len(xs), "pending": sum(1 for x in xs if x.get("f20") is None)}
        for h in ("f5", "f20"):
            v = [x[h] for x in xs if x.get(h) is not None]
            # 賣出類(sl/tp/exit/lead_x/跌破)是「訊號後應該跌」,方向翻過來算勝率
            bearish = key in ("sl", "exit", "lead_x", "fav_dn", "fav_brk_dn", "port_sl") or "跌破" in key or key.endswith("_x")
            if len(v) >= 3:
                win = sum(1 for z in v if (z < 0 if bearish else z > 0)) / len(v)
                r[h] = {"n": len(v), "win": round(100 * win), "med": round(st.median(v), 2), "avg": round(sum(v) / len(v), 2),
                        "worst": round(min(v) if not bearish else max(v), 2), "bear": bearish}
        out[typ][key] = r
    return out


def main():
    try: L = json.load(open(LOG, encoding="utf-8"))
    except Exception: log("沒有 signal_log.json"); return
    items = L.get("items") or []
    n = fill(items)
    json.dump(L, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    S = agg(items)
    S["u"] = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    S["total"] = len(items)
    S["since"] = items[0]["d"] if items else None
    json.dump(S, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"✅ 訊號成績單:{len(items)} 筆,本次補 {n} 個報酬;類別 {len(S['cat'])}、種類 {len(S['kind'])}")


if __name__ == "__main__":
    main()
