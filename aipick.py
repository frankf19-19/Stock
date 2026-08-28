#!/usr/bin/env python3
"""K研所 · 🤖 AI Pick 週選模型 v1(r702)
每週五收盤後(或週末/週一第一班)由量化模型選出「下週看漲」的台股 5 檔,
給出本週建議買價/追價上限/目標/停損,寫入 aipick.json 後**凍結不再改動**;
之後每一班都用 k/ 分片的實際 K 線回頭核對:有沒有成交、下週收在哪、有沒有到目標/停損,
累積成準確率與漲跌幅統計,前端 AI Pick 區塊直接讀。

輸入:data.json、k/tw*.json      輸出:aipick.json(自我累積,不可被覆蓋重建)
規則:
  ・買進週 = 建議買進的那一週(週一日期);評估週 = 買進週的下一週
  ・成交判定:買進週任一日 開盤≤買價 → 以開盤成交;最低≤買價 → 以買價成交;
              否則最低≤追價上限 → 以追價上限成交;全週都沒碰到 → 未成交(不計入勝率)
  ・結算:評估週最後一根 K 收盤 vs 成交價;>0 命中(win)、<0 失誤(loss)、=0 平(flat)
  ・目標/停損:成交後(含成交日)任一日 最高≥目標 → 到目標;最低≤停損 → 觸停損(統計用,不改變結算)
"""
import json, os, sys, datetime as dt

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
TODAY = NOW.date()
OUT = "aipick.json"
MODEL = "v1"
N_PICK = 5
MAX_PER_SECTOR = 2
KEEP_WEEKS = 80


# ───────────────────────── 工具 ─────────────────────────
def monday(d):
    return d - dt.timedelta(days=d.weekday())


def iso(d):
    return d.isoformat()


def tick(px):
    """台股升降單位"""
    if px < 10: return 0.01
    if px < 50: return 0.05
    if px < 100: return 0.1
    if px < 500: return 0.5
    if px < 1000: return 1.0
    return 5.0


def rtick(px, mode="near"):
    t = tick(px)
    q = px / t
    if mode == "down": q = int(q)
    elif mode == "up": q = int(q) + (0 if abs(q - int(q)) < 1e-9 else 1)
    else: q = round(q)
    v = q * t
    return round(v, 2)


def avg(a):
    return sum(a) / len(a) if a else 0.0


def atr(o, p=14):
    """o=[[開,高,低,收,量]...] 取最後 p 期 TR 簡單平均"""
    if len(o) < p + 1: return None
    s = 0.0
    for i in range(len(o) - p, len(o)):
        h, l, pc = o[i][1], o[i][2], o[i - 1][3]
        s += max(h - l, abs(h - pc), abs(l - pc))
    return s / p


def shard_key(sid):
    t = str(sid)
    return t[:3] if t[:2] == "00" else t[:2]


_SH = {}
def shard(sid):
    k = shard_key(sid)
    if k not in _SH:
        p = f"k/tw{k}.json"
        try:
            with open(p, encoding="utf-8") as f: _SH[k] = json.load(f)
        except Exception:
            _SH[k] = {}
    return _SH[k]


def bars_of(sid):
    e = shard(sid).get(sid)
    if not e or not isinstance(e.get("d"), list) or not isinstance(e.get("o"), list): return [], []
    d, o = e["d"], e["o"]
    n = min(len(d), len(o))
    return d[:n], o[:n]


def load_json(p, default):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception:
        return default


# ───────────────────────── 選股模型 ─────────────────────────
def score_one(s, d, o, cutoff):
    """回傳 (score, why[], meta) 或 None。cutoff:只用日期 < cutoff 的 K"""
    idx = [i for i, x in enumerate(d) if x < cutoff]
    if len(idx) < 65: return None
    o = [o[i] for i in idx]
    d = [d[i] for i in idx]
    if any(len(x) < 5 for x in o[-65:]): return None
    c = [x[3] for x in o]; h = [x[1] for x in o]; l = [x[2] for x in o]; v = [x[4] or 0 for x in o]
    last = c[-1]
    if not (last >= 10): return None
    ma5, ma10, ma20, ma60 = avg(c[-5:]), avg(c[-10:]), avg(c[-20:]), avg(c[-60:])
    ma20p = avg(c[-25:-5])
    r5 = last / c[-6] - 1; r20 = last / c[-21] - 1; r60 = last / c[-61] - 1
    bias20 = last / ma20 - 1
    v5, v20 = avg(v[-5:]), avg(v[-20:])
    if v20 <= 0: return None
    vr = v5 / v20
    liq = avg([c[i] * v[i] for i in range(len(c) - 20, len(c))]) * 1000   # 元/日
    if liq < 3e7: return None                                            # 日均成交值 < 3,000 萬:流動性不足
    h20 = max(h[-21:-1]); near = last / h20
    a = atr(o, 14)
    if not a or a <= 0: return None
    # 追高/乖離過大剔除
    if r5 > 0.15 or bias20 > 0.15: return None
    # 連續跌破季線且季線下彎:不做
    if last < ma60 and ma20 < ma60 and ma20 < ma20p: return None

    sc = 0.0; why = []
    # 趨勢結構
    if ma5 > ma20: sc += 10
    if ma20 > ma60: sc += 10; why.append("月線在季線上")
    if last > ma20: sc += 5
    if ma20 > ma20p: sc += 4; why.append("月線翻揚")
    # 動能
    sc += max(-10, min(25, r20 * 100)) * 0.8 + max(-20, min(50, r60 * 100)) * 0.3
    if r20 > 0.05: why.append(f"20日 {r20*100:+.1f}%")
    # 突破位置
    if near >= 0.98: sc += 10; why.append("貼近20日高" if last <= h20 else "創20日新高")
    if last > h20: sc += 5
    # 量能
    if 1.1 <= vr <= 2.5: sc += 8; why.append(f"量增 {vr:.1f}x")
    elif vr > 2.5: sc += 3; why.append(f"爆量 {vr:.1f}x")
    elif vr < 0.7: sc -= 5
    # 乖離健康度
    if 0 <= bias20 <= 0.06: sc += 6
    elif bias20 <= 0.10: sc += 2
    elif bias20 > 0.10: sc -= 6
    elif bias20 < -0.03: sc -= 4
    # 基本面 / 籌碼
    f = ((s.get("f") or {}).get("score") or 50); cs = ((s.get("c") or {}).get("score") or 50)
    sc += (f - 50) / 50 * 12; sc += (cs - 50) / 50 * 10
    if f >= 70: why.append(f"基本面 {f} 分")
    raw = ((s.get("c") or {}).get("raw") or {})
    f5 = raw.get("f5")
    if isinstance(f5, (int, float)) and f5 > 0 and f5 / max(v20 * 5, 1) > 0.05:
        sc += 6; why.append(f"外資5日 +{int(f5):,} 張")
    if s.get("t3"): sc += 4; why.append("三率三升")
    if s.get("thesis"): sc += 3
    # 回測不破(拉回站穩 10 日線且月線向上)
    kind = "trend"
    if r5 <= 0 and last >= ma10 and ma20 > ma20p:
        sc += 4; kind = "pullback"; why.append("拉回站穩10日線")
    if last > h20 and vr >= 1.1: kind = "break"
    # 買價:貼近 5 日線 → 直接以收盤買;否則等回測到 5 日線附近(不低於收盤-0.5ATR)
    bias5 = last / ma5 - 1
    if bias5 <= 0.015: buy = last
    else: buy = max(ma5, last - 0.5 * a)
    buy = rtick(buy, "down")
    buy_hi = rtick(buy * 1.015, "up")
    tgt = rtick(min(buy * 1.12, max(buy * 1.04, buy + 2.0 * a)), "near")
    stp = rtick(max(buy * 0.92, buy - 2.0 * a), "near")
    meta = {"ref_close": round(last, 2), "ref_day": d[-1], "atr": round(a, 2), "buy": buy, "buy_hi": buy_hi,
            "target": tgt, "stop": stp, "kind": kind, "r20": round(r20 * 100, 1), "bias20": round(bias20 * 100, 1),
            "vr": round(vr, 2)}
    return sc, why[:5], meta


def gen_week(data, buy_week):
    cutoff = iso(buy_week)
    cands = []
    for s in data.get("stocks", []):
        if s.get("market") != "TW" or s.get("etf") or s.get("disp"): continue
        if not (isinstance(s.get("price"), (int, float)) and s["price"] > 0): continue
        d, o = bars_of(s["id"])
        if not d: continue
        r = score_one(s, d, o, cutoff)
        if not r: continue
        sc, why, meta = r
        cands.append((sc, s, why, meta))
    cands.sort(key=lambda x: -x[0])
    picks, per = [], {}
    for sc, s, why, meta in cands:
        sec = s.get("sector") or "其他"
        if per.get(sec, 0) >= MAX_PER_SECTOR: continue
        per[sec] = per.get(sec, 0) + 1
        picks.append({"id": s["id"], "name": s.get("name") or s["id"], "sector": sec,
                      "score": round(sc, 1), "why": why, **meta,
                      "fill": None, "entry": None, "hi": None, "lo": None, "last": None, "last_day": None,
                      "ret": None, "hit_tp": False, "hit_sl": False, "result": "pending"})
        if len(picks) >= N_PICK: break
    ref_day = max((p["ref_day"] for p in picks), default=cutoff)
    return {"buy_week": cutoff, "eval_week": iso(buy_week + dt.timedelta(days=7)),
            "made": NOW.strftime("%Y-%m-%d %H:%M"), "ref_day": ref_day, "model": MODEL,
            "status": "open", "picks": picks, "n_cand": len(cands)}


# ───────────────────────── 追蹤結算 ─────────────────────────
def evaluate(week):
    bw = dt.date.fromisoformat(week["buy_week"]); ew = bw + dt.timedelta(days=7)
    bw_end = iso(bw + dt.timedelta(days=4)); ew_end = iso(ew + dt.timedelta(days=4))
    buy_week_over = TODAY > bw + dt.timedelta(days=6)
    eval_over = TODAY > ew + dt.timedelta(days=6)     # 評估週之後的週一起一定結算
    all_done = True
    for p in week["picks"]:
        d, o = bars_of(p["id"])
        bb = [(d[i], o[i]) for i in range(len(d)) if week["buy_week"] <= d[i] <= bw_end and len(o[i]) >= 4]
        eb = [(d[i], o[i]) for i in range(len(d)) if week["eval_week"] <= d[i] <= ew_end and len(o[i]) >= 4]
        # 成交判定(僅買進週)
        fill, entry = p.get("fill"), p.get("entry")
        if not fill:
            for day, b in bb:
                op, hi, lo = b[0], b[1], b[2]
                if op <= p["buy"]: fill, entry = day, op; break
                if lo <= p["buy"]: fill, entry = day, p["buy"]; break
            if not fill:
                for day, b in bb:
                    if b[2] <= p["buy_hi"]: fill, entry = day, min(max(b[0], p["buy"]), p["buy_hi"]); break
        p["fill"], p["entry"] = fill, (round(entry, 2) if entry else None)
        if fill:
            held = [(day, b) for day, b in (bb + eb) if day >= fill]
            hi = max((b[1] for _, b in held), default=None)
            lo = min((b[2] for _, b in held), default=None)
            lastc = held[-1][1][3] if held else None
            p["hi"], p["lo"], p["last"], p["last_day"] = hi, lo, lastc, (held[-1][0] if held else None)
            p["hit_tp"] = bool(hi is not None and hi >= p["target"])
            p["hit_sl"] = bool(lo is not None and lo <= p["stop"])
            p["ret"] = round((lastc / entry - 1) * 100, 2) if (lastc and entry) else None
            done = bool(eb and (eb[-1][0] >= ew_end or eval_over))
            if done:
                r = p["ret"] or 0
                p["result"] = "win" if r > 0 else ("loss" if r < 0 else "flat")
            else:
                p["result"] = "pending"; all_done = False
        else:
            if buy_week_over and (bb or TODAY > bw + dt.timedelta(days=9)):
                p["result"] = "nofill"
            else:
                p["result"] = "pending"; all_done = False
    if all_done and week["picks"]:
        week["status"] = "done"
    elif TODAY >= ew:
        week["status"] = "tracking"
    else:
        week["status"] = "open"


def stats_of(weeks):
    done = [w for w in weeks if w.get("status") == "done"]
    picks = [p for w in done for p in w["picks"]]
    filled = [p for p in picks if p.get("result") in ("win", "loss", "flat")]
    wins = [p for p in filled if p["result"] == "win"]; losses = [p for p in filled if p["result"] == "loss"]
    rets = [p["ret"] for p in filled if isinstance(p.get("ret"), (int, float))]
    wr = [p["ret"] for p in wins]; lr = [p["ret"] for p in losses]
    st = {"weeks": len(done), "n": len(picks), "filled": len(filled), "nofill": len([p for p in picks if p.get("result") == "nofill"]),
          "wins": len(wins), "losses": len(losses), "flat": len([p for p in filled if p["result"] == "flat"]),
          "win_rate": round(len(wins) / (len(wins) + len(losses)) * 100, 1) if (wins or losses) else None,
          "avg_ret": round(avg(rets), 2) if rets else None,
          "avg_win": round(avg(wr), 2) if wr else None, "avg_loss": round(avg(lr), 2) if lr else None,
          "best": max(rets) if rets else None, "worst": min(rets) if rets else None,
          "tp_rate": round(len([p for p in filled if p.get("hit_tp")]) / len(filled) * 100, 1) if filled else None,
          "sl_rate": round(len([p for p in filled if p.get("hit_sl")]) / len(filled) * 100, 1) if filled else None,
          "sum_ret": round(sum(rets), 2) if rets else None}
    # 每週小結(勝/檔/平均)
    st["by_week"] = []
    eq = 100.0; curve = []
    for w in done:
        fw = [p for p in w["picks"] if p.get("result") in ("win", "loss", "flat")]
        r = [p["ret"] for p in fw if isinstance(p.get("ret"), (int, float))]
        a = avg(r) if r else 0.0
        eq *= (1 + a / 100); curve.append(round(eq, 2))
        st["by_week"].append({"buy_week": w["buy_week"], "n": len(w["picks"]), "filled": len(fw),
                              "wins": len([p for p in fw if p["result"] == "win"]), "avg": round(a, 2) if r else None})
    st["equity"] = curve
    return st


# ───────────────────────── 主流程 ─────────────────────────
def main():
    data = load_json("data.json", {})
    if not data.get("stocks"):
        print("aipick:data.json 不可用,略過"); return
    J = load_json(OUT, {"model": MODEL, "weeks": [], "stats": {}})
    weeks = J.get("weeks") or []
    weeks = [w for w in weeks if isinstance(w, dict) and w.get("buy_week")]

    # 這一班應該存在的「買進週」
    wd = TODAY.weekday(); hm = NOW.hour * 60 + NOW.minute
    if (wd == 4 and hm >= 14 * 60 + 30) or wd >= 5:
        buy_week = monday(TODAY) + dt.timedelta(days=7)
    else:
        buy_week = monday(TODAY)
    force = os.environ.get("AIPICK_FORCE") == "1"
    if not weeks:   # 首次建檔:用「當時只看得到的 K」逐週回測過去 26 週(walk-forward),讓統計一開始就有樣本;標記 bt=True 與實戰分開統計
        n_bt = int(os.environ.get("AIPICK_BACKFILL", "26") or 0)
        for k in range(n_bt, 0, -1):
            bwk = monday(TODAY) - dt.timedelta(days=7 * k)
            if bwk + dt.timedelta(days=13) > TODAY: continue      # 評估週還沒走完的不回測
            w = gen_week(data, bwk)
            if w["picks"]:
                w["bt"] = True; weeks.append(w)
        print(f"aipick:回測建檔 {len(weeks)} 週")
    have = next((w for w in weeks if w["buy_week"] == iso(buy_week)), None)
    if force and have:
        weeks = [w for w in weeks if w is not have]; have = None; print("aipick:AIPICK_FORCE 重算本週")
    if not have:
        ok = True
        if wd == 4 and buy_week > monday(TODAY):   # 週五盤後:必須等到週五 K 入庫(以台積電為準)才選,否則留給下一班
            d, _ = bars_of("2330")
            if not d or d[-1] < iso(TODAY):
                ok = False; print(f"aipick:週五 K 尚未入庫(最新 {d[-1] if d else '無'}),本班不選股")
        if ok:
            w = gen_week(data, buy_week)
            if w["picks"]:
                weeks.append(w)
                print(f"aipick:選出 {w['buy_week']} 買進週 {len(w['picks'])} 檔(候選 {w['n_cand']}):" +
                      "、".join(f"{p['name']}@{p['buy']}" for p in w["picks"]))
            else:
                print("aipick:無符合標的,本週不選")
    # 逐週結算(已 done 的不再動,結果永久凍結)
    for w in weeks:
        if w.get("status") != "done":
            try: evaluate(w)
            except Exception as e: print("aipick:evaluate 失敗", w.get("buy_week"), e)
    weeks.sort(key=lambda w: w["buy_week"])
    weeks = weeks[-KEEP_WEEKS:]
    out = {"model": MODEL, "updated": NOW.strftime("%Y-%m-%d %H:%M"), "weeks": weeks,
           "stats": stats_of([w for w in weeks if not w.get("bt")]),        # 實戰(凍結後追蹤)
           "stats_bt": stats_of([w for w in weeks if w.get("bt")])}         # 回測(首次建檔 walk-forward)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    st, sb = out["stats"], out["stats_bt"]
    print(f"aipick:完成 實戰 {st['weeks']} 週 勝率 {st['win_rate']}% 平均 {st['avg_ret']}% | 回測 {sb['weeks']} 週 勝率 {sb['win_rate']}% 平均 {sb['avg_ret']}%")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("aipick:例外", e); sys.exit(0)   # 絕不讓主流程失敗
