"""r1158: FINRA's published calendar, no guessed settlement-date offset."""
import datetime as dt
import gzip
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request

URL = 'https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest'
PATH = Path('archive/ext/finra_publication.json')


class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.heading=None; self.h=[]; self.year=None
        self.row=None; self.cell=None; self.out={}
    def handle_starttag(self, tag, attrs):
        if tag in ('h2', 'h3'):
            self.heading=tag; self.h=[]
        if tag=='tr': self.row=[]
        if tag in ('td','th') and self.row is not None: self.cell=[]
    def handle_data(self, text):
        if self.heading: self.h.append(text)
        if self.cell is not None: self.cell.append(text)
    def handle_endtag(self, tag):
        if tag==self.heading:
            m=re.search(r'(20\d{2})\s+Short Interest Reporting Dates', ' '.join(self.h))
            self.year=int(m[1]) if m else None
            self.heading=None
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(self.cell)); self.cell=None
        if tag=='tr' and self.row is not None:
            if self.year and len(self.row)==3:
                try:
                    first=re.search(r'([A-Za-z]+)\s+(\d{1,2})',self.row[0])
                    last=re.search(r'([A-Za-z]+)\s+(\d{1,2})',self.row[2])
                    if first and last:
                        settlement=dt.datetime.strptime(f'{first[0]} {self.year}', '%B %d %Y').date()
                        publication=dt.datetime.strptime(f'{last[0]} {self.year}', '%B %d %Y').date()
                        if publication<settlement: publication=publication.replace(year=self.year+1)
                        if 1 <= (publication-settlement).days <= 25:
                            self.out[settlement.isoformat()]=publication.isoformat()
                except ValueError: pass
            self.row=None


def parse_calendar(text):
    parser=CalendarParser(); parser.feed(text); return parser.out


def load_calendar():
    try: return json.loads(PATH.read_text(encoding='utf-8')).get('dates',{})
    except (OSError,ValueError): return {}


def update_calendar(raw=None):
    if raw is None:
        req=urllib.request.Request(URL,headers={'User-Agent':'KLabResearch/1.0'})
        with urllib.request.urlopen(req,timeout=20) as r: raw=r.read()
    dates=parse_calendar(raw.decode('utf-8'))
    if not dates: raise ValueError('No verified FINRA calendar rows; old calendar retained')
    merged=load_calendar(); merged.update(dates)
    digest=hashlib.sha256(raw).hexdigest()
    source=PATH.parent/'finra_calendar_raw'/(digest+'.html.gz'); source.parent.mkdir(parents=True,exist_ok=True)
    if not source.exists(): source.write_bytes(gzip.compress(raw,mtime=0))
    # Existing calendar rows are never pruned when FINRA shortens its public table.
    data={'version':1,'source_url':URL,'source_raw':str(source).replace('\\','/'),'sha256':digest,
          'fetched_at':dt.datetime.now(dt.timezone.utc).isoformat(),'dates':merged}
    tmp=PATH.with_suffix('.tmp');tmp.write_text(json.dumps(data,separators=(',',':')),encoding='utf-8');tmp.replace(PATH)
    return merged


def available_date(settlement, dates):
    published=dates.get(settlement)
    if not published: return None
    try:
        if published <= settlement: return None
        # No publication timestamp: start after its calendar date, then align to real market sessions.
        return (dt.date.fromisoformat(published)+dt.timedelta(days=1)).isoformat()
    except ValueError: return None
