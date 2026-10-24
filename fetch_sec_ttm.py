"""r1158: incremental SEC companyfacts for current TTM review; immutable raw sources, no trading rules.
python fetch_sec_ttm.py --limit 120 --budget 480
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
import zipfile
import io
from financial_integrity import current_flow_ttm

ROOT = Path('archive/sec_facts')
OUT = Path('sec_ttm.json')
UA = {'User-Agent': 'KLabResearch/1.0 klab.research@gmail.com', 'Accept': 'application/json', 'Accept-Encoding': 'gzip'}


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    os.replace(tmp, path)


def archive_bytes(folder, raw, suffix='.json.gz'):
    digest = hashlib.sha256(raw).hexdigest()
    path = ROOT / folder / (digest + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(gzip.compress(raw, mtime=0))
    return str(path).replace('\\', '/'), digest


def read_source(entry):
    if entry.get("raw_pack"):
        with zipfile.ZipFile(entry["raw_pack"]) as pack:
            raw = gzip.decompress(pack.read(entry["raw_member"]))
    else:
        raw = gzip.decompress(Path(entry["raw_path"]).read_bytes())
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("SEC source checksum mismatch")
    return json.loads(raw)


def pack_sources(issuers, max_bytes=2 * 1024 * 1024):
    """Keep raw snapshots intact in small immutable packs; local staging files are never deleted."""
    batch, size = [], 0
    def flush():
        if not batch: return
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as pack:
            for cik, entry, payload in batch:
                member = str(cik) + "/" + Path(entry["raw_path"]).name
                item = zipfile.ZipInfo(member, date_time=(2026, 1, 1, 0, 0, 0))
                pack.writestr(item, payload)
        raw = buffer.getvalue()
        path = ROOT / "packs" / (hashlib.sha256(raw).hexdigest() + ".zip")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists(): path.write_bytes(raw)
        for cik, entry, payload in batch:
            entry["raw_pack"] = str(path).replace("\\", "/")
            entry["raw_member"] = str(cik) + "/" + Path(entry.pop("raw_path")).name
        batch.clear()
    for cik, entry in sorted(issuers.items()):
        if not entry.get("raw_path"): continue
        payload = Path(entry["raw_path"]).read_bytes()
        if batch and size + len(payload) > max_bytes:
            flush(); size = 0
        batch.append((cik, entry, payload)); size += len(payload)
    flush()


def main(limit=120, budget=480):
    t0 = time.monotonic()
    old = read_json(OUT, {})
    if old:
        archive_bytes('indexes', json.dumps(old, sort_keys=True, separators=(',', ':')).encode())
    stocks = read_json('data.json', {}).get('stocks', [])
    wanted = {str(s['id']).upper() for s in stocks if s.get('market') == 'US' and not s.get('etf')}
    mapping = {k: int(v) for k, v in read_json('us_cik.json', {}).items() if k in wanted}
    if not mapping:
        raise RuntimeError('No current issuer mapping; existing data preserved')
    groups = {}
    for ticker, cik in mapping.items():
        groups.setdefault(str(cik), []).append(ticker)
    issuers = old.get('issuers') or {}
    out = {'version': 1, 'updated': old.get('updated'), 's': mapping, 'issuers': issuers, 'purpose': 'current_review_only', 'pit_eligible': False}
    queue = sorted(groups, key=lambda c: (issuers.get(c, {}).get('last_success', ''), c))
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = (now - dt.timedelta(hours=20)).isoformat()
    n = failed = 0
    for cik in queue:
        if time.monotonic() - t0 > budget or n >= limit:
            break
        prev = issuers.get(cik, {})
        if prev.get('last_success', '') >= cutoff:
            continue
        url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json'
        n += 1
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=18) as response:
                raw = response.read()
                if response.headers.get('Content-Encoding') == 'gzip':
                    raw = gzip.decompress(raw)
            company = json.loads(raw)
            if int(company.get('cik', 0)) != int(cik) or not isinstance(company.get('facts'), dict):
                raise ValueError('CIK or payload mismatch')
            digest = hashlib.sha256(raw).hexdigest()
            if digest == prev.get('sha256') and prev.get('raw_pack'):
                reference = {k: prev[k] for k in ('raw_pack', 'raw_member')}
            else:
                path, digest = archive_bytes(cik, raw)
                reference = {'raw_path': path}
            stamp = dt.datetime.now(dt.timezone.utc).isoformat()
            issuers[cik] = {'cik': int(cik), 'tickers': sorted(groups[cik]), 'source_url': url,
                **reference, 'sha256': digest, 'last_success': stamp, 'last_attempt': stamp,
                'metrics': {key: current_flow_ttm(company, key) for key in ('rev', 'ni')},
                'security_eps_verified': False, 'pit_eligible': False}
            failed = 0
        except Exception as exc:
            # Preserve successful data and its original date; failure is a separate state.
            issuers[cik] = dict(prev, last_attempt=dt.datetime.now(dt.timezone.utc).isoformat(), error=type(exc).__name__)
            failed += 1
            print(f'CIK {cik}: {type(exc).__name__}, previous version retained', flush=True)
        out['updated'] = dt.datetime.now(dt.timezone.utc).isoformat()
        atomic_json(OUT, out)  # checkpoint each issuer, so timeout does not discard earlier sources
        if n % 25 == 0:
            print(f'SEC sources {n}; complete revenue {sum(bool((v.get("metrics", {}).get("rev") or {}).get("complete")) for v in issuers.values())}', flush=True)
        if failed >= 5:
            break
        time.sleep(0.55)  # sequential, below 2 requests/second, no third-party proxy
    pack_sources(issuers)
    atomic_json(OUT, out)
    print(f'SEC current-review index: {len(mapping)} securities, {len(issuers)} issuers stored, {n} requests', flush=True)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=120)
    parser.add_argument('--budget', type=int, default=480)
    args = parser.parse_args()
    raise SystemExit(main(args.limit, args.budget))
