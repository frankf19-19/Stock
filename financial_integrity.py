"""r1158: period-safe financial calculations. No network, scoring or trade-rule changes."""
import calendar
import datetime as dt
import math
import re

VERSION = 1


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def quarter_number(label):
    m = re.fullmatch(r'(\d{4})Q([1-4])', str(label))
    return int(m[1]) * 4 + int(m[2]) - 1 if m else None


def cashflow_ttm(by_date):
    """Calendar YTD cash flow -> four adjacent single quarters; missing predecessor is unknown."""
    cumulative = {}
    for label, value in by_date.items():
        try:
            date = dt.date.fromisoformat(label)
        except (ValueError, TypeError):
            continue
        if date.month not in (3, 6, 9, 12) or date.day != calendar.monthrange(date.year, date.month)[1] or not finite(value):
            continue
        cumulative[date.year * 4 + date.month // 3 - 1] = (label, value)
    latest = max(cumulative, default=None)
    info = {'version': VERSION, 'complete': False, 'unit': 'TWD', 'method': 'four_adjacent_single_quarters_from_ytd',
            'period_end': cumulative[latest][0] if latest is not None else None,
            'periods': [], 'components': [], 'missing_reason': 'insufficient_periods', 'published_at': None}
    if latest is None:
        return None, info
    single = {}
    for q, (label, value) in cumulative.items():
        if q % 4 == 0:
            single[q] = value
        elif q - 1 in cumulative:
            single[q] = value - cumulative[q - 1][1]
    wanted = list(range(latest - 3, latest + 1))
    info['periods'] = [f'{q // 4}Q{q % 4 + 1}' for q in wanted]
    info['components'] = [{'period': f'{q // 4}Q{q % 4 + 1}', 'value': single.get(q)} for q in wanted]
    if not all(q in single for q in wanted):
        return None, info
    info.update(complete=True, missing_reason=None)
    return sum(single[q] for q in wanted), info


def aligned_income(quarters, revenues, margins, periods):
    """Do not silently replace missing income with zero or compare different CF and NI periods."""
    if len(periods) != 4 or len(set(quarters)) != len(quarters):
        return None
    values = dict(zip(quarters, zip(revenues, margins)))
    total = 0
    for q in periods:
        pair = values.get(q)
        if pair is None or not all(finite(v) for v in pair):
            return None
        total += pair[0] * 1e6 * pair[1] / 100
    return total


def financial_retry_due(entry, due_quarter, today):
    """Failed and unsupported records rotate fairly; a failed request is not a successful quarter."""
    state = entry.get('fin_fetch') or {}
    if state.get('attempt_date', '') > (today - dt.timedelta(days=1)).isoformat():
        return False
    fin = entry.get('fin') or {}
    return (state.get('version') != VERSION or entry.get('ocfq') != due_quarter
            or not (fin.get('cf_quality') or {}).get('complete') or fin.get('fcf4') is None)


TAGS = {
    'rev': ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'),
    'ni': ('NetIncomeLoss',),
}


def _facts(company, tag, as_of):
    rows = (((company.get('facts') or {}).get('us-gaap') or {}).get(tag) or {}).get('units', {}).get('USD', [])
    out = {}
    for r in rows:
        if r.get('form') not in ('10-K', '10-K/A', '10-Q', '10-Q/A') or not finite(r.get('val')):
            continue
        try:
            start, end, filed = (dt.date.fromisoformat(r[k]) for k in ('start', 'end', 'filed'))
        except (ValueError, KeyError, TypeError):
            continue
        if filed > as_of or end > as_of or not r.get('accn') or start > end:
            continue
        k = (start, end)
        if k not in out or (filed.isoformat(), r['accn']) > (out[k]['filed'], out[k]['accn']):
            out[k] = {k: r[k] for k in ('start', 'end', 'val', 'filed', 'accn', 'form')}
    return list(out.values())


def current_flow_ttm(company, key, as_of=None):
    """Current restated review only, not point-in-time backtest data. Never subtract EPS."""
    as_of = as_of or dt.datetime.now(dt.timezone.utc).date()
    candidates = []
    newest_metric_end = None
    for priority, tag in enumerate(TAGS[key]):
        facts = _facts(company, tag, as_of)
        if not facts:
            continue
        latest_end = max(x['end'] for x in facts)
        newest_metric_end = max(newest_metric_end or latest_end, latest_end)
        if (as_of - dt.date.fromisoformat(latest_end)).days > 550:
            continue
        duration = lambda x: (dt.date.fromisoformat(x['end']) - dt.date.fromisoformat(x['start'])).days + 1
        annuals = [x for x in facts if 350 <= duration(x) <= 380 and x['form'].startswith('10-K')]
        for annual in annuals:
            if annual['end'] == latest_end:
                candidates.append((latest_end, -priority, {'value': annual['val'] / 1e6, 'period_start': annual['start'],
                    'period_end': latest_end, 'method': 'reported_fiscal_year', 'components': [annual], 'concept': tag}))
                continue
            next_start = (dt.date.fromisoformat(annual['end']) + dt.timedelta(days=1)).isoformat()
            currents = [x for x in facts if x['start'] == next_start and x['end'] == latest_end and 70 <= duration(x) <= 300]
            for cur in currents:
                prior = [x for x in facts if x['start'] == annual['start'] and x['end'] < annual['end']
                         and abs(duration(x) - duration(cur)) <= 8]
                if not prior:
                    continue
                old = max(prior, key=lambda x: (x['accn'] == cur['accn'], x['filed'], -abs(duration(x) - duration(cur))))
                if not 350 <= (dt.date.fromisoformat(latest_end) - dt.date.fromisoformat(old['end'])).days <= 380:
                    continue
                candidates.append((latest_end, -priority, {'value': (annual['val'] + cur['val'] - old['val']) / 1e6,
                    'period_start': (dt.date.fromisoformat(old['end']) + dt.timedelta(days=1)).isoformat(),
                    'period_end': latest_end, 'method': 'annual_plus_ytd_minus_comparable_ytd',
                    'components': [annual, cur, old], 'concept': tag}))
    candidates = [x for x in candidates if x[0] == newest_metric_end]
    if not candidates:
        return {'complete': False, 'value': None, 'missing_reason': 'no_supported_complete_period', 'unit': 'USD_million'}
    end, _, result = max(candidates, key=lambda x: (x[0], x[1]))
    result.update(complete=True, unit='USD_million', filed=max(x['filed'] for x in result['components']),
                  published_at=None, time_precision='filing_date_only', pit_eligible=False)
    return result
