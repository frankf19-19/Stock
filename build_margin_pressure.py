"""r1193: public balance changes and explicitly hypothetical single-position stress prices."""
import argparse,datetime,gzip,hashlib,json,math,csv,io
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
def read(p):
 b=p.read_bytes();return json.loads(gzip.decompress(b) if p.suffix=='.gz' else b)
def valid_date(x):
 try:return isinstance(x,str) and datetime.date.fromisoformat(x).isoformat()==x
 except (ValueError,TypeError):return False
def number(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def preserve_snapshot(j,root=ROOT):
 if not isinstance(j,dict) or not valid_date(j.get('updated')):return
 b=json.dumps(j,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode();h=hashlib.sha256(b).hexdigest();p=root/'archive/hist/margin'/j['updated']/(h+'.json.gz');p.parent.mkdir(parents=True,exist_ok=True)
 if not p.exists():p.write_bytes(gzip.compress(b,mtime=0))
 active=root/'archive/hist/margin/active.json';index=read(active) if active.exists() else {};index[j['updated']]=h;tmp=active.with_suffix('.tmp');tmp.write_bytes(json.dumps(index,sort_keys=True).encode());tmp.replace(active)
def calculate(balances,prices,calendar,asof):
 if asof not in balances or asof not in calendar:return None
 i=calendar.index(asof);qty=balances[asof];p=prices.get(asof);out={'asof':asof,'balance':qty,'close':p,'windows':{},'warnings':[],'scenarios':[]}
 for n in (5,20,60):
  if i<n:out['windows'][str(n)]=None;continue
  ds=calendar[i-n:i+1];start=balances.get(ds[0]);observed=sum(d in balances for d in ds)
  if start is None or not number(start) or start<=0:out['windows'][str(n)]=None;continue
  jump=(qty==0 and any(balances.get(d,0)>0 for d in ds)) or any(a in balances and b in balances and (balances[b]==0<balances[a] or balances[a]>0 and abs(balances[b]/balances[a]-1)>.8) for a,b in zip(ds,ds[1:]))
  out['windows'][str(n)]={'from':ds[0],'to':asof,'start':start,'end':qty,'delta':qty-start,'pct':(qty/start-1)*100 if not jump else None,'observed':observed,'expected':n+1,'complete':observed==n+1,'discontinuity':jump,'price_pct':(p/prices[ds[0]]-1)*100 if number(p) and p>0 and number(prices.get(ds[0])) and prices[ds[0]]>0 else None}
 ds=calendar[max(0,i-59):i+1];vals=[(d,balances[d]) for d in ds if d in balances];peak=max(vals,key=lambda x:x[1]) if vals else None
 jump=(qty==0 and any(balances.get(d,0)>0 for d in ds)) or any(a in balances and b in balances and (balances[b]==0<balances[a] or balances[a]>0 and abs(balances[b]/balances[a]-1)>.8) for a,b in zip(ds,ds[1:]))
 out['peak60']={'date':peak[0],'balance':peak[1],'removed':peak[1]-qty,'removed_pct':(1-qty/peak[1])*100 if peak[1]>0 and not jump else None,'observed':len(vals),'expected':60,'complete':len(ds)==60 and len(vals)==60,'discontinuity':jump} if peak else None
 if jump:out['warnings'].append('融資餘額有歸零或單日逾80%變動，先核對停資、分割及來源，不推定已洗清。')
 if not number(p) or p<=0:out['warnings'].append('缺同日有效收盤，暫不試算壓力價。');return out
 if qty<=0:out['warnings'].append('最新融資餘額為零，不能估算目前融資戶壓力。');return out
 for n,kind,label in [(20,'mean','假設買在近20日平均收盤'),(20,'high','假設買在近20日最高收盤'),(60,'high','假設買在近60日最高收盤')]:
  if i+1<n:continue
  dates=calendar[i-n+1:i+1];xs=[prices.get(d) for d in dates]
  if not all(number(x) and x>0 for x in xs):continue
  if any(abs(b/a-1)>.25 for a,b in zip(xs,xs[1:])):out['warnings'].append('價格有逾25%斷層，成本情境暫停，先核對公司行動。');continue
  cost=sum(xs)/len(xs) if kind=='mean' else max(xs)
  out['scenarios'].append({'label':label,'from':dates[0],'to':asof,'cost':cost,'loan_ratio':.6,'trigger_ratio':1.3,'line':cost*.6*1.3,'maintenance_pct':p/(cost*.6)*100,'to_line_pct':(cost*.6*1.3/p-1)*100})
 return out
def build(root=ROOT,today=None):
 today=today or datetime.datetime.now(ZoneInfo('Asia/Taipei')).date();cut=today.isoformat();sources={}
 def load(p):
  b=p.read_bytes();sources[p.relative_to(root).as_posix()]=hashlib.sha256(b).hexdigest();return json.loads(gzip.decompress(b) if p.suffix=='.gz' else b)
 data=load(root/'data.json');hol=load(root/'holidays.json').get('tw',{});balances={};prices={};calendar=set()
 def put(sid,d,v):
  if valid_date(d) and d<=cut and datetime.date.fromisoformat(d).weekday()<5 and d not in hol and number(v) and v>=0:balances.setdefault(sid,{})[d]=v
 for year in (today.year-1,today.year):
  for p in sorted((root/f'archive/margin/tw/{year}').glob('*.json.gz')):
   for sid,e in load(p).items():
    for d,v in zip(e.get('d',[]),e.get('mb',[])):put(sid,d,v)
 active=root/'archive/hist/margin/active.json';revisions=load(active) if active.exists() else {}
 for date,h in sorted(revisions.items()):
  if not valid_date(date) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h):raise ValueError('Bad margin revision index')
  p=root/'archive/hist/margin'/date/(h+'.json.gz')
  if p.parent.name<str(today-datetime.timedelta(days=180)):continue
  j=load(p)
  for sid,rows in j.get('hist',{}).items():
   for d,v in rows:put(sid,d,v)
 for p in sorted((root/'c').glob('tw*.json')):
  for sid,e in load(p).items():
   for d,v in zip(e.get('cd',[]),e.get('mf',[])):put(sid,d,v)
 m=load(root/'margin.json');preserve_snapshot(m,root)
 for sid,rows in m.get('hist',{}).items():
  for d,v in rows:put(sid,d,v)
 for p in sorted((root/'k').glob('tw*.json')):
  for sid,e in load(p).items():
   for d,r in zip(e.get('d',[]),e.get('o',[])):
    if valid_date(d) and d<=cut and datetime.date.fromisoformat(d).weekday()<5 and d not in hol and len(r)>=5 and number(r[3]) and r[3]>0:
     if d==cut and datetime.datetime.now(ZoneInfo('Asia/Taipei')).time()<datetime.time(13,30):continue
     prices.setdefault(sid,{})[d]=r[3];calendar.add(d)
 calendar=sorted(calendar);out={'schema':1,'version':'r1193','generated':datetime.datetime.now(ZoneInfo('Asia/Taipei')).isoformat(),'basis':'public_balance_and_explicit_hypothetical_costs','official_account_maintenance':False,'sources':sources,'stocks':{}}
 for s in data['stocks']:
  if s.get('market')!='TW' or s.get('etf'):continue
  sid=s['id'];b=balances.get(sid,{})
  if not b:continue
  asof=max(b);f=calculate(b,prices.get(sid,{}),calendar,asof)
  if f:out['stocks'][sid]={'id':sid,'name':s['name'],**f}
 if not out['stocks']:raise ValueError('No stock balances; preserve previous projection')
 raw=json.dumps(out,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode();z=gzip.compress(raw,mtime=0);h=hashlib.sha256(raw).hexdigest();p=root/'archive/stock_research/margin_pressure'/cut/(h+'.json.gz');p.parent.mkdir(parents=True,exist_ok=True)
 if not p.exists():p.write_bytes(z)
 tmp=root/'margin_pressure.json.gz.tmp';tmp.write_bytes(z);tmp.replace(root/'margin_pressure.json.gz')
 buf=io.StringIO(newline='');w=csv.writer(buf);w.writerow(['代碼','名稱','融資日期','餘額張','近5日增減張','近20日增減張','近60日高峰日期','高峰張','高峰後減少張','高峰後減少%','高峰窗口完整'])
 for s in out['stocks'].values():
  pk=s['peak60'] or {};a=s['windows']['5'] or {};b=s['windows']['20'] or {};w.writerow([s['id'],s['name'],s['asof'],s['balance'],a.get('delta'),b.get('delta'),pk.get('date'),pk.get('balance'),pk.get('removed'),pk.get('removed_pct'),pk.get('complete')])
 (root/'margin_pressure.csv').write_bytes(('\ufeff'+buf.getvalue()).encode());print('margin pressure',len(out['stocks']),'stocks',len(z),'bytes');return out
if __name__=='__main__':build()
