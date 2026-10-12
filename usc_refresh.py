#!/usr/bin/env python3
"""r1082:只重算 AI Pick 頁「🌙 美股昨晚收盤 → 台股怎麼看」(aipick.json 的 usc),其他欄位原封不動。
給 usc.yml(排程保險發現這張卡過期時補跑)用。"""
import json, usclose
J = json.load(open("aipick.json", encoding="utf-8"))
u = usclose.get(None)
if u:
    J["usc"] = u
    json.dump(J, open("aipick.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("usc 更新:", u.get("at"), "台股上次收盤", u.get("tw_last"), {k: v.get("since", v.get("chg")) for k, v in (u.get("idx") or {}).items()})
else:
    print("usc 沒有更新(Yahoo 讀不到)")
