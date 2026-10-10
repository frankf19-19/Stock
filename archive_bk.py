"""r1054:🗄 分點紀錄永久保存——我們自己的分點資料庫(GitHub Releases,不佔 repo、不會被快取清掉)
=====================================================================================
  bk15-<年>        每天一檔 <日期>.json.gz:全市場每檔「前 15 大買賣分點摘要」(買/賣分點、張數、均價、買賣家數、
                   主力淨額、集中度、成交張、隔日沖、買賣均價)——來源 bkraw(約 250 日)與每日新增
  bkall-<年>-<月>  每天一檔 <日期>.tsv.gz:全部券商買張/賣張/買均價/賣均價(FinMind Sponsor 有效時每天產生)
  bkall-backup     全券商多年歷史(bkall/)每週備份,依股票代號前兩碼分包;快取被清掉時 bkall.py 自動還原
狀態 → bk/_archive_status.json(網站顯示「已保存幾天」)
"""
import os, json, gzip, glob, subprocess, tarfile, time, datetime as dt

REPO = os.environ.get("GITHUB_REPOSITORY", "frankf19-19/Stock")
TMP = "/tmp/bkarc"


def log(*a): print(*a, flush=True)


def gh(*args, check=True):
    r = subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True)
    if check and r.returncode != 0: raise RuntimeError(f"gh {' '.join(args[:3])}: {r.stderr[:200]}")
    return r.stdout


def ensure(tag, title):
    if subprocess.run(["gh", "release", "view", tag, "-R", REPO], capture_output=True).returncode != 0:
        gh("release", "create", tag, "--title", title, "--notes", "K研所 分點紀錄永久保存(自動產生,請勿刪除)", "--latest=false")
        log(f"  建立 release {tag}")


def assets(tag):
    try: return {a["name"]: a.get("size") for a in json.loads(gh("release", "view", tag, "--json", "assets")).get("assets") or []}
    except Exception: return {}


def upload(tag, files):
    for i in range(0, len(files), 20):                          # 一次傳 20 個
        gh("release", "upload", tag, *files[i:i + 20], "--clobber")


def bk15():
    """bkraw(或 bk/)的前 15 大摘要 → 每天一檔"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb", "fetch_broker.py"); fb = importlib.util.module_from_spec(spec); spec.loader.exec_module(fb)
    R = fb.load_shards("bkraw") or fb.load_shards("bk")
    days = {}
    for sh in R.values():
        for sid, e in sh.items():
            for d, s in zip(e.get("d") or [], e.get("s") or []):
                if s: days.setdefault(d, {})[sid] = s
    if not days: log("bk15:沒有資料"); return {}
    os.makedirs(f"{TMP}/bk15", exist_ok=True)
    by_year = {}
    for d in sorted(days): by_year.setdefault(d[:4], []).append(d)
    have_all = []; recent = set(sorted(days)[-6:])                 # 最近 6 天每次重傳(晚上會陸續補齊)
    for y, ds in by_year.items():
        tag = f"bk15-{y}"; ensure(tag, f"分點前 15 大摘要 {y}")
        have = assets(tag); up = []
        for d in ds:
            nm = f"{d}.json.gz"
            if nm in have and d not in recent: continue
            p = f"{TMP}/bk15/{nm}"
            with gzip.open(p, "wt", encoding="utf-8") as f: json.dump(days[d], f, ensure_ascii=False, separators=(",", ":"))
            up.append(p)
        if up: upload(tag, up); log(f"  bk15-{y}:上傳 {len(up)} 天")
        have_all += [n[:10] for n in assets(tag)]
    have_all = sorted(set(have_all))
    return {"days": len(have_all), "from": have_all[0] if have_all else None, "to": have_all[-1] if have_all else None,
            "stocks_last": len(days.get(max(days), {}))}


def bkall_days():
    fs = sorted(glob.glob("bkraw/days/*.tsv.gz"))
    out = []
    for p in fs:
        d = os.path.basename(p)[:10]; tag = f"bkall-{d[:7]}"
        ensure(tag, f"全部券商分點 {d[:7]}")
        upload(tag, [p]); out.append(d)
    if out: log(f"  全券商每日:上傳 {len(out)} 天")
    return out


def deltas():
    """r1060:每班新抓到的全券商分點(bkall/_delta/<run>.tsv.gz)→ Releases bkall-delta-<年-月>,上傳成功才刪本機"""
    fs = sorted(glob.glob("bkall/_delta/*.tsv.gz"))
    if not fs: return 0
    tag = f"bkall-delta-{dt.datetime.now().strftime('%Y-%m')}"
    ensure(tag, f"全部券商分點・每班新增 {tag[-7:]}")
    n = 0
    for p in fs:
        try:
            gh("release", "upload", tag, p, "--clobber"); os.remove(p); n += 1
        except Exception as e: log(f"  每班新增上傳失敗(下班再傳):{e}")
    log(f"  全券商每班新增:上傳 {n} 檔 → {tag}")
    return n


def backup(force=False):
    """bkall/ 每週備份(依代號前兩碼分包)"""
    files = sorted(glob.glob("bkall/[0-9]*/*.tsv.gz"))
    if not files: return None
    st_p = "bkall/_backup.json"
    try: st = json.load(open(st_p))
    except Exception: st = {}
    size = sum(os.path.getsize(p) for p in files)
    every = 1 if size < 1.5e9 else 6.5                            # r1060:資料還小時每天整包備份;變大後每週(平時靠每班新增 delta)
    if not force and time.time() - st.get("t", 0) < every * 86400: return st
    ensure("bkall-backup", "全部券商分點歷史備份")
    os.makedirs(f"{TMP}/bak", exist_ok=True); groups = {}
    for p in files: groups.setdefault(os.path.basename(os.path.dirname(p))[:2], []).append(p)
    up = []
    for g, ps in groups.items():
        t = f"{TMP}/bak/bkall_{g}.tar"
        with tarfile.open(t, "w") as tf:
            for p in ps: tf.add(p, arcname=os.path.relpath(p, "bkall"))
        up.append(t)
    for extra in ("bkall/_state.json", "bkall/_brokers.json"):
        if os.path.exists(extra): up.append(extra)
    upload("bkall-backup", up)
    st = {"t": time.time(), "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "files": len(files)}
    json.dump(st, open(st_p, "w")); log(f"  全券商歷史備份:{len(files)} 檔 → {len(up)} 包")
    return st


def restore():
    """bkall/ 不見了(快取被清)→ 從 bkall-backup 還原"""
    if glob.glob("bkall/[0-9]*/*.tsv.gz"): return False
    if subprocess.run(["gh", "release", "view", "bkall-backup", "-R", REPO], capture_output=True).returncode != 0: return False
    os.makedirs(f"{TMP}/rest", exist_ok=True); os.makedirs("bkall", exist_ok=True)
    gh("release", "download", "bkall-backup", "-D", f"{TMP}/rest", "--clobber")
    n = 0
    for t in glob.glob(f"{TMP}/rest/*.tar"):
        with tarfile.open(t) as tf: tf.extractall("bkall"); n += 1
    for extra in ("_state.json", "_brokers.json"):
        p = f"{TMP}/rest/{extra}"
        if os.path.exists(p): os.replace(p, f"bkall/{extra}")
    log(f"從備份還原全券商歷史:{n} 包")
    try:                                                       # r1060:再把每班新增(備份之後抓的)依序補上
        import bkall
        tags = sorted(r["tag_name"] for r in json.loads(subprocess.run(["gh", "api", f"repos/{REPO}/releases?per_page=100"], capture_output=True, text=True).stdout or "[]") if str(r.get("tag_name", "")).startswith("bkall-delta-"))
        k = 0
        for tag in tags:
            os.makedirs(f"{TMP}/delta/{tag}", exist_ok=True)
            gh("release", "download", tag, "-D", f"{TMP}/delta/{tag}", "--clobber")
            for p in sorted(glob.glob(f"{TMP}/delta/{tag}/*.tsv.gz")):
                buf = {}
                for ln in gzip.open(p, "rt", encoding="utf-8"):
                    x = ln.rstrip("\n").split("\t")
                    if len(x) == 7: buf.setdefault(x[0], {})[(x[1], x[2])] = tuple(float(v) for v in x[3:])
                bkall.merge(buf, delta=False); k += 1
        log(f"  每班新增補回:{k} 檔")
    except Exception as e: log(f"  每班新增補回失敗:{e}")
    return True


def restore_bk15():
    """r1061:bkraw(前 15 大分點 250 日)快取不見了 → 從 Releases bk15-<年> 每日檔重建"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb", "fetch_broker.py"); fb = importlib.util.module_from_spec(spec); spec.loader.exec_module(fb)
    y = dt.date.today().year; n = 0; R = {}
    for tag in (f"bk15-{y - 1}", f"bk15-{y}"):
        if subprocess.run(["gh", "release", "view", tag, "-R", REPO], capture_output=True).returncode != 0: continue
        os.makedirs(f"{TMP}/b15/{tag}", exist_ok=True)
        gh("release", "download", tag, "-D", f"{TMP}/b15/{tag}", "--clobber")
        for p in sorted(glob.glob(f"{TMP}/b15/{tag}/*.json.gz")):
            day = os.path.basename(p)[:10]
            try:
                for sid, summ in json.load(gzip.open(p, "rt", encoding="utf-8")).items(): fb.raw_put(R, sid, day, summ)
                n += 1
            except Exception as e: log(f"  {p} 讀取失敗:{e}")
    if R: fb.save_shards(R, fb.RAW)
    log(f"從永久紀錄還原 bkraw:{n} 天、{sum(len(s) for s in R.values())} 檔"); return n


def main():
    st = {"t": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    try: st["bk15"] = bk15()
    except Exception as e: st["bk15_err"] = str(e)[:300]; log(f"bk15 失敗:{e}")
    try: st["delta"] = deltas()
    except Exception as e: st["delta_err"] = str(e)[:300]; log(f"每班新增失敗:{e}")
    try: st["bkall_days"] = bkall_days()[-5:]
    except Exception as e: st["bkall_err"] = str(e)[:300]; log(f"全券商每日失敗:{e}")
    try:
        b = backup(force=os.environ.get("BK_BACKUP_FORCE") == "1")
        if b: st["backup"] = {k: b.get(k) for k in ("at", "files")}
    except Exception as e: st["backup_err"] = str(e)[:300]; log(f"備份失敗:{e}")
    try:
        old = json.load(open("bk/_archive_status.json", encoding="utf-8"))
        for k in ("backup",):
            if k not in st and k in old: st[k] = old[k]
    except Exception: pass
    os.makedirs("bk", exist_ok=True)
    json.dump(st, open("bk/_archive_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(json.dumps(st, ensure_ascii=False))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "restore": restore()
    elif len(sys.argv) > 1 and sys.argv[1] == "restore_bk15": restore_bk15()
    else: main()
