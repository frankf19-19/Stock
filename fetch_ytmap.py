#!/usr/bin/env python3
"""r1114:節目每一集的 YouTube 影片對照表 → <show>_yt.json(永久、只增不減)
用 yt-dlp 的「扁平列表」抓頻道的 /streams 與 /videos 兩個分頁(直播與一般影片),只拿標題與影片 ID,不下載、不用金鑰、零成本;
標題正規化(去日期前綴/【標籤】/標點)後當 key,podcast 集名就能對到 YouTube 連結(推薦好書的「那集」連結、集數卡的 ▶️ YouTube)。
用法:python fetch_ytmap.py yth"""
import json, re, sys, datetime as dt
from listen_show import SHOWS, norm


def title_date(t):
    """標題裡的日期 → ISO:2026/10/14(三)… 或英文版 10/14/2026 (Wed)…(YouTube 會依語系回自動翻譯的標題)"""
    m = re.match(r"\s*(\d{4})/(\d{1,2})/(\d{1,2})", t)
    if m: return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m: return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def is_en(t): return not re.search(r"[\u4e00-\u9fff]", t or "")

def log(*a): print(*a, flush=True)


def main():
    show = (sys.argv[1] if len(sys.argv) > 1 else "yth").strip()
    C = SHOWS.get(show)
    if not C or not C.get("yt_cid"): log("✗ 沒有頻道 ID"); sys.exit(1)
    outp = f"{show}_yt.json"
    try: old = json.load(open(outp, encoding="utf-8"))
    except Exception: old = {"v": 1, "show": show, "m": {}}
    M = old.get("m") or {}; D = old.get("d") or {}
    try:
        import yt_dlp
    except Exception as e:
        log(f"✗ 沒有 yt-dlp:{e}"); sys.exit(1)
    opts = {"extract_flat": True, "quiet": True, "no_warnings": True, "skip_download": True, "playlistend": (1500 if not (M and D) else 80), "ignoreerrors": True,
            "extractor_args": {"youtube": {"lang": ["zh-TW", "zh-Hant", "zh"]}},      # 要中文標題(預設會拿到 YouTube 自動翻譯的英文標題,對不到 podcast 集名)
            "http_headers": {"Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5"}}
    added = 0; seen = 0; recent = []
    for tab in ("streams", "videos"):
        url = f"https://www.youtube.com/channel/{C['yt_cid']}/{tab}"
        try:
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(url, download=False) or {}
            ents = [e for e in (info.get("entries") or []) if e]
            log(f"  {tab}:{len(ents)} 支")
            for e in ents:
                vid = e.get("id"); t = e.get("title") or ""
                if not vid or not t: continue
                seen += 1; recent.append(vid)
                k = norm(t)
                if len(k) >= 6 and (k not in M or (is_en(M[k].get("t")) and not is_en(t))):
                    if k not in M: added += 1
                    M[k] = {"id": vid, "t": t}
                di = title_date(t)
                if di and (di not in D or not is_en(t)): D[di] = vid             # 同一天只有一場直播:日期也當 key(英文標題也對得到)
        except Exception as ex:
            log(f"  {tab} 失敗:{ex}")
    out = {"v": 1, "show": show, "u": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"), "n": len(M), "m": M, "d": D}
    if seen or not old.get("m"):
        json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False)
        # r1116:給前端的小檔(完整檔 300 KB 太大):日期索引全部 + 最近看到的 100 支標題索引(集數卡只需要最近幾集)
        rs = set(recent[:100]); lite_m = {k: v for k, v in M.items() if v.get("id") in rs}
        json.dump({"v": 1, "u": out["u"], "d": D, "m": lite_m}, open(f"{show}_yt_lite.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log(f"完成:{outp} 共 {len(M)} 支、日期索引 {len(D)} 天(新增 {added},本次看到 {seen},英文標題 {sum(1 for v in M.values() if is_en(v.get('t')))})")


if __name__ == "__main__":
    main()
