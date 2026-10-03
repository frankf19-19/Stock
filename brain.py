#!/usr/bin/env python3
"""🧠 K研所大腦(r905)→ brain.json

像人一樣:記得經驗 → 每天收盤後回顧 → 寫下學到什麼 → 提出改進(驗證過才採用)。

每天做四件事:
  ① 訊號可信度:每種訊號(突破、分點進場、主力連買…)用「訊號後 20 日」的真實結果算勝率,
     用貝氏收縮(樣本少時往 50% 拉)得到「可信度」,跟上次比 → 變準/變不準
  ② AI Pick 自我檢討(台股、美股):實戰 vs 回測、最近 4 週 vs 全期、模型權重這週改重視什麼
  ③ AI 交易員檢討:依出場原因看賺賠(停損太多?移動停利太早?)
  ④ 行事曆:從資料學到新的休市日
產出:
  brain.json = { trust:{kind:{...}}, journal:[{d, items:[{tag, text, level}]}], suggestions:[...], snap:{...} }
規則:大腦「只記錄、只建議」;建議要累積足夠樣本、並在網站上由人確認後才改規則(驗證過才採用)。
"""
import json, os, datetime as dt, statistics as st

OUT = "brain.json"
TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ); TODAY = NOW.date().isoformat()

NAMES = {  # 訊號代號 → 白話
    "bk_sb": "分點連買", "bk_ss": "分點連賣", "bk_b": "分點大買", "bk_x": "分點大賣",
    "kb_b": "關鍵分點進場", "kb_x": "關鍵分點出場", "kb_b2": "兩家以上關鍵分點同日進場", "kb_x2": "兩家以上關鍵分點同日出場",
    "kb_sb": "關鍵分點連買", "kb_ss": "關鍵分點連賣", "kb_t1": "關鍵分點預期發動日", "kb_t2": "關鍵分點預期高點日",
    "fill": "AI Pick 成交", "chase": "AI Pick 追價成交", "tp": "AI Pick 停利", "sl": "AI Pick 停損", "exit": "AI Pick 出場", "exp": "AI Pick 到期",
    "fz": "最愛:進入買點帶", "ftp": "持股:到停利", "fh": "最愛:突破", "fl": "最愛:跌破",
    "lead_b": "主力大買", "lead_x": "主力大賣", "lead_s3": "主力開始連買",
}
BEAR = {"sl", "exit", "lead_x", "bk_ss", "bk_x", "kb_x", "kb_x2", "kb_ss", "fl"}


def load(p, d):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return d


# r912:實戰訊號 ↔ 15 年長期研究的對應(長期研究的勝率當「先驗」——先有多年經驗,再用實戰修正)
LONG_MAP = {"lead_b": "inst_big_buy", "lead_x": "inst_big_sell", "lead_s3": "inst_streak3", "fh": "brk20", "fl": "brk_dn_ma20"}
STUDY = {}


def trust_of(v, bear, kind=None):
    """貝氏收縮勝率:先驗 = 長期研究勝率(沒有就 50%)、強度 30 筆 → 樣本少時不會被幾筆運氣騙到"""
    wins = sum(1 for z in v if (z < 0 if bear else z > 0))
    p0 = ((STUDY.get("signals") or {}).get(LONG_MAP.get(kind, ""), {}) or {}).get("win20", 50) / 100
    return round(100 * (wins + 30 * p0) / (len(v) + 30), 1), round(100 * wins / len(v), 1)


def review_signals(prev, J):
    A = load("signal_arch.json", {"items": []})["items"]
    P = load("signal_log.json", {"items": []})["items"]
    by = {}
    for x in A:
        by.setdefault(str(x["k"]).split("|")[0], []).append(x)
    T = {}
    for k, xs in by.items():
        v = [x["f20"] for x in xs if x.get("f20") is not None]
        if len(v) < 10: continue
        bear = k in BEAR
        tr, raw = trust_of(v, bear, k)
        v5 = [x["f5"] for x in xs if x.get("f5") is not None]
        T[k] = {"name": NAMES.get(k, k), "n": len(v), "trust": tr, "win": raw, "med20": round(st.median(v), 2),
                "med5": round(st.median(v5), 2) if v5 else None, "bear": bear}
        old = (prev.get("trust") or {}).get(k)
        if old and abs(tr - old["trust"]) >= 3 and len(v) >= 30:
            up = tr > old["trust"]
            J.append({"tag": "訊號", "level": "good" if up else "warn",
                      "text": f"「{NAMES.get(k, k)}」可信度 {old['trust']} → {tr}({'變準' if up else '變不準'};{len(v)} 筆、20 日{'下跌' if bear else '上漲'}機率 {raw}%)"})
    pend = len(P)
    graded = sum(len(v) for v in by.values())
    if not T:
        oldest = min((x["d"] for x in P), default=None)
        J.append({"tag": "訊號", "level": "info",
                  "text": f"訊號記憶累積中:待評分 {pend:,} 筆(最早 {oldest or '—'}),已評分 {graded} 筆。每筆要等 20 個交易日才知道準不準,第一批約 {(dt.date.fromisoformat(oldest) + dt.timedelta(days=30)).isoformat() if oldest else '—'} 出爐。"})
    else:
        best = sorted([t for t in T.values() if t["n"] >= 30], key=lambda t: -t["trust"])[:3]
        worst = sorted([t for t in T.values() if t["n"] >= 30], key=lambda t: t["trust"])[:2]
        if best: J.append({"tag": "訊號", "level": "good", "text": "目前最可靠:" + "、".join(f"{t['name']}(可信度 {t['trust']})" for t in best)})
        if worst and worst[0]["trust"] < 50: J.append({"tag": "訊號", "level": "warn", "text": "目前最不可靠:" + "、".join(f"{t['name']}(可信度 {t['trust']})" for t in worst) + " —— 看到這類提醒要打折"})
    return T, {"pending": pend, "graded": graded}


def review_aipick(fn, label, prev, J, S):
    A = load(fn, None)
    if not A: return None
    st_live, st_bt = A.get("stats") or {}, A.get("stats_bt") or {}
    weeks = [w for w in A.get("weeks") or [] if not w.get("bt") and w.get("status") == "done"]
    rec = []
    for w in weeks[-4:]:
        for p in w.get("picks") or []:
            if p.get("ret") is not None: rec.append(p["ret"])
    snap = {"live_n": st_live.get("filled"), "live_win": st_live.get("win_rate"), "live_avg": st_live.get("avg_ret"),
            "bt_win": st_bt.get("win_rate"), "bt_avg": st_bt.get("avg_ret"),
            "rec_n": len(rec), "rec_avg": round(sum(rec) / len(rec), 2) if rec else None,
            "rec_win": round(100 * sum(1 for r in rec if r > 0) / len(rec)) if rec else None}
    if (snap["live_n"] or 0) >= 10 and snap["bt_win"] is not None and snap["live_win"] is not None:
        gap = snap["live_win"] - snap["bt_win"]
        J.append({"tag": label, "level": "good" if gap >= -5 else "warn",
                  "text": f"實戰 {snap['live_n']} 筆勝率 {snap['live_win']}%、平均 {snap['live_avg']}%;回測 {snap['bt_win']}%、{snap['bt_avg']}%"
                          + ("——實戰跟回測一致,模型可信" if gap >= -5 else f"——實戰比回測差 {abs(round(gap))} 個百分點,留意是否市場風格改變")})
    elif (snap["live_n"] or 0) < 10:
        J.append({"tag": label, "level": "info", "text": f"實戰樣本累積中({snap['live_n'] or 0} 筆,滿 10 筆開始跟回測比對)"})
    if snap["rec_n"] >= 8 and snap["rec_avg"] is not None and (snap["live_avg"] or 0) != 0:
        if snap["rec_avg"] < (snap["live_avg"] or 0) - 2:
            J.append({"tag": label, "level": "warn", "text": f"最近 4 週平均 {snap['rec_avg']}%,明顯低於全期 {snap['live_avg']}%——近期選股失靈,模型下週會用新結果重新訓練"})
        elif snap["rec_avg"] > (snap["live_avg"] or 0) + 2:
            J.append({"tag": label, "level": "good", "text": f"最近 4 週平均 {snap['rec_avg']}%,優於全期 {snap['live_avg']}%——近期手感好"})
    # 模型權重變化:這週最重視 / 權重變化最大的特徵
    L = A.get("learn") or {}
    w, feats = L.get("w") or [], L.get("feats") or L.get("names") or []
    if w and feats and len(w) == len(feats):
        sd = L.get("sd") or [1] * len(w)
        cur = {f: round(x, 3) for f, x, v in zip(feats, w, sd) if (v or 0) > 1e-4}   # 常數特徵(例:美股無籌碼資料)權重沒有意義,不列
        old = ((prev.get("snap") or {}).get(label) or {}).get("w") or {}
        top = sorted(cur.items(), key=lambda kv: -abs(kv[1]))[:3]
        J.append({"tag": label, "level": "info", "text": "模型目前最重視:" + "、".join(f"{k}({'+' if v > 0 else ''}{v})" for k, v in top)})
        if old:
            ch = sorted(((k, cur[k] - old.get(k, 0)) for k in cur), key=lambda kv: -abs(kv[1]))
            if ch and abs(ch[0][1]) >= 0.05:
                k, d = ch[0]
                J.append({"tag": label, "level": "info", "text": f"這次重新訓練後,「{k}」的權重{'提高' if d > 0 else '降低'} {abs(round(d, 3))}——從最新結果學到的調整"})
        snap["w"] = cur
    S[label] = snap
    return snap


def review_trader(J, SUG):
    T = load("aitrader.json", {})
    for mk, lab in (("TW", "AI 交易員(台股)"), ("US", "AI 交易員(美股)")):
        A = T.get(mk)
        if not A: continue
        s = A.get("sum") or {}
        if s.get("n_trades"):
            J.append({"tag": lab, "level": "good" if (s.get("ret") or 0) >= (s.get("bench_ret") or 0) else "warn",
                      "text": f"淨值 NT${s.get('nav_twd', 0):,}({s.get('ret')}%),同期 {'SPY' if mk == 'US' else '0050'} {s.get('bench_ret')}%;已平倉 {s.get('closed', 0)} 筆、勝 {s.get('wins', 0)}"})
        sells = [t for t in A.get("trades") or [] if t["side"] == "sell" and t.get("ret") is not None]
        if len(sells) >= 20:
            grp = {}
            for t in sells:
                why = t.get("why", "")
                g = "停損" if why.startswith("停損") else "移動停利" if why.startswith("移動停利") else "訊號轉弱"
                grp.setdefault(g, []).append(t)
            n = len(sells); sl = grp.get("停損", [])
            if len(sl) / n > 0.5:
                hold = st.median([t.get("hold") or 0 for t in sl])
                SUG.append({"id": f"trader_{mk}_stop", "area": lab, "status": "待驗證",
                            "text": f"{len(sl)}/{n} 筆是停損出場(中位持有 {hold} 天)——停損可能太緊。候選:停損從 2ATR 放寬到 2.5ATR,需先用過去資料回測比較再決定"})
    return


def review_study(prev, J, S):
    global STUDY
    STUDY = load("brain_study.json", {})
    sig = STUDY.get("signals") or {}
    if not sig: return
    S["study_u"] = STUDY.get("u")
    if (prev.get("snap") or {}).get("study_u") == STUDY.get("u"): return      # 研究沒更新就不重複寫
    rg = STUDY.get("range") or ["?", "?"]; base = STUDY.get("base") or {}
    J.append({"tag": "長期經驗", "level": "info",
              "text": f"讀完 {rg[0][:4]}~{rg[1][:4]} 年、{STUDY.get('stocks', 0):,} 檔的歷史:任意一天買進,20 日後上漲機率 {base.get('win20')}%、中位 {base.get('med20')}%(這是比較基準)"})
    bull = sorted([(k, v) for k, v in sig.items() if not v["bear"] and v.get("excess20") is not None], key=lambda kv: -kv[1]["excess20"])
    for k, v in bull[:2]:
        J.append({"tag": "長期經驗", "level": "good" if v["excess20"] > 0 else "info",
                  "text": f"「{v['name']}」{v['n']:,} 次:20 日上漲機率 {v['win20']}%、比同日大盤{'多' if v['excess20'] >= 0 else '少'} {abs(v['excess20'])}%,{v['stable']} 年有效"})
    for k, v in bull[-2:]:
        if v["excess20"] < 0:
            J.append({"tag": "長期經驗", "level": "warn",
                      "text": f"「{v['name']}」長期反而比大盤差 {abs(v['excess20'])}%({v['n']:,} 次)——看到這訊號別急著追"})
    for k, v in sig.items():
        if v["bear"]:
            J.append({"tag": "長期經驗", "level": "good" if v["win20"] > 52 else "info",
                      "text": f"「{v['name']}」{v['n']:,} 次:20 日下跌機率 {v['win20']}%、中位 {v['med20']}%,{v['stable']} 年有效"})


def review_v2(prev, J, S):
    """r937:AI Pick v2 模型每月重訓的結果"""
    L = load("brain_v2_log.json", {}).get("runs") or []
    if not L: return
    r = L[-1]; S["v2_last"] = r.get("d")
    if (prev.get("snap") or {}).get("v2_last") == r.get("d"): return
    if r.get("ok"):
        J.append({"tag": "AI Pick 模型", "level": "good",
                  "text": f"v2 模型重新訓練完成:{r.get('samples', 0):,} 筆樣本(到 {r.get('to')}),最近 52 週走查 {r['last52w'].get('avg_ret')}%/勝率 {r['last52w'].get('win')}%;目前最重視 " + "、".join(f"{k}({v:+})" for k, v in r.get("top", []))})
    else:
        J.append({"tag": "AI Pick 模型", "level": "warn", "text": f"v2 模型重訓未通過檢查(最近 52 週 {r['last52w'].get('avg_ret')}%),保留舊模型——市場風格可能改變,下月再試"})


def main():
    prev = load(OUT, {})
    J, S, SUG = [], {}, list(prev.get("suggestions") or [])
    review_study(prev, J, S)
    review_v2(prev, J, S)
    trust, mem = review_signals(prev, J)
    review_aipick("aipick.json", "AI Pick(台股)", prev, J, S)
    review_aipick("aipick_us.json", "AI Pick(美股)", prev, J, S)
    review_trader(J, SUG)
    H = load("holidays.json", {}); lr = H.get("learned") or {}
    new = [k for k in lr if k not in (prev.get("snap") or {}).get("learned_seen", [])]
    if new and prev:
        J.append({"tag": "行事曆", "level": "info", "text": "從資料學到新的休市日:" + "、".join(k.split(":", 1)[1] + ("(台股)" if k.startswith("tw") else "(美股)") for k in new[:5])})
    S["learned_seen"] = list(lr.keys())
    S["memory"] = mem
    # 去重建議(同 id 保留最新)
    seen, sug2 = set(), []
    for s in reversed(SUG):
        if s["id"] in seen: continue
        seen.add(s["id"]); sug2.append(s)
    journal = [j for j in (prev.get("journal") or []) if j.get("d") != TODAY]
    journal.append({"d": TODAY, "t": NOW.strftime("%H:%M"), "items": J})
    res = {"u": NOW.strftime("%Y-%m-%d %H:%M"), "trust": trust, "journal": journal[-60:], "hist": "brain_hist/", "suggestions": list(reversed(sug2))[-20:], "snap": S}
    with open(OUT, "w", encoding="utf-8") as f: json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    # r906:永久記憶——每天一筆(日誌 + 可信度快照 + AI Pick/交易員狀態),依年份存檔,永不刪除
    try:
        os.makedirs("brain_hist", exist_ok=True)
        hp = f"brain_hist/{TODAY[:4]}.json"
        Hh = load(hp, {"days": []})
        Hh["days"] = [x for x in Hh["days"] if x.get("d") != TODAY]
        Hh["days"].append({"d": TODAY, "t": NOW.strftime("%H:%M"), "items": J,
                           "trust": {k: {"n": v["n"], "trust": v["trust"], "win": v["win"], "med20": v["med20"]} for k, v in trust.items()},
                           "snap": {k: v for k, v in S.items() if k not in ("learned_seen",)}})
        Hh["days"].sort(key=lambda x: x["d"])
        with open(hp, "w", encoding="utf-8") as f: json.dump(Hh, f, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        print("大腦永久記憶寫入失敗", e)
    print(f"🧠 大腦:今日 {len(J)} 條心得、可信度追蹤 {len(trust)} 種訊號、待驗證建議 {len(sug2)} 條;記憶:待評分 {mem['pending']:,}、已評分 {mem['graded']:,}")


if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc(); print("大腦例外", e)
