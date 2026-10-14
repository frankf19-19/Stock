#!/usr/bin/env python3
"""r1091:AI Pick 盤中輕量檔 → trader_live.json
aipick.json 有 490 KB(gzip 後 100 KB),前端盤中不可能每分鐘重抓;
盤中迴圈(update_quotes.yml 每 5 分鐘)跑完 aipick.py 後順便把「會在盤中變的部分」抽出來寫成小檔(約 30 KB,gzip 後 <10 KB),
前端盤中每 60 秒讀這個小檔併回 AI Pick 的 trader 狀態:開盤成交、盤中停損、關注清單、今天發生的事,一分鐘內就看得到。
"""
import json, datetime as dt

TZ = dt.timezone(dt.timedelta(hours=8))


def main():
    try: J = json.load(open("aipick.json", encoding="utf-8"))
    except Exception as e:
        print("aip_live:讀不到 aipick.json", e); return
    T = J.get("trader") or {}
    if not T: print("aip_live:沒有 trader 狀態"); return
    L = {k: T.get(k) for k in ("ver", "updated", "last_bar", "pos", "pend", "watch", "watch_d", "sig_done", "nav", "stats", "rules") if k in T}
    L["trades"] = (T.get("trades") or [])[-30:]
    L["log"] = (T.get("log") or [])[-60:]
    for grp in ("pv", "os"):                                        # 量價組 / 其他分組:只帶盤中會動的欄位
        G = T.get(grp) or {}
        if not G: continue
        g = {k: G.get(k) for k in ("ver", "updated", "pos", "pend", "picks", "picks_d", "nav", "stats", "rules", "pxmap", "last_rb", "done", "start", "n_scored") if k in G}
        g["log"] = (G.get("log") or [])[:20]
        g["trades"] = (G.get("trades") or [])[-20:]
        L[grp] = g
    out = {"u": dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "src": J.get("updated"), "trader": L}
    s = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    open("trader_live.json", "w", encoding="utf-8").write(s)
    print(f"aip_live:trader_live.json {len(s)//1024} KB(持股 {len(L.get('pos') or [])}、待買 {len(L.get('pend') or [])})")


if __name__ == "__main__":
    main()
