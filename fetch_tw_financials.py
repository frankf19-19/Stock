"""r1159: additive, versioned Taiwan financial history. Current provider view, never PIT signals."""
import argparse
import calendar
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from financial_integrity import finite

VERSION = 1
START = '2015-01-01'
API = 'https://api.finmindtrade.com/api/v4/data'
DATASETS = {'income': 'TaiwanStockFinancialStatements', 'balance': 'TaiwanStockBalanceSheet',
            'cashflow': 'TaiwanStockCashFlowsStatement'}
FIELDS = {
 'income': {'revenue': ('Revenue', 'OperatingRevenue'), 'net_income': ('IncomeAfterTaxes', 'IncomeAfterTax', 'NetIncome'),
            'gross_profit': ('GrossProfit',), 'operating_income': ('OperatingIncome',), 'eps': ('EPS',)},
 'balance': {'assets': ('TotalAssets',), 'liabilities': ('Liabilities', 'TotalLiabilities'),
             'equity': ('Equity', 'TotalEquity'), 'cash': ('CashAndCashEquivalents',),
             'inventory': ('Inventories',), 'receivables': ('AccountsReceivableNet',)},
 'cashflow': {'ocf': ('CashFlowsFromOperatingActivities',),
              'capex': ('PropertyAndPlantAndEquipment', 'AcquisitionOfPropertyPlantAndEquipment')}
}


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def read_json(path, default=None):
    if not path.exists(): return default
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp'); tmp.write_bytes(data); tmp.replace(path)


def snapshot(root, directory, obj):
    raw = encoded(obj); digest = hashlib.sha256(raw).hexdigest()
    path = root / directory / (digest + '.json.gz')
    if not path.exists(): atomic(path, gzip.compress(raw, mtime=0))
    return {'path': path.relative_to(root).as_posix(), 'sha256': digest}


def quarter(date):
    try: d = dt.date.fromisoformat(date)
    except (ValueError, TypeError): return None
    if d.month not in (3, 6, 9, 12) or d.day != calendar.monthrange(d.year, d.month)[1]: return None
    return d.year * 4 + d.month // 3 - 1


def qlabel(n): return f'{n // 4}Q{n % 4 + 1}'


def normalize(kind, rows, sid, as_of=None):
    """Keep every raw row separately; ambiguous duplicate facts are null, never last-wins."""
    values = {}; invalid = 0
    for row in rows:
        if str(row.get('stock_id')) != sid: invalid += 1; continue
        d = row.get('date'); n = quarter(d)
        if n is None or (as_of and d > as_of) or not isinstance(row.get('type'), str): invalid += 1; continue
        k = row['type']; v = row.get('value')
        if not finite(v): invalid += 1; continue
        values.setdefault(n, {}).setdefault(k, []).append((v, str(row.get('origin_name') or '')))
    out = {}; conflicts = []
    for n, facts in sorted(values.items()):
        entry = {'period': qlabel(n), 'date': f'{n//4}-{(n%4+1)*3:02d}-{calendar.monthrange(n//4,(n%4+1)*3)[1]}'}
        for key, aliases in FIELDS[kind].items():
            # Alias preference is explicit; do not combine multiple concepts.
            fact = next((facts[a] for a in aliases if a in facts), None)
            if fact is None: entry[key] = None; continue
            distinct = {v for v, _ in fact}
            if len(distinct) != 1:
                entry[key] = None; conflicts.append({'period': qlabel(n), 'field': key}); continue
            if key == 'capex' and not all(re.search('取得|購置|购置|acqui|purchase', name, re.I) for _, name in fact):
                entry[key] = None; continue
            entry[key] = fact[0][0]
        out[n] = entry
    if kind == 'income':
        # Providers report half-year companies too. Q2/Q4 in a year without Q1/Q3 cannot be proved single-quarter.
        for n, e in out.items():
            e['single_quarter_verified'] = n % 4 in (0, 2) or any(n//4*4 + q in out for q in (0, 2))
            e['eps_basis_verified'] = False
    if kind == 'cashflow':
        for n, e in out.items():
            for key in FIELDS[kind]:
                v = e[key]; prev = out.get(n-1, {}).get(key) if n%4 else 0
                e[key + '_quarter'] = v - prev if finite(v) and finite(prev) else None
            e['basis'] = 'year_to_date'
    return out, {'invalid_rows': invalid, 'conflicts': conflicts}


def build_history(sid, sources, raw_refs, fetched_at, old=None, start=START):
    reports = {}; diag = {}
    for kind in DATASETS:
        rows = (sources.get(kind) or {}).get('data') or []
        reports[kind], diag[kind] = normalize(kind, rows, sid, fetched_at[:10])
    # Source omissions never erase previously captured periods or replace known facts with nulls.
    merged = {kind: dict(rows) for kind, rows in reports.items()}
    for kind in DATASETS:
        for prev in (old or {}).get('statements', {}).get(kind, []):
            n = quarter(prev.get('date'))
            if n is None: continue
            if n not in merged[kind]:
                merged[kind][n] = dict(prev, retained_from_previous=True)
            else:
                for key, val in prev.items():
                    if not key.endswith('_quarter') and key not in ('retained_fields', 'retained_from_previous') and merged[kind][n].get(key) is None and val is not None:
                        # Conflicted current facts stay null, not silently repaired from old data.
                        if any(c['period']==qlabel(n) and c['field']==key.removesuffix('_quarter') for c in diag[kind]['conflicts']): continue
                        merged[kind][n][key] = val
                        merged[kind][n].setdefault('retained_fields', []).append(key)
    # Recompute single-quarter CF after merging retained YTD facts; never preserve a stale difference.
    for n, e in merged['cashflow'].items():
        for key in FIELDS['cashflow']:
            v=e.get(key); prev=merged['cashflow'].get(n-1,{}).get(key) if n%4 else 0
            e[key+'_quarter']=v-prev if finite(v) and finite(prev) else None
    all_n = sorted(set().union(*(set(x) for x in merged.values())))
    records = []
    for n in all_n:
        inc = merged['income'].get(n, {}); bs = merged['balance'].get(n, {}); cf = merged['cashflow'].get(n, {})
        e = {'period': qlabel(n), 'date': (inc or bs or cf)['date']}
        for k in FIELDS['income']: e[k] = inc.get(k) if inc.get('single_quarter_verified') else None
        for k in FIELDS['balance']: e[k] = bs.get(k)
        for k in FIELDS['cashflow']: e[k] = cf.get(k + '_quarter')
        e['fcf'] = e['ocf'] - abs(e['capex']) if finite(e['ocf']) and finite(e['capex']) else None
        rv = e['revenue']; ni = e['net_income']
        e['net_margin'] = ni / rv * 100 if finite(ni) and finite(rv) and rv > 0 else None
        e['debt_ratio'] = e['liabilities']/e['assets']*100 if finite(e['liabilities']) and finite(e['assets']) and e['assets']>0 else None
        records.append(e)
    by_n = {quarter(e['date']): e for e in records}
    latest = max(all_n, default=None); ttm = {'periods': [qlabel(n) for n in range(latest-3,latest+1)] if latest is not None else []}
    for k in ('revenue','net_income','ocf','capex','fcf'):
        # A retained history fact is not a fresh, verified TTM component. Only this response's
        # four actual quarters (and this response's YTD predecessors) can qualify.
        def current_value(n):
            if k in ('revenue','net_income'):
                row=reports['income'].get(n,{})
                return row.get(k) if row.get('single_quarter_verified') else None
            row=reports['cashflow'].get(n,{})
            if k=='fcf':
                ocf=row.get('ocf_quarter');capex=row.get('capex_quarter')
                return ocf-abs(capex) if finite(ocf) and finite(capex) else None
            return row.get(k+'_quarter')
        vals = [current_value(n) for n in range(latest-3,latest+1)] if latest is not None else []
        ttm[k] = sum(abs(v) if k=='capex' else v for v in vals) if len(vals)==4 and all(finite(v) for v in vals) else None
    ttm['cash_conversion'] = ttm['ocf']/ttm['net_income'] if finite(ttm['ocf']) and finite(ttm['net_income']) and ttm['net_income']>0 else None
    coverage = {}
    for kind in DATASETS:
        available = sorted(reports[kind]); preserved = sorted(merged[kind])
        gaps = [qlabel(n) for n in range(preserved[0],preserved[-1]+1) if n not in merged[kind]] if preserved else []
        coverage[kind] = {'source_quarters': len(available), 'quarters': len(preserved),
                          'first': qlabel(preserved[0]) if preserved else None, 'last': qlabel(preserved[-1]) if preserved else None,
                          'missing_quarters': gaps, 'first_date': merged[kind][preserved[0]]['date'] if preserved else None,
                          'last_date': merged[kind][preserved[-1]]['date'] if preserved else None,
                          'retained_quarters': len(set(preserved)-set(available))}
    return {'version': VERSION, 'id': sid, 'source': 'FinMind', 'requested_start': start,
            'fetched_at': fetched_at, 'published_at': None, 'pit_eligible': False,
            'unit': 'TWD', 'eps_unit': 'TWD_per_share', 'eps_basis_verified': False,
            'raw_sources': raw_refs, 'coverage': coverage, 'diagnostics': diag,
            'statements': {k:[merged[k][n] for n in sorted(merged[k])] for k in DATASETS},
            'quarters': records, 'ttm': ttm}


class QuotaError(Exception): pass


def fetch(kind, sid, start, end, token):
    params = {'dataset': DATASETS[kind], 'data_id': sid, 'start_date': start, 'end_date': end}
    headers = {'User-Agent': 'Klab financial history research klab.research@gmail.com'}
    if token: headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(API + '?' + urllib.parse.urlencode(params), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as res: payload = json.load(res)
    except urllib.error.HTTPError as exc:
        if exc.code in (402,429): raise QuotaError('provider_quota') from None
        raise RuntimeError('provider_http_' + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError): raise RuntimeError('provider_connection') from None
    if not isinstance(payload,dict) or payload.get('status') != 200 or not isinstance(payload.get('data'),list):
        # Never include arbitrary provider messages or auth headers in logs.
        if str(payload.get('status')) in ('402','429'): raise QuotaError('provider_quota')
        raise RuntimeError('provider_response')
    return payload


def run(args):
    root = Path(args.root); directory = root/'fundamentals/tw'; directory.mkdir(parents=True,exist_ok=True)
    index_path = directory/'index.json'; index = read_json(index_path, {'version': VERSION, 'stocks': {}})
    data = read_json(root/'data.json', {})
    universe = {str(s['id']) for s in data.get('stocks',[]) if s.get('market')=='TW' and not s.get('etf') and re.fullmatch(r'[0-9A-Za-z_-]+',str(s.get('id','')))}
    explicit = [x.strip() for x in args.symbols.split(',') if x.strip()] if args.symbols else []
    if set(explicit)-universe: raise ValueError('Unknown or ETF security')
    entries = index.setdefault('stocks',{}); now = dt.datetime.now(dt.timezone.utc); today = now.date().isoformat()
    def due(sid):
        e=entries.get(sid,{}); last=e.get('last_success','')
        if e.get('attempt_date')==today: return False
        return not last or (now-dt.datetime.fromisoformat(last)).days >= (7 if not e.get('complete_fetch') else 30)
    targets = explicit or sorted((s for s in universe if due(s)),key=lambda s:(bool(entries.get(s,{}).get('last_success')),entries.get(s,{}).get('attempt_date',''),s))
    deadline = time.monotonic()+args.seconds; calls=ok=0; token=os.environ.get('FINMIND_TOKEN','').strip()
    if index_path.exists(): snapshot(root,'archive/tw_financial/indexes',index)
    for sid in targets:
        if calls+3>args.limit or time.monotonic()+140>deadline: break
        prior = entries.get(sid,{})
        prior_path = directory/(sid+'.json.gz'); old = read_json(prior_path)
        refs = dict((old or {}).get('raw_sources',{})); sources = {}; failed=[]; quota=False
        for kind in DATASETS:
            try:
                calls+=1; payload=fetch(kind,sid,args.start,today,token)
                refs[kind]=snapshot(root,'archive/tw_financial/raw/'+sid+'/'+kind,payload)
                sources[kind]=payload
            except QuotaError: failed.append(kind);quota=True;break
            except Exception as exc: failed.append(kind);print(sid,kind,type(exc).__name__,flush=True)
            time.sleep(args.delay)
        if sources:
            history=build_history(sid,sources,refs,now.isoformat(),old,args.start)
            if old: snapshot(root,'archive/tw_financial/versions/'+sid,old)
            atomic(prior_path,gzip.compress(encoded(history),mtime=0));ok+=1
            entries[sid]={'coverage':history['coverage'],'last_success':now.isoformat(),
                           'complete_fetch':not failed and all(history['coverage'][k]['source_quarters'] for k in DATASETS),
                           'attempt_date':today,'failed':failed,'path':'fundamentals/tw/'+sid+'.json.gz'}
        else: entries[sid]=dict(prior,attempt_date=today,failed=failed or list(DATASETS))
        index.update(updated=now.isoformat(),source='FinMind',requested_start=args.start,pit_eligible=False,
                     universe_count=len(universe),with_history=sum(any(c.get('quarters',0) for c in e.get('coverage',{}).values()) for e in entries.values()))
        atomic(index_path,encoded(index))
        print(sid,'saved' if sources else 'unavailable','calls',calls,flush=True)
        if quota: print('Provider quota reached; checkpoint preserved.',flush=True);break
    print('Complete:',ok,'securities;',calls,'requests.',flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',default='.');ap.add_argument('--symbols',default='')
    ap.add_argument('--start',default=START);ap.add_argument('--limit',type=int,default=240)
    ap.add_argument('--seconds',type=int,default=900);ap.add_argument('--delay',type=float,default=0.6)
    run(ap.parse_args())
