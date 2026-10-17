#!/usr/bin/env python3
"""r1111:節目推薦的好書 → <show>_books.json(永久、只增不減)
來源 ①:節目 podcast RSS 每集描述裡的「書名：/作者：/原文作者：/譯者：/出版社：/出版日期：/連結」區塊(財經皓角每週的抽書好書,官方寫的,最可靠)
來源 ②:AI 聽完整集的整理裡「## 本集推薦的書」段落(listen_show.py 的 prompt 會要它列出;節目口頭提到、描述沒寫的書,標「AI 聽到」)
用法:python fetch_books.py yth"""
import json, os, re, sys, html, datetime as dt
import requests
from listen_show import SHOWS, UA, norm

def log(*a): print(*a, flush=True)


def feed_items(C):
    j = requests.get(f"https://itunes.apple.com/lookup?id={C['apple']}", headers=UA, timeout=20).json()
    feed = ((j.get("results") or [{}])[0]).get("feedUrl")
    if not feed: return []
    xml = requests.get(feed, headers=UA, timeout=40).text
    out = []
    for blk in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def tag(t):
            m = re.search(rf"<{t}[^>]*>(.*?)</{t}>", blk, re.S); v = (m.group(1) if m else "").strip()
            return html.unescape(re.sub(r"^<!\[CDATA\[(.*)\]\]>$", r"\1", v, flags=re.S)).strip()
        d = re.sub(r"<br\s*/?>|</p>|</div>", "\n", tag("description")); d = re.sub(r"<[^>]+>", "", d)
        iso = ""
        try:
            from email.utils import parsedate_to_datetime
            iso = (parsedate_to_datetime(tag("pubDate")) + dt.timedelta(hours=8)).strftime("%Y-%m-%d")
        except Exception: pass
        out.append({"t": tag("title"), "d": html.unescape(d), "link": tag("link"), "dt": iso})
    return out


def parse_desc(d):
    """一集描述 → [{title, author, orig, trans, pub, pubd, url}];一集可能不只一本"""
    L = [x.strip() for x in d.split("\n")]
    books = []; cur = None
    for i, ln in enumerate(L):
        m = re.match(r"^書名[:：]\s*(.+)$", ln)
        if m:
            cur = {"title": m.group(1).strip(" 　"), "author": "", "orig": "", "trans": "", "pub": "", "pubd": "", "url": ""}
            books.append(cur); continue
        if not cur: continue
        for key, pat in (("orig", r"^原文作者[:：]\s*(.+)$"), ("author", r"^作者[:：]\s*(.+)$"), ("trans", r"^譯者[:：]\s*(.+)$"),
                         ("pub", r"^出版社[:：]\s*(.+)$"), ("pubd", r"^出版日期[:：]\s*(.+)$")):
            m = re.match(pat, ln)
            if m and not cur[key]: cur[key] = m.group(1).strip(" 　"); break
        else:
            m = re.match(r"^(https?://\S+)$", ln)
            if m and not cur["url"] and not re.search(r"jackalopelin|yutinghao\.finance|ecpay|reurl\.cc/(n563rd|rvvqAr)", ln): cur["url"] = m.group(1)
            elif ln.startswith("(") or ln.startswith("《早晨") or ln.startswith("免責"): cur = None   # 區塊結束
    return [b for b in books if len(b["title"]) >= 2]


def parse_digest(s):
    """AI 整理裡「## 本集推薦的書」段落:* **書名**(作者):他怎麼說"""
    out = []; inside = False
    for ln in str(s or "").split("\n"):
        if re.match(r"^\s*#{1,4}\s", ln): inside = bool(re.search(r"推薦的書|好書|書籍", ln)); continue
        if not inside: continue
        m = re.match(r"^\s*[-*•]\s+\*\*(.+?)\*\*\s*(?:[(（](.*?)[)）])?\s*[:：]?\s*(.*)$", ln)
        if m:
            t = m.group(1).strip("《》 ");
            if re.search(r"沒有|無|未提", t): continue
            out.append({"title": t, "author": (m.group(2) or "").strip(), "why": m.group(3).strip()[:160]})
    return out


def main():
    show = (sys.argv[1] if len(sys.argv) > 1 else "yth").strip()
    C = SHOWS.get(show)
    if not C: log(f"✗ 不認識的節目 {show}"); sys.exit(1)
    outp = f"{show}_books.json"
    try: old = json.load(open(outp, encoding="utf-8"))
    except Exception: old = {"v": 1, "show": show, "books": []}
    books = old.get("books") or []
    seen = {(norm(b.get("title")), b.get("ep_dt")) for b in books}
    added = 0
    # ① RSS 描述
    try:
        items = feed_items(C); log(f"RSS {len(items)} 集")
        for it in items:
            for b in parse_desc(it["d"]):
                k = (norm(b["title"]), it["dt"])
                if k in seen: continue
                seen.add(k); added += 1
                books.append({**b, "src": "desc", "ep": it["t"], "ep_dt": it["dt"], "ep_url": it["link"]})
    except Exception as e:
        log(f"  RSS 失敗:{e}")
    # ② AI 整理(yth.json 最近幾集 + 月歸檔)
    try:
        eps = []
        try: eps += (json.load(open(C["out"], encoding="utf-8")).get("eps") or [])
        except Exception: pass
        hd = C.get("hist_dir")
        if hd and os.path.isdir(hd):
            for f in sorted(os.listdir(hd)):
                if f.endswith(".json"):
                    try: eps += json.load(open(os.path.join(hd, f), encoding="utf-8")) or []
                    except Exception: pass
        for e in eps:
            edt = str(e.get("dt") or "")[:10]
            for b in parse_digest(e.get("s")):
                k = (norm(b["title"]), edt)
                if k in seen or any(norm(b["title"]) == norm(x.get("title")) and x.get("ep_dt") == edt for x in books): continue
                seen.add(k); added += 1
                books.append({"title": b["title"], "author": b["author"], "why": b["why"], "src": "ai", "ep": e.get("t"), "ep_dt": edt, "ep_url": e.get("yt") or ""})
    except Exception as e:
        log(f"  AI 整理解析失敗:{e}")
    books.sort(key=lambda b: (b.get("ep_dt") or ""), reverse=True)
    out = {"v": 1, "show": show, "name": C["name"], "u": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"), "n": len(books), "books": books}
    json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False)
    log(f"完成:{outp} 共 {len(books)} 本(新增 {added})")


if __name__ == "__main__":
    main()
