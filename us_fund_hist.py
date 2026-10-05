"""r1002:美股歷史季報(SEC EDGAR XBRL frames)——給 AI Pick 美股做「基本面條件」滾動驗證與實盤篩選
每一季、每個科目一個請求(全市場),2012Q1 起約 58 季 × 4 科目 ≈ 230 個請求;已抓過的季只補最近 3 季。
輸出 archive/usf_hist.json.gz:{"updated":..,"q":["12Q1",...],"s":{"AAPL":{"rev":[百萬,...],"ni":[..],"eps":[..],"oi":[..]}}}
各陣列與 q 對齊(缺值 null)。季報公開時間:回測一律假設「季末 +60 天」才看得到(10-Q 法定 40~45 天、10-K 60~75 天)。"""
import json, gzip, os, time, datetime
import fetch_usf as F

OUT = "archive/usf_hist.json.gz"
TAGS = [("rev", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD"), ("rev", "Revenues", "USD"),
        ("rev", "SalesRevenueNet", "USD"), ("ni", "NetIncomeLoss", "USD"), ("oi", "OperatingIncomeLoss", "USD"),
        ("eps", "EarningsPerShareDiluted", "USD-per-shares")]


def quarters():
    t = datetime.date.today(); y, q = t.year, (t.month - 1) // 3 + 1; out = []
    yy, qq = 2012, 1
    while (yy, qq) < (y, q):
        out.append((yy, qq)); qq += 1
        if qq > 4: yy, qq = yy + 1, 1
    return out


def main(budget_sec=1500, log=print):
    t0 = time.time()
    try: H = json.load(gzip.open(OUT, "rt"))
    except Exception: H = {"q": [], "s": {}, "done": []}
    try:
        t2c = {k: int(v) for k, v in json.load(open("us_cik.json", encoding="utf-8")).items()}
    except Exception:
        t2c = {}
    if not t2c: log("us_fund_hist:沒有 us_cik.json,略過"); return
    c2t = {c: t for t, c in t2c.items()}
    qs = quarters(); labs = [f"{y % 100:02d}Q{q}" for y, q in qs]
    done = set(H.get("done") or []); recent = set(labs[-3:])
    cells = {}                                                     # (tk, lab) -> {key: val}
    for tk, e in (H.get("s") or {}).items():
        for i, lab in enumerate(H.get("q") or []):
            for k in ("rev", "ni", "oi", "eps"):
                arr = e.get(k) or []
                if i < len(arr) and arr[i] is not None: cells.setdefault((tk, lab), {})[k] = arr[i]
    n_req = 0
    for (y, q), lab in zip(qs, labs):
        if lab in done and lab not in recent: continue
        if time.time() - t0 > budget_sec: log("us_fund_hist:時間到,下次接著抓"); break
        ok = True
        for key, tag, unit in TAGS:
            j = F.get_json(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/{unit}/CY{y}Q{q}.json"); n_req += 1
            time.sleep(0.15)
            if j is None: ok = False; continue
            for row in j.get("data") or []:
                tk = c2t.get(int(row.get("cik", 0))); v = row.get("val")
                if not tk or v is None: continue
                c = cells.setdefault((tk, lab), {})
                if key not in c: c[key] = round(float(v) / 1e6, 2) if key != "eps" else round(float(v), 3)
        if ok: done.add(lab)
    out = {"updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "q": labs, "s": {}, "done": sorted(done)}
    for tk in t2c:
        e = {k: [cells.get((tk, lab), {}).get(k) for lab in labs] for k in ("rev", "ni", "oi", "eps")}
        if sum(1 for x in e["rev"] if x is not None) >= 4: out["s"][tk] = e
    os.makedirs("archive", exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f: json.dump(out, f, separators=(",", ":"))
    log(f"us_fund_hist:{len(out['s'])} 檔、{len(done)}/{len(labs)} 季完成、本次 {n_req} 個請求、{int(time.time()-t0)} 秒")


if __name__ == "__main__":
    main()
