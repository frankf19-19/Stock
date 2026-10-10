"""r1061:一次性——從 git 歷史把「只留最近 N 天」檔案的舊版本全部翻出來,併進 archive/hist(網站自己的永久紀錄)
需要完整歷史:actions/checkout fetch-depth: 0(filter: blob:none 只在需要時才下載舊檔)"""
import os, sys, subprocess, shutil, datetime as dt
import archive_all as AA
# (路徑樣式, 對應的整理函式, 每隔幾天取一個舊版本——檔案本身保留越久,間隔可以越大)
TARGETS = [("e", "*.json", [AA.etf], 1), ("", "gov.json", [AA.gov], 1), ("", "gooaye.json", [AA.ai_text], 0),
           ("", "conf_ai.json", [AA.ai_text], 1), ("", "tdcc.json", [AA.tdcc9], 7), ("", "taifex.json", [AA.taifex], 30),
           ("sbl", "tw*.json", [AA.sbl], 60), ("c", "meta.json", [AA.market], 60), ("c", "tw*.json", [AA.fin_rev], 30),
           ("", "data.json", [AA.market], 1)]
TMP = "/tmp/rechist"
def sh(*a): return subprocess.run(a, capture_output=True, text=True).stdout
def main():
    since = os.environ.get("REC_SINCE", "2025-01-01")
    for d, pat, fns, every in TARGETS:
        spec = f"{d}/{pat}" if d else pat
        rows = [x.split(" ", 1) for x in sh("git", "log", f"--since={since}", "--format=%H %cI", "--", spec).splitlines() if x.strip()]
        rows.reverse()                                            # 由舊到新(新的覆蓋舊的)
        pick, last = [], None
        for h, t in rows:
            day = dt.date.fromisoformat(t[:10])
            if last is None or every == 0 or (day - last).days >= every: pick.append((h, t)); last = day
        AA.log(f"{spec}:{len(rows)} 個版本,取 {len(pick)} 個")
        for h, t in pick:
            shutil.rmtree(TMP, ignore_errors=True); os.makedirs(os.path.join(TMP, d or "."), exist_ok=True)
            names = [n for n in sh("git", "ls-tree", "--name-only", h, f"{d}/" if d else ".").splitlines()
                     if __import__("fnmatch").fnmatch(os.path.basename(n), pat) and (os.path.dirname(n) == d)]
            for n in names:
                b = subprocess.run(["git", "show", f"{h}:{n}"], capture_output=True).stdout
                if b: open(os.path.join(TMP, n), "wb").write(b)
            AA.SRC = TMP; AA.run_all(fns)
    AA.SRC = "."; AA.run_all()                                     # 最後用目前版本收尾(最新的為準)
    AA.log("翻出舊資料:" + "、".join(f"{k} +{v}" for k, v in AA.STAT.items()))
if __name__ == "__main__": main()
