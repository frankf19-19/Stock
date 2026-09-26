#!/usr/bin/env python3
"""K研所 · 🤖 AI 交易員(r894)——台股、美股各一個 NT$1,000 萬模擬帳戶,往前實盤累積

不是回測,是「從開戶日起每天真的照規則交易」的模擬帳戶:
  • 選股:沿用 AI Pick 的評分模型(aipick.score_one),每週第一個交易日重新排名
  • 部位:最多 10 檔、每檔目標約 1/10 淨值、同產業最多 2 檔;台股可零股、美股以股為單位
  • 下單:限價單(模型建議買價,可追到 +1.5%),掛 5 個交易日沒成交就撤
  • 出場:沒有固定賣出日——只看三件事
        ① 停損:進場價 −2ATR(最多 −8%)
        ② 移動停利:從持有期間最高收盤回落 2.5ATR
        ③ 訊號轉弱:週排名掉出前 30% 且收盤跌破月線 → 下週一開盤賣
  • 成本:台股 手續費 0.1425%×6 折(最低 20 元)+ 賣出證交稅 0.3%;美股 複委託 0.1%(最低 US$5)+ 匯差 0.1%
  • 美股帳戶開戶時以當天匯率把 NT$1,000 萬換成美元,之後以美元交易,淨值再用當天匯率換回台幣顯示
  • 每筆交易都寫下理由;每天記淨值,並並列 0050 / SPY 同期「買進抱著」的淨值當對照

用法:AITRADER_MKT=TW python aitrader.py / AITRADER_MKT=US python aitrader.py
狀態:aitrader.json(兩個市場同檔,各自一格)
"""
import json, os, sys, datetime as dt

MKT = (os.environ.get("AITRADER_MKT") or "TW").upper()
os.environ["AIPICK_MKT"] = MKT                     # 讓 aipick 以同市場參數載入(時區/分片/跳動)
import aipick as AP                                   # noqa: E402

US = MKT == "US"
OUT = "aitrader.json"
CAP_TWD = 10_000_000
START = os.environ.get("AITRADER_START") or "2026-09-28"   # 開戶日(該週一起下單)
NPOS = 10
MAX_SEC = 2
ORDER_DAYS = 5
BENCH = "SPY" if US else "0050"
FEE = 0.001 if US else 0.001425 * 0.6
FEE_MIN = 5.0 if US else 20.0
TAX_SELL = 0.0 if US else 0.003
FX_SPREAD = 0.001 if US else 0.0


def r2(x): return round(float(x), 2)


def bar_at(sid, day):
    d, o = AP.bars_of(sid)
    try:
        i = d.index(day)
    except ValueError:
        return None
    b = o[i]
    return b if len(b) >= 4 and b[3] else None


def close_on_or_before(sid, day):
    d, o = AP.bars_of(sid)
    for i in range(len(d) - 1, -1, -1):
        if d[i] <= day and len(o[i]) >= 4 and o[i][3]:
            return o[i][3]
    return None


def ma20_upto(sid, day):
    d, o = AP.bars_of(sid)
    c = [o[i][3] for i in range(len(d)) if d[i] <= day and len(o[i]) >= 4 and o[i][3]]
    return sum(c[-20:]) / min(20, len(c)) if c else None


def fee_of(amt):
    return max(FEE_MIN, amt * FEE) + amt * FX_SPREAD


def new_acct(data):
    fx = float(((data.get("macro") or {}).get("fx") or {}).get("USDTWD") or 31.6) if US else 1.0
    cash = CAP_TWD / fx
    return {"mkt": MKT, "start": START, "cap_twd": CAP_TWD, "fx0": fx, "cur": "USD" if US else "TWD",
            "cash": r2(cash), "cap": r2(cash), "pos": {}, "orders": {}, "trades": [], "nav": [],
            "bench": {"sym": BENCH, "px0": None}, "last_day": None, "last_rank": None}


def rank_universe(data, day):
    out = []
    for s in data.get("stocks") or []:
        if s.get("market") != MKT or s.get("etf") or s.get("disp"): continue
        d, o = AP.bars_of(s["id"])
        if not d: continue
        r = AP.score_one(s, d, o, day)
        if not r: continue
        sc, why, meta = r
        out.append((sc, s, why, meta))
    out.sort(key=lambda x: -x[0])
    return out


def trade(A, day, side, sid, name, sh, px, reason, extra=None):
    amt = sh * px
    fee = fee_of(amt)
    tax = amt * TAX_SELL if side == "sell" else 0.0
    t = {"d": day, "side": side, "id": sid, "name": name, "sh": sh, "px": r2(px), "amt": r2(amt),
         "fee": r2(fee), "tax": r2(tax), "why": reason}
    if extra: t.update(extra)
    A["trades"].append(t)
    return fee, tax


def process_day(A, data, day, week_start, rank_cache):
    pos, orders = A["pos"], A["orders"]
    # ① 每週第一個交易日:訊號轉弱 → 開盤賣;重新排名、補掛單
    if week_start:
        R = rank_cache.get(day)
        if R is None:
            R = rank_universe(data, day); rank_cache[day] = R
        n = len(R); rk = {x[1]["id"]: i for i, x in enumerate(R)}
        A["last_rank"] = {"d": day, "n": n, "top": [{"id": x[1]["id"], "name": x[1].get("name"), "sc": round(x[0], 1)} for x in R[:12]]}
        for sid in list(pos):
            p = pos[sid]; b = bar_at(sid, day)
            if not b: continue
            m20 = ma20_upto(sid, AP.iso(dt.date.fromisoformat(day) - dt.timedelta(days=1)))
            r = rk.get(sid)
            if (r is None or r > n * 0.3) and m20 and p.get("lastc", p["entry"]) < m20:
                px = b[0]; fee, tax = trade(A, day, "sell", sid, p["name"], p["sh"], px,
                    f"訊號轉弱:週排名{'掉出候選' if r is None else f'第 {r+1}/{n}'}、收盤跌破月線 {m20:.2f} → 開盤出場",
                    {"entry": p["entry"], "ret": r2((px / p["entry"] - 1) * 100), "hold": p.get("days", 0)})
                A["cash"] = r2(A["cash"] + p["sh"] * px - fee - tax); del pos[sid]
        orders.clear()
        per = {}
        for sid, p in pos.items(): per[p.get("sec")] = per.get(p.get("sec"), 0) + 1
        slots = NPOS - len(pos)
        for sc, s, why, meta in R:
            if slots <= 0: break
            sid = s["id"]
            if sid in pos: continue
            sec = s.get("sector") or "?"
            if per.get(sec, 0) >= MAX_SEC: continue
            per[sec] = per.get(sec, 0) + 1; slots -= 1
            orders[sid] = {"name": s.get("name") or sid, "sec": sec, "buy": meta["buy"], "hi": meta["buy_hi"],
                           "atr": meta["atr"], "sc": round(sc, 1), "why": why[:4], "placed": day, "left": ORDER_DAYS}
    # ② 掛單成交(限價;跳空低開就用開盤價)
    nav_now = A["cash"] + sum(p["sh"] * p.get("lastc", p["entry"]) for p in pos.values())
    for sid in list(orders):
        o = orders[sid]; b = bar_at(sid, day)
        o["left"] -= 1
        if b:
            fill = b[0] if b[0] <= o["hi"] else (o["buy"] if b[2] <= o["buy"] else None)
            if fill:
                target = nav_now / NPOS; budget = min(target, A["cash"])
                sh = int(budget / (fill * (1 + FEE + FX_SPREAD)))
                if not US and sh >= 1000: sh = sh // 1000 * 1000 if sh >= 1000 else sh   # 台股:整張為主、零頭用零股
                if sh > 0 and budget >= target * 0.3:
                    fee, _ = trade(A, day, "buy", sid, o["name"], sh, fill,
                        f"模型評分 {o['sc']}(週排名前段)・" + "、".join(o["why"]) + f";限價 {o['buy']} 成交",
                        {"sc": o["sc"]})
                    A["cash"] = r2(A["cash"] - sh * fill - fee)
                    stop = max(fill * 0.92, fill - 2 * o["atr"])
                    pos[sid] = {"name": o["name"], "sec": o["sec"], "sh": sh, "entry": r2(fill), "d0": day,
                                "atr": o["atr"], "stop": AP.rtick(stop, "near"), "peak": fill, "lastc": b[3], "days": 0}
                    del orders[sid]; continue
        if o["left"] <= 0: del orders[sid]
    # ③ 持股風控:停損 / 移動停利(成交當天不檢查)
    for sid in list(pos):
        p = pos[sid]; b = bar_at(sid, day)
        if not b: continue
        if p["d0"] == day:
            p["lastc"] = b[3]; p["peak"] = max(p["peak"], b[3]); continue
        p["days"] = p.get("days", 0) + 1
        if b[2] <= p["stop"]:
            px = min(b[0], p["stop"]); trailing = p["stop"] >= p["entry"]
            fee, tax = trade(A, day, "sell", sid, p["name"], p["sh"], px,
                ("移動停利:從高點 {:.2f} 回落觸發 {:.2f}".format(p["peak"], p["stop"]) if trailing
                 else "停損:跌破 {:.2f}(進場 {:.2f})".format(p["stop"], p["entry"])),
                {"entry": p["entry"], "ret": r2((px / p["entry"] - 1) * 100), "hold": p["days"]})
            A["cash"] = r2(A["cash"] + p["sh"] * px - fee - tax); del pos[sid]; continue
        p["lastc"] = b[3]; p["peak"] = max(p["peak"], b[3])
        p["stop"] = AP.rtick(max(p["stop"], p["peak"] - 2.5 * p["atr"]), "near")
    # ④ 收盤淨值
    mv = sum(p["sh"] * p["lastc"] for p in pos.values())
    nav = A["cash"] + mv
    bpx = close_on_or_before(BENCH, day)
    if A["bench"]["px0"] is None and bpx: A["bench"]["px0"] = bpx
    fx = float(((data.get("macro") or {}).get("fx") or {}).get("USDTWD") or A["fx0"]) if US else 1.0
    A["nav"].append([day, r2(nav), r2(A["cash"]), len(pos), r2(bpx or 0), round(fx, 3)])


def run():
    data = AP.load_json("data.json", {})
    if not data.get("stocks"): print("aitrader:data.json 讀不到"); return
    J = AP.load_json(OUT, {})
    A = J.get(MKT) or new_acct(data)
    days, _ = AP.bars_of(AP.BENCH_SID)
    todo = [d for d in days if d >= A["start"] and (A["last_day"] is None or d > A["last_day"])]
    if not todo:
        print(f"aitrader[{MKT}]:沒有新交易日(開戶 {A['start']},最後處理 {A['last_day']})")
    rank_cache = {}
    for day in todo:
        prev = A["last_day"]
        wk = prev is None or dt.date.fromisoformat(prev).isocalendar()[:2] != dt.date.fromisoformat(day).isocalendar()[:2]
        process_day(A, data, day, wk, rank_cache)
        A["last_day"] = day
    # 摘要
    if A["nav"]:
        last = A["nav"][-1]; fx = last[5] if US else 1.0
        nav_twd = last[1] * fx
        b0 = A["bench"]["px0"]; bret = (last[4] / b0 - 1) * 100 if b0 and last[4] else None
        A["sum"] = {"d": last[0], "nav_twd": round(nav_twd), "ret": round((nav_twd / CAP_TWD - 1) * 100, 2),
                    "bench_ret": round(bret, 2) if bret is not None else None, "n_pos": last[3],
                    "cash_pct": round(last[2] / last[1] * 100, 1) if last[1] else None,
                    "n_trades": len(A["trades"]),
                    "closed": len([t for t in A["trades"] if t["side"] == "sell"]),
                    "wins": len([t for t in A["trades"] if t["side"] == "sell" and (t.get("ret") or 0) > 0]),
                    "fees": round(sum(t["fee"] + t["tax"] for t in A["trades"]), 2)}
        print(f"aitrader[{MKT}]:{last[0]} 淨值 NT${nav_twd:,.0f}({A['sum']['ret']:+.2f}%)vs {BENCH} {A['sum']['bench_ret']}%,持股 {last[3]} 檔")
    A["trades"] = A["trades"][-600:]
    A["nav"] = A["nav"][-800:]
    A["updated"] = AP.NOW.strftime("%Y-%m-%d %H:%M")
    J[MKT] = A
    J["rules"] = {"npos": NPOS, "max_sec": MAX_SEC, "order_days": ORDER_DAYS, "stop": "−2ATR(最多 −8%)",
                  "trail": "高點回落 2.5ATR", "decay": "週排名掉出前 30% 且跌破月線"}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(J, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        import traceback; traceback.print_exc()
        print("aitrader:例外", e); sys.exit(0)
