#!/usr/bin/env python3
"""🧠 AI Pick v2 每月自動重新訓練(r937)——休市日執行
1) 用最新 archive 重建 15 年特徵(v2_engine)2) 訓練新權重 3) 用最近 52 週走查式回測做 sanity 檢查
4) 通過就覆寫 aipick_v2_model.json,並把變化寫進 brain_v2_log.json 給大腦日誌用。距上次訓練 < 25 天就略過。"""
import json, os, sys, subprocess, datetime as dt, glob
import numpy as np
WORK = "v2work"; MODEL = "aipick_v2_model.json"; LOG = "brain_v2_log.json"
TODAY = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
old = {}
try: old = json.load(open(MODEL, encoding="utf-8"))
except Exception: pass
last = (old.get("trained_on") or {}).get("to", "2000-01-01")
if os.environ.get("FORCE") != "1" and (TODAY - dt.date.fromisoformat(last)).days < 25:
    print(f"retrain:上次訓練資料到 {last},未滿 25 天,略過"); sys.exit(0)
os.makedirs(WORK, exist_ok=True)
env = dict(os.environ, MKT="TW", V2WORK=WORK)
r = subprocess.run([sys.executable, "v2_engine.py"], env=env, capture_output=True, text=True, timeout=1500); print(r.stdout[-400:])
if not os.path.exists(f"{WORK}/tw_X.npy"): print("retrain:特徵建立失敗", r.stderr[-300:]); sys.exit(0)
# 寬度(過熱過濾用)
cal = json.load(open(f"{WORK}/tw_cal.json")); n = len(cal); above = np.zeros(n); cnt = np.zeros(n)
def ma(x, w):
    c = np.cumsum(np.nan_to_num(x)); out = np.full_like(x, np.nan); out[w - 1:] = (c[w - 1:] - np.concatenate(([0], c[:-w]))) / w; return out
for p in glob.glob(f"{WORK}/tw_bars/*.npy"):
    B = np.load(p); c = B[3].astype(float); ok = ~np.isnan(c); m20 = ma(c, 20); m60 = ma(c, 60); v = ok & ~np.isnan(m60)
    cnt += v; above += v & (c > m20)
np.save(f"{WORK}/tw_breadth.npy", np.stack([above / np.maximum(cnt, 1)] * 3))
sys.path.insert(0, "."); os.environ["MKT"] = "TW"; os.environ["V2WORK"] = WORK
import v2_sim as S
from v2_engine import FEATS
ybin = (S.Y > 0).astype(float); m = S.DAY < len(S.CAL) - 10
w, b, mu, sd = S.fit_logit(S.X[m], ybin[m])
# sanity:最近 52 週走查(A 模型 + 過熱過濾)
os.environ["REGIME"] = "b20>0.70"
cache = {}
def model_A(fi):
    yr = S.CAL[fi][:4]
    if yr in cache: return cache[yr]
    first = next(k for k in sorted(set(S.DAY.tolist())) if S.CAL[k][:4] == yr); mm = (S.DAY < first - 10)
    if mm.sum() < 20000: return None
    cache[yr] = S.fit_logit(S.X[mm], ybin[mm]); return cache[yr]
yrs = [TODAY.year - 1, TODAY.year]
res = S.simulate(model_A, yrs, "A"); cut = (TODAY - dt.timedelta(days=365)).isoformat()
rs = [x for x in res if "ret" in x and x["fri"] >= cut]; avg = float(np.mean([x["ret"] for x in rs])) if rs else 0; win = float(np.mean([x["ret"] > 0 for x in rs])) * 100 if rs else 0
ok = len(rs) >= 60 and avg > 0
new = {"ver": f"v2-{TODAY.isoformat()}", "feats": FEATS, "w": [round(float(x), 6) for x in w], "b": round(float(b), 6), "mu": [round(float(x), 6) for x in mu], "sd": [round(float(x), 6) for x in sd],
       "trained_on": {"samples": int(m.sum()), "from": S.CAL[int(S.DAY[m].min())], "to": S.CAL[int(S.DAY[m].max())]},
       "regime": old.get("regime") or {"rule": "b20>0.70"}, "backtest": dict(old.get("backtest") or {}, last52w={"avg_ret": round(avg, 2), "win": round(win, 1), "n": len(rs)})}
top = sorted(zip(FEATS, [float(x) for x in w]), key=lambda kv: -abs(kv[1]))[:3]
entry = {"d": TODAY.isoformat(), "ok": ok, "samples": int(m.sum()), "to": new["trained_on"]["to"], "last52w": new["backtest"]["last52w"], "top": [[k, round(v, 3)] for k, v in top],
         "prev": (old.get("trained_on") or {}).get("to")}
if ok:
    json.dump(new, open(MODEL, "w", encoding="utf-8"), ensure_ascii=False); print(f"retrain:✅ 新模型上線(樣本 {m.sum():,} 到 {new['trained_on']['to']};最近 52 週 {avg:+.2f}% 勝率 {win:.1f}%)")
else:
    print(f"retrain:⚠ 新模型未通過檢查(最近 52 週 {avg:+.2f}%、{len(rs)} 筆),保留舊模型")
try: L = json.load(open(LOG, encoding="utf-8"))
except Exception: L = {"runs": []}
L["runs"] = (L["runs"] + [entry])[-60:]; json.dump(L, open(LOG, "w", encoding="utf-8"), ensure_ascii=False)
