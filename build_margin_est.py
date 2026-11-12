"""r1236 融資維持率「估算」(Frank 11/12:總覽要大盤融資維持率、個股也要寫出來現在是高還是低)。
公開資料沒有每個融資戶的實際借款,所以這裡全部是估算,前端一律標「估算」:
  大盤(上市) = Σ(個股融資餘額張數 × 1000 × 收盤價) ÷ 上市融資餘額金額(data.json macro.credit)。兩邊都是公開數字;
               只涵蓋站內有的上市股票,少數沒收錄的不計(會讓數字略偏低)。
  個股       = 現價 ÷ (估算的融資平均成本 × 60%)。平均成本用「增減加權法」:融資餘額增加的那天,增加的張數用當天收盤價算進成本;
               減少的那天,視為各批等比例還掉(平均成本不變)。價格單日跳動 >25% 當成除權/分割,成本同比例調整。
               起算日(SEED_FROM)原有的餘額沒有成本資料,先用當天收盤價代替;它佔現在餘額的比例寫在 q,太高(>35%)就標「可信度低」。
               沒算利息、現金股利、不同融資成數(一律 60%)。
輸出 margin_est.json:{d, mkt:{d,r,h:[[日期,維持率]...]}, s:{代號:{c 平均成本, m 維持率%, lo/hi 近 60 日最低/最高, rk 近 250 日排名百分位, q 起算殘留比例, n 天數,
     u 套牢張數比例%, k 維持率<140% 的張數比例%, b5/b20 融資餘額近 5/20 日變化%, p5/p20 股價近 5/20 日變化%, h 近 30 日維持率}}}
"""
import json, gzip, glob, os, datetime
ROOT = os.path.dirname(os.path.abspath(__file__)); os.chdir(ROOT)
METHOD = os.environ.get('MARGIN_EST_METHOD', 'mix')
SEED_FROM = (datetime.date.today() - datetime.timedelta(days=560)).isoformat()   # 融資最長可展延到 18 個月

def load(p):
    b = open(p, 'rb').read()
    return json.loads(gzip.decompress(b) if p.endswith('.gz') else b)

def main():
    data = load('data.json'); hol = (load('holidays.json') or {}).get('tw', {}) if os.path.exists('holidays.json') else {}
    info = {s['id']: s for s in data['stocks'] if s.get('market') != 'US'}
    bal = {}; px = {}
    def put(sid, d, v):
        if sid in info and isinstance(d, str) and d >= SEED_FROM and isinstance(v, (int, float)) and v >= 0 and d not in hol: bal.setdefault(sid, {})[d] = v
    y0 = int(SEED_FROM[:4])
    for year in range(y0, datetime.date.today().year + 1):
        for p in sorted(glob.glob(f'archive/margin/tw/{year}/*.json.gz')):
            for sid, e in load(p).items():
                for d, v in zip(e.get('d', []), e.get('mb', [])): put(sid, d, v)
    act = 'archive/hist/margin/active.json'
    if os.path.exists(act):
        for date, h in sorted(load(act).items()):
            p = f'archive/hist/margin/{date}/{h}.json.gz'
            if date >= SEED_FROM and os.path.exists(p):
                for sid, rows in (load(p).get('hist') or {}).items():
                    for d, v in rows: put(sid, d, v)
    for p in sorted(glob.glob('c/tw*.json')):
        for sid, e in load(p).items():
            for d, v in zip(e.get('cd', []), e.get('mf', [])): put(sid, d, v)
    m = load('margin.json')
    for sid, rows in (m.get('hist') or {}).items():
        for d, v in rows: put(sid, d, v)
    for p in sorted(glob.glob('k/tw*.json')):
        for sid, e in load(p).items():
            if sid not in info: continue
            for d, r in zip(e.get('d', []), e.get('o', [])):
                if d >= SEED_FROM and len(r) >= 4 and isinstance(r[3], (int, float)) and r[3] > 0: px.setdefault(sid, {})[d] = r[3]
    out = {}; AGG = {}
    for sid, B in bal.items():
        P = px.get(sid) or {}; ds = sorted(d for d in B if d in P)
        if len(ds) < 60 or info[sid].get('etf'): continue
        lots = []; seed = 0.0; first = True; prev = None; series = []; q = 0.0; cost = None   # lots:[成本, 張數, 是否起算殘留],舊的在前
        for d in ds:
            b = B[d]; p = P[d]
            if prev and lots and abs(p / prev - 1) > 0.25:                      # 除權/分割/減資
                for L in lots: L[0] *= p / prev
            prev = p
            if b <= 0: lots = []; q = 0.0; first = False; continue
            if not lots: lots = [[p, b, first]]; first = False
            elif b > q: lots.append([p, b - q, False])
            elif b < q:
                need = q - b
                if METHOD == 'mix':                                                # 一半等比例還、一半先進先出(跟真實大盤校驗最接近)
                    k = 1 - (need / 2) / q
                    for L in lots: L[1] *= k
                    need /= 2
                if METHOD in ('fifo', 'mix'):
                    for L in sorted(lots, key=lambda L: -L[0]):                    # 先走掉已經低於追繳線的(成本最高的先)
                        if need <= 0 or p / (L[0] * 0.6) >= 1.3: break
                        t = min(L[1], need); L[1] -= t; need -= t
                    for L in lots:                                                # 其餘先進先出(融資有期限,舊的先還)
                        if need <= 0: break
                        t = min(L[1], need); L[1] -= t; need -= t
                else:
                    k = b / q
                    for L in lots: L[1] *= k
                lots = [L for L in lots if L[1] > 1e-9]
            q = b
            cap = p / (0.6 * 1.3)                                                 # 收盤還在、卻低於 130% 的部位:視為已補錢到追繳線
            for L in lots:
                if L[0] > cap: L[0] = cap
            tq = sum(L[1] for L in lots)
            if tq <= 0: lots = []; q = 0.0; continue
            cost = sum(L[0] * L[1] for L in lots) / tq; seed = sum(L[1] for L in lots if L[2])
            series.append((d, p / (cost * 0.6) * 100)); AGG.setdefault(d, [0.0, 0.0]); 
            if info[sid].get('ex') == 'tse': AGG[d][0] += b * p; AGG[d][1] += b * cost * 0.6
        if not series or q <= 0 or cost is None or series[-1][0] != ds[-1]: continue
        last = series[-1][1]; w60 = [v for _, v in series[-60:]]; w250 = [v for _, v in series[-250:]]
        pN = P[ds[-1]]; tq = sum(L[1] for L in lots) or 1
        under = sum(L[1] for L in lots if L[0] > pN) / tq                      # 成本高於現價(套牢)的張數比例
        near = sum(L[1] for L in lots if pN / (L[0] * 0.6) < 1.4) / tq          # 維持率 <140%(離追繳線近)的張數比例
        def chg(D, n):
            if len(ds) <= n: return None
            a = D.get(ds[-1 - n]); b = D.get(ds[-1])
            return round((b / a - 1) * 100, 1) if a and b is not None else None
        out[sid] = {'c': round(cost, 2), 'm': round(last, 1), 'd': ds[-1], 'lo': round(min(w60), 1), 'hi': round(max(w60), 1),
                    'rk': round(sum(v <= last for v in w250) / len(w250) * 100), 'q': round(seed / q, 2), 'n': len(series), 'b': int(q),
                    'u': round(under * 100), 'k': round(near * 100), 'b5': chg(B, 5), 'b20': chg(B, 20), 'p5': chg(P, 5), 'p20': chg(P, 20),
                    'h': [round(v) for _, v in series[-30:]]}
    # 大盤(上市)
    cr = (data.get('macro') or {}).get('credit') or {}; H = cr.get('h') or {}; mk = []
    for d, fin in zip(H.get('d') or [], H.get('fin') or []):
        if not fin: continue
        tot = 0.0; n = 0
        for sid, s in info.items():
            if s.get('ex') != 'tse': continue
            b = (bal.get(sid) or {}).get(d); p = (px.get(sid) or {}).get(d)
            if b and p: tot += b * 1000 * p; n += 1
        if n >= 600: mk.append([d, round(tot / 1e8 / fin * 100, 1)])
    chk = [(d, r, round(AGG[d][0] / AGG[d][1] * 100, 1)) for d, r in mk if d in AGG and AGG[d][1] > 0]
    if chk: print('校驗(真實大盤 vs 個股估算加總):', chk[-5:], '平均差', round(sum(e - r for _, r, e in chk) / len(chk), 1), '最大差', round(max(abs(e - r) for _, r, e in chk), 1))
    res = {'ver': 'r1236', 'gen': datetime.datetime.now().isoformat(timespec='seconds'), 'est': True,
           'mkt': ({'d': mk[-1][0], 'r': mk[-1][1], 'h': mk[-90:]} if mk else None), 's': out}
    if len(out) < 300: raise SystemExit(f'margin_est: only {len(out)} stocks, keep previous')
    json.dump(res, open('margin_est.json.tmp', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':')); os.replace('margin_est.json.tmp', 'margin_est.json')
    try:                                                                      # 永久紀錄:大盤每天一筆 + 當天全部個股快照
        os.makedirs('archive/margin_est', exist_ok=True); hp = 'archive/margin_est/mkt.json'
        hist = load(hp) if os.path.exists(hp) else {}
        for d, r in mk: hist.setdefault(d, r)
        if mk: hist[mk[-1][0]] = mk[-1][1]
        json.dump(dict(sorted(hist.items())), open(hp, 'w'), separators=(',', ':'))
        if mk: open(f"archive/margin_est/{mk[-1][0]}.json.gz", 'wb').write(gzip.compress(json.dumps(res, ensure_ascii=False, separators=(',', ':')).encode(), mtime=0))
    except Exception as e: print('archive failed', e)
    print('margin_est', len(out), 'stocks; market', res['mkt'] and (res['mkt']['d'], res['mkt']['r']), 'hist', len(mk))

if __name__ == '__main__': main()
