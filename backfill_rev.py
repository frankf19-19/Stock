#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
r575 月營收 + 季報歷史回補:把 c/tw*.json 的 rm/ry/ra(月營收)補到 40 個月、
fq/qr/gm/om/nm(季報)補到 12 季。研究報告的表格與圖表需要這些歷史才畫得出來。

來源(與 update_data.py 同源,逐月/逐季翻頁):
  月營收 = MOPS t21sc03 逐月彙總頁(上市 sii + 上櫃 otc,國內 0 / KY 1)
  季報   = MOPS ajax_t163sb06(綜合損益表:毛利率/營益率/淨利率/營收)
單位沿用後端既有慣例:ra=千元、qr=百萬元(前端 r575 起自動換算成億元)。
一次跑完約 15~25 分鐘;跑完後 c/tw*.json 直接被覆寫提交。
"""
import json, os, time, io, datetime as dt
import requests
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) research-backfill"}
REV_MONTHS = 40
FIN_QUARTERS = 12
TPE = dt.timezone(dt.timedelta(hours=8))


def log(*a):
    print(*a, flush=True)


def numf(x):
    try:
        v = float(str(x).replace(",", "").replace("%", "").strip())
        return None if v != v else v
    except Exception:
        return None


def months_back(n):
    """回傳最近 n 個月的 (year, month),由舊到新;不含當月(當月未申報)。"""
    now = dt.datetime.now(TPE)
    y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    out = []
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def fetch_rev_month(y, m):
    """單月全市場營收:{sid: (yoy%, 'YYYY-MM', amt千元)}"""
    out = {}
    roc = y - 1911
    for mk in ("sii", "otc"):
        for sfx in ("0", "1"):
            u = f"https://mops.twse.com.tw/nas/t21/{mk}/t21sc03_{roc}_{m}_{sfx}.html"
            try:
                r = requests.get(u, headers={**UA, "Referer": "https://mops.twse.com.tw/"}, timeout=25)
                if r.status_code != 200 or len(r.content) < 2000:
                    continue
                html = r.content.decode("big5", errors="ignore")
                for df in pd.read_html(io.StringIO(html)):
                    cols = ["".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in df.columns]

                    def ci(*pats):
                        return next((i for i, c in enumerate(cols) if all(p in c for p in pats)), None)

                    i_id, i_yoy, i_amt = ci("公司", "代號"), ci("去年同月", "增減"), ci("當月營收")
                    if None in (i_id, i_yoy):
                        continue
                    for _, row in df.iterrows():
                        sid = str(row.iloc[i_id]).strip()
                        if not (sid.isdigit() and 4 <= len(sid) <= 6):
                            continue
                        yoy = numf(row.iloc[i_yoy])
                        if yoy is None:
                            continue
                        amt = numf(row.iloc[i_amt]) if i_amt is not None else None
                        out[sid] = (yoy, f"{y}-{m:02d}", amt)
            except Exception as ex:
                log(f"  [warn] 月營收 {y}-{m:02d} {mk}/{sfx}: {ex}")
            time.sleep(0.4)
    return out


def fetch_fin_quarter(y, q):
    """單季全市場三率+營收:{sid: (label, gm, om, nm, rev百萬)}"""
    out = {}
    roc = y - 1911
    for typek in ("sii", "otc"):
        try:
            r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t163sb06",
                              data={"encodeURIComponent": 1, "step": 1, "firstin": 1,
                                    "off": 1, "TYPEK": typek, "year": str(roc), "season": f"{q:02d}"},
                              headers={**UA, "Referer": "https://mopsov.twse.com.tw/"}, timeout=30)
            if r.status_code != 200:
                continue
            html = r.content.decode("utf-8", errors="ignore")
            for df in pd.read_html(io.StringIO(html)):
                cols = [str(c) for c in df.columns]

                def ci(*pats):
                    return next((i for i, c in enumerate(cols) if all(p in c for p in pats)), None)

                i_id = ci("公司", "代號")
                i_gm, i_om, i_nm = ci("毛利率"), ci("營業利益率"), ci("稅後純益率")
                if i_nm is None:
                    i_nm = ci("淨利率")
                i_rv = ci("營業收入")
                if None in (i_id, i_gm, i_om, i_nm):
                    continue
                for _, row in df.iterrows():
                    sid = str(row.iloc[i_id]).strip()
                    if not (sid.isdigit() and len(sid) == 4):
                        continue
                    gm, om, nm = numf(row.iloc[i_gm]), numf(row.iloc[i_om]), numf(row.iloc[i_nm])
                    if None in (gm, om, nm):
                        continue
                    rv = numf(row.iloc[i_rv]) if i_rv is not None else None
                    out[sid] = (f"{y}Q{q}", gm, om, nm, rv)
        except Exception as ex:
            log(f"  [warn] 季報 {y}Q{q} {typek}: {ex}")
        time.sleep(0.6)
    return out


def quarters_back(n):
    now = dt.datetime.now(TPE)
    y, q = now.year, (now.month - 1) // 3 + 1
    q -= 1                      # 當季尚未公告
    if q == 0:
        y, q = y - 1, 4
    out = []
    for _ in range(n):
        out.append((y, q))
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return list(reversed(out))


def main():
    if not os.path.isdir("c"):
        log("找不到 c/ 目錄,結束"); return 1
    shards = {}
    for fn in sorted(os.listdir("c")):
        if fn.startswith("tw") and fn.endswith(".json"):
            try:
                shards[fn] = json.load(open(f"c/{fn}", encoding="utf-8"))
            except Exception:
                shards[fn] = {}
    if not shards:
        log("c/ 內沒有分片,結束"); return 1
    log(f"載入籌碼分片 {len(shards)} 個")

    def put(sid, key, val):
        fn = f"tw{sid[0]}.json"
        d = shards.get(fn)
        if d is None or sid not in d:
            return False
        e = d[sid]
        e.setdefault(key, [])
        return e

    # ── 月營收回補 ──
    mons = months_back(REV_MONTHS)
    log(f"回補月營收:{mons[0][0]}-{mons[0][1]:02d} ~ {mons[-1][0]}-{mons[-1][1]:02d}({len(mons)} 個月)")
    rev_by_month = {}
    for (y, m) in mons:
        got = fetch_rev_month(y, m)
        rev_by_month[f"{y}-{m:02d}"] = got
        log(f"  {y}-{m:02d}: {len(got)} 家")
    for fn, d in shards.items():
        for sid, e in d.items():
            rm, ry, ra = [], [], []
            for lab in [f"{y}-{m:02d}" for (y, m) in mons]:
                got = rev_by_month.get(lab, {}).get(sid)
                if not got:
                    continue
                rm.append(lab); ry.append(got[0]); ra.append(got[2])
            if len(rm) > len(e.get("rm", [])):
                e["rm"], e["ry"], e["ra"] = rm[-REV_MONTHS:], ry[-REV_MONTHS:], ra[-REV_MONTHS:]

    # ── 季報回補 ──
    qs = quarters_back(FIN_QUARTERS)
    log(f"回補季報:{qs[0][0]}Q{qs[0][1]} ~ {qs[-1][0]}Q{qs[-1][1]}({len(qs)} 季)")
    fin_by_q = {}
    for (y, q) in qs:
        got = fetch_fin_quarter(y, q)
        fin_by_q[f"{y}Q{q}"] = got
        log(f"  {y}Q{q}: {len(got)} 家")
    for fn, d in shards.items():
        for sid, e in d.items():
            fq, qr, gm, om, nm = [], [], [], [], []
            for lab in [f"{y}Q{q}" for (y, q) in qs]:
                got = fin_by_q.get(lab, {}).get(sid)
                if not got:
                    continue
                fq.append(got[0]); gm.append(got[1]); om.append(got[2]); nm.append(got[3]); qr.append(got[4])
            if len(fq) > len(e.get("fq", [])):
                e["fq"], e["gm"], e["om"], e["nm"], e["qr"] = (fq[-FIN_QUARTERS:], gm[-FIN_QUARTERS:],
                                                               om[-FIN_QUARTERS:], nm[-FIN_QUARTERS:],
                                                               qr[-FIN_QUARTERS:])

    tot_m = tot_q = 0
    for fn, d in shards.items():
        for sid, e in d.items():
            tot_m += len(e.get("rm", [])); tot_q += len(e.get("fq", []))
        json.dump(d, open(f"c/{fn}", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    n = sum(len(d) for d in shards.values()) or 1
    log(f"完成:平均每檔月營收 {tot_m/n:.1f} 筆、季報 {tot_q/n:.1f} 筆")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
